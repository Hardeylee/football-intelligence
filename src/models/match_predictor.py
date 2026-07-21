"""
Match Prediction Engine — Club Football
Takes two team names, returns market probabilities for:
- Result (Home/Draw/Away)
- Over/Under Goals (1.5, 2.5, 3.5)
- BTTS
- Yellow Cards
- Corners

PATCH NOTE (backtest injection parameters):

predict_match() used to read PROFILES_FILE/H2H_FILE/FORCE_PROMOTED
directly from module globals with no override, and predict_goals()
always applied the live player_availability adjustment unconditionally.
This meant backtester_v4.py's snapshot-based approach (see
build_snapshot_profiles.py / build_snapshot_elo.py) had no way to
actually reach match_predictor.py -- every backtest call failed with
"unexpected keyword argument" since these parameters didn't exist here
yet, even though epl_elo.py had already been refactored the same way.

Fix: predict_match() now accepts profiles_path, h2h_path, elo_path,
apply_availability, and force_promoted as optional parameters. All
default to None/True, which reproduces the exact previous behavior
(live production files, FORCE_PROMOTED module constant, availability
always applied) -- so every existing call site (telegram_bot.py's
handle_epl_match/handle_gw_request, the __main__ block below) keeps
working unchanged with zero code changes required there.

SECOND BUG CAUGHT DURING THIS REFACTOR, not just a mechanical port:
the missing-team fallback loop checked `if team in PROMOTED_TEAM_PROFILES`
unconditionally, regardless of force_promoted. PROMOTED_TEAM_PROFILES is
keyed for 2026/27's promoted teams (2025/26 Championship form). A team
missing from a historical snapshot (e.g. Ipswich, correctly absent from
team_profiles_asof_24-25.json since they weren't in the EPL in 22-23/
23-24) would silently receive their 2025/26 form via this fallback even
with force_promoted=set() passed in -- the exact same "borrowed future
rating" leak build_snapshot_elo.py already diagnosed and fixed for Elo,
just hiding in this file's fallback path instead. Fixed: the
PROMOTED_TEAM_PROFILES check is now gated on `team in active_force_promoted`
as well, so an empty force_promoted set actually means "never use these
overrides," not "use them only when the module constant happens to
already forbid it."

PATCH NOTE (home_win compression correction, "Candidate C"):

Session-long investigation (see diagnose_elo_only_calibration.py,
diagnose_elo_vs_blend_matched.py, diagnose_team_dominance_check.py,
diagnose_hist_form_vs_elo_full.py, diagnose_compression_fix_candidates.py,
diagnose_candidate_c_out_of_sample.py) found predict_result()'s home_win
was overconfident specifically in the 20-40% range, with two separate,
independently-confirmed causes:

  1. Elo itself (predict_result_elo(), unblended) is somewhat
     overconfident around 30-40% -- an upstream issue in epl_elo.py,
     NOT addressed by this patch. Tracked as a separate open item.

  2. hist_home and form_home are structurally COMPRESSED relative to
     elo_home across their ENTIRE range (Pearson correlation -0.869 /
     -0.931 against elo_home, linear across all 10 deciles, not just
     the extremes) -- they can't swing as far from 50% as Elo can, so
     blending them in always pulls Elo's confident home_win predictions
     back toward the middle. This helps away_win's high buckets (Elo
     alone was overconfident there; already confirmed clean this
     session) but actively hurts home_win's low buckets, where Elo
     alone was already reasonably calibrated and the blend made it
     worse (home_win 20-30%: Elo-only gap -4.5%/ok, full-pipeline gap
     -21.0%/bad).

This patch addresses #2 only. It rescales hist_home/form_home in logit
space to match elo_home's spread (constants measured directly from two
INDEPENDENT halves of the 2024/25 season and confirmed stable --
stretch_hist 2.005x vs 2.035x, stretch_form 2.325x vs 2.329x -- so this
is not fit to the same data it's being validated against), then tapers
that correction off above elo_home~45% (a structural choice, not a
measured statistic) since an earlier untapered version measurably
damaged the already-well-calibrated 50-90% range.

Only home_win's hist/form components are corrected -- away_win and
draw's hist/form components, and the H2H stage, are all untouched.

Validated via Brier score (lower = better), home_win only:
  in-sample  (constants + grading both from final holdout): 0.2095 -> 0.2076
  out-of-sample (constants from validation half, graded on final holdout,
                 never used to derive the constants): 0.2095 -> 0.2076
Zero cost to draw or away_win Brier scores in either run. home_win
20-30% bucket gap improved from -21.1% to roughly -11.5% (real
progress, not fully closed -- the remainder is cause #1 above, upstream
in Elo, out of scope for this patch). 30-40% is largely untouched by
design, since diagnose_hist_form_vs_elo_full.py's decile table showed
compression's contribution there was already small before the taper.

This patch does NOT change hist_away/form_away/hist_draw/form_draw, the
H2H block, or any other market (goals/cards/corners). It only touches
predict_result()'s home_win computation and adds the constants/helpers
above it.

PATCH NOTE (MatchContext cutover):

predict_goals()/predict_result()/predict_cards()/predict_corners() used
to each take their own subset of (home, away, profiles, h2h_data,
elo_path, xg_path, apply_availability) and, in predict_goals()/
predict_result(), independently re-derived things predict_match() had
already resolved -- notably each of predict_goals() and predict_result()
called get_h2h(home, away, h2h_data) separately (same lookup run twice
per predict_match() call), and predict_goals() loaded xg_profiles and
predict_result() loaded elo_ratings via their own module-level imports,
duplicating work predict_match() could do once.

Fix: predict_match() now builds a single MatchContext via
resolve_match_context() (see match_context.py) and passes that to all
four engines instead. resolve_match_context() also absorbs the
missing-team profile fallback loop that used to live inline in
predict_match() -- same logic, same force_promoted gating, just moved
to one place instead of being duplicated across this file and any
diagnostic scripts' own ensure_team_profiles()-style helpers.

predict_match()'s own public signature is UNCHANGED -- every existing
call site (telegram_bot.py, the __main__ block below, backtester_v4.py,
snapshot_golden_predictions.py) keeps working with zero changes. Only
predict_goals()/predict_result()/predict_cards()/predict_corners()'s
signatures changed, since match_predictor.py is the only file that
calls them directly (grepped for external callers before this change
shipped -- see MatchContext design conversation for the check run).

Manager/referee/availability data are deliberately NOT part of
MatchContext -- see match_context.py's module docstring for why (their
loaders don't support point-in-time snapshot paths yet). Those three
are still fetched exactly as before: apply_manager_adjustments() and
get_formation_adjustment() are still called from predict_match() after
the four engines run, unchanged; get_xg_reduction() is still called
from inside predict_goals(), unchanged, gated on apply_availability
exactly as before.
"""

import json
import math
import os
import sys
from datetime import datetime

# PROJECT_ROOT-from-__file__ fix -- without this, running this file
# directly (`python src\models\match_predictor.py`) fails with
# ModuleNotFoundError: No module named 'src', because Python only puts
# this file's own directory (src/models) on sys.path, not the project
# root. Same fix already applied to backtester_v4.py and every
# diagnose_*.py script in src/utils for the identical reason -- this
# file just never needed it before because its first `from src....`
# import used to happen deeper inside predict_goals()/predict_result(),
# not at the top of predict_match() itself.
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

PROFILES_FILE = "data/team_profiles.json"
H2H_FILE = "data/h2h.json"

HOME_ADVANTAGE = 0.06

# Same 20% Championship-to-EPL step-up discount as
# xg_scraper.PROMOTION_DISCOUNT (0.80), applied to PROMOTED_TEAM_PROFILES'
# win rates below. Kept as a separate constant (not imported) since
# PROMOTED_TEAM_PROFILES is a module-level dict built at import time and
# xg_scraper is otherwise only imported locally inside functions in this
# file. If xg_scraper.PROMOTION_DISCOUNT ever changes, update this to match.
PROMOTED_WIN_RATE_DISCOUNT = 0.80

# ── COMPRESSION CORRECTION CONSTANTS ("Candidate C") ────────────────
# See PATCH NOTE above for the full investigation trail. Summary of
# where each number comes from, so this isn't an unexplained magic
# constant later:
#
# COMPRESSION_STRETCH_HIST / COMPRESSION_STRETCH_FORM: the ratio of
# elo_home's logit-space standard deviation to hist_home's / form_home's,
# i.e. "how much wider elo_home's spread is than hist_home's/form_home's".
# Measured independently on two non-overlapping halves of the 2024/25
# season and averaged, since both measurements agreed closely:
#     stretch_hist: 2.005x (final holdout half) / 2.035x (validation half) -> avg 2.020
#     stretch_form: 2.325x (final holdout half) / 2.329x (validation half) -> avg 2.327
#
# COMPRESSION_MEAN_HIST_LOGIT / COMPRESSION_MEAN_FORM_LOGIT: the average
# logit-space value of hist_home / form_home, used as the center point
# the rescale stretches around (preserves central tendency, only changes
# spread). Taken from the validation half specifically -- the only half
# with an explicitly recorded measurement -- but the close agreement of
# the stretch factors across both halves suggests this isn't sensitive
# to which half it came from.
#
# COMPRESSION_TAPER_THRESHOLD / COMPRESSION_TAPER_STEEPNESS: structural
# design choices, NOT measured statistics. An earlier untapered version
# of this correction (applied uniformly across the whole range) fixed
# home_win 20-30% but measurably broke the already-well-calibrated
# 50-90% range (home_win 60-70% gap went from +3.1%/ok to -13.0%/bad).
# The taper fades the correction to ~0 above elo_home~45%, so it only
# applies where the diagnosed problem (compression pulling weak-home
# predictions up) actually lives.
COMPRESSION_STRETCH_HIST = 2.020
COMPRESSION_STRETCH_FORM = 2.327
COMPRESSION_MEAN_HIST_LOGIT = -0.194
COMPRESSION_MEAN_FORM_LOGIT = -0.525
COMPRESSION_TAPER_THRESHOLD = 0.45
COMPRESSION_TAPER_STEEPNESS = 14


def _logit(p: float) -> float:
    """Log-odds of p, clamped away from 0/1 to avoid math domain errors."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _compression_taper_weight(elo_home: float) -> float:
    """
    ~1.0 when elo_home is well below COMPRESSION_TAPER_THRESHOLD (the
    correction applies at close to full strength), fading smoothly to
    ~0.0 above it (correction effectively switched off). Smooth, not a
    hard cutoff, to avoid a discontinuity in predicted probability as
    elo_home crosses the threshold.
    """
    return _sigmoid(COMPRESSION_TAPER_STEEPNESS *
                    (COMPRESSION_TAPER_THRESHOLD - elo_home))


def _apply_compression_correction(value: float, elo_home: float,
                                  mean_logit: float, stretch: float) -> float:
    """
    Rescales `value` (hist_home or form_home) in logit space to better
    match elo_home's spread, centered on `mean_logit` so only spread
    changes, not central tendency -- then blends that rescaled value
    back toward the original using the taper weight, so the correction
    only meaningfully applies where elo_home is low. See PATCH NOTE
    above for the full derivation and validation of these constants.
    """
    value_logit = _logit(value)
    rescaled = _sigmoid(mean_logit + (value_logit - mean_logit) * stretch)
    tw = _compression_taper_weight(elo_home)
    return tw * rescaled + (1 - tw) * value


# Promoted teams forced to use Championship-based profiles
# even if stale historical EPL data exists
FORCE_PROMOTED = {"Ipswich", "Coventry City", "Hull City"}

# Explicit profiles for promoted teams built from Championship data.
#
# win_rate / draw_rate / loss_rate / home_win_rate / away_win_rate were
# CORRECTED against the final 2025/26 Championship table and FootyStats
# results (Coventry finished 1st/champions: 27W-11D-7L in 45 games;
# Ipswich 2nd: 22W-15D-8L; Hull 6th: 23W-11D-15L in a longer,
# playoff-inclusive sample). The previous hardcoded values badly
# understated Coventry and Ipswich specifically -- e.g. Coventry (the
# eventual champions) was coded with a 38% win / 38% loss rate, and
# Ipswich (2nd place) was coded with a 53% loss rate. Both looked like
# relegation-threatened sides rather than the two best teams in the
# division. home_win_rate/away_win_rate are DERIVED estimates (the
# original home/away skew shape preserved, re-anchored to the corrected
# overall rate) rather than independently verified splits.
#
# avg_yellow_cards was corrected via Sofascore end-of-season data.
# avg_corners_for / avg_corners_against and their home/away splits were
# CORRECTED via SoccerStats.com's Championship 2025/26 corner splits
# (exact home/away/total, for AND against -- not derived estimates).
# These independently corroborate the Sofascore corners-for figures used
# for the yellow-card fix (Coventry 5.30 vs Sofascore 5.3, Ipswich 5.70
# vs 5.7), which is a good cross-check that both sources are reliable.
#
# STILL UNVERIFIED / OUT OF SCOPE, flagged rather than silently left:
# - form_score for all three teams
# - Red cards: Sofascore gave season totals (Coventry 3, Ipswich 1,
#   Hull 2), not per-match rates, and predict_cards() doesn't currently
#   read a red-card field at all -- only yellows feed the cards market.
#   Not wired in; would need a logic change in predict_cards(), not just
#   a value here, if red-card risk is ever wanted as a signal.
#
# IMPORTANT for backtesting: this dict is ONLY valid for 2026/27 live
# production use. It must never be applied to a historical backtest for
# a different season -- see predict_match()'s force_promoted parameter
# and the PATCH NOTE above.
PROMOTED_TEAM_PROFILES = {
    "Coventry City": {
        "win_rate":        0.48,   # was 0.60 -- 0.60 * 0.80 discount
        "draw_rate":       0.24,
        "loss_rate":       0.28,   # was 0.16 -- absorbs the 0.12 discounted off win_rate
        "btts_rate":       0.59,
        "over15_rate":     0.83,
        "over25_rate":     0.54,
        "clean_sheet_rate": 0.21,
        "home_win_rate":   0.592,  # was 0.74 -- 0.74 * 0.80 discount
        "home_avg_goals_scored":   1.83,
        "home_avg_goals_conceded": 1.27,
        "away_win_rate":   0.368,  # was 0.46 -- 0.46 * 0.80 discount
        "away_avg_goals_scored":   1.46,
        "away_avg_goals_conceded": 1.65,
        "avg_yellow_cards":    1.5,
        "avg_corners_for":     5.30,
        "avg_corners_against": 4.20,
        "home_avg_yellow_cards":   1.3,
        "away_avg_yellow_cards":   1.7,
        "home_avg_corners_for":    5.91,
        "home_avg_corners_against": 3.48,
        "away_avg_corners_for":    4.70,
        "away_avg_corners_against": 4.91,
        "form_score":      0.44,  # NOT re-verified in this pass
    },
    "Hull City": {
        "win_rate":        0.376,  # was 0.47 -- 0.47 * 0.80 discount
        "draw_rate":       0.22,
        "loss_rate":       0.404,  # was 0.31 -- absorbs the 0.094 discounted off win_rate
        "btts_rate":       0.50,
        "over15_rate":     0.78,
        "over25_rate":     0.46,
        "clean_sheet_rate": 0.26,
        "home_win_rate":   0.48,   # was 0.60 -- 0.60 * 0.80 discount
        "home_avg_goals_scored":   1.52,
        "home_avg_goals_conceded": 1.21,
        "away_win_rate":   0.272,  # was 0.34 -- 0.34 * 0.80 discount
        "away_avg_goals_scored":   1.18,
        "away_avg_goals_conceded": 1.58,
        "avg_yellow_cards":    2.5,
        "avg_corners_for":     4.50,
        "avg_corners_against": 5.98,
        "home_avg_yellow_cards":   2.33,
        "away_avg_yellow_cards":   2.67,
        "home_avg_corners_for":    4.52,
        "home_avg_corners_against": 4.57,
        "away_avg_corners_for":    4.48,
        "away_avg_corners_against": 7.39,
        "form_score":      0.40,  # NOT re-verified in this pass
    },
    "Ipswich": {
        "win_rate":        0.392,  # was 0.49 -- 0.49 * 0.80 discount
        "draw_rate":       0.33,
        "loss_rate":       0.278,  # was 0.18 -- absorbs the 0.098 discounted off win_rate
        "btts_rate":       0.50,
        "over15_rate":     0.74,
        "over25_rate":     0.45,
        "clean_sheet_rate": 0.18,
        "home_win_rate":   0.472,  # was 0.59 -- 0.59 * 0.80 discount
        "home_avg_goals_scored":   1.26,
        "home_avg_goals_conceded": 1.42,
        "away_win_rate":   0.304,  # was 0.38 -- 0.38 * 0.80 discount
        "away_avg_goals_scored":   0.95,
        "away_avg_goals_conceded": 1.89,
        "avg_yellow_cards":    2.0,
        "avg_corners_for":     5.70,
        "avg_corners_against": 3.93,
        "home_avg_yellow_cards":   1.82,
        "away_avg_yellow_cards":   2.18,
        "home_avg_corners_for":    6.17,
        "home_avg_corners_against": 3.83,
        "away_avg_corners_for":    5.22,
        "away_avg_corners_against": 4.04,
        "form_score":      0.32,  # NOT re-verified in this pass
    },
}


def load_profiles(path: str = None) -> dict:
    """Pass a different path to load a point-in-time snapshot instead
    of the live production file."""
    with open(path or PROFILES_FILE) as f:
        return json.load(f)["teams"]


def load_h2h(path: str = None) -> dict:
    """Pass a different path to load a point-in-time snapshot instead
    of the live production file."""
    with open(path or H2H_FILE) as f:
        return json.load(f)["h2h"]


def get_h2h(home: str, away: str, h2h: dict) -> dict:
    key = f"{home}_vs_{away}"
    reverse = f"{away}_vs_{home}"
    return h2h.get(key) or h2h.get(reverse) or {}


def _build_league_average(profiles: dict) -> dict:
    """Build a league average profile from all existing team profiles."""
    if not profiles:
        return {}

    keys = [
        "win_rate", "draw_rate", "loss_rate",
        "btts_rate", "over15_rate", "over25_rate",
        "home_win_rate", "home_avg_goals_scored", "home_avg_goals_conceded",
        "away_win_rate", "away_avg_goals_scored", "away_avg_goals_conceded",
        "avg_yellow_cards", "avg_corners_for", "avg_corners_against",
        "form_score", "clean_sheet_rate",
        "home_avg_yellow_cards", "away_avg_yellow_cards",
        "home_avg_corners_for", "home_avg_corners_against",
        "away_avg_corners_for", "away_avg_corners_against",
    ]

    avg = {}
    for key in keys:
        vals = [p[key] for p in profiles.values() if key in p]
        avg[key] = round(sum(vals) / len(vals), 3) if vals else 0.5

    # Promoted teams are weaker than average
    avg["win_rate"] = round(avg["win_rate"] * 0.85, 3)
    avg["home_win_rate"] = round(avg["home_win_rate"] * 0.85, 3)
    avg["away_win_rate"] = round(avg["away_win_rate"] * 0.85, 3)
    avg["form_score"] = round(avg["form_score"] * 0.85, 3)

    return avg


def predict_goals(ctx, apply_availability: bool = True) -> dict:
    """
    Predict goals using xG data (primary) blended with
    historical rates (secondary) and H2H (tertiary).

    ctx: a MatchContext (see match_context.py), built once by
    predict_match() via resolve_match_context(). Supplies home/away
    profiles, the resolved h2h pair, and the two teams' xG profile
    entries -- all previously loaded independently inside this
    function.

    apply_availability: when False (backtesting), skips the player
    availability adjustment entirely. Kept as a separate parameter
    rather than folded into MatchContext, since availability isn't
    point-in-time snapshot-safe yet -- see match_context.py's module
    docstring.
    """
    hp = ctx.home_profile
    ap = ctx.away_profile

    home_xg_data = ctx.xg_profiles["home"]
    away_xg_data = ctx.xg_profiles["away"]

    if home_xg_data and away_xg_data:
        home_xg = (home_xg_data["avg_xg_for"] +
                   away_xg_data["avg_xg_against"]) / 2
        away_xg = (away_xg_data["avg_xg_for"] +
                   home_xg_data["avg_xg_against"]) / 2

        over15_rate = (
            home_xg_data["xg_over15_rate"] * 0.35 +
            away_xg_data["xg_over15_rate"] * 0.35 +
            hp.get("over15_rate", 0.75) * 0.15 +
            ap.get("over15_rate", 0.75) * 0.15
        )
        over25_rate = (
            home_xg_data["xg_over25_rate"] * 0.35 +
            away_xg_data["xg_over25_rate"] * 0.35 +
            hp.get("over25_rate", 0.55) * 0.15 +
            ap.get("over25_rate", 0.55) * 0.15
        )
        btts_rate = (
            home_xg_data["xg_btts_rate"] * 0.35 +
            away_xg_data["xg_btts_rate"] * 0.35 +
            hp.get("btts_rate", 0.55) * 0.15 +
            ap.get("btts_rate", 0.55) * 0.15
        )
        data_source = "xG"

    else:
        home_xg = (hp["home_avg_goals_scored"] +
                   ap["away_avg_goals_conceded"]) / 2
        away_xg = (ap["away_avg_goals_scored"] +
                   hp["home_avg_goals_conceded"]) / 2
        over15_rate = (hp.get("over15_rate", 0.75) +
                       ap.get("over15_rate", 0.75)) / 2
        over25_rate = (hp.get("over25_rate", 0.55) +
                       ap.get("over25_rate", 0.55)) / 2
        btts_rate = (hp.get("btts_rate", 0.55) + ap.get("btts_rate", 0.55)) / 2
        data_source = "historical"

    # H2H adjustment
    h2h = ctx.h2h
    if h2h and h2h["matches"] >= 3:
        h2h_avg = h2h["avg_goals"]
        home_xg = (home_xg * 0.80) + (h2h_avg * 0.5 * 0.20)
        away_xg = (away_xg * 0.80) + (h2h_avg * 0.5 * 0.20)
        h2h_over25 = 1.0 if h2h_avg > 2.5 else 0.0
        over25_rate = (over25_rate * 0.85) + (h2h_over25 * 0.15)

    over35_rate = over25_rate * 0.48

    # ── PLAYER AVAILABILITY ADJUSTMENT ──────────────────────────
    # Applied last, after xG/historical/H2H blending, since it represents
    # "this team is missing key players right now" and should apply
    # regardless of which upstream data path produced the base numbers.
    # See src/models/player_availability.py -- reduction only triggers
    # for logged-unavailable players whose Opta importance > 0.20.
    if apply_availability:
        from src.models.player_availability import get_xg_reduction
        home_avail = get_xg_reduction(ctx.home_team)
        away_avail = get_xg_reduction(ctx.away_team)
    else:
        home_avail = {"factor": 1.0, "players": []}
        away_avail = {"factor": 1.0, "players": []}

    home_xg = round(home_xg * home_avail["factor"], 2)
    away_xg = round(away_xg * away_avail["factor"], 2)

    # NOTE: over15/over25/over35/btts_rate are NOT derived from home_xg/
    # away_xg via a Poisson relationship in this codebase -- they come
    # from a separate blend of xg_profiles' precomputed rates (see above).
    # Scaling them by the same factor is a reasonable approximation, not
    # an exact derivation -- flagged so this isn't mistaken for more
    # precision than actually exists.
    combined_factor = (home_avail["factor"] + away_avail["factor"]) / 2
    over15_rate = over15_rate * combined_factor
    over25_rate = over25_rate * combined_factor
    over35_rate = over35_rate * combined_factor
    btts_rate = btts_rate * combined_factor

    availability_note = {
        "home_factor": home_avail["factor"],
        "home_players_out": home_avail["players"],
        "away_factor": away_avail["factor"],
        "away_players_out": away_avail["players"],
    }

    return {
        "home_xg":     round(home_xg, 2),
        "away_xg":     round(away_xg, 2),
        "total_xg":    round(home_xg + away_xg, 2),
        "data_source": data_source,
        "over15":      round(min(over15_rate, 0.97), 3),
        "over25":      round(min(over25_rate, 0.95), 3),
        "over35":      round(min(over35_rate, 0.85), 3),
        "under15":     round(max(1 - over15_rate, 0.03), 3),
        "under25":     round(max(1 - over25_rate, 0.05), 3),
        "under35":     round(max(1 - over35_rate, 0.15), 3),
        "btts_yes":    round(min(btts_rate, 0.95), 3),
        "btts_no":     round(max(1 - btts_rate, 0.05), 3),
        "availability": availability_note,
    }


def predict_result(ctx) -> dict:
    """
    Predict match result blending:
    - Elo ratings (50%) — current team strength
    - Historical home/away rates (30%) — venue form
    - Recent form score (20%) — momentum

    ctx: a MatchContext (see match_context.py). Supplies home/away
    profiles, the resolved h2h pair, and the Elo ratings dict --
    previously loaded independently inside this function via
    epl_elo.load_ratings(elo_path).

    NOTE: hist_home/form_home have a compression correction applied
    (see module-level PATCH NOTE and the COMPRESSION_* constants above)
    before entering the blend. hist_away/form_away/hist_draw/form_draw
    are unaffected.
    """
    hp = ctx.home_profile
    ap = ctx.away_profile

    # Elo prediction (50%)
    from src.models.epl_elo import predict_result_elo
    elo_pred = predict_result_elo(
        ctx.home_team, ctx.away_team, ctx.elo_ratings)
    elo_home = elo_pred["home_win"]
    elo_draw = elo_pred["draw"]
    elo_away = elo_pred["away_win"]

    # Historical rates (30%)
    # HOME_ADVANTAGE removed from here -- home_win_rate is already
    # measured from home matches only, so it already reflects whatever
    # home-advantage this team actually gets. Adding HOME_ADVANTAGE on
    # top double-counted it, confirmed via diagnose_stacking.py: every
    # weak-home-vs-strong-away backtest-snapshot fixture showed a
    # consistent unconditional +0.04 to +0.10 pull toward home_win the
    # moment this stage ran, present in ALL 190 backtest matches --
    # which is why it, not the promoted-team or H2H fixes, is the
    # mechanism behind the untouched home_win/away_win calibration
    # buckets. Elo's own home advantage (100 rating points, in
    # predict_result_elo) is kept as the single legitimate application.
    home_win_rate = hp.get("home_win_rate", hp.get("win_rate", 0.45))
    away_win_rate = ap.get("away_win_rate", ap.get("win_rate", 0.30))
    draw_base = (hp.get("draw_rate", 0.25) + ap.get("draw_rate", 0.25)) / 2

    hist_total = home_win_rate + away_win_rate + draw_base
    hist_home = home_win_rate / hist_total
    hist_away = away_win_rate / hist_total
    hist_draw = draw_base / hist_total

    # Form score (20%) -- same reasoning, HOME_ADVANTAGE*0.5 removed.
    home_form = hp.get("form_score", 0.5)
    away_form = ap.get("form_score", 0.5)
    total_form = home_form + away_form + 0.25
    form_home = home_form / total_form
    form_away = away_form / total_form
    form_draw = 0.25 / total_form

    # ── COMPRESSION CORRECTION (home component only) ────────────────
    # hist_home/form_home are structurally compressed relative to
    # elo_home -- see module-level PATCH NOTE for the full investigation
    # and validation. Only the home-side components are corrected;
    # hist_away/form_away/hist_draw/form_draw are left exactly as
    # computed above.
    hist_home = _apply_compression_correction(
        hist_home, elo_home, COMPRESSION_MEAN_HIST_LOGIT, COMPRESSION_STRETCH_HIST)
    form_home = _apply_compression_correction(
        form_home, elo_home, COMPRESSION_MEAN_FORM_LOGIT, COMPRESSION_STRETCH_FORM)

    # Blend
    home_win = (elo_home * 0.50) + (hist_home * 0.30) + (form_home * 0.20)
    away_win = (elo_away * 0.50) + (hist_away * 0.30) + (form_away * 0.20)
    draw = (elo_draw * 0.50) + (hist_draw * 0.30) + (form_draw * 0.20)

    # H2H adjustment
    h2h = ctx.h2h
    if h2h and h2h["matches"] >= 3:
        h2h_home = h2h["home_wins"] / h2h["matches"]
        h2h_away = h2h["away_wins"] / h2h["matches"]
        # was missing entirely -- home_win and away_win were both being
        # corrected against real h2h history, draw wasn't, despite
        # h2h["draws"] being available (format_prediction() already
        # reads it directly). This asymmetry is a likely contributor to
        # the ~4.5-point draw underprediction confirmed via
        # check_draw_rate.py (24.1% actual vs ~19.5% predicted on the
        # diagnose_stacking.py sample).
        h2h_draw = h2h["draws"] / h2h["matches"]
        home_win = (home_win * 0.80) + (h2h_home * 0.20)
        away_win = (away_win * 0.80) + (h2h_away * 0.20)
        draw = (draw * 0.80) + (h2h_draw * 0.20)

    # Normalize
    total = home_win + away_win + draw
    home_win = home_win / total
    away_win = away_win / total
    draw = draw / total

    return {
        "home_win":     round(home_win, 3),
        "draw":         round(draw, 3),
        "away_win":     round(away_win, 3),
        "home_or_draw": round(home_win + draw, 3),
        "away_or_draw": round(away_win + draw, 3),
        "home_elo":     elo_pred.get("home_elo", 1500),
        "away_elo":     elo_pred.get("away_elo", 1500),
    }


def predict_cards(ctx) -> dict:
    """
    Predict yellow cards using home/away split card rates,
    referee tendency, derby factor and manager pressing intensity.

    ctx: a MatchContext. Supplies home/away profiles and the referee
    name -- previously separate (profiles, referee) parameters.
    """
    hp = ctx.home_profile
    ap = ctx.away_profile
    home, away = ctx.home_team, ctx.away_team

    home_cards_rate = hp.get("home_avg_yellow_cards",
                             hp.get("avg_yellow_cards", 1.5))
    away_cards_rate = ap.get("away_avg_yellow_cards",
                             ap.get("avg_yellow_cards", 1.8))

    avg_cards = home_cards_rate + away_cards_rate

    derby_pairs = [
        {"Arsenal", "Tottenham"}, {"Arsenal", "Chelsea"},
        {"Man United", "Man City"},
        {"Liverpool", "Everton"}, {"Liverpool", "Man United"},
        {"Chelsea", "Tottenham"}, {"Newcastle", "Sunderland"},
    ]
    is_derby = {home, away} in derby_pairs
    if is_derby:
        avg_cards *= 1.2

    def cards_prob(line: float, expected: float) -> float:
        """
        Poisson-based replacement for the old hard-capped step function.
        Card counts are discrete and non-negative, which Poisson models
        naturally -- same approach already used for the BTTS fix in
        xg_scraper.derive_market_rates(). The old step function hit its
        1.0 ceiling for 5/7 sample fixtures (diagnose_stacking.py) and
        drove the calibration report's cards overconfidence finding
        (predicted ~84%, actual ~58% on the real n=85 avg_cards>3.5
        bucket). This curve was validated against that same real bucket
        before being wired in: Poisson(4.3) over35 = 0.623, close to the
        actual 0.58 -- a much tighter fit than the old flat 1.0.
        """
        k = int(line) + 1  # 3.5 -> need P(X >= 4)
        cdf = 0.0
        term = math.exp(-expected)
        cdf += term
        for i in range(1, k):
            term *= expected / i
            cdf += term
        return round(min(max(1 - cdf, 0.05), 0.95), 3)

    base_over35 = cards_prob(3.5, avg_cards)
    base_over45 = cards_prob(4.5, avg_cards)

    from src.models.referee_profiler import load_referee_profiles, adjust_cards_for_referee
    ref_profiles = load_referee_profiles()
    ref_adjustment = adjust_cards_for_referee(
        base_over35, base_over45, ctx.referee, ref_profiles)

    return {
        "avg_total_cards":   round(avg_cards, 2),
        "is_derby":          is_derby,
        "over25_cards":      round(min(ref_adjustment["over35_cards"] + 0.15, 0.95), 3),
        "over35_cards":      ref_adjustment["over35_cards"],
        "over45_cards":      ref_adjustment["over45_cards"],
        "under35_cards":     round(1 - ref_adjustment["over35_cards"], 3),
        "referee":           ref_adjustment["referee"],
        "referee_tendency":  ref_adjustment["referee_tendency"],
        "referee_avg_cards": ref_adjustment["referee_avg_cards"],
        "referee_found":     ref_adjustment["referee_found"],
    }


def predict_corners(ctx) -> dict:
    """
    Predict corners using home/away split rates.
    Uses continuous probability function calibrated to EPL actuals.

    ctx: a MatchContext. Supplies home/away profiles.
    """
    hp = ctx.home_profile
    ap = ctx.away_profile

    home_corners_for = hp.get("home_avg_corners_for",
                              hp.get("avg_corners_for", 5.0))
    away_corners_against = ap.get("away_avg_corners_against",
                                  ap.get("avg_corners_against", 5.0))
    away_corners_for = ap.get("away_avg_corners_for",
                              ap.get("avg_corners_for", 4.5))
    home_corners_against = hp.get("home_avg_corners_against",
                                  hp.get("avg_corners_against", 4.5))

    home_expected = (home_corners_for + away_corners_against) / 2
    away_expected = (away_corners_for + home_corners_against) / 2
    avg_corners = home_expected + away_expected

    def corners_prob(line: float, expected: float) -> float:
        """
        Linear calibration anchored to EPL actuals (760 matches):
        Over 8.5: 68.3% | Over 10.5: 46.1% | Over 12.5: 23.8%
        """
        base = {8.5: 0.683, 10.5: 0.461, 12.5: 0.238}
        sensitivity = {8.5: 0.055, 10.5: 0.065, 12.5: 0.060}
        delta = expected - 10.1
        prob = base[line] + (sensitivity[line] * delta)
        return round(min(max(prob, 0.05), 0.95), 3)

    return {
        "avg_total_corners": round(avg_corners, 2),
        "home_expected":     round(home_expected, 2),
        "away_expected":     round(away_expected, 2),
        "over85_corners":    corners_prob(8.5,  avg_corners),
        "over105_corners":   corners_prob(10.5, avg_corners),
        "over125_corners":   corners_prob(12.5, avg_corners),
    }


def predict_match(
    home_team: str,
    away_team: str,
    referee: str = "",
    profiles_path: str = None,
    h2h_path: str = None,
    elo_path: str = None,
    xg_path: str = None,
    apply_availability: bool = True,
    force_promoted: set = None,
) -> dict:
    """
    Master function — runs all engines, returns full prediction.

    profiles_path / h2h_path / elo_path / xg_path: pass point-in-time
    snapshot files to backtest a historical season honestly. Default to
    None, which uses the live production files — existing call sites
    unaffected.

    Signature UNCHANGED from before the MatchContext cutover -- builds
    a MatchContext internally via resolve_match_context() and passes it
    to the four engines. See module-level PATCH NOTE (MatchContext
    cutover) above.
    """
    from src.models.match_context import resolve_match_context

    ctx = resolve_match_context(
        home_team, away_team, referee,
        profiles_path=profiles_path, h2h_path=h2h_path,
        elo_path=elo_path, xg_path=xg_path,
        force_promoted=force_promoted,
    )

    # Preserve the exact console messages the old inline fallback loop
    # produced -- snapshot_golden_predictions.py and other scripts'
    # console output already expect this exact text.
    for team, note in ctx.fallback_notes.items():
        if note == "promoted_profile":
            print(f"[INFO] {team} using promoted team profile")
        else:
            print(
                f"[INFO] {team} not in historical profiles — using league average fallback")

    goals = predict_goals(ctx, apply_availability=apply_availability)
    result = predict_result(ctx)
    cards = predict_cards(ctx)
    corners = predict_corners(ctx)

    h2h_data = ctx.h2h

    # Apply manager tactical adjustments
    from src.models.epl_manager_profiles import apply_manager_adjustments
    mgr_adjusted = apply_manager_adjustments(
        home_team, away_team, goals, cards, corners
    )

    # Apply formation matchup adjustments (30% weight)
    from src.models.formation_engine import get_formation_adjustment
    formation_adj = get_formation_adjustment(home_team, away_team)

    fadj_goals = formation_adj["goals_adjustment"] * 0.30
    fadj_cards = formation_adj["cards_adjustment"] * 0.30
    fadj_corners = formation_adj["corners_adjustment"] * 0.30

    adj_goals = mgr_adjusted["goals"]
    adj_cards = mgr_adjusted["cards"]
    adj_corners = mgr_adjusted["corners"]

    adj_goals["over25"] = round(
        min(max(adj_goals["over25"] + fadj_goals, 0.05), 0.95), 3)
    adj_goals["over15"] = round(
        min(max(adj_goals["over15"] + fadj_goals, 0.05), 0.97), 3)
    adj_goals["btts_yes"] = round(
        min(max(adj_goals["btts_yes"] + fadj_goals, 0.05), 0.95), 3)
    adj_goals["over35"] = round(
        min(max(adj_goals["over35"] + fadj_goals, 0.05), 0.85), 3)
    adj_goals["under25"] = round(1 - adj_goals["over25"], 3)

    adj_cards["over35_cards"] = round(
        min(max(adj_cards["over35_cards"] + fadj_cards, 0.05), 0.95), 3)
    adj_cards["over45_cards"] = round(
        min(max(adj_cards["over45_cards"] + fadj_cards, 0.05), 0.90), 3)
    adj_cards["over25_cards"] = round(
        min(max(adj_cards["over25_cards"] + fadj_cards, 0.05), 0.97), 3)

    adj_corners["over85_corners"] = round(
        min(max(adj_corners["over85_corners"] + fadj_corners, 0.05), 0.95), 3)
    adj_corners["over105_corners"] = round(
        min(max(adj_corners["over105_corners"] + fadj_corners, 0.05), 0.90), 3)

    return {
        "home_team":    home_team,
        "away_team":    away_team,
        "generated":    datetime.now().isoformat(),
        "result":       result,
        "goals":        adj_goals,
        "cards":        adj_cards,
        "corners":      adj_corners,
        "h2h":          h2h_data,
        "home_manager": mgr_adjusted["home_manager"],
        "away_manager": mgr_adjusted["away_manager"],
        "formation":    formation_adj,
    }


def format_prediction(pred: dict) -> str:
    """Print-friendly prediction summary."""
    if "error" in pred:
        return f"ERROR: {pred['error']}"

    h = pred["home_team"]
    a = pred["away_team"]
    r = pred["result"]
    g = pred["goals"]
    c = pred["cards"]
    co = pred["corners"]
    h2h = pred.get("h2h", {})
    fm = pred.get("formation", {})

    lines = [
        f"\n{'='*45}",
        f"  {h} vs {a}",
        f"{'='*45}",
        f"\n📊 RESULT PROBABILITIES",
        f"  {h} Win:    {r['home_win']*100:.1f}%",
        f"  Draw:         {r['draw']*100:.1f}%",
        f"  {a} Win:  {r['away_win']*100:.1f}%",
        f"  {h} DC:   {r['home_or_draw']*100:.1f}%",
        f"  {a} DC:   {r['away_or_draw']*100:.1f}%",
        f"  Elo: {r.get('home_elo', '?')} vs {r.get('away_elo', '?')}",

        f"\n👔 {pred.get('home_manager', {}).get('name', '?')} ({pred.get('home_manager', {}).get('style', '?')})",
        f"   vs {pred.get('away_manager', {}).get('name', '?')} ({pred.get('away_manager', {}).get('style', '?')})",
        f"⚔️ {fm.get('home_formation', '?')} vs {fm.get('away_formation', '?')} — {fm.get('matchup_type', '')}",

        f"\n⚽ GOALS  (xG: {g['home_xg']} - {g['away_xg']})",
        f"  Over 1.5:   {g['over15']*100:.1f}%",
        f"  Over 2.5:   {g['over25']*100:.1f}%",
        f"  Over 3.5:   {g['over35']*100:.1f}%",
        f"  BTTS Yes:   {g['btts_yes']*100:.1f}%",

        f"\n🟨 CARDS  (avg total: {c['avg_total_cards']})",
        f"  Referee: {c['referee']} — {c['referee_tendency']} ({c['referee_avg_cards']} cards/game)",
        f"  Over 2.5:   {c['over25_cards']*100:.1f}%",
        f"  Over 3.5:   {c['over35_cards']*100:.1f}%",
        f"  Over 4.5:   {c['over45_cards']*100:.1f}%",
        f"  Derby match: {'YES ⚠️' if c['is_derby'] else 'No'}",

        f"\n🚩 CORNERS (avg total: {co['avg_total_corners']})",
        f"  Over 8.5:   {co['over85_corners']*100:.1f}%",
        f"  Over 10.5:  {co['over105_corners']*100:.1f}%",
        f"  Over 12.5:  {co['over125_corners']*100:.1f}%",
    ]

    if h2h:
        lines += [
            f"\n📋 H2H ({h2h['matches']} matches)",
            f"  {h} wins: {h2h['home_wins']}",
            f"  {a} wins: {h2h['away_wins']}",
            f"  Draws:    {h2h['draws']}",
            f"  Avg goals per game: {h2h['avg_goals']}",
        ]

    return "\n".join(lines)


if __name__ == "__main__":
    pred = predict_match("Arsenal", "Chelsea")
    print(format_prediction(pred))

    print("\n")

    pred2 = predict_match("Man City", "Liverpool")
    print(format_prediction(pred2))
