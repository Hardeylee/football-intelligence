"""
diff_golden_predictions.py

Companion tool to snapshot_golden_predictions.py -- flagged in that
script's own docstring as "the natural next tool to build once the
MatchContext refactor actually exists and there's a second snapshot to
compare against." That moment is now: data/golden_snapshot_post_matchcontext.json
exists alongside the original data/golden_snapshot_pre_matchcontext.json.

Unlike diagnose_match_context_sanity.py (deleted after use, since it
duplicated pipeline logic -- a KEEP IN SYNC risk), this script only
diffs two JSON files against each other. It doesn't reproduce any
model logic, so there's nothing here to drift out of sync as
match_predictor.py changes. Safe to keep permanently and reuse for any
future pre/post-refactor safety check, not just this one.

WHAT COUNTS AS A DIFFERENCE
----------------------------
Every field inside each fixture's predict_match() output (result/
goals/cards/corners/h2h/home_manager/away_manager/formation), compared
recursively. Floats are compared with a small tolerance (default 1e-6)
to avoid flagging harmless floating-point noise as a regression --
these two snapshots ran the real pipeline twice, so any float
differences beyond this tolerance are a genuine behavior change, not
rounding jitter.

"generated" is not present in either snapshot (already stripped by
snapshot_golden_predictions.py), so no special-casing needed here.

USAGE
-----
    python -m src.utils.diff_golden_predictions

    # Point at different files:
    python -m src.utils.diff_golden_predictions --before data/golden_snapshot_pre_matchcontext.json --after data/golden_snapshot_post_matchcontext.json
"""

import argparse
import json


def flatten(d, prefix=""):
    """Flattens a nested dict into {dotted.path: value} for easy
    field-by-field comparison and reporting."""
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = d
    return out


def values_differ(a, b, float_tol=1e-6) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) > float_tol
    return a != b


def diff_fixture(before: dict, after: dict, float_tol=1e-6) -> list:
    """Returns a list of (field, before_val, after_val) for every field
    that differs, added, or removed between one fixture's before/after
    output."""
    flat_before = flatten(before)
    flat_after = flatten(after)

    diffs = []
    all_fields = set(flat_before) | set(flat_after)
    for field in sorted(all_fields):
        b = flat_before.get(field, "<MISSING>")
        a = flat_after.get(field, "<MISSING>")
        if b == "<MISSING>" or a == "<MISSING>":
            diffs.append((field, b, a))
        elif values_differ(b, a, float_tol):
            diffs.append((field, b, a))
    return diffs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--before", default="data/golden_snapshot_pre_matchcontext.json")
    parser.add_argument(
        "--after", default="data/golden_snapshot_post_matchcontext.json")
    parser.add_argument("--float-tol", type=float, default=1e-6,
                        help="tolerance for float comparisons (default 1e-6)")
    parser.add_argument("--max-fixtures-shown", type=int, default=25,
                        help="max number of differing fixtures to print in detail")
    args = parser.parse_args()

    with open(args.before) as f:
        before_snap = json.load(f)
    with open(args.after) as f:
        after_snap = json.load(f)

    before_fixtures = before_snap["fixtures"]
    after_fixtures = after_snap["fixtures"]

    print("=" * 80)
    print("  GOLDEN SNAPSHOT DIFF")
    print("=" * 80)
    print(f"  before: {args.before}")
    print(
        f"    git commit: {before_snap['metadata'].get('git_commit', '(unavailable)')}")
    print(f"    fixtures:   {len(before_fixtures)}")
    print(f"  after:  {args.after}")
    print(
        f"    git commit: {after_snap['metadata'].get('git_commit', '(unavailable)')}")
    print(f"    fixtures:   {len(after_fixtures)}")
    print()

    before_keys = set(before_fixtures)
    after_keys = set(after_fixtures)

    only_before = before_keys - after_keys
    only_after = after_keys - before_keys
    common = before_keys & after_keys

    if only_before:
        print(
            f"[WARN] {len(only_before)} fixture(s) in 'before' but missing from 'after':")
        for k in sorted(only_before)[:10]:
            print(f"  {k}")
        print()

    if only_after:
        print(
            f"[WARN] {len(only_after)} fixture(s) in 'after' but missing from 'before':")
        for k in sorted(only_after)[:10]:
            print(f"  {k}")
        print()

    print(f"Comparing {len(common)} fixtures present in both snapshots "
          f"(float tolerance: {args.float_tol})...\n")

    differing_fixtures = {}
    for key in sorted(common):
        diffs = diff_fixture(
            before_fixtures[key], after_fixtures[key], args.float_tol)
        if diffs:
            differing_fixtures[key] = diffs

    if not differing_fixtures:
        print("=" * 80)
        print(
            f"  RESULT: PASS -- zero differences across all {len(common)} fixtures.")
        print("  predict_match()'s output is identical before and after the")
        print("  MatchContext cutover. Safe to treat this as confirmed.")
        print("=" * 80)
        return

    print(
        f"[FAIL] {len(differing_fixtures)}/{len(common)} fixture(s) differ:\n")
    for i, (key, diffs) in enumerate(differing_fixtures.items()):
        if i >= args.max_fixtures_shown:
            print(
                f"  ...and {len(differing_fixtures) - args.max_fixtures_shown} more fixtures with differences")
            break
        print(f"  {key}")
        for field, b, a in diffs:
            print(f"    {field}: before={b!r}  after={a!r}")
        print()

    print("=" * 80)
    print(
        f"  RESULT: FAIL -- {len(differing_fixtures)} fixture(s) changed. Do not")
    print("  treat the MatchContext cutover as confirmed until every difference")
    print("  above is understood and either fixed or explicitly accepted as")
    print("  intentional.")
    print("=" * 80)


if __name__ == "__main__":
    main()
