"""
EPL Club Elo Rating System
Initialises and updates Elo ratings for all EPL clubs.
Uses historical results to build starting ratings.
Updates after each match result.

Starting rating: 1500 (league average)
K-factor: 32 (standard for club football)
Home advantage: 100 Elo points

PATCH NOTE (backtest leak fix):

initialise_ratings() used to read TRAIN_FILES and PROMOTED_RATINGS
directly from module globals, which meant there was no way to build a
point-in-time snapshot (e.g. "ratings as of end of 23-24, before 24-25
kicks off") without either mutating these globals or duplicating the
whole function. Two separate leaks stacked on top of each other as a
result:

1. TRAIN_FILES included seasons up through 25-26.csv. Any backtest
   against 24-25 fixtures that called load_ratings() in production was
   getting ratings built from 24-25's own results plus a full season
   after it -- the model already "knew" the outcome of the season being
   tested.

2. PROMOTED_RATINGS is hardcoded for 2026/27's promoted teams
   (Coventry City, Ipswich, Hull City), derived from their 2025/26
   Championship form. The 2024/25 season's actual promoted teams were
   Leicester, Ipswich, and Southampton -- a different set of clubs.
   Naively reusing initialise_ratings() for a 24/25 backtest would
   silently override Ipswich's rating with form from a season two years
   in their future, while Leicester/Southampton -- that season's real
   promoted teams -- got no override treatment at all.

Fix: initialise_ratings() now takes train_files and promoted_overrides
as explicit parameters instead of reading globals. The __main__ block
below passes TRAIN_FILES/PROMOTED_RATINGS explicitly for live production
use (behavior unchanged). A separate snapshot script
(build_snapshot_elo.py) calls the same function with only pre-cutoff
seasons and promoted_overrides=None, so backtest ratings and production
ratings share one code path instead of two copies drifting apart.

save_ratings()/load_ratings() also take an optional path param so a
snapshot file (e.g. data/epl_elo_ratings_asof_24-25.json) can't collide
with the live data/epl_elo_ratings.json.
"""

import json
import os
import csv
from datetime import datetime

ELO_FILE = "data/epl_elo_ratings.json"
BASE_RATING = 1500
K_FACTOR = 32
HOME_ADVANTAGE = 100

TRAIN_FILES = [
    ("data/raw/22-23.csv", 0.10),
    ("data/raw/23-24.csv", 0.20),
    ("data/raw/24-25.csv", 0.30),
    ("data/raw/25-26.csv", 0.40),
]

# Promoted teams + teams with stale Elo data
# Override with realistic starting ratings based on Championship performance.
#
# CORRECTED: previous values had Hull (1350) rated ABOVE Ipswich (1320),
# which is backwards -- confirmed against the final 2025/26 Championship
# table: Coventry finished 1st (champions), Ipswich 2nd, Hull 6th. Ipswich
# should never have been rated below a team that finished 4 places behind
# them. New values preserve Coventry's correctly-highest rating and fix
# the Ipswich/Hull ordering to match final league position. Still
# estimates (not derived from a full Elo simulation of Championship
# results), same caveat as before -- just no longer internally
# contradictory.
#
# NOTE: these values are specific to the 2026/27 season's promoted
# clubs. They are ONLY valid for live production use via the __main__
# block below (which passes them explicitly) -- do NOT reuse them for
# backtesting any other season. See build_snapshot_elo.py, which
# deliberately passes promoted_overrides=None for exactly this reason.
PROMOTED_RATINGS = {
    "Coventry City": 1380,  # Champions, unchanged -- was already correctly highest
    # 2nd place -- was 1320 (lower than Hull), now correctly above Hull
    "Ipswich":       1360,
    # 6th place -- was 1350 (higher than Ipswich), now correctly below Ipswich
    "Hull City":     1310,
}


def expected_score(rating_a: float, rating_b: float) -> float:
    """Expected score for team A against team B."""
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def update_elo(
    home_rating: float,
    away_rating: float,
    home_goals:  int,
    away_goals:  int,
    k: float = K_FACTOR,
) -> tuple:
    """
    Update Elo ratings after a match.
    Returns (new_home_rating, new_away_rating).
    Goal difference multiplier rewards bigger wins.
    """
    home_adj = home_rating + HOME_ADVANTAGE
    exp_home = expected_score(home_adj, away_rating)
    exp_away = 1 - exp_home

    if home_goals > away_goals:
        actual_home, actual_away = 1.0, 0.0
    elif home_goals < away_goals:
        actual_home, actual_away = 0.0, 1.0
    else:
        actual_home, actual_away = 0.5, 0.5

    goal_diff = abs(home_goals - away_goals)
    if goal_diff <= 1:
        multiplier = 1.0
    elif goal_diff == 2:
        multiplier = 1.5
    else:
        multiplier = 1.75

    new_home = home_rating + k * multiplier * (actual_home - exp_home)
    new_away = away_rating + k * multiplier * (actual_away - exp_away)

    return round(new_home, 1), round(new_away, 1)


def initialise_ratings(train_files: list, promoted_overrides: dict = None) -> dict:
    """
    Build Elo ratings from historical match data.
    All teams start at 1500, ratings evolve through however many
    seasons are passed in train_files.

    train_files: list of (filepath, weight) tuples. Caller controls
    exactly which seasons are visible -- this is what makes the same
    function usable for both live production ratings (all seasons,
    passed explicitly from TRAIN_FILES in __main__) and a point-in-time
    backtest snapshot (only seasons up to a cutoff, see
    build_snapshot_elo.py).

    promoted_overrides: optional {team: rating} dict, applied AFTER
    training data is processed. Defaults to None -- overrides are never
    applied unless the caller explicitly asks for them, since a wrong
    override (a rating from the wrong season) is worse than no override
    at all. When None, teams with no training-data appearances simply
    fall back to BASE_RATING, which is the honest "no prior data" state
    for a backtest involving a promoted team not covered by the training
    seasons.
    """
    ratings = {}

    def get_rating(team: str) -> float:
        if team not in ratings:
            ratings[team] = BASE_RATING
        return ratings[team]

    for filepath, weight in train_files:
        if not os.path.exists(filepath):
            print(f"  [SKIP] {filepath} not found")
            continue

        season_k = K_FACTOR * (1 + weight)

        matches = []
        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get("HomeTeam") or not row.get("FTHG"):
                    continue
                try:
                    matches.append({
                        "home": row["HomeTeam"],
                        "away": row["AwayTeam"],
                        "hg":   int(float(row["FTHG"])),
                        "ag":   int(float(row["FTAG"])),
                    })
                except (ValueError, TypeError):
                    continue

        print(f"  {filepath}: {len(matches)} matches (K={season_k:.0f})")

        for m in matches:
            home_r = get_rating(m["home"])
            away_r = get_rating(m["away"])
            new_h, new_a = update_elo(
                home_r, away_r, m["hg"], m["ag"], season_k
            )
            ratings[m["home"]] = new_h
            ratings[m["away"]] = new_a

    if promoted_overrides:
        print("\n  Applying promoted team overrides:")
        for team, rating in promoted_overrides.items():
            old = f"{ratings[team]:.0f}" if team in ratings else "NEW"
            ratings[team] = rating
            print(f"    {team:<20} {old} → {rating}")

    return ratings


def predict_result_elo(
    home_team: str,
    away_team: str,
    ratings:   dict,
) -> dict:
    """
    Predict match result probabilities from Elo ratings.
    Returns home win, draw, away win probabilities.
    """
    home_r = ratings.get(home_team, BASE_RATING)
    away_r = ratings.get(away_team, BASE_RATING)

    home_adj = home_r + HOME_ADVANTAGE
    exp_home = expected_score(home_adj, away_r)
    exp_away = expected_score(away_r, home_adj)

    rating_diff = abs(home_adj - away_r)
    draw_prob = max(0.10, 0.28 - (rating_diff / 2000))

    home_win = exp_home * (1 - draw_prob / 2)
    away_win = exp_away * (1 - draw_prob / 2)

    total = home_win + draw_prob + away_win
    home_win = home_win / total
    away_win = away_win / total
    draw = draw_prob / total

    return {
        "home_win":     round(home_win, 3),
        "draw":         round(draw, 3),
        "away_win":     round(away_win, 3),
        "home_or_draw": round(home_win + draw, 3),
        "away_or_draw": round(away_win + draw, 3),
        "home_elo":     home_r,
        "away_elo":     away_r,
        "elo_diff":     round(home_r - away_r, 0),
    }


def save_ratings(ratings: dict, path: str = ELO_FILE):
    """Save Elo ratings to JSON. Pass a different path to write a
    snapshot without touching the live production file."""
    os.makedirs("data", exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "updated_at":  datetime.now().isoformat(),
            "base_rating": BASE_RATING,
            "ratings":     ratings,
        }, f, indent=2)
    print(f"\nSaved {len(ratings)} Elo ratings → {path}")


def load_ratings(path: str = ELO_FILE) -> dict:
    """Load Elo ratings from JSON. Pass a different path to load a
    snapshot instead of the live production file."""
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)["ratings"]


def settle_elo(
    home_team:  str,
    away_team:  str,
    home_goals: int,
    away_goals: int,
):
    """Update Elo ratings after a real match result."""
    ratings = load_ratings()
    if not ratings:
        print("[ERROR] No Elo ratings found. Run initialise first.")
        return

    home_r = ratings.get(home_team, BASE_RATING)
    away_r = ratings.get(away_team, BASE_RATING)

    new_h, new_a = update_elo(home_r, away_r, home_goals, away_goals)

    print(f"{home_team}: {home_r} → {new_h} ({new_h - home_r:+.1f})")
    print(f"{away_team}: {away_r} → {new_a} ({new_a - away_r:+.1f})")

    ratings[home_team] = new_h
    ratings[away_team] = new_a
    save_ratings(ratings)


if __name__ == "__main__":
    print("Initialising EPL Elo ratings...\n")
    ratings = initialise_ratings(TRAIN_FILES, PROMOTED_RATINGS)
    save_ratings(ratings)

    print("\nEPL Elo Rankings (2026/27 season start):")
    print(f"{'Rank':<5} {'Team':<25} {'Rating':>7}  {'Bar'}")
    print("-" * 60)

    seen = set()
    rank = 1
    ranked = sorted(ratings.items(), key=lambda x: x[1], reverse=True)
    for team, rating in ranked:
        if team in seen:
            continue
        seen.add(team)
        bar = "█" * max(0, int((rating - 1300) / 20))
        print(f"  {rank:>2}. {team:<25} {rating:>7.1f}  {bar}")
        rank += 1

    print("\nSample predictions:")
    tests = [
        ("Arsenal",       "Chelsea"),
        ("Man City",      "Liverpool"),
        ("Ipswich",       "Sunderland"),
        ("Nott'm Forest", "Leeds"),
        ("Arsenal",       "Coventry City"),
        ("Hull City",     "Man United"),
    ]
    for home, away in tests:
        pred = predict_result_elo(home, away, ratings)
        print(
            f"  {home:<20} vs {away:<20} "
            f"H {pred['home_win']:.0%} / "
            f"D {pred['draw']:.0%} / "
            f"A {pred['away_win']:.0%} "
            f"(Elo: {pred['home_elo']:.0f} vs {pred['away_elo']:.0f})"
        )
