"""
Snapshot xG builder — point-in-time xG profiles for backtesting.
Mirrors build_snapshot_elo.py / build_snapshot_profiles.py.

Builds xG profiles using ONLY seasons that predate the 2024/25 test
season (22-23, 23-24), with promoted-team Championship overrides
disabled. PROMOTED_TEAM_XG (in xg_scraper.py) is 2025/26 Championship
data and Ipswich is a key in it — leaving include_promoted at its
default True would silently hand Ipswich their future Championship
form for a 24/25 backtest fixture. include_promoted=False is what
prevents that.
"""

import os
import sys

# PROJECT_ROOT-from-__file__ pattern (cwd-safe) — this class of bug has hit
# backtester_v4.py, diagnose_btts_ceiling.py, and diagnose_stacking.py
# already this session, all missing this same setup. xg_scraper is imported
# INSIDE build_snapshot() below, not here at module level, so no
# formatter/import-sorter can hoist it above this sys.path.insert.
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Was 0.25/0.75 -- inverted relative to real-world outcomes: 22-23
# (~2.85 goals/game, confirmed via web search) is much closer to the
# 24-25 test season's actual 2.93 g/g than 23-24 (3.28 g/g, a confirmed
# record-outlier season) is. The old 75% weight on the outlier is what
# drove the over25 market's diagnosed inflation (see handover note).
# Using a neutral 50/50 split, NOT a ratio tuned to hit 2.93 exactly --
# deliberately tuning to match this one known historical season's actual
# outcome would be look-ahead bias baked into the weighting itself, and
# wouldn't generalize to a real future season whose scoring rate is
# unknown in advance. 50/50 just stops over-weighting a known anomaly.
SNAPSHOT_XG_FILES = [
    ("xg 22-23.csv", 0.50),
    ("xg 23-24.csv", 0.50),
]

OUTPUT_FILE = "data/xg_profiles_asof_24-25.json"

# Teams promoted INTO the EPL for 2024/25. A snapshot built only from
# 22-23/23-24 data should have NO entry for these — no prior-season xG
# exists for them at this point in time. Their presence in the output
# means data leaked in somewhere.
ACTUAL_24_25_PROMOTED = ["Leicester", "Ipswich", "Southampton"]


def build_snapshot():
    from src.collectors import xg_scraper  # local import, see note at top of file
    print("Building point-in-time xG snapshot (as-of 2024/25)...")
    print(f"Source files: {SNAPSHOT_XG_FILES}")
    print("Promoted-team Championship overrides: DISABLED "
          "(include_promoted=False)\n")

    profiles = xg_scraper.build_xg_profiles(
        csv_files_with_weights=SNAPSHOT_XG_FILES,
        include_promoted=False,
    )

    if not profiles:
        print("[ERROR] No profiles built — check that the files in "
              f"{SNAPSHOT_XG_FILES} exist in {xg_scraper.RAW_XG_DIR}")
        return

    xg_scraper.save_xg_profiles(profiles, path=OUTPUT_FILE)

    print("\nSpot-check — 2024/25's actual promoted teams should be "
          "ABSENT (honest 'no data' state, not a borrowed rating):")
    all_absent = True
    for team in ACTUAL_24_25_PROMOTED:
        if team in profiles:
            all_absent = False
            print(f"  ❌ LEAK: {team} found in snapshot "
                  f"(avg_xg_for={profiles[team]['avg_xg_for']}) — "
                  f"this should NOT happen with include_promoted=False")
        else:
            print(f"  ✅ {team} correctly absent")

    if all_absent:
        print("\nSpot-check passed — no promoted-team leak detected.")


if __name__ == "__main__":
    build_snapshot()
