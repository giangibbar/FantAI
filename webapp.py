"""AiBet — Flask web app for Fantacalcio Mantra auction."""

import json
from flask import Flask, render_template, request, jsonify
from src.valuation import load_db, valuate_player, get_top_players, search_players, suggest_alternative, should_buy
from src.league_roster import load_league_data

app = Flask(__name__, template_folder="templates", static_folder="static")

# Auto-refresh data on startup (if older than 24h)
print("Controllo dati...")
from src.quotazioni import scrape_quotazioni
from src.fantacalcio import scrape_all_seasons
from pathlib import Path
import time

quot_file = Path("data/quotazioni_fantacalcio.csv")
stats_file = Path("data/fantacalcio/all_seasons.csv")
stale = lambda f: not f.exists() or (time.time() - f.stat().st_mtime > 86400)

try:
    if stale(quot_file):
        print("  Aggiornamento quotazioni da fantacalcio.it...")
        scrape_quotazioni()
    if stale(stats_file):
        print("  Aggiornamento statistiche da fantacalcio.it...")
        scrape_all_seasons()
    print("  ✓ Dati aggiornati")
except Exception as e:
    print(f"  ⚠️ Errore: {e} (uso dati esistenti)")

db = load_db()

# Load SOS Fanta data
try:
    from src.sosfanta import load_sosfanta_data
    sosfanta = load_sosfanta_data()
except Exception:
    sosfanta = {}

# Load league rosters and market prices
league_teams, market_prices = load_league_data()
print(f"Loaded: {len(league_teams)} fantasy teams, {len(market_prices)} market prices")

# Get all Serie A squads
SQUAD_NAMES = {"ATA":"Atalanta","BOL":"Bologna","CAG":"Cagliari","COM":"Como","CRE":"Cremonese","FIO":"Fiorentina","GEN":"Genoa","INT":"Inter","JUV":"Juventus","LAZ":"Lazio","LEC":"Lecce","MIL":"Milan","NAP":"Napoli","PAR":"Parma","PIS":"Pisa","ROM":"Roma","SAS":"Sassuolo","TOR":"Torino","UDI":"Udinese","VER":"Verona"}
squads = sorted(SQUAD_NAMES.values())


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def api_search():
    from unicodedata import normalize, category
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    # Normalize query (remove accents, Turkish chars)
    q_norm = q.replace('ı', 'i').replace('İ', 'i').replace('ş', 's').replace('ç', 'c').replace('ğ', 'g').replace('ø', 'o')
    q_norm = ''.join(c for c in normalize('NFD', q_norm) if category(c) != 'Mn')
    return jsonify(search_players(q_norm, db, sosfanta, market_prices))


@app.route("/api/player/<name>")
def api_player(name):
    val = valuate_player(name, db, sosfanta, market_prices)
    if not val:
        return jsonify({"error": "Giocatore non trovato"}), 404
    return jsonify(val)


@app.route("/api/player_profile/<name>")
def api_player_profile(name):
    """Scrape detailed profile from fantacalcio.it (FVM, MV, rigori, pro/contro)."""
    import requests as req
    from bs4 import BeautifulSoup

    # Find player link from quotazioni page
    from src.quotazioni import load_quotazioni
    quot = load_quotazioni()
    # Normalize search: strip accents, apostrophes, asterisks
    from unicodedata import normalize as _n, category as _c
    def _clean(s):
        s = s.replace("'","").replace("'","").replace("*","")
        return ''.join(c for c in _n('NFD', s.lower()) if _c(c) != 'Mn')
    search = _clean(name)
    player = quot[quot["nome"].apply(lambda x: search in _clean(x))]
    if player.empty:
        return jsonify({"error": "Non trovato"}), 404

    # Build profile URL
    p_name = player.iloc[0]["nome"].lower().replace(" ", "-").replace("'", "").replace("*", "")
    p_squad = player.iloc[0]["squadra"].lower()
    squad_map = {"ata":"atalanta","bol":"bologna","cag":"cagliari","com":"como","cre":"cremonese","fio":"fiorentina","gen":"genoa","int":"inter","juv":"juventus","laz":"lazio","lec":"lecce","mil":"milan","nap":"napoli","par":"parma","pis":"pisa","rom":"roma","sas":"sassuolo","tor":"torino","udi":"udinese","ver":"verona"}
    squad_full = squad_map.get(p_squad, p_squad)

    # Try to find the actual link from the quotazioni page
    try:
        r = req.get(f"https://www.fantacalcio.it/quotazioni-fantacalcio", timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        link = None
        for a in soup.find_all("a", class_="player-name", href=True):
            if search in _clean(a.get_text(strip=True)):
                link = a["href"]
                break

        if not link:
            return jsonify({"error": "Link profilo non trovato"}), 404

        r2 = req.get(link, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        soup2 = BeautifulSoup(r2.text, "html.parser")

        result = {"nome": player.iloc[0]["nome"]}

        # Stats box
        stats_div = soup2.find("div", class_="player-stats")
        if stats_div:
            text = stats_div.get_text(" ", strip=True)
            result["stats_raw"] = text

        # Tables: gol casa/trasferta, rigori, ammonizioni
        tables = soup2.find_all("table")
        for t in tables:
            for row in t.find_all("tr"):
                ths = row.find_all("th")
                tds = row.find_all("td")
                if ths and tds:
                    key = ths[0].get_text(strip=True)
                    val_text = tds[0].get_text(strip=True)
                    if "casa/trasferta" in key.lower():
                        result["gol_casa_trasferta"] = val_text
                    elif "rigori" in key.lower():
                        result["rigori"] = val_text
                    elif "ammonizioni" in key.lower():
                        result["ammonizioni"] = val_text
                    elif "partite" in key.lower():
                        result["partite"] = val_text

        # Description
        desc = soup2.find("div", class_="description")
        if desc:
            result["descrizione"] = desc.get_text(strip=True)[:300]

        # Pro/Contro
        for li in soup2.find_all("li", class_="bullist"):
            text = li.get_text(strip=True)
            if text.startswith("PRO"):
                result["pro"] = text[4:].strip()
            elif text.startswith("CONTRO"):
                result["contro"] = text[7:].strip()

        # SOS Fanta description (from guida asta)
        surname = _clean(name.split()[0])
        for page_key in ["guida_asta_att", "guida_asta_cen", "guida_asta_dif", "guida_asta_por"]:
            page_content = sosfanta.get(page_key, {}).get("content", "")
            for line in page_content.split("\n"):
                if len(line) > 80 and " - " not in line[:30]:
                    line_start = _clean(line[:40])
                    if surname in line_start:
                        result["sosfanta_desc"] = line[:400]
                        break
            if "sosfanta_desc" in result:
                break

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/top")
def api_top():
    role = request.args.get("role", None)
    squadra = request.args.get("squadra", None)
    limit = int(request.args.get("limit", 30))
    return jsonify(get_top_players(db, role=role, squadra=squadra, limit=limit, sosfanta=sosfanta, market_prices=market_prices))


@app.route("/api/alternative/<name>")
def api_alternative(name):
    return jsonify(suggest_alternative(name, db, sosfanta, market_prices))


@app.route("/api/should_buy", methods=["POST"])
def api_should_buy():
    data = request.get_json()
    name = data.get("nome", "")
    price = int(data.get("prezzo", 0))
    my_team = data.get("rosa", [])
    budget_left = int(data.get("budget", 500))
    return jsonify(should_buy(name, price, my_team, budget_left, db, sosfanta, market_prices))


@app.route("/api/squads")
def api_squads():
    return jsonify(squads)


@app.route("/api/state", methods=["GET"])
def api_state_load():
    """Load saved state from server file."""
    state_file = Path("data/user_state.json")
    if state_file.exists():
        return jsonify(json.loads(state_file.read_text()))
    return jsonify({})


@app.route("/api/state", methods=["POST"])
def api_state_save():
    """Save state to server file."""
    data = request.get_json()
    Path("data/user_state.json").write_text(json.dumps(data, ensure_ascii=False))
    return jsonify({"ok": True})


@app.route("/api/sosfanta")
def api_sosfanta():
    """Get all SOS Fanta articles."""
    return jsonify(sosfanta)


@app.route("/api/player_tags")
def api_player_tags():
    """Extract player tags from tier lines like 'TOP - Svilar, Di Gregorio, Maignan'."""
    from src.listone import load_listone
    listone = load_listone()

    # Build lookup
    listone_entries = []
    surname_count = {}
    from unicodedata import normalize as _nrm, category as _cat
    def _norm_name(s):
        s = s.replace('ı','i').replace('ş','s').replace('ç','c').replace('ğ','g').replace('ø','o').replace('*','')
        s = ''.join(c for c in _nrm('NFD', s.lower()) if _cat(c) != 'Mn')
        return s.rstrip("''\u2019'").replace("'","")
    for _, row in listone.iterrows():
        parts = row["nome"].replace("*","").split()
        surname = _norm_name(parts[0]) if parts else ""
        firstname = _norm_name(parts[1]) if len(parts) >= 2 else ""
        surname_count[surname] = surname_count.get(surname, 0) + 1
        listone_entries.append({"surname": surname, "firstname": firstname})

    def match_name(raw_name):
        """Match SOS Fanta name to listone surname. Returns unique key."""
        from unicodedata import normalize, category
        def _norm(s):
            s = s.replace('ı','i').replace('ş','s').replace('ç','c').replace('ğ','g').replace('ø','o')
            s = ''.join(c for c in normalize('NFD', s.lower()) if category(c) != 'Mn')
            return s.rstrip("''\u2019'*.,;:").replace("'","").replace("*","")

        raw = raw_name.strip().rstrip(".,;:")
        parts = raw.split()
        if not parts:
            return None

        # "M. Thuram" -> initial + surname
        if len(parts) == 2 and len(parts[0]) <= 2 and parts[0].endswith("."):
            initial = parts[0][0].lower()
            surname = _norm(parts[1])
            if len(surname) < 3:
                return None
            if surname_count.get(surname, 0) > 1:
                for e in listone_entries:
                    if e["surname"] == surname and e["firstname"] and e["firstname"][0] == initial:
                        return surname + "_" + initial
            return surname

        # "E. Ferguson" style
        if len(parts) == 2 and len(parts[0]) == 2 and parts[0][1] == '.':
            initial = parts[0][0].lower()
            surname = _norm(parts[1])
            if len(surname) < 3:
                return None
            if surname_count.get(surname, 0) > 1:
                return surname + "_" + initial
            return surname

        # Single word
        word = _norm(parts[-1])
        if len(word) < 3:
            return None
        # Try as surname
        matches = [e for e in listone_entries if e["surname"] == word]
        if matches:
            return word
        # Try as firstname -> return "surname_firstinitial" for uniqueness
        for e in listone_entries:
            if e["firstname"] == word and len(word) > 3:
                return e["surname"] + "_" + word[0]
        return None

    TIERS = ["TOP", "SEMITOP", "SOTTO AI SEMITOP", "JOLLY PRIMA FASCIA", "JOLLY SECONDA FASCIA", "JOLLY TERZA FASCIA", "JOLLY QUARTA FASCIA", "FASCIA ALTA", "FASCIA MEDIA", "LOW COST PRIMA FASCIA", "LOW COST SECONDA FASCIA", "SOPRA AI LOW COST", "LEGHE NUMEROSE", "SCOMMESSE", "GIOVANI SCOMMESSE", "INFORTUNATI", "A RISCHIO", "DA EVITARE"]

    tags = {}

    for page_key in ["guida_asta_att", "guida_asta_cen", "guida_asta_dif", "guida_asta_por"]:
        content = sosfanta.get(page_key, {}).get("content", "")
        for line in content.split("\n"):
            # Match lines like "TOP - Name1, Name2, Name3"
            for t in TIERS:
                if line.startswith(t) and (" - " in line or " -" in line):
                    # Split on " - " or " -" (some lines miss the space after dash)
                    if " - " in line:
                        names_part = line.split(" - ", 1)[1]
                    else:
                        names_part = line.split(" -", 1)[1]
                    for name in names_part.split(","):
                        key = match_name(name)
                        if key and key not in tags:
                            tags[key] = [t]
                    break

    # Add RIG
    rig_content = sosfanta.get("rigoristi", {}).get("content", "")
    for line in rig_content.split("\n"):
        for word in line.split():
            w = word.rstrip(".,;:èéòàù")
            if len(w) > 3:
                key = match_name(w)
                if key:
                    tags.setdefault(key, [])
                    if "RIG" not in tags[key]:
                        tags[key].append("RIG")

    # Manual overrides for ambiguous names
    OVERRIDES = {
        "martinez_l": "TOP",  # Lautaro Martinez (att)
        "martinez_j": "JOLLY SECONDA FASCIA",  # Martinez Jo. (por)
        "ferguson_j": "SEMITOP",  # Joe Ferguson (att)
        "ferguson_l": "SOPRA AI LOW COST",  # Lewis Ferguson (cen)
    }
    for key, tier in OVERRIDES.items():
        tags[key] = [tier]

    return jsonify(tags)




@app.route("/api/svincolati")
def api_svincolati():
    """Get free agents (players not in any fantasy team). This is the main player list for auction."""
    from src.listone import load_listone
    from unicodedata import normalize, category
    from pathlib import Path
    listone = load_listone()

    def _simplify(s):
        s = s.replace('ı', 'i').replace('İ', 'i').replace('ş', 's').replace('ç', 'c').replace('ğ', 'g').replace('ø', 'o').replace('ü', 'u').replace('ö', 'o')
        s = ''.join(c for c in normalize('NFD', s.lower()) if category(c) != 'Mn')
        return s.rstrip("''\u2019'*").replace("'", "").replace("\u2019", "").replace("'", "").replace("*", "")

    # Load name mapping file if exists
    mapping = {}
    mapping_file = Path("data/mapping_nomi.csv")
    if mapping_file.exists():
        import csv
        with open(mapping_file) as f:
            for row in csv.DictReader(f):
                if row.get("db_nome"):
                    mapping[row["listone_nome"].lower()] = row["db_nome"]

    # Precompute DB lookup by simplified surname (highest FM wins for duplicates)
    db_sorted = db.sort_values("fantamedia", ascending=False)
    db_lookup = {}
    db_lookup_short = {}
    db_dupes = {}  # surname -> [all matching rows]
    for _, row_db in db_sorted.iterrows():
        key = _simplify(row_db["nome"].split()[0]) if row_db["nome"] else ""
        if key:
            db_dupes.setdefault(key, []).append(row_db)
            if key not in db_lookup:
                db_lookup[key] = row_db
            if len(key) >= 6 and key[:6] not in db_lookup_short:
                db_lookup_short[key[:6]] = row_db

    role = request.args.get("role")
    squadra = request.args.get("squadra")
    q = request.args.get("q", "").lower()

    result = []
    for _, row in listone.iterrows():
        if role and row["ruolo"] != role:
            continue
        if squadra:
            # Map full name to abbreviation for comparison
            sq_abbr = next((k for k,v in SQUAD_NAMES.items() if v.lower()==squadra.lower()), squadra)
            if row["squadra"].lower() != squadra.lower() and row["squadra"].upper() != sq_abbr.upper():
                continue
        if q and q not in row["nome"].lower():
            continue

        # Match by simplified surname + role for disambiguation
        mapped_name = mapping.get(row["nome"].lower())
        surname = _simplify(mapped_name.split()[0]) if mapped_name else _simplify(row["nome"].split()[0])
        matched = db_lookup.get(surname)

        # If multiple players with same surname, try to match by role too
        if matched is not None and surname in db_dupes:
            role_map = {"Por": "P", "D": "D", "C": "C", "A": "A"}
            listone_role = role_map.get(row["ruolo"], "")
            candidates = [r for r in db_dupes[surname] if r.get("ruolo") == listone_role]
            if candidates:
                matched = candidates[0]

        if matched is None and len(surname) >= 6:
            matched = db_lookup_short.get(surname[:6])
        mantra = ""
        fm = 0
        presenze = 0
        if matched is not None:
            mantra = matched.get("ruolo_mantra", "")
            fm = matched.get("fantamedia", 0)
            presenze = int(matched.get("presenze", 0))

        # Estimate FM from quotazione for new players
        import math
        is_nuovo = bool(fm == 0)
        fm_stimata = False
        if is_nuovo and row["quotazione"] >= 3:
            fm = round(0.28 * math.log(row["quotazione"] + 1) + 5.56, 2)
            fm_stimata = True

        result.append({
            "nome": row["nome"],
            "ruolo": row["ruolo"],
            "ruolo_mantra": mantra or row["ruolo"],
            "squadra": row["squadra"],
            "quotazione": int(row["quotazione"]),
            "fm": round(fm, 2),
            "presenze": presenze,
            "nuovo": is_nuovo,
            "fm_stimata": fm_stimata,
        })

    return jsonify(sorted(result, key=lambda x: x["quotazione"], reverse=True))


@app.route("/api/sosfanta/<key>")
def api_sosfanta_page(key):
    """Get a specific SOS Fanta page."""
    page = sosfanta.get(key)
    if not page:
        return jsonify({"error": "Page not found"}), 404
    return jsonify(page)


@app.route("/api/sosfanta/refresh", methods=["POST"])
def api_sosfanta_refresh():
    """Force re-scrape SOS Fanta pages."""
    global sosfanta
    from src.sosfanta import scrape_all_pages
    sosfanta = scrape_all_pages(force=True)
    return jsonify({"ok": True, "pages": len(sosfanta)})


@app.route("/api/sosfanta/update_url", methods=["POST"])
def api_sosfanta_update_url():
    """Update a SOS Fanta page URL (for new season links)."""
    data = request.get_json()
    key = data.get("key", "")
    url = data.get("url", "")
    title = data.get("title", "")
    if not key or not url:
        return jsonify({"error": "key e url richiesti"}), 400
    from src.sosfanta import update_url
    update_url(key, url, title)
    return jsonify({"ok": True, "key": key, "url": url})


@app.route("/api/sosfanta/scrape_url", methods=["POST"])
def api_sosfanta_scrape_url():
    """Scrape a custom URL provided by the user."""
    data = request.get_json()
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "URL mancante"}), 400
    try:
        import requests as req
        from bs4 import BeautifulSoup
        r = req.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        main = soup.select_one("main") or soup.select_one("article") or soup.select_one("body")
        for tag in main.find_all(["nav", "header", "footer", "script", "style"]):
            tag.decompose()
        paragraphs = []
        for el in main.find_all(["p", "h2", "h3", "li"]):
            text = el.get_text(strip=True)
            if len(text) > 15:
                if el.name in ("h2", "h3"):
                    paragraphs.append(f"\n**{text}**\n")
                else:
                    paragraphs.append(text)
        content = "\n\n".join(paragraphs)
        return jsonify({"content": content, "url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/league_teams")
def api_league_teams():
    """Get all fantasy teams and their rosters from the league."""
    return jsonify(league_teams)


@app.route("/api/upload_rose", methods=["POST"])
def api_upload_rose():
    """Upload a new Rose file (xlsx or csv)."""
    global league_teams, market_prices
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file"}), 400

    from pathlib import Path
    save_path = Path("data") / f.filename
    f.save(save_path)

    league_teams, market_prices = load_league_data()
    return jsonify({"ok": True, "teams": len(league_teams), "players": len(market_prices)})


@app.route("/api/listone")
def api_listone():
    """Get full player list with quotazioni."""
    from src.listone import load_listone
    df = load_listone()
    role = request.args.get("role")
    squadra = request.args.get("squadra")
    if role:
        df = df[df["ruolo"] == role]
    if squadra:
        df = df[df["squadra"].str.lower() == squadra.lower()]
    return jsonify(df.to_dict("records"))


@app.route("/api/upload_listone", methods=["POST"])
def api_upload_listone():
    """Upload a new listone CSV for next season."""
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file"}), 400

    from pathlib import Path
    # Save with season name
    filename = f.filename if f.filename.endswith(".csv") else "listone_upload.csv"
    save_path = Path("data") / filename
    f.save(save_path)
    return jsonify({"ok": True, "file": filename})



# --- Server-side persistence ---
import json as _json
_USER_DATA_FILE = Path("data/user_data.json")


@app.route("/api/userdata", methods=["GET"])
def api_userdata_load():
    """Load user data from server."""
    if _USER_DATA_FILE.exists():
        return app.response_class(_USER_DATA_FILE.read_text(encoding="utf-8"), mimetype="application/json")
    return jsonify({})


@app.route("/api/userdata", methods=["POST"])
def api_userdata_save():
    """Save user data to server."""
    data = request.get_json()
    _USER_DATA_FILE.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
