"""Scraper for Fantacalcio.it player stats (5 seasons)."""

import requests
import pandas as pd
from bs4 import BeautifulSoup
from pathlib import Path
from rich.console import Console
from rich.progress import track

console = Console()

BASE_URL = "https://www.fantacalcio.it/statistiche-serie-a/{season}/fantamedia"
SEASONS = ["2024-25", "2023-24", "2022-23", "2021-22", "2020-21"]
DATA_DIR = Path(__file__).parent.parent / "data" / "fantacalcio"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def scrape_season(season: str) -> pd.DataFrame:
    """Scrape player stats for a single season from fantacalcio.it."""
    url = BASE_URL.format(season=season)
    resp = requests.get(url, timeout=20, headers=HEADERS)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find_all("table")[0]
    rows = table.find_all("tr")[1:]  # skip header

    players = []
    for row in rows:
        ths = row.find_all("th")
        tds = row.find_all("td")

        # Extract role (classic: p/d/c/a)
        role_el = row.find("th", class_="player-role-classic")
        role_span = role_el.find("span", class_="role") if role_el else None
        role = role_span["data-value"].upper() if role_span and role_span.get("data-value") else ""

        # Extract Mantra role
        mantra_el = row.find("th", class_="player-role-mantra")
        mantra_spans = mantra_el.find_all("span", class_="role-mantra") if mantra_el else []
        mantra_role = ";".join(s["data-value"].capitalize() for s in mantra_spans if s.get("data-value"))

        # Extract name
        name_el = row.find("th", class_="player-name")
        name = name_el.get_text(strip=True) if name_el else ""

        # Extract team and stats from td cells
        if len(tds) < 12 or not name:
            continue

        def parse_num(val: str) -> float:
            val = val.strip().replace(",", ".")
            if "/" in val:
                parts = val.split("/")
                return float(parts[0].strip()) if parts[0].strip() else 0
            try:
                return float(val)
            except ValueError:
                return 0

        team = tds[0].get_text(strip=True)
        players.append({
            "nome": name,
            "ruolo": role,
            "ruolo_mantra": mantra_role or role.capitalize(),
            "squadra": team,
            "presenze": int(parse_num(tds[1].get_text(strip=True))),
            "media_voto": parse_num(tds[2].get_text(strip=True)),
            "fantamedia": parse_num(tds[3].get_text(strip=True)),
            "gol": int(parse_num(tds[4].get_text(strip=True))),
            "gol_subiti": int(parse_num(tds[5].get_text(strip=True))),
            "rigori_tirati": int(parse_num(tds[6].get_text(strip=True))),
            "rigori_parati": int(parse_num(tds[7].get_text(strip=True))),
            "assist": int(parse_num(tds[8].get_text(strip=True))),
            "ammonizioni": int(parse_num(tds[9].get_text(strip=True))),
            "espulsioni": int(parse_num(tds[10].get_text(strip=True))),
            "stagione": season,
        })

    return pd.DataFrame(players)


def scrape_all_seasons() -> pd.DataFrame:
    """Scrape all 5 seasons and save to CSV."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_data = []

    for season in track(SEASONS, description="Scaricamento statistiche..."):
        csv_path = DATA_DIR / f"stats_{season}.csv"

        if csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            try:
                df = scrape_season(season)
                df.to_csv(csv_path, index=False)
                console.print(f"  [green]✓ {season}: {len(df)} giocatori[/green]")
            except Exception as e:
                console.print(f"  [red]✗ {season}: {e}[/red]")
                continue

        all_data.append(df)

    if not all_data:
        return pd.DataFrame()

    combined = pd.concat(all_data, ignore_index=True)
    combined.to_csv(DATA_DIR / "all_seasons.csv", index=False)
    console.print(f"\n[bold green]Totale: {len(combined)} record ({len(combined['nome'].unique())} giocatori unici)[/bold green]")
    return combined


def load_player_db() -> pd.DataFrame:
    """Load the player database (scrape if not exists)."""
    csv_path = DATA_DIR / "all_seasons.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return scrape_all_seasons()


if __name__ == "__main__":
    scrape_all_seasons()
