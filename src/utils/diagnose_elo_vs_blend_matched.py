"""
diagnose_elo_vs_blend_matched.py

DIAGNOSTIC ONLY — calls the real predict_result_elo() and predict_match()
(via backtester_v4.predict_fixture()) directly. Does not change any
model file. Safe to run against live or snapshot data.

WHY THIS EXISTS
----------------
diagnose_elo_only_calibration.py bucketed Elo-only and full-pipeline
home_win SEPARATELY across the 190-fixture final holdout half. That
run showed two different shapes in the same 20-40% range:

    home_win 20-30%:  Elo-only gap -4.5% (ok)   full-pipeline gap -21.0% (bad)
    home_win 30-40%:  Elo-only gap -12.4% (bad) full-pipeline gap -11.4% (bad, same size)

That's real signal (20-30% looks blend-introduced, 30-40% looks
upstream-in-Elo-already) but the two tables bucket fixtures
INDEPENDENTLY -- a fixture Elo puts at 24% might land at 31% after
blending, so "the 19 fixtures in Elo-only's 20-30% bucket" and "the 23
fixtures in full-pipeline's 20-30% bucket" are not necessarily the same
matches. That independence means the previous run can't say WHICH
fixtures the blend is moving, or by how much, or whether it's a few
outliers vs a broad shift.

This script fixes that by computing BOTH numbers for every one of the
same 190 fixtures, side by side per match, so the actual delta the
blend applies to each individual fixture is visible directly --
matched pairs, not independently re-bucketed aggregates.

HOW IT WORKS
------------
1. Same chronological 50/50 split, same final holdout half (~190
   matches) as backtester_v4.py and diagnose_elo_only_calibration.py --
   directly comparable to both.
2. For every fixture, computes:
     - elo_home_win   (REAL predict_result_elo(), no blend)
     - full_home_win  (REAL predict_match() -> result.home_win, full blend)
     - delta = full_home_win - elo_home_win
     - actual (bool)
3. Filters to fixtures where EITHER elo_home_win OR full_home_win falls
   in [0.20, 0.40) -- the two open buckets -- and prints one row per
   fixture: both numbers, the delta, and the actual result.
4. Splits that filtered set into two groups and reports separately:
     - "moved INTO 20-40% by the blend" (elo outside the range, full
       inside it)
     - "already in 20-40% before blending, blend kept it there or moved
       it within/out" (elo inside the range)
   so a small number of blend-introduced outliers is distinguishable
   from a broad shift affecting most fixtures in the range.
5. Prints avg delta and actual-hit-rate for each group.

USAGE
-----
    python src/utils/diagnose_elo_vs_blend_matched.py
"""

# isort: skip_file
#
# ^ LOAD-BEARING, same reason as the other diagnose_*.py scripts in
# this project -- keeps sys.path.insert() below from being hoisted
# below a `from src...` import by an editor's import-sorter.

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

RANGE_LO = 0.20
RANGE_HI = 0.40


def in_range(x: float) -> bool:
    return RANGE_LO <= x < RANGE_HI


def elo_only_predict(home: str, away: str, elo_path: str) -> float:
    """REAL call to predict_result_elo() -- no blending of any kind."""
    from src.models.epl_elo import load_ratings, predict_result_elo

    elo_ratings = load_ratings(elo_path) if elo_path else load_ratings()
    pred = predict_result_elo(home, away, elo_ratings)
    return pred["home_win"]


def main():
    from src.utils.backtester_v4 import (
        TEST_SEASON_FILE, VALIDATION_FRACTION, SNAPSHOT_ELO,
        load_csv_file, predict_fixture, get_actuals,
    )

    print("=" * 100)
    print("  ELO-ONLY vs FULL-PIPELINE — matched per-fixture home_win, filtered to 20-40%")
    print("=" * 100)

    all_matches = load_csv_file(TEST_SEASON_FILE)
    if not all_matches:
        print(f"[ERROR] No matches loaded from {TEST_SEASON_FILE}.")
        return

    split_idx = int(len(all_matches) * VALIDATION_FRACTION)
    final_matches = all_matches[split_idx:]
    print(f"\nFinal holdout half: {len(final_matches)} matches\n")

    rows = []
    skipped = 0

    for m in final_matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        actuals = get_actuals(m)

        try:
            elo_hw = elo_only_predict(home, away, SNAPSHOT_ELO)
        except Exception as e:
            skipped += 1
            print(f"  [SKIP] {home} vs {away} (elo): {e}")
            continue

        full_pred = predict_fixture(home, away, m.get("Referee", ""))
        if not full_pred or "_error" in full_pred:
            skipped += 1
            print(f"  [SKIP] {home} vs {away} (full): "
                  f"{full_pred.get('_error', 'unknown error')}")
            continue

        full_hw = full_pred["home_win"]

        if not (in_range(elo_hw) or in_range(full_hw)):
            continue

        rows.append({
            "fixture": f"{home} vs {away}",
            "elo_hw": elo_hw,
            "full_hw": full_hw,
            "delta": round(full_hw - elo_hw, 3),
            "actual": actuals["home_win"],
            "moved_in": (not in_range(elo_hw)) and in_range(full_hw),
            "moved_out": in_range(elo_hw) and (not in_range(full_hw)),
            "stayed_in": in_range(elo_hw) and in_range(full_hw),
        })

    print(f"Scored {len(rows)} fixtures touching the 20-40% range "
          f"(by either stage), skipped={skipped}\n")

    rows.sort(key=lambda r: r["delta"], reverse=True)

    print(f"{'Fixture':<32} {'Elo':>7} {'Full':>7} {'Δ':>7}  {'Actual':>7}  Note")
    print("-" * 100)
    for r in rows:
        note = ("MOVED IN by blend" if r["moved_in"]
                else "moved OUT by blend" if r["moved_out"]
                else "stayed in range")
        actual_str = "HOME WIN" if r["actual"] else "no"
        print(f"{r['fixture']:<32} {r['elo_hw']*100:>6.1f}% {r['full_hw']*100:>6.1f}% "
              f"{r['delta']*100:>+6.1f}%  {actual_str:>7}  {note}")

    moved_in = [r for r in rows if r["moved_in"]]
    stayed_in = [r for r in rows if r["stayed_in"]]
    moved_out = [r for r in rows if r["moved_out"]]

    def group_stats(group: list, label: str):
        if not group:
            print(f"\n  {label}: none")
            return
        avg_delta = sum(r["delta"] for r in group) / len(group)
        avg_full = sum(r["full_hw"] for r in group) / len(group)
        hit_rate = sum(1 for r in group if r["actual"]) / len(group)
        print(f"\n  {label}: n={len(group)}  avg_delta={avg_delta*100:+.1f}%  "
              f"avg_predicted(full)={avg_full*100:.1f}%  actual_hit_rate={hit_rate*100:.1f}%  "
              f"gap={hit_rate*100 - avg_full*100:+.1f}%")

    print("\n" + "=" * 100)
    print("GROUP BREAKDOWN")
    print("=" * 100)
    group_stats(
        moved_in, "MOVED IN by blend (Elo said <20% or >=40%, full pipeline put them in 20-40%)")
    group_stats(
        stayed_in, "STAYED IN range (Elo already had them in 20-40%, blend kept them there)")
    group_stats(
        moved_out, "MOVED OUT by blend (Elo had them in 20-40%, full pipeline moved them out)")

    print("\n" + "=" * 100)
    print("READING THIS")
    print("=" * 100)
    print(
        "If 'MOVED IN by blend' is a small group with a large positive avg_delta and a\n"
        "low actual_hit_rate relative to avg_predicted(full) -- these are fixtures the\n"
        "blend is specifically dragging INTO the 20-40% home_win range from outside it,\n"
        "and they're inflating the bucket's overconfidence on their own. That points at\n"
        "hist_home/form_home in predict_result() for THESE specific fixtures -- check\n"
        "their raw home_win_rate/form_score inputs (e.g. via diagnose_result_stacking.py)\n"
        "for a data quality issue (stale/wrong values for specific teams) vs a formula\n"
        "issue (affects many fixtures roughly equally).\n\n"
        "If 'STAYED IN range' is the larger group and its gap looks similar to what\n"
        "diagnose_elo_only_calibration.py already showed for Elo-only's 30-40% bucket --\n"
        "that's the upstream-in-Elo story confirmed at the individual-fixture level, not\n"
        "just in aggregate. In that case the blend is innocent for these fixtures and the\n"
        "next place to look is epl_elo.py itself (ratings, HOME_ADVANTAGE=100, K_FACTOR,\n"
        "or the draw_prob floor formula).\n\n"
        "Either way, scan the fixture list above for repeated team names -- if 3-4\n"
        "fixtures share a home or away team, that's the team-level dominance possibility\n"
        "(item 4 in the handover note) surfacing directly, not a formula problem at all.\n"
    )


if __name__ == "__main__":
    main()
