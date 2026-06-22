"""
Club Football Value Detector
Compares match_predictor probabilities against SportyBet odds.
Flags markets where edge >= 8% and EV >= 0.10
"""

from src.models.match_predictor import predict_match

MIN_EDGE = 0.08
MIN_EV = 0.10


def implied_prob(odds: float) -> float:
    """Convert decimal odds to implied probability."""
    return round(1 / odds, 4) if odds > 1 else 0.0


def calculate_edge(model_prob: float, market_odds: float) -> dict:
    """Calculate edge and EV for a single market."""
    imp = implied_prob(market_odds)
    edge = model_prob - imp
    ev = (model_prob * (market_odds - 1)) - (1 - model_prob)
    return {
        "model_prob":   round(model_prob, 3),
        "implied_prob": round(imp, 3),
        "odds":         market_odds,
        "edge":         round(edge, 4),
        "ev":           round(ev, 4),
        "value":        edge >= MIN_EDGE and ev >= MIN_EV,
    }


def detect_value(home_team: str, away_team: str, sportybet_odds: dict) -> dict:
    """
    Main function. Takes team names + SportyBet odds dict.
    Returns all markets with value flags.

    sportybet_odds format:
    {
        "home_win":    2.10,
        "draw":        3.40,
        "away_win":    3.80,
        "over15":      1.35,
        "over25":      1.90,
        "over35":      3.20,
        "under25":     1.95,
        "btts_yes":    1.75,
        "btts_no":     2.05,
        "over35_cards": 1.85,
        "over45_cards": 2.40,
        "over85_corners":  1.55,
        "over105_corners": 2.10,
    }
    """
    pred = predict_match(home_team, away_team)
    if "error" in pred:
        return {"error": pred["error"]}

    r = pred["result"]
    g = pred["goals"]
    c = pred["cards"]
    co = pred["corners"]

    # Map model probs to market keys
    market_map = {
        "home_win":       r["home_win"],
        "draw":           r["draw"],
        "away_win":       r["away_win"],
        "home_or_draw":   r["home_or_draw"],
        "away_or_draw":   r["away_or_draw"],
        "over15":         g["over15"],
        "over25":         g["over25"],
        "over35":         g["over35"],
        "under25":        g["under25"],
        "btts_yes":       g["btts_yes"],
        "btts_no":        g["btts_no"],
        "over35_cards":   c["over35_cards"],
        "over45_cards":   c["over45_cards"],
        "over85_corners": co["over85_corners"],
        "over105_corners": co["over105_corners"],
    }

    results = {}
    value_bets = []

    for market, model_prob in market_map.items():
        odds = sportybet_odds.get(market)
        if not odds:
            continue
        analysis = calculate_edge(model_prob, odds)
        results[market] = analysis
        if analysis["value"]:
            value_bets.append({
                "market": market,
                "odds":   odds,
                "edge":   analysis["edge"],
                "ev":     analysis["ev"],
                "model_prob": analysis["model_prob"],
            })

    # Sort value bets by edge descending
    value_bets.sort(key=lambda x: x["edge"], reverse=True)

    return {
        "home_team":   home_team,
        "away_team":   away_team,
        "prediction":  pred,
        "all_markets": results,
        "value_bets":  value_bets,
        "has_value":   len(value_bets) > 0,
    }


def format_value_report(analysis: dict) -> str:
    """Format value report for display/Telegram."""
    if "error" in analysis:
        return f"ERROR: {analysis['error']}"

    h = analysis["home_team"]
    a = analysis["away_team"]
    vb = analysis["value_bets"]
    pred = analysis["prediction"]
    g = pred["goals"]

    market_labels = {
        "home_win":        f"{h} Win",
        "draw":            "Draw",
        "away_win":        f"{a} Win",
        "home_or_draw":    f"{h} DC",
        "away_or_draw":    f"{a} DC",
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

    lines = [
        f"⚽ {h} vs {a}",
        f"xG: {g['home_xg']} — {g['away_xg']}",
        "",
    ]

    if vb:
        lines.append("✅ VALUE BETS FOUND:")
        for b in vb:
            label = market_labels.get(b["market"], b["market"])
            lines.append(
                f"  🎯 {label} @ {b['odds']}"
                f" | Edge: {b['edge']*100:.1f}%"
                f" | EV: {b['ev']:.2f}"
                f" | Model: {b['model_prob']*100:.1f}%"
            )
    else:
        lines.append("❌ No value bets found for this match.")

    return "\n".join(lines)


if __name__ == "__main__":
    # Test with dummy SportyBet odds
    test_odds = {
        "home_win":        1.85,
        "draw":            3.60,
        "away_win":        4.20,
        "over15":          1.40,
        "over25":          1.95,
        "over35":          3.10,
        "under25":         1.90,
        "btts_yes":        1.80,
        "btts_no":         2.00,
        "over35_cards":    1.90,
        "over45_cards":    2.50,
        "over85_corners":  1.60,
        "over105_corners": 2.20,
    }

    analysis = detect_value("Arsenal", "Chelsea", test_odds)
    print(format_value_report(analysis))
