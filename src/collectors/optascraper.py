import requests
import json
import time


class AnalystScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self.base_page = 'https://theanalyst.com/competition/premier-league/stats'
        self.api_url = 'https://theanalyst.com/wp-json/sdapi/v1/soccerdata/tournamentstats'

    def refresh_session(self):
        """Visit the actual page first so the server sets a fresh session cookie."""
        r = self.session.get(self.base_page, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(
                f"Couldn't load base page, status {r.status_code}")
        # cookie should now be in self.session.cookies automatically
        if 'STYXKEY_sdapi_session' not in self.session.cookies.get_dict():
            print(
                "Warning: session cookie not found after page load, API may reject requests")

    def fetch_stats(self, tmcl, post_id, subpage='stats', retries=1):
        params = {
            'tmcl': tmcl,
            '_meta_post_id': post_id,
            '_meta_subpage': subpage
        }
        headers = {'Referer': self.base_page}
        r = self.session.get(self.api_url, params=params,
                             headers=headers, timeout=15)

        if r.status_code in (401, 403) and retries > 0:
            print("Session likely expired, refreshing...")
            self.refresh_session()
            return self.fetch_stats(tmcl, post_id, subpage, retries=retries - 1)

        r.raise_for_status()
        return r.json()


if __name__ == '__main__':
    scraper = AnalystScraper()
    scraper.refresh_session()

    data = scraper.fetch_stats(
        tmcl='51r6ph2woavlbbpk8f29nynf8',
        post_id='135731',
        subpage='stats'
    )

    with open('data/analyst_raw.json', 'w') as f:
        json.dump(data, f, indent=2)

    print('Saved. Top keys:', list(data.keys())[:10])
