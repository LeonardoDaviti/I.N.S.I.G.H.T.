"""Move another site's pages out of the source that stored them as its posts (once): kept, never deleted.

    python -m insight_core.scripts.repair_foreign_pages [--dry-run] [--source ID]

Before v10.13.9 an archive read the site of its feed's first item, so a link blog (its items link a newspaper)
crawled the newspaper's sitemap and stored its pages as the blog's posts; that made the newspaper the blog's home
site (SourceFacts.home_site), so OwnPages gave the blog every page of the newspaper, and a saved or collected
page of it landed under the blog too. A source's own pages are on its own site (archive_ladder.own_site): its
address's, the site its archive's ladder recorded, or the site archive_ladder.source_site reads from its feed now
(one request, asked only of a source with pages off the first two; an unreadable feed: the source is skipped).

A post is moved when it is on none of those and is a page read from an address (page_watch.read_from_address: an
archive's or page watch's page), or a page collected for it (`missed_by_feed`) or saved to it (`saved_by_owner`)
because it seemed the source's. It goes to the Saved source as an outside page is kept there: a collected
original, story_only (shown in its story and on its post page, no feed row, no unread count; saving it drops the
mark), a saved page as it was. Its row and id are kept (read state, stories, links stay); its external id becomes
its address (Saved's), and metadata.moved_from records {source_id, external_id, at, why: foreign_site}. The
sources' post statistics are refreshed. --dry-run reads in a read-only transaction. JSON summary per source.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

import psycopg

from insight_core.db import repo_post_stats
from insight_core.ingestion import archive_ladder
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import parsing, saved
from insight_core.ingestion.kinds.page_watch import read_from_address
from insight_core.utils.addresses import host_of
from insight_core.utils.post_fields import SAVED_KEY, STORY_ONLY_KEY

WHY = "foreign_site"
MOVED_KEY = "moved_from"
MISSED_KEY = "missed_by_feed"   # saved_service.collect_for_source's mark
SAMPLES = 3

SOURCES_SQL = """SELECT id::text, handle_or_url, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url),
                        settings->'archive'->'checkpoint'->'ladder'->>'site'
                   FROM sources WHERE platform <> %(saved)s AND (%(source)s::uuid IS NULL OR id = %(source)s::uuid)"""
POSTS_SQL = f"""SELECT p.id::text, p.url, p.external_id, p.metadata->>'adapter', p.metadata ? '{MISSED_KEY}',
                       p.metadata ? '{SAVED_KEY}'
                  FROM posts p WHERE p.source_id = %s::uuid"""


def is_candidate(external_id: Optional[str], adapter: Optional[str], missed: bool, saved_here: bool) -> bool:
    """Whether a post was stored because its page seemed the source's own (not because the feed carried it)."""
    return read_from_address(external_id, adapter) or missed or saved_here


def feed_site(feed: str, read_feed: Callable[[str], str]) -> str:
    """The source's own site as an archive reads it now (archive_ladder.source_site of its feed). Raises what the
    read raises."""
    text = read_feed(feed)
    items = [p["url"] for p in parsing.parse_feed_posts(text, feed) if isinstance(p.get("url"), str)]
    return archive_ladder.source_site(feed, text, items)


def _read_feed(url: str) -> str:
    async def fetch() -> str:
        return (await KindHttp().get_text(url))[0]
    return asyncio.run(fetch())


def foreign(url: str, feed: str, sites: Sequence[Optional[str]]) -> bool:
    """Whether an address is on none of the source's own sites (archive_ladder.own_site)."""
    return not any(archive_ladder.own_site(url, site or feed, feed) for site in sites)


def run(conn: psycopg.Connection, *, dry_run: bool, source_id: Optional[str],
        read_feed: Callable[[str], str] = _read_feed) -> Dict[str, Any]:
    out: Dict[str, Any] = {"dry_run": dry_run, "sources": [], "posts": 0, "skipped": []}
    now = datetime.now(timezone.utc).isoformat()
    with conn.cursor() as cur:
        if dry_run:
            cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT id::text FROM sources WHERE platform = %s AND handle_or_url = %s",
                    (saved.PLATFORM, saved.HANDLE))
        found = cur.fetchone()
        saved_id = found[0] if found else None
        cur.execute(SOURCES_SQL, {"saved": saved.PLATFORM, "source": source_id})
        for sid, feed, name, ladder_site in cur.fetchall():
            cur.execute(POSTS_SQL, (sid,))
            rows = cur.fetchall()
            sites: List[Optional[str]] = [None, ladder_site]   # None: the feed's own site
            moved = [row for row in rows if is_candidate(*row[2:6]) and foreign(row[1], feed, sites)]
            if not moved:
                continue
            try:
                sites.append(feed_site(feed, read_feed))
            except Exception as exc:  # noqa: BLE001 - its own site unknown: nothing of it is moved
                out["skipped"].append({"source": sid, "name": name, "candidates": len(moved), "error": str(exc)[:200]})
                continue
            moved = [row for row in moved if foreign(row[1], feed, sites)]
            if not moved:
                continue
            kinds = Counter("saved" if row[5] else "collected" if row[4] else "read_from_address" for row in moved)
            hosts = Counter(host_of(row[1]) for row in moved)
            s = {"source": sid, "name": name, "posts": len(rows), "moved": len(moved),
                 "share": round(len(moved) / len(rows), 3), "own_site": sites[-1], "kinds": dict(kinds),
                 "hosts": dict(hosts.most_common(5)), "samples": [row[1] for row in moved[:SAMPLES]]}
            if not dry_run:
                if saved_id is None:
                    raise SystemExit("No Saved source: save one page first, then run this again")
                s["done"] = _move(cur, saved_id, sid, moved, now)
            out["sources"].append(s)
            out["posts"] += len(moved)
        if not dry_run and out["posts"]:
            repo_post_stats.refresh(cur)
    out["sources"].sort(key=lambda s: -s["moved"])
    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    return out


def _move(cur: Any, saved_id: str, sid: str, rows: List[Sequence[Any]], now: str) -> int:
    """The rows to the Saved source, one statement per kind of row; returns how many moved."""
    by_kind: Dict[bool, List[str]] = defaultdict(list)   # saved by the owner -> ids
    for row in rows:
        by_kind[bool(row[5])].append(row[0])
    done = 0
    for saved_here, ids in by_kind.items():
        story_only = "" if saved_here else f" || jsonb_build_object('{STORY_ONLY_KEY}', true)"
        cur.execute(f"""UPDATE posts SET source_id = %(saved)s::uuid, external_id = url,
                               metadata = metadata{story_only} || jsonb_build_object('{MOVED_KEY}', jsonb_build_object(
                                   'source_id', source_id::text, 'external_id', external_id, 'at', %(at)s::text,
                                   'why', %(why)s::text))
                         WHERE id = ANY(%(ids)s::uuid[]) AND source_id = %(sid)s::uuid
                           AND NOT EXISTS (SELECT 1 FROM posts o WHERE o.source_id = %(saved)s::uuid
                                             AND o.external_id = posts.url)""",
                    {"saved": saved_id, "at": now, "why": WHY, "ids": ids, "sid": sid})
        done += cur.rowcount
    return done


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source")
    args = ap.parse_args(argv)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        print(json.dumps(run(conn, dry_run=args.dry_run, source_id=args.source), indent=2, ensure_ascii=False))
    return 0


__all__ = ["feed_site", "foreign", "is_candidate", "run"]

if __name__ == "__main__":
    raise SystemExit(main())
