"""
Manager Intelligence Engine.

Key insight: Teams are not static entities. When a manager changes,
the team's tactical identity, formation, pressing intensity, and
defensive structure can change significantly.

This engine:
1. Tracks current and historical managers for each team
2. Models tactical identity per manager
3. Applies a confidence penalty when a new manager has recently
   been appointed (not enough data to trust historical stats)
4. Adjusts match predictions based on tactical matchups

For the World Cup specifically:
- Manager continuity is HIGH (most have been in post 2+ years)
- Tactical familiarity matters enormously at tournament level
- Teams that recently changed manager are at a disadvantage
"""

import json
import os
from datetime import datetime, date
from dataclasses import dataclass, asdict
from typing import Optional

MANAGERS_FILE = "data/managers.json"


@dataclass
class Manager:
    name: str
    appointed: str          # ISO date string YYYY-MM-DD
    nationality: str
    previous_clubs: list
    formation: str          # Primary formation e.g. "4-3-3"
    style: str              # "possession" | "counter" | "pressing" | "defensive"
    pressing_intensity: str  # "high" | "medium" | "low"
    defensive_line: str     # "high" | "medium" | "deep"
    notes: str = ""


@dataclass
class TeamManagerProfile:
    team_name: str
    current_manager: Manager
    previous_manager: Optional[dict] = None
    manager_change_date: Optional[str] = None
    games_under_current_manager: int = 0
    win_rate_under_current: float = 0.0


# World Cup 2026 — Manager Database
# Tracking all 48 qualified nations
WORLD_CUP_MANAGERS = {
    # GROUP A
    "Mexico": {
        "manager": "Javier Aguirre",
        "appointed": "2023-08-01",
        "nationality": "Mexican",
        "formation": "4-3-3",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Second spell. Pragmatic, defensive-minded. Prioritises organisation over possession."
    },
    "South Africa": {
        "manager": "Hugo Broos",
        "appointed": "2021-05-01",
        "nationality": "Belgian",
        "formation": "4-4-2",
        "style": "defensive",
        "pressing_intensity": "low",
        "defensive_line": "deep",
        "notes": "Experienced. Built Bafana Bafana into AFCON qualifiers. Disciplined structure."
    },
    "Korea Republic": {
        "manager": "Hong Myung-bo",
        "appointed": "2023-02-27",
        "nationality": "South Korean",
        "formation": "4-2-3-1",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Former national team captain. Transition period after Klinsmann dismissal."
    },
    "Czechia": {
        "manager": "Ivan Hasek",
        "appointed": "2023-11-01",
        "nationality": "Czech",
        "formation": "4-2-3-1",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Relatively new appointment. Czech style — technical, structured."
    },

    # GROUP B
    "Canada": {
        "manager": "Jesse Marsch",
        "appointed": "2023-12-01",
        "nationality": "American",
        "formation": "4-3-3",
        "style": "pressing",
        "pressing_intensity": "high",
        "defensive_line": "high",
        "notes": "High energy pressing system. Former RB Leipzig coach. Brings European intensity."
    },
    "Bosnia and Herzegovina": {
        "manager": "Sergej Barbarez",
        "appointed": "2023-01-01",
        "nationality": "Bosnian",
        "formation": "4-2-3-1",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Former national team striker. First major coaching role at senior international level."
    },
    "Qatar": {
        "manager": "Marquez Lopez",
        "appointed": "2023-06-01",
        "nationality": "Spanish",
        "formation": "4-3-3",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Spanish influence. Qatar investing heavily in football infrastructure."
    },
    "Switzerland": {
        "manager": "Murat Yakin",
        "appointed": "2021-08-01",
        "nationality": "Swiss",
        "formation": "3-4-3",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Solid continuity. Led Switzerland to excellent Euros 2024 campaign. Tactically flexible."
    },

    # GROUP C
    "Brazil": {
        "manager": "Dorival Junior",
        "appointed": "2024-01-06",
        "nationality": "Brazilian",
        "formation": "4-2-3-1",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Restored stability after turbulent period. More pragmatic than previous coaches."
    },
    "Morocco": {
        "manager": "Walid Regragui",
        "appointed": "2022-08-31",
        "nationality": "Moroccan",
        "formation": "4-3-3",
        "style": "counter",
        "pressing_intensity": "high",
        "defensive_line": "medium",
        "notes": "World Cup 2022 semifinalist. Excellent defensive organisation. Counter-attacking threat."
    },
    "Haiti": {
        "manager": "Marc Collat",
        "appointed": "2023-01-01",
        "nationality": "French",
        "formation": "4-4-2",
        "style": "defensive",
        "pressing_intensity": "low",
        "defensive_line": "deep",
        "notes": "Underdog. Will park the bus against top teams."
    },
    "Scotland": {
        "manager": "Steve Clarke",
        "appointed": "2019-05-16",
        "nationality": "Scottish",
        "formation": "3-4-3",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Long tenure — excellent stability. Consistent performer. Hard to beat defensively."
    },

    # GROUP D
    "United States": {
        "manager": "Mauricio Pochettino",
        "appointed": "2023-12-05",
        "nationality": "Argentinian",
        "formation": "4-3-3",
        "style": "pressing",
        "pressing_intensity": "high",
        "defensive_line": "high",
        "notes": "High-profile appointment. Pressing system, demands high energy. Tactical upgrade."
    },
    "Paraguay": {
        "manager": "Daniel Garnero",
        "appointed": "2023-03-01",
        "nationality": "Argentinian",
        "formation": "4-4-2",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Solid CONMEBOL qualifying campaign."
    },
    "Australia": {
        "manager": "Tony Popovic",
        "appointed": "2024-10-01",
        "nationality": "Australian",
        "formation": "4-3-3",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Relatively new. Replaced Graham Arnold. Building his own identity."
    },
    "Turkiye": {
        "manager": "Vincenzo Montella",
        "appointed": "2023-08-03",
        "nationality": "Italian",
        "formation": "4-2-3-1",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Excellent Euros 2024 campaign. Italian tactical discipline. Technically strong setup."
    },

    # GROUP E
    "Germany": {
        "manager": "Julian Nagelsmann",
        "appointed": "2023-09-22",
        "nationality": "German",
        "formation": "4-2-3-1",
        "style": "pressing",
        "pressing_intensity": "high",
        "defensive_line": "high",
        "notes": "Excellent Euros 2024 host. High pressing, vertical football. Germany rejuvenated."
    },
    "Curacao": {
        "manager": "Frédéric Née",
        "appointed": "2022-01-01",
        "nationality": "French",
        "formation": "4-4-2",
        "style": "defensive",
        "pressing_intensity": "low",
        "defensive_line": "deep",
        "notes": "First World Cup. Will be extremely defensive against Germany and Ecuador."
    },
    "Ivory Coast": {
        "manager": "Emerse Faé",
        "appointed": "2024-01-15",
        "nationality": "Ivorian",
        "formation": "4-3-3",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "AFCON 2024 winner. Hero appointment after Peseiro sacking mid-tournament."
    },
    "Ecuador": {
        "manager": "Sebastián Beccacece",
        "appointed": "2023-12-01",
        "nationality": "Argentinian",
        "formation": "4-4-2",
        "style": "pressing",
        "pressing_intensity": "high",
        "defensive_line": "high",
        "notes": "Aggressive pressing system. Physical, direct."
    },

    # GROUP F
    "Netherlands": {
        "manager": "Ronald Koeman",
        "appointed": "2023-07-01",
        "nationality": "Dutch",
        "formation": "4-3-3",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "high",
        "notes": "Euro 2024 finalist. Dutch total football principles. Quality throughout."
    },
    "Japan": {
        "manager": "Hajime Moriyasu",
        "appointed": "2018-07-26",
        "nationality": "Japanese",
        "formation": "4-2-3-1",
        "style": "pressing",
        "pressing_intensity": "high",
        "defensive_line": "medium",
        "notes": "Long tenure — outstanding World Cup 2022. High energy pressing. Famous for giant-killing."
    },
    "Sweden": {
        "manager": "Jon Dahl Tomasson",
        "appointed": "2022-06-21",
        "nationality": "Danish",
        "formation": "4-4-2",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Swedish pragmatism. Hard to break down. Strong set pieces."
    },
    "Tunisia": {
        "manager": "Jalel Kadri",
        "appointed": "2021-12-01",
        "nationality": "Tunisian",
        "formation": "4-3-3",
        "style": "defensive",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Disciplined. Will look to frustrate bigger sides."
    },

    # GROUP G
    "Belgium": {
        "manager": "Domenico Tedesco",
        "appointed": "2023-02-01",
        "nationality": "Italian-German",
        "formation": "3-4-3",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Last chance for golden generation. Tactically flexible with quality players."
    },
    "Egypt": {
        "manager": "Hossam Hassan",
        "appointed": "2023-10-01",
        "nationality": "Egyptian",
        "formation": "4-2-3-1",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Salah-dependent. Will look to exploit wide areas."
    },
    "IR Iran": {
        "manager": "Amir Ghalenoei",
        "appointed": "2023-06-01",
        "nationality": "Iranian",
        "formation": "4-3-3",
        "style": "defensive",
        "pressing_intensity": "low",
        "defensive_line": "deep",
        "notes": "Pragmatic. Physical. Difficult to beat. Strong team spirit."
    },
    "New Zealand": {
        "manager": "Darren Bazeley",
        "appointed": "2023-01-01",
        "nationality": "New Zealander",
        "formation": "4-4-2",
        "style": "defensive",
        "pressing_intensity": "low",
        "defensive_line": "deep",
        "notes": "Will be extremely defensive. Physical. Set piece threat."
    },

    # GROUP H
    "Spain": {
        "manager": "Luis de la Fuente",
        "appointed": "2023-01-01",
        "nationality": "Spanish",
        "formation": "4-3-3",
        "style": "possession",
        "pressing_intensity": "high",
        "defensive_line": "high",
        "notes": "Euro 2024 winner. Young, dynamic squad. Tiki-taka evolved. Heavy favourites."
    },
    "Cape Verde": {
        "manager": "Bubista",
        "appointed": "2020-01-01",
        "nationality": "Cape Verdean",
        "formation": "4-4-2",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Long tenure. Excellent AFCON campaigns. Will be dangerous on counter."
    },
    "Saudi Arabia": {
        "manager": "Herve Renard",
        "appointed": "2023-08-01",
        "nationality": "French",
        "formation": "4-3-3",
        "style": "pressing",
        "pressing_intensity": "high",
        "defensive_line": "medium",
        "notes": "Famous for beating Argentina in 2022. High line, high press. Tactically brave."
    },
    "Uruguay": {
        "manager": "Marcelo Bielsa",
        "appointed": "2023-06-01",
        "nationality": "Argentinian",
        "formation": "3-3-1-3",
        "style": "pressing",
        "pressing_intensity": "high",
        "defensive_line": "high",
        "notes": "El Loco. Most distinctive tactical identity in football. Extreme high press. Unpredictable."
    },

    # GROUP I
    "France": {
        "manager": "Didier Deschamps",
        "appointed": "2012-07-08",
        "nationality": "French",
        "formation": "4-3-3",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Longest serving elite manager. Ultra pragmatic. Won 2018 WC. Finals machine."
    },
    "Senegal": {
        "manager": "Aliou Cissé",
        "appointed": "2015-03-07",
        "nationality": "Senegalese",
        "formation": "4-3-3",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "AFCON winner 2022. Long tenure = excellent cohesion. Physical, direct, dangerous."
    },
    "Iraq": {
        "manager": "Jesus Casas",
        "appointed": "2023-01-01",
        "nationality": "Spanish",
        "formation": "4-2-3-1",
        "style": "defensive",
        "pressing_intensity": "low",
        "defensive_line": "deep",
        "notes": "Will be defensive. First World Cup in decades. Punching above weight."
    },
    "Norway": {
        "manager": "Stale Solbakken",
        "appointed": "2022-01-01",
        "nationality": "Norwegian",
        "formation": "4-3-3",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Haaland-dependent. Direct, physical, dangerous on transition."
    },

    # GROUP J
    "Argentina": {
        "manager": "Lionel Scaloni",
        "appointed": "2018-08-01",
        "nationality": "Argentinian",
        "formation": "4-4-2",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "World Cup 2022 winner. Copa America winner. Tactically brilliant. Messi's last dance."
    },
    "Algeria": {
        "manager": "Vladimir Petkovic",
        "appointed": "2023-01-01",
        "nationality": "Swiss-Bosnian",
        "formation": "4-3-3",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Experienced. Former Switzerland manager. Rebuilding Algeria after AFCON disappointments."
    },
    "Austria": {
        "manager": "Ralf Rangnick",
        "appointed": "2022-07-01",
        "nationality": "German",
        "formation": "4-2-3-1",
        "style": "pressing",
        "pressing_intensity": "high",
        "defensive_line": "high",
        "notes": "Godfather of gegenpressing. Transformed Austria. Excellent Euros 2024."
    },
    "Jordan": {
        "manager": "Hussein Ammouta",
        "appointed": "2023-01-01",
        "nationality": "Moroccan",
        "formation": "4-4-2",
        "style": "defensive",
        "pressing_intensity": "low",
        "defensive_line": "deep",
        "notes": "Will be defensive. AFCON final 2024 was overachievement. Organised."
    },

    # GROUP K
    "Portugal": {
        "manager": "Roberto Martinez",
        "appointed": "2023-01-06",
        "nationality": "Spanish",
        "formation": "4-3-3",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Former Belgium manager. Excellent squad depth. Post-Ronaldo transition ongoing."
    },
    "DR Congo": {
        "manager": "Sébastien Desabre",
        "appointed": "2023-01-01",
        "nationality": "French",
        "formation": "4-3-3",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Athletic, physical. AFCON semifinalists. Dangerous on the break."
    },
    "Uzbekistan": {
        "manager": "Srecko Katanec",
        "appointed": "2022-01-01",
        "nationality": "Slovenian",
        "formation": "4-2-3-1",
        "style": "defensive",
        "pressing_intensity": "low",
        "defensive_line": "medium",
        "notes": "First World Cup. Will be pragmatic and hard to break down."
    },
    "Colombia": {
        "manager": "Nestor Lorenzo",
        "appointed": "2022-07-01",
        "nationality": "Argentinian",
        "formation": "4-2-3-1",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Copa America 2024 finalists. Excellent qualifying campaign. Dangerous side."
    },

    # GROUP L
    "England": {
        "manager": "Thomas Tuchel",
        "appointed": "2024-10-16",
        "nationality": "German",
        "formation": "4-2-3-1",
        "style": "pressing",
        "pressing_intensity": "high",
        "defensive_line": "high",
        "notes": "NEW MANAGER — replaced Southgate. German pressing philosophy. Tactical upgrade expected."
    },
    "Croatia": {
        "manager": "Zlatko Dalic",
        "appointed": "2017-10-07",
        "nationality": "Croatian",
        "formation": "4-3-3",
        "style": "possession",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Long tenure. WC 2018 finalist, WC 2022 third place. Experienced. Modric era ending."
    },
    "Ghana": {
        "manager": "Otto Addo",
        "appointed": "2024-09-01",
        "nationality": "Ghanaian-German",
        "formation": "4-2-3-1",
        "style": "counter",
        "pressing_intensity": "medium",
        "defensive_line": "medium",
        "notes": "Second spell. Physical, direct. Building young squad."
    },
    "Panama": {
        "manager": "Thomas Christiansen",
        "appointed": "2022-01-01",
        "nationality": "Danish-Spanish",
        "formation": "4-4-2",
        "style": "defensive",
        "pressing_intensity": "low",
        "defensive_line": "deep",
        "notes": "Will be extremely defensive vs England and Croatia. Set piece oriented."
    },
}

# How much to reduce confidence for recently appointed managers
# The newer the manager, the less we trust historical team statistics
MANAGER_TENURE_CONFIDENCE = {
    "0-3 months": 0.70,    # 30% reduction in statistical confidence
    "3-6 months": 0.80,    # 20% reduction
    "6-12 months": 0.90,   # 10% reduction
    "12+ months": 1.00,    # Full confidence
}

# Tactical matchup advantages
# How much to adjust probabilities based on style matchups
TACTICAL_MATCHUP_ADJUSTMENTS = {
    # Press vs possession = slight press advantage
    ("pressing", "possession"): 0.03,
    # Counter vs possession = slight counter advantage
    ("counter", "possession"): 0.02,
    # Press vs deep block = press advantage
    ("pressing", "defensive"): 0.04,
    # Possession vs counter = slight disadvantage
    ("possession", "counter"): -0.02,
    # Defensive vs counter = slight defensive advantage
    ("defensive", "counter"): 0.01,
}


class ManagerIntelligence:
    """
    Manager Intelligence Engine.

    Tracks managerial profiles and applies tactical adjustments
    to base Elo predictions.

    Works as a multiplier layer ON TOP of EloModel predictions.
    Does not replace Elo — enhances it.
    """

    def __init__(self):
        self.managers = self._load_managers()

    def _load_managers(self):
        if os.path.exists(MANAGERS_FILE):
            with open(MANAGERS_FILE, "r") as f:
                data = json.load(f)
            print(f"[MANAGER] Loaded {len(data)} manager profiles from file")
            return data
        print(
            f"[MANAGER] Using initial database: {len(WORLD_CUP_MANAGERS)} teams")
        return WORLD_CUP_MANAGERS.copy()

    def save_managers(self):
        os.makedirs("data", exist_ok=True)
        with open(MANAGERS_FILE, "w") as f:
            json.dump(self.managers, f, indent=2)

    def get_manager(self, team_name):
        """Get manager profile for a team."""
        if team_name in self.managers:
            return self.managers[team_name]
        # Try alternate names
        alternates = {
            "USA": "United States",
            "Korea Republic": "Korea Republic",
            "IR Iran": "IR Iran",
            "Congo DR": "DR Congo",
            "Bosnia & Herzegovina": "Bosnia and Herzegovina",
            "Turkiye": "Turkiye",
        }
        alt = alternates.get(team_name)
        if alt and alt in self.managers:
            return self.managers[alt]
        return None

    def get_tenure_months(self, team_name):
        """Calculate how many months current manager has been in post."""
        profile = self.get_manager(team_name)
        if not profile:
            return 24  # Assume established if unknown

        try:
            appointed = datetime.strptime(
                profile["appointed"], "%Y-%m-%d"
            ).date()
            today = date.today()
            months = (today.year - appointed.year) * 12 + \
                     (today.month - appointed.month)
            return max(0, months)
        except:
            return 24

    def get_tenure_confidence(self, team_name):
        """
        Returns confidence multiplier based on manager tenure.
        New manager = lower confidence in historical stats.
        """
        months = self.get_tenure_months(team_name)

        if months < 3:
            return MANAGER_TENURE_CONFIDENCE["0-3 months"]
        elif months < 6:
            return MANAGER_TENURE_CONFIDENCE["3-6 months"]
        elif months < 12:
            return MANAGER_TENURE_CONFIDENCE["6-12 months"]
        else:
            return MANAGER_TENURE_CONFIDENCE["12+ months"]

    def get_tactical_adjustment(self, home_team, away_team):
        """
        Calculate probability adjustment based on tactical matchup.
        Returns (home_adj, away_adj) — adjustments to add to probabilities.
        """
        home_profile = self.get_manager(home_team)
        away_profile = self.get_manager(away_team)

        if not home_profile or not away_profile:
            return 0.0, 0.0

        home_style = home_profile.get("style", "")
        away_style = away_profile.get("style", "")

        # Check direct matchup
        home_adj = TACTICAL_MATCHUP_ADJUSTMENTS.get(
            (home_style, away_style), 0.0
        )
        away_adj = TACTICAL_MATCHUP_ADJUSTMENTS.get(
            (away_style, home_style), 0.0
        )

        return home_adj, away_adj

    def apply_manager_adjustments(self, base_prediction, home_team, away_team):
        """
        Apply manager intelligence adjustments to base Elo prediction.

        Adjustments made:
        1. Tactical matchup advantage/disadvantage
        2. Manager tenure confidence (new manager = wider uncertainty)

        Returns enhanced prediction dict.
        """
        probs = base_prediction["model_probability"].copy()

        home_profile = self.get_manager(home_team)
        away_profile = self.get_manager(away_team)

        # Tactical adjustment
        home_tactical_adj, away_tactical_adj = self.get_tactical_adjustment(
            home_team, away_team
        )

        # Tenure confidence
        home_confidence = self.get_tenure_confidence(home_team)
        away_confidence = self.get_tenure_confidence(away_team)
        combined_confidence = (home_confidence + away_confidence) / 2

        # Apply tactical adjustments
        home_prob = probs["home"] + (home_tactical_adj * 100)
        away_prob = probs["away"] + (away_tactical_adj * 100)
        draw_prob = probs["draw"]

        # Normalize
        total = home_prob + draw_prob + away_prob
        home_prob = round(home_prob / total * 100, 2)
        draw_prob = round(draw_prob / total * 100, 2)
        away_prob = round(100 - home_prob - draw_prob, 2)

        # Build enhanced prediction
        enhanced = base_prediction.copy()
        enhanced["model_probability"] = {
            "home": home_prob,
            "draw": draw_prob,
            "away": away_prob
        }
        enhanced["manager_intelligence"] = {
            "home_manager": home_profile.get("manager", "Unknown") if home_profile else "Unknown",
            "home_style": home_profile.get("style", "unknown") if home_profile else "unknown",
            "home_formation": home_profile.get("formation", "unknown") if home_profile else "unknown",
            "home_tenure_months": self.get_tenure_months(home_team),
            "home_confidence": home_confidence,
            "away_manager": away_profile.get("manager", "Unknown") if away_profile else "Unknown",
            "away_style": away_profile.get("style", "unknown") if away_profile else "unknown",
            "away_formation": away_profile.get("formation", "unknown") if away_profile else "unknown",
            "away_tenure_months": self.get_tenure_months(away_team),
            "away_confidence": away_confidence,
            "combined_confidence": combined_confidence,
            "tactical_matchup": f"{home_profile.get('style', '?') if home_profile else '?'} vs {away_profile.get('style', '?') if away_profile else '?'}",
            "home_tactical_adj": home_tactical_adj,
            "away_tactical_adj": away_tactical_adj,
            "base_probability": probs,
        }

        return enhanced

    def get_match_narrative(self, home_team, away_team):
        """
        Generate human-readable tactical narrative for a match.
        Used by the Explanation Engine later.
        """
        home = self.get_manager(home_team)
        away = self.get_manager(away_team)

        if not home or not away:
            return "Insufficient manager data for tactical analysis."

        home_months = self.get_tenure_months(home_team)
        away_months = self.get_tenure_months(away_team)

        narrative = []

        narrative.append(
            f"{home_team} ({home['manager']}, {home['formation']}, "
            f"{home['style']} style) vs "
            f"{away_team} ({away['manager']}, {away['formation']}, "
            f"{away['style']} style)"
        )

        # Tactical matchup comment
        matchup = f"{home['style']} vs {away['style']}"
        matchup_comments = {
            "pressing vs possession": f"{home_team}'s high press will look to disrupt {away_team}'s build-up play.",
            "possession vs counter": f"{away_team} will absorb pressure and look to exploit space behind {home_team}'s high line.",
            "counter vs possession": f"{home_team} will sit deep and look to hit {away_team} on the break.",
            "pressing vs defensive": f"{home_team}'s intensity should create chances but {away_team}'s deep block may frustrate.",
            "defensive vs pressing": f"{away_team}'s press vs {home_team}'s defensive structure — expect a physical battle.",
        }

        comment = matchup_comments.get(matchup, f"Tactical matchup: {matchup}")
        narrative.append(comment)

        # New manager warning
        if home_months < 6:
            narrative.append(
                f"⚠ {home_team}: {home['manager']} appointed only "
                f"{home_months} months ago — statistical confidence reduced."
            )
        if away_months < 6:
            narrative.append(
                f"⚠ {away_team}: {away['manager']} appointed only "
                f"{away_months} months ago — statistical confidence reduced."
            )

        # Notes
        if home.get("notes"):
            narrative.append(f"{home_team}: {home['notes']}")
        if away.get("notes"):
            narrative.append(f"{away_team}: {away['notes']}")

        return "\n  ".join(narrative)

    def print_all_managers(self):
        """Print full manager database."""
        print(f"\n{'='*65}")
        print(f"  WORLD CUP 2026 — MANAGER DATABASE")
        print(f"  {len(self.managers)} teams registered")
        print(f"{'='*65}\n")

        for group in "ABCDEFGHIJKL":
            from src.models.elo_model import WORLD_CUP_GROUPS
            teams = WORLD_CUP_GROUPS.get(group, [])
            print(f"  GROUP {group}")
            for team in teams:
                profile = self.get_manager(team)
                if profile:
                    months = self.get_tenure_months(team)
                    conf = self.get_tenure_confidence(team)
                    new_flag = " ⚠ NEW" if months < 6 else ""
                    print(f"  {team:<25} {profile['manager']:<25} "
                          f"{profile['formation']:<8} "
                          f"{months:>2}mo  conf:{conf:.0%}{new_flag}")
            print()


if __name__ == "__main__":
    intel = ManagerIntelligence()
    intel.print_all_managers()

    print(f"\n{'='*65}")
    print(f"  SAMPLE TACTICAL NARRATIVES")
    print(f"{'='*65}")

    test_matches = [
        ("Spain", "Uruguay"),
        ("Germany", "Curacao"),
        ("Argentina", "Algeria"),
        ("England", "Panama"),
        ("Brazil", "Morocco"),
    ]

    for home, away in test_matches:
        print(f"\n  {home} vs {away}")
        print(f"  {'-'*55}")
        narrative = intel.get_match_narrative(home, away)
        print(f"  {narrative}")
