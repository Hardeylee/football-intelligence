"""
Acca Builder — High Confidence Market Selector
Selects best legs for accumulator bets based on model probability.
Does NOT require value edge — focuses on confidence threshold instead.
Minimum confidence: 70% model probability to qualify as acca leg.
"""

from src.models.match_predictor import predict_match
from src.models.streak_analyzer import analyze_match_streaks, get_streak_confirmation

MIN_CONFIDENCE = 0.70   # Minimum model probability to qualify
MIN_STRONG = 0.80   # Strong confidence threshold
MIN_VERY_STRONG = 0.90   # Very strong confidence threshold

MARKET_LABELS = {
    "home_win":        "{home} Win",
    "draw":            "Draw",
    "away_win":        "{away} Win",
    "home_or_draw":    "{home} DC",
    "away_or_draw":    "{away} DC",
    "over15":          "Over 1.5 Goals",
    "over25":          "Over 2.5 Goals",
    "over35":          "Over 3.5 Goals",
    "under25":         "Under 2.5 Goals",
    "btts_yes":        "BTTS Yes",
    "btts_no":         "BTTS No",
    "over35_cards":    "Over 3.5 Cards",
    "over45_cards":    "Over 4.5 Cards",
    "over85_corners":  "Over 8.5 Corners",
    "over105_corners": "Over 10.5 Corners",
}


def confidence_label(prob: float) -> str:
    if prob >= MIN_VERY_STRONG:
        return "⭐⭐⭐ VERY STRONG"
    elif prob >= MIN_STRONG:
        return "⭐⭐ STRONG"
    elif prob >= MIN_CONFIDENCE:
        return "⭐ MODERATE"
    else:
        return "❌ LOW"


def get_market_probs(home: str, away: str, odds: dict = None) -> dict:
    """Get all market probabilities for a match."""
    pred = predict_match(home, away)
    if "error" in pred:
        return {}

    g = pred["goals"]
    r = pred["result"]
    c = pred["cards"]
    co = pred["corners"]

    return {
        "home_win":        r["home_win"],
        "draw":            r["draw"],
        "away_win":        r["away_win"],
        "home_or_draw":    r["home_or_draw"],
        "away_or_draw":    r["away_or_draw"],
        "over15":          g["over15"],
        "over25":          g["over25"],
        "over35":          g["over35"],
        "under25":         g["under25"],
        "btts_yes":        g["btts_yes"],
        "btts_no":         g["btts_no"],
        "over35_cards":    c["over35_cards"],
        "over45_cards":    c["over45_cards"],
        "over85_corners":  co["over85_corners"],
        "over105_corners": co["over105_corners"],
        "_prediction":     pred,
    }


def get_label(market: str, home: str, away: str) -> str:
    template = MARKET_LABELS.get(market, market)
    return template.replace("{home}", home).replace("{away}", away)


def build_match_acca_legs(
    home: str,
    away: str,
    odds: dict = None,
    top_n: int = 2,
) -> dict:
    """
    Get top N acca legs for a single match.
    Returns ranked list of high-confidence markets.
    """
    probs = get_market_probs(home, away, odds)
    if not probs:
        return {"error": f"Could not predict {home} vs {away}"}

    pred = probs.pop("_prediction")

    # Get streak data
    streak_data = analyze_match_streaks(home, away)
    home_streaks = streak_data.get("home_streaks", {})
    away_streaks = streak_data.get("away_streaks", {})

    confirmation = get_streak_confirmation(
        home_streaks, away_streaks,
        model_over25=probs.get("over25", 0),
        model_btts=probs.get("btts_yes", 0),
        model_over35_cards=probs.get("over35_cards", 0),
        model_over85_corners=probs.get("over85_corners", 0),
    )

    # Filter and rank by confidence
    qualified = []
    for market, prob in probs.items():
        if prob < MIN_CONFIDENCE:
            continue

        # Get odds if provided
        market_odds = odds.get(market) if odds else None

        # Check streak confirmation
        streak_signal = None
        if market in confirmation:
            streak_signal = confirmation[market]["signal"]

        qualified.append({
            "market":        market,
            "label":         get_label(market, home, away),
            "probability":   round(prob, 3),
            "odds":          market_odds,
            "confidence":    confidence_label(prob),
            "streak_signal": streak_signal,
        })

    # Sort by probability descending
    qualified.sort(key=lambda x: x["probability"], reverse=True)

    # Get manager info
    home_mgr = pred.get("home_manager", {})
    away_mgr = pred.get("away_manager", {})

    return {
        "home_team":    home,
        "away_team":    away,
        "home_xg":      pred["goals"]["home_xg"],
        "away_xg":      pred["goals"]["away_xg"],
        "home_manager": home_mgr.get("name", "Unknown"),
        "away_manager": away_mgr.get("name", "Unknown"),
        "top_legs":     qualified[:top_n],
        "all_legs":     qualified,
        "total_qualified": len(qualified),
    }


def build_acca(matches: list, odds_map: dict = None, top_per_match: int = 1) -> dict:
    """
    Build a full accumulator from multiple matches.

    matches: list of (home, away) tuples
    odds_map: dict of "Home vs Away" -> odds dict
    top_per_match: how many legs to pick per match

    Returns suggested acca with combined odds and confidence.
    """
    match_analyses = []
    suggested_legs = []
    combined_odds = 1.0
    all_strong = True

    for home, away in matches:
        key = f"{home} vs {away}"
        odds = odds_map.get(key) if odds_map else None

        result = build_match_acca_legs(home, away, odds, top_n=top_per_match)

        if "error" in result:
            match_analyses.append({
                "home": home, "away": away, "error": result["error"]
            })
            continue

        match_analyses.append(result)

        # Pick best leg for suggested acca
        if result["top_legs"]:
            best = result["top_legs"][0]
            suggested_legs.append({
                "match":       f"{home} vs {away}",
                "market":      best["label"],
                "probability": best["probability"],
                "odds":        best["odds"],
                "confidence":  best["confidence"],
                "streak":      best["streak_signal"],
            })

            if best["odds"]:
                combined_odds *= best["odds"]

            if best["probability"] < MIN_STRONG:
                all_strong = False

    # Risk assessment
    n_legs = len(suggested_legs)
    if n_legs == 0:
        risk = "NO LEGS"
    elif n_legs <= 2:
        risk = "LOW RISK"
    elif n_legs <= 4:
        risk = "MODERATE RISK"
    else:
        risk = "HIGH RISK"

    avg_prob = (
        sum(l["probability"] for l in suggested_legs) / n_legs
        if n_legs else 0
    )

    return {
        "matches":        match_analyses,
        "suggested_legs": suggested_legs,
        "combined_odds":  round(combined_odds, 2) if combined_odds != 1.0 else None,
        "n_legs":         n_legs,
        "avg_probability": round(avg_prob, 3),
        "all_strong":     all_strong,
        "risk":           risk,
    }


def format_acca_report(acca: dict) -> str:
    """Format acca builder report for Telegram."""
    lines = ["🎯 <b>ACCA BUILDER</b>", ""]

    for i, match in enumerate(acca["matches"], 1):
        if "error" in match:
            lines.append(
                f"{i}️⃣ {match['home']} vs {match['away']} — ❌ {match['error']}")
            continue

        home = match["home_team"]
        away = match["away_team"]
        lines.append(
            f"{i}️⃣ <b>{home} vs {away}</b> "
            f"(xG: {match['home_xg']} — {match['away_xg']})"
        )
        lines.append(
            f"   👔 {match['home_manager']} vs {match['away_manager']}"
        )

        for j, leg in enumerate(match["top_legs"], 1):
            streak_icon = ""
            if leg["streak_signal"] == "CONFIRMS":
                streak_icon = " 📈"
            elif leg["streak_signal"] == "CONFLICTS":
                streak_icon = " ⚠️"

            odds_str = f"@ {leg['odds']}" if leg["odds"] else ""
            lines.append(
                f"   {'🥇' if j == 1 else '🥈'} {leg['label']} {odds_str}"
                f" — {leg['probability']*100:.0f}% {leg['confidence']}{streak_icon}"
            )
        lines.append("")

    # Suggested acca
    if acca["suggested_legs"]:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📋 <b>SUGGESTED ACCA ({acca['n_legs']} legs)</b>")
        for leg in acca["suggested_legs"]:
            streak_icon = " 📈" if leg["streak"] == "CONFIRMS" else (
                " ⚠️" if leg["streak"] == "CONFLICTS" else ""
            )
            odds_str = f"@ {leg['odds']}" if leg["odds"] else ""
            lines.append(
                f"  ✅ {leg['market']} {odds_str} "
                f"— {leg['probability']*100:.0f}%{streak_icon}"
            )

        lines.append("")
        if acca["combined_odds"]:
            lines.append(f"💰 Combined odds: <b>{acca['combined_odds']}</b>")
        lines.append(f"📊 Avg confidence: {acca['avg_probability']*100:.0f}%")
        lines.append(f"⚡ Risk: {acca['risk']}")
        lines.append(
            f"{'✅ All legs strong confidence' if acca['all_strong'] else '⚠️ Some legs moderate confidence'}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing acca builder...\n")

    # Test single match
    print("Single match — Arsenal vs Chelsea:")
    result = build_match_acca_legs("Arsenal", "Chelsea", top_n=2)
    for leg in result["top_legs"]:
        print(
            f"  {leg['label']}: {leg['probability']*100:.0f}% — {leg['confidence']}")

    print("\nMulti-match acca:")
    acca = build_acca([
        ("Arsenal",  "Chelsea"),
        ("Man City", "Liverpool"),
        ("Leeds",    "Ipswich"),
    ])
    print(format_acca_report(acca))
