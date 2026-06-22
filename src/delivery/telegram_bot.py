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


# ─── FUZZY TEAM NAME MATCHER ─────────────────────────────────────

def load_known_teams() -> list:
    with open("data/team_profiles.json") as f:
        return list(json.load(f)["teams"].keys())


def fuzzy_match(raw: str, teams: list) -> str:
    raw = raw.lower().strip()

    # Common shorthand aliases
    aliases = {
        "man united":   "Manchester United",
        "man utd":      "Manchester United",
        "man u":        "Manchester United",
        "mufc":         "Manchester United",
        "man city":     "Manchester City",
        "man c":        "Manchester City",
        "mcfc":         "Manchester City",
        "spurs":        "Tottenham",
        "tottenham hotspur": "Tottenham",
        "wolves":       "Wolverhampton Wanderers",
        "wolverhampton": "Wolverhampton Wanderers",
        "west ham":     "West Ham",
        "leicester":    "Leicester",
        "brighton":     "Brighton",
        "newcastle":    "Newcastle",
        "villa":        "Aston Villa",
        "forest":       "Nottingham Forest",
        "nott forest":  "Nottingham Forest",
        "nffc":         "Nottingham Forest",
        "brentford":    "Brentford",
        "fulham":       "Fulham",
        "everton":      "Everton",
        "ipswich":      "Ipswich",
        "southampton":  "Southampton",
        "bournemouth":  "Bournemouth",
        "crystal palace": "Crystal Palace",
        "palace":       "Crystal Palace",
        "luton":        "Luton",
        "burnley":      "Burnley",
        "sheffield utd": "Sheffield United",
        "sheffield united": "Sheffield United",
    }

    if raw in aliases:
        return aliases[raw]

    # Exact match (case-insensitive)
    for t in teams:
        if t.lower() == raw:
            return t

    # Partial match — raw is contained in team name or vice versa
    for t in teams:
        if raw in t.lower() or t.lower() in raw:
            return t

    # Word overlap scoring
    raw_words = set(raw.split())
    best, best_score = None, 0
    for t in teams:
        overlap = len(raw_words & set(t.lower().split()))
        if overlap > best_score:
            best, best_score = t, overlap

    return best or raw.title()


# ─── EPL MATCH HANDLER ───────────────────────────────────────────

async def handle_epl_match(home_team: str, away_team: str):
    """Run club value detection and send report to Telegram."""
    await send_message(f"🔍 Analysing <b>{home_team} vs {away_team}</b>...")

    # Placeholder odds — will be replaced with live SportyBet scrape
    placeholder_odds = {
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

    analysis = detect_value(home_team, away_team, placeholder_odds)
    report = format_value_report(analysis)
    await send_message(report)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages like 'Arsenal vs Chelsea'."""
    text = update.message.text.strip()

    # Only respond to messages from your chat
    if str(update.message.chat_id) != str(CHAT_ID):
        return

    if " vs " in text.lower():
        parts = text.lower().split(" vs ")
        raw_home = parts[0].strip()
        raw_away = parts[1].strip()

        known_teams = load_known_teams()
        home = fuzzy_match(raw_home, known_teams)
        away = fuzzy_match(raw_away, known_teams)

        await handle_epl_match(home, away)
    else:
        await send_message(
            "❓ Format: <b>Arsenal vs Chelsea</b>\n"
            "Works with shortcuts too:\n"
            "<code>man utd vs liverpool</code>\n"
            "<code>spurs vs man city</code>"
        )


def run_bot_listener():
    """Start the bot in listening mode — responds to messages."""
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))
    print("[BOT] Listening for messages... (Ctrl+C to stop)")
    app.run_polling()


# ─── EXISTING FUNCTIONS (unchanged) ──────────────────────────────

async def send_value_bets():
    """Load latest analysis and send value bets to Telegram."""

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
    """Send performance summary."""

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
    """Send a test message to verify bot works."""
    msg = (
        f"✅ <b>Football Intelligence Bot Active</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 Bot is connected and working\n"
        f"⚽ Ready to send value bet alerts\n"
        f"📅 {datetime.now().strftime('%d %b %Y %H:%M')}\n\n"
        f"💡 Type any match: <code>Arsenal vs Chelsea</code>\n"
        f"💡 Shortcuts work: <code>man utd vs spurs</code>"
    )
    await send_message(msg)


async def send_market_analysis():
    """Send market analysis for all World Cup matches."""

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
