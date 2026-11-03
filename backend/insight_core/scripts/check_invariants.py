"""Run the invariants over a whole copy (issue 0075 B).

    python -m insight_core.scripts.check_invariants --db <dsn> [--now ISO] [--json out.json]
                                                   [--baseline main.json] [--allow name=reason …] [--only name …]

Read-only. Prints one line per invariant: its count, how many things it looked at, its time. With
--baseline (another run's --json, main's on the same copy) it exits 1 when a count rose and no
--allow names the reason. The example ids go to --json only: keep it in plan/research/ (private).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from insight_core.checks import invariants
from insight_core.checks.session import copy_now, open_copy


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--now")
    ap.add_argument("--json")
    ap.add_argument("--baseline")
    ap.add_argument("--allow", nargs="*", default=[], help="name=reason: a rise the spec names")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int)
    args = ap.parse_args(argv)

    with open_copy(args.db) as conn, conn.cursor() as cur:
        run = invariants.Run(args.db, cur, copy_now(cur, args.now), workers=args.workers)
        found = invariants.run_all(run, args.only)
    for f in found:
        count = "n/a" if f.count < 0 else f"{f.count:>6}"
        print(f"{f.name:<34} {count} of {f.of:<7} {f.seconds:>5}s  {f.what}{'  (' + f.note + ')' if f.note else ''}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"now": run.now.isoformat(), "found": [asdict(f) for f in found]}, fh, ensure_ascii=False, indent=1)
    if args.baseline:
        with open(args.baseline, encoding="utf-8") as fh:
            base = {f["name"]: f["count"] for f in json.load(fh)["found"]}
        allowed = dict(a.split("=", 1) for a in args.allow)
        rose = invariants.compare(found, base, allowed)
        for line in rose:
            print(f"ROSE  {line}")
        return 1 if rose else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
