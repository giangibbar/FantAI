"""XGBoost models with walk-forward validation for football prediction."""

import warnings
import pandas as pd
import numpy as np
from xgboost import XGBClassifier
from rich.console import Console
from rich.progress import track
from rich.table import Table

from src.elo import compute_elo_ratings
from src.features import clean_matches, build_dataset, get_avg_odds
from src.backtest import run_backtest, print_backtest_report, BacktestResult

warnings.filterwarnings("ignore", category=FutureWarning)
console = Console()

FEATURE_COLS = [
    "elo_diff", "home_elo", "away_elo",
    "home_form_pts", "home_form_gs", "home_form_gc", "home_form_shots", "home_form_sot",
    "away_form_pts", "away_form_gs", "away_form_gc", "away_form_shots", "away_form_sot",
    "h2h_home_wins", "h2h_draws", "h2h_avg_goals",
    "home_attack", "home_defense", "away_attack", "away_defense",
    "implied_home", "implied_draw", "implied_away",
]


def _make_xgb(n_classes: int = 3) -> XGBClassifier:
    """Create XGBoost classifier with tuned params."""
    params = dict(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        reg_alpha=0.1, reg_lambda=1.0, random_state=42, verbosity=0,
    )
    if n_classes == 2:
        params.update(objective="binary:logistic", eval_metric="logloss")
    else:
        params.update(objective="multi:softprob", num_class=3, eval_metric="mlogloss")
    return XGBClassifier(**params)


def train_models(train_df: pd.DataFrame) -> dict:
    """Train 1X2, Over/Under, and BTTS models."""
    X = train_df[FEATURE_COLS].fillna(0).values

    # 1X2
    model_1x2 = _make_xgb(3)
    model_1x2.fit(X, train_df["result"].values)

    # Over/Under 2.5
    model_ou = _make_xgb(2)
    model_ou.fit(X, train_df["over25"].values)

    # BTTS
    model_btts = _make_xgb(2)
    model_btts.fit(X, train_df["btts"].values)

    return {"1x2": model_1x2, "ou": model_ou, "btts": model_btts}


def predict_match_xgb(models: dict, row: pd.Series) -> dict:
    """Get all probabilities from trained models."""
    X = np.array([row[FEATURE_COLS].fillna(0).values.astype(float)])

    probs_1x2 = models["1x2"].predict_proba(X)[0]
    prob_over = models["ou"].predict_proba(X)[0][1]
    prob_btts = models["btts"].predict_proba(X)[0][1]

    return {
        "prob_home": float(probs_1x2[0]),
        "prob_draw": float(probs_1x2[1]),
        "prob_away": float(probs_1x2[2]),
        "prob_over25": float(prob_over),
        "prob_under25": float(1 - prob_over),
        "prob_btts_yes": float(prob_btts),
        "prob_btts_no": float(1 - prob_btts),
    }


def walk_forward_validation(
    df: pd.DataFrame,
    train_months: int = 12,
    min_value: float = 0.10,
    stake_mode: str = "kelly",
    min_odds: float = 1.40,
    max_odds: float = 5.0,
) -> BacktestResult:
    """Walk-forward: train on past, predict month by month."""
    console.print("[bold]Running walk-forward validation...[/bold]")
    console.print(f"  min_value={min_value:.0%}, odds=[{min_odds}-{max_odds}], stake={stake_mode}")

    df = df.sort_values("date").reset_index(drop=True)
    df["month"] = df["date"].dt.to_period("M")
    months = sorted(df["month"].unique())

    if len(months) < train_months + 2:
        console.print("[red]Not enough data[/red]")
        return BacktestResult()

    all_predictions = []
    test_months = months[train_months:]

    for month in track(test_months, description="Walk-forward..."):
        train_data = df[df["month"] < month]
        test_data = df[df["month"] == month]

        if len(train_data) < 100 or len(test_data) == 0:
            continue

        models = train_models(train_data)

        for _, row in test_data.iterrows():
            preds = predict_match_xgb(models, row)
            all_predictions.append({
                "date": row["date"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "result": row["result"],
                "total_goals": row["total_goals"],
                "over25": row["over25"],
                "btts": row["btts"],
                **preds,
                "odds_h": row["odds_h"],
                "odds_d": row["odds_d"],
                "odds_a": row["odds_a"],
                "odds_over25": row.get("odds_o25", 0),
                "odds_under25": row.get("odds_u25", 0),
            })

    if not all_predictions:
        console.print("[red]No predictions generated[/red]")
        return BacktestResult()

    pred_df = pd.DataFrame(all_predictions)
    console.print(f"[green]{len(pred_df)} predictions over {len(test_months)} months[/green]")

    result = run_backtest(
        pred_df, min_value=min_value, stake_mode=stake_mode,
        min_odds=min_odds, max_odds=max_odds,
    )
    return result


def optimize_params(df: pd.DataFrame) -> None:
    """Test multiple parameter combinations to find best config."""
    console.print("\n[bold]═══ PARAMETER OPTIMIZATION ═══[/bold]\n")

    configs = [
        {"min_value": 0.05, "min_odds": 1.20, "max_odds": 8.0, "stake_mode": "flat"},
        {"min_value": 0.10, "min_odds": 1.40, "max_odds": 5.0, "stake_mode": "flat"},
        {"min_value": 0.15, "min_odds": 1.50, "max_odds": 4.0, "stake_mode": "flat"},
        {"min_value": 0.10, "min_odds": 1.40, "max_odds": 5.0, "stake_mode": "kelly"},
        {"min_value": 0.15, "min_odds": 1.50, "max_odds": 4.0, "stake_mode": "kelly"},
        {"min_value": 0.20, "min_odds": 1.50, "max_odds": 3.5, "stake_mode": "kelly"},
    ]

    results_table = Table(title="Optimization Results")
    results_table.add_column("Config")
    results_table.add_column("Bets")
    results_table.add_column("Win%")
    results_table.add_column("Yield")
    results_table.add_column("Drawdown")

    for cfg in configs:
        result = walk_forward_validation(df, **cfg)
        label = f"v>{cfg['min_value']:.0%} odds[{cfg['min_odds']}-{cfg['max_odds']}] {cfg['stake_mode']}"
        yield_style = "green" if result.yield_pct >= 0 else "red"
        results_table.add_row(
            label,
            str(result.total_bets),
            f"{result.win_rate:.1%}",
            f"[{yield_style}]{result.yield_pct:+.1%}[/{yield_style}]",
            f"{result.max_drawdown:.0%}",
        )

    console.print(results_table)


def run_full_pipeline(leagues: list[str] | None = None, min_value: float = 0.10, optimize: bool = False) -> BacktestResult | None:
    """Run full pipeline: load → features → walk-forward → report."""
    from src.data import load_all_data

    console.print("[bold]Loading data...[/bold]")
    df = load_all_data()
    if df.empty:
        console.print("[red]No data. Run: aibet download[/red]")
        return None

    df = clean_matches(df)
    df = get_avg_odds(df)

    if leagues:
        df = df[df["League"].isin(leagues)]

    console.print(f"[green]{len(df)} matches loaded[/green]")
    console.print("Computing ELO ratings...")
    df = compute_elo_ratings(df)

    console.print("Building features...")
    dataset = build_dataset(df)
    console.print(f"[green]{len(dataset)} matches with full features[/green]")

    if len(dataset) < 200:
        console.print("[red]Not enough data[/red]")
        return None

    if optimize:
        optimize_params(dataset)
        return None

    result = walk_forward_validation(dataset, min_value=min_value, stake_mode="kelly", min_odds=1.40, max_odds=5.0)
    print_backtest_report(result)
    return result
