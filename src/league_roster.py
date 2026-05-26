"""Parse league rosters from Excel/CSV (fantacalcio.it export format)."""

import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def parse_rose_excel(filepath: str | Path) -> dict:
    """Parse Rose_*.xlsx file. Returns {team_name: [{ruolo_mantra, nome, squadra, costo}]}."""
    df = pd.read_excel(filepath, header=None)
    teams = {}
    current_left = None
    current_right = None

    for i in range(len(df)):
        row = df.iloc[i]
        val0 = str(row[0]).strip() if pd.notna(row[0]) else ""
        val5 = str(row[5]).strip() if pd.notna(row[5]) else ""

        # Detect team names (col 0 or 5, with NaN in next col, not a role/header)
        skip = ["Ruolo", "nan", "NaN", ""]
        is_role = lambda v: any(r in v for r in ["Por", "Dc", "Dd", "Ds", "E", "M", "C", "W", "T", "Pc", "A", "B"])

        if val0 and pd.isna(row[1]) and val0 not in skip and "Crediti" not in val0 and "http" not in val0 and "*" not in val0 and "Rose" not in val0 and not is_role(val0):
            current_left = val0
            teams.setdefault(current_left, [])

        if val5 and pd.isna(row[6]) and val5 not in skip and "Crediti" not in val5 and "http" not in val5 and "*" not in val5 and "Rose" not in val5 and not is_role(val5):
            current_right = val5
            teams.setdefault(current_right, [])

        # Player data left (cols 0-3)
        if current_left and pd.notna(row[1]) and pd.notna(row[2]) and val0 != "Ruolo" and is_role(val0):
            try:
                teams[current_left].append({
                    "ruolo_mantra": val0,
                    "nome": str(row[1]).strip(),
                    "squadra": str(row[2]).strip(),
                    "costo": int(row[3]) if pd.notna(row[3]) else 0,
                })
            except (ValueError, TypeError):
                pass

        # Player data right (cols 5-8)
        if current_right and pd.notna(row[6]) and pd.notna(row[7]) and val5 != "Ruolo" and is_role(val5):
            try:
                teams[current_right].append({
                    "ruolo_mantra": val5,
                    "nome": str(row[6]).strip(),
                    "squadra": str(row[7]).strip(),
                    "costo": int(row[8]) if pd.notna(row[8]) else 0,
                })
            except (ValueError, TypeError):
                pass

    return teams


def get_market_prices(teams: dict) -> dict[str, int]:
    """Get what each player was bought for across all teams. {name: price}."""
    prices = {}
    for team, players in teams.items():
        for p in players:
            prices[p["nome"].lower()] = p["costo"]
    return prices


def load_league_data() -> tuple[dict, dict]:
    """Load league rosters and market prices. Returns (teams, prices)."""
    # Look for any xlsx in data/
    for f in DATA_DIR.glob("Rose_*.xlsx"):
        teams = parse_rose_excel(f)
        prices = get_market_prices(teams)
        return teams, prices

    # Try CSV
    for f in DATA_DIR.glob("rose_*.csv"):
        df = pd.read_csv(f)
        # Assume columns: fantasquadra, ruolo_mantra, nome, squadra, costo
        teams = {}
        for _, row in df.iterrows():
            team = row.get("fantasquadra", "Unknown")
            teams.setdefault(team, []).append({
                "ruolo_mantra": row.get("ruolo_mantra", ""),
                "nome": row.get("nome", ""),
                "squadra": row.get("squadra", ""),
                "costo": int(row.get("costo", 0)),
            })
        prices = get_market_prices(teams)
        return teams, prices

    return {}, {}
