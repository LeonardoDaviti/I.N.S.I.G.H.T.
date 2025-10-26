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