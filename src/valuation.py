"""Player valuation engine for Fantacalcio Mantra auction."""

import pandas as pd
import numpy as np
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "fantacalcio" / "all_seasons.csv"
SEASON_WEIGHTS = {"2024-25": 0.40, "2023-24": 0.25, "2022-23": 0.15, "2021-22": 0.12, "2020-21": 0.08}

MANTRA_ROLES_ALL = ["Por", "Dc", "Dd", "Ds", "E", "M", "C", "W", "T", "Pc", "A", "B"]


def load_db() -> pd.DataFrame:
    if not DATA_PATH.exists():
        from src.fantacalcio import scrape_all_seasons
        scrape_all_seasons()
    return pd.read_csv(DATA_PATH)


def valuate_player(name: str, db: pd.DataFrame, sosfanta: dict = None, market_prices: dict = None) -> dict | None:
    """Full valuation for a player."""
    player_df = db[db["nome"].str.lower() == name.lower()]
    if player_df.empty:
        matches = db[db["nome"].str.lower().str.contains(name.lower(), na=False)]
        if matches.empty:
            return None
        player_df = matches[matches["nome"] == matches.iloc[0]["nome"]]

    name = player_df.iloc[0]["nome"]
    role = player_df.iloc[0]["ruolo"]
    team = player_df.sort_values("stagione", ascending=False).iloc[0]["squadra"]
    mantra_role = player_df.sort_values("stagione", ascending=False).iloc[0].get("ruolo_mantra", role)
    seasons = player_df.sort_values("stagione", ascending=False)

    # Projected fantamedia (weighted)
    fm_weighted = weight_sum = 0
    for _, row in seasons.iterrows():
        w = SEASON_WEIGHTS.get(row["stagione"], 0.05)
        if row["presenze"] >= 5:
            fm_weighted += row["fantamedia"] * w
            weight_sum += w
    projected_fm = fm_weighted / weight_sum if weight_sum > 0 else seasons.iloc[0]["fantamedia"]

    # Consistency
    fms = seasons[seasons["presenze"] >= 10]["fantamedia"].values
    consistency = 1 - min(np.std(fms), 2) / 2 if len(fms) >= 2 else 0.5

    # Injury risk
    avg_presenze = seasons["presenze"].mean()
    injury_risk = 1 - min(avg_presenze / 34, 1.0)

    avg_gol = seasons["gol"].mean()
    avg_assist = seasons["assist"].mean()

    # Titolare / Rigorista
    is_titolare = False
    is_rigorista = False

    # Titolare = played 25+ games in latest season (regular starter)
    latest = seasons.iloc[0] if not seasons.empty else None
    if latest is not None and latest.get("presenze", 0) >= 25:
        is_titolare = True

    # Also check SOS Fanta formazioni
    if sosfanta and not is_titolare:
        form_content = sosfanta.get("formazioni_tipo", {}).get("content", "")
        # Check surname
        if name.lower() in form_content.lower():
            is_titolare = True

    # Rigorista from SOS Fanta
    if sosfanta:
        rig_content = sosfanta.get("rigoristi", {}).get("content", "")
        if name.lower() in rig_content.lower():
            is_rigorista = True

    # Price: use market price if available, otherwise calculate
    market_price = market_prices.get(name.lower(), 0) if market_prices else 0

    base_prices = {"A": 22, "C": 14, "D": 7, "P": 4}
    base = base_prices.get(role, 10)
    fm_bonus = max(0, (projected_fm - 6.0)) * 18
    presence_factor = min(avg_presenze / 30, 1.0)
    titolare_bonus = 1.15 if is_titolare else 0.85
    rigorista_bonus = 1.2 if is_rigorista else 1.0
    calc_price = round((base + fm_bonus) * presence_factor * titolare_bonus * rigorista_bonus * (0.7 + consistency * 0.3))

    # Blend market price with calculated (market is more reliable if available)
    if market_price > 0:
        suggested_price = round(market_price * 0.6 + calc_price * 0.4)
    else:
        suggested_price = calc_price

    max_price = round(suggested_price * 1.3)

    return {
        "nome": name,
        "ruolo": role,
        "ruolo_mantra": mantra_role,
        "squadra": team,
        "fm_proiettata": round(projected_fm, 2),
        "consistenza": round(consistency * 100),
        "rischio_infortunio": round(injury_risk * 100),
        "media_presenze": round(avg_presenze, 1),
        "media_gol": round(avg_gol, 1),
        "media_assist": round(avg_assist, 1),
        "prezzo_suggerito": suggested_price,
        "prezzo_max": max_price,
        "prezzo_mercato": market_price,
        "titolare": is_titolare,
        "rigorista": is_rigorista,
        "stagioni": len(seasons),
        "storico": seasons[["stagione", "squadra", "presenze", "fantamedia", "gol", "assist"]].to_dict("records"),
    }


def get_top_players(db: pd.DataFrame, role: str = None, squadra: str = None, limit: int = 50, sosfanta: dict = None, market_prices: dict = None) -> list[dict]:
    """Top players by projected value. Filter by classic role or squadra."""
    active = db[db["stagione"] == "2024-25"]
    if role:
        active = active[active["ruolo"] == role.upper()]
    if squadra:
        active = active[active["squadra"].str.lower() == squadra.lower()]

    results = []
    for name in active["nome"].unique():
        val = valuate_player(name, db, sosfanta, market_prices)
        if val and val["media_presenze"] >= 8:
            results.append(val)

    return sorted(results, key=lambda x: x["fm_proiettata"], reverse=True)[:limit]


def search_players(query: str, db: pd.DataFrame, sosfanta: dict = None, market_prices: dict = None) -> list[dict]:
    """Search players by name."""
    matches = db[db["nome"].str.lower().str.contains(query.lower(), na=False)]
    names = matches.sort_values("stagione", ascending=False)["nome"].unique()[:20]
    return [v for name in names if (v := valuate_player(name, db, sosfanta, market_prices))]


def suggest_alternative(name: str, db: pd.DataFrame, sosfanta: dict = None, market_prices: dict = None) -> list[dict]:
    """Suggest alternatives if you missed a player."""
    target = valuate_player(name, db, sosfanta, market_prices)
    if not target:
        return []

    candidates = get_top_players(db, role=target["ruolo"], limit=100, sosfanta=sosfanta, market_prices=market_prices)
    alternatives = [p for p in candidates if p["nome"] != target["nome"] and p["prezzo_suggerito"] <= target["prezzo_suggerito"] and p["fm_proiettata"] >= target["fm_proiettata"] - 0.5]
    return sorted(alternatives, key=lambda x: x["fm_proiettata"], reverse=True)[:5]


def should_buy(name: str, price: int, my_team: list[dict], budget_left: int, db: pd.DataFrame, sosfanta: dict = None, market_prices: dict = None) -> dict:
    """Advise whether to buy a player at given price. Mantra rules: 28 players, 1Por+5dif+5off starters."""
    val = valuate_player(name, db, sosfanta, market_prices)
    if not val:
        return {"consiglio": "❓ Giocatore non trovato", "motivo": ""}

    players_left = 28 - len(my_team)
    if players_left <= 0:
        return {"consiglio": "🛑 ROSA PIENA", "motivo": "Hai già 28 giocatori.", "giocatore": val}

    if price > budget_left:
        return {"consiglio": "🛑 BUDGET INSUFFICIENTE", "motivo": f"Hai solo {budget_left} crediti.", "giocatore": val}

    # Smart budget check: need 1 credit per remaining player after this one
    min_remaining = players_left - 1
    max_spendable = budget_left - min_remaining
    avg_remaining = (budget_left - price) / max(players_left - 1, 1) if players_left > 1 else 0

    if price > max_spendable:
        return {"consiglio": "🛑 TROPPO", "motivo": f"Puoi spendere max {max_spendable} (ti servono {min_remaining}×1cr per i restanti {min_remaining} slot).", "giocatore": val}

    if price > val["prezzo_max"]:
        return {"consiglio": "🛑 NON PRENDERE", "motivo": f"Troppo caro. Vale max {val['prezzo_max']}, chiedono {price}.", "giocatore": val}

    if price <= val["prezzo_suggerito"] * 0.8:
        verdict = "🟢 AFFARE! PRENDI"
        motivo = f"Sotto il valore di {val['prezzo_suggerito'] - price} crediti. "
    elif price <= val["prezzo_suggerito"]:
        verdict = "🟢 PRENDI"
        motivo = f"Prezzo giusto (vale {val['prezzo_suggerito']}). "
    elif price <= val["prezzo_max"]:
        verdict = "🟡 VALUTA"
        motivo = f"Sopra il valore (vale {val['prezzo_suggerito']}, max {val['prezzo_max']}). "
    else:
        verdict = "🛑 LASCIA"
        motivo = f"Troppo caro (vale {val['prezzo_suggerito']}). "

    if val["titolare"]:
        motivo += "✅ Titolare. "
    if val["rigorista"]:
        motivo += "⚽ Rigorista! "
    if val["rischio_infortunio"] > 40:
        motivo += "🏥 Rischio infortuni. "
    if val["prezzo_mercato"] > 0:
        motivo += f"📊 Pagato {val['prezzo_mercato']} nella lega. "

    # Lineup suggestion (Mantra: 1 Por + 5 difensivi + 5 offensivi)
    motivo += suggest_lineup_position(val, my_team)

    return {"consiglio": verdict, "motivo": motivo, "giocatore": val}


def suggest_lineup_position(player: dict, my_team: list[dict]) -> str:
    """Mantra lineup: 1 Por + 5 difensivi (D) + 5 offensivi (C/A). 12 panchina."""
    role = player["ruolo"]

    # Classify by Mantra type
    # D = difensivo (Dc, Dd, Ds, B, E, M in mantra)
    # C, A = offensivo (C, T, W, A, Pc in mantra)
    # P = portiere
    dif_in_team = sorted([p.get("fm_proiettata", 0) for p in my_team if p.get("ruolo") == "D"], reverse=True)
    off_in_team = sorted([p.get("fm_proiettata", 0) for p in my_team if p.get("ruolo") in ("C", "A")], reverse=True)
    por_in_team = sorted([p.get("fm_proiettata", 0) for p in my_team if p.get("ruolo") == "P"], reverse=True)

    fm = player["fm_proiettata"]

    if role == "P":
        if not por_in_team or fm > por_in_team[0]:
            return "📋 TITOLARE (#1). "
        return "📋 Panchina (riserva). "
    elif role == "D":
        if len(dif_in_team) < 5:
            return f"📋 TITOLARE (hai {len(dif_in_team)}/5 difensivi). "
        if fm > dif_in_team[4]:
            return "📋 TITOLARE (entra nei top 5 difensivi). "
        return "📋 Panchina/Rotazione. "
    else:  # C or A
        if len(off_in_team) < 5:
            return f"📋 TITOLARE (hai {len(off_in_team)}/5 offensivi). "
        if fm > off_in_team[4]:
            return "📋 TITOLARE (entra nei top 5 offensivi). "
        return "📋 Panchina/Rotazione. "
