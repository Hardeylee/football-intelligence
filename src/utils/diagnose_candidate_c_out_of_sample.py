"""
diagnose_candidate_c_out_of_sample.py

DIAGNOSTIC ONLY — does NOT modify match_predictor.py or any production
file.

WHY THIS EXISTS
----------------
Candidate C (tapered variance-matched rescale) was designed and tuned
entirely against the FINAL holdout half (~190 matches):
  - stretch_hist=2.005x, stretch_form=2.325x, and the hist/form logit
    means were all MEASURED from that same 190-fixture set.
  - TAPER_THRESHOLD (0.45) and TAPER_STEEPNESS (14) were chosen by
    looking at which value stopped the damage Candidates A/B caused,
    also observed on that same set.
  - The Brier-score win (0.2095 -> 0.2076) that made C look best was
    ALSO measured on that same set.

That's circular enough to be a real concern: a fix shaped by, and
graded on, the exact same 190 fixtures might just be fitting quirks of
that particular sample (specific teams, specific results that season)
rather than a genuine generalizable correction. The whole point of the
system is to predict NEW 2026/27 fixtures this dataset has never seen
-- a fix that only works on the fixtures it was designed against is not
good enough to ship.

This script re-derives Candidate C's constants (stretch_hist,
stretch_form, hist/form logit means) from the VALIDATION half instead
-- the other ~190 matches from the same season, never looked at during
any of this session's candidate design or tuning -- then applies the
SAME taper threshold/steepness (0.45 / 14, structural choices, not
measured statistics) to the FINAL holdout half, which is what all the
prior candidate comparisons were graded on.

Two things to look for:
  1. Are the validation-derived stretch factors/means CLOSE to the
     final-holdout-derived ones (2.005x / 2.325x)? If yes, that's
     reassuring -- the compression ratio is a stable property of
     hist_home/form_home vs elo_home generally, not a fluke of one
     190-match sample. If wildly different, the whole rescale idea is
     less trustworthy than it looked.
  2. Does the OUT-OF-SAMPLE version of Candidate C still beat baseline
     on the final holdout's Brier score and bucket table? If yes, the
     fix is real and worth implementing. If the improvement vanishes
     or reverses, Candidate C was overfit to the final holdout and
     should not be shipped as designed -- back to the drawing board on
     the fix's shape, not just its constants.

USAGE
-----
    python src/utils/diagnose_candidate_c_out_of_sample.py
"""

# isort: skip_file
import math
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

BUCKET_EDGES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
TAPER_THRESHOLD = 0.45
TAPER_STEEPNESS = 14


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def stdev(vals: list) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    return (sum((v - mean) ** 2 for v in vals) / n) ** 0.5


def taper_weight(elo_home: float) -> float:
    return sigmoid(TAPER_STEEPNESS * (TAPER_THRESHOLD - elo_home))


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


def print_bucket_row(b: dict):
    if b["n"] >= 8:
        flag = "⚠" if abs(b["gap"]) >= 0.10 else "ok"
    else:
        flag = "(low n)"
    print(f"    {b['label']:<8} n={b['n']:>3}  pred={b['avg_predicted']*100:>5.1f}%  "
          f"actual={b['actual_rate']*100:>5.1f}%  gap={b['gap']*100:>+6.1f}%  {flag}")


def brier(rows: list, prob_key: str, actual_key: str) -> float:
    return sum((r[prob_key] - (1.0 if r[actual_key] else 0.0)) ** 2
               for r in rows) / len(rows)


def collect_components(matches: list, profiles: dict, force_promoted: set,
                       elo_path: str, get_actuals_fn, ensure_fn,
                       stage_a_elo_only, raw_hist_components, raw_form_components) -> tuple:
    """Returns (rows, profiles) where rows have raw elo/hist/form home
    components + actuals for every fixture in `matches`."""
    rows = []
    for m in matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        actuals = get_actuals_fn(m)
        profiles = ensure_fn(profiles, [home, away], force_promoted)

        elo = stage_a_elo_only(home, away, elo_path)
        hist = raw_hist_components(home, away, profiles)
        form = raw_form_components(home, away, profiles)

        rows.append({
            "home": home, "away": away,
            "elo_home": elo["home_win"], "elo_away": elo["away_win"], "elo_draw": elo["draw"],
            "hist_home": hist["hist_home"], "hist_away": hist["hist_away"], "hist_draw": hist["hist_draw"],
            "form_home": form["form_home"], "form_away": form["form_away"], "form_draw": form["form_draw"],
            "actual_home_win": actuals["home_win"],
            "actual_draw": actuals["draw"],
            "actual_away_win": actuals["away_win"],
        })
    return rows, profiles


def main():
    from src.utils.backtester_v4 import (
        TEST_SEASON_FILE, VALIDATION_FRACTION, SNAPSHOT_ELO, SNAPSHOT_H2H,
        SNAPSHOT_PROFILES, load_csv_file, get_actuals,
    )
    from src.models.match_predictor import (
        load_profiles, load_h2h, get_h2h, FORCE_PROMOTED,
        _build_league_average, PROMOTED_TEAM_PROFILES,
    )
    from src.utils.diagnose_stacking import (
        stage_a_elo_only, raw_hist_components, raw_form_components,
    )

    print("=" * 100)
    print("  CANDIDATE C — OUT-OF-SAMPLE CHECK (constants from validation half, graded on final half)")
    print("=" * 100)

    all_matches = load_csv_file(TEST_SEASON_FILE)
    if not all_matches:
        print(f"[ERROR] No matches loaded from {TEST_SEASON_FILE}.")
        return

    split_idx = int(len(all_matches) * VALIDATION_FRACTION)
    validation_matches = all_matches[:split_idx]
    final_matches = all_matches[split_idx:]
    print(
        f"\nValidation half: {len(validation_matches)} matches (used ONLY to derive constants)")
    print(f"Final half: {len(final_matches)} matches (used ONLY to grade the result -- "
          f"this is the SAME set every prior candidate comparison this session was graded on)\n")

    profiles = load_profiles(SNAPSHOT_PROFILES)
    h2h_data = load_h2h(SNAPSHOT_H2H)

    def ensure_team_profiles(profiles, teams, active_force_promoted):
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

    print("Deriving rescale constants from VALIDATION half...")
    val_rows, profiles = collect_components(
        validation_matches, profiles, FORCE_PROMOTED, SNAPSHOT_ELO,
        get_actuals, ensure_team_profiles,
        stage_a_elo_only, raw_hist_components, raw_form_components)

    val_hist_logits = [logit(r["hist_home"]) for r in val_rows]
    val_form_logits = [logit(r["form_home"]) for r in val_rows]
    val_elo_logits = [logit(r["elo_home"]) for r in val_rows]

    std_elo_val = stdev(val_elo_logits)
    std_hist_val = stdev(val_hist_logits)
    std_form_val = stdev(val_form_logits)
    mean_hist_val = sum(val_hist_logits) / len(val_hist_logits)
    mean_form_val = sum(val_form_logits) / len(val_form_logits)

    stretch_hist_val = std_elo_val / std_hist_val if std_hist_val else 1.0
    stretch_form_val = std_elo_val / std_form_val if std_form_val else 1.0

    print(f"\n  VALIDATION-derived constants:")
    print(
        f"    stretch_hist = {stretch_hist_val:.3f}x   (final-holdout-derived was 2.005x)")
    print(
        f"    stretch_form = {stretch_form_val:.3f}x   (final-holdout-derived was 2.325x)")
    print(f"    mean_hist (logit) = {mean_hist_val:.3f}")
    print(f"    mean_form (logit) = {mean_form_val:.3f}")

    stability_note = "STABLE — close to final-holdout values, good sign" \
        if abs(stretch_hist_val - 2.005) < 0.4 and abs(stretch_form_val - 2.325) < 0.4 \
        else "DIFFERS meaningfully from final-holdout values — treat with caution"
    print(f"    -> {stability_note}\n")

    print("Computing components for FINAL holdout half (grading set)...")
    final_rows, profiles = collect_components(
        final_matches, profiles, FORCE_PROMOTED, SNAPSHOT_ELO,
        get_actuals, ensure_team_profiles,
        stage_a_elo_only, raw_hist_components, raw_form_components)

    def apply_h2h_and_normalize(home, away, home_win, away_win, draw):
        h2h = get_h2h(home, away, h2h_data)
        if h2h and h2h["matches"] >= 3:
            h2h_home = h2h["home_wins"] / h2h["matches"]
            h2h_away = h2h["away_wins"] / h2h["matches"]
            h2h_draw = h2h["draws"] / h2h["matches"]
            home_win = (home_win * 0.80) + (h2h_home * 0.20)
            away_win = (away_win * 0.80) + (h2h_away * 0.20)
            draw = (draw * 0.80) + (h2h_draw * 0.20)
        total = home_win + away_win + draw
        return home_win / total, away_win / total, draw / total

    baseline_rows, cand_c_oos_rows = [], []

    for r in final_rows:
        b_home = (r["elo_home"] * 0.50) + \
            (r["hist_home"] * 0.30) + (r["form_home"] * 0.20)
        b_away = (r["elo_away"] * 0.50) + \
            (r["hist_away"] * 0.30) + (r["form_away"] * 0.20)
        b_draw = (r["elo_draw"] * 0.50) + \
            (r["hist_draw"] * 0.30) + (r["form_draw"] * 0.20)
        b_home, b_away, b_draw = apply_h2h_and_normalize(
            r["home"], r["away"], b_home, b_away, b_draw)

        # Candidate C, but using VALIDATION-derived stretch/mean constants
        # -- everything else (taper shape, 50/30/20 weights) identical to
        # the version graded earlier this session.
        hist_home_logit = logit(r["hist_home"])
        form_home_logit = logit(r["form_home"])
        rescaled_hist_home = sigmoid(
            mean_hist_val + (hist_home_logit - mean_hist_val) * stretch_hist_val)
        rescaled_form_home = sigmoid(
            mean_form_val + (form_home_logit - mean_form_val) * stretch_form_val)

        tw = taper_weight(r["elo_home"])
        c_hist_home = tw * rescaled_hist_home + (1 - tw) * r["hist_home"]
        c_form_home = tw * rescaled_form_home + (1 - tw) * r["form_home"]

        c_home = (r["elo_home"] * 0.50) + \
            (c_hist_home * 0.30) + (c_form_home * 0.20)
        c_away = b_away
        c_draw = b_draw
        c_home, c_away, c_draw = apply_h2h_and_normalize(
            r["home"], r["away"], c_home, c_away, c_draw)

        baseline_rows.append({"home_win": b_home, "draw": b_draw, "away_win": b_away,
                              "actual_home_win": r["actual_home_win"], "actual_draw": r["actual_draw"],
                              "actual_away_win": r["actual_away_win"]})
        cand_c_oos_rows.append({"home_win": c_home, "draw": c_draw, "away_win": c_away,
                                "actual_home_win": r["actual_home_win"], "actual_draw": r["actual_draw"],
                                "actual_away_win": r["actual_away_win"]})

    def report(label: str, rows: list):
        print(f"\n{'='*100}\n  {label}\n{'='*100}")
        for market, actual_key in [("home_win", "actual_home_win"),
                                   ("draw", "actual_draw"),
                                   ("away_win", "actual_away_win")]:
            buckets = build_buckets(rows, market, actual_key)
            print(f"\n  {market}:")
            for b in buckets:
                print_bucket_row(b)

    report("BASELINE (real predict_result() blend, graded on final holdout)", baseline_rows)
    report("CANDIDATE C — OUT-OF-SAMPLE (constants from validation half, graded on final holdout)", cand_c_oos_rows)

    print("\n" + "=" * 100)
    print("BRIER SCORE — baseline vs Candidate C (out-of-sample constants)")
    print("=" * 100)
    print(f"\n{'Variant':<30} {'home_win':>10} {'draw':>10} {'away_win':>10}")
    print("-" * 65)
    for label, rows in [("Baseline", baseline_rows), ("Candidate C (out-of-sample)", cand_c_oos_rows)]:
        bh = brier(rows, "home_win", "actual_home_win")
        bd = brier(rows, "draw", "actual_draw")
        ba = brier(rows, "away_win", "actual_away_win")
        print(f"{label:<30} {bh:>10.4f} {bd:>10.4f} {ba:>10.4f}")

    print(
        "\n  For reference, the earlier IN-SAMPLE run (constants AND grading both from")
    print("  the final holdout) scored: Baseline home_win=0.2095, Candidate C home_win=0.2076")

    print("\n" + "=" * 100)
    print("READING THIS")
    print("=" * 100)
    print(
        "If the out-of-sample home_win Brier score still beats baseline by roughly the\n"
        "same margin as the in-sample run (~0.0019 improvement) -- Candidate C is real,\n"
        "not an artifact of tuning on the grading set, and is safe to actually implement\n"
        "in match_predictor.py using these (or the original) constants.\n\n"
        "If the improvement shrinks substantially or disappears -- Candidate C was\n"
        "overfit to the final holdout's specific fixtures, and should NOT be shipped as\n"
        "designed. In that case the underlying finding from diagnose_hist_form_vs_elo_full.py\n"
        "(hist/form compression relative to Elo, correlation -0.869/-0.931) is still real\n"
        "and worth fixing -- but the taper shape/threshold would need to be re-derived\n"
        "properly via a grid search on the validation half only, the same way\n"
        "backtester_v4.py's tune_thresholds() already does for value-bet edge thresholds,\n"
        "rather than hand-picked by eye against the final holdout the way this session did it.\n"
    )


if __name__ == "__main__":
    main()
