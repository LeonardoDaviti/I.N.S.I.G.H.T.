"""
Business logic for source management.
Handles CRUD operations for sources table.
"""
import urllib.parse
from typing import Any, Dict, List, Tuple

import psycopg

from insight_core.db import database as db
from insight_core.db.repo_fetch_state import FetchStateRepository
from insight_core.db.repo_sources import SourcesRepository
from insight_core.ingestion.kinds.page_watch import normalise_prefix
from insight_core.ingestion.kinds.parsing import web_address
from insight_core.logs.core.logger_config import get_component_logger

def _valid_page_watch(value: Any) -> Dict[str, Any]:
    """settings.page_watch (issue 0028): {} or {"prefix": "/news/"}."""
    if not isinstance(value, dict):
        raise ValueError("page_watch must be an object")
    prefix = value.get("prefix")
    return {"prefix": normalise_prefix(prefix)} if prefix else {}


class SourcesService:
    """Manages sources (add, update, delete, list)."""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = SourcesRepository(db_url)
        self.logger = get_component_logger("sources_service")
    
    def get_all_sources(self) -> List[Dict[str, Any]]:
        """Get all sources from database."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_all_sources(cur)
    
    def removed_sources(self) -> Dict[Tuple[str, str], Any]:
        """{(platform, handle_or_url): removed_at} of the addresses removed (or switched away
        from) and not added again (issue 0072)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.removed(cur)

    def get_source_by_id(self, source_id: str) -> Dict[str, Any] | None:
        """Get a single source by UUID."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_source_by_id(cur, source_id)
    
    def update_source_status(self, source_id: str, enabled: bool) -> Dict[str, Any]:
        """Enable or disable a source."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                success = self.repo.update_enabled(cur, source_id, enabled)
                conn.commit()
                
                if success:
                    self.logger.info(f"Source {source_id} → enabled={enabled}")
                    return {"source_id": source_id, "enabled": enabled}
                else:
                    raise LookupError(f"Source {source_id} not found")
    
    def set_in_main_digest(self, source_id: str, in_main_digest: bool) -> Dict[str, Any]:
        """Include/exclude a single source from the main digests."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                ok = self.repo.set_in_main_digest(cur, source_id, in_main_digest)
                conn.commit()
                if not ok:
                    raise LookupError(f"Source {source_id} not found")
                self.logger.info(f"Source {source_id} -> in_main_digest={in_main_digest}")
                return {"source_id": source_id, "in_main_digest": in_main_digest}

    def set_folder_in_main_digest(self, folder_id: str, in_main_digest: bool) -> Dict[str, Any]:
        """Apply the digest switch to every source in a folder/track."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                changed = self.repo.set_in_main_digest_for_folder(cur, folder_id, in_main_digest)
                conn.commit()
                self.logger.info(f"Folder {folder_id} -> in_main_digest={in_main_digest} ({changed} sources)")
                return {"folder_id": folder_id, "in_main_digest": in_main_digest, "sources_updated": changed}

    def add_source(self, platform: str, handle: str, *, in_main_digest: bool = True) -> Dict[str, Any]:
        """Add new source to database. ValueError when it is already a source."""
        return self._add(platform, handle, in_main_digest=in_main_digest)

    def _add(self, platform: str, handle: str, *, in_main_digest: bool = True,
             settings: Dict[str, Any] | None = None, enabled: bool = True) -> Dict[str, Any]:
        """Insert one source with its first settings and state in one transaction: a bad
        value or a failure leaves no row behind."""
        handle = (handle or "").strip()
        if not handle:
            raise ValueError("handle_or_url is required")
        settings = self._valid_settings(settings or {})
        try:
            with db.transaction(self.db_url) as cur:
                source_id = self.repo.insert_source(cur, platform, handle, in_main_digest=in_main_digest)
                if settings:
                    self.repo.merge_source_settings(cur, source_id, settings)
                if not enabled:
                    self.repo.update_enabled(cur, source_id, False)
        except psycopg.errors.UniqueViolation:
            raise ValueError(f"{platform}/{handle} is already a source") from None
        self.logger.info(f"Added source: {platform}/{handle}")
        return {"source_id": source_id, "platform": platform, "handle": handle}

    def switch_source(self, source_id: str, url: str, page_watch: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Point a source at a new address (issue 0036): a feed, or a page to follow
        (page_watch {} or {"prefix"}). One transaction: the address, settings.page_watch, and
        a clean fetch state (no failures, no backoff, no doctor finding). The id, name, tracks,
        read state and posts stay; posts match by URL, so nothing is duplicated.
        Returns the old {handle_or_url, page_watch}. LookupError for no such source,
        ValueError for a bad address or one that is already a source."""
        handle = web_address(url, "An address is needed to switch to")
        if urllib.parse.urlparse(handle).scheme.lower() not in ("http", "https"):
            raise ValueError("A source can only switch to an http or https address")
        if page_watch is not None:
            page_watch = _valid_page_watch(page_watch)
        try:
            with db.transaction(self.db_url) as cur:
                old = self.repo.get_source_by_id(cur, source_id)
                if old is None or not self.repo.set_address(cur, source_id, handle, page_watch):
                    raise LookupError(f"Source {source_id} not found")
                FetchStateRepository().clear_failures(cur, source_id,
                                                      new_address=old["handle_or_url"] != handle)
                # The address it left is no source now: an import never adds it back (issue 0072).
                if old["handle_or_url"] != handle:
                    self.repo.remember_removed(cur, old["platform"], old["handle_or_url"])
                self.repo.forget_removed(cur, old["platform"], handle)
        except psycopg.errors.UniqueViolation:
            raise ValueError(f"{handle} is already a source") from None
        self.logger.info(f"Switched source {source_id}: {old['handle_or_url']} -> {handle}")
        return {"handle_or_url": old["handle_or_url"], "page_watch": (old.get("settings") or {}).get("page_watch")}

    def delete_source(self, source_id: str) -> bool:
        """Delete source (and cascade delete its posts). The cascade can run for minutes: the process's statement
        timeout, not a request's (issue 0188)."""
        with db.long_statements(), db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                deleted = self.repo.delete_source(cur, source_id)
                conn.commit()
                if deleted:
                    self.logger.info(f"Deleted source: {source_id}")
                return deleted
    
    def get_sources_with_post_counts(self) -> List[Dict[str, Any]]:
        """Get all sources with their post counts."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_sources_with_post_counts(cur)
    
    def get_source_with_settings(self, source_id: str) -> Dict[str, Any]:
        """Get source with merged settings (platform defaults + overrides)."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                # Get source basic info
                sources = self.repo.get_all_sources(cur)
                source = next((s for s in sources if s["id"] == source_id), None)
                
                if not source:
                    raise LookupError(f"Source {source_id} not found")
                
                # Get merged settings
                settings = self.repo.get_source_settings(cur, source_id)
                
                return {
                    **source,
                    "settings": settings
                }
    
    def get_all_sources_with_settings(self) -> List[Dict[str, Any]]:
        """Get all sources with their merged settings and post counts."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                sources_with_counts = self.repo.get_sources_with_post_counts(cur)
                
                # Add settings to each source
                for source in sources_with_counts:
                    source["settings"] = self.repo.get_source_settings(cur, source["id"])
                
                return sources_with_counts

    def list_sources(self) -> List[Dict[str, Any]]:
        """GET /api/sources (issue 0105): every source with its settings and post count, as
        get_all_sources_with_settings, without each source's archive history (kept in the database:
        the source's own settings and the archive status still read it)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            sources = self.repo.get_sources_with_post_counts(cur)
            settings = self.repo.listed_settings(cur)
        for source in sources:
            source["settings"] = settings.get(source["id"], {})
        return sources

    def update_source_settings(self, source_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update settings for a source.
        Validates settings before updating.
        """
        validated_settings = self._valid_settings(settings)
        with db.connection(self.db_url) as conn:
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
                    raise LookupError(f"Source {source_id} not found")

    @staticmethod
    def _valid_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
        """The settings a user may set, the numbers parsed. ValueError for a value that is not a number.

        Posts per fetch is not one of them: it is the kind's own number (issue 0027)."""
        valid_keys = {"display_name", "fetch_delay_seconds", "priority", "page_watch", "watch_changes"}
        validated = {k: v for k, v in settings.items() if k in valid_keys}
        # Watch for changes (issue 0039): re-read its stored pages now and then. Off by default.
        if "watch_changes" in validated and not isinstance(validated["watch_changes"], bool):
            raise ValueError("watch_changes must be true or false")
        if "page_watch" in validated:
            validated["page_watch"] = _valid_page_watch(validated["page_watch"])
        for key in ("fetch_delay_seconds", "priority"):
            if key in validated:
                try:
                    validated[key] = int(validated[key])
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be a whole number") from None
        return validated

    def name_if_unnamed(self, source_id: str, name: str) -> bool:
        """Name a source that has no name (issue 0178: what its feed or page calls itself); a name the owner set
        is never written over. True when it was named."""
        name = " ".join(str(name or "").split())
        if not name:
            return False
        with db.transaction(self.db_url) as cur:
            named = self.repo.name_if_unnamed(cur, source_id, name)
        if named:
            self.logger.info(f"Named source {source_id}: {name}")
        return named

    def merge_source_settings(self, source_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Merge internal settings payloads, including archive metadata."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                merged_settings = self.repo.merge_source_settings(cur, source_id, settings)
                conn.commit()

                if merged_settings is None:
                    raise LookupError(f"Source {source_id} not found")

                self.logger.info(f"Merged internal settings for source {source_id}")
                return {
                    "source_id": source_id,
                    "settings": merged_settings,
                }

    def add_with_settings(self, platform: str, handle: str, *, settings: Dict[str, Any] | None = None,
                          enabled: bool = True) -> Dict[str, Any]:
        """Add one source with its first settings and state (POST /api/sources), all or nothing."""
        return self._add(platform, handle, settings=settings, enabled=enabled)
