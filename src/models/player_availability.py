"""
player_availability.py
Injury/unavailability lookups feeding goal-probability reductions in
match_predictor.py.

Reads:
  data/player_availability.json   (written by telegram_bot.py's `injured` command)
  data/opta_player_importance.json (written by opta_tactical_engine.py)
"""
import json
import os

AVAILABILITY_FILE = "data/player_availability.json"
IMPORTANCE_FILE = "data/opta_player_importance.json"

HIGH_IMPORTANCE_THRESHOLD = 0.20  # matches get_high_importance_threshold()
MAX_XG_REDUCTION = 0.40  # cap -- a team's xG can never drop more than 40%


def load_availability() -> dict:
    if not os.path.exists(AVAILABILITY_FILE):
        return {}
    with open(AVAILABILITY_FILE) as f:
        return json.load(f)


def load_importance() -> dict:
    if not os.path.exists(IMPORTANCE_FILE):
        return {}
    with open(IMPORTANCE_FILE) as f:
        return json.load(f)


def _canonical_team(team: str) -> str:
    """
    Normalize whatever team string was passed in against
    opta_tactical_engine.NAME_MAP. Falls back to stripping common Opta
    club-suffix variants (" FC", " AFC", " CF") and retrying, since
    opta_player_importance.json stores raw suffixed names (e.g.
    "Arsenal FC") that NAME_MAP's variants list doesn't include -- this
    was causing every team's players to fail to match, not just one.
    """
    from src.models.opta_tactical_engine import resolve_canonical_name
    canonical = resolve_canonical_name(team)
    if canonical:
        return canonical

    stripped = team
    for suffix in (" FC", " AFC", " CF"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break

    return resolve_canonical_name(stripped) or team


def _name_matches(logged_name: str, importance_name: str) -> bool:
    """Whole-word match, case-insensitive -- 'Rice' matches 'Declan Rice'
    but not 'Price'."""
    return bool(set(logged_name.lower().split()) & set(importance_name.lower().split()))


def get_xg_reduction(team: str) -> dict:
    """
    Returns {"factor": float, "players": [...]} for a team based on
    currently-logged unavailable players whose importance exceeds
    HIGH_IMPORTANCE_THRESHOLD. factor is the multiplier to apply to xG
    (e.g. 0.82 = an 18% reduction), capped at MAX_XG_REDUCTION.
    Unmatched or low-importance players are silently skipped (logged to
    console, not treated as an error).
    """
    availability = load_availability()
    canonical = _canonical_team(team)
    team_entry = availability.get(team) or availability.get(canonical)
    if not team_entry:
        return {"factor": 1.0, "players": []}

    logged_players = team_entry.get("players", []) if isinstance(
        team_entry, dict) else team_entry
    if not logged_players:
        return {"factor": 1.0, "players": []}

    importance = load_importance()
    team_entries = [v for v in importance.values(
    ) if _canonical_team(v.get("team", "")) == canonical]

    matched = []
    total_importance = 0.0
    for logged_name in logged_players:
        best = None
        for entry in team_entries:
            if _name_matches(logged_name, entry.get("name", "")):
                if best is None or entry["importance"] > best["importance"]:
                    best = entry
        if best and best["importance"] > HIGH_IMPORTANCE_THRESHOLD:
            matched.append({
                "logged_as": logged_name,
                "matched_name": best["name"],
                "importance": best["importance"],
            })
            total_importance += best["importance"]
        elif not best:
            print(f"[AVAILABILITY] '{logged_name}' ({team}) not found in "
                  f"opta_player_importance.json -- no adjustment applied.")

    reduction = min(total_importance, MAX_XG_REDUCTION)
    return {"factor": round(1 - reduction, 3), "players": matched}
