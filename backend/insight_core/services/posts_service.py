"""
Business logic layer for posts operations.
Coordinates between API and database repository.
"""
from typing import Dict, Any

from insight_core.db import database as db

from insight_core.db.repo_posts import PostsRepository
from insight_core.logs.core.logger_config import get_component_logger


class PostsService:
    """
    Post storage stats and metadata. Listing posts is the reader's job (reader_service).
    """

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = PostsRepository(db_url)
        self.logger = get_component_logger("posts_service")

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
