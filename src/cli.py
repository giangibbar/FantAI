"""CLI for AiBet — football prediction system."""

import sys
from rich.console import Console
from rich.table import Table

from src.data import download_all, load_all_data
from src.features import clean_matches, compute_team_stats, get_avg_odds
from src.model import predict_match, find_value_bets

console = Console()


def cmd_download():
    """Download historical data."""
    console.print("[bold]Downloading historical data...[/bold]")
    download_all()


def cmd_predict(home: str, away: str, league: str = "I1"):
    """Predict a single match."""
    df = load_all_data()
    if df.empty:
        console.print("[red]No data. Run: aibet download[/red]")
        return

    df = clean_matches(df)
    league_df = df[df["League"] == league]

    if league_df.empty:
        console.print(f"[red]No data for league {league}[/red]")
        return

    stats = compute_team_stats(league_df)
    avg_home = league_df["FTHG"].mean()
    avg_away = league_df["FTAG"].mean()

    home_stats = stats[stats["Team"] == home]
    away_stats = stats[stats["Team"] == away]

    if home_stats.empty or away_stats.empty:
        console.print(f"[red]Team not found. Available: {sorted(stats['Team'].unique())}[/red]")
        return

    h = home_stats.iloc[0]
    a = away_stats.iloc[0]

    pred = predict_match(
        home_attack=h["AttackStrength"],
        home_defense=h["DefenseStrength"],
        away_attack=a["AttackStrength"],
        away_defense=a["DefenseStrength"],
        league_avg_home=avg_home,
        league_avg_away=avg_away,
        home_team=home,
        away_team=away,
    )

    # Display
    table = Table(title=f"🎯 {home} vs {away}")
    table.add_column("Market", style="bold")
    table.add_column("Probability")
    table.add_column("Fair Odds")

    table.add_row("1 (Home)", f"{pred.prob_home:.1%}", f"{1/pred.prob_home:.2f}")
    table.add_row("X (Draw)", f"{pred.prob_draw:.1%}", f"{1/pred.prob_draw:.2f}")
    table.add_row("2 (Away)", f"{pred.prob_away:.1%}", f"{1/pred.prob_away:.2f}")
    table.add_row("Over 2.5", f"{pred.prob_over25:.1%}", f"{1/pred.prob_over25:.2f}")
    table.add_row("Under 2.5", f"{pred.prob_under25:.1%}", f"{1/pred.prob_under25:.2f}")

    console.print(table)
    console.print(f"Expected score: [bold]{pred.exp_home_goals} - {pred.exp_away_goals}[/bold]")


def cmd_schedina(league: str = "I1", min_value: float = 0.05):
    """Generate schedina with value bets from latest odds."""
    df = load_all_data()
    if df.empty:
        console.print("[red]No data. Run: aibet download[/red]")
        return

    df = clean_matches(df)
    df = get_avg_odds(df)
    league_df = df[df["League"] == league]

    stats = compute_team_stats(league_df)
    avg_home = league_df["FTHG"].mean()
    avg_away = league_df["FTAG"].mean()

    # Use last matchday as "upcoming" simulation
    last_date = league_df["Date"].max()
    last_matches = league_df[league_df["Date"] == last_date]

    all_bets = []

    for _, row in last_matches.iterrows():
        home, away = row["HomeTeam"], row["AwayTeam"]
        h = stats[stats["Team"] == home]
        a = stats[stats["Team"] == away]

        if h.empty or a.empty:
            continue

        pred = predict_match(
            home_attack=h.iloc[0]["AttackStrength"],
            home_defense=h.iloc[0]["DefenseStrength"],
            away_attack=a.iloc[0]["AttackStrength"],
            away_defense=a.iloc[0]["DefenseStrength"],
            league_avg_home=avg_home,
            league_avg_away=avg_away,
            home_team=home,
            away_team=away,
        )

        odds_h = row.get("AvgOddsH", 0)
        odds_d = row.get("AvgOddsD", 0)
        odds_a = row.get("AvgOddsA", 0)

        if odds_h and odds_d and odds_a:
            bets = find_value_bets(pred, odds_h, odds_d, odds_a, min_value=min_value)
            all_bets.extend(bets)

    if not all_bets:
        console.print("[yellow]No value bets found with current threshold.[/yellow]")
        return

    table = Table(title=f"📋 SCHEDINA — {league} (value > {min_value:.0%})")
    table.add_column("Match")
    table.add_column("Tip", style="bold cyan")
    table.add_column("Odds")
    table.add_column("Model Prob")
    table.add_column("Value", style="green")
    table.add_column("Conf")

    for bet in sorted(all_bets, key=lambda x: x["value"], reverse=True)[:10]:
        table.add_row(
            bet["match"], bet["tip"], f"{bet['odds']:.2f}",
            bet["model_prob"], bet["value"], bet["confidence"],
        )

    console.print(table)


def main():
    """Entry point."""
    args = sys.argv[1:]

    if not args or args[0] == "help":
        console.print("[bold]AiBet[/bold] — Football prediction system")
        console.print("  [cyan]download[/cyan]              Download historical data")
        console.print("  [cyan]predict HOME AWAY[/cyan]     Predict a match (add LEAGUE code)")
        console.print("  [cyan]schedina[/cyan]              Generate value bet schedina")
        console.print("  [cyan]backtest[/cyan]              Run walk-forward backtest with XGBoost")
        console.print("  [cyan]optimize[/cyan]              Test multiple configs to find best params")
        console.print("  [cyan]next LEAGUE[/cyan]           Predict next matchday (I1, E0, SP1, D1, F1)")
        console.print("  [cyan]teams LEAGUE[/cyan]          List available teams")
        return

    cmd = args[0]

    if cmd == "download":
        cmd_download()
    elif cmd == "predict" and len(args) >= 3:
        league = args[3] if len(args) > 3 else "I1"
        cmd_predict(args[1], args[2], league)
    elif cmd == "schedina":
        league = args[1] if len(args) > 1 else "I1"
        cmd_schedina(league)
    elif cmd == "backtest":
        from src.xgb_model import run_full_pipeline
        leagues = [args[1]] if len(args) > 1 else None
        min_val = float(args[2]) if len(args) > 2 else 0.10
        run_full_pipeline(leagues=leagues, min_value=min_val)
    elif cmd == "optimize":
        from src.xgb_model import run_full_pipeline
        leagues = [args[1]] if len(args) > 1 else None
        run_full_pipeline(leagues=leagues, optimize=True)
    elif cmd == "next":
        from src.next_match import predict_next_matchday
        league = args[1] if len(args) > 1 else "I1"
        predict_next_matchday(league)
    elif cmd == "teams":
        league = args[1] if len(args) > 1 else "I1"
        df = load_all_data()
        df = clean_matches(df)
        teams = sorted(df[df["League"] == league]["HomeTeam"].unique())
        console.print(f"[bold]Teams in {league}:[/bold]")
        for t in teams:
            console.print(f"  {t}")
    else:
        console.print("[red]Unknown command. Run 'aibet help'[/red]")


if __name__ == "__main__":
    main()
