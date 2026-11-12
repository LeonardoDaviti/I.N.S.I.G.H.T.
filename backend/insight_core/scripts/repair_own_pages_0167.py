"""Give each followed site's pages back to it (issue 0167), once: the pages another source stored first.

    python -m insight_core.scripts.repair_own_pages_0167                 # dry run: reports, changes nothing
    python -m insight_core.scripts.repair_own_pages_0167 --apply         # moves what the report lists
    python -m insight_core.scripts.repair_own_pages_0167 --no-fetch      # no request: the stored evidence only
    python -m insight_core.scripts.repair_own_pages_0167 --source <id>   # one owner source

A page held by a source that doesn't own it (Hacker News, a link blog, a trending list: utils/own_pages.owns) whose
site an enabled website source follows is a candidate. It moves to that source when the source lists it:
  - **listed** (the default, one source at a time, PAGE_GAP_S between two requests): the source's own listing is
    asked: a page watch's listing page and its section's sitemap (page_watch.discover), a feed's items and its
    site's post sitemap. A page it lists is its page; one it doesn't is left (reported "not listed").
  - **--no-fetch**: no request. The page is the source's when the stored row says the source's own fetch wrote it
    (metadata.adapter, the page watch's), or 0084 B's rule (repo_linked's OwnPages, learned from the stored posts)
    names it. Else it is left (reported "unsure").
Of two followed sources of one site (a blog's feed, a page watch of a section), the one listing the page takes it.

A move is PostsRepository.hand_over, as a live fetch does it: one row, its id kept (its stories, readings, labels,
News rows, notes and reader state stay), and the holder keeps a post citing the page. Nothing is deleted.

Resumable: each owner source is a transaction of its own; a page moved is no candidate any more, so a second run
finds only what is left. --state FILE records the owners done (a stopped run resumes after them).
Prints the report as JSON.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db import database as db  # noqa: E402
from insight_core.db.repo_posts import PostsRepository  # noqa: E402
from insight_core.utils import own_pages  # noqa: E402
from insight_core.utils.url_normalization import normalize_url  # noqa: E402

logger = logging.getLogger("insight.repair_own_pages_0167")

PAGE_GAP_S = 2.0          # between two requests of the listing reads (one source at a time)


@dataclass
class Owner:
    id: str
    platform: str
    handle: str
    name: str
    settings: Dict[str, Any]

    @property
    def site(self) -> str:
        return own_pages.page_site(self.handle)

    @property
    def page_watch(self) -> Optional[Dict[str, Any]]:
        found = self.settings.get("page_watch")
        return found if isinstance(found, dict) else None


@dataclass
class Held:
    post_id: str
    url: str
    normalized: str
    title: Optional[str]
    holder: str
    holder_name: str
    adapter: Optional[str]


@dataclass
class Report:
    owners: List[Dict[str, Any]] = field(default_factory=list)
    moved: int = 0
    would_move: int = 0
    left: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {"would_move": self.would_move, "moved": self.moved, "left": self.left, "owners": self.owners}


def followed_owners(cur: Any, source_id: Optional[str] = None) -> List[Owner]:
    """The enabled website sources (own_pages.OWNER_KIND), every one or one."""
    cur.execute("""SELECT id::text, platform, handle_or_url, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url),
                          COALESCE(settings, '{}'::jsonb)
                     FROM sources WHERE enabled AND (%s::uuid IS NULL OR id = %s::uuid) ORDER BY id""",
                (source_id, source_id))
    out = [Owner(*row) for row in cur.fetchall()]
    return [o for o in out if own_pages.owns(o.platform, o.handle, o.handle)]


def held_pages(cur: Any, sites: Iterable[str]) -> Dict[str, List[Held]]:
    """{site: the posts on it held by a source that doesn't own them}, a platform's post addresses and citations
    aside."""
    sites = set(sites)
    cur.execute("SELECT DISTINCT url_host FROM posts WHERE url_host IS NOT NULL")
    hosts = [h for (h,) in cur.fetchall() if own_pages.page_site(f"https://{h}/") in sites]
    if not hosts:
        return {}
    cur.execute("""SELECT p.id::text, p.url, COALESCE(p.normalized_url, p.url), p.title, s.id::text, s.platform,
                          s.handle_or_url, COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url),
                          p.metadata->>'adapter'
                     FROM posts p JOIN sources s ON s.id = p.source_id
                    WHERE p.url_host = ANY(%s) AND p.album_of IS NULL AND NOT p.metadata ? 'cites'
                      AND NOT platform_post_address(COALESCE(p.normalized_url, p.url))
                    ORDER BY p.id""", (hosts,))
    out: Dict[str, List[Held]] = defaultdict(list)
    for post_id, url, normalized, title, holder, platform, handle, name, adapter in cur.fetchall():
        if (platform or "").lower() == "saved" or own_pages.owns(platform, handle, url):
            continue
        out[own_pages.page_site(url)].append(Held(post_id, url, normalized, title, holder, name, adapter))
    return dict(out)


async def listed_addresses(http: Any, owner: Owner) -> Set[str]:
    """The normalized addresses the owner's own listing names now: a page watch's listing page and sitemap, a feed's
    items and its site's post sitemap. Raises what the requests raise."""
    from insight_core.ingestion.kinds import page_watch, parsing

    found: Set[str] = set()
    watch = owner.page_watch
    if watch is not None:
        discovery = await page_watch.discover(http, owner.handle, watch.get("prefix"))
        found |= set(discovery.listed) | set(discovery.sitemap)
    else:
        text, _ = await http.get_text(owner.handle)
        found |= {post["url"] for post in parsing.parse_feed_posts(text, owner.handle) if post.get("url")}
        await http.sleep(PAGE_GAP_S)
        try:
            found |= {loc for loc, _ in await page_watch.sitemap_entries(http, owner.handle, "", posts_only=True)}
        except Exception as exc:  # noqa: BLE001 - no sitemap: the feed's items only
            logger.info("0167: no sitemap read for %s (%s)", owner.name, exc)
    return {n for n in (normalize_url(u) for u in found) if n}


def stored_evidence(cur: Any, owners: Sequence[Owner], pages: Sequence[Held]) -> Dict[str, str]:
    """{post id: owner id} by what is stored (--no-fetch): the owner's page watch wrote the row (metadata.adapter),
    else 0084 B's rule names one of these owners."""
    from insight_core.db.repo_linked import _followed, _own_pages

    by_id = {o.id: o for o in owners}
    watchers = [o for o in owners if o.page_watch is not None]
    own, _, _ = _own_pages(cur, _followed(cur))
    out: Dict[str, str] = {}
    for page in pages:
        if page.adapter == "page_watch" and len(watchers) == 1:
            out[page.post_id] = watchers[0].id
            continue
        named = own.owner(page.url)
        if named in by_id:
            out[page.post_id] = named
    return out


def _done(state: Optional[Path]) -> Set[str]:
    if state is None or not state.exists():
        return set()
    return set(json.loads(state.read_text() or "[]"))


def _mark(state: Optional[Path], done: Set[str]) -> None:
    if state is not None:
        state.write_text(json.dumps(sorted(done)))


async def run(db_url: str, *, apply: bool = False, fetch: bool = True, source_id: Optional[str] = None,
              http: Any = None, state: Optional[Path] = None) -> Dict[str, Any]:
    report = Report()
    repo = PostsRepository(db_url)
    done = _done(state)
    with db.connection(db_url) as conn, conn.cursor() as cur:
        owners = followed_owners(cur, source_id)
        by_site: Dict[str, List[Owner]] = defaultdict(list)
        for owner in owners:
            by_site[owner.site].append(owner)
        held = held_pages(cur, by_site)
        conn.commit()
    if fetch and http is None:
        from insight_core.ingestion.http import KindHttp
        http = KindHttp()
    for site, pages in sorted(held.items()):
        site_owners = [o for o in by_site.get(site, []) if o.id not in done]
        if not site_owners:
            continue
        chosen: Dict[str, str] = {}
        unread: Dict[str, str] = {}
        if fetch:
            for owner in site_owners:
                try:
                    listed = await listed_addresses(http, owner)
                except Exception as exc:  # noqa: BLE001 - this owner's listing unread: its pages are left
                    unread[owner.id] = str(exc)[:160]
                    continue
                finally:
                    await http.sleep(PAGE_GAP_S)
                for page in pages:
                    if page.post_id not in chosen and normalize_url(page.url) in listed:
                        chosen[page.post_id] = owner.id
        else:
            with db.connection(db_url) as conn, conn.cursor() as cur:
                chosen = stored_evidence(cur, site_owners, pages)
        for owner in site_owners:
            mine = [p for p in pages if chosen.get(p.post_id) == owner.id]
            row: Dict[str, Any] = {"source_id": owner.id, "source": owner.name, "site": site,
                                   "pages": [{"post_id": p.post_id, "url": p.url, "title": p.title, "from": p.holder_name}
                                             for p in mine]}
            if owner.id in unread:
                row["listing_unread"] = unread[owner.id]
            report.would_move += len(mine)
            if apply and mine:
                with db.connection(db_url) as conn, conn.cursor() as cur:
                    moved = sum(1 for p in mine if repo.hand_over(cur, p.post_id, owner.id))
                    conn.commit()
                report.moved += moved
                row["moved"] = moved
            report.owners.append(row)
            done.add(owner.id)
            _mark(state, done)
        left = [p for p in pages if p.post_id not in chosen]
        report.left += len(left)
        if left:
            report.owners.append({"site": site, ("not listed" if fetch else "unsure"):
                                  [{"post_id": p.post_id, "url": p.url, "from": p.holder_name} for p in left]})
    return report.as_dict()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--apply", action="store_true", help="move the pages (default: a dry run)")
    ap.add_argument("--no-fetch", action="store_true", help="no request: the stored evidence only")
    ap.add_argument("--source", help="one owner source id")
    ap.add_argument("--state", type=Path, help="a file recording the owners done (resumes after them)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    db_url = args.db
    if not db_url:
        from insight_core.db.ensure_db import ensure_database
        db_url = ensure_database()
    out = asyncio.run(run(db_url, apply=args.apply, fetch=not args.no_fetch, source_id=args.source, state=args.state))
    print(json.dumps({"dry_run": not args.apply, **out}, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
