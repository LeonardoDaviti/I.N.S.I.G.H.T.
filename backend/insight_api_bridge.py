# backend/insight_api_bridge.py
from insight_core.db.ensure_db import ensure_database
from insight_core.services.sources_service import SourcesService
from insight_core.services.posts_service import PostsService
from datetime import datetime, date
# from insight_core.services.briefing_service import BriefingService

from typing import List, Dict, Any

class InsightApiBridge:
    def __init__(self):
        self.db = ensure_database()
        self.sources_service = SourcesService(self.db)
        self.posts_service = PostsService(self.db)
    # ============= SOURCES MANAGEMENT =============

    def get_all_sources(self) -> List[Dict[str, Any]]:
        """Get all sources from database (flat list)."""
        return self.sources_service.get_all_sources()
    
    def get_sources_config(self) -> Dict[str, Any]:
        """
        Get sources in frontend-compatible format.
        Transforms flat DB list into nested platform structure.
        """
        sources = self.sources_service.get_all_sources()
        
        # Group sources by platform
        platforms_data = {}
        for source in sources:
            platform = source["platform"]
            
            # Initialize platform if not exists
            if platform not in platforms_data:
                platforms_data[platform] = {
                    "enabled": False,  # Will be set to True if ANY source is enabled
                    "sources": []
                }
            
            # Add source to platform
            platforms_data[platform]["sources"].append({
                "id": source["handle_or_url"],
                "state": "enabled" if source["enabled"] else "disabled",
                "db_id": source["id"]  # Keep DB UUID for updates
            })
            
            # If any source is enabled, mark platform as enabled
            if source["enabled"]:
                platforms_data[platform]["enabled"] = True
        
        # Build frontend-compatible structure
        return {
            "metadata": {
                "name": "I.N.S.I.G.H.T.",
                "description": "Intelligence Network for Systematic Gathering and Handling of Topics",
                "version": "Mark VI"
            },
            "platforms": platforms_data
        }
    
    def get_enabled_sources(self) -> List[Dict[str, Any]]:
        """Get only enabled sources (flat list)."""
        return self.sources_service.get_enabled_sources()

    def update_source(self, source_id: str, enabled: bool) -> Dict[str, Any]:
        """Enable/disable a single source by UUID."""
        return self.sources_service.update_source_status(source_id, enabled)
    
    def update_sources_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update sources from frontend config format.
        Handles add/remove/enable/disable operations.
        """
        # Get current sources from DB
        current_sources = self.sources_service.get_all_sources()
        
        # Build lookup: (platform, handle) → db_id
        current_lookup = {
            (s["platform"], s["handle_or_url"]): s["id"]
            for s in current_sources
        }
        
        # Track operations
        stats = {
            "added": 0,
            "updated": 0,
            "deleted": 0,
            "errors": []
        }
        
        # Process each platform from frontend
        new_sources_set = set()
        
        for platform, platform_data in config.get("platforms", {}).items():
            for source_item in platform_data.get("sources", []):
                handle = source_item["id"]
                state = source_item["state"]
                enabled = (state == "enabled")
                
                key = (platform, handle)
                new_sources_set.add(key)
                
                # Check if source exists in DB
                if key in current_lookup:
                    # Update existing source
                    db_id = current_lookup[key]
                    try:
                        self.sources_service.update_source_status(db_id, enabled)
                        stats["updated"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to update {platform}/{handle}: {e}")
                else:
                    # Add new source
                    try:
                        self.sources_service.add_source(platform, handle)
                        stats["added"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to add {platform}/{handle}: {e}")
        
        # Delete sources that are no longer in frontend config
        for key, db_id in current_lookup.items():
            if key not in new_sources_set:
                try:
                    self.sources_service.delete_source(db_id)
                    stats["deleted"] += 1
                except Exception as e:
                    stats["errors"].append(f"Failed to delete {key}: {e}")
        
        return {
            "success": len(stats["errors"]) == 0,
            "stats": stats,
            "message": f"Added: {stats['added']}, Updated: {stats['updated']}, Deleted: {stats['deleted']}"
        }
    
    def add_source(self, platform: str, handle: str) -> Dict[str, Any]:
        """Add new source to database."""
        return self.sources_service.add_source(platform, handle)
    
    def delete_source(self, source_id: str) -> bool:
        """Remove source from database."""
        return self.sources_service.delete_source(source_id)
    
    def get_sources_with_counts(self) -> Dict[str, Any]:
        """
        Get all sources with post counts, grouped by platform.
        
        Returns:
            Dict with success, platforms grouped data, and total_posts
        """
        try:
            # Get sources with counts from service
            sources = self.sources_service.get_sources_with_post_counts()
            
            # Group by platform
            platforms = {}
            total_posts = 0
            
            for source in sources:
                platform = source["platform"]
                
                # Initialize platform if not exists
                if platform not in platforms:
                    platforms[platform] = {
                        "sources": [],
                        "total_count": 0
                    }
                
                # Add source to platform
                platforms[platform]["sources"].append({
                    "id": source["id"],
                    "handle_or_url": source["handle_or_url"],
                    "enabled": source["enabled"],
                    "post_count": source["post_count"]
                })
                
                # Update counts
                platforms[platform]["total_count"] += source["post_count"]
                total_posts += source["post_count"]
            
            return {
                "success": True,
                "platforms": platforms,
                "total_posts": total_posts
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "platforms": {},
                "total_posts": 0
            }


    # ============= POSTS RETRIEVAL =============

    def get_posts_by_source(self, source_id: str) -> Dict[str, Any]:
        """
        Get all posts for a specific source from database.

        Args:
            source_id: UUID of the source
            
        Returns:
            Dict with success, posts, source_id, total
        """
        try:
            # Get posts from service
            posts = self.posts_service.get_posts_by_source(source_id)
            
            return {
                "success": True,
                "posts": posts,
                "source_id": source_id,
                "total": len(posts)
            }
            
        except Exception as e:
            # Database or other errors
            return {
                "success": False,
                "error": str(e),
                "posts": [],
                "total": 0,
                "source_id": source_id
            }

    def get_posts_by_date(self, date_str: str) -> Dict[str, Any]:
        """
        Get posts for a specific date from database.

        Args:
            date_str: Date string in format "YYYY-MM-DD"
            
        Returns:
            Dict with success, posts, date, total
        """
        try:
            # Parse date string to date object
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            
            # Get posts from service
            posts = self.posts_service.get_posts_by_date(date_obj)
            
            return {
                "success": True,
                "posts": posts,
                "date": date_str,
                "total": len(posts),
                "source": "database"
            }
            
        except ValueError as e:
            # Invalid date format
            return {
                "success": False,
                "error": f"Invalid date format: {date_str}. Expected YYYY-MM-DD",
                "posts": [],
                "total": 0
            }
        except Exception as e:
            # Database or other errors
            return {
                "success": False,
                "error": str(e),
                "posts": [],
                "total": 0
            }
