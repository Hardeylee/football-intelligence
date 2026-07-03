"""
Formation-Based Matchup Engine
Analyses tactical formation matchups and produces market adjustments.
Data source: manager profiles in epl_manager_profiles.py

Modifiers produced:
- goals_adjustment:   affects over/under and BTTS probabilities
- cards_adjustment:   affects yellow cards market
- corners_adjustment: affects corners market
- dominance_score:    0-1, how much home team dominates tactically
"""

# Formation characteristics
# Each formation has: width, defensive_line, attacking_numbers, pressing_trap
FORMATION_PROFILES = {
    "4-3-3": {
        "width":             8,   # Wide wingers
        "defensive_line":    7,
        "attacking_numbers": 7,   # 3 forwards
        "pressing_intensity": 8,
        "midfield_control":  6,
        "set_piece_threat":  6,
    },
    "4-2-3-1": {
        "width":             7,
        "defensive_line":    6,
        "attacking_numbers": 6,
        "pressing_intensity": 7,
        "midfield_control":  8,   # Strong double pivot
        "set_piece_threat":  7,
    },
    "4-4-2": {
        "width":             7,
        "defensive_line":    5,
        "attacking_numbers": 6,   # 2 strikers
        "pressing_intensity": 6,
        "midfield_control":  6,
        "set_piece_threat":  7,
    },
    "4-5-1": {
        "width":             6,
        "defensive_line":    4,
        "attacking_numbers": 3,   # Compact, hard to beat
        "pressing_intensity": 4,
        "midfield_control":  8,
        "set_piece_threat":  5,
    },
    "3-5-2": {
        "width":             9,   # Wing backs very wide
        "defensive_line":    6,
        "attacking_numbers": 7,
        "pressing_intensity": 7,
        "midfield_control":  7,
        "set_piece_threat":  8,
    },
    "3-4-3": {
        "width":             9,
        "defensive_line":    7,
        "attacking_numbers": 8,
        "pressing_intensity": 9,
        "midfield_control":  5,
        "set_piece_threat":  6,
    },
    "4-1-4-1": {
        "width":             7,
        "defensive_line":    5,
        "attacking_numbers": 5,
        "pressing_intensity": 6,
        "midfield_control":  8,
        "set_piece_threat":  6,
    },
    "Unknown": {
        "width":             6,
        "defensive_line":    5,
        "attacking_numbers": 5,
        "pressing_intensity": 5,
        "midfield_control":  5,
        "set_piece_threat":  5,
    },
}


def get_formation_profile(formation: str) -> dict:
    """Get formation profile, falling back to closest match."""
    if formation in FORMATION_PROFILES:
        return FORMATION_PROFILES[formation]

    # Try partial match (e.g. "4-3-3 / 4-2-3-1" -> use first)
    if "/" in formation:
        primary = formation.split("/")[0].strip()
        if primary in FORMATION_PROFILES:
            return FORMATION_PROFILES[primary]

    return FORMATION_PROFILES["Unknown"]


def analyse_matchup(
    home_formation: str,
    away_formation: str,
    home_pressing: int,
    away_pressing: int,
    home_def_line: int,
    away_def_line: int,
) -> dict:
    """
    Core matchup analysis. Takes formation and tactical attributes
    of both teams and produces market adjustments.
    """
    hf = get_formation_profile(home_formation)
    af = get_formation_profile(away_formation)

    # ── SPACE CREATION ───────────────────────────────────────────
    # High defensive line + attacking opponents = more space behind
    # High pressing + low defensive line of opponent = more goals

    home_space_created = (
        home_pressing * 0.4 +
        hf["attacking_numbers"] * 0.3 +
        away_def_line * 0.3  # Higher away def line = more space to exploit
    ) / 10

    away_space_created = (
        away_pressing * 0.4 +
        af["attacking_numbers"] * 0.3 +
        home_def_line * 0.3
    ) / 10

    total_space = (home_space_created + away_space_created) / 2

    # Goals adjustment: more space = more goals
    if total_space > 0.65:
        goals_adj = 0.05
    elif total_space > 0.55:
        goals_adj = 0.02
    elif total_space < 0.40:
        goals_adj = -0.05
    else:
        goals_adj = 0.0

    # ── FRICTION / CARDS ─────────────────────────────────────────
    # High press vs high press = lots of fouls = more cards
    # Defensive vs attacking = frustration fouls = more cards
    # Possession vs possession = fewer fouls

    press_clash = (home_pressing + away_pressing) / 20
    style_clash = abs(hf["attacking_numbers"] - af["attacking_numbers"]) / 8

    friction = (press_clash * 0.6 + style_clash * 0.4)

    if friction > 0.65:
        cards_adj = 0.08   # High friction = significantly more cards
    elif friction > 0.50:
        cards_adj = 0.04
    elif friction < 0.35:
        cards_adj = -0.04  # Low friction = fewer cards
    else:
        cards_adj = 0.0

    # ── CORNERS ──────────────────────────────────────────────────
    # Wide formations win more corners
    # High attacking numbers + wide play = more corners
    # Away team defending deep = more corners for home

    home_corner_threat = (
        hf["width"] * 0.5 +
        hf["attacking_numbers"] * 0.3 +
        # Lower away def line = more defending = more corners
        (10 - away_def_line) * 0.2
    ) / 10

    away_corner_threat = (
        af["width"] * 0.5 +
        af["attacking_numbers"] * 0.3 +
        (10 - home_def_line) * 0.2
    ) / 10

    total_corner_threat = (home_corner_threat + away_corner_threat) / 2

    if total_corner_threat > 0.65:
        corners_adj = 0.07
    elif total_corner_threat > 0.55:
        corners_adj = 0.03
    elif total_corner_threat < 0.40:
        corners_adj = -0.05
    else:
        corners_adj = 0.0

    # ── DOMINANCE ────────────────────────────────────────────────
    # How much does home team tactically dominate?
    home_dominance = (
        hf["midfield_control"] * 0.4 +
        home_pressing * 0.3 +
        hf["attacking_numbers"] * 0.3
    ) / 10

    away_dominance = (
        af["midfield_control"] * 0.4 +
        away_pressing * 0.3 +
        af["attacking_numbers"] * 0.3
    ) / 10

    dominance_score = round(
        home_dominance / (home_dominance + away_dominance), 3)

    # ── MATCHUP LABEL ─────────────────────────────────────────────
    if home_pressing > 7 and away_pressing > 7:
        matchup_type = "High Press Battle — expect cards and goals"
    elif home_pressing > 7 and away_pressing < 5:
        matchup_type = "Press vs Sit Deep — home dominance likely"
    elif home_pressing < 5 and away_pressing > 7:
        matchup_type = "Away Press vs Deep Block — away team in control"
    elif hf["attacking_numbers"] > 6 and af["attacking_numbers"] > 6:
        matchup_type = "Open Game — both teams attack"
    elif hf["attacking_numbers"] < 5 and af["attacking_numbers"] < 5:
        matchup_type = "Tactical Battle — low scoring likely"
    else:
        matchup_type = "Balanced Matchup"

    return {
        "home_formation":    home_formation,
        "away_formation":    away_formation,
        "matchup_type":      matchup_type,
        "goals_adjustment":  round(goals_adj, 3),
        "cards_adjustment":  round(cards_adj, 3),
        "corners_adjustment": round(corners_adj, 3),
        "dominance_score":   dominance_score,
        "home_space_created": round(home_space_created, 3),
        "away_space_created": round(away_space_created, 3),
        "friction_score":    round(friction, 3),
        "corner_threat":     round(total_corner_threat, 3),
    }


def get_formation_adjustment(home_team: str, away_team: str) -> dict:
    """
    Main function — looks up manager formations and returns adjustments.
    Integrates with epl_manager_profiles.
    """
    from src.models.epl_manager_profiles import get_manager_profile

    home_mgr = get_manager_profile(home_team)
    away_mgr = get_manager_profile(away_team)

    home_formation = home_mgr.get("formation", "Unknown")
    away_formation = away_mgr.get("formation", "Unknown")
    home_pressing = home_mgr.get("pressing_intensity", 5)
    away_pressing = away_mgr.get("pressing_intensity", 5)
    home_def_line = home_mgr.get("defensive_line", 5)
    away_def_line = away_mgr.get("defensive_line", 5)

    result = analyse_matchup(
        home_formation, away_formation,
        home_pressing,  away_pressing,
        home_def_line,  away_def_line,
    )

    result["home_manager"] = home_mgr.get("manager", "Unknown")
    result["away_manager"] = away_mgr.get("manager", "Unknown")
    result["home_style"] = home_mgr.get("style", "Unknown")
    result["away_style"] = away_mgr.get("style", "Unknown")

    return result


def format_formation_report(adj: dict) -> str:
    """Format formation matchup for Telegram."""
    lines = [
        f"⚔️ <b>TACTICAL MATCHUP</b>",
        f"{adj['home_formation']} vs {adj['away_formation']}",
        f"<i>{adj['matchup_type']}</i>",
        "",
        f"📐 Dominance: {'Home' if adj['dominance_score'] > 0.55 else 'Away' if adj['dominance_score'] < 0.45 else 'Balanced'} "
        f"({adj['dominance_score']*100:.0f}% home)",
        f"⚽ Goals impact:   {'+' if adj['goals_adjustment'] >= 0 else ''}{adj['goals_adjustment']*100:.0f}%",
        f"🟨 Cards impact:   {'+' if adj['cards_adjustment'] >= 0 else ''}{adj['cards_adjustment']*100:.0f}%",
        f"🚩 Corners impact: {'+' if adj['corners_adjustment'] >= 0 else ''}{adj['corners_adjustment']*100:.0f}%",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing formation engine...\n")

    test_matches = [
        ("Arsenal",   "Tottenham"),
        ("Man City",  "Liverpool"),
        ("Nott'm Forest", "Leeds"),
        ("Everton",   "Crystal Palace"),
        ("Brighton",  "Aston Villa"),
    ]

    for home, away in test_matches:
        adj = get_formation_adjustment(home, away)
        print(
            f"{home} ({adj['home_formation']}) vs {away} ({adj['away_formation']})")
        print(f"  Type:     {adj['matchup_type']}")
        print(f"  Goals:    {adj['goals_adjustment']:+.0%}")
        print(f"  Cards:    {adj['cards_adjustment']:+.0%}")
        print(f"  Corners:  {adj['corners_adjustment']:+.0%}")
        print(f"  Dominance:{adj['dominance_score']:.0%} home")
        print()
