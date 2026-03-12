# backend/insight_api_bridge.py
from insight_core.db.ensure_db import ensure_database

from insight_core.services.sources_service import SourcesService
from insight_core.services.posts_service import PostsService
from insight_core.services.topics_service import TopicsService
from insight_core.services.briefing_service import BriefingService
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.services.source_config_sync_service import SourceConfigSyncService
from insight_core.services.youtube_service import YouTubeService

from insight_core.scripts.ingest import ingest_posts
from insight_core.scripts.safe_ingest import safe_ingest_posts

from datetime import datetime, date

from typing import List, Dict, Any

class InsightApiBridge:
    def __init__(self):
        self.db = ensure_database()
        self.sources_service = SourcesService(self.db)
        self.posts_service = PostsService(self.db)
        self.topics_service = TopicsService(self.db)
        self.briefing_service = BriefingService(self.db)
        self.source_fetch_service = SourceFetchService(self.db)
        self.source_config_sync_service = SourceConfigSyncService(self.db)
        self.youtube_service = YouTubeService(self.db)

    def _export_sources_json(self) -> None:
        try:
            self.source_config_sync_service.sync_db_to_json()
        except Exception:
            # Source mutations should still succeed even if the file export fails.
            pass
    
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

    def sync_sources_registry(self, direction: str) -> Dict[str, Any]:
        if direction == "json-to-db":
            return self.source_config_sync_service.sync_json_to_db(mirror=True)
        if direction == "db-to-json":
            return self.source_config_sync_service.sync_db_to_json()
        return {"success": False, "error": f"Unsupported sync direction: {direction}"}

    def update_source(self, source_id: str, enabled: bool) -> Dict[str, Any]:
        """Enable/disable a single source by UUID."""
        result = self.sources_service.update_source_status(source_id, enabled)
        self._export_sources_json()
        return result
    
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
        
        result = {
            "success": len(stats["errors"]) == 0,
            "stats": stats,
            "message": f"Added: {stats['added']}, Updated: {stats['updated']}, Deleted: {stats['deleted']}"
        }
        self._export_sources_json()
        return result
    
    def add_source(self, platform: str, handle: str) -> Dict[str, Any]:
        """Add new source to database."""
        result = self.sources_service.add_source(platform, handle)
        self._export_sources_json()
        return result
    
    def delete_source(self, source_id: str) -> bool:
        """Remove source from database."""
        deleted = self.sources_service.delete_source(source_id)
        if deleted:
            self._export_sources_json()
        return deleted
    
    def get_source_settings(self, source_id: str) -> Dict[str, Any]:
        """
        Get settings for a specific source.
        
        Args:
            source_id: UUID of the source
            
        Returns:
            Dict with success, settings, and source info
        """
        try:
            source_with_settings = self.sources_service.get_source_with_settings(source_id)
            
            return {
                "success": True,
                "source_id": source_id,
                "settings": source_with_settings.get("settings", {}),
                "source": source_with_settings
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "settings": {}
            }
    
    def update_source_settings(self, source_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update settings for a specific source.
        
        Args:
            source_id: UUID of the source
            settings: Dict of settings to update
            
        Returns:
            Dict with success status
        """
        try:
            result = self.sources_service.update_source_settings(source_id, settings)
            
            return {
                "success": True,
                "source_id": source_id,
                "settings": result.get("settings", {})
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_sources_with_settings(self) -> Dict[str, Any]:
        """
        Get all sources with their settings and post counts.
        
        Returns:
            Dict with success, sources with settings and counts
        """
        try:
            sources = self.sources_service.get_all_sources_with_settings()
            
            # Add post counts (reuse existing logic)
            sources_with_counts = self.sources_service.get_sources_with_post_counts()
            
            # Merge
            for source in sources:
                count_data = next((s for s in sources_with_counts if s["id"] == source["id"]), None)
                if count_data:
                    source["post_count"] = count_data.get("post_count", 0)
                else:
                    source["post_count"] = 0
            
            return {
                "success": True,
                "sources": sources,
                "total": len(sources)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "sources": []
            }
    
    def get_sources_with_counts(self) -> Dict[str, Any]:
        """
        Get all sources with post counts, grouped by platform.
        
        Returns:
            Dict with success, platforms grouped data, and total_posts
        """
        try:
            sources_with_settings = self.sources_service.get_all_sources_with_settings()
            
            # Group by platform
            platforms = {}
            total_posts = 0
            
            for source in sources_with_settings:
                platform = source["platform"]
                settings = source.get("settings", {})
                post_count = source.get("post_count", 0)
                
                if platform not in platforms:
                    platforms[platform] = {
                        "sources": [],
                        "total_count": 0
                    }
                
                # Get display name from settings
                display_name = settings.get("display_name") or source["handle_or_url"]
                
                platforms[platform]["sources"].append({
                    "id": source["id"],
                    "handle_or_url": source["handle_or_url"],
                    "display_name": display_name,
                    "enabled": source["enabled"],
                    "post_count": post_count,
                    "priority": settings.get("priority", 999)
                })
                
                platforms[platform]["total_count"] += post_count
                total_posts += post_count
            
            # Sort sources within each platform by priority
            for platform in platforms.values():
                platform["sources"].sort(key=lambda s: s["priority"])
            
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

    # ============= ARCHIVE =============

    async def get_archive_plan(self, source_id: str, desired_posts: int | None = None) -> Dict[str, Any]:
        """Inspect a source and estimate archive effort."""
        try:
            plan = await self.source_fetch_service.plan_archive(source_id, desired_posts)
            return {
                "success": True,
                "archive": plan,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    async def run_archive(self, source_id: str, desired_posts: int | None = None) -> Dict[str, Any]:
        """Archive posts for a single source into the shared posts table."""
        try:
            result = await self.source_fetch_service.archive_source(source_id, desired_posts)
            return result
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "source_id": source_id,
            }

    def get_archive_status(self, source_id: str) -> Dict[str, Any]:
        """Return persisted archive metadata plus current storage stats."""
        try:
            source = self.sources_service.get_source_with_settings(source_id)
            post_stats = self.posts_service.get_source_post_stats(source_id)
            archive_settings = source.get("settings", {}).get("archive", {})

            return {
                "success": True,
                "source_id": source_id,
                "archive": {
                    **archive_settings,
                    "stored_posts": post_stats["post_count"],
                    "oldest_published_at": post_stats["oldest_published_at"].isoformat() if post_stats.get("oldest_published_at") else None,
                    "latest_published_at": post_stats["latest_published_at"].isoformat() if post_stats.get("latest_published_at") else None,
                },
                "source": source,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "source_id": source_id,
            }

    # ============= BRIEFINGS =============

    async def generate_daily_briefing(self, date_str: str) -> Dict[str, Any]:
        """Generate a DB-backed daily briefing."""
        try:
            return await self.briefing_service.generate_daily_briefing(date_str)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    async def generate_daily_briefing_with_topics(
        self,
        date_str: str,
        include_unreferenced: bool = True,
    ) -> Dict[str, Any]:
        """Generate a DB-backed topic briefing."""
        try:
            return await self.briefing_service.generate_daily_briefing_with_topics(date_str, include_unreferenced)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
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


    # ============= INGESTION =============

    async def ingest_posts(self):
        """Ingest posts from all sources."""
        try:
            return await ingest_posts()
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "posts_ingested": 0,
                "sources_ingested": 0,
            }

    async def safe_ingest_posts(self):
        """Ingest posts from all sources that need updating."""
        try:
            return await safe_ingest_posts()
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "posts_ingested": 0,
                "sources_ingested": 0,
            }

    # ============= YOUTUBE =============

    def list_youtube_channel_videos(self, source_handle: str, limit: int | None = None) -> Dict[str, Any]:
        try:
            result = self.youtube_service.list_channel_videos(source_handle, limit=limit)
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def build_youtube_channel_roadmap(self, source_handle: str, limit: int | None = None) -> Dict[str, Any]:
        try:
            result = self.youtube_service.build_channel_roadmap(source_handle, limit=limit)
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def build_youtube_playlists(self, source_handle: str, limit: int = 20) -> Dict[str, Any]:
        try:
            result = self.youtube_service.build_playlists(source_handle, limit=limit)
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def evaluate_youtube_video(self, source_handle: str, video_ref: str) -> Dict[str, Any]:
        try:
            result = await self.youtube_service.evaluate_video(source_handle, video_ref)
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def chat_with_youtube_video(self, source_handle: str, video_ref: str, question: str) -> Dict[str, Any]:
        try:
            return await self.youtube_service.chat_with_video(source_handle, video_ref, question)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_youtube_watch_progress(self, video_id: str) -> Dict[str, Any]:
        try:
            progress = self.youtube_service.get_watch_progress(video_id)
            return {"success": True, "progress": progress}
        except Exception as e:
            return {"success": False, "error": str(e), "progress": None}

    def save_youtube_watch_progress(
        self,
        *,
        video_id: str,
        video_url: str,
        title: str,
        duration_seconds: int | None,
        progress_seconds: int,
        source_id: str | None = None,
        notes_markdown: str | None = None,
        completed: bool | None = None,
    ) -> Dict[str, Any]:
        try:
            progress = self.youtube_service.save_watch_progress(
                video_id=video_id,
                video_url=video_url,
                title=title,
                duration_seconds=duration_seconds,
                progress_seconds=progress_seconds,
                source_id=source_id,
                notes_markdown=notes_markdown,
                completed=completed,
            )
            return {"success": True, "progress": progress}
        except Exception as e:
            return {"success": False, "error": str(e), "progress": None}

    # ============= TOPICS RETRIEVAL =============

    def get_topics_by_date(self, date_str: str) -> Dict[str, Any]:
        """
        Get all topics for a specific date with their associated posts.
        
        Args:
            date_str: Date string in format "YYYY-MM-DD"
            
        Returns:
            Dict with success, topics (with posts), date, total
        """
        try:
            # Parse date string to date object
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            
            # Get topics from service
            topics = self.topics_service.get_topics_by_date(date_obj)
            
            if not topics:
                return {
                    "success": True,
                    "topics": [],
                    "date": date_str,
                    "total": 0,
                    "message": f"No topics found for {date_str}"
                }
            
            # Enrich each topic with its posts
            enriched_topics = []
            for topic in topics:
                posts = self.topics_service.get_posts_for_topic(topic['id'])
                
                enriched_topics.append({
                    "id": topic['id'],
                    "title": topic['title'],
                    "summary": topic.get('summary'),
                    "is_outlier": topic['is_outlier'],
                    "created_at": topic['created_at'].isoformat() if topic.get('created_at') else None,
                    "post_count": len(posts),
                    "posts": posts
                })
            
            return {
                "success": True,
                "topics": enriched_topics,
                "date": date_str,
                "total": len(enriched_topics)
            }
            
        except ValueError as e:
            # Invalid date format
            return {
                "success": False,
                "error": f"Invalid date format: {date_str}. Expected YYYY-MM-DD",
                "topics": [],
                "total": 0
            }
        except Exception as e:
            # Database or other errors
            return {
                "success": False,
                "error": str(e),
                "topics": [],
                "total": 0
            }

    def get_topic_by_id(self, topic_id: str) -> Dict[str, Any]:
        """
        Get a single topic with its posts.
        
        Args:
            topic_id: UUID of the topic
            
        Returns:
            Dict with success, topic data, and posts
        """
        try:
            # Get topic from service
            topic = self.topics_service.get_topic_by_id(topic_id)
            
            if not topic:
                return {
                    "success": False,
                    "error": f"Topic not found: {topic_id}",
                    "topic": None
                }
            
            # Get posts for this topic
            posts = self.topics_service.get_posts_for_topic(topic_id)
            
            # Build enriched topic response
            enriched_topic = {
                "id": topic['id'],
                "title": topic['title'],
                "summary": topic.get('summary'),
                "is_outlier": topic['is_outlier'],
                "date": topic['date'].isoformat() if topic.get('date') else None,
                "created_at": topic['created_at'].isoformat() if topic.get('created_at') else None,
                "post_count": len(posts),
                "posts": posts
            }
            
            return {
                "success": True,
                "topic": enriched_topic
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "topic": None
            }

    def get_posts_for_topic(self, topic_id: str) -> Dict[str, Any]:
        """
        Get all posts associated with a specific topic.
        
        Args:
            topic_id: UUID of the topic
            
        Returns:
            Dict with success, posts, topic_id, total
        """
        try:
            # Get posts from service
            posts = self.topics_service.get_posts_for_topic(topic_id)
            
            return {
                "success": True,
                "posts": posts,
                "topic_id": topic_id,
                "total": len(posts)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "posts": [],
                "topic_id": topic_id,
                "total": 0
            }

    def check_topics_exist(self, date_str: str) -> Dict[str, Any]:
        """
        Check if topics exist for a specific date.
        
        Args:
            date_str: Date string in format "YYYY-MM-DD"
            
        Returns:
            Dict with success and exists flag
        """
        try:
            # Parse date string to date object
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            
            # Check if topics exist
            exists = self.topics_service.topics_exist_for_date(date_obj)
            
            return {
                "success": True,
                "exists": exists,
                "date": date_str
            }
            
        except ValueError as e:
            return {
                "success": False,
                "error": f"Invalid date format: {date_str}. Expected YYYY-MM-DD",
                "exists": False
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "exists": False
            }

    def find_similar_topics(self, topic_id: str, threshold: float = 0.75, limit: int = 10) -> Dict[str, Any]:
        """
        Find topics similar to a given topic (future: when embeddings are added).
        
        Args:
            topic_id: UUID of the source topic
            threshold: Minimum similarity score (0-1)
            limit: Maximum number of results
            
        Returns:
            Dict with success, similar topics
        """
        try:
            # Get similar topics from service
            similar = self.topics_service.find_similar_topics(topic_id, threshold, limit)
            
            return {
                "success": True,
                "similar_topics": similar,
                "source_topic_id": topic_id,
                "total": len(similar)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "similar_topics": [],
                "total": 0
            }

    def update_topic_title(self, topic_id: str, new_title: str) -> Dict[str, Any]:
        """
        Update the title of a topic.
        
        Args:
            topic_id: UUID of the topic
            new_title: New title for the topic
            
        Returns:
            Dict with success status
        """
        try:
            # Validate input
            if not new_title or not new_title.strip():
                return {
                    "success": False,
                    "error": "Title cannot be empty"
                }
            
            # Update topic title
            success = self.topics_service.update_topic_title(topic_id, new_title.strip())
            
            if success:
                return {
                    "success": True,
                    "topic_id": topic_id,
                    "title": new_title.strip()
                }
            else:
                return {
                    "success": False,
                    "error": f"Topic not found: {topic_id}"
                }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def move_post_to_outlier(self, post_id: str, source_topic_id: str, date_str: str) -> Dict[str, Any]:
        """
        Move a post from a topic to the outlier topic.
        
        Args:
            post_id: UUID of the post
            source_topic_id: UUID of the current topic
            date_str: Date string (YYYY-MM-DD) for finding/creating outlier topic
            
        Returns:
            Dict with success status and outlier topic ID
        """
        try:
            # Parse date
            from datetime import datetime
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            
            # Move post to outlier
            result = self.topics_service.move_post_to_outlier(post_id, source_topic_id, target_date)
            
            if result["success"]:
                return {
                    "success": True,
                    "post_id": post_id,
                    "source_topic_id": source_topic_id,
                    "outlier_topic_id": result["outlier_topic_id"],
                    "message": "Post moved to outlier topic"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to move post. Post may not exist in source topic."
                }
            
        except ValueError as e:
            return {
                "success": False,
                "error": f"Invalid date format: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    # ============= TOPIC MODELING (FOR TESTING) =============

    # Note: Topic generation should be done via scripts, not API
    # But we keep this for testing purposes
    
    def model_topics(self, posts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Model topics from a list of posts (testing only)."""
        try:
            processor = self.briefing_service.processor
            if not processor.is_setup and not processor.setup_processor():
                return {
                    "success": False,
                    "error": "Processor not setup. Call setup_processor() first"
                }
            return processor.model_topics(posts)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
