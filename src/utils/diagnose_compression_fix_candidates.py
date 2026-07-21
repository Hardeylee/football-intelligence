"""
diagnose_compression_fix_candidates.py

DIAGNOSTIC ONLY — does NOT modify match_predictor.py or any production
file. Simulates two candidate fixes for the compression effect found by
diagnose_hist_form_vs_elo_full.py entirely in this script, and reports
what home_win calibration WOULD look like under each, on the same 190
real fixtures. Nothing here is wired into the live pipeline.

WHY THIS EXISTS
----------------
diagnose_hist_form_vs_elo_full.py confirmed, with a strong linear trend
across all 10 deciles (not just the extremes) and Pearson correlations
of -0.869 (hist) / -0.931 (form) against elo_home:

  hist_home and form_home are structurally COMPRESSED relative to
  elo_home across their entire range -- they can't swing as far from
  50% as Elo can, so blending always pulls Elo's confident predictions
  back toward the middle. This helps away_win's high buckets (already
  confirmed clean) but actively hurts home_win's low buckets, where
  Elo alone was already reasonably calibrated (20-30%: Elo-only gap
  -4.5%, "ok") and the blend makes it worse (full-pipeline gap -21.0%).

This script tests two candidate fixes for that specific mechanism,
BEFORE writing either into match_predictor.py:

  CANDIDATE A -- variance-matched logit rescale.
    Measures the actual standard deviation of elo_home, hist_home, and
    form_home across all 190 real fixtures (not assumed or guessed).
    Converts hist_home/form_home to logit space, rescales each to match
    elo_home's logit-space standard deviation (centered on its own
    mean, so central tendency is preserved -- only spread changes),
    converts back, then re-blends with the SAME 50/30/20 weights
    already in predict_result(). Isolates "does fixing the compression
    alone, with everything else unchanged, close the gap".

  CANDIDATE B -- confidence-weighted blend.
    When elo_home is far from 50% (Elo is confident), increases Elo's
    blend weight and shrinks hist/form's proportionally, instead of a
    fixed 50/30/20 split applied uniformly regardless of how lopsided
    Elo already thinks the matchup is. weight_elo = 0.50 + CONFIDENCE_K
    * |elo_home - 0.5| * 2, capped at MAX_ELO_WEIGHT; hist/form split
    the remainder in their existing 30:20 (=60:40) ratio. Tests a
    structurally different fix: not correcting hist/form's spread, but
    trusting them less exactly when Elo is already confident.

  CANDIDATE C -- TAPERED variance-matched rescale.
    Added after A and B were both tested and found to damage the
    already-well-calibrated 50-90% home_win range (home_win 60-70% went
    from baseline's gap +3.1%/ok to -13.0%/-18.0% under A/B
    respectively) while fixing the 20-30% bucket. C applies the exact
    same rescale as Candidate A, but multiplies the correction by a
    taper weight that is ~1.0 when elo_home is well below
    TAPER_THRESHOLD (0.45) and fades smoothly to ~0.0 above it -- so
    the correction only meaningfully applies to weak-home fixtures,
    where diagnose_hist_form_vs_elo_full.py's evidence actually points,
    and leaves fixtures where Elo already favors the home team alone.

Both candidates are then bucketed with the SAME 10-point buckets used
throughout this session and compared directly against BASELINE (today's
real predict_result() blend, unchanged) for the two open buckets
(home_win 20-30% and 30-40%) plus draw and away_win overall, so a fix
that solves home_win but quietly breaks away_win/draw (which are
already confirmed calibrated) would be visible immediately, not
discovered later.

CAVEATS, stated up front rather than glossed over:
  - This is a SIMULATION against the same 190-fixture holdout the fix
    would eventually be graded on. A fix that looks good here still
    needs the normal held-out validation discipline (backtester_v4.py's
    validation/final split) once actually implemented -- this script
    is a cheap first filter to avoid coding up a fix that provably
    doesn't work, not a replacement for that process.
  - Candidate A's logit-rescale changes hist_home/form_home's SPREAD
    but is deliberately built to preserve their MEAN (measured from
    these fixtures) -- so it should not systematically shift the
    average prediction up or down, only how far predictions can swing
    from center. Worth confirming that's actually true in the printed
    output (avg predicted should stay close to baseline) rather than
    assuming the math did what it was meant to.
  - Neither candidate touches draw_base or the H2H stage -- both only
    change how home_win/away_win are computed pre-H2H, then H2H and
    normalization are reapplied identically to baseline.

USAGE
-----
    python src/utils/diagnose_compression_fix_candidates.py
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
CONFIDENCE_K = 0.30   # Candidate B: how much extra weight Elo gains per
# unit of |elo_home - 0.5|*2 (0=no effect, 1=huge)
MAX_ELO_WEIGHT = 0.80  # Candidate B: never let Elo's weight exceed this

# Candidate C: only correct compression when elo_home is BELOW this --
# added after Candidates A and B both showed the fix applied globally
# damages the already-well-calibrated 50-90% range (home_win 60-70% went
# from baseline's +3.1%/ok to -13.0%/-18.0% under A/B respectively).
# The actual problem (per diagnose_hist_form_vs_elo_full.py) is that
# hist/form refuse to go as low as Elo for weak-home fixtures -- there's
# no equivalent evidence the correction is needed above ~45%, so C
# fades the correction out there instead of applying it uniformly.
TAPER_THRESHOLD = 0.45
TAPER_STEEPNESS = 14  # higher = sharper cutoff around TAPER_THRESHOLD


def taper_weight(elo_home: float) -> float:
    """1.0 well below TAPER_THRESHOLD, 0.0 well above it, smooth
    transition around it (no hard cliff, avoids a discontinuity in the
    predicted probability as elo_home crosses the threshold)."""
    return sigmoid(TAPER_STEEPNESS * (TAPER_THRESHOLD - elo_home))


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
    flag = ""
    if b["n"] >= 8:
        flag = "⚠" if abs(b["gap"]) >= 0.10 else "ok"
    else:
        flag = "(low n)"
    print(f"    {b['label']:<8} n={b['n']:>3}  pred={b['avg_predicted']*100:>5.1f}%  "
          f"actual={b['actual_rate']*100:>5.1f}%  gap={b['gap']*100:>+6.1f}%  {flag}")


def main():
    from src.utils.backtester_v4 import (
        TEST_SEASON_FILE, VALIDATION_FRACTION, SNAPSHOT_ELO, SNAPSHOT_H2H,
        SNAPSHOT_PROFILES, load_csv_file, get_actuals,
    )
    from src.models.match_predictor import (
        load_profiles, load_h2h, get_h2h, FORCE_PROMOTED,
        _build_league_average, PROMOTED_TEAM_PROFILES,
    )
    # See earlier note in this session: this script's own docstring
    # calls itself diagnose_result_stacking.py, but it is actually
    # saved on disk as diagnose_stacking.py (process rule 9).
    from src.utils.diagnose_stacking import (
        stage_a_elo_only, raw_hist_components, raw_form_components,
    )

    print("=" * 100)
    print("  COMPRESSION FIX CANDIDATES — simulated only, no production files changed")
    print("=" * 100)

    all_matches = load_csv_file(TEST_SEASON_FILE)
    if not all_matches:
        print(f"[ERROR] No matches loaded from {TEST_SEASON_FILE}.")
        return

    split_idx = int(len(all_matches) * VALIDATION_FRACTION)
    final_matches = all_matches[split_idx:]
    print(f"\nFinal holdout half: {len(final_matches)} matches\n")

    profiles = load_profiles(SNAPSHOT_PROFILES)
    h2h_data = load_h2h(SNAPSHOT_H2H)  # point-in-time snapshot, matching
    # backtester_v4.py's real predict_fixture()
    # exactly -- NOT the live h2h.json, which
    # was this script's original bug (see fix
    # note added after the first run flagged
    # baseline disagreeing with the already-
    # verified real backtest numbers).

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

    # ---- Pass 1: collect raw components for all 190 fixtures ----
    raw = []
    for m in final_matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        actuals = get_actuals(m)
        profiles = ensure_team_profiles(profiles, [home, away], FORCE_PROMOTED)

        elo = stage_a_elo_only(home, away, SNAPSHOT_ELO)
        hist = raw_hist_components(home, away, profiles)
        form = raw_form_components(home, away, profiles)

        raw.append({
            "home": home, "away": away,
            "elo_home": elo["home_win"], "elo_away": elo["away_win"], "elo_draw": elo["draw"],
            "hist_home": hist["hist_home"], "hist_away": hist["hist_away"], "hist_draw": hist["hist_draw"],
            "form_home": form["form_home"], "form_away": form["form_away"], "form_draw": form["form_draw"],
            "actual_home_win": actuals["home_win"],
            "actual_draw": actuals["draw"],
            "actual_away_win": actuals["away_win"],
        })

    print(f"Collected raw components for {len(raw)} fixtures.\n")

    # ---- Measure actual spread (std dev) directly from these fixtures ----
    elo_logits = [logit(r["elo_home"]) for r in raw]
    hist_logits = [logit(r["hist_home"]) for r in raw]
    form_logits = [logit(r["form_home"]) for r in raw]

    std_elo = stdev(elo_logits)
    std_hist = stdev(hist_logits)
    std_form = stdev(form_logits)
    mean_hist = sum(hist_logits) / len(hist_logits)
    mean_form = sum(form_logits) / len(form_logits)

    stretch_hist = std_elo / std_hist if std_hist else 1.0
    stretch_form = std_elo / std_form if std_form else 1.0

    print(f"Measured logit-space std dev (home_win):")
    print(f"  elo_home:  {std_elo:.3f}")
    print(
        f"  hist_home: {std_hist:.3f}  (stretch factor to match elo: {stretch_hist:.3f}x)")
    print(
        f"  form_home: {std_form:.3f}  (stretch factor to match elo: {stretch_form:.3f}x)\n")

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

    baseline_rows, cand_a_rows, cand_b_rows, cand_c_rows = [], [], [], []

    for r in raw:
        # ---- BASELINE: reproduce today's real blend exactly ----
        b_home = (r["elo_home"] * 0.50) + \
            (r["hist_home"] * 0.30) + (r["form_home"] * 0.20)
        b_away = (r["elo_away"] * 0.50) + \
            (r["hist_away"] * 0.30) + (r["form_away"] * 0.20)
        b_draw = (r["elo_draw"] * 0.50) + \
            (r["hist_draw"] * 0.30) + (r["form_draw"] * 0.20)
        b_home, b_away, b_draw = apply_h2h_and_normalize(
            r["home"], r["away"], b_home, b_away, b_draw)

        # ---- CANDIDATE A: variance-matched logit rescale ----
        # Rescale hist_home/form_home in logit space to elo's spread,
        # centered on THEIR OWN mean (preserves central tendency).
        # away/draw components are left as baseline for this candidate
        # -- only home_win's compression is targeted, since that's
        # where the actual calibration problem sits.
        hist_home_logit = logit(r["hist_home"])
        form_home_logit = logit(r["form_home"])
        a_hist_home = sigmoid(
            mean_hist + (hist_home_logit - mean_hist) * stretch_hist)
        a_form_home = sigmoid(
            mean_form + (form_home_logit - mean_form) * stretch_form)

        a_home = (r["elo_home"] * 0.50) + \
            (a_hist_home * 0.30) + (a_form_home * 0.20)
        a_away = b_away  # unchanged component for away/draw in this candidate
        a_draw = b_draw
        a_home, a_away, a_draw = apply_h2h_and_normalize(
            r["home"], r["away"], a_home, a_away, a_draw)

        # ---- CANDIDATE B: confidence-weighted blend ----
        # 0 (toss-up) to 1 (Elo very sure)
        confidence = abs(r["elo_home"] - 0.5) * 2
        elo_weight = min(0.50 + CONFIDENCE_K * confidence, MAX_ELO_WEIGHT)
        remaining = 1 - elo_weight
        # preserve hist:form = 30:20 ratio
        hist_weight = remaining * (0.30 / 0.50)
        form_weight = remaining * (0.20 / 0.50)

        c_home = (r["elo_home"] * elo_weight) + (r["hist_home"]
                                                 * hist_weight) + (r["form_home"] * form_weight)
        c_away = (r["elo_away"] * elo_weight) + (r["hist_away"]
                                                 * hist_weight) + (r["form_away"] * form_weight)
        c_draw = (r["elo_draw"] * elo_weight) + (r["hist_draw"]
                                                 * hist_weight) + (r["form_draw"] * form_weight)
        c_home, c_away, c_draw = apply_h2h_and_normalize(
            r["home"], r["away"], c_home, c_away, c_draw)

        # ---- CANDIDATE C: TAPERED variance-matched rescale ----
        # Same rescale as Candidate A, but faded out via taper_weight()
        # so it only meaningfully applies where elo_home is low --
        # leaves the 50-90% range (already well-calibrated at baseline)
        # essentially untouched, unlike A and B which both damaged it.
        tw = taper_weight(r["elo_home"])
        d_hist_home = tw * a_hist_home + (1 - tw) * r["hist_home"]
        d_form_home = tw * a_form_home + (1 - tw) * r["form_home"]

        d_home = (r["elo_home"] * 0.50) + \
            (d_hist_home * 0.30) + (d_form_home * 0.20)
        d_away = b_away  # unchanged, same as Candidate A
        d_draw = b_draw
        d_home, d_away, d_draw = apply_h2h_and_normalize(
            r["home"], r["away"], d_home, d_away, d_draw)

        baseline_rows.append({"home_win": b_home, "draw": b_draw, "away_win": b_away,
                              "actual_home_win": r["actual_home_win"], "actual_draw": r["actual_draw"],
                              "actual_away_win": r["actual_away_win"]})
        cand_a_rows.append({"home_win": a_home, "draw": a_draw, "away_win": a_away,
                            "actual_home_win": r["actual_home_win"], "actual_draw": r["actual_draw"],
                            "actual_away_win": r["actual_away_win"]})
        cand_b_rows.append({"home_win": c_home, "draw": c_draw, "away_win": c_away,
                            "actual_home_win": r["actual_home_win"], "actual_draw": r["actual_draw"],
                            "actual_away_win": r["actual_away_win"]})
        cand_c_rows.append({"home_win": d_home, "draw": d_draw, "away_win": d_away,
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

    report("A. BASELINE (today's real predict_result() blend, reproduced)", baseline_rows)
    report("B. CANDIDATE A — variance-matched logit rescale (home_win component only)", cand_a_rows)
    report("C. CANDIDATE B — confidence-weighted blend (elo weight scales with elo's confidence)", cand_b_rows)
    report("D. CANDIDATE C — TAPERED rescale (Candidate A's fix, faded out above elo_home~45%)", cand_c_rows)

    # ---- Brier score comparison, bucket-independent ----
    # Added after Candidate A vs C showed a confusing discrepancy at
    # home_win 20-30% (same n=15, nearly identical avg predicted
    # probability, but a full win's difference in actual outcomes) --
    # with only 15 fixtures in that bucket, a tiny prediction shift can
    # move 1-2 fixtures across the bucket boundary and swing the
    # actual-rate by ~6-7 points on its own, which looks like a real
    # calibration difference but may just be bucket-reshuffling noise.
    # Brier score (mean squared error between predicted probability and
    # the 0/1 actual outcome) is computed directly per-fixture across
    # ALL 190 matches with no binning at all, so it can't be distorted
    # by fixtures crossing a bucket edge. Lower is better; 0 = perfect,
    # 0.25 = a model that always predicts 50/50 for a 50/50 coin flip.
    def brier(rows: list, prob_key: str, actual_key: str) -> float:
        return sum((r[prob_key] - (1.0 if r[actual_key] else 0.0)) ** 2
                   for r in rows) / len(rows)

    print("\n" + "=" * 100)
    print("BRIER SCORE COMPARISON (bucket-independent, lower = better calibrated)")
    print("=" * 100)
    print(f"\n{'Variant':<15} {'home_win':>10} {'draw':>10} {'away_win':>10}")
    print("-" * 50)
    for label, rows in [("Baseline", baseline_rows), ("Candidate A", cand_a_rows),
                        ("Candidate B", cand_b_rows), ("Candidate C", cand_c_rows)]:
        bh = brier(rows, "home_win", "actual_home_win")
        bd = brier(rows, "draw", "actual_draw")
        ba = brier(rows, "away_win", "actual_away_win")
        print(f"{label:<15} {bh:>10.4f} {bd:>10.4f} {ba:>10.4f}")
    print(
        "\n  Focus on the home_win column -- the lowest number there, combined with a\n"
        "  bucket table (above) that doesn't show new ⚠ flags in the 50-90% range, is\n"
        "  the actual best candidate. This number can't be moved by bucket-boundary\n"
        "  reshuffling the way the binned tables above can be, so treat it as the\n"
        "  tie-breaker if the bucket tables look ambiguous or contradictory.\n"
    )

    print("\n" + "=" * 100)
    print("READING THIS")
    print("=" * 100)
    print(
        "Compare the home_win 20-30% and 30-40% rows across all four reports first --\n"
        "those are the two open buckets. Then check whether the SAME candidate keeps\n"
        "home_win 60-70%/70-80% and away_win's mid buckets clean, since A and B were\n"
        "both found to fix the low end while damaging that already-good range.\n\n"
        "Candidate C exists specifically to test whether tapering the correction off\n"
        "above elo_home~45% recovers the damage A/B caused there while keeping most of\n"
        "A's improvement at the low end. If C achieves that -- it's the one worth\n"
        "actually implementing. If C still damages the upper range, or barely improves\n"
        "the low end once tapered, that's real evidence the fix needs a different shape\n"
        "entirely (e.g. a per-team correction rather than a global elo_home-based one),\n"
        "not just a narrower window on the same mechanism.\n\n"
        "Whichever candidate looks best here still needs to go through backtester_v4.py's\n"
        "normal validation/final split once it's actually written into predict_result() --\n"
        "this script is a cheap pre-filter, not the final calibration report.\n"
    )


if __name__ == "__main__":
    main()
