"""
Value Detection Engine.

Compares our Elo model probabilities against SportyBet's implied
probabilities to identify positive expected value (EV) opportunities.

Core formula:
    EV = (Model Probability * Decimal Odds) - 1
    Edge = Model Probability - Implied Probability

Only flag bets where EV > threshold AND Edge > threshold.
"""

import json
import os
from datetime import datetime
from src.models.elo_model import EloModel
from src.collectors.sportybet_scraper import fetch_sportybet_odds, parse_matches

# Minimum thresholds to flag a value bet
MIN_EDGE = 8.0          # Minimum edge % over bookmaker
MIN_EV = 0.10           # Minimum expected value (5% return per unit)
MIN_ODDS = 1.30         # Ignore very short odds — too risky
MAX_ODDS = 15.0         # Ignore very long odds — too uncertain

OUTPUT_FILE = "data/value_bets.json"


def implied_probability(decimal_odds):
    """Convert decimal odds to implied probability %."""
    if decimal_odds <= 1.0:
        return 100.0
    return round(1 / decimal_odds * 100, 4)


def expected_value(model_prob_pct, decimal_odds):
    """
    Calculate expected value of a bet.

    EV > 0 means profitable long-term.
    EV = -1 means you lose your entire stake.
    EV = +0.10 means 10% return per unit staked.
    """
    model_prob = model_prob_pct / 100
    return round((model_prob * decimal_odds) - 1, 4)


def detect_value(sportybet_match, elo_prediction):
    """
    Compare SportyBet odds vs Elo model for a single match.
    Returns list of value bets found (can be 0, 1, 2, or 3).
    """
    value_bets = []

    if not sportybet_match.get("has_odds"):
        return value_bets

    odds = sportybet_match["odds"]
    model_probs = elo_prediction["model_probability"]

    outcomes = [
        {
            "outcome": "Home Win",
            "team": sportybet_match["home_team"],
            "decimal_odds": odds["home"],
            "model_prob": model_probs["home"],
        },
        {
            "outcome": "Draw",
            "team": "Draw",
            "decimal_odds": odds["draw"],
            "model_prob": model_probs["draw"],
        },
        {
            "outcome": "Away Win",
            "team": sportybet_match["away_team"],
            "decimal_odds": odds["away"],
            "model_prob": model_probs["away"],
        }
    ]

    for outcome in outcomes:
        dec_odds = outcome["decimal_odds"]
        model_prob = outcome["model_prob"]

        # Skip odds outside our range
        if dec_odds < MIN_ODDS or dec_odds > MAX_ODDS:
            continue

        bookie_prob = implied_probability(dec_odds)
        edge = round(model_prob - bookie_prob, 2)
        ev = expected_value(model_prob, dec_odds)

        if edge >= MIN_EDGE and ev >= MIN_EV:
            value_bets.append({
                "outcome": outcome["outcome"],
                "selection": outcome["team"],
                "decimal_odds": dec_odds,
                "model_probability": model_prob,
                "implied_probability": bookie_prob,
                "edge": edge,
                "expected_value": ev,
                "rating": get_value_rating(edge, ev)
            })

    return value_bets


def get_value_rating(edge, ev):
    """
    Simple value rating system.

    ★★★  = Strong value
    ★★   = Good value  
    ★    = Marginal value
    """
    if edge >= 15 and ev >= 0.15:
        return "★★★ STRONG"
    elif edge >= 10 and ev >= 0.10:
        return "★★ GOOD"
    else:
        return "★ MARGINAL"


def run_value_detection():
    """
    Full pipeline:
    1. Fetch SportyBet odds
    2. Generate Elo predictions for each match
    3. Compare and flag value bets
    """
    print(f"\n{'='*65}")
    print(f"  FOOTBALL INTELLIGENCE — VALUE DETECTION ENGINE")
    print(f"  {datetime.now().strftime('%d %b %Y %H:%M:%S')}")
    print(f"{'='*65}\n")

    # Step 1: Fetch live odds
    print("[1/3] Fetching SportyBet odds...")
    raw_data = fetch_sportybet_odds(page_size=50)
    sportybet_matches = parse_matches(raw_data)

    if not sportybet_matches:
        print("[ERROR] No matches fetched from SportyBet")
        return []

    matches_with_odds = [m for m in sportybet_matches if m["has_odds"]]
    print(f"[OK] {len(matches_with_odds)} matches with odds\n")

    # Step 2: Generate Elo predictions
    print("[2/3] Generating Elo model predictions...")
    model = EloModel()

    # Step 3: Compare and detect value
    print("[3/3] Running value detection...\n")

    all_value_bets = []
    match_analyses = []

    for match in matches_with_odds:
        home = match["home_team"]
        away = match["away_team"]

        # World Cup = neutral venue
        prediction = model.predict_match(home, away, neutral_venue=True)
        value_bets = detect_value(match, prediction)

        match_analysis = {
            "home_team": home,
            "away_team": away,
            "competition": match.get("competition", ""),
            "kick_off": match.get("kick_off", ""),
            "sportybet_odds": match["odds"],
            "sportybet_implied": match["implied_probability"],
            "model_probability": prediction["model_probability"],
            "home_elo": prediction["home_rating"],
            "away_elo": prediction["away_rating"],
            "value_bets": value_bets,
            "has_value": len(value_bets) > 0
        }

        match_analyses.append(match_analysis)
        all_value_bets.extend(value_bets)

    # Display results
    display_results(match_analyses)

    # Save
    save_results(match_analyses)

    return all_value_bets


def display_results(match_analyses):
    value_matches = [m for m in match_analyses if m["has_value"]]
    no_value = [m for m in match_analyses if not m["has_value"]]

    print(f"\n{'='*65}")
    print(f"  VALUE BETS DETECTED: {len(value_matches)} matches")
    print(f"  No value:            {len(no_value)} matches")
    print(f"{'='*65}")

    if value_matches:
        print(f"\n  *** VALUE OPPORTUNITIES ***\n")
        for match in value_matches:
            print(f"  {match['home_team']} vs {match['away_team']}")
            print(f"  Kick-off: {match['kick_off']}")
            print(f"  Elo:      {match['home_elo']} vs {match['away_elo']}")
            print(f"")
            print(
                f"  {'Outcome':<12} {'Odds':>6} {'Bookie%':>9} {'Model%':>8} {'Edge':>7} {'EV':>7} {'Rating'}")
            print(f"  {'-'*65}")

            # Show all outcomes for context
            odds = match["sportybet_odds"]
            bookie = match["sportybet_implied"]
            model = match["model_probability"]

            outcomes = [
                ("Home Win", odds["home"], bookie["home"], model["home"]),
                ("Draw", odds["draw"], bookie["draw"], model["draw"]),
                ("Away Win", odds["away"], bookie["away"], model["away"]),
            ]

            value_outcomes = {vb["outcome"] for vb in match["value_bets"]}

            for name, odd, bk, md in outcomes:
                edge = round(md - bk, 2)
                ev = expected_value(md, odd)
                flag = " ← VALUE" if name in value_outcomes else ""
                rating = ""
                if name in value_outcomes:
                    for vb in match["value_bets"]:
                        if vb["outcome"] == name:
                            rating = vb["rating"]

                print(f"  {name:<12} {odd:>6.2f} {bk:>8.2f}% {md:>7.2f}% "
                      f"{edge:>+6.2f}% {ev:>+6.3f}  {rating}{flag}")

            print()

    else:
        print(f"\n  No value bets found in current matches.")
        print(f"  This is normal — value opportunities are rare.")
        print(f"  The model is working correctly.\n")

    print(f"\n  ALL MATCHES ANALYZED:\n")
    for match in match_analyses:
        model = match["model_probability"]
        bookie = match["sportybet_implied"]
        print(f"  {match['home_team']:<22} vs {match['away_team']:<22}")
        print(
            f"  Model:  {model['home']:>5.1f}% / {model['draw']:>5.1f}% / {model['away']:>5.1f}%")
        print(
            f"  Bookie: {bookie['home']:>5.1f}% / {bookie['draw']:>5.1f}% / {bookie['away']:>5.1f}%")
        if match["has_value"]:
            print(f"  *** VALUE DETECTED ***")
        print()

    print(f"{'='*65}\n")


def save_results(match_analyses):
    os.makedirs("data", exist_ok=True)
    output = {
        "generated_at": datetime.now().isoformat(),
        "total_matches": len(match_analyses),
        "value_matches": len([m for m in match_analyses if m["has_value"]]),
        "analyses": match_analyses
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[SAVED] Full analysis → {OUTPUT_FILE}")


if __name__ == "__main__":
    run_value_detection()
