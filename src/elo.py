"""ELO rating system for football teams, updated match by match."""

import pandas as pd
import numpy as np


DEFAULT_ELO = 1500
K_FACTOR = 32
HOME_ADVANTAGE = 65


def expected_score(elo_a: float, elo_b: float) -> float:
    """Expected score for team A against team B."""
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400))


def update_elo(
    home_elo: float, away_elo: float, home_goals: int, away_goals: int, k: float = K_FACTOR
) -> tuple[float, float]:
    """Update ELO ratings after a match. Returns (new_home_elo, new_away_elo)."""
    # Actual score: 1 = win, 0.5 = draw, 0 = loss
    if home_goals > away_goals:
        actual_home = 1.0
    elif home_goals == away_goals:
        actual_home = 0.5
    else:
        actual_home = 0.0

    # Goal difference multiplier (bigger wins = bigger ELO change)
    goal_diff = abs(home_goals - away_goals)
    if goal_diff <= 1:
        gd_mult = 1.0
    elif goal_diff == 2:
        gd_mult = 1.5
    else:
        gd_mult = (11 + goal_diff) / 8

    # Expected with home advantage baked in
    exp_home = expected_score(home_elo + HOME_ADVANTAGE, away_elo)

    delta = k * gd_mult * (actual_home - exp_home)
    return home_elo + delta, away_elo - delta


def compute_elo_ratings(df: pd.DataFrame) -> pd.DataFrame:
    """Compute ELO ratings for all teams, match by match.

    Returns df with added columns: HomeElo, AwayElo (pre-match ratings).
    """
    df = df.sort_values("Date").reset_index(drop=True)
    elos: dict[str, float] = {}

    home_elos = []
    away_elos = []

    for _, row in df.iterrows():
        home = row["HomeTeam"]
        away = row["AwayTeam"]
        league = row.get("League", "")

        # Initialize if new team
        if home not in elos:
            elos[home] = DEFAULT_ELO
        if away not in elos:
            elos[away] = DEFAULT_ELO

        # Store pre-match ELO
        home_elos.append(elos[home])
        away_elos.append(elos[away])

        # Update after match
        new_home, new_away = update_elo(
            elos[home], elos[away], int(row["FTHG"]), int(row["FTAG"])
        )
        elos[home] = new_home
        elos[away] = new_away

    df["HomeElo"] = home_elos
    df["AwayElo"] = away_elos
    df["EloDiff"] = df["HomeElo"] - df["AwayElo"]

    return df


def get_current_elos(df: pd.DataFrame) -> dict[str, float]:
    """Get final ELO ratings after processing all matches."""
    df = df.sort_values("Date").reset_index(drop=True)
    elos: dict[str, float] = {}

    for _, row in df.iterrows():
        home = row["HomeTeam"]
        away = row["AwayTeam"]

        if home not in elos:
            elos[home] = DEFAULT_ELO
        if away not in elos:
            elos[away] = DEFAULT_ELO

        new_home, new_away = update_elo(
            elos[home], elos[away], int(row["FTHG"]), int(row["FTAG"])
        )
        elos[home] = new_home
        elos[away] = new_away

    return elos
