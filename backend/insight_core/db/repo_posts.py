import os, sys, json, hashlib
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
        external_id = post.get("external_id", None)

        # Lists -> JSON
        media_urls = json.dumps(post.get("media_urls", []))
        categories = json.dumps(post.get("categories", []))

        # Optional Fields
        title = post.get("title", None)
        content_html = post.get("content_html", None)
        lang = post.get("lang", None)
        content_hash = self._build_content_hash(title, content, content_html)
        # metadata = post.get("metadata", {}) ❌ Not stored yet (future)

        # SQL QUERY
        # Build SQL query
        query = """
            INSERT INTO posts (
                source_id, 
                url, 
                external_id,
                published_at, 
                title, 
                content, 
                content_html, 
                lang,
                content_hash,
                media_urls, 
                categories
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            ON CONFLICT (url) DO UPDATE SET
                external_id = COALESCE(EXCLUDED.external_id, posts.external_id),
                published_at = COALESCE(EXCLUDED.published_at, posts.published_at),
                title = COALESCE(EXCLUDED.title, posts.title),
                content = COALESCE(EXCLUDED.content, posts.content),
                content_html = COALESCE(EXCLUDED.content_html, posts.content_html),
                lang = COALESCE(EXCLUDED.lang, posts.lang),
                content_hash = COALESCE(EXCLUDED.content_hash, posts.content_hash),
                media_urls = EXCLUDED.media_urls,
                categories = EXCLUDED.categories,
                fetched_at = now(),
                updated_at = now()
            RETURNING id, (xmax = 0) AS inserted
        """
        
        # Execute with parameters
        cur.execute(query, (
            source_id,
            url,
            external_id,
            published_at,
            title,
            content,
            content_html,
            lang,
            content_hash,
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

        

    def get_posts_by_source(self, cur: Cursor, source_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all posts for a specific source, sorted by date descending.
        
        Args:
            cur: Database cursor
            source_id: UUID of the source
            
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
            WHERE p.source_id = %s
            ORDER BY COALESCE(p.published_at, p.fetched_at) DESC
        """
        cur.execute(query, (source_id,))
        rows = cur.fetchall()
        
        if not rows:
            self.logger.info(f"No posts found for source: {source_id}")
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

        self.logger.info(f"Successfully got {len(posts)} posts for source: {source_id}")
        
        return posts

    def get_post_count(self, source_id) -> int:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM posts WHERE source_id = %s", (source_id,))
                row = cur.fetchone()
                return row[0] if row else 0

    def get_post_count_by_date(self, date) -> int:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM posts
                    WHERE DATE(COALESCE(published_at, fetched_at)) = %s
                    """,
                    (date,),
                )
                row = cur.fetchone()
                return row[0] if row else 0

    def get_source_post_stats(self, cur: Cursor, source_id: str) -> Dict[str, Any]:
        """Return aggregate storage stats for a single source."""
        query = """
            SELECT
                COUNT(*) AS post_count,
                MIN(published_at) AS oldest_published_at,
                MAX(published_at) AS latest_published_at,
                MAX(fetched_at) AS latest_fetched_at
            FROM posts
            WHERE source_id = %s
        """
        cur.execute(query, (source_id,))
        row = cur.fetchone()

        return {
            "post_count": row[0] or 0,
            "oldest_published_at": row[1],
            "latest_published_at": row[2],
            "latest_fetched_at": row[3],
        }

    def _build_content_hash(self, title: Optional[str], content: str, content_html: Optional[str]) -> str:
        """Create a stable digest for dedupe and update tracking."""
        payload = "\n".join(
            part.strip()
            for part in [
                title or "",
                content or "",
                content_html or "",
            ]
            if part
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload else ""
