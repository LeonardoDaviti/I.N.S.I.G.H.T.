"""Read the @mentions of the X and Bluesky posts stored before 0235, once, and time it.

    python -m insight_core.scripts.backfill_mentions [--db DSN] [--batch N]

A post saved after 0235 reads its mentions when it is saved (utils/post_links.extract_links); this reads them for the
posts stored before (StoriesRepository.fill_mentions): the posts of X and Bluesky sources whose text holds an @, a batch
a transaction, resumable (its place in system_settings `mentions_backfill`: a stopped run goes on where it stopped).
Each post's links are written as extract_links reads them now: the rows it had, plus its mentions (kind 'mention',
boilerplate, so no story, News or Mark X rule reads them). Then Discover's kept counts are dropped, so its next count
(the story job's, or Discover's own) is a full one that counts the mentions. Reads no page, fetches nothing, asks no
model. Prints {posts, mentions, seconds, peak_mb} as JSON. Not run by any job: run it by hand, once, after the deploy.
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
from insight_core.db.repo_discover import KEPT_KEY
from insight_core.db.repo_stories import LINKS_BATCH, StoriesRepository


def run(dsn: str, batch: int = LINKS_BATCH) -> dict:
    repo = StoriesRepository()
    started = time.monotonic()
    posts = db.fill_until_done(dsn, lambda cur: repo.fill_mentions(cur, batch), StoriesRepository.mentions_left)
    with db.transaction(dsn) as cur:
        cur.execute("SELECT count(*) FROM post_links WHERE kind = 'mention'")
        mentions = cur.fetchone()[0]
        if posts:
            cur.execute("DELETE FROM system_settings WHERE key = %s", (KEPT_KEY,))   # the next count counts them
    return {"posts": posts, "mentions": mentions, "seconds": round(time.monotonic() - started, 1),
            "peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--batch", type=int, default=LINKS_BATCH)
    args = ap.parse_args(argv)
    if not args.db:
        ap.error("--db or DATABASE_URL is needed")
    print(json.dumps(run(args.db, args.batch)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
