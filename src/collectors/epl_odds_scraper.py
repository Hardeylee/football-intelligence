"""
EPL Odds Scraper — SportyBet Nigeria
Pulls live odds for Premier League matches including:
- 1X2, Over/Under 1.5/2.5/3.5, BTTS, Double Chance
Uses the same internal API endpoint as the World Cup scraper.
"""

import requests
import json
import os
from datetime import datetime

# Map SportyBet team names to football-data.co.uk canonical names
SPORTYBET_NAME_MAP = {
    "Man Utd":          "Man United",
    "Manchester Utd":   "Man United",
    "Manchester United": "Man United",
    "Man City":         "Man City",
    "Manchester City":  "Man City",
    "Nottingham Forest": "Nott'm Forest",
    "Nott'm Forest":    "Nott'm Forest",
    "Newcastle United": "Newcastle",
    "Newcastle Utd":    "Newcastle",
    "Leeds United":     "Leeds",
    "Ipswich Town":     "Ipswich",
    "Sunderland AFC":   "Sunderland",
    "Wolverhampton":    "Wolves",
    "Wolverhampton Wanderers": "Wolves",
    "Tottenham Hotspur": "Tottenham",
    "West Ham United":  "West Ham",
    "Sheffield Utd":    "Sheffield United",
    "Coventry City":    "Coventry City",
    "Hull City":        "Hull City",
    "Brighton & Hove Albion": "Brighton",
    "Brighton & Hove":  "Brighton",
    "Aston Villa":      "Aston Villa",
    "Crystal Palace":   "Crystal Palace",
    "Bournemouth":      "Bournemouth",
    "Brentford":        "Brentford",
    "Fulham":           "Fulham",
    "Chelsea":          "Chelsea",
    "Arsenal":          "Arsenal",
    "Everton":          "Everton",
    "Liverpool":        "Liverpool",
}


def normalise_team_name(name: str) -> str:
    """Convert SportyBet team name to canonical football-data.co.uk format."""
    return SPORTYBET_NAME_MAP.get(name, name)


OUTPUT_FILE = "data/epl_odds.json"

API_URL = "https://www.sportybet.com/api/ng/factsCenter/wapConfigurableEventsByOrder"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.sportybet.com",
    "Referer": "https://www.sportybet.com/ng/",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Current-Country": "NG"
}

# Market IDs from SportyBet raw response inspection
MARKET_IDS = {
    "1":  "1x2",           # 1X2
    "18": "over_under",    # Total goals O/U
    "29": "btts",          # GG/NG (Both teams to score)
    "10": "double_chance",  # Double chance
}


def fetch_raw(page_size=100) -> dict:
    payload = {
        "productId": 3,
        "sportId": "sr:sport:1",
        "order": 0,
        "pageNum": 1,
        "pageSize": page_size,
        "withOneUpMarket": False,
        "withTwoUpMarket": False
    }
    try:
        response = requests.post(
            API_URL, headers=HEADERS, json=payload, timeout=15
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[ERROR] API call failed: {e}")
        return {}


def parse_markets(markets: list) -> dict:
    """
    Extract all relevant odds from a match's markets list.
    Returns dict matching club_value_detector's expected format.
    """
    odds = {
        "home_win":        None,
        "draw":            None,
        "away_win":        None,
        "home_or_draw":    None,
        "away_or_draw":    None,
        "over15":          None,
        "over25":          None,
        "over35":          None,
        "under15":         None,
        "under25":         None,
        "under35":         None,
        "btts_yes":        None,
        "btts_no":         None,
        "over35_cards":    None,
        "over45_cards":    None,
        "over85_corners":  None,
        "over105_corners": None,
    }

    for market in markets:
        mid = str(market.get("id", ""))
        specifier = market.get("specifier", "")
        outcomes = market.get("outcomes", [])
        is_active = market.get("status", 1) == 0  # 0 = active

        if not is_active:
            continue

        # ── 1X2 ──────────────────────────────────────────
        if mid == "1" and not specifier:
            for o in outcomes:
                try:
                    val = float(o.get("odds", 0))
                    desc = o.get("desc", "").lower()
                    oid = str(o.get("id", ""))
                    if oid == "1" or desc == "home":
                        odds["home_win"] = val
                    elif oid == "2" or desc == "draw":
                        odds["draw"] = val
                    elif oid == "3" or desc == "away":
                        odds["away_win"] = val
                except:
                    continue

        # ── OVER/UNDER GOALS ─────────────────────────────
        elif mid == "18":
            for o in outcomes:
                try:
                    val = float(o.get("odds", 0))
                    desc = o.get("desc", "").lower()
                    if "over 1.5" in desc:
                        odds["over15"] = val
                    elif "under 1.5" in desc:
                        odds["under15"] = val
                    elif "over 2.5" in desc:
                        odds["over25"] = val
                    elif "under 2.5" in desc:
                        odds["under25"] = val
                    elif "over 3.5" in desc:
                        odds["over35"] = val
                    elif "under 3.5" in desc:
                        odds["under35"] = val
                except:
                    continue

        # ── BTTS (GG/NG) ─────────────────────────────────
        elif mid == "29":
            for o in outcomes:
                try:
                    val = float(o.get("odds", 0))
                    desc = o.get("desc", "").lower()
                    oid = str(o.get("id", ""))
                    if oid == "74" or desc == "yes":
                        odds["btts_yes"] = val
                    elif oid == "76" or desc == "no":
                        odds["btts_no"] = val
                except:
                    continue

        # ── DOUBLE CHANCE ─────────────────────────────────
        elif mid == "10" and not specifier:
            for o in outcomes:
                try:
                    val = float(o.get("odds", 0))
                    desc = o.get("desc", "").lower()
                    oid = str(o.get("id", ""))
                    if oid == "9" or "home or draw" in desc:
                        odds["home_or_draw"] = val
                    elif oid == "11" or "draw or away" in desc:
                        odds["away_or_draw"] = val
                except:
                    continue

    return odds


def extract_epl_matches(data: dict) -> list:
    """Extract Premier League matches from raw API response."""
    matches = []
    tournaments = data.get("data", {}).get("tournaments", [])

    for t in tournaments:
        category = t.get("categoryName", "")
        t_name = t.get("name", "")

        # Filter to Premier League only
        if "Premier League" not in t_name or category != "England":
            continue

        for event in t.get("events", []):
            home = normalise_team_name(event.get("homeTeamName", ""))
            away = normalise_team_name(event.get("awayTeamName", ""))
            if not home or not away:
                continue

            # Skip live matches
            if event.get("matchStatus", "") not in ["", "Not start", 0, "0"]:
                continue

            start_ms = event.get("estimateStartTime", 0)
            kick_off = (
                datetime.fromtimestamp(
                    start_ms / 1000).strftime("%d %b %Y %H:%M")
                if start_ms else "TBC"
            )

            markets = event.get("markets", [])
            odds = parse_markets(markets)

            matches.append({
                "event_id":   event.get("eventId", ""),
                "home_team":  home,
                "away_team":  away,
                "kick_off":   kick_off,
                "odds":       odds,
                "has_1x2":    all([odds["home_win"], odds["draw"], odds["away_win"]]),
                "scraped_at": datetime.now().isoformat(),
            })

    return matches


def get_epl_odds() -> list:
    """Main function — fetch and return EPL odds."""
    raw = fetch_raw(page_size=100)
    if not raw:
        return []
    matches = extract_epl_matches(raw)
    return matches


def get_odds_for_match(home_team: str, away_team: str) -> dict:
    """
    Fetch live odds for a specific match.
    Used by the Telegram bot when user types 'Arsenal vs Chelsea'.
    Returns odds dict or None if match not found.
    """
    matches = get_epl_odds()

    home_lower = home_team.lower()
    away_lower = away_team.lower()

    for m in matches:
        if (home_lower in m["home_team"].lower() or
                m["home_team"].lower() in home_lower) and \
           (away_lower in m["away_team"].lower() or
                m["away_team"].lower() in away_lower):
            return m["odds"]

    return None


def save_odds(matches: list):
    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "scraped_at": datetime.now().isoformat(),
            "total": len(matches),
            "matches": matches
        }, f, indent=2)
    print(f"Saved {len(matches)} EPL matches → {OUTPUT_FILE}")


if __name__ == "__main__":
    print("Fetching EPL odds from SportyBet...\n")
    matches = get_epl_odds()

    if not matches:
        print("No EPL matches found. Either no matches today or API changed.")
    else:
        for m in matches:
            o = m["odds"]
            print(f"⚽ {m['home_team']} vs {m['away_team']} — {m['kick_off']}")
            print(
                f"   1X2:     {o['home_win']} / {o['draw']} / {o['away_win']}")
            print(
                f"   Over 1.5: {o['over15']}  Over 2.5: {o['over25']}  Over 3.5: {o['over35']}")
            print(f"   BTTS:     Yes {o['btts_yes']} / No {o['btts_no']}")
            print(
                f"   DC:       1X {o['home_or_draw']} / X2 {o['away_or_draw']}")
            print()
        save_odds(matches)
