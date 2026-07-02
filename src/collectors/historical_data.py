"""
Historical Data Ingestion — football-data.co.uk
Loads EPL CSV files and builds team profile store.
Applies RECENCY WEIGHTING so recent seasons count more than older ones.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime

RAW_DATA_DIR = "data/raw"
PROCESSED_FILE = "data/team_profiles.json"
MATCHES_FILE = "data/historical_matches.json"

# Recency weights per season file — must sum to 1.0
# More recent seasons weighted higher
SEASON_WEIGHTS = {
    "22-23.csv": 0.10,  # 3 seasons ago — least relevant
    "23-24.csv": 0.20,  # 2 seasons ago
    "24-25.csv": 0.30,  # Last season
    "25-26.csv": 0.40,  # Most recent — highest weight
}

REQUIRED_COLS = [
    "Date", "HomeTeam", "AwayTeam",
    "FTHG", "FTAG", "FTR",
    "HS", "AS", "HST", "AST",
    "HC", "AC", "HF", "AF",
    "HY", "AY", "HR", "AR",
    "B365H", "B365D", "B365A",
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
    """Load all CSV files, tagging each match with its season weight."""
    all_matches = []

    if not os.path.exists(RAW_DATA_DIR):
        print(f"[ERROR] Directory not found: {RAW_DATA_DIR}")
        return []

    csv_files = [
        f for f in os.listdir(RAW_DATA_DIR)
        if f.endswith(".csv") and not f.startswith("xg")
    ]

    if not csv_files:
        print(f"[ERROR] No CSV files found in {RAW_DATA_DIR}")
        return []

    for filename in sorted(csv_files):
        filepath = os.path.join(RAW_DATA_DIR, filename)
        weight = SEASON_WEIGHTS.get(filename, 0.25)
        matches = load_csv(filepath)

        # Tag each match with season and weight
        for m in matches:
            m["_season"] = filename.replace(".csv", "")
            m["_weight"] = weight

        print(
            f"  Loaded {filename}: {len(matches)} matches (weight: {weight})")
        all_matches.extend(matches)

    print(f"\n  Total matches loaded: {len(all_matches)}")
    return all_matches


def build_team_profiles(matches: list) -> dict:
    """
    Build a profile for each team using recency-weighted match data.
    Each match contributes proportionally to its season weight.
    """
    stats = defaultdict(lambda: {
        # Weighted accumulators
        "w_total":        0.0,
        "w_wins":         0.0,
        "w_draws":        0.0,
        "w_losses":       0.0,
        "w_goals_scored": 0.0,
        "w_goals_conceded": 0.0,
        "w_home_total":   0.0,
        "w_home_wins":    0.0,
        "w_home_goals_scored":   0.0,
        "w_home_goals_conceded": 0.0,
        "w_away_total":   0.0,
        "w_away_wins":    0.0,
        "w_away_goals_scored":   0.0,
        "w_away_goals_conceded": 0.0,
        "w_yellow_cards": 0.0,
        "w_red_cards":    0.0,
        "w_fouls":        0.0,
        "w_corners_for":  0.0,
        "w_corners_against": 0.0,
        "w_shots_for":    0.0,
        "w_shots_against": 0.0,
        "w_clean_sheets": 0.0,
        "w_btts":         0.0,
        "w_over25":       0.0,
        "w_over15":       0.0,
        "w_home_yellow_cards":    0.0,
        "w_away_yellow_cards":    0.0,
        "w_home_corners_for":     0.0,
        "w_home_corners_against": 0.0,
        "w_away_corners_for":     0.0,
        "w_away_corners_against": 0.0,
        # Recent form (unweighted — last 6 actual matches)
        "recent_form":    [],
        "recent_matches": 0,
    })

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
        result = m["FTR"]
        w = m.get("_weight", 0.25)  # Season weight

        total = hg + ag
        btts = hg > 0 and ag > 0

        # ── HOME TEAM ──────────────────────────────────────
        s = stats[home]
        s["w_total"] += w
        s["w_home_total"] += w
        s["w_goals_scored"] += hg * w
        s["w_goals_conceded"] += ag * w
        s["w_home_goals_scored"] += hg * w
        s["w_home_goals_conceded"] += ag * w
        s["w_yellow_cards"] += m["HY"] * w
        s["w_red_cards"] += m["HR"] * w
        s["w_fouls"] += m["HF"] * w
        s["w_corners_for"] += m["HC"] * w
        s["w_corners_against"] += m["AC"] * w
        s["w_shots_for"] += m["HS"] * w
        s["w_shots_against"] += m["AS"] * w
        s["recent_matches"] += 1
        s["w_home_yellow_cards"] += m["HY"] * w
        s["w_home_corners_for"] += m["HC"] * w
        s["w_home_corners_against"] += m["AC"] * w

        if ag == 0:
            s["w_clean_sheets"] += w
        if btts:
            s["w_btts"] += w
        if total > 2.5:
            s["w_over25"] += w
        if total > 1.5:
            s["w_over15"] += w

        if result == "H":
            s["w_wins"] += w
            s["w_home_wins"] += w
            s["recent_form"].append("W")
        elif result == "D":
            s["w_draws"] += w
            s["recent_form"].append("D")
        else:
            s["w_losses"] += w
            s["recent_form"].append("L")

        # ── AWAY TEAM ──────────────────────────────────────
        s = stats[away]
        s["w_total"] += w
        s["w_away_total"] += w
        s["w_goals_scored"] += ag * w
        s["w_goals_conceded"] += hg * w
        s["w_away_goals_scored"] += ag * w
        s["w_away_goals_conceded"] += hg * w
        s["w_yellow_cards"] += m["AY"] * w
        s["w_red_cards"] += m["AR"] * w
        s["w_fouls"] += m["AF"] * w
        s["w_corners_for"] += m["AC"] * w
        s["w_corners_against"] += m["HC"] * w
        s["w_shots_for"] += m["AS"] * w
        s["w_shots_against"] += m["HS"] * w
        s["recent_matches"] += 1
        s["w_away_yellow_cards"] += m["AY"] * w
        s["w_away_corners_for"] += m["AC"] * w
        s["w_away_corners_against"] += m["HC"] * w

        if hg == 0:
            s["w_clean_sheets"] += w
        if btts:
            s["w_btts"] += w
        if total > 2.5:
            s["w_over25"] += w
        if total > 1.5:
            s["w_over15"] += w

        if result == "A":
            s["w_wins"] += w
            s["w_away_wins"] += w
            s["recent_form"].append("W")
        elif result == "D":
            s["w_draws"] += w
            s["recent_form"].append("D")
        else:
            s["w_losses"] += w
            s["recent_form"].append("L")

    # Build final profiles with weighted averages
    profiles = {}
    for team, s in stats.items():
        wt = s["w_total"]
        wh = s["w_home_total"] or 0.001
        wa = s["w_away_total"] or 0.001

        if wt < 0.1:
            continue

        profiles[team] = {
            "matches_played": s["recent_matches"],
            "win_rate":       round(s["w_wins"] / wt, 3),
            "draw_rate":      round(s["w_draws"] / wt, 3),
            "loss_rate":      round(s["w_losses"] / wt, 3),

            # Goals
            "avg_goals_scored":    round(s["w_goals_scored"] / wt, 3),
            "avg_goals_conceded":  round(s["w_goals_conceded"] / wt, 3),
            "avg_goals_total":     round((s["w_goals_scored"] + s["w_goals_conceded"]) / wt, 3),
            "clean_sheet_rate":    round(s["w_clean_sheets"] / wt, 3),
            "btts_rate":           round(s["w_btts"] / wt, 3),
            "over15_rate":         round(s["w_over15"] / wt, 3),
            "over25_rate":         round(s["w_over25"] / wt, 3),

            # Home splits
            "home_matches":            int(s["recent_matches"] / 2),
            "home_win_rate":           round(s["w_home_wins"] / wh, 3),
            "home_avg_goals_scored":   round(s["w_home_goals_scored"] / wh, 3),
            "home_avg_goals_conceded": round(s["w_home_goals_conceded"] / wh, 3),

            # Away splits
            "away_matches":            int(s["recent_matches"] / 2),
            "away_win_rate":           round(s["w_away_wins"] / wa, 3),
            "away_avg_goals_scored":   round(s["w_away_goals_scored"] / wa, 3),
            "away_avg_goals_conceded": round(s["w_away_goals_conceded"] / wa, 3),

            # Discipline
            "avg_yellow_cards":   round(s["w_yellow_cards"] / wt, 3),
            "avg_red_cards":      round(s["w_red_cards"] / wt, 3),
            "avg_fouls":          round(s["w_fouls"] / wt, 3),

            # Set pieces
            "avg_corners_for":    round(s["w_corners_for"] / wt, 3),
            "avg_corners_against": round(s["w_corners_against"] / wt, 3),

            # Shots
            "avg_shots_for":      round(s["w_shots_for"] / wt, 3),
            "avg_shots_against":  round(s["w_shots_against"] / wt, 3),

            # Recent form (last 6 actual matches)
            "recent_form":  s["recent_form"][-6:],
            "form_score":   round(
                sum(3 if r == "W" else 1 if r == "D" else 0
                    for r in s["recent_form"][-6:]) / 18, 3
            ),
        }

    return profiles


def build_h2h(matches: list) -> dict:
    """Build head-to-head record for every team pair."""
    h2h = defaultdict(lambda: {
        "matches": 0, "home_wins": 0, "away_wins": 0, "draws": 0,
        "goals_list": []
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

    result = {}
    for key, h in h2h.items():
        n = h["matches"]
        goals = h["goals_list"]
        result[key] = {
            "matches":   n,
            "home_wins": h["home_wins"],
            "away_wins": h["away_wins"],
            "draws":     h["draws"],
            "avg_goals": round(sum(goals) / n, 2) if n else 0,
            "btts_rate": round(sum(1 for g in goals if g > 0) / n, 2) if n else 0,
        }

    return result


def save_data(profiles: dict, matches: list, h2h: dict):
    """Save all processed data to JSON files."""
    os.makedirs("data", exist_ok=True)

    with open(PROCESSED_FILE, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "recency_weights": SEASON_WEIGHTS,
            "teams": profiles
        }, f, indent=2)
    print(f"  Saved team profiles → {PROCESSED_FILE}")

    with open(MATCHES_FILE, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "matches": matches
        }, f, indent=2)
    print(f"  Saved match history → {MATCHES_FILE}")

    h2h_file = "data/h2h.json"
    with open(h2h_file, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "h2h": h2h
        }, f, indent=2)
    print(f"  Saved H2H data      → {h2h_file}")


if __name__ == "__main__":
    print("=" * 50)
    print("  Football Data Ingestion — with Recency Weighting")
    print("=" * 50)
    print(f"\n  Season weights:")
    for season, w in SEASON_WEIGHTS.items():
        print(f"    {season}: {w*100:.0f}%")

    print("\n[1] Loading CSV files...")
    matches = load_all_seasons()

    if not matches:
        exit(1)

    print("\n[2] Building weighted team profiles...")
    profiles = build_team_profiles(matches)
    print(f"  Built profiles for {len(profiles)} teams")

    print("\n[3] Building H2H records...")
    h2h = build_h2h(matches)
    print(f"  Built {len(h2h)} H2H records")

    print("\n[4] Saving data...")
    save_data(profiles, matches, h2h)

    print("\n[5] Sample — Arsenal profile (recency weighted):")
    if "Arsenal" in profiles:
        p = profiles["Arsenal"]
        print(f"  Win rate:           {p['win_rate']}")
        print(f"  Avg goals scored:   {p['avg_goals_scored']}")
        print(f"  Avg goals conceded: {p['avg_goals_conceded']}")
        print(f"  BTTS rate:          {p['btts_rate']}")
        print(f"  Over 2.5 rate:      {p['over25_rate']}")
        print(f"  Avg yellow cards:   {p['avg_yellow_cards']}")
        print(f"  Home win rate:      {p['home_win_rate']}")
        print(f"  Recent form:        {p['recent_form']}")

    print("\nDone.")
