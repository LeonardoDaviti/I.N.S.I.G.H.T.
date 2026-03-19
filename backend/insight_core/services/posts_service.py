"""
Business logic layer for posts operations.
Coordinates between API and database repository.
"""
from typing import List, Dict, Any, Optional
from datetime import date

import psycopg
from psycopg import Connection

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

    def get_posts_by_date(self, date: date) -> List[Dict[str, Any]]:
        """Get posts for a specific date."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_posts_by_date(cur, date)
    
    def get_posts_by_source(self, source_id: str) -> List[Dict[str, Any]]:
        """Get all posts for a specific source, sorted by date descending."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_posts_by_source(cur, source_id)

    def get_source_post_stats(self, source_id: str) -> Dict[str, Any]:
        """Get aggregate storage stats for a source."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_source_post_stats(cur, source_id)

    def update_post_categories(self, post_id: str, categories: List[str]) -> bool:
        """Update the stored categories for a post."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                updated = self.repo.update_post_categories(cur, post_id, categories)
                conn.commit()
                return updated

    def update_post_metadata(self, post_id: str, metadata: Dict[str, Any]) -> bool:
        """Update the stored metadata for a post."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                updated = self.repo.update_post_metadata(cur, post_id, metadata)
                conn.commit()
                return updated
