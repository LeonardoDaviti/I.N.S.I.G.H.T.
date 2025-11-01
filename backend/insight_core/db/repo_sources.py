"""
Repository for sources table operations.
Handles all SQL queries for source management.
"""
import psycopg
from psycopg import Cursor
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
            "max_posts_per_fetch": 50
        }
        
        # Merge: defaults + source overrides
        merged = {**defaults, **source_settings}
        
        self.logger.debug(f"Merged settings for source {source_id}: {merged}")
        return merged
    
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
        import json
        
        query = """
            UPDATE sources
            SET settings = %s, updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        cur.execute(query, (json.dumps(settings), source_id))
        row = cur.fetchone()
        
        if row:
            self.logger.info(f"Updated settings for source {source_id}")
            return True
        else:
            self.logger.warning(f"Source {source_id} not found")
            return False
    