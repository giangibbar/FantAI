"""Scrape SOS Fanta for all auction-relevant info."""

import requests
from bs4 import BeautifulSoup
from pathlib import Path
import json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
CACHE_DIR = Path(__file__).parent.parent / "data" / "sosfanta"
URLS_FILE = CACHE_DIR / "urls.json"

DEFAULT_PAGES = {
    "guida_asta_por": {
        "url": "https://www.sosfanta.com/consigli-fantacalcio/guida-asta-fantacalcio-2025-2026-divisione-fasce-consigli/",
        "title": "Guida Asta — Portieri",
    },
    "guida_asta_dif": {
        "url": "https://www.sosfanta.com/consigli-fantacalcio/guida-asta-fantacalcio-2025-2026-divisione-fasce-consigli/2",
        "title": "Guida Asta — Difensori",
    },
    "guida_asta_cen": {
        "url": "https://www.sosfanta.com/consigli-fantacalcio/guida-asta-fantacalcio-2025-2026-divisione-fasce-consigli/3",
        "title": "Guida Asta — Centrocampisti",
    },
    "guida_asta_att": {
        "url": "https://www.sosfanta.com/consigli-fantacalcio/guida-asta-fantacalcio-2025-2026-divisione-fasce-consigli/4",
        "title": "Guida Asta — Attaccanti",
    },
    "formazioni_tipo": {
        "url": "https://www.sosfanta.com/asta-riparazione-fantacalcio/tutte-le-formazioni-tipo-in-serie-a-per-lasta-di-riparazione-oggi-giocherebbero-cosi/",
        "title": "Formazioni Tipo",
    },
    "rigoristi": {
        "url": "https://www.sosfanta.com/asta-riparazione-fantacalcio/tutti-i-rigoristi-in-serie-a-cosa-cambia-dopo-il-calciomercato-e-la-lista-completa-squadra-per-squadra/",
        "title": "Rigoristi",
    },
    "gerarchie_portieri": {
        "url": "https://www.sosfanta.com/asta-riparazione-fantacalcio/portieri-ecco-tutte-le-gerarchie-con-le-novita-dopo-il-mercato-e-meta-stagione-primo-secondo-e-terzo/",
        "title": "Gerarchie Portieri",
    },
    "chi_prendere_difensori": {
        "url": "https://www.sosfanta.com/asta-riparazione-fantacalcio/chi-prendere-allasta-di-riparazione-al-fantacalcio-ecco-sei-difensori-di-prezzo-diverso/",
        "title": "Chi Prendere: Difensori",
    },
    "chi_prendere_centrocampisti": {
        "url": "https://www.sosfanta.com/asta-riparazione-fantacalcio/chi-prendere-allasta-di-riparazione-al-fantacalcio-ecco-otto-centrocampisti-di-prezzo-diverso/",
        "title": "Chi Prendere: Centrocampisti",
    },
    "chi_prendere_attaccanti": {
        "url": "https://www.sosfanta.com/asta-riparazione-fantacalcio/chi-prendere-allasta-di-riparazione-al-fantacalcio-ecco-sei-attaccanti-di-prezzo-diverso/",
        "title": "Chi Prendere: Attaccanti",
    },
    "chi_svincolare_difensori": {
        "url": "https://www.sosfanta.com/consigli-fantacalcio/difensori-chi-svincolare-e-chi-no-buongiorno-beukema-bellanova-de-vrij-gosens-angelino-lucumi/",
        "title": "Chi Svincolare: Difensori",
    },
    "chi_svincolare_centrocampisti": {
        "url": "https://www.sosfanta.com/consigli-fantacalcio/centrocampisti-chi-svincolare-e-chi-no-pasalic-zhegrova-berna-loftus-conceicao-oristanio-maldini/",
        "title": "Chi Svincolare: Centrocampisti",
    },
    "chi_svincolare_attaccanti": {
        "url": "https://www.sosfanta.com/consigli-fantacalcio/attacco-chi-svincolare-e-chi-no-davis-kean-dybala-simeone-zapata-piccoli-giovane-stulic/",
        "title": "Chi Svincolare: Attaccanti",
    },
}


def _fetch_page_content(url: str) -> str:
    """Fetch and extract readable content from a SOS Fanta page."""
    r = requests.get(url, timeout=20, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    main = soup.select_one("main")
    if not main:
        return ""

    # Remove nav, header, footer, ads
    for tag in main.find_all(["nav", "header", "footer", "script", "style"]):
        tag.decompose()

    # Get paragraphs with meaningful content
    paragraphs = []
    for el in main.find_all(["p", "h2", "h3", "li"]):
        text = el.get_text(strip=True)
        if len(text) > 20:
            if el.name in ("h2", "h3"):
                paragraphs.append(f"\n**{text}**\n")
            else:
                paragraphs.append(text)

    return "\n\n".join(paragraphs)


def get_pages() -> dict:
    """Load URLs from config file, or use defaults."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if URLS_FILE.exists():
        return json.loads(URLS_FILE.read_text())
    return DEFAULT_PAGES


def save_pages(pages: dict):
    """Save URLs config."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    URLS_FILE.write_text(json.dumps(pages, ensure_ascii=False, indent=2))


def update_url(key: str, url: str, title: str = None):
    """Update a single URL. If key doesn't exist, creates it."""
    pages = get_pages()
    if key in pages:
        pages[key]["url"] = url
        if title:
            pages[key]["title"] = title
    else:
        pages[key] = {"url": url, "title": title or key}
    save_pages(pages)


def scrape_all_pages(force: bool = False) -> dict:
    """Scrape all SOS Fanta pages. Returns {key: {title, content}}."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "all_pages.json"

    if cache_file.exists() and not force:
        return json.loads(cache_file.read_text())

    pages = get_pages()
    data = {}
    for key, info in pages.items():
        try:
            content = _fetch_page_content(info["url"])
            data[key] = {"title": info["title"], "content": content, "url": info["url"]}
        except Exception as e:
            data[key] = {"title": info["title"], "content": f"Errore: {e}", "url": info["url"]}

    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def load_sosfanta_data() -> dict:
    """Load SOS Fanta data (scrape if needed). Returns full data dict."""
    return scrape_all_pages()


if __name__ == "__main__":
    data = scrape_all_pages(force=True)
    for key, info in data.items():
        print(f"{info['title']}: {len(info['content'])} chars")
