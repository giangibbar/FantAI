"""AiBet — Streamlit GUI."""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="AiBet", page_icon="⚽", layout="wide")

# --- Data loading (cached) ---
@st.cache_data(ttl=3600)
def load_data():
    from src.data import load_all_data
    from src.features import clean_matches, get_avg_odds
    from src.elo import compute_elo_ratings
    df = load_all_data()
    df = clean_matches(df)
    df = get_avg_odds(df)
    df = compute_elo_ratings(df)
    return df


@st.cache_data(ttl=3600)
def build_features(df, league):
    from src.features import build_dataset
    league_df = df[df["League"] == league]
    return build_dataset(league_df), league_df


@st.cache_resource
def train_cached_models(dataset_hash, dataset):
    from src.xgb_model import train_models
    return train_models(dataset)


# --- Sidebar ---
st.sidebar.title("⚽ AiBet")
LEAGUES = {"I1": "🇮🇹 Serie A", "E0": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League", "SP1": "🇪🇸 La Liga", "D1": "🇩🇪 Bundesliga", "F1": "🇫🇷 Ligue 1"}
page = st.sidebar.radio("", ["🔮 Prossimo Turno", "⚽ Fantacalcio", "📊 Stats & Ranking", "✍️ Match Preview", "📋 Schedina", "📈 Backtest"])
league = st.sidebar.selectbox("Lega", list(LEAGUES.keys()), format_func=lambda x: LEAGUES[x])

# Load data
with st.spinner("Caricamento dati..."):
    df = load_data()
    dataset, league_df = build_features(df, league)

if len(dataset) < 100:
    st.error("Dati insufficienti. Esegui `aibet download` prima.")
    st.stop()

models = train_cached_models(hash(dataset.to_json()), dataset)


# --- Pages ---
if page == "🔮 Prossimo Turno":
    st.title(f"🔮 Prossimo Turno — {LEAGUES[league]}")

    from src.elo import get_current_elos
    from src.features import weighted_form, head_to_head, home_away_strength
    from src.xgb_model import predict_match_xgb, FEATURE_COLS
    from src.next_match import fetch_upcoming_fixtures, _find_team

    elos = get_current_elos(league_df)

    # Fetch real upcoming fixtures
    fixtures_data = fetch_upcoming_fixtures(league)
    if not fixtures_data:
        st.warning("Nessuna partita in programma trovata per questa lega.")
        st.stop()

    predictions = []
    now = pd.Timestamp.now()

    for fix in fixtures_data:
        home = _find_team(fix["home"], league_df)
        away = _find_team(fix["away"], league_df)
        if not home or not away:
            continue

        hf = weighted_form(league_df, home, now)
        af = weighted_form(league_df, away, now)
        h2h = head_to_head(league_df, home, away, now)
        hs = home_away_strength(league_df, home, now)
        as_ = home_away_strength(league_df, away, now)

        odds_h = fix.get("odds_h", 0) or 0
        odds_d = fix.get("odds_d", 0) or 0
        odds_a = fix.get("odds_a", 0) or 0

        row = pd.Series({
            "elo_diff": elos.get(home, 1500) - elos.get(away, 1500),
            "home_elo": elos.get(home, 1500), "away_elo": elos.get(away, 1500),
            "home_form_pts": hf["form_pts"], "home_form_gs": hf["form_gs"],
            "home_form_gc": hf["form_gc"], "home_form_shots": hf["form_shots"],
            "home_form_sot": hf["form_sot"],
            "away_form_pts": af["form_pts"], "away_form_gs": af["form_gs"],
            "away_form_gc": af["form_gc"], "away_form_shots": af["form_shots"],
            "away_form_sot": af["form_sot"],
            "h2h_home_wins": h2h["h2h_home_wins"], "h2h_draws": h2h["h2h_draws"],
            "h2h_avg_goals": h2h["h2h_avg_goals"],
            "home_attack": hs["home_attack"], "home_defense": hs["home_defense"],
            "away_attack": as_["away_attack"], "away_defense": as_["away_defense"],
            "implied_home": 1.0/odds_h if odds_h > 1 else 0,
            "implied_draw": 1.0/odds_d if odds_d > 1 else 0,
            "implied_away": 1.0/odds_a if odds_a > 1 else 0,
        })

        preds = predict_match_xgb(models, row)
        probs_1x2 = {"1": preds["prob_home"], "X": preds["prob_draw"], "2": preds["prob_away"]}
        best = max(probs_1x2, key=probs_1x2.get)
        tips = []
        if probs_1x2[best] > 0.50:
            tips.append(best)
        if preds["prob_over25"] > 0.55:
            tips.append("O2.5")
        if preds["prob_btts_yes"] > 0.55:
            tips.append("BTTS")

        predictions.append({
            "Data": fix["date"],
            "Partita": f"{home} vs {away}",
            "1": f"{preds['prob_home']:.0%}", "X": f"{preds['prob_draw']:.0%}",
            "2": f"{preds['prob_away']:.0%}", "Over 2.5": f"{preds['prob_over25']:.0%}",
            "Entrambe segnano": f"{preds['prob_btts_yes']:.0%}",
            "Quota": f"{odds_h:.2f}/{odds_d:.2f}/{odds_a:.2f}" if odds_h else "-",
            "Suggerimento": " + ".join(tips) or "-",
        })

    if predictions:
        st.dataframe(pd.DataFrame(predictions), use_container_width=True, hide_index=True,
                     height=(len(predictions) + 1) * 35 + 3)
        st.caption("""
        **Legenda:** 1 = vittoria casa · X = pareggio · 2 = vittoria trasferta · 
        Over 2.5 = più di 2 gol totali · Entrambe segnano = entrambe fanno almeno 1 gol · 
        Quota = quote Bet365 (1/X/2) · Suggerimento = mercati dove il modello è più sicuro
        """)
    else:
        st.warning("Impossibile predire le partite (nomi squadre non trovati nei dati storici).")


elif page == "⚽ Fantacalcio":
    st.title(f"⚽ Fantacalcio Optimizer — {LEAGUES[league]}")
    st.markdown("Suggerisce i giocatori migliori da schierare in base a form, difficoltà avversario e gol attesi.")

    from src.elo import get_current_elos
    from src.features import weighted_form, home_away_strength

    elos = get_current_elos(league_df)
    teams = sorted(set(league_df["HomeTeam"].unique()) | set(league_df["AwayTeam"].unique()))

    # Compute team ratings
    now = pd.Timestamp.now()
    team_ratings = []
    for team in teams:
        form = weighted_form(league_df, team, now)
        if form["form_n"] < 3:
            continue
        elo = elos.get(team, 1500)
        team_ratings.append({
            "Squadra": team,
            "ELO": int(elo),
            "Form (pts/g)": round(form["form_pts"], 2),
            "Gol fatti/g": round(form["form_gs"], 2),
            "Gol subiti/g": round(form["form_gc"], 2),
            "Tiri/g": round(form["form_shots"], 1),
            "Attacco ⭐": round(form["form_gs"] * (2500 - elo) / 1000, 2),  # attack vs weak defense
            "Clean Sheet %": round(max(0, 1 - form["form_gc"]) * 100, 0),
        })

    ratings_df = pd.DataFrame(team_ratings)

    # Fantacalcio advice
    st.subheader("🎯 Chi schierare questa giornata")

    # Best attacks (schiera attaccanti di queste squadre)
    st.markdown("**Attaccanti da schierare** (squadre in forma offensiva vs difese deboli):")
    attack_df = ratings_df.sort_values("Attacco ⭐", ascending=False).head(5)
    st.dataframe(attack_df[["Squadra", "Gol fatti/g", "Form (pts/g)", "Attacco ⭐"]], hide_index=True)

    # Best defenses (schiera difensori/portieri di queste squadre)
    st.markdown("**Difensori/Portieri da schierare** (squadre che subiscono meno):")
    defense_df = ratings_df.sort_values("Gol subiti/g").head(5)
    st.dataframe(defense_df[["Squadra", "Gol subiti/g", "Clean Sheet %", "ELO"]], hide_index=True)

    # Avoid these
    st.markdown("**Da evitare** (squadre in crisi):")
    avoid_df = ratings_df.sort_values("Form (pts/g)").head(5)
    st.dataframe(avoid_df[["Squadra", "Form (pts/g)", "Gol subiti/g", "ELO"]], hide_index=True)

    # Full ranking
    with st.expander("📋 Ranking completo"):
        st.dataframe(ratings_df.sort_values("ELO", ascending=False), hide_index=True, use_container_width=True)


elif page == "📊 Stats & Ranking":
    st.title(f"📊 Stats & Ranking — {LEAGUES[league]}")

    from src.elo import get_current_elos
    from src.features import weighted_form, home_away_strength

    elos = get_current_elos(league_df)
    teams = sorted(set(league_df["HomeTeam"].unique()) | set(league_df["AwayTeam"].unique()))
    now = pd.Timestamp.now()

    # --- ELO Ranking ---
    st.subheader("🏆 Classifica ELO")
    elo_data = [{"Squadra": t, "ELO": int(elos.get(t, 1500))} for t in teams]
    elo_df = pd.DataFrame(elo_data).sort_values("ELO", ascending=False).reset_index(drop=True)
    elo_df.index += 1
    elo_df.index.name = "#"

    fig = px.bar(elo_df.head(20), x="Squadra", y="ELO", color="ELO",
                 color_continuous_scale="RdYlGn", title="Top 20 ELO Rating")
    fig.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)

    # --- Form chart ---
    st.subheader("📈 Form recente (ultimi 10 match)")
    form_data = []
    for team in teams:
        f = weighted_form(league_df, team, now)
        if f["form_n"] >= 3:
            form_data.append({"Squadra": team, "Punti/g": round(f["form_pts"], 2),
                              "Gol fatti/g": round(f["form_gs"], 2), "Gol subiti/g": round(f["form_gc"], 2)})

    form_df = pd.DataFrame(form_data).sort_values("Punti/g", ascending=False)
    fig2 = px.bar(form_df.head(20), x="Squadra", y=["Gol fatti/g", "Gol subiti/g"],
                  barmode="group", title="Gol fatti vs subiti (media pesata)",
                  color_discrete_map={"Gol fatti/g": "#2ecc71", "Gol subiti/g": "#e74c3c"})
    fig2.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig2, use_container_width=True)

    # --- Head to Head ---
    st.subheader("⚔️ Head-to-Head")
    from src.features import head_to_head

    col1, col2 = st.columns(2)
    t1 = col1.selectbox("Squadra 1", teams, index=0)
    t2 = col2.selectbox("Squadra 2", [t for t in teams if t != t1], index=0)

    h2h = head_to_head(league_df, t1, t2, now, n=20)
    if h2h["h2h_n"] > 0:
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Vittorie {t1}", f"{h2h['h2h_home_wins']:.0%}")
        c2.metric("Pareggi", f"{h2h['h2h_draws']:.0%}")
        c3.metric(f"Vittorie {t2}", f"{h2h['h2h_away_wins']:.0%}")
        st.metric("Media gol negli scontri diretti", f"{h2h['h2h_avg_goals']:.1f}")
    else:
        st.info("Nessuno scontro diretto trovato nei dati.")

    # --- League stats ---
    st.subheader("📊 Statistiche lega")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Partite", len(league_df))
    col2.metric("Gol/partita", f"{league_df['TotalGoals'].mean():.2f}")
    col3.metric("Over 2.5", f"{league_df['Over25'].mean():.0%}")
    col4.metric("BTTS", f"{league_df['BTTS'].mean():.0%}")


elif page == "✍️ Match Preview":
    st.title(f"✍️ Match Preview Generator — {LEAGUES[league]}")
    st.markdown("Genera automaticamente testi di anteprima per le prossime partite.")

    from src.elo import get_current_elos
    from src.features import weighted_form, head_to_head, home_away_strength
    from src.xgb_model import predict_match_xgb
    from src.next_match import fetch_upcoming_fixtures, _find_team

    elos = get_current_elos(league_df)
    now = pd.Timestamp.now()

    fixtures = fetch_upcoming_fixtures(league)
    if not fixtures:
        st.warning("Nessuna partita in programma.")
        st.stop()

    for fix in fixtures:
        home = _find_team(fix["home"], league_df)
        away = _find_team(fix["away"], league_df)
        if not home or not away:
            continue

        hf = weighted_form(league_df, home, now)
        af = weighted_form(league_df, away, now)
        h2h = head_to_head(league_df, home, away, now)
        hs = home_away_strength(league_df, home, now)
        as_ = home_away_strength(league_df, away, now)

        home_elo = elos.get(home, 1500)
        away_elo = elos.get(away, 1500)

        row = pd.Series({
            "elo_diff": home_elo - away_elo,
            "home_elo": home_elo, "away_elo": away_elo,
            "home_form_pts": hf["form_pts"], "home_form_gs": hf["form_gs"],
            "home_form_gc": hf["form_gc"], "home_form_shots": hf["form_shots"],
            "home_form_sot": hf["form_sot"],
            "away_form_pts": af["form_pts"], "away_form_gs": af["form_gs"],
            "away_form_gc": af["form_gc"], "away_form_shots": af["form_shots"],
            "away_form_sot": af["form_sot"],
            "h2h_home_wins": h2h["h2h_home_wins"], "h2h_draws": h2h["h2h_draws"],
            "h2h_avg_goals": h2h["h2h_avg_goals"],
            "home_attack": hs["home_attack"], "home_defense": hs["home_defense"],
            "away_attack": as_["away_attack"], "away_defense": as_["away_defense"],
            "implied_home": 0, "implied_draw": 0, "implied_away": 0,
        })

        preds = predict_match_xgb(models, row)

        # Generate preview text
        home_form_txt = "ottima" if hf["form_pts"] > 2.2 else "buona" if hf["form_pts"] > 1.5 else "mediocre" if hf["form_pts"] > 1.0 else "pessima"
        away_form_txt = "ottima" if af["form_pts"] > 2.2 else "buona" if af["form_pts"] > 1.5 else "mediocre" if af["form_pts"] > 1.0 else "pessima"

        favorite = home if preds["prob_home"] > preds["prob_away"] else away
        fav_prob = max(preds["prob_home"], preds["prob_away"])

        preview = f"""**{home} vs {away}** — {fix['date']}

{home} arriva a questa sfida in forma {home_form_txt} (media {hf['form_pts']:.1f} punti/partita, {hf['form_gs']:.1f} gol fatti). """

        if home_elo > away_elo + 50:
            preview += f"I padroni di casa partono favoriti con un rating ELO superiore ({int(home_elo)} vs {int(away_elo)}). "
        elif away_elo > home_elo + 50:
            preview += f"Nonostante il fattore campo, {away} ha un rating ELO superiore ({int(away_elo)} vs {int(home_elo)}). "

        preview += f"{away} è in forma {away_form_txt} ({af['form_pts']:.1f} punti/partita, {af['form_gs']:.1f} gol fatti, {af['form_gc']:.1f} subiti).\n\n"

        if h2h["h2h_n"] >= 3:
            preview += f"Negli ultimi scontri diretti: {h2h['h2h_home_wins']:.0%} vittorie {home}, {h2h['h2h_draws']:.0%} pareggi, {h2h['h2h_away_wins']:.0%} vittorie {away} (media {h2h['h2h_avg_goals']:.1f} gol).\n\n"

        preview += f"**Pronostico:** {favorite} favorita al {fav_prob:.0%}. "
        if preds["prob_over25"] > 0.55:
            preview += f"Partita che si preannuncia ricca di gol (Over 2.5 al {preds['prob_over25']:.0%}). "
        else:
            preview += f"Partita che potrebbe essere bloccata (Under 2.5 al {preds['prob_under25']:.0%}). "
        if preds["prob_btts_yes"] > 0.55:
            preview += "Entrambe le squadre dovrebbero andare a segno."

        with st.expander(f"📝 {home} vs {away} — {fix['date']}", expanded=True):
            st.markdown(preview)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("1", f"{preds['prob_home']:.0%}")
            c2.metric("X", f"{preds['prob_draw']:.0%}")
            c3.metric("2", f"{preds['prob_away']:.0%}")
            c4.metric("O2.5", f"{preds['prob_over25']:.0%}")


elif page == "📋 Schedina":
    st.title(f"📋 Schedina — {LEAGUES[league]}")

    min_value = st.slider("Soglia Value minima", 0.05, 0.30, 0.10, 0.01)

    from src.features import compute_team_stats
    from src.model import predict_match, find_value_bets

    stats = compute_team_stats(league_df)
    avg_home = league_df["FTHG"].mean()
    avg_away = league_df["FTAG"].mean()

    last_date = league_df["Date"].max()
    last_matches = league_df[league_df["Date"] == last_date]

    all_bets = []
    for _, row in last_matches.iterrows():
        h = stats[stats["Team"] == row["HomeTeam"]]
        a = stats[stats["Team"] == row["AwayTeam"]]
        if h.empty or a.empty:
            continue

        pred = predict_match(
            h.iloc[0]["AttackStrength"], h.iloc[0]["DefenseStrength"],
            a.iloc[0]["AttackStrength"], a.iloc[0]["DefenseStrength"],
            avg_home, avg_away, row["HomeTeam"], row["AwayTeam"],
        )

        odds_h = row.get("AvgOddsH", row.get("B365H", 0))
        odds_d = row.get("AvgOddsD", row.get("B365D", 0))
        odds_a = row.get("AvgOddsA", row.get("B365A", 0))

        if odds_h and odds_d and odds_a:
            bets = find_value_bets(pred, odds_h, odds_d, odds_a, min_value=min_value)
            all_bets.extend(bets)

    if all_bets:
        bets_df = pd.DataFrame(all_bets).sort_values("value", ascending=False).head(10)
        st.dataframe(bets_df, use_container_width=True, hide_index=True)
    else:
        st.warning("Nessuna value bet trovata con questa soglia.")


elif page == "📈 Backtest":
    st.title("📈 Backtest Results")
    st.info("Il backtest completo richiede ~2 minuti. Usa la CLI per risultati dettagliati: `aibet backtest`")

    # Show historical stats
    st.subheader(f"Statistiche storiche — {LEAGUES[league]}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Partite totali", len(league_df))
    col2.metric("Media gol/partita", f"{league_df['TotalGoals'].mean():.2f}")
    col3.metric("% Over 2.5", f"{league_df['Over25'].mean():.0%}")

    # Goals distribution
    fig = px.histogram(league_df, x="TotalGoals", nbins=8, title="Distribuzione gol per partita",
                       color_discrete_sequence=["#2ecc71"])
    fig.update_layout(xaxis_title="Gol totali", yaxis_title="Frequenza")
    st.plotly_chart(fig, use_container_width=True)

    # Home/Away/Draw distribution
    results = league_df["FTR"].value_counts()
    fig2 = px.pie(values=results.values, names=["Casa (H)", "Pareggio (D)", "Trasferta (A)"],
                  title="Distribuzione risultati", color_discrete_sequence=["#2ecc71", "#f39c12", "#e74c3c"])
    st.plotly_chart(fig2, use_container_width=True)
