"""
Backtester v3 — EPL Match Prediction Accuracy
Tests model predictions against actual 2024/25 results.
Uses 2022/23 + 2023/24 as training data with RECENCY WEIGHTING.

CHANGES FROM v2 (see chat for full reasoning):

1. THRESHOLD LEAKAGE FIX
   v2 hardcoded min_edge = 0.15 / 0.08 with no visible tuning step, which
   means those numbers were either guessed or hand-tuned by watching this
   same script's outAput on the 24/25 season — i.e. tuned on the test set.
   v3 splits 24/25 chronologically into a VALIDATION half (used only to
   grid-search min_edge per market) and a FINAL TEST half (used only to
   report accuracy/ROI). The threshold search never sees the matches it's
   scored against.

2. SURVIVORSHIP BIAS FIX
   v2 silently dropped any match involving a team with no 22/23 or 23/24
   data (i.e. every promoted team — exactly the matches a model is most
   likely to get wrong). v3 builds a league-average fallback profile and
   uses it for unseen teams instead of dropping them, and reports how many
   matches used a fallback so you can see the effect.

3. DEAD CODE REMOVED
   v2 had two identical market-evaluation loops back to back; the first
   computed `value` and discarded it. Removed.

4. form_score RELABELED, NOT FIXED
   v2's "form_score" was literally win_rate again (wins / weight), so
   blending home_win_rate with form_score was blending win rate with
   itself, not with recent momentum. True recency-within-season form needs
   match-level date ordering, which isn't built yet — flagged as a
   follow-up rather than silently faked. Renamed to make this honest.
"""

import json
import os
import csv
from collections import defaultdict
from datetime import datetime
from itertools import product

TEST_SEASON_FILE = "data/raw/24-25.csv"
TRAIN_FILES = [
    ("data/raw/22-23.csv", 0.25),  # 25% weight — oldest
    ("data/raw/23-24.csv", 0.75),  # 75% weight — more recent
]
BACKTEST_OUTPUT = "data/backtest_results.json"

# Fraction of the test season (chronologically, earliest first) used to
# tune min_edge. The remaining fraction is the untouched final test set
# that all reported accuracy/ROI numbers come from.
VALIDATION_FRACTION = 0.5

# Grid searched per market group when tuning thresholds on the validation
# half. Keep this coarse — a fine grid on a small validation set just
# re-introduces the overfitting this fix is meant to remove.
RESULT_EDGE_GRID = [0.10, 0.12, 0.15, 0.18, 0.20]
GOALS_EDGE_GRID = [0.05, 0.08, 0.10, 0.12, 0.15]

REQUIRED_COLS = [
    "Date", "HomeTeam", "AwayTeam",
    "FTHG", "FTAG", "FTR",
    "HC", "AC", "HF", "AF",
    "HY", "AY", "HR", "AR",
    "B365H", "B365D", "B365A",
    "B365>2.5", "B365<2.5",
]

RESULT_MARKETS = {"home_win", "draw", "away_win"}


def parse_date(datestr: str):
    """football-data.co.uk uses dd/mm/yy or dd/mm/yyyy depending on season."""
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
        for row in reader:
            if not row.get("HomeTeam") or not row.get("Date"):
                continue
            match = {}
            for col in REQUIRED_COLS:
                val = row.get(col, "")
                if col in ["FTHG", "FTAG", "HC", "AC", "HF", "AF", "HY", "AY", "HR", "AR"]:
                    try:
                        match[col] = int(float(val)) if val else 0
                    except (ValueError, TypeError):
                        match[col] = 0
                else:
                    try:
                        match[col] = float(val) if val else None
                    except (ValueError, TypeError):
                        match[col] = val
            match["_parsed_date"] = parse_date(match["Date"])
            matches.append(match)

    # Sort chronologically. Required for the validation/final-test split
    # below to actually be a time split rather than an arbitrary one —
    # if any rows fail to parse they're pushed to the end rather than
    # silently interleaved, and we warn so it's visible.
    unparsed = [m for m in matches if m["_parsed_date"] is None]
    if unparsed:
        print(f"[WARN] {len(unparsed)} rows in {filepath} had unparseable "
              f"dates — sorted last, check date format.")
    matches.sort(key=lambda m: m["_parsed_date"] or datetime.max)
    return matches


def build_weighted_profiles(train_files: list) -> dict:
    """Build team profiles with recency weighting across seasons."""
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
            # Renamed from form_score: this is season win rate, not
            # recent-match momentum. True recency-within-season form is
            # still an open TODO — needs match-level date ordering per
            # team, not built yet.
            "blended_win_rate":        round(s["wins"] / w, 3),
        }

    return profiles


def build_league_average_profile(profiles: dict) -> dict:
    """
    Fallback profile for teams with no training-season data (promoted
    teams). Simple mean across all known teams. Crude, but strictly
    better than dropping the match: it means "assume league-average"
    instead of "pretend this fixture didn't happen."
    """
    if not profiles:
        return {}
    keys = next(iter(profiles.values())).keys()
    avg = {}
    for k in keys:
        vals = [p[k] for p in profiles.values()]
        avg[k] = round(sum(vals) / len(vals), 3)
    return avg


def predict_match(home: str, away: str, profiles: dict,
                  fallback: dict) -> tuple:
    """
    Predict match using weighted profiles.
    Returns (prediction_dict, used_fallback_bool). Teams missing from
    `profiles` now use the league-average fallback instead of being
    skipped, so promoted teams stay in the test set. `used_fallback`
    lets the caller track how often this happens.
    """
    used_fallback = home not in profiles or away not in profiles
    hp = profiles.get(home, fallback)
    ap = profiles.get(away, fallback)
    if not hp or not ap:
        return {}, used_fallback

    HOME_ADV = 0.06

    home_xg = (hp["home_avg_goals_scored"] + ap["away_avg_goals_conceded"]) / 2
    away_xg = (ap["away_avg_goals_scored"] + hp["home_avg_goals_conceded"]) / 2

    over15 = (hp["over15_rate"] + ap["over15_rate"]) / 2
    over25 = (hp["over25_rate"] + ap["over25_rate"]) / 2
    btts = (hp["btts_rate"] + ap["btts_rate"]) / 2
    over35_cards = (hp["over35_cards_rate"] + ap["over35_cards_rate"]) / 2

    home_str = (hp["home_win_rate"] + hp["blended_win_rate"]) / 2 + HOME_ADV
    away_str = (ap["away_win_rate"] + ap["blended_win_rate"]) / 2
    draw_base = (hp["draw_rate"] + ap["draw_rate"]) / 2
    total = home_str + away_str + draw_base

    pred = {
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
    return pred, used_fallback


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


MARKET_ODDS_COL = {
    "home_win":     "B365H",
    "draw":         "B365D",
    "away_win":     "B365A",
    "over25":       "B365>2.5",
    "btts":         None,
    "over35_cards": None,
}


def score_matches(matches: list, profiles: dict, fallback: dict,
                  thresholds: dict) -> dict:
    """
    Run predictions + value-bet evaluation over a set of matches using a
    FIXED set of thresholds (no tuning here). Used for both the
    threshold grid-search on the validation half (thresholds swept
    externally, one call per candidate) and the final scoring on the
    held-out half (thresholds fixed from validation).
    """
    market_stats = defaultdict(lambda: {
        "total": 0, "correct": 0,
        "value_bets": 0, "value_correct": 0,
        "profit": 0.0, "stake": 0.0,
    })
    match_results = []
    skipped = 0
    fallback_used = 0

    for m in matches:
        home, away = m["HomeTeam"], m["AwayTeam"]
        pred, used_fb = predict_match(home, away, profiles, fallback)
        if not pred:
            skipped += 1
            continue
        if used_fb:
            fallback_used += 1

        actuals = get_actuals(m)
        match_record = {
            "date": m["Date"], "home": home, "away": away,
            "score": actuals["score"], "result": m["FTR"],
            "used_fallback": used_fb, "markets": {},
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
        "skipped": skipped, "fallback_used": fallback_used,
    }


def tune_thresholds(validation_matches: list, profiles: dict,
                    fallback: dict) -> dict:
    """
    Grid-search min_edge per market GROUP (result markets share one
    value, goals markets share another) on the validation half only.
    Picks whichever edge maximizes ROI on the validation half, with a
    minimum sample-size guard so a threshold that happens to produce 3
    lucky bets can't win by accident.
    """
    MIN_SAMPLE = 8  # ignore candidate thresholds with too few value bets to trust

    def best_edge(grid, market_group):
        best = {"edge": grid[len(grid) // 2], "roi": float("-inf")}
        for edge in grid:
            thresholds = {m: edge for m in market_group}
            for m in MARKET_ODDS_COL:
                thresholds.setdefault(m, edge)
            result = score_matches(
                validation_matches, profiles, fallback, thresholds)
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
    print("  BACKTESTER v3 — leak-checked, survivorship-corrected")
    print("=" * 60)

    print("\nBuilding weighted profiles...")
    profiles = build_weighted_profiles(TRAIN_FILES)
    fallback = build_league_average_profile(profiles)
    print(f"Profiles: {len(profiles)} teams\n")

    print("Loading 2024/25 test season...")
    test_matches = load_csv_file(TEST_SEASON_FILE)
    print(f"Matches: {len(test_matches)}\n")

    split_idx = int(len(test_matches) * VALIDATION_FRACTION)
    validation_matches = test_matches[:split_idx]
    final_matches = test_matches[split_idx:]
    print(f"Validation half: {len(validation_matches)} matches "
          f"(used ONLY to pick min_edge)")
    print(f"Final test half: {len(final_matches)} matches "
          f"(used ONLY to report results, never seen during tuning)\n")

    print("Tuning thresholds on validation half...")
    thresholds = tune_thresholds(validation_matches, profiles, fallback)

    print("\nScoring final held-out half with fixed thresholds...")
    result = score_matches(final_matches, profiles, fallback, thresholds)

    print(f"\nTested: {len(result['matches'])} matches "
          f"(skipped: {result['skipped']}, "
          f"used fallback profile: {result['fallback_used']})")

    if result["skipped"] > 0:
        print(f"[WARN] {result['skipped']} matches skipped — "
              f"check for teams missing from both profiles and fallback.")

    return {
        "test_season":        "2024/25",
        "train_seasons":      [f[0] for f in TRAIN_FILES],
        "weights":            {f[0]: f[1] for f in TRAIN_FILES},
        "validation_matches": len(validation_matches),
        "final_test_matches": len(final_matches),
        "tuned_thresholds":   thresholds,
        "total_matches":      len(result["matches"]),
        "skipped":            result["skipped"],
        "fallback_used":      result["fallback_used"],
        "summary":            result["summary"],
        "matches":            result["matches"],
    }


def print_summary(results: dict):
    s = results["summary"]

    print("=" * 70)
    print(
        f"  BACKTEST RESULTS — {results['test_season']} (FINAL HOLDOUT HALF ONLY)")
    print(f"  Training: 2022/23 (25%) + 2023/24 (75%)")
    print(
        f"  Thresholds tuned on: first {results['validation_matches']} matches")
    print(
        f"  Results reported on: last {results['final_test_matches']} matches")
    print(f"  Matches tested: {results['total_matches']}  "
          f"(skipped: {results['skipped']}, fallback used: {results['fallback_used']})")
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
              f"holdout half — ROI% at this sample size is not reliable, "
              f"treat as directional at best.")

    print("\n📊 KEY INSIGHTS (final holdout half only):")
    for market, r in s.items():
        if r["value_bets"] > 0:
            tag = "✅" if r["roi_pct"] > 0 else "❌"
            print(f"  {tag} {labels.get(market, market).strip()}: "
                  f"{r['roi_pct']:+.1f}% ROI on {r['value_bets']} bets")


if __name__ == "__main__":
    results = run_backtest()

    os.makedirs("data", exist_ok=True)
    with open(BACKTEST_OUTPUT, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved → {BACKTEST_OUTPUT}\n")

    print_summary(results)
