"""Download historical match data from football-data.co.uk."""

import requests
import pandas as pd
from pathlib import Path
from rich.console import Console
from rich.progress import track

from src.config import FD_BASE_URL, SEASONS, LEAGUES, DATA_RAW

console = Console()


def download_season(league_code: str, season: str, output_dir: Path) -> Path | None:
    """Download a single season CSV. Returns path or None on failure."""
    url = f"{FD_BASE_URL}/{season}/{league_code}.csv"
    output_path = output_dir / f"{league_code}_{season}.csv"

    if output_path.exists():
        return output_path

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
        return output_path
    except requests.RequestException as e:
        console.print(f"[red]Failed: {url} — {e}[/red]")
        return None


def download_all() -> list[Path]:
    """Download all configured leagues and seasons."""
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    downloaded = []

    tasks = [(code, season) for code in LEAGUES for season in SEASONS]

    for code, season in track(tasks, description="Downloading..."):
        path = download_season(code, season, DATA_RAW)
        if path:
            downloaded.append(path)

    console.print(f"[green]Downloaded {len(downloaded)}/{len(tasks)} files[/green]")
    return downloaded


def load_all_data() -> pd.DataFrame:
    """Load all downloaded CSVs into a single DataFrame."""
    frames = []
    for csv_path in sorted(DATA_RAW.glob("*.csv")):
        try:
            df = pd.read_csv(csv_path, encoding="utf-8", on_bad_lines="skip")
            parts = csv_path.stem.split("_")
            df["League"] = parts[0]
            df["Season"] = parts[1] if len(parts) > 1 else "unknown"
            frames.append(df)
        except Exception as e:
            console.print(f"[yellow]Skip {csv_path.name}: {e}[/yellow]")

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    download_all()
