"""
Elo Rating Model for Football Match Probability Estimation.

Elo is a well-established rating system used by FIFA, chess, and 
professional betting syndicates as a baseline probability model.

Each team has a rating. Stronger teams have higher ratings.
The difference in ratings predicts match outcome probability.
"""

import math
import json
import os
from datetime import datetime

# World Cup 2026 team Elo ratings
# Source: Based on FIFA rankings + historical World Cup performance
# These are calibrated starting ratings — model updates them as results come in

INITIAL_ELO_RATINGS = {
    # Group A
    "Brazil": 2050,
    "Germany": 1980,
    "France": 2020,
    "Argentina": 2080,
    "England": 1970,
    "Spain": 1990,
    "Portugal": 1960,
    "Netherlands": 1950,
    "Belgium": 1920,
    "Italy": 1910,
    "Croatia": 1880,
    "Uruguay": 1870,
    "Mexico": 1820,
    "USA": 1800,
    "Colombia": 1830,
    "Ecuador": 1780,
    "Peru": 1760,
    "Chile": 1770,
    "Paraguay": 1720,
    "Venezuela": 1680,
    "Bolivia": 1640,
    "Canada": 1750,
    "Morocco": 1830,
    "Senegal": 1800,
    "Tunisia": 1720,
    "Egypt": 1740,
    "Nigeria": 1760,
    "Ghana": 1700,
    "Cameroon": 1710,
    "South Africa": 1660,
    "Ivory Coast": 1730,
    "Algeria": 1740,
    "Mali": 1680,
    "Australia": 1740,
    "Japan": 1800,
    "Korea Republic": 1770,
    "Iran": 1750,
    "Saudi Arabia": 1690,
    "Qatar": 1640,
    "China": 1600,
    "Indonesia": 1560,
    "Switzerland": 1900,
    "Denmark": 1880,
    "Poland": 1820,
    "Sweden": 1840,
    "Austria": 1810,
    "Czech Republic": 1790,
    "Czechia": 1790,
    "Slovakia": 1760,
    "Hungary": 1760,
    "Romania": 1740,
    "Serbia": 1820,
    "Ukraine": 1800,
    "Turkey": 1810,
    "Greece": 1730,
    "Scotland": 1770,
    "Wales": 1760,
    "Ireland": 1720,
    "Norway": 1810,
    "Finland": 1720,
    "Bosnia & Herzegovina": 1730,
    "Bosnia and Herzegovina": 1730,
    "Slovenia": 1730,
    "Albania": 1700,
    "Kosovo": 1670,
    "North Macedonia": 1680,
    "Montenegro": 1660,
    "Georgia": 1700,
    "Armenia": 1650,
    "Azerbaijan": 1600,
    "Uzbekistan": 1640,
    "Panama": 1680,
    "Jamaica": 1650,
    "Honduras": 1630,
    "Costa Rica": 1700,
    "New Zealand": 1650,
    "DR Congo": 1690,
    "Congo DR": 1690,
    "Jordan": 1620,
    "Iraq": 1660,
    "Kuwait": 1590,
    "Bahrain": 1580,
    "Oman": 1600,
    "UAE": 1610,
    "India": 1540,
    "Turkiye": 1810,
    "IR Iran": 1750,
    "Cape Verde": 1680,
    "Haiti": 1620,
    "Curacao": 1640,
    "AGF Aarhus": 1700,
    "KKS Lech Poznan": 1750,
}

ELO_FILE = "data/elo_ratings.json"

# Elo constants
K_FACTOR = 32          # How much ratings change per match
HOME_ADVANTAGE = 65    # Elo points added for home team (neutral = 0)
DRAW_FACTOR = 0.25     # Probability weight for draws in football


class EloModel:
    """
    Elo-based football match probability model.

    Core formula:
        Expected score = 1 / (1 + 10^((RatingB - RatingA) / 400))

    For football we convert expected score to 1X2 probabilities
    using a draw factor calibrated to historical data.
    """

    def __init__(self):
        self.ratings = self.load_ratings()
        self.match_history = []

    def load_ratings(self):
        """Load ratings from file or use initial ratings."""
        if os.path.exists(ELO_FILE):
            with open(ELO_FILE, "r") as f:
                data = json.load(f)
                print(
                    f"[ELO] Loaded {len(data['ratings'])} team ratings from file")
                return data["ratings"]
        else:
            print(
                f"[ELO] Using initial ratings for {len(INITIAL_ELO_RATINGS)} teams")
            return INITIAL_ELO_RATINGS.copy()

    def save_ratings(self):
        """Persist ratings to file."""
        os.makedirs("data", exist_ok=True)
        with open(ELO_FILE, "w") as f:
            json.dump({
                "updated_at": datetime.now().isoformat(),
                "total_teams": len(self.ratings),
                "ratings": self.ratings
            }, f, indent=2)

    def get_rating(self, team_name):
        """Get team rating, returning default for unknown teams."""
        # Try exact match first
        if team_name in self.ratings:
            return self.ratings[team_name]

        # Try case-insensitive match
        for name, rating in self.ratings.items():
            if name.lower() == team_name.lower():
                return rating

        # Unknown team — return conservative default
        print(
            f"  [ELO] Unknown team: '{team_name}' — using default rating 1650")
        return 1650

    def expected_score(self, rating_a, rating_b):
        """
        Calculate expected score for team A against team B.
        Returns value between 0 and 1 (like a probability).
        """
        return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

    def predict_match(self, home_team, away_team, neutral_venue=False):
        """
        Generate 1X2 probabilities for a match.

        Args:
            home_team: Name of home team
            away_team: Name of away team  
            neutral_venue: True for World Cup (no home advantage)

        Returns:
            Dict with home/draw/away probabilities and metadata
        """
        home_rating = self.get_rating(home_team)
        away_rating = self.get_rating(away_team)

        # Apply home advantage (0 for neutral World Cup venues)
        effective_home_rating = home_rating + \
            (0 if neutral_venue else HOME_ADVANTAGE)

        # Calculate expected scores
        home_expected = self.expected_score(effective_home_rating, away_rating)
        away_expected = 1 - home_expected

        # Convert to 1X2 probabilities
        # In football, draws occur ~25% of games
        # We model this by compressing home/away probs toward center

        # Draw probability: higher when teams are closely matched
        rating_diff = abs(effective_home_rating - away_rating)
        draw_prob = DRAW_FACTOR * math.exp(-rating_diff / 800)
        draw_prob = max(0.05, min(0.35, draw_prob))  # Clamp between 5-35%

        # Adjust home/away to account for draw
        remaining = 1 - draw_prob
        home_prob = home_expected * remaining
        away_prob = away_expected * remaining

        # Normalize to ensure they sum to 1.0
        total = home_prob + draw_prob + away_prob
        home_prob = round(home_prob / total, 4)
        draw_prob = round(draw_prob / total, 4)
        away_prob = round(1 - home_prob - draw_prob, 4)

        return {
            "home_team": home_team,
            "away_team": away_team,
            "home_rating": home_rating,
            "away_rating": away_rating,
            "rating_diff": round(effective_home_rating - away_rating, 1),
            "neutral_venue": neutral_venue,
            "model_probability": {
                "home": round(home_prob * 100, 2),
                "draw": round(draw_prob * 100, 2),
                "away": round(away_prob * 100, 2)
            },
            "model": "elo_v1",
            "generated_at": datetime.now().isoformat()
        }

    def update_ratings(self, home_team, away_team, result, neutral_venue=False):
        """
        Update Elo ratings after a match result.

        Args:
            result: "home" | "draw" | "away"
        """
        home_rating = self.get_rating(home_team)
        away_rating = self.get_rating(away_team)

        effective_home = home_rating + (0 if neutral_venue else HOME_ADVANTAGE)
        home_expected = self.expected_score(effective_home, away_rating)

        # Actual scores
        if result == "home":
            home_actual, away_actual = 1.0, 0.0
        elif result == "draw":
            home_actual, away_actual = 0.5, 0.5
        else:
            home_actual, away_actual = 0.0, 1.0

        # Update ratings
        new_home = home_rating + K_FACTOR * (home_actual - home_expected)
        new_away = away_rating + K_FACTOR * (away_actual - (1 - home_expected))

        self.ratings[home_team] = round(new_home, 1)
        self.ratings[away_team] = round(new_away, 1)

        return {
            "home_team": home_team,
            "away_team": away_team,
            "result": result,
            "home_rating_before": home_rating,
            "away_rating_before": away_rating,
            "home_rating_after": self.ratings[home_team],
            "away_rating_after": self.ratings[away_team],
        }

    def get_top_ratings(self, n=20):
        """Return top N teams by rating."""
        sorted_teams = sorted(
            self.ratings.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_teams[:n]


if __name__ == "__main__":
    model = EloModel()

    print("\n=== TOP 20 TEAMS BY ELO RATING ===")
    for i, (team, rating) in enumerate(model.get_top_ratings(20), 1):
        print(f"  {i:2}. {team:<25} {rating}")

    print("\n=== SAMPLE PREDICTIONS ===")
    test_matches = [
        ("Portugal", "Congo DR", True),
        ("England", "Croatia", True),
        ("Mexico", "Korea Republic", True),
        ("Canada", "Qatar", True),
        ("Switzerland", "Bosnia & Herzegovina", True),
    ]

    for home, away, neutral in test_matches:
        pred = model.predict_match(home, away, neutral_venue=neutral)
        probs = pred["model_probability"]
        print(f"\n  {home} vs {away}")
        print(f"  Ratings: {pred['home_rating']} vs {pred['away_rating']}")
        print(
            f"  Model:   Home {probs['home']}%  Draw {probs['draw']}%  Away {probs['away']}%")
