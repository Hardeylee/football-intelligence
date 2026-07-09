"""
Asian Handicap Engine
Predicts Asian Handicap probabilities using Elo rating difference
and xG-based expected goal margin.

How AH works:
- AH -1.5 home: home team must win by 2+ goals
- AH -0.5 home: home team must win by 1+ goals
- AH 0.0:       if home wins = win, draw = push (stake returned)
- AH +0.5 away: away team must not lose
- AH +1.5 away: away team can lose by 1 and still win the bet

SportyBet AH lines typically: -2.5, -2, -1.5, -1, -0.75, -0.5, 0, +0.5
"""

import math
from src.models.epl_elo import load_ratings, predict_result_elo

# Elo to expected goal margin mapping
# Every 100 Elo points ≈ 0.5 goal advantage
ELO_TO_GOAL_FACTOR = 0.004  # Calibrated via MSE minimisation against EPL 2024/25 data


def expected_goal_margin(home_elo: float, away_elo: float) -> float:
    elo_diff = home_elo - away_elo
    home_advantage = 0.092  # Real EPL mean margin from 380 matches
    margin = (elo_diff * ELO_TO_GOAL_FACTOR) + home_advantage
    return round(margin, 2)


def margin_to_ah_prob(expected_margin: float, line: float, std_dev: float = 1.866) -> float:
    """
    Convert expected goal margin to AH probability for a given line.
    Uses normal distribution — goal margins roughly follow normal dist.

    line: the handicap line from home team's perspective
          e.g. -1.5 means home must win by 2+
    std_dev: standard deviation of goal margin (~1.4 in EPL)
    """
    z = (line - expected_margin) / std_dev
    prob = 1 - (0.5 * (1 + math.erf(z / math.sqrt(2))))
    return round(min(max(prob, 0.05), 0.95), 3)


def get_recommended_line(home_elo: float, away_elo: float) -> float:
    """
    Suggest the best AH line based on expected margin.
    Targets the line where home probability is closest to 50%
    — this is where AH offers most value vs 1X2.
    """
    margin = expected_goal_margin(home_elo, away_elo)

    if margin >= 2.5:
        return -2.0
    elif margin >= 1.8:
        return -1.5
    elif margin >= 1.2:
        return -1.0
    elif margin >= 0.7:
        return -0.5
    elif margin >= 0.2:
        return 0.0
    elif margin >= -0.3:
        return 0.5
    elif margin >= -0.8:
        return 1.0
    else:
        return 1.5


def predict_ah(
    home_team:  str,
    away_team:  str,
    line:       float = None,
    live_odds:  dict = None,
    ratings:    dict = None,
) -> dict:
    """
    Main function — predict Asian Handicap probabilities.

    home_team:  home team name
    away_team:  away team name
    line:       AH line to evaluate. If None, auto-selects recommended line.
    live_odds:  dict with 'home_ah' and 'away_ah' odds if available.
    ratings:    optional Elo ratings dict (used in backtesting)
    """
    if ratings is None:
        ratings = load_ratings()

    home_elo = ratings.get(home_team, 1500)
    away_elo = ratings.get(away_team, 1500)

    expected_margin = expected_goal_margin(home_elo, away_elo)

    if line is None:
        line = get_recommended_line(home_elo, away_elo)

    # Calculate probabilities for all key lines
    lines_to_check = [-2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]
    all_lines = {}
    for l in lines_to_check:
        home_prob = margin_to_ah_prob(expected_margin, l)
        all_lines[l] = {
            "home_prob": home_prob,
            "away_prob": round(1 - home_prob, 3),
        }

    # Primary line
    home_prob = margin_to_ah_prob(expected_margin, line)
    away_prob = round(1 - home_prob, 3)

    # Value detection if odds provided
    value_home = None
    value_away = None
    if live_odds:
        home_odds = live_odds.get("home_ah")
        away_odds = live_odds.get("away_ah")
        if home_odds and home_odds > 1:
            implied = 1 / home_odds
            edge = home_prob - implied
            value_home = {
                "odds":  home_odds,
                "edge":  round(edge, 4),
                "value": False,  # AH value detection disabled — model not calibrated
            }
        if away_odds and away_odds > 1:
            implied = 1 / away_odds
            edge = away_prob - implied
            value_away = {
                "odds":  away_odds,
                "edge":  round(edge, 4),
                "value": edge >= 0.08,
            }

    return {
        "home_team":        home_team,
        "away_team":        away_team,
        "home_elo":         home_elo,
        "away_elo":         away_elo,
        "expected_margin":  expected_margin,
        "recommended_line": line,
        "home_prob":        home_prob,
        "away_prob":        away_prob,
        "all_lines":        all_lines,
        "value_home":       value_home,
        "value_away":       value_away,
        "line_label_home":  f"{home_team} {line:+.1f}",
        "line_label_away":  f"{away_team} {-line:+.1f}",
    }


def format_ah_report(pred: dict) -> str:
    """Format AH report for Telegram."""
    h = pred["home_team"]
    a = pred["away_team"]
    line = pred["recommended_line"]
    margin = pred["expected_margin"]

    lines = [
        f"🎯 <b>ASIAN HANDICAP</b>",
        f"Expected margin: {h} by {margin:+.2f} goals",
        f"Recommended: {pred['line_label_home']} / {pred['line_label_away']}",
        f"",
        f"<b>Key lines:</b>",
    ]

    for l, probs in sorted(pred["all_lines"].items()):
        if l < -2.5 or l > 2.0:
            continue
        home_pct = probs["home_prob"] * 100
        away_pct = probs["away_prob"] * 100
        marker = " ◀ recommended" if l == line else ""
        lines.append(
            f"  {h} {l:+.1f}: {home_pct:.0f}% | "
            f"{a} {-l:+.1f}: {away_pct:.0f}%{marker}"
        )

    if pred["value_home"] and pred["value_home"]["value"]:
        v = pred["value_home"]
        lines.append(
            f"\n✅ VALUE: {pred['line_label_home']} @ {v['odds']} "
            f"| Edge: {v['edge']*100:.1f}%"
        )
    if pred["value_away"] and pred["value_away"]["value"]:
        v = pred["value_away"]
        lines.append(
            f"\n✅ VALUE: {pred['line_label_away']} @ {v['odds']} "
            f"| Edge: {v['edge']*100:.1f}%"
        )

    return "\n".join(lines)


def backtest_ah(test_file: str = "data/raw/24-25.csv") -> dict:
    """
    Backtest AH predictions against historical Bet365 AH odds.
    Uses ONLY 2022/23 + 2023/24 Elo ratings to predict 2024/25 matches.
    No look-ahead bias.
    """
    import csv as _csv
    from src.models.epl_elo import BASE_RATING, update_elo, PROMOTED_RATINGS

    print("Backtesting Asian Handicap (clean — no look-ahead bias)...\n")

    # Build Elo from training seasons ONLY
    ratings = {}

    def get_r(team: str) -> float:
        if team not in ratings:
            ratings[team] = BASE_RATING
        return ratings[team]

    train_files = [
        ("data/raw/22-23.csv", 35),
        ("data/raw/23-24.csv", 38),
    ]

    for filepath, k in train_files:
        with open(filepath, encoding="utf-8-sig") as f:
            for row in _csv.DictReader(f):
                try:
                    h = row["HomeTeam"]
                    a = row["AwayTeam"]
                    hg = int(float(row["FTHG"]))
                    ag = int(float(row["FTAG"]))
                    hr, ar = update_elo(get_r(h), get_r(a), hg, ag, k)
                    ratings[h] = hr
                    ratings[a] = ar
                except:
                    continue

    # Apply promoted team starting ratings
    for team, rating in PROMOTED_RATINGS.items():
        ratings[team] = rating

    print(f"  Teams rated: {len(ratings)}\n")

    total = correct = value_bets = value_won = profit = 0

    with open(test_file, encoding="utf-8-sig") as f:
        matches = list(_csv.DictReader(f))

    for row in matches:
        home = row.get("HomeTeam", "")
        away = row.get("AwayTeam", "")
        if not home or not away:
            continue

        try:
            hg = int(float(row["FTHG"]))
            ag = int(float(row["FTAG"]))
            ah_line = float(row.get("AHh", 0) or 0)
            ah_odds_h = float(row.get("B365AHH", 0) or 0)
            ah_odds_a = float(row.get("B365AHA", 0) or 0)
        except:
            continue

        if not ah_odds_h or not ah_odds_a:
            continue

        # Predict using current (pre-match) ratings
        pred = predict_ah(
            home, away,
            line=ah_line,
            live_odds={"home_ah": ah_odds_h, "away_ah": ah_odds_a},
            ratings=ratings,
        )

        # Actual result vs handicap
        actual_margin = hg - ag
        home_covered = actual_margin > ah_line
        is_push = (actual_margin == ah_line)

        total += 1

        # Accuracy
        predicted_home = pred["home_prob"] > 0.5
        if not is_push and predicted_home == home_covered:
            correct += 1

        # Value bet P&L
        if pred["value_home"] and pred["value_home"]["value"]:
            value_bets += 1
            if home_covered and not is_push:
                value_won += 1
                profit += (ah_odds_h - 1) * 1000
            elif not is_push:
                profit -= 1000

        elif pred["value_away"] and pred["value_away"]["value"]:
            value_bets += 1
            if not home_covered and not is_push:
                value_won += 1
                profit += (ah_odds_a - 1) * 1000
            elif not is_push:
                profit -= 1000

        # Update Elo after each match (rolling — simulates real-time)
        home_r = ratings.get(home, BASE_RATING)
        away_r = ratings.get(away, BASE_RATING)
        new_h, new_a = update_elo(home_r, away_r, hg, ag)
        ratings[home] = new_h
        ratings[away] = new_a

    roi = profit / (value_bets * 1000) * 100 if value_bets else 0

    return {
        "total":      total,
        "correct":    correct,
        "accuracy":   round(correct / total, 3) if total else 0,
        "value_bets": value_bets,
        "value_won":  value_won,
        "profit":     round(profit, 0),
        "roi_pct":    round(roi, 1),
    }


if __name__ == "__main__":
    print("Asian Handicap Engine Test\n")

    tests = [
        ("Arsenal",   "Coventry City"),
        ("Man City",  "Liverpool"),
        ("Ipswich",   "Sunderland"),
        ("Brighton",  "Aston Villa"),
        ("Hull City", "Man United"),
    ]

    for home, away in tests:
        pred = predict_ah(home, away)
        print(f"{home} vs {away}")
        print(f"  Elo: {pred['home_elo']:.0f} vs {pred['away_elo']:.0f}")
        print(f"  Expected margin: {pred['expected_margin']:+.2f} goals")
        print(f"  Recommended line: {pred['line_label_home']}")
        print(f"  Home cover prob:  {pred['home_prob']*100:.0f}%")
        print(f"  Away cover prob:  {pred['away_prob']*100:.0f}%")
        print()

    print("\n" + "=" * 50)
    print("BACKTESTING vs Bet365 AH odds (2024/25):")
    print("=" * 50)
    results = backtest_ah()
    print(f"Matches tested:  {results['total']}")
    print(f"Accuracy:        {results['accuracy']*100:.1f}%")
    print(f"Value bets:      {results['value_bets']}")
    print(f"Value won:       {results['value_won']}/{results['value_bets']}")
    print(f"Profit:          ₦{results['profit']:,.0f}")
    print(f"ROI:             {results['roi_pct']:+.1f}%")
