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
        url = post['url'] # Let KeyError happen
        content = post.get("content", "")
        published_at = post.get("date", None)

        # Lists -> JSON
        media_urls = json.dumps(post.get("media_urls", []))
        categories = json.dumps(post.get("categories", []))

        # Optional Fields
        title = post.get("title", None)
        content_html = post.get("content_html", None)
        # metadata = post.get("metadata", {}) ❌ Not stored yet (future)

        # SQL QUERY
        # Build SQL query
        query = """
            INSERT INTO posts (
                source_id, 
                url, 
                published_at, 
                title, 
                content, 
                content_html, 
                media_urls, 
                categories
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            ON CONFLICT (url) DO UPDATE SET
                fetched_at = now(),
                updated_at = now()
            RETURNING id, (xmax = 0) AS inserted
        """
        
        # Execute with parameters
        cur.execute(query, (
            source_id,
            url,
            published_at,
            title,
            content,
            content_html,
            media_urls,
            categories
        ))
        
        # Fetch result
        row = cur.fetchone()
        post_id = str(row[0])  # UUID → string
        was_inserted = row[1]  # Boolean
        
        # Log action
        action = "Inserted" if was_inserted else "Updated"
        self.logger.debug(f"{action} post: {url[:60]}...")
        
        return (post_id, was_inserted)
        


    def upsert_posts_batch(self, cur: Cursor, posts: List[Dict[str, Any]], source_id: str) -> Dict[str, int]:
        """Save multiple posts. Returns dict of (post_id, was_inserted) for each post."""
        # Call upsert_post for each post
        pass

    # ===============================
    # READ OPERATIONS
    # ===============================

    def get_posts_by_date(self, cur: Cursor, date) -> List[Dict[str, Any]]:
        """
        Retrieve posts for a specific date.
        
        Args:
            cur: Database cursor
            target_date: Python date object (e.g., date(2025, 10, 23))
            
        Returns:
            List of post dicts with all fields populated
        """
        
        query = """
            SELECT
                p.id,
                p.url,
                p.content,
                p.published_at,
                p.fetched_at,
                p.content_html,
                p.media_urls,
                p.categories,
                p.title,
                s.platform,
                s.handle_or_url
            FROM posts p
            JOIN sources s ON p.source_id = s.id
            WHERE DATE(COALESCE(p.published_at, p.fetched_at)) = %s
            ORDER BY COALESCE(p.published_at, p.fetched_at) DESC
        """
        cur.execute(query, (date,))
        rows = cur.fetchall()
        
        if not rows:
            self.logger.error(f"No posts found by date: {date}")
            return []

        posts = []
        for row in rows:
            post = {
                'id': str(row[0]),
                'url': row[1],
                'content': row[2],
                'date': row[3],                # For Frontend
                'published_at': row[3],
                'fetched_at': row[4],
                'content_html': row[5],
                'media_urls': row[6],
                'categories': row[7],
                'title': row[8],
                'platform': row[9],
                'handle_or_url': row[10],
                'source': row[10]              # For Frontend
            }
            posts.append(post)

        self.logger.info(f"Successfully got {len(posts)} posts by date: {date}")
        
        return posts

        

    def get_posts_by_source(self, source_id) -> List[Dict[str, Any]]:
        pass

    def get_post_count(self, source_id) -> int:
        pass

    def get_post_count_by_date(self, date) -> int:
        pass
