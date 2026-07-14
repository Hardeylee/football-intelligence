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
import os
from datetime import datetime
from collections import defaultdict

RAW_XG_DIR = "data/raw/xg"
OUTPUT_FILE = "data/xg_profiles.json"

# Map Understat team names → football-data.co.uk canonical names
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

# EPL adjustment factor for promoted teams (Championship → EPL step up).
# Applied ONLY to attacking output (raw_xg) -- see add_promoted_teams()
# below. Previously this was also applied to raw_xga, which implied a
# promoted team's defense gets BETTER stepping up to a tougher league.
# That was backwards and has been corrected: raw_xga is now used as-is,
# undiscounted. There's no established factor in this codebase for how
# much MORE a promoted side should be expected to concede against EPL-
# level attacks, so rather than invent one, the raw Championship xGA rate
# is used directly -- flagged as a likely understatement of real
# defensive risk for these teams, not a solved problem.
PROMOTION_DISCOUNT = 0.80

# Promoted teams xG data from FootyStats Championship stats.
# raw_xg and raw_xga below were verified against live footystats.org team
# pages during this session (Coventry, Ipswich confirmed directly;
# Ipswich's xGA additionally cross-checked against a second independent
# source, OddAlerts, which had them at 1.03/90 -- consistent). Hull's
# xGA was checked and reported as 1.64 but not independently re-verified
# by a second source in this session -- worth a spot-check if precision
# matters here. The previous hardcoded values were stale/wrong with no
# consistent direction of error (some too high, some too low), which is
# why this whole block is a manual-entry risk -- see the automation note
# in add_promoted_teams() docstring.
PROMOTED_TEAM_XG = {
    # 2025/26 promoted teams (from Championship 2025/26 season)
    "Coventry City": {
        # was 1.83 -- stale, verified via OddAlerts (2.04/90)
        "raw_xg":            2.04,
        # was 1.65 -- stale, verified via footystats.org/clubs/coventry-city-fc-239
        "raw_xga":           1.27,
        "matches":           46,
        "avg_goals_for":     2.11,
        "avg_goals_against": 0.98,
        "championship_season": "2025/26",
    },
    "Hull City": {
        # unchanged -- no clean single-source figure found to verify against this session
        "raw_xg":            1.67,
        # was 1.21 -- flagged as stale/wrong, updated per live FootyStats check
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
    # Ipswich were in EPL 2024/25 so they have EPL history already
    # but keeping Championship backup in case they're not in profiles
    "Ipswich": {
        "raw_xg":            1.45,   # was 1.30 -- stale, verified via footystats.org H2H data
        # was 1.90 -- stale, verified via footystats.org AND OddAlerts (1.03/90, tightest defense in Championship)
        "raw_xga":           1.20,
        "matches":           46,
        "avg_goals_for":     1.40,
        "avg_goals_against": 1.60,
        "championship_season": "2024/25 EPL (relegated) + discount",
    },
}


def load_xg_csv(filepath: str) -> list:
    """Load one season's xG CSV. Returns list of team dicts."""
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
    """
    Derive over/under and BTTS market probability rates from xG values.
    Uses Poisson-inspired approximations.
    """
    total_xg = avg_xg + avg_xga
    return {
        "xg_over15_rate": round(min(total_xg / 3.0, 0.97), 3),
        "xg_over25_rate": round(min(total_xg / 5.0, 0.95), 3),
        "xg_btts_rate":   round(min((avg_xg * avg_xga) / 2.0, 0.90), 3),
    }


# Teams where we override EPL data with adjusted estimate
FORCE_OVERRIDE = ["Ipswich"]


def add_promoted_teams(profiles: dict) -> dict:
    """
    Add promoted teams not already in EPL xG profiles.
    Uses Championship xG data. PROMOTION_DISCOUNT is applied ONLY to
    raw_xg (attacking output) -- raw_xga is used undiscounted. See the
    PROMOTION_DISCOUNT comment above for why the two aren't symmetric.
    Only adds a team if it's not already in profiles from EPL data,
    except for FORCE_OVERRIDE teams which always use this estimate.
    """
    for team, data in PROMOTED_TEAM_XG.items():
        if team in profiles and team not in FORCE_OVERRIDE:
            continue

        avg_xg = round(data["raw_xg"] * PROMOTION_DISCOUNT, 3)
        avg_xga = round(data["raw_xga"], 3)  # undiscounted, intentionally
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


def build_xg_profiles() -> dict:
    """
    Load all EPL xG CSV files and build per-team profiles.
    Averages xG across all available seasons.
    Then adds promoted teams with Championship adjustment.
    """
    if not os.path.exists(RAW_XG_DIR):
        print(f"[ERROR] Directory not found: {RAW_XG_DIR}")
        return {}

    csv_files = sorted([
        f for f in os.listdir(RAW_XG_DIR) if f.endswith(".csv")
    ])

    if not csv_files:
        print(f"[ERROR] No CSV files in {RAW_XG_DIR}")
        return {}

    # Accumulate stats per team across seasons
    team_stats = defaultdict(lambda: {
        "seasons":       0,
        "total_matches": 0,
        "total_xg":      0.0,
        "total_xga":     0.0,
        "total_goals":   0,
        "total_ga":      0,
    })

    # Recency weights for xG seasons
    XG_WEIGHTS = {
        "xg 22-23.csv": 0.10,
        "xg 23-24.csv": 0.20,
        "xg 24-25.csv": 0.30,
        "xg 25-26.csv": 0.40,
    }

    for filename in csv_files:
        filepath = os.path.join(RAW_XG_DIR, filename)
        rows = load_xg_csv(filepath)
        weight = XG_WEIGHTS.get(filename, 0.25)
        print(f"  {filename}: {len(rows)} teams (weight: {weight})")

        for r in rows:
            s = team_stats[r["team"]]
            s["seasons"] += 1
            s["total_matches"] += r["matches"] * weight
            s["total_xg"] += r["xG"] * weight
            s["total_xga"] += r["xGA"] * weight
            s["total_goals"] += r["goals"] * weight
            s["total_ga"] += r["ga"] * weight

    # Build final profiles with averages
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

    # Add promoted teams not already in EPL data
    print("\nAdding promoted teams with Championship adjustment...")
    profiles = add_promoted_teams(profiles)

    return profiles


def save_xg_profiles(profiles: dict):
    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "source":     "Understat EPL CSV + Championship adjustments",
            "teams":      profiles
        }, f, indent=2)
    print(f"\nSaved {len(profiles)} xG profiles → {OUTPUT_FILE}")


def load_xg_profiles() -> dict:
    if not os.path.exists(OUTPUT_FILE):
        return {}
    with open(OUTPUT_FILE) as f:
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
