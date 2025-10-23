import os, sys, json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from psycopg import Connection, Cursor

from insight_core.logs.core.logger_config import setup_logging, get_component_logger
from insight_core.db.ensure_db import ensure_database


class PostsRepository:
    """
    Database access layer for posts table.
    Handles all SQL operations for storing and retrieving posts.
    """

    def __init__(self, db_url: str):
        self.db_url = db_url

        
        self.logger = get_component_logger("repo_posts")
        self.logger.info(f"PostsRepository initialized")

    # ===============================
    # WRITE OPERATIONS
    # ===============================

    def upsert_post(self, cur: Cursor, post: Dict[str, Any], source_id: str) -> Tuple[str, bool]:
        """Save single post. Returns (post_id, was_inserted)."""
        # if new -> insert
        # if exists -> do nothing
        # if exists but different -> Update

        # Unified Structure
        platform = post.get("platform", "")
        source = post.get("source", "")
        url = post.get("url", "")
        content = post.get("content", "")
        date = post.get("date", "")
        media_urls = post.get("media_urls", []).get("urls", [])
        categories = post.get("categories", [])
        metadata = post.get("metadata", {})

        # Optional Fields
        title = post.get("title", "")
        content_html = post.get("content_html", "")

        pass

    def upsert_posts_batch(self, cur: Cursor, posts: List[Dict[str, Any]], source_id: str) -> Dict[str, int]:
        """Save multiple posts. Returns dict of (post_id, was_inserted) for each post."""
        # Call upsert_post for each post
        pass

    # ===============================
    # READ OPERATIONS
    # ===============================

    def get_posts_by_date(self, source_id: str, date) -> List[Dict[str, Any]]:
        pass

    def get_posts_by_source(self, source_id) -> List[Dict[str, Any]]:
        pass

    def get_post_count(self, source_id) -> int:
        pass

    def get_post_count_by_date(self, date) -> int:
        pass
