"""
Business logic layer for posts operations.
Coordinates between API and database repository.
"""
from functools import lru_cache
from typing import Dict, Any

from insight_core.db import database as db

from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_posts import PostsRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.utils.stamps import BODIES, fingerprint

STORED_BODIES_KEY = "stored_bodies"


@lru_cache(maxsize=1)
def stored_bodies_stamp() -> str:
    """The reader rule the stored bodies were brought up to (issue 0068: 0063's link labels): what the
    repair makes of the sample's bodies (utils/stamps.py, issue 0071), which it reads and how it leaves them."""
    from insight_core.ingestion.kinds.parsing import HIDDEN_HINT_RE, _without_hidden_link_labels, strip_html

    return fingerprint([(bool(HIDDEN_HINT_RE.search(body)), _without_hidden_link_labels(body),
                         strip_html(_without_hidden_link_labels(body))) for body in BODIES])


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
        0068), as search's refill does for its index (0042): `stored_bodies` holds the stamp of the
        rule the stored bodies are at (stored_bodies_stamp), and the repair reads only what was
        stored, nothing fetched: the screen-reader labels inside links (0063) go. Returns how many
        posts changed."""
        with db.transaction(self.db_url) as cur:
            done = (SystemSettingsRepository.get(cur, STORED_BODIES_KEY) or ({}, None))[0] or {}
            if done.get("rules") == stored_bodies_stamp():
                return 0
            changed = self.repo.drop_hidden_link_labels(cur)
            SystemSettingsRepository.upsert(cur, STORED_BODIES_KEY, {"rules": stored_bodies_stamp(), "changed": changed})
        return changed
