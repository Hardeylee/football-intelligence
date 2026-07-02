"""
Result Tracker — EPL Prediction Accuracy Monitor
Logs predictions before each match, compares to actual results after.
Tracks ROI and accuracy per market across the season.
Run after each gameweek to update records.
"""

import json
import os
from datetime import datetime
from collections import defaultdict

PREDICTIONS_FILE = "data/prediction_log.json"
RESULTS_FILE = "data/tracked_results.json"
PERFORMANCE_FILE = "data/epl_performance.json"


# ─── LOGGING PREDICTIONS ─────────────────────────────────────────

def log_prediction(
    home_team: str,
    away_team: str,
    kick_off: str,
    prediction: dict,
    odds: dict,
    value_bets: list,
):
    """
    Log a prediction before a match is played.
    Called automatically when bot analyses a match.
    """
    os.makedirs("data", exist_ok=True)

    # Load existing log
    if os.path.exists(PREDICTIONS_FILE):
        with open(PREDICTIONS_FILE) as f:
            log = json.load(f)
    else:
        log = {"predictions": []}

    # Check if already logged
    match_key = f"{home_team}_vs_{away_team}_{kick_off}"
    existing = [p for p in log["predictions"] if p["match_key"] == match_key]
    if existing:
        return  # Already logged

    entry = {
        "match_key":  match_key,
        "home_team":  home_team,
        "away_team":  away_team,
        "kick_off":   kick_off,
        "logged_at":  datetime.now().isoformat(),
        "settled":    False,
        "result":     None,

        # Model predictions
        "model": {
            "home_win":      prediction.get("result", {}).get("home_win"),
            "draw":          prediction.get("result", {}).get("draw"),
            "away_win":      prediction.get("result", {}).get("away_win"),
            "over25":        prediction.get("goals", {}).get("over25"),
            "btts":          prediction.get("goals", {}).get("btts_yes"),
            "over35_cards":  prediction.get("cards", {}).get("over35_cards"),
            "over85_corners": prediction.get("corners", {}).get("over85_corners"),
        },

        # Odds at time of prediction
        "odds": {
            "home_win":  odds.get("home_win"),
            "draw":      odds.get("draw"),
            "away_win":  odds.get("away_win"),
            "over25":    odds.get("over25"),
            "btts_yes":  odds.get("btts_yes"),
        },

        # Value bets flagged
        "value_bets": [
            {
                "market": vb["market"],
                "odds":   vb["odds"],
                "edge":   vb["edge"],
                "prob":   vb["model_prob"],
            }
            for vb in value_bets
        ],
    }

    log["predictions"].append(entry)
    log["total"] = len(log["predictions"])
    log["updated_at"] = datetime.now().isoformat()

    with open(PREDICTIONS_FILE, "w") as f:
        json.dump(log, f, indent=2)


# ─── SETTLING RESULTS ────────────────────────────────────────────

def settle_match(
    home_team: str,
    away_team: str,
    home_goals: int,
    away_goals: int,
    kick_off: str = None,
):
    """
    Settle a completed match against logged predictions.
    Updates prediction log and performance records.
    """
    if not os.path.exists(PREDICTIONS_FILE):
        print(f"[WARN] No predictions log found.")
        return

    with open(PREDICTIONS_FILE) as f:
        log = json.load(f)

    # Find matching prediction
    matched = None
    for pred in log["predictions"]:
        if (pred["home_team"].lower() == home_team.lower() and
            pred["away_team"].lower() == away_team.lower() and
                not pred["settled"]):
            matched = pred
            break

    if not matched:
        print(
            f"[WARN] No unsettled prediction found for {home_team} vs {away_team}")
        return

    # Calculate actuals
    total_goals = home_goals + away_goals
    result_ftr = "H" if home_goals > away_goals else "A" if away_goals > home_goals else "D"

    actuals = {
        "home_goals":   home_goals,
        "away_goals":   away_goals,
        "total_goals":  total_goals,
        "result":       result_ftr,
        "home_win":     result_ftr == "H",
        "draw":         result_ftr == "D",
        "away_win":     result_ftr == "A",
        "over25":       total_goals > 2.5,
        "btts":         home_goals > 0 and away_goals > 0,
    }

    # Settle value bets
    settled_vbets = []
    total_profit = 0.0
    for vb in matched["value_bets"]:
        market = vb["market"]
        outcome = actuals.get(market, actuals.get(
            market.replace("_yes", ""), False))
        won = bool(outcome)
        odds = vb["odds"] or 2.0
        profit = (odds - 1) * 1000 if won else -1000

        settled_vbets.append({
            **vb,
            "won":    won,
            "profit": profit,
        })
        total_profit += profit

    matched["settled"] = True
    matched["settled_at"] = datetime.now().isoformat()
    matched["actual_result"] = actuals
    matched["value_bets"] = settled_vbets
    matched["total_profit"] = total_profit

    # Model accuracy check
    model = matched["model"]
    checks = {}
    if model.get("home_win") and model.get("home_win") > 0.5:
        checks["predicted_home_win"] = actuals["home_win"]
    if model.get("over25") and model.get("over25") > 0.5:
        checks["predicted_over25"] = actuals["over25"]
    if model.get("btts") and model.get("btts") > 0.5:
        checks["predicted_btts"] = actuals["btts"]

    matched["model_checks"] = checks

    with open(PREDICTIONS_FILE, "w") as f:
        json.dump(log, f, indent=2)

    print(f"✅ Settled: {home_team} {home_goals}-{away_goals} {away_team}")
    print(f"   Value bet P&L: ₦{total_profit:+,.0f}")

    # Update performance records
    update_performance(log)


# ─── PERFORMANCE TRACKING ────────────────────────────────────────

def update_performance(log: dict):
    """Recalculate performance stats from all settled predictions."""
    settled = [p for p in log["predictions"] if p["settled"]]

    if not settled:
        return

    market_stats = defaultdict(lambda: {
        "total": 0, "correct": 0,
        "value_bets": 0, "value_won": 0,
        "profit": 0.0, "stake": 0.0,
    })

    for pred in settled:
        actuals = pred.get("actual_result", {})
        model = pred.get("model", {})

        # Track model accuracy
        for market in ["home_win", "draw", "away_win", "over25", "btts"]:
            if model.get(market) is None:
                continue
            s = market_stats[market]
            s["total"] += 1
            predicted_yes = model[market] > 0.5
            actual_yes = actuals.get(market, False)
            if predicted_yes == actual_yes:
                s["correct"] += 1

        # Track value bet P&L
        for vb in pred.get("value_bets", []):
            market = vb["market"]
            s = market_stats[market]
            s["value_bets"] += 1
            s["stake"] += 1000
            s["profit"] += vb.get("profit", 0)
            if vb.get("won"):
                s["value_won"] += 1

    # Build summary
    summary = {}
    for market, s in market_stats.items():
        n = s["total"]
        vn = s["value_bets"]
        summary[market] = {
            "predictions":    n,
            "correct":        s["correct"],
            "accuracy":       round(s["correct"] / n, 3) if n else 0,
            "value_bets":     vn,
            "value_won":      s["value_won"],
            "value_accuracy": round(s["value_won"] / vn, 3) if vn else 0,
            "profit":         round(s["profit"], 0),
            "roi_pct":        round(s["profit"] / s["stake"] * 100, 1) if s["stake"] else 0,
        }

    performance = {
        "updated_at":      datetime.now().isoformat(),
        "total_predicted": len(log["predictions"]),
        "total_settled":   len(settled),
        "summary":         summary,
    }

    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(performance, f, indent=2)


# ─── REPORTING ───────────────────────────────────────────────────

def print_performance():
    """Print current season performance to terminal."""
    if not os.path.exists(PERFORMANCE_FILE):
        print("No performance data yet. Settle some matches first.")
        return

    with open(PERFORMANCE_FILE) as f:
        perf = json.load(f)

    s = perf["summary"]
    print("=" * 65)
    print(f"  EPL PERFORMANCE TRACKER")
    print(f"  Updated: {perf['updated_at'][:16]}")
    print(
        f"  Predicted: {perf['total_predicted']} | Settled: {perf['total_settled']}")
    print("=" * 65)

    labels = {
        "home_win":     "Home Win    ",
        "draw":         "Draw        ",
        "away_win":     "Away Win    ",
        "over25":       "Over 2.5    ",
        "btts":         "BTTS        ",
        "over35_cards": "Cards 3.5+  ",
        "over85_corners": "Corners 8.5+",
    }

    print(f"\n{'Market':<14} {'Accuracy':>8} {'VBets':>6} {'V.Acc':>6} {'Profit':>12} {'ROI%':>7}")
    print("-" * 60)

    for market, label in labels.items():
        if market not in s:
            continue
        r = s[market]
        vb_acc = f"{r['value_accuracy']*100:.1f}%" if r["value_bets"] else "N/A"
        profit = f"₦{r['profit']:,.0f}" if r["value_bets"] else "N/A"
        roi = f"{r['roi_pct']:.1f}%" if r["value_bets"] else "N/A"
        print(
            f"{label} "
            f"{r['accuracy']*100:>7.1f}%  "
            f"{r['value_bets']:>5}  "
            f"{vb_acc:>6}  "
            f"{profit:>12}  "
            f"{roi:>7}"
        )

    total_profit = sum(s[m]["profit"]
                       for m in s if s[m].get("value_bets", 0) > 0)
    total_vbets = sum(s[m]["value_bets"] for m in s)
    total_stake = total_vbets * 1000
    total_roi = total_profit / total_stake * 100 if total_stake else 0

    print("-" * 60)
    print(f"{'TOTAL':<14} {'':>8} {total_vbets:>5}  {'':>6}  ₦{total_profit:>10,.0f}  {total_roi:>6.1f}%")
    print("=" * 65)


def send_performance_telegram():
    """Format performance report for Telegram."""
    if not os.path.exists(PERFORMANCE_FILE):
        return "📊 No performance data yet."

    with open(PERFORMANCE_FILE) as f:
        perf = json.load(f)

    s = perf["summary"]
    lines = [
        "📊 <b>EPL PERFORMANCE TRACKER</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"Matches predicted: {perf['total_predicted']}",
        f"Matches settled:   {perf['total_settled']}",
        "",
    ]

    market_labels = {
        "over25":       "Over 2.5 Goals",
        "btts":         "BTTS Yes",
        "over35_cards": "Cards 3.5+",
        "home_win":     "Home Win",
    }

    for market, label in market_labels.items():
        if market not in s:
            continue
        r = s[market]
        if r["value_bets"] > 0:
            icon = "✅" if r["roi_pct"] > 0 else "❌"
            lines.append(
                f"{icon} {label}: {r['value_bets']} bets | "
                f"{r['value_accuracy']*100:.0f}% acc | "
                f"₦{r['profit']:,.0f} | {r['roi_pct']:+.1f}% ROI"
            )

    total_profit = sum(s[m]["profit"]
                       for m in s if s[m].get("value_bets", 0) > 0)
    total_vbets = sum(s[m]["value_bets"] for m in s)
    total_stake = total_vbets * 1000
    total_roi = total_profit / total_stake * 100 if total_stake else 0

    lines += [
        "",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"💰 Total: {total_vbets} bets | ₦{total_profit:,.0f} | {total_roi:+.1f}% ROI",
        f"📅 Updated: {perf['updated_at'][:16]}",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print_performance()
    elif sys.argv[1] == "settle":
        # Usage: python -m src.utils.result_tracker settle "Arsenal" "Chelsea" 2 1
        if len(sys.argv) >= 6:
            settle_match(
                home_team=sys.argv[2],
                away_team=sys.argv[3],
                home_goals=int(sys.argv[4]),
                away_goals=int(sys.argv[5]),
            )
        else:
            print(
                "Usage: python -m src.utils.result_tracker settle HomeTeam AwayTeam HomeGoals AwayGoals")
    elif sys.argv[1] == "show":
        print_performance()
