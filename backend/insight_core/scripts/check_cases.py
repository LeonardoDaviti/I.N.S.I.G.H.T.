"""Run the judged cases against a copy (issue 0075 A).

    python -m insight_core.scripts.check_cases --db <dsn> --cases <cases.json> [--now ISO] [--only id …]
                                              [--verbose] [--json out.json]

Read-only: every connection it opens refuses writes. One line per case; exits 1 when a case marked
`pass` fails (or can't be asked), and lists the cases marked `fail` that pass now and the kinds it
doesn't check. The cases hold the owner's data: keep them, and --json's output, in plan/research/.
"""
from __future__ import annotations

import argparse
import json
import sys

from insight_core.checks import cases
from insight_core.checks.session import copy_now, open_copy
from insight_core.checks.surfaces import Context


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--now", help="the clock the services read (default: the copy's last fetch)")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", help="write every result here")
    args = ap.parse_args(argv)

    all_cases = cases.load(args.cases)
    with open_copy(args.db) as conn, conn.cursor() as cur:
        ctx = Context(args.db, copy_now(cur, args.now), cur)
        results = cases.run(ctx, all_cases, args.only)
    print("\n".join(cases.lines(results, args.verbose)))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"now": ctx.now.isoformat(), "summary": cases.summary(results),
                       "results": [{"id": r.id, "kind": r.case.get("kind"), "marked": r.marked, "status": r.status,
                                    "details": r.details} for r in results]}, f, ensure_ascii=False, indent=1)
    return 1 if cases.summary(results)["broken"] else 0


if __name__ == "__main__":
    sys.exit(main())
