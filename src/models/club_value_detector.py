"""
Club Football Value Detector
Compares match_predictor probabilities against SportyBet odds.
Flags markets where edge >= 8% and EV >= 0.10
"""

from src.models.match_predictor import predict_match

MIN_EDGE = 0.08        # Default minimum edge
MIN_EV = 0.10          # Minimum expected value
RESULT_MIN_EDGE = 0.15  # Higher bar for 1X2 result markets


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


def check_goals_filter(home_team: str, away_team: str, min_rate: float = 0.55) -> dict:
    """
    Check if both teams have high enough over 2.5 rates.
    Uses historical profiles first, falls back to xG-derived rates for promoted teams.
    """
    import json

    try:
        with open("data/team_profiles.json") as f:
            hist = json.load(f)["teams"]
    except:
        hist = {}

    try:
        with open("data/xg_profiles.json") as f:
            xg = json.load(f)["teams"]
    except:
        xg = {}

    def get_over25_rate(team: str) -> tuple:
        """Returns (rate, source)"""
        # Try historical first
        if team in hist and hist[team].get("over25_rate", 0) > 0:
            return hist[team]["over25_rate"], "historical"
        # Fall back to xG-derived rate
        if team in xg and xg[team].get("xg_over25_rate", 0) > 0:
            return xg[team]["xg_over25_rate"], "xG"
        return 0.50, "league_average"  # Neutral fallback

    home_rate, home_source = get_over25_rate(home_team)
    away_rate, away_source = get_over25_rate(away_team)

    # Apply promoted team discount if using xG source
    # Promoted teams' xG rates from Championship need slight reduction
    if home_source == "xG":
        home_rate = round(home_rate * 0.92, 3)
    if away_source == "xG":
        away_rate = round(away_rate * 0.92, 3)

    both_qualify = home_rate >= min_rate and away_rate >= min_rate

    return {
        "home_over25_rate":   home_rate,
        "away_over25_rate":   away_rate,
        "home_source":        home_source,
        "away_source":        away_source,
        "both_qualify":       both_qualify,
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

    # Markets that need higher edge threshold
    result_markets = {"home_win", "draw",
                      "away_win", "home_or_draw", "away_or_draw"}

    for market, model_prob in market_map.items():
        odds = sportybet_odds.get(market)
        if not odds:
            continue

        # Use higher edge threshold for result markets
        min_edge = RESULT_MIN_EDGE if market in result_markets else MIN_EDGE
        imp = implied_prob(odds)
        edge = model_prob - imp
        ev = (model_prob * (odds - 1)) - (1 - model_prob)

        analysis = {
            "model_prob":   round(model_prob, 3),
            "implied_prob": round(imp, 3),
            "odds":         odds,
            "edge":         round(edge, 4),
            "ev":           round(ev, 4),
            "value":        edge >= min_edge and ev >= MIN_EV,
            "min_edge_used": min_edge,
        }

        results[market] = analysis
        if analysis["value"]:
            value_bets.append({
                "market":     market,
                "odds":       odds,
                "edge":       analysis["edge"],
                "ev":         analysis["ev"],
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

    # Add goals filter info
    gf = check_goals_filter(h, a)
    if gf["home_over25_rate"] and gf["away_over25_rate"]:
        home_src = "xG" if gf.get("home_source") == "xG" else ""
        away_src = "xG" if gf.get("away_source") == "xG" else ""
        lines.append(
            f"📊 Over 2.5 rates: {h} {gf['home_over25_rate']*100:.0f}%{home_src} | "
            f"{a} {gf['away_over25_rate']*100:.0f}%{away_src}"
            f" {'✅' if gf['both_qualify'] else '⚠️ one team low'}"
        )

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
