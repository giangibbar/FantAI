"""Scrape player quotazioni and Mantra roles from fantacalcio.it (Serie A + Euroleghe)."""

import requests
from bs4 import BeautifulSoup
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

URLS = {
    "serie_a": "https://www.fantacalcio.it/quotazioni-fantacalcio",
    "euroleghe": "https://www.fantacalcio.it/calciatori-fantacalcio-euro-leghe",
}


def _parse_table(soup) -> list[dict]:
    """Parse a fantacalcio.it player table."""
    table = soup.find("table")
    if not table:
        return []

    players = []
    for row in table.find_all("tr")[1:]:
        name_el = row.find("th", class_="player-name")
        if not name_el:
            continue

        name = name_el.get_text(strip=True)
        role_el = row.find("th", class_="player-role-classic")
        role_span = role_el.find("span", class_="role") if role_el else None
        role = role_span["data-value"].upper() if role_span and role_span.get("data-value") else ""

        mantra_el = row.find("th", class_="player-role-mantra")
        mantra_spans = mantra_el.find_all("span", class_="role-mantra") if mantra_el else []
        mantra = ";".join(s["data-value"].capitalize() for s in mantra_spans if s.get("data-value"))

        tds = [td.get_text(strip=True) for td in row.find_all("td")]
        # Columns: Sq, QI, QA, FVM, ... (may repeat for classic/mantra)
        squadra = tds[0] if tds else ""
        qi = int(tds[1]) if len(tds) > 1 and tds[1].isdigit() else 0
        qa = int(tds[2]) if len(tds) > 2 and tds[2].isdigit() else 0

        players.append({
            "nome": name,
            "ruolo": role,
            "ruolo_mantra": mantra or role,
            "squadra": squadra,
            "quotazione_iniziale": qi,
            "quotazione_attuale": qa,
        })

    return players


def scrape_quotazioni() -> pd.DataFrame:
    """Scrape Serie A + Euroleghe quotazioni."""
    all_players = []

    for key, url in URLS.items():
        r = requests.get(url, timeout=30, headers=HEADERS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        players = _parse_table(soup)
        for p in players:
            p["fonte"] = key
        all_players.extend(players)
        print(f"  {key}: {len(players)} giocatori")

    df = pd.DataFrame(all_players)
    df.to_csv(DATA_DIR / "quotazioni_fantacalcio.csv", index=False)
    print(f"Totale: {len(df)} giocatori salvati in data/quotazioni_fantacalcio.csv")
    return df


def load_quotazioni() -> pd.DataFrame:
    """Load quotazioni (scrape if not exists)."""
    path = DATA_DIR / "quotazioni_fantacalcio.csv"
    if path.exists():
        return pd.read_csv(path)
    return scrape_quotazioni()


if __name__ == "__main__":
    scrape_quotazioni()
