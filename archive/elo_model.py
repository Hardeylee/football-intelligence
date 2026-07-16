"""
Elo Rating Model — National Teams
FIFA World Cup 2026 Edition

Only contains the 48 qualified nations.
Club football ratings live in elo_clubs.py (built when EPL season starts).

Architecture decision: Separate national and club rating pools entirely.
They measure different things and should never be mixed.
"""

import math
import json
import os
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# FIFA WORLD CUP 2026 — 48 QUALIFIED NATIONS
# Ratings based on: FIFA rankings, recent tournament performance,
# head-to-head records, and qualifying campaign strength
#
# Scale: 1500 = average international team
#        1700 = solid qualifier
#        1800 = strong contender
#        1900 = elite
#        2000+ = world class
# ============================================================

WORLD_CUP_2026_TEAMS = {
    # GROUP A
    "Mexico":           1820,
    "South Africa":     1660,
    "Korea Republic":   1770,  # SportyBet uses this name
    "South Korea":      1770,  # Alternative name mapping
    "Czechia":          1790,

    # GROUP B
    "Canada":           1750,
    "Bosnia and Herzegovina": 1730,
    "Bosnia & Herzegovina":   1730,  # Alternative spelling
    "Qatar":            1640,
    "Switzerland":      1900,

    # GROUP C
    "Brazil":           2050,
    "Morocco":          1830,
    "Haiti":            1620,
    "Scotland":         1770,

    # GROUP D
    "United States":    1800,
    "USA":              1800,  # SportyBet uses this
    "Paraguay":         1720,
    "Australia":        1740,
    "Turkey":           1810,
    "Turkiye":          1810,  # SportyBet uses this spelling

    # GROUP E
    "Germany":          1980,
    "Curacao":          1640,
    "Ivory Coast":      1730,
    "Ecuador":          1780,

    # GROUP F
    "Netherlands":      1950,
    "Japan":            1800,
    "Sweden":           1840,
    "Tunisia":          1720,

    # GROUP G
    "Belgium":          1920,
    "Egypt":            1740,
    "Iran":             1750,
    "IR Iran":          1750,  # SportyBet uses this
    "New Zealand":      1650,

    # GROUP H
    "Spain":            1990,
    "Cape Verde":       1680,
    "Saudi Arabia":     1690,
    "Uruguay":          1870,

    # GROUP I
    "France":           2020,
    "Senegal":          1800,
    "Iraq":             1660,
    "Norway":           1810,

    # GROUP J
    "Argentina":        2080,
    "Algeria":          1740,
    "Austria":          1810,
    "Jordan":           1620,

    # GROUP K
    "Portugal":         1960,
    "DR Congo":         1690,
    "Congo DR":         1690,  # Alternative name
    "Uzbekistan":       1640,
    "Colombia":         1830,

    # GROUP L
    "England":          1970,
    "Croatia":          1880,
    "Ghana":            1700,
    "Panama":           1680,
}

# Group structure for context-aware predictions
WORLD_CUP_GROUPS = {
    "A": ["Mexico", "South Africa", "Korea Republic", "Czechia"],
    "B": ["Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Australia", "Turkiye"],
    "E": ["Germany", "Curacao", "Ivory Coast", "Ecuador"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "IR Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "DR Congo", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}

ELO_FILE = "data/elo_ratings_national.json"

# ============================================================
# ELO CONSTANTS
# K_FACTOR: How much ratings shift per match
#   Higher = faster learning, more volatile
#   Lower  = more stable, slower to adapt
#   32 is standard for international football
#
# HOME_ADVANTAGE: World Cup is at neutral venues
#   Set to 0 for all matches
#   Will be configurable for EPL (estimated ~65 points)
#
# DRAW_CALIBRATION: Football-specific draw modeling
#   Draws occur ~25-28% in international football
#   Exponential decay — fewer draws in mismatched games
# ============================================================

K_FACTOR = 32
HOME_ADVANTAGE = 65
DRAW_CALIBRATION = 0.27


class EloModel:
    """
    Elo-based national team probability model.

    Responsibilities:
    - Store and update team ratings
    - Generate 1X2 match probabilities
    - Track rating history
    - Persist ratings between sessions

    Does NOT handle:
    - Club football (separate model)
    - Player availability adjustments (Player Impact Engine)
    - Manager changes (Manager Intelligence Engine)
    - Motivation factors (Context Engine)

    Those engines will apply multipliers ON TOP of this base probability.
    """

    def __init__(self):
        self.ratings = self._load_ratings()
        self.history = []

    def _load_ratings(self) -> dict:
        """
        Load ratings from file if exists, otherwise use initial ratings.
        File takes precedence — it contains learned ratings from results.
        """
        if os.path.exists(ELO_FILE):
            try:
                with open(ELO_FILE, "r") as f:
                    data = json.load(f)
                logger.info(
                    f"Loaded {len(data['ratings'])} team ratings from {ELO_FILE}")
                return data["ratings"]
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(
                    f"Could not load ratings file: {e}. Using initial ratings.")

        logger.info(
            f"Using initial ratings for {len(WORLD_CUP_2026_TEAMS)} World Cup teams")
        return WORLD_CUP_2026_TEAMS.copy()

    def save_ratings(self) -> None:
        """Persist current ratings to file."""
        os.makedirs("data", exist_ok=True)
        payload = {
            "updated_at": datetime.now().isoformat(),
            "total_teams": len(self.ratings),
            "model_version": "elo_national_v1",
            "ratings": self.ratings
        }
        with open(ELO_FILE, "w") as f:
            json.dump(payload, f, indent=2)
        logger.info(f"Ratings saved to {ELO_FILE}")

    def get_rating(self, team_name: str) -> float:
        """
        Get team rating by name.
        Handles name variations SportyBet uses vs our stored names.
        Returns None if team not in World Cup — caller decides how to handle.
        """
        # Exact match
        if team_name in self.ratings:
            return self.ratings[team_name]

        # Case-insensitive match
        for name, rating in self.ratings.items():
            if name.lower() == team_name.lower():
                return rating

        # Not found — log warning, return conservative default
        logger.warning(
            f"Team not found: '{team_name}' — not a 2026 World Cup qualifier? Using 1650.")
        return 1650

    def _expected_score(self, rating_a: float, rating_b: float) -> float:
        """
        Standard Elo expected score formula.
        Returns probability of team A winning (ignoring draws).
        Range: 0.0 to 1.0
        """
        return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))

    def _draw_probability(self, rating_diff: float) -> float:
        """
        Estimate draw probability based on rating difference.

        Key insight: Draws are most common when teams are closely matched.
        As rating gap grows, draws become less likely.

        Calibrated to ~27% draw rate for even matchups,
        dropping to ~8% for 400+ point gaps.
        """
        draw_prob = DRAW_CALIBRATION * math.exp(-abs(rating_diff) / 700.0)
        return max(0.06, min(0.32, draw_prob))

    def predict_match(
        self,
        home_team: str,
        away_team: str,
        neutral_venue: bool = True
    ) -> dict:
        """
        Generate 1X2 probabilities for a match.

        For World Cup: always neutral_venue=True (all matches in USA/Canada/Mexico)
        For EPL: neutral_venue=False (home advantage applies)

        Returns full prediction dict including ratings and metadata.
        Other engines (manager, player, motivation) apply adjustments
        to model_probability AFTER this base prediction.
        """
        home_rating = self.get_rating(home_team)
        away_rating = self.get_rating(away_team)

        # Home advantage only applies in domestic football
        advantage = 0 if neutral_venue else HOME_ADVANTAGE
        effective_home = home_rating + advantage

        # Base win expectancy (ignoring draws)
        home_win_base = self._expected_score(effective_home, away_rating)
        away_win_base = 1.0 - home_win_base

        # Draw probability
        rating_diff = effective_home - away_rating
        draw_prob = self._draw_probability(rating_diff)

        # Scale win probabilities to leave room for draw
        remaining = 1.0 - draw_prob
        home_prob = home_win_base * remaining
        away_prob = away_win_base * remaining

        # Normalize (floating point safety)
        total = home_prob + draw_prob + away_prob
        home_prob = home_prob / total
        draw_prob = draw_prob / total
        away_prob = away_prob / total

        return {
            "home_team": home_team,
            "away_team": away_team,
            "home_rating": home_rating,
            "away_rating": away_rating,
            "rating_diff": round(rating_diff, 1),
            "neutral_venue": neutral_venue,
            "model_probability": {
                "home": round(home_prob * 100, 2),
                "draw": round(draw_prob * 100, 2),
                "away": round(away_prob * 100, 2)
            },
            "model": "elo_national_v1",
            "generated_at": datetime.now().isoformat()
        }

    def update_from_result(
        self,
        home_team: str,
        away_team: str,
        result: str,
        neutral_venue: bool = True,
        weight: float = 1.0
    ) -> dict:
        """
        Update ratings after a match result.

        Args:
            result:  "home" | "draw" | "away"
            weight:  1.0 = normal, 1.5 = knockout, 0.5 = friendly
                     World Cup group stage = 1.0
                     World Cup knockout = 1.5

        Returns rating changes for logging.
        """
        home_rating = self.get_rating(home_team)
        away_rating = self.get_rating(away_team)

        advantage = 0 if neutral_venue else HOME_ADVANTAGE
        effective_home = home_rating + advantage
        home_expected = self._expected_score(effective_home, away_rating)

        # Actual outcome scores
        score_map = {
            "home": (1.0, 0.0),
            "draw": (0.5, 0.5),
            "away": (0.0, 1.0)
        }
        home_actual, away_actual = score_map[result]

        # Weighted K factor
        k = K_FACTOR * weight

        # Update
        new_home = home_rating + k * (home_actual - home_expected)
        new_away = away_rating + k * (away_actual - (1.0 - home_expected))

        self.ratings[home_team] = round(new_home, 1)
        self.ratings[away_team] = round(new_away, 1)

        change = {
            "home_team": home_team,
            "away_team": away_team,
            "result": result,
            "home_before": home_rating,
            "away_before": away_rating,
            "home_after": self.ratings[home_team],
            "away_after": self.ratings[away_team],
            "home_change": round(new_home - home_rating, 1),
            "away_change": round(new_away - away_rating, 1),
        }

        logger.info(
            f"Ratings updated: {home_team} {change['home_change']:+.1f} | "
            f"{away_team} {change['away_change']:+.1f} | Result: {result}"
        )

        self.history.append(change)
        return change

    def get_group_standings(self, group: str) -> list:
        """Return teams in a group sorted by current Elo rating."""
        teams = WORLD_CUP_GROUPS.get(group.upper(), [])
        return sorted(
            [(t, self.get_rating(t)) for t in teams],
            key=lambda x: x[1],
            reverse=True
        )

    def get_top_ratings(self, n: int = 20) -> list:
        """Return top N teams by current rating."""
        # Deduplicate (remove alternative name mappings)
        seen_ratings = {}
        for name, rating in self.ratings.items():
            if rating not in seen_ratings.values() or name not in [
                "South Korea", "USA", "Bosnia & Herzegovina",
                "Turkey", "IR Iran", "Congo DR"
            ]:
                seen_ratings[name] = rating

        return sorted(seen_ratings.items(), key=lambda x: x[1], reverse=True)[:n]

    def get_group_preview(self) -> None:
        """Print all groups with ratings — useful for tournament preview."""
        print(f"\n{'='*65}")
        print(f"  FIFA WORLD CUP 2026 — ELO RATINGS BY GROUP")
        print(f"{'='*65}")

        for group, teams in WORLD_CUP_GROUPS.items():
            print(f"\n  GROUP {group}")
            print(f"  {'-'*40}")
            for team in teams:
                rating = self.get_rating(team)
                bar = "█" * int((rating - 1600) / 30)
                print(f"  {team:<25} {rating:>4}  {bar}")


if __name__ == "__main__":
    model = EloModel()

    # Show group preview
    model.get_group_preview()

    print(f"\n\n{'='*65}")
    print(f"  TOP 20 TEAMS BY ELO RATING")
    print(f"{'='*65}")
    for i, (team, rating) in enumerate(model.get_top_ratings(20), 1):
        print(f"  {i:2}. {team:<25} {rating}")

    print(f"\n\n{'='*65}")
    print(f"  SAMPLE MATCH PREDICTIONS")
    print(f"{'='*65}")

    test_matches = [
        ("Brazil", "Morocco"),
        ("Argentina", "Algeria"),
        ("England", "Panama"),
        ("Portugal", "Uzbekistan"),
        ("France", "Haiti"),
        ("Germany", "Curacao"),
        ("Mexico", "South Africa"),
        ("Switzerland", "Qatar"),
    ]

    for home, away in test_matches:
        pred = model.predict_match(home, away, neutral_venue=True)
        p = pred["model_probability"]
        diff = pred["rating_diff"]
        print(f"\n  {home} vs {away}")
        print(
            f"  Ratings: {pred['home_rating']} vs {pred['away_rating']}  (diff: {diff:+.0f})")
        print(
            f"  Home: {p['home']:>5.1f}%  Draw: {p['draw']:>5.1f}%  Away: {p['away']:>5.1f}%")
