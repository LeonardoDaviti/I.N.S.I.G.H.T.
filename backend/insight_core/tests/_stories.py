"""One factory for the posts and sources tests make (issue 0071).

    story_post(...)                 a StoryPost, what the story, tree and News rules read
    insert_source(cur, ...)         a scratch source in the database, named
    insert_post(cur, source, ...)   a post row, and its read links when `links` is given

A test file binds its own defaults (its clock, its marks) in a line or two around these, so a
change to StoryPost or to the posts table is made here once.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from insight_core.db.repo_post_parts import PostPartsRepository
from insight_core.tests._db import insert_scratch_source
from insight_core.utils.story_rules import StoryPost
from insight_core.utils.url_normalization import normalize_url


def story_post(pid: str, source: str, *, at: datetime, hours: float = 0.0, kind: str = "site",
               site: Optional[str] = None, text_hash: Optional[str] = None, chars: Optional[int] = None,
               links: Iterable = (), texts: Optional[dict] = None, home: Optional[str] = None, **fields) -> StoryPost:
    """A post of `source` at `at` + `hours`, on `site` (default "<source>.test"). `links` are
    (target, stored post id) pairs and `texts` their words; a post with a `text_hash` has 200
    characters unless `chars` says otherwise. Any other StoryPost field passes through."""
    return StoryPost(id=pid, source_id=source, kind=kind, own_site=site or f"{source}.test",
                     t=at + timedelta(hours=hours), content_hash=text_hash,
                     text_chars=chars if chars is not None else (200 if text_hash else 0),
                     links=list(links), link_texts=dict(texts or {}), home_site=home, **fields)


def insert_source(cur, name: Optional[str] = None, *, handle: Optional[str] = None, platform: str = "rss",
                  in_main_digest: bool = False, followed_days: Optional[int] = None) -> str:
    """A scratch source (`_db.insert_scratch_source`: disabled, so no tick fetches it), with
    `name` as its display name, `handle` as its address, and added `followed_days` ago."""
    source = insert_scratch_source(cur, platform=platform, in_main_digest=in_main_digest)
    cur.execute(
        """UPDATE sources SET
               settings = CASE WHEN %(name)s::text IS NULL THEN settings
                               ELSE jsonb_build_object('display_name', %(name)s::text) END,
               handle_or_url = COALESCE(%(handle)s, handle_or_url),
               created_at = COALESCE(now() - make_interval(days => %(days)s), created_at)
           WHERE id = %(id)s""",
        {"name": name, "handle": handle, "days": followed_days, "id": source})
    return source


def insert_post(cur, source: str, url: str, *, at: Optional[datetime] = None, title: Optional[str] = None, content: Optional[str] = None,
                html: Optional[str] = None, content_hash: Optional[str] = None, host: Optional[str] = None,
                normalized: Optional[str] = None, author: Optional[str] = None, links: Optional[Iterable] = None):
    """A post row, published `at` (default the database's now()); its id as the database returns
    it. `normalized` defaults to normalize_url(url), `host` to the address's host. With `links` (targets, or (target, words) pairs, in order) its
    links are stored as read; without, the story job reads them from `html`. Parsed as a save parses it
    (post_parts, issue 0076)."""
    cur.execute(
        """INSERT INTO posts (source_id, url, normalized_url, url_host, title, content, content_html, content_hash,
                              published_at, author, links_scanned_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()), %s, CASE WHEN %s THEN now() END)
           RETURNING id""",
        (source, url, normalized or normalize_url(url), host or url.split("/")[2], title, content, html, content_hash,
         at, author, links is not None))
    post_id = cur.fetchone()[0]
    for position, link in enumerate(links or ()):
        target, text = link if isinstance(link, tuple) else (link, None)
        cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position, link_text) "
                    "VALUES (%s, %s, '', %s, %s)", (post_id, target, position, text))
    PostPartsRepository.write(cur, [str(post_id)])
    return post_id
