import requests
import json
import os
from datetime import datetime

OUTPUT_FILE = "data/sportybet_odds.json"

API_URL = "https://www.sportybet.com/api/ng/factsCenter/wapConfigurableEventsByOrder"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.sportybet.com",
    "Referer": "https://www.sportybet.com/ng/",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Current-Country": "NG"
}

# World Cup tournament ID discovered from DevTools
WORLD_CUP_TOURNAMENT_ID = "sr:tournament:16"


def fetch_sportybet_odds(page_num=1, page_size=50):
    """
    Call SportyBet's internal API directly.
    Payload structure discovered via DevTools network inspection.
    """
    payload = {
        "productId": 3,
        "sportId": "sr:sport:1",
        "order": 0,
        "pageNum": page_num,
        "pageSize": page_size,
        "withOneUpMarket": True,
        "withTwoUpMarket": True
    }

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Calling SportyBet API...")

    try:
        response = requests.post(
            API_URL,
            headers=HEADERS,
            json=payload,
            timeout=15
        )
        response.raise_for_status()
        data = response.json()

        # Save raw response for inspection
        os.makedirs("data", exist_ok=True)
        with open("data/sportybet_raw.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"[OK] Raw response saved → data/sportybet_raw.json")

        return data

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] API call failed: {e}")
        return None


def parse_matches(data):
    """Parse SportyBet API response into clean match objects."""

    if not data:
        return []

    biz_code = data.get("bizCode")
    if biz_code != 10000:
        print(
            f"[ERROR] API returned bizCode {biz_code}: {data.get('message')}")
        return []

    matches = []
    tournaments = data.get("data", {}).get("tournaments", [])

    print(f"[OK] Tournaments found: {len(tournaments)}")

    for tournament in tournaments:
        tournament_name = tournament.get("name", "Unknown")
        events = tournament.get("events", [])

        print(f"  → {tournament_name}: {len(events)} events")

        for event in events:
            try:
                match = parse_event(event, tournament_name)
                if match:
                    matches.append(match)
            except Exception as e:
                continue

    return matches


def parse_event(event, tournament_name):
    """Parse a single event from SportyBet API."""

    # Basic match info
    event_id = event.get("eventId", "")
    game_id = event.get("gameId", "")
    status = event.get("matchStatus", "")

    # Skip live matches for now (focus on pre-match value)
    # status 0 = Not started, which is what we want

    home_team = event.get("homeTeamName", "")
    away_team = event.get("awayTeamName", "")

    if not home_team or not away_team:
        return None

    # Kick-off time (Unix timestamp in milliseconds)
    start_time_ms = event.get("estimateStartTime", 0)
    if start_time_ms:
        kick_off = datetime.fromtimestamp(
            start_time_ms / 1000).strftime("%d %b %Y %H:%M")
    else:
        kick_off = "TBC"

    # Extract 1X2 odds from markets
    home_odds = draw_odds = away_odds = None

    markets = event.get("markets", []) or event.get("oddsMap", []) or []

    # Try to find 1X2 market
    for market in markets:
        market_id = str(market.get("id", "") or market.get("marketId", ""))

        # 1X2 market is usually market ID 1 or "1_1"
        if market_id in ["1", "1_1", "sr:market:1"]:
            outcomes = market.get("outcomes", []) or market.get("odds", [])
            for outcome in outcomes:
                outcome_type = str(outcome.get("id", "")
                                   or outcome.get("type", ""))
                odds_val = outcome.get("odds") or outcome.get(
                    "price") or outcome.get("value")

                if odds_val:
                    try:
                        odds_val = float(odds_val)
                        # Outcome IDs: 1=home, 2=draw, 3=away (varies by bookmaker)
                        if outcome_type in ["1", "home"]:
                            home_odds = odds_val
                        elif outcome_type in ["2", "draw", "x"]:
                            draw_odds = odds_val
                        elif outcome_type in ["3", "away"]:
                            away_odds = odds_val
                    except:
                        continue

    # If market parsing didn't work, try direct odds fields
    if not all([home_odds, draw_odds, away_odds]):
        home_odds = event.get("homeOdds") or event.get("home_odds")
        draw_odds = event.get("drawOdds") or event.get("draw_odds")
        away_odds = event.get("awayOdds") or event.get("away_odds")

    # Build match object even without odds — useful for fixture tracking
    match = {
        "event_id": event_id,
        "game_id": game_id,
        "competition": tournament_name,
        "home_team": home_team,
        "away_team": away_team,
        "kick_off": kick_off,
        "status": status,
        "source": "SportyBet Nigeria",
        "scraped_at": datetime.now().isoformat(),
        "odds": None,
        "implied_probability": None,
        "bookmaker_margin": None,
        "has_odds": False
    }

    if all([home_odds, draw_odds, away_odds]):
        try:
            home_odds = float(home_odds)
            draw_odds = float(draw_odds)
            away_odds = float(away_odds)

            impl_home = round(1 / home_odds * 100, 2)
            impl_draw = round(1 / draw_odds * 100, 2)
            impl_away = round(1 / away_odds * 100, 2)
            margin = round(impl_home + impl_draw + impl_away, 2)

            match["odds"] = {
                "home": home_odds,
                "draw": draw_odds,
                "away": away_odds
            }
            match["implied_probability"] = {
                "home": impl_home,
                "draw": impl_draw,
                "away": impl_away
            }
            match["bookmaker_margin"] = margin
            match["has_odds"] = True
        except:
            pass

    return match


def display_matches(matches):
    if not matches:
        print("\n[INFO] No matches parsed.")
        print("[INFO] Check data/sportybet_raw.json to inspect API response structure.")
        return

    with_odds = [m for m in matches if m["has_odds"]]
    without_odds = [m for m in matches if not m["has_odds"]]

    print(f"\n{'='*65}")
    print(f"  SPORTYBET NIGERIA — LIVE ODDS")
    print(f"  Scraped: {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"  Matches with odds: {len(with_odds)} / {len(matches)}")
    print(f"{'='*65}")

    if with_odds:
        for i, match in enumerate(with_odds, 1):
            print(f"\n  [{i}] {match['home_team']} vs {match['away_team']}")
            print(f"      Competition: {match['competition']}")
            print(f"      Kick-off:    {match['kick_off']}")
            print(f"      Status:      {match['status']}")
            print(f"      Odds     →   Home: {match['odds']['home']}  "
                  f"Draw: {match['odds']['draw']}  "
                  f"Away: {match['odds']['away']}")
            print(f"      Implied  →   Home: {match['implied_probability']['home']}%  "
                  f"Draw: {match['implied_probability']['draw']}%  "
                  f"Away: {match['implied_probability']['away']}%")
            print(f"      Margin:      {match['bookmaker_margin']}%")
    else:
        print("\n  Matches found but odds not parsed yet.")
        print("  Check data/sportybet_raw.json for the odds structure.")
        print("\n  Matches found:")
        for i, match in enumerate(matches[:10], 1):
            print(
                f"  [{i}] {match['home_team']} vs {match['away_team']} — {match['kick_off']}")

    print(f"\n{'='*65}")
    print(f"  Total matches: {len(matches)}")
    print(f"{'='*65}\n")


def save_matches(matches):
    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "scraped_at": datetime.now().isoformat(),
            "total": len(matches),
            "with_odds": len([m for m in matches if m["has_odds"]]),
            "matches": matches
        }, f, indent=2)
    print(f"[SAVED] {len(matches)} matches → {OUTPUT_FILE}")


def main():
    raw_data = fetch_sportybet_odds(page_size=50)
    matches = parse_matches(raw_data)
    display_matches(matches)
    if matches:
        save_matches(matches)


if __name__ == "__main__":
    main()
