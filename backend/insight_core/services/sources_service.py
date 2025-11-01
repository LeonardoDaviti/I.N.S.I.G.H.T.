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
    
    def get_source_with_settings(self, source_id: str) -> Dict[str, Any]:
        """Get source with merged settings (platform defaults + overrides)."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                # Get source basic info
                sources = self.repo.get_all_sources(cur)
                source = next((s for s in sources if s["id"] == source_id), None)
                
                if not source:
                    raise ValueError(f"Source {source_id} not found")
                
                # Get merged settings
                settings = self.repo.get_source_settings(cur, source_id)
                
                return {
                    **source,
                    "settings": settings
                }
    
    def get_all_sources_with_settings(self) -> List[Dict[str, Any]]:
        """Get all sources with their merged settings and post counts."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                sources_with_counts = self.repo.get_sources_with_post_counts(cur)
                
                # Add settings to each source
                for source in sources_with_counts:
                    source["settings"] = self.repo.get_source_settings(cur, source["id"])
                
                return sources_with_counts
    
    def update_source_settings(self, source_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update settings for a source.
        Validates settings before updating.
        """
        # Validate settings
        valid_keys = {"display_name", "fetch_delay_seconds", "priority", "max_posts_per_fetch"}
        validated_settings = {k: v for k, v in settings.items() if k in valid_keys}
        
        # Type validation
        if "fetch_delay_seconds" in validated_settings:
            validated_settings["fetch_delay_seconds"] = int(validated_settings["fetch_delay_seconds"])
        if "priority" in validated_settings:
            validated_settings["priority"] = int(validated_settings["priority"])
        if "max_posts_per_fetch" in validated_settings:
            validated_settings["max_posts_per_fetch"] = int(validated_settings["max_posts_per_fetch"])
        
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                success = self.repo.update_source_settings(cur, source_id, validated_settings)
                conn.commit()
                
                if success:
                    self.logger.info(f"Updated settings for source {source_id}")
                    return {
                        "source_id": source_id,
                        "settings": validated_settings
                    }
                else:
                    raise ValueError(f"Source {source_id} not found")