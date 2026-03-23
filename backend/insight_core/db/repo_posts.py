import os, sys, json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from psycopg import Connection, Cursor

from insight_core.logs.core.logger_config import setup_logging, get_component_logger
from insight_core.db.ensure_db import ensure_database
from insight_core.utils.entity_memory import build_post_memory_fields
from insight_core.utils.evidence import build_post_evidence_fields


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
        media_urls = self._json_dumps(post.get("media_urls", []))
        categories = self._json_dumps(post.get("categories", []))

        # Optional Fields
        title = post.get("title", None)
        content_html = post.get("content_html", None)
        lang = post.get("lang", None)
        metadata = self._json_dumps(post.get("metadata", {}))
        memory_fields = build_post_memory_fields(post)
        evidence = build_post_evidence_fields(post)
        content_hash = evidence.get("content_hash") or self._build_content_hash(title, content, content_html)
        language_code = evidence.get("language_code")
        language_confidence = evidence.get("language_confidence")
        normalized_url = evidence.get("normalized_url")
        canonical_url = evidence.get("canonical_url")
        url_host = evidence.get("url_host")
        title_hash = evidence.get("title_hash")
        normalization_version = evidence.get("normalization_version")

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
                title_original,
                body_original,
                title_pivot,
                summary_pivot,
                title_pivot_version,
                summary_pivot_version,
                content_hash,
                language_code,
                language_confidence,
                normalized_url,
                canonical_url,
                url_host,
                title_hash,
                normalization_version,
                enriched_at,
                metadata,
                media_urls, 
                categories
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s::jsonb, %s::jsonb, %s::jsonb)
            ON CONFLICT (url) DO UPDATE SET
                external_id = COALESCE(EXCLUDED.external_id, posts.external_id),
                published_at = COALESCE(EXCLUDED.published_at, posts.published_at),
                title = COALESCE(EXCLUDED.title, posts.title),
                content = COALESCE(EXCLUDED.content, posts.content),
                content_html = COALESCE(EXCLUDED.content_html, posts.content_html),
                lang = COALESCE(EXCLUDED.lang, posts.lang),
                title_original = COALESCE(EXCLUDED.title_original, posts.title_original),
                body_original = COALESCE(EXCLUDED.body_original, posts.body_original),
                title_pivot = EXCLUDED.title_pivot,
                summary_pivot = EXCLUDED.summary_pivot,
                title_pivot_version = EXCLUDED.title_pivot_version,
                summary_pivot_version = EXCLUDED.summary_pivot_version,
                content_hash = COALESCE(EXCLUDED.content_hash, posts.content_hash),
                language_code = EXCLUDED.language_code,
                language_confidence = EXCLUDED.language_confidence,
                normalized_url = EXCLUDED.normalized_url,
                canonical_url = EXCLUDED.canonical_url,
                url_host = EXCLUDED.url_host,
                title_hash = EXCLUDED.title_hash,
                normalization_version = EXCLUDED.normalization_version,
                enriched_at = now(),
                metadata = COALESCE(EXCLUDED.metadata, posts.metadata),
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
            memory_fields.get("title_original"),
            memory_fields.get("body_original"),
            memory_fields.get("title_pivot"),
            memory_fields.get("summary_pivot"),
            memory_fields.get("title_pivot_version"),
            memory_fields.get("summary_pivot_version"),
            content_hash,
            language_code,
            language_confidence,
            normalized_url,
            canonical_url,
            url_host,
            title_hash,
            normalization_version,
            metadata,
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
        inserted = 0
        updated = 0
        for post in posts:
            _, was_inserted = self.upsert_post(cur, post, source_id)
            if was_inserted:
                inserted += 1
            else:
                updated += 1
        return {"inserted": inserted, "updated": updated}

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
                p.metadata,
                p.media_urls,
                p.categories,
                p.title,
                p.source_id,
                p.lang,
                p.language_code,
                p.language_confidence,
                p.normalized_url,
                p.canonical_url,
                p.url_host,
                p.title_hash,
                p.content_hash,
                p.normalization_version,
                p.enriched_at,
                p.title_original,
                p.body_original,
                p.title_pivot,
                p.summary_pivot,
                p.title_pivot_version,
                p.summary_pivot_version,
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
                'metadata': row[6] or {},
                'media_urls': row[7],
                'categories': row[8],
                'title': row[9],
                'source_id': str(row[10]),
                'lang': row[11],
                'language_code': row[12],
                'language_confidence': row[13],
                'normalized_url': row[14],
                'canonical_url': row[15],
                'url_host': row[16],
                'title_hash': row[17],
                'content_hash': row[18],
                'normalization_version': row[19],
                'enriched_at': row[20],
                'title_original': row[21],
                'body_original': row[22],
                'title_pivot': row[23],
                'summary_pivot': row[24],
                'title_pivot_version': row[25],
                'summary_pivot_version': row[26],
                'platform': row[27],
                'handle_or_url': row[28],
                'source': row[28],              # For Frontend
            }
            posts.append(post)

        self.logger.info(f"Successfully got {len(posts)} posts by date: {date}")
        
        return posts

        

    def get_posts_by_source(
        self,
        cur: Cursor,
        source_id: str,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve posts for a specific source, sorted by date descending.
        
        Args:
            cur: Database cursor
            source_id: UUID of the source
            limit: Optional page size
            offset: Optional page offset
            
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
                p.metadata,
                p.media_urls,
                p.categories,
                p.title,
                p.source_id,
                p.lang,
                p.language_code,
                p.language_confidence,
                p.normalized_url,
                p.canonical_url,
                p.url_host,
                p.title_hash,
                p.content_hash,
                p.normalization_version,
                p.enriched_at,
                p.title_original,
                p.body_original,
                p.title_pivot,
                p.summary_pivot,
                p.title_pivot_version,
                p.summary_pivot_version,
                s.platform,
                s.handle_or_url,
                COALESCE(s.settings->>'display_name', s.handle_or_url) AS source_display_name
            FROM posts p
            JOIN sources s ON p.source_id = s.id
            WHERE p.source_id = %s
            ORDER BY COALESCE(p.published_at, p.fetched_at) DESC
        """
        params: List[Any] = [source_id]
        if limit is not None:
            query += "\n LIMIT %s OFFSET %s"
            params.extend([max(1, int(limit)), max(0, int(offset))])

        cur.execute(query, tuple(params))
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
                'metadata': row[6] or {},
                'media_urls': row[7],
                'categories': row[8],
                'title': row[9],
                'source_id': str(row[10]),
                'lang': row[11],
                'language_code': row[12],
                'language_confidence': row[13],
                'normalized_url': row[14],
                'canonical_url': row[15],
                'url_host': row[16],
                'title_hash': row[17],
                'content_hash': row[18],
                'normalization_version': row[19],
                'enriched_at': row[20],
                'title_original': row[21],
                'body_original': row[22],
                'title_pivot': row[23],
                'summary_pivot': row[24],
                'title_pivot_version': row[25],
                'summary_pivot_version': row[26],
                'platform': row[27],
                'handle_or_url': row[28],
                'source': row[28],              # For Frontend
                'source_display_name': row[29],
            }
            posts.append(post)

        self.logger.info(f"Successfully got {len(posts)} posts for source: {source_id}")
        
        return posts

    def get_posts_by_source_and_range(
        self,
        cur: Cursor,
        source_id: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        """Retrieve posts for a specific source within an inclusive date range."""
        query = """
            SELECT
                p.id,
                p.url,
                p.content,
                p.published_at,
                p.fetched_at,
                p.content_html,
                p.metadata,
                p.media_urls,
                p.categories,
                p.title,
                p.source_id,
                p.lang,
                p.language_code,
                p.language_confidence,
                p.normalized_url,
                p.canonical_url,
                p.url_host,
                p.title_hash,
                p.content_hash,
                p.normalization_version,
                p.enriched_at,
                p.title_original,
                p.body_original,
                p.title_pivot,
                p.summary_pivot,
                p.title_pivot_version,
                p.summary_pivot_version,
                s.platform,
                s.handle_or_url,
                COALESCE(s.settings->>'display_name', s.handle_or_url) AS source_display_name
            FROM posts p
            JOIN sources s ON p.source_id = s.id
            WHERE p.source_id = %s
              AND DATE(COALESCE(p.published_at, p.fetched_at)) BETWEEN %s AND %s
            ORDER BY DATE(COALESCE(p.published_at, p.fetched_at)) ASC, COALESCE(p.published_at, p.fetched_at) ASC, p.created_at ASC
        """
        cur.execute(query, (source_id, start_date, end_date))
        rows = cur.fetchall()

        if not rows:
            self.logger.info(
                "No posts found for source %s in range %s to %s",
                source_id,
                start_date,
                end_date,
            )
            return []

        posts = []
        for row in rows:
            post = {
                'id': str(row[0]),
                'url': row[1],
                'content': row[2],
                'date': row[3],
                'published_at': row[3],
                'fetched_at': row[4],
                'content_html': row[5],
                'metadata': row[6] or {},
                'media_urls': row[7],
                'categories': row[8],
                'title': row[9],
                'source_id': str(row[10]),
                'lang': row[11],
                'language_code': row[12],
                'language_confidence': row[13],
                'normalized_url': row[14],
                'canonical_url': row[15],
                'url_host': row[16],
                'title_hash': row[17],
                'content_hash': row[18],
                'normalization_version': row[19],
                'enriched_at': row[20],
                'title_original': row[21],
                'body_original': row[22],
                'title_pivot': row[23],
                'summary_pivot': row[24],
                'title_pivot_version': row[25],
                'summary_pivot_version': row[26],
                'platform': row[27],
                'handle_or_url': row[28],
                'source': row[28],
                'source_display_name': row[29],
            }
            posts.append(post)

        self.logger.info(
            "Successfully got %s posts for source %s in range %s to %s",
            len(posts),
            source_id,
            start_date,
            end_date,
        )
        return posts

    def get_posts_by_ids(self, cur: Cursor, post_ids: List[str]) -> List[Dict[str, Any]]:
        """Retrieve multiple posts by UUID, preserving caller order as much as possible."""
        if not post_ids:
            return []

        requested_rows = ", ".join(f"(%s::uuid, {index})" for index in range(1, len(post_ids) + 1))
        query = """
            SELECT
                p.id,
                p.url,
                p.content,
                p.published_at,
                p.fetched_at,
                p.content_html,
                p.metadata,
                p.media_urls,
                p.categories,
                p.title,
                p.source_id,
                p.lang,
                p.language_code,
                p.language_confidence,
                p.normalized_url,
                p.canonical_url,
                p.url_host,
                p.title_hash,
                p.content_hash,
                p.normalization_version,
                p.enriched_at,
                p.title_original,
                p.body_original,
                p.title_pivot,
                p.summary_pivot,
                p.title_pivot_version,
                p.summary_pivot_version,
                s.platform,
                s.handle_or_url,
                COALESCE(s.settings->>'display_name', s.handle_or_url) AS source_display_name
            FROM posts p
            JOIN sources s ON p.source_id = s.id
            JOIN (VALUES {requested_rows}) AS requested(post_id, ord) ON p.id = requested.post_id
            ORDER BY requested.ord
        """.format(requested_rows=requested_rows)
        cur.execute(query, tuple(post_ids))
        rows = cur.fetchall()

        posts_by_id = {
            str(row[0]): {
                'id': str(row[0]),
                'url': row[1],
                'content': row[2],
                'date': row[3],
                'published_at': row[3],
                'fetched_at': row[4],
                'content_html': row[5],
                'metadata': row[6] or {},
                'media_urls': row[7],
                'categories': row[8],
                'title': row[9],
                'source_id': str(row[10]),
                'lang': row[11],
                'language_code': row[12],
                'language_confidence': row[13],
                'normalized_url': row[14],
                'canonical_url': row[15],
                'url_host': row[16],
                'title_hash': row[17],
                'content_hash': row[18],
                'normalization_version': row[19],
                'enriched_at': row[20],
                'title_original': row[21],
                'body_original': row[22],
                'title_pivot': row[23],
                'summary_pivot': row[24],
                'title_pivot_version': row[25],
                'summary_pivot_version': row[26],
                'platform': row[27],
                'handle_or_url': row[28],
                'source': row[28],
                'source_display_name': row[29],
            }
            for row in rows
        }

        ordered = [posts_by_id[post_id] for post_id in post_ids if post_id in posts_by_id]
        return ordered

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

    def update_post_categories(self, cur: Cursor, post_id: str, categories: List[str]) -> bool:
        """Persist generated categories for a single post."""
        query = """
            UPDATE posts
            SET categories = %s::jsonb,
                updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        cur.execute(query, (self._json_dumps(categories), post_id))
        return cur.fetchone() is not None

    def update_post_metadata(self, cur: Cursor, post_id: str, metadata: Dict[str, Any]) -> bool:
        """Persist metadata for a single post."""
        query = """
            UPDATE posts
            SET metadata = %s::jsonb,
                updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        cur.execute(query, (self._json_dumps(metadata), post_id))
        return cur.fetchone() is not None

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

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(value, default=self._json_default)

    def _json_default(self, value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value)} is not JSON serializable")
