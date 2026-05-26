"""Configuration for AiBet."""

from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
DATA_RAW = ROOT_DIR / "data" / "raw"
DATA_PROCESSED = ROOT_DIR / "data" / "processed"

# football-data.co.uk CSV base URL
FD_BASE_URL = "https://www.football-data.co.uk/mmz4281"

# Seasons to download (last 5 full seasons)
SEASONS = ["2122", "2223", "2324", "2425", "2526"]

# Leagues: (code for URL, display name)
LEAGUES = {
    "I1": "Serie A",
    "E0": "Premier League",
    "SP1": "La Liga",
    "D1": "Bundesliga",
    "F1": "Ligue 1",
}

# Key columns from football-data.co.uk CSVs
MATCH_COLS = [
    "Date", "HomeTeam", "AwayTeam",
    "FTHG", "FTAG", "FTR",  # Full time home/away goals, result
    "HTHG", "HTAG", "HTR",  # Half time
    "HS", "AS", "HST", "AST",  # Shots, shots on target
    "HC", "AC",  # Corners
    "HF", "AF",  # Fouls
    "HY", "AY", "HR", "AR",  # Cards
]

# Bookmaker odds columns (1X2)
ODDS_COLS = [
    "B365H", "B365D", "B365A",  # Bet365
    "BWH", "BWD", "BWA",  # Betway
    "PSH", "PSD", "PSA",  # Pinnacle
]

# Over/Under 2.5 odds
OU_COLS = ["B365>2.5", "B365<2.5", "P>2.5", "P<2.5"]
