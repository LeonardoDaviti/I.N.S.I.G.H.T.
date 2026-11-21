"""Hide the listing pages stored as posts before v10.35 (once): kept, never deleted.

    python -m insight_core.scripts.hide_listing_pages [--dry-run] [--source ID]

A feed's archive read a WordPress sitemap's taxonomy files and stored each tag page (a listing of one article, its
title, opening and date) as a post; page watch stored a few category and author pages. New reads refuse them
(page_watch.not_post, listing_address); this hides the ones stored before, through the source's item filter: each
source with a stored listing page (page_watch.stored_listing decides: a page its archive or page watch read as an
article, at a /tag/, /category/, /topic/, /author/ address; never a feed's item, a saved page or a release's tag)
gets the `listing` flag on its rule (item_filter.put_listing, `by` insight; its other patterns kept), and its posts
are marked again: filtered_by set, so the feeds, unread counts and Mark X's planners skip them. Nothing is deleted;
a post's stories, readings and track verdicts stay. --dry-run reads in a read-only transaction and writes nothing.
JSON summary: per source, whether a rule was added (or the flag joined its rule), the posts hidden, three samples.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Optional, Sequence

import psycopg

from insight_core.ingestion.kinds.page_watch import LISTING_SEGMENTS, SITE_PAGE_ADAPTERS
from insight_core.utils import item_filter

# The candidates, narrowed in SQL (a listing word among the path's segments, a site page's row); the decision is
# page_watch.stored_listing's, in Python.
_WORDS = "|".join(sorted(LISTING_SEGMENTS))
CANDIDATES_SQL = f"""
    SELECT {item_filter._FIELDS_SQL}, p.source_id::text,
           COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url)
      FROM posts p JOIN sources s ON s.id = p.source_id
     WHERE p.metadata->>'adapter' = ANY(%(adapters)s) AND p.external_id LIKE '/%%'
       AND lower(p.url) ~ '/({_WORDS})/[^/?#]+/?([?#].*)?$'
       AND (%(source)s::uuid IS NULL OR p.source_id = %(source)s::uuid)
     ORDER BY p.source_id, p.url"""


def run(conn: psycopg.Connection, *, dry_run: bool, source_id: Optional[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"dry_run": dry_run, "sources": [], "posts": 0}
    with conn.cursor() as cur:
        if dry_run:
            cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(CANDIDATES_SQL, {"adapters": sorted(SITE_PAGE_ADAPTERS), "source": source_id})
        by_source: Dict[str, Dict[str, Any]] = {}
        for row in cur.fetchall():
            if not item_filter._hides({"listing": True}, row):
                continue
            s = by_source.setdefault(row[6], {"source": row[6], "name": row[7], "listing_pages": 0, "samples": []})
            s["listing_pages"] += 1
            if len(s["samples"]) < 3:
                s["samples"].append(row[2])
        for sid, s in sorted(by_source.items(), key=lambda kv: -kv[1]["listing_pages"]):
            got = item_filter.current(cur, [sid]).get(sid)
            s["rule"] = ("has the flag" if got and (got["rule"] or {}).get("listing")
                         else "flag joins its rule" if got else "rule added")
            if not dry_run:
                item_filter.put_listing(cur, sid)
                cur.execute("""SELECT count(*) FROM posts p JOIN source_filters f ON f.id = p.filtered_by
                                WHERE p.source_id = %s AND f.rule ? 'listing'""", (sid,))
                s["hidden"] = cur.fetchone()[0]
            out["sources"].append(s)
            out["posts"] += s["listing_pages"]
    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source")
    args = ap.parse_args(argv)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        print(json.dumps(run(conn, dry_run=args.dry_run, source_id=args.source), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
