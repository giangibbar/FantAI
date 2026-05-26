"""Advanced feature engineering: weighted form, H2H, attack/defense strength."""

import pandas as pd
import numpy as np


def clean_matches(df: pd.DataFrame) -> pd.DataFrame:
    """Clean raw match data."""
    df = df.dropna(subset=["FTHG", "FTAG", "FTR"]).copy()
    df["FTHG"] = df["FTHG"].astype(int)
    df["FTAG"] = df["FTAG"].astype(int)

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)

    df["TotalGoals"] = df["FTHG"] + df["FTAG"]
    df["Over25"] = (df["TotalGoals"] > 2.5).astype(int)
    df["BTTS"] = ((df["FTHG"] > 0) & (df["FTAG"] > 0)).astype(int)

    return df


def _exponential_weights(n: int, decay: float = 0.85) -> np.ndarray:
    """Generate exponential decay weights. Most recent match = highest weight."""
    weights = np.array([decay ** i for i in range(n - 1, -1, -1)])
    return weights / weights.sum()


def weighted_form(df: pd.DataFrame, team: str, before_date: pd.Timestamp, n: int = 10, decay: float = 0.85) -> dict:
    """Compute weighted recent form for a team (exponential decay).

    Returns dict with: points, goals_scored, goals_conceded, shots, shots_on_target.
    """
    # Get last n matches before date
    home = df[(df["HomeTeam"] == team) & (df["Date"] < before_date)].tail(n)
    away = df[(df["AwayTeam"] == team) & (df["Date"] < before_date)].tail(n)

    matches = pd.concat([
        home.assign(
            GS=home["FTHG"], GC=home["FTAG"],
            Pts=home["FTR"].map({"H": 3, "D": 1, "A": 0}),
            S=home.get("HS", pd.Series(dtype=float)),
            ST=home.get("HST", pd.Series(dtype=float)),
            IsHome=1,
        ),
        away.assign(
            GS=away["FTAG"], GC=away["FTHG"],
            Pts=away["FTR"].map({"A": 3, "D": 1, "H": 0}),
            S=away.get("AS", pd.Series(dtype=float)),
            ST=away.get("AST", pd.Series(dtype=float)),
            IsHome=0,
        ),
    ]).sort_values("Date").tail(n)

    if len(matches) < 3:
        return {"form_pts": 0, "form_gs": 0, "form_gc": 0, "form_shots": 0, "form_sot": 0, "form_n": 0}

    w = _exponential_weights(len(matches), decay)

    return {
        "form_pts": float(np.average(matches["Pts"].fillna(0), weights=w)),
        "form_gs": float(np.average(matches["GS"].fillna(0), weights=w)),
        "form_gc": float(np.average(matches["GC"].fillna(0), weights=w)),
        "form_shots": float(np.average(matches["S"].fillna(0), weights=w)),
        "form_sot": float(np.average(matches["ST"].fillna(0), weights=w)),
        "form_n": len(matches),
    }


def head_to_head(df: pd.DataFrame, home: str, away: str, before_date: pd.Timestamp, n: int = 10) -> dict:
    """Compute head-to-head stats between two teams."""
    h2h = df[
        ((df["HomeTeam"] == home) & (df["AwayTeam"] == away) |
         (df["HomeTeam"] == away) & (df["AwayTeam"] == home))
        & (df["Date"] < before_date)
    ].tail(n)

    if len(h2h) < 2:
        return {"h2h_home_wins": 0, "h2h_draws": 0, "h2h_away_wins": 0, "h2h_avg_goals": 0, "h2h_n": 0}

    home_wins = len(h2h[
        ((h2h["HomeTeam"] == home) & (h2h["FTR"] == "H")) |
        ((h2h["AwayTeam"] == home) & (h2h["FTR"] == "A"))
    ])
    away_wins = len(h2h[
        ((h2h["HomeTeam"] == away) & (h2h["FTR"] == "H")) |
        ((h2h["AwayTeam"] == away) & (h2h["FTR"] == "A"))
    ])
    draws = len(h2h[h2h["FTR"] == "D"])

    return {
        "h2h_home_wins": home_wins / len(h2h),
        "h2h_draws": draws / len(h2h),
        "h2h_away_wins": away_wins / len(h2h),
        "h2h_avg_goals": h2h["TotalGoals"].mean(),
        "h2h_n": len(h2h),
    }


def home_away_strength(df: pd.DataFrame, team: str, before_date: pd.Timestamp, n: int = 15) -> dict:
    """Compute home/away specific attack and defense strength."""
    league_df = df[df["Date"] < before_date]
    if league_df.empty:
        return {"home_attack": 1.0, "home_defense": 1.0, "away_attack": 1.0, "away_defense": 1.0}

    avg_hg = league_df["FTHG"].mean() or 1.0
    avg_ag = league_df["FTAG"].mean() or 1.0

    home_matches = league_df[league_df["HomeTeam"] == team].tail(n)
    away_matches = league_df[league_df["AwayTeam"] == team].tail(n)

    home_attack = (home_matches["FTHG"].mean() / avg_hg) if len(home_matches) >= 3 else 1.0
    home_defense = (home_matches["FTAG"].mean() / avg_ag) if len(home_matches) >= 3 else 1.0
    away_attack = (away_matches["FTAG"].mean() / avg_ag) if len(away_matches) >= 3 else 1.0
    away_defense = (away_matches["FTHG"].mean() / avg_hg) if len(away_matches) >= 3 else 1.0

    return {
        "home_attack": home_attack,
        "home_defense": home_defense,
        "away_attack": away_attack,
        "away_defense": away_defense,
    }


def build_features_for_match(df: pd.DataFrame, idx: int) -> dict | None:
    """Build full feature vector for a single match row."""
    row = df.iloc[idx]
    date = row["Date"]
    home = row["HomeTeam"]
    away = row["AwayTeam"]
    league = row.get("League", "")

    league_df = df[df["League"] == league] if league else df

    # Need enough history
    past = league_df[league_df["Date"] < date]
    if len(past) < 50:
        return None

    # Form
    home_form = weighted_form(league_df, home, date)
    away_form = weighted_form(league_df, away, date)

    if home_form["form_n"] < 3 or away_form["form_n"] < 3:
        return None

    # H2H
    h2h = head_to_head(league_df, home, away, date)

    # Strength
    home_str = home_away_strength(league_df, home, date)
    away_str = home_away_strength(league_df, away, date)

    # ELO (if available)
    elo_diff = row.get("EloDiff", 0)
    home_elo = row.get("HomeElo", 1500)
    away_elo = row.get("AwayElo", 1500)

    # Odds (implied probabilities)
    odds_h = row.get("AvgOddsH", row.get("B365H", 0))
    odds_d = row.get("AvgOddsD", row.get("B365D", 0))
    odds_a = row.get("AvgOddsA", row.get("B365A", 0))
    odds_o25 = row.get("AvgOddsO25", row.get("B365>2.5", 0))
    odds_u25 = row.get("AvgOddsU25", row.get("B365<2.5", 0))

    features = {
        # ELO
        "elo_diff": elo_diff,
        "home_elo": home_elo,
        "away_elo": away_elo,
        # Home form
        "home_form_pts": home_form["form_pts"],
        "home_form_gs": home_form["form_gs"],
        "home_form_gc": home_form["form_gc"],
        "home_form_shots": home_form["form_shots"],
        "home_form_sot": home_form["form_sot"],
        # Away form
        "away_form_pts": away_form["form_pts"],
        "away_form_gs": away_form["form_gs"],
        "away_form_gc": away_form["form_gc"],
        "away_form_shots": away_form["form_shots"],
        "away_form_sot": away_form["form_sot"],
        # H2H
        "h2h_home_wins": h2h["h2h_home_wins"],
        "h2h_draws": h2h["h2h_draws"],
        "h2h_avg_goals": h2h["h2h_avg_goals"],
        # Strength
        "home_attack": home_str["home_attack"],
        "home_defense": home_str["home_defense"],
        "away_attack": away_str["away_attack"],
        "away_defense": away_str["away_defense"],
        # Odds implied probs
        "implied_home": 1.0 / odds_h if odds_h > 1 else 0,
        "implied_draw": 1.0 / odds_d if odds_d > 1 else 0,
        "implied_away": 1.0 / odds_a if odds_a > 1 else 0,
        # Target
        "result": {"H": 0, "D": 1, "A": 2}.get(row["FTR"], -1),
        "total_goals": row["TotalGoals"],
        "over25": row["Over25"],
        "btts": row["BTTS"],
        # Meta
        "date": date,
        "home_team": home,
        "away_team": away,
        "odds_h": odds_h,
        "odds_d": odds_d,
        "odds_a": odds_a,
        "odds_o25": odds_o25 if odds_o25 else 0,
        "odds_u25": odds_u25 if odds_u25 else 0,
    }

    return features


def build_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Build full feature dataset from all matches."""
    records = []
    for i in range(len(df)):
        feat = build_features_for_match(df, i)
        if feat and feat["result"] >= 0:
            records.append(feat)

    return pd.DataFrame(records)


def get_avg_odds(df: pd.DataFrame) -> pd.DataFrame:
    """Compute average bookmaker odds per match."""
    odds_h = [c for c in ["B365H", "BWH", "PSH"] if c in df.columns]
    odds_d = [c for c in ["B365D", "BWD", "PSD"] if c in df.columns]
    odds_a = [c for c in ["B365A", "BWA", "PSA"] if c in df.columns]

    if odds_h:
        df["AvgOddsH"] = df[odds_h].mean(axis=1)
    if odds_d:
        df["AvgOddsD"] = df[odds_d].mean(axis=1)
    if odds_a:
        df["AvgOddsA"] = df[odds_a].mean(axis=1)

    # Over/Under 2.5
    ou_over = [c for c in ["B365>2.5", "P>2.5"] if c in df.columns]
    ou_under = [c for c in ["B365<2.5", "P<2.5"] if c in df.columns]
    if ou_over:
        df["AvgOddsO25"] = df[ou_over].mean(axis=1)
    if ou_under:
        df["AvgOddsU25"] = df[ou_under].mean(axis=1)

    return df


def compute_team_stats(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """Compute attack/defense strength per team (simple version for CLI predict)."""
    avg_home_goals = df["FTHG"].mean() or 1.0
    avg_away_goals = df["FTAG"].mean() or 1.0
    teams = set(df["HomeTeam"].unique()) | set(df["AwayTeam"].unique())
    records = []
    for team in teams:
        home_m = df[df["HomeTeam"] == team].tail(window)
        away_m = df[df["AwayTeam"] == team].tail(window)
        if len(home_m) < 3 or len(away_m) < 3:
            continue
        attack = ((home_m["FTHG"].mean() / avg_home_goals) + (away_m["FTAG"].mean() / avg_away_goals)) / 2
        defense = ((home_m["FTAG"].mean() / avg_away_goals) + (away_m["FTHG"].mean() / avg_home_goals)) / 2
        records.append({"Team": team, "AttackStrength": attack, "DefenseStrength": defense})
    return pd.DataFrame(records)
