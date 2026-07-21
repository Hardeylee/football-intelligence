"""
diagnose_over25_bucket.py

DIAGNOSTIC ONLY — calls your real match_predictor.py, epl_manager_profiles.py,
and formation_engine.py functions directly. Does not change any of them.

WHY THIS EXISTS
----------------
diagnose_stacking.py's 7 hand-picked fixtures showed the manager+formation
stage moving over25 in BOTH directions with no consistent sign -- e.g.
Arsenal vs Tottenham -0.081, Man City vs Liverpool +0.059. That's either a
real (non-inflationary) finding or two effects canceling out by coincidence
in a too-small sample. This script fixes both problems:

  1. SPLITS manager and formation into two separate deltas instead of one
     combined "B->C" number, by calling apply_manager_adjustments() and
     get_formation_adjustment() as two distinct real calls.
  2. Runs against the ACTUAL final-holdout-half fixtures from 2024/25
     (same chronological split backtester_v4.py uses), filtered down to
     ONLY the matches whose over25 prediction lands in the 60-70% bucket
     -- the exact population calibration_report.json flagged as 14.7
     points overconfident (102 matches, predicted 64.7%, actual 50.0%).

A built-in sanity check compares this script's own n/predicted-mean/
actual-rate for that bucket against the calibration report's numbers
(n=102, predicted 64.7%, actual 50.0%). If they don't roughly match, that's
a signal something in this reproduction (team names, snapshot files, split
boundary) has drifted from what actually produced the calibration report,
and the manager/formation findings below should be treated with caution
until that's resolved.

HOW IT WORKS
------------
For each matching fixture:
  B.  predict_goals() over25 -- post-xG-blend/H2H/availability, PRE any of
      manager/formation (real call).
  B2. apply_manager_adjustments()'s over25 -- POST manager, PRE formation
      (real call, isolated).
  C.  final over25 after formation adjustment + clipping -- reproduces
      predict_match()'s exact clipping formula on top of B2 (manual
      reproduction of those two lines, flagged, keep in sync) so the
      formation-only delta can be isolated from the manager-only delta
      instead of only seeing their combined effect.

USAGE
-----
    python src/utils/diagnose_over25_bucket.py

    # narrower/wider bucket, or a different season file:
    python src/utils/diagnose_over25_bucket.py --bucket-low 0.60 --bucket-high 0.70 --season-csv data/raw/24-25.csv

Defaults match backtester_v4.py exactly: same snapshot files, same
apply_availability=False, same force_promoted=set(), same 50/50
chronological validation/final split, same data/raw/24-25.csv season file.
"""

# isort: skip_file
#
# ^ LOAD-BEARING. Do not remove, and do not let VSCode's "Organize
# Imports" / format-on-save reorder this file -- the `from src...`
# imports below must run AFTER the sys.path.insert() call, or Python
# can't find the `src` package (ModuleNotFoundError: No module named
# 'src'). This exact bug hit diagnose_stacking.py twice already.

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.models.match_predictor import (  # noqa: E402
    load_profiles, load_h2h, _build_league_average,
    PROMOTED_TEAM_PROFILES,
    predict_goals, predict_cards, predict_corners, predict_match,
)
from src.models.epl_manager_profiles import apply_manager_adjustments  # noqa: E402
from src.models.formation_engine import get_formation_adjustment  # noqa: E402


# ---- Reproduced exactly from backtester_v4.py -- KEEP IN SYNC ----
TEST_SEASON_FILE_DEFAULT = "data/raw/24-25.csv"
SNAPSHOT_PROFILES = "data/team_profiles_asof_24-25.json"
SNAPSHOT_H2H = "data/h2h_asof_24-25.json"
SNAPSHOT_ELO = "data/epl_elo_ratings_asof_24-25.json"
SNAPSHOT_XG = "data/xg_profiles_asof_24-25.json"
VALIDATION_FRACTION = 0.5
REQUIRED_COLS = [
    "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
    "HY", "AY", "HR", "AR", "B365H", "B365D", "B365A",
    "B365>2.5", "B365<2.5",
]


def parse_date(datestr: str):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(datestr, fmt)
        except (ValueError, TypeError):
            continue
    return None


def load_csv_file(filepath: str) -> list:
    """Reproduced from backtester_v4.py's load_csv_file(). KEEP IN SYNC."""
    matches = []
    if not os.path.exists(filepath):
        print(f"[ERROR] Not found: {filepath}")
        return []
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        has_referee = "Referee" in (reader.fieldnames or [])
        for row in reader:
            if not row.get("HomeTeam") or not row.get("Date"):
                continue
            match = {}
            for col in REQUIRED_COLS:
                val = row.get(col, "")
                if col in ["FTHG", "FTAG", "HY", "AY", "HR", "AR"]:
                    try:
                        match[col] = int(float(val)) if val else 0
                    except (ValueError, TypeError):
                        match[col] = 0
                else:
                    try:
                        match[col] = float(val) if val else None
                    except (ValueError, TypeError):
                        match[col] = val
            match["Referee"] = row.get("Referee", "") if has_referee else ""
            match["_parsed_date"] = parse_date(match["Date"])
            matches.append(match)
    matches.sort(key=lambda m: m["_parsed_date"] or datetime.max)
    return matches
# ---- end reproduced section ----


def ensure_team_profiles(profiles: dict, teams: list) -> dict:
    """
    Reproduces predict_match()'s missing-team fallback with
    force_promoted=set() -- matching backtester_v4.py's predict_fixture()
    exactly, so PROMOTED_TEAM_PROFILES (2025/26 data) never gets used for
    this historical 2024/25 backtest. KEEP IN SYNC with predict_match().
    """
    missing = [t for t in teams if t not in profiles]
    if missing:
        league_avg = _build_league_average(profiles)
        for team in missing:
            profiles[team] = league_avg.copy()
    return profiles


def reproduce_formation_clip(over25_post_manager: float, formation_adj: dict) -> float:
    """
    Manual reproduction of predict_match()'s final over25 adjustment:
        fadj_goals = formation_adj["goals_adjustment"] * 0.30
        over25 = min(max(over25 + fadj_goals, 0.05), 0.95)
    KEEP IN SYNC with predict_match().
    """
    fadj_goals = formation_adj["goals_adjustment"] * 0.30
    return round(min(max(over25_post_manager + fadj_goals, 0.05), 0.95), 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season-csv", default=TEST_SEASON_FILE_DEFAULT)
    parser.add_argument("--bucket-low", type=float, default=0.60)
    parser.add_argument("--bucket-high", type=float, default=0.70)
    args = parser.parse_args()

    for path in (SNAPSHOT_PROFILES, SNAPSHOT_H2H, SNAPSHOT_ELO, SNAPSHOT_XG, args.season_csv):
        if not os.path.exists(path):
            print(f"[ERROR] Missing file: {path}")
            sys.exit(1)

    print(f"Season CSV: {args.season_csv}")
    print(f"Bucket: [{args.bucket_low}, {args.bucket_high})\n")

    all_matches = load_csv_file(args.season_csv)
    split_idx = int(len(all_matches) * VALIDATION_FRACTION)
    final_matches = all_matches[split_idx:]
    print(f"Final holdout half: {len(final_matches)} matches "
          f"(this must match backtester_v4.py's 'Final test half' count "
          f"from your earlier run -- if it doesn't, this script's split "
          f"or CSV isn't reproducing the same run)\n")

    profiles = load_profiles(SNAPSHOT_PROFILES)
    h2h_data = load_h2h(SNAPSHOT_H2H)

    rows = []
    bucket_predicted = []
    bucket_actual_hits = []

    for m in final_matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        referee = m.get("Referee", "")

        try:
            profiles = ensure_team_profiles(profiles, [home, away])

            # Stage B: predict_goals() direct, matching backtest kwargs exactly
            goals_direct = predict_goals(
                home, away, profiles, h2h_data,
                apply_availability=False, xg_path=SNAPSHOT_XG,
            )
            stage_b_over25 = goals_direct["over25"]

            # Only proceed with the expensive manager/formation isolation
            # if this fixture is actually in the flagged bucket -- but we
            # need the FINAL (post-adjustment) over25 to know that, so we
            # compute the full stack for every fixture first, then filter.
            cards_direct = predict_cards(home, away, profiles, referee=referee)
            corners_direct = predict_corners(home, away, profiles)

            # Stage B2: manager adjustment only, isolated (real call)
            mgr_adjusted = apply_manager_adjustments(
                home, away, goals_direct, cards_direct, corners_direct
            )
            stage_b2_over25 = mgr_adjusted["goals"]["over25"]

            # Stage C: formation adjustment on top, reproducing predict_match()'s
            # exact clip formula so it's isolated from the manager step
            formation_adj = get_formation_adjustment(home, away)
            stage_c_over25 = reproduce_formation_clip(
                stage_b2_over25, formation_adj)

            # Cross-check against the REAL predict_match() final value --
            # if these don't match (within rounding), the manual clip
            # reproduction above has drifted from predict_match() and
            # needs fixing before trusting the isolated deltas.
            full_pred = predict_match(
                home, away, referee=referee,
                profiles_path=SNAPSHOT_PROFILES, h2h_path=SNAPSHOT_H2H,
                elo_path=SNAPSHOT_ELO, xg_path=SNAPSHOT_XG,
                apply_availability=False, force_promoted=set(),
            )
            real_final_over25 = full_pred["goals"]["over25"]

        except Exception as e:
            print(f"  [SKIP] {home} vs {away}: {e}")
            continue

        # Filter to the flagged bucket using the REAL final predict_match()
        # value, since that's what the calibration report actually bucketed.
        if not (args.bucket_low <= real_final_over25 < args.bucket_high):
            continue

        total_goals = m["FTHG"] + m["FTAG"]
        actual_over25 = total_goals > 2.5

        rows.append({
            "fixture": f"{home} vs {away}", "date": m["Date"],
            "B_pre_mgr_formation": stage_b_over25,
            "B2_post_manager_only": stage_b2_over25,
            "delta_mgr": round(stage_b2_over25 - stage_b_over25, 3),
            "C_reproduced_post_formation": stage_c_over25,
            "delta_formation": round(stage_c_over25 - stage_b2_over25, 3),
            "real_predict_match_final": real_final_over25,
            "reproduction_mismatch": round(abs(stage_c_over25 - real_final_over25), 3),
            "actual_over25": actual_over25,
        })
        bucket_predicted.append(real_final_over25)
        bucket_actual_hits.append(actual_over25)

    if not rows:
        print("[WARN] No fixtures fell in this bucket. Check that the "
              "snapshot files and season CSV match what produced "
              "calibration_report.json.")
        return

    # ---- Sanity check against calibration_report.json's reported numbers ----
    n = len(rows)
    mean_pred = sum(bucket_predicted) / n
    actual_rate = sum(bucket_actual_hits) / n
    mismatches = [r for r in rows if r["reproduction_mismatch"] > 0.001]

    print("=" * 110)
    print("SANITY CHECK vs calibration_report.json's over25 60-70% bucket "
          "(reported: n=102, predicted 64.7%, actual 50.0%)")
    print("=" * 110)
    print(f"This run:                                    n={n}, "
          f"predicted mean={mean_pred:.3f}, actual rate={actual_rate:.3f}")
    if abs(n - 102) > 15 or abs(mean_pred - 0.647) > 0.03 or abs(actual_rate - 0.50) > 0.05:
        print("[WARN] These numbers diverge meaningfully from the calibration "
              "report. The findings below may not represent the same "
              "population -- check snapshot file versions and season CSV "
              "before trusting the manager/formation breakdown.")
    else:
        print("Close enough to the calibration report's numbers -- this run "
              "is very likely checking the same population.")
    if mismatches:
        print(f"\n[WARN] {len(mismatches)}/{n} fixtures had a reproduction "
              f"mismatch >0.001 between the manual formation-clip formula "
              f"and predict_match()'s real output -- the manager/formation "
              f"split may be slightly off for those rows specifically.")

    # ---- Per-fixture table ----
    print("\n" + "=" * 110)
    print(
        f"OVER25 STACKING -- {n} fixtures in the [{args.bucket_low}, {args.bucket_high}) bucket")
    print("=" * 110)
    for r in rows:
        outcome = "HIT (over)" if r["actual_over25"] else "missed (under)"
        print(f"\n{r['fixture']} ({r['date']})  actual: {outcome}")
        print(f"  B  (pre-mgr/formation):        {r['B_pre_mgr_formation']}")
        print(
            f"  B2 (post-manager only):        {r['B2_post_manager_only']}   (Δ manager: {r['delta_mgr']:+.3f})")
        print(
            f"  C  (post-formation, reproduced): {r['C_reproduced_post_formation']}   (Δ formation: {r['delta_formation']:+.3f})")
        print(f"  Real predict_match() final:    {r['real_predict_match_final']}"
              + (f"   [MISMATCH vs reproduction: {r['reproduction_mismatch']}]" if r["reproduction_mismatch"] > 0.001 else ""))

    # ---- Summary: which stage is consistently inflating ----
    mgr_deltas = [r["delta_mgr"] for r in rows]
    form_deltas = [r["delta_formation"] for r in rows]
    mgr_positive = sum(1 for d in mgr_deltas if d > 0)
    form_positive = sum(1 for d in form_deltas if d > 0)

    print("\n" + "=" * 110)
    print("SUMMARY")
    print("=" * 110)
    print(f"Manager step:   avg Δ={sum(mgr_deltas)/n:+.4f}   "
          f"positive in {mgr_positive}/{n} fixtures")
    print(f"Formation step: avg Δ={sum(form_deltas)/n:+.4f}   "
          f"positive in {form_positive}/{n} fixtures")
    print(f"\nMean predicted over25 in this bucket: {mean_pred:.3f}")
    print(f"Actual over25 rate in this bucket:     {actual_rate:.3f}")
    print(
        f"Overconfidence gap:                    {mean_pred - actual_rate:+.3f}")
    print(
        "\nIf one step's avg Δ is consistently positive across most fixtures "
        "(not just on average), that's the stage inflating over25 for this "
        "specific bucket. If both steps are small/mixed-sign like the "
        "7-fixture sample was, the overconfidence likely isn't coming from "
        "manager/formation at all -- it would point back to the xG-blend "
        "weighting (the 0.35/0.35/0.15/0.15 split) or the historical "
        "over25_rate inputs feeding it, which would need a different "
        "diagnostic than this one."
    )


if __name__ == "__main__":
    main()
