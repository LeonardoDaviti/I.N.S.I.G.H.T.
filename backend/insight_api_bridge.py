# backend/insight_api_bridge.py
from insight_core.db.ensure_db import ensure_database

from insight_core.services.sources_service import SourcesService
from insight_core.services.folders_service import FoldersService
from insight_core.services.posts_service import PostsService
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.services.source_config_sync_service import SourceConfigSyncService
from insight_core.services.system_logs_service import SystemLogsService
from insight_core.services.operations_service import (
    EMPTY_SOURCE_HEALTH,
    OperationsService,
    backlog_posts,
    sources_failing,
)
from insight_core.ingestion import FetchRequest, SourceSelector, Trigger, run_ingestion
from insight_core.ingestion.kinds.base import KindUnavailable
from insight_core.ingestion.ports import JobProgressSink
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.reader_service import ReaderService
from insight_core.services.youtube_service import YouTubeService
from insight_core.services.credentials_service import CredentialsService


from datetime import datetime

from typing import List, Dict, Any


class InsightApiBridge:
    def __init__(self):
        self.db = ensure_database()
        self.sources_service = SourcesService(self.db)
        self.folders_service = FoldersService(self.db)
        self.posts_service = PostsService(self.db)
        self.source_fetch_service = SourceFetchService(self.db)
        self.source_config_sync_service = SourceConfigSyncService(self.db)
        self.system_logs_service = SystemLogsService()
        # One kind registry for the health table and the archive: the same resolution the
        # runner uses (KindRegistry.default), built once.
        self.operations_service = OperationsService(self.db, kinds=self.source_fetch_service.kinds)
        self.post_detail_service = PostDetailService(self.db)
        self.reader_service = ReaderService(self.db)
        self.youtube_service = YouTubeService(self.db)
        self.credentials_service = CredentialsService(self.db)

    # ============= CONNECTIONS (credentials) =============
    # Write-only: these return the CredentialsService views, never a value.

    def get_credentials(self) -> Dict[str, Any]:
        return self.credentials_service.list()

    def put_credential(self, provider: str, key: str, value: Any) -> Dict[str, Any]:
        return self.credentials_service.put(provider, key, value)

    def delete_credential(self, provider: str, key: str) -> Dict[str, Any]:
        return self.credentials_service.delete(provider, key)

    async def test_credentials(self, provider: str) -> Dict[str, Any]:
        return await self.credentials_service.test(provider)

    async def telegram_login_start(self, phone: Any) -> Dict[str, Any]:
        return await self.credentials_service.login_start(phone)

    async def telegram_login_code(self, code: Any) -> Dict[str, Any]:
        return await self.credentials_service.login_code(code)

    async def telegram_login_password(self, password: Any) -> Dict[str, Any]:
        return await self.credentials_service.login_password(password)

    def telegram_login_cancel(self) -> Dict[str, Any]:
        return self.credentials_service.login_cancel()

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

    def _export_sources_json(self) -> None:
        try:
            self.source_config_sync_service.sync_db_to_json()
        except Exception:
            # Source mutations should still succeed even if the file export fails.
            pass
    
    # ============= SOURCES MANAGEMENT =============

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
    
    def delete_source(self, source_id: str) -> bool:
        """Remove source from database."""
        deleted = self.sources_service.delete_source(source_id)
        if deleted:
            self._export_sources_json()
        return deleted

    def add_source_with_settings(
        self, platform: str, handle: str, settings: Dict[str, Any] | None, enabled: bool
    ) -> Dict[str, Any]:
        """Add a single source (non-destructive), apply settings, and set enabled state."""
        try:
            added = self.sources_service.add_source(platform, handle)
            source_id = added["source_id"]
            if settings:
                self.sources_service.update_source_settings(source_id, settings)
            self.sources_service.update_source_status(source_id, enabled)
            self._export_sources_json()
            return {"success": True, "source_id": source_id, "platform": platform, "handle_or_url": handle}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_source_enabled(self, source_id: str, enabled: bool) -> Dict[str, Any]:
        """Enable/disable a single source (durable to sources.json)."""
        try:
            self.sources_service.update_source_status(source_id, enabled)
            self._export_sources_json()
            return {"success": True, "source_id": source_id, "enabled": enabled}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_source_api(self, source_id: str) -> Dict[str, Any]:
        """Delete a single source, returning an API envelope."""
        try:
            deleted = self.delete_source(source_id)
            if not deleted:
                return {"success": False, "error": f"Source {source_id} not found"}
            return {"success": True, "deleted": True, "source_id": source_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============= FOLDERS =============

    def get_folders(self) -> Dict[str, Any]:
        """List folders with source and post counts."""
        try:
            folders = self.folders_service.list_folders()
            return {"success": True, "folders": folders, "total": len(folders)}
        except Exception as e:
            return {"success": False, "error": str(e), "folders": []}

    def create_folder(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create a folder from a config dict."""
        try:
            name = str(config.get("name") or "").strip()
            if not name:
                return {"success": False, "error": "Folder name is required", "folder": None}
            folder = self.folders_service.create_folder(
                name=name,
                description=config.get("description"),
                sort_order=int(config.get("sort_order", 999)),
                kind=str(config.get("kind") or "folder"),
                exclude_from_main_digest=bool(config.get("exclude_from_main_digest", False)),
                match_keywords=config.get("match_keywords") or [],
            )
            return {"success": True, "folder": folder}
        except Exception as e:
            return {"success": False, "error": str(e), "folder": None}

    async def ingest_folder_now(
        self, folder_id: str, limit: int | None = None, *, job_id: str | None = None
    ) -> Dict[str, Any]:
        """Fetch every enabled source in a folder/track now (forced), through the ingestion runner."""
        request = FetchRequest(SourceSelector.folder(folder_id), Trigger.MANUAL, force=True, limit=limit)
        return await self.run_ingestion_job(request, job_id=job_id)

    def get_folder_posts(
        self, folder_id: str, limit: int = 50, offset: int = 0, since_days: int | None = None
    ) -> Dict[str, Any]:
        """Reading feed for one folder/track: newest posts from its sources."""
        try:
            folder = self.folders_service.get_folder(folder_id)
            if not folder:
                return {"success": False, "error": f"Folder {folder_id} not found", "posts": []}
            source_ids = self.folders_service.list_source_ids(folder_id)
            feed = self.posts_service.get_folder_feed(
                source_ids, limit=limit, offset=offset, since_days=since_days
            )
            return {"success": True, "folder": folder, "source_count": len(source_ids), **feed}
        except Exception as e:
            return {"success": False, "error": str(e), "posts": []}

    def set_source_main_digest(self, source_id: str, in_main_digest: bool) -> Dict[str, Any]:
        """Include/exclude one source from the main digests."""
        try:
            return {"success": True, **self.sources_service.set_in_main_digest(source_id, in_main_digest)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_folder_main_digest(self, folder_id: str, in_main_digest: bool) -> Dict[str, Any]:
        """Apply the digest switch to every source in a folder/track, and record the intent."""
        try:
            result = self.sources_service.set_folder_in_main_digest(folder_id, in_main_digest)
            # Keep the folder's declared intent in step with what was applied.
            self.folders_service.update_folder(
                folder_id, {"exclude_from_main_digest": not in_main_digest}
            )
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_folder(self, folder_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Update folder fields."""
        try:
            folder = self.folders_service.update_folder(folder_id, fields)
            return {"success": True, "folder": folder}
        except ValueError as e:
            return {"success": False, "error": str(e), "folder": None}
        except Exception as e:
            return {"success": False, "error": str(e), "folder": None}

    def delete_folder(self, folder_id: str) -> Dict[str, Any]:
        """Delete a folder."""
        try:
            deleted = self.folders_service.delete_folder(folder_id)
            if not deleted:
                return {"success": False, "error": f"Folder {folder_id} not found"}
            return {"success": True, "deleted": True, "folder_id": folder_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_folder_sources(self, folder_id: str) -> Dict[str, Any]:
        """List the sources attached to a folder."""
        try:
            sources = self.folders_service.list_sources(folder_id)
            return {"success": True, "sources": sources, "total": len(sources)}
        except Exception as e:
            return {"success": False, "error": str(e), "sources": []}

    def get_source_folders(self, source_id: str) -> Dict[str, Any]:
        """List the folder ids a source belongs to."""
        try:
            folder_ids = self.folders_service.list_folders_for_source(source_id)
            return {"success": True, "folder_ids": folder_ids}
        except Exception as e:
            return {"success": False, "error": str(e), "folder_ids": []}

    def add_source_to_folder(self, folder_id: str, source_id: str) -> Dict[str, Any]:
        """Attach a source to a folder."""
        try:
            added = self.folders_service.add_source(folder_id, source_id)
            return {"success": True, "added": added, "folder_id": folder_id, "source_id": source_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def remove_source_from_folder(self, folder_id: str, source_id: str) -> Dict[str, Any]:
        """Detach a source from a folder."""
        try:
            removed = self.folders_service.remove_source(folder_id, source_id)
            return {"success": True, "removed": removed, "folder_id": folder_id, "source_id": source_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============= SYSTEM STATUS =============

    def get_status(self) -> Dict[str, Any]:
        """Unified machine-readable system state for agents and observability."""
        counts = self.operations_service.get_database_counts()
        freshness = self.operations_service.get_corpus_freshness()
        scheduler = self.operations_service.get_scheduler_config()
        jobs = self.operations_service.list_recent_jobs(20)
        health_summary = self.operations_service.get_source_health()["summary"]
        all_sources = self.sources_service.get_all_sources()
        folders = self.folders_service.list_folders()

        return {
            "success": True,
            "healthy": True,
            "generated_at": datetime.now().isoformat(),
            "corpus": {**counts, "total_sources": len(all_sources), **freshness},
            "scheduler": scheduler,
            "folders": [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "source_count": f.get("source_count", 0),
                    "post_count": f.get("post_count", 0),
                }
                for f in folders
            ],
            "recent_jobs": [
                {
                    "id": j["id"],
                    "job_type": j.get("job_type", ""),
                    "status": j.get("status", ""),
                    "started_at": j.get("started_at"),
                    "finished_at": j.get("finished_at"),
                    "message": j.get("message"),
                }
                for j in jobs
            ],
            "source_health_summary": {
                "monitored": sum(health_summary.values()),
                # Failing sources: retrying now or waiting in backoff.
                "errors": sources_failing(health_summary),
            },
        }


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
            kinds = self.source_fetch_service.kinds
            catalog = []
            for source in sources:
                if not source.get("enabled"):
                    continue
                archive = (source.get("settings") or {}).get("archive", {})
                stored = int(archive.get("stored_posts") or source.get("post_count") or 0)
                catalog.append(
                    {
                        "source_id": source["id"],
                        "display_name": (source.get("settings") or {}).get("display_name") or source["handle_or_url"],
                        "platform": source["platform"],
                        "kind": kinds.resolve(source).name,
                        "enabled": bool(source.get("enabled")),
                        "stored_posts": stored,
                        "available_posts": archive.get("available_posts"),
                        # E1: the backlog is available - stored, or None when unknown; the
                        # plan's remaining_posts is a requested target, never aliased to it.
                        "backlog_posts": backlog_posts(archive.get("available_posts"), stored),
                        "remaining_posts": archive.get("remaining_posts"),
                        "estimated_seconds": archive.get("estimated_seconds"),
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
        except KindUnavailable as e:
            return {"success": False, "error": e.reason, "unavailable": True}
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
        job_id: str | None = None,
    ) -> Dict[str, Any]:
        """Archive posts for a single source into the shared posts table.

        With job_id (the route already started the job) progress lands on that job;
        otherwise the run starts its own archive_source job.
        """
        job_id = job_id or self._start_job_safe(
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
            # An archive run is not a live fetch: it does not touch source_fetch_state, so
            # paging old posts can neither delay the next live fetch nor reset its backoff.
            # Its own status lives in settings.archive.
            self._finish_job_safe(
                job_id,
                status="success" if result.get("success") else "failed",
                message=result.get("error") or f"Archived {result.get('posts_fetched', 0)} posts",
                payload=result,
            )
            return result
        except KindUnavailable as e:
            self._finish_job_safe(job_id, status="failed", message=f"Unavailable: {e.reason}",
                                  payload={"source_id": source_id, "unavailable": True})
            return {"success": False, "error": e.reason, "unavailable": True, "source_id": source_id}
        except Exception as e:
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

    def archive_support(self, source_id: str) -> Dict[str, Any]:
        """Whether the source can archive and what its available count means (no network)."""
        return self.source_fetch_service.archive_support(source_id)

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
                "support": self._archive_support_or_none(source_id),
                # The newest archive job: a running one the sheet attaches to, or the last result.
                "latest_job": self._latest_archive_job_or_none(source_id),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "source_id": source_id,
            }

    def _latest_archive_job_or_none(self, source_id: str) -> Dict[str, Any] | None:
        try:
            return self.operations_service.latest_job_for_source("archive_source", source_id)
        except Exception:
            return None

    def _archive_support_or_none(self, source_id: str) -> Dict[str, Any] | None:
        try:
            return self.archive_support(source_id)
        except Exception:
            return None

    async def fetch_source_now(self, source_id: str, limit: int | None = None, *, job_id: str | None = None) -> Dict[str, Any]:
        """Fetch one source now (forced, even when disabled), through the ingestion runner."""
        request = FetchRequest(SourceSelector.source(source_id), Trigger.MANUAL, force=True, limit=limit)
        return await self.run_ingestion_job(request, job_id=job_id)

    async def run_ingestion_cycle(self, force: bool = False, *, job_id: str | None = None) -> Dict[str, Any]:
        """The manual "Run cycle": every enabled source, due ones only unless forced."""
        request = FetchRequest(SourceSelector.all(), Trigger.MANUAL, force=bool(force))
        return await self.run_ingestion_job(request, job_id=job_id)

    async def run_ingestion_job(self, request: FetchRequest, *, job_id: str | None = None) -> Dict[str, Any]:
        """run_ingestion with job progress; the job is finished in every case. Returns the report payload."""
        status, message, payload = "failed", "Ingestion run did not finish", {}
        try:
            report = await run_ingestion(request, progress=JobProgressSink(self.operations_service, job_id))
            status, message, payload = report.job_status, report.summary_line(), report.to_payload()
            return payload
        except Exception as e:
            message = f"Ingestion run failed: {e}"
            payload = {"success": False, "error": str(e), "selector": request.selector.as_dict()}
            return payload
        finally:
            self._finish_job_safe(job_id, status=status, message=message, payload=payload, compact=True)

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

    # ============= POSTS RETRIEVAL =============

    def get_posts_by_source(
        self,
        source_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Get posts for a specific source from database.

        Args:
            source_id: UUID of the source
            limit: Optional page size
            offset: Page offset
            
        Returns:
            Dict with success, posts, source_id, total
        """
        try:
            posts = self.posts_service.get_posts_by_source(source_id, limit=limit, offset=offset)
            total = self.posts_service.get_source_post_stats(source_id).get("post_count", 0)
            current_offset = max(0, int(offset or 0))
            has_more = current_offset + len(posts) < int(total)
            
            return {
                "success": True,
                "posts": posts,
                "source_id": source_id,
                "total": int(total),
                "returned": len(posts),
                "offset": current_offset,
                "limit": limit,
                "has_more": has_more,
            }
            
        except Exception as e:
            # Database or other errors
            return {
                "success": False,
                "error": str(e),
                "posts": [],
                "total": 0,
                "returned": 0,
                "offset": max(0, int(offset or 0)),
                "limit": limit,
                "has_more": False,
                "source_id": source_id,
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

    def get_scheduler_config(self) -> Dict[str, Any]:
        try:
            scheduler = self.operations_service.get_scheduler_config()
            try:
                scheduler["state"] = self.operations_service.get_scheduler_state()
            except Exception:
                scheduler["state"] = {}
            return {"success": True, "scheduler": scheduler}
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
            return {"success": False, "error": str(e), "jobs": [], "source_health": EMPTY_SOURCE_HEALTH, "alerts": []}

    def get_sources_health(self) -> Dict[str, Any]:
        """SourcesHealthResponse. New-endpoint contract: errors propagate to the route."""
        return self.operations_service.get_source_health()

    def set_cadence_override(self, source_id: str, hours: float | None) -> Dict[str, Any]:
        """Write the cadence override; LookupError for an unknown source."""
        return {"success": True, "row": self.operations_service.set_cadence_override(source_id, hours)}

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
            reader_state = self.post_detail_service.get_post_reader_state(post_id)
            return {"success": True, "post": post, "reader_state": reader_state}
        except Exception as e:
            return {"success": False, "error": str(e), "post": None, "reader_state": None}

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

    # ============= READER (Mark IX) =============
    # New endpoints: errors propagate (the route maps them to 400/500 with a clean detail)
    # instead of being wrapped in {success: false}.

    def get_feed(self, scope, *, filter: str, view: str, cursor, limit: int, days: int | None) -> Dict[str, Any]:
        return self.reader_service.feed(scope, filter=filter, view=view, cursor=cursor, limit=limit, days=days)

    def get_unread_counts(self) -> Dict[str, Any]:
        return self.reader_service.unread_counts()

    def mark_read_through(self, scope, through, newest) -> Dict[str, Any]:
        return self.reader_service.mark_read_through(scope, through, newest)

    def set_posts_read(self, post_ids: List[str], read: bool) -> Dict[str, Any]:
        return {"success": True, "updated": self.reader_service.set_read(post_ids, read)}

    def set_post_read(self, post_id: str, read: bool) -> Dict[str, Any]:
        updated = self.reader_service.set_read([post_id], read)
        return {"success": True, "post_id": post_id, "updated": updated}

    # ============= REDDIT COMMENTS =============

    async def fetch_reddit_comments(self, post_id: str, *, limit: int = 80, refresh: bool = False, job_id: str | None = None) -> Dict[str, Any]:
        job_id = job_id or self._start_job_safe(
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
