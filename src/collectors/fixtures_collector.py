import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")
API_HOST = os.getenv("API_FOOTBALL_HOST")

HEADERS = {
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": API_HOST
}

BASE_URL = f"https://{API_HOST}"

WORLD_CUP_ID = 1
CURRENT_SEASON = 2026


def get_upcoming_fixtures():
    """Fetch World Cup fixtures for the next 7 days."""

    url = f"{BASE_URL}/fixtures"

    today = datetime.now().strftime("%Y-%m-%d")
    next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    params = {
        "league": WORLD_CUP_ID,
        "season": CURRENT_SEASON,
        "from": today,
        "to": next_week
    }

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching upcoming fixtures...")

    try:
        response = requests.get(url, headers=HEADERS,
                                params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        if data.get("errors"):
            print(f"[ERROR] API returned errors: {data['errors']}")
            return None

        results = data.get("results", 0)
        print(f"[OK] Fixtures returned: {results}")

        return data.get("response", [])

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to fetch fixtures: {e}")
        return None


def parse_fixtures(fixtures):
    """Structure fixture data into clean format."""

    if not fixtures:
        return []

    parsed = []

    for fixture in fixtures:
        f = fixture.get("fixture", {})
        teams = fixture.get("teams", {})

        parsed.append({
            "fixture_id": f.get("id"),
            "date": f.get("date"),
            "venue": f.get("venue", {}).get("name", "Unknown"),
            "home_team": teams.get("home", {}).get("name"),
            "away_team": teams.get("away", {}).get("name"),
            "home_team_id": teams.get("home", {}).get("id"),
            "away_team_id": teams.get("away", {}).get("id"),
            "status": f.get("status", {}).get("long")
        })

    return parsed


def display_fixtures(fixtures):
    """Print fixtures to terminal."""

    if not fixtures:
        print("\n[INFO] No upcoming fixtures found.")
        return

    print(f"\n{'='*65}")
    print(f"  FIFA WORLD CUP 2026 — NEXT {len(fixtures)} FIXTURES")
    print(f"  Fetched: {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'='*65}")

    for i, fix in enumerate(fixtures, 1):
        print(f"\n  [{i}] {fix['home_team']} vs {fix['away_team']}")
        print(f"      Date:   {fix['date']}")
        print(f"      Venue:  {fix['venue']}")
        print(f"      Status: {fix['status']}")

    print(f"\n{'='*65}\n")


if __name__ == "__main__":
    raw = get_upcoming_fixtures()
    fixtures = parse_fixtures(raw)
    display_fixtures(fixtures)
