"""
Streak Analyzer — EPL Match Streaks
Analyzes recent form streaks for teams using historical match data.
Used to confirm or challenge model predictions.

Streaks tracked:
- Over 1.5 / 2.5 / 3.5 goals
- BTTS (both teams score)
- Clean sheets
- Cards over 3.5
- Corners over 8.5
- Win / Draw / Loss streak
"""

import json
import os
from datetime import datetime

MATCHES_FILE = "data/historical_matches.json"
DEFAULT_WINDOW = 6  # Last N matches


def load_matches() -> list:
    """Load all historical matches."""
    if not os.path.exists(MATCHES_FILE):
        return []
    with open(MATCHES_FILE) as f:
        return json.load(f)["matches"]


def get_team_matches(team: str, matches: list, n: int = DEFAULT_WINDOW) -> list:
    """
    Get last N matches for a team (home or away).
    Returns matches sorted by date, most recent last.
    """
    def parse_date(d):
        for fmt in ["%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"]:
            try:
                return datetime.strptime(d, fmt)
            except:
                continue
        return datetime.min

    team_matches = []
    for m in matches:
        if m.get("HomeTeam") == team or m.get("AwayTeam") == team:
            team_matches.append(m)

    # Sort by date
    team_matches.sort(key=lambda m: parse_date(m.get("Date", "")))

    return team_matches[-n:]


def analyze_team_streaks(team: str, recent_matches: list) -> dict:
    """
    Calculate streak stats for a team from their recent matches.
    Returns counts and rates for each market.
    """
    n = len(recent_matches)
    if n == 0:
        return {}

    stats = {
        "matches_analyzed": n,
        "over15_goals":  0,
        "over25_goals":  0,
        "over35_goals":  0,
        "btts":          0,
        "clean_sheets":  0,
        "over35_cards":  0,
        "over85_corners": 0,
        "wins":          0,
        "draws":         0,
        "losses":        0,
        "goals_scored":  0,
        "goals_conceded": 0,
    }

    for m in recent_matches:
        is_home = m.get("HomeTeam") == team

        hg = m.get("FTHG", 0)
        ag = m.get("FTAG", 0)
        total_goals = hg + ag

        scored    = hg if is_home else ag
        conceded  = ag if is_home else hg
        result    = m.get("FTR", "")

        hy = m.get("HY", 0)
        ay = m.get("AY", 0)
        hr = m.get("HR", 0)
        ar = m.get("AR", 0)
        total_cards = hy + ay + hr + ar

        hc = m.get("HC", 0)
        ac = m.get("AC", 0)
        total_corners = hc + ac

        # Goals markets
        if total_goals > 1.5:
            stats["over15_goals"] += 1
        if total_goals > 2.5:
            stats["over25_goals"] += 1
        if total_goals > 3.5:
            stats["over35_goals"] += 1

        # BTTS
        if hg > 0 and ag > 0:
            stats["btts"] += 1

        # Clean sheet (team didn't concede)
        if conceded == 0:
            stats["clean_sheets"] += 1

        # Cards
        if total_cards > 3.5:
            stats["over35_cards"] += 1

        # Corners
        if total_corners > 8.5:
            stats["over85_corners"] += 1

        # Result
        if (is_home and result == "H") or (not is_home and result == "A"):
            stats["wins"] += 1
        elif result == "D":
            stats["draws"] += 1
        else:
            stats["losses"] += 1

        stats["goals_scored"]   += scored
        stats["goals_conceded"] += conceded

    # Calculate rates
    rates = {
        "matches":           n,
        "over15_rate":       round(stats["over15_goals"] / n, 2),
        "over25_rate":       round(stats["over25_goals"] / n, 2),
        "over35_rate":       round(stats["over35_goals"] / n, 2),
        "btts_rate":         round(stats["btts"] / n, 2),
        "clean_sheet_rate":  round(stats["clean_sheets"] / n, 2),
        "over35_cards_rate": round(stats["over35_cards"] / n, 2),
        "over85_corners_rate": round(stats["over85_corners"] / n, 2),
        "win_rate":          round(stats["wins"] / n, 2),
        "draw_rate":         round(stats["draws"] / n, 2),
        "loss_rate":         round(stats["losses"] / n, 2),
        "avg_goals_scored":  round(stats["goals_scored"] / n, 2),
        "avg_goals_conceded": round(stats["goals_conceded"] / n, 2),
        # Raw counts for display (e.g. "5/6")
        "over15_count":      stats["over15_goals"],
        "over25_count":      stats["over25_goals"],
        "over35_count":      stats["over35_goals"],
        "btts_count":        stats["btts"],
        "clean_sheet_count": stats["clean_sheets"],
        "over35_cards_count": stats["over35_cards"],
        "over85_corners_count": stats["over85_corners"],
        "wins":              stats["wins"],
        "draws":             stats["draws"],
        "losses":            stats["losses"],
    }

    return rates


def get_streak_confirmation(
    home_streaks: dict,
    away_streaks: dict,
    model_over25: float,
    model_btts: float,
    model_over35_cards: float,
    model_over85_corners: float,
    n: int = DEFAULT_WINDOW,
) -> dict:
    """
    Compare model predictions against recent streaks.
    Returns confirmation signals for each market.

    Confirmation = model and streak agree (both high or both low)
    Conflict = model and streak disagree
    """
    def confirm(model_prob: float, home_rate: float, away_rate: float,
                threshold: float = 0.5) -> str:
        avg_streak_rate = (home_rate + away_rate) / 2
        model_high   = model_prob >= threshold
        streak_high  = avg_streak_rate >= threshold
        if model_high and streak_high:
            return "CONFIRMS"
        elif not model_high and not streak_high:
            return "CONFIRMS"
        else:
            return "CONFLICTS"

    if not home_streaks or not away_streaks:
        return {}

    return {
        "over25": {
            "signal":     confirm(model_over25,
                                  home_streaks["over25_rate"],
                                  away_streaks["over25_rate"]),
            "home_rate":  home_streaks["over25_rate"],
            "away_rate":  away_streaks["over25_rate"],
            "home_count": home_streaks["over25_count"],
            "away_count": away_streaks["over25_count"],
        },
        "btts": {
            "signal":     confirm(model_btts,
                                  home_streaks["btts_rate"],
                                  away_streaks["btts_rate"]),
            "home_rate":  home_streaks["btts_rate"],
            "away_rate":  away_streaks["btts_rate"],
            "home_count": home_streaks["btts_count"],
            "away_count": away_streaks["btts_count"],
        },
        "over35_cards": {
            "signal":     confirm(model_over35_cards,
                                  home_streaks["over35_cards_rate"],
                                  away_streaks["over35_cards_rate"]),
            "home_rate":  home_streaks["over35_cards_rate"],
            "away_rate":  away_streaks["over35_cards_rate"],
            "home_count": home_streaks["over35_cards_count"],
            "away_count": away_streaks["over35_cards_count"],
        },
        "over85_corners": {
            "signal":     confirm(model_over85_corners,
                                  home_streaks["over85_corners_rate"],
                                  away_streaks["over85_corners_rate"]),
            "home_rate":  home_streaks["over85_corners_rate"],
            "away_rate":  away_streaks["over85_corners_rate"],
            "home_count": home_streaks["over85_corners_count"],
            "away_count": away_streaks["over85_corners_count"],
        },
    }


def analyze_match_streaks(home_team: str, away_team: str,
                           n: int = DEFAULT_WINDOW) -> dict:
    """
    Main function — analyze streaks for both teams in a match.
    Returns full streak data and confirmation signals.
    """
    matches = load_matches()

    home_recent = get_team_matches(home_team, matches, n)
    away_recent = get_team_matches(away_team, matches, n)

    home_streaks = analyze_team_streaks(home_team, home_recent)
    away_streaks = analyze_team_streaks(away_team, away_recent)

    return {
        "home_team":    home_team,
        "away_team":    away_team,
        "window":       n,
        "home_streaks": home_streaks,
        "away_streaks": away_streaks,
    }


def format_streak_report(
    home_team: str,
    away_team: str,
    home_streaks: dict,
    away_streaks: dict,
    confirmation: dict = None,
    n: int = DEFAULT_WINDOW,
) -> str:
    """Format streak report for Telegram."""

    if not home_streaks or not away_streaks:
        return ""

    def fmt(count, total, label):
        rate = count / total if total else 0
        icon = "✅" if rate >= 0.5 else "❌"
        return f"{icon} {count}/{total}"

    t = n

    lines = [
        f"\n📈 <b>RECENT STREAKS</b> (last {n} matches)",
        f"<b>{home_team}:</b>",
        f"  Over 2.5: {fmt(home_streaks['over25_count'], t, 'o25')}  "
        f"BTTS: {fmt(home_streaks['btts_count'], t, 'btts')}  "
        f"CS: {fmt(home_streaks['clean_sheet_count'], t, 'cs')}",
        f"  Cards 3.5+: {fmt(home_streaks['over35_cards_count'], t, 'cards')}  "
        f"Corners 8.5+: {fmt(home_streaks['over85_corners_count'], t, 'corners')}",
        f"  Form: {home_streaks['wins']}W {home_streaks['draws']}D "
        f"{home_streaks['losses']}L",

        f"\n<b>{away_team}:</b>",
        f"  Over 2.5: {fmt(away_streaks['over25_count'], t, 'o25')}  "
        f"BTTS: {fmt(away_streaks['btts_count'], t, 'btts')}  "
        f"CS: {fmt(away_streaks['clean_sheet_count'], t, 'cs')}",
        f"  Cards 3.5+: {fmt(away_streaks['over35_cards_count'], t, 'cards')}  "
        f"Corners 8.5+: {fmt(away_streaks['over85_corners_count'], t, 'corners')}",
        f"  Form: {away_streaks['wins']}W {away_streaks['draws']}D "
        f"{away_streaks['losses']}L",
    ]

    # Add confirmation signals
    if confirmation:
        lines.append("\n<b>Streak vs Model:</b>")
        for market, data in confirmation.items():
            signal = data["signal"]
            icon = "🟢" if signal == "CONFIRMS" else "🔴"
            market_labels = {
                "over25":        "Over 2.5 Goals",
                "btts":          "BTTS",
                "over35_cards":  "Over 3.5 Cards",
                "over85_corners":"Over 8.5 Corners",
            }
            label = market_labels.get(market, market)
            home_str = f"{int(data['home_count'])}/{t}"
            away_str = f"{int(data['away_count'])}/{t}"
            lines.append(
                f"  {icon} {label}: "
                f"{home_str} | {away_str} — {signal}"
            )

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing streak analyzer...\n")

    result = analyze_match_streaks("Arsenal", "Chelsea")
    h = result["home_streaks"]
    a = result["away_streaks"]
    n = result["window"]

    print(f"Arsenal (last {n} matches):")
    print(f"  Over 2.5:    {h['over25_count']}/{n} ({h['over25_rate']*100:.0f}%)")
    print(f"  BTTS:        {h['btts_count']}/{n} ({h['btts_rate']*100:.0f}%)")
    print(f"  Clean sheets:{h['clean_sheet_count']}/{n}")
    print(f"  Cards 3.5+:  {h['over35_cards_count']}/{n}")
    print(f"  Corners 8.5+:{h['over85_corners_count']}/{n}")
    print(f"  Form:        {h['wins']}W {h['draws']}D {h['losses']}L")

    print(f"\nChelsea (last {n} matches):")
    print(f"  Over 2.5:    {a['over25_count']}/{n} ({a['over25_rate']*100:.0f}%)")
    print(f"  BTTS:        {a['btts_count']}/{n} ({a['btts_rate']*100:.0f}%)")
    print(f"  Clean sheets:{a['clean_sheet_count']}/{n}")
    print(f"  Cards 3.5+:  {a['over35_cards_count']}/{n}")
    print(f"  Corners 8.5+:{a['over85_corners_count']}/{n}")
    print(f"  Form:        {a['wins']}W {a['draws']}D {a['losses']}L")