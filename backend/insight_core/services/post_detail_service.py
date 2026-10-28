"""
One post for the reader: detail, reader state (opens, reading time, favourite) (stored Reddit comments come with its metadata).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

import psycopg

from insight_core.db import database as db

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.db.repo_interactions import PostInteractionsRepository
from insight_core.db.repo_reader import ReaderRepository
from insight_core.utils.media import post_media
from insight_core.utils.post_fields import display_title


class PostDetailService:
    """Serve the detail view of a single post."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("post_detail_service")
        self.interactions = PostInteractionsRepository()
        self.reader_repo = ReaderRepository()

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
                      s.settings
                    FROM posts p
                    JOIN sources s ON s.id = p.source_id
                    WHERE p.id = %s
                    """,
                    (post_id,),
                )
                row = cur.fetchone()

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
            "content_html": row[8],
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
        }

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
