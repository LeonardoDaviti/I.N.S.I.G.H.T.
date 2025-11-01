import sys
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from insight_core.db.repo_posts import PostsRepository
from insight_core.services.posts_service import PostsService
from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

# Setup
setup_logging(debug_mode=True)
logger = get_component_logger("test_posts_by_source")

# Connect to DB
db_url = ensure_database()

class PostsBySourceTest:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = PostsRepository(db_url)
        self.service = PostsService(db_url)

    def get_first_source_id(self):
        """Get a source ID from the database for testing"""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM sources LIMIT 1")
                row = cur.fetchone()
                if row:
                    return str(row[0])
                else:
                    logger.error("No sources found in database. Please add sources first.")
                    return None

    def test_repo(self, source_id: str):
        """Test repository layer"""
        logger.info(f"Testing repo.get_posts_by_source({source_id})")
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                posts = self.repo.get_posts_by_source(cur, source_id)
                logger.info(f"✅ Retrieved {len(posts)} posts from repository")
                if posts:
                    logger.info(f"Sample post title: {posts[0].get('title', 'No title')}")
                    logger.info(f"Sample post platform: {posts[0].get('platform', 'Unknown')}")
                    logger.info(f"Sample post source: {posts[0].get('handle_or_url', 'Unknown')}")
                return posts
    
    def test_service(self, source_id: str):
        """Test service layer"""
        logger.info(f"Testing service.get_posts_by_source({source_id})")
        posts = self.service.get_posts_by_source(source_id)
        logger.info(f"✅ Retrieved {len(posts)} posts from service")
        return posts

# Run test
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("TESTING: Posts by Source Feature")
    logger.info("=" * 60)
    
    test = PostsBySourceTest(db_url)
    
    # Get a test source ID
    test_source_id = test.get_first_source_id()
    
    if test_source_id:
        logger.info(f"\n🧪 Using test source_id: {test_source_id}\n")
        
        # Test repository
        logger.info("--- Test 1: Repository Layer ---")
        posts = test.test_repo(test_source_id)
        
        # Test service
        logger.info("\n--- Test 2: Service Layer ---")
        posts = test.test_service(test_source_id)
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ ALL TESTS PASSED!")
        logger.info("=" * 60)
    else:
        logger.error("\n❌ Cannot run tests without a source in the database")
        logger.info("Please add sources using the frontend or seed_sources.py")

