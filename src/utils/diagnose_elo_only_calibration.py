"""
diagnose_elo_only_calibration.py

DIAGNOSTIC ONLY — calls src.models.epl_elo.predict_result_elo() directly,
with ZERO blending against historical rates, form, or H2H. Does not
change any model file. Safe to run against live or snapshot data.

WHY THIS EXISTS
----------------
Session status (see handover note): away_win is now fully calibrated
after removing HOME_ADVANTAGE double-counting from predict_result()'s
historical/form stages. home_win remains overconfident specifically in
the 20-40% range:

    home_win  20-30%  n=23  predicted 25.4%  actual  4.3%   gap -21.1%
    home_win  30-40%  n=29  predicted 35.6%  actual 24.1%   gap -11.5%

The opponent-blindness hypothesis (tested in diagnose_result_disagreement.py)
was ruled out at full 190-fixture scale. Every fix so far has touched the
BLEND (predict_result()'s hist/form/H2H stages) -- none has asked whether
Elo's OWN predictions, with no blending at all, are themselves well
calibrated in this range. This script answers exactly that question:
strip the blend out entirely, bucket predict_result_elo()'s raw output
against the same real 190-fixture final holdout half used by
backtester_v4.py, and compare.

Two possible outcomes:
  - If Elo-only is ALSO overconfident in the 20-40% home_win range in
    roughly the same shape as the full pipeline -- the problem is
    upstream, inside epl_elo.py (rating quality, K-factor, the
    HOME_ADVANTAGE=100 constant, or the draw_prob floor formula), and
    reweighting predict_result()'s blend won't fix it.
  - If Elo-only is well calibrated (or overconfident in a DIFFERENT
    range/shape) -- the problem is introduced downstream, inside
    predict_result()'s hist/form/H2H blend, and epl_elo.py itself is
    not the place to look next.

This script draws NO conclusion on its own -- it prints the buckets,
the person reads the shape.

HOW IT WORKS
------------
1. Loads the same TEST_SEASON_FILE, applies the same chronological
   50/50 validation/final split, and uses the same "final test half"
   (~190 matches) as backtester_v4.py -- so results are directly
   comparable to the existing calibration report, not a fresh sample
   that could tell a different, unrelated story.
2. For every fixture in that final half, calls the REAL
   predict_result_elo() using the same SNAPSHOT_ELO file
   backtester_v4.py uses -- no historical rates, no form, no H2H, no
   promoted-team overrides (SNAPSHOT_ELO is built with
   promoted_overrides=None per epl_elo.py's PATCH NOTE, same as the
   real pipeline's backtest condition).
3. Buckets predicted home_win / draw / away_win into 10-point-wide
   buckets (matching the calibration report's own bucket width) and
   prints predicted-avg vs actual-rate vs gap vs n per bucket, for all
   three markets.
4. Also runs the SAME bucketing on the full pipeline's real
   predict_result() output (calling predict_fixture() from
   backtester_v4.py) side-by-side, so the Elo-only and full-pipeline
   numbers for the 20-40% home_win range sit right next to each other
   for direct comparison -- no need to cross-reference two separate
   runs or two separate documents by hand.

USAGE
-----
    python src/utils/diagnose_elo_only_calibration.py

    # Uses backtester_v4.py's own SNAPSHOT_* file paths and
    # TEST_SEASON_FILE by default (imported directly, not re-typed --
    # a re-typed copy of those five path strings is exactly the kind of
    # "KEEP IN SYNC" duplication this project has already been burned
    # by once this session).
"""

# isort: skip_file
#
# ^ LOAD-BEARING, same reason as diagnose_stacking.py /
# diagnose_result_stacking.py: keeps the sys.path.insert() below from
# being hoisted below any `from src...` import by an editor's
# import-sorter.

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# 10-point-wide buckets, 0-100%, matching the calibration report's own
# bucket width (20-30%, 30-40%, 50-60%, 70-80% are all 10 points wide
# in the handover note's numbers).
BUCKET_EDGES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def bucket_label(lo: float, hi: float) -> str:
    return f"{int(lo*100)}-{int(hi*100)}%"


def bucket_index(prob: float) -> int:
    """Which bucket a probability falls into. 1.0 goes in the last
    bucket rather than overflowing."""
    idx = int(prob * 10)
    return min(idx, 9)


def build_buckets(rows: list, prob_key: str, actual_key: str) -> list:
    """
    rows: list of dicts, each with a predicted probability (prob_key)
    and a boolean actual outcome (actual_key).
    Returns one dict per non-empty bucket: label, n, avg_predicted,
    actual_rate, gap (actual - predicted).
    """
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
            "label": bucket_label(lo, hi),
            "n": len(b),
            "avg_predicted": round(avg_pred, 3),
            "actual_rate": round(actual_rate, 3),
            "gap": round(actual_rate - avg_pred, 3),
        })
    return out


def print_bucket_table(title: str, buckets: list):
    print(f"\n  {title}")
    print(
        f"  {'Bucket':<10} {'n':>4}  {'predicted':>10}  {'actual':>8}  {'gap':>8}  flag")
    print(f"  {'-'*10} {'-'*4}  {'-'*10}  {'-'*8}  {'-'*8}  ----")
    for b in buckets:
        gap = b["gap"]
        flag = ""
        if b["n"] >= 8:
            if gap <= -0.10:
                flag = "⚠ overconfident"
            elif gap >= 0.10:
                flag = "⚠ underconfident"
            else:
                flag = "ok"
        else:
            flag = "(low n)"
        print(f"  {b['label']:<10} {b['n']:>4}  {b['avg_predicted']*100:>9.1f}%  "
              f"{b['actual_rate']*100:>7.1f}%  {gap*100:>+7.1f}%  {flag}")


def elo_only_predict(home: str, away: str, elo_path: str) -> dict:
    """REAL call to predict_result_elo() -- no blending of any kind."""
    from src.models.epl_elo import load_ratings, predict_result_elo

    elo_ratings = load_ratings(elo_path) if elo_path else load_ratings()
    pred = predict_result_elo(home, away, elo_ratings)
    return {
        "home_win": pred["home_win"],
        "draw":     pred["draw"],
        "away_win": pred["away_win"],
    }


def main():
    from src.utils.backtester_v4 import (
        TEST_SEASON_FILE, VALIDATION_FRACTION, SNAPSHOT_ELO,
        load_csv_file, predict_fixture, get_actuals,
    )

    print("=" * 78)
    print("  ELO-ONLY vs FULL-PIPELINE CALIBRATION — home_win / draw / away_win")
    print("=" * 78)

    print(f"\nUsing elo_path={SNAPSHOT_ELO}")
    print(f"Loading {TEST_SEASON_FILE} and reproducing backtester_v4.py's "
          f"chronological {VALIDATION_FRACTION:.0%}/{1-VALIDATION_FRACTION:.0%} split...")

    all_matches = load_csv_file(TEST_SEASON_FILE)
    if not all_matches:
        print(f"[ERROR] No matches loaded from {TEST_SEASON_FILE} -- "
              f"check the file exists and re-run.")
        return

    split_idx = int(len(all_matches) * VALIDATION_FRACTION)
    final_matches = all_matches[split_idx:]
    print(f"Final holdout half: {len(final_matches)} matches "
          f"(same half backtester_v4.py reports its calibration numbers on)\n")

    elo_rows = []
    full_rows = []
    skipped_elo = 0
    skipped_full = 0

    for m in final_matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        actuals = get_actuals(m)

        try:
            elo_pred = elo_only_predict(home, away, SNAPSHOT_ELO)
            elo_rows.append({
                "home_win": elo_pred["home_win"], "actual_home_win": actuals["home_win"],
                "draw": elo_pred["draw"], "actual_draw": actuals["draw"],
                "away_win": elo_pred["away_win"], "actual_away_win": actuals["away_win"],
            })
        except Exception as e:
            skipped_elo += 1
            print(f"  [SKIP elo] {home} vs {away}: {e}")

        full_pred = predict_fixture(home, away, m.get("Referee", ""))
        if not full_pred or "_error" in full_pred:
            skipped_full += 1
            continue
        full_rows.append({
            "home_win": full_pred["home_win"], "actual_home_win": actuals["home_win"],
            "draw": full_pred["draw"], "actual_draw": actuals["draw"],
            "away_win": full_pred["away_win"], "actual_away_win": actuals["away_win"],
        })

    print(f"Scored: {len(elo_rows)} elo-only, {len(full_rows)} full-pipeline "
          f"(skipped elo={skipped_elo}, skipped full={skipped_full})")

    for market, actual_key in [("home_win", "actual_home_win"),
                               ("draw", "actual_draw"),
                               ("away_win", "actual_away_win")]:
        print("\n" + "=" * 78)
        print(f"  MARKET: {market}")
        print("=" * 78)

        elo_buckets = build_buckets(elo_rows, market, actual_key)
        print_bucket_table(
            f"A. Elo-only (predict_result_elo(), no blend)", elo_buckets)

        full_buckets = build_buckets(full_rows, market, actual_key)
        print_bucket_table(
            f"B. Full pipeline (predict_result(), real blend)", full_buckets)

    print("\n" + "=" * 78)
    print("READING THIS")
    print("=" * 78)
    print(
        "Focus on the home_win 20-30% and 30-40% rows specifically -- those are\n"
        "the two open buckets from the calibration report.\n\n"
        "If table A (Elo-only) shows roughly the SAME overconfidence gap in those\n"
        "buckets as table B (full pipeline) -- the problem is upstream, inside\n"
        "epl_elo.py itself (rating quality from initialise_ratings(), the flat\n"
        "HOME_ADVANTAGE=100 constant, K_FACTOR, or the draw_prob floor formula\n"
        "`max(0.10, 0.28 - rating_diff/2000)` in predict_result_elo()). Reweighting\n"
        "predict_result()'s blend would not fix an upstream Elo problem -- it would\n"
        "just be averaging a bad number with two other numbers.\n\n"
        "If table A is well calibrated (or wrong in a different range/shape) while\n"
        "table B is overconfident in 20-40% -- the blend itself (hist_home/form_home\n"
        "in predict_result(), or how H2H interacts with them) is introducing the\n"
        "problem, and epl_elo.py is not where to look next. In that case, revisit\n"
        "items 3 (draw_prob floor) and 4 (team-level dominance check) from the\n"
        "handover note's open-items list -- those become the live leads again.\n"
    )


if __name__ == "__main__":
    main()
