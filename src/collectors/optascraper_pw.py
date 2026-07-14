"""
Opta/TheAnalyst stats scraper using Playwright.

Why Playwright and not requests:
The site's session cookie (STYXKEY_sdapi_session) appears to be set by
client-side JS / a bot-detection challenge, not a plain Set-Cookie header.
A headless browser executes that JS so the cookie actually gets set,
then we intercept the API response directly from network traffic.

Time-series support:
Each successful scrape is saved both to a "latest" file (overwritten each
run, e.g. data/premier_league_raw.json) and to a timestamped snapshot under
data/history/ so historical data accumulates over time. The site's own
cache headers indicate data refreshes roughly every 2 hours server-side,
so by default this script skips re-scraping a competition if its latest
file is newer than that — pass force=True to override.

Multi-league support:
COMPETITIONS below maps a short name to the (page_url, tmcl, post_id) triple
needed to fetch that competition's stats. To add a new league:
    1. Visit https://theanalyst.com/competition/<slug>/stats in a real browser
    2. Open DevTools > Network, filter for "tournamentstats"
    3. Copy the tmcl and _meta_post_id query params from that request
    4. Add an entry to COMPETITIONS below

Usage:
    python src/collectors/optascraper_pw.py                  # all competitions
    python src/collectors/optascraper_pw.py premier_league    # just one
    python src/collectors/optascraper_pw.py championship      # just one
"""

import json
import os
import sys
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

MIN_REFRESH_INTERVAL = timedelta(hours=2)
API_URL_FRAGMENT = "sdapi/v1/soccerdata/tournamentstats"

# Add more competitions here as you discover their tmcl / post_id values.
COMPETITIONS = {
    "premier_league": {
        "page_url": "https://theanalyst.com/competition/premier-league/stats",
        "tmcl": "51r6ph2woavlbbpk8f29nynf8",
        "post_id": "135731",
    },
    "championship": {
        # Confirmed via 200 OK on the actual tournamentstats request,
        # DevTools Network tab, English Championship stats page.
        "page_url": "https://theanalyst.com/competition/english-championship/stats",
        "tmcl": "bmmk637l2a33h90zlu36kx8no",
        "post_id": "135742",
    },
}


class OptaPlaywrightScraper:
    def __init__(self, headless=True, out_dir="data"):
        self.headless = headless
        self.out_dir = out_dir
        self.history_dir = os.path.join(out_dir, "history")
        os.makedirs(self.out_dir, exist_ok=True)
        os.makedirs(self.history_dir, exist_ok=True)

    def _is_fresh(self, out_path):
        if not os.path.exists(out_path):
            return False
        mtime = datetime.fromtimestamp(os.path.getmtime(out_path))
        return datetime.now() - mtime < MIN_REFRESH_INTERVAL

    def fetch_stats(self, page_url, out_filename, wait_ms=12000, force=False):
        """
        page_url: the competition stats page to load
        out_filename: where to save the captured JSON, relative to out_dir
        wait_ms: how long to wait for the API call to fire after page load
        force: if True, skip the freshness check and scrape anyway
        """
        out_path = os.path.join(self.out_dir, out_filename)

        if not force and self._is_fresh(out_path):
            print(
                f"  {out_path} is less than {MIN_REFRESH_INTERVAL} old — skipping.")
            with open(out_path) as f:
                return json.load(f)

        captured = {}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            def handle_response(response):
                if API_URL_FRAGMENT in response.url and response.status == 200:
                    try:
                        captured["url"] = response.url
                        captured["data"] = response.json()
                    except Exception as e:
                        print(
                            f"  Could not parse JSON from {response.url}: {e}")

            page.on("response", handle_response)

            print(f"  Loading {page_url} ...")
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(wait_ms)

            browser.close()

        if not captured:
            print("  No matching API response captured.")
            return None

        with open(out_path, "w") as f:
            json.dump(captured["data"], f, indent=2)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        history_filename = f"{os.path.splitext(out_filename)[0]}_{timestamp}.json"
        history_path = os.path.join(self.history_dir, history_filename)
        with open(history_path, "w") as f:
            json.dump(captured["data"], f, indent=2)

        print(f"  Saved latest to: {out_path}")
        print(f"  Saved snapshot to: {history_path}")
        return captured["data"]

    def fetch_competition(self, name, force=False):
        if name not in COMPETITIONS:
            print(
                f"Unknown competition '{name}'. Known: {list(COMPETITIONS.keys())}")
            return None
        comp = COMPETITIONS[name]
        print(f"[{name}]")
        return self.fetch_stats(
            page_url=comp["page_url"],
            out_filename=f"{name}_raw.json",
            force=force,
        )

    def fetch_all(self, force=False):
        results = {}
        for name in COMPETITIONS:
            results[name] = self.fetch_competition(name, force=force)
        return results


if __name__ == "__main__":
    scraper = OptaPlaywrightScraper(headless=True)

    if len(sys.argv) > 1:
        # e.g. python optascraper_pw.py premier_league
        scraper.fetch_competition(sys.argv[1])
    else:
        scraper.fetch_all()