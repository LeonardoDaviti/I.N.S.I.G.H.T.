"""Posts: storage stats and the one-off repair of stored bodies to the current reader rule."""
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
    """The stamp of the reader rule for stored bodies: what the repair makes of utils/stamps.py's sample bodies."""
    from insight_core.ingestion.kinds.parsing import HIDDEN_HINT_RE, _without_hidden_link_labels, strip_html

    return fingerprint([(bool(HIDDEN_HINT_RE.search(body)), _without_hidden_link_labels(body),
                         strip_html(_without_hidden_link_labels(body))) for body in BODIES])


class PostsService:
    """Post storage stats. Listing posts is reader_service's job."""

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
        """Bring stored bodies up to the current reader rule once (`stored_bodies` holds the stamp they are at),
        from what is stored, nothing fetched. Returns how many posts changed."""
        with db.transaction(self.db_url) as cur:
            done = (SystemSettingsRepository.get(cur, STORED_BODIES_KEY) or ({}, None))[0] or {}
            if done.get("rules") == stored_bodies_stamp():
                return 0
            changed = self.repo.drop_hidden_link_labels(cur)
            SystemSettingsRepository.upsert(cur, STORED_BODIES_KEY, {"rules": stored_bodies_stamp(), "changed": changed})
        return changed
