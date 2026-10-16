"""The ingestion module (Mark IX): one entry point for every fetch run.

    report = await run_ingestion(FetchRequest(SourceSelector.all(), Trigger.SCHEDULER))

The only callers are main.py (the API routes), scripts/run_scheduler.py and the
scripts/safe_ingest.py CLI shim.

Deliberately import-light: adapters/*.py import ingestion.kinds.base, and importing that
runs this file first. The types are cheap; the runner, the ports and the real adapters are
imported inside the functions, so `import insight_core.adapters` never pulls in the DB
layer or the services through this file.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from insight_core.ingestion.types import (
    FetchRequest,
    OutcomeStatus,
    RunReport,
    SourceSelector,
    Trigger,
)

if TYPE_CHECKING:
    from insight_core.ingestion.ports import ProgressSink
    from insight_core.ingestion.runner import IngestionRunner


def default_runner(db_url: Optional[str] = None) -> "IngestionRunner":
    """The runner with every real port: Db* stores, PgAdvisoryRunLock, availability_from_env
    and the process-wide FetchGates.shared() (call it inside the running event loop).

    This is the composition root, so it is the one place in ingestion/ that wires services
    in: YouTubeService for the youtube_channel kind, and the posts/sources services the
    archive metadata writer reads.
    """
    import os
    from datetime import datetime, timezone

    from insight_core.db.ensure_db import ensure_database
    from insight_core.ingestion.archive_metadata import ArchiveMetadataWriter
    from insight_core.ingestion.gates import FetchGates
    from insight_core.ingestion.http import KindHttp
    from insight_core.ingestion.inspection import DbInspectionRefresher
    from insight_core.ingestion.kinds import KindRegistry
    from insight_core.ingestion.ports import (
        DbFetchStateStore,
        DbPostSaver,
        DbSourceCatalog,
        PgAdvisoryRunLock,
    )
    from insight_core.ingestion.runner import IngestionRunner
    from insight_core.ingestion.schedule import availability_from_env
    from insight_core.services.posts_service import PostsService
    from insight_core.services.sources_service import SourcesService
    from insight_core.services.youtube_service import YouTubeService

    db_url = db_url or os.getenv("DATABASE_URL") or ensure_database()

    def clock() -> datetime:
        return datetime.now(timezone.utc)

    return IngestionRunner(
        catalog=DbSourceCatalog(db_url),
        state=DbFetchStateStore(db_url),
        saver=DbPostSaver(db_url),
        inspections=DbInspectionRefresher(
            writer=ArchiveMetadataWriter(posts=PostsService(db_url), sources=SourcesService(db_url)),
        ),
        registry=KindRegistry.default(KindHttp(), YouTubeService(db_url), db_url=db_url),
        gates=FetchGates.shared(),
        run_lock=PgAdvisoryRunLock(db_url),
        availability=availability_from_env,
        clock=clock,
    )


async def run_ingestion(
    request: FetchRequest,
    *,
    progress: "Optional[ProgressSink]" = None,
    runner: "Optional[IngestionRunner]" = None,
) -> RunReport:
    """Run one fetch run. The caller owns the job: it finishes it with report.to_payload()."""
    from insight_core.ingestion.ports import NULL_PROGRESS

    runner = runner or default_runner()
    return await runner.run(request, progress=progress or NULL_PROGRESS)


__all__ = [
    "FetchRequest",
    "OutcomeStatus",
    "RunReport",
    "SourceSelector",
    "Trigger",
    "default_runner",
    "run_ingestion",
]
