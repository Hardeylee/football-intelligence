from src.collectors.injury_scraper import scrape_team_injuries

injuries = scrape_team_injuries('England', '703')
print(f'England injuries found: {len(injuries)}')
for i in injuries[:3]:
    print(f"  - {i['player']} ({i['position']}): {i['injury']}")
