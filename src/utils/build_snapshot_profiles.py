"""
Snapshot Profile Builder
Builds team_profiles.json and h2h.json using ONLY matches from the given
season CSVs -- no data from the season being backtested against.

Why this exists: match_predictor.py's load_profiles()/load_h2h() always
read whatever is currently on disk, with no date filter. If those files
reflect the current (2025/26+) season, "backtesting" against 24/25 with
them means the model already knows how 24/25 actually turned out -- the
same leak class the backtester's threshold-tuning fix addressed, but
here it'd be silent since nothing in match_predictor.py guards against it.

Usage:
    python -m src.utils.build_snapshot_profiles

Produces:
    data/team_profiles_asof_24-25.json
    data/h2h_asof_24-25.json

Point the backtest harness at these snapshot files specifically -- do
NOT overwrite the live data/team_profiles.json / data/h2h.json with
them, since those may be relied on elsewhere for live predictions.

STILL OPEN: Elo ratings have the exact same problem (epl_elo.py's
load_ratings() has no date parameter either) and predict_result()
weights Elo at 50% -- the single largest input to the result market.
This script does not touch that; it needs a point-in-time Elo snapshot
built the same way before result-market backtesting is fully honest.
"""

import json
import os
import csv
from collections import defaultdict
from datetime import datetime

# Same train files/weights as the backtester -- only pre-24/25 data.
SNAPSHOT_SOURCE_FILES = [
    ("data/raw/22-23.csv", 0.25),
    ("data/raw/23-24.csv", 0.75),
]

OUTPUT_PROFILES = "data/team_profiles_asof_24-25.json"
OUTPUT_H2H = "data/h2h_asof_24-25.json"

REQUIRED_COLS = [
    "Date", "HomeTeam", "AwayTeam",
    "FTHG", "FTAG", "FTR",
    "HC", "AC", "HF", "AF",
    "HY", "AY", "HR", "AR",
]


def load_csv_file(filepath: str) -> list:
    matches = []
    if not os.path.exists(filepath):
        print(f"[WARN] Not found: {filepath}")
        return []
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("HomeTeam") or not row.get("Date"):
                continue
            match = {}
            for col in REQUIRED_COLS:
                val = row.get(col, "")
                if col in ["FTHG", "FTAG", "HC", "AC", "HF", "AF", "HY", "AY", "HR", "AR"]:
                    try:
                        match[col] = int(float(val)) if val else 0
                    except (ValueError, TypeError):
                        match[col] = 0
                else:
                    match[col] = val
            matches.append(match)
    return matches


def build_team_profiles(source_files: list) -> dict:
    """
    Builds the exact schema match_predictor.py expects from
    load_profiles(): win_rate, draw_rate, loss_rate, btts_rate,
    over15_rate, over25_rate, home/away splits for goals, cards,
    corners, plus clean_sheet_rate and form_score.

    form_score is left as win_rate (same caveat as the backtester's
    blended_win_rate rename) -- this snapshot builder does not invent
    real recency-within-season form, it just avoids calling a win-rate
    duplicate something misleading. Flagged in the output JSON's
    _meta block rather than silently shipped.
    """
    stats = defaultdict(lambda: {
        "weight": 0.0,
        "wins": 0.0, "draws": 0.0, "losses": 0.0,
        "btts": 0.0, "over15": 0.0, "over25": 0.0,
        "home_weight": 0.0, "home_wins": 0.0,
        "home_goals_scored": 0.0, "home_goals_conceded": 0.0,
        "home_cards": 0.0, "home_corners_for": 0.0, "home_corners_against": 0.0,
        "home_clean_sheets": 0.0,
        "away_weight": 0.0, "away_wins": 0.0,
        "away_goals_scored": 0.0, "away_goals_conceded": 0.0,
        "away_cards": 0.0, "away_corners_for": 0.0, "away_corners_against": 0.0,
        "away_clean_sheets": 0.0,
        "total_cards": 0.0, "total_corners_for": 0.0, "total_corners_against": 0.0,
    })

    for filepath, weight in source_files:
        matches = load_csv_file(filepath)
        print(f"  {filepath}: {len(matches)} matches (weight: {weight})")

        for m in matches:
            home, away = m["HomeTeam"], m["AwayTeam"]
            hg, ag = m["FTHG"], m["FTAG"]
            result = m["FTR"]
            total_goals = hg + ag
            btts = hg > 0 and ag > 0

            s = stats[home]
            s["weight"] += weight
            s["home_weight"] += weight
            s["home_goals_scored"] += hg * weight
            s["home_goals_conceded"] += ag * weight
            s["home_cards"] += m["HY"] * weight
            s["home_corners_for"] += m["HC"] * weight
            s["home_corners_against"] += m["AC"] * weight
            s["total_cards"] += (m["HY"] + m["AY"]) * weight
            s["total_corners_for"] += m["HC"] * weight
            s["total_corners_against"] += m["AC"] * weight
            if ag == 0:
                s["home_clean_sheets"] += weight
            if btts:
                s["btts"] += weight
            if total_goals > 1.5:
                s["over15"] += weight
            if total_goals > 2.5:
                s["over25"] += weight
            if result == "H":
                s["wins"] += weight
                s["home_wins"] += weight
            elif result == "D":
                s["draws"] += weight
            else:
                s["losses"] += weight

            s = stats[away]
            s["weight"] += weight
            s["away_weight"] += weight
            s["away_goals_scored"] += ag * weight
            s["away_goals_conceded"] += hg * weight
            s["away_cards"] += m["AY"] * weight
            s["away_corners_for"] += m["AC"] * weight
            s["away_corners_against"] += m["HC"] * weight
            s["total_cards"] += (m["HY"] + m["AY"]) * weight
            s["total_corners_for"] += m["AC"] * weight
            s["total_corners_against"] += m["HC"] * weight
            if hg == 0:
                s["away_clean_sheets"] += weight
            if btts:
                s["btts"] += weight
            if total_goals > 1.5:
                s["over15"] += weight
            if total_goals > 2.5:
                s["over25"] += weight
            if result == "A":
                s["wins"] += weight
                s["away_wins"] += weight
            elif result == "D":
                s["draws"] += weight
            else:
                s["losses"] += weight

    profiles = {}
    for team, s in stats.items():
        w = s["weight"]
        hw = s["home_weight"] or 0.001
        aw = s["away_weight"] or 0.001
        if w < 0.3:
            continue

        profiles[team] = {
            "win_rate":                 round(s["wins"] / w, 3),
            "draw_rate":                round(s["draws"] / w, 3),
            "loss_rate":                round(s["losses"] / w, 3),
            "btts_rate":                round(s["btts"] / w, 3),
            "over15_rate":              round(s["over15"] / w, 3),
            "over25_rate":              round(s["over25"] / w, 3),
            "clean_sheet_rate":         round((s["home_clean_sheets"] + s["away_clean_sheets"]) / w, 3),
            "home_win_rate":            round(s["home_wins"] / hw, 3),
            "home_avg_goals_scored":    round(s["home_goals_scored"] / hw, 3),
            "home_avg_goals_conceded":  round(s["home_goals_conceded"] / hw, 3),
            "away_win_rate":            round(s["away_wins"] / aw, 3),
            "away_avg_goals_scored":    round(s["away_goals_scored"] / aw, 3),
            "away_avg_goals_conceded":  round(s["away_goals_conceded"] / aw, 3),
            "avg_yellow_cards":         round(s["total_cards"] / w, 3),
            "avg_corners_for":          round(s["total_corners_for"] / w, 3),
            "avg_corners_against":      round(s["total_corners_against"] / w, 3),
            "home_avg_yellow_cards":    round(s["home_cards"] / hw, 3),
            "away_avg_yellow_cards":    round(s["away_cards"] / aw, 3),
            "home_avg_corners_for":     round(s["home_corners_for"] / hw, 3),
            "home_avg_corners_against": round(s["home_corners_against"] / hw, 3),
            "away_avg_corners_for":     round(s["away_corners_for"] / aw, 3),
            "away_avg_corners_against": round(s["away_corners_against"] / aw, 3),
            # NOTE: not real recency-within-season form -- same win_rate
            # duplicate issue as the backtester had. Flagged, not hidden.
            "form_score":               round(s["wins"] / w, 3),
        }

    return profiles


def build_h2h(source_files: list) -> dict:
    """
    Builds h2h.json entries using only matches from the source files
    (pre-cutoff). Key format matches get_h2h()'s lookup:
    "{home}_vs_{away}" -- get_h2h() also checks the reverse key, so we
    only need to write one direction per pair, but we accumulate both
    home and away fixtures between the same two teams either way.
    """
    pairs = defaultdict(lambda: {
        "matches": 0, "home_wins": 0, "away_wins": 0, "draws": 0,
        "total_goals": 0,
    })

    for filepath, _ in source_files:
        matches = load_csv_file(filepath)
        for m in matches:
            home, away = m["HomeTeam"], m["AwayTeam"]
            key = f"{home}_vs_{away}"
            p = pairs[key]
            p["matches"] += 1
            p["total_goals"] += m["FTHG"] + m["FTAG"]
            if m["FTR"] == "H":
                p["home_wins"] += 1
            elif m["FTR"] == "A":
                p["away_wins"] += 1
            else:
                p["draws"] += 1

    h2h = {}
    for key, p in pairs.items():
        h2h[key] = {
            "matches":    p["matches"],
            "home_wins":  p["home_wins"],
            "away_wins":  p["away_wins"],
            "draws":      p["draws"],
            "avg_goals":  round(p["total_goals"] / p["matches"], 2) if p["matches"] else 0,
        }
    return h2h


def main():
    print("=" * 60)
    print("  SNAPSHOT PROFILE BUILDER")
    print(f"  Source: {[f[0] for f in SNAPSHOT_SOURCE_FILES]}")
    print("  (no data after this point is used -- safe for backtesting")
    print("   any season starting after these source files end)")
    print("=" * 60)

    print("\nBuilding team profiles...")
    profiles = build_team_profiles(SNAPSHOT_SOURCE_FILES)
    print(f"  {len(profiles)} teams profiled")

    print("\nBuilding head-to-head records...")
    h2h = build_h2h(SNAPSHOT_SOURCE_FILES)
    print(f"  {len(h2h)} team pairs")

    os.makedirs("data", exist_ok=True)

    profiles_out = {
        "_meta": {
            "generated": datetime.now().isoformat(),
            "source_files": [f[0] for f in SNAPSHOT_SOURCE_FILES],
            "warning": "form_score is win_rate, not true recency-weighted "
                       "form -- see build_snapshot_profiles.py docstring.",
        },
        "teams": profiles,
    }
    with open(OUTPUT_PROFILES, "w") as f:
        json.dump(profiles_out, f, indent=2)
    print(f"\nSaved → {OUTPUT_PROFILES}")

    h2h_out = {
        "_meta": {
            "generated": datetime.now().isoformat(),
            "source_files": [f[0] for f in SNAPSHOT_SOURCE_FILES],
        },
        "h2h": h2h,
    }
    with open(OUTPUT_H2H, "w") as f:
        json.dump(h2h_out, f, indent=2)
    print(f"Saved → {OUTPUT_H2H}")

    print("\n[REMINDER] Elo ratings still need the same point-in-time "
          "treatment before result-market backtests are fully honest -- "
          "not handled by this script.")


if __name__ == "__main__":
    main()
