import sys
import os
from pathlib import Path
import asyncio
from datetime import date

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.connectors.rss_connector import RssConnector
from insight_core.connectors.telegram_connector import TelegramConnector
from insight_core.db.repo_posts import PostsRepository
from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import setup_logging, get_component_logger
import json

# Setup
setup_logging(debug_mode=True)
logger = get_component_logger("test_persistence")

# Connect to DB
db_url = ensure_database()

class UpsertTest:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = PostsRepository(db_url)

    async def fetch_single_telegram_post(self):
        telegram_connector = TelegramConnector()
        telegram_connector.setup_connector()
        await telegram_connector.connect()
        posts = await telegram_connector.fetch_posts('@durov', 1)
        await telegram_connector.disconnect()
        return posts[0]

    async def upsert_post(self, post: dict):
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self.repo.upsert_post(cur, post, '1998ddf8-aef3-4ff3-bf16-d7252f8e3c23')
                conn.commit()

# test = UpsertTest(db_url)
# single_post = asyncio.run(test.fetch_single_telegram_post())
# asyncio.run(test.upsert_post(single_post))

        