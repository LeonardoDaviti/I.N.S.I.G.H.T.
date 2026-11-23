"""Re-read stored teaser posts in full, once (the full-text repair).

    python -m insight_core.scripts.repair_full_text [--dry-run] [--source ID] [--limit N] [--retry]
    python -m insight_core.scripts.repair_full_text --rule [--dry-run] [--source ID] [--limit N]
    python -m insight_core.scripts.repair_full_text --entities [--dry-run] [--source ID]

Which posts: a body shorter than full_text.SHORT_BODY_CHARS, or a paid teaser (metadata.paywalled), never read
from its page, newest first. How each is read again:
  - a substack source: its post from Substack's API (paid ones only with the Substack session in Connections);
  - a generic RSS source: the article page, as new posts are read (ingestion/full_text.py), unless the source
    has `fetch_full_content: false` or the link is not an article;
  - a nitter_rss tweet that is an X Article given as a link: its article (kinds/x_articles.py);
  - every other kind is skipped: its post is whole.

--rule: instead, the generic RSS teasers (short, or cut by a "read more" link) whose last read ended
nothing_longer, not_same_article or needs_script, or recorded none, read again once per full_text.FULL_TEXT_RULE
version. Each read records its outcome and the version, so a stopped run resumes and a second run finds nothing.
The ingestion process runs it at each start (repair_safely).

Polite: one site's posts one at a time, full_text.PAGE_DELAY_S apart, up to SITE_CONCURRENCY sites at once; a
site failing STOP_AFTER_FAILURES times in a row is left for the next run. Every read is marked
metadata.full_text_checked_at (--retry includes those) and counted in metadata.page_tries; a failed request is
not marked checked. --dry-run prints what a run would read. The summary is printed as JSON.

--entities reads no page: it decodes HTML codes ("That&#39;s") left in stored plain text (every post, or
--source's); with --dry-run it only counts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db import database as db  # noqa: E402
from insight_core.db.repo_posts import FULL_TEXT_CHECKED, PAGE_TRIES_KEY, PostsRepository  # noqa: E402
from insight_core.ingestion import full_text  # noqa: E402
from insight_core.ingestion.http import HttpError, KindHttp  # noqa: E402
from insight_core.ingestion.kinds import KindRegistry  # noqa: E402
from insight_core.ingestion.kinds import x_articles  # noqa: E402
from insight_core.ingestion.kinds.base import KindUnavailable  # noqa: E402
from insight_core.ingestion.kinds.substack import SUBSTACK_HOST_KEY, SubstackKind  # noqa: E402
from insight_core.utils.addresses import host_of  # noqa: E402
from insight_core.utils.content_fingerprints import decode_entities  # noqa: E402

logger = logging.getLogger("insight.scripts.repair_full_text")

SITE_CONCURRENCY = 4
STOP_AFTER_FAILURES = 3

Item = Tuple[Dict[str, Any], Any]  # (candidate post, its source kind)


def plan(posts: Sequence[Dict[str, Any]], registry: KindRegistry, *, rule: bool = False
         ) -> Tuple[Dict[str, List[Item]], Counter]:
    """The posts to read, grouped by site, and why the others are skipped. With `rule`: generic RSS teasers only
    (full_text.is_teaser)."""
    sites: Dict[str, List[Item]] = defaultdict(list)
    skipped: Counter = Counter()
    for post in posts:
        source = post["source"]
        kind = registry.resolve(source)
        if kind.name == "nitter_rss" and x_articles.is_article_post(post) and x_articles.lookups_on(getattr(kind, "env", os.environ)):
            sites[x_articles.HOST_KEY].append((post, kind))   # an X Article the bridge gave as a link
        elif rule and kind.name == "generic_rss" and not isinstance(kind, SubstackKind) and not full_text.is_teaser(post):
            skipped["no teaser"] += 1
        elif rule and (isinstance(kind, SubstackKind) or kind.name != "generic_rss"):
            skipped[f"kind {kind.name}"] += 1
        elif isinstance(kind, SubstackKind):
            sites[SUBSTACK_HOST_KEY].append((post, kind))
        elif kind.name != "generic_rss":
            skipped[f"kind {kind.name}"] += 1
        elif not full_text.full_page_enabled(source):
            skipped["full page turned off for the source"] += 1
        elif not full_text.page_is_article(post["url"]):
            skipped["link is not an article"] += 1
        else:
            sites[host_of(post["url"])].append((post, kind))
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
        self.outcomes: Counter = Counter()
        self.stopped: Dict[str, str] = {}

    async def run(self, *, dry_run: bool = False, source_id: Optional[str] = None,
                  limit: Optional[int] = None, retry: bool = False, entities: bool = False,
                  rule: bool = False) -> Dict[str, Any]:
        if entities:
            return await asyncio.to_thread(self._decode_entities, dry_run, source_id)
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            posts = self.posts.full_text_candidates(
                cur, short_chars=full_text.SHORT_BODY_CHARS, source_id=source_id, retry=retry, limit=limit,
                rule=full_text.FULL_TEXT_RULE if rule else None, outcomes=full_text.READ_AGAIN_OUTCOMES,
                skip_hosts=sorted(full_text.NOT_ARTICLE_HOSTS) if rule else ())
        sites, skipped = plan(posts, self.registry, rule=rule)
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
            # every read's outcome: full, nothing_longer, not_same_article, needs_script, error:/http:
            "outcomes": dict(self.outcomes),
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
                found, outcome = await self._read(post, kind)
            except KindUnavailable as exc:
                self._stop(host, exc.reason, items[index:])
                return
            except Exception as exc:  # noqa: BLE001 - one post must not stop the others
                logger.warning("Could not read %s (%s): %s", post["url"], type(exc).__name__, str(exc)[:200])
                self.outcomes[full_text.error_outcome(exc)] += 1
                # a failed request is counted, so the fetch's retry reads it again
                await asyncio.to_thread(self._write, post, None, full_text.error_outcome(exc),
                                        failed=True, counted=isinstance(exc, HttpError))
                self.counts["failed"] += 1
                failures += 1
                if failures >= STOP_AFTER_FAILURES:
                    self._stop(host, f"{failures} failures in a row, last: {str(exc)[:200]}", items[index + 1:])
                    return
                continue
            failures = 0
            self.outcomes[outcome] += 1
            # nothing longer for a post with no body is a failed try: read again
            await asyncio.to_thread(self._write, post, found, outcome, failed=not found and full_text.empty_read_failed(post))
            self.counts["repaired" if found else "nothing_longer"] += 1
            done = self.counts["repaired"] + self.counts["nothing_longer"] + self.counts["failed"]
            if done % 100 == 0:
                logger.info("Full text: %s posts read again, %s in full", done, self.counts["repaired"])

    def _stop(self, host: str, reason: str, left: List[Item]) -> None:
        logger.warning("Stopped reading %s: %s", host, reason)
        self.stopped[host] = reason
        self.counts["left"] += len(left)

    async def _read(self, post: Dict[str, Any], kind: Any) -> Tuple[Optional[Dict[str, Any]], str]:
        """(the full body ({content, content_html, metadata}) or None, the read's outcome)."""
        current = full_text.body_text(post)
        if kind.name == "nitter_rss":
            fresh = await kind.read_article_post(post)
            if fresh is None:
                raise x_articles.ArticleUnavailable(f"no X Article for {post['url']}")
            found = {key: fresh[key] for key in ("title", "content", "content_html", "metadata")}
            return found, full_text.outcome_of(fresh["metadata"]) or full_text.FULL
        if isinstance(kind, SubstackKind):
            fresh = await kind.read_post(post["source"], post["url"])
            if not fresh or fresh["metadata"].get("paywalled") or len(full_text.body_text(fresh)) <= len(current):
                return None, full_text.NOTHING_LONGER
            return ({"content": fresh["content"], "content_html": fresh["content_html"], "metadata": fresh["metadata"]},
                    full_text.FULL)
        read = await full_text.read_page(self.http, post["url"], current, title=post.get("title"),
                                         site=str(post["source"].get("handle_or_url") or ""))
        if read.article is None:
            return None, read.outcome
        return full_text.with_full_text({}, *read.article), read.outcome   # content, content_html and metadata

    def _write(self, post: Dict[str, Any], found: Optional[Dict[str, Any]], outcome: str, *,
               failed: bool = False, counted: bool = True) -> None:
        """Store a read: its full text, or only that it was checked, with its outcome and the rules' version.
        Counted in page_tries; a failed one is not checked, so it is read again."""
        now = self.clock()
        tried = ({PAGE_TRIES_KEY: full_text.with_page_try(post, now, failed=failed)["metadata"][PAGE_TRIES_KEY]}
                 if counted else {})
        checked = {} if failed else {FULL_TEXT_CHECKED: now.isoformat()}
        why = full_text.with_outcome({}, outcome, now)["metadata"]
        with db.transaction(self.db_url) as cur:
            if found:
                self.posts.save_full_text(cur, post["id"], {**found, "metadata": {**found["metadata"], **checked, **tried, **why}})
            else:
                self.posts.merge_metadata(cur, post["id"], {**checked, **tried, **why})


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-read stored teaser posts in full, once.")
    parser.add_argument("--dry-run", action="store_true", help="read nothing; print what a run would read")
    parser.add_argument("--source", metavar="ID", help="only this source's posts")
    parser.add_argument("--limit", type=int, metavar="N", help="at most N posts, newest first")
    parser.add_argument("--retry", action="store_true", help="include posts an earlier run already read")
    parser.add_argument("--rule", action="store_true",
                        help="the teasers left short, read again once per version of the rules (issue 0140)")
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
        dry_run=args.dry_run, source_id=args.source, limit=args.limit, retry=args.retry, entities=args.entities,
        rule=args.rule))
    print(json.dumps(summary, indent=2))
    return 0


def repair_safely(db_url: str, *, http: Optional[KindHttp] = None, registry: Optional[KindRegistry] = None
                  ) -> Optional[Dict[str, Any]]:
    """The ingestion process's start: `--rule`, logged; resumable, so a later start finds nothing. Never raises.
    Nothing with INSIGHT_DISCOVER_READS=0 (a machine that must not fetch) or INSIGHT_FULL_TEXT_REPAIR=0."""
    import os

    if os.getenv("INSIGHT_DISCOVER_READS", "1") == "0" or os.getenv("INSIGHT_FULL_TEXT_REPAIR", "1") == "0":
        return None
    try:
        if http is None:
            http = KindHttp()
        if registry is None:
            from insight_core.services.youtube_service import YouTubeService

            registry = KindRegistry.default(http, YouTubeService(db_url), db_url=db_url)
        summary = asyncio.run(Repair(db_url, http=http, registry=registry).run(rule=True))
    except Exception:  # noqa: BLE001 - the repair is never worth the start
        logger.exception("Full text: could not read the teasers again")
        return None
    if summary.get("to_read"):
        logger.info("Full text (rules v%s): %s", full_text.FULL_TEXT_RULE, json.dumps(summary))
    return summary


if __name__ == "__main__":
    sys.exit(main())
