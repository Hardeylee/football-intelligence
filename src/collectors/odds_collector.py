import os
import requests
from dotenv import load_dotenv
import json
from datetime import datetime

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"


def get_premier_league_odds():
    """Fetch live Premier League match odds from The Odds API."""

    url = f"{BASE_URL}/sports/soccer_fifa_world_cup/odds"

    params = {
        "apiKey": API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal",
        "dateFormat": "iso"
    }

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching Premier League odds...")

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        remaining = response.headers.get("x-requests-remaining", "unknown")
        print(f"[OK] API credits remaining: {remaining}")

        return data

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to fetch odds: {e}")
        return None


def parse_odds(data):
    """Extract and structure match odds into clean format."""

    if not data:
        return []

    matches = []

    for event in data:
        home_team = event.get("home_team")
        away_team = event.get("away_team")
        commence_time = event.get("commence_time")

        best_home = None
        best_draw = None
        best_away = None

        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        if outcome["name"] == home_team:
                            if best_home is None or outcome["price"] > best_home:
                                best_home = outcome["price"]
                        elif outcome["name"] == "Draw":
                            if best_draw is None or outcome["price"] > best_draw:
                                best_draw = outcome["price"]
                        elif outcome["name"] == away_team:
                            if best_away is None or outcome["price"] > best_away:
                                best_away = outcome["price"]

        if best_home and best_draw and best_away:
            # Convert decimal odds to implied probabilities
            impl_home = round(1 / best_home * 100, 2)
            impl_draw = round(1 / best_draw * 100, 2)
            impl_away = round(1 / best_away * 100, 2)
            total_margin = round(impl_home + impl_draw + impl_away, 2)

            matches.append({
                "home_team": home_team,
                "away_team": away_team,
                "kick_off": commence_time,
                "best_odds": {
                    "home": best_home,
                    "draw": best_draw,
                    "away": best_away
                },
                "implied_probability": {
                    "home": impl_home,
                    "draw": impl_draw,
                    "away": impl_away
                },
                "bookmaker_margin": total_margin
            })

    return matches


def display_odds(matches):
    """Print odds to terminal in readable format."""

    if not matches:
        print("\n[INFO] No upcoming matches found.")
        return

    print(f"\n{'='*65}")
    print(f"  PREMIER LEAGUE — UPCOMING MATCHES & ODDS")
    print(f"  Fetched: {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'='*65}")

    for i, match in enumerate(matches, 1):
        print(f"\n  [{i}] {match['home_team']} vs {match['away_team']}")
        print(f"      Kick-off: {match['kick_off']}")
        print(f"      Best Odds  →  Home: {match['best_odds']['home']}  "
              f"Draw: {match['best_odds']['draw']}  "
              f"Away: {match['best_odds']['away']}")
        print(f"      Implied %  →  Home: {match['implied_probability']['home']}%  "
              f"Draw: {match['implied_probability']['draw']}%  "
              f"Away: {match['implied_probability']['away']}%")
        print(f"      Bookmaker margin: {match['bookmaker_margin']}% "
              f"(overround above 100% = bookie edge)")

    print(f"\n{'='*65}")
    print(f"  Total matches found: {len(matches)}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    raw_data = get_premier_league_odds()
    matches = parse_odds(raw_data)
    display_odds(matches)
