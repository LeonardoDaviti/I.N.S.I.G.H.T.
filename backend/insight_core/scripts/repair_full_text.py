"""Re-read stored teaser posts in full, once (the full-text repair).

    python -m insight_core.scripts.repair_full_text [--dry-run] [--source ID] [--limit N] [--retry]
    python -m insight_core.scripts.repair_full_text --entities [--dry-run] [--source ID]

Which posts: a body shorter than full_text.SHORT_BODY_CHARS, or a paid teaser of any length
(metadata.paywalled), that was never read from its page, newest first. How each is read again:
  - a source of the substack kind: its post from Substack's API (free posts come in full;
    paid ones only with the Substack session in Connections);
  - a generic RSS source: the article page, as new posts are read (ingestion/full_text.py),
    unless the source has `fetch_full_content: false` or the link is not an article;
  - every other kind is skipped: a tweet, a Telegram message, a Reddit post or a video
    description is the whole post.

Polite: the posts of one site are read one at a time, full_text.PAGE_DELAY_S apart, up to
SITE_CONCURRENCY sites at once. A site that fails STOP_AFTER_FAILURES times in a row is
blocking us; its remaining posts are left for the next run.

Every post read is marked metadata.full_text_checked_at, so the next run does not read it
again; --retry includes them (after adding a Substack session, say). --dry-run reads
nothing: it prints what a run would read. The summary is printed as JSON.

--entities reads no page: it decodes the HTML codes ("That&#39;s") left in the plain text
of posts stored before strip_html decoded them, in every stored post (or --source's).
With --dry-run it only counts the posts it would change.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db import database as db  # noqa: E402
from insight_core.db.repo_posts import FULL_TEXT_CHECKED, FULL_TEXT_FLAG, PostsRepository  # noqa: E402
from insight_core.ingestion import full_text  # noqa: E402
from insight_core.ingestion.http import KindHttp  # noqa: E402
from insight_core.ingestion.kinds import KindRegistry  # noqa: E402
from insight_core.ingestion.kinds.base import KindUnavailable  # noqa: E402
from insight_core.ingestion.kinds.substack import SUBSTACK_HOST_KEY, SubstackKind  # noqa: E402
from insight_core.utils.content_fingerprints import decode_entities  # noqa: E402

logger = logging.getLogger("insight.scripts.repair_full_text")

SITE_CONCURRENCY = 4
STOP_AFTER_FAILURES = 3

Item = Tuple[Dict[str, Any], Any]  # (candidate post, its source kind)


def plan(posts: Sequence[Dict[str, Any]], registry: KindRegistry) -> Tuple[Dict[str, List[Item]], Counter]:
    """The posts to read, grouped by site, and why the others are skipped."""
    sites: Dict[str, List[Item]] = defaultdict(list)
    skipped: Counter = Counter()
    for post in posts:
        source = post["source"]
        kind = registry.resolve(source)
        if isinstance(kind, SubstackKind):
            sites[SUBSTACK_HOST_KEY].append((post, kind))
        elif kind.name != "generic_rss":
            skipped[f"kind {kind.name}"] += 1
        elif not full_text.full_page_enabled(source):
            skipped["full page turned off for the source"] += 1
        elif not full_text.page_is_article(post["url"]):
            skipped["link is not an article"] += 1
        else:
            sites[(urllib.parse.urlparse(post["url"]).hostname or "").lower()].append((post, kind))
    return dict(sites), skipped


class Repair:
    def __init__(self, db_url: str, *, http: KindHttp, registry: KindRegistry,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.db_url = db_url
        self.http = http
        self.registry = registry
        self.clock = clock
        self.posts = PostsRepository(db_url)
        self.counts: Counter = Counter()
        self.stopped: Dict[str, str] = {}

    async def run(self, *, dry_run: bool = False, source_id: Optional[str] = None,
                  limit: Optional[int] = None, retry: bool = False, entities: bool = False) -> Dict[str, Any]:
        if entities:
            return await asyncio.to_thread(self._decode_entities, dry_run, source_id)
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            posts = self.posts.full_text_candidates(cur, short_chars=full_text.SHORT_BODY_CHARS,
                                                    source_id=source_id, retry=retry, limit=limit)
        sites, skipped = plan(posts, self.registry)
        summary: Dict[str, Any] = {
            "candidates": len(posts),
            "to_read": sum(len(items) for items in sites.values()),
            "sites": len(sites),
            "skipped": dict(skipped),
        }
        if dry_run:
            busiest = sorted(sites.items(), key=lambda site: (-len(site[1]), site[0]))
            summary["by_site"] = {host: len(items) for host, items in busiest}
            return summary
        gate = asyncio.Semaphore(SITE_CONCURRENCY)

        async def one_site(host: str, items: List[Item]) -> None:
            async with gate:
                await self._site(host, items)

        await asyncio.gather(*(one_site(host, items) for host, items in sites.items()))
        summary.update({
            "repaired": self.counts["repaired"],
            "nothing_longer": self.counts["nothing_longer"],
            "failed": self.counts["failed"],
            "left_for_next_run": self.counts["left"],
            "stopped_sites": self.stopped,
        })
        return summary

    def _decode_entities(self, dry_run: bool, source_id: Optional[str]) -> Dict[str, Any]:
        with db.transaction(self.db_url) as cur:
            stored = self.posts.contents_with_entities(cur, source_id=source_id)
            changed = [(post_id, decoded) for post_id, content in stored
                       if (decoded := decode_entities(content)) != content]
            if dry_run:
                return {"with_codes": len(stored), "to_decode": len(changed)}
            self.posts.save_contents(cur, changed)
        return {"with_codes": len(stored), "decoded": len(changed)}

    async def _site(self, host: str, items: List[Item]) -> None:
        failures = 0
        for index, (post, kind) in enumerate(items):
            if index:
                await self.http.sleep(full_text.PAGE_DELAY_S)
            try:
                found = await self._read(post, kind)
            except KindUnavailable as exc:
                self._stop(host, exc.reason, items[index:])
                return
            except Exception as exc:  # noqa: BLE001 - one post must not stop the others
                logger.warning("Could not read %s: %s", post["url"], str(exc)[:200])
                self.counts["failed"] += 1
                failures += 1
                if failures >= STOP_AFTER_FAILURES:
                    self._stop(host, f"{failures} failures in a row, last: {str(exc)[:200]}", items[index + 1:])
                    return
                continue
            failures = 0
            await asyncio.to_thread(self._write, post["id"], found)
            self.counts["repaired" if found else "nothing_longer"] += 1

    def _stop(self, host: str, reason: str, left: List[Item]) -> None:
        logger.warning("Stopped reading %s: %s", host, reason)
        self.stopped[host] = reason
        self.counts["left"] += len(left)

    async def _read(self, post: Dict[str, Any], kind: Any) -> Optional[Dict[str, Any]]:
        """The full body ({content, content_html, metadata}), or None when nothing is longer."""
        current = full_text.body_text(post)
        if isinstance(kind, SubstackKind):
            fresh = await kind.read_post(post["source"], post["url"])
            if not fresh or fresh["metadata"].get("paywalled") or len(full_text.body_text(fresh)) <= len(current):
                return None
            return {"content": fresh["content"], "content_html": fresh["content_html"], "metadata": fresh["metadata"]}
        article = await full_text.read_article(self.http, post["url"], current)
        if article is None:
            return None
        html, text = article
        return {"content": text, "content_html": html, "metadata": {FULL_TEXT_FLAG: True}}

    def _write(self, post_id: str, found: Optional[Dict[str, Any]]) -> None:
        checked = {FULL_TEXT_CHECKED: self.clock().isoformat()}
        with db.transaction(self.db_url) as cur:
            if found:
                self.posts.save_full_text(cur, post_id, {**found, "metadata": {**found["metadata"], **checked}})
            else:
                self.posts.mark_full_text_checked(cur, post_id, checked[FULL_TEXT_CHECKED])


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-read stored teaser posts in full, once.")
    parser.add_argument("--dry-run", action="store_true", help="read nothing; print what a run would read")
    parser.add_argument("--source", metavar="ID", help="only this source's posts")
    parser.add_argument("--limit", type=int, metavar="N", help="at most N posts, newest first")
    parser.add_argument("--retry", action="store_true", help="include posts an earlier run already read")
    parser.add_argument("--entities", action="store_true",
                        help="read no page; decode the HTML codes (&#39;) in stored posts' text")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    import os

    from insight_core.db.ensure_db import ensure_database
    from insight_core.logs.core.logger_config import setup_logging
    from insight_core.services.youtube_service import YouTubeService

    args = parse_args(argv)
    setup_logging(debug_mode=False)
    db_url = os.getenv("DATABASE_URL") or ensure_database()
    http = KindHttp()
    registry = KindRegistry.default(http, YouTubeService(db_url), db_url=db_url)
    summary = asyncio.run(Repair(db_url, http=http, registry=registry).run(
        dry_run=args.dry_run, source_id=args.source, limit=args.limit, retry=args.retry, entities=args.entities))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
