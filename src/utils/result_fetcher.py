"""
Auto Result Fetcher — SportyBet Direct API.

Fetches match results directly from SportyBet's internal API.
Same source as our odds — no external API needed, no paywall.

Endpoint discovered via DevTools:
GET https://www.sportybet.com/api/ng/factsCenter/eventResultList
Params: sportId, startTime, endTime, count
"""

import requests
import json
import os
from datetime import datetime, timedelta
from src.models.elo_model import EloModel

RESULTS_FILE = "data/prediction_results.json"
PERFORMANCE_FILE = "data/model_performance.json"

RESULTS_API = "https://www.sportybet.com/api/ng/factsCenter/eventResultList"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://www.sportybet.com/ng/",
    "Origin": "https://www.sportybet.com",
    "Current-Country": "NG"
}

WORLD_CUP_TOURNAMENT_ID = "sr:tournament:16"


def fetch_results(date_str=None):
    """
    Fetch completed World Cup results for a given date.
    date_str: YYYY-MM-DD, defaults to yesterday
    """
    if not date_str:
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Convert date to millisecond timestamps
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    params = {
        "count": 100,
        "lastId": "",
        "sportId": "sr:sport:1",
        "startTime": start_ms,
        "endTime": end_ms,
        "_": int(datetime.now().timestamp() * 1000)
    }

    print(f"[FETCHER] Fetching results for {date_str}...")

    try:
        response = requests.get(
            RESULTS_API,
            headers=HEADERS,
            params=params,
            timeout=15
        )
        response.raise_for_status()
        data = response.json()

        # Save raw response
        os.makedirs("data", exist_ok=True)
        with open(f"data/results_{date_str}.json", "w") as f:
            json.dump(data, f, indent=2)

        if data.get("bizCode") != 10000:
            print(f"[ERROR] API error: {data.get('message')}")
            return []

        return data.get("data", {}).get("tournaments", [])

    except Exception as e:
        print(f"[ERROR] Failed to fetch results: {e}")
        return []


def parse_world_cup_results(tournaments):
    """Extract only World Cup results from tournament list."""
    results = []

    for tournament in tournaments:
        if tournament.get("id") != WORLD_CUP_TOURNAMENT_ID:
            continue

        for event in tournament.get("events", []):
            if event.get("matchStatus") != "Ended":
                continue

            score = event.get("setScore", "0:0")
            try:
                home_goals, away_goals = map(int, score.split(":"))
            except:
                continue

            if home_goals > away_goals:
                result = "home"
            elif away_goals > home_goals:
                result = "away"
            else:
                result = "draw"

            results.append({
                "event_id": event.get("eventId"),
                "game_id": event.get("gameId"),
                "home_team": event.get("homeTeamName"),
                "away_team": event.get("awayTeamName"),
                "score": score,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "result": result,
                "kick_off_ms": event.get("estimateStartTime"),
                "competition": "World Cup"
            })

    return results


def load_predictions():
    """Load saved value bet predictions."""
    if not os.path.exists("data/value_bets.json"):
        print("[FETCHER] No predictions file found.")
        return []
    with open("data/value_bets.json") as f:
        data = json.load(f)
    return data.get("analyses", [])


def load_tracked_results():
    """Load previously tracked results."""
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {"results": [], "total": 0}


def normalize_name(name):
    """Normalize team names for matching."""
    name_map = {
        "usa": "united states",
        "united states": "usa",
        "turkiye": "turkey",
        "turkey": "turkiye",
        "ir iran": "iran",
        "iran": "ir iran",
        "korea republic": "south korea",
        "south korea": "korea republic",
        "dr congo": "congo dr",
        "congo dr": "dr congo",
        "bosnia and herzegovina": "bosnia & herzegovina",
        "bosnia & herzegovina": "bosnia and herzegovina",
    }
    n = name.lower().strip()
    return name_map.get(n, n)


def match_to_prediction(result, predictions):
    """Find the prediction that matches this result."""
    for pred in predictions:
        if (normalize_name(pred["home_team"]) == normalize_name(result["home_team"]) and
                normalize_name(pred["away_team"]) == normalize_name(result["away_team"])):
            return pred
    return None


def process_date(date_str=None):
    """
    Full pipeline for a given date:
    1. Fetch results from SportyBet
    2. Match to predictions
    3. Calculate ROI
    4. Update Elo ratings
    5. Save performance data
    """
    if not date_str:
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"\n{'='*65}")
    print(f"  AUTO RESULT FETCHER — {date_str}")
    print(f"{'='*65}\n")

    # Fetch results
    tournaments = fetch_results(date_str)
    wc_results = parse_world_cup_results(tournaments)

    if not wc_results:
        print(f"[INFO] No World Cup results found for {date_str}")
        return

    print(f"[OK] World Cup results found: {len(wc_results)}")
    for r in wc_results:
        print(f"  {r['home_team']} {r['score']} {r['away_team']} → {r['result']}")

    # Load predictions and existing tracked results
    predictions = load_predictions()
    tracked = load_tracked_results()
    existing_ids = {r.get("event_id") for r in tracked["results"]}

    elo_model = EloModel()
    new_records = []

    for result in wc_results:
        if result["event_id"] in existing_ids:
            print(
                f"[SKIP] Already tracked: {result['home_team']} vs {result['away_team']}")
            continue

        # Find matching prediction
        prediction = match_to_prediction(result, predictions)

        # Calculate bet results
        bet_results = []
        if prediction:
            model_probs = prediction.get("model_probability", {})
            model_pick = max(
                [("home", model_probs.get("home", 0)),
                 ("draw", model_probs.get("draw", 0)),
                 ("away", model_probs.get("away", 0))],
                key=lambda x: x[1]
            )[0]
            model_correct = (model_pick == result["result"])

            outcome_map = {"Home Win": "home",
                           "Draw": "draw", "Away Win": "away"}
            for vb in prediction.get("value_bets", []):
                bet_outcome = outcome_map.get(vb["outcome"], "")
                won = (bet_outcome == result["result"])
                roi = round(vb["decimal_odds"] - 1, 4) if won else -1.0
                bet_results.append({
                    "outcome": vb["outcome"],
                    "odds": vb["decimal_odds"],
                    "edge": vb["edge"],
                    "won": won,
                    "roi": roi
                })
        else:
            model_pick = "unknown"
            model_correct = False

        record = {
            "event_id": result["event_id"],
            "home_team": result["home_team"],
            "away_team": result["away_team"],
            "date": date_str,
            "score": result["score"],
            "actual_result": result["result"],
            "model_predicted": model_pick,
            "model_correct": model_correct,
            "model_probability": prediction.get("model_probability", {}) if prediction else {},
            "sportybet_odds": prediction.get("sportybet_odds", {}) if prediction else {},
            "value_bets_flagged": len(prediction.get("value_bets", [])) if prediction else 0,
            "bet_results": bet_results,
            "total_roi": round(sum(b["roi"] for b in bet_results), 4),
            "had_prediction": prediction is not None,
            "recorded_at": datetime.now().isoformat()
        }

        new_records.append(record)

        # Display
        correct_str = "✓ CORRECT" if model_correct else "✗ WRONG"
        pred_str = f"(predicted {model_pick})" if prediction else "(no prediction)"
        print(
            f"\n  {result['home_team']} {result['score']} {result['away_team']}")
        print(f"  Model: {correct_str} {pred_str}")

        if bet_results:
            for b in bet_results:
                status = "WON ✓" if b["won"] else "LOST ✗"
                print(
                    f"  Bet: {b['outcome']:<12} @ {b['odds']}  {status}  ROI: {b['roi']:+.3f}")
            print(f"  Match ROI: {record['total_roi']:+.4f} units")

        # Update Elo
        elo_model.update_from_result(
            result["home_team"],
            result["away_team"],
            result["result"],
            neutral_venue=True
        )

    if new_records:
        elo_model.save_ratings()
        print(f"\n[OK] Elo ratings updated")

        tracked["results"].extend(new_records)
        tracked["total"] = len(tracked["results"])
        tracked["last_updated"] = datetime.now().isoformat()

        with open(RESULTS_FILE, "w") as f:
            json.dump(tracked, f, indent=2)
        print(f"[SAVED] {len(new_records)} results → {RESULTS_FILE}")

        calculate_performance(tracked["results"])


def calculate_performance(results):
    """Calculate and display performance metrics."""
    if not results:
        return

    with_pred = [r for r in results if r["had_prediction"]]
    total = len(with_pred)
    if total == 0:
        print("[INFO] No matched predictions yet")
        return

    correct = sum(1 for r in with_pred if r["model_correct"])
    all_bets = [b for r in with_pred for b in r.get("bet_results", [])]
    total_bets = len(all_bets)
    won_bets = sum(1 for b in all_bets if b["won"])
    total_roi = sum(b["roi"] for b in all_bets)

    perf = {
        "calculated_at": datetime.now().isoformat(),
        "matches_tracked": len(results),
        "matches_with_predictions": total,
        "model_accuracy": round(correct / total * 100, 2),
        "value_bets_total": total_bets,
        "value_bets_won": won_bets,
        "win_rate": round(won_bets / total_bets * 100, 2) if total_bets > 0 else 0,
        "total_roi_units": round(total_roi, 4),
        "roi_pct": round(total_roi / total_bets * 100, 2) if total_bets > 0 else 0
    }

    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(perf, f, indent=2)

    print(f"\n{'='*65}")
    print(f"  MODEL PERFORMANCE")
    print(f"{'='*65}")
    print(f"  Matches tracked:    {len(results)}")
    print(f"  Model accuracy:     {perf['model_accuracy']}%")
    print(f"  Value bets total:   {total_bets}")
    print(f"  Bets won:           {won_bets}")
    print(f"  Win rate:           {perf['win_rate']}%")
    print(f"  Total ROI:          {perf['total_roi_units']:+.4f} units")
    print(f"  ROI %:              {perf['roi_pct']:+.2f}%")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else None
    process_date(date)
