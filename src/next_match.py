"""Fetch upcoming fixtures and predict next matchday."""

import requests
import pandas as pd
from datetime import datetime
from rich.console import Console
from rich.table import Table

from src.config import LEAGUES
from src.data import load_all_data
from src.features import clean_matches, get_avg_odds
from src.elo import compute_elo_ratings, get_current_elos
from src.xgb_model import train_models, predict_match_xgb, FEATURE_COLS
from src.features import weighted_form, head_to_head, home_away_strength

console = Console()

FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"


def fetch_upcoming_fixtures(league: str = "I1") -> list[dict]:
    """Fetch real upcoming fixtures from football-data.co.uk."""
    try:
        resp = requests.get(FIXTURES_URL, timeout=15)
        resp.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(resp.content.decode("utf-8-sig")))
    except Exception as e:
        console.print(f"[red]Cannot fetch fixtures: {e}[/red]")
        return []

    league_df = df[df["Div"] == league]
    if league_df.empty:
        console.print(f"[yellow]No upcoming fixtures for {league}[/yellow]")
        return []

    fixtures = []
    for _, row in league_df.iterrows():
        fixtures.append({
            "date": row["Date"],
            "home": row["HomeTeam"],
            "away": row["AwayTeam"],
            "odds_h": row.get("B365H", 0),
            "odds_d": row.get("B365D", 0),
            "odds_a": row.get("B365A", 0),
            "odds_o25": row.get("B365>2.5", 0),
            "odds_u25": row.get("B365<2.5", 0),
        })

    return fixtures


def predict_next_matchday(league: str = "I1") -> None:
    """Predict upcoming matches for a league."""
    console.print(f"\n[bold]🔮 Predicting next matchday — {LEAGUES.get(league, league)}[/bold]\n")

    fixtures = fetch_upcoming_fixtures(league)
    if not fixtures:
        console.print("[red]No upcoming fixtures found[/red]")
        return

    console.print(f"[green]Found {len(fixtures)} upcoming matches[/green]")

    # Load historical data and train model
    console.print("Loading data and training model...")
    df = load_all_data()
    df = clean_matches(df)
    df = get_avg_odds(df)
    league_df = df[df["League"] == league]

    if len(league_df) < 100:
        console.print("[red]Not enough historical data[/red]")
        return

    league_df = compute_elo_ratings(league_df)
    elos = get_current_elos(league_df)

    from src.features import build_dataset
    dataset = build_dataset(league_df)
    if len(dataset) < 100:
        console.print("[red]Not enough features data[/red]")
        return

    models = train_models(dataset)

    predictions = []
    for fix in fixtures:
        home_match = _find_team(fix["home"], league_df)
        away_match = _find_team(fix["away"], league_df)

        if not home_match or not away_match:
            continue

        now = pd.Timestamp.now()
        home_form_data = weighted_form(league_df, home_match, now)
        away_form_data = weighted_form(league_df, away_match, now)
        h2h_data = head_to_head(league_df, home_match, away_match, now)
        home_str = home_away_strength(league_df, home_match, now)
        away_str = home_away_strength(league_df, away_match, now)

        home_elo = elos.get(home_match, 1500)
        away_elo = elos.get(away_match, 1500)

        # Use real odds as implied probs if available
        odds_h = fix.get("odds_h", 0) or 0
        odds_d = fix.get("odds_d", 0) or 0
        odds_a = fix.get("odds_a", 0) or 0

        row = pd.Series({
            "elo_diff": home_elo - away_elo,
            "home_elo": home_elo, "away_elo": away_elo,
            "home_form_pts": home_form_data["form_pts"],
            "home_form_gs": home_form_data["form_gs"],
            "home_form_gc": home_form_data["form_gc"],
            "home_form_shots": home_form_data["form_shots"],
            "home_form_sot": home_form_data["form_sot"],
            "away_form_pts": away_form_data["form_pts"],
            "away_form_gs": away_form_data["form_gs"],
            "away_form_gc": away_form_data["form_gc"],
            "away_form_shots": away_form_data["form_shots"],
            "away_form_sot": away_form_data["form_sot"],
            "h2h_home_wins": h2h_data["h2h_home_wins"],
            "h2h_draws": h2h_data["h2h_draws"],
            "h2h_avg_goals": h2h_data["h2h_avg_goals"],
            "home_attack": home_str["home_attack"],
            "home_defense": home_str["home_defense"],
            "away_attack": away_str["away_attack"],
            "away_defense": away_str["away_defense"],
            "implied_home": 1.0 / odds_h if odds_h > 1 else 0,
            "implied_draw": 1.0 / odds_d if odds_d > 1 else 0,
            "implied_away": 1.0 / odds_a if odds_a > 1 else 0,
        })

        preds = predict_match_xgb(models, row)
        predictions.append({
            "date": fix["date"],
            "home": home_match,
            "away": away_match,
            "odds_h": odds_h, "odds_d": odds_d, "odds_a": odds_a,
            **preds,
        })

    if not predictions:
        console.print("[red]Could not predict any matches (team names not found)[/red]")
        return

    # Display
    table = Table(title=f"📋 Prossimo Turno — {LEAGUES.get(league, league)}")
    table.add_column("Data")
    table.add_column("Partita")
    table.add_column("1", style="cyan")
    table.add_column("X", style="yellow")
    table.add_column("2", style="magenta")
    table.add_column("O2.5")
    table.add_column("BTTS")
    table.add_column("Quota")
    table.add_column("Tip", style="bold green")

    for p in predictions:
        probs_1x2 = {"1": p["prob_home"], "X": p["prob_draw"], "2": p["prob_away"]}
        best_1x2 = max(probs_1x2, key=probs_1x2.get)

        tips = []
        if probs_1x2[best_1x2] > 0.50:
            tips.append(best_1x2)
        if p["prob_over25"] > 0.55:
            tips.append("O2.5")
        if p["prob_btts_yes"] > 0.55:
            tips.append("BTTS")

        # Show odds for best tip
        odds_map = {"1": p["odds_h"], "X": p["odds_d"], "2": p["odds_a"]}
        best_odds = odds_map.get(best_1x2, 0)

        table.add_row(
            p["date"],
            f"{p['home']} vs {p['away']}",
            f"{p['prob_home']:.0%}",
            f"{p['prob_draw']:.0%}",
            f"{p['prob_away']:.0%}",
            f"{p['prob_over25']:.0%}",
            f"{p['prob_btts_yes']:.0%}",
            f"{best_odds:.2f}" if best_odds else "-",
            " + ".join(tips) if tips else "-",
        )

    console.print(table)


def _find_team(name: str, df: pd.DataFrame) -> str | None:
    """Fuzzy match team name against known teams in data."""
    teams = set(df["HomeTeam"].unique()) | set(df["AwayTeam"].unique())

    # Exact match
    if name in teams:
        return name

    # Case-insensitive
    name_lower = name.lower()
    for t in teams:
        if t.lower() == name_lower:
            return t

    # Substring match
    for t in teams:
        if name_lower in t.lower() or t.lower() in name_lower:
            return t

    # First word match (e.g. "Inter" matches "Inter")
    name_first = name_lower.split()[0] if name else ""
    for t in teams:
        if t.lower().startswith(name_first) and len(name_first) >= 3:
            return t

    return None
