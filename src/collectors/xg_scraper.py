"""
xG Data Loader — Understat CSV files
Loads season-level xG data for EPL teams from manually downloaded CSVs.
Files downloaded from understat.com/league/EPL
Format: semicolon-separated with columns:
number;team;matches;wins;draws;loses;goals;ga;points;xG;xGA;xPTS

Promoted teams use Championship xG data with a 20% EPL adjustment.
"""

import csv
import json
import math
import os
from datetime import datetime
from collections import defaultdict

RAW_XG_DIR = "data/raw/xg"
OUTPUT_FILE = "data/xg_profiles.json"

TEAM_NAME_MAP = {
    "Manchester City":           "Man City",
    "Manchester United":         "Man United",
    "Arsenal":                   "Arsenal",
    "Chelsea":                   "Chelsea",
    "Liverpool":                 "Liverpool",
    "Tottenham":                 "Tottenham",
    "Aston Villa":               "Aston Villa",
    "Newcastle United":          "Newcastle",
    "Brighton":                  "Brighton",
    "West Ham":                  "West Ham",
    "Wolverhampton Wanderers":   "Wolves",
    "Nottingham Forest":         "Nott'm Forest",
    "Brentford":                 "Brentford",
    "Fulham":                    "Fulham",
    "Crystal Palace":            "Crystal Palace",
    "Everton":                   "Everton",
    "Bournemouth":               "Bournemouth",
    "Luton":                     "Luton",
    "Burnley":                   "Burnley",
    "Sheffield United":          "Sheffield United",
    "Southampton":               "Southampton",
    "Ipswich":                   "Ipswich",
    "Leicester":                 "Leicester",
    "Sunderland":                "Sunderland",
    "Leeds":                     "Leeds",
    "Leeds United":              "Leeds",
}

PROMOTION_DISCOUNT = 0.80

PROMOTED_TEAM_XG = {
    "Coventry City": {
        "raw_xg":            2.04,
        "raw_xga":           1.27,
        "matches":           46,
        "avg_goals_for":     2.11,
        "avg_goals_against": 0.98,
        "championship_season": "2025/26",
    },
    "Hull City": {
        "raw_xg":            1.67,
        "raw_xga":           1.64,
        "matches":           46,
        "avg_goals_for":     1.52,
        "avg_goals_against": 0.96,
        "championship_season": "2024/25",
    },
    "Sunderland": {
        "raw_xg":            1.65,
        "raw_xga":           1.33,
        "matches":           46,
        "avg_goals_for":     1.26,
        "avg_goals_against": 1.04,
        "championship_season": "2024/25",
    },
    "Ipswich": {
        "raw_xg":            1.45,
        "raw_xga":           1.20,
        "matches":           46,
        "avg_goals_for":     1.40,
        "avg_goals_against": 1.60,
        "championship_season": "2024/25 EPL (relegated) + discount",
    },
}


def load_xg_csv(filepath: str) -> list:
    rows = []
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                team_raw = row["team"].strip().strip('"')
                team = TEAM_NAME_MAP.get(team_raw, team_raw)
                matches = int(row["matches"])
                xg = float(row["xG"])
                xga = float(row["xGA"])
                goals = int(row["goals"])
                ga = int(row["ga"])

                rows.append({
                    "team":    team,
                    "matches": matches,
                    "xG":      xg,
                    "xGA":     xga,
                    "goals":   goals,
                    "ga":      ga,
                    "avg_xg":  round(xg / matches, 3),
                    "avg_xga": round(xga / matches, 3),
                })
            except Exception:
                continue
    return rows


def derive_market_rates(avg_xg: float, avg_xga: float) -> dict:
    total_xg = avg_xg + avg_xga

    # BTTS: Poisson-grounded replacement for the old (avg_xg * avg_xga) / 2.0
    # formula, which had no statistical basis and pinned 26/27 EPL teams at
    # its 0.90 cap (mean 0.892, stdev 0.039 — see diagnose_btts_ceiling.py).
    # P(team scores >=1) and P(team concedes >=1) under independent Poisson
    # assumptions, multiplied together. This saturates below 1.0 on its own
    # as avg_xg/avg_xga grow, so no artificial cap is needed — but a 0.95
    # safety ceiling is kept for consistency with the other two rates below
    # and to guard against pathological input data.
    p_scores = 1 - math.exp(-avg_xg)
    p_concedes = 1 - math.exp(-avg_xga)
    btts_rate = p_scores * p_concedes

    return {
        "xg_over15_rate": round(min(total_xg / 3.0, 0.97), 3),
        "xg_over25_rate": round(min(total_xg / 5.0, 0.95), 3),
        "xg_btts_rate":   round(min(btts_rate, 0.95), 3),
    }


FORCE_OVERRIDE = ["Ipswich"]


def add_promoted_teams(profiles: dict) -> dict:
    for team, data in PROMOTED_TEAM_XG.items():
        if team in profiles and team not in FORCE_OVERRIDE:
            continue

        avg_xg = round(data["raw_xg"] * PROMOTION_DISCOUNT, 3)
        avg_xga = round(data["raw_xga"], 3)
        rates = derive_market_rates(avg_xg, avg_xga)

        profiles[team] = {
            "seasons":             1,
            "matches":             data["matches"],
            "avg_xg_for":          avg_xg,
            "avg_xg_against":      avg_xga,
            "avg_goals_for":       data["avg_goals_for"],
            "avg_goals_against":   data["avg_goals_against"],
            "xg_over15_rate":      rates["xg_over15_rate"],
            "xg_over25_rate":      rates["xg_over25_rate"],
            "xg_btts_rate":        rates["xg_btts_rate"],
            "source": (
                f"Championship {data['championship_season']} "
                f"+ {int((1-PROMOTION_DISCOUNT)*100)}% EPL attack adjustment "
                f"(xGA undiscounted)"
            ),
        }
        print(
            f"  + Promoted team added: {team:<20} "
            f"xG: {avg_xg} (raw: {data['raw_xg']}, discounted) | "
            f"xGA: {avg_xga} (raw, undiscounted)"
        )

    return profiles


def build_xg_profiles(csv_files_with_weights: list = None,
                      include_promoted: bool = True) -> dict:
    """
    csv_files_with_weights: optional list of (filename, weight) tuples,
    relative to RAW_XG_DIR. None (default) reproduces live behavior:
    scan RAW_XG_DIR, weight via XG_WEIGHTS (fallback 0.25).

    include_promoted: default True (live). False skips add_promoted_teams()
    entirely — needed for historical backtests since PROMOTED_TEAM_XG
    contains 2025/26 Championship data (Ipswich is a key in it).
    """
    if not os.path.exists(RAW_XG_DIR):
        print(f"[ERROR] Directory not found: {RAW_XG_DIR}")
        return {}

    XG_WEIGHTS = {
        "xg 22-23.csv": 0.10,
        "xg 23-24.csv": 0.20,
        "xg 24-25.csv": 0.30,
        "xg 25-26.csv": 0.40,
    }

    if csv_files_with_weights is not None:
        files_and_weights = list(csv_files_with_weights)
        missing = [f for f, _ in files_and_weights
                   if not os.path.exists(os.path.join(RAW_XG_DIR, f))]
        if missing:
            print(f"[ERROR] Missing CSV file(s) in {RAW_XG_DIR}: {missing}")
            return {}
    else:
        csv_files = sorted([
            f for f in os.listdir(RAW_XG_DIR) if f.endswith(".csv")
        ])
        if not csv_files:
            print(f"[ERROR] No CSV files in {RAW_XG_DIR}")
            return {}
        files_and_weights = [(f, XG_WEIGHTS.get(f, 0.25)) for f in csv_files]

    team_stats = defaultdict(lambda: {
        "seasons":       0,
        "total_matches": 0,
        "total_xg":      0.0,
        "total_xga":     0.0,
        "total_goals":   0,
        "total_ga":      0,
    })

    for filename, weight in files_and_weights:
        filepath = os.path.join(RAW_XG_DIR, filename)
        rows = load_xg_csv(filepath)
        print(f"  {filename}: {len(rows)} teams (weight: {weight})")

        for r in rows:
            s = team_stats[r["team"]]
            s["seasons"] += 1
            s["total_matches"] += r["matches"] * weight
            s["total_xg"] += r["xG"] * weight
            s["total_xga"] += r["xGA"] * weight
            s["total_goals"] += r["goals"] * weight
            s["total_ga"] += r["ga"] * weight

    profiles = {}
    for team, s in team_stats.items():
        n = s["total_matches"]
        if n == 0:
            continue

        avg_xg = s["total_xg"] / n
        avg_xga = s["total_xga"] / n
        rates = derive_market_rates(avg_xg, avg_xga)

        profiles[team] = {
            "seasons":           s["seasons"],
            "matches":           n,
            "avg_xg_for":        round(avg_xg, 3),
            "avg_xg_against":    round(avg_xga, 3),
            "avg_goals_for":     round(s["total_goals"] / n, 3),
            "avg_goals_against": round(s["total_ga"] / n, 3),
            "xg_over15_rate":    rates["xg_over15_rate"],
            "xg_over25_rate":    rates["xg_over25_rate"],
            "xg_btts_rate":      rates["xg_btts_rate"],
            "source":            "Understat EPL CSV",
        }

    if include_promoted:
        print("\nAdding promoted teams with Championship adjustment...")
        profiles = add_promoted_teams(profiles)

    return profiles


def save_xg_profiles(profiles: dict, path: str = None):
    target = path or OUTPUT_FILE
    out_dir = os.path.dirname(target) or "data"
    os.makedirs(out_dir, exist_ok=True)
    with open(target, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "source":     "Understat EPL CSV + Championship adjustments",
            "teams":      profiles
        }, f, indent=2)
    print(f"\nSaved {len(profiles)} xG profiles → {target}")


def load_xg_profiles(path: str = None) -> dict:
    target = path or OUTPUT_FILE
    if not os.path.exists(target):
        return {}
    with open(target) as f:
        return json.load(f)["teams"]


if __name__ == "__main__":
    print("Building xG profiles from Understat CSVs...\n")

    profiles = build_xg_profiles()

    if not profiles:
        print("No profiles built. Check data/raw/xg/ directory.")
        exit(1)

    save_xg_profiles(profiles)

    print("\nAll teams with xG profiles:")
    ranked = sorted(
        profiles.items(),
        key=lambda x: x[1]["avg_xg_for"],
        reverse=True
    )
    for team, p in ranked:
        source_flag = "📊" if p.get("source") == "Understat EPL CSV" else "⬆️"
        print(
            f"  {source_flag} {team:<25} "
            f"xG: {p['avg_xg_for']:.3f}  "
            f"xGA: {p['avg_xg_against']:.3f}  "
            f"({p['seasons']} season{'s' if p['seasons'] > 1 else ''})"
        )

    print("\nSample — Arsenal:")
    if "Arsenal" in profiles:
        p = profiles["Arsenal"]
        print(f"  Seasons:        {p['seasons']}")
        print(f"  Avg xG for:     {p['avg_xg_for']}")
        print(f"  Avg xG against: {p['avg_xg_against']}")
        print(f"  Over 2.5 rate:  {p['xg_over25_rate']}")
        print(f"  BTTS rate:      {p['xg_btts_rate']}")
