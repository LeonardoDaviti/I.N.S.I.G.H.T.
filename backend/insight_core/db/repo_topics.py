import os, sys, json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from datetime import date

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from psycopg import Connection, Cursor

from insight_core.logs.core.logger_config import setup_logging, get_component_logger


class TopicsRepository:
    """
    Database access layer for topics table.
    Handles all SQL operations for storing and retrieving topics.
    """

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("repo_topics")
        self.logger.info(f"TopicsRepository initialized")

    # ===============================
    # CHECK OPERATIONS
    # ===============================

    def topics_exist_for_date(self, cur: Cursor, target_date: date) -> bool:
        """
        Check if any topics exist for a specific date.
        
        Args:
            cur: Database cursor
            target_date: Python date object
            
        Returns:
            True if topics exist, False otherwise
        """
        query = """
            SELECT EXISTS(
                SELECT 1 FROM topics 
                WHERE date = %s
            )
        """
        cur.execute(query, (target_date,))
        exists = cur.fetchone()[0]
        
        self.logger.debug(f"Topics exist for {target_date}: {exists}")
        return exists

    def get_topic_by_id(self, cur: Cursor, topic_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single topic by ID.
        
        Args:
            cur: Database cursor
            topic_id: UUID of the topic
            
        Returns:
            Topic dict or None if not found
        """
        query = """
            SELECT 
                id,
                date,
                title,
                summary,
                is_outlier,
                created_at
            FROM topics
            WHERE id = %s
        """
        cur.execute(query, (topic_id,))
        row = cur.fetchone()
        
        if not row:
            self.logger.debug(f"Topic not found: {topic_id}")
            return None
        
        topic = {
            'id': str(row[0]),
            'date': row[1],
            'title': row[2],
            'summary': row[3],
            'is_outlier': row[4],
            'created_at': row[5]
        }
        
        self.logger.debug(f"Retrieved topic: {topic_id}")
        return topic

    def get_topic_by_date_and_title(self, cur: Cursor, target_date: date, title: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a topic by date and title (used to check if outlier topic already exists).
        
        Args:
            cur: Database cursor
            target_date: Python date object
            title: Topic title
            
        Returns:
            Topic dict or None if not found
        """
        query = """
            SELECT 
                id,
                date,
                title,
                summary,
                is_outlier,
                created_at
            FROM topics
            WHERE date = %s AND title = %s
        """
        cur.execute(query, (target_date, title))
        row = cur.fetchone()
        
        if not row:
            self.logger.debug(f"Topic not found for date {target_date} and title '{title}'")
            return None
        
        topic = {
            'id': str(row[0]),
            'date': row[1],
            'title': row[2],
            'summary': row[3],
            'is_outlier': row[4],
            'created_at': row[5]
        }
        
        self.logger.debug(f"Retrieved topic by date/title: {topic['id']}")
        return topic

    # ===============================
    # READ OPERATIONS
    # ===============================

    def get_topics_by_date(self, cur: Cursor, target_date: date) -> List[Dict[str, Any]]:
        """
        Retrieve all topics for a specific date (including outliers).
        
        Args:
            cur: Database cursor
            target_date: Python date object
            
        Returns:
            List of topic dicts ordered by is_outlier ASC, created_at
        """
        query = """
            SELECT 
                id,
                date,
                title,
                summary,
                is_outlier,
                created_at
            FROM topics
            WHERE date = %s
            ORDER BY is_outlier ASC, created_at
        """
        cur.execute(query, (target_date,))
        rows = cur.fetchall()
        
        if not rows:
            self.logger.info(f"No topics found for date: {target_date}")
            return []
        
        topics = []
        for row in rows:
            topic = {
                'id': str(row[0]),
                'date': row[1],
                'title': row[2],
                'summary': row[3],
                'is_outlier': row[4],
                'created_at': row[5]
            }
            topics.append(topic)
        
        self.logger.info(f"Successfully got {len(topics)} topics for date: {target_date}")
        return topics

    def get_posts_for_topic(self, cur: Cursor, topic_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all posts associated with a specific topic.
        
        Args:
            cur: Database cursor
            topic_id: UUID of the topic
            
        Returns:
            List of post dicts ordered by published_at DESC
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
            FROM topic_posts tp
            JOIN posts p ON tp.post_id = p.id
            JOIN sources s ON p.source_id = s.id
            WHERE tp.topic_id = %s
            ORDER BY COALESCE(p.published_at, p.fetched_at) DESC
        """
        cur.execute(query, (topic_id,))
        rows = cur.fetchall()
        
        if not rows:
            self.logger.info(f"No posts found for topic: {topic_id}")
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
        
        self.logger.info(f"Successfully got {len(posts)} posts for topic: {topic_id}")
        return posts

    def find_similar_topics(
        self, 
        cur: Cursor, 
        topic_id: str, 
        threshold: float = 0.75, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find similar topics using pgvector cosine similarity.
        
        Args:
            cur: Database cursor
            topic_id: UUID of the source topic
            threshold: Minimum similarity score (default 0.75)
            limit: Maximum number of results (default 10)
            
        Returns:
            List of similar topic dicts with similarity scores
        """
        query = """
            SELECT 
                t2.id,
                t2.title,
                t2.date,
                1 - (t1.embedding <=> t2.embedding) as similarity
            FROM topics t1
            CROSS JOIN topics t2
            WHERE t1.id = %s
              AND t2.id != %s
              AND t1.is_outlier = FALSE
              AND t2.is_outlier = FALSE
              AND 1 - (t1.embedding <=> t2.embedding) > %s
            ORDER BY t1.embedding <=> t2.embedding
            LIMIT %s
        """
        cur.execute(query, (topic_id, topic_id, threshold, limit))
        rows = cur.fetchall()
        
        if not rows:
            self.logger.debug(f"No similar topics found for: {topic_id}")
            return []
        
        similar_topics = []
        for row in rows:
            topic = {
                'id': str(row[0]),
                'title': row[1],
                'date': row[2],
                'similarity_score': float(row[3])
            }
            similar_topics.append(topic)
        
        self.logger.debug(f"Found {len(similar_topics)} similar topics for: {topic_id}")
        return similar_topics

    # ===============================
    # WRITE OPERATIONS
    # ===============================

    def insert_topic(
        self, 
        cur: Cursor, 
        target_date: date, 
        title: str, 
        embedding: Optional[List[float]], 
        is_outlier: bool = False,
        summary: str = None
    ) -> str:
        """
        Insert a new topic and return its UUID.
        
        Args:
            cur: Database cursor
            target_date: Python date object
            title: Topic title
            embedding: List of floats (1024 dimensions) or None for outliers
            is_outlier: Whether this is an outlier topic
            summary: Optional topic summary
            
        Returns:
            UUID of the inserted topic
            
        Note:
            If embedding is None, is_outlier must be True (CHECK constraint)
        """
        # Convert embedding list to string format for pgvector
        embedding_str = None
        if embedding is not None:
            embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
        
        query = """
            INSERT INTO topics (
                date,
                title,
                summary,
                embedding,
                is_outlier
            )
            VALUES (%s, %s, %s, %s::vector(1024), %s)
            RETURNING id
        """
        
        cur.execute(query, (
            target_date,
            title,
            summary,
            embedding_str,
            is_outlier
        ))
        
        row = cur.fetchone()
        topic_id = str(row[0])
        
        self.logger.debug(f"Inserted topic: {title} (outlier={is_outlier})")
        return topic_id

    def insert_topic_post(self, cur: Cursor, topic_id: str, post_id: str):
        """
        Insert a topic-post association.
        
        Args:
            cur: Database cursor
            topic_id: UUID of the topic
            post_id: UUID of the post
            
        Note:
            Uses ON CONFLICT DO NOTHING for idempotency
        """
        query = """
            INSERT INTO topic_posts (topic_id, post_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """
        
        cur.execute(query, (topic_id, post_id))
        self.logger.debug(f"Inserted topic_post: topic={topic_id[:8]}..., post={post_id[:8]}...")

    def insert_topic_connection(self, cur: Cursor, source_id: str, target_id: str, score: float):
        """
        Insert a topic connection with similarity score.
        
        Args:
            cur: Database cursor
            source_id: UUID of the source topic
            target_id: UUID of the target topic
            score: Similarity score (float)
            
        Note:
            Uses ON CONFLICT DO NOTHING for idempotency
        """
        query = """
            INSERT INTO topic_connections (source_topic_id, target_topic_id, similarity_score)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """
        
        cur.execute(query, (source_id, target_id, score))
        self.logger.debug(f"Inserted connection: {source_id[:8]}... -> {target_id[:8]}... (score={score:.3f})")

    # ===============================
    # BATCH OPERATIONS
    # ===============================

    def insert_topics_batch(self, cur: Cursor, topics_data: List[Dict[str, Any]]) -> List[str]:
        """
        Insert multiple topics and return their UUIDs.
        
        Args:
            cur: Database cursor
            topics_data: List of topic dicts, each with:
                - date: Python date object
                - title: str
                - embedding: List[float] or None
                - is_outlier: bool
                - summary: Optional[str]
                
        Returns:
            List of topic UUIDs in the same order as input
        """
        topic_ids = []
        
        for topic_data in topics_data:
            topic_id = self.insert_topic(
                cur,
                target_date=topic_data['date'],
                title=topic_data['title'],
                embedding=topic_data.get('embedding'),
                is_outlier=topic_data.get('is_outlier', False),
                summary=topic_data.get('summary')
            )
            topic_ids.append(topic_id)
        
        self.logger.info(f"Batch inserted {len(topic_ids)} topics")
        return topic_ids

    def insert_connections_batch(self, cur: Cursor, connections: List[Tuple[str, str, float]]):
        """
        Insert multiple topic connections efficiently.
        
        Args:
            cur: Database cursor
            connections: List of tuples (source_id, target_id, score)
            
        Note:
            Uses executemany for performance
        """
        if not connections:
            return
        
        query = """
            INSERT INTO topic_connections (source_topic_id, target_topic_id, similarity_score)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """
        
        cur.executemany(query, connections)
        self.logger.info(f"Batch inserted {len(connections)} connections")

