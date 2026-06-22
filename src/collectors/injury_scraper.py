"""
Injury & Suspension Scraper — Sofascore API.

Scrapes current injury and suspension data for all 48 World Cup teams.
Used to adjust match predictions when key players are unavailable.
Free source — no API key needed.
"""

import requests
import json
import os
import time
from datetime import datetime

INJURIES_FILE = "data/injuries.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sofascore.com",
    "Origin": "https://www.sofascore.com",
}

# Sofascore national team IDs for all 48 World Cup 2026 nations
WORLD_CUP_TEAM_IDS = {
    # GROUP A
    "Mexico":               4703,
    "South Africa":         56966,
    "Ecuador":              4719,
    "Canada":               4723,
    # GROUP B
    "Qatar":                56969,
    "Bosnia and Herzegovina": 4688,
    "Switzerland":          4715,
    "Korea Republic":       4701,
    # GROUP C
    "Brazil":               4722,
    "Morocco":              56971,
    "Haiti":                56990,
    "Scotland":             4712,
    # GROUP D
    "United States":        4718,
    "Paraguay":             4725,
    "Australia":            4716,
    "Turkiye":              4692,
    # GROUP E
    "Germany":              4698,
    "Curacao":              56991,
    "Ivory Coast":          56965,
    "Albania":              4685,
    # GROUP F
    "Netherlands":          4705,
    "Japan":                4702,
    "Sweden":               4713,
    "Tunisia":              56973,
    # GROUP G
    "Belgium":              4687,
    "Egypt":                56967,
    "IR Iran":              4700,
    "New Zealand":          56987,
    # GROUP H
    "Spain":                4711,
    "Cape Verde":           56993,
    "Saudi Arabia":         56968,
    "Uruguay":              4726,
    # GROUP I
    "France":               4697,
    "Senegal":              56972,
    "Iraq":                 56979,
    "Norway":               4706,
    # GROUP J
    "Argentina":            4714,
    "Algeria":              56964,
    "Austria":              4686,
    "Jordan":               56980,
    # GROUP K
    "Portugal":             4709,
    "DR Congo":             56975,
    "Uzbekistan":           56996,
    "Colombia":             4720,
    # GROUP L
    "England":              4713,  # Will be corrected below
    "Czechia":              4689,
    "Nigeria":              56974,
    "Ghana":                56976,
    "Panama":               4724,
    "Jamaica":              56989,
    "Venezuela":            4727,
    "Honduras":             56986,
    "El Salvador":          56985,
    "Costa Rica":           4721,
    "Slovenia":             4710,
    "Slovakia":             4693,
    "Serbia":               4694,
    "Romania":              4690,
    "Poland":               4707,
    "Hungary":              4699,
    "Croatia":              4696,
    "Ukraine":              4695,
    "Denmark":              4691,
    "Greece":               4684,
}

# Correct England ID (Sweden above was wrong placeholder)
WORLD_CUP_TEAM_IDS["England"] = 4704
WORLD_CUP_TEAM_IDS["Sweden"] = 4713

# Player importance weights
GOALKEEPER_WEIGHT = 0.08
STAR_PLAYER_WEIGHT = 0.12
KEY_PLAYER_WEIGHT = 0.06
SQUAD_PLAYER_WEIGHT = 0.02

# Known star players per nation (expand as needed)
STAR_PLAYERS = {
    "Brazil":       ["Vinicius", "Rodrygo", "Endrick", "Alisson"],
    "France":       ["Mbappe", "Griezmann", "Camavinga"],
    "England":      ["Bellingham", "Saka", "Kane"],
    "Argentina":    ["Messi", "Martinez", "De Paul"],
    "Portugal":     ["Ronaldo", "Felix", "Cancelo"],
    "Spain":        ["Yamal", "Pedri", "Morata"],
    "Germany":      ["Musiala", "Wirtz", "Neuer"],
    "Netherlands":  ["Van Dijk", "Depay", "Gakpo"],
    "Belgium":      ["De Bruyne", "Lukaku", "Courtois"],
    "Morocco":      ["Ziyech", "En-Nesyri", "Hakimi"],
    "United States": ["Pulisic", "Reyna", "Turner"],
    "Mexico":       ["Lozano", "Jimenez", "Ochoa"],
    "Canada":       ["David", "Buchanan", "Johnston"],
    "Japan":        ["Mitoma", "Kubo", "Endo"],
    "Senegal":      ["Mane", "Sarr", "Mendy"],
    "Uruguay":      ["Valverde", "Nunez", "Suarez"],
    "Colombia":     ["James", "Diaz", "Cuesta"],
    "Norway":       ["Haaland", "Odegaard"],
    "Sweden":       ["Isak", "Kulusevski"],
    "Denmark":      ["Eriksen", "Hojlund"],
    "Croatia":      ["Modric", "Kovacic"],
    "Serbia":       ["Vlahovic", "Tadic"],
    "Switzerland":  ["Xhaka", "Embolo", "Sommer"],
    "Poland":       ["Lewandowski", "Szczesny"],
    "Ukraine":      ["Mudryk", "Zinchenko"],
    "Austria":      ["Alaba", "Arnautovic"],
    "Korea Republic": ["Son", "Kim Min-jae"],
    "Australia":    ["Leckie", "Irvine"],
    "Iran":         ["Taremi", "Azmoun"],
    "Tunisia":      ["Khazri", "Msakni"],
    "Egypt":        ["Salah", "El-Shenawy"],
    "Nigeria":      ["Osimhen", "Lookman"],
    "Ghana":        ["Kudus", "Ayew"],
    "South Africa": ["Percy Tau", "Zwane"],
    "Ivory Coast":  ["Zaha", "Haller", "Sangare"],
    "Senegal":      ["Mane", "Sarr", "Gueye"],
    "Saudi Arabia": ["Al-Dawsari", "Al-Shahrani"],
    "Iraq":         ["Ayman Hussein"],
    "Qatar":        ["Afif", "Al-Haydos"],
    "Ecuador":      ["Caicedo", "Valencia"],
    "Paraguay":     ["Sanabria", "Almiron"],
    "Venezuela":    ["Soteldo", "Rondon"],
    "Honduras":     ["Elis"],
    "Costa Rica":   ["Navas", "Campbell"],
    "Panama":       ["Davis", "Fajardo"],
}


def scrape_team_injuries(team_name: str, team_id: int) -> list:
    """
    Scrape injury and suspension data for one team from Sofascore.
    Returns list of dicts: {player, position, injury, impact, is_key_absence}
    """
    url = f"https://api.sofascore.com/api/v1/team/{team_id}/players"
    injuries = []

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)

        if response.status_code != 200:
            print(f"  [WARN] {team_name}: status {response.status_code}")
            return []

        data = response.json()
        players = data.get("players", [])

        star_names = STAR_PLAYERS.get(team_name, [])

        for entry in players:
            player_data = entry.get("player", {})
            player_name = player_data.get("name", "Unknown")
            position_raw = player_data.get("position", "")
            injury_status = entry.get("injuryStatus", None)

            if not injury_status:
                continue  # Skip healthy players

            # Map position codes
            position_map = {
                "G":  "Goalkeeper",
                "D":  "Defender",
                "M":  "Midfielder",
                "F":  "Forward",
                "GK": "Goalkeeper",
            }
            position = position_map.get(
                position_raw, position_raw or "Unknown")

            # Determine injury type label
            status_map = {
                "injured":   "Injured",
                "ill":       "Ill",
                "suspended": "Suspended",
                "doubt":     "Doubt",
                "missing":   "Missing",
            }
            injury_label = status_map.get(
                str(injury_status).lower(), str(injury_status)
            )

            # Injury reason (if available)
            injury_reason = player_data.get("injuryType", "")
            if injury_reason:
                injury_label = f"{injury_label} ({injury_reason})"

            # Calculate impact weight
            is_star = any(
                star.lower() in player_name.lower() for star in star_names
            )
            if position == "Goalkeeper":
                weight = GOALKEEPER_WEIGHT
            elif is_star:
                weight = STAR_PLAYER_WEIGHT
            else:
                weight = KEY_PLAYER_WEIGHT

            injuries.append({
                "player":        player_name,
                "position":      position,
                "injury":        injury_label,
                "impact":        weight,
                "is_key_absence": is_star or position == "Goalkeeper",
            })

    except Exception as e:
        print(f"  [ERROR] {team_name}: {e}")

    return injuries


def get_team_injuries(team_name: str, injury_data: dict) -> list:
    """Retrieve stored injuries for a team."""
    return injury_data.get(team_name, [])


def assess_injury_impact(team_name: str, injuries: list) -> tuple:
    """
    Returns (total_impact_float, key_absences_list).
    total_impact is summed probability shift (e.g. 0.18 = 18% weaker).
    """
    total = sum(i["impact"] for i in injuries)
    key = [i for i in injuries if i.get("is_key_absence")]
    return round(total, 3), key


def scrape_all_teams(delay: float = 2.0) -> dict:
    """Scrape injuries for all 48 World Cup teams. Returns full injury dict."""
    all_injuries = {}
    teams = list(WORLD_CUP_TEAM_IDS.items())

    print(f"Scraping injuries for {len(teams)} teams...\n")

    for i, (team_name, team_id) in enumerate(teams, 1):
        print(f"[{i}/{len(teams)}] {team_name}...", end=" ")
        injuries = scrape_team_injuries(team_name, team_id)
        all_injuries[team_name] = injuries
        count = len(injuries)
        print(f"{count} injured/suspended")
        if delay and i < len(teams):
            time.sleep(delay)

    return all_injuries


def save_injuries(injury_data: dict):
    """Save injury data to JSON file."""
    os.makedirs("data", exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(),
        "teams": injury_data,
    }
    with open(INJURIES_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nSaved to {INJURIES_FILE}")


def load_injuries() -> dict:
    """Load cached injury data."""
    if not os.path.exists(INJURIES_FILE):
        return {}
    with open(INJURIES_FILE) as f:
        data = json.load(f)
    return data.get("teams", {})


def enhance_prediction_with_injuries(prediction: dict, injury_data: dict) -> dict:
    """Adjust a match prediction dict with injury impact data."""
    home_team = prediction.get("home_team", "")
    away_team = prediction.get("away_team", "")

    home_injuries = get_team_injuries(home_team, injury_data)
    away_injuries = get_team_injuries(away_team, injury_data)

    home_impact, home_key = assess_injury_impact(home_team, home_injuries)
    away_impact, away_key = assess_injury_impact(away_team, away_injuries)

    probs = prediction.get("probabilities", {}).copy()

    # Shift home win probability down if home team has injuries
    if home_impact > 0:
        shift = min(home_impact, 0.15)
        probs["home_win"] = max(0.01, probs.get("home_win", 0.33) - shift)
        probs["away_win"] = min(0.99, probs.get(
            "away_win", 0.33) + shift * 0.6)
        probs["draw"] = min(0.99, probs.get("draw", 0.33) + shift * 0.4)

    # Shift away win probability down if away team has injuries
    if away_impact > 0:
        shift = min(away_impact, 0.15)
        probs["away_win"] = max(0.01, probs.get("away_win", 0.33) - shift)
        probs["home_win"] = min(0.99, probs.get(
            "home_win", 0.33) + shift * 0.6)
        probs["draw"] = min(0.99, probs.get("draw", 0.33) + shift * 0.4)

    # Renormalize
    total = sum(probs.values())
    if total > 0:
        probs = {k: round(v / total, 4) for k, v in probs.items()}

    enhanced = prediction.copy()
    enhanced["model_probability"] = probs
    enhanced["injury_data"] = {
        "home_injuries":    home_injuries,
        "home_key_absences": home_key,
        "home_impact":      home_impact,
        "away_injuries":    away_injuries,
        "away_key_absences": away_key,
        "away_impact":      away_impact,
        "adjusted":         home_impact > 0 or away_impact > 0,
    }

    return enhanced


def format_injury_report(home_team: str, away_team: str, injury_data: dict) -> str:
    """Format injury report string for Telegram."""
    home_injuries = get_team_injuries(home_team, injury_data)
    away_injuries = get_team_injuries(away_team, injury_data)

    _, home_key = assess_injury_impact(home_team, home_injuries)
    _, away_key = assess_injury_impact(away_team, away_injuries)

    lines = ["🏥 <b>INJURY REPORT</b>"]

    if home_key:
        lines.append(f"\n🔴 <b>{home_team} — Key Absences:</b>")
        for p in home_key[:3]:
            lines.append(f"  • {p['player']} ({p['position']}): {p['injury']}")
    elif home_injuries:
        lines.append(
            f"\n🟡 <b>{home_team}:</b> {len(home_injuries)} minor absences")
    else:
        lines.append(f"\n✅ <b>{home_team}:</b> Full squad available")

    if away_key:
        lines.append(f"\n🔴 <b>{away_team} — Key Absences:</b>")
        for p in away_key[:3]:
            lines.append(f"  • {p['player']} ({p['position']}): {p['injury']}")
    elif away_injuries:
        lines.append(
            f"\n🟡 <b>{away_team}:</b> {len(away_injuries)} minor absences")
    else:
        lines.append(f"\n✅ <b>{away_team}:</b> Full squad available")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing Sofascore injury scraper...\n")

    # Test single team first
    test_teams = [
        ("Switzerland", WORLD_CUP_TEAM_IDS["Switzerland"]),
        ("Canada",      WORLD_CUP_TEAM_IDS["Canada"]),
        ("England",     WORLD_CUP_TEAM_IDS["England"]),
    ]

    for team_name, team_id in test_teams:
        print(f"\n{'='*40}")
        print(f"  {team_name} (ID: {team_id})")
        print(f"{'='*40}")
        injuries = scrape_team_injuries(team_name, team_id)
        if injuries:
            for p in injuries:
                key_flag = " ⭐" if p["is_key_absence"] else ""
                print(
                    f"  ❌ {p['player']} ({p['position']}): {p['injury']}{key_flag}")
            impact, key = assess_injury_impact(team_name, injuries)
            print(f"\n  Impact: -{impact*100:.1f}% | Key absences: {len(key)}")
        else:
            print("  ✅ No injuries found")
