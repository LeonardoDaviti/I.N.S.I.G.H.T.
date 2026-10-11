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

    def get_source_by_id(self, source_id: str) -> Dict[str, Any] | None:
        """Get a single source by UUID."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_source_by_id(cur, source_id)
    
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
    
    def set_in_main_digest(self, source_id: str, in_main_digest: bool) -> Dict[str, Any]:
        """Include/exclude a single source from the main digests."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                ok = self.repo.set_in_main_digest(cur, source_id, in_main_digest)
                conn.commit()
                if not ok:
                    raise ValueError(f"Source {source_id} not found")
                self.logger.info(f"Source {source_id} -> in_main_digest={in_main_digest}")
                return {"source_id": source_id, "in_main_digest": in_main_digest}

    def set_folder_in_main_digest(self, folder_id: str, in_main_digest: bool) -> Dict[str, Any]:
        """Apply the digest switch to every source in a folder/track."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                changed = self.repo.set_in_main_digest_for_folder(cur, folder_id, in_main_digest)
                conn.commit()
                self.logger.info(f"Folder {folder_id} -> in_main_digest={in_main_digest} ({changed} sources)")
                return {"folder_id": folder_id, "in_main_digest": in_main_digest, "sources_updated": changed}

    def add_source(self, platform: str, handle: str, *, in_main_digest: bool = True) -> Dict[str, Any]:
        """Add new source to database."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                source_id = self.repo.insert_source(cur, platform, handle, in_main_digest=in_main_digest)
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
                merged_settings = self.repo.merge_source_settings(cur, source_id, validated_settings)
                conn.commit()
                
                if merged_settings is not None:
                    self.logger.info(f"Updated settings for source {source_id}")
                    return {
                        "source_id": source_id,
                        "settings": merged_settings
                    }
                else:
                    raise ValueError(f"Source {source_id} not found")

    def merge_source_settings(self, source_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Merge internal settings payloads, including archive metadata."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                merged_settings = self.repo.merge_source_settings(cur, source_id, settings)
                conn.commit()

                if merged_settings is None:
                    raise ValueError(f"Source {source_id} not found")

                self.logger.info(f"Merged internal settings for source {source_id}")
                return {
                    "source_id": source_id,
                    "settings": merged_settings,
                }

    # ------------------------------------------------------------------ views for the Sources screens

    def config_view(self) -> Dict[str, Any]:
        """Sources nested by platform: {metadata, platforms: {p: {enabled, sources: [...]}}}.

        A platform is enabled when any of its sources is.
        """
        platforms: Dict[str, Any] = {}
        for source in self.get_all_sources():
            platform = platforms.setdefault(source["platform"], {"enabled": False, "sources": []})
            platform["sources"].append({
                "id": source["handle_or_url"],
                "state": "enabled" if source["enabled"] else "disabled",
                "db_id": source["id"],  # Keep DB UUID for updates
            })
            if source["enabled"]:
                platform["enabled"] = True
        return {
            "metadata": {
                "name": "I.N.S.I.G.H.T.",
                "description": "Intelligence Network for Systematic Gathering and Handling of Topics",
                "version": "Mark VI",
            },
            "platforms": platforms,
        }

    def apply_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Make the sources match a config_view-shaped dict: add, enable/disable, delete.

        One failing source does not stop the rest; its error lands in stats["errors"].
        """
        current = {(s["platform"], s["handle_or_url"]): s["id"] for s in self.get_all_sources()}
        stats: Dict[str, Any] = {"added": 0, "updated": 0, "deleted": 0, "errors": []}
        wanted = set()

        for platform, platform_data in config.get("platforms", {}).items():
            for item in platform_data.get("sources", []):
                handle = item["id"]
                enabled = item["state"] == "enabled"
                key = (platform, handle)
                wanted.add(key)
                if key in current:
                    try:
                        self.update_source_status(current[key], enabled)
                        stats["updated"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to update {platform}/{handle}: {e}")
                else:
                    try:
                        self.add_source(platform, handle)
                        stats["added"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to add {platform}/{handle}: {e}")

        for key, db_id in current.items():
            if key not in wanted:
                try:
                    self.delete_source(db_id)
                    stats["deleted"] += 1
                except Exception as e:
                    stats["errors"].append(f"Failed to delete {key}: {e}")

        return {
            "success": len(stats["errors"]) == 0,
            "stats": stats,
            "message": f"Added: {stats['added']}, Updated: {stats['updated']}, Deleted: {stats['deleted']}",
        }

    def with_settings_and_counts(self) -> List[Dict[str, Any]]:
        """Every source with its merged settings and post_count."""
        sources = self.get_all_sources_with_settings()
        counts = {s["id"]: s.get("post_count", 0) for s in self.get_sources_with_post_counts()}
        for source in sources:
            source["post_count"] = counts.get(source["id"], 0)
        return sources

    def counts_by_platform(self) -> Dict[str, Any]:
        """{platforms: {p: {sources, total_count}}, total_posts}; sources sorted by priority."""
        platforms: Dict[str, Any] = {}
        total_posts = 0
        for source in self.get_all_sources_with_settings():
            settings = source.get("settings", {})
            post_count = source.get("post_count", 0)
            platform = platforms.setdefault(source["platform"], {"sources": [], "total_count": 0})
            platform["sources"].append({
                "id": source["id"],
                "handle_or_url": source["handle_or_url"],
                "display_name": settings.get("display_name") or source["handle_or_url"],
                "enabled": source["enabled"],
                "post_count": post_count,
                "priority": settings.get("priority", 999),
            })
            platform["total_count"] += post_count
            total_posts += post_count
        for platform in platforms.values():
            platform["sources"].sort(key=lambda s: s["priority"])
        return {"platforms": platforms, "total_posts": total_posts}
