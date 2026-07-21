"""
diagnose_over25_inputs.py

DIAGNOSTIC ONLY — reads your real snapshot data and calls load_profiles()/
load_xg_profiles() directly. Does not change any model file.

WHY THIS EXISTS
----------------
diagnose_over25_bucket.py ruled out manager/formation as the cause of the
60-70% bucket's 14.7-point overconfidence (avg deltas +0.0075 and +0.0033,
both mixed-sign across fixtures) and confirmed n=102/predicted 64.7%/actual
50.0% matches the calibration report exactly. That pointed upstream, to
predict_goals()'s xG-blend stage itself.

This script splits that further into two competing hypotheses:

  HYPOTHESIS A: the xG MAGNITUDES are fine, but the RATE FORMULAS built on
  top of them are miscalibrated -- e.g. xg_scraper.py's
  derive_market_rates() uses a flat linear formula,
  xg_over25_rate = min(total_xg / 5.0, 0.95), which has no statistical
  basis (goals aren't linear in total xG -- they're closer to Poisson-
  distributed). Or the historical over25_rate fields in the team_profiles
  snapshot (15% weight each side) are stale/wrong independent of xG.

  HYPOTHESIS B: the xG magnitudes THEMSELVES are inflated (teams' avg_xg
  values in xg_profiles_asof_24-25.json are too high), so even a
  statistically correct conversion would still overpredict over25.

HOW IT SEPARATES THEM
----------------------
For each of the 102 bucket fixtures, this script computes an independent,
textbook-standard reference probability directly from total_xg (home_xg +
away_xg) using the Poisson distribution: if home and away goals are each
approximately Poisson-distributed (a standard, widely-used approximation
in football analytics — not this codebase's own formula), their sum is
also Poisson with rate = total_xg, so:

    P(total goals > 2.5) = 1 - P(total <= 2)
                          = 1 - [P(0) + P(1) + P(2)]   under Poisson(total_xg)

This is computed from scratch here (pure Python, no scipy needed) — it is
NOT read from your codebase, specifically so it can serve as an
independent check rather than testing the model against itself.

  - If this Poisson reference probability, averaged across the 102
    fixtures, comes out close to the model's own ~64.7% blended rate,
    that means total_xg itself is already implying too many goals —
    HYPOTHESIS B, the xG magnitudes are the problem (points back at
    xg_scraper.py's season-weighting or the underlying Understat data).

  - If the Poisson reference probability comes out close to the ACTUAL
    50.0% outcome rate instead, that means total_xg is basically fine,
    and the gap is being introduced by xg_over25_rate's linear /5.0
    formula and/or the historical over25_rate fields — HYPOTHESIS A,
    the conversion formulas are the problem (points at
    derive_market_rates() and/or the team_profiles snapshot).

USAGE
-----
    python src/utils/diagnose_over25_inputs.py
"""

# isort: skip_file
#
# ^ LOAD-BEARING. Do not remove, and do not let VSCode's "Organize
# Imports" / format-on-save reorder this file -- the `from src...`
# imports below must run AFTER the sys.path.insert() call, or Python
# can't find the `src` package (ModuleNotFoundError: No module named
# 'src'). This exact bug has hit earlier diagnostic scripts in this
# project twice already.

import argparse
import csv
import math
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.models.match_predictor import (  # noqa: E402
    load_profiles, load_h2h, _build_league_average,
    predict_goals, predict_match,
)
from src.collectors.xg_scraper import load_xg_profiles  # noqa: E402


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
    """Matches predict_match()'s fallback with force_promoted=set(),
    exactly as backtester_v4.py calls it. KEEP IN SYNC."""
    missing = [t for t in teams if t not in profiles]
    if missing:
        league_avg = _build_league_average(profiles)
        for team in missing:
            profiles[team] = league_avg.copy()
    return profiles


def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_over25(total_xg: float) -> float:
    """
    Independent reference probability: P(total goals > 2.5) assuming
    goals ~ Poisson(total_xg). This is a standard football-analytics
    approximation, computed from scratch here -- NOT read from
    xg_scraper.py or match_predictor.py -- specifically so it can serve
    as a check on those files' own formulas rather than testing them
    against themselves.
    """
    cdf_le_2 = sum(poisson_pmf(k, total_xg) for k in range(3))
    return 1 - cdf_le_2


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

    all_matches = load_csv_file(args.season_csv)
    split_idx = int(len(all_matches) * VALIDATION_FRACTION)
    final_matches = all_matches[split_idx:]

    profiles = load_profiles(SNAPSHOT_PROFILES)
    h2h_data = load_h2h(SNAPSHOT_H2H)
    xg_profiles = load_xg_profiles(SNAPSHOT_XG)

    rows = []

    for m in final_matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        referee = m.get("Referee", "")

        try:
            profiles = ensure_team_profiles(profiles, [home, away])

            full_pred = predict_match(
                home, away, referee=referee,
                profiles_path=SNAPSHOT_PROFILES, h2h_path=SNAPSHOT_H2H,
                elo_path=SNAPSHOT_ELO, xg_path=SNAPSHOT_XG,
                apply_availability=False, force_promoted=set(),
            )
            real_final_over25 = full_pred["goals"]["over25"]

            if not (args.bucket_low <= real_final_over25 < args.bucket_high):
                continue

            goals_direct = predict_goals(
                home, away, profiles, h2h_data,
                apply_availability=False, xg_path=SNAPSHOT_XG,
            )
            total_xg = goals_direct["total_xg"]
            data_source = goals_direct["data_source"]

            home_xg_over25_rate = xg_profiles.get(
                home, {}).get("xg_over25_rate")
            away_xg_over25_rate = xg_profiles.get(
                away, {}).get("xg_over25_rate")
            hp_hist_over25 = profiles[home].get("over25_rate")
            ap_hist_over25 = profiles[away].get("over25_rate")

        except Exception as e:
            print(f"  [SKIP] {home} vs {away}: {e}")
            continue

        total_goals = m["FTHG"] + m["FTAG"]
        actual_over25 = total_goals > 2.5

        rows.append({
            "fixture": f"{home} vs {away}", "date": m["Date"],
            "data_source": data_source,
            "total_xg": total_xg,
            "poisson_over25": round(poisson_over25(total_xg), 3),
            "model_over25_final": real_final_over25,
            "model_over25_stage_b": goals_direct["over25"],
            "home_xg_over25_rate": home_xg_over25_rate,
            "away_xg_over25_rate": away_xg_over25_rate,
            "hp_hist_over25_rate": hp_hist_over25,
            "ap_hist_over25_rate": ap_hist_over25,
            "actual_over25": actual_over25,
        })

    if not rows:
        print("[WARN] No fixtures in bucket -- check snapshot/season files.")
        return

    n = len(rows)
    mean_total_xg = sum(r["total_xg"] for r in rows) / n
    mean_poisson = sum(r["poisson_over25"] for r in rows) / n
    mean_model_b = sum(r["model_over25_stage_b"] for r in rows) / n
    mean_model_final = sum(r["model_over25_final"] for r in rows) / n
    actual_rate = sum(1 for r in rows if r["actual_over25"]) / n

    print("=" * 118)
    print(
        f"OVER25 INPUT BREAKDOWN -- {n} fixtures in [{args.bucket_low}, {args.bucket_high}) bucket")
    print("=" * 118)
    print(f"{'Fixture':<28}{'src':<6}{'tot_xg':>8}{'poisson':>9}{'model_B':>9}{'model_C':>9}"
          f"{'hXgRate':>9}{'aXgRate':>9}{'hHistR':>8}{'aHistR':>8}{'actual':>8}")
    print("-" * 118)
    for r in rows:
        print(f"{r['fixture']:<28}{r['data_source']:<6}{r['total_xg']:>8.2f}"
              f"{r['poisson_over25']:>9.3f}{r['model_over25_stage_b']:>9.3f}"
              f"{r['model_over25_final']:>9.3f}"
              f"{str(r['home_xg_over25_rate']):>9}{str(r['away_xg_over25_rate']):>9}"
              f"{str(r['hp_hist_over25_rate']):>8}{str(r['ap_hist_over25_rate']):>8}"
              f"{('OVER' if r['actual_over25'] else 'under'):>8}")

    print("\n" + "=" * 118)
    print("SUMMARY -- averages across all bucket fixtures")
    print("=" * 118)
    print(
        f"  Mean total_xg (home_xg + away_xg):              {mean_total_xg:.3f}")
    print(f"  Mean POISSON-implied over25 probability:        {mean_poisson:.3f}  "
          f"(independent reference, from total_xg only)")
    print(
        f"  Mean model blend over25 (pre-mgr/formation):     {mean_model_b:.3f}")
    print(
        f"  Mean model FINAL over25 (post all adjustments):  {mean_model_final:.3f}")
    print(
        f"  ACTUAL over25 rate (real outcomes):              {actual_rate:.3f}")

    print("\n" + "=" * 118)
    print("READING THIS")
    print("=" * 118)
    gap_poisson_vs_actual = mean_poisson - actual_rate
    gap_poisson_vs_model = mean_model_final - mean_poisson
    print(
        f"Gap: Poisson reference vs ACTUAL outcome rate:   {gap_poisson_vs_actual:+.3f}\n"
        f"Gap: model's final over25 vs Poisson reference:  {gap_poisson_vs_model:+.3f}\n\n"
    )
    if abs(gap_poisson_vs_actual) <= 0.05 and abs(gap_poisson_vs_model) >= 0.08:
        print(
            "HYPOTHESIS A SUPPORTED: the Poisson reference (built only from total_xg)\n"
            "lands close to the ACTUAL outcome rate, meaning total_xg itself is\n"
            "reasonably calibrated. The gap is being introduced AFTER that point --\n"
            "most likely xg_scraper.py's derive_market_rates() linear formula\n"
            "(xg_over25_rate = min(total_xg / 5.0, 0.95), which has no statistical\n"
            "basis vs. the Poisson relationship), and/or the historical over25_rate\n"
            "fields in team_profiles_asof_24-25.json running independently high.\n"
            "Compare the hXgRate/aXgRate columns above against what Poisson would\n"
            "imply for each team's own xG to see the /5.0 formula's distortion directly."
        )
    elif abs(gap_poisson_vs_model) <= 0.05 and abs(gap_poisson_vs_actual) >= 0.08:
        print(
            "HYPOTHESIS B SUPPORTED: the Poisson reference lands close to the MODEL's\n"
            "own final over25 rate, not the actual outcome rate -- meaning total_xg\n"
            "itself is already too high for these fixtures. The rate-conversion\n"
            "formulas are behaving reasonably given their input; the input (xG\n"
            "magnitudes from xg_profiles_asof_24-25.json / xg_scraper.py's season\n"
            "weighting) is what's inflated. Worth checking the XG_WEIGHTS blend in\n"
            "xg_scraper.py's build_xg_profiles() and whether the raw Understat CSVs\n"
            "themselves are being read/weighted correctly for this snapshot."
        )
    else:
        print(
            "MIXED: neither gap is clearly small, meaning both the xG magnitudes AND\n"
            "the rate-conversion formulas may be contributing something to the\n"
            "overconfidence, or the effects are partially offsetting. Look at the\n"
            "per-fixture table above -- particularly whether hXgRate/aXgRate values\n"
            "are systematically higher than what each team's own total_xg would\n"
            "imply via Poisson, which would isolate the formula issue even in a\n"
            "mixed aggregate picture."
        )


if __name__ == "__main__":
    main()
