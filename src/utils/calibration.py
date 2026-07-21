"""
Calibration checker — predicted probability vs actual outcome frequency.

Reads data/backtest_results_v4.json (the 190 final-holdout matches from
the last backtester_v4.py run, xG-leak-fixed) and buckets every
prediction by its stated probability, then checks how often that
probability actually came true.

This uses ALL 190 scored matches per market, not just the 44 flagged
value bets -- so it answers a different question than the ROI number
did. ROI told you whether the threshold-and-stake strategy on a small
subsample made money. This tells you whether the model's probabilities
themselves are honest, across the full sample.

A well-calibrated model: among every prediction where the model said
"60-70%", the outcome should have actually happened roughly 60-70% of
the time. A big gap in either direction means the probabilities
themselves are the problem, not just the betting threshold.

Usage (from project root, venv active):
    python -m src.utils.calibration
"""

import json
import os
from collections import defaultdict

BACKTEST_FILE = "data/backtest_results_v4.json"
OUTPUT_FILE = "data/calibration_report.json"

BUCKET_EDGES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

MARKETS = ["home_win", "draw", "away_win", "over25", "btts", "over35_cards"]


def get_bucket_label(prob: float) -> str:
    """Which 10%-wide bucket a probability falls into. 1.0 goes in the
    top bucket rather than falling through the range check."""
    for i in range(len(BUCKET_EDGES) - 1):
        lo, hi = BUCKET_EDGES[i], BUCKET_EDGES[i + 1]
        if lo <= prob < hi or (hi == 1.0 and prob >= hi):
            return f"{int(lo*100)}-{int(hi*100)}%"
    return "unknown"


def build_calibration(matches: list) -> dict:
    """
    For each market, group every prediction into its probability bucket,
    then compare the average predicted probability in that bucket
    against how often the outcome actually happened.
    """
    buckets = defaultdict(
        lambda: defaultdict(
            lambda: {"count": 0, "correct": 0, "prob_sum": 0.0})
    )

    for m in matches:
        for market, data in m.get("markets", {}).items():
            if market not in MARKETS:
                continue
            prob = data["model_prob"]
            correct = data["correct"]
            label = get_bucket_label(prob)
            b = buckets[market][label]
            b["count"] += 1
            b["prob_sum"] += prob
            if correct:
                b["correct"] += 1

    report = {}
    for market, bucket_data in buckets.items():
        rows = []
        for i in range(len(BUCKET_EDGES) - 1):
            lo, hi = BUCKET_EDGES[i], BUCKET_EDGES[i + 1]
            label = f"{int(lo*100)}-{int(hi*100)}%"
            d = bucket_data.get(label)
            if not d or d["count"] == 0:
                continue
            avg_predicted = round(d["prob_sum"] / d["count"], 3)
            actual_rate = round(d["correct"] / d["count"], 3)
            gap = round(actual_rate - avg_predicted, 3)
            # negative gap: model claimed higher confidence than reality
            # (overconfident). positive gap: model was too cautious
            # (underconfident). Threshold of 0.10 is a starting point,
            # not a statistically tuned cutoff -- treat as a flag to
            # look closer, not a verdict, especially on low-n buckets.
            if gap < -0.10:
                flag = "overconfident"
            elif gap > 0.10:
                flag = "underconfident"
            else:
                flag = "ok"
            rows.append({
                "bucket": label,
                "n": d["count"],
                "avg_predicted_prob": avg_predicted,
                "actual_hit_rate": actual_rate,
                "gap": gap,
                "flag": flag,
            })
        report[market] = rows

    return report


def print_report(report: dict):
    print("=" * 72)
    print("  CALIBRATION REPORT -- all 190 final-holdout predictions per market")
    print("  gap = actual_hit_rate - avg_predicted_prob")
    print("  negative gap = model overconfident | positive = underconfident")
    print("  low n (<5) buckets are noisy -- read the flag loosely there")
    print("=" * 72)

    for market, rows in report.items():
        if not rows:
            continue
        print(f"\n{market}")
        print(
            f"  {'bucket':<10} {'n':>4} {'predicted':>10} {'actual':>8} {'gap':>7}  flag")
        for r in rows:
            print(
                f"  {r['bucket']:<10} {r['n']:>4} "
                f"{r['avg_predicted_prob']*100:>9.1f}% "
                f"{r['actual_hit_rate']*100:>7.1f}% "
                f"{r['gap']*100:>6.1f}%  {r['flag']}"
            )


def run():
    if not os.path.exists(BACKTEST_FILE):
        print(f"[ERROR] Missing {BACKTEST_FILE}.")
        print("  Run: python -m src.utils.backtester_v4  first.")
        return

    with open(BACKTEST_FILE) as f:
        data = json.load(f)

    matches = data.get("matches", [])
    if not matches:
        print("[ERROR] backtest_results_v4.json has no 'matches' data.")
        return

    report = build_calibration(matches)

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print_report(report)
    print(f"\nSaved -> {OUTPUT_FILE}")


if __name__ == "__main__":
    run()
