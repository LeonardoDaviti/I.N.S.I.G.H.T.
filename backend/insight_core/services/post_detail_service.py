"""
One post for the reader: detail, reader state (opens, reading time, favourite) (stored Reddit comments come with its metadata).
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urljoin

import psycopg

from insight_core.db import database as db

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.db.repo_interactions import PostInteractionsRepository
from insight_core.db.repo_reader import ReaderRepository, repost_of
from insight_core.services.news_service import NewsService
from insight_core.utils.media import post_media
from insight_core.utils.post_links import body_hrefs, quoted_tweet
from insight_core.utils.url_normalization import normalize_url
from insight_core.utils.post_fields import display_title


# A tweet's quote card as Nitter writes it (post_links.QUOTED): a rule, then a <blockquote> citing
# the quoted tweet; and the quoted tweet's bare address in the text above it.
QUOTE_CARD = re.compile(r"\s*(?:<hr\s*/?>\s*)?<blockquote>(?:(?!</blockquote>).)*?<cite>.*?</blockquote>", re.I | re.S)
_EMPTY_P = re.compile(r"<p>\s*</p>\s*", re.I)


def without_quote(content_html: Optional[str]) -> str:
    """A reply's HTML without its quote card and the quoted tweet's bare address (issue 0070)."""
    quoted = quoted_tweet(content_html) or ""
    status = re.escape(quoted.rsplit("/", 1)[-1])
    html_ = QUOTE_CARD.sub("", content_html or "", count=1)
    html_ = re.sub(rf'<a\b[^>]*href="[^"]*/status/{status}\b[^"]*"[^>]*>[^<\s]*</a>', "", html_)
    return _EMPTY_P.sub("", html_).strip()


class PostDetailService:
    """Serve the detail view of a single post."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("post_detail_service")
        self.interactions = PostInteractionsRepository()
        self.reader_repo = ReaderRepository()
        self.news = NewsService(db_url)

    def get_post_by_id(self, post_id: str) -> Optional[Dict[str, Any]]:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      p.id,
                      p.source_id,
                      p.url,
                      p.external_id,
                      p.published_at,
                      p.fetched_at,
                      p.title,
                      p.content,
                      p.content_html,
                      p.media_urls,
                      p.categories,
                      p.metadata,
                      p.lang,
                      p.language_code,
                      p.language_confidence,
                      p.normalized_url,
                      p.canonical_url,
                      p.url_host,
                      p.content_hash,
                      p.created_at,
                      p.updated_at,
                      s.platform,
                      s.handle_or_url,
                      s.settings,
                      p.author,
                      p.reposted_by,
                      -- A Telegram album's pictures (issue 0069): shown in its post's body.
                      (SELECT string_agg(a.content_html, '' ORDER BY a.published_at, length(a.url), a.url)
                         FROM posts a WHERE a.album_of = p.id)
                    FROM posts p
                    JOIN sources s ON s.id = p.source_id
                    WHERE p.id = %s
                    """,
                    (post_id,),
                )
                row = cur.fetchone()
                # The classics this post builds on (issue 0051): at most 2, none without one.
                background = self.news.background(cur, post_id) if row else []
                story = self.story(cur, post_id) if row else None
                internal = self.internal_links(cur, post_id, row[2], row[8], row[7]) if row else {}

        if not row:
            return None

        source_settings = row[23] or {}
        media = post_media(row[9], row[2])
        return {
            "id": str(row[0]),
            "source_id": str(row[1]),
            "url": row[2],
            "external_id": row[3],
            "published_at": row[4].isoformat() if row[4] else None,
            "fetched_at": row[5].isoformat() if row[5] else None,
            "title": display_title(row[6], row[7]),
            "content": row[7],
            "content_html": row[8] + row[26] if row[8] and row[26] else row[8],
            "media_urls": row[9] or [],
            "images": media["images"],
            "video": media["video"],
            "categories": row[10] or [],
            "metadata": row[11] or {},
            "lang": row[12],
            "language_code": row[13],
            "language_confidence": float(row[14]) if row[14] is not None else None,
            "normalized_url": row[15],
            "canonical_url": row[16],
            "url_host": row[17],
            "content_hash": row[18],
            "created_at": row[19].isoformat() if row[19] else None,
            "updated_at": row[20].isoformat() if row[20] else None,
            "platform": row[21],
            "source": row[22],
            "source_display_name": source_settings.get("display_name") or row[22],
            "background": background,
            "story": story,
            # A repost (issue 0066): "↻ @by, from @author", as the feed row says it.
            "repost": repost_of(row[21], row[22], row[24], row[25]),
            "internal_links": internal,
        }

    @staticmethod
    def story(cur: psycopg.Cursor, post_id: str) -> Optional[Dict[str, Any]]:
        """The post's story as the feed's lead carries it (issue 0055: the same `story`, from the
        same query), when it has 2+ voices or is a thread (issue 0066); else None (no story, or
        copies of one voice)."""
        item: Dict[str, Any] = {"id": str(post_id)}
        ReaderRepository.attach_stories(cur, [item])
        story = item.get("story")
        if not story or not (story["voices"] >= 2 or story["thread"]):
            return None
        # A thread's replies read as the post does (issue 0068): each its stored HTML and the
        # links in it to stored posts, rendered by the post page's reader. A reply's quote of a tweet
        # of its own story is no card (issue 0070): it was read above, `quotes_above` says so.
        replies = {p["id"]: p for p in story["posts"] if p["parent_reason"] == "thread"}
        if replies:
            cur.execute("SELECT id, url, content_html, content, normalized_url FROM posts WHERE id = ANY(%s::uuid[])",
                        ([post_id, *(p["id"] for p in story["posts"])],))
            rows = cur.fetchall()
            in_story = {row[4] for row in rows}
            for reply_id, url, content_html, content, _ in rows:
                reply = replies.get(str(reply_id))
                if reply is None:
                    continue
                quoted = quoted_tweet(content_html)
                reply["quotes_above"] = quoted is not None and quoted in in_story
                reply["html"] = without_quote(content_html) if reply["quotes_above"] else content_html
                reply["internal_links"] = PostDetailService.internal_links(cur, str(reply_id), url, content_html, content)
        return story

    @staticmethod
    def internal_links(cur: psycopg.Cursor, post_id: str, post_url: Optional[str],
                       content_html: Optional[str], content: Optional[str]) -> Dict[str, str]:
        """{href as the post's text has it: the id of the stored post at that address} (issue
        0057). Any link counts, the post's own platform included; looked up by address: the post
        with that exact url, else the first seen (0049) at its normalized address. Not the post
        itself."""
        hrefs: List[str] = []
        urls: List[str] = []
        normalized: List[str] = []
        for href in body_hrefs(content_html, content):
            try:   # a malformed address (a "port" that is a sentence) is skipped, never fatal
                absolute = urljoin(post_url or "", href)
                address = normalize_url(absolute) if absolute.lower().startswith(("http://", "https://")) else None
            except ValueError:
                continue
            if address:
                hrefs.append(href)
                urls.append(absolute)
                normalized.append(address)
        if not hrefs:
            return {}
        cur.execute(
            """
            SELECT k.href, t.id
            FROM unnest(%s::text[], %s::text[], %s::text[]) AS k(href, url, address)
            JOIN LATERAL (SELECT tp.id FROM posts tp
                          WHERE (tp.url = k.url OR tp.normalized_url = k.address) AND tp.id <> %s::uuid
                          ORDER BY tp.url = k.url DESC, tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            """,
            (hrefs, urls, normalized, str(post_id)),
        )
        return {href: str(target) for href, target in cur.fetchall()}

    def get_post_reader_state(self, post_id: str) -> Dict[str, Any]:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.interactions.get_post_reader_state(cur, post_id)

    def record_post_open(self, post_id: str, *, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Log the open and mark the post read (the first read time is kept), in one transaction."""
        with self._post_write(post_id) as cur:
            stored = self.interactions.record_post_interaction(cur, post_id, "opened", metadata or {})
            self.reader_repo.set_read(cur, [post_id], True)
        return stored

    @contextmanager
    def _post_write(self, post_id: str) -> Iterator[psycopg.Cursor]:
        """One transaction that writes about a post; LookupError (404) when there is no such post."""
        try:
            with db.transaction(self.db_url) as cur:
                yield cur
        except psycopg.errors.ForeignKeyViolation:
            raise LookupError(f"Post {post_id} not found") from None

    def record_reading_session(
        self,
        post_id: str,
        *,
        duration_seconds: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            **(metadata or {}),
            "duration_seconds": max(0, int(duration_seconds)),
        }
        with self._post_write(post_id) as cur:
            stored = self.interactions.record_post_interaction(cur, post_id, "reading_session", payload)
        return stored

    def save_position(self, post_id: str, block: Optional[int], blocks: Optional[int]) -> None:
        """Where a long post was left (issue 0030); block None clears it (the post was finished)."""
        with self._post_write(post_id) as cur:
            self.reader_repo.set_position(cur, post_id, block, blocks)

    def toggle_favorite(self, post_id: str, favorited: bool) -> Dict[str, Any]:
        interaction_type = "favorited" if favorited else "unfavorited"
        with self._post_write(post_id) as cur:
            stored = self.interactions.record_post_interaction(
                cur, post_id, interaction_type, {"favorited": favorited}
            )
            self.reader_repo.set_starred(cur, post_id, favorited)
        state = self.get_post_reader_state(post_id)
        return {
            "post_id": post_id,
            "favorited": state.get("is_favorited", False),
            "interaction": stored,
            "reader_state": state,
        }
