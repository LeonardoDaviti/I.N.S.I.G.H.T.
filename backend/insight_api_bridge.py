# backend/insight_api_bridge.py
from insight_core.db.ensure_db import ensure_database
from insight_core.services.sources_service import SourcesService
# from insight_core.services.posts_service import PostsService
# from insight_core.services.briefing_service import BriefingService

from typing import List, Dict, Any


class InsightApiBridge:
    def __init__(self):
        self.db = ensure_database()

        self.sources_service = SourcesService(self.db)
        # self.posts_service = PostsService(self.db)


    # ============= SOURCES MANAGEMENT =============

    def get_all_sources(self) -> List[Dict[str, Any]]:
        """Get all sources from database."""
        return self.sources_service.get_all_sources()
    
    def get_enabled_sources(self) -> List[Dict[str, Any]]:
        """Get only enabled sources."""
        return self.sources_service.get_enabled_sources()

    def update_source(self, source_id: str, enabled: bool) -> Dict[str, Any]:
        """Enable/disable a source."""
        return self.sources_service.update_source_status(source_id, enabled)
    
    def add_source(self, platform: str, handle: str) -> Dict[str, Any]:
        """Add new source to database."""
        return self.sources_service.add_source(platform, handle)
    
    def delete_source(self, source_id: str) -> bool:
        """Remove source from database."""
        return self.sources_service.delete_source(source_id)

    # ============= POSTS RETRIEVAL =============
    
    def get_posts_for_date(self, date: str) -> Dict[str, Any]:
        """
        Get posts for a date (cache-first).
        If not in DB → fetch from sources → save → return.
        """
        # return self.posts_service.get_posts_for_date(date)
        pass
