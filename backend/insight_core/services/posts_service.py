"""
Business logic layer for posts operations.
Coordinates between API and database repository.
"""
from typing import Dict, Any

from insight_core.db import database as db

from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_posts import PostsRepository
from insight_core.logs.core.logger_config import get_component_logger

# The reader rule the stored bodies were brought up to (issue 0068): 1, 0063's link labels.
STORED_BODIES_KEY = "stored_bodies"
STORED_BODIES_VERSION = 1


class PostsService:
    """
    Post storage stats. Listing posts is the reader's job (reader_service).
    """

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = PostsRepository(db_url)
        self.logger = get_component_logger("posts_service")

    def get_source_post_stats(self, source_id: str) -> Dict[str, Any]:
        """Get aggregate storage stats for a source."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_source_post_stats(cur, source_id)

    def catch_up_stored_bodies(self) -> int:
        """Bring the bodies stored before a reader rule up to it, once, in the background (issue
        0068), as search's refill does for its index (0042): `stored_bodies` holds the version the
        stored bodies are at, and each version's repair reads only what was stored, nothing
        fetched. Version 1: the screen-reader labels inside links (0063) go. Returns how many
        posts changed."""
        with db.transaction(self.db_url) as cur:
            done = (SystemSettingsRepository.get(cur, STORED_BODIES_KEY) or ({}, None))[0] or {}
            if done.get("version", 0) >= STORED_BODIES_VERSION:
                return 0
            changed = self.repo.drop_hidden_link_labels(cur)
            SystemSettingsRepository.upsert(cur, STORED_BODIES_KEY, {"version": STORED_BODIES_VERSION, "changed": changed})
        return changed
