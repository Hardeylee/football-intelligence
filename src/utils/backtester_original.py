"""
Backtester v2 — EPL Match Prediction Accuracy
Tests model predictions against actual 2024/25 results.
Uses 2022/23 + 2023/24 as training data with RECENCY WEIGHTING.
Now properly tests over/under 2.5 goals using Bet365 odds from CSVs.
"""

import json
import os
import csv
from collections import defaultdict

TEST_SEASON_FILE = "data/raw/24-25.csv"
TRAIN_FILES = [
    ("data/raw/22-23.csv", 0.25),  # 25% weight — oldest
    ("data/raw/23-24.csv", 0.75),  # 75% weight — more recent
]
BACKTEST_OUTPUT = "data/backtest_results.json"

REQUIRED_COLS = [
    "Date", "HomeTeam", "AwayTeam",
    "FTHG", "FTAG", "FTR",
    "HC", "AC", "HF", "AF",
    "HY", "AY", "HR", "AR",
    "B365H", "B365D", "B365A",
    "B365>2.5", "B365<2.5",
]


def load_csv_file(filepath: str) -> list:
    matches = []
    if not os.path.exists(filepath):
        print(f"[WARN] Not found: {filepath}")
        return []
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("HomeTeam") or not row.get("Date"):
                continue
            match = {}
            for col in REQUIRED_COLS:
                val = row.get(col, "")
                if col in ["FTHG", "FTAG", "HC", "AC", "HF", "AF", "HY", "AY", "HR", "AR"]:
                    try:
                        match[col] = int(float(val)) if val else 0
                    except:
                        match[col] = 0
                else:
                    try:
                        match[col] = float(val) if val else None
                    except:
                        match[col] = val
            matches.append(match)
    return matches


def build_weighted_profiles(train_files: list) -> dict:
    """
    Build team profiles with recency weighting.
    Recent seasons count more than older ones.
    """
    stats = defaultdict(lambda: {
        "weight":           0.0,
        "wins":             0.0,
        "draws":            0.0,
        "losses":           0.0,
        "goals_scored":     0.0,
        "goals_conceded":   0.0,
        "home_weight":      0.0,
        "home_wins":        0.0,
        "home_goals_scored":   0.0,
        "home_goals_conceded": 0.0,
        "away_weight":      0.0,
        "away_wins":        0.0,
        "away_goals_scored":   0.0,
        "away_goals_conceded": 0.0,
        "yellow_cards":     0.0,
        "corners_for":      0.0,
        "corners_against":  0.0,
        "btts":             0.0,
        "over25":           0.0,
        "over15":           0.0,
        "over35_cards":     0.0,
    })

    for filepath, weight in train_files:
        matches = load_csv_file(filepath)
        print(f"  {filepath}: {len(matches)} matches (weight: {weight})")

        for m in matches:
            home = m["HomeTeam"]
            away = m["AwayTeam"]
            hg, ag = m["FTHG"], m["FTAG"]
            result = m["FTR"]
            total = hg + ag
            btts = hg > 0 and ag > 0
            total_cards = m["HY"] + m["AY"] + m["HR"] + m["AR"]

            s = stats[home]
            s["weight"] += weight
            s["home_weight"] += weight
            s["goals_scored"] += hg * weight
            s["goals_conceded"] += ag * weight
            s["home_goals_scored"] += hg * weight
            s["home_goals_conceded"] += ag * weight
            s["yellow_cards"] += m["HY"] * weight
            s["corners_for"] += m["HC"] * weight
            s["corners_against"] += m["AC"] * weight
            if btts:
                s["btts"] += weight
            if total > 1.5:
                s["over15"] += weight
            if total > 2.5:
                s["over25"] += weight
            if total_cards > 3.5:
                s["over35_cards"] += weight
            if result == "H":
                s["wins"] += weight
                s["home_wins"] += weight
            elif result == "D":
                s["draws"] += weight
            else:
                s["losses"] += weight

            s = stats[away]
            s["weight"] += weight
            s["away_weight"] += weight
            s["goals_scored"] += ag * weight
            s["goals_conceded"] += hg * weight
            s["away_goals_scored"] += ag * weight
            s["away_goals_conceded"] += hg * weight
            s["yellow_cards"] += m["AY"] * weight
            s["corners_for"] += m["AC"] * weight
            s["corners_against"] += m["HC"] * weight
            if btts:
                s["btts"] += weight
            if total > 1.5:
                s["over15"] += weight
            if total > 2.5:
                s["over25"] += weight
            if total_cards > 3.5:
                s["over35_cards"] += weight
            if result == "A":
                s["wins"] += weight
                s["away_wins"] += weight
            elif result == "D":
                s["draws"] += weight
            else:
                s["losses"] += weight

    profiles = {}
    for team, s in stats.items():
        w = s["weight"]
        hw = s["home_weight"] or 0.001
        aw = s["away_weight"] or 0.001
        if w < 0.3:
            continue

        profiles[team] = {
            "win_rate":                round(s["wins"] / w, 3),
            "draw_rate":               round(s["draws"] / w, 3),
            "loss_rate":               round(s["losses"] / w, 3),
            "btts_rate":               round(s["btts"] / w, 3),
            "over15_rate":             round(s["over15"] / w, 3),
            "over25_rate":             round(s["over25"] / w, 3),
            "over35_cards_rate":       round(s["over35_cards"] / w, 3),
            "home_win_rate":           round(s["home_wins"] / hw, 3),
            "home_avg_goals_scored":   round(s["home_goals_scored"] / hw, 3),
            "home_avg_goals_conceded": round(s["home_goals_conceded"] / hw, 3),
            "away_win_rate":           round(s["away_wins"] / aw, 3),
            "away_avg_goals_scored":   round(s["away_goals_scored"] / aw, 3),
            "away_avg_goals_conceded": round(s["away_goals_conceded"] / aw, 3),
            "avg_yellow_cards":        round(s["yellow_cards"] / w, 3),
            "avg_corners_for":         round(s["corners_for"] / w, 3),
            "avg_corners_against":     round(s["corners_against"] / w, 3),
            "form_score":              round(s["wins"] / w, 3),
        }

    return profiles


def predict_match(home: str, away: str, profiles: dict) -> dict:
    """Predict match using weighted profiles."""
    if home not in profiles or away not in profiles:
        return {}

    hp = profiles[home]
    ap = profiles[away]

    HOME_ADV = 0.06

    home_xg = (hp["home_avg_goals_scored"] + ap["away_avg_goals_conceded"]) / 2
    away_xg = (ap["away_avg_goals_scored"] + hp["home_avg_goals_conceded"]) / 2

    over15 = (hp["over15_rate"] + ap["over15_rate"]) / 2
    over25 = (hp["over25_rate"] + ap["over25_rate"]) / 2
    btts = (hp["btts_rate"] + ap["btts_rate"]) / 2
    over35_cards = (hp["over35_cards_rate"] + ap["over35_cards_rate"]) / 2

    home_str = (hp["home_win_rate"] + hp["form_score"]) / 2 + HOME_ADV
    away_str = (ap["away_win_rate"] + ap["form_score"]) / 2
    draw_base = (hp["draw_rate"] + ap["draw_rate"]) / 2
    total = home_str + away_str + draw_base

    return {
        "home_win":      round(home_str / total, 3),
        "draw":          round(draw_base / total, 3),
        "away_win":      round(away_str / total, 3),
        "over15":        round(min(over15, 0.97), 3),
        "over25":        round(min(over25, 0.95), 3),
        "btts":          round(min(btts, 0.95), 3),
        "over35_cards":  round(min(over35_cards, 0.95), 3),
        "home_xg":       round(home_xg, 2),
        "away_xg":       round(away_xg, 2),
    }


def get_actuals(m: dict) -> dict:
    hg = m["FTHG"]
    ag = m["FTAG"]
    total = hg + ag
    total_cards = m["HY"] + m["AY"] + m["HR"] + m["AR"]

    return {
        "home_win":     m["FTR"] == "H",
        "draw":         m["FTR"] == "D",
        "away_win":     m["FTR"] == "A",
        "over15":       total > 1.5,
        "over25":       total > 2.5,
        "btts":         hg > 0 and ag > 0,
        "over35_cards": total_cards > 3.5,
        "score":        f"{hg}-{ag}",
        "total_goals":  total,
    }


def check_value(model_prob: float, odds: float, min_edge: float = 0.08) -> dict:
    """Check if a market represents value."""
    if not odds or odds <= 1:
        return {"is_value": False, "edge": 0, "implied": 0}
    implied = 1 / odds
    edge = model_prob - implied
    return {
        "is_value": edge >= min_edge,
        "edge":     round(edge, 4),
        "implied":  round(implied, 3),
    }


def run_backtest() -> dict:
    print("=" * 60)
    print("  BACKTESTER v2 — with recency weighting")
    print("=" * 60)

    print("\nBuilding weighted profiles...")
    profiles = build_weighted_profiles(TRAIN_FILES)
    print(f"Profiles: {len(profiles)} teams\n")

    print("Loading 2024/25 test season...")
    test_matches = load_csv_file(TEST_SEASON_FILE)
    print(f"Matches: {len(test_matches)}\n")

    markets = {
        "home_win":     ("B365H",     None),
        "draw":         ("B365D",     None),
        "away_win":     ("B365A",     None),
        "over25":       ("B365>2.5",  None),
        "btts":         (None,        None),
        "over35_cards": (None,        None),
    }

    market_stats = defaultdict(lambda: {
        "total": 0, "correct": 0,
        "value_bets": 0, "value_correct": 0,
        "profit": 0.0, "stake": 0.0,
    })

    match_results = []
    skipped = 0

    for m in test_matches:
        home = m["HomeTeam"]
        away = m["AwayTeam"]

        pred = predict_match(home, away, profiles)
        if not pred:
            skipped += 1
            continue

        actuals = get_actuals(m)

        match_record = {
            "date":   m["Date"],
            "home":   home,
            "away":   away,
            "score":  actuals["score"],
            "result": m["FTR"],
            "markets": {}
        }

        RESULT_MARKETS = {"home_win", "draw", "away_win"}

        for market, (odds_col, _) in markets.items():
            if market not in pred or market not in actuals:
                continue

            model_prob = pred[market]
            correct = actuals[market]
            odds = m.get(odds_col) if odds_col else None

            min_edge = 0.15 if market in {
                "home_win", "draw", "away_win"} else 0.08
            value = check_value(model_prob, odds, min_edge)

        for market, (odds_col, _) in markets.items():
            if market not in pred or market not in actuals:
                continue

            model_prob = pred[market]
            correct = actuals[market]
            odds = m.get(odds_col) if odds_col else None

            RESULT_MARKETS = {"home_win", "draw", "away_win"}
            min_edge = 0.15 if market in RESULT_MARKETS else 0.08
            value = check_value(model_prob, odds, min_edge)

            s = market_stats[market]
            s["total"] += 1
            if correct:
                s["correct"] += 1

            profit = None
            if value["is_value"] and odds:
                s["value_bets"] += 1
                s["stake"] += 1000
                if correct:
                    s["value_correct"] += 1
                    profit = (odds - 1) * 1000
                    s["profit"] += profit
                else:
                    profit = -1000
                    s["profit"] -= 1000

            match_record["markets"][market] = {
                "model_prob":  model_prob,
                "correct":     correct,
                "odds":        odds,
                "edge":        value["edge"],
                "is_value":    value["is_value"],
                "profit":      profit,
            }

        match_results.append(match_record)

    print(f"Tested: {len(match_results)} matches (skipped: {skipped})\n")

    summary = {}
    for market, s in market_stats.items():
        n = s["total"]
        vn = s["value_bets"]
        summary[market] = {
            "total":          n,
            "correct":        s["correct"],
            "accuracy":       round(s["correct"] / n, 3) if n else 0,
            "value_bets":     vn,
            "value_correct":  s["value_correct"],
            "value_accuracy": round(s["value_correct"] / vn, 3) if vn else 0,
            "profit":         round(s["profit"], 0),
            "roi_pct":        round(s["profit"] / s["stake"] * 100, 1) if s["stake"] else 0,
        }

    return {
        "test_season":   "2024/25",
        "train_seasons": [f[0] for f in TRAIN_FILES],
        "weights":       {f[0]: f[1] for f in TRAIN_FILES},
        "total_matches": len(match_results),
        "skipped":       skipped,
        "summary":       summary,
        "matches":       match_results,
    }


def print_summary(results: dict):
    s = results["summary"]

    print("=" * 70)
    print(f"  BACKTEST RESULTS — {results['test_season']}")
    print(f"  Training: 2022/23 (25%) + 2023/24 (75%)")
    print(f"  Matches tested: {results['total_matches']}")
    print("=" * 70)

    labels = {
        "home_win":     "Home Win    ",
        "draw":         "Draw        ",
        "away_win":     "Away Win    ",
        "over25":       "Over 2.5    ",
        "btts":         "BTTS        ",
        "over35_cards": "Cards 3.5+  ",
    }

    print(f"\n{'Market':<14} {'Accuracy':>8} {'VBets':>6} "
          f"{'V.Acc':>6} {'Profit ₦':>12} {'ROI%':>7}")
    print("-" * 60)

    for market, label in labels.items():
        if market not in s:
            continue
        r = s[market]
        vb_acc = f"{r['value_accuracy']*100:.1f}%" if r['value_bets'] > 0 else "N/A"
        profit = f"₦{r['profit']:,.0f}" if r['value_bets'] > 0 else "N/A"
        roi = f"{r['roi_pct']:.1f}%" if r['value_bets'] > 0 else "N/A"
        print(
            f"{label} "
            f"{r['accuracy']*100:>7.1f}%  "
            f"{r['value_bets']:>5}  "
            f"{vb_acc:>6}  "
            f"{profit:>12}  "
            f"{roi:>7}"
        )

    total_profit = sum(s[m]["profit"] for m in s if s[m]["value_bets"] > 0)
    total_stake = sum(s[m]["value_bets"] * 1000 for m in s)
    total_vbets = sum(s[m]["value_bets"] for m in s)
    total_roi = total_profit / total_stake * 100 if total_stake else 0

    print("-" * 60)
    print(f"{'TOTAL':<14} {'':>8} {total_vbets:>5}  "
          f"{'':>6}  ₦{total_profit:>10,.0f}  {total_roi:>6.1f}%")
    print("=" * 70)

    print("\n📊 KEY INSIGHTS:")
    for market, r in s.items():
        if r["value_bets"] > 0:
            if r["roi_pct"] > 0:
                print(f"  ✅ {labels.get(market, market).strip()}: "
                      f"+{r['roi_pct']:.1f}% ROI on {r['value_bets']} bets")
            else:
                print(f"  ❌ {labels.get(market, market).strip()}: "
                      f"{r['roi_pct']:.1f}% ROI on {r['value_bets']} bets")


if __name__ == "__main__":
    results = run_backtest()

    os.makedirs("data", exist_ok=True)
    with open(BACKTEST_OUTPUT, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved → {BACKTEST_OUTPUT}\n")

    print_summary(results)
