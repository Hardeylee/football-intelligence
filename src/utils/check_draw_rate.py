import csv

files = ["data/raw/22-23.csv", "data/raw/23-24.csv",
         "data/raw/24-25.csv", "data/raw/25-26.csv"]
total, draws = 0, 0

for path in files:
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not row.get("FTHG") or not row.get("FTAG"):
                continue
            try:
                hg, ag = int(float(row["FTHG"])), int(float(row["FTAG"]))
            except (ValueError, TypeError):
                continue
            total += 1
            if hg == ag:
                draws += 1

print(f"{draws}/{total} draws = {draws/total:.1%}")
