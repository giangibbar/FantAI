"""Load the full Serie A player list from fantacalcio.it quotazioni."""

import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def load_listone() -> pd.DataFrame:
    """Load listone from quotazioni_fantacalcio.csv (scraped from fantacalcio.it)."""
    quot_path = DATA_DIR / "quotazioni_fantacalcio.csv"
    if quot_path.exists():
        df = pd.read_csv(quot_path)
        df = df[df["fonte"] == "serie_a"].copy()
        df = df.rename(columns={"quotazione_attuale": "quotazione"})
        return df[["nome", "ruolo", "ruolo_mantra", "squadra", "quotazione"]]

    # If not available, trigger scrape
    from src.quotazioni import scrape_quotazioni
    scrape_quotazioni()
    return load_listone()
