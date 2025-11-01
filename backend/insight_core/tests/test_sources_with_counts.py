import sys
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from insight_core.db.repo_sources import SourcesRepository
from insight_core.services.sources_service import SourcesService
from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

# Setup
setup_logging(debug_mode=True)
logger = get_component_logger("test_sources_with_counts")

# Connect to DB
db_url = ensure_database()

class SourcesWithCountsTest:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = SourcesRepository(db_url)
        self.service = SourcesService(db_url)

    def test_repo(self):
        """Test repository layer"""
        logger.info("Testing repo.get_sources_with_post_counts()")
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                sources = self.repo.get_sources_with_post_counts(cur)
                logger.info(f"✅ Retrieved {len(sources)} sources from repository")
                
                # Display results
                if sources:
                    logger.info("\nSources with post counts:")
                    for source in sources:
                        logger.info(f"  - {source['platform']}/{source['handle_or_url']}: {source['post_count']} posts")
                    
                    # Calculate total
                    total_posts = sum(s['post_count'] for s in sources)
                    logger.info(f"\nTotal posts across all sources: {total_posts}")
                else:
                    logger.warning("No sources found in database")
                
                return sources
    
    def test_service(self):
        """Test service layer"""
        logger.info("\nTesting service.get_sources_with_post_counts()")
        sources = self.service.get_sources_with_post_counts()
        logger.info(f"✅ Retrieved {len(sources)} sources from service")
        return sources

# Run test
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("TESTING: Sources with Post Counts Feature")
    logger.info("=" * 60)
    
    test = SourcesWithCountsTest(db_url)
    
    # Test repository
    logger.info("\n--- Test 1: Repository Layer ---")
    sources = test.test_repo()
    
    # Test service
    logger.info("\n--- Test 2: Service Layer ---")
    sources = test.test_service()
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ ALL TESTS PASSED!")
    logger.info("=" * 60)
    
    if not sources:
        logger.info("\n⚠️  Note: No sources in database")
        logger.info("Add sources using the frontend or seed_sources.py")

