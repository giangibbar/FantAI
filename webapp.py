"""AiBet — Flask web app for Fantacalcio Mantra auction."""

from flask import Flask, render_template, request, jsonify
from src.valuation import load_db, valuate_player, get_top_players, search_players, suggest_alternative, should_buy
from src.league_roster import load_league_data

app = Flask(__name__, template_folder="templates", static_folder="static")
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

# Get all Serie A squads from listone (full names)
from src.listone import load_listone
_listone = load_listone()
squads = sorted(_listone["squadra"].unique().tolist())


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
    for _, row in listone.iterrows():
        parts = row["nome"].split()
        surname = parts[0].lower() if parts else ""
        firstname = parts[1].lower() if len(parts) >= 2 else ""
        surname_count[surname] = surname_count.get(surname, 0) + 1
        listone_entries.append({"surname": surname, "firstname": firstname})

    def match_name(raw_name):
        """Match SOS Fanta name to listone surname. Returns unique key."""
        raw = raw_name.strip().rstrip(".,;:")
        parts = raw.split()
        if not parts:
            return None

        # "M. Thuram" -> initial + surname
        if len(parts) == 2 and len(parts[0]) <= 2 and parts[0].endswith("."):
            initial = parts[0][0].lower()
            surname = parts[1].lower()
            if len(surname) < 3:
                return None
            if surname_count.get(surname, 0) > 1:
                for e in listone_entries:
                    if e["surname"] == surname and e["firstname"] and e["firstname"][0] == initial:
                        return surname + "_" + initial
            return surname

        # "E. Ferguson" style with initial
        if len(parts) == 2 and len(parts[0]) == 2 and parts[0][1] == '.':
            initial = parts[0][0].lower()
            surname = parts[1].lower()
            if len(surname) < 3:
                return None
            if surname_count.get(surname, 0) > 1:
                return surname + "_" + initial
            return surname

        # Single word - must be at least 3 chars
        word = parts[-1].lower()
        if len(word) < 3:
            return None
        # Try as surname (unique only)
        matches = [e for e in listone_entries if e["surname"] == word]
        if len(matches) == 1:
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
                if line.startswith(t) and " - " in line:
                    names_part = line.split(" - ", 1)[1]
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
        return s.rstrip("''\u2019'").replace("'", "").replace("\u2019", "").replace("'", "")

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
    db_sorted = db.sort_values(["stagione", "fantamedia"], ascending=[False, False])
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
        if squadra and row["squadra"].lower() != squadra.lower():
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
        if matched is not None:
            mantra = matched.get("ruolo_mantra", "")
            fm = matched.get("fantamedia", 0)

        result.append({
            "nome": row["nome"],
            "ruolo": row["ruolo"],
            "ruolo_mantra": mantra or row["ruolo"],
            "squadra": row["squadra"],
            "quotazione": int(row["quotazione"]),
            "fm": round(fm, 2),
            "nuovo": bool(fm == 0),
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
