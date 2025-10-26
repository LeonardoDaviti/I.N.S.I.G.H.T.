# backend/scripts/ingest_daily.py
"""
Fetch posts from enabled sources and save to database.
Usage: python backend/insight_core/scripts/ingest.py
"""
import sys
from pathlib import Path
import json

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import asyncio
from datetime import date
from insight_core.db.ensure_db import ensure_database
from insight_core.db.repo_posts import PostsRepository
from insight_core.services.sources_service import SourcesService
from insight_core.connectors import create_connector
import psycopg
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

setup_logging(debug_mode=True)
logger = get_component_logger("ingest_posts")

async def ingest_posts():
    """Fetch and save posts from enabled sources."""

    # 0. Get database URL
    db_url = ensure_database()
    
    # 1. Get enabled sources from database
    sources_service = SourcesService(db_url)
    enabled_sources = sources_service.get_enabled_sources()

    logger.info(f"Enabled sources: {json.dumps(enabled_sources, indent=4)}")

    # 2. Group by platform
    by_platform = {}
    for source in enabled_sources:
        platform = source["platform"]
        if platform not in by_platform:
            by_platform[platform] = []
        by_platform[platform].append(source)
    
    logger.info(f"Sources by platform: {json.dumps(by_platform, indent=4)}")
    
    # 3. Fetch posts from each platform
    all_posts = []
    for platform, sources in by_platform.items():
        connector = create_connector(platform)
        connector.setup_connector()
        await connector.connect()
        logger.info(f"Connected to {platform} connector")
        for source in sources:
            posts = await connector.fetch_posts(source["handle_or_url"], limit=50)
            logger.info(f"Fetched {len(posts)} posts from {source['handle_or_url']}")
            # Attach source_id to each post
            for post in posts:
                post["_source_id"] = source["id"]
            all_posts.extend(posts)
        
        await connector.disconnect()
        logger.info(f"Disconnected from {platform} connector")
    
    # 4. Save to database
    repo = PostsRepository(db_url)
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for post in all_posts:
                source_id = post.pop("_source_id")
                repo.upsert_post(cur, post, source_id)
                logger.info(f"Saved post: {post['url']}")
        conn.commit()
        # logger.info(f"Saved {len(all_posts)} posts to database")
    
    logger.info(f"✅ Ingested {len(all_posts)} posts from {len(enabled_sources)} sources")

if __name__ == "__main__":
    asyncio.run(ingest_posts())