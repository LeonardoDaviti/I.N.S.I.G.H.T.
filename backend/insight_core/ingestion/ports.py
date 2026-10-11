"""The ingestion runner's ports (Protocols) and their real adapters (spec §A.1, §3).

The runner sees only the Protocols. Each Db* adapter opens one connection per method call,
does its work and commits, so the runner makes one store call per phase (through
asyncio.to_thread) rather than holding a connection across a fetch. The test adapters live
in tests/_ingestion_fakes.py.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
)

import psycopg

from insight_core.db.repo_fetch_state import FetchStateRepository, FetchStateRow
from insight_core.db.repo_posts import PostDraft, PostsRepository, SaveBatchResult
from insight_core.ingestion.schedule import FetchDecision, backoff_delay
from insight_core.ingestion.types import FetchOutcome, SourceSelector, Trigger

logger = logging.getLogger("insight.ingestion.ports")

Source = Mapping[str, Any]
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- protocols


class SourceCatalog(Protocol):
    def load(self, selector: SourceSelector) -> List[Dict[str, Any]]: ...


class FetchStateStore(Protocol):
    def load(self, source_ids: Sequence[str]) -> Dict[str, FetchStateRow]: ...

    def record_decisions(self, decisions: Sequence[tuple[str, FetchDecision]], *,
                         now: Optional[datetime] = None) -> None: ...

    def record_outcomes(self, outcomes: Sequence[FetchOutcome], *, trigger: Trigger | str,
                        now: Optional[datetime] = None,
                        backoff: Optional[Callable[[int], timedelta]] = None) -> List[FetchStateRow]: ...


class PostSaver(Protocol):
    def save(self, drafts: Sequence[PostDraft]) -> SaveBatchResult: ...


class InspectionRefresher(Protocol):
    async def refresh(self, source: Source, kind: Any, fetched_posts: int) -> None: ...


class RunLock(Protocol):
    def try_acquire(self) -> contextlib.AbstractAsyncContextManager[bool]: ...


class ProgressSink(Protocol):
    def event(self, phase: str, data: dict) -> None: ...


# --------------------------------------------------------------------------- progress


class _NullProgress:
    def event(self, phase: str, data: dict) -> None:
        return None


NULL_PROGRESS: ProgressSink = _NullProgress()

# Rough job progress per phase, so the Operations panel's bar moves.
_PHASE_PROGRESS = {"decided": 10.0, "fetched": 60.0, "saved": 80.0, "inspected": 100.0}


class JobProgressSink:
    """Appends each phase to a job_runs row. Never raises: progress is not worth a run."""

    def __init__(self, operations_service: Any, job_id: Optional[str]) -> None:
        self.ops = operations_service
        self.job_id = job_id

    def event(self, phase: str, data: dict) -> None:
        if not self.job_id:
            return
        try:
            self.ops.append_job_event(
                self.job_id,
                message=f"Ingestion {phase}",
                level="info",
                progress=_PHASE_PROGRESS.get(phase),
                payload={"phase": phase, **(data or {})},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record ingestion progress (%s): %s", phase, exc)


# --------------------------------------------------------------------------- catalog


class DbSourceCatalog:
    """One query per load (SourcesRepository.load_for_ingestion); settings merged with defaults."""

    def __init__(self, db_url: str, repo: Any = None) -> None:
        self.db_url = db_url
        if repo is None:
            from insight_core.db.repo_sources import SourcesRepository

            repo = SourcesRepository(db_url)
        self.repo = repo

    def load(self, selector: SourceSelector) -> List[Dict[str, Any]]:
        if selector.kind != "all":
            try:
                uuid.UUID(str(selector.id))
            except (TypeError, ValueError):
                return []
        with psycopg.connect(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.load_for_ingestion(cur, selector.kind, selector.id)


# --------------------------------------------------------------------------- fetch state


class DbFetchStateStore:
    """FetchStateRepository with connection handling, a clock and the backoff ladder.

    `now` and `backoff` default to the injected clock and ladder; the runner passes its own
    (FixedClock-driven now, a backoff bound to its `rand`), so a run records one timestamp.
    """

    def __init__(
        self,
        db_url: str,
        repo: Optional[FetchStateRepository] = None,
        *,
        clock: Clock = utc_now,
        backoff: Callable[[int], timedelta] = backoff_delay,
    ) -> None:
        self.db_url = db_url
        self.repo = repo or FetchStateRepository()
        self.clock = clock
        self.backoff = backoff

    def load(self, source_ids: Sequence[str]) -> Dict[str, FetchStateRow]:
        with psycopg.connect(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.load(cur, source_ids)

    def record_decisions(self, decisions: Sequence[tuple[str, FetchDecision]], *,
                         now: Optional[datetime] = None) -> None:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self.repo.record_decisions(cur, decisions, now or self.clock())
            conn.commit()

    def record_outcome(self, outcome: FetchOutcome, *, trigger: Trigger | str,
                       now: Optional[datetime] = None,
                       backoff: Optional[Callable[[int], timedelta]] = None) -> FetchStateRow:
        return self.record_outcomes([outcome], trigger=trigger, now=now, backoff=backoff)[0]

    def record_outcomes(self, outcomes: Sequence[FetchOutcome], *, trigger: Trigger | str,
                        now: Optional[datetime] = None,
                        backoff: Optional[Callable[[int], timedelta]] = None) -> List[FetchStateRow]:
        if not outcomes:
            return []
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                rows = self.repo.record_outcomes(
                    cur, outcomes, trigger=trigger, now=now or self.clock(), backoff=backoff or self.backoff
                )
            conn.commit()
        return rows

    def refresh_cadence(self) -> int:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                updated = self.repo.refresh_cadence(cur)
            conn.commit()
        return updated


# --------------------------------------------------------------------------- saver


class DbPostSaver:
    """PostsRepository.save_batch on a fresh connection (save_batch owns the transaction)."""

    def __init__(self, db_url: str, repo: Optional[PostsRepository] = None) -> None:
        self.db_url = db_url
        self.repo = repo or PostsRepository(db_url)

    def save(self, drafts: Sequence[PostDraft]) -> SaveBatchResult:
        if not drafts:
            return SaveBatchResult()
        with psycopg.connect(self.db_url) as conn:
            return self.repo.save_batch(conn, drafts)


# --------------------------------------------------------------------------- run lock


RUN_LOCK_KEY = "insight.ingestion_run"


class PgAdvisoryRunLock:
    """pg_try_advisory_lock on a dedicated connection held for the whole run.

    A session-level lock, so it is released when the connection closes even if the unlock
    is never reached (a killed process frees it with its backend).
    """

    def __init__(self, db_url: str, key: str = RUN_LOCK_KEY) -> None:
        self.db_url = db_url
        self.key = key

    def _acquire(self):
        conn = psycopg.connect(self.db_url, autocommit=True)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (self.key,))
                acquired = bool(cur.fetchone()[0])
        except Exception:
            conn.close()
            raise
        return conn, acquired

    def _release(self, conn, acquired: bool) -> None:
        try:
            if acquired:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (self.key,))
        finally:
            conn.close()

    @contextlib.asynccontextmanager
    async def try_acquire(self) -> AsyncIterator[bool]:
        conn, acquired = await asyncio.to_thread(self._acquire)
        try:
            yield acquired
        finally:
            await asyncio.to_thread(self._release, conn, acquired)
