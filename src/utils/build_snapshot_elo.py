"""
build_snapshot_elo.py
Point-in-time Elo ratings for backtesting -- built ONLY from 22-23.csv +
23-24.csv, matching backtester_v3.py's TRAIN_FILES and
build_snapshot_profiles.py's source seasons. No promoted-team overrides
applied: PROMOTED_RATINGS in epl_elo.py is specific to 2026/27's
promoted sides (Coventry City, Ipswich, Hull City) and would misdate a
24/25 backtest -- e.g. it would rate Ipswich using their 2025/26
Championship-winning form, two years after the season being tested, and
wouldn't cover 24/25's actual promoted teams (Leicester, Ipswich,
Southampton) at all. See initialise_ratings()'s docstring in epl_elo.py
for the full reasoning.

Teams absent from these two seasons (e.g. Ipswich, who weren't in the
EPL in 22-23 or 23-24) fall back to BASE_RATING (1500) -- an honest
"no prior data" state rather than a borrowed future rating.

Usage:
    python -m src.utils.build_snapshot_elo

Produces:
    data/epl_elo_ratings_asof_24-25.json

Point match_predictor.py's predict_result() at this file (once it
accepts a path parameter -- open item, see chat) instead of the live
data/epl_elo_ratings.json when backtesting 24/25 fixtures.
"""

from src.models.epl_elo import initialise_ratings, save_ratings, predict_result_elo

TRAIN_FILES = [
    ("data/raw/22-23.csv", 0.25),
    ("data/raw/23-24.csv", 0.75),
]

OUTPUT_PATH = "data/epl_elo_ratings_asof_24-25.json"


def main():
    print("=" * 60)
    print("  SNAPSHOT ELO BUILDER")
    print(f"  Source: {[f[0] for f in TRAIN_FILES]}")
    print("  (no promoted-team overrides applied -- see docstring)")
    print("=" * 60)

    ratings = initialise_ratings(TRAIN_FILES, promoted_overrides=None)
    save_ratings(ratings, path=OUTPUT_PATH)

    print(f"\n{len(ratings)} teams rated from pre-24/25 data.")

    # Sanity spot-check: any of 24/25's actual promoted teams
    # (Leicester, Ipswich, Southampton) that have no top-flight history
    # in 22-23/23-24 should show up at BASE_RATING, not a borrowed value.
    print("\nSpot-check -- 24/25's actual promoted teams:")
    for team in ["Leicester", "Ipswich", "Southampton"]:
        rating = ratings.get(team, 1500)
        flag = " (BASE_RATING -- no prior top-flight data, as expected)" if team not in ratings else ""
        print(f"  {team:<15} {rating:>7}{flag}")


if __name__ == "__main__":
    main()
