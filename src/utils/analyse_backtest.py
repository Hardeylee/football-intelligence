"""
Deeper analysis of backtest results.
Filters value bets by additional criteria to find stronger signals.
"""

import json
import csv
from collections import defaultdict

BACKTEST_FILE = "data/backtest_results.json"
TRAIN_FILES = ["data/raw/22-23.csv", "data/raw/23-24.csv"]


def load_team_over25_rates() -> dict:
    """Load each team's over 2.5 rate from training data."""
    stats = defaultdict(lambda: {"matches": 0, "over25": 0})

    for filepath in TRAIN_FILES:
        with open(filepath, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                home = row.get("HomeTeam", "")
                away = row.get("AwayTeam", "")
                try:
                    hg = int(float(row.get("FTHG", 0) or 0))
                    ag = int(float(row.get("FTAG", 0) or 0))
                except:
                    continue

                for team in [home, away]:
                    stats[team]["matches"] += 1
                    if hg + ag > 2.5:
                        stats[team]["over25"] += 1

    return {
        team: round(s["over25"] / s["matches"], 3)
        for team, s in stats.items()
        if s["matches"] >= 10
    }


def analyse():
    with open(BACKTEST_FILE) as f:
        data = json.load(f)

    rates = load_team_over25_rates()

    print("=" * 70)
    print("OVER 2.5 DEEP ANALYSIS")
    print("=" * 70)

    # Filter 1: Both teams over 2.5 rate > 55%
    print("\n📊 FILTER: Both teams over 2.5 rate > 55% (from training data)")
    print(f"{'Date':<12} {'Match':<35} {'H.Rate':>7} {'A.Rate':>7} {'Result':>8} {'Profit':>10}")
    print("-" * 80)

    f1_wins = f1_losses = f1_profit = 0
    for m in data["matches"]:
        market = m["markets"].get("over25", {})
        if not market.get("is_value"):
            continue

        home_rate = rates.get(m["home"], 0)
        away_rate = rates.get(m["away"], 0)

        if home_rate > 0.55 and away_rate > 0.55:
            result = "WIN" if market["correct"] else "LOSS"
            profit = market["profit"] or 0
            f1_profit += profit
            if market["correct"]:
                f1_wins += 1
            else:
                f1_losses += 1
            print(
                f"{m['date']:<12} {m['home']+' vs '+m['away']:<35} "
                f"{home_rate:>7.1%} {away_rate:>7.1%} "
                f"{result:>8} N{profit:>8,.0f}"
            )

    f1_total = f1_wins + f1_losses
    if f1_total:
        print(f"\n  Results: {f1_wins}W {f1_losses}L | "
              f"Accuracy: {f1_wins/f1_total:.1%} | "
              f"Profit: N{f1_profit:,.0f} | "
              f"ROI: {f1_profit/(f1_total*1000)*100:.1f}%")

    # Filter 2: Edge > 12%
    print("\n\n📊 FILTER: Edge > 12% only")
    print(f"{'Date':<12} {'Match':<35} {'Edge':>6} {'Odds':>6} {'Result':>8} {'Profit':>10}")
    print("-" * 80)

    f2_wins = f2_losses = f2_profit = 0
    for m in data["matches"]:
        market = m["markets"].get("over25", {})
        if not market.get("is_value"):
            continue
        if market.get("edge", 0) > 0.12:
            result = "WIN" if market["correct"] else "LOSS"
            profit = market["profit"] or 0
            f2_profit += profit
            if market["correct"]:
                f2_wins += 1
            else:
                f2_losses += 1
            print(
                f"{m['date']:<12} {m['home']+' vs '+m['away']:<35} "
                f"{market['edge']:>6.1%} {market['odds']:>6.2f} "
                f"{result:>8} N{profit:>8,.0f}"
            )

    f2_total = f2_wins + f2_losses
    if f2_total:
        print(f"\n  Results: {f2_wins}W {f2_losses}L | "
              f"Accuracy: {f2_wins/f2_total:.1%} | "
              f"Profit: N{f2_profit:,.0f} | "
              f"ROI: {f2_profit/(f2_total*1000)*100:.1f}%")

    # Filter 3: Both teams over 2.5 > 55% AND edge > 10%
    print("\n\n📊 FILTER: Both teams over 2.5 > 55% AND edge > 10%")
    print(f"{'Date':<12} {'Match':<35} {'Edge':>6} {'Result':>8} {'Profit':>10}")
    print("-" * 75)

    f3_wins = f3_losses = f3_profit = 0
    for m in data["matches"]:
        market = m["markets"].get("over25", {})
        if not market.get("is_value"):
            continue

        home_rate = rates.get(m["home"], 0)
        away_rate = rates.get(m["away"], 0)

        if home_rate > 0.55 and away_rate > 0.55 and market.get("edge", 0) > 0.10:
            result = "WIN" if market["correct"] else "LOSS"
            profit = market["profit"] or 0
            f3_profit += profit
            if market["correct"]:
                f3_wins += 1
            else:
                f3_losses += 1
            print(
                f"{m['date']:<12} {m['home']+' vs '+m['away']:<35} "
                f"{market['edge']:>6.1%} "
                f"{result:>8} N{profit:>8,.0f}"
            )

    f3_total = f3_wins + f3_losses
    if f3_total:
        print(f"\n  Results: {f3_wins}W {f3_losses}L | "
              f"Accuracy: {f3_wins/f3_total:.1%} | "
              f"Profit: N{f3_profit:,.0f} | "
              f"ROI: {f3_profit/(f3_total*1000)*100:.1f}%")

    # Show each team's over 2.5 rate
    print("\n\n📊 TEAM OVER 2.5 RATES (training data):")
    ranked = sorted(rates.items(), key=lambda x: x[1], reverse=True)
    for team, rate in ranked:
        bar = "█" * int(rate * 20)
        print(f"  {team:<25} {rate:.1%} {bar}")


if __name__ == "__main__":
    analyse()
