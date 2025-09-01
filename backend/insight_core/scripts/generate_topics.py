# backend/insight_core/scripts/generate_topics.py
"""
Generate topics from posts for a specific date and save to database.
Usage: python backend/insight_core/scripts/generate_topics.py [YYYY-MM-DD]
"""
import sys
from pathlib import Path
import time
from datetime import date, datetime

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from insight_core.db.ensure_db import ensure_database
from insight_core.db.repo_posts import PostsRepository
from insight_core.db.repo_topics import TopicsRepository
from insight_core.services.topics_service import TopicsService
from insight_core.processors.ai.gemini_processor import GeminiProcessor
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

DEBUG_MODE = True
setup_logging(debug_mode=DEBUG_MODE)
logger = get_component_logger("generate_topics")


class TopicGenerator:
    """
    Generates topics from posts using AI and stores them in the database.
    """
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.posts_repo = PostsRepository(db_url)
        self.topics_service = TopicsService(db_url)
        self.processor = GeminiProcessor()
        
    def setup(self) -> bool:
        """Setup AI processor."""
        # Setup Gemini processor
        if not self.processor.setup_processor():
            logger.error("Failed to setup Gemini processor")
            return False
        
        logger.info("AI processor configured successfully")
        return True
    
    def fetch_posts_by_date(self, target_date: date):
        """Fetch all posts for a specific date."""
        logger.info(f"📥 Fetching posts for {target_date}")
        
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                posts = self.posts_repo.get_posts_by_date(cur, target_date)
                
        if not posts:
            logger.warning(f"⚠️  No posts found for {target_date}")
            return []
        
        logger.info(f"✅ Retrieved {len(posts)} posts for {target_date}")
        return posts
    
    def generate_topics_from_posts(self, posts: list, target_date: date) -> dict:
        """
        Generate topics from posts and store in database.
        
        Args:
            posts: List of post dictionaries
            target_date: Date for the topics
            
        Returns:
            Dictionary with statistics
        """
        if not posts:
            logger.warning("No posts to generate topics from")
            return {
                "success": False,
                "error": "No posts provided"
            }
        
        # Check if topics already exist for this date
        if self.topics_service.topics_exist_for_date(target_date):
            logger.warning(f"⚠️  Topics already exist for {target_date}")
            logger.info("To regenerate, manually delete existing topics first")
            return {
                "success": False,
                "error": "Topics already exist for this date"
            }
        
        # 1. Run topic modeling
        logger.info(f"🤖 Running topic modeling on {len(posts)} posts...")
        start_time = time.time()
        
        result = self.processor.model_topics(posts)
        
        if not result["success"]:
            logger.error(f"❌ Topic modeling failed: {result.get('error')}")
            return result
        
        modeling_time = time.time() - start_time
        logger.info(f"✅ Topic modeling completed in {modeling_time:.2f}s")
        
        topic_names = result["topic_names"]
        assignments = result["assignments"]
        
        logger.info(f"📊 Found {len(topic_names)} topics from {len(assignments)} posts")
        
        # 2. Store topics in database
        logger.info("💾 Storing topics in database...")
        storage_start = time.time()
        
        # Map LLM topic IDs to database UUIDs
        topic_id_map = {}  # Maps LLM topic_id (0, 1, 2...) to database UUID
        
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                # Store regular topics (without embeddings for now)
                for topic_id_str, topic_title in topic_names.items():
                    topic_id_int = int(topic_id_str)
                    
                    logger.debug(f"   Storing topic: '{topic_title}'")
                    
                    # Insert topic (as outlier since we're not generating embeddings yet)
                    db_topic_id = self.topics_service.repo.insert_topic(
                        cur,
                        target_date=target_date,
                        title=topic_title,
                        embedding=None,
                        is_outlier=False,
                        summary=None
                    )
                    
                    topic_id_map[topic_id_int] = db_topic_id
                    logger.debug(f"   ✅ Topic {topic_id_int} -> {db_topic_id[:8]}...")
                
                # Create separate outlier topic if needed
                outlier_posts = [post_id for post_id, tid in assignments.items() if tid == -1]
                if outlier_posts:
                    logger.info(f"📌 Creating uncategorized topic for {len(outlier_posts)} posts")
                    outlier_topic_id = self.topics_service.repo.insert_topic(
                        cur,
                        target_date=target_date,
                        title="Uncategorized Posts",
                        embedding=None,
                        is_outlier=True,
                        summary=None
                    )
                    topic_id_map[-1] = outlier_topic_id
                    logger.debug(f"   ✅ Uncategorized topic -> {outlier_topic_id[:8]}...")
                
                conn.commit()
        
        storage_time = time.time() - storage_start
        logger.info(f"✅ Topics stored in database in {storage_time:.2f}s")
        
        # 3. Store topic-post associations
        logger.info("🔗 Creating topic-post associations...")
        association_start = time.time()
        
        # Create a set of valid post IDs for validation
        valid_post_ids = {post['id'] for post in posts}
        associations_created = 0
        skipped_invalid_posts = 0
        
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                
                for post_id, topic_id_int in assignments.items():
                    # Validate post ID exists in our original posts
                    if post_id not in valid_post_ids:
                        logger.warning(f"Post ID {post_id} not found in original posts, skipping")
                        skipped_invalid_posts += 1
                        continue
                    
                    # Get database UUID for this topic
                    db_topic_id = topic_id_map.get(topic_id_int)
                    
                    if db_topic_id is None:
                        logger.warning(f"No database ID found for topic {topic_id_int}")
                        continue
                    
                    # Insert association
                    self.topics_service.repo.insert_topic_post(cur, db_topic_id, post_id)
                    associations_created += 1
                
                conn.commit()
        
        if skipped_invalid_posts > 0:
            logger.warning(f"⚠️  Skipped {skipped_invalid_posts} associations with invalid post IDs")
        
        association_time = time.time() - association_start
        logger.info(f"✅ Created {associations_created} topic-post associations in {association_time:.2f}s")
        
        # Summary
        total_time = time.time() - start_time
        logger.info("=" * 70)
        logger.info("✅ TOPIC GENERATION COMPLETE")
        logger.info("=" * 70)
        logger.info(f"📊 Statistics:")
        logger.info(f"   - Date: {target_date}")
        logger.info(f"   - Topics created: {len(topic_names)}")
        logger.info(f"   - Posts processed: {len(assignments)}")
        logger.info(f"   - Outlier posts: {len(outlier_posts)}")
        logger.info(f"   - Associations: {associations_created}")
        if skipped_invalid_posts > 0:
            logger.info(f"   - Skipped (invalid): {skipped_invalid_posts}")
        logger.info(f"⏱️  Timing:")
        logger.info(f"   - Topic modeling: {modeling_time:.2f}s")
        logger.info(f"   - Storage: {storage_time:.2f}s")
        logger.info(f"   - Associations: {association_time:.2f}s")
        logger.info(f"   - Total: {total_time:.2f}s")
        logger.info("=" * 70)
        
        return {
            "success": True,
            "date": str(target_date),
            "topics_created": len(topic_names),
            "posts_processed": len(assignments),
            "outlier_posts": len(outlier_posts),
            "associations_created": associations_created,
            "timing": {
                "modeling": modeling_time,
                "storage": storage_time,
                "associations": association_time,
                "total": total_time
            }
        }


def main():
    """Main function to run topic generation."""
    # Parse date argument
    if len(sys.argv) > 1:
        try:
            target_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        except ValueError:
            logger.error("Invalid date format. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        # Use today by default
        target_date = date.today()
    
    logger.info("=" * 70)
    logger.info("INSIGHT TOPIC GENERATOR")
    logger.info("=" * 70)
    logger.info(f"Target date: {target_date}")
    logger.info("")
    
    # Get database URL
    db_url = ensure_database()
    
    # Initialize generator
    generator = TopicGenerator(db_url)
    
    # Setup
    logger.info("🔧 Setting up AI models...")
    if not generator.setup():
        logger.error("❌ Setup failed")
        sys.exit(1)
    
    logger.info("✅ Setup complete\n")
    
    # Fetch posts
    posts = generator.fetch_posts_by_date(target_date)
    
    if not posts:
        logger.error(f"❌ No posts found for {target_date}")
        logger.info("Run ingest.py first to fetch posts")
        sys.exit(1)
    
    # Generate topics
    result = generator.generate_topics_from_posts(posts, target_date)
    
    if not result["success"]:
        logger.error(f"❌ Topic generation failed: {result.get('error')}")
        sys.exit(1)
    
    logger.info("\n✅ All done!")


if __name__ == "__main__":
    main()

