# backend/insight_api_bridge.py
from insight_core.db.ensure_db import ensure_database

from insight_core.services.sources_service import SourcesService
from insight_core.services.posts_service import PostsService
from insight_core.services.topics_service import TopicsService
from insight_core.services.briefing_service import BriefingService
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.services.source_config_sync_service import SourceConfigSyncService
from insight_core.services.entity_memory_service import EntityMemoryService
from insight_core.services.event_memory_service import EventMemoryService
from insight_core.services.evidence_foundation_service import EvidenceFoundationService
from insight_core.services.inbox_service import InboxService
from insight_core.services.analyst_actions_service import AnalystActionsService
from insight_core.services.system_logs_service import SystemLogsService
from insight_core.services.operations_service import OperationsService
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.explainability_service import ExplainabilityService
from insight_core.services.stories_service import StoriesService
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
        self.entity_memory_service = EntityMemoryService(self.db)
        self.event_memory_service = EventMemoryService(self.db)
        self.evidence_service = EvidenceFoundationService(self.db)
        self.system_logs_service = SystemLogsService()
        self.operations_service = OperationsService(self.db)
        self.post_detail_service = PostDetailService(self.db)
        self.explainability_service = ExplainabilityService(self.db)
        self.stories_service = StoriesService(self.db)
        self.inbox_service = InboxService(
            self.db,
            operations_service=self.operations_service,
            stories_service=self.stories_service,
            post_detail_service=self.post_detail_service,
        )
        self.analyst_actions_service = AnalystActionsService(
            self.db,
            stories_service=self.stories_service,
            post_detail_service=self.post_detail_service,
        )
        self.youtube_service = YouTubeService(self.db)

    def _start_job_safe(self, *args, **kwargs) -> str | None:
        try:
            return self.operations_service.start_job(*args, **kwargs)
        except Exception:
            return None

    def _finish_job_safe(self, job_id: str | None, **kwargs) -> None:
        if not job_id:
            return
        try:
            self.operations_service.finish_job(job_id, **kwargs)
        except Exception:
            return

    def _append_job_event_safe(self, job_id: str | None, **kwargs) -> None:
        if not job_id:
            return
        try:
            self.operations_service.append_job_event(job_id, **kwargs)
        except Exception:
            return

    def _record_source_status_safe(self, source_id: str, **kwargs) -> None:
        try:
            self.operations_service.record_source_status(source_id, **kwargs)
        except Exception:
            return

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

    def get_archive_catalog(self) -> Dict[str, Any]:
        try:
            sources = self.sources_service.get_all_sources_with_settings()
            catalog = []
            for source in sources:
                if not source.get("enabled"):
                    continue
                archive = (source.get("settings") or {}).get("archive", {})
                catalog.append(
                    {
                        "source_id": source["id"],
                        "display_name": (source.get("settings") or {}).get("display_name") or source["handle_or_url"],
                        "platform": source["platform"],
                        "enabled": bool(source.get("enabled")),
                        "stored_posts": int(archive.get("stored_posts") or source.get("post_count") or 0),
                        "available_posts": archive.get("available_posts"),
                        "archive_status": archive.get("status") or "not_archived",
                        "resume_ready": bool(archive.get("resume_ready")),
                        "source_type": archive.get("source_type"),
                        "last_archived_at": archive.get("last_archived_at"),
                        "last_live_fetch_at": archive.get("last_live_fetch_at"),
                        "checkpoint": archive.get("checkpoint"),
                        "rate_limit": archive.get("rate_limit") or {},
                    }
                )
            catalog.sort(key=lambda item: (item["archive_status"] != "partial", item["archive_status"] != "not_archived", item["display_name"].lower()))
            return {"success": True, "sources": catalog, "total": len(catalog)}
        except Exception as e:
            return {"success": False, "error": str(e), "sources": [], "total": 0}

    async def get_archive_plan(
        self,
        source_id: str,
        desired_posts: int | None = None,
        *,
        resume: bool = True,
        rate_limit_overrides: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Inspect a source and estimate archive effort."""
        try:
            plan = await self.source_fetch_service.plan_archive(
                source_id,
                desired_posts,
                resume=resume,
                rate_limit_overrides=rate_limit_overrides,
            )
            return {
                "success": True,
                "archive": plan,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    async def run_archive(
        self,
        source_id: str,
        desired_posts: int | None = None,
        *,
        resume: bool = True,
        rate_limit_overrides: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Archive posts for a single source into the shared posts table."""
        job_id = self._start_job_safe(
            "archive_source",
            trigger="manual",
            source_id=source_id,
            payload={
                "desired_posts": desired_posts,
                "resume": resume,
                "rate_limit": rate_limit_overrides or {},
            },
        )
        try:
            self._append_job_event_safe(
                job_id,
                message="Archive job started",
                level="info",
                payload={"desired_posts": desired_posts, "resume": resume, "rate_limit": rate_limit_overrides or {}},
            )
            result = await self.source_fetch_service.archive_source(
                source_id,
                desired_posts,
                progress_callback=lambda event: self._append_job_event_safe(
                    job_id,
                    message=str(event.get("message") or event.get("stage") or "Archive progress"),
                    level="info",
                    progress=event.get("progress"),
                    payload=event,
                ),
                resume=resume,
                rate_limit_overrides=rate_limit_overrides,
            )
            if result.get("success"):
                self._record_source_status_safe(
                    source_id,
                    status="healthy",
                    message=f"Archived {result.get('posts_fetched', 0)} posts",
                    trigger="manual",
                    fetched_posts=result.get("posts_fetched"),
                )
            self._finish_job_safe(
                job_id,
                status="success" if result.get("success") else "failed",
                message=result.get("error") or f"Archived {result.get('posts_fetched', 0)} posts",
                payload=result,
            )
            return result
        except Exception as e:
            self._record_source_status_safe(
                source_id,
                status="error",
                message=str(e),
                trigger="manual",
            )
            self._finish_job_safe(
                job_id,
                status="failed",
                message=str(e),
                payload={"source_id": source_id},
            )
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

    async def fetch_source_now(self, source_id: str, limit: int | None = None) -> Dict[str, Any]:
        """Fetch the latest posts for a single source immediately."""
        job_id = self._start_job_safe(
            "fetch_source_now",
            trigger="manual",
            source_id=source_id,
            payload={"limit": limit},
        )
        try:
            result = await self.source_fetch_service.ingest_source_now(source_id, limit)
            self._record_source_status_safe(
                source_id,
                status="healthy",
                message=f"Fetched {result.get('posts_fetched', 0)} posts",
                trigger="manual",
                fetched_posts=result.get("posts_fetched"),
            )
            self._finish_job_safe(
                job_id,
                status="success",
                message=f"Fetched {result.get('posts_fetched', 0)} posts",
                payload=result,
            )
            return result
        except Exception as e:
            self._record_source_status_safe(
                source_id,
                status="error",
                message=str(e),
                trigger="manual",
            )
            self._finish_job_safe(
                job_id,
                status="failed",
                message=str(e),
                payload={"source_id": source_id},
            )
            return {
                "success": False,
                "error": str(e),
                "source_id": source_id,
            }

    def get_ingestion_logs(self, log_name: str = "application", lines: int = 200) -> Dict[str, Any]:
        """Return recent shared log lines for ingestion/backend operations."""
        try:
            return self.system_logs_service.get_log_tail(log_name, lines)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "log": log_name,
                "lines": [],
            }

    # ============= BRIEFINGS =============

    async def generate_daily_briefing(self, date_str: str) -> Dict[str, Any]:
        """Generate a DB-backed daily briefing."""
        job_id = self._start_job_safe(
            "daily_briefing",
            trigger="manual",
            message=f"Generate daily briefing for {date_str}",
            payload={"date": date_str},
        )
        try:
            self._append_job_event_safe(job_id, message=f"Starting daily briefing for {date_str}", level="info")
            result = await self.briefing_service.generate_daily_briefing(date_str)
            self._finish_job_safe(
                job_id,
                status="success" if result.get("success") else "failed",
                message=result.get("error") or f"Processed {result.get('posts_processed', 0)} posts",
                payload={
                    **result,
                    "estimated_tokens": result.get("estimated_tokens"),
                },
            )
            return result
        except Exception as e:
            self._finish_job_safe(job_id, status="failed", message=str(e), payload={"date": date_str})
            return {
                "success": False,
                "error": str(e),
            }

    async def generate_daily_briefing_with_topics(
        self,
        date_str: str,
        include_unreferenced: bool = True,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        """Generate a DB-backed topic briefing."""
        job_id = self._start_job_safe(
            "topic_briefing",
            trigger="manual",
            message=f"Generate topic briefing for {date_str}",
            payload={"date": date_str, "include_unreferenced": include_unreferenced},
        )
        try:
            self._append_job_event_safe(job_id, message=f"Starting topic briefing for {date_str}", level="info")
            result = await self.briefing_service.generate_daily_briefing_with_topics(
                date_str,
                include_unreferenced,
                refresh=refresh,
            )
            self._finish_job_safe(
                job_id,
                status="success" if result.get("success") else "failed",
                message=result.get("error") or f"Processed {result.get('posts_processed', 0)} posts",
                payload={
                    **result,
                    "estimated_tokens": result.get("estimated_tokens"),
                },
            )
            return result
        except Exception as e:
            self._finish_job_safe(job_id, status="failed", message=str(e), payload={"date": date_str})
            return {
                "success": False,
                "error": str(e),
            }

    async def generate_weekly_briefing(self, date_str: str, refresh: bool = False) -> Dict[str, Any]:
        """Generate a DB-backed weekly briefing."""
        job_id = self._start_job_safe(
            "weekly_briefing",
            trigger="manual",
            message=f"Generate weekly briefing for {date_str}",
            payload={"date": date_str, "refresh": refresh},
        )
        try:
            self._append_job_event_safe(job_id, message=f"Starting weekly briefing anchored at {date_str}", level="info")
            result = await self.briefing_service.generate_weekly_briefing(date_str, refresh=refresh)
            self._finish_job_safe(
                job_id,
                status="success" if result.get("success") else "failed",
                message=result.get("error") or f"Combined {result.get('daily_briefings_used', 0)} daily briefings",
                payload={
                    **result,
                    "estimated_tokens": result.get("estimated_tokens"),
                },
            )
            return result
        except Exception as e:
            self._finish_job_safe(job_id, status="failed", message=str(e), payload={"date": date_str})
            return {
                "success": False,
                "error": str(e),
            }

    async def generate_weekly_topic_briefing(self, date_str: str, refresh: bool = False) -> Dict[str, Any]:
        """Generate a DB-backed weekly topic briefing."""
        job_id = self._start_job_safe(
            "weekly_topic_briefing",
            trigger="manual",
            message=f"Generate weekly topic briefing for {date_str}",
            payload={"date": date_str, "refresh": refresh},
        )
        try:
            self._append_job_event_safe(job_id, message=f"Starting weekly topic briefing anchored at {date_str}", level="info")
            result = await self.briefing_service.generate_weekly_topic_briefing(date_str, refresh=refresh)
            self._finish_job_safe(
                job_id,
                status="success" if result.get("success") else "failed",
                message=result.get("error") or f"Combined {result.get('daily_briefings_used', 0)} daily topic briefings",
                payload={
                    **result,
                    "estimated_tokens": result.get("estimated_tokens"),
                },
            )
            return result
        except Exception as e:
            self._finish_job_safe(job_id, status="failed", message=str(e), payload={"date": date_str})
            return {
                "success": False,
                "error": str(e),
            }

    async def generate_source_vertical_briefing(
        self,
        source_id: str,
        start_date: str,
        end_date: str,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        """Generate a DB-backed source vertical briefing."""
        job_id = self._start_job_safe(
            "vertical_briefing_source",
            trigger="manual",
            message=f"Generate vertical briefing for {source_id}",
            payload={
                "source_id": source_id,
                "start_date": start_date,
                "end_date": end_date,
                "refresh": refresh,
            },
        )
        try:
            self._append_job_event_safe(
                job_id,
                message=f"Starting source vertical briefing for {source_id} ({start_date} to {end_date})",
                level="info",
            )
            result = await self.briefing_service.generate_source_vertical_briefing(
                source_id,
                start_date,
                end_date,
                refresh=refresh,
            )
            self._finish_job_safe(
                job_id,
                status="success" if result.get("success") else "failed",
                message=result.get("error") or f"Processed {result.get('posts_processed', 0)} posts into {len(result.get('tracks', []))} tracks",
                payload={
                    **result,
                    "estimated_tokens": result.get("estimated_tokens"),
                },
            )
            return result
        except Exception as e:
            self._finish_job_safe(
                job_id,
                status="failed",
                message=str(e),
                payload={
                    "source_id": source_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
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
        job_id = self._start_job_safe("ingest_all", trigger="manual")
        try:
            result = await ingest_posts(trigger="manual")
            self._finish_job_safe(
                job_id,
                status="success" if result.get("success") else "failed",
                message=result.get("error") or f"Ingested {result.get('posts_ingested', 0)} posts",
                payload=result,
            )
            return result
        except Exception as e:
            self._finish_job_safe(job_id, status="failed", message=str(e))
            return {
                "success": False,
                "error": str(e),
                "posts_ingested": 0,
                "sources_ingested": 0,
            }

    async def safe_ingest_posts(self):
        """Ingest posts from all sources that need updating."""
        job_id = self._start_job_safe("safe_ingest", trigger="manual")
        try:
            result = await safe_ingest_posts(trigger="manual")
            self._finish_job_safe(
                job_id,
                status="success" if result.get("success") else "failed",
                message=result.get("error") or f"Ingested {result.get('posts_ingested', 0)} posts",
                payload=result,
            )
            return result
        except Exception as e:
            self._finish_job_safe(job_id, status="failed", message=str(e))
            return {
                "success": False,
                "error": str(e),
                "posts_ingested": 0,
                "sources_ingested": 0,
            }

    def get_scheduler_config(self) -> Dict[str, Any]:
        try:
            return {"success": True, "scheduler": self.operations_service.get_scheduler_config()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_scheduler_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return {"success": True, "scheduler": self.operations_service.update_scheduler_config(config)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_operations_overview(self) -> Dict[str, Any]:
        try:
            return self.operations_service.get_operations_overview()
        except Exception as e:
            return {"success": False, "error": str(e), "jobs": [], "source_health": [], "alerts": []}

    def get_operation_job(self, job_id: str) -> Dict[str, Any]:
        try:
            job = self.operations_service.get_job(job_id)
            if not job:
                return {"success": False, "error": f"Job {job_id} not found", "job": None}
            return {"success": True, "job": job}
        except Exception as e:
            return {"success": False, "error": str(e), "job": None}

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

    # ============= POST DETAILS =============

    def get_post_detail(self, post_id: str) -> Dict[str, Any]:
        try:
            post = self.post_detail_service.get_post_by_id(post_id)
            if not post:
                return {"success": False, "error": f"Post {post_id} not found", "post": None}
            notes = self.post_detail_service.get_notes(post_id)
            summary = self.post_detail_service.get_cached_summary(post_id)
            summary_references = self.post_detail_service.get_post_summary_references(post_id)
            highlights = self.post_detail_service.get_post_highlights(post_id)
            reader_state = self.post_detail_service.get_post_reader_state(post_id)
            return {
                "success": True,
                "post": post,
                "notes": notes,
                "summary": summary,
                "summary_references": summary_references,
                "highlights": highlights,
                "reader_state": reader_state,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "post": None, "summary": None, "summary_references": [], "highlights": [], "reader_state": None}

    def get_post_highlights(self, post_id: str, refresh: bool = False) -> Dict[str, Any]:
        try:
            result = self.post_detail_service.get_or_generate_highlights(post_id, refresh=refresh)
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e), "post_id": post_id, "highlights": []}

    def get_post_reader_state(self, post_id: str) -> Dict[str, Any]:
        try:
            state = self.post_detail_service.get_post_reader_state(post_id)
            return {"success": True, "post_id": post_id, "reader_state": state}
        except Exception as e:
            return {"success": False, "error": str(e), "post_id": post_id, "reader_state": None}

    def record_post_open(self, post_id: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        try:
            stored = self.post_detail_service.record_post_open(post_id, metadata=metadata)
            return {"success": True, "event": stored}
        except Exception as e:
            return {"success": False, "error": str(e), "event": None}

    def record_post_reading_session(self, post_id: str, duration_seconds: int, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        try:
            stored = self.post_detail_service.record_reading_session(post_id, duration_seconds=duration_seconds, metadata=metadata)
            return {"success": True, "event": stored}
        except Exception as e:
            return {"success": False, "error": str(e), "event": None}

    def toggle_post_favorite(self, post_id: str, favorited: bool) -> Dict[str, Any]:
        try:
            result = self.post_detail_service.toggle_favorite(post_id, favorited)
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e), "post_id": post_id}

    def get_post_evidence(self, post_id: str) -> Dict[str, Any]:
        try:
            evidence = self.evidence_service.get_post_evidence_debug(post_id)
            if not evidence:
                return {"success": False, "error": f"Post {post_id} not found", "evidence": None}
            return {"success": True, "evidence": evidence}
        except Exception as e:
            return {"success": False, "error": str(e), "evidence": None}

    def get_post_memory(self, post_id: str) -> Dict[str, Any]:
        try:
            memory = self.entity_memory_service.get_post_memory_debug(post_id)
            if not memory:
                return {"success": False, "error": f"Post {post_id} not found", "memory": None}
            return {"success": True, "memory": memory}
        except Exception as e:
            return {"success": False, "error": str(e), "memory": None}

    def get_post_events(self, post_id: str) -> Dict[str, Any]:
        try:
            events = self.event_memory_service.get_post_event_debug(post_id)
            if not events:
                return {"success": False, "error": f"Post {post_id} not found", "events": None}
            return {"success": True, "events": events}
        except Exception as e:
            return {"success": False, "error": str(e), "events": None}

    def get_stories(
        self,
        *,
        status: str | None = None,
        story_kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        try:
            limit = 100 if limit is None else int(limit)
            offset = 0 if offset is None else int(offset)
            stories = self.stories_service.list_stories(
                status=status,
                story_kind=story_kind,
                limit=limit,
                offset=offset,
            )
            return {
                "success": True,
                "stories": stories,
                "total": len(stories),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stories": [],
                "total": 0,
            }

    def get_story(self, story_id: str) -> Dict[str, Any]:
        try:
            story = self.stories_service.get_story_detail(story_id)
            if not story:
                return {"success": False, "error": f"Story {story_id} not found", "story": None}
            return {"success": True, "story": story}
        except Exception as e:
            return {"success": False, "error": str(e), "story": None}

    def get_story_timeline(self, story_id: str) -> Dict[str, Any]:
        try:
            timeline = self.stories_service.get_story_timeline(story_id)
            if not timeline:
                return {"success": False, "error": f"Story {story_id} not found", "story": None, "timeline": []}
            return {"success": True, **timeline}
        except Exception as e:
            return {"success": False, "error": str(e), "story": None, "timeline": []}

    def get_post_story(self, post_id: str) -> Dict[str, Any]:
        try:
            post = self.post_detail_service.get_post_by_id(post_id)
            if not post:
                return {"success": False, "error": f"Post {post_id} not found", "post_id": post_id, "stories": []}
            return {"success": True, **self.stories_service.get_post_story(post_id)}
        except Exception as e:
            return {"success": False, "error": str(e), "post_id": post_id, "stories": []}

    # ============= INBOX =============

    def get_inbox(self, batch_id: str | None = None, limit: int = 20) -> Dict[str, Any]:
        try:
            return self.inbox_service.get_inbox(batch_id=batch_id, limit=limit)
        except Exception as e:
            return {"success": False, "error": str(e), "batch": None, "items": [], "total": 0}

    def get_inbox_batches(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        try:
            return self.inbox_service.list_batches(limit=limit, offset=offset)
        except Exception as e:
            return {"success": False, "error": str(e), "batches": [], "total": 0}

    def get_inbox_items(
        self,
        *,
        batch_id: str | None = None,
        status: str | None = None,
        target_type: str | None = None,
        source_id: str | None = None,
        generated_for_date: str | date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        try:
            return self.inbox_service.list_items(
                batch_id=batch_id,
                status=status,
                target_type=target_type,
                source_id=source_id,
                generated_for_date=generated_for_date,
                limit=limit,
                offset=offset,
            )
        except Exception as e:
            return {"success": False, "error": str(e), "items": [], "total": 0}

    def get_inbox_item(self, item_id: str) -> Dict[str, Any]:
        try:
            return self.inbox_service.get_item_detail(item_id)
        except Exception as e:
            return {"success": False, "error": str(e), "item": None, "target": None, "actions": []}

    def rebuild_inbox(
        self,
        generated_for_date: str | date | None = None,
        *,
        scope_type: str = "daily_queue",
        scope_value: str | None = None,
        limit: int = 20,
        actor_id: str | None = None,
    ) -> Dict[str, Any]:
        try:
            return self.inbox_service.rebuild_inbox(
                generated_for_date=generated_for_date,
                scope_type=scope_type,
                scope_value=scope_value,
                limit=limit,
                actor_id=actor_id,
            )
        except Exception as e:
            return {"success": False, "error": str(e), "batch": None, "items": [], "total": 0}

    def record_inbox_action(
        self,
        item_id: str,
        action_type: str,
        *,
        actor_id: str | None = None,
        payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        try:
            return self.analyst_actions_service.record_action(
                item_id,
                action_type,
                actor_id=actor_id,
                payload=payload,
            )
        except Exception as e:
            return {"success": False, "error": str(e), "action": None, "item": None, "side_effects": []}

    def get_inbox_actions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        target_type: str | None = None,
        target_id: str | None = None,
        inbox_item_id: str | None = None,
    ) -> Dict[str, Any]:
        try:
            return self.analyst_actions_service.list_actions(
                limit=limit,
                offset=offset,
                target_type=target_type,
                target_id=target_id,
                inbox_item_id=inbox_item_id,
            )
        except Exception as e:
            return {"success": False, "error": str(e), "actions": [], "total": 0}

    def rebuild_post_evidence(self, post_id: str) -> Dict[str, Any]:
        job_id = self._start_job_safe(
            "evidence_enrichment",
            trigger="manual",
            message=f"Rebuild evidence for post {post_id}",
            payload={"post_id": post_id},
        )
        try:
            if job_id:
                self._append_job_event_safe(job_id, message=f"Rebuilding evidence for post {post_id}", level="info")
            result = self.evidence_service.rebuild_post_evidence(post_id, job_run_id=job_id)
            self._finish_job_safe(
                job_id,
                status="success",
                message="Evidence rebuilt for post",
                payload=result,
            )
            return {"success": True, "job_id": job_id, "result": result}
        except Exception as e:
            self._finish_job_safe(
                job_id,
                status="failed",
                message=str(e),
                payload={"post_id": post_id},
            )
            return {"success": False, "error": str(e)}

    def rebuild_evidence_for_date(self, date_value: str, limit: int | None = None) -> Dict[str, Any]:
        job_id = self._start_job_safe(
            "evidence_enrichment",
            trigger="manual",
            message=f"Rebuild evidence for date {date_value}",
            payload={"date": date_value, "limit": limit},
        )
        try:
            target_date = date.fromisoformat(date_value)
            if job_id:
                self._append_job_event_safe(job_id, message=f"Rebuilding evidence for date {target_date.isoformat()}", level="info")
            result = self.evidence_service.rebuild_date_evidence(target_date, limit=limit, job_run_id=job_id)
            self._finish_job_safe(
                job_id,
                status="success",
                message="Evidence rebuilt for date",
                payload=result,
            )
            return {"success": True, "job_id": job_id, "result": result}
        except Exception as e:
            self._finish_job_safe(
                job_id,
                status="failed",
                message=str(e),
                payload={"date": date_value, "limit": limit},
            )
            return {"success": False, "error": str(e)}

    def rebuild_post_memory(self, post_id: str) -> Dict[str, Any]:
        job_id = self._start_job_safe(
            "entity_memory",
            trigger="manual",
            message=f"Rebuild entity memory for post {post_id}",
            payload={"post_id": post_id},
        )
        try:
            if job_id:
                self._append_job_event_safe(job_id, message=f"Rebuilding entity memory for post {post_id}", level="info")
            result = self.entity_memory_service.rebuild_post_memory(post_id, job_run_id=job_id)
            self._finish_job_safe(
                job_id,
                status="success",
                message="Entity memory rebuilt for post",
                payload=result,
            )
            return {"success": True, "job_id": job_id, "result": result}
        except Exception as e:
            self._finish_job_safe(
                job_id,
                status="failed",
                message=str(e),
                payload={"post_id": post_id},
            )
            return {"success": False, "error": str(e)}

    def rebuild_memory_for_date(self, date_value: str, limit: int | None = None) -> Dict[str, Any]:
        job_id = self._start_job_safe(
            "entity_memory",
            trigger="manual",
            message=f"Rebuild entity memory for date {date_value}",
            payload={"date": date_value, "limit": limit},
        )
        try:
            target_date = date.fromisoformat(date_value)
            if job_id:
                self._append_job_event_safe(job_id, message=f"Rebuilding entity memory for date {target_date.isoformat()}", level="info")
            result = self.entity_memory_service.rebuild_date_memory(target_date, limit=limit, job_run_id=job_id)
            self._finish_job_safe(
                job_id,
                status="success",
                message="Entity memory rebuilt for date",
                payload=result,
            )
            return {"success": True, "job_id": job_id, "result": result}
        except Exception as e:
            self._finish_job_safe(
                job_id,
                status="failed",
                message=str(e),
                payload={"date": date_value, "limit": limit},
            )
            return {"success": False, "error": str(e)}

    def rebuild_post_events(self, post_id: str) -> Dict[str, Any]:
        job_id = self._start_job_safe(
            "event_memory",
            trigger="manual",
            message=f"Rebuild event memory for post {post_id}",
            payload={"post_id": post_id},
        )
        try:
            if job_id:
                self._append_job_event_safe(job_id, message=f"Rebuilding event memory for post {post_id}", level="info")
            result = self.event_memory_service.rebuild_post_events(post_id, job_run_id=job_id)
            self._finish_job_safe(
                job_id,
                status="success",
                message="Event memory rebuilt for post",
                payload=result,
            )
            return {"success": True, "job_id": job_id, "result": result}
        except Exception as e:
            self._finish_job_safe(
                job_id,
                status="failed",
                message=str(e),
                payload={"post_id": post_id},
            )
            return {"success": False, "error": str(e)}

    def rebuild_events_for_date(self, date_value: str, limit: int | None = None) -> Dict[str, Any]:
        job_id = self._start_job_safe(
            "event_memory",
            trigger="manual",
            message=f"Rebuild event memory for date {date_value}",
            payload={"date": date_value, "limit": limit},
        )
        try:
            target_date = date.fromisoformat(date_value)
            if job_id:
                self._append_job_event_safe(job_id, message=f"Rebuilding event memory for date {target_date.isoformat()}", level="info")
            result = self.event_memory_service.rebuild_date_events(target_date, limit=limit, job_run_id=job_id)
            self._finish_job_safe(
                job_id,
                status="success",
                message="Event memory rebuilt for date",
                payload=result,
            )
            return {"success": True, "job_id": job_id, "result": result}
        except Exception as e:
            self._finish_job_safe(
                job_id,
                status="failed",
                message=str(e),
                payload={"date": date_value, "limit": limit},
            )
            return {"success": False, "error": str(e)}

    def get_post_notes(self, post_id: str) -> Dict[str, Any]:
        try:
            return {"success": True, **self.post_detail_service.get_notes(post_id)}
        except Exception as e:
            return {"success": False, "error": str(e), "post_id": post_id, "notes_markdown": ""}

    def save_post_notes(self, post_id: str, notes_markdown: str) -> Dict[str, Any]:
        try:
            return {"success": True, **self.post_detail_service.save_notes(post_id, notes_markdown)}
        except Exception as e:
            return {"success": False, "error": str(e), "post_id": post_id}

    def get_post_summary(self, post_id: str, refresh: bool = False) -> Dict[str, Any]:
        job_id = self._start_job_safe(
            "post_analysis",
            trigger="manual",
            message=f"Generate summary for post {post_id}",
            payload={"post_id": post_id, "refresh": refresh},
        )
        try:
            self._append_job_event_safe(job_id, message=f"Generating summary for post {post_id}", level="info")
            result = {"success": True, **self.post_detail_service.get_or_generate_summary(post_id, refresh=refresh)}
            self._finish_job_safe(
                job_id,
                status="success",
                message="Post summary ready",
                payload=result,
            )
            return result
        except Exception as e:
            self._finish_job_safe(job_id, status="failed", message=str(e), payload={"post_id": post_id})
            return {"success": False, "error": str(e), "post_id": post_id}

    def chat_about_post(self, post_id: str, question: str) -> Dict[str, Any]:
        job_id = self._start_job_safe(
            "post_chat_message",
            trigger="manual",
            message=f"Chat about post {post_id}",
            payload={"post_id": post_id, "question_chars": len(question or "")},
        )
        try:
            self._append_job_event_safe(job_id, message=f"Submitting post chat prompt for {post_id}", level="info")
            result = self.post_detail_service.chat_about_post(post_id, question)
            self._finish_job_safe(
                job_id,
                status="success" if result.get("success") else "failed",
                message="Post chat response ready" if result.get("success") else result.get("error"),
                payload=result,
            )
            return result
        except Exception as e:
            self._finish_job_safe(job_id, status="failed", message=str(e), payload={"post_id": post_id})
            return {"success": False, "error": str(e), "post_id": post_id}

    async def fetch_reddit_comments(self, post_id: str, *, limit: int = 80, refresh: bool = False) -> Dict[str, Any]:
        job_id = self._start_job_safe(
            "reddit_comments_fetch",
            trigger="manual",
            message=f"Fetch Reddit comments for {post_id}",
            payload={"post_id": post_id, "limit": limit, "refresh": refresh},
        )
        try:
            self._append_job_event_safe(job_id, message=f"Fetching Reddit comments for {post_id}", level="info")
            result = {"success": True, **await self.post_detail_service.fetch_reddit_comments(post_id, limit=limit, refresh=refresh)}
            self._finish_job_safe(
                job_id,
                status="success",
                message=f"Fetched {result.get('comment_count', 0)} comments",
                payload=result,
            )
            return result
        except Exception as e:
            self._finish_job_safe(job_id, status="failed", message=str(e), payload={"post_id": post_id})
            return {"success": False, "error": str(e), "post_id": post_id}

    async def get_reddit_comments_briefing(self, post_id: str, *, limit: int = 80, refresh: bool = False) -> Dict[str, Any]:
        job_id = self._start_job_safe(
            "reddit_comments_briefing",
            trigger="manual",
            message=f"Generate Reddit comments briefing for {post_id}",
            payload={"post_id": post_id, "limit": limit, "refresh": refresh},
        )
        try:
            self._append_job_event_safe(job_id, message=f"Generating Reddit comments briefing for {post_id}", level="info")
            result = {"success": True, **await self.post_detail_service.get_or_generate_reddit_comments_briefing(post_id, limit=limit, refresh=refresh)}
            self._finish_job_safe(
                job_id,
                status="success",
                message="Reddit discussion briefing ready",
                payload=result,
            )
            return result
        except Exception as e:
            self._finish_job_safe(job_id, status="failed", message=str(e), payload={"post_id": post_id})
            return {"success": False, "error": str(e), "post_id": post_id}

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
