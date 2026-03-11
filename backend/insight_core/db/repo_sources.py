"""
Repository for sources table operations.
Handles all SQL queries for source management.
"""
import json
import psycopg
from psycopg import Cursor
from datetime import date, datetime
from typing import List, Dict, Any, Optional
from insight_core.logs.core.logger_config import get_component_logger

class SourcesRepository:
    """Database access layer for sources table."""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("repo_sources")
    
    def get_all_sources(self, cur: Cursor) -> List[Dict[str, Any]]:
        """Get all sources."""
        query = """
            SELECT id, platform, handle_or_url, enabled, created_at, updated_at
            FROM sources
            ORDER BY platform, handle_or_url
        """
        cur.execute(query)
        rows = cur.fetchall()
        
        sources = []
        for row in rows:
            sources.append({
                "id": str(row[0]),
                "platform": row[1],
                "handle_or_url": row[2],
                "enabled": row[3],
                "created_at": row[4],
                "updated_at": row[5]
            })
        
        self.logger.debug(f"Retrieved {len(sources)} sources")
        return sources

    def get_source_by_id(self, cur: Cursor, source_id: str) -> Optional[Dict[str, Any]]:
        """Get a single source by UUID."""
        query = """
            SELECT id, platform, handle_or_url, enabled, settings, created_at, updated_at
            FROM sources
            WHERE id = %s
        """
        cur.execute(query, (source_id,))
        row = cur.fetchone()

        if not row:
            return None

        return {
            "id": str(row[0]),
            "platform": row[1],
            "handle_or_url": row[2],
            "enabled": row[3],
            "settings": row[4] or {},
            "created_at": row[5],
            "updated_at": row[6],
        }
    
    def get_enabled_sources(self, cur: Cursor) -> List[Dict[str, Any]]:
        """Get only enabled sources."""
        query = """
            SELECT id, platform, handle_or_url
            FROM sources
            WHERE enabled = TRUE
            ORDER BY platform, handle_or_url
        """
        cur.execute(query)
        rows = cur.fetchall()
        
        sources = []
        for row in rows:
            sources.append({
                "id": str(row[0]),
                "platform": row[1],
                "handle_or_url": row[2]
            })
        
        self.logger.debug(f"Retrieved {len(sources)} enabled sources")
        return sources
    
    def update_enabled(self, cur: Cursor, source_id: str, enabled: bool) -> bool:
        """Update source enabled status."""
        query = """
            UPDATE sources
            SET enabled = %s, updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        cur.execute(query, (enabled, source_id))
        row = cur.fetchone()
        
        if row:
            self.logger.debug(f"Updated source {source_id} → enabled={enabled}")
            return True
        else:
            self.logger.warning(f"Source {source_id} not found")
            return False
    
    def insert_source(self, cur: Cursor, platform: str, handle: str) -> str:
        """Insert new source."""
        query = """
            INSERT INTO sources (platform, handle_or_url, enabled)
            VALUES (%s, %s, TRUE)
            RETURNING id
        """
        cur.execute(query, (platform, handle))
        row = cur.fetchone()
        source_id = str(row[0])
        
        self.logger.info(f"Inserted source: {platform}/{handle} → {source_id}")
        return source_id
    
    def delete_source(self, cur: Cursor, source_id: str) -> bool:
        """Delete source (cascade deletes posts)."""
        query = "DELETE FROM sources WHERE id = %s RETURNING id"
        cur.execute(query, (source_id,))
        row = cur.fetchone()
        
        if row:
            self.logger.info(f"Deleted source: {source_id}")
            return True
        else:
            self.logger.warning(f"Source {source_id} not found")
            return False
    
    def get_sources_with_post_counts(self, cur: Cursor) -> List[Dict[str, Any]]:
        """
        Get all sources with their post counts.
        
        Returns:
            List of source dicts with post_count field
        """
        query = """
            SELECT 
                s.id,
                s.platform,
                s.handle_or_url,
                s.enabled,
                s.created_at,
                s.updated_at,
                COUNT(p.id) as post_count
            FROM sources s
            LEFT JOIN posts p ON s.id = p.source_id
            GROUP BY s.id, s.platform, s.handle_or_url, s.enabled, s.created_at, s.updated_at
            ORDER BY s.platform, s.handle_or_url
        """
        cur.execute(query)
        rows = cur.fetchall()
        
        sources = []
        for row in rows:
            sources.append({
                "id": str(row[0]),
                "platform": row[1],
                "handle_or_url": row[2],
                "enabled": row[3],
                "created_at": row[4],
                "updated_at": row[5],
                "post_count": row[6]
            })
        
        self.logger.debug(f"Retrieved {len(sources)} sources with post counts")
        return sources
    
    def get_source_settings(self, cur: Cursor, source_id: str) -> Dict[str, Any]:
        """
        Get settings for a source with defaults.
        
        Args:
            cur: Database cursor
            source_id: UUID of the source
            
        Returns:
            Dict with settings (defaults + source overrides)
        """
        query = """
            SELECT s.settings
            FROM sources s
            WHERE s.id = %s
        """
        cur.execute(query, (source_id,))
        row = cur.fetchone()
        
        if not row:
            self.logger.warning(f"Source {source_id} not found")
            return {}
        
        source_settings = row[0] if row[0] else {}

        # Default settings (same for all platforms for simplicity)
        defaults = {
            "fetch_delay_seconds": 1,
            "priority": 999,
            "max_posts_per_fetch": 50,
            "archive": {
                "status": "not_archived",
                "stored_posts": 0,
                "available_posts": None,
                "first_post_date": None,
                "last_archived_at": None,
                "last_live_fetch_at": None,
                "source_type": None,
            },
        }

        merged = self._deep_merge_dicts(defaults, source_settings)

        self.logger.debug(f"Merged settings for source {source_id}: {merged}")
        return merged

    def merge_source_settings(self, cur: Cursor, source_id: str, settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Merge new settings into the existing JSONB payload and persist the result.

        Returns:
            The merged settings dict, or None when the source does not exist.
        """
        source = self.get_source_by_id(cur, source_id)
        if not source:
            self.logger.warning(f"Source {source_id} not found")
            return None

        current_settings = source.get("settings") or {}
        merged_settings = self._deep_merge_dicts(current_settings, settings)

        query = """
            UPDATE sources
            SET settings = %s, updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        json_safe_settings = self._make_json_safe(merged_settings)
        cur.execute(query, (json.dumps(json_safe_settings), source_id))
        row = cur.fetchone()

        if not row:
            self.logger.warning(f"Source {source_id} not found")
            return None

        self.logger.info(f"Updated settings for source {source_id}")
        return json_safe_settings

    def update_source_settings(self, cur: Cursor, source_id: str, settings: Dict[str, Any]) -> bool:
        """
        Update settings for a source.
        
        Args:
            cur: Database cursor
            source_id: UUID of the source
            settings: Dict of settings to update
            
        Returns:
            True if updated, False if source not found
        """
        merged = self.merge_source_settings(cur, source_id, settings)
        return merged is not None

    def _deep_merge_dicts(self, base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Merge nested dictionaries without clobbering existing archive metadata."""
        merged = dict(base)

        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value

        return merged

    def _make_json_safe(self, value: Any) -> Any:
        """Convert nested datetime values into JSON-safe ISO strings."""
        if isinstance(value, dict):
            return {key: self._make_json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._make_json_safe(item) for item in value]
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value
    
