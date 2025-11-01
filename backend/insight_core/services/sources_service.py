"""
Business logic for source management.
Handles CRUD operations for sources table.
"""
import psycopg
from typing import List, Dict, Any
from insight_core.db.repo_sources import SourcesRepository
from insight_core.logs.core.logger_config import get_component_logger

class SourcesService:
    """Manages sources (add, update, delete, list)."""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = SourcesRepository(db_url)
        self.logger = get_component_logger("sources_service")
    
    def get_all_sources(self) -> List[Dict[str, Any]]:
        """Get all sources from database."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_all_sources(cur)
    
    def get_enabled_sources(self) -> List[Dict[str, Any]]:
        """Get only enabled sources."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_enabled_sources(cur)
    
    def update_source_status(self, source_id: str, enabled: bool) -> Dict[str, Any]:
        """Enable or disable a source."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                success = self.repo.update_enabled(cur, source_id, enabled)
                conn.commit()
                
                if success:
                    self.logger.info(f"Source {source_id} → enabled={enabled}")
                    return {"source_id": source_id, "enabled": enabled}
                else:
                    raise ValueError(f"Source {source_id} not found")
    
    def add_source(self, platform: str, handle: str) -> Dict[str, Any]:
        """Add new source to database."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                source_id = self.repo.insert_source(cur, platform, handle)
                conn.commit()
                self.logger.info(f"Added source: {platform}/{handle}")
                return {"source_id": source_id, "platform": platform, "handle": handle}
    
    def delete_source(self, source_id: str) -> bool:
        """Delete source (and cascade delete its posts)."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                deleted = self.repo.delete_source(cur, source_id)
                conn.commit()
                if deleted:
                    self.logger.info(f"Deleted source: {source_id}")
                return deleted
    
    def get_sources_with_post_counts(self) -> List[Dict[str, Any]]:
        """Get all sources with their post counts."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_sources_with_post_counts(cur)