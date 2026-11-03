"""The incremental story job equals a full rebuild (issue 0072 A), checked on a scratch copy.

    check(db_url, held=30, batches=3)   -> {"same": bool, "tables": {name: {rows, differing, ...}}, "runs": [...]}
    python -m insight_core.scripts.story_identity [held] [batches] [hours]

It changes the database it is given, so only a copy: it refuses the live and the lab's databases.
1. The newest `held` posts (by when they were stored) are held back, with their links, and removed.
2. A full run builds the state.
3. They come back in `batches` "fetches", the oldest stored first (posts and links, one transaction
   each), with an incremental run after each, the clock `hours` on each time (News's window moves).
4. Every derived table is read (`snapshot`), a full run at the last clock rebuilds over the same
   posts, and the tables are read again and compared row by row (`compare`).
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
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        incremental = snapshot(cur)
    runs.append(run("full", clock))
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        full = snapshot(cur)
        cur.execute("DROP TABLE IF EXISTS identity_held_posts, identity_held_links")
    tables = compare(incremental, full)
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
