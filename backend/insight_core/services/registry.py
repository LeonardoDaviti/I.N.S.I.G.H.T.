"""The services the API routes call, built once per process.

    from insight_core.services.registry import services
    services().reader.list_posts(...)

`services()` builds every service on first use, from DATABASE_URL (ensure_database) and the
environment, and hands back the same `Services` after that. Tests swap the whole set with
`use(...)`: real services against the scratch database, or a stand-in object with only the
attributes the route under test touches.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Services:
    db_url: str
    sources: Any
    folders: Any
    posts: Any
    source_fetch: Any
    source_config_sync: Any
    system_logs: Any
    operations: Any
    post_detail: Any
    reader: Any
    youtube: Any
    credentials: Any
    media_proxy: Any
    saved: Any


def build_services(db_url: Optional[str] = None) -> Services:
    from insight_core.db.ensure_db import ensure_database
    from insight_core.services.credentials_service import CredentialsService
    from insight_core.services.folders_service import FoldersService
    from insight_core.services.media_proxy_service import MediaProxyService
    from insight_core.services.operations_service import OperationsService
    from insight_core.services.post_detail_service import PostDetailService
    from insight_core.services.posts_service import PostsService
    from insight_core.services.reader_service import ReaderService
    from insight_core.services.saved_service import SavedService
    from insight_core.services.source_config_sync_service import SourceConfigSyncService
    from insight_core.services.source_fetch_service import SourceFetchService
    from insight_core.services.sources_service import SourcesService
    from insight_core.services.system_logs_service import SystemLogsService
    from insight_core.services.youtube_service import YouTubeService

    db_url = db_url or ensure_database()
    source_fetch = SourceFetchService(db_url)
    sources = SourcesService(db_url)
    source_config_sync = SourceConfigSyncService(db_url)
    return Services(
        db_url=db_url,
        sources=sources,
        folders=FoldersService(db_url),
        posts=PostsService(db_url),
        source_fetch=source_fetch,
        source_config_sync=source_config_sync,
        system_logs=SystemLogsService(),
        # One kind registry for the health table and the archive: the same resolution the
        # runner uses (KindRegistry.default), built once.
        operations=OperationsService(db_url, kinds=source_fetch.kinds),
        post_detail=PostDetailService(db_url),
        reader=ReaderService(db_url),
        youtube=YouTubeService(db_url),
        credentials=CredentialsService(db_url),
        media_proxy=MediaProxyService(db_url),
        saved=SavedService(db_url, sources=sources, source_config_sync=source_config_sync, kinds=source_fetch.kinds),
    )


_current: Optional[Services] = None


def services() -> Services:
    global _current
    if _current is None:
        _current = build_services()
    return _current


def use(replacement: Any) -> Any:
    """Swap the services every route sees; returns the previous set (None if not built yet)."""
    global _current
    previous, _current = _current, replacement
    return previous
