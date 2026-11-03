"""The tables the story job writes, row by row: read them, and compare two states (two runs on one copy,
or two copies). Every column but updated_at is read, so a version that adds a column is compared on it.

    python -m insight_core.checks.table_rows --a <dsn> --b <dsn> [--json out]

compares two databases' derived tables, read-only (e.g. main's and a branch's scratch copies after their
story jobs: a move that should change nothing must show 0, 0075's merge rule).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Set, Tuple

TABLES = ("stories", "story_posts", "story_mentions", "news_stories", "news_posts", "classics")
SKIP_COLUMNS = {"updated_at"}
SHOWN = 5

Tables = Dict[str, Set[Tuple[str, ...]]]


def read_tables(cur: Any, tables=TABLES) -> Tables:
    out: Tables = {}
    for table in tables:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s "
                    "ORDER BY ordinal_position", (table,))
        columns = [r[0] for r in cur.fetchall() if r[0] not in SKIP_COLUMNS]
        if not columns:
            continue
        cur.execute(f"SELECT {', '.join(f'{c}::text' for c in columns)} FROM {table}")
        out[table] = {tuple(r) for r in cur.fetchall()}
    return out


def by_table(a: Tables, b: Tables) -> Dict[str, int]:
    """table -> how many rows are in one state only, for the tables that differ."""
    return {t: len(a.get(t, set()) ^ b.get(t, set())) for t in sorted(set(a) | set(b)) if a.get(t, set()) ^ b.get(t, set())}


def differences(a: Tables, b: Tables, shown: int = SHOWN) -> Dict[str, Tuple[List[tuple], List[tuple]]]:
    """table -> (a few rows only in a, a few only in b), for the tables that differ."""
    return {t: (sorted(a.get(t, set()) - b.get(t, set()))[:shown], sorted(b.get(t, set()) - a.get(t, set()))[:shown])
            for t in by_table(a, b)}


def story_ids(tables: Tables) -> Dict[frozenset, str]:
    """A story's posts -> its id."""
    members: Dict[str, set] = {}
    for row in tables.get("story_posts", set()):
        members.setdefault(row[0], set()).add(row[1])
    return {frozenset(posts): sid for sid, posts in members.items()}


def main(argv=None) -> int:
    from insight_core.checks.session import open_copy
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    with open_copy(args.a) as ca, ca.cursor() as cur:
        a = read_tables(cur)
    with open_copy(args.b) as cb, cb.cursor() as cur:
        b = read_tables(cur)
    counts = by_table(a, b)
    for t in sorted(set(a) | set(b)):
        print(f"{t:<16} {len(a.get(t, ())):>8} | {len(b.get(t, ())):>8}  differing {counts.get(t, 0)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"by_table": counts, "examples": differences(a, b)}, f, ensure_ascii=False, indent=1)
    return 1 if counts else 0


if __name__ == "__main__":
    sys.exit(main())
