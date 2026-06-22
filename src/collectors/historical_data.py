"""
Historical Data Ingestion — football-data.co.uk
Loads EPL CSV files and builds team profile store.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime

RAW_DATA_DIR = "data/raw"
PROCESSED_FILE = "data/team_profiles.json"
MATCHES_FILE = "data/historical_matches.json"

# Columns we care about from football-data.co.uk CSVs
REQUIRED_COLS = [
    "Date", "HomeTeam", "AwayTeam",
    "FTHG", "FTAG", "FTR",        # Full time goals + result
    "HS", "AS",                    # Shots
    "HST", "AST",                  # Shots on target
    "HC", "AC",                    # Corners
    "HF", "AF",                    # Fouls
    "HY", "AY",                    # Yellow cards
    "HR", "AR",                    # Red cards
    "B365H", "B365D", "B365A",    # Bet365 odds (for reference)
]


def load_csv(filepath: str) -> list:
    """Load a single CSV file, return list of match dicts."""
    matches = []
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("HomeTeam") or not row.get("Date"):
                continue
            match = {}
            for col in REQUIRED_COLS:
                val = row.get(col, "")
                # Convert numeric fields
                if col in ["FTHG", "FTAG", "HS", "AS", "HST", "AST",
                           "HC", "AC", "HF", "AF", "HY", "AY", "HR", "AR"]:
                    try:
                        match[col] = int(float(val)) if val else 0
                    except:
                        match[col] = 0
                elif col in ["B365H", "B365D", "B365A"]:
                    try:
                        match[col] = float(val) if val else None
                    except:
                        match[col] = None
                else:
                    match[col] = val
            matches.append(match)
    return matches


def load_all_seasons() -> list:
    """Load all CSV files from data/raw/ directory."""
    all_matches = []
    if not os.path.exists(RAW_DATA_DIR):
        print(f"[ERROR] Directory not found: {RAW_DATA_DIR}")
        print("Create data/raw/ and place your CSV files there.")
        return []

    csv_files = [f for f in os.listdir(RAW_DATA_DIR) if f.endswith(".csv")]
    if not csv_files:
        print(f"[ERROR] No CSV files found in {RAW_DATA_DIR}")
        return []

    for filename in sorted(csv_files):
        filepath = os.path.join(RAW_DATA_DIR, filename)
        matches = load_csv(filepath)
        print(f"  Loaded {filename}: {len(matches)} matches")
        all_matches.extend(matches)

    print(f"\n  Total matches loaded: {len(all_matches)}")
    return all_matches


def build_team_profiles(matches: list) -> dict:
    """
    Build a profile for each team from historical match data.
    Returns dict of team_name -> profile stats.
    """
    # Accumulate raw stats per team
    stats = defaultdict(lambda: {
        "matches": 0,
        "wins": 0, "draws": 0, "losses": 0,
        "goals_scored": 0, "goals_conceded": 0,
        "home_matches": 0, "home_wins": 0,
        "home_goals_scored": 0, "home_goals_conceded": 0,
        "away_matches": 0, "away_wins": 0,
        "away_goals_scored": 0, "away_goals_conceded": 0,
        "yellow_cards": 0, "red_cards": 0,
        "fouls_committed": 0,
        "corners_for": 0, "corners_against": 0,
        "shots_for": 0, "shots_against": 0,
        "clean_sheets": 0,
        "btts_count": 0,           # Both teams scored
        "over25_count": 0,         # Match had 3+ goals
        "over15_count": 0,         # Match had 2+ goals
        "recent_form": [],         # Last 6 results W/D/L
    })

    # Sort by date so recent_form is accurate
    def parse_date(d):
        for fmt in ["%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"]:
            try:
                return datetime.strptime(d, fmt)
            except:
                continue
        return datetime.min

    matches_sorted = sorted(matches, key=lambda m: parse_date(m["Date"]))

    for m in matches_sorted:
        home = m["HomeTeam"]
        away = m["AwayTeam"]
        hg = m["FTHG"]
        ag = m["FTAG"]
        result = m["FTR"]  # H/D/A

        total_goals = hg + ag
        btts = hg > 0 and ag > 0

        # --- HOME TEAM ---
        s = stats[home]
        s["matches"] += 1
        s["home_matches"] += 1
        s["goals_scored"] += hg
        s["goals_conceded"] += ag
        s["home_goals_scored"] += hg
        s["home_goals_conceded"] += ag
        s["yellow_cards"] += m["HY"]
        s["red_cards"] += m["HR"]
        s["fouls_committed"] += m["HF"]
        s["corners_for"] += m["HC"]
        s["corners_against"] += m["AC"]
        s["shots_for"] += m["HS"]
        s["shots_against"] += m["AS"]
        if ag == 0:
            s["clean_sheets"] += 1
        if btts:
            s["btts_count"] += 1
        if total_goals > 2.5:
            s["over25_count"] += 1
        if total_goals > 1.5:
            s["over15_count"] += 1
        if result == "H":
            s["wins"] += 1
            s["home_wins"] += 1
            s["recent_form"].append("W")
        elif result == "D":
            s["draws"] += 1
            s["recent_form"].append("D")
        else:
            s["losses"] += 1
            s["recent_form"].append("L")

        # --- AWAY TEAM ---
        s = stats[away]
        s["matches"] += 1
        s["away_matches"] += 1
        s["goals_scored"] += ag
        s["goals_conceded"] += hg
        s["away_goals_scored"] += ag
        s["away_goals_conceded"] += hg
        s["yellow_cards"] += m["AY"]
        s["red_cards"] += m["AR"]
        s["fouls_committed"] += m["AF"]
        s["corners_for"] += m["AC"]
        s["corners_against"] += m["HC"]
        s["shots_for"] += m["AS"]
        s["shots_against"] += m["HS"]
        if hg == 0:
            s["clean_sheets"] += 1
        if btts:
            s["btts_count"] += 1
        if total_goals > 2.5:
            s["over25_count"] += 1
        if total_goals > 1.5:
            s["over15_count"] += 1
        if result == "A":
            s["wins"] += 1
            s["away_wins"] += 1
            s["recent_form"].append("W")
        elif result == "D":
            s["draws"] += 1
            s["recent_form"].append("D")
        else:
            s["losses"] += 1
            s["recent_form"].append("L")

    # Build final profiles with averages
    profiles = {}
    for team, s in stats.items():
        n = s["matches"]
        if n == 0:
            continue
        profiles[team] = {
            "matches_played": n,
            "win_rate":       round(s["wins"] / n, 3),
            "draw_rate":      round(s["draws"] / n, 3),
            "loss_rate":      round(s["losses"] / n, 3),

            # Goals
            "avg_goals_scored":    round(s["goals_scored"] / n, 2),
            "avg_goals_conceded":  round(s["goals_conceded"] / n, 2),
            "avg_goals_total":     round((s["goals_scored"] + s["goals_conceded"]) / n, 2),
            "clean_sheet_rate":    round(s["clean_sheets"] / n, 3),
            "btts_rate":           round(s["btts_count"] / n, 3),
            "over15_rate":         round(s["over15_count"] / n, 3),
            "over25_rate":         round(s["over25_count"] / n, 3),

            # Home splits
            "home_matches": s["home_matches"],
            "home_win_rate": round(s["home_wins"] / s["home_matches"], 3) if s["home_matches"] else 0,
            "home_avg_goals_scored":   round(s["home_goals_scored"] / s["home_matches"], 2) if s["home_matches"] else 0,
            "home_avg_goals_conceded": round(s["home_goals_conceded"] / s["home_matches"], 2) if s["home_matches"] else 0,

            # Away splits
            "away_matches": s["away_matches"],
            "away_win_rate": round(s["away_wins"] / s["away_matches"], 3) if s["away_matches"] else 0,
            "away_avg_goals_scored":   round(s["away_goals_scored"] / s["away_matches"], 2) if s["away_matches"] else 0,
            "away_avg_goals_conceded": round(s["away_goals_conceded"] / s["away_matches"], 2) if s["away_matches"] else 0,

            # Discipline
            "avg_yellow_cards":   round(s["yellow_cards"] / n, 2),
            "avg_red_cards":      round(s["red_cards"] / n, 2),
            "avg_fouls":          round(s["fouls_committed"] / n, 2),

            # Set pieces
            "avg_corners_for":    round(s["corners_for"] / n, 2),
            "avg_corners_against": round(s["corners_against"] / n, 2),

            # Shots
            "avg_shots_for":      round(s["shots_for"] / n, 2),
            "avg_shots_against":  round(s["shots_against"] / n, 2),

            # Recent form (last 6)
            "recent_form":        s["recent_form"][-6:],
            "form_score":         round(
                sum(3 if r == "W" else 1 if r == "D" else 0
                    for r in s["recent_form"][-6:]) / 18, 3
            ),
        }

    return profiles


def build_h2h(matches: list) -> dict:
    """Build head-to-head record for every team pair."""
    h2h = defaultdict(lambda: {
        "matches": 0, "home_wins": 0, "away_wins": 0, "draws": 0,
        "avg_goals": 0.0, "btts_rate": 0.0, "goals_list": []
    })

    for m in matches:
        home = m["HomeTeam"]
        away = m["AwayTeam"]
        key = f"{home}_vs_{away}"
        hg, ag = m["FTHG"], m["FTAG"]

        h = h2h[key]
        h["matches"] += 1
        h["goals_list"].append(hg + ag)
        if m["FTR"] == "H":
            h["home_wins"] += 1
        elif m["FTR"] == "A":
            h["away_wins"] += 1
        else:
            h["draws"] += 1

    # Calculate averages
    result = {}
    for key, h in h2h.items():
        n = h["matches"]
        goals = h["goals_list"]
        result[key] = {
            "matches":    n,
            "home_wins":  h["home_wins"],
            "away_wins":  h["away_wins"],
            "draws":      h["draws"],
            "avg_goals":  round(sum(goals) / n, 2) if n else 0,
            "btts_rate":  round(sum(1 for g in goals if g > 0) / n, 2) if n else 0,
        }

    return result


def save_data(profiles: dict, matches: list, h2h: dict):
    """Save all processed data to JSON files."""
    os.makedirs("data", exist_ok=True)

    # Team profiles
    with open(PROCESSED_FILE, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "teams": profiles
        }, f, indent=2)
    print(f"  Saved team profiles → {PROCESSED_FILE}")

    # Historical matches
    with open(MATCHES_FILE, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "matches": matches
        }, f, indent=2)
    print(f"  Saved match history → {MATCHES_FILE}")

    # H2H
    h2h_file = "data/h2h.json"
    with open(h2h_file, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "h2h": h2h
        }, f, indent=2)
    print(f"  Saved H2H data      → {h2h_file}")


if __name__ == "__main__":
    print("=" * 50)
    print("  Football Data Ingestion")
    print("=" * 50)

    print("\n[1] Loading CSV files...")
    matches = load_all_seasons()

    if not matches:
        exit(1)

    print("\n[2] Building team profiles...")
    profiles = build_team_profiles(matches)
    print(f"  Built profiles for {len(profiles)} teams")

    print("\n[3] Building H2H records...")
    h2h = build_h2h(matches)
    print(f"  Built {len(h2h)} H2H records")

    print("\n[4] Saving data...")
    save_data(profiles, matches, h2h)

    print("\n[5] Sample — Arsenal profile:")
    if "Arsenal" in profiles:
        p = profiles["Arsenal"]
        print(f"  Avg goals scored:   {p['avg_goals_scored']}")
        print(f"  Avg goals conceded: {p['avg_goals_conceded']}")
        print(f"  BTTS rate:          {p['btts_rate']}")
        print(f"  Over 2.5 rate:      {p['over25_rate']}")
        print(f"  Avg yellow cards:   {p['avg_yellow_cards']}")
        print(f"  Recent form:        {p['recent_form']}")

    print("\nDone.")
