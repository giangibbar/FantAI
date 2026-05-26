# 🏆 FantAI

Assistente intelligente per l'asta del Fantacalcio Mantra.

## Cosa fa

FantAI ti aiuta durante l'asta del fantacalcio con il sistema Mantra:

- **📊 Database giocatori** — Statistiche degli ultimi 5 anni (fantamedia, gol, assist, presenze) da fantacalcio.it
- **🎯 Valutazione asta** — Ti dice se un giocatore vale il prezzo proposto, suggerisce alternative
- **📋 Gestione rosa** — Traccia i tuoi acquisti, mostra copertura moduli con percentuale
- **💡 Suggerisci top 11** — Per ogni formazione, suggerisce i migliori giocatori disponibili rispettando il budget
- **👥 Tracker avversari** — Monitora cosa comprano gli altri e quanto spendono
- **⭐ Preferiti e note** — Segna giocatori da tenere d'occhio, appunti per l'asta
- **📊 Info SOS Fanta** — Guida asta, formazioni tipo, rigoristi, gerarchie portieri (scraping automatico)

## Requisiti

- Python 3.11+
- Connessione internet (per scraping dati)

## Installazione

```bash
cd FantAI
python3 -m venv .venv
source .venv/bin/activate
pip install flask pandas beautifulsoup4 lxml openpyxl requests rich
```

## Avvio

```bash
python webapp.py
```

Apri **http://localhost:5000** dal browser (PC o telefono sulla stessa rete).

## Struttura

```
FantAI/
├── webapp.py              # Flask server
├── templates/index.html   # Frontend (single page app)
├── static/moduli/         # Immagini formazioni Mantra
├── src/
│   ├── fantacalcio.py     # Scraper statistiche fantacalcio.it
│   ├── listone.py         # Scraper listone giocatori
│   ├── sosfanta.py        # Scraper SOS Fanta (guide, formazioni, rigoristi)
│   ├── valuation.py       # Motore di valutazione giocatori
│   └── league_roster.py   # Parser rose della lega
├── data/
│   ├── fantacalcio/       # Stats 5 stagioni (CSV)
│   ├── listone_2025_26.csv
│   ├── mapping_nomi.csv   # Mapping nomi listone ↔ database
│   └── Rose_*.xlsx        # Rose della lega (riferimento prezzi)
```

## Aggiornamento per nuova stagione

1. **Listone** — Carica il nuovo CSV da ⚙️ Impostazioni
2. **Link SOS Fanta** — Aggiorna gli URL quando escono le nuove guide
3. **Mapping nomi** — Compila `data/mapping_nomi.csv` per i giocatori non riconosciuti
4. **Stats** — Esegui `python -m src.fantacalcio` per scrappare la nuova stagione

## Fonti dati

| Fonte | Cosa fornisce |
|-------|--------------|
| [fantacalcio.it](https://www.fantacalcio.it) | Fantamedie, ruoli Mantra, statistiche 5 anni |
| [fantamagic.it](https://www.fantamagic.it) | Listone giocatori con quotazioni |
| [SOS Fanta](https://www.sosfanta.com) | Guide asta, formazioni tipo, rigoristi |
| [football-data.co.uk](https://www.football-data.co.uk) | Risultati e quote storiche |

## License

MIT
