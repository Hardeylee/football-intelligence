"""
diagnose_btts_ceiling.py

DIAGNOSTIC ONLY — does not change any model behavior.

Purpose: confirm or rule out the theory that derive_market_rates()'s BTTS
formula was clustering most teams near a hard ceiling regardless of actual
opponent — which explained the calibration report's finding that the
80-90% predicted bucket (100/190 matches) had an actual BTTS rate of only
43%. As of this version, derive_market_rates() has been fixed to use a
Poisson-grounded formula (P(scores>=1) * P(concedes>=1)) instead of the
old (avg_xg_for * avg_xg_against) / 2.0 formula that caused the clustering.
This script now verifies that fix.

CHANGE LOG (this version):
  - Capped BTTS/Over25 values are now computed by importing and calling
    the REAL derive_market_rates() from xg_scraper.py, instead of a local
    reimplementation. This makes it structurally impossible for this
    diagnostic to silently go stale again if the formula changes.
  - BTTS_CAP updated from 0.90 to 0.95 to match the new formula's ceiling.
  - The RAW (pre-cap) BTTS column still uses a small local Poisson
    calculation, marked KEEP IN SYNC below, since derive_market_rates()
    only exposes capped output and the whole point of this script is
    seeing how hard the cap bites.

What it does:
  1. Loads a saved xg_profiles.json (path passed as CLI arg, or defaults
     to data/xg_profiles.json)
  2. For every team, calls the real derive_market_rates() for the capped
     xg_btts_rate / xg_over25_rate, and separately computes the RAW
     (uncapped) BTTS value to show how close each team sits to the cap.
  3. Prints summary stats: how many teams are within 0.02 of each cap,
     and the spread (min/max/std) of both rates across all teams — a
     tight spread near the cap supports the clustering theory, a wide
     spread argues against it.

This does NOT touch match-level predictions or any actual match's real
BTTS outcome — it only looks at the per-team profile inputs the formula
runs on.

Usage:
    python src/utils/diagnose_btts_ceiling.py
    python src/utils/diagnose_btts_ceiling.py data/xg_profiles_asof_24-25.json
"""

import json
import math
import os
import sys
import statistics

# PROJECT_ROOT-from-__file__ pattern (cwd-safe, unlike sys.path.insert(0, "."))
# NOTE: derive_market_rates is deliberately imported INSIDE recompute_rates()
# below, not here at module level. A top-of-file import can get hoisted above
# this sys.path.insert by VSCode's organize-imports-on-save even with an
# `isort: skip_file` comment present — this happened on this exact file.
# A local import inside the function can't be reordered by any formatter,
# so this is immune to that bug by construction.
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)


DEFAULT_PATH = "data/xg_profiles.json"
BTTS_CAP = 0.95
OVER25_CAP = 0.95
NEAR_CAP_THRESHOLD = 0.02  # "within this much of the cap counts as clustered"


def load_profiles(path: str) -> dict:
    if not os.path.exists(path):
        print(f"[ERROR] File not found: {path}")
        print("Pass the path to your xg_profiles JSON as a CLI argument, e.g.:")
        print("  python diagnose_btts_ceiling.py data/xg_profiles.json")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    teams = data.get("teams", data)  # tolerate either wrapped or raw format
    if not teams:
        print(f"[ERROR] No teams found in {path}")
        sys.exit(1)
    return teams


def recompute_rates(avg_xg_for: float, avg_xg_against: float) -> dict:
    """Capped values come from the REAL derive_market_rates() — guaranteed
    to match production. Raw (uncapped) BTTS is a local KEEP IN SYNC copy
    of the same Poisson math, needed only to show cap proximity."""
    from src.collectors.xg_scraper import derive_market_rates  # local import, see note at top of file
    real_rates = derive_market_rates(avg_xg_for, avg_xg_against)

    # KEEP IN SYNC with the Poisson BTTS calc inside xg_scraper.derive_market_rates().
    # This exists only to expose the pre-cap value; the capped value above is authoritative.
    p_scores = 1 - math.exp(-avg_xg_for)
    p_concedes = 1 - math.exp(-avg_xg_against)
    raw_btts = p_scores * p_concedes

    total_xg = avg_xg_for + avg_xg_against
    raw_over25 = total_xg / 5.0

    return {
        "raw_over25": round(raw_over25, 4),
        "capped_over25": real_rates["xg_over25_rate"],
        "over25_hit_cap": raw_over25 > OVER25_CAP,
        "raw_btts": round(raw_btts, 4),
        "capped_btts": real_rates["xg_btts_rate"],
        "btts_hit_cap": raw_btts > BTTS_CAP,
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    print(f"Loading profiles from: {path}\n")
    teams = load_profiles(path)

    rows = []
    for team, p in teams.items():
        avg_xg_for = p.get("avg_xg_for")
        avg_xg_against = p.get("avg_xg_against")
        if avg_xg_for is None or avg_xg_against is None:
            print(f"  [skip] {team}: missing avg_xg_for/avg_xg_against")
            continue
        rates = recompute_rates(avg_xg_for, avg_xg_against)
        rows.append((team, avg_xg_for, avg_xg_against, rates))

    if not rows:
        print("[ERROR] No usable team rows found.")
        sys.exit(1)

    # ---- Per-team table, sorted by capped BTTS descending ----
    rows.sort(key=lambda r: r[3]["capped_btts"], reverse=True)

    print("=" * 100)
    print(f"{'Team':<20}{'xG_for':>8}{'xG_against':>12}{'raw_BTTS':>10}"
          f"{'cap_BTTS':>10}{'hit_cap':>9}{'raw_O25':>9}{'cap_O25':>9}{'hit_cap':>9}")
    print("=" * 100)
    for team, xf, xa, r in rows:
        print(f"{team:<20}{xf:>8.3f}{xa:>12.3f}{r['raw_btts']:>10.3f}"
              f"{r['capped_btts']:>10.3f}{str(r['btts_hit_cap']):>9}"
              f"{r['raw_over25']:>9.3f}{r['capped_over25']:>9.3f}{str(r['over25_hit_cap']):>9}")

    # ---- Summary stats ----
    btts_vals = [r[3]["capped_btts"] for r in rows]
    over25_vals = [r[3]["capped_over25"] for r in rows]
    btts_hit_cap_count = sum(1 for r in rows if r[3]["btts_hit_cap"])
    over25_hit_cap_count = sum(1 for r in rows if r[3]["over25_hit_cap"])
    btts_near_cap_count = sum(
        1 for r in rows if BTTS_CAP - r[3]["capped_btts"] <= NEAR_CAP_THRESHOLD
    )
    over25_near_cap_count = sum(
        1 for r in rows if OVER25_CAP - r[3]["capped_over25"] <= NEAR_CAP_THRESHOLD
    )

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"Teams analyzed: {len(rows)}")
    print()
    print(f"BTTS rate (per-team, capped at {BTTS_CAP}):")
    print(f"  min={min(btts_vals):.3f}  max={max(btts_vals):.3f}  "
          f"mean={statistics.mean(btts_vals):.3f}  stdev={statistics.pstdev(btts_vals):.3f}")
    print(f"  Teams whose RAW value actually exceeds {BTTS_CAP} (cap literally triggered): "
          f"{btts_hit_cap_count}/{len(rows)}")
    print(f"  Teams within {NEAR_CAP_THRESHOLD} of the {BTTS_CAP} cap (effectively clustered at ceiling): "
          f"{btts_near_cap_count}/{len(rows)}")
    print()
    print(f"Over 2.5 rate (per-team, capped at {OVER25_CAP}):")
    print(f"  min={min(over25_vals):.3f}  max={max(over25_vals):.3f}  "
          f"mean={statistics.mean(over25_vals):.3f}  stdev={statistics.pstdev(over25_vals):.3f}")
    print(f"  Teams whose RAW value actually exceeds {OVER25_CAP} (cap literally triggered): "
          f"{over25_hit_cap_count}/{len(rows)}")
    print(f"  Teams within {NEAR_CAP_THRESHOLD} of the {OVER25_CAP} cap (effectively clustered at ceiling): "
          f"{over25_near_cap_count}/{len(rows)}")

    print("\n" + "=" * 100)
    print("READING THIS")
    print("=" * 100)
    print(
        "NOTE: these are single-team profile rates, not match-level predictions.\n"
        "A real match combines TWO teams' rates (home and away) — so even if no single\n"
        "team's raw BTTS value hits the cap on its own, match-level predicted probability\n"
        "is a further combination of these per-team rates inside predict_goals()/\n"
        "predict_match() (not shown here).\n\n"
        "What this script DOES tell you:\n"
        "  - If most teams' per-team BTTS rate sits in a narrow band close to the cap,\n"
        "    that's strong support for the ceiling-clustering theory: the match-level formula\n"
        "    is very likely combining two already-high inputs, pushing the final number toward\n"
        "    the cap for almost every fixture, not just high-scoring matchups.\n"
        "  - If per-team BTTS rates are widely spread (low stdev is bad, high stdev is good\n"
        "    for the model), the ceiling isn't the whole story and the match-level combination\n"
        "    logic (wherever BTTS gets computed from two teams, not shown in this file) needs\n"
        "    to be checked next.\n"
    )


if __name__ == "__main__":
    main()
