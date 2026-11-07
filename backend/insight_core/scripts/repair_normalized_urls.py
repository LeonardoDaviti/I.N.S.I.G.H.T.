"""Fill the address fields of the posts stored without them, once (issue 0130 E1).

    python -m insight_core.scripts.repair_normalized_urls [--db DSN] [--batch N] [--dry-run]

1,146 posts of the server's copy of 2026-11-05 (7 sources, all fetched 18-21 March 2026) have an address but no
`normalized_url` (nor `canonical_url`, nor `url_host`), so every read that matches posts by `normalized_url` (News,
stories, Discover, originals, the linked line) misses them. This fills each by today's rule, the save path's own
(utils/post_fields.build_post_fields: normalize_url, canonicalize_url, extract_url_host of the post's url), and only
where the column is empty: nothing filled before is changed, no post is removed (two posts of one address stay two
posts; the story job's queue regroups the ones filled, as for any address change).

A batch a transaction, oldest id first, its rows `FOR UPDATE SKIP LOCKED`: a stopped run goes on where it stopped,
and two at once never write one row twice. A post with no http(s) address is left as it is (none on the server's
copy); one today's rule cannot read is left and counted. The deploy's first start runs it (the ingestion process, logged); this runs it by hand.
Prints {posts, filled, unreadable, seconds} as JSON. Reads no page, fetches nothing.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db import database as db  # noqa: E402
from insight_core.utils.url_normalization import canonicalize_url, extract_url_host, normalize_url  # noqa: E402

logger = logging.getLogger("insight.repair_normalized_urls")

BATCH = 500
# What is missing: an http(s) address of the post's own, no normalized form of it (the invariant's scope:
# post.address_unnormalized). Anything else in `url` is no address today's rule reads.
MISSING_SQL = "normalized_url IS NULL AND url ~* '^https?://'"


def missing(cur: Any) -> int:
    """How many posts have an address and no normalized_url."""
    cur.execute(f"SELECT count(*) FROM posts WHERE {MISSING_SQL}")
    return int(cur.fetchone()[0])


def fill_batch(cur: Any, after: str, batch: int = BATCH) -> Dict[str, Any]:
    """One batch past id `after`: {seen, filled, unreadable, last}. last None: none left past `after`."""
    cur.execute(f"SELECT id::text, url FROM posts WHERE {MISSING_SQL} AND id::text > %s "
                "ORDER BY id::text LIMIT %s FOR UPDATE SKIP LOCKED", (after, batch))
    rows = cur.fetchall()
    filled = unreadable = 0
    for post_id, url in rows:
        normalized = normalize_url(url)
        if not normalized:
            unreadable += 1
            continue
        cur.execute(
            "UPDATE posts SET normalized_url = %s, canonical_url = COALESCE(canonical_url, %s), "
            "url_host = COALESCE(url_host, %s) WHERE id = %s::uuid AND normalized_url IS NULL",
            (normalized, canonicalize_url(url) or normalized, extract_url_host(url), post_id))
        filled += cur.rowcount or 0
    return {"seen": len(rows), "filled": filled, "unreadable": unreadable, "last": rows[-1][0] if rows else None}


def repair(db_url: str, *, batch: int = BATCH, dry_run: bool = False) -> Dict[str, Any]:
    """Fill every post's missing address fields (see the module docstring). Returns the counts and the time."""
    started = time.monotonic()
    with db.connection(db_url) as conn, conn.cursor() as cur:
        before = missing(cur)
    totals = {"posts": before, "filled": 0, "unreadable": 0}
    if dry_run or not before:
        return {**totals, "dry_run": dry_run, "seconds": round(time.monotonic() - started, 2)}
    after = ""
    while True:
        with db.transaction(db_url) as cur:
            found = fill_batch(cur, after, batch)
        totals["filled"] += found["filled"]
        totals["unreadable"] += found["unreadable"]
        if found["last"] is None:
            break
        after = found["last"]
    return {**totals, "seconds": round(time.monotonic() - started, 2)}


def repair_safely(db_url: str) -> Optional[Dict[str, Any]]:
    """The deploy's first start: the repair, logged; never raises (the process starts either way)."""
    try:
        result = repair(db_url)
    except Exception:  # noqa: BLE001 - the repair is never worth the start
        logger.exception("Addresses: could not fill the posts stored without a normalized address")
        return None
    if result["posts"]:
        logger.info("Addresses: %s of %s posts stored without a normalized address filled (%s unreadable) in %ss",
                    result["filled"], result["posts"], result["unreadable"], result["seconds"])
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not args.db:
        ap.error("--db or DATABASE_URL is needed")
    print(json.dumps(repair(args.db, batch=args.batch, dry_run=args.dry_run)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
