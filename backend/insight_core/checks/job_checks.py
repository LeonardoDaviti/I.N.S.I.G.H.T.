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


def table_checksums(cur: Any) -> Dict[str, tuple]:
    """{table: (rows, md5 of its rows' md5s)} of every table but Mark X's mx_* (0079's per-table checksum)."""
    from psycopg import sql
    cur.execute("SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r' "
                "AND relname NOT LIKE 'mx\\_%' ORDER BY 1")
    out = {}
    for (table,) in cur.fetchall():
        cur.execute(sql.SQL("SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) "
                            "FROM (SELECT md5(x::text) h FROM {} x) s").format(sql.Identifier(table)))
        out[table] = tuple(cur.fetchone())
    return out


def _mx_rows(cur: Any) -> int:
    cur.execute("SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r' "
                "AND relname LIKE 'mx\\_%'")
    total = 0
    for (table,) in cur.fetchall():
        cur.execute(f"SELECT count(*) FROM {table}")
        total += cur.fetchone()[0]
    return total


def markx_unchanged(db_url: str, now: datetime) -> List[Found]:
    """0086 Safety 1: Mark IX's tables are the same with Mark X on and off. With Mark X off the scheduler runs nothing
    (no mx_* row is written); then two decision runs with it on (the second must find the first's work done) leave every
    table but mx_* row for row as it was. After the runs, the read-only Mark X invariants hold on what they wrote."""
    import os
    what = "Mark IX's tables (every table but mx_*) two decision runs with Mark X on change, or a run with it off"
    try:
        from insight_core.markx import decide
    except ImportError:
        return [Found("markx.ix_unchanged", "mark x", what, -1, 0, note="not measured: this version has no decision job")]
    from insight_core.checks import invariants
    with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:
        before, mx_before = table_checksums(cur), _mx_rows(cur)
    old = os.environ.get("INSIGHT_MARKX")
    started = time.monotonic()
    try:
        os.environ["INSIGHT_MARKX"] = "off"
        try:   # the scheduler moved to markx/jobs.py (0112 Decided 10); a version before has it in decide.py
            from insight_core.markx.jobs import Scheduler
        except ImportError:
            Scheduler = decide.Scheduler
        off = Scheduler(debounce=None, every=None).run_now()
        with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:
            off_rows = _mx_rows(cur) - mx_before
        os.environ["INSIGHT_MARKX"] = "on"
        runs = []
        for _ in range(2):
            with open_copy(db_url, writable=True) as conn, conn.cursor() as cur, conn.transaction():
                runs.append(decide.run(cur, now=now))
    finally:
        if old is None:
            os.environ.pop("INSIGHT_MARKX", None)
        else:
            os.environ["INSIGHT_MARKX"] = old
    with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:
        after = table_checksums(cur)
        run = invariants.Run(db_url, cur, now)
        mx = [invariants.Found(i.name, i.area, i.what, len(ids), of, run.sample(ids))
              for i in invariants.INVARIANTS if i.name.startswith("markx.") for ids, of in [i.count(run)]]
    seconds = round(time.monotonic() - started, 1)
    changed = sorted(t for t in set(before) | set(after) if before.get(t) != after.get(t))
    first, second = runs
    note = {"off": {"ran": off is not None, "mx_rows_written": off_rows},
            "first_run": {k: first.get(k) for k in ("stories", "posts", "questions", "answered", "changes", "news", "tasks_added")},
            "second_run": {"memberships": second.get("memberships"), "news_written": (second.get("news") or {}).get("written"),
                           "tasks_added": second.get("tasks_added")}}
    out = [Found("markx.ix_unchanged", "mark x", what, len(changed) + (1 if off_rows else 0) + (1 if off is not None else 0),
                 len(before), [f"{t}: {before.get(t)} -> {after.get(t)}" for t in changed][:EXAMPLES],
                 seconds, note=json.dumps(note, default=str))]
    out.append(Found("markx.after_run", "mark x", "the Mark X invariants on what the decision runs wrote (2-5, summed)",
                     sum(f.count for f in mx), sum(f.of for f in mx), [f"{f.name}: {e}" for f in mx for e in f.examples][:EXAMPLES],
                     note=json.dumps({f.name: f.count for f in mx})))
    return out


def check(db_url: str, now: datetime, identity: str = IDENTITY) -> List[Found]:
    scratch_only(db_url)
    found = rebuild_twice(db_url, now)
    found += markx_unchanged(db_url, now)
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
