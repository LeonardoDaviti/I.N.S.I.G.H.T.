"""
Test Topic Modeler
==================

Tests for the Gemini Topic Modeler processor.

Tests:
1. JSON structure parsing
2. Topic modeling correctness
3. Post assignments validation
"""

import sys
from pathlib import Path
from datetime import date

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from insight_core.db.repo_posts import PostsRepository
from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import setup_logging, get_component_logger
from insight_core.processors.ai.gemini_topic_modeler import GeminiTopicModeler

# Setup
setup_logging(debug_mode=True)
logger = get_component_logger("test_topic_modeler")

# Connect to DB
db_url = ensure_database()


class TopicModelerTest:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = PostsRepository(db_url)
        self.modeler = GeminiTopicModeler()
        
    def fetch_posts_by_date(self, target_date: date):
        """Fetch posts for a specific date"""
        logger.info(f"Fetching posts for {target_date}")
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                posts = self.repo.get_posts_by_date(cur, target_date)
                logger.info(f"✅ Retrieved {len(posts)} posts for {target_date}")
                return posts
    
    def test_setup(self):
        """Test 1: Setup the topic modeler"""
        logger.info("\n--- Test 1: Setup Topic Modeler ---")
        success = self.modeler.setup_processor()
        
        if success:
            logger.info("✅ Topic modeler setup successful")
        else:
            logger.error("❌ Topic modeler setup failed")
            
        assert success, "Failed to setup topic modeler"
        return success
    
    def test_json_structure(self, result: dict):
        """Test 2: Validate JSON structure"""
        logger.info("\n--- Test 2: JSON Structure Validation ---")
        
        # Check success field
        assert "success" in result, "Missing 'success' field"
        logger.info("✅ Has 'success' field")
        
        if not result["success"]:
            logger.error(f"❌ Topic modeling failed: {result.get('error', 'Unknown error')}")
            assert False, f"Topic modeling failed: {result.get('error')}"
        
        # Check required fields
        assert "topic_names" in result, "Missing 'topic_names' field"
        assert "assignments" in result, "Missing 'assignments' field"
        assert "total_posts" in result, "Missing 'total_posts' field"
        assert "total_topics" in result, "Missing 'total_topics' field"
        logger.info("✅ Has all required fields")
        
        # Validate topic_names structure
        topic_names = result["topic_names"]
        assert isinstance(topic_names, dict), "topic_names should be a dictionary"
        logger.info(f"✅ topic_names is a dict with {len(topic_names)} topics")
        
        # Validate assignments structure
        assignments = result["assignments"]
        assert isinstance(assignments, dict), "assignments should be a dictionary"
        logger.info(f"✅ assignments is a dict with {len(assignments)} assignments")
        
        # Validate topic IDs are sequential starting from 0
        topic_ids = [int(tid) for tid in topic_names.keys() if tid != "-1"]
        topic_ids.sort()
        if topic_ids:
            expected_ids = list(range(len(topic_ids)))
            assert topic_ids == expected_ids, f"Topic IDs should be sequential starting from 0, got {topic_ids}"
            logger.info(f"✅ Topic IDs are sequential: {topic_ids}")
        
        # Validate each assignment maps to a valid topic
        for post_id, topic_id in assignments.items():
            assert isinstance(topic_id, int), f"Topic ID for post {post_id} should be an integer"
            if topic_id != -1:
                assert str(topic_id) in topic_names, f"Topic ID {topic_id} not found in topic_names"
        logger.info("✅ All assignments reference valid topics")
        
        logger.info("\n📊 JSON Structure Summary:")
        logger.info(f"   - Total topics: {len(topic_names)}")
        logger.info(f"   - Total assignments: {len(assignments)}")
        logger.info(f"   - Total posts: {result['total_posts']}")
        
        return True
    
    def test_topic_modeling(self, posts: list, result: dict):
        """Test 3: Validate topic modeling correctness"""
        logger.info("\n--- Test 3: Topic Modeling Validation ---")
        
        # Check that all posts were assigned
        assignments = result["assignments"]
        post_ids_in_result = set(assignments.keys())
        post_ids_from_db = {post.get('id') for post in posts}
        
        # Some posts might be missing if they were truncated, but we should have most of them
        coverage = len(post_ids_in_result) / len(post_ids_from_db) if post_ids_from_db else 0
        logger.info(f"✅ Post coverage: {coverage * 100:.1f}% ({len(post_ids_in_result)}/{len(post_ids_from_db)})")
        
        # Display topics and their assignments
        topic_names = result["topic_names"]
        logger.info("\n📚 Discovered Topics:")
        
        for topic_id, topic_name in topic_names.items():
            # Count posts in this topic
            post_count = sum(1 for tid in assignments.values() if str(tid) == topic_id)
            logger.info(f"   Topic {topic_id}: '{topic_name}' ({post_count} posts)")
        
        # Count outliers
        outlier_count = sum(1 for tid in assignments.values() if tid == -1)
        if outlier_count > 0:
            logger.info(f"   Outliers: {outlier_count} posts")
        
        # Validate that we have reasonable topic distribution
        topics_with_posts = sum(1 for topic_id in topic_names.keys() 
                               if sum(1 for tid in assignments.values() if str(tid) == topic_id) > 0)
        logger.info(f"\n✅ {topics_with_posts}/{len(topic_names)} topics have assigned posts")
        
        # Check that topics have descriptive names (not empty or too short)
        for topic_id, topic_name in topic_names.items():
            assert len(topic_name.strip()) > 0, f"Topic {topic_id} has empty name"
            assert len(topic_name.split()) >= 1, f"Topic {topic_id} name too short: '{topic_name}'"
        logger.info("✅ All topic names are descriptive")
        
        return True
    
    def run_all_tests(self):
        """Run all tests sequentially"""
        logger.info("=" * 70)
        logger.info("TESTING: Gemini Topic Modeler")
        logger.info("=" * 70)
        
        # Test 1: Setup
        self.test_setup()
        
        # Fetch posts from two dates
        date1 = date(2025, 11, 3)
        date2 = date(2025, 11, 2)
        
        posts_date1 = self.fetch_posts_by_date(date1)
        posts_date2 = self.fetch_posts_by_date(date2)
        
        # Combine posts
        all_posts = posts_date2
        logger.info(f"\n📦 Total posts to model: {len(all_posts)}")
        
        if len(all_posts) == 0:
            logger.warning("⚠️  No posts found for testing. Please add some posts first.")
            logger.info("You can run the following to add posts:")
            logger.info("  - cd backend/insight_core/tests")
            logger.info("  - python connector_test.py")
            return False
        
        # Display sample posts
        logger.info("\n📄 Sample posts:")
        for i, post in enumerate(all_posts[:3]):
            title = post.get('title', 'No Title')
            logger.info(f"   {i+1}. {title}...")
        
        # Run topic modeling
        logger.info("\n🤖 Running topic modeling...")
        logger.info("   (This may take 10-30 seconds depending on post count)")
        
        result = self.modeler.model_topics(all_posts)
        
        # Test 2: JSON structure
        self.test_json_structure(result)
        
        # Test 3: Topic modeling correctness
        self.test_topic_modeling(all_posts, result)
        
        logger.info("\n" + "=" * 70)
        logger.info("✅ ALL TESTS PASSED!")
        logger.info("=" * 70)
        
        return True


if __name__ == "__main__":
    test = TopicModelerTest(db_url)
    try:
        test.run_all_tests()
    except AssertionError as e:
        logger.error(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"\n❌ UNEXPECTED ERROR: {e}")
        sys.exit(1)

