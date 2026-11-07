"""Read the refs of every post stored before post_refs (issue 0125), once, and time it.

    python -m insight_core.scripts.backfill_post_refs [--db DSN] [--batch N]

The story job does the same at its start (StoriesService.fill_refs: the backend's first start after the deploy
runs it in the background); this runs it by hand. A batch a transaction, `FOR UPDATE SKIP LOCKED`, resumable
(posts.refs_scanned_at: a stopped run goes on where it stopped). Then the signature pass over every source's refs.
Prints {posts, rows, seconds, peak_mb} as JSON. Reads no page, fetches nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db import database as db
from insight_core.db.repo_post_refs import REFS_BATCH, PostRefsRepository


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--batch", type=int, default=REFS_BATCH)
    args = ap.parse_args(argv)
    if not args.db:
        ap.error("--db or DATABASE_URL is needed")
    started = time.monotonic()
    posts = db.fill_until_done(args.db, lambda cur: PostRefsRepository.fill_missing(cur, args.batch),
                               PostRefsRepository.missing)
    filled_at = time.monotonic()
    with db.transaction(args.db) as cur:
        marked = PostRefsRepository.mark_boilerplate(cur)
        cur.execute("SELECT count(*) FROM post_refs WHERE valid_to IS NULL")
        rows = cur.fetchone()[0]
    print(json.dumps({"posts": posts, "rows": rows, "boilerplate_marked": marked,
                      "fill_seconds": round(filled_at - started, 1), "seconds": round(time.monotonic() - started, 1),
                      "peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
