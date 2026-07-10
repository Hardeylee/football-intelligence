"""
EPL Manager Profiles — 2026/27 Season
Tactical profiles for all 20 EPL managers.
Used to adjust cards, corners, and goals market predictions.

Attributes per manager:
- pressing_intensity: how high and hard they press (0-10)
- defensive_line: how high the defensive line sits (0-10)
- attacking_tempo: speed and directness of attack (0-10)
- set_piece_focus: emphasis on set pieces (0-10)
- foul_tendency: how often team commits fouls (0-10)
- style: broad tactical label
- cards_modifier: adjustment to cards probability (-0.15 to +0.15)
- corners_modifier: adjustment to corners probability (-0.15 to +0.15)
- goals_modifier: adjustment to goals probability (-0.10 to +0.10)
"""

EPL_MANAGER_PROFILES = {

    "Arsenal": {
        "manager":            "Mikel Arteta",
        "style":              "High Press / Possession",
        "formation":          "4-3-3",
        "pressing_intensity": 9,
        "defensive_line":     8,
        "attacking_tempo":    7,
        "set_piece_focus":    8,
        "foul_tendency":      5,
        "cards_modifier":     0.05,   # High press = slightly more cards
        "corners_modifier": -0.05,  # Possession team = fewer corners needed
        "goals_modifier":     0.05,   # Clinical attack
        "notes": "Arteta's Arsenal dominate possession and press high. Strong set piece taker. Defensively organized."
    },

    "Aston Villa": {
        "manager":            "Unai Emery",
        "style":              "Structured Attack / Counter",
        "formation":          "4-2-3-1",
        "pressing_intensity": 7,
        "defensive_line":     6,
        "attacking_tempo":    7,
        "set_piece_focus":    7,
        "foul_tendency":      6,
        "cards_modifier":     0.05,
        "corners_modifier":   0.05,
        "goals_modifier":     0.05,
        "notes": "Emery builds compact defensive shape then attacks quickly. Good at set pieces. European football pedigree."
    },

    "Bournemouth": {
        "manager":            "Marco Rose",
        "style":              "High Press / Vertical",
        "formation":          "4-2-3-1",
        "pressing_intensity": 8,
        "defensive_line":     7,
        "attacking_tempo":    8,
        "set_piece_focus":    5,
        "foul_tendency":      7,
        "cards_modifier":     0.08,   # Aggressive pressing = more cards
        "corners_modifier":   0.05,
        "goals_modifier":     0.05,
        "notes": "Rose's teams press aggressively and play vertical football. Higher card rates due to pressing intensity."
    },

    "Brentford": {
        "manager":            "Keith Andrews",
        "style":              "Direct / Set Piece Focused",
        "formation":          "4-3-3",
        "pressing_intensity": 6,
        "defensive_line":     5,
        "attacking_tempo":    7,
        "set_piece_focus":    9,
        "foul_tendency":      6,
        "cards_modifier":     0.03,
        "corners_modifier":   0.08,   # Set piece heavy = more corners
        "goals_modifier":     0.00,
        "notes": "Brentford DNA of set piece dominance continues. Direct play wins corners. New manager, same philosophy."
    },

    "Brighton": {
        "manager":            "Fabian Hurzeler",
        "style":              "Possession / High Press",
        "formation":          "4-2-3-1",
        "pressing_intensity": 8,
        "defensive_line":     8,
        "attacking_tempo":    7,
        "set_piece_focus":    6,
        "foul_tendency":      5,
        "cards_modifier":     0.03,
        "corners_modifier": -0.03,
        "goals_modifier":     0.03,
        "notes": "Continues De Zerbi's possession principles. Technical, press-oriented, positional play."
    },

    "Chelsea": {
        "manager":            "Xabi Alonso",
        "style":              "Possession / Structured",
        "formation":          "4-2-3-1",
        "pressing_intensity": 7,
        "defensive_line":     7,
        "attacking_tempo":    7,
        "set_piece_focus":    6,
        "foul_tendency":      5,
        "cards_modifier":     0.00,
        "corners_modifier":   0.00,
        "goals_modifier":     0.03,
        "notes": "Alonso's Leverkusen were organized, possession-based and clinical. Expects similar Chelsea approach."
    },

    "Coventry City": {
        "manager":            "Frank Lampard",
        "style":              "Attacking / Direct",
        "formation":          "4-3-3",
        "pressing_intensity": 6,
        "defensive_line":     5,
        "attacking_tempo":    7,
        "set_piece_focus":    6,
        "foul_tendency":      6,
        "cards_modifier":     0.03,
        "corners_modifier":   0.05,
        "goals_modifier":     0.00,
        "notes": "Lampard favors attacking football but defensively can be vulnerable. Promoted side adjusting to EPL."
    },

    "Crystal Palace": {
        "manager":            "Pierre Sage",
        "style":              "Counter Attack / Organized",
        "formation":          "4-4-2",
        "pressing_intensity": 5,
        "defensive_line":     4,
        "attacking_tempo":    6,
        "set_piece_focus":    6,
        "foul_tendency":      6,
        "cards_modifier":     0.05,   # Physical, counter-attacking style
        "corners_modifier":   0.05,
        "goals_modifier": -0.03,  # Defensive-first approach
        "notes": "Sage impressed at Lyon with organized defensive structure and quick transitions."
    },

    "Everton": {
        "manager":            "David Moyes",
        "style":              "Defensive / Organized",
        "formation":          "4-5-1 / 4-4-2",
        "pressing_intensity": 4,
        "defensive_line":     4,
        "attacking_tempo":    5,
        "set_piece_focus":    7,
        "foul_tendency":      7,
        "cards_modifier":     0.08,   # Physical, defensive — high foul rate
        "corners_modifier":   0.05,
        "goals_modifier": -0.05,  # Low scoring matches
        "notes": "Moyes is pragmatic and defensive. Teams typically grind results. High foul rates, set piece reliant."
    },

    "Fulham": {
        "manager":            "Alvaro Arbeloa",
        "style":              "Structured / Defensive",
        "formation":          "4-4-2 / 4-2-3-1",
        "pressing_intensity": 5,
        "defensive_line":     5,
        "attacking_tempo":    6,
        "set_piece_focus":    6,
        "foul_tendency":      6,
        "cards_modifier":     0.03,
        "corners_modifier":   0.02,
        "goals_modifier": -0.02,
        "notes": "Arbeloa is an unproven manager at senior level. Former Real Madrid Castilla coach. Likely to set up defensively while getting used to the Premier League. Neutral modifiers with slight defensive lean until we see his style develop."
    },

    "Hull City": {
        "manager":            "Sergej Jakirovic",
        "style":              "Pressing / Aggressive",
        "formation":          "4-2-3-1",
        "pressing_intensity": 7,
        "defensive_line":     6,
        "attacking_tempo":    7,
        "set_piece_focus":    6,
        "foul_tendency":      7,
        "cards_modifier":     0.07,   # Promoted side, aggressive style
        "corners_modifier":   0.05,
        "goals_modifier": -0.03,  # Likely to struggle in EPL
        "notes": "Jakirovic's Hull were physical and pressing in Championship. Adjustment period expected in EPL."
    },

    "Ipswich": {
        "manager":            "Gary O'Neil",
        "style":              "Counter Attack / Compact",
        "formation":          "4-2-3-1",
        "pressing_intensity": 6,
        "defensive_line":     5,
        "attacking_tempo":    6,
        "set_piece_focus":    6,
        "foul_tendency":      6,
        "cards_modifier":     0.03,
        "corners_modifier":   0.03,
        "goals_modifier": -0.05,  # Relegated last season, rebuilding
        "notes": "O'Neil is organized and hard to beat. Ipswich were relegated but have experienced EPL manager now."
    },

    "Leeds": {
        "manager":            "Daniel Farke",
        "style":              "High Press / Attacking",
        "formation":          "4-2-3-1",
        "pressing_intensity": 8,
        "defensive_line":     7,
        "attacking_tempo":    8,
        "set_piece_focus":    6,
        "foul_tendency":      6,
        "cards_modifier":     0.05,
        "corners_modifier":   0.03,
        "goals_modifier":     0.05,   # Farke's teams score a lot
        "notes": "Farke's teams are aggressive, high-scoring and pressing. Won Championship twice with this style."
    },

    "Liverpool": {
        "manager":            "Andoni Iraola",
        "style":              "High Press / Vertical",
        "formation":          "4-3-3",
        "pressing_intensity": 9,
        "defensive_line":     8,
        "attacking_tempo":    9,
        "set_piece_focus":    6,
        "foul_tendency":      6,
        "cards_modifier":     0.05,
        "corners_modifier":   0.00,
        "goals_modifier":     0.05,
        "notes": "Iraola's Bournemouth pressed relentlessly. Brings same intensity to Liverpool. Transition season."
    },

    "Man City": {
        "manager":            "Enzo Maresca",
        "style":              "Possession / Positional",
        "formation":          "4-3-3",
        "pressing_intensity": 7,
        "defensive_line":     7,
        "attacking_tempo":    7,
        "set_piece_focus":    6,
        "foul_tendency":      4,
        "cards_modifier": -0.03,  # Disciplined, possession-based
        "corners_modifier": -0.05,  # Possession team = fewer corners
        "goals_modifier":     0.03,
        "notes": "Maresca continues City's positional play philosophy. Leicester showed he can replicate Guardiola's system."
    },

    "Man United": {
        "manager":            "Michael Carrick",
        "style":              "Structured / Counter",
        "formation":          "4-2-3-1",
        "pressing_intensity": 6,
        "defensive_line":     5,
        "attacking_tempo":    6,
        "set_piece_focus":    6,
        "foul_tendency":      6,
        "cards_modifier":     0.03,
        "corners_modifier":   0.03,
        "goals_modifier":     0.00,
        "notes": "Carrick is methodical and defensively organized. Middlesbrough showed ability to be competitive with limited resources."
    },

    "Newcastle": {
        "manager":            "Eddie Howe",
        "style":              "High Press / Direct",
        "formation":          "4-3-3",
        "pressing_intensity": 8,
        "defensive_line":     7,
        "attacking_tempo":    8,
        "set_piece_focus":    7,
        "foul_tendency":      7,
        "cards_modifier":     0.07,   # Physical, high press = cards
        "corners_modifier":   0.08,   # Direct play wins corners
        "goals_modifier":     0.03,
        "notes": "Howe's Newcastle are physical, press hard and win lots of corners. High energy, high card matches."
    },

    "Nott'm Forest": {
        "manager":            "Vitor Pereira",
        "style":              "Defensive / Counter",
        "formation":          "4-4-2 / 4-5-1",
        "pressing_intensity": 5,
        "defensive_line":     4,
        "attacking_tempo":    5,
        "set_piece_focus":    7,
        "foul_tendency":      8,
        "cards_modifier":     0.10,   # Very physical, defensive style
        "corners_modifier":   0.05,
        "goals_modifier": -0.07,  # Low scoring defensive matches
        "notes": "Pereira sets up defensively compact teams. Very physical. High card rates. Low scoring matches typical."
    },

    "Tottenham": {
        "manager":            "Roberto De Zerbi",
        "style":              "Possession / High Press",
        "formation":          "4-2-3-1",
        "pressing_intensity": 9,
        "defensive_line":     8,
        "attacking_tempo":    8,
        "set_piece_focus":    5,
        "foul_tendency":      6,
        "cards_modifier":     0.05,
        "corners_modifier": -0.03,
        "goals_modifier":     0.07,   # De Zerbi teams score a lot
        "notes": "De Zerbi's Brighton averaged 2+ goals/game. Spurs with better players should be even more attacking."
    },

    "Sunderland": {
        "manager":            "Regis Le Bris",
        "style":              "High Press / Attacking",
        "formation":          "4-2-3-1",
        "pressing_intensity": 8,
        "defensive_line":     7,
        "attacking_tempo":    7,
        "set_piece_focus":    6,
        "foul_tendency":      6,
        "cards_modifier":     0.05,
        "corners_modifier":   0.03,
        "goals_modifier":     0.03,
        "notes": "Le Bris transformed Sunderland with attractive pressing football. First EPL season but proven Championship pedigree."
    },
    # Remove from fixtures automatically via team profile check
}


def get_manager_profile(team: str) -> dict:
    """Get manager profile for a team. Returns neutral profile if not found."""
    return EPL_MANAGER_PROFILES.get(team, {
        "manager":            "Unknown",
        "style":              "Unknown",
        "formation":          "Unknown",
        "pressing_intensity": 5,
        "defensive_line":     5,
        "attacking_tempo":    5,
        "set_piece_focus":    5,
        "foul_tendency":      5,
        "cards_modifier":     0.00,
        "corners_modifier":   0.00,
        "goals_modifier":     0.00,
        "notes":              "No manager profile available."
    })


def apply_manager_adjustments(
    home_team: str,
    away_team: str,
    goals_prob: dict,
    cards_prob: dict,
    corners_prob: dict,
) -> dict:
    """
    Apply manager tactical modifiers to market probabilities.
    Blends home and away manager tendencies.
    Returns adjusted probabilities for all three markets.
    """
    home_mgr = get_manager_profile(home_team)
    away_mgr = get_manager_profile(away_team)

    # Average the two managers' modifiers
    cards_mod = (home_mgr["cards_modifier"] + away_mgr["cards_modifier"]) / 2
    corners_mod = (home_mgr["corners_modifier"] +
                   away_mgr["corners_modifier"]) / 2
    goals_mod = (home_mgr["goals_modifier"] + away_mgr["goals_modifier"]) / 2

    # Apply to goals
    adjusted_goals = goals_prob.copy()
    adjusted_goals["over25"] = round(
        min(max(goals_prob["over25"] + goals_mod, 0.05), 0.95), 3)
    adjusted_goals["over15"] = round(
        min(max(goals_prob["over15"] + goals_mod, 0.05), 0.97), 3)
    adjusted_goals["over35"] = round(
        min(max(goals_prob["over35"] + goals_mod, 0.05), 0.85), 3)
    adjusted_goals["btts_yes"] = round(
        min(max(goals_prob["btts_yes"] + goals_mod, 0.05), 0.95), 3)
    adjusted_goals["under25"] = round(1 - adjusted_goals["over25"], 3)
    adjusted_goals["under15"] = round(1 - adjusted_goals["over15"], 3)

    # Apply to cards
    adjusted_cards = cards_prob.copy()
    adjusted_cards["over35_cards"] = round(
        min(max(cards_prob["over35_cards"] + cards_mod, 0.05), 0.95), 3)
    adjusted_cards["over45_cards"] = round(
        min(max(cards_prob["over45_cards"] + cards_mod, 0.05), 0.90), 3)
    adjusted_cards["over25_cards"] = round(
        min(max(cards_prob["over25_cards"] + cards_mod, 0.05), 0.97), 3)

    # Apply to corners
    adjusted_corners = corners_prob.copy()
    adjusted_corners["over85_corners"] = round(
        min(max(corners_prob["over85_corners"] + corners_mod, 0.05), 0.95), 3)
    adjusted_corners["over105_corners"] = round(
        min(max(corners_prob["over105_corners"] + corners_mod, 0.05), 0.90), 3)

    return {
        "goals":   adjusted_goals,
        "cards":   adjusted_cards,
        "corners": adjusted_corners,
        "home_manager": {
            "name":  home_mgr["manager"],
            "style": home_mgr["style"],
        },
        "away_manager": {
            "name":  away_mgr["manager"],
            "style": away_mgr["style"],
        },
    }


if __name__ == "__main__":
    print("EPL Manager Profiles — 2026/27\n")
    print(f"{'Club':<20} {'Manager':<25} {'Style':<30} Cards  Corners  Goals")
    print("-" * 95)
    for team, p in sorted(EPL_MANAGER_PROFILES.items()):
        if team == "Sunderland":
            continue
        print(
            f"{team:<20} {p['manager']:<25} {p['style']:<30} "
            f"{p['cards_modifier']:+.2f}   "
            f"{p['corners_modifier']:+.2f}     "
            f"{p['goals_modifier']:+.2f}"
        )

    print("\nTest — Arsenal vs Tottenham adjustment:")
    from src.models.match_predictor import predict_match
    pred = predict_match("Arsenal", "Tottenham")
    result = apply_manager_adjustments(
        "Arsenal", "Tottenham",
        pred["goals"], pred["cards"], pred["corners"]
    )
    print(
        f"  Home: {result['home_manager']['name']} ({result['home_manager']['style']})")
    print(
        f"  Away: {result['away_manager']['name']} ({result['away_manager']['style']})")
    print(f"  Over 2.5 (adjusted): {result['goals']['over25']*100:.1f}%")
    print(
        f"  Over 3.5 cards (adjusted): {result['cards']['over35_cards']*100:.1f}%")
    print(
        f"  Over 8.5 corners (adjusted): {result['corners']['over85_corners']*100:.1f}%")
