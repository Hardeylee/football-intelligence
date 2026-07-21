"""
diagnose_team_dominance_check.py

DIAGNOSTIC ONLY — reuses backtester_v4.py's real predict_fixture() and
epl_elo.predict_result_elo(), plus match_predictor.load_profiles() to
read raw snapshot values. Does not change any model file.

WHY THIS EXISTS
----------------
diagnose_elo_vs_blend_matched.py found that of the 13 fixtures the
blend pushes INTO the home_win 20-40% range from outside it, Everton
is the home team in 4 and Leicester in 2 -- 6 of 13 (46%), all losses,
0/13 hit rate for the group overall. That's the "team-level dominance"
possibility (item 4 in the handover note) surfacing directly, not
necessarily a formula problem affecting fixtures broadly.

This script does two things to separate a DATA problem (this team's
home_win_rate/form_score in the snapshot is simply wrong) from a
FORMULA problem (the value is accurate but the blend over-weights it):

  1. Aggregates every fixture from the same filtered 20-40% set by HOME
     TEAM, so the concentration seen manually above is quantified
     (n, avg predicted, actual hit rate, gap) rather than eyeballed.
  2. For any team appearing 3+ times, prints that team's raw
     home_win_rate / away_win_rate / draw_rate / form_score straight
     from the snapshot profile file (data/team_profiles_asof_24-25.json
     by default, same file predict_result() actually reads), alongside
     an independent sanity check: that team's ACTUAL home win/draw/loss
     rate computed directly from this same 2024/25 season's raw
     fixture list (both validation and final halves).

CAVEAT ON THE SANITY CHECK, read before trusting it:
The snapshot profile is meant to reflect the team's form BEFORE the
24-25 season (that's the whole point of "asof_24-25" -- no lookahead).
The actual-rate this script computes is FROM the 24-25 season itself,
because that's the only data conveniently available to compare against
without knowing the exact seasons build_snapshot_profiles.py used to
construct the snapshot. So a mismatch here is only a same-season
"does this team's snapshot line up with how they actually played that
year" gut check -- not a rigorous training-period verification. If the
mismatch is large, the next step is finding build_snapshot_profiles.py
and checking its actual source seasons directly, the same way the
Championship xGA values were cross-verified against FootyStats earlier
this project.

USAGE
-----
    python src/utils/diagnose_team_dominance_check.py
"""

# isort: skip_file
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

RANGE_LO = 0.20
RANGE_HI = 0.40
MIN_APPEARANCES_FOR_PROFILE_DUMP = 3


def in_range(x: float) -> bool:
    return RANGE_LO <= x < RANGE_HI


def elo_only_predict(home: str, away: str, elo_path: str) -> float:
    from src.models.epl_elo import load_ratings, predict_result_elo

    elo_ratings = load_ratings(elo_path) if elo_path else load_ratings()
    pred = predict_result_elo(home, away, elo_ratings)
    return pred["home_win"]


def compute_actual_home_record(team: str, all_matches: list) -> dict:
    """
    Independent same-season sanity check -- NOT a training-period
    verification, see module docstring caveat. Scans every fixture in
    the full 2024/25 season (both halves) where `team` played at home
    and computes their real win/draw/loss rate directly from FTR.
    """
    home_matches = [m for m in all_matches if m["HomeTeam"] == team]
    n = len(home_matches)
    if n == 0:
        return {"n": 0}
    wins = sum(1 for m in home_matches if m["FTR"] == "H")
    draws = sum(1 for m in home_matches if m["FTR"] == "D")
    losses = sum(1 for m in home_matches if m["FTR"] == "A")
    return {
        "n": n,
        "actual_home_win_rate": round(wins / n, 3),
        "actual_home_draw_rate": round(draws / n, 3),
        "actual_home_loss_rate": round(losses / n, 3),
    }


def main():
    from src.utils.backtester_v4 import (
        TEST_SEASON_FILE, VALIDATION_FRACTION, SNAPSHOT_ELO,
        SNAPSHOT_PROFILES, load_csv_file, predict_fixture, get_actuals,
    )
    from src.models.match_predictor import load_profiles

    print("=" * 100)
    print("  TEAM DOMINANCE CHECK — home_win 20-40% bucket, grouped by home team")
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
            continue

        full_pred = predict_fixture(home, away, m.get("Referee", ""))
        if not full_pred or "_error" in full_pred:
            skipped += 1
            continue

        full_hw = full_pred["home_win"]

        if not (in_range(elo_hw) or in_range(full_hw)):
            continue

        rows.append({
            "home": home, "away": away,
            "elo_hw": elo_hw, "full_hw": full_hw,
            "delta": round(full_hw - elo_hw, 3),
            "actual": actuals["home_win"],
            "moved_in": (not in_range(elo_hw)) and in_range(full_hw),
        })

    print(
        f"Scored {len(rows)} fixtures touching the 20-40% range, skipped={skipped}\n")

    # Group by home team
    by_team = {}
    for r in rows:
        by_team.setdefault(r["home"], []).append(r)

    team_stats = []
    for team, group in by_team.items():
        n = len(group)
        avg_pred = sum(r["full_hw"] for r in group) / n
        hit_rate = sum(1 for r in group if r["actual"]) / n
        moved_in_n = sum(1 for r in group if r["moved_in"])
        team_stats.append({
            "team": team, "n": n,
            "avg_predicted": round(avg_pred, 3),
            "actual_hit_rate": round(hit_rate, 3),
            "gap": round(hit_rate - avg_pred, 3),
            "moved_in_n": moved_in_n,
        })

    team_stats.sort(key=lambda t: t["n"], reverse=True)

    print(f"{'Home team':<20} {'n':>3} {'moved_in':>9} {'avg_pred':>9} {'actual':>8} {'gap':>8}")
    print("-" * 65)
    for t in team_stats:
        print(f"{t['team']:<20} {t['n']:>3} {t['moved_in_n']:>9} "
              f"{t['avg_predicted']*100:>8.1f}% {t['actual_hit_rate']*100:>7.1f}% "
              f"{t['gap']*100:>+7.1f}%")

    flagged = [t for t in team_stats if t["n"]
               >= MIN_APPEARANCES_FOR_PROFILE_DUMP]

    print("\n" + "=" * 100)
    print(
        f"RAW PROFILE CHECK — teams appearing {MIN_APPEARANCES_FOR_PROFILE_DUMP}+ times in the 20-40% bucket")
    print("=" * 100)

    if not flagged:
        print(f"\n  No team appeared {MIN_APPEARANCES_FOR_PROFILE_DUMP}+ times -- "
              f"the bucket is NOT dominated by a small number of teams. "
              f"This weakens the team-level data-quality hypothesis.")
    else:
        profiles = load_profiles(SNAPSHOT_PROFILES)
        for t in flagged:
            team = t["team"]
            print(f"\n  {team}  (appears {t['n']}x in the filtered set, "
                  f"{t['moved_in_n']}x specifically moved-in-by-blend)")

            p = profiles.get(team)
            if not p:
                print(f"    [WARN] {team} not found in {SNAPSHOT_PROFILES} -- "
                      f"likely running through the league-average or promoted-team "
                      f"fallback in predict_match(), not its own real profile at all.")
                continue

            print(f"    snapshot profile:  home_win_rate={p.get('home_win_rate')}  "
                  f"away_win_rate={p.get('away_win_rate')}  "
                  f"draw_rate={p.get('draw_rate')}  form_score={p.get('form_score')}")

            actual = compute_actual_home_record(
                team, final_matches + all_matches[:split_idx])
            if actual["n"] == 0:
                print(f"    [WARN] no home matches found for {team} in "
                      f"{TEST_SEASON_FILE} at all -- can't sanity-check.")
                continue
            print(f"    same-season actual (n={actual['n']} home matches, 24-25 full season):  "
                  f"win_rate={actual['actual_home_win_rate']}  "
                  f"draw_rate={actual['actual_home_draw_rate']}  "
                  f"loss_rate={actual['actual_home_loss_rate']}")

            snap_hwr = p.get("home_win_rate")
            if snap_hwr is not None:
                diff = round(snap_hwr - actual["actual_home_win_rate"], 3)
                flag = "⚠ LARGE MISMATCH" if abs(
                    diff) >= 0.10 else "roughly consistent"
                print(f"    snapshot vs same-season actual home_win_rate delta: "
                      f"{diff:+.3f}  ({flag})")

    print("\n" + "=" * 100)
    print("READING THIS")
    print("=" * 100)
    print(
        "If one or two teams account for most of the n in the table above, and their\n"
        "snapshot home_win_rate/form_score sits well above their same-season actual\n"
        "home record (LARGE MISMATCH flag) -- that's a real, cheap-to-fix data problem\n"
        "with THIS team's profile, not a general blend-weighting bug. Worth checking\n"
        "against a second source (FootyStats etc.) the same way the promoted-team\n"
        "Championship values were, before editing the snapshot file directly.\n\n"
        "If the flagged teams' snapshot values look roughly consistent with their actual\n"
        "same-season record -- the data is fine and it's genuinely a blend-formula issue\n"
        "(hist_home/form_home weighting these mid-table teams' rates too heavily relative\n"
        "to Elo when Elo already has a confident read on the matchup). That points back at\n"
        "predict_result()'s 30%/20% weighting, not at any one team's data.\n\n"
        "If no team appears 3+ times, the 'team dominance' hypothesis itself is probably\n"
        "not the main story here and the upstream-Elo explanation from the 'stayed in'\n"
        "group (previous script) is likely doing more of the work.\n"
    )


if __name__ == "__main__":
    main()
