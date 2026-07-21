"""
diagnose_result_disagreement.py

DIAGNOSTIC ONLY — calls your real match_predictor.py / epl_elo.py
functions directly, plus reuses the already-proven-in-sync reproduction
helpers from diagnose_stacking.py rather than re-deriving them a third
time. Does not change predict_result() or any other model file.

WHY THIS EXISTS
----------------
After the HOME_ADVANTAGE double-counting fix, away_win's calibration
buckets went fully clean, but home_win's 20-30% (n=23, gap -21.1%) and
30-40% (n=29, gap -11.5%) buckets barely moved. Comparing two sample
fixtures from diagnose_stacking.py's backtest-snapshot run pointed at a
specific, different mechanism:

    Sheffield Utd vs Man City:  Elo=0.060  ->  final=0.068  (barely moves)
    Ipswich vs Man City:        Elo=0.122  ->  final=0.227  (nearly doubles)

Elo is opponent-aware -- it knows exactly who's on the other side of the
pitch. home_win_rate and form_score are NOT opponent-aware -- they're a
team's average performance across ALL opponents faced, home or away,
strong or weak. When a mediocre home team draws an elite away side,
Elo correctly craters. hist_home/form_home don't move nearly as much,
because they don't know who the away team is. The 30%+20%=50% blend
weight given to these opponent-blind signals can drag the final number
back toward that team's season-average, even against a signature elite
opponent.

This script doesn't assume that's the whole story -- it tests it
directly: bucket ALL 190 real holdout fixtures by how much Elo and the
hist/form blend disagree about the home team, then check whether the
high-disagreement bucket is where the overconfidence actually
concentrates.

HOW IT WORKS
------------
For each of the 190 real 2024/25 holdout-half fixtures (same CSV rows,
same season the calibration report's numbers came from):

  1. Reuses stage_a_elo_only(), raw_hist_components(), raw_form_components()
     from diagnose_stacking.py — these are the already-proven-in-sync
     reproduction of predict_result()'s internal stages. Imported, not
     copied, so there is exactly one place that can drift out of sync
     with predict_result(), not three.
  2. Computes hist_form_home = a weighted average of hist_home and
     form_home using their ACTUAL relative weights inside predict_result()
     (0.30 and 0.20 out of the combined 0.50 non-Elo weight, i.e. 0.6/0.4
     of each other). KEEP IN SYNC: if predict_result()'s blend weights
     (currently 0.50/0.30/0.20) ever change, this ratio must be updated
     to match.
  3. signed_disagreement = hist_form_home - elo_home. Positive means
     hist/form rate the home team MORE favourably than Elo does (the
     exact direction the Ipswich example showed); negative means Elo
     is more optimistic about the home team than hist/form.
  4. Calls the REAL predict_match() for the actual final home_win/
     away_win probability (post H2H, post manager/formation -- the
     number that actually gets bet on), and compares against the
     real match result from the CSV.
  5. Splits all 190 fixtures into three equal-sized buckets (terciles)
     by signed_disagreement, and reports predicted vs actual home_win
     rate (and away_win rate) per bucket -- same gap calculation as
     calibration.py.

If the high-disagreement tercile shows a much worse home_win gap than
the low-disagreement tercile, that's direct, dataset-wide confirmation
of the opponent-blindness hypothesis, not just a two-fixture anecdote.

USAGE
-----
    python src/utils/diagnose_result_disagreement.py

    # non-default paths, if your snapshot files ever move:
    python src/utils/diagnose_result_disagreement.py --csv data/raw/24-25.csv --profiles data/team_profiles_asof_24-25.json --h2h data/h2h_asof_24-25.json --elo data/epl_elo_ratings_asof_24-25.json

Defaults to the SAME snapshot files and the SAME "last 190 matches"
final-holdout half that backtester_v4.py and calibration.py use, so
these numbers are directly comparable to the calibration report.
"""

# isort: skip_file
#
# LOAD-BEARING, same reason as diagnose_stacking.py -- see that file's
# header comment for the full explanation. Keeps sys.path.insert()
# below from being hoisted above the `from src...` imports by an
# editor's import-sorter.

import argparse
import csv
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def load_season_matches(csv_path: str) -> list:
    """
    Loads HomeTeam/AwayTeam/FTHG/FTAG from a raw season CSV -- same
    columns/parsing as epl_elo.py's initialise_ratings(). Returns
    matches in file order (assumed chronological, same assumption
    backtester_v4.py makes when it splits "first 190" / "last 190").
    """
    matches = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("HomeTeam") or not row.get("FTHG"):
                continue
            try:
                matches.append({
                    "home": row["HomeTeam"],
                    "away": row["AwayTeam"],
                    "hg":   int(float(row["FTHG"])),
                    "ag":   int(float(row["FTAG"])),
                })
            except (ValueError, TypeError):
                continue
    return matches


def actual_result(hg: int, ag: int) -> str:
    if hg > ag:
        return "home_win"
    if hg < ag:
        return "away_win"
    return "draw"


def ensure_team_profiles(profiles: dict, teams: list, active_force_promoted: set) -> dict:
    """Same fallback reproduction as diagnose_stacking.py -- KEEP IN
    SYNC with predict_match()'s missing-team fallback logic if that
    changes."""
    from src.models.match_predictor import _build_league_average, PROMOTED_TEAM_PROFILES

    missing = [t for t in teams if t not in profiles or t in active_force_promoted]
    if missing:
        league_avg = _build_league_average(profiles)
        for team in missing:
            if team in active_force_promoted and team in PROMOTED_TEAM_PROFILES:
                profiles[team] = PROMOTED_TEAM_PROFILES[team].copy()
            else:
                profiles[team] = league_avg.copy()
    return profiles


def analyse_fixture(home: str, away: str, profiles: dict, h2h_data: dict,
                    elo_path: str, profiles_path: str, h2h_path: str) -> dict:
    """
    Computes signed disagreement for one fixture and gets the REAL
    final predict_match() home_win/away_win for comparison against the
    actual result. Reuses diagnose_stacking.py's already-in-sync
    stage_a_elo_only/raw_hist_components/raw_form_components rather
    than re-deriving them.
    """
    from src.utils.diagnose_stacking import (
        stage_a_elo_only, raw_hist_components, raw_form_components,
    )
    from src.models.match_predictor import predict_match

    elo = stage_a_elo_only(home, away, elo_path)
    hist = raw_hist_components(home, away, profiles)
    form = raw_form_components(home, away, profiles)

    # KEEP IN SYNC: 0.30/0.20 are predict_result()'s actual hist/form
    # blend weights (out of a combined 0.50 non-Elo share). If those
    # weights change in predict_result(), update this ratio to match.
    hist_form_home = (hist["hist_home"] * 0.30 +
                      form["form_home"] * 0.20) / 0.50
    hist_form_away = (hist["hist_away"] * 0.30 +
                      form["form_away"] * 0.20) / 0.50

    signed_disagreement_home = round(hist_form_home - elo["home_win"], 4)
    signed_disagreement_away = round(hist_form_away - elo["away_win"], 4)

    full_pred = predict_match(
        home, away,
        profiles_path=profiles_path, h2h_path=h2h_path, elo_path=elo_path,
        apply_availability=False,   # backtest condition, matches backtester_v4.py
        force_promoted=set(),       # backtest condition, matches backtester_v4.py
    )

    return {
        "elo_home": elo["home_win"], "elo_away": elo["away_win"],
        "hist_form_home": round(hist_form_home, 3),
        "hist_form_away": round(hist_form_away, 3),
        "signed_disagreement_home": signed_disagreement_home,
        "signed_disagreement_away": signed_disagreement_away,
        "final_home_win": full_pred["result"]["home_win"],
        "final_away_win": full_pred["result"]["away_win"],
    }


def bucket_and_report(rows: list, sort_key: str, pred_key: str, actual_key: str, label: str):
    """
    Splits rows into three equal-sized terciles by sort_key, reports
    predicted vs actual hit rate per tercile -- same gap definition as
    calibration.py (actual - predicted; negative = overconfident).
    """
    sorted_rows = sorted(rows, key=lambda r: r[sort_key])
    n = len(sorted_rows)
    third = n // 3
    terciles = [
        ("LOW disagreement", sorted_rows[:third]),
        ("MID disagreement", sorted_rows[third:2 * third]),
        ("HIGH disagreement", sorted_rows[2 * third:]),
    ]

    print(f"\n{label}")
    print(f"  {'tercile':<20} {'n':>4} {'avg_disagree':>13} {'avg_predicted':>14} "
          f"{'actual_rate':>12} {'gap':>8}  flag")
    for name, bucket in terciles:
        bn = len(bucket)
        if bn == 0:
            continue
        avg_disagree = sum(r[sort_key] for r in bucket) / bn
        avg_pred = sum(r[pred_key] for r in bucket) / bn
        actual_rate = sum(1 for r in bucket if r[actual_key]) / bn
        gap = actual_rate - avg_pred
        flag = ("overconfident" if gap < -0.05 else
                "underconfident" if gap > 0.05 else "ok")
        print(f"  {name:<20} {bn:>4} {avg_disagree:>+13.3f} {avg_pred*100:>13.1f}% "
              f"{actual_rate*100:>11.1f}% {gap*100:>+7.1f}%  {flag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="data/raw/24-25.csv",
                        help="raw season CSV (HomeTeam/AwayTeam/FTHG/FTAG columns)")
    parser.add_argument(
        "--profiles", default="data/team_profiles_asof_24-25.json")
    parser.add_argument("--h2h", default="data/h2h_asof_24-25.json")
    parser.add_argument(
        "--elo", default="data/epl_elo_ratings_asof_24-25.json")
    parser.add_argument("--half", choices=["validation", "final", "both"], default="final",
                        help="which 190-match half to analyse -- 'final' matches "
                        "calibration.py's reported numbers")
    args = parser.parse_args()

    from src.models.match_predictor import load_profiles, load_h2h, FORCE_PROMOTED

    all_matches = load_season_matches(args.csv)
    half_n = len(all_matches) // 2
    if args.half == "validation":
        matches = all_matches[:half_n]
    elif args.half == "final":
        matches = all_matches[half_n:]
    else:
        matches = all_matches

    print(f"csv={args.csv}  half={args.half}  matches={len(matches)}\n")

    profiles = load_profiles(args.profiles)
    h2h_data = load_h2h(args.h2h)

    rows = []
    skipped = []
    for m in matches:
        home, away = m["home"], m["away"]
        try:
            profiles = ensure_team_profiles(
                profiles, [home, away], FORCE_PROMOTED)
            analysis = analyse_fixture(
                home, away, profiles, h2h_data,
                args.elo, args.profiles, args.h2h)
        except KeyError as e:
            skipped.append(f"{home} vs {away} (missing key: {e})")
            continue

        result = actual_result(m["hg"], m["ag"])
        rows.append({
            "fixture": f"{home} vs {away}",
            "signed_disagreement_home": analysis["signed_disagreement_home"],
            "signed_disagreement_away": analysis["signed_disagreement_away"],
            "final_home_win": analysis["final_home_win"],
            "final_away_win": analysis["final_away_win"],
            "was_home_win": result == "home_win",
            "was_away_win": result == "away_win",
        })

    print(f"Analysed: {len(rows)} fixtures  (skipped: {len(skipped)})")
    if skipped:
        print("  Skipped fixtures (missing profile/team data):")
        for s in skipped[:10]:
            print(f"    - {s}")
        if len(skipped) > 10:
            print(f"    ... and {len(skipped) - 10} more")

    bucket_and_report(
        rows, "signed_disagreement_home", "final_home_win", "was_home_win",
        "HOME_WIN calibration by hist/form-vs-Elo disagreement "
        "(positive = hist/form more favourable to home team than Elo)")

    bucket_and_report(
        rows, "signed_disagreement_away", "final_away_win", "was_away_win",
        "AWAY_WIN calibration by hist/form-vs-Elo disagreement "
        "(positive = hist/form more favourable to away team than Elo)")

    print("\n" + "=" * 100)
    print("READING THIS")
    print("=" * 100)
    print(
        "If the HIGH disagreement tercile shows a substantially worse (more negative)\n"
        "gap than the LOW tercile for home_win, that's dataset-wide confirmation of the\n"
        "opponent-blindness hypothesis: hist_home/form_home don't know who the away\n"
        "team is, so when they rate a home team well above what Elo (which DOES know)\n"
        "says against this specific opponent, the blend drags the final prediction back\n"
        "up toward that team's season-average, and calibration suffers exactly there.\n\n"
        "If the gap is roughly flat across all three terciles instead, the disagreement\n"
        "magnitude isn't the driver, and the home_win 20-40% overconfidence has a\n"
        "different, still-unidentified cause -- don't reweight the blend based on this\n"
        "hypothesis in that case.\n"
    )


if __name__ == "__main__":
    main()
