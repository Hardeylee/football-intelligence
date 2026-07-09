from src.models.epl_elo import BASE_RATING, update_elo, PROMOTED_RATINGS
from src.models.asian_handicap import predict_ah
import csv as _csv

ratings = {}


def get_r(t):
    if t not in ratings:
        ratings[t] = BASE_RATING
    return ratings[t]


# Build training Elo
train = [("data/raw/22-23.csv", 35), ("data/raw/23-24.csv", 38)]
for fp, k in train:
    with open(fp, encoding="utf-8-sig") as f:
        for row in _csv.DictReader(f):
            try:
                h, a = row["HomeTeam"], row["AwayTeam"]
                hg, ag = int(float(row["FTHG"])), int(float(row["FTAG"]))
                hr, ar = update_elo(get_r(h), get_r(a), hg, ag, k)
                ratings[h], ratings[a] = hr, ar
            except:
                continue

for t, r in PROMOTED_RATINGS.items():
    ratings[t] = r

# Check first 15 matches of 24-25
print(f"{'Match':<35} {'Line':>5} {'Model':>6} {'Implied':>8} {'Edge':>6} {'Value':>6}")
print("-" * 70)

with open("data/raw/24-25.csv", encoding="utf-8-sig") as f:
    for i, row in enumerate(_csv.DictReader(f)):
        if i >= 15:
            break
        home = row["HomeTeam"]
        away = row["AwayTeam"]
        try:
            ah_line = float(row.get("AHh", 0) or 0)
            ah_h = float(row.get("B365AHH", 0) or 0)
            ah_a = float(row.get("B365AHA", 0) or 0)
        except:
            continue
        if not ah_h:
            continue

        pred = predict_ah(home, away, line=ah_line,
                          live_odds={"home_ah": ah_h, "away_ah": ah_a},
                          ratings=ratings)
        model = pred["home_prob"]
        implied = 1 / ah_h
        edge = model - implied
        vh = pred["value_home"]
        va = pred["value_away"]
        is_val = (vh and vh["value"]) or (va and va["value"])

        match = f"{home} vs {away}"
        print(f"{match:<35} {ah_line:>5.1f} {model:>6.0%} {implied:>8.0%} {edge:>+6.0%} {'YES' if is_val else 'no':>6}")
