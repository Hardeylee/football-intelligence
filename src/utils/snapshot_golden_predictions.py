"""
snapshot_golden_predictions.py

SAFETY NET, NOT A DIAGNOSTIC. Calls the real predict_match() pipeline
end-to-end (result, goals, cards, corners, manager/formation
adjustments -- everything, not just the result market) for every
fixture in the 2024/25 season, and saves the full output to a JSON
file. This is the "snapshot known-good fixtures and diff old vs new
pipeline before cutover" step the roadmap flags as required before the
MatchContext refactor -- run this BEFORE any MatchContext code exists,
so there's a real, current-pipeline baseline to diff a future
MatchContext-refactored pipeline against, fixture by fixture, field by
field.

WHY SNAPSHOT DATA, NOT LIVE PRODUCTION DATA
---------------------------------------------
Uses the same backtest snapshot files as backtester_v4.py
(SNAPSHOT_PROFILES/SNAPSHOT_H2H/SNAPSHOT_ELO/SNAPSHOT_XG, force_promoted=
set(), apply_availability=False) rather than live production files.
This is deliberate: live team_profiles.json/h2h.json/elo ratings/
availability data change as the season progresses, and FORCE_PROMOTED's
meaning changes season to season. If this snapshot were built from live
data, a diff run next month would show differences caused by the
underlying data changing, not by any MatchContext code change --
exactly the kind of false-positive diff noise that would make this
safety net useless. Point-in-time snapshot data is frozen and won't
drift, so any future diff against it isolates pipeline BEHAVIOR changes
only.

WHY THE "generated" TIMESTAMP FIELD IS STRIPPED
--------------------------------------------------
predict_match()'s return dict includes "generated":
datetime.now().isoformat() -- this is different on every single call,
snapshot or not. Left in, a diff against a future re-run would show a
mismatch on literally every fixture regardless of whether any real
pipeline behavior changed, burying any actual regression under 380
lines of timestamp noise. This field is deliberately excluded from what
gets hashed/compared -- captured once in the top-level metadata instead
(when THIS snapshot was generated), not per-fixture.

WHAT GETS SAVED
------------------
data/golden_snapshot_pre_matchcontext.json:
    {
      "metadata": {
        "generated_at": ...,
        "git_commit": ... (if available, else null),
        "snapshot_files": [profiles/h2h/elo/xg paths used],
        "test_season_file": ...,
        "total_fixtures": ...,
        "skipped_fixtures": [...],
      },
      "fixtures": {
        "HomeTeam vs AwayTeam (Date)": { full predict_match() output,
                                          minus the "generated" field },
        ...
      }
    }

Fixture keys include the date because the same two teams can meet
twice in a season (home and away legs) -- team-name-only keys would
silently collide and overwrite one leg's snapshot with the other's.

USAGE
-----
    python src/utils/snapshot_golden_predictions.py

    # Re-run later (e.g. right before MatchContext cutover, to catch
    # any drift from other unrelated changes in between):
    python src/utils/snapshot_golden_predictions.py --out data/golden_snapshot_pre_matchcontext_v2.json

THIS SCRIPT DOES NOT DIFF ANYTHING. It only captures the baseline. A
diff_golden_predictions.py companion script (loads two snapshot JSONs,
reports every fixture/field that differs) is the natural next tool to
build once the MatchContext refactor actually exists and there's a
second snapshot to compare against -- not built yet since there's
nothing to diff against until then.
"""

# isort: skip_file
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEFAULT_OUTPUT = "data/golden_snapshot_pre_matchcontext.json"


def get_git_commit() -> str:
    """Best-effort git commit hash for provenance. Returns None if git
    isn't available or this isn't a git repo -- not fatal, just means
    the metadata is a little less useful."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return None


def strip_nondeterministic_fields(pred: dict) -> dict:
    """Removes the "generated" timestamp field (see module docstring)
    so the saved snapshot is stable across re-runs when nothing about
    the actual pipeline has changed. Shallow copy -- predict_match()'s
    return dict is flat enough that this is safe; nested dicts
    (result/goals/cards/corners/etc.) are untouched, only the top-level
    "generated" key is dropped."""
    cleaned = dict(pred)
    cleaned.pop("generated", None)
    return cleaned


def build_snapshot(output_path: str) -> dict:
    from src.utils.backtester_v4 import (
        load_csv_file, TEST_SEASON_FILE,
        SNAPSHOT_PROFILES, SNAPSHOT_H2H, SNAPSHOT_ELO, SNAPSHOT_XG,
    )
    from src.models.match_predictor import predict_match

    for path in (SNAPSHOT_PROFILES, SNAPSHOT_H2H, SNAPSHOT_ELO, SNAPSHOT_XG):
        full_path = os.path.join(PROJECT_ROOT, path)
        if not os.path.exists(full_path):
            print(f"[ERROR] Missing snapshot file: {path}")
            print("  Run build_snapshot_profiles.py, build_snapshot_elo.py, "
                  "and build_snapshot_xg.py first -- same requirement as "
                  "backtester_v4.py.")
            return {}

    matches = load_csv_file(TEST_SEASON_FILE)
    print(f"Loaded {len(matches)} fixtures from {TEST_SEASON_FILE}")
    print("Running the real predict_match() pipeline for every fixture "
          "(this is the slow part -- same cost as a full backtester_v4.py "
          "scoring pass)...\n")

    fixtures = {}
    skipped = []

    for i, m in enumerate(matches):
        home, away = m["HomeTeam"], m["AwayTeam"]
        referee = m.get("Referee", "")
        date = m.get("Date", "?")
        key = f"{home} vs {away} ({date})"

        try:
            pred = predict_match(
                home, away, referee,
                profiles_path=SNAPSHOT_PROFILES,
                h2h_path=SNAPSHOT_H2H,
                elo_path=SNAPSHOT_ELO,
                xg_path=SNAPSHOT_XG,
                apply_availability=False,
                force_promoted=set(),
            )
        except Exception as e:
            skipped.append({"fixture": key, "error": str(e)})
            print(f"  [SKIP] {key}: {e}")
            continue

        fixtures[key] = strip_nondeterministic_fields(pred)

        if (i + 1) % 50 == 0:
            print(f"  ...{i + 1}/{len(matches)} fixtures done")

    print(f"\nCaptured {len(fixtures)} fixtures, skipped {len(skipped)}.")

    snapshot = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "git_commit": get_git_commit(),
            "snapshot_files": {
                "profiles": SNAPSHOT_PROFILES,
                "h2h": SNAPSHOT_H2H,
                "elo": SNAPSHOT_ELO,
                "xg": SNAPSHOT_XG,
            },
            "test_season_file": TEST_SEASON_FILE,
            "total_fixtures": len(matches),
            "captured_fixtures": len(fixtures),
            "skipped_fixtures": skipped,
            "note": (
                "This is the pipeline's real predict_match() output, captured "
                "BEFORE the MatchContext refactor, using frozen point-in-time "
                "snapshot data (not live production files) so a future diff "
                "isolates pipeline behavior changes rather than data drift. "
                "The 'generated' timestamp field is stripped from every "
                "fixture's output for the same reason -- see module "
                "docstring in snapshot_golden_predictions.py."
            ),
        },
        "fixtures": fixtures,
    }

    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUTPUT,
                        help=f"output path (default: {DEFAULT_OUTPUT})")
    args = parser.parse_args()

    print("=" * 70)
    print("  GOLDEN SNAPSHOT — pre-MatchContext baseline")
    print("=" * 70 + "\n")

    snapshot = build_snapshot(args.out)
    if not snapshot:
        sys.exit(1)

    full_out_path = os.path.join(PROJECT_ROOT, args.out)
    os.makedirs(os.path.dirname(full_out_path), exist_ok=True)

    if os.path.exists(full_out_path):
        print(f"\n[WARN] {args.out} already exists and will be overwritten. "
              f"If you meant to keep the existing golden snapshot and add a "
              f"newer comparison point, re-run with --out pointing at a "
              f"different filename instead.")

    with open(full_out_path, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)

    print(f"\nSaved → {args.out}")
    print(f"  {snapshot['metadata']['captured_fixtures']} fixtures captured, "
          f"{len(snapshot['metadata']['skipped_fixtures'])} skipped")
    print(
        f"  git commit: {snapshot['metadata']['git_commit'] or '(unavailable)'}")
    print(
        "\nThis file is the baseline for the MatchContext cutover. Do not "
        "regenerate it casually once the MatchContext design work starts -- "
        "it needs to represent the pipeline's behavior BEFORE that refactor "
        "began. Commit it to git so it survives independently of any local "
        "changes."
    )


if __name__ == "__main__":
    main()
