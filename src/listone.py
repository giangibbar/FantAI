"""Scrape/load the full Serie A player list (listone) with quotazioni."""

import requests
import pandas as pd
from bs4 import BeautifulSoup
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
LISTONE_URL = "https://www.fantamagic.it/fantacalcio/listapersquadra.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def scrape_listone() -> pd.DataFrame:
    """Scrape full player list from fantamagic.it."""
    r = requests.get(LISTONE_URL, timeout=20, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    tables = soup.find_all("table")

    # Tables 7=Por, 8=Dif, 9=Cen, 10=Att (0-indexed: 7,8,9,10 but may shift)
    # Find tables with 3-column rows (Nome, Quotazione, Squadra)
    role_map = {"Por": None, "D": None, "C": None, "A": None}
    role_tables = []

    for t in tables:
        rows = t.find_all("tr")
        if len(rows) > 50:
            first_row = rows[0].find_all("td")
            if len(first_row) == 3:
                role_tables.append(t)

    roles = ["Por", "D", "C", "A"]
    players = []

    for i, t in enumerate(role_tables):
        role = roles[i] if i < len(roles) else "?"
        for row in t.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) == 3:
                nome = cells[0].get_text(strip=True)
                quota = cells[1].get_text(strip=True)
                squadra = cells[2].get_text(strip=True)
                if nome and squadra:
                    try:
                        players.append({
                            "nome": nome,
                            "ruolo": role,
                            "squadra": squadra,
                            "quotazione": int(quota),
                        })
                    except ValueError:
                        pass

    df = pd.DataFrame(players)
    df.to_csv(DATA_DIR / "listone_2025_26.csv", index=False)
    return df


def load_listone() -> pd.DataFrame:
    """Load listone (prefer quotazioni from fantacalcio.it, fallback to scraped)."""
    # Prefer the full quotazioni file (has Mantra roles for all)
    quot_path = DATA_DIR / "quotazioni_fantacalcio.csv"
    if quot_path.exists():
        df = pd.read_csv(quot_path)
        # Only Serie A for the listone
        df = df[df["fonte"] == "serie_a"].copy()
        df = df.rename(columns={"quotazione_attuale": "quotazione"})
        return df[["nome", "ruolo", "ruolo_mantra", "squadra", "quotazione"]]

    # Fallback to old listone
    for f in sorted(DATA_DIR.glob("listone_*.csv"), reverse=True):
        return pd.read_csv(f)

    return scrape_listone()


if __name__ == "__main__":
    df = scrape_listone()
    print(f"Totale: {len(df)} giocatori")
    print(f"Per ruolo: {df['ruolo'].value_counts().to_dict()}")
    print(f"\nTop quotazioni:")
    print(df.nlargest(10, "quotazione")[["nome", "ruolo", "squadra", "quotazione"]].to_string(index=False))
