"""
Result Tracker — Learning Engine Foundation.

Tracks every prediction we make and the actual result.
This is how the model improves over time.

Metrics tracked:
- Prediction accuracy
- Calibration (does 70% confidence actually win 70% of the time?)
- ROI (if we had bet on every flagged value bet)
- Closing Line Value (CLV) — did our odds improve before kickoff?
"""

import json
import os
from datetime import datetime

RESULTS_FILE = "data/prediction_results.json"
PERFORMANCE_FILE = "data/model_performance.json"


def load_results():
    """Load all tracked predictions."""
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            return json.load(f)
    return {"predictions": [], "total": 0}


def save_result(match_data, actual_result):
    """
    Record actual match result against our prediction.

    Args:
        match_data: Full match analysis dict from value_detector
        actual_result: "home" | "draw" | "away"
    """
    results = load_results()

    home = match_data["home_team"]
    away = match_data["away_team"]
    model_probs = match_data["model_probability"]
    bookie_odds = match_data["sportybet_odds"]

    # What did our model predict as most likely?
    model_prediction = max(
        [("home", model_probs["home"]),
         ("draw", model_probs["draw"]),
         ("away", model_probs["away"])],
        key=lambda x: x[1]
    )[0]

    # Was the model correct?
    model_correct = (model_prediction == actual_result)

    # Calculate ROI for each value bet we flagged
    value_bet_results = []
    for vb in match_data.get("value_bets", []):
        outcome_map = {"Home Win": "home", "Draw": "draw", "Away Win": "away"}
        bet_outcome = outcome_map.get(vb["outcome"], "")
        bet_won = (bet_outcome == actual_result)

        if bet_won:
            roi = vb["decimal_odds"] - 1  # Profit per unit
        else:
            roi = -1.0  # Lost stake

        value_bet_results.append({
            "outcome": vb["outcome"],
            "odds": vb["decimal_odds"],
            "model_prob": vb["model_probability"],
            "edge": vb["edge"],
            "ev": vb["expected_value"],
            "won": bet_won,
            "roi": round(roi, 4)
        })

    record = {
        "match_id": f"{home}_{away}_{match_data.get('kick_off', '')}".replace(" ", "_"),
        "home_team": home,
        "away_team": away,
        "kick_off": match_data.get("kick_off", ""),
        "competition": match_data.get("competition", ""),
        "recorded_at": datetime.now().isoformat(),
        "actual_result": actual_result,
        "model_prediction": model_prediction,
        "model_correct": model_correct,
        "model_probability": model_probs,
        "sportybet_odds": bookie_odds,
        "value_bets_flagged": len(match_data.get("value_bets", [])),
        "value_bet_results": value_bet_results,
        "total_roi": round(sum(vb["roi"] for vb in value_bet_results), 4)
    }

    results["predictions"].append(record)
    results["total"] = len(results["predictions"])
    results["last_updated"] = datetime.now().isoformat()

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"[TRACKER] Result saved: {home} vs {away} → {actual_result}")
    return record


def calculate_performance():
    """
    Calculate model performance metrics from all tracked results.

    This is the learning engine — it tells us:
    1. Is our model accurate?
    2. Is it calibrated?
    3. Is it profitable?
    """
    results = load_results()
    predictions = results.get("predictions", [])

    if not predictions:
        print("[TRACKER] No results tracked yet.")
        return None

    total = len(predictions)
    correct = sum(1 for p in predictions if p["model_correct"])

    # Collect all value bets
    all_value_bets = []
    for p in predictions:
        all_value_bets.extend(p.get("value_bet_results", []))

    total_bets = len(all_value_bets)
    winning_bets = sum(1 for vb in all_value_bets if vb["won"])
    total_roi = sum(vb["roi"] for vb in all_value_bets)

    # Calibration check
    # Group predictions by confidence band
    calibration = {
        "50-60%": {"predicted": 0, "correct": 0},
        "60-70%": {"predicted": 0, "correct": 0},
        "70-80%": {"predicted": 0, "correct": 0},
        "80%+": {"predicted": 0, "correct": 0},
    }

    for p in predictions:
        probs = p["model_probability"]
        pred = p["model_prediction"]
        actual = p["actual_result"]
        confidence = probs.get(pred, 0)

        if 50 <= confidence < 60:
            band = "50-60%"
        elif 60 <= confidence < 70:
            band = "60-70%"
        elif 70 <= confidence < 80:
            band = "70-80%"
        else:
            band = "80%+"

        calibration[band]["predicted"] += 1
        if p["model_correct"]:
            calibration[band]["correct"] += 1

    performance = {
        "calculated_at": datetime.now().isoformat(),
        "total_matches": total,
        "model_accuracy": round(correct / total * 100, 2) if total > 0 else 0,
        "total_value_bets": total_bets,
        "winning_value_bets": winning_bets,
        "win_rate": round(winning_bets / total_bets * 100, 2) if total_bets > 0 else 0,
        "total_roi_units": round(total_roi, 4),
        "roi_percentage": round(total_roi / total_bets * 100, 2) if total_bets > 0 else 0,
        "calibration": calibration
    }

    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(performance, f, indent=2)

    display_performance(performance)
    return performance


def display_performance(perf):
    """Print performance report to terminal."""
    print(f"\n{'='*65}")
    print(f"  MODEL PERFORMANCE REPORT")
    print(f"  Generated: {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'='*65}")
    print(f"\n  Matches tracked:     {perf['total_matches']}")
    print(f"  Model accuracy:      {perf['model_accuracy']}%")
    print(f"\n  Value bets flagged:  {perf['total_value_bets']}")
    print(f"  Bets won:            {perf['winning_value_bets']}")
    print(f"  Win rate:            {perf['win_rate']}%")
    print(f"  Total ROI:           {perf['total_roi_units']:+.4f} units")
    print(f"  ROI %:               {perf['roi_percentage']:+.2f}%")

    print(f"\n  CALIBRATION CHECK")
    print(f"  {'Band':<12} {'Predicted':>10} {'Correct':>10} {'Actual%':>10}")
    print(f"  {'-'*45}")
    for band, data in perf["calibration"].items():
        if data["predicted"] > 0:
            actual_pct = round(data["correct"] / data["predicted"] * 100, 1)
            print(
                f"  {band:<12} {data['predicted']:>10} {data['correct']:>10} {actual_pct:>9}%")

    print(f"\n{'='*65}\n")


def record_result_interactive():
    """
    Interactive CLI to record a match result.
    Run this after matches finish to feed results back into model.
    """
    print("\n=== RECORD MATCH RESULT ===")

    # Load today's predictions
    if not os.path.exists("data/value_bets.json"):
        print("[ERROR] No predictions found. Run python -m src.main first.")
        return

    with open("data/value_bets.json", "r") as f:
        analyses = json.load(f)

    matches = analyses.get("analyses", [])

    if not matches:
        print("[ERROR] No match analyses found.")
        return

    print(f"\nMatches in current analysis ({len(matches)} total):")
    for i, m in enumerate(matches, 1):
        result_recorded = "✓" if any(
            p.get("home_team") == m["home_team"] and p.get(
                "away_team") == m["away_team"]
            for p in load_results()["predictions"]
        ) else " "
        print(
            f"  [{result_recorded}] {i}. {m['home_team']} vs {m['away_team']} — {m['kick_off']}")

    print("\nEnter match number to record result (or 0 to exit):")
    try:
        choice = int(input("> "))
        if choice == 0:
            return
        if choice < 1 or choice > len(matches):
            print("[ERROR] Invalid choice")
            return

        match = matches[choice - 1]
        print(
            f"\nRecording result for: {match['home_team']} vs {match['away_team']}")
        print("Result: 1=Home Win  X=Draw  2=Away Win")
        print("Enter result (1/X/2):")

        result_input = input("> ").strip().upper()
        result_map = {"1": "home", "X": "draw", "2": "away"}

        if result_input not in result_map:
            print(
                "[ERROR] Invalid result. Enter python -m src.models.elo_model1, X or 2")
            return

        actual_result = result_map[result_input]
        record = save_result(match, actual_result)

        print(f"\n[OK] Result recorded: {actual_result}")
        print(
            f"     Model was: {'CORRECT ✓' if record['model_correct'] else 'WRONG ✗'}")

        if record["value_bet_results"]:
            print(f"\n     Value bet results:")
            for vb in record["value_bet_results"]:
                status = "WON ✓" if vb["won"] else "LOST ✗"
                print(
                    f"     {vb['outcome']:<12} @ {vb['odds']}  {status}  ROI: {vb['roi']:+.3f}")

        print(f"\n     Total ROI this match: {record['total_roi']:+.4f} units")

    except (ValueError, KeyboardInterrupt):
        print("\n[INFO] Cancelled")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "performance":
        calculate_performance()
    else:
        record_result_interactive()
