"""
Injury & Suspension Scraper — Transfermarkt.

Scrapes current injury and suspension data for all 48 World Cup teams.
Used to adjust match predictions when key players are unavailable.
Free source — no API key needed.
Updates daily from transfermarkt.com
"""

import requests
import json
import os
import time
from datetime import datetime
from bs4 import BeautifulSoup

INJURIES_FILE = "data/injuries.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.transfermarkt.com"
}

# Transfermarkt team IDs for all 48 World Cup 2026 nations
WORLD_CUP_TEAM_IDS = {
    # GROUP A
    "Mexico":           "164",
    "South Africa":     "576",
    "Korea Republic":   "466",
    "Czechia":          "89",
    # GROUP B
    "Canada":           "732",
    "Bosnia and Herzegovina": "608",
    "Qatar":            "781",
    "Switzerland":      "148",
    # GROUP C
    "Brazil":           "20",
    "Morocco":          "349",
    "Haiti":            "467",
    "Scotland":         "752",
    # GROUP D
    "United States":    "684",
    "Paraguay":         "318",
    "Australia":        "107",
    "Turkiye":          "768",
    # GROUP E
    "Germany":          "50",
    "Curacao":          "1067",
    "Ivory Coast":      "402",
    "Ecuador":          "749",
    # GROUP F
    "Netherlands":      "64",
    "Japan":            "412",
    "Sweden":           "86",
    "Tunisia":          "397",
    # GROUP G
    "Belgium":          "105",
    "Egypt":            "76",
    "IR Iran":          "209",
    "New Zealand":      "490",
    # GROUP H
    "Spain":            "157",
    "Cape Verde":       "794",
    "Saudi Arabia":     "523",
    "Uruguay":          "321",
    # GROUP I
    "France":           "23",
    "Senegal":          "444",
    "Iraq":             "252",
    "Norway":           "671",
    # GROUP J
    "Argentina":        "3437",
    "Algeria":          "341",
    "Austria":          "115",
    "Jordan":           "621",
    # GROUP K
    "Portugal":         "165",
    "DR Congo":         "474",
    "Uzbekistan":       "1025",
    "Colombia":         "410",
    # GROUP L
    "England":          "703",
    "Croatia":          "498",
    "Ghana":            "389",
    "Panama":           "766",
}

# Player importance tiers — how much does losing this player matter?
# We estimate based on position and assumed role
GOALKEEPER_WEIGHT = 0.08      # Losing starting GK = 8% probability shift
STAR_PLAYER_WEIGHT = 0.12     # Losing star = 12% shift
KEY_PLAYER_WEIGHT = 0.06      # Losing key player = 6% shift
SQUAD_PLAYER_WEIGHT = 0.02    # Losing squad player = 2% shift


def scrape_team_injuries(team_name, team_id):
    """
    Scrape injury and suspension data for one team from Transfermarkt.
    """
    url = f"https://www.transfermarkt.com/x/startseite/verein/{team_id}"

    # Use the injuries endpoint
    injuries_url = f"https://www.transfermarkt.com/x/verletzte-spieler/verein/{team_id}"

    try:
        response = requests.get(
            injuries_url,
            headers=HEADERS,
            timeout=15
        )

        if response.status_code != 200:
            # Try alternate URL format
            alt_url = f"https://www.transfermarkt.com/{team_name.lower().replace(' ', '-')}/kader/verein/{team_id}"
            response = requests.get(alt_url, headers=HEADERS, timeout=15)

        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.content, "lxml")
        injured_players = []

        # Find injury table
        injury_table = soup.find("table", {"class": "items"})
        if not injury_table:
            return []

        rows = injury_table.find_all("tr", {"class": ["odd", "even"]})

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            try:
                player_name = ""
                name_cell = row.find("td", {"class": "hauptlink"})
                if name_cell:
                    player_name = name_cell.get_text(strip=True)

                position = cells[1].get_text(
                    strip=True) if len(cells) > 1 else ""
                injury_type = cells[3].get_text(
                    strip=True) if len(cells) > 3 else ""
                return_date = cells[4].get_text(
                    strip=True) if len(cells) > 4 else "Unknown"

                if player_name:
                    injured_players.append({
                        "player": player_name,
                        "position": position,
                        "injury": injury_type,
                        "return_date": return_date
                    })

            except Exception:
                continue

        return injured_players

    except Exception as e:
        print(f"  [INJURY] Error scraping {team_name}: {e}")
        return []


def load_injuries():
    """Load cached injury data."""
    if os.path.exists(INJURIES_FILE):
        with open(INJURIES_FILE) as f:
            data = json.load(f)
        # Check if data is fresh (less than 24 hours old)
        updated = datetime.fromisoformat(data.get("updated_at", "2000-01-01"))
        age_hours = (datetime.now() - updated).total_seconds() / 3600
        if age_hours < 24:
            print(f"[INJURY] Using cached data ({age_hours:.1f}h old)")
            return data.get("teams", {})
        else:
            print(
                f"[INJURY] Cache expired ({age_hours:.1f}h old) — refreshing")

    return None


def save_injuries(injury_data):
    """Save injury data to cache file."""
    os.makedirs("data", exist_ok=True)
    with open(INJURIES_FILE, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "total_teams": len(injury_data),
            "teams": injury_data
        }, f, indent=2)
    print(
        f"[INJURY] Saved data for {len(injury_data)} teams → {INJURIES_FILE}")


def fetch_all_injuries(force_refresh=False):
    """
    Fetch injury data for all 48 World Cup teams.
    Uses cache if fresh, otherwise scrapes Transfermarkt.
    """
    if not force_refresh:
        cached = load_injuries()
        if cached:
            return cached

    print(f"\n[INJURY] Scraping Transfermarkt for all 48 teams...")
    print(f"[INJURY] This takes ~2 minutes (rate limiting to avoid blocks)\n")

    injury_data = {}

    for i, (team, team_id) in enumerate(WORLD_CUP_TEAM_IDS.items(), 1):
        print(f"  [{i:2}/{len(WORLD_CUP_TEAM_IDS)}] {team}...", end=" ")

        injuries = scrape_team_injuries(team, team_id)
        injury_data[team] = injuries

        if injuries:
            print(f"{len(injuries)} injured/suspended")
        else:
            print("none found")

        # Rate limiting — be respectful to avoid IP block
        time.sleep(2.5)

    save_injuries(injury_data)
    return injury_data


def get_team_injuries(team_name, injury_data):
    """Get injuries for a specific team, handling name variations."""
    if team_name in injury_data:
        return injury_data[team_name]

    # Try alternate names
    alt_names = {
        "USA": "United States",
        "Korea Republic": "Korea Republic",
        "IR Iran": "IR Iran",
        "Congo DR": "DR Congo",
        "Bosnia & Herzegovina": "Bosnia and Herzegovina",
        "Turkiye": "Turkiye",
    }
    alt = alt_names.get(team_name)
    if alt and alt in injury_data:
        return injury_data[alt]

    return []


def assess_injury_impact(team_name, injuries):
    """
    Assess how much injuries affect team strength.
    Returns probability adjustment (negative = team weakened).
    """
    if not injuries:
        return 0.0, []

    impact = 0.0
    key_absences = []

    # Position importance weights
    position_weights = {
        "goalkeeper": GOALKEEPER_WEIGHT,
        "centre-back": KEY_PLAYER_WEIGHT,
        "central midfield": KEY_PLAYER_WEIGHT,
        "attacking midfield": STAR_PLAYER_WEIGHT,
        "centre-forward": STAR_PLAYER_WEIGHT,
        "left winger": KEY_PLAYER_WEIGHT,
        "right winger": KEY_PLAYER_WEIGHT,
        "left-back": SQUAD_PLAYER_WEIGHT,
        "right-back": SQUAD_PLAYER_WEIGHT,
        "defensive midfield": KEY_PLAYER_WEIGHT,
    }

    for injury in injuries[:5]:  # Cap at 5 most impactful
        position = injury.get("position", "").lower()
        player = injury.get("player", "")
        weight = SQUAD_PLAYER_WEIGHT

        for pos_key, pos_weight in position_weights.items():
            if pos_key in position:
                weight = pos_weight
                break

        impact += weight

        if weight >= KEY_PLAYER_WEIGHT:
            key_absences.append({
                "player": player,
                "position": injury.get("position", ""),
                "injury": injury.get("injury", ""),
                "return_date": injury.get("return_date", "Unknown"),
                "impact_weight": weight
            })

    # Cap total impact at 25%
    impact = min(impact, 0.25)
    return round(impact, 4), key_absences


def apply_injury_adjustments(prediction, home_team, away_team, injury_data):
    """
    Apply injury adjustments to base prediction probabilities.
    Returns enhanced prediction with injury context.
    """
    home_injuries = get_team_injuries(home_team, injury_data)
    away_injuries = get_team_injuries(away_team, injury_data)

    home_impact, home_key = assess_injury_impact(home_team, home_injuries)
    away_impact, away_key = assess_injury_impact(away_team, away_injuries)

    probs = prediction["model_probability"].copy()

    # Apply adjustments
    # If home team has injuries, reduce their win probability
    # and redistribute to draw and away
    if home_impact > 0:
        reduction = home_impact * probs["home"] / 100
        probs["home"] = round(probs["home"] - reduction * 100, 2)
        probs["draw"] = round(probs["draw"] + reduction * 50, 2)
        probs["away"] = round(probs["away"] + reduction * 50, 2)

    if away_impact > 0:
        reduction = away_impact * probs["away"] / 100
        probs["away"] = round(probs["away"] - reduction * 100, 2)
        probs["draw"] = round(probs["draw"] + reduction * 50, 2)
        probs["home"] = round(probs["home"] + reduction * 50, 2)

    # Normalize
    total = probs["home"] + probs["draw"] + probs["away"]
    probs["home"] = round(probs["home"] / total * 100, 2)
    probs["draw"] = round(probs["draw"] / total * 100, 2)
    probs["away"] = round(100 - probs["home"] - probs["draw"], 2)

    enhanced = prediction.copy()
    enhanced["model_probability"] = probs
    enhanced["injury_data"] = {
        "home_injuries": home_injuries,
        "home_key_absences": home_key,
        "home_impact": home_impact,
        "away_injuries": away_injuries,
        "away_key_absences": away_key,
        "away_impact": away_impact,
        "adjusted": home_impact > 0 or away_impact > 0
    }

    return enhanced


def format_injury_report(home_team, away_team, injury_data):
    """Format injury report for Telegram."""
    home_injuries = get_team_injuries(home_team, injury_data)
    away_injuries = get_team_injuries(away_team, injury_data)

    _, home_key = assess_injury_impact(home_team, home_injuries)
    _, away_key = assess_injury_impact(away_team, away_injuries)

    lines = ["🏥 <b>INJURY REPORT</b>"]

    if home_key:
        lines.append(f"\n🔴 <b>{home_team} — Key Absences:</b>")
        for p in home_key[:3]:
            lines.append(
                f"  ❌ {p['player']} ({p['position']})\n"
                f"     {p['injury']} — Return: {p['return_date']}"
            )
    else:
        lines.append(f"\n✅ <b>{home_team}</b> — No major absences")

    if away_key:
        lines.append(f"\n🔴 <b>{away_team} — Key Absences:</b>")
        for p in away_key[:3]:
            lines.append(
                f"  ❌ {p['player']} ({p['position']})\n"
                f"     {p['injury']} — Return: {p['return_date']}"
            )
    else:
        lines.append(f"\n✅ <b>{away_team}</b> — No major absences")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    force = "--refresh" in sys.argv
    data = fetch_all_injuries(force_refresh=force)

    print(f"\n=== INJURY SUMMARY ===")
    teams_with_injuries = {
        t: injuries for t, injuries in data.items() if injuries
    }
    print(f"Teams with injuries: {len(teams_with_injuries)}/{len(data)}")

    for team, injuries in teams_with_injuries.items():
        impact, key = assess_injury_impact(team, injuries)
        if key:
            print(f"\n{team} (impact: -{impact*100:.1f}%):")
            for p in key[:2]:
                print(f"  ❌ {p['player']} — {p['injury']}")
