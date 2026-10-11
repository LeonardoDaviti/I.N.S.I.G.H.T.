"""
Business logic layer for posts operations.
Coordinates between API and database repository.
"""
from typing import List, Dict, Any, Optional
from datetime import date

from insight_core.db import database as db

from insight_core.db.repo_posts import PostsRepository
from insight_core.logs.core.logger_config import get_component_logger


class PostsService:
    """
    Service layer for posts business logic.
    Handles post retrieval with caching strategy.
    """

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = PostsRepository(db_url)
        self.logger = get_component_logger("posts_service")

    def get_posts_by_date(self, date: date, main_digest_only: bool = False) -> List[Dict[str, Any]]:
        """Get posts for a specific date."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_posts_by_date(cur, date, main_digest_only=main_digest_only)
    
    def get_posts_by_source(
        self,
        source_id: str,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get posts for a specific source, sorted by date descending."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_posts_by_source(cur, source_id, limit=limit, offset=offset)

    def get_folder_feed(
        self, folder_id_source_ids: List[str], limit: int = 50, offset: int = 0,
        since_days: int | None = None,
    ) -> Dict[str, Any]:
        """Newest-first reading feed for a set of sources, with a real total."""
        if not folder_id_source_ids:
            return {"posts": [], "total": 0, "returned": 0, "has_more": False}
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                posts = self.repo.get_posts_for_source_ids(
                    cur, folder_id_source_ids, limit=limit, offset=offset, since_days=since_days
                )
                total = self.repo.count_posts_for_source_ids(cur, folder_id_source_ids, since_days=since_days)
        return {
            "posts": posts,
            "total": total,
            "returned": len(posts),
            "has_more": offset + len(posts) < total,
        }

    def get_source_post_stats(self, source_id: str) -> Dict[str, Any]:
        """Get aggregate storage stats for a source."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_source_post_stats(cur, source_id)

    def update_post_metadata(self, post_id: str, metadata: Dict[str, Any]) -> bool:
        """Update the stored metadata for a post."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                updated = self.repo.update_post_metadata(cur, post_id, metadata)
                conn.commit()
                return updated
