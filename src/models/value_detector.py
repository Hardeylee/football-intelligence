"""
Value Detection Engine.

Compares our Elo model probabilities against SportyBet's implied
probabilities to identify positive expected value (EV) opportunities.

Pipeline:
1. Fetch live odds from SportyBet
2. Filter to World Cup matches only
3. Generate Elo base prediction
4. Apply Manager Intelligence adjustments
5. Compare adjusted probabilities vs bookmaker
6. Flag value bets above threshold
"""

import json
import os
from datetime import datetime
from src.models.elo_model import EloModel
from src.models.manager_intelligence import ManagerIntelligence
from src.collectors.sportybet_scraper import fetch_sportybet_odds, parse_matches

# Minimum thresholds to flag a value bet
MIN_EDGE = 8.0
MIN_EV = 0.10
MIN_ODDS = 1.30
MAX_ODDS = 15.0

# Only analyse these competitions with national team Elo model
VALID_COMPETITIONS = ["World Cup"]

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
    EV = +0.10 means 10% return per unit staked.
    """
    model_prob = model_prob_pct / 100
    return round((model_prob * decimal_odds) - 1, 4)


def get_value_rating(edge, ev):
    """
    Simple value rating system.
    ★★★ = Strong value
    ★★  = Good value
    ★   = Marginal value
    """
    if edge >= 15 and ev >= 0.15:
        return "★★★ STRONG"
    elif edge >= 10 and ev >= 0.10:
        return "★★ GOOD"
    else:
        return "★ MARGINAL"


def detect_value(sportybet_match, prediction):
    """
    Compare SportyBet odds vs model prediction for a single match.
    Returns list of value bets found.
    """
    value_bets = []

    if not sportybet_match.get("has_odds"):
        return value_bets

    odds = sportybet_match["odds"]
    model_probs = prediction["model_probability"]

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


def run_value_detection():
    """
    Full pipeline:
    1. Fetch SportyBet odds
    2. Filter to World Cup only
    3. Generate Elo + Manager Intelligence predictions
    4. Compare and flag value bets
    """
    print(f"\n{'='*65}")
    print(f"  FOOTBALL INTELLIGENCE — VALUE DETECTION ENGINE")
    print(f"  {datetime.now().strftime('%d %b %Y %H:%M:%S')}")
    print(f"{'='*65}\n")

    # Step 1: Fetch live odds
    print("[1/3] Fetching SportyBet odds...")
    raw_data = fetch_sportybet_odds(page_size=50)
    all_matches = parse_matches(raw_data)

    if not all_matches:
        print("[ERROR] No matches fetched from SportyBet")
        return []

    # Step 2: Filter to World Cup matches only
    matches_with_odds = [
        m for m in all_matches
        if m["has_odds"] and m.get("competition", "") in VALID_COMPETITIONS
    ]

    total_fetched = len(all_matches)
    total_filtered = len(matches_with_odds)
    total_skipped = total_fetched - total_filtered

    print(f"[OK] Fetched: {total_fetched} matches total")
    print(f"[OK] World Cup matches with odds: {total_filtered}")
    if total_skipped > 0:
        print(f"[--] Skipped {total_skipped} non-World Cup matches\n")

    if not matches_with_odds:
        print("[ERROR] No World Cup matches found")
        return []

    # Step 3: Initialise models
    print("[2/3] Generating Elo + Manager Intelligence predictions...")
    elo_model = EloModel()
    manager_intel = ManagerIntelligence()

    # Step 4: Analyse each match
    print("[3/3] Running value detection...\n")

    all_value_bets = []
    match_analyses = []

    for match in matches_with_odds:
        home = match["home_team"]
        away = match["away_team"]
        competition = match.get("competition", "")
        kick_off = match.get("kick_off", "")

        # Base Elo prediction (neutral venue for World Cup)
        prediction = elo_model.predict_match(
            home, away, neutral_venue=True
        )

        # Apply Manager Intelligence adjustments
        prediction = manager_intel.apply_manager_adjustments(
            prediction, home, away
        )

        # Detect value bets
        value_bets = detect_value(match, prediction)

        # Build full match analysis record
        match_analysis = {
            "home_team": home,
            "away_team": away,
            "competition": competition,
            "kick_off": kick_off,
            "sportybet_odds": match["odds"],
            "sportybet_implied": match["implied_probability"],
            "model_probability": prediction["model_probability"],
            "home_elo": prediction["home_rating"],
            "away_elo": prediction["away_rating"],
            "manager_intelligence": prediction.get("manager_intelligence", {}),
            "tactical_narrative": manager_intel.get_match_narrative(home, away),
            "value_bets": value_bets,
            "has_value": len(value_bets) > 0
        }

        match_analyses.append(match_analysis)
        all_value_bets.extend(value_bets)

    # Display and save results
    display_results(match_analyses)
    save_results(match_analyses)

    return all_value_bets


def display_results(match_analyses):
    """Print full analysis to terminal."""
    value_matches = [m for m in match_analyses if m["has_value"]]
    no_value = [m for m in match_analyses if not m["has_value"]]

    print(f"\n{'='*65}")
    print(f"  VALUE BETS DETECTED: {len(value_matches)} matches")
    print(f"  No value:            {len(no_value)} matches")
    print(f"{'='*65}")

    if value_matches:
        print(f"\n  *** VALUE OPPORTUNITIES ***\n")

        for match in value_matches:
            home = match["home_team"]
            away = match["away_team"]
            mgr = match.get("manager_intelligence", {})

            print(f"  {home} vs {away}")
            print(f"  Kick-off:  {match['kick_off']}")
            print(f"  Elo:       {match['home_elo']} vs {match['away_elo']}")

            # Manager context
            if mgr:
                print(f"  Managers:  {mgr.get('home_manager', '?')} "
                      f"({mgr.get('home_formation', '?')}, "
                      f"{mgr.get('home_style', '?')}) vs "
                      f"{mgr.get('away_manager', '?')} "
                      f"({mgr.get('away_formation', '?')}, "
                      f"{mgr.get('away_style', '?')})")
                print(f"  Matchup:   {mgr.get('tactical_matchup', '?')}")
                print(
                    f"  Confidence: {mgr.get('combined_confidence', 1.0):.0%}")

            print(f"")
            print(f"  {'Outcome':<12} {'Odds':>6} {'Bookie%':>9} "
                  f"{'Model%':>8} {'Edge':>7} {'EV':>7}  Rating")
            print(f"  {'-'*65}")

            odds = match["sportybet_odds"]
            bookie = match["sportybet_implied"]
            model = match["model_probability"]
            value_outcomes = {vb["outcome"] for vb in match["value_bets"]}

            outcomes = [
                ("Home Win", odds["home"], bookie["home"], model["home"]),
                ("Draw",     odds["draw"], bookie["draw"], model["draw"]),
                ("Away Win", odds["away"], bookie["away"], model["away"]),
            ]

            for name, odd, bk, md in outcomes:
                edge = round(md - bk, 2)
                ev = expected_value(md, odd)
                is_value = name in value_outcomes
                flag = " ← VALUE" if is_value else ""
                rating = ""
                if is_value:
                    for vb in match["value_bets"]:
                        if vb["outcome"] == name:
                            rating = vb["rating"]
                print(f"  {name:<12} {odd:>6.2f} {bk:>8.2f}% {md:>7.2f}% "
                      f"{edge:>+6.2f}% {ev:>+6.3f}  {rating}{flag}")

            # Tactical narrative
            narrative = match.get("tactical_narrative", "")
            if narrative:
                print(f"\n  Tactical context:")
                for line in narrative.split("\n  "):
                    print(f"  {line}")
            print()

    else:
        print(f"\n  No value bets found in current matches.")
        print(f"  This is normal — value opportunities are rare.\n")

    # Summary table of all matches
    print(f"\n  ALL WORLD CUP MATCHES ANALYSED:\n")
    print(f"  {'Home':<22} {'Away':<22} {'H%':>5} {'D%':>5} "
          f"{'A%':>5}  {'Matchup':<20} Value")
    print(f"  {'-'*80}")

    for match in match_analyses:
        model = match["model_probability"]
        mgr = match.get("manager_intelligence", {})
        matchup = mgr.get("tactical_matchup", "unknown")[:20]
        flag = "  ★ VALUE" if match["has_value"] else ""
        print(f"  {match['home_team']:<22} {match['away_team']:<22} "
              f"{model['home']:>5.1f} {model['draw']:>5.1f} "
              f"{model['away']:>5.1f}  {matchup:<20}{flag}")

    print(f"\n{'='*65}\n")


def save_results(match_analyses):
    """Save full analysis to JSON."""
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
