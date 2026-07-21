"""
diagnose_hist_form_vs_elo_full.py

DIAGNOSTIC ONLY — reuses the ALREADY-VERIFIED reproduction functions
from diagnose_result_stacking.py (raw_hist_components, raw_form_components,
stage_a_elo_only) rather than re-deriving the formulas a second time.
Those functions were confirmed in-sync with the real predict_result()
via that script's own SYNC WARNING check, so reusing them here is safer
than a fresh reproduction that could quietly drift. Does not change any
model file.

WHY THIS EXISTS
----------------
Two things are now confirmed:
  1. Elo-only is itself somewhat overconfident in home_win 30-40%
     (diagnose_elo_only_calibration.py).
  2. The blend pulls a specific extra set of fixtures INTO the 20-40%
     range from below (diagnose_elo_vs_blend_matched.py's "moved in"
     group: n=13, 0/13 hit rate).
  3. That "moved in" group is NOT dominated by 1-2 teams with bad data
     (diagnose_team_dominance_check.py: mismatches between snapshot and
     same-season actuals go in BOTH directions across many teams, no
     shared data-quality story) -- 12 of 15 home teams in the filtered
     set have a negative gap, which looks structural.

The original "opponent-blindness" hypothesis (hist_home/form_home don't
know who the away team is, so they can't drop as low as Elo does for a
huge mismatch) was tested and ruled out -- but that test bucketed
fixtures into disagreement TERCILES, which the script's own output
flagged as confounded with underdog-ness (avg_predicted dropped almost
monotonically across terciles). This script re-tests the same
underlying idea a cleaner way: instead of bucketing by disagreement and
checking calibration gap, it directly correlates (hist_home - elo_home)
and (form_home - elo_home) against elo_home itself, across ALL 190
fixtures continuously -- no terciles, so no bucket-induced confound to
hide or manufacture a trend.

If hist_home/form_home structurally sit further above elo_home
specifically as elo_home gets smaller (i.e. the bigger the underdog, the
bigger the pull-up), that's the opponent-blindness mechanism confirmed
directly and quantified -- not a story about disagreement buckets, a
direct value-vs-value relationship.

HOW IT WORKS
------------
For all 190 fixtures in the final holdout half:
    - elo_home       (real predict_result_elo(), stage_a_elo_only())
    - hist_home       (raw_hist_components(), pre-normalization)
    - form_home       (raw_form_components(), pre-normalization)
    - delta_hist = hist_home - elo_home
    - delta_form = form_home - elo_home
Prints:
    - A decile table: fixtures bucketed by elo_home into 10 deciles,
      avg elo_home / avg delta_hist / avg delta_form per decile, so the
      relationship (if any) is visible as a trend across the deciles.
    - Pearson correlation coefficient between elo_home and delta_hist,
      and between elo_home and delta_form, computed with plain Python
      (no numpy dependency) -- a negative correlation means "the
      smaller elo_home is, the bigger the pull-up", i.e. the mechanism
      the handover note's "READING THIS" section flagged as worth
      checking directly.

USAGE
-----
    python src/utils/diagnose_hist_form_vs_elo_full.py
"""

# isort: skip_file
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def pearson_corr(xs: list, ys: list) -> float:
    """Plain-Python Pearson correlation, no numpy dependency."""
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = (var_x * var_y) ** 0.5
    if denom == 0:
        return 0.0
    return cov / denom


def main():
    from src.utils.backtester_v4 import (
        TEST_SEASON_FILE, VALIDATION_FRACTION, SNAPSHOT_ELO,
        SNAPSHOT_PROFILES, load_csv_file, get_actuals,
    )
    from src.models.match_predictor import load_profiles, FORCE_PROMOTED, _build_league_average, PROMOTED_TEAM_PROFILES
    # NOTE: the script whose own docstring calls itself
    # "diagnose_result_stacking.py" is actually saved on disk as
    # diagnose_stacking.py -- it overwrote the original cards/goals
    # script of that name rather than being saved alongside it under
    # its own filename (see handover note, process rule 9). Importing
    # from the actual filename, not the name in its docstring.
    from src.utils.diagnose_stacking import (
        stage_a_elo_only, raw_hist_components, raw_form_components,
    )

    print("=" * 100)
    print("  hist_home / form_home vs elo_home — continuous relationship, all 190 fixtures")
    print("=" * 100)

    all_matches = load_csv_file(TEST_SEASON_FILE)
    if not all_matches:
        print(f"[ERROR] No matches loaded from {TEST_SEASON_FILE}.")
        return

    split_idx = int(len(all_matches) * VALIDATION_FRACTION)
    final_matches = all_matches[split_idx:]
    print(f"\nFinal holdout half: {len(final_matches)} matches\n")

    profiles = load_profiles(SNAPSHOT_PROFILES)

    def ensure_team_profiles(profiles, teams, active_force_promoted):
        """Same fallback reproduction used by diagnose_result_stacking.py's
        own ensure_team_profiles() -- KEEP IN SYNC with match_predictor.py's
        predict_match() missing-team logic."""
        missing = [
            t for t in teams if t not in profiles or t in active_force_promoted]
        if missing:
            league_avg = _build_league_average(profiles)
            for team in missing:
                if team in active_force_promoted and team in PROMOTED_TEAM_PROFILES:
                    profiles[team] = PROMOTED_TEAM_PROFILES[team].copy()
                else:
                    profiles[team] = league_avg.copy()
        return profiles

    rows = []
    skipped = 0

    for m in final_matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        actuals = get_actuals(m)

        try:
            profiles = ensure_team_profiles(
                profiles, [home, away], FORCE_PROMOTED)
            elo = stage_a_elo_only(home, away, SNAPSHOT_ELO)
            hist = raw_hist_components(home, away, profiles)
            form = raw_form_components(home, away, profiles)
        except Exception as e:
            skipped += 1
            print(f"  [SKIP] {home} vs {away}: {e}")
            continue

        rows.append({
            "fixture": f"{home} vs {away}",
            "elo_home": elo["home_win"],
            "hist_home": hist["hist_home"],
            "form_home": form["form_home"],
            "delta_hist": round(hist["hist_home"] - elo["home_win"], 4),
            "delta_form": round(form["form_home"] - elo["home_win"], 4),
            "actual": actuals["home_win"],
        })

    print(f"Scored {len(rows)} fixtures, skipped={skipped}\n")

    # Decile table by elo_home
    rows_sorted = sorted(rows, key=lambda r: r["elo_home"])
    n = len(rows_sorted)
    decile_size = max(1, n // 10)

    print(f"{'Elo decile':<14} {'n':>4} {'avg_elo_home':>13} {'avg_delta_hist':>15} {'avg_delta_form':>15}")
    print("-" * 70)
    for i in range(0, n, decile_size):
        chunk = rows_sorted[i:i + decile_size]
        if not chunk:
            continue
        avg_elo = sum(r["elo_home"] for r in chunk) / len(chunk)
        avg_dh = sum(r["delta_hist"] for r in chunk) / len(chunk)
        avg_df = sum(r["delta_form"] for r in chunk) / len(chunk)
        lo_label = f"{avg_elo*100:.0f}%ish"
        print(f"{lo_label:<14} {len(chunk):>4} {avg_elo*100:>12.1f}% "
              f"{avg_dh*100:>+14.1f}% {avg_df*100:>+14.1f}%")

    elo_vals = [r["elo_home"] for r in rows]
    delta_hist_vals = [r["delta_hist"] for r in rows]
    delta_form_vals = [r["delta_form"] for r in rows]

    corr_hist = pearson_corr(elo_vals, delta_hist_vals)
    corr_form = pearson_corr(elo_vals, delta_form_vals)

    print(
        f"\n  Pearson correlation, elo_home vs delta_hist (hist_home - elo_home): {corr_hist:+.3f}")
    print(
        f"  Pearson correlation, elo_home vs delta_form (form_home - elo_home): {corr_form:+.3f}")

    print("\n" + "=" * 100)
    print("READING THIS")
    print("=" * 100)
    print(
        "A negative correlation means: the SMALLER elo_home is (the bigger an underdog\n"
        "Elo thinks the home team is), the LARGER the positive gap between hist_home/\n"
        "form_home and elo_home -- i.e. hist/form structurally refuse to go as low as\n"
        "Elo does for lopsided matchups, and pull the blended number back up. A\n"
        "correlation near 0 (or positive) means no such structural relationship exists\n"
        "and the earlier ruled-out opponent-blindness idea really is dead, full stop --\n"
        "in which case the 'moved in' fixtures from the matched-pairs script are better\n"
        "explained by something else (e.g. draw_base or form_score's fixed +0.25/+0.5\n"
        "additive constants acting as a soft floor, independent of the opponent).\n\n"
        "The decile table shows the SHAPE of this relationship directly -- worth checking\n"
        "whether the effect is roughly linear across all deciles (a genuine structural\n"
        "issue, worth a formula fix) or concentrated only in the bottom 1-2 deciles (a\n"
        "narrower edge-case, e.g. only relevant for the most extreme mismatches like\n"
        "promoted teams away at the top 4).\n"
    )


if __name__ == "__main__":
    main()
