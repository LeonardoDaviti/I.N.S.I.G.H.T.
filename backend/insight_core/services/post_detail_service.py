"""
One post for the reader: detail, reader state (opens, reading time, favourite) and Reddit comments.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import psycopg

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.db.repo_interactions import PostInteractionsRepository
from insight_core.db.repo_reader import ReaderRepository
from insight_core.services.posts_service import PostsService
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.utils.media import post_media


class PostDetailService:
    """Serve the detail view of a single post."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("post_detail_service")
        self.posts_service = PostsService(db_url)
        self.source_fetch_service = SourceFetchService(db_url)
        self.interactions = PostInteractionsRepository()
        self.reader_repo = ReaderRepository()

    def get_post_by_id(self, post_id: str) -> Optional[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
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
            "title": row[6],
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
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.interactions.get_post_reader_state(cur, post_id)

    def record_post_open(self, post_id: str, *, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Log the open and mark the post read (the first read time is kept), in one transaction."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                stored = self.interactions.record_post_interaction(cur, post_id, "opened", metadata or {})
                self.reader_repo.set_read(cur, [post_id], True)
            conn.commit()
        return stored

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
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                stored = self.interactions.record_post_interaction(cur, post_id, "reading_session", payload)
            conn.commit()
        return stored

    def toggle_favorite(self, post_id: str, favorited: bool) -> Dict[str, Any]:
        interaction_type = "favorited" if favorited else "unfavorited"
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                stored = self.interactions.record_post_interaction(
                    cur, post_id, interaction_type, {"favorited": favorited}
                )
                self.reader_repo.set_starred(cur, post_id, favorited)
            conn.commit()
        state = self.get_post_reader_state(post_id)
        return {
            "post_id": post_id,
            "favorited": state.get("is_favorited", False),
            "interaction": stored,
            "reader_state": state,
        }

    async def fetch_reddit_comments(self, post_id: str, *, limit: int = 80, refresh: bool = False) -> Dict[str, Any]:
        post = self.get_post_by_id(post_id)
        if not post:
            raise ValueError(f"Post {post_id} not found")
        if post.get("platform") != "reddit":
            raise ValueError("Reddit comments are only available for reddit posts")

        metadata = dict(post.get("metadata") or {})
        discussion = dict(metadata.get("reddit_discussion") or {})
        cached_comments = discussion.get("comments") if isinstance(discussion.get("comments"), list) else []
        cached_limit = int(discussion.get("limit") or len(cached_comments) or 0)

        if not refresh and cached_comments and cached_limit >= limit:
            return {
                "post_id": post_id,
                "comments": cached_comments[:limit],
                "comment_count": min(len(cached_comments), limit),
                "cached": True,
                "fetched_at": discussion.get("fetched_at"),
            }

        comments = await self.source_fetch_service.fetch_reddit_comments_for_post(post["url"], limit=limit)
        updated_discussion = {
            **discussion,
            "comments": comments,
            "limit": limit,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata["reddit_discussion"] = updated_discussion
        self.posts_service.update_post_metadata(post_id, metadata)

        return {
            "post_id": post_id,
            "comments": comments,
            "comment_count": len(comments),
            "cached": False,
            "fetched_at": updated_discussion["fetched_at"],
        }
