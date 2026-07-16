"""
Parses data/analyst_raw.json into a single flat per-player table.

Structure being parsed:
player
├── attack        -> overall, nonPenalty
├── possession    -> chanceCreation, passing
├── carries       -> overall
├── defending     -> overall, discipline
└── goalkeeping   -> overall

Each leaf is a list of dicts, one per player, keyed by player_id.
This script merges all leaves into one wide table, joined on player_id,
prefixing stat columns by category_subcategory to avoid name collisions.

Usage:
    python parse_player_stats.py
"""

import json
import pandas as pd
import sys

# Columns that are identity/metadata rather than stats — keep unprefixed,
# and only take them once (from the first table that has them).
IDENTITY_COLS = {
    "player_id", "player", "first_name", "last_name", "date_of_birth", "age",
    "team_id", "shirt_number", "squad_position", "squad_position_detailed",
    "player_uuid", "team_uuid", "contestantName", "contestantClubName",
    "contestantShortName", "contestantCode"
}


def load_data(competition="premier_league", data_dir="data"):
    path = f"{data_dir}/{competition}_raw.json"
    with open(path) as f:
        return json.load(f)


def build_player_table(data):
    player_data = data["player"]

    merged = None
    identity_frames = []

    for category, subcats in player_data.items():
        if category in ("lastUpdated", "league"):
            continue
        if not isinstance(subcats, dict):
            continue

        for subcat_name, records in subcats.items():
            if not isinstance(records, list) or not records:
                continue

            df = pd.DataFrame(records)

            if "player_id" not in df.columns:
                print(
                    f"Skipping {category}.{subcat_name} — no player_id column")
                continue

            # Capture identity columns from every table that has them
            id_cols_present = [
                c for c in IDENTITY_COLS if c in df.columns and c != "player_id"]
            if id_cols_present:
                identity_frames.append(
                    df[["player_id"] + id_cols_present].copy())

            # Stat columns = everything not identity, not player_id
            stat_cols = [
                c for c in df.columns if c not in IDENTITY_COLS and c != "player_id"]
            prefix = f"{category}_{subcat_name}_"
            renamed = df[["player_id"] + stat_cols].rename(
                columns={c: prefix + c for c in stat_cols}
            )

            if merged is None:
                merged = renamed
            else:
                merged = merged.merge(renamed, on="player_id", how="outer")

    # Combine identity info from all categories, keeping the first non-null
    # value per player_id for each identity column (fills gaps like goalkeepers
    # who are absent from the attack table but present elsewhere)
    identity_all = pd.concat(identity_frames, ignore_index=True)
    identity_df = identity_all.groupby("player_id", as_index=False).first()

    # Attach identity columns back
    final = identity_df.merge(merged, on="player_id", how="outer")
    return final


TEAM_IDENTITY_COLS = {"team_id", "team", "contestantName"}


def build_team_table(data):
    team_data = data["team"]

    merged = None
    identity_frames = []

    for category, subcats in team_data.items():
        if category in ("lastUpdated", "league"):
            continue
        if not isinstance(subcats, dict):
            continue

        for subcat_name, records in subcats.items():
            if not isinstance(records, list) or not records:
                continue

            df = pd.DataFrame(records)

            if "team_id" not in df.columns:
                print(f"Skipping {category}.{subcat_name} — no team_id column")
                continue

            id_cols_present = [
                c for c in TEAM_IDENTITY_COLS if c in df.columns and c != "team_id"]
            if id_cols_present:
                identity_frames.append(
                    df[["team_id"] + id_cols_present].copy())

            stat_cols = [
                c for c in df.columns if c not in TEAM_IDENTITY_COLS and c != "team_id"]
            prefix = f"{category}_{subcat_name}_"
            renamed = df[["team_id"] + stat_cols].rename(
                columns={c: prefix + c for c in stat_cols}
            )

            if merged is None:
                merged = renamed
            else:
                merged = merged.merge(renamed, on="team_id", how="outer")

    identity_all = pd.concat(identity_frames, ignore_index=True)
    identity_df = identity_all.groupby("team_id", as_index=False).first()

    final = identity_df.merge(merged, on="team_id", how="outer")
    return final


def dedup_columns(df, id_col):
    """
    Drops columns that are exact duplicates of another column (same values
    in every row). Keeps the first occurrence. Common in this dataset because
    fields like 'played' repeat identically across attack/defending/misc splits.
    """
    seen = {}
    drop_cols = []

    for col in df.columns:
        if col == id_col:
            continue
        # Use a tuple of values as a fingerprint (handles NaN safely via string cast)
        fingerprint = tuple(df[col].astype(str).fillna("NaN"))
        if fingerprint in seen:
            drop_cols.append(col)
        else:
            seen[fingerprint] = col

    if drop_cols:
        print(
            f"Dropping {len(drop_cols)} duplicate columns: {drop_cols[:10]}{'...' if len(drop_cols) > 10 else ''}")
    return df.drop(columns=drop_cols)


if __name__ == "__main__":
    competition = sys.argv[1] if len(sys.argv) > 1 else "premier_league"

    data = load_data(competition=competition)
    table = build_player_table(data)
    table = dedup_columns(table, "player_id")

    print(f"Players — Shape: {table.shape[0]} rows, {table.shape[1]} columns")
    out_path = f"data/{competition}_players_flat.csv"
    table.to_csv(out_path, index=False)
    print(f"Saved to {out_path}")

    team_table = build_team_table(data)
    team_table = dedup_columns(team_table, "team_id")
    print(
        f"\nTeams — Shape: {team_table.shape[0]} rows, {team_table.shape[1]} columns")
    team_out_path = f"data/{competition}_teams_flat.csv"
    team_table.to_csv(team_out_path, index=False)
    print(f"Saved to {team_out_path}")
