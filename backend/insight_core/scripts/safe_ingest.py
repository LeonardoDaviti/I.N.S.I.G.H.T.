# backend/insight_core/scripts/safe_ingest.py
"""
Safe ingestion script that only fetches from sources that need updating.

Filtering Logic:
- Sources with 0 posts (newly added) → FETCH
- Sources with latest post older than 24h → FETCH  
- Sources with recent posts (< 24h) → SKIP

This prevents redundant fetching during development iterations.

Usage: python backend/insight_core/scripts/safe_ingest.py
"""
import sys
from pathlib import Path
import time
from datetime import datetime, timedelta, timezone

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import asyncio
import psycopg
from psycopg import Cursor
from insight_core.db.ensure_db import ensure_database
from insight_core.db.repo_posts import PostsRepository
from insight_core.services.sources_service import SourcesService
from insight_core.connectors import create_connector
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

DEBUG_MODE = True  # Set to False for production
setup_logging(debug_mode=DEBUG_MODE)
logger = get_component_logger("safe_ingest")

# Configuration
SKIP_THRESHOLD_HOURS = 24


def get_source_post_stats(cur: Cursor, source_id: str) -> tuple[int, datetime | None]:
    """
    Get post count and latest fetch time for a source.
    
    Returns:
        (post_count, latest_fetched_at)
    """
    query = """
        SELECT 
            COUNT(*) as post_count,
            MAX(fetched_at) as latest_fetched_at
        FROM posts
        WHERE source_id = %s
    """
    cur.execute(query, (source_id,))
    row = cur.fetchone()
    
    post_count = row[0] if row else 0
    latest_fetched_at = row[1] if row and row[1] else None
    
    return post_count, latest_fetched_at


def should_fetch_source(cur: Cursor, source: dict) -> tuple[bool, str]:
    """
    Determine if a source should be fetched based on post history.
    
    Returns:
        (should_fetch: bool, reason: str)
    """
    source_id = source["id"]
    display_name = source["settings"].get("display_name") or source["handle_or_url"]
    
    post_count, latest_fetched_at = get_source_post_stats(cur, source_id)
    
    # Case 1: No posts yet (newly added source)
    if post_count == 0:
        return True, "📦 New source (0 posts)"
    
    # Case 2: Has posts, check freshness
    if latest_fetched_at:
        now = datetime.now(timezone.utc)
        time_since_fetch = now - latest_fetched_at
        hours_since_fetch = time_since_fetch.total_seconds() / 3600
        
        if hours_since_fetch < SKIP_THRESHOLD_HOURS:
            return False, f"⏭️  Recently fetched {hours_since_fetch:.1f}h ago ({post_count} posts)"
        else:
            return True, f"🔄 Stale data ({hours_since_fetch:.1f}h old, {post_count} posts)"
    
    # Case 3: Has posts but no fetched_at (shouldn't happen, but safe fallback)
    return True, f"⚠️  Unknown fetch time ({post_count} posts)"


async def safe_ingest_posts():
    """Fetch and save posts only from sources that need updating."""
    
    # Start total timer
    total_start_time = time.time()
    platform_timings = {}

    # 0. Get database URL
    db_url = ensure_database()
    
    # 1. Get all sources with settings from database
    sources_service = SourcesService(db_url)
    all_sources = sources_service.get_all_sources_with_settings()
    
    # Filter only enabled sources
    enabled_sources = [s for s in all_sources if s["enabled"]]
    
    if not enabled_sources:
        logger.warning("⚠️  No enabled sources found")
        return

    logger.info(f"📊 Found {len(enabled_sources)} enabled sources")
    
    # 2. Filter sources based on fetch history
    sources_to_fetch = []
    sources_to_skip = []
    
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for source in enabled_sources:
                should_fetch, reason = should_fetch_source(cur, source)
                display_name = source["settings"].get("display_name") or source["handle_or_url"]
                
                if should_fetch:
                    sources_to_fetch.append(source)
                    logger.info(f"✅ {display_name}: {reason}")
                else:
                    sources_to_skip.append(source)
                    logger.info(f"⏭️  {display_name}: {reason}")
    
    # 3. Summary
    logger.info("=" * 60)
    logger.info(f"📥 Sources to fetch: {len(sources_to_fetch)}")
    logger.info(f"⏭️  Sources to skip:  {len(sources_to_skip)}")
    logger.info("=" * 60)
    
    if not sources_to_fetch:
        logger.info("✨ All sources are up to date! Nothing to fetch.")
        return
    
    # 4. Group by platform and sort by priority within each platform
    by_platform = {}
    for source in sources_to_fetch:
        platform = source["platform"]
        if platform not in by_platform:
            by_platform[platform] = []
        by_platform[platform].append(source)
    
    # Sort sources within each platform by priority (lower = first)
    for platform in by_platform:
        by_platform[platform].sort(key=lambda s: (
            s["settings"]["priority"],
            s["handle_or_url"]
        ))
    
    # Log priority order for each platform
    for platform, sources in by_platform.items():
        priority_info = [
            f"[{s['settings']['priority']}] {s['settings'].get('display_name') or s['handle_or_url']}"
            for s in sources
        ]
        logger.info(f"📋 {platform.upper()} priority order: {' → '.join(priority_info)}")
    
    # 5. Fetch posts from each platform in priority order
    all_posts = []
    for platform, sources in by_platform.items():
        platform_start_time = time.time()
        
        connector = create_connector(platform)
        connector.setup_connector()
        await connector.connect()
        logger.info(f"🔌 Connected to {platform} connector")
        
        for idx, source in enumerate(sources):
            try:
                # Get source-specific settings
                max_posts = source["settings"]["max_posts_per_fetch"]
                fetch_delay = source["settings"]["fetch_delay_seconds"]
                display_name = source["settings"].get("display_name") or source["handle_or_url"]
                priority = source["settings"]["priority"]
                
                # Fetch posts with custom limit
                logger.info(f"📥 [{priority}] Fetching up to {max_posts} posts from {display_name}")
                posts = await connector.fetch_posts(source["handle_or_url"], limit=max_posts)
                logger.info(f"✅ [{priority}] {display_name}: fetched {len(posts)} posts")
                
                # Attach source_id to each post
                for post in posts:
                    post["_source_id"] = source["id"]
                all_posts.extend(posts)
                
                # Apply delay AFTER fetching (except for last source in platform)
                if idx < len(sources) - 1:
                    logger.info(f"⏳ Waiting {fetch_delay}s before next source...")
                    await asyncio.sleep(fetch_delay)
                    
            except Exception as e:
                # Log error but continue with remaining sources
                logger.error(f"❌ Failed to fetch from {source['handle_or_url']}: {e}")
                continue
        
        await connector.disconnect()
        logger.info(f"🔌 Disconnected from {platform} connector")
        
        # Record platform timing
        platform_elapsed = time.time() - platform_start_time
        platform_timings[platform] = platform_elapsed
        
        if DEBUG_MODE:
            logger.debug(f"⏱️  {platform.upper()} completed in {platform_elapsed:.2f}s")
    
    # 6. Save to database
    db_start_time = time.time()
    repo = PostsRepository(db_url)
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for post in all_posts:
                source_id = post.pop("_source_id")
                repo.upsert_post(cur, post, source_id)
                logger.info(f"Saved post: {post['url']}")
        conn.commit()
    
    db_elapsed = time.time() - db_start_time
    total_elapsed = time.time() - total_start_time
    
    logger.info(f"✅ Ingested {len(all_posts)} posts from {len(sources_to_fetch)} sources")
    
    # Log timing summary (only in debug mode)
    if DEBUG_MODE:
        logger.debug("=" * 60)
        logger.debug("⏱️  TIMING SUMMARY")
        logger.debug("=" * 60)
        
        # Per-platform timings
        for platform, elapsed in platform_timings.items():
            source_count = len(by_platform[platform])
            logger.debug(f"  {platform.upper():12s} : {elapsed:6.2f}s ({source_count} sources)")
        
        logger.debug("-" * 60)
        logger.debug(f"  {'DATABASE':12s} : {db_elapsed:6.2f}s ({len(all_posts)} posts)")
        logger.debug("-" * 60)
        logger.debug(f"  {'TOTAL':12s} : {total_elapsed:6.2f}s")
        logger.debug("=" * 60)


if __name__ == "__main__":
    asyncio.run(safe_ingest_posts())


