"""
MatchContext — immutable per-fixture snapshot of everything predict_match()
needs to hand to its four engines (goals/result/cards/corners).

DESIGN DECISION (stated explicitly, per this project's process rules):
MatchContext holds only the four sources that already support point-in-time
snapshot loading -- profiles, h2h, elo ratings, xG profiles -- via
resolve_match_context()'s profiles_path/h2h_path/elo_path/xg_path params.

Manager profiles (epl_manager_profiles.py), referee profiles
(referee_profiler.py), and player availability (player_availability.py)
are deliberately NOT loaded into MatchContext, because none of their
loader functions currently accept a path override -- they always read
live production JSON (data/opta_tactical_profiles.json,
data/referee_profiles.json, data/player_availability.json /
data/opta_player_importance.json). Folding them into MatchContext today
would make the object claim a point-in-time correctness it can't actually
deliver for those three sources -- exactly the "stale data is silent"
failure mode this project has already hit and fixed twice (Elo
PROMOTED_RATINGS leak, profiles PROMOTED_TEAM_PROFILES leak, both
described in match_predictor.py's and epl_elo.py's own PATCH NOTEs).
This is a correctness decision, not a scoping shortcut.

WHY THIS MATTERS FOR THE LONG-TERM ROADMAP:
MatchContext is designed to double as the input the future Evidence
Engine and AI Explanation Layer will consume -- "here is everything that
went into this prediction, and how trustworthy/current each piece is" --
and eventually as the feature-vector source for ML once validation
clears it (per this project's "always validation before ML" principle).
That makes honesty about data lineage matter more here than almost
anywhere else in the codebase: an explanation layer that says "the model
weighed the referee's card tendency" without being able to say whether
that referee data was point-in-time-correct, or just today's live file,
would be actively misleading -- worse than not mentioning it at all.

data_provenance exists so every downstream consumer -- today's four
engines, tomorrow's evidence engine -- can see plainly which fields are
snapshot-safe and which aren't, rather than that distinction living only
in a docstring someone has to go read. manager/referee/availability are
listed in data_provenance as "live_only_no_snapshot_support" even though
MatchContext holds no data for them, specifically so nothing downstream
has to go rediscover that gap on its own.

Once epl_manager_profiles.py / referee_profiler.py / player_availability.py
gain path params (tracked separately -- NOT part of this MatchContext
work), extending MatchContext to hold their data becomes a pure additive
change: new fields, updated data_provenance entries, zero change to the
fields that already exist here. Nothing about today's shape needs to be
revisited when that happens.

CONSOLIDATION BONUS (not the point of this file, but worth noting):
predict_goals() and predict_result() currently each call
get_h2h(home, away, h2h_data) independently -- the same lookup run twice
per predict_match() call. resolve_match_context() below does it once;
MatchContext.h2h is already the resolved home-vs-away pair, not the raw
h2h.json dict.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchContext:
    home_team: str
    away_team: str
    referee: str

    home_profile: dict
    away_profile: dict
    h2h: dict                # resolved home-vs-away pair, not the raw h2h.json dict
    elo_ratings: dict        # full ratings dict -- predict_result_elo() does its
    # own per-team lookup + 1500 fallback internally
    xg_profiles: dict        # {"home": {...} or {}, "away": {...} or {}}

    fallback_notes: dict     # {team: "promoted_profile" | "league_average"} --
    # only present for teams that needed a fallback
    data_provenance: dict    # lineage manifest -- see resolve_match_context()


def resolve_match_context(
    home_team: str,
    away_team: str,
    referee: str = "",
    profiles_path: str = None,
    h2h_path: str = None,
    elo_path: str = None,
    xg_path: str = None,
    force_promoted: set = None,
) -> MatchContext:
    """
    Single place that resolves all snapshot-safe match state for one
    fixture. Centralizes the missing-team profile fallback logic that
    currently lives inline in match_predictor.py's predict_match() --
    see that file's PATCH NOTE for the force_promoted-gating bug that
    was fixed there (a team missing from a historical snapshot must
    fall through to league_avg, not silently borrow PROMOTED_TEAM_PROFILES'
    2025/26 Championship form). That fix is preserved here unchanged,
    just moved to one place instead of being duplicated across
    match_predictor.py and any diagnostic scripts' own
    ensure_team_profiles()-style helpers (roadmap item 3 from the
    MatchContext design questions).

    All five path/override params default to None, matching
    predict_match()'s existing defaults -- None means "use live
    production files / the FORCE_PROMOTED module constant", exactly
    today's behavior.
    """
    from src.models.match_predictor import (
        load_profiles, load_h2h, get_h2h, _build_league_average,
        FORCE_PROMOTED, PROMOTED_TEAM_PROFILES,
    )
    from src.models.epl_elo import load_ratings
    from src.collectors.xg_scraper import load_xg_profiles

    profiles = load_profiles(profiles_path)
    h2h_all = load_h2h(h2h_path)
    active_force_promoted = (
        force_promoted if force_promoted is not None else FORCE_PROMOTED
    )

    # ── Missing-team fallback (moved from predict_match(), unchanged logic) ──
    fallback_notes = {}
    missing = []
    if home_team not in profiles or home_team in active_force_promoted:
        missing.append(home_team)
    if away_team not in profiles or away_team in active_force_promoted:
        missing.append(away_team)

    if missing:
        league_avg = _build_league_average(profiles)
        for team in missing:
            # Gated on active_force_promoted, not just PROMOTED_TEAM_PROFILES
            # membership -- see match_predictor.py's PATCH NOTE. An empty
            # force_promoted set must mean "never use these overrides."
            if team in active_force_promoted and team in PROMOTED_TEAM_PROFILES:
                profiles[team] = PROMOTED_TEAM_PROFILES[team].copy()
                fallback_notes[team] = "promoted_profile"
            else:
                profiles[team] = league_avg.copy()
                fallback_notes[team] = "league_average"

    # ── Elo ──────────────────────────────────────────────────────────
    elo_ratings = load_ratings(elo_path) if elo_path else load_ratings()

    # ── xG (only the two teams' entries, not the whole file) ──────────
    xg_all = load_xg_profiles(xg_path)
    xg_profiles = {
        "home": xg_all.get(home_team, {}),
        "away": xg_all.get(away_team, {}),
    }

    # ── H2H (resolved pair, done once here instead of twice downstream) ──
    h2h_pair = get_h2h(home_team, away_team, h2h_all)

    # ── Provenance manifest ────────────────────────────────────────────
    # "point_in_time" only when an explicit snapshot path was passed in --
    # matches the same convention match_predictor.py already uses (None =
    # live production file). manager/referee/availability are listed here
    # even though MatchContext holds no data for them -- see module
    # docstring for why that matters to the future evidence engine /
    # explanation layer.
    data_provenance = {
        "profiles":     "point_in_time" if profiles_path else "live_production",
        "h2h":          "point_in_time" if h2h_path else "live_production",
        "elo":          "point_in_time" if elo_path else "live_production",
        "xg":           "point_in_time" if xg_path else "live_production",
        "manager":      "live_only_no_snapshot_support",
        "referee":      "live_only_no_snapshot_support",
        "availability": "live_only_no_snapshot_support",
    }

    return MatchContext(
        home_team=home_team,
        away_team=away_team,
        referee=referee,
        home_profile=profiles[home_team],
        away_profile=profiles[away_team],
        h2h=h2h_pair,
        elo_ratings=elo_ratings,
        xg_profiles=xg_profiles,
        fallback_notes=fallback_notes,
        data_provenance=data_provenance,
    )
