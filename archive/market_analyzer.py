"""
Market Analysis Engine.

Analyses each match and recommends specific betting markets
based on Elo ratings, tactical profiles, and historical patterns.

Markets covered:
- Over 1.5 / Over 2.5 goals
- Team over 0.5 / over 1.5 goals  
- Under 4.5 goals
- Double chance
- Draw no bet
- Both teams to score

Works as a layer ON TOP of Elo predictions.
Does not require stats data — uses rating gaps and tactical profiles.
"""

from src.models.elo_model import WORLD_CUP_2026_TEAMS
from src.models.manager_intelligence import WORLD_CUP_MANAGERS


# Rating gap thresholds
DOMINANT_GAP = 300      # e.g. Brazil vs Haiti
STRONG_GAP = 150        # e.g. England vs Panama
COMPETITIVE_GAP = 75    # e.g. France vs Norway
EVEN_MATCH = 75         # Below this = genuinely competitive


def get_match_profile(home_team, away_team, home_elo, away_elo):
    """
    Build a match profile from ratings and tactical data.
    This drives all market recommendations.
    """
    gap = abs(home_elo - away_elo)
    stronger = home_team if home_elo > away_elo else away_team
    weaker = away_team if home_elo > away_elo else home_team
    stronger_elo = max(home_elo, away_elo)
    weaker_elo = min(home_elo, away_elo)

    home_mgr = WORLD_CUP_MANAGERS.get(home_team, {})
    away_mgr = WORLD_CUP_MANAGERS.get(away_team, {})

    home_style = home_mgr.get("style", "unknown")
    away_style = away_mgr.get("style", "unknown")
    home_pressing = home_mgr.get("pressing_intensity", "medium")
    away_pressing = away_mgr.get("pressing_intensity", "medium")

    # High scoring styles
    attacking_styles = ["pressing", "possession"]
    defensive_styles = ["defensive", "counter"]

    home_attacking = home_style in attacking_styles
    away_attacking = away_style in attacking_styles
    both_attacking = home_attacking and away_attacking
    both_defensive = (
        home_style in defensive_styles and
        away_style in defensive_styles
    )

    high_press_match = (
        home_pressing == "high" or away_pressing == "high"
    )

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_elo": home_elo,
        "away_elo": away_elo,
        "gap": gap,
        "stronger": stronger,
        "weaker": weaker,
        "stronger_elo": stronger_elo,
        "weaker_elo": weaker_elo,
        "home_style": home_style,
        "away_style": away_style,
        "home_pressing": home_pressing,
        "away_pressing": away_pressing,
        "both_attacking": both_attacking,
        "both_defensive": both_defensive,
        "high_press_match": high_press_match,
        "home_attacking": home_attacking,
        "away_attacking": away_attacking,
    }


def analyze_markets(home_team, away_team, home_elo, away_elo, model_probs):
    """
    Main function — analyze all markets for a match.
    Returns ranked list of recommendations.
    """
    profile = get_match_profile(home_team, away_team, home_elo, away_elo)
    recommendations = []

    home_win_prob = model_probs["home"]
    draw_prob = model_probs["draw"]
    away_win_prob = model_probs["away"]
    stronger_win_prob = max(home_win_prob, away_win_prob)
    home_stronger = home_win_prob > away_win_prob

    gap = profile["gap"]
    stronger = profile["stronger"]
    weaker = profile["weaker"]

    # ================================================================
    # MARKET 1: OVER 1.5 GOALS
    # ================================================================
    over15_confidence = None
    over15_reasons = []

    if gap >= DOMINANT_GAP:
        over15_confidence = "HIGH"
        over15_reasons.append(
            f"{stronger} ({profile['stronger_elo']}) rated "
            f"{gap} points above {weaker} — dominant mismatch expected"
        )
        over15_reasons.append(
            "Strong teams score early and often vs weak opposition"
        )
    elif gap >= STRONG_GAP and profile["both_attacking"]:
        over15_confidence = "HIGH"
        over15_reasons.append(
            f"Both teams play attacking football "
            f"({profile['home_style']} vs {profile['away_style']})"
        )
        over15_reasons.append(f"Rating gap of {gap} favours open game")
    elif gap >= STRONG_GAP:
        over15_confidence = "MEDIUM"
        over15_reasons.append(
            f"{stronger} expected to control and score. "
            f"Rating gap: {gap} points"
        )
    elif profile["both_attacking"] and gap >= COMPETITIVE_GAP:
        over15_confidence = "MEDIUM"
        over15_reasons.append(
            "Both teams attack — goals likely from both ends"
        )
    elif profile["both_defensive"]:
        over15_confidence = "LOW"
        over15_reasons.append(
            "Both teams defensive — goals may be limited"
        )
    else:
        over15_confidence = "MEDIUM"
        over15_reasons.append(
            f"Competitive match — at least 2 goals expected in most cases"
        )

    recommendations.append({
        "market": "Over 1.5 Goals",
        "confidence": over15_confidence,
        "reasons": over15_reasons,
        "stake_suggestion": _stake_suggestion(over15_confidence),
        "icon": "⚽"
    })

    # ================================================================
    # MARKET 2: STRONGER TEAM OVER 0.5 GOALS (to score at least 1)
    # ================================================================
    team_score_confidence = None
    team_score_reasons = []

    if gap >= DOMINANT_GAP:
        team_score_confidence = "VERY HIGH"
        team_score_reasons.append(
            f"{stronger} rated {profile['stronger_elo']} — "
            f"elite teams score in virtually every match"
        )
        team_score_reasons.append(
            f"{gap} Elo point gap makes {weaker} extremely unlikely "
            f"to keep a clean sheet"
        )
    elif gap >= STRONG_GAP:
        team_score_confidence = "HIGH"
        team_score_reasons.append(
            f"{stronger} significantly stronger — "
            f"expected to find the net"
        )
        if profile["home_attacking"] and home_stronger:
            team_score_reasons.append(
                f"{home_team}'s attacking style increases scoring likelihood"
            )
        elif profile["away_attacking"] and not home_stronger:
            team_score_reasons.append(
                f"{away_team}'s attacking style increases scoring likelihood"
            )
    elif stronger_win_prob >= 65:
        team_score_confidence = "MEDIUM"
        team_score_reasons.append(
            f"Model gives {stronger} {stronger_win_prob:.1f}% win probability "
            f"— implies goals scored"
        )
    else:
        team_score_confidence = "LOW"
        team_score_reasons.append(
            "Evenly matched — neither team guaranteed to score"
        )

    recommendations.append({
        "market": f"{stronger} Over 0.5 Goals",
        "confidence": team_score_confidence,
        "reasons": team_score_reasons,
        "stake_suggestion": _stake_suggestion(team_score_confidence),
        "icon": "🎯"
    })

    # ================================================================
    # MARKET 3: STRONGER TEAM OVER 1.5 GOALS (to score 2+)
    # ================================================================
    if gap >= DOMINANT_GAP:
        recommendations.append({
            "market": f"{stronger} Over 1.5 Goals",
            "confidence": "HIGH",
            "reasons": [
                f"{gap} point gap — dominant teams routinely score 2+ "
                f"vs heavy underdogs at World Cup level",
                f"E.g. Canada 6-0 Qatar, Brazil historically vs weak groups"
            ],
            "stake_suggestion": _stake_suggestion("HIGH"),
            "icon": "🎯"
        })
    elif gap >= STRONG_GAP and profile["both_attacking"]:
        recommendations.append({
            "market": f"{stronger} Over 1.5 Goals",
            "confidence": "MEDIUM",
            "reasons": [
                f"Attacking style + {gap} point advantage = "
                f"multiple goals likely"
            ],
            "stake_suggestion": _stake_suggestion("MEDIUM"),
            "icon": "🎯"
        })

    # ================================================================
    # MARKET 4: UNDER 4.5 GOALS
    # ================================================================
    # This hits in ~92% of matches — always recommend as safe anchor
    under45_reasons = [
        "Under 4.5 goals hits in over 90% of professional football matches",
        "Safe anchor market — use as base of any combination bet"
    ]

    if profile["both_defensive"]:
        under45_reasons.append(
            "Both teams defensive — 5+ goals extremely unlikely"
        )
        under45_conf = "VERY HIGH"
    elif gap >= DOMINANT_GAP:
        under45_reasons.append(
            f"Even dominant mismatches rarely exceed 4 goals — "
            f"teams defend in depth when trailing heavily"
        )
        under45_conf = "HIGH"
    else:
        under45_conf = "HIGH"

    recommendations.append({
        "market": "Under 4.5 Goals",
        "confidence": under45_conf,
        "reasons": under45_reasons,
        "stake_suggestion": "SAFE ANCHOR — combine with other markets",
        "icon": "🛡️"
    })

    # ================================================================
    # MARKET 5: DOUBLE CHANCE
    # ================================================================
    dc_market = None
    dc_confidence = None
    dc_reasons = []

    if stronger_win_prob >= 75:
        # Strong favourite — double chance with draw
        if home_stronger:
            dc_market = f"Double Chance — {home_team} or Draw (1X)"
        else:
            dc_market = f"Double Chance — {away_team} or Draw (X2)"

        dc_confidence = "HIGH"
        dc_reasons.append(
            f"Model gives {stronger} {stronger_win_prob:.1f}% win probability"
        )
        dc_reasons.append(
            "Double chance removes loss risk — only needs win or draw"
        )

    elif stronger_win_prob >= 60:
        if home_stronger:
            dc_market = f"Double Chance — {home_team} or Draw (1X)"
        else:
            dc_market = f"Double Chance — {away_team} or Draw (X2)"

        dc_confidence = "MEDIUM"
        dc_reasons.append(
            f"Slight favourite at {stronger_win_prob:.1f}% — "
            f"double chance provides safety net"
        )

    if dc_market:
        recommendations.append({
            "market": dc_market,
            "confidence": dc_confidence,
            "reasons": dc_reasons,
            "stake_suggestion": _stake_suggestion(dc_confidence),
            "icon": "🔒"
        })

    # ================================================================
    # MARKET 6: DRAW NO BET
    # ================================================================
    if stronger_win_prob >= 65 and gap >= STRONG_GAP:
        if home_stronger:
            dnb_market = f"Draw No Bet — {home_team}"
        else:
            dnb_market = f"Draw No Bet — {away_team}"

        recommendations.append({
            "market": dnb_market,
            "confidence": "MEDIUM",
            "reasons": [
                f"Better odds than double chance, money back on draw",
                f"{stronger} has {stronger_win_prob:.1f}% win probability",
                "Recommended when favourite odds are too short for value"
            ],
            "stake_suggestion": _stake_suggestion("MEDIUM"),
            "icon": "🔄"
        })

    # ================================================================
    # MARKET 7: BOTH TEAMS TO SCORE
    # ================================================================
    btts_confidence = None
    btts_reasons = []

    if profile["both_attacking"] and gap <= COMPETITIVE_GAP:
        btts_confidence = "MEDIUM"
        btts_reasons.append(
            f"Both teams attack ({profile['home_style']} vs "
            f"{profile['away_style']}) in a competitive matchup"
        )
        btts_reasons.append(
            "Evenly matched teams with attacking intent = goals both ends"
        )
    elif gap >= DOMINANT_GAP:
        btts_confidence = "LOW"
        btts_reasons.append(
            f"{weaker} unlikely to score vs {stronger} "
            f"({gap} point gap)"
        )
    elif profile["both_defensive"]:
        btts_confidence = "LOW"
        btts_reasons.append(
            "Both defensive teams — one clean sheet likely"
        )

    if btts_confidence and btts_confidence != "LOW":
        recommendations.append({
            "market": "Both Teams to Score",
            "confidence": btts_confidence,
            "reasons": btts_reasons,
            "stake_suggestion": _stake_suggestion(btts_confidence),
            "icon": "⚽⚽"
        })

    # ================================================================
    # COMBO SUGGESTIONS (the goldmine at ₦1000 stake)
    # ================================================================
    combos = build_combo_suggestions(recommendations, home_team, away_team)

    return {
        "home_team": home_team,
        "away_team": away_team,
        "profile": profile,
        "recommendations": sorted(
            recommendations,
            key=lambda x: _confidence_rank(x["confidence"]),
            reverse=True
        ),
        "combo_suggestions": combos
    }


def build_combo_suggestions(recommendations, home_team, away_team):
    """
    Build 2-3 fold combo suggestions from high confidence markets.
    These are the ₦1000 stake plays.
    """
    combos = []

    high_conf = [
        r for r in recommendations
        if r["confidence"] in ["VERY HIGH", "HIGH"]
    ]

    if len(high_conf) >= 2:
        combo_markets = high_conf[:2]
        combos.append({
            "type": "2-FOLD COMBO",
            "markets": [m["market"] for m in combo_markets],
            "confidence": "HIGH",
            "note": "Both markets independently high confidence. "
                    "Combine for better return at ₦1000 stake."
        })

    if len(high_conf) >= 3:
        combo_markets = high_conf[:3]
        combos.append({
            "type": "3-FOLD COMBO",
            "markets": [m["market"] for m in combo_markets],
            "confidence": "MEDIUM",
            "note": "Higher return but all 3 must hit. "
                    "Only play if confident in all 3."
        })

    # Under 4.5 + Over 1.5 is always a safe combo (hits ~70%+)
    has_over15 = any("Over 1.5 Goals" in r["market"]
                     and "Team" not in r["market"]
                     for r in recommendations
                     if r["confidence"] in ["HIGH", "VERY HIGH"])
    has_under45 = any("Under 4.5" in r["market"] for r in recommendations)

    if has_over15 and has_under45:
        combos.append({
            "type": "SAFE COMBO",
            "markets": ["Over 1.5 Goals", "Under 4.5 Goals"],
            "confidence": "HIGH",
            "note": "Classic safe combo — hits when match has 2, 3 or 4 goals. "
                    "Good base for ₦1000 stake."
        })

    return combos


def _confidence_rank(confidence):
    """Numeric rank for sorting."""
    ranks = {"VERY HIGH": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    return ranks.get(confidence, 0)


def _stake_suggestion(confidence):
    """Stake guidance at ₦1000 max budget."""
    suggestions = {
        "VERY HIGH": "₦800-1000 — strong single or anchor of combo",
        "HIGH": "₦500-800 — solid single or part of combo",
        "MEDIUM": "₦300-500 — part of combo only",
        "LOW": "AVOID — insufficient confidence"
    }
    return suggestions.get(confidence, "AVOID")


def format_market_analysis_telegram(analysis):
    """Format market analysis for Telegram message."""
    home = analysis["home_team"]
    away = analysis["away_team"]
    profile = analysis["profile"]
    recs = analysis["recommendations"]
    combos = analysis["combo_suggestions"]

    conf_icons = {
        "VERY HIGH": "🟢🟢",
        "HIGH": "🟢",
        "MEDIUM": "🟡",
        "LOW": "🔴"
    }

    lines = [
        f"⚽ <b>{home} vs {away}</b>",
        f"📊 Elo: {profile['home_elo']} vs {profile['away_elo']} "
        f"(gap: {profile['gap']})",
        f"⚔️ {profile['home_style']} vs {profile['away_style']}",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"<b>MARKET RECOMMENDATIONS:</b>",
    ]

    for rec in recs[:4]:  # Top 4 only to keep message clean
        conf = rec["confidence"]
        icon = conf_icons.get(conf, "⚪")
        lines.append(f"\n{rec['icon']} <b>{rec['market']}</b>")
        lines.append(f"   {icon} {conf}")
        lines.append(f"   {rec['reasons'][0]}")
        lines.append(f"   💰 {rec['stake_suggestion']}")

    if combos:
        lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"<b>💡 COMBO SUGGESTIONS (₦1000 stake):</b>")
        for combo in combos[:2]:
            lines.append(f"\n🎰 <b>{combo['type']}</b>")
            for market in combo["markets"]:
                lines.append(f"   + {market}")
            lines.append(f"   📝 {combo['note']}")

    return "\n".join(lines)
