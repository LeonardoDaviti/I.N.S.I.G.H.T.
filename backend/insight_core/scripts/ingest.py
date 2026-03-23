# backend/scripts/ingest_daily.py
"""
Fetch posts from enabled sources and save to database.
Usage: python backend/insight_core/scripts/ingest.py
"""
import sys
from pathlib import Path
import json
import time

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import asyncio
from insight_core.db.ensure_db import ensure_database
from insight_core.db.repo_posts import PostsRepository
from insight_core.services.entity_memory_service import EntityMemoryService
from insight_core.services.event_memory_service import EventMemoryService
from insight_core.services.sources_service import SourcesService
from insight_core.services.operations_service import OperationsService
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.connectors import create_connector
import psycopg
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

DEBUG_MODE = True  # Set to False for production
setup_logging(debug_mode=DEBUG_MODE)
logger = get_component_logger("ingest_posts")

async def ingest_posts(trigger: str = "manual"):
    """Fetch and save posts from enabled sources with priority-based ordering."""
    
    # Start total timer
    total_start_time = time.time()
    platform_timings = {}

    # 0. Get database URL
    db_url = ensure_database()
    
    # 1. Get all sources with settings from database
    sources_service = SourcesService(db_url)
    operations_service = OperationsService(db_url)
    fetch_service = SourceFetchService(db_url)
    all_sources = sources_service.get_all_sources_with_settings()
    
    # Filter only enabled sources
    enabled_sources = [s for s in all_sources if s["enabled"]]
    
    if not enabled_sources:
        logger.warning("⚠️  No enabled sources found")
        return {
            "success": True,
            "posts_ingested": 0,
            "sources_ingested": 0,
        }

    logger.info(f"📊 Found {len(enabled_sources)} enabled sources")

    # 2. Group by platform and sort by priority within each platform
    by_platform = {}
    for source in enabled_sources:
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
    
    # 3. Fetch posts from each platform in priority order
    all_posts = []
    source_lookup = {source["id"]: source for source in enabled_sources}
    for platform, sources in by_platform.items():
        platform_start_time = time.time()

        connector = None
        if platform not in {"rss", "reddit", "youtube"}:
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
                if platform in {"rss", "reddit", "youtube"}:
                    posts = await fetch_service.fetch_live_posts(source, limit=max_posts)
                else:
                    posts = await connector.fetch_posts(source["handle_or_url"], limit=max_posts)
                logger.info(f"✅ [{priority}] {display_name}: fetched {len(posts)} posts")
                operations_service.record_source_status(
                    source["id"],
                    status="healthy",
                    message=f"Fetched {len(posts)} posts",
                    trigger=trigger,
                    fetched_posts=len(posts),
                )
                
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
                operations_service.record_source_status(
                    source["id"],
                    status="error",
                    message=str(e),
                    trigger=trigger,
                )
                continue
        
        if connector:
            await connector.disconnect()
            logger.info(f"🔌 Disconnected from {platform} connector")
        
        # Record platform timing
        platform_elapsed = time.time() - platform_start_time
        platform_timings[platform] = platform_elapsed
        
        if DEBUG_MODE:
            logger.debug(f"⏱️  {platform.upper()} completed in {platform_elapsed:.2f}s")
    
    # 4. Save to database
    db_start_time = time.time()
    repo = PostsRepository(db_url)
    memory_service = EntityMemoryService(db_url)
    event_service = EventMemoryService(db_url)
    per_source_fetch_counts = {}
    persisted_posts = []
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for post in all_posts:
                post_copy = dict(post)
                source_id = post_copy.pop("_source_id")
                per_source_fetch_counts[source_id] = per_source_fetch_counts.get(source_id, 0) + 1
                post_id, _ = repo.upsert_post(cur, post_copy, source_id)
                persisted_posts.append(
                    {
                        **post_copy,
                        "id": post_id,
                        "_source_id": source_id,
                    }
                )
        conn.commit()

    if persisted_posts:
        try:
            memory_service.process_posts(persisted_posts)
        except Exception as exc:
            logger.warning("Entity memory enrichment skipped: %s", exc)
        try:
            event_service.process_posts(persisted_posts)
        except Exception as exc:
            logger.warning("Event memory enrichment skipped: %s", exc)

    for source_id, fetched_posts in per_source_fetch_counts.items():
        source = source_lookup.get(source_id)
        if source and source["platform"] in {"rss", "reddit", "youtube"}:
            await fetch_service.record_live_fetch(source_id, source, fetched_posts=fetched_posts)
    
    db_elapsed = time.time() - db_start_time
    total_elapsed = time.time() - total_start_time
    
    logger.info(f"✅ Ingested {len(all_posts)} posts from {len(enabled_sources)} sources")
    
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

    return {
        "success": True,
        "posts_ingested": len(all_posts),
        "sources_ingested": len(enabled_sources),
    }

if __name__ == "__main__":
    asyncio.run(ingest_posts())
