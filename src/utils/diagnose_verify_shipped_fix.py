"""
diagnose_verify_shipped_fix.py

DIAGNOSTIC ONLY — reads data/backtest_results_v4.json, the file
backtester_v4.py already saved from its real run against the ACTUAL
shipped match_predictor.py (with the compression correction now live in
predict_result()). Does not call the pipeline again, does not change
any file. This is the real, non-simulated confirmation of everything
diagnose_compression_fix_candidates.py / diagnose_candidate_c_out_of_sample.py
predicted in simulation.

WHY THIS EXISTS
----------------
backtester_v4.py's own printed output reports ACCURACY and ROI on value
bets at a tuned edge threshold -- useful for the betting side of the
project, but NOT the calibration metric (predicted probability vs
actual outcome rate, bucketed) that this entire session's investigation
was measured against. ROI at n=18 value bets is dominated by variance,
not model quality, and the min_edge threshold was freshly re-tuned this
run -- neither is comparable to the -21.1%/-11.5% calibration gaps this
session has been tracking.

data/backtest_results_v4.json, saved by that same run, contains every
one of the 190 final-holdout fixtures' REAL model_prob and REAL correct
(actual outcome) for home_win/draw/away_win -- exactly what's needed to
rebuild the same calibration bucket table used throughout this session,
from the real shipped pipeline's actual output, not a simulation.

HOW IT WORKS
------------
Loads data/backtest_results_v4.json, pulls home_win/draw/away_win's
model_prob + correct for every match, buckets them with the same
10-point buckets used in every prior script this session, and prints
the result next to the LAST KNOWN pre-fix numbers (hardcoded from the
handover note / this session's confirmed baseline) so the before/after
is direct, not something to eyeball across separate runs.

USAGE
-----
    python src/utils/diagnose_verify_shipped_fix.py
"""

import json
import os

DATA_FILE = "data/backtest_results_v4.json"

BUCKET_EDGES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

# Last confirmed pre-fix numbers, for direct before/after comparison.
# home_win: from this session's real backtester_v4-graded baseline
# (diagnose_compression_fix_candidates.py's baseline report, which itself
# matched the originally reported calibration report numbers).
# draw/away_win: from the same baseline report, for completeness --
# both were already confirmed clean before this fix and should stay
# clean now.
PRE_FIX_BUCKETS = {
    "home_win": {
        "20-30%": {"n": 24, "predicted": 0.252, "actual": 0.042, "gap": -0.211},
        "30-40%": {"n": 30, "predicted": 0.357, "actual": 0.233, "gap": -0.123},
        "60-70%": {"n": 31, "predicted": 0.646, "actual": 0.677, "gap": +0.031},
        "70-80%": {"n": 14, "predicted": 0.725, "actual": 0.714, "gap": -0.010},
    },
}


def bucket_index(prob: float) -> int:
    return min(int(prob * 10), 9)


def build_buckets(rows: list, prob_key: str, actual_key: str) -> list:
    buckets = [[] for _ in range(10)]
    for r in rows:
        buckets[bucket_index(r[prob_key])].append(r)
    out = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        lo, hi = BUCKET_EDGES[i], BUCKET_EDGES[i + 1]
        avg_pred = sum(r[prob_key] for r in b) / len(b)
        actual_rate = sum(1 for r in b if r[actual_key]) / len(b)
        out.append({
            "label": f"{int(lo*100)}-{int(hi*100)}%",
            "n": len(b),
            "avg_predicted": round(avg_pred, 3),
            "actual_rate": round(actual_rate, 3),
            "gap": round(actual_rate - avg_pred, 3),
        })
    return out


def print_bucket_row(b: dict, pre_fix: dict = None):
    if b["n"] >= 8:
        flag = "⚠" if abs(b["gap"]) >= 0.10 else "ok"
    else:
        flag = "(low n)"
    line = (f"    {b['label']:<8} n={b['n']:>3}  pred={b['avg_predicted']*100:>5.1f}%  "
            f"actual={b['actual_rate']*100:>5.1f}%  gap={b['gap']*100:>+6.1f}%  {flag}")
    if pre_fix:
        line += f"    (was: gap={pre_fix['gap']*100:+.1f}%, n={pre_fix['n']})"
    print(line)


def main():
    if not os.path.exists(DATA_FILE):
        print(f"[ERROR] {DATA_FILE} not found. Run backtester_v4.py first "
              f"(it saves this file automatically).")
        return

    with open(DATA_FILE) as f:
        data = json.load(f)

    matches = data.get("matches", [])
    if not matches:
        print(f"[ERROR] No matches found in {DATA_FILE}.")
        return

    print("=" * 100)
    print("  VERIFYING SHIPPED FIX — real backtester_v4.py output, not a simulation")
    print("=" * 100)
    print(f"\nLoaded {len(matches)} fixtures from {DATA_FILE}")
    print(
        f"Generated at (from file, if present): {data.get('test_season', '?')}\n")

    rows = []
    skipped = 0
    for m in matches:
        markets = m.get("markets", {})
        row = {}
        ok = True
        for market in ("home_win", "draw", "away_win"):
            entry = markets.get(market)
            if not entry or "model_prob" not in entry or "correct" not in entry:
                ok = False
                break
            row[market] = entry["model_prob"]
            row[f"actual_{market}"] = entry["correct"]
        if ok:
            rows.append(row)
        else:
            skipped += 1

    print(
        f"Usable fixtures: {len(rows)} (skipped {skipped} with missing market data)\n")

    for market, actual_key in [("home_win", "actual_home_win"),
                               ("draw", "actual_draw"),
                               ("away_win", "actual_away_win")]:
        print(f"\n{'='*100}\n  {market}\n{'='*100}")
        buckets = build_buckets(rows, market, actual_key)
        pre_fix_market = PRE_FIX_BUCKETS.get(market, {})
        for b in buckets:
            print_bucket_row(b, pre_fix_market.get(b["label"]))

    def brier(rows: list, prob_key: str, actual_key: str) -> float:
        return sum((r[prob_key] - (1.0 if r[actual_key] else 0.0)) ** 2
                   for r in rows) / len(rows)

    print("\n" + "=" * 100)
    print("BRIER SCORE (real shipped pipeline)")
    print("=" * 100)
    for market, actual_key in [("home_win", "actual_home_win"),
                               ("draw", "actual_draw"),
                               ("away_win", "actual_away_win")]:
        score = brier(rows, market, actual_key)
        print(f"  {market:<10}: {score:.4f}")
    print(f"\n  For reference, this session's simulated baseline home_win Brier was 0.2095,")
    print(f"  and the fix (in-sample and out-of-sample) brought it to 0.2076.")

    print("\n" + "=" * 100)
    print("READING THIS")
    print("=" * 100)
    print(
        "The '(was: ...)' annotations on home_win's 20-30%/30-40%/60-70%/70-80% rows\n"
        "show this session's last confirmed pre-fix numbers directly alongside the real\n"
        "shipped pipeline's new numbers. 20-30% should have moved from roughly -21.1%\n"
        "toward roughly -11 to -12% (the fix's validated improvement); 60-70%/70-80%\n"
        "should be close to unchanged (that's the taper doing its job -- no damage to\n"
        "the range that was already fine). If the real numbers land noticeably outside\n"
        "the ranges the simulation predicted, something in the shipped code differs\n"
        "from what was validated -- worth diffing match_predictor.py's predict_result()\n"
        "against the version this session actually tested before trusting it further.\n\n"
        "The home_win Brier score above is the real, non-simulated version of the\n"
        "0.2095 -> 0.2076 improvement -- if it's meaningfully worse than 0.2076, that's\n"
        "the clearest single signal something didn't transfer correctly from simulation\n"
        "to production.\n"
    )


if __name__ == "__main__":
    main()
