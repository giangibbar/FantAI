"""Poisson-based match prediction model."""

import numpy as np
from scipy.stats import poisson
from dataclasses import dataclass


@dataclass
class MatchPrediction:
    """Prediction for a single match."""
    home_team: str
    away_team: str
    exp_home_goals: float
    exp_away_goals: float
    prob_home: float
    prob_draw: float
    prob_away: float
    prob_over25: float
    prob_under25: float


def predict_match(
    home_attack: float,
    home_defense: float,
    away_attack: float,
    away_defense: float,
    league_avg_home: float,
    league_avg_away: float,
    home_team: str = "",
    away_team: str = "",
    max_goals: int = 7,
) -> MatchPrediction:
    """Predict match outcome using Poisson model.

    Expected goals:
      home_exp = home_attack * away_defense * league_avg_home
      away_exp = away_attack * home_defense * league_avg_away
    """
    exp_home = home_attack * away_defense * league_avg_home
    exp_away = away_attack * home_defense * league_avg_away

    # Clamp to reasonable range
    exp_home = np.clip(exp_home, 0.2, 5.0)
    exp_away = np.clip(exp_away, 0.2, 5.0)

    # Build score matrix
    home_probs = [poisson.pmf(i, exp_home) for i in range(max_goals + 1)]
    away_probs = [poisson.pmf(i, exp_away) for i in range(max_goals + 1)]

    score_matrix = np.outer(home_probs, away_probs)

    prob_home = np.sum(np.tril(score_matrix, -1))  # home > away
    prob_draw = np.sum(np.diag(score_matrix))
    prob_away = np.sum(np.triu(score_matrix, 1))  # away > home

    # Over/Under 2.5
    prob_under25 = sum(
        score_matrix[i][j]
        for i in range(max_goals + 1)
        for j in range(max_goals + 1)
        if i + j <= 2
    )
    prob_over25 = 1 - prob_under25

    return MatchPrediction(
        home_team=home_team,
        away_team=away_team,
        exp_home_goals=round(exp_home, 2),
        exp_away_goals=round(exp_away, 2),
        prob_home=round(prob_home, 4),
        prob_draw=round(prob_draw, 4),
        prob_away=round(prob_away, 4),
        prob_over25=round(prob_over25, 4),
        prob_under25=round(prob_under25, 4),
    )


def find_value_bets(
    prediction: MatchPrediction,
    odds_home: float,
    odds_draw: float,
    odds_away: float,
    odds_over25: float | None = None,
    odds_under25: float | None = None,
    min_value: float = 0.05,
) -> list[dict]:
    """Find value bets where model probability > implied probability + margin."""
    bets = []

    markets = [
        ("1", prediction.prob_home, odds_home),
        ("X", prediction.prob_draw, odds_draw),
        ("2", prediction.prob_away, odds_away),
    ]
    if odds_over25:
        markets.append(("O2.5", prediction.prob_over25, odds_over25))
    if odds_under25:
        markets.append(("U2.5", prediction.prob_under25, odds_under25))

    for tip, model_prob, odds in markets:
        if odds <= 1.0:
            continue
        implied_prob = 1.0 / odds
        value = model_prob - implied_prob

        if value >= min_value:
            bets.append({
                "match": f"{prediction.home_team} vs {prediction.away_team}",
                "tip": tip,
                "odds": odds,
                "model_prob": f"{model_prob:.1%}",
                "implied_prob": f"{implied_prob:.1%}",
                "value": f"+{value:.1%}",
                "confidence": _confidence_stars(value),
            })

    return sorted(bets, key=lambda x: x["value"], reverse=True)


def _confidence_stars(value: float) -> str:
    if value >= 0.20:
        return "★★★★★"
    elif value >= 0.15:
        return "★★★★"
    elif value >= 0.10:
        return "★★★"
    elif value >= 0.07:
        return "★★"
    return "★"
