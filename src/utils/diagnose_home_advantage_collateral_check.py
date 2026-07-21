"""
diagnose_home_advantage_collateral_check.py

DIAGNOSTIC ONLY -- calls real epl_elo.py / backtester_v4.py functions
directly. Does not modify anything. Safe to run against snapshot data.

WHY THIS EXISTS
----------------
diagnose_elo_30_40_investigation.py found a WEAK signal for lowering
HOME_ADVANTAGE from 100 to 80: validation-half Brier improved by only
0.0005 (100=0.2271, 80=0.2266 -- essentially tied), and the baseline
itself didn't replicate across halves (validation-half bucket gap was
-1.5%/fine, final-half was -12.4%/bad, same formula, same season).
That combination -- a near-tied validation "winner" plus a baseline
that doesn't reproduce across halves -- is the exact bucket-noise
pattern flagged as a new learning last session, so before treating
HOME_ADVANTAGE=80 as a real candidate, this checks the thing that
matters most: HOME_ADVANTAGE is a GLOBAL constant, applied to every
fixture, not scoped to the 30-40% home_win bucket. Two ranges are
already confirmed clean and must not break:
    - away_win: "confirmed fully calibrated" (see handover note)
    - home_win 60-70% / 70-80%: confirmed clean, specifically what
      Candidate A/B's collateral damage broke last session when a fix
      was applied without scoping to where the diagnosed problem
      actually lived.

This script computes, for BOTH HOME_ADVANTAGE=100 (baseline) and
HOME_ADVANTAGE=80 (candidate), a full decile bucket table AND overall
Brier for home_win, draw, and away_win, across the FULL season (both
190-match halves combined, 380 fixtures -- maximum available data,
since this is a sanity/collateral check, not a fresh out-of-sample
grading exercise on top of what's already been done).

USAGE
-----
    python src/utils/diagnose_home_advantage_collateral_check.py

    # Test a different candidate value:
    python src/utils/diagnose_home_advantage_collateral_check.py --candidate 90
"""

# isort: skip_file
import argparse
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DECILES = [(i / 10, (i + 1) / 10) for i in range(10)]


# Reproduction of predict_result_elo(), parameterized on home_advantage.
# Source of truth: src/models/epl_elo.py. KEEP IN SYNC with that
# function. Duplicated here (not imported from
# diagnose_elo_30_40_investigation.py) to keep this script
# self-contained and independently runnable, same convention as the
# other diagnostic scripts this session.
def repro_predict_result_elo(home_r: float, away_r: float, home_advantage: float) -> dict:
    def expected_score(a, b):
        return 1 / (1 + 10 ** ((b - a) / 400))

    home_adj = home_r + home_advantage
    exp_home = expected_score(home_adj, away_r)
    exp_away = expected_score(away_r, home_adj)
    rating_diff = abs(home_adj - away_r)
    draw_prob = max(0.10, 0.28 - (rating_diff / 2000))

    home_win = exp_home * (1 - draw_prob / 2)
    away_win = exp_away * (1 - draw_prob / 2)

    total = home_win + draw_prob + away_win
    return {
        "home_win": home_win / total,
        "draw": draw_prob / total,
        "away_win": away_win / total,
    }


def brier(preds_and_outcomes: list) -> float:
    if not preds_and_outcomes:
        return float("nan")
    return sum((p - o) ** 2 for p, o in preds_and_outcomes) / len(preds_and_outcomes)


def build_rows(matches: list, ratings: dict, home_advantage: float) -> list:
    rows = []
    for m in matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        home_r = ratings.get(home, 1500)
        away_r = ratings.get(away, 1500)
        p = repro_predict_result_elo(home_r, away_r, home_advantage)
        rows.append({
            "home": home, "away": away,
            "home_win": p["home_win"], "draw": p["draw"], "away_win": p["away_win"],
            "actual_home": m["FTR"] == "H",
            "actual_draw": m["FTR"] == "D",
            "actual_away": m["FTR"] == "A",
        })
    return rows


def bucket_table_for_market(rows: list, market: str, actual_key: str) -> list:
    table = []
    for lo, hi in DECILES:
        in_bucket = [r for r in rows if lo <= r[market]
                     < hi or (hi == 1.0 and r[market] == 1.0)]
        n = len(in_bucket)
        if n == 0:
            continue
        pred_avg = sum(r[market] for r in in_bucket) / n
        actual = sum(r[actual_key] for r in in_bucket) / n
        b = brier([(r[market], 1.0 if r[actual_key] else 0.0)
                  for r in in_bucket])
        table.append({
            "range": f"{lo:.0%}-{hi:.0%}", "n": n,
            "pred": pred_avg, "actual": actual, "gap": actual - pred_avg, "brier": b,
        })
    return table


def print_comparison(market: str, actual_key: str, baseline_rows: list, candidate_rows: list,
                     candidate_value: float):
    print(f"\n{'=' * 100}")
    print(f"MARKET: {market}")
    print(f"{'=' * 100}")

    base_table = bucket_table_for_market(baseline_rows, market, actual_key)
    cand_table = bucket_table_for_market(candidate_rows, market, actual_key)

    base_overall = brier(
        [(r[market], 1.0 if r[actual_key] else 0.0) for r in baseline_rows])
    cand_overall = brier(
        [(r[market], 1.0 if r[actual_key] else 0.0) for r in candidate_rows])

    print(f"  Overall Brier -- HOME_ADVANTAGE=100: {base_overall:.4f}   "
          f"HOME_ADVANTAGE={candidate_value:.0f}: {cand_overall:.4f}   "
          f"({'better' if cand_overall < base_overall else 'WORSE'})")

    print(f"\n  {'Range':<10} {'n':>4} | "
          f"{'base pred':>9} {'base act':>9} {'base gap':>9} {'base brier':>11} | "
          f"{'cand pred':>9} {'cand act':>9} {'cand gap':>9} {'cand brier':>11} | flag")
    print("  " + "-" * 108)

    base_by_range = {r["range"]: r for r in base_table}
    cand_by_range = {r["range"]: r for r in cand_table}

    for lo, hi in DECILES:
        rng = f"{lo:.0%}-{hi:.0%}"
        b = base_by_range.get(rng)
        c = cand_by_range.get(rng)
        if not b or not c:
            continue
        flag = ""
        # Flag collateral damage: a bucket whose gap was small (|gap| <
        # 10%, i.e. already reasonably calibrated) that gets meaningfully
        # WORSE under the candidate -- this is the specific failure mode
        # Candidate A/B hit last session.
        if abs(b["gap"]) < 0.10 and abs(c["gap"]) > abs(b["gap"]) + 0.05:
            flag = "  <-- COLLATERAL DAMAGE (was clean, now worse)"
        print(f"  {rng:<10} {b['n']:>4} | "
              f"{b['pred']:>8.1%} {b['actual']:>8.1%} {b['gap']:>+8.1%} {b['brier']:>10.4f} | "
              f"{c['pred']:>8.1%} {c['actual']:>8.1%} {c['gap']:>+8.1%} {c['brier']:>10.4f} |{flag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elo", default=None,
                        help="path to elo ratings snapshot (defaults to backtester_v4.SNAPSHOT_ELO)")
    parser.add_argument("--candidate", type=float, default=80,
                        help="candidate HOME_ADVANTAGE value to test against the 100 baseline")
    args = parser.parse_args()

    from src.utils.backtester_v4 import load_csv_file, TEST_SEASON_FILE, SNAPSHOT_ELO
    from src.models.epl_elo import load_ratings

    elo_path = args.elo or SNAPSHOT_ELO
    matches = load_csv_file(TEST_SEASON_FILE)
    ratings = load_ratings(elo_path)

    print(f"elo={elo_path}")
    print(f"Full season: {len(matches)} matches (both halves combined -- this is a\n"
          f"collateral-damage sanity check across max available data, not a fresh\n"
          f"out-of-sample grading exercise on top of what diagnose_elo_30_40_investigation.py\n"
          f"already did)")
    print(
        f"Testing candidate HOME_ADVANTAGE={args.candidate:.0f} against baseline=100\n")

    baseline_rows = build_rows(matches, ratings, 100)
    candidate_rows = build_rows(matches, ratings, args.candidate)

    print_comparison("home_win", "actual_home", baseline_rows,
                     candidate_rows, args.candidate)
    print_comparison("draw", "actual_draw", baseline_rows,
                     candidate_rows, args.candidate)
    print_comparison("away_win", "actual_away", baseline_rows,
                     candidate_rows, args.candidate)

    print(f"\n{'=' * 100}")
    print("READING THIS")
    print(f"{'=' * 100}")
    print(
        "If any bucket flagged COLLATERAL DAMAGE -- especially in away_win (confirmed\n"
        "fully calibrated per the handover note) or home_win 60-70%/70-80% (confirmed\n"
        "clean) -- that rules out shipping HOME_ADVANTAGE=80 as a global constant change,\n"
        "regardless of how the 30-40% bucket itself looks. A real fix would need to be\n"
        "scoped/tapered the way Candidate C was for the compression correction, not\n"
        "applied as a flat global constant change.\n\n"
        "If overall Brier improves for home_win with zero collateral flags anywhere,\n"
        "that's real supporting evidence -- but given how weak and unreplicated the\n"
        "original validation-half signal was (100 vs 80 tied within 0.0005 Brier,\n"
        "baseline gap flipping from -1.5% to -12.4% between halves), even a clean result\n"
        "here should probably be treated as 'worth testing against another season's data\n"
        "before shipping' rather than ready to implement -- there isn't a second\n"
        "independent season available in this project yet to confirm it the way\n"
        "Candidate C's constants were confirmed across two independent halves.\n"
    )


if __name__ == "__main__":
    main()
