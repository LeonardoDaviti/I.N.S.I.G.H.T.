#!/usr/bin/env python3
"""
Test Suite for PostsRepository
Tests upsert_post, duplicate detection, and database operations.
"""

import sys
import os
from pathlib import Path
import asyncio
from datetime import date

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from psycopg import Cursor

from insight_core.connectors.rss_connector import RssConnector
from insight_core.connectors.telegram_connector import TelegramConnector
from insight_core.db.repo_posts import PostsRepository
from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

# Setup
setup_logging(debug_mode=True)
logger = get_component_logger("test_repo_posts")


class PostsRepositoryTestSuite:
    """Test suite for PostsRepository CRUD operations."""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = PostsRepository(db_url)
        self.test_results = {
            "passed": 0,
            "failed": 0,
            "errors": []
        }
    
    # ===============================
    # HELPER METHODS
    # ===============================
    
    def lookup_source_id(self, cur: Cursor, platform: str, handle: str) -> str:
        """
        Find source_id from sources table.
        Returns UUID string or raises if not found.
        """
        cur.execute(
            "SELECT id FROM sources WHERE platform = %s AND handle_or_url = %s",
            (platform, handle)
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Source not found: {platform}/{handle}. Run seed_sources.py!")
        return str(row[0])
    
    def assert_equal(self, actual, expected, test_name: str):
        """Simple assertion helper."""
        if actual == expected:
            logger.info(f"✓ {test_name}: PASSED")
            self.test_results["passed"] += 1
        else:
            error_msg = f"✗ {test_name}: FAILED - Expected {expected}, got {actual}"
            logger.error(error_msg)
            self.test_results["failed"] += 1
            self.test_results["errors"].append(error_msg)
    
    def assert_true(self, condition, test_name: str):
        """Assert condition is True."""
        self.assert_equal(condition, True, test_name)
    
    def assert_false(self, condition, test_name: str):
        """Assert condition is False."""
        self.assert_equal(condition, False, test_name)
    
    # ===============================
    # FETCH HELPERS
    # ===============================
    
    async def fetch_rss_post(self):
        """Fetch 1 RSS post from Simon Willison."""
        connector = RssConnector()
        connector.setup_connector()
        await connector.connect()
        posts = await connector.fetch_posts("https://simonwillison.net/atom/everything/", 1)
        await connector.disconnect()
        return posts[0] if posts else None
    
    async def fetch_telegram_post(self):
        """Fetch 1 Telegram post from durov channel."""
        connector = TelegramConnector()
        connector.setup_connector()
        await connector.connect()
        posts = await connector.fetch_posts("seeallochnaya", 1)
        await connector.disconnect()
        return posts[0] if posts else None
    
    # ===============================
    # TEST CASES
    # ===============================
    
    def test_1_upsert_rss_post(self, cur: Cursor, rss_post: dict, source_id: str):
        """Test inserting a new RSS post."""
        logger.info("\n[TEST 1] Upsert RSS Post (First Insert)")
        
        # Execute upsert
        post_id, was_inserted = self.repo.upsert_post(cur, rss_post, source_id)
        
        # Assertions
        self.assert_true(was_inserted, "RSS post should be inserted (first time)")
        self.assert_true(len(post_id) > 0, "Post ID should be non-empty UUID string")
        
        logger.info(f"   Post ID: {post_id}")
        logger.info(f"   URL: {rss_post['url'][:60]}...")
        
        return post_id
    
    def test_2_upsert_telegram_post(self, cur: Cursor, telegram_post: dict, source_id: str):
        """Test inserting a new Telegram post."""
        logger.info("\n[TEST 2] Upsert Telegram Post (First Insert)")
        
        post_id, was_inserted = self.repo.upsert_post(cur, telegram_post, source_id)
        
        self.assert_true(was_inserted, "Telegram post should be inserted (first time)")
        self.assert_true(len(post_id) > 0, "Post ID should be non-empty UUID string")
        
        logger.info(f"   Post ID: {post_id}")
        logger.info(f"   URL: {telegram_post['url'][:60]}...")
        
        return post_id
    
    def test_3_duplicate_detection_rss(self, cur: Cursor, rss_post: dict, source_id: str, original_post_id: str):
        """Test that re-inserting same RSS URL updates, not duplicates."""
        logger.info("\n[TEST 3] Duplicate Detection (RSS)")
        
        # Re-insert same post
        post_id, was_inserted = self.repo.upsert_post(cur, rss_post, source_id)
        
        # Should be update, not insert
        self.assert_false(was_inserted, "Should be UPDATE (not INSERT) on duplicate URL")
        self.assert_equal(post_id, original_post_id, "Post ID should remain the same")
        
        logger.info(f"   Post ID unchanged: {post_id}")
    
    def test_4_duplicate_detection_telegram(self, cur: Cursor, telegram_post: dict, source_id: str, original_post_id: str):
        """Test that re-inserting same Telegram URL updates, not duplicates."""
        logger.info("\n[TEST 4] Duplicate Detection (Telegram)")
        
        post_id, was_inserted = self.repo.upsert_post(cur, telegram_post, source_id)
        
        self.assert_false(was_inserted, "Should be UPDATE (not INSERT) on duplicate URL")
        self.assert_equal(post_id, original_post_id, "Post ID should remain the same")
        
        logger.info(f"   Post ID unchanged: {post_id}")
    
    def test_5_verify_in_database(self, cur: Cursor, post_id: str, expected_url: str):
        """Verify post exists in database with correct data."""
        logger.info(f"\n[TEST 5] Verify Post in Database: {post_id}")
        
        # Query database
        cur.execute(
            "SELECT url, content, media_urls, categories FROM posts WHERE id = %s",
            (post_id,)
        )
        row = cur.fetchone()
        
        # Assertions
        self.assert_true(row is not None, "Post should exist in database")
        
        if row:
            url, content, media_urls, categories = row
            self.assert_true(url == expected_url, "URL should match")
            self.assert_true(len(content) > 0, "Content should not be empty")
            self.assert_true(isinstance(media_urls, list), "media_urls should be list (JSONB)")
            self.assert_true(isinstance(categories, list), "categories should be list (JSONB)")
            
            logger.info(f"   ✓ URL: {url[:60]}...")
            logger.info(f"   ✓ Content length: {len(content)} chars")
            logger.info(f"   ✓ Media URLs: {len(media_urls)} items")
            logger.info(f"   ✓ Categories: {len(categories)} items")
    
    def test_6_count_posts(self, cur: Cursor, source_id: str):
        """Test counting posts for a specific source."""
        logger.info(f"\n[TEST 6] Count Posts for Source: {source_id}")
        
        # Count posts for this source
        cur.execute(
            "SELECT COUNT(*) FROM posts WHERE source_id = %s",
            (source_id,)
        )
        count = cur.fetchone()[0]
        
        self.assert_true(count >= 1, f"Should have at least 1 post for source (found {count})")
        logger.info(f"   ✓ Found {count} post(s) for this source")
        
        return count
    
    # ===============================
    # RUN ALL TESTS
    # ===============================
    
    async def run_all_tests(self):
        """Execute all test cases."""
        logger.info("=" * 70)
        logger.info("STARTING POSTS REPOSITORY TEST SUITE")
        logger.info("=" * 70)
        
        # Fetch test data
        logger.info("\n[SETUP] Fetching test posts from connectors...")
        rss_post = await self.fetch_rss_post()
        telegram_post = await self.fetch_telegram_post()
        
        if not rss_post:
            logger.error("✗ Failed to fetch RSS post")
            return
        if not telegram_post:
            logger.error("✗ Failed to fetch Telegram post")
            return
        
        logger.info(f"✓ Fetched RSS: {rss_post['url'][:60]}...")
        logger.info(f"✓ Fetched Telegram: {telegram_post['url'][:60]}...")
        
        # Run tests with database connection
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                
                # Lookup source IDs
                logger.info("\n[SETUP] Looking up source IDs...")
                try:
                    rss_source_id = "02c67c7e-82d2-49a7-9a3e-2325cfdca3e2"
                    telegram_source_id = "1998ddf8-aef3-4ff3-bf16-d7252f8e3c23"
                    logger.info(f"✓ RSS source ID: {rss_source_id}")
                    logger.info(f"✓ Telegram source ID: {telegram_source_id}")
                except ValueError as e:
                    logger.error(f"✗ {e}")
                    return
                
                # Test 1: Insert RSS
                rss_post_id = self.test_1_upsert_rss_post(cur, rss_post, rss_source_id)
                
                # Test 2: Insert Telegram
                telegram_post_id = self.test_2_upsert_telegram_post(cur, telegram_post, telegram_source_id)
                
                # Test 3: Duplicate RSS
                self.test_3_duplicate_detection_rss(cur, rss_post, rss_source_id, rss_post_id)
                
                # Test 4: Duplicate Telegram
                self.test_4_duplicate_detection_telegram(cur, telegram_post, telegram_source_id, telegram_post_id)
                
                # Test 5: Verify in DB
                self.test_5_verify_in_database(cur, rss_post_id, rss_post['url'])
                self.test_5_verify_in_database(cur, telegram_post_id, telegram_post['url'])
                
                # Test 6: Count posts
                self.test_6_count_posts(cur, rss_source_id)
                self.test_6_count_posts(cur, telegram_source_id)
                
                # Commit transaction
                conn.commit()
                logger.info("\n✓ All changes committed to database")
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print test results summary."""
        logger.info("\n" + "=" * 70)
        logger.info("TEST SUITE COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Passed: {self.test_results['passed']}")
        logger.info(f"Failed: {self.test_results['failed']}")
        
        if self.test_results['failed'] > 0:
            logger.error("\n✗ FAILURES:")
            for error in self.test_results['errors']:
                logger.error(f"  {error}")
        else:
            logger.info("\n✓ ALL TESTS PASSED!")
        
        logger.info("=" * 70)


async def main():
    """Entry point."""
    db_url = ensure_database()
    suite = PostsRepositoryTestSuite(db_url)
    await suite.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())