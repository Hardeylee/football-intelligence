"""
opta_tactical_engine.py

Derives team tactical ratings and player importance scores from real Opta
(The Analyst) data, replacing the subjective hardcoded numbers previously
used in epl_manager_profiles.py (e.g. pressing_intensity: 9).

INPUTS
------
data/premier_league_teams_flat.csv    (20 teams x 128 cols)
data/premier_league_players_flat.csv  (644 players x 92 cols)

OUTPUTS
-------
data/opta_tactical_profiles.json      one entry per team, 0-10 scale ratings
data/opta_player_importance.json      one entry per player, xG-share based

RUN
---
python -m src.models.opta_tactical_engine

Re-run this after every optascraper_pw.py refresh so profiles auto-update
through the season, per the original design intent.

DATA GAPS — DELIBERATELY NOT WORKED AROUND
--------------------------------------------
1. corners_modifier: The Opta team export has no corners column at all
   (checked full 128-column list). This engine does NOT produce a
   corners_modifier. The existing historical-data-based corners engine
   should keep being used as-is until a real corners field is found.

2. attacking_tempo: There is no team-level "progressive passes" column.
   Progressive passing only exists at player level
   (carries_overall_progressive_carries). Rather than silently substitute
   something and call it progressive passes, this engine derives tempo
   from sequences_overall_direct_attacks and sequences_overall_direct_speed_for
   (how often and how quickly a team attacks directly), which is a
   genuinely different (though related) signal. If you want tempo built
   from actual progressive-pass volume, that requires aggregating the
   player CSV per team — flagging as a possible follow-up, not done here.

3. defensive_line: There is no "defensive action distance" column.
   sequences_overall_start_distance (average distance from goal at which
   a team's possession sequences begin) is used as the proxy instead.
   This correlates with pressing height / defensive line but is not the
   same measurement the original spec assumed.

4. Small-sample distortion: newly promoted teams (Coventry, Hull, Ipswich)
   and any team early in the season will have low attack_overall_played
   counts. Ratings computed off a handful of games are noisy. A team below
   MIN_GAMES_FOR_TRUST falls back to a neutral rating for any metric,
   rather than reporting a confident-looking number built on 2-3 matches
   (5.0 for the 0-10 ratings, 0.0 for the delta modifiers).

OUTPUT SCALE -- TWO DIFFERENT RANGES, DO NOT MIX UP
----------------------------------------------------
- pressing_intensity, foul_tendency, set_piece_focus, attacking_tempo,
  defensive_line: 0-10 rating, same scale as the existing hardcoded
  EPL_MANAGER_PROFILES values (e.g. Arsenal's pressing_intensity: 9).
- cards_modifier: -0.15 to +0.15 delta, added directly onto a probability
  by apply_manager_adjustments() in epl_manager_profiles.py.
- goals_modifier: -0.10 to +0.10 delta, same additive pattern.
- corners_modifier is NOT produced by this engine at all (see gap #1
  above). epl_manager_profiles.py must keep sourcing corners_modifier
  from the hardcoded EPL_MANAGER_PROFILES dict for every team, always.
"""

import json
import os
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
TEAMS_CSV = DATA_DIR / "premier_league_teams_flat.csv"
PLAYERS_CSV = DATA_DIR / "premier_league_players_flat.csv"
CHAMPIONSHIP_TEAMS_CSV = DATA_DIR / "championship_teams_flat.csv"
TACTICAL_OUT = DATA_DIR / "opta_tactical_profiles.json"
IMPORTANCE_OUT = DATA_DIR / "opta_player_importance.json"

MIN_GAMES_FOR_TRUST = 4  # below this, fall back to neutral rating
NEUTRAL = 5.0

# Matches PROMOTION_DISCOUNT in src/collectors/xg_scraper.py. Applied ONLY
# to attacking output (xg_per_game) for promoted teams -- never to xga, and
# never to style/behavioral metrics (pressing, fouls, tempo, set pieces).
# xg_scraper.py currently discounts both xg and xga symmetrically for
# promoted teams, which is backwards for xga (it implies a promoted team's
# defense improves stepping up to a tougher league). That's flagged as a
# separate, pre-existing issue in xg_scraper.py -- not corrected here, since
# it's outside this file and already-committed code, but worth revisiting.
PROMOTION_DISCOUNT = 0.80

# The three 2026/27 promoted sides, and their exact contestantName string
# in the Championship Opta export (checked against a real scrape -- these
# are not guesses). Update if The Analyst renames a club.
PROMOTED_TEAMS = {
    "Coventry City": "Coventry City FC",
    "Hull City": "Hull City AFC",
    "Ipswich": "Ipswich Town FC",
}

# football-data.co.uk canonical name -> Opta contestantShortName / contestantName
# variants seen from the API. Extend this as mismatches turn up; do NOT guess
# silently — an unmapped team falls through to neutral profile with a warning.
NAME_MAP = {
    "Arsenal": ["Arsenal"],
    "Aston Villa": ["Aston Villa"],
    "Bournemouth": ["Bournemouth", "AFC Bournemouth"],
    "Brentford": ["Brentford"],
    "Brighton": ["Brighton", "Brighton & Hove Albion", "Brighton and Hove Albion"],
    "Chelsea": ["Chelsea"],
    "Coventry City": ["Coventry", "Coventry City"],
    "Crystal Palace": ["Crystal Palace"],
    "Everton": ["Everton"],
    "Fulham": ["Fulham"],
    "Hull City": ["Hull", "Hull City"],
    "Ipswich": ["Ipswich", "Ipswich Town"],
    "Leeds": ["Leeds", "Leeds United"],
    "Liverpool": ["Liverpool"],
    "Man City": ["Manchester City", "Man City"],
    "Man United": ["Manchester United", "Man United", "Man Utd"],
    "Newcastle": ["Newcastle", "Newcastle United"],
    "Nott'm Forest": ["Nottingham Forest", "Nott'm Forest", "Forest"],
    "Sunderland": ["Sunderland"],
    "Tottenham": ["Tottenham", "Tottenham Hotspur", "Spurs"],
}


def _min_max(series: pd.Series) -> pd.Series:
    """Scale a pandas Series to 0-10. Flat series (all equal) -> all 5.0."""
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series([NEUTRAL] * len(series), index=series.index)
    return (series - lo) / (hi - lo) * 10


def _center_scale(series: pd.Series, max_delta: float) -> pd.Series:
    """
    Scale a series to a small delta centered on 0, matching the modifier
    format epl_manager_profiles.py actually consumes (e.g. cards_modifier
    in range -0.15..+0.15, added directly onto a probability). This is a
    DIFFERENT scale from _min_max's 0-10 ratings -- do not mix them up.
    Team above league mean -> positive delta. Below -> negative.
    Clipped at +/- max_delta so no single outlier team blows past the
    range the consuming code expects.
    """
    mean = series.mean()
    spread = series.max() - series.min()
    if spread == 0:
        return pd.Series([0.0] * len(series), index=series.index)
    scaled = (series - mean) / (spread / 2) * max_delta
    return scaled.clip(-max_delta, max_delta)


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, pd.NA)


def _scale_value_minmax(value: float, reference: pd.Series) -> float:
    """
    Same 0-10 scaling as _min_max, but for a single external value placed
    against an existing reference distribution (used for promoted teams,
    which are scaled against the EPL distribution rather than their own
    league's). The value is clipped into the reference's observed range
    first, so a team far outside EPL norms still lands at a sensible 0 or
    10 rather than extrapolating past the scale.
    """
    lo, hi = reference.min(), reference.max()
    if hi == lo:
        return NEUTRAL
    clipped = min(max(value, lo), hi)
    return round((clipped - lo) / (hi - lo) * 10, 2)


def _scale_value_delta(value: float, reference: pd.Series, max_delta: float) -> float:
    """Single-value counterpart to _center_scale, same clipping logic."""
    mean = reference.mean()
    spread = reference.max() - reference.min()
    if spread == 0:
        return 0.0
    scaled = (value - mean) / (spread / 2) * max_delta
    return round(max(-max_delta, min(max_delta, scaled)), 3)


def load_team_data() -> pd.DataFrame:
    if not TEAMS_CSV.exists():
        raise FileNotFoundError(
            f"{TEAMS_CSV} not found. Run optascraper_pw.py first."
        )
    df = pd.read_csv(TEAMS_CSV)
    return df


def load_championship_team_data() -> pd.DataFrame | None:
    """
    Returns None (not raises) if the file doesn't exist -- the promoted-team
    pathway is optional. A user who hasn't scraped Championship data yet
    should still get a working engine for the 17 established EPL teams;
    Coventry/Hull/Ipswich just stay unmapped with a printed note, same as
    before this pathway existed.
    """
    if not CHAMPIONSHIP_TEAMS_CSV.exists():
        return None
    return pd.read_csv(CHAMPIONSHIP_TEAMS_CSV)


def resolve_canonical_name(contestant_name: str) -> str | None:
    for canonical, variants in NAME_MAP.items():
        if contestant_name in variants:
            return canonical
    return None


def build_tactical_profiles(df: pd.DataFrame) -> dict:
    played = df["attack_overall_played"].clip(lower=1)  # avoid div/0

    # --- pressing_intensity: lower PPDA = more aggressive press ---
    ppda = df["sequences_overall_ppda"]
    inv_ppda = 1 / ppda.replace(0, pd.NA)
    pressing_intensity = _min_max(inv_ppda)

    # --- foul_tendency: fouls committed per game ---
    fouls_per_game = df["misc_overall_fouls_lost"] / played
    foul_tendency = _min_max(fouls_per_game)

    # --- cards_modifier: DELTA scale (-0.15..+0.15), matches
    # epl_manager_profiles.py's cards_modifier which is added directly onto
    # a probability. NOT the same 0-10 scale as pressing_intensity etc.
    yellows_per_game = df["misc_overall_yellows"] / played
    reds_per_game = df["misc_overall_reds"] / played
    card_load = yellows_per_game + (reds_per_game * 2)
    cards_modifier = _center_scale(card_load, max_delta=0.15)

    # --- goals_modifier: DELTA scale (-0.10..+0.10). Combined goal
    # involvement (a team's own xG plus xG conceded) is used as the proxy
    # for "matches this team is in tend to be high/low scoring", which is
    # what the consuming code actually means by goals_modifier -- it's not
    # purely attacking strength, it bumps over/under and BTTS together.
    xg_per_game = df["attack_overall_xg"] / played
    xga_per_game = df["defending_overall_xg_against"] / played
    goal_involvement = xg_per_game + xga_per_game
    goals_modifier = _center_scale(goal_involvement, max_delta=0.10)

    # --- set_piece_focus: share of total xG that comes from set pieces ---
    set_piece_focus = _safe_div(
        df["attack_set_piece_team_sp_xG"], df["attack_overall_xg"]
    ).fillna(0) * 10
    set_piece_focus = set_piece_focus.clip(0, 10)

    # --- attacking_tempo: direct-attack frequency and speed (proxy, see docstring) ---
    direct_attacks_per_game = df["sequences_overall_direct_attacks"] / played
    direct_speed = df["sequences_overall_direct_speed_for"]
    tempo_raw = _min_max(direct_attacks_per_game) * \
        0.5 + _min_max(direct_speed) * 0.5
    attacking_tempo = tempo_raw

    # --- defensive_line: how far up the pitch sequences start (proxy, see docstring) ---
    defensive_line = _min_max(df["sequences_overall_start_distance"])

    profiles = {}
    for idx, row in df.iterrows():
        canonical = resolve_canonical_name(row.get("contestantName", ""))
        if canonical is None:
            canonical = resolve_canonical_name(row.get("team", ""))
        if canonical is None:
            print(
                f"WARNING: could not map Opta team '{row.get('contestantName')}' "
                f"/ '{row.get('team')}' to a canonical name. Skipping — check "
                f"NAME_MAP in opta_tactical_engine.py."
            )
            continue

        games_played = int(row["attack_overall_played"])
        trusted = games_played >= MIN_GAMES_FOR_TRUST

        def val(series_val):
            return round(float(series_val), 2) if trusted else NEUTRAL

        # cards_modifier / goals_modifier default to 0.0 (neutral delta) on
        # fallback, not NEUTRAL (5.0) -- they're a different scale than the
        # 0-10 ratings, so the untrusted-sample fallback must match.
        def delta_val(series_val):
            return round(float(series_val), 3) if trusted else 0.0

        profiles[canonical] = {
            "games_played": games_played,
            "sample_trusted": trusted,
            "pressing_intensity": val(pressing_intensity[idx]),
            "foul_tendency": val(foul_tendency[idx]),
            "set_piece_focus": val(set_piece_focus[idx]),
            "attacking_tempo": val(attacking_tempo[idx]),
            "defensive_line": val(defensive_line[idx]),
            "cards_modifier": delta_val(cards_modifier[idx]),
            "goals_modifier": delta_val(goals_modifier[idx]),
            "raw": {
                "ppda": round(float(ppda[idx]), 2) if pd.notna(ppda[idx]) else None,
                "xg_per_game": round(float(xg_per_game[idx]), 2),
                "xga_per_game": round(float(xga_per_game[idx]), 2),
                "fouls_per_game": round(float(fouls_per_game[idx]), 2),
                "card_load": round(float(card_load[idx]), 3),
                "goal_involvement": round(float(goal_involvement[idx]), 2),
            },
        }

    return profiles


def build_promoted_team_profiles(epl_df: pd.DataFrame, champ_df: pd.DataFrame) -> dict:
    """
    Builds tactical profiles for the promoted sides (PROMOTED_TEAMS) from
    Championship data, positioned against the EPL distribution rather than
    the Championship one -- these ratings feed EPL match predictions, so
    "pressing_intensity: 6" needs to mean the same thing whether the team
    is Arsenal or Coventry.

    Discount policy (see PROMOTION_DISCOUNT docstring above): ONLY
    xg_per_game (attacking output) is multiplied by 0.80 before scaling,
    matching xg_scraper.py's established pattern. xga_per_game is left at
    its raw Championship rate, undiscounted -- applying the same 0.80 to
    conceded xG would mean "promoted team's defense gets better stepping
    up to a tougher league," which is backwards. xg_scraper.py currently
    discounts both raw_xg and raw_xga symmetrically; that's worth revisiting
    there too, but isn't changed here since it's already-tested, committed
    code outside this function's scope. There's no established factor in
    this codebase for how much MORE a promoted side should be expected to
    concede against EPL-level attacks, so rather than invent one, the raw
    Championship xga rate is used as-is -- flagged here as a likely
    understatement of real defensive risk, not a solved problem.
    """
    epl_played = epl_df["attack_overall_played"].clip(lower=1)

    epl_inv_ppda = 1 / epl_df["sequences_overall_ppda"].replace(0, pd.NA)
    epl_fouls_per_game = epl_df["misc_overall_fouls_lost"] / epl_played
    epl_yellows_per_game = epl_df["misc_overall_yellows"] / epl_played
    epl_reds_per_game = epl_df["misc_overall_reds"] / epl_played
    epl_card_load = epl_yellows_per_game + (epl_reds_per_game * 2)
    epl_xg_per_game = epl_df["attack_overall_xg"] / epl_played
    epl_xga_per_game = epl_df["defending_overall_xg_against"] / epl_played
    epl_goal_involvement = epl_xg_per_game + epl_xga_per_game
    epl_direct_attacks_per_game = epl_df["sequences_overall_direct_attacks"] / epl_played
    epl_direct_speed = epl_df["sequences_overall_direct_speed_for"]
    epl_start_distance = epl_df["sequences_overall_start_distance"]

    profiles = {}

    for canonical, champ_name in PROMOTED_TEAMS.items():
        champ_rows = champ_df[champ_df["contestantName"] == champ_name]
        if champ_rows.empty:
            print(
                f"WARNING: '{champ_name}' not found in Championship data for "
                f"promoted team {canonical}. Check PROMOTED_TEAMS mapping or "
                f"whether the Championship scrape covers the right season."
            )
            continue
        row = champ_rows.iloc[0]

        champ_played = max(int(row["attack_overall_played"]), 1)
        games_played = int(row["attack_overall_played"])
        trusted = games_played >= MIN_GAMES_FOR_TRUST

        ppda = row["sequences_overall_ppda"]
        inv_ppda = (1 / ppda) if ppda and pd.notna(ppda) and ppda != 0 else None
        fouls_per_game = row["misc_overall_fouls_lost"] / champ_played
        yellows_per_game = row["misc_overall_yellows"] / champ_played
        reds_per_game = row["misc_overall_reds"] / champ_played
        card_load = yellows_per_game + (reds_per_game * 2)

        # Discount applied ONLY to attacking output (xg), matching
        # xg_scraper.py's PROMOTION_DISCOUNT. xga is left raw -- see
        # docstring above on why discounting conceded xG downward is
        # backwards for a team stepping up in quality.
        xg_per_game_raw = row["attack_overall_xg"] / champ_played
        xga_per_game_raw = row["defending_overall_xg_against"] / champ_played
        xg_per_game = xg_per_game_raw * PROMOTION_DISCOUNT
        xga_per_game = xga_per_game_raw  # undiscounted, intentionally
        goal_involvement = xg_per_game + xga_per_game

        sp_xg = row.get("attack_set_piece_team_sp_xG", 0) or 0
        overall_xg = row.get("attack_overall_xg", 0) or 0
        set_piece_focus = round(
            min(max((sp_xg / overall_xg) * 10, 0), 10), 2) if overall_xg else 0.0

        direct_attacks_per_game = row["sequences_overall_direct_attacks"] / champ_played
        direct_speed = row["sequences_overall_direct_speed_for"]
        start_distance = row["sequences_overall_start_distance"]

        if not trusted:
            profiles[canonical] = {
                "games_played": games_played,
                "sample_trusted": False,
                "pressing_intensity": NEUTRAL,
                "foul_tendency": NEUTRAL,
                "set_piece_focus": NEUTRAL,
                "attacking_tempo": NEUTRAL,
                "defensive_line": NEUTRAL,
                "cards_modifier": 0.0,
                "goals_modifier": 0.0,
                "source": "championship_discounted",
                "raw": {"note": "insufficient Championship sample"},
            }
            continue

        pressing_intensity = (
            _scale_value_minmax(
                inv_ppda, epl_inv_ppda) if inv_ppda is not None else NEUTRAL
        )
        tempo = (
            _scale_value_minmax(direct_attacks_per_game,
                                epl_direct_attacks_per_game) * 0.5
            + _scale_value_minmax(direct_speed, epl_direct_speed) * 0.5
        )

        profiles[canonical] = {
            "games_played": games_played,
            "sample_trusted": True,
            "pressing_intensity": pressing_intensity,
            "foul_tendency": _scale_value_minmax(fouls_per_game, epl_fouls_per_game),
            "set_piece_focus": set_piece_focus,
            "attacking_tempo": round(tempo, 2),
            "defensive_line": _scale_value_minmax(start_distance, epl_start_distance),
            "cards_modifier": _scale_value_delta(card_load, epl_card_load, max_delta=0.15),
            "goals_modifier": _scale_value_delta(goal_involvement, epl_goal_involvement, max_delta=0.10),
            "source": "championship_discounted",
            "raw": {
                "ppda": round(float(ppda), 2) if pd.notna(ppda) else None,
                "xg_per_game_raw": round(float(xg_per_game_raw), 2),
                "xg_per_game_discounted": round(float(xg_per_game), 2),
                "xga_per_game": round(float(xga_per_game), 2),
                "fouls_per_game": round(float(fouls_per_game), 2),
                "discount_applied": PROMOTION_DISCOUNT,
                "discount_applied_to": ["xg_per_game"],
                "discount_not_applied_to": ["xga_per_game"],
            },
        }

    return profiles


def load_player_data() -> pd.DataFrame:
    if not PLAYERS_CSV.exists():
        raise FileNotFoundError(
            f"{PLAYERS_CSV} not found. Run optascraper_pw.py first."
        )
    return pd.read_csv(PLAYERS_CSV)


def build_player_importance(players_df: pd.DataFrame, teams_df: pd.DataFrame) -> dict:
    """player_importance = player_xg / team_total_xg.

    Team total xG is taken from the teams CSV (attack_overall_xg), matched
    by team_id, rather than re-summed from the players CSV, since the
    players file may not include every squad member (e.g. players with 0
    minutes) and the team file's total is the authoritative figure.
    """
    team_xg_by_id = dict(
        zip(teams_df["team_id"], teams_df["attack_overall_xg"]))
    team_name_by_id = dict(
        zip(teams_df["team_id"], teams_df["contestantName"]))

    importance = {}
    skipped_no_team_xg = 0

    for _, row in players_df.iterrows():
        team_id = row.get("team_id")
        team_total_xg = team_xg_by_id.get(team_id)

        raw_player_xg = row.get("attack_overall_xg")
        player_xg = float(raw_player_xg) if pd.notna(raw_player_xg) else 0.0

        if not team_total_xg or pd.isna(team_total_xg) or team_total_xg == 0:
            skipped_no_team_xg += 1
            continue

        canonical_team = resolve_canonical_name(
            team_name_by_id.get(team_id, ""))
        importance_score = round(player_xg / float(team_total_xg), 4)

        player_name = row.get(
            "player") or f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()

        raw_mins = row.get("attack_overall_mins_played")
        mins_played = int(raw_mins) if pd.notna(raw_mins) else 0

        importance[str(row.get("player_id"))] = {
            "name": player_name,
            "team": canonical_team or team_name_by_id.get(team_id),
            "player_xg": round(player_xg, 2),
            "importance": importance_score,
            "mins_played": mins_played,
        }

    if skipped_no_team_xg:
        print(
            f"NOTE: skipped {skipped_no_team_xg} players with no matching "
            f"team xG total (likely 0-xG teams or unmatched team_id)."
        )

    return importance


def get_high_importance_threshold() -> float:
    """Players above this importance score trigger the goal-probability
    reduction when unavailable, per the injury engine design in the
    handover note (importance > 0.20)."""
    return 0.20


def run():
    DATA_DIR.mkdir(exist_ok=True)

    teams_df = load_team_data()
    players_df = load_player_data()

    tactical_profiles = build_tactical_profiles(teams_df)

    champ_df = load_championship_team_data()
    if champ_df is not None:
        promoted_profiles = build_promoted_team_profiles(teams_df, champ_df)
        tactical_profiles.update(promoted_profiles)
        print(f"Promoted teams added from Championship data: "
              f"{list(promoted_profiles.keys())}")
    else:
        print(f"NOTE: {CHAMPIONSHIP_TEAMS_CSV} not found -- promoted teams "
              f"(Coventry City, Hull City, Ipswich) stay unmapped. Run "
              f"optascraper_pw.py championship + parse_player_stats.py "
              f"championship to fix this.")

    player_importance = build_player_importance(players_df, teams_df)

    with open(TACTICAL_OUT, "w") as f:
        json.dump(tactical_profiles, f, indent=2)
    with open(IMPORTANCE_OUT, "w") as f:
        json.dump(player_importance, f, indent=2)

    trusted_count = sum(1 for p in tactical_profiles.values()
                        if p["sample_trusted"])
    print(f"Tactical profiles written: {len(tactical_profiles)} teams "
          f"({trusted_count} trusted, {len(tactical_profiles) - trusted_count} "
          f"on neutral fallback due to small sample).")
    print(
        f"Player importance scores written: {len(player_importance)} players.")
    print(f"-> {TACTICAL_OUT}")
    print(f"-> {IMPORTANCE_OUT}")


if __name__ == "__main__":
    run()
