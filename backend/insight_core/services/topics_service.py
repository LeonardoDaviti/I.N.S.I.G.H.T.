"""
Business logic layer for topics operations.
Coordinates between API and database repository.
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import date

import psycopg
from psycopg import Connection

from insight_core.db.repo_topics import TopicsRepository
from insight_core.logs.core.logger_config import get_component_logger


class TopicsService:
    """
    Service layer for topics business logic.
    Handles topic retrieval and management operations.
    """

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = TopicsRepository(db_url)
        self.logger = get_component_logger("topics_service")

    # ===============================
    # CHECK OPERATIONS
    # ===============================

    def topics_exist_for_date(self, target_date: date) -> bool:
        """Check if any topics exist for a specific date."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.topics_exist_for_date(cur, target_date)

    def get_topic_by_id(self, topic_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single topic by ID."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_topic_by_id(cur, topic_id)

    def get_topic_by_date_and_title(self, target_date: date, title: str) -> Optional[Dict[str, Any]]:
        """Retrieve a topic by date and title."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_topic_by_date_and_title(cur, target_date, title)

    # ===============================
    # READ OPERATIONS
    # ===============================

    def get_topics_by_date(self, target_date: date) -> List[Dict[str, Any]]:
        """Get all topics for a specific date (including outliers)."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_topics_by_date(cur, target_date)

    def delete_topics_by_date(self, target_date: date) -> int:
        """Delete all topics for a specific date."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                deleted = self.repo.delete_topics_by_date(cur, target_date)
                conn.commit()
                return deleted

    def get_posts_for_topic(self, topic_id: str) -> List[Dict[str, Any]]:
        """Get all posts associated with a specific topic."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_posts_for_topic(cur, topic_id)

    def find_similar_topics(
        self, 
        topic_id: str, 
        threshold: float = 0.75, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Find similar topics using pgvector cosine similarity."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.find_similar_topics(cur, topic_id, threshold, limit)

    # ===============================
    # WRITE OPERATIONS
    # ===============================

    def insert_topic(
        self, 
        target_date: date, 
        title: str, 
        embedding: Optional[List[float]], 
        is_outlier: bool = False,
        summary: str = None
    ) -> str:
        """Insert a new topic and return its UUID."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                topic_id = self.repo.insert_topic(
                    cur, target_date, title, embedding, is_outlier, summary
                )
                conn.commit()
                return topic_id

    def insert_topic_post(self, topic_id: str, post_id: str):
        """Insert a topic-post association."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self.repo.insert_topic_post(cur, topic_id, post_id)
                conn.commit()

    def insert_topic_connection(self, source_id: str, target_id: str, score: float):
        """Insert a topic connection with similarity score."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self.repo.insert_topic_connection(cur, source_id, target_id, score)
                conn.commit()

    # ===============================
    # BATCH OPERATIONS
    # ===============================

    def insert_topics_batch(self, topics_data: List[Dict[str, Any]]) -> List[str]:
        """
        Insert multiple topics and return their UUIDs.
        All inserts happen in a single transaction.
        """
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                topic_ids = self.repo.insert_topics_batch(cur, topics_data)
                conn.commit()
                return topic_ids

    def insert_connections_batch(self, connections: List[Tuple[str, str, float]]):
        """
        Insert multiple topic connections efficiently.
        All inserts happen in a single transaction.
        """
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self.repo.insert_connections_batch(cur, connections)
                conn.commit()

    # ===============================
    # UPDATE OPERATIONS
    # ===============================

    def update_topic_title(self, topic_id: str, new_title: str) -> bool:
        """
        Update the title of a topic.
        
        Args:
            topic_id: UUID of the topic
            new_title: New title for the topic
            
        Returns:
            True if update was successful, False otherwise
        """
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                success = self.repo.update_topic_title(cur, topic_id, new_title)
                if success:
                    conn.commit()
                    self.logger.info(f"Updated topic title: {topic_id}")
                return success

    def move_post_between_topics(self, post_id: str, source_topic_id: str, target_topic_id: str) -> bool:
        """
        Move a post from one topic to another.
        
        Args:
            post_id: UUID of the post
            source_topic_id: UUID of the source topic
            target_topic_id: UUID of the target topic
            
        Returns:
            True if move was successful, False otherwise
        """
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                success = self.repo.move_post_between_topics(cur, post_id, source_topic_id, target_topic_id)
                if success:
                    conn.commit()
                    self.logger.info(f"Moved post {post_id} from topic {source_topic_id} to {target_topic_id}")
                return success

    def move_post_to_outlier(self, post_id: str, source_topic_id: str, target_date: date) -> Dict[str, Any]:
        """
        Move a post from a topic to the outlier topic for a specific date.
        Creates the outlier topic if it doesn't exist.
        
        Args:
            post_id: UUID of the post
            source_topic_id: UUID of the source topic
            target_date: Date for finding/creating outlier topic
            
        Returns:
            Dict with success status and outlier topic ID
        """
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                result = self.repo.move_post_to_outlier(cur, post_id, source_topic_id, target_date)
                if result["success"]:
                    conn.commit()
                    self.logger.info(f"Moved post {post_id} to outlier topic {result['outlier_topic_id']}")
                return result

    # ===============================
    # COMBINED OPERATIONS
    # ===============================

    def save_topics_with_connections(
        self,
        target_date: date,
        topics_data: List[Dict[str, Any]],
        connections: List[Tuple[str, str, float]]
    ) -> List[str]:
        """
        Save multiple topics and their connections in a single transaction.
        
        Args:
            target_date: Date for the topics
            topics_data: List of topic dicts (date, title, embedding, is_outlier, summary)
            connections: List of connection tuples (source_id, target_id, score)
            
        Returns:
            List of topic UUIDs
        """
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                # Insert topics
                topic_ids = self.repo.insert_topics_batch(cur, topics_data)
                
                # Insert connections
                if connections:
                    self.repo.insert_connections_batch(cur, connections)
                
                conn.commit()
                self.logger.info(
                    f"Saved {len(topic_ids)} topics and {len(connections)} connections "
                    f"for date {target_date}"
                )
                return topic_ids

    def save_topic_with_posts(
        self,
        target_date: date,
        title: str,
        embedding: Optional[List[float]],
        post_ids: List[str],
        is_outlier: bool = False,
        summary: str = None
    ) -> str:
        """
        Save a topic and associate it with multiple posts in a single transaction.
        
        Args:
            target_date: Date for the topic
            title: Topic title
            embedding: Topic embedding or None for outliers
            post_ids: List of post UUIDs to associate
            is_outlier: Whether this is an outlier topic
            summary: Optional topic summary
            
        Returns:
            Topic UUID
        """
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                # Insert topic
                topic_id = self.repo.insert_topic(
                    cur, target_date, title, embedding, is_outlier, summary
                )
                
                # Associate posts
                for post_id in post_ids:
                    self.repo.insert_topic_post(cur, topic_id, post_id)
                
                conn.commit()
                self.logger.info(
                    f"Saved topic '{title}' with {len(post_ids)} posts "
                    f"for date {target_date}"
                )
                return topic_id
