"""Title and date again the unreadable pages you saved from a link, once, by hand (v10.42).

    python -m insight_core.scripts.repair_saved_titles [--dry-run]

A page saved with metadata.unreadable whose title is a link's words to it (post_links.link_text) that read as no
title ("пишет", "here": post_links.titled_link_text) is titled as a save titles it now (SavedService.known_title,
else saved_service.unread_title: the slug, else the address); one dated by a linking post while its address names
an earlier day is dated by that day. The old title and date go to metadata.retitled_from. Nothing is deleted; the
source a post is under is left as it is. Prints each change and the totals as JSON lines.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from insight_core.db.migrate import get_conn
from insight_core.services.saved_service import SavedService, address_day_before, unread_title
from insight_core.utils.post_links import titled_link_text

CANDIDATES = """
    SELECT p.id::text, p.url, p.title, p.published_at, p.fetched_at FROM posts p
     WHERE p.metadata->>'adapter' = 'saved' AND (p.metadata->>'unreadable')::boolean
       AND EXISTS (SELECT 1 FROM post_links pl WHERE pl.target_url = COALESCE(p.normalized_url, p.url)
                     AND lower(btrim(pl.link_text)) = lower(btrim(p.title)))
     ORDER BY p.fetched_at, p.id
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    args = ap.parse_args()
    service = SavedService(os.environ["DATABASE_URL"], sources=None, source_config_sync=None, kinds=None)
    changed = 0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(CANDIDATES)
        for post_id, url, title, published_at, fetched_at in cur.fetchall():
            if titled_link_text(" ".join((title or "").split())):
                continue
            new_title = service.known_title([url]) or unread_title("", url)
            linked = service.first_linked([url], fetched_at or datetime.now(timezone.utc))
            day = address_day_before(url, fetched_at or datetime.now(timezone.utc))
            new_date = day if day is not None and published_at is not None and published_at == linked and day < published_at \
                else published_at
            print(json.dumps({"post_id": post_id, "url": url, "title": [title, new_title],
                              "published_at": [str(published_at), str(new_date)]}, ensure_ascii=False), flush=True)
            changed += 1
            if not args.dry_run:
                cur.execute("UPDATE posts SET title = %s, published_at = %s,"
                            " published_precision = CASE WHEN %s THEN 'date' ELSE published_precision END, metadata = metadata || jsonb_build_object("
                            "'retitled_from', jsonb_build_object('title', title, 'published_at', published_at)) "
                            "WHERE id = %s::uuid", (new_title, new_date, new_date != published_at, post_id))
        conn.rollback() if args.dry_run else conn.commit()
    print(json.dumps({"changed": changed, "dry_run": args.dry_run}))


if __name__ == "__main__":
    main()
