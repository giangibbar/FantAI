"""Backtest engine: simulate betting on historical data and track performance."""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class Bet:
    """A single bet placed."""
    date: pd.Timestamp
    match: str
    tip: str
    odds: float
    stake: float
    model_prob: float
    won: bool
    profit: float


@dataclass
class BacktestResult:
    """Results of a backtest run."""
    bets: list[Bet] = field(default_factory=list)
    initial_bankroll: float = 1000.0

    @property
    def total_bets(self) -> int:
        return len(self.bets)

    @property
    def wins(self) -> int:
        return sum(1 for b in self.bets if b.won)

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_bets if self.total_bets else 0

    @property
    def total_staked(self) -> float:
        return sum(b.stake for b in self.bets)

    @property
    def total_profit(self) -> float:
        return sum(b.profit for b in self.bets)

    @property
    def roi(self) -> float:
        """Return on investment (profit / initial bankroll)."""
        return self.total_profit / self.initial_bankroll if self.initial_bankroll else 0

    @property
    def yield_pct(self) -> float:
        """Yield = profit / total staked."""
        return self.total_profit / self.total_staked if self.total_staked else 0

    @property
    def max_drawdown(self) -> float:
        """Maximum drawdown from peak bankroll."""
        if not self.bets:
            return 0
        cumulative = np.cumsum([b.profit for b in self.bets])
        bankroll = self.initial_bankroll + cumulative
        peak = np.maximum.accumulate(bankroll)
        drawdown = (peak - bankroll) / peak
        return float(drawdown.max())

    @property
    def longest_losing_streak(self) -> int:
        streak = max_streak = 0
        for b in self.bets:
            if not b.won:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        return max_streak

    @property
    def final_bankroll(self) -> float:
        return self.initial_bankroll + self.total_profit

    @property
    def avg_odds(self) -> float:
        return np.mean([b.odds for b in self.bets]) if self.bets else 0

    def monthly_breakdown(self) -> pd.DataFrame:
        """Monthly P&L breakdown."""
        if not self.bets:
            return pd.DataFrame()
        df = pd.DataFrame([{"date": b.date, "profit": b.profit, "won": b.won} for b in self.bets])
        df["month"] = df["date"].dt.to_period("M")
        monthly = df.groupby("month").agg(
            bets=("profit", "count"),
            wins=("won", "sum"),
            profit=("profit", "sum"),
        ).reset_index()
        monthly["cumulative"] = monthly["profit"].cumsum()
        return monthly


def run_backtest(
    predictions: pd.DataFrame,
    min_value: float = 0.05,
    stake_mode: str = "flat",
    flat_stake: float = 10.0,
    kelly_fraction: float = 0.25,
    bankroll: float = 1000.0,
    max_odds: float = 8.0,
    min_odds: float = 1.20,
) -> BacktestResult:
    """Run backtest on predictions DataFrame.

    predictions must have columns:
        date, home_team, away_team, result (0=H, 1=D, 2=A),
        prob_home, prob_draw, prob_away, prob_over25,
        odds_h, odds_d, odds_a, (optional: odds_over25)
    """
    result = BacktestResult(initial_bankroll=bankroll)
    current_bankroll = bankroll

    for _, row in predictions.iterrows():
        if current_bankroll <= 0:
            break

        markets = []

        # 1X2 markets
        for tip, prob_col, odds_col, actual in [
            ("1", "prob_home", "odds_h", 0),
            ("X", "prob_draw", "odds_d", 1),
            ("2", "prob_away", "odds_a", 2),
        ]:
            prob = row.get(prob_col, 0)
            odds = row.get(odds_col, 0)

            if not odds or odds < min_odds or odds > max_odds or not prob:
                continue

            implied = 1.0 / odds
            value = prob - implied

            if value >= min_value:
                markets.append({
                    "tip": tip,
                    "prob": prob,
                    "odds": odds,
                    "value": value,
                    "won": row["result"] == actual,
                })

        # Over 2.5
        if "prob_over25" in row:
            prob = row.get("prob_over25", 0)
            odds = row.get("odds_over25", 0) or row.get("odds_o25", 0)
            if odds and odds >= min_odds and odds <= max_odds and prob:
                implied = 1.0 / odds
                value = prob - implied
                if value >= min_value:
                    markets.append({
                        "tip": "O2.5",
                        "prob": prob,
                        "odds": odds,
                        "value": value,
                        "won": row.get("total_goals", 0) > 2.5,
                    })

        # Under 2.5
        if "prob_under25" in row:
            prob = row.get("prob_under25", 0)
            odds = row.get("odds_under25", 0) or row.get("odds_u25", 0)
            if odds and odds >= min_odds and odds <= max_odds and prob:
                implied = 1.0 / odds
                value = prob - implied
                if value >= min_value:
                    markets.append({
                        "tip": "U2.5",
                        "prob": prob,
                        "odds": odds,
                        "value": value,
                        "won": row.get("total_goals", 0) <= 2.5,
                    })

        # BTTS Yes
        if "prob_btts_yes" in row:
            prob = row.get("prob_btts_yes", 0)
            odds = row.get("odds_btts_yes", 0)
            if odds and odds >= min_odds and odds <= max_odds and prob:
                implied = 1.0 / odds
                value = prob - implied
                if value >= min_value:
                    markets.append({
                        "tip": "BTTS",
                        "prob": prob,
                        "odds": odds,
                        "value": value,
                        "won": bool(row.get("btts", 0)),
                    })

        # BTTS No
        if "prob_btts_no" in row:
            prob = row.get("prob_btts_no", 0)
            odds = row.get("odds_btts_no", 0)
            if odds and odds >= min_odds and odds <= max_odds and prob:
                implied = 1.0 / odds
                value = prob - implied
                if value >= min_value:
                    markets.append({
                        "tip": "noBTTS",
                        "prob": prob,
                        "odds": odds,
                        "value": value,
                        "won": not bool(row.get("btts", 0)),
                    })

        # Place best value bet per match (avoid correlated bets)
        if not markets:
            continue

        best = max(markets, key=lambda x: x["value"])

        # Stake calculation
        if stake_mode == "kelly":
            # Kelly criterion: f = (bp - q) / b where b = odds - 1
            b = best["odds"] - 1
            p = best["prob"]
            q = 1 - p
            kelly = (b * p - q) / b
            stake = max(0, min(kelly * kelly_fraction * current_bankroll, current_bankroll * 0.05))
        else:
            stake = min(flat_stake, current_bankroll)

        if stake < 1.0:
            continue

        profit = (best["odds"] - 1) * stake if best["won"] else -stake
        current_bankroll += profit

        result.bets.append(Bet(
            date=row["date"],
            match=f"{row['home_team']} vs {row['away_team']}",
            tip=best["tip"],
            odds=best["odds"],
            stake=round(stake, 2),
            model_prob=best["prob"],
            won=best["won"],
            profit=round(profit, 2),
        ))

    return result


def print_backtest_report(result: BacktestResult) -> None:
    """Print formatted backtest report."""
    console.print("\n[bold]═══ BACKTEST REPORT ═══[/bold]\n")

    table = Table(title="Performance Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Total Bets", str(result.total_bets))
    table.add_row("Wins / Losses", f"{result.wins} / {result.total_bets - result.wins}")
    table.add_row("Win Rate", f"{result.win_rate:.1%}")
    table.add_row("Avg Odds", f"{result.avg_odds:.2f}")
    table.add_row("", "")
    table.add_row("Total Staked", f"€{result.total_staked:.0f}")
    table.add_row("Total Profit", f"€{result.total_profit:+.0f}")
    table.add_row("ROI", f"{result.roi:+.1%}")
    table.add_row("Yield", f"{result.yield_pct:+.1%}")
    table.add_row("", "")
    table.add_row("Initial Bankroll", f"€{result.initial_bankroll:.0f}")
    table.add_row("Final Bankroll", f"€{result.final_bankroll:.0f}")
    table.add_row("Max Drawdown", f"{result.max_drawdown:.1%}")
    table.add_row("Longest Losing Streak", str(result.longest_losing_streak))

    console.print(table)

    # Monthly breakdown
    monthly = result.monthly_breakdown()
    if not monthly.empty:
        console.print("\n[bold]Monthly P&L:[/bold]")
        mtable = Table()
        mtable.add_column("Month")
        mtable.add_column("Bets")
        mtable.add_column("Wins")
        mtable.add_column("Profit")
        mtable.add_column("Cumulative")

        for _, m in monthly.iterrows():
            profit_style = "green" if m["profit"] >= 0 else "red"
            mtable.add_row(
                str(m["month"]),
                str(int(m["bets"])),
                str(int(m["wins"])),
                f"[{profit_style}]€{m['profit']:+.0f}[/{profit_style}]",
                f"€{m['cumulative']:+.0f}",
            )

        console.print(mtable)
