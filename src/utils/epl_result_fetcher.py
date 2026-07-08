"""
EPL Result Fetcher — SportyBet Nigeria
Fetches completed EPL match results and auto-settles predictions.
Run after each gameweek to update result tracker automatically.
"""

import requests
import json
import os
from datetime import datetime

from src.utils.result_tracker import settle_match, print_performance

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    "Accept": "application/json",
    "Origin": "https://www.sportybet.com",
    "Referer": "https://www.sportybet.com/ng/",
    "Current-Country": "NG",
}

RESULTS_API = "https://www.sportybet.com/api/ng/factsCenter/wapConfigurableEventsByOrder"

# Map SportyBet names to canonical names
NAME_MAP = {
    "Man Utd":           "Man United",
    "Manchester United": "Man United",
    "Manchester Utd":    "Man United",
    "Man City":          "Man City",
    "Manchester City":   "Man City",
    "Nottingham Forest": "Nott'm Forest",
    "Newcastle United":  "Newcastle",
    "Newcastle Utd":     "Newcastle",
    "Leeds United":      "Leeds",
    "Ipswich Town":      "Ipswich",
    "Sunderland AFC":    "Sunderland",
    "Wolverhampton Wanderers": "Wolves",
    "Tottenham Hotspur": "Tottenham",
    "West Ham United":   "West Ham",
    "Sheffield Utd":     "Sheffield United",
    "Brighton & Hove Albion": "Brighton",
    "Coventry City":     "Coventry City",
    "Hull City":         "Hull City",
    "Aston Villa":       "Aston Villa",
    "Crystal Palace":    "Crystal Palace",
    "Bournemouth":       "Bournemouth",
    "Brentford":         "Brentford",
    "Fulham":            "Fulham",
    "Chelsea":           "Chelsea",
    "Arsenal":           "Arsenal",
    "Everton":           "Everton",
    "Liverpool":         "Liverpool",
}


def normalise(name: str) -> str:
    return NAME_MAP.get(name, name)


def fetch_epl_results() -> list:
    """
    Fetch completed EPL matches from SportyBet.
    Returns list of settled match dicts.
    """
    payload = {
        "productId":       3,
        "sportId":         "sr:sport:1",
        "order":           0,
        "pageNum":         1,
        "pageSize":        100,
        "withOneUpMarket": False,
        "withTwoUpMarket": False,
    }

    try:
        response = requests.post(
            RESULTS_API, headers=HEADERS, json=payload, timeout=15
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[ERROR] Could not fetch results: {e}")
        return []

    results = []
    tournaments = data.get("data", {}).get("tournaments", [])

    for t in tournaments:
        t_name = t.get("name", "")
        category = t.get("categoryName", "")

        if "Premier League" not in t_name or category != "England":
            continue

        for event in t.get("events", []):
            status = event.get("matchStatus", "")

            # Only settled matches
            if status not in ["ended", "finished", "3", 3]:
                continue

            home_raw = event.get("homeTeamName", "")
            away_raw = event.get("awayTeamName", "")
            home = normalise(home_raw)
            away = normalise(away_raw)

            # Extract score
            score = event.get("score", "")
            home_goals = None
            away_goals = None

            if score and "-" in str(score):
                try:
                    parts = str(score).split("-")
                    home_goals = int(parts[0].strip())
                    away_goals = int(parts[1].strip())
                except:
                    pass

            # Try markets for score if not in score field
            if home_goals is None:
                for market in event.get("markets", []):
                    if market.get("id") == "1" and market.get("specifier") == "":
                        for outcome in market.get("outcomes", []):
                            if outcome.get("isWinner"):
                                pass  # Extract from outcome desc if needed

            if home_goals is None:
                continue

            results.append({
                "home_team":  home,
                "away_team":  away,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "score":      f"{home_goals}-{away_goals}",
                "status":     status,
            })

    return results


def auto_settle_gameweek():
    """
    Fetch all completed EPL results and settle logged predictions.
    Run after each gameweek completes.
    """
    print("=" * 55)
    print("  EPL Auto-Settler")
    print(f"  {datetime.now().strftime('%d %b %Y %H:%M')}")
    print("=" * 55)

    # Load prediction log
    log_file = "data/prediction_log.json"
    if not os.path.exists(log_file):
        print("\n[WARN] No prediction log found. Nothing to settle.")
        return

    with open(log_file) as f:
        log = json.load(f)

    unsettled = [
        p for p in log.get("predictions", [])
        if not p.get("settled")
    ]

    if not unsettled:
        print("\n✅ All predictions already settled.")
        print_performance()
        return

    print(f"\nUnsettled predictions: {len(unsettled)}")
    print("Fetching EPL results from SportyBet...\n")

    results = fetch_epl_results()

    if not results:
        print("[WARN] No completed EPL results found on SportyBet.")
        print("Tip: Results appear after matches finish.")
        print("Try running this command again after GW completes.")
        return

    print(f"Completed matches found: {len(results)}\n")

    settled_count = 0
    not_found = []

    for pred in unsettled:
        home = pred["home_team"]
        away = pred["away_team"]

        # Find matching result
        matched = None
        for r in results:
            if (r["home_team"].lower() == home.lower() and
                    r["away_team"].lower() == away.lower()):
                matched = r
                break

        if not matched:
            not_found.append(f"{home} vs {away}")
            continue

        print(f"Settling: {home} {matched['score']} {away}")
        settle_match(
            home_team=home,
            away_team=away,
            home_goals=matched["home_goals"],
            away_goals=matched["away_goals"],
        )
        settled_count += 1

    print(f"\n{'='*55}")
    print(f"  Settled: {settled_count} matches")
    if not_found:
        print(f"  Not found on SportyBet: {len(not_found)}")
        for m in not_found:
            print(f"    - {m}")
    print("=" * 55)

    if settled_count > 0:
        print("\nUpdated performance:")
        print_performance()


def manual_settle(home: str, away: str, score: str):
    """
    Manually settle a single match.
    Usage: python -m src.utils.epl_result_fetcher settle Arsenal Chelsea 2-1
    """
    try:
        parts = score.split("-")
        home_goals = int(parts[0])
        away_goals = int(parts[1])
    except:
        print(f"[ERROR] Invalid score format: {score}. Use format: 2-1")
        return

    settle_match(home, away, home_goals, away_goals)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "settle":
        # Manual settle: python -m src.utils.epl_result_fetcher settle Arsenal Chelsea 2-1
        if len(sys.argv) >= 5:
            manual_settle(sys.argv[2], sys.argv[3], sys.argv[4])
        else:
            print(
                "Usage: python -m src.utils.epl_result_fetcher settle HomeTeam AwayTeam Score")
            print(
                "Example: python -m src.utils.epl_result_fetcher settle Arsenal Chelsea 2-1")
    else:
        # Auto settle all
        auto_settle_gameweek()
