"""
Referee Profiler — built from football-data.co.uk CSVs
Calculates each referee's card tendencies from 4 seasons of EPL data.
Used to adjust cards market predictions.
"""

import csv
import json
import os
from collections import defaultdict

RAW_DATA_DIR = "data/raw"
REFEREE_FILE = "data/referee_profiles.json"


def build_referee_profiles() -> dict:
    """Read all CSVs and build a profile per referee."""

    stats = defaultdict(lambda: {
        "matches": 0,
        "total_yellows": 0,
        "total_reds": 0,
        "home_yellows": 0,
        "away_yellows": 0,
        "over35_cards": 0,
        "over45_cards": 0,
        "over55_cards": 0,
    })

    csv_files = [f for f in os.listdir(RAW_DATA_DIR) if f.endswith(".csv")]

    for filename in sorted(csv_files):
        filepath = os.path.join(RAW_DATA_DIR, filename)
        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ref = row.get("Referee", "").strip()
                if not ref:
                    continue

                try:
                    hy = int(float(row.get("HY", 0) or 0))
                    ay = int(float(row.get("AY", 0) or 0))
                    hr = int(float(row.get("HR", 0) or 0))
                    ar = int(float(row.get("AR", 0) or 0))
                except:
                    continue

                total_yellows = hy + ay
                total_reds = hr + ar
                total_cards = total_yellows + total_reds

                s = stats[ref]
                s["matches"] += 1
                s["total_yellows"] += total_yellows
                s["total_reds"] += total_reds
                s["home_yellows"] += hy
                s["away_yellows"] += ay

                if total_cards > 3.5:
                    s["over35_cards"] += 1
                if total_cards > 4.5:
                    s["over45_cards"] += 1
                if total_cards > 5.5:
                    s["over55_cards"] += 1

    # Build profiles with averages
    profiles = {}
    for ref, s in stats.items():
        n = s["matches"]
        if n < 5:
            continue  # Skip refs with too few games

        avg_yellows = s["total_yellows"] / n
        avg_reds = s["total_reds"] / n
        avg_cards = avg_yellows + avg_reds

        # Card tendency rating
        if avg_cards >= 5.0:
            tendency = "STRICT"
        elif avg_cards >= 3.5:
            tendency = "AVERAGE"
        else:
            tendency = "LENIENT"

        profiles[ref] = {
            "matches":         n,
            "avg_yellows":     round(avg_yellows, 2),
            "avg_reds":        round(avg_reds, 2),
            "avg_total_cards": round(avg_cards, 2),
            "avg_home_yellows": round(s["home_yellows"] / n, 2),
            "avg_away_yellows": round(s["away_yellows"] / n, 2),
            "over35_rate":     round(s["over35_cards"] / n, 3),
            "over45_rate":     round(s["over45_cards"] / n, 3),
            "over55_rate":     round(s["over55_cards"] / n, 3),
            "tendency":        tendency,
        }

    return profiles


def save_referee_profiles(profiles: dict):
    from datetime import datetime
    os.makedirs("data", exist_ok=True)
    with open(REFEREE_FILE, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "referees": profiles
        }, f, indent=2)
    print(f"Saved {len(profiles)} referee profiles → {REFEREE_FILE}")


def load_referee_profiles() -> dict:
    if not os.path.exists(REFEREE_FILE):
        return {}
    with open(REFEREE_FILE) as f:
        return json.load(f)["referees"]


def get_referee_adjustment(referee: str, profiles: dict) -> dict:
    """
    Returns card probability adjustments for a given referee.
    Falls back to league averages if referee not found.
    """
    # League average fallback
    default = {
        "avg_total_cards": 3.8,
        "over35_rate":     0.52,
        "over45_rate":     0.30,
        "over55_rate":     0.15,
        "tendency":        "AVERAGE",
        "found":           False,
    }

    if not referee or not profiles:
        return default

    # Try exact match first
    if referee in profiles:
        p = profiles[referee]
        return {**p, "found": True}

    # Try partial match (first/last name)
    ref_lower = referee.lower()
    for name, p in profiles.items():
        if ref_lower in name.lower() or name.lower() in ref_lower:
            return {**p, "found": True}

    return default


def adjust_cards_for_referee(
    base_over35: float,
    base_over45: float,
    referee: str,
    profiles: dict
) -> dict:
    """
    Blend base team card rates with referee tendency.
    Referee gets 40% weight — strongest single predictor.
    """
    ref = get_referee_adjustment(referee, profiles)

    # Blend: 60% team history, 40% referee tendency
    blended_over35 = (base_over35 * 0.60) + (ref["over35_rate"] * 0.40)
    blended_over45 = (base_over45 * 0.60) + (ref["over45_rate"] * 0.40)

    return {
        "referee":          referee or "Unknown",
        "referee_tendency": ref["tendency"],
        "referee_avg_cards": ref["avg_total_cards"],
        "over35_cards":     round(min(blended_over35, 0.95), 3),
        "over45_cards":     round(min(blended_over45, 0.90), 3),
        "referee_found":    ref["found"],
    }


if __name__ == "__main__":
    print("Building referee profiles from CSV data...\n")
    profiles = build_referee_profiles()
    save_referee_profiles(profiles)

    print("\nTop 10 strictest referees:")
    ranked = sorted(profiles.items(),
                    key=lambda x: x[1]["avg_total_cards"], reverse=True)
    for ref, p in ranked[:10]:
        print(f"  {ref:<25} {p['avg_total_cards']} cards/game "
              f"({p['matches']} matches) — {p['tendency']}")

    print("\n10 most lenient referees:")
    for ref, p in ranked[-10:]:
        print(f"  {ref:<25} {p['avg_total_cards']} cards/game "
              f"({p['matches']} matches) — {p['tendency']}")
