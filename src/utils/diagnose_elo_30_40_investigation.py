"""
diagnose_elo_30_40_investigation.py

DIAGNOSTIC ONLY -- calls real epl_elo.py / backtester_v4.py functions
directly (load_ratings, predict_result_elo, load_csv_file, and the
validation/final chronological split). Does not modify epl_elo.py,
match_predictor.py, or backtester_v4.py. Safe to run against snapshot
data.

WHY THIS EXISTS
----------------
From the current handover note: home_win 30-40% is the last unresolved
calibration problem, already independently confirmed to live UPSTREAM
IN ELO ITSELF, not in the blend (Elo-only gap -12.4% roughly matches
full-pipeline gap -11.5%/-12.3% at this bucket -- see
diagnose_elo_only_calibration.py from the prior session). Three
explanations are already ruled out (blend introduction, opponent-
blindness, team-level stale data). Four hypotheses remain, queued but
untested:

    1. Rating separation -- are ratings simply noisier/less separated
       for the mid-table teams that tend to land in this bucket?
    2. HOME_ADVANTAGE=100 (flat, applied uniformly) -- miscalibrated
       specifically for the matchups that produce a 30-40% home_win
       prediction?
    3. draw_prob = max(0.10, 0.28 - rating_diff/2000) -- is the 0.10
       floor wrong for the rating gaps in this bucket?
    4. Team concentration -- re-run the dominance check, but scoped to
       THIS bucket specifically (the prior dominance check was scoped
       to the blend's "moved-in" fixtures, not this bucket).

This script tests all four in one pass, using the SAME chronological
validation/final split as backtester_v4.py -- constants for hypotheses
2 and 3 are derived from the validation half only and graded on the
final half, mirroring this session's own out-of-sample discipline for
Candidate C (deriving a fix's constants from the same data used to
grade it is circular even when some other split exists for thresholds).

Per this session's own new learning ("bucket-level calibration
comparisons get noisy at n=15-30 -- use Brier score as the tie-
breaker"), every hypothesis test below reports Brier score alongside
the bucket table, and hypothesis 1 uses a continuous correlation check
rather than binning into quartiles as its primary evidence.

WHAT THIS SCRIPT DOES NOT DO
------------------------------
It does not change epl_elo.py. HOME_ADVANTAGE and the draw_prob floor
are hardcoded as module constants in the real predict_result_elo(), not
parameters -- so hypotheses 2 and 3 need a local reproduction of that
formula, parameterized, to grid-search over candidate values. That
reproduction is validated against the REAL predict_result_elo() at
default constants (HOME_ADVANTAGE=100, floor=0.10, base=0.28,
scale=2000) for every fixture before anything else runs -- if it
doesn't match, the SYNC WARNING at the top of the output says so and
the rest of the run should not be trusted.

USAGE
-----
    python src/utils/diagnose_elo_30_40_investigation.py

    # Point at a different Elo snapshot:
    python src/utils/diagnose_elo_30_40_investigation.py --elo data/epl_elo_ratings_asof_24-25.json
"""

# isort: skip_file
#
# ^ LOAD-BEARING, same reason as diagnose_stacking.py /
# diagnose_result_stacking.py -- keeps the sys.path.insert() below from
# being hoisted below a `from src...` import by an editor's
# import-sorter.

import argparse
import math
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

BUCKET_LO = 0.30
BUCKET_HI = 0.40


# ── Reproduction of predict_result_elo(), parameterized ─────────────
# Source of truth: src/models/epl_elo.py, expected_score() and
# predict_result_elo(). KEEP IN SYNC with that function. Parameterized
# on home_advantage/draw_floor/draw_base/draw_scale ONLY so hypotheses
# 2 and 3 below can grid-search them -- everything else (goal-diff
# multiplier logic doesn't apply here, this is prediction not update)
# is an exact copy of the real formula.
def repro_predict_result_elo(home_r: float, away_r: float,
                             home_advantage: float = 100,
                             draw_floor: float = 0.10,
                             draw_base: float = 0.28,
                             draw_scale: float = 2000) -> dict:
    def expected_score(a, b):
        return 1 / (1 + 10 ** ((b - a) / 400))

    home_adj = home_r + home_advantage
    exp_home = expected_score(home_adj, away_r)
    exp_away = expected_score(away_r, home_adj)

    rating_diff = abs(home_adj - away_r)
    draw_prob = max(draw_floor, draw_base - (rating_diff / draw_scale))

    home_win = exp_home * (1 - draw_prob / 2)
    away_win = exp_away * (1 - draw_prob / 2)

    total = home_win + draw_prob + away_win
    return {
        "home_win": home_win / total,
        "draw": draw_prob / total,
        "away_win": away_win / total,
        "rating_diff": rating_diff,
    }


def brier(preds_and_outcomes: list) -> float:
    """Standard Brier score: mean squared error of predicted prob
    against the binary outcome (1 if that outcome happened, else 0).
    No binning -- this is this session's own preferred tie-breaker."""
    if not preds_and_outcomes:
        return float("nan")
    return sum((p - o) ** 2 for p, o in preds_and_outcomes) / len(preds_and_outcomes)


def load_all_fixtures(elo_path: str):
    """Reuses backtester_v4.py's own CSV loader and chronological
    validation/final split so the population here is directly
    comparable to every other diagnostic and to the shipped fix's own
    verification -- not a separately-invented split."""
    from src.utils.backtester_v4 import (
        load_csv_file, TEST_SEASON_FILE, VALIDATION_FRACTION, SNAPSHOT_ELO,
    )
    from src.models.epl_elo import load_ratings, predict_result_elo

    resolved_elo_path = elo_path or SNAPSHOT_ELO
    matches = load_csv_file(TEST_SEASON_FILE)
    split_idx = int(len(matches) * VALIDATION_FRACTION)
    validation_matches = matches[:split_idx]
    final_matches = matches[split_idx:]

    ratings = load_ratings(resolved_elo_path)

    return validation_matches, final_matches, ratings, predict_result_elo, resolved_elo_path


def build_rows(matches: list, ratings: dict, real_predict_result_elo) -> list:
    """
    For every fixture: real elo-only prediction (via the actual
    function, not the reproduction), the reproduction's own output at
    default constants (for the sync check), rating_diff, and the
    actual result. Filters nothing yet -- bucket filtering happens
    downstream so callers can re-bucket under different hypotheses if
    needed.
    """
    rows = []
    for m in matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        home_r = ratings.get(home, 1500)
        away_r = ratings.get(away, 1500)

        real_pred = real_predict_result_elo(home, away, ratings)
        repro_pred = repro_predict_result_elo(home_r, away_r)

        rows.append({
            "date": m["Date"], "home": home, "away": away,
            "home_r": home_r, "away_r": away_r,
            "real_home_win": real_pred["home_win"],
            "real_draw": real_pred["draw"],
            "real_away_win": real_pred["away_win"],
            "repro_home_win": repro_pred["home_win"],
            "repro_draw": repro_pred["draw"],
            "rating_diff": repro_pred["rating_diff"],
            "actual_home": m["FTR"] == "H",
            "actual_draw": m["FTR"] == "D",
            "actual_away": m["FTR"] == "A",
        })
    return rows


def check_sync(rows: list) -> list:
    mismatches = []
    for r in rows:
        if abs(r["real_home_win"] - r["repro_home_win"]) > 0.002:
            mismatches.append(f"{r['home']} vs {r['away']} "
                              f"(real={r['real_home_win']:.4f} "
                              f"repro={r['repro_home_win']:.4f})")
    return mismatches


def bucket_table(rows: list, lo=BUCKET_LO, hi=BUCKET_HI) -> dict:
    in_bucket = [r for r in rows if lo <= r["real_home_win"] < hi]
    n = len(in_bucket)
    if n == 0:
        return {"n": 0}
    predicted_avg = sum(r["real_home_win"] for r in in_bucket) / n
    actual_rate = sum(r["actual_home"] for r in in_bucket) / n
    b = brier([(r["real_home_win"], 1.0 if r["actual_home"] else 0.0)
               for r in in_bucket])
    return {
        "n": n, "predicted_avg": predicted_avg, "actual_rate": actual_rate,
        "gap": actual_rate - predicted_avg, "brier": b, "rows": in_bucket,
    }


def hypothesis_1_rating_separation(bucket_rows: list):
    print("\n" + "-" * 100)
    print("HYPOTHESIS 1 -- rating separation (noisier/less-separated mid-table ratings)")
    print("-" * 100)
    if len(bucket_rows) < 4:
        print(
            f"  n={len(bucket_rows)} too small to say anything meaningful here.")
        return

    diffs = [r["rating_diff"] for r in bucket_rows]
    mean_diff = sum(diffs) / len(diffs)
    print(f"  rating_diff (home_adj - away, abs) across bucket: "
          f"mean={mean_diff:.1f}  min={min(diffs):.1f}  max={max(diffs):.1f}")

    # Continuous check, per this session's own preference over binning:
    # correlate rating_diff against squared error (real_home_win vs
    # actual outcome). If small-rating_diff fixtures drive the
    # miscalibration, error should shrink as rating_diff grows.
    sq_errors = [(r["real_home_win"] - (1.0 if r["actual_home"] else 0.0)) ** 2
                 for r in bucket_rows]
    n = len(bucket_rows)
    mean_x = mean_diff
    mean_y = sum(sq_errors) / n
    cov = sum((diffs[i] - mean_x) * (sq_errors[i] - mean_y)
              for i in range(n)) / n
    std_x = math.sqrt(sum((d - mean_x) ** 2 for d in diffs) / n)
    std_y = math.sqrt(sum((e - mean_y) ** 2 for e in sq_errors) / n)
    corr = cov / (std_x * std_y) if std_x > 0 and std_y > 0 else float("nan")

    print(f"  Pearson correlation(rating_diff, squared_error) = {corr:.3f}")
    print("  Interpretation: a strong NEGATIVE correlation would mean tighter-rated")
    print("  (more evenly-matched) fixtures in this bucket carry more error -- evidence")
    print("  FOR rating-separation/noise as (part of) the cause. Near-zero means this")
    print("  bucket's error doesn't depend on how separated the ratings are, which")
    print("  argues AGAINST this hypothesis as the primary driver.")

    print(f"\n  Per-fixture detail:")
    for r in sorted(bucket_rows, key=lambda x: x["rating_diff"]):
        print(f"    {r['home']:<18} vs {r['away']:<18}  "
              f"rating_diff={r['rating_diff']:>6.1f}  "
              f"pred={r['real_home_win']:.3f}  actual={'H' if r['actual_home'] else ('D' if r['actual_draw'] else 'A')}")


def hypothesis_2_home_advantage(validation_rows: list, final_rows: list):
    print("\n" + "-" * 100)
    print("HYPOTHESIS 2 -- HOME_ADVANTAGE=100 sizing")
    print("-" * 100)

    # Fixed population: fixtures that land in the bucket under the
    # DEFAULT HOME_ADVANTAGE=100 assignment. We don't re-bucket per
    # candidate value -- that would make the population itself an
    # artifact of the candidate being tested, which would make the
    # comparison meaningless.
    val_bucket = [r for r in validation_rows if BUCKET_LO <=
                  r["real_home_win"] < BUCKET_HI]
    final_bucket = [r for r in final_rows if BUCKET_LO <=
                    r["real_home_win"] < BUCKET_HI]

    if len(val_bucket) < 8:
        print(f"  Validation-half bucket n={len(val_bucket)} is small -- treat the "
              f"chosen HOME_ADVANTAGE with caution, but still report it.")

    candidates = [40, 60, 80, 100, 120, 140, 160]
    print(f"  Deriving best HOME_ADVANTAGE from validation half (n={len(val_bucket)}), "
          f"grid={candidates}:")

    best = {"value": 100, "brier": float("inf")}
    for ha in candidates:
        preds = []
        for r in val_bucket:
            p = repro_predict_result_elo(
                r["home_r"], r["away_r"], home_advantage=ha)
            preds.append((p["home_win"], 1.0 if r["actual_home"] else 0.0))
        b = brier(preds)
        flag = ""
        if b < best["brier"]:
            best = {"value": ha, "brier": b}
            flag = "  <-- best so far"
        print(f"    HOME_ADVANTAGE={ha:>3}  Brier={b:.4f}{flag}")

    print(f"\n  Best on validation half: HOME_ADVANTAGE={best['value']} "
          f"(Brier {best['brier']:.4f})")

    baseline_final = brier([(r["real_home_win"], 1.0 if r["actual_home"] else 0.0)
                            for r in final_bucket])
    candidate_preds = []
    for r in final_bucket:
        p = repro_predict_result_elo(
            r["home_r"], r["away_r"], home_advantage=best["value"])
        candidate_preds.append(
            (p["home_win"], 1.0 if r["actual_home"] else 0.0))
    candidate_final = brier(candidate_preds)

    print(f"\n  OUT-OF-SAMPLE CHECK on final half (n={len(final_bucket)}, same bucket "
          f"population as baseline, i.e. still assigned under HOME_ADVANTAGE=100):")
    print(
        f"    baseline (HOME_ADVANTAGE=100):        Brier={baseline_final:.4f}")
    print(f"    candidate (HOME_ADVANTAGE={best['value']}):"
          f"{' ' * max(1, 9 - len(str(best['value'])))}Brier={candidate_final:.4f}")
    if candidate_final < baseline_final:
        print(f"    -> IMPROVEMENT held out-of-sample. This is real signal, not "
              f"overfit to the validation half.")
    else:
        print(f"    -> Did NOT improve out-of-sample. Treat the validation-half result "
              f"as likely noise/overfit -- do not ship a HOME_ADVANTAGE change on this "
              f"evidence alone.")


def hypothesis_3_draw_floor(validation_rows: list, final_rows: list):
    print("\n" + "-" * 100)
    print("HYPOTHESIS 3 -- draw_prob floor (0.10) / base (0.28) / scale (2000)")
    print("-" * 100)

    val_bucket = [r for r in validation_rows if BUCKET_LO <=
                  r["real_home_win"] < BUCKET_HI]
    final_bucket = [r for r in final_rows if BUCKET_LO <=
                    r["real_home_win"] < BUCKET_HI]

    floor_hit = [r for r in val_bucket + final_bucket
                 if (0.28 - r["rating_diff"] / 2000) <= 0.10]
    floor_not_hit = [r for r in val_bucket + final_bucket
                     if (0.28 - r["rating_diff"] / 2000) > 0.10]
    print(f"  Of {len(val_bucket) + len(final_bucket)} bucket fixtures (both halves): "
          f"{len(floor_hit)} hit the 0.10 draw_prob floor, {len(floor_not_hit)} did not.")
    if floor_hit:
        actual_draw_floor = sum(r["actual_draw"]
                                for r in floor_hit) / len(floor_hit)
        print(f"    Floor-hit fixtures: actual draw rate = {actual_draw_floor:.1%} "
              f"(floor forces predicted draw_prob=10% pre-normalization for these)")
    if floor_not_hit:
        actual_draw_not = sum(r["actual_draw"]
                              for r in floor_not_hit) / len(floor_not_hit)
        print(
            f"    Non-floor fixtures:  actual draw rate = {actual_draw_not:.1%}")

    # Grid search floor + scale jointly on the draw AND home_win Brier
    # combined (the floor affects both, since draw_prob feeds directly
    # into how much of the remaining probability mass goes to
    # home_win/away_win). Base (0.28) left fixed -- changing three
    # constants at once on this small an n risks overfitting to noise;
    # base is the least-implicated constant per the floor-hit/not-hit
    # split above, so it's held constant this pass.
    floor_grid = [0.05, 0.08, 0.10, 0.12, 0.15]
    scale_grid = [1500, 2000, 2500, 3000]

    print(f"\n  Grid search (floor x scale) on validation half (n={len(val_bucket)}), "
          f"combined home_win + draw Brier:")
    best = {"floor": 0.10, "scale": 2000, "brier": float("inf")}
    for floor in floor_grid:
        for scale in scale_grid:
            preds = []
            for r in val_bucket:
                p = repro_predict_result_elo(r["home_r"], r["away_r"],
                                             draw_floor=floor, draw_scale=scale)
                preds.append((p["home_win"], 1.0 if r["actual_home"] else 0.0))
                preds.append((p["draw"], 1.0 if r["actual_draw"] else 0.0))
            b = brier(preds)
            if b < best["brier"]:
                best = {"floor": floor, "scale": scale, "brier": b}

    print(f"  Best on validation half: floor={best['floor']}  scale={best['scale']} "
          f"(Brier={best['brier']:.4f})")

    def combined_brier(rows, floor, scale):
        preds = []
        for r in rows:
            p = repro_predict_result_elo(r["home_r"], r["away_r"],
                                         draw_floor=floor, draw_scale=scale)
            preds.append((p["home_win"], 1.0 if r["actual_home"] else 0.0))
            preds.append((p["draw"], 1.0 if r["actual_draw"] else 0.0))
        return brier(preds)

    baseline_final = combined_brier(final_bucket, 0.10, 2000)
    candidate_final = combined_brier(
        final_bucket, best["floor"], best["scale"])

    print(f"\n  OUT-OF-SAMPLE CHECK on final half (n={len(final_bucket)}):")
    print(
        f"    baseline (floor=0.10, scale=2000):  Brier={baseline_final:.4f}")
    print(f"    candidate (floor={best['floor']}, scale={best['scale']}):"
          f"      Brier={candidate_final:.4f}")
    if candidate_final < baseline_final:
        print(f"    -> IMPROVEMENT held out-of-sample.")
    else:
        print(f"    -> Did NOT improve out-of-sample. Likely noise -- do not ship on "
              f"this evidence alone.")


def hypothesis_4_team_concentration(all_bucket_rows: list):
    print("\n" + "-" * 100)
    print("HYPOTHESIS 4 -- team concentration, scoped to the 30-40% bucket specifically")
    print("-" * 100)
    print("  (Prior session's dominance check was scoped to the blend's 'moved-in' "
          "fixtures, not this bucket -- this is the first time it's run against "
          "30-40% directly.)")

    by_team = defaultdict(list)
    for r in all_bucket_rows:
        by_team[r["home"]].append(r)

    print(
        f"\n  {'Home team':<20} {'n':>3} {'pred_avg':>9} {'actual':>8} {'gap':>8}")
    print("  " + "-" * 52)
    negative_gap_teams = 0
    total_teams = 0
    for team, rows in sorted(by_team.items(), key=lambda kv: -len(kv[1])):
        n = len(rows)
        pred_avg = sum(r["real_home_win"] for r in rows) / n
        actual = sum(r["actual_home"] for r in rows) / n
        gap = actual - pred_avg
        total_teams += 1
        if gap < 0:
            negative_gap_teams += 1
        flag = "" if n >= 2 else "  (n=1, low confidence)"
        print(
            f"  {team:<20} {n:>3} {pred_avg:>8.1%} {actual:>8.1%} {gap:>+7.1%}{flag}")

    print(f"\n  {negative_gap_teams}/{total_teams} home teams show a negative gap "
          f"(overconfident) in this bucket.")
    print("  Interpretation: if this is close to universal (most/all teams negative,")
    print("  similar to the 12/15 finding in the prior dominance check), that argues")
    print("  AGAINST team-specific concentration and FOR a structural/formula cause --")
    print("  consistent with hypotheses 1-3 above rather than this one. A result")
    print("  concentrated in 2-3 specific teams would argue FOR this hypothesis instead.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elo", default=None,
                        help="path to elo ratings snapshot (defaults to "
                             "backtester_v4.SNAPSHOT_ELO)")
    args = parser.parse_args()

    validation_matches, final_matches, ratings, real_predict_result_elo, elo_path = \
        load_all_fixtures(args.elo)

    print(f"elo={elo_path}")
    print(f"Validation half: {len(validation_matches)} matches   "
          f"Final half: {len(final_matches)} matches\n")

    validation_rows = build_rows(
        validation_matches, ratings, real_predict_result_elo)
    final_rows = build_rows(final_matches, ratings, real_predict_result_elo)

    mismatches = check_sync(validation_rows) + check_sync(final_rows)
    if mismatches:
        print("!" * 100)
        print(f"SYNC WARNING: repro_predict_result_elo() diverged from the real "
              f"predict_result_elo() for {len(mismatches)} fixture(s):")
        for m in mismatches[:10]:
            print(f"  {m}")
        print("This means epl_elo.py has changed since this script was written --")
        print("do not trust anything below until repro_predict_result_elo() is fixed")
        print("to match the real function again.")
        print("!" * 100 + "\n")

    val_bucket_info = bucket_table(validation_rows)
    final_bucket_info = bucket_table(final_rows)

    print("=" * 100)
    print(f"BASELINE -- Elo-only, home_win {BUCKET_LO:.0%}-{BUCKET_HI:.0%} bucket, "
          f"default constants (HOME_ADVANTAGE=100, draw floor=0.10)")
    print("=" * 100)
    for label, info in [("Validation half", val_bucket_info), ("Final half", final_bucket_info)]:
        if info["n"] == 0:
            print(f"  {label}: no fixtures in bucket.")
            continue
        print(f"  {label}: n={info['n']}  predicted_avg={info['predicted_avg']:.1%}  "
              f"actual_rate={info['actual_rate']:.1%}  gap={info['gap']:+.1%}  "
              f"Brier={info['brier']:.4f}")

    all_bucket_rows = val_bucket_info.get(
        "rows", []) + final_bucket_info.get("rows", [])

    if not all_bucket_rows:
        print("\nNo fixtures in the 30-40% bucket at all -- nothing to investigate. "
              "Check the Elo snapshot path.")
        return

    hypothesis_1_rating_separation(all_bucket_rows)
    hypothesis_2_home_advantage(validation_rows, final_rows)
    hypothesis_3_draw_floor(validation_rows, final_rows)
    hypothesis_4_team_concentration(all_bucket_rows)

    print("\n" + "=" * 100)
    print("READING THIS")
    print("=" * 100)
    print(
        "None of hypotheses 2/3 should be shipped on validation-half Brier alone --\n"
        "only ship if the out-of-sample check on the final half also improved, same\n"
        "discipline as Candidate C. If hypothesis 1's correlation is weak/near-zero AND\n"
        "hypothesis 4 shows a broad (not concentrated) negative gap AND neither 2 nor 3\n"
        "improves out-of-sample, that's a real result too -- it would mean the 30-40%\n"
        "problem isn't cleanly explained by any of these four single-constant\n"
        "explanations, and the next step should look at whether TWO of these interact\n"
        "(e.g. HOME_ADVANTAGE sizing conditional on rating separation) rather than\n"
        "testing each in isolation.\n"
    )


if __name__ == "__main__":
    main()
