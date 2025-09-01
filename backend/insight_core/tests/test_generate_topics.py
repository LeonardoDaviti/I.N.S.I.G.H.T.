"""
Test Topic Generation and Storage
==================================

Tests for the complete topic generation pipeline:
1. Fetch posts for a date
2. Generate topics using AI
3. Generate embeddings
4. Store topics in database
5. Store topic-post associations

Usage: python backend/insight_core/tests/test_generate_topics.py [YYYY-MM-DD]
"""

import sys
from pathlib import Path
from datetime import date, datetime

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import setup_logging, get_component_logger
from insight_core.scripts.generate_topics import TopicGenerator
from insight_core.services.topics_service import TopicsService

# Setup
setup_logging(debug_mode=True)
logger = get_component_logger("test_generate_topics")

# Connect to DB
db_url = ensure_database()


class GenerateTopicsTest:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.generator = TopicGenerator(db_url)
        self.topics_service = TopicsService(db_url)
        
    def test_setup(self):
        """Test 1: Setup AI processor"""
        logger.info("\n--- Test 1: Setup ---")
        success = self.generator.setup()
        
        if success:
            logger.info("✅ Setup successful")
        else:
            logger.error("❌ Setup failed")
            
        assert success, "Failed to setup generator"
        return success
    
    def test_fetch_posts(self, target_date: date):
        """Test 2: Fetch posts for the target date"""
        logger.info(f"\n--- Test 2: Fetch Posts for {target_date} ---")
        
        posts = self.generator.fetch_posts_by_date(target_date)
        
        if not posts:
            logger.warning(f"⚠️  No posts found for {target_date}")
            logger.info("You can run the ingest script to add posts:")
            logger.info("  python backend/insight_core/scripts/ingest.py")
            return None
        
        logger.info(f"✅ Retrieved {len(posts)} posts")
        
        # Display sample posts
        logger.info("\n📄 Sample posts:")
        for i, post in enumerate(posts[:3]):
            title = post.get('title', 'No Title')
            content_preview = post.get('content', '')[:100]
            logger.info(f"   {i+1}. {title}")
            logger.info(f"      {content_preview}...")
        
        return posts
    
    def test_topic_generation(self, posts: list, target_date: date):
        """Test 3: Generate topics and store in database"""
        logger.info(f"\n--- Test 3: Topic Generation for {target_date} ---")
        
        # Check if topics already exist
        exists = self.topics_service.topics_exist_for_date(target_date)
        if exists:
            logger.warning(f"⚠️  Topics already exist for {target_date}")
            logger.info("Skipping generation. To regenerate, delete existing topics first.")
            
            # Fetch and display existing topics
            topics = self.topics_service.get_topics_by_date(target_date)
            logger.info(f"\n📚 Existing topics ({len(topics)}):")
            for topic in topics:
                logger.info(f"   - {topic['title']} (outlier={topic['is_outlier']})")
            
            return {
                "success": True,
                "message": "Topics already exist",
                "topics_created": len(topics)
            }
        
        # Generate topics
        logger.info(f"🤖 Generating topics for {len(posts)} posts...")
        logger.info("   (This may take 30-60 seconds)")
        
        result = self.generator.generate_topics_from_posts(posts, target_date)
        
        assert result["success"], f"Topic generation failed: {result.get('error')}"
        
        logger.info("\n✅ Topic generation completed successfully!")
        
        return result
    
    def test_verify_storage(self, target_date: date):
        """Test 4: Verify topics are stored correctly"""
        logger.info(f"\n--- Test 4: Verify Storage ---")
        
        # Fetch topics
        topics = self.topics_service.get_topics_by_date(target_date)
        
        assert len(topics) > 0, "No topics found in database"
        logger.info(f"✅ Found {len(topics)} topics in database")
        
        # Display topics
        logger.info("\n📚 Stored Topics:")
        for topic in topics:
            logger.info(f"   - {topic['title']}")
            logger.info(f"     ID: {topic['id']}")
            logger.info(f"     Outlier: {topic['is_outlier']}")
            logger.info(f"     Created: {topic['created_at']}")
            
            # Fetch posts for this topic
            posts = self.topics_service.get_posts_for_topic(topic['id'])
            logger.info(f"     Posts: {len(posts)}")
            
            # Display sample posts
            for i, post in enumerate(posts[:2]):
                title = post.get('title', 'No Title')
                logger.info(f"       {i+1}. {title}...")
            
            if len(posts) > 2:
                logger.info(f"       ... and {len(posts) - 2} more")
            
            logger.info("")
        
        return topics
    
    def run_all_tests(self, target_date: date):
        """Run all tests sequentially"""
        logger.info("=" * 70)
        logger.info("TESTING: Topic Generation and Storage")
        logger.info("=" * 70)
        logger.info(f"Target date: {target_date}\n")
        
        # Test 1: Setup
        self.test_setup()
        
        # Test 2: Fetch posts
        posts = self.test_fetch_posts(target_date)
        if not posts:
            logger.warning("\n⚠️  No posts available for testing")
            logger.info("Please run ingest.py first to add posts")
            return False
        
        # Test 3: Generate topics
        result = self.test_topic_generation(posts, target_date)
        
        # Test 4: Verify storage
        topics = self.test_verify_storage(target_date)
        
        # Final summary
        logger.info("=" * 70)
        logger.info("✅ ALL TESTS PASSED!")
        logger.info("=" * 70)
        logger.info(f"Summary:")
        logger.info(f"  - Date: {target_date}")
        logger.info(f"  - Posts: {len(posts)}")
        logger.info(f"  - Topics: {len(topics)}")
        logger.info("=" * 70)
        
        return True


def main():
    """Main test runner"""
    # Parse date argument
    if len(sys.argv) > 1:
        try:
            target_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        except ValueError:
            logger.error("Invalid date format. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        # Use a recent date for testing (adjust as needed)
        target_date = date(2025, 11, 13)
        logger.info(f"No date provided, using default: {target_date}")
    
    test = GenerateTopicsTest(db_url)
    
    try:
        test.run_all_tests(target_date)
    except AssertionError as e:
        logger.error(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"\n❌ UNEXPECTED ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

