"""
Match Prediction Engine — Club Football
Takes two team names, returns market probabilities for:
- Result (Home/Draw/Away)
- Over/Under Goals (1.5, 2.5, 3.5)
- BTTS
- Yellow Cards
- Corners
"""

import json
import os
from datetime import datetime
from src.models.referee_profiler import load_referee_profiles, adjust_cards_for_referee
from src.collectors.xg_scraper import load_xg_profiles
from src.models.epl_manager_profiles import apply_manager_adjustments
from src.models.formation_engine import get_formation_adjustment

PROFILES_FILE = "data/team_profiles.json"
H2H_FILE = "data/h2h.json"

# Home advantage factor (well established in football research)
HOME_ADVANTAGE = 0.06


def load_profiles() -> dict:
    with open(PROFILES_FILE) as f:
        return json.load(f)["teams"]


def load_h2h() -> dict:
    with open(H2H_FILE) as f:
        return json.load(f)["h2h"]


def get_h2h(home: str, away: str, h2h: dict) -> dict:
    key = f"{home}_vs_{away}"
    reverse = f"{away}_vs_{home}"
    return h2h.get(key) or h2h.get(reverse) or {}


def predict_goals(home: str, away: str, profiles: dict, h2h_data: dict) -> dict:
    """
    Predict goals using xG data (primary) blended with
    historical rates (secondary) and H2H (tertiary).
    """
    hp = profiles[home]
    ap = profiles[away]

    # Load xG profiles
    xg_profiles = load_xg_profiles()
    home_xg_data = xg_profiles.get(home, {})
    away_xg_data = xg_profiles.get(away, {})

    # Expected goals — xG attack vs xG defense
    if home_xg_data and away_xg_data:
        # Primary: xG based (home attack vs away defense)
        home_xg = (home_xg_data["avg_xg_for"] +
                   away_xg_data["avg_xg_against"]) / 2
        away_xg = (away_xg_data["avg_xg_for"] +
                   home_xg_data["avg_xg_against"]) / 2

        # Market rates — blend xG rates with historical rates (70/30)
        over15_rate = (
            home_xg_data["xg_over15_rate"] * 0.35 +
            away_xg_data["xg_over15_rate"] * 0.35 +
            hp["over15_rate"] * 0.15 +
            ap["over15_rate"] * 0.15
        )
        over25_rate = (
            home_xg_data["xg_over25_rate"] * 0.35 +
            away_xg_data["xg_over25_rate"] * 0.35 +
            hp["over25_rate"] * 0.15 +
            ap["over25_rate"] * 0.15
        )
        btts_rate = (
            home_xg_data["xg_btts_rate"] * 0.35 +
            away_xg_data["xg_btts_rate"] * 0.35 +
            hp["btts_rate"] * 0.15 +
            ap["btts_rate"] * 0.15
        )
        data_source = "xG"

    else:
        # Fallback: historical rates only
        home_xg = (hp["home_avg_goals_scored"] +
                   ap["away_avg_goals_conceded"]) / 2
        away_xg = (ap["away_avg_goals_scored"] +
                   hp["home_avg_goals_conceded"]) / 2
        over15_rate = (hp["over15_rate"] + ap["over15_rate"]) / 2
        over25_rate = (hp["over25_rate"] + ap["over25_rate"]) / 2
        btts_rate = (hp["btts_rate"] + ap["btts_rate"]) / 2
        data_source = "historical"

    # H2H adjustment
    h2h = get_h2h(home, away, h2h_data)
    if h2h and h2h["matches"] >= 3:
        h2h_avg = h2h["avg_goals"]
        home_xg = (home_xg * 0.80) + (h2h_avg * 0.5 * 0.20)
        away_xg = (away_xg * 0.80) + (h2h_avg * 0.5 * 0.20)
        h2h_over25 = 1.0 if h2h_avg > 2.5 else 0.0
        over25_rate = (over25_rate * 0.85) + (h2h_over25 * 0.15)

    over35_rate = over25_rate * 0.48

    return {
        "home_xg":      round(home_xg, 2),
        "away_xg":      round(away_xg, 2),
        "total_xg":     round(home_xg + away_xg, 2),
        "data_source":  data_source,
        "over15":       round(min(over15_rate, 0.97), 3),
        "over25":       round(min(over25_rate, 0.95), 3),
        "over35":       round(min(over35_rate, 0.85), 3),
        "under15":      round(max(1 - over15_rate, 0.03), 3),
        "under25":      round(max(1 - over25_rate, 0.05), 3),
        "under35":      round(max(1 - over35_rate, 0.15), 3),
        "btts_yes":     round(min(btts_rate, 0.95), 3),
        "btts_no":      round(max(1 - btts_rate, 0.05), 3),
    }


def predict_result(home: str, away: str, profiles: dict, h2h_data: dict) -> dict:
    """
    Predict match result using form, home advantage, and H2H.
    """
    hp = profiles[home]
    ap = profiles[away]

    # Base win rates from home/away splits
    home_strength = (hp["home_win_rate"] +
                     hp["form_score"]) / 2 + HOME_ADVANTAGE
    away_strength = (ap["away_win_rate"] + ap["form_score"]) / 2
    draw_base = (hp["draw_rate"] + ap["draw_rate"]) / 2

    # H2H adjustment
    h2h = get_h2h(home, away, h2h_data)
    if h2h and h2h["matches"] >= 3:
        h2h_home_rate = h2h["home_wins"] / h2h["matches"]
        h2h_away_rate = h2h["away_wins"] / h2h["matches"]
        home_strength = (home_strength * 0.75) + (h2h_home_rate * 0.25)
        away_strength = (away_strength * 0.75) + (h2h_away_rate * 0.25)

    # Normalize to sum to 1
    total = home_strength + away_strength + draw_base
    home_win = home_strength / total
    away_win = away_strength / total
    draw = draw_base / total

    return {
        "home_win":      round(home_win, 3),
        "draw":          round(draw, 3),
        "away_win":      round(away_win, 3),
        "home_or_draw":  round(home_win + draw, 3),
        "away_or_draw":  round(away_win + draw, 3),
    }


def predict_cards(home: str, away: str, profiles: dict, referee: str = "") -> dict:
    """
    Predict yellow cards using home/away split card rates,
    team foul rates, referee tendency, derby factor and
    manager pressing intensity.
    Home teams average fewer cards than away teams.
    """
    hp = profiles[home]
    ap = profiles[away]

    # Use home/away card splits if available
    # Home team cards at home, away team cards away
    home_cards_rate = hp.get("home_avg_yellow_cards",
                             hp.get("avg_yellow_cards", 1.5))
    away_cards_rate = ap.get("away_avg_yellow_cards",
                             ap.get("avg_yellow_cards", 1.8))

    avg_cards = home_cards_rate + away_cards_rate

    # Derby factor
    derby_pairs = [
        {"Arsenal", "Tottenham"}, {"Arsenal", "Chelsea"},
        {"Manchester United", "Manchester City"},
        {"Man United", "Man City"},
        {"Liverpool", "Everton"}, {"Liverpool", "Man United"},
        {"Chelsea", "Tottenham"}, {"Newcastle", "Sunderland"},
    ]
    is_derby = {home, away} in derby_pairs
    if is_derby:
        avg_cards *= 1.2

    # Base rates
    base_over35 = 1.0 if avg_cards > 3.5 else 0.65 if avg_cards > 2.8 else 0.40
    base_over45 = 1.0 if avg_cards > 4.5 else 0.45 if avg_cards > 3.5 else 0.25

    # Referee adjustment
    ref_profiles = load_referee_profiles()
    ref_adjustment = adjust_cards_for_referee(
        base_over35, base_over45, referee, ref_profiles)

    return {
        "avg_total_cards":   round(avg_cards, 2),
        "is_derby":          is_derby,
        "over25_cards":      round(min(ref_adjustment["over35_cards"] + 0.15, 0.95), 3),
        "over35_cards":      ref_adjustment["over35_cards"],
        "over45_cards":      ref_adjustment["over45_cards"],
        "under35_cards":     round(1 - ref_adjustment["over35_cards"], 3),
        "referee":           ref_adjustment["referee"],
        "referee_tendency":  ref_adjustment["referee_tendency"],
        "referee_avg_cards": ref_adjustment["referee_avg_cards"],
        "referee_found":     ref_adjustment["referee_found"],
    }


def predict_corners(home: str, away: str, profiles: dict) -> dict:
    """
    Predict corners using home/away split rates.
    Uses continuous probability function instead of fixed thresholds.
    Home teams win more corners (more attacking intent).
    """
    hp = profiles[home]
    ap = profiles[away]

    # Home team corners at home vs away team corners away
    home_corners_for = hp.get("home_avg_corners_for",
                              hp.get("avg_corners_for", 5.0))
    away_corners_against = ap.get("away_avg_corners_against",
                                  ap.get("avg_corners_against", 5.0))
    away_corners_for = ap.get("away_avg_corners_for",
                              ap.get("avg_corners_for", 4.5))
    home_corners_against = hp.get("home_avg_corners_against",
                                  hp.get("avg_corners_against", 4.5))

    # Total expected corners
    home_expected = (home_corners_for + away_corners_against) / 2
    away_expected = (away_corners_for + home_corners_against) / 2
    avg_corners = home_expected + away_expected

    # Continuous probability function based on expected corners
    # Calibrated against EPL historical data:
    # EPL average: ~10 corners/game
    # Over 8.5 hits ~65% of EPL matches
    # Over 10.5 hits ~40% of EPL matches
    # Over 12.5 hits ~20% of EPL matches

    def corners_prob(line: float, expected: float) -> float:
        """
        Linear calibration anchored to actual EPL rates (last 2 seasons, 760 matches):
        At EPL average (10.1 corners/game):
          Over 8.5:  68.3%
          Over 10.5: 46.1%
          Over 12.5: 23.8%
        """
        base = {8.5: 0.683, 10.5: 0.461, 12.5: 0.238}
        sensitivity = {8.5: 0.055, 10.5: 0.065, 12.5: 0.060}
        delta = expected - 10.1
        prob = base[line] + (sensitivity[line] * delta)
        return round(min(max(prob, 0.05), 0.95), 3)

    over85 = corners_prob(8.5,  avg_corners)
    over105 = corners_prob(10.5, avg_corners)
    over125 = corners_prob(12.5, avg_corners)

    return {
        "avg_total_corners": round(avg_corners, 2),
        "home_expected":     round(home_expected, 2),
        "away_expected":     round(away_expected, 2),
        "over85_corners":    over85,
        "over105_corners":   over105,
        "over125_corners":   over125,
    }


def _build_league_average(profiles: dict) -> dict:
    """Build a league average profile from all existing team profiles."""
    if not profiles:
        return {}

    keys = [
        "win_rate", "draw_rate", "loss_rate",
        "btts_rate", "over15_rate", "over25_rate",
        "home_win_rate", "home_avg_goals_scored", "home_avg_goals_conceded",
        "away_win_rate", "away_avg_goals_scored", "away_avg_goals_conceded",
        "avg_yellow_cards", "avg_corners_for", "avg_corners_against",
        "form_score", "clean_sheet_rate",
    ]

    avg = {}
    for key in keys:
        vals = [p[key] for p in profiles.values() if key in p]
        avg[key] = round(sum(vals) / len(vals), 3) if vals else 0.5

    # Promoted teams are weaker than average — apply 10% reduction
    avg["win_rate"] = round(avg["win_rate"] * 0.85, 3)
    avg["home_win_rate"] = round(avg["home_win_rate"] * 0.85, 3)
    avg["away_win_rate"] = round(avg["away_win_rate"] * 0.85, 3)
    avg["form_score"] = round(avg["form_score"] * 0.85, 3)

    return avg


def predict_match(home_team: str, away_team: str, referee: str = "") -> dict:
    """
    Master function — runs all engines, returns full prediction.
    """
    profiles = load_profiles()
    h2h = load_h2h()

    # Validate teams exist — use league average fallback for promoted teams
    missing = []
    if home_team not in profiles:
        missing.append(home_team)
    if away_team not in profiles:
        missing.append(away_team)

    if missing:
        # Build league average profile as fallback
        league_avg = _build_league_average(profiles)
        for team in missing:
            profiles[team] = league_avg.copy()
            print(
                f"[INFO] {team} not in historical profiles — using league average fallback")

    goals = predict_goals(home_team, away_team, profiles, h2h)
    result = predict_result(home_team, away_team, profiles, h2h)
    cards = predict_cards(home_team, away_team, profiles, referee)
    corners = predict_corners(home_team, away_team, profiles)

    h2h_data = get_h2h(home_team, away_team, h2h)

   # Apply manager tactical adjustments
    mgr_adjusted = apply_manager_adjustments(
        home_team, away_team, goals, cards, corners
    )

    # Apply formation matchup adjustments on top
    formation_adj = get_formation_adjustment(home_team, away_team)

    # Blend formation adjustments (weighted 30% — supports manager adjustments)
    fadj_goals = formation_adj["goals_adjustment"] * 0.30
    fadj_cards = formation_adj["cards_adjustment"] * 0.30
    fadj_corners = formation_adj["corners_adjustment"] * 0.30

    adj_goals = mgr_adjusted["goals"]
    adj_cards = mgr_adjusted["cards"]
    adj_corners = mgr_adjusted["corners"]

    adj_goals["over25"] = round(
        min(max(adj_goals["over25"] + fadj_goals,   0.05), 0.95), 3)
    adj_goals["over15"] = round(
        min(max(adj_goals["over15"] + fadj_goals,   0.05), 0.97), 3)
    adj_goals["btts_yes"] = round(
        min(max(adj_goals["btts_yes"] + fadj_goals,   0.05), 0.95), 3)
    adj_goals["over35"] = round(
        min(max(adj_goals["over35"] + fadj_goals,   0.05), 0.85), 3)
    adj_goals["under25"] = round(1 - adj_goals["over25"], 3)

    adj_cards["over35_cards"] = round(
        min(max(adj_cards["over35_cards"] + fadj_cards, 0.05), 0.95), 3)
    adj_cards["over45_cards"] = round(
        min(max(adj_cards["over45_cards"] + fadj_cards, 0.05), 0.90), 3)
    adj_cards["over25_cards"] = round(
        min(max(adj_cards["over25_cards"] + fadj_cards, 0.05), 0.97), 3)

    adj_corners["over85_corners"] = round(
        min(max(adj_corners["over85_corners"] + fadj_corners, 0.05), 0.95), 3)
    adj_corners["over105_corners"] = round(
        min(max(adj_corners["over105_corners"] + fadj_corners, 0.05), 0.90), 3)
    return {
        "home_team":      home_team,
        "away_team":      away_team,
        "generated":      datetime.now().isoformat(),
        "result":         result,
        "goals":          adj_goals,
        "cards":          adj_cards,
        "corners":        adj_corners,
        "h2h":            h2h_data,
        "home_manager":   mgr_adjusted["home_manager"],
        "away_manager":   mgr_adjusted["away_manager"],
        "formation":      formation_adj,
    }


def format_prediction(pred: dict) -> str:
    """Print-friendly prediction summary."""
    if "error" in pred:
        return f"ERROR: {pred['error']}"

    h = pred["home_team"]
    a = pred["away_team"]
    r = pred["result"]
    g = pred["goals"]
    c = pred["cards"]
    co = pred["corners"]
    h2h = pred.get("h2h", {})

    lines = [
        f"\n{'='*45}",
        f"  {h} vs {a}",
        f"{'='*45}",
        f"\n📊 RESULT PROBABILITIES",
        f"  {h} Win:    {r['home_win']*100:.1f}%",
        f"  Draw:         {r['draw']*100:.1f}%",
        f"  {a} Win:  {r['away_win']*100:.1f}%",
        f"  {h} DC:   {r['home_or_draw']*100:.1f}%",
        f"  {a} DC:   {r['away_or_draw']*100:.1f}%",

        f"\n👔 {pred.get('home_manager', {}).get('name', '?')} ({pred.get('home_manager', {}).get('style', '?')})",
        f"   vs {pred.get('away_manager', {}).get('name', '?')} ({pred.get('away_manager', {}).get('style', '?')})",
        f"⚔️ {pred.get('formation', {}).get('home_formation', '?')} vs {pred.get('formation', {}).get('away_formation', '?')} — {pred.get('formation', {}).get('matchup_type', '')}",
        f"\n⚽ GOALS  (xG: {g['home_xg']} - {g['away_xg']})",
        f"  Over 1.5:   {g['over15']*100:.1f}%",
        f"  Over 2.5:   {g['over25']*100:.1f}%",
        f"  Over 3.5:   {g['over35']*100:.1f}%",
        f"  BTTS Yes:   {g['btts_yes']*100:.1f}%",

        f"\n🟨 CARDS  (avg total: {c['avg_total_cards']})",
        f"  Referee: {c['referee']} — {c['referee_tendency']} ({c['referee_avg_cards']} cards/game)",
        f"  Over 2.5:   {c['over25_cards']*100:.1f}%",
        f"  Over 3.5:   {c['over35_cards']*100:.1f}%",
        f"  Over 4.5:   {c['over45_cards']*100:.1f}%",
        f"  Derby match: {'YES ⚠️' if c['is_derby'] else 'No'}",

        f"\n🚩 CORNERS (avg total: {co['avg_total_corners']})",
        f"  Over 8.5:   {co['over85_corners']*100:.1f}%",
        f"  Over 10.5:  {co['over105_corners']*100:.1f}%",
        f"  Over 12.5:  {co['over125_corners']*100:.1f}%",
    ]

    if h2h:
        lines += [
            f"\n📋 H2H ({h2h['matches']} matches)",
            f"  {h} wins: {h2h['home_wins']}",
            f"  {a} wins: {h2h['away_wins']}",
            f"  Draws:    {h2h['draws']}",
            f"  Avg goals per game: {h2h['avg_goals']}",
        ]

    return "\n".join(lines)


if __name__ == "__main__":
    # Test: Arsenal vs Chelsea
    pred = predict_match("Arsenal", "Chelsea")
    print(format_prediction(pred))

    print("\n")

    # Test: Manchester City vs Liverpool
    pred2 = predict_match("Man City", "Liverpool")
    print(format_prediction(pred2))
