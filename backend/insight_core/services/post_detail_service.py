"""
One post for the reader: detail, reader state (opens, reading time, favourite) (stored Reddit comments come with its metadata).
"""
from __future__ import annotations

import html as html_lib
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urljoin

import psycopg

from insight_core.db import database as db
from insight_core.ingestion import full_text

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.db.repo_interactions import PostInteractionsRepository
from insight_core.db.repo_post_refs import PostRefsRepository
from insight_core.db.repo_reader import ReaderRepository, repost_of, voice_sources
from insight_core.services.news_service import NewsService
from insight_core.db.repo_post_parts import body, shown_title
from insight_core.utils.media import post_media
from insight_core.utils.post_links import body_hrefs
from insight_core.utils.url_normalization import normalize_url
from insight_core.utils.post_fields import link_kind, quote_byline_linked


def _with_quoted(content_html: Optional[str], quoted: Optional[str]) -> Optional[str]:
    """The HTML whose links internal_links looks up, with the quoted tweet's x.com address the byline links (0126)."""
    return f'{content_html or ""}<a href="{html_lib.escape(quoted, quote=True)}"></a>' if quoted else content_html


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
                         FROM posts a WHERE a.album_of = p.id),
                      -- Its parts (issue 0076: read once, when it was saved).
                      pp.title, pp.text_cut, pp.text_decode_entities, pp.text_cut_leaves_break, pp.text_copy, pp.html_cut, pp.html_decode_entities, pp.html_cut_leaves_break, pp.html_copy, pp.quoted, pp.quote_only, pp.folded, pp.counts, pp.link_target
                    FROM posts p
                    JOIN sources s ON s.id = p.source_id
                    LEFT JOIN post_parts pp ON pp.post_id = p.id
                    WHERE p.id = %s
                    """,
                    (post_id,),
                )
                row = cur.fetchone()
                # The classics this post builds on (issue 0051): at most 2, none without one.
                background = self.news.background(cur, post_id) if row else []
                story = self.story(cur, post_id, str(row[1])) if row else None
                internal = self.internal_links(cur, post_id, row[2], _with_quoted(row[8], row[36]), row[7]) if row else {}
                link = self.link(cur, row[40], story, row[2]) if row else None
                news = self.news.row_of(cur, post_id, str(row[1])) if row else None

        if not row:
            return None

        source_settings = row[23] or {}
        media = post_media(row[9], row[2])
        # The text starts after a title taken from it, without a feed's own lines (hnrss's counts:
        # the byline says them), issue 0070. A thread's post with words of its own that quotes a post of its
        # thread is no card: the thread lists it (issue 0072 D4); its title is the one every place shows (D1).
        quoted = row[36] if story and story["thread"] and not row[37] else None
        if row[27] is None:   # not parsed yet: as it was stored
            title, content, html = row[6], row[7], row[8]
        elif quoted and quoted in {normalize_url(p["url"]) for p in story["posts"]}:
            title, content, html = row[27], row[38]["text"], row[38]["body"]   # its quote card folded
        else:
            title, content, html = row[27], body(row[7], row[28:32]), body(row[8], row[32:36])
        # The quote card's byline opens the quoted tweet on x.com (issue 0126), inside INSIGHT when it is stored.
        html = quote_byline_linked(html, row[36])
        counts ={"points": row[39]["points"], "comments": row[39]["comments"]} if row[39] else None
        return {
            "id": str(row[0]),
            "source_id": str(row[1]),
            "url": row[2],
            "external_id": row[3],
            "published_at": row[4].isoformat() if row[4] else None,
            "fetched_at": row[5].isoformat() if row[5] else None,
            "title": title,
            "counts": counts,
            "content": content,
            "content_html": html + row[26] if html and row[26] else html,
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
            # A link post's page (issue 0072): {url, title, post_id}, read when the post has no words of its own.
            "link": link,
            # Its News row (issue 0083): {id, title, voices, lead_id, scope}, the page says "In News".
            "news": news,
            # Why it shows its feed's summary only (issue 0140), or None: "Summary only · <reason> · Open the page".
            "teaser_reason": full_text.teaser_reason(row[11], url=row[2], title=row[6], content_html=row[8]),
        }

    @staticmethod
    def story(cur: psycopg.Cursor, post_id: str, source_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The post's story as the feed's lead carries it (issue 0055: the same `story`, from the
        same query), when it has 2+ voices, is a thread (issue 0066) or another source shared it (issue
        0072 D4: "also shared by", as the feed row says); else None (no story, or copies of one voice
        by its own source)."""
        item: Dict[str, Any] = {"id": str(post_id)}
        ReaderRepository.attach_stories(cur, [item])
        story = item.get("story")
        others = story and source_id and any(source["id"] != source_id for source in voice_sources(story["sources"]))
        if not story or not (story["voices"] >= 2 or story["thread"] or others):
            return None
        # A thread's replies read as the post does (issue 0068): each its stored HTML and the
        # links in it to stored posts, rendered by the post page's reader. A reply's quote of a tweet
        # of its own story is no card (issue 0070): it was read above, `quotes_above` says so.
        replies = {p["id"]: p for p in story["posts"] if p["parent_reason"] == "thread"}
        if replies:
            cur.execute("SELECT p.id, p.url, p.content_html, p.content, p.normalized_url, pp.quoted, pp.folded FROM posts p "
                        "LEFT JOIN post_parts pp ON pp.post_id = p.id WHERE p.id = ANY(%s::uuid[])",
                        ([post_id, *(p["id"] for p in story["posts"])],))
            rows = cur.fetchall()
            in_story = {row[4] for row in rows}
            for reply_id, url, content_html, content, _, quoted, folded in rows:
                reply = replies.get(str(reply_id))
                if reply is None:
                    continue
                reply["quotes_above"] = quoted is not None and quoted in in_story
                reply["html"] = folded["html"] if reply["quotes_above"] else quote_byline_linked(content_html, quoted)
                reply["internal_links"] = PostDetailService.internal_links(cur, str(reply_id), url,
                                                                           _with_quoted(content_html, quoted), content)
        return story

    @staticmethod
    def link(cur: psycopg.Cursor, url: Optional[str], story: Optional[Dict[str, Any]],
             post_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The page a link post shares (issue 0072): {url, title, post_id, kind}, titled by the stored post at
        its address (opened here), else by its story's outside origin when it is that page. `kind`
        (issue 0072 D4): a picture opens the picture; a video on Reddit's video host plays on the post's
        own page (`post_url`)."""
        if not url:
            return None
        kind = link_kind(url)
        if kind == "video" and post_url:
            return {"url": post_url, "title": None, "post_id": None, "kind": kind}
        address = normalize_url(url)
        cur.execute(f"SELECT p.id, {shown_title()} FROM posts p WHERE p.normalized_url = %s ORDER BY p.fetched_at, p.id LIMIT 1",
                    (address,))
        stored = cur.fetchone()
        origin = (story or {}).get("origin") or {}
        title = stored[1] if stored else origin.get("title") if origin.get("url") == address else None
        return {"url": url, "title": title or None, "post_id": str(stored[0]) if stored else None, "kind": kind}

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

    def connected(self, post_id: str, *, full: bool = False) -> Optional[Dict[str, Any]]:
        """The post's Connected block (issue 0125): {earlier, later, outside, more}, None for no such post. Read
        apart from the post (the page asks for it after the post), so the post never waits on it."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return PostRefsRepository.connected(cur, post_id, full=full)

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
