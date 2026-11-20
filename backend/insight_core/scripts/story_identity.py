"""The incremental story job equals a full rebuild (issue 0072 A), checked on a scratch copy.

    check(db_url, held=30, batches=3)   -> {"same": bool, "tables": {name: {rows, differing, ...}}, "runs": [...]}
    same_rows(a, b)                     -> the same, for two databases (URLs or connections) already built
    python -m insight_core.scripts.story_identity [held] [batches] [hours]

It changes the database it is given, so only a copy: it refuses the live and the lab's databases.
1. The newest `held` posts (by when they were stored) are held back, with their links, and removed.
2. A full run builds the state.
3. They come back in `batches` "fetches", the oldest stored first (posts and links, one transaction
   each), with an incremental run after each, the clock `hours` on each time (News's window moves).
4. Every derived table is kept in the copy (`keep`: one unlogged table each, its rows and each row's
   md5 of its text), a full run at the last clock rebuilds over the same posts, the tables are kept
   again, and the two are compared row by row in SQL (`compare_kept`, 0253): only the differing rows
   come to Python, as `compare` shows them. `snapshot` and `compare` hold every row as JSON text in
   Python (4M rows at the server's size, twice): `same_rows` (two databases) still uses them.
`run(mode, clock)` runs a job ("full" or "incremental"): in this process unless the caller times
it in its own (the lab's measurements did).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set

import psycopg
from psycopg.conninfo import conninfo_to_dict

PROTECTED = ("insight", "insight_lab", "insight_server_copy")

TABLES = {
    "stories": "SELECT id, first_at, voices, origin_url, origin_title, origin_linked_by FROM stories",
    "story_posts": "SELECT post_id, story_id, role, reasons, voice, parent_id, parent_reason, parent_url, position "
                   "FROM story_posts",
    "story_mentions": "SELECT story_id, post_id FROM story_mentions",
    "post_edges": "SELECT src_post, dst_post, dst_url, dst_story, kind, weight, evidence, made_by FROM post_edges",
    "story_keys": "SELECT key, post_id FROM story_keys",
    "post_links": "SELECT post_id, target_url, boilerplate FROM post_links",
    "news_stories": "SELECT id, first_at, voices, reports, shares, mentions, round(score, 2) FROM news_stories",
    "news_posts": "SELECT post_id, news_id, role, voice, name, position FROM news_posts",
    "news_surges": "SELECT name, at, posts, usual FROM news_surges",
    "classics": "SELECT target_url, post_id, voices, first_at, last_at, title, citers FROM classics",
    "discover_addresses": "SELECT url, key, site, platform, article, rules FROM discover_addresses",
    "discover_counts": "SELECT f::text FROM system_settings, jsonb_array_elements(value->'found') f "
                       "WHERE key = 'discover_counts'",
    "discover_mirrors": "SELECT value->'mirrors' FROM system_settings WHERE key = 'discover_counts'",
}


def snapshot(cur: Any) -> Dict[str, Set[str]]:
    """Every row of every table the story job derives, each as text."""
    out = {}
    for name, sql in TABLES.items():
        cur.execute(sql)
        out[name] = {json.dumps(row, default=str, sort_keys=True) for row in cur.fetchall()}
    return out


def compare(a: Dict[str, Set[str]], b: Dict[str, Set[str]], shown: int = 5) -> Dict[str, Dict[str, Any]]:
    """Per table: its rows (in `b`), how many differ, and a few of each side's."""
    return {name: {"rows": len(b[name]), "differing": len(a[name] ^ b[name]),
                   "only_first": sorted(a[name] - b[name])[:shown], "only_second": sorted(b[name] - a[name])[:shown]}
            for name in TABLES}


KEPT = "identity_kept"          # identity_kept_<state>_<table>: unlogged tables in the copy, dropped after


def _kept(state: str, name: str) -> str:
    return f"{KEPT}_{state}_{name}"


def _keep_one(cur: Any, state: str, name: str) -> None:
    from psycopg import sql as q
    table = q.Identifier(_kept(state, name))
    cur.execute(q.SQL("DROP TABLE IF EXISTS {}").format(table))
    cur.execute(q.SQL("CREATE UNLOGGED TABLE {} AS SELECT r.*, md5(r::text) AS h FROM ({}) r").format(table, q.SQL(TABLES[name])))


def _each(db_url: str, work: Callable[[Any, str], Any]) -> Dict[str, Any]:
    """`work(cur, name)` for every table of TABLES at once, a connection each (Postgres does the work)."""
    from concurrent.futures import ThreadPoolExecutor

    def one(name: str) -> Any:
        with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
            return work(cur, name)
    with ThreadPoolExecutor(max_workers=len(TABLES)) as pool:
        return dict(zip(TABLES, pool.map(one, TABLES)))


def keep(cur: Any, state: str, db_url: Optional[str] = None) -> None:
    """Every table the story job derives (TABLES' queries), kept in the copy as it is now: per table an unlogged table
    of its rows and `h`, the md5 of the row's text. Nothing comes to Python. With `db_url`, the tables at once."""
    if db_url:
        _each(db_url, lambda c, name: _keep_one(c, state, name))
        return
    for name in TABLES:
        _keep_one(cur, state, name)


def drop_kept(cur: Any, states=("first", "second")) -> None:
    from psycopg import sql as q
    for state in states:
        for name in TABLES:
            cur.execute(q.SQL("DROP TABLE IF EXISTS {}").format(q.Identifier(_kept(state, name))))


def _only(cur: Any, mine: str, other: str, shown: int) -> "tuple[int, List[str]]":
    """The rows of `mine` (a kept table) that `other` lacks, as `compare` counts them (distinct) and the first `shown`
    of them as `compare` shows them: JSON text, sorted. Streamed: a few rows held, however many differ."""
    import heapq
    from psycopg import sql as q
    a, b = q.Identifier(mine), q.Identifier(other)
    cur.execute(q.SQL("SELECT count(*) FROM (SELECT h FROM {} EXCEPT SELECT h FROM {}) d").format(a, b))
    count = cur.fetchone()[0]
    if not count:
        return 0, []
    # each differing row once (DISTINCT ON its text's hash), streamed: the smallest few kept, however many differ
    with cur.connection.transaction(), cur.connection.cursor(name="identity_only") as named:
        named.itersize = 5000
        named.execute(q.SQL("SELECT DISTINCT ON (h) * FROM {} WHERE h IN (SELECT h FROM {} EXCEPT SELECT h FROM {})")
                      .format(a, a, b))
        at = [c.name for c in named.description].index("h")
        texts = (json.dumps(row[:at] + row[at + 1:], default=str, sort_keys=True) for row in named)
        return count, sorted(set(heapq.nsmallest(shown * 2, texts)))[:shown]


def _compare_one(cur: Any, name: str, first: str, second: str, shown: int) -> Dict[str, Any]:
    from psycopg import sql as q
    a, b = _kept(first, name), _kept(second, name)
    cur.execute(q.SQL("SELECT count(*) FILTER (WHERE y.h IS NOT NULL), count(*) FILTER (WHERE y.h IS NULL), "
                      "count(*) FILTER (WHERE x.h IS NULL) FROM (SELECT DISTINCT h FROM {}) x "
                      "FULL JOIN (SELECT DISTINCT h FROM {}) y ON x.h = y.h").format(q.Identifier(a), q.Identifier(b)))
    rows, n_first, n_second = cur.fetchone()
    only_first = _only(cur, a, b, shown)[1] if n_first else []
    only_second = _only(cur, b, a, shown)[1] if n_second else []
    return {"rows": rows, "differing": n_first + n_second, "only_first": only_first, "only_second": only_second}


def compare_kept(cur: Any, first: str = "first", second: str = "second", shown: int = 5,
                 db_url: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """`compare` of two kept states, in SQL: per table its distinct rows in `second`, how many rows are in one state
    only, and a few of each side's (JSON text, sorted, as `compare` shows them). Rows are compared by their text (its
    md5): what the JSON of `snapshot` tells apart, the row text does too. With `db_url`, the tables at once."""
    if db_url:
        return _each(db_url, lambda c, name: _compare_one(c, name, first, second, shown))
    return {name: _compare_one(cur, name, first, second, shown) for name in TABLES}


def same_rows(a: Any, b: Any) -> Dict[str, Any]:
    """Every table the story job derives, compared row by row between two databases (each a URL or an
    open connection): {"same", "tables"}. Read only."""
    def read(db: Any) -> Dict[str, Set[str]]:
        if isinstance(db, str):
            with psycopg.connect(db) as conn, conn.cursor() as cur:
                return snapshot(cur)
        with db.cursor() as cur:
            return snapshot(cur)
    tables = compare(read(a), read(b))
    return {"same": all(t["differing"] == 0 for t in tables.values()), "tables": tables}


def in_process(db_url: str) -> Callable[[str, datetime], Dict[str, Any]]:
    from insight_core.services.stories_service import StoriesService

    def run(mode: str, clock: datetime) -> Dict[str, Any]:
        return StoriesService(db_url, clock=lambda: clock).recompute(full=mode == "full")
    return run


def check(db_url: str, *, held: int = 30, batches: int = 3, hours: float = 2.0, clock: Optional[datetime] = None,
          run: Optional[Callable[[str, datetime], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The check (the module's notes). Returns {"same", "tables", "runs"}."""
    name = str(conninfo_to_dict(db_url).get("dbname") or "")
    if name in PROTECTED:
        raise ValueError(f"{name} is not a scratch copy")
    run = run or in_process(db_url)
    clock = clock or datetime.now(timezone.utc)
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS identity_held_posts, identity_held_links")
        cur.execute("SELECT id FROM posts ORDER BY created_at DESC, id DESC LIMIT %s", (held,))
        ids = [r[0] for r in cur.fetchall()][::-1]   # the oldest stored first
        cur.execute("CREATE TABLE identity_held_posts AS SELECT * FROM posts WHERE id = ANY(%s)", (ids,))
        cur.execute("CREATE TABLE identity_held_links AS SELECT * FROM post_links WHERE post_id = ANY(%s)", (ids,))
        cur.execute("UPDATE identity_held_posts SET album_of = NULL WHERE album_of = ANY(%s)", (ids,))
        cur.execute("DELETE FROM posts WHERE id = ANY(%s)", (ids,))
    runs: List[Dict[str, Any]] = [run("full", clock)]
    size = -(-len(ids) // max(1, batches))
    for i in range(0, len(ids), size):
        chunk = ids[i:i + size]
        with psycopg.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO posts SELECT * FROM identity_held_posts WHERE id = ANY(%s) ORDER BY created_at", (chunk,))
            cur.execute("INSERT INTO post_links SELECT * FROM identity_held_links WHERE post_id = ANY(%s)", (chunk,))
        clock += timedelta(hours=hours)
        runs.append(run("incremental", clock))
    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        keep(cur, "first", db_url)               # the incremental job's rows
    runs.append(run("full", clock))
    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        keep(cur, "second", db_url)              # the full rebuild's
        try:
            tables = compare_kept(cur, db_url=db_url)
        finally:
            drop_kept(cur)
            cur.execute("DROP TABLE IF EXISTS identity_held_posts, identity_held_links")
    return {"same": all(t["differing"] == 0 for t in tables.values()), "tables": tables, "runs": runs}


if __name__ == "__main__":
    import os

    args = [float(a) for a in sys.argv[1:4]]
    result = check(os.environ["DATABASE_URL"], held=int(args[0]) if args else 30,
                   batches=int(args[1]) if len(args) > 1 else 3, hours=args[2] if len(args) > 2 else 2.0)
    for table, found in result["tables"].items():
        print(f"{table:20} rows {found['rows']:8}  differing {found['differing']}")
    print("identical" if result["same"] else "different")
    sys.exit(0 if result["same"] else 1)
