"""
Telegram Bot — Football Intelligence Delivery Layer.
Sends value bet alerts directly to your phone.
"""

import asyncio
import os
import json
from src.models.market_analyzer import analyze_markets, format_market_analysis_telegram
from src.models.club_value_detector import detect_value, format_value_report
from datetime import datetime
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from src.models.acca_builder import build_acca, format_acca_report, build_match_acca_legs

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


async def send_message(text):
    bot = Bot(token=TOKEN)
    await bot.send_message(
        chat_id=CHAT_ID,
        text=text,
        parse_mode="HTML"
    )
    print(f"[TG] Sent: {text[:60]}...")


# ─── TEAM NAME ALIASES ───────────────────────────────────────────

ALIASES = {
    # Manchester United
    "man united":           "Manchester United",
    "man utd":              "Manchester United",
    "man u":                "Manchester United",
    "mufc":                 "Manchester United",
    "united":               "Manchester United",
    "red devils":           "Manchester United",

    # Manchester City
    "man city":             "Manchester City",
    "man c":                "Manchester City",
    "mcfc":                 "Manchester City",
    "city":                 "Manchester City",
    "the citizens":         "Manchester City",

    # Tottenham
    "spurs":                "Tottenham",
    "tottenham hotspur":    "Tottenham",
    "thfc":                 "Tottenham",
    "tottenham":            "Tottenham",

    # Arsenal
    "arsenal":              "Arsenal",
    "the gunners":          "Arsenal",
    "afc":                  "Arsenal",
    "gooners":              "Arsenal",
    "gunners":              "Arsenal",

    # Chelsea
    "chelsea":              "Chelsea",
    "the blues":            "Chelsea",
    "cfc":                  "Chelsea",
    "blues":                "Chelsea",

    # Liverpool
    "liverpool":            "Liverpool",
    "the reds":             "Liverpool",
    "lfc":                  "Liverpool",
    "pool":                 "Liverpool",
    "reds":                 "Liverpool",

    # Wolverhampton
    "wolves":               "Wolverhampton Wanderers",
    "wolverhampton":        "Wolverhampton Wanderers",
    "wwfc":                 "Wolverhampton Wanderers",

    # West Ham
    "west ham":             "West Ham",
    "hammers":              "West Ham",
    "whufc":                "West Ham",
    "irons":                "West Ham",

    # Aston Villa
    "villa":                "Aston Villa",
    "aston villa":          "Aston Villa",
    "avfc":                 "Aston Villa",
    "villans":              "Aston Villa",

    # Nottingham Forest
    "forest":               "Nottingham Forest",
    "nott forest":          "Nottingham Forest",
    "nffc":                 "Nottingham Forest",
    "nottingham":           "Nottingham Forest",
    "nott'm forest":        "Nottingham Forest",

    # Newcastle
    "newcastle":            "Newcastle United",
    "newcastle utd":        "Newcastle United",
    "nufc":                 "Newcastle United",
    "magpies":              "Newcastle United",
    "toon":                 "Newcastle United",

    # Leicester
    "leicester":            "Leicester",
    "leicester city":       "Leicester",
    "lcfc":                 "Leicester",
    "foxes":                "Leicester",

    # Brighton
    "brighton":             "Brighton",
    "brighton & hove":      "Brighton",
    "bhafc":                "Brighton",
    "seagulls":             "Brighton",

    # Crystal Palace
    "crystal palace":       "Crystal Palace",
    "palace":               "Crystal Palace",
    "cpfc":                 "Crystal Palace",
    "eagles":               "Crystal Palace",

    # Everton
    "everton":              "Everton",
    "efc":                  "Everton",
    "toffees":              "Everton",

    # Brentford
    "brentford":            "Brentford",
    "bees":                 "Brentford",

    # Fulham
    "fulham":               "Fulham",
    "ffc":                  "Fulham",
    "cottagers":            "Fulham",

    # Bournemouth
    "bournemouth":          "Bournemouth",
    "afcb":                 "Bournemouth",
    "cherries":             "Bournemouth",

    # Southampton
    "southampton":          "Southampton",
    "saints":               "Southampton",

    # Ipswich
    "ipswich":              "Ipswich",
    "ipswich town":         "Ipswich",
    "itfc":                 "Ipswich",
    "tractor boys":         "Ipswich",

    # Luton
    "luton":                "Luton",
    "luton town":           "Luton",
    "hatters":              "Luton",

    # Burnley
    "burnley":              "Burnley",
    "clarets":              "Burnley",

    # Sheffield United
    "sheffield utd":        "Sheffield United",
    "sheffield united":     "Sheffield United",
    "sufc":                 "Sheffield United",
    "blades":               "Sheffield United",

    # Leeds
    "leeds":                "Leeds United",
    "leeds utd":            "Leeds United",
    "lufc":                 "Leeds United",
    "whites":               "Leeds United",

    # Sunderland
    "sunderland":           "Sunderland",
    "safc":                 "Sunderland",
    "black cats":           "Sunderland",

    # Hull
    "hull":                 "Hull City",
    "hull city":            "Hull City",
    "tigers":               "Hull City",

    # Coventry must be explicit to avoid "city" matching Man City
    "coventry":             "Coventry City",
    "coventry city":        "Coventry City",
    "cov":                  "Coventry City",
    "ccfc":                 "Coventry City",
    "sky blues":            "Coventry City",
    # Middlesbrough
    "middlesbrough":        "Middlesbrough",
    "boro":                 "Middlesbrough",
    "mfc":                  "Middlesbrough",

    # West Brom
    "west brom":            "West Brom",
    "west bromwich":        "West Brom",
    "wba":                  "West Brom",
    "baggies":              "West Brom",

    # Watford
    "watford":              "Watford",
    "hornets":              "Watford",

    # Norwich
    "norwich":              "Norwich City",
    "canaries":             "Norwich City",
    "ncfc":                 "Norwich City",

    # QPR
    "qpr":                  "QPR",
    "queens park rangers":  "QPR",

    # Blackburn
    "blackburn":            "Blackburn",
    "blackburn rovers":     "Blackburn",
    "rovers":               "Blackburn",

    # Swansea
    "swansea":              "Swansea City",
    "swans":                "Swansea City",

    # Cardiff
    "cardiff":              "Cardiff City",
    "bluebirds":            "Cardiff City",

    # Stoke
    "stoke":                "Stoke City",
    "potters":              "Stoke City",

    # Millwall
    "millwall":             "Millwall",
    "lions":                "Millwall",
}


# ─── FUZZY TEAM NAME MATCHER ─────────────────────────────────────

def load_known_teams() -> list:
    with open("data/team_profiles.json") as f:
        return list(json.load(f)["teams"].keys())


def fuzzy_match(raw: str, teams: list) -> str:
    raw = raw.lower().strip()

    # Check aliases first (case-insensitive)
    if raw in ALIASES:
        return ALIASES[raw]

    # Exact match (case-insensitive)
    for t in teams:
        if t.lower() == raw:
            return t

    # Multi-word exact phrase match — prevents "coventry city" matching "man city"
    for t in teams:
        t_lower = t.lower()
        if raw == t_lower:
            return t
        # All words in raw must appear in team name in order
        raw_words = raw.split()
        if all(w in t_lower for w in raw_words):
            return t

    # Partial match — raw contained in team name or vice versa
    for t in teams:
        if raw in t.lower() or t.lower() in raw:
            return t

    # Word overlap scoring — require majority match
    raw_words = set(raw.split())
    best, best_score = None, 0
    for t in teams:
        t_words = set(t.lower().split())
        overlap = len(raw_words & t_words)
        if overlap > best_score and overlap >= len(raw_words) * 0.6:
            best, best_score = t, overlap

    return best or raw.title()


# ─── EPL MATCH HANDLER ───────────────────────────────────────────

async def handle_epl_match(home_team: str, away_team: str):
    """Run club value detection with live SportyBet odds + streak analysis."""
    await send_message(f"🔍 Analysing <b>{home_team} vs {away_team}</b>...")

    from src.collectors.epl_odds_scraper import get_odds_for_match
    from src.models.streak_analyzer import (
        analyze_match_streaks, get_streak_confirmation, format_streak_report
    )

    # Fetch live odds
    live_odds = get_odds_for_match(home_team, away_team)
    if live_odds and live_odds.get("home_win"):
        odds_source = "Live SportyBet odds"
        odds = live_odds
    else:
        odds_source = "Model odds (match not found on SportyBet)"
        odds = {
            "home_win":        2.10,
            "draw":            3.40,
            "away_win":        3.80,
            "over15":          1.35,
            "over25":          1.90,
            "over35":          3.20,
            "under25":         1.95,
            "btts_yes":        1.75,
            "btts_no":         2.05,
            "over35_cards":    1.85,
            "over45_cards":    2.40,
            "over85_corners":  1.55,
            "over105_corners": 2.10,
        }

    # Run value detection
    analysis = detect_value(home_team, away_team, odds)
    if "error" in analysis:
        await send_message(f"❌ {analysis['error']}\nCheck team names match EPL clubs.")
        return

    # Run streak analysis
    streak_data = analyze_match_streaks(home_team, away_team)
    home_streaks = streak_data["home_streaks"]
    away_streaks = streak_data["away_streaks"]

    # Get confirmation signals
    pred = analysis["prediction"]
    confirmation = get_streak_confirmation(
        home_streaks,
        away_streaks,
        model_over25=pred["goals"]["over25"],
        model_btts=pred["goals"]["btts_yes"],
        model_over35_cards=pred["cards"]["over35_cards"],
        model_over85_corners=pred["corners"]["over85_corners"],
    )

    # Format and send value report
    report = format_value_report(analysis)
    footer = f"\n\n📡 <i>{odds_source}</i>"
    await send_message(report + footer)

    # Send streak report as separate message
    streak_report = format_streak_report(
        home_team, away_team,
        home_streaks, away_streaks,
        confirmation
    )
    if streak_report:
        await send_message(streak_report)


async def handle_acca_request(text: str):
    """
    Handle acca requests.
    Format: acca Arsenal vs Chelsea, Man City vs Liverpool, Leeds vs Ipswich
    """
    from src.collectors.epl_odds_scraper import get_odds_for_match

    # Strip the 'acca' prefix
    raw = text.lower().replace("acca", "").strip()

    # Split by comma to get individual matches
    raw_matches = [m.strip() for m in raw.split(",") if "vs" in m.lower()]

    if not raw_matches:
        await send_message(
            "❓ Acca format:\n"
            "<code>acca Arsenal vs Chelsea, Man City vs Liverpool</code>"
        )
        return

    known_teams = load_known_teams()
    matches = []
    odds_map = {}

    for raw_match in raw_matches:
        parts = raw_match.lower().split(" vs ")
        if len(parts) != 2:
            continue
        home = fuzzy_match(parts[0].strip(), known_teams)
        away = fuzzy_match(parts[1].strip(), known_teams)
        matches.append((home, away))

        # Try to fetch live odds
        live_odds = get_odds_for_match(home, away)
        if live_odds and live_odds.get("home_win"):
            odds_map[f"{home} vs {away}"] = live_odds

    if not matches:
        await send_message("❌ No valid matches found. Format: acca Arsenal vs Chelsea, Liverpool vs Leeds")
        return

    await send_message(f"🔍 Building acca for <b>{len(matches)} matches</b>...")

    acca = build_acca(matches, odds_map if odds_map else None)
    report = format_acca_report(acca)
    await send_message(report)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages."""
    text = update.message.text.strip()

    if str(update.message.chat_id) != str(CHAT_ID):
        return

    text_lower = text.lower().strip()

    # Acca request
    if text_lower.startswith("acca"):
        await handle_acca_request(text)
        return

    # Count how many "vs" are in the message
    # Handle different line break formats Telegram might send
    import re
    lines = [l.strip()
             for l in re.split(r'[\n\r]+', text) if "vs" in l.lower()]

    # Multiple matches in one message
    if len(lines) > 1:
        await send_message(f"🔍 Processing <b>{len(lines)} matches</b>...")
        known_teams = load_known_teams()
        for line in lines:
            parts = line.lower().split(" vs ")
            if len(parts) != 2:
                continue
            home = fuzzy_match(parts[0].strip(), known_teams)
            away = fuzzy_match(parts[1].strip(), known_teams)
            await handle_epl_match(home, away)
            await asyncio.sleep(2)
        return

    # Single match
    if " vs " in text_lower:
        parts = text_lower.split(" vs ")
        raw_home = parts[0].strip()
        raw_away = parts[1].strip()
        known_teams = load_known_teams()
        home = fuzzy_match(raw_home, known_teams)
        away = fuzzy_match(raw_away, known_teams)
        await handle_epl_match(home, away)
        return

    # Unknown command
    await send_message(
        "❓ Commands:\n"
        "Match: <code>Arsenal vs Chelsea</code>\n"
        "Multiple: paste multiple matches on separate lines\n"
        "Acca: <code>acca Arsenal vs Chelsea, Man City vs Liverpool</code>\n"
        "Shortcuts: <code>spurs vs reds</code>, <code>united vs city</code>"
    )


def run_bot_listener():
    """Start the bot in listening mode."""
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))
    print("[BOT] Listening for messages... (Ctrl+C to stop)")
    app.run_polling()


# ─── EXISTING FUNCTIONS ───────────────────────────────────────────

async def send_value_bets():
    if not os.path.exists("data/value_bets.json"):
        await send_message("⚠️ No analysis found. Run the pipeline first.")
        return

    with open("data/value_bets.json") as f:
        data = json.load(f)

    analyses = data.get("analyses", [])
    value_matches = [m for m in analyses if m["has_value"]]
    generated = data.get("generated_at", "")[:16].replace("T", " ")

    if not value_matches:
        msg = (
            f"🔍 <b>FOOTBALL INTELLIGENCE</b>\n"
            f"📅 {generated}\n\n"
            f"No value bets found in current analysis.\n"
            f"Matches analysed: {len(analyses)}"
        )
        await send_message(msg)
        return

    header = (
        f"🎯 <b>FOOTBALL INTELLIGENCE</b>\n"
        f"📅 {generated}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>{len(value_matches)} VALUE BETS FOUND</b>\n"
        f"📊 {len(analyses)} matches analysed"
    )
    await send_message(header)
    await asyncio.sleep(1)

    for match in value_matches:
        home = match["home_team"]
        away = match["away_team"]
        kick_off = match["kick_off"]
        home_elo = match["home_elo"]
        away_elo = match["away_elo"]
        model = match["model_probability"]
        bookie = match["sportybet_implied"]
        mgr = match.get("manager_intelligence", {})

        rating_map = {
            "★★★ STRONG": "🔥🔥🔥 STRONG",
            "★★ GOOD":    "⭐⭐ GOOD",
            "★ MARGINAL": "⭐ MARGINAL"
        }

        vb_lines = []
        for vb in match["value_bets"]:
            rating = rating_map.get(vb["rating"], vb["rating"])
            edge = vb["edge"]
            ev = vb["expected_value"]
            vb_lines.append(
                f"  🎯 <b>{vb['outcome']}</b> @ {vb['decimal_odds']}\n"
                f"  Edge: +{edge}% | EV: +{ev:.3f} | {rating}"
            )

        vb_text = "\n".join(vb_lines)
        tactical = ""
        if mgr:
            tactical = (
                f"\n⚔️ {mgr.get('home_style', '?')} vs "
                f"{mgr.get('away_style', '?')}\n"
                f"👔 {mgr.get('home_manager', '?')} vs "
                f"{mgr.get('away_manager', '?')}"
            )

        msg = (
            f"⚽ <b>{home} vs {away}</b>\n"
            f"🕐 {kick_off}\n"
            f"📈 Elo: {home_elo} vs {away_elo}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Model probabilities:</b>\n"
            f"  1: {model['home']}% | X: {model['draw']}% | 2: {model['away']}%\n"
            f"<b>SportyBet implied:</b>\n"
            f"  1: {bookie['home']}% | X: {bookie['draw']}% | 2: {bookie['away']}%\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>VALUE BETS:</b>\n"
            f"{vb_text}"
            f"{tactical}"
        )

        await send_message(msg)
        await asyncio.sleep(1.5)


async def send_daily_summary():
    if not os.path.exists("data/model_performance.json"):
        await send_message("📊 No performance data yet.")
        return

    with open("data/model_performance.json") as f:
        perf = json.load(f)

    roi = perf.get("total_roi_units", 0)
    roi_pct = perf.get("roi_pct", 0)
    accuracy = perf.get("model_accuracy", 0)
    total_bets = perf.get("value_bets_total", 0)
    won = perf.get("value_bets_won", 0)
    win_rate = perf.get("win_rate", 0)
    roi_icon = "📈" if roi >= 0 else "📉"

    msg = (
        f"📊 <b>MODEL PERFORMANCE REPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Model accuracy:  {accuracy}%\n"
        f"💰 Value bets:      {won}/{total_bets} won\n"
        f"📉 Win rate:        {win_rate}%\n"
        f"{roi_icon} Total ROI:       {roi:+.4f} units\n"
        f"📊 ROI %:           {roi_pct:+.2f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Updated: {datetime.now().strftime('%d %b %Y %H:%M')}"
    )
    await send_message(msg)


async def send_test():
    msg = (
        f"✅ <b>Football Intelligence Bot Active</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 Bot is connected and working\n"
        f"⚽ Ready to send value bet alerts\n"
        f"📅 {datetime.now().strftime('%d %b %Y %H:%M')}\n\n"
        f"💡 Type any match:\n"
        f"<code>Arsenal vs Chelsea</code>\n"
        f"<code>united vs city</code>\n"
        f"<code>spurs vs reds</code>"
    )
    await send_message(msg)


async def send_market_analysis():
    if not os.path.exists("data/value_bets.json"):
        await send_message("⚠️ No analysis found. Run pipeline first.")
        return

    with open("data/value_bets.json") as f:
        data = json.load(f)

    analyses = data.get("analyses", [])
    if not analyses:
        await send_message("No matches found.")
        return

    await send_message(
        f"📊 <b>MARKET ANALYSIS — {len(analyses)} MATCHES</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Full breakdown of recommended markets\n"
        f"for every World Cup match today.\n"
        f"Stake guide based on ₦1000 max budget."
    )
    await asyncio.sleep(1)

    for match in analyses:
        analysis = analyze_markets(
            match["home_team"],
            match["away_team"],
            match["home_elo"],
            match["away_elo"],
            match["model_probability"]
        )
        msg = format_market_analysis_telegram(analysis)
        await send_message(msg)
        await asyncio.sleep(2)


# ─── ENTRY POINT ─────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"

    if cmd == "test":
        asyncio.run(send_test())
    elif cmd == "bets":
        asyncio.run(send_value_bets())
    elif cmd == "markets":
        asyncio.run(send_market_analysis())
    elif cmd == "summary":
        asyncio.run(send_daily_summary())
    elif cmd == "all":
        async def send_all():
            await send_value_bets()
            await asyncio.sleep(2)
            await send_market_analysis()
        asyncio.run(send_all())
    elif cmd == "match":
        if len(sys.argv) >= 4:
            known = load_known_teams()
            home = fuzzy_match(sys.argv[2].lower(), known)
            away = fuzzy_match(sys.argv[3].lower(), known)
            asyncio.run(handle_epl_match(home, away))
        else:
            print("Usage: python -m src.delivery.telegram_bot match Arsenal Chelsea")
    elif cmd == "listen":
        run_bot_listener()
