"""
diagnose_result_stacking.py

DIAGNOSTIC ONLY — calls your real match_predictor.py / epl_elo.py
functions directly. Does not change predict_result() or any other
model file. Safe to run against live or snapshot data.

WHY THIS EXISTS
----------------
The calibration report has flagged home_win and away_win as
overconfident across this entire session, untouched by the BTTS/cards/
over25 fixes:

    home_win  20-30%  n=21  predicted 25.3%  actual  4.8%   gap -20.5%
    home_win  30-40%  n=28  predicted 35.1%  actual 25.0%   gap -10.1%
    away_win  50-60%  n=11  predicted 55.7%  actual 45.5%   gap -10.2%
    away_win  70-80%  n=2   predicted 75.4%  actual 50.0%   gap -25.4%  (noisy, n=2)

Both HOME_WIN (low end) and AWAY_WIN (mid/high end) are overconfident.
That's a different shape than a simple "too much home bias" bug --
if that were the whole story you'd expect away_win to be UNDERconfident
where home_win is overconfident, not overconfident in the same
direction. One hypothesis worth checking directly: predict_result()'s
H2H adjustment step re-blends home_win and away_win at 80/20, but never
touches draw -- so if draw ends up underweighted anywhere in the stack,
both home_win and away_win could inflate together at draw's expense.
This script does not assume that's the answer -- it traces every stage
so the real numbers can confirm or rule it out.

HOW IT WORKS
------------
For each sample fixture, calls/reproduces predict_result()'s internal
stages in order and prints the value at each point:

    A. Elo-only            — REAL call to predict_result_elo().
    B. + Historical (30%)  — reproduced: hist_home/hist_away/hist_draw
                              blended with A at fixed 50/30 weights,
                              form excluded, renormalized to isolate
                              what historical rates alone change.
    C. + Form (20%)        — reproduced: full elo+hist+form blend,
                              matches predict_result()'s pre-H2H,
                              pre-normalize home_win/away_win/draw
                              exactly.
    D. + H2H               — reproduced: predict_result()'s H2H
                              re-blend (home_win/away_win only, draw
                              untouched), if h2h data qualifies.
    E. Final (normalized)  — REAL call to predict_result(), used to
                              VALIDATE stage D's reproduction is still
                              in sync with the live function. If D and
                              E disagree beyond normalization, the
                              reproduction below is stale -- fix it
                              before trusting anything else in this
                              script's output.

Also prints, per fixture: raw home_win_rate/away_win_rate/draw_base,
raw home_form/away_form, and whether H2H fired -- so a floor/ceiling
effect on any one component is visible directly rather than inferred.

At the end, prints the average predicted draw probability across all
sample fixtures. Compare this by hand to your calibration report's own
draw bucket (if it has one) or your backtest's actual draw rate -- if
predicted draw sits noticeably below the real rate, that's direct
evidence for the "draw underweighted, both wings inflated" hypothesis
above.

USAGE
-----
    python src/utils/diagnose_result_stacking.py

    # Backtest-condition run — same snapshot files as backtester_v4.py:
    python src/utils/diagnose_result_stacking.py --profiles data/team_profiles_asof_24-25.json --h2h data/h2h_asof_24-25.json --elo data/epl_elo_ratings_asof_24-25.json

Note: like diagnose_stacking.py, this always uses the default
FORCE_PROMOTED module constant (not backtester_v4.py's force_promoted=set()).
That only matters for the promoted-team sample fixture below (Ipswich
vs Man City); the rest are unaffected either way.
"""

# isort: skip_file
#
# ^ LOAD-BEARING, same reason as diagnose_stacking.py: keeps the
# sys.path.insert() below from being hoisted below any `from src...`
# import by an editor's import-sorter. Kept here as a second line of
# defense even though this script uses the local-import-inside-function
# pattern (see PROCESS RULE #5 in the handover note) rather than
# top-level imports, since argparse/math/os/sys below are still
# stdlib imports that a sorter could otherwise reorder around the
# PROJECT_ROOT computation.

import argparse
import os
import sys

# Derive project root from this script's own location, not cwd --
# same reasoning as diagnose_stacking.py. This script is expected to
# live at src/utils/<this file>, so parent-of-parent-of-parent is the
# project root regardless of where the command is run from.
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# Sample fixtures deliberately skewed toward the two flagged buckets:
# weak-home-vs-strong-away (to land in home_win 20-40%) and
# mid-home-vs-strong-away (to land in away_win 50-80%). Also includes
# one promoted-team fixture to exercise the fallback-profile path, and
# one top-vs-top control fixture as a sanity baseline.
SAMPLE_FIXTURES = [
    ("Sheffield United", "Man City",
     "Weak home vs elite away — home_win low-end target"),
    ("Wolves",            "Liverpool", "Weak-ish home vs elite away"),
    ("Leeds",              "Arsenal",  "Newly-promoted-tier home vs strong away"),
    ("Ipswich",            "Man City",
     "Promoted home vs elite away (fallback profile path)"),
    ("Brighton",           "Man City",
     "Mid home vs elite away — away_win mid-bucket target"),
    ("Everton",            "Liverpool", "Merseyside derby, away favoured"),
    ("Nott'm Forest",      "Chelsea",  "Lower-mid home vs strong away"),
    ("Man City",           "Liverpool",
     "Top vs top — control fixture, no bucket skew"),
]


def ensure_team_profiles(profiles: dict, teams: list, active_force_promoted: set) -> dict:
    """
    Reproduces predict_match()'s missing-team fallback logic so a direct
    call to predict_result() in this script doesn't KeyError on promoted
    teams. Mirrors match_predictor.py's predict_match() body — KEEP IN
    SYNC if that logic changes. (Same helper as diagnose_stacking.py,
    duplicated here rather than imported to keep this script
    self-contained and independently runnable.)
    """
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


def stage_a_elo_only(home: str, away: str, elo_path: str) -> dict:
    """
    Stage A: REAL call to predict_result_elo() — not reproduced.
    """
    from src.models.epl_elo import load_ratings, predict_result_elo

    elo_ratings = load_ratings(elo_path) if elo_path else load_ratings()
    elo_pred = predict_result_elo(home, away, elo_ratings)
    return {
        "home_win": elo_pred["home_win"],
        "draw":     elo_pred["draw"],
        "away_win": elo_pred["away_win"],
        "home_elo": elo_pred.get("home_elo"),
        "away_elo": elo_pred.get("away_elo"),
    }


def raw_hist_components(home: str, away: str, profiles: dict) -> dict:
    """
    Reproduction of predict_result()'s historical-rate lines, BEFORE
    normalization. Source of truth: match_predictor.py predict_result(),
    the home_win_rate/away_win_rate/draw_base/hist_total/hist_home/
    hist_away/hist_draw lines. KEEP IN SYNC with that function.
    """
    from src.models.match_predictor import HOME_ADVANTAGE

    hp = profiles[home]
    ap = profiles[away]

    home_win_rate = hp.get("home_win_rate", hp.get("win_rate", 0.45))
    away_win_rate = ap.get("away_win_rate", ap.get("win_rate", 0.30))
    draw_base = (hp.get("draw_rate", 0.25) + ap.get("draw_rate", 0.25)) / 2

    hist_total = home_win_rate + away_win_rate + draw_base
    hist_home = home_win_rate / hist_total
    hist_away = away_win_rate / hist_total
    hist_draw = draw_base / hist_total
    return {
        "home_win_rate": home_win_rate,
        "away_win_rate": away_win_rate,
        "draw_base": round(draw_base, 3),
        "home_advantage_const": HOME_ADVANTAGE,
        "hist_home": round(hist_home, 3),
        "hist_away": round(hist_away, 3),
        "hist_draw": round(hist_draw, 3),
        "hist_sum_check": round(hist_home + hist_away + hist_draw, 4),
    }


def raw_form_components(home: str, away: str, profiles: dict) -> dict:
    """
    Reproduction of predict_result()'s form-score lines, BEFORE
    normalization. Source of truth: match_predictor.py predict_result(),
    the home_form/away_form/total_form/form_home/form_away/form_draw
    lines. KEEP IN SYNC with that function.
    """
    from src.models.match_predictor import HOME_ADVANTAGE

    hp = profiles[home]
    ap = profiles[away]

    home_form = hp.get("form_score", 0.5)
    away_form = ap.get("form_score", 0.5)
    total_form = home_form + away_form + 0.25
    form_home = home_form / total_form
    form_away = away_form / total_form
    form_draw = 0.25 / total_form

    return {
        "home_form": home_form,
        "away_form": away_form,
        "form_home": round(form_home, 3),
        "form_away": round(form_away, 3),
        "form_draw": round(form_draw, 3),
        # NOT expected to be exactly 1.0 -- predict_result() adds
        # HOME_ADVANTAGE*0.5 to the numerator of form_home only, without
        # adding the matching amount to total_form's denominator the way
        # the historical-rate block does. Printed here so the drift is
        # visible rather than silently absorbed into the final blend.
        "form_sum_check": round(form_home + form_away + form_draw, 4),
    }


def stage_b_elo_plus_hist(elo: dict, hist: dict) -> dict:
    """
    Stage B: elo (50%) + hist (30%) ONLY, form excluded, renormalized
    to the 0.80 weight actually used so the three values sum to 1.
    This isolates what historical rates alone shift, relative to
    Elo-only -- not a line that exists in predict_result() itself.
    """
    raw_home = elo["home_win"] * 0.50 + hist["hist_home"] * 0.30
    raw_away = elo["away_win"] * 0.50 + hist["hist_away"] * 0.30
    raw_draw = elo["draw"] * 0.50 + hist["hist_draw"] * 0.30
    total = raw_home + raw_away + raw_draw
    return {
        "home_win": round(raw_home / total, 3),
        "away_win": round(raw_away / total, 3),
        "draw": round(raw_draw / total, 3),
    }


def stage_c_full_preh2h(elo: dict, hist: dict, form: dict) -> dict:
    """
    Stage C: full elo(50%) + hist(30%) + form(20%) blend, matching
    predict_result()'s home_win/away_win/draw lines EXACTLY, before
    H2H and before final normalization. Source of truth:
    match_predictor.py predict_result(), the "# Blend" block.
    KEEP IN SYNC with that function.
    """
    home_win = (elo["home_win"] * 0.50) + \
        (hist["hist_home"] * 0.30) + (form["form_home"] * 0.20)
    away_win = (elo["away_win"] * 0.50) + \
        (hist["hist_away"] * 0.30) + (form["form_away"] * 0.20)
    draw = (elo["draw"] * 0.50) + (hist["hist_draw"] *
                                   0.30) + (form["form_draw"] * 0.20)
    return {
        "home_win": round(home_win, 4),
        "away_win": round(away_win, 4),
        "draw": round(draw, 4),
        "presum_check": round(home_win + away_win + draw, 4),
    }


def stage_d_post_h2h(stage_c: dict, home: str, away: str, h2h_data: dict) -> dict:
    """
    Stage D: predict_result()'s H2H re-blend, reproduced. As of the
    draw-blending fix, all three outcomes (home_win, away_win, draw)
    are now corrected against real h2h rates when h2h fires -- draw is
    no longer carried through unchanged from stage C. Source of truth:
    match_predictor.py predict_result(), the "# H2H adjustment" block.
    KEEP IN SYNC with that function.
    """
    from src.models.match_predictor import get_h2h

    home_win = stage_c["home_win"]
    away_win = stage_c["away_win"]
    draw = stage_c["draw"]
    h2h_fired = False

    h2h = get_h2h(home, away, h2h_data)
    if h2h and h2h["matches"] >= 3:
        h2h_fired = True
        h2h_home = h2h["home_wins"] / h2h["matches"]
        h2h_away = h2h["away_wins"] / h2h["matches"]
        h2h_draw = h2h["draws"] / h2h["matches"]
        home_win = (home_win * 0.80) + (h2h_home * 0.20)
        away_win = (away_win * 0.80) + (h2h_away * 0.20)
        draw = (draw * 0.80) + (h2h_draw * 0.20)

    return {
        "home_win": round(home_win, 4),
        "away_win": round(away_win, 4),
        "draw": round(draw, 4),
        "h2h_fired": h2h_fired,
        "presum_check": round(home_win + away_win + draw, 4),
    }


def stage_e_final_normalized(stage_d: dict) -> dict:
    """
    Normalize stage D, reproducing predict_result()'s final
    normalization lines exactly. KEEP IN SYNC with that function.
    """
    total = stage_d["home_win"] + stage_d["away_win"] + stage_d["draw"]
    return {
        "home_win": round(stage_d["home_win"] / total, 3),
        "away_win": round(stage_d["away_win"] / total, 3),
        "draw": round(stage_d["draw"] / total, 3),
    }


def real_predict_result(home: str, away: str, profiles: dict, h2h_data: dict, elo_path: str) -> dict:
    """REAL call to predict_result() — used to validate the
    reproduction above is still in sync."""
    from src.models.match_predictor import predict_result

    return predict_result(home, away, profiles, h2h_data, elo_path=elo_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", default=None,
                        help="path to team_profiles snapshot")
    parser.add_argument("--h2h", default=None, help="path to h2h snapshot")
    parser.add_argument("--elo", default=None,
                        help="path to elo ratings snapshot")
    args = parser.parse_args()

    from src.models.match_predictor import load_profiles, load_h2h, FORCE_PROMOTED

    print(f"profiles={args.profiles or '(live)'}  h2h={args.h2h or '(live)'}  "
          f"elo={args.elo or '(live)'}\n")

    profiles = load_profiles(args.profiles)
    h2h_data = load_h2h(args.h2h)

    rows = []
    sync_mismatches = []

    for home, away, label in SAMPLE_FIXTURES:
        profiles = ensure_team_profiles(profiles, [home, away], FORCE_PROMOTED)

        elo = stage_a_elo_only(home, away, args.elo)
        hist = raw_hist_components(home, away, profiles)
        form = raw_form_components(home, away, profiles)

        b = stage_b_elo_plus_hist(elo, hist)
        c = stage_c_full_preh2h(elo, hist, form)
        d = stage_d_post_h2h(c, home, away, h2h_data)
        e_repro = stage_e_final_normalized(d)
        e_real = real_predict_result(home, away, profiles, h2h_data, args.elo)

        # Validate reproduction against the real function. Allow tiny
        # float rounding drift (0.002) but flag anything bigger -- that
        # means stage_b/c/d above have gone stale relative to the live
        # predict_result() and must be fixed before trusting this run.
        mismatch = abs(e_repro["home_win"] - e_real["home_win"]) > 0.005
        if mismatch:
            sync_mismatches.append(f"{home} vs {away}")

        rows.append({
            "fixture": f"{home} vs {away}", "label": label,
            "elo": elo, "hist": hist, "form": form,
            "b": b, "c": c, "d": d, "e_repro": e_repro, "e_real": e_real,
            "mismatch": mismatch,
        })

    print("=" * 130)
    print("RESULT — home_win / draw / away_win through the stack")
    print("=" * 130)

    for r in rows:
        print(f"\n{r['fixture']}  ({r['label']})")
        print(f"  raw inputs:  home_win_rate={r['hist']['home_win_rate']}  "
              f"away_win_rate={r['hist']['away_win_rate']}  draw_base={r['hist']['draw_base']}  "
              f"home_form={r['form']['home_form']}  away_form={r['form']['away_form']}  "
              f"HOME_ADVANTAGE={r['hist']['home_advantage_const']}")
        print(f"  A. Elo only:              H={r['elo']['home_win']:.3f}  D={r['elo']['draw']:.3f}  "
              f"A={r['elo']['away_win']:.3f}   (elo {r['elo']['home_elo']} vs {r['elo']['away_elo']})")
        print(f"  B. + historical (30%):    H={r['b']['home_win']:.3f}  D={r['b']['draw']:.3f}  "
              f"A={r['b']['away_win']:.3f}   (Δhome A→B: {r['b']['home_win']-r['elo']['home_win']:+.3f})")
        print(f"  C. + form (20%), pre-H2H: H={r['c']['home_win']:.3f}  D={r['c']['draw']:.3f}  "
              f"A={r['c']['away_win']:.3f}   (Δhome B→C: {r['c']['home_win']-r['b']['home_win']:+.3f})  "
              f"[presum={r['c']['presum_check']}]")
        print(f"  D. + H2H (fired={r['d']['h2h_fired']}):    H={r['d']['home_win']:.3f}  D={r['d']['draw']:.3f}  "
              f"A={r['d']['away_win']:.3f}   (Δhome C→D: {r['d']['home_win']-r['c']['home_win']:+.3f})  "
              f"[draw now h2h-adjusted when fired]")
        print(f"  E. Final normalized:      H={r['e_repro']['home_win']:.3f}  D={r['e_repro']['draw']:.3f}  "
              f"A={r['e_repro']['away_win']:.3f}")
        print(f"     real predict_result(): H={r['e_real']['home_win']:.3f}  D={r['e_real']['draw']:.3f}  "
              f"A={r['e_real']['away_win']:.3f}" +
              ("   ⚠ MISMATCH vs reproduction — see note below" if r["mismatch"] else "   (matches reproduction ✓)"))

    avg_draw_final = sum(r["e_real"]["draw"]
                         for r in rows) / len(rows)
    avg_home_c = sum(r["c"]["home_win"] for r in rows) / len(rows)
    avg_home_final = sum(r["e_real"]["home_win"] for r in rows) / len(rows)
    avg_away_c = sum(r["c"]["away_win"] for r in rows) / len(rows)
    avg_away_final = sum(r["e_real"]["away_win"] for r in rows) / len(rows)

    print(f"\n  AVERAGES across {len(rows)} fixtures:")
    print(
        f"    home_win:  pre-H2H (C)={avg_home_c:.3f}   final (E)={avg_home_final:.3f}")
    print(
        f"    away_win:  pre-H2H (C)={avg_away_c:.3f}   final (E)={avg_away_final:.3f}")
    print(f"    draw:      final (E)={avg_draw_final:.3f}")
    print(
        f"    (Compare avg_draw_final to your calibration report's actual draw rate")
    print(f"     or backtest's real draw frequency by hand -- if final predicted draw")
    print(f"     sits notably below the real rate, that's direct evidence draws are")
    print(f"     being underweighted, which would inflate both home_win and away_win.)")

    if sync_mismatches:
        print("\n" + "!" * 130)
        print(f"  SYNC WARNING: reproduction diverged from real predict_result() for: "
              f"{', '.join(sync_mismatches)}")
        print("  This means stage_b/c/d in this script no longer match the live")
        print("  match_predictor.py predict_result() function. Do not trust the A→D")
        print("  stage breakdown above until this is fixed -- check predict_result()")
        print(
            "  for changes since this script was last updated (see the 'KEEP IN SYNC'")
        print("  comments on raw_hist_components(), raw_form_components(),")
        print("  stage_c_full_preh2h(), and stage_d_post_h2h()).")
        print("!" * 130)

    print("\n" + "=" * 130)
    print("READING THIS")
    print("=" * 130)
    print(
        "For fixtures aimed at the home_win 20-40% bucket (Sheffield United/Wolves/Leeds\n"
        "vs strong away sides): watch whether stage A (Elo alone) already sits well below\n"
        "20%, and how much stages B and C pull it back up. If Elo alone says e.g. 8-12%\n"
        "but the final (E) lands at 25-35%, hist_home and form_home are the source --\n"
        "check their raw inputs above. Both hist_home and form_home have a constant term\n"
        "added to the numerator only (HOME_ADVANTAGE and HOME_ADVANTAGE*0.5) which can act\n"
        "as a floor when home_win_rate/home_form are themselves very low, since the home\n"
        "team's historical win rate already reflects real home-venue performance before\n"
        "this extra constant is added on top -- worth checking whether that's double-\n"
        "counting home advantage rather than a genuine independent signal.\n\n"
        "For fixtures aimed at the away_win 50-80% bucket (Brighton/Everton/Forest vs\n"
        "strong away sides): same read, but watch away_win instead, and also watch draw.\n"
        "Stage D never adjusts draw, only home_win/away_win -- if predicted draw is\n"
        "consistently lower than real draw frequency (see the average printed above),\n"
        "that alone would inflate BOTH home_win and away_win's calibration in the same\n"
        "direction, which matches the pattern in the calibration report better than a\n"
        "simple 'too much home bias' explanation would (that would inflate home_win while\n"
        "deflating away_win, not inflate both).\n\n"
        "If the SYNC WARNING above fired for any fixture, fix that first -- everything else\n"
        "in this readout is unreliable until the reproduction matches the real function\n"
        "again.\n"
    )


if __name__ == "__main__":
    main()
