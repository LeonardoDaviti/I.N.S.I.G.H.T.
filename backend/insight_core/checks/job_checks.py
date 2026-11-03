"""The invariants that run the story job (issue 0075 B, "Stories"), so they only ever get a scratch copy
(job.scratch_only), after a full rebuild.

    python -m insight_core.checks.job_checks --db <scratch dsn> [--now ISO] [--identity module:function] [--json out]

- `story.rebuild_identity` and `story.id_changes`: a second full rebuild with no new posts writes the
  same rows (table_rows), and no story's id changes.
- `story.identity`: the incremental job equals a full rebuild, row by row (0072 A's oracle). That check
  belongs to the incremental job (`insight_core.scripts.story_identity.check`, its own slice); this
  calls it, pluggable by `--identity`, as `fn(db_url, clock=now)` -> {"same", "tables": {name: {"differing",
  "only_first", "only_second", "rows"}}}. On a version without it the invariant is "not measured", with
  a note saying so, never a silent pass.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from insight_core.checks import table_rows
from insight_core.checks.invariants import EXAMPLES, Found
from insight_core.checks.job import run_full, scratch_only
from insight_core.checks.session import copy_now, open_copy

IDENTITY = "insight_core.scripts.story_identity:check"


def rebuild_twice(db_url: str, now: datetime) -> List[Found]:
    with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:
        first = table_rows.read_tables(cur)
        started = time.monotonic()
        run_full(db_url, now)
        again = table_rows.read_tables(cur)
    seconds = round(time.monotonic() - started, 1)
    of = sum(len(rows) for rows in first.values())
    a, b = table_rows.story_ids(first), table_rows.story_ids(again)
    moved = sorted(f"{a[m]} -> {b[m]}" for m in a.keys() & b.keys() if a[m] != b[m])
    counts = table_rows.by_table(first, again)
    return [
        Found("story.rebuild_identity", "stories", "rows a second full rebuild with no new posts writes differently",
              sum(counts.values()), of, [f"{t}: -{x} +{y}" for t, (x, y) in table_rows.differences(first, again).items()][:EXAMPLES],
              seconds, note=json.dumps({"by_table": counts}) if counts else ""),
        Found("story.id_changes", "stories", "a story whose id changes in a rebuild with no new posts", len(moved), len(a), moved[:EXAMPLES]),
    ]


def _identity_function(spec: str) -> Optional[Callable[..., Dict[str, Any]]]:
    module, _, name = spec.partition(":")
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError):
        return None


def incremental_identity(db_url: str, now: datetime, spec: str = IDENTITY) -> Found:
    what = "rows the incremental job writes unlike a full rebuild (the incremental job's own check)"
    check = _identity_function(spec)
    if check is None:
        return Found("story.identity", "stories", what, -1, 0,
                     note=f"not measured: {spec} is not in this version (the incremental job brings it)")
    started = time.monotonic()
    result = check(db_url, clock=now)
    tables = result.get("tables", {})
    differing = {t: v.get("differing", 0) for t, v in tables.items() if v.get("differing")}
    examples = [f"{t}: -{v.get('only_first', [])[:1]} +{v.get('only_second', [])[:1]}" for t, v in tables.items() if v.get("differing")]
    return Found("story.identity", "stories", what, sum(differing.values()), sum(v.get("rows", 0) for v in tables.values()),
                 examples[:EXAMPLES], round(time.monotonic() - started, 1), note=json.dumps({"by_table": differing, "same": result.get("same")}))


def check(db_url: str, now: datetime, identity: str = IDENTITY) -> List[Found]:
    scratch_only(db_url)
    found = rebuild_twice(db_url, now)
    found.append(incremental_identity(db_url, now, identity))   # last: it holds posts back and brings them in again
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--now")
    ap.add_argument("--identity", default=IDENTITY, help="module:function of the incremental job's identity check")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    scratch_only(args.db)
    with open_copy(args.db, writable=True) as conn, conn.cursor() as cur:
        now = copy_now(cur, args.now)
    found = check(args.db, now, args.identity)
    for f in found:
        count = "n/a" if f.count < 0 else f"{f.count:>6}"
        print(f"{f.name:<34} {count} of {f.of:<7} {f.seconds:>5}s  {f.what}{'  (' + f.note + ')' if f.note else ''}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"now": now.isoformat(), "found": [asdict(f) for f in found]}, fh, ensure_ascii=False, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
