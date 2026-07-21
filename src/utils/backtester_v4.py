"""
Backtester v4 — tests the REAL production pipeline
Unlike v3 (which reimplements a simplified win-rate/goals-rate model
inline), this calls src.models.match_predictor.predict_match() per
fixture -- the actual Elo + xG + manager-adjustment + formation-engine
+ availability pipeline. Slower than v3 (real per-match calls through
six layers vs. vectorized CSV math), but it's the only backtest that
says anything about the system actually built rather than a standalone
placeholder sharing a function name.

Point-in-time correctness relies on match_predictor.predict_match()'s
backtest kwargs (profiles_path/h2h_path/elo_path/apply_availability/
force_promoted) -- every call in this file passes all five. See
match_predictor.py's predict_match() docstring for why each one matters.

Reuses from v3, unchanged: chronological validation/final-test split,
grid-search threshold tuning on the validation half only, league-average
fallback awareness, minimum-sample guard on tuned thresholds.

KNOWN OPEN RISK, not fixed here: team-name convention mismatches.
snapshot profiles/H2H (built by build_snapshot_profiles.py) and this
season's fixtures both come from the same football-data.co.uk CSVs, so
those two should agree on team names. But predict_match() also touches
xg_scraper.py (Understat-based), epl_manager_profiles.py,
formation_engine.py, and referee_profiler.py internally -- if any of
those use a different naming convention (this codebase has hit this
exact bug twice before per the project's own history), affected teams
silently fall back to historical/default data rather than crashing.
Worth spot-checking data_source in a few individual predictions after a
real run -- if "xG" almost never appears, that's the symptom.
"""

import json
import os
import csv
import sys
from collections import defaultdict
from datetime import datetime

# PROJECT_ROOT-from-__file__ pattern (cwd-safe). This script never had a
# path-fix at all before now -- that's why `python src\utils\backtester_v4.py`
# failed with ModuleNotFoundError: No module named 'src'. match_predictor is
# imported INSIDE predict_fixture() below, not here at module level, so no
# formatter/import-sorter can hoist it above this sys.path.insert and
# silently re-break it -- same fix already applied to diagnose_btts_ceiling.py
# and diagnose_stacking.py this session, for the same reason.
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TEST_SEASON_FILE = "data/raw/24-25.csv"

SNAPSHOT_PROFILES = "data/team_profiles_asof_24-25.json"
SNAPSHOT_H2H = "data/h2h_asof_24-25.json"
SNAPSHOT_ELO = "data/epl_elo_ratings_asof_24-25.json"
SNAPSHOT_XG = "data/xg_profiles_asof_24-25.json"

BACKTEST_OUTPUT = "data/backtest_results_v4.json"

VALIDATION_FRACTION = 0.5

RESULT_EDGE_GRID = [0.10, 0.12, 0.15, 0.18, 0.20]
# Widened downward -- last two backtest runs both tuned to 0.08 or 0.1,
# the lowest values then available in the grid, suggesting the true
# optimum may sit below what was previously offered. Adding 0.0 and 0.02
# lets the grid search actually find a lower optimum if one exists,
# instead of being artificially floored at 0.05.
GOALS_EDGE_GRID = [0.0, 0.02, 0.05, 0.08, 0.10, 0.12, 0.15]

REQUIRED_COLS = [
    "Date", "HomeTeam", "AwayTeam",
    "FTHG", "FTAG", "FTR",
    "HY", "AY", "HR", "AR",
    "B365H", "B365D", "B365A",
    "B365>2.5", "B365<2.5",
]

RESULT_MARKETS = {"home_win", "draw", "away_win"}

MARKET_ODDS_COL = {
    "home_win":     "B365H",
    "draw":         "B365D",
    "away_win":     "B365A",
    "over25":       "B365>2.5",
    "btts":         None,
    "over35_cards": None,
}


def parse_date(datestr: str):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(datestr, fmt)
        except (ValueError, TypeError):
            continue
    return None


def load_csv_file(filepath: str) -> list:
    matches = []
    if not os.path.exists(filepath):
        print(f"[WARN] Not found: {filepath}")
        return []
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        has_referee = "Referee" in (reader.fieldnames or [])
        for row in reader:
            if not row.get("HomeTeam") or not row.get("Date"):
                continue
            match = {}
            for col in REQUIRED_COLS:
                val = row.get(col, "")
                if col in ["FTHG", "FTAG", "HY", "AY", "HR", "AR"]:
                    try:
                        match[col] = int(float(val)) if val else 0
                    except (ValueError, TypeError):
                        match[col] = 0
                else:
                    try:
                        match[col] = float(val) if val else None
                    except (ValueError, TypeError):
                        match[col] = val
            match["Referee"] = row.get("Referee", "") if has_referee else ""
            match["_parsed_date"] = parse_date(match["Date"])
            matches.append(match)

    unparsed = [m for m in matches if m["_parsed_date"] is None]
    if unparsed:
        print(f"[WARN] {len(unparsed)} rows in {filepath} had unparseable "
              f"dates -- sorted last, check date format.")
    matches.sort(key=lambda m: m["_parsed_date"] or datetime.max)
    return matches


def predict_fixture(home: str, away: str, referee: str) -> dict:
    """
    Calls the real pipeline with all five backtest kwargs. Returns a
    flat dict matching the market keys used by score_matches(), pulled
    out of predict_match()'s nested result/goals/cards structure.
    Returns {} on any exception -- a fixture that crashes the real
    pipeline gets skipped and counted, not silently dropped, so
    skipped-count stays meaningful the way it did in v3.
    """
    try:
        # local import, see note at top of file
        from src.models.match_predictor import predict_match
        pred = predict_match(
            home, away, referee,
            profiles_path=SNAPSHOT_PROFILES,
            h2h_path=SNAPSHOT_H2H,
            elo_path=SNAPSHOT_ELO,
            xg_path=SNAPSHOT_XG,
            apply_availability=False,
            force_promoted=set(),
        )
    except Exception as e:
        return {"_error": str(e)}

    return {
        "home_win":     pred["result"]["home_win"],
        "draw":         pred["result"]["draw"],
        "away_win":     pred["result"]["away_win"],
        "over25":       pred["goals"]["over25"],
        "btts":         pred["goals"]["btts_yes"],
        "over35_cards": pred["cards"]["over35_cards"],
        "_data_source": pred["goals"]["data_source"],
    }


def get_actuals(m: dict) -> dict:
    hg, ag = m["FTHG"], m["FTAG"]
    total = hg + ag
    total_cards = m["HY"] + m["AY"] + m["HR"] + m["AR"]

    return {
        "home_win":     m["FTR"] == "H",
        "draw":         m["FTR"] == "D",
        "away_win":     m["FTR"] == "A",
        "over25":       total > 2.5,
        "btts":         hg > 0 and ag > 0,
        "over35_cards": total_cards > 3.5,
        "score":        f"{hg}-{ag}",
    }


def check_value(model_prob: float, odds, min_edge: float) -> dict:
    if not odds or odds <= 1:
        return {"is_value": False, "edge": 0, "implied": 0}
    implied = 1 / odds
    edge = model_prob - implied
    return {
        "is_value": edge >= min_edge,
        "edge":     round(edge, 4),
        "implied":  round(implied, 3),
    }


def score_matches(matches: list, thresholds: dict) -> dict:
    """
    Runs the REAL pipeline per fixture and evaluates value bets with a
    fixed set of thresholds (no tuning here -- same separation of
    concerns as v3's score_matches/tune_thresholds split).
    """
    market_stats = defaultdict(lambda: {
        "total": 0, "correct": 0,
        "value_bets": 0, "value_correct": 0,
        "profit": 0.0, "stake": 0.0,
    })
    match_results = []
    skipped = 0
    data_source_counts = defaultdict(int)

    for m in matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        referee = m.get("Referee", "")

        pred = predict_fixture(home, away, referee)
        if not pred or "_error" in pred:
            skipped += 1
            if pred.get("_error"):
                print(f"  [SKIP] {home} vs {away}: {pred['_error']}")
            continue

        data_source_counts[pred["_data_source"]] += 1
        actuals = get_actuals(m)
        match_record = {
            "date": m["Date"], "home": home, "away": away,
            "score": actuals["score"], "result": m["FTR"],
            "data_source": pred["_data_source"], "markets": {},
        }

        for market, odds_col in MARKET_ODDS_COL.items():
            if market not in pred or market not in actuals:
                continue
            model_prob = pred[market]
            correct = actuals[market]
            odds = m.get(odds_col) if odds_col else None
            min_edge = thresholds[market]
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
                "model_prob": model_prob, "correct": correct,
                "odds": odds, "edge": value["edge"],
                "is_value": value["is_value"], "profit": profit,
            }

        match_results.append(match_record)

    summary = {}
    for market, s in market_stats.items():
        n, vn = s["total"], s["value_bets"]
        summary[market] = {
            "total": n, "correct": s["correct"],
            "accuracy": round(s["correct"] / n, 3) if n else 0,
            "value_bets": vn, "value_correct": s["value_correct"],
            "value_accuracy": round(s["value_correct"] / vn, 3) if vn else 0,
            "profit": round(s["profit"], 0),
            "roi_pct": round(s["profit"] / s["stake"] * 100, 1) if s["stake"] else 0,
            "min_edge_used": thresholds[market],
        }

    return {
        "summary": summary, "matches": match_results,
        "skipped": skipped, "data_source_counts": dict(data_source_counts),
    }


def tune_thresholds(validation_matches: list) -> dict:
    """
    Same grid-search pattern as v3, but each candidate threshold means
    re-running the REAL pipeline over the validation half -- this is
    the slow part. MIN_SAMPLE guard unchanged: ignore candidates with
    too few value bets to trust.
    """
    MIN_SAMPLE = 8

    def best_edge(grid, market_group):
        best = {"edge": grid[len(grid) // 2], "roi": float("-inf")}
        for edge in grid:
            thresholds = {m: edge for m in market_group}
            for m in MARKET_ODDS_COL:
                thresholds.setdefault(m, edge)
            result = score_matches(validation_matches, thresholds)
            vbets = sum(result["summary"].get(m, {}).get("value_bets", 0)
                        for m in market_group)
            if vbets < MIN_SAMPLE:
                continue
            profit = sum(result["summary"].get(m, {}).get("profit", 0)
                         for m in market_group)
            stake = vbets * 1000
            roi = profit / stake * 100 if stake else float("-inf")
            if roi > best["roi"]:
                best = {"edge": edge, "roi": roi, "n": vbets}
        return best

    result_best = best_edge(RESULT_EDGE_GRID, RESULT_MARKETS)
    goals_markets = {"over25", "btts", "over35_cards"}
    goals_best = best_edge(GOALS_EDGE_GRID, goals_markets)

    print(f"  Tuned result-market min_edge: {result_best['edge']} "
          f"(validation ROI {result_best.get('roi', 0):.1f}%, "
          f"n={result_best.get('n', 0)})")
    print(f"  Tuned goals-market min_edge:  {goals_best['edge']} "
          f"(validation ROI {goals_best.get('roi', 0):.1f}%, "
          f"n={goals_best.get('n', 0)})")

    thresholds = {}
    for m in RESULT_MARKETS:
        thresholds[m] = result_best["edge"]
    for m in goals_markets:
        thresholds[m] = goals_best["edge"]
    return thresholds


def run_backtest() -> dict:
    print("=" * 60)
    print("  BACKTESTER v4 — real match_predictor.py pipeline")
    print("=" * 60)

    for path in (SNAPSHOT_PROFILES, SNAPSHOT_H2H, SNAPSHOT_ELO, SNAPSHOT_XG):
        if not os.path.exists(path):
            print(f"[ERROR] Missing snapshot file: {path}")
            print("  Run build_snapshot_profiles.py, build_snapshot_elo.py, "
                  "and build_snapshot_xg.py first.")
            return {}

    print("\nLoading 2024/25 test season...")
    test_matches = load_csv_file(TEST_SEASON_FILE)
    print(f"Matches: {len(test_matches)}\n")

    split_idx = int(len(test_matches) * VALIDATION_FRACTION)
    validation_matches = test_matches[:split_idx]
    final_matches = test_matches[split_idx:]
    print(f"Validation half: {len(validation_matches)} matches "
          f"(used ONLY to pick min_edge)")
    print(f"Final test half: {len(final_matches)} matches "
          f"(used ONLY to report results)\n")

    print("Tuning thresholds on validation half "
          "(this calls the real pipeline repeatedly -- slow)...")
    thresholds = tune_thresholds(validation_matches)

    print("\nScoring final held-out half with fixed thresholds...")
    result = score_matches(final_matches, thresholds)

    print(f"\nTested: {len(result['matches'])} matches "
          f"(skipped: {result['skipped']})")
    print(f"Data source usage: {result['data_source_counts']}")

    if result["skipped"] > 0:
        print(f"[WARN] {result['skipped']} matches skipped -- see [SKIP] "
              f"lines above for the underlying errors.")

    xg_count = result["data_source_counts"].get("xG", 0)
    hist_count = result["data_source_counts"].get("historical", 0)
    if xg_count == 0 and hist_count > 0:
        print("[WARN] 0 matches used xG data -- every fixture fell back to "
              "historical rates. Check team-name alignment between "
              "xg_scraper.py's Understat data and this season's fixture "
              "names (see module docstring).")

    return {
        "test_season":        "2024/25",
        "pipeline":           "real (match_predictor.predict_match)",
        "snapshot_files":     [SNAPSHOT_PROFILES, SNAPSHOT_H2H, SNAPSHOT_ELO],
        "validation_matches": len(validation_matches),
        "final_test_matches": len(final_matches),
        "tuned_thresholds":   thresholds,
        "total_matches":      len(result["matches"]),
        "skipped":            result["skipped"],
        "data_source_counts": result["data_source_counts"],
        "summary":            result["summary"],
        "matches":            result["matches"],
    }


def print_summary(results: dict):
    if not results:
        return
    s = results["summary"]

    print("=" * 70)
    print(f"  BACKTEST RESULTS — {results['test_season']} "
          f"(v4, REAL PIPELINE, FINAL HOLDOUT HALF ONLY)")
    print(
        f"  Thresholds tuned on: first {results['validation_matches']} matches")
    print(
        f"  Results reported on: last {results['final_test_matches']} matches")
    print(f"  Matches tested: {results['total_matches']}  "
          f"(skipped: {results['skipped']})")
    print(f"  Data source usage: {results['data_source_counts']}")
    print(f"  Tuned thresholds: {results['tuned_thresholds']}")
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

    if total_vbets < 15:
        print(f"\n[WARN] Only {total_vbets} total value bets in the final "
              f"holdout half -- ROI% at this sample size is not reliable.")

    print("\n📊 KEY INSIGHTS (final holdout half only, real pipeline):")
    for market, r in s.items():
        if r["value_bets"] > 0:
            tag = "✅" if r["roi_pct"] > 0 else "❌"
            print(f"  {tag} {labels.get(market, market).strip()}: "
                  f"{r['roi_pct']:+.1f}% ROI on {r['value_bets']} bets")


if __name__ == "__main__":
    results = run_backtest()
    if results:
        os.makedirs("data", exist_ok=True)
        with open(BACKTEST_OUTPUT, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nSaved → {BACKTEST_OUTPUT}\n")
        print_summary(results)
