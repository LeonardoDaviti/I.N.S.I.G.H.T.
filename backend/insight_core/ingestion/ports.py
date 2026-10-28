"""The ingestion runner's ports (Protocols) and their real adapters (spec §A.1, §3).

The runner sees only the Protocols. Each Db* adapter takes a pooled connection
(insight_core.db.database) per method call, does its work and commits, so the runner makes
one store call per phase (through asyncio.to_thread) rather than holding a connection across
a fetch. The test adapters live
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

from insight_core.db import database as db
from insight_core.db.repo_fetch_state import FetchStateRepository, FetchStateRow
from insight_core.db.repo_posts import PostDraft, PostsRepository, SaveBatchResult
from insight_core.ingestion.http import Validators
from insight_core.ingestion.page_changes import PageCheck, WatchedPage
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

    def load_validators(self, source_ids: Sequence[str]) -> Dict[str, Dict[str, Validators]]: ...

    def save_validators(self, source_id: str, validators: Mapping[str, Validators]) -> None: ...


class PostSaver(Protocol):
    def save(self, drafts: Sequence[PostDraft]) -> SaveBatchResult: ...


class PageWatchStore(Protocol):
    """Watched pages (issue 0039): which of a source's are due a check, and what each check found."""

    def due(self, source_id: str, *, now: datetime, limit: int) -> List[WatchedPage]: ...

    def checked(self, source_id: str, checks: Sequence[PageCheck], *, now: datetime) -> None: ...


class InspectionRefresher(Protocol):
    """Records a fetched source's archive metadata. Never raises."""

    async def refresh(self, source: Source, kind: Any, fetched_posts: int) -> None: ...


class RunLock(Protocol):
    def try_acquire(self) -> contextlib.AbstractAsyncContextManager[bool]: ...


class ProgressSink(Protocol):
    """The runner calls event() in a worker thread, so it may block on the database."""

    def event(self, phase: str, data: dict) -> None: ...


# --------------------------------------------------------------------------- progress


class _NullProgress:
    def event(self, phase: str, data: dict) -> None:
        return None


NULL_PROGRESS: ProgressSink = _NullProgress()

class JobProgressSink:
    """Appends an event per source fetched and per slow-down to a job_runs row. Never raises:
    progress is not worth a run. The "decided" and "saved" phases add none: they repeat the
    run's summary, which the job already shows.

    A "source" event (one source fetched and saved) also sets the payload's live counters,
    `sources: {done, total}` and `new_posts`, which the top bar's activity sign reads. A
    "doctor" event is the source doctor's switch (issue 0036), its line as it wrote it.
    """

    def __init__(self, operations_service: Any, job_id: Optional[str]) -> None:
        self.ops = operations_service
        self.job_id = job_id

    def event(self, phase: str, data: dict) -> None:
        if not self.job_id or phase not in ("source", "slowed", "doctor"):
            return
        data = data or {}
        progress, fields = None, None
        if phase == "source":
            sources = data["sources"]
            progress = 100.0 * sources["done"] / max(1, sources["total"])
            fields = {"sources": sources, "new_posts": data["new_posts"]}
            message = _source_line(data)
            level = "error" if data.get("status") == "error" else "info"
        elif phase == "doctor":
            message, level = data["line"], "warning"
        else:
            message, level = slowed_line(data), "warning"
        try:
            self.ops.append_job_event(
                self.job_id,
                message=message,
                level=level,
                progress=progress,
                payload={"phase": phase, **data},
                fields=fields,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record ingestion progress (%s): %s", phase, exc)


def slowed_line(data: dict) -> str:
    """A host limited us: "reddit.com: too many requests, slowing to 16 s" (runner and archive)."""
    why = "timed out" if data.get("timed_out") else "too many requests"
    return f"{data['host']}: {why}, slowing to {data['gap_s']:g} s"


def _source_line(data: dict) -> str:
    """One source's event: "r/viture: 3 new of 25 · 52 of 81 sources", "Simon Willison: unchanged
    · 3 of 81 sources" (its feed answered 304, issue 0044), or why it failed; with
    "· 2 of 3 pages lost most of their images" when pages read for it did (issue 0032), and
    "· 50 pages checked for changes, 2 updated" when it watches its pages (issue 0039)."""
    name, sources = data["display_name"], data["sources"]
    of_run = f"{sources['done']} of {sources['total']} source{'' if sources['total'] == 1 else 's'}"
    status = data.get("status")
    if status == "error":
        return f"{name}: failed, {(data.get('error') or 'error')[:160]} · {of_run}"
    if status == "unavailable":
        return f"{name}: unavailable, {(data.get('error') or 'not available')[:160]} · {of_run}"
    lost = data.get("pages_lost_images") or 0
    images = (f" · {lost} of {data.get('pages_read') or lost} page{'' if data.get('pages_read') == 1 else 's'}"
              f" lost most of their images" if lost else "")
    checked = data.get("checked") or 0
    changes = (f" · {checked} page{'' if checked == 1 else 's'} checked for changes, {data.get('updated') or 0} updated"
               if checked else "")
    if data.get("unchanged"):
        return f"{name}: unchanged{changes} · {of_run}"
    return f"{name}: {data.get('new', 0)} new of {data.get('fetched', 0)}{images}{changes} · {of_run}"


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
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
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
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.load(cur, source_ids)

    def record_decisions(self, decisions: Sequence[tuple[str, FetchDecision]], *,
                         now: Optional[datetime] = None) -> None:
        with db.connection(self.db_url) as conn:
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
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                rows = self.repo.record_outcomes(
                    cur, outcomes, trigger=trigger, now=now or self.clock(), backoff=backoff or self.backoff
                )
            conn.commit()
        return rows

    def load_validators(self, source_ids: Sequence[str]) -> Dict[str, Dict[str, Validators]]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.load_validators(cur, source_ids)

    def save_validators(self, source_id: str, validators: Mapping[str, Validators]) -> None:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                self.repo.replace_validators(cur, source_id, validators)
            conn.commit()

    def refresh_cadence(self) -> int:
        with db.connection(self.db_url) as conn:
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
        with db.connection(self.db_url) as conn:
            return self.repo.save_batch(conn, drafts)


# --------------------------------------------------------------------------- watched pages


class DbPageWatchStore:
    """PageWatchRepository with connection handling (issue 0039)."""

    def __init__(self, db_url: str, repo: Any = None) -> None:
        self.db_url = db_url
        if repo is None:
            from insight_core.db.repo_page_watch import PageWatchRepository

            repo = PageWatchRepository()
        self.repo = repo

    def due(self, source_id: str, *, now: datetime, limit: int) -> List[WatchedPage]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            rows = self.repo.due(cur, source_id, now=now, limit=limit)
        return [WatchedPage(row["post_id"], row["url"], row["text_hash"], row["modified"],
                            Validators(row["etag"], row["last_modified"], row["learned_at"]), row["head_missed"])
                for row in rows]

    def checked(self, source_id: str, checks: Sequence[PageCheck], *, now: datetime) -> None:
        if not checks:
            return
        rows = [{"post_id": c.post_id, "text_hash": c.text_hash, "modified": c.modified,
                 "head_missed": c.head_missed, "etag": c.validators.etag if c.validators else None,
                 "last_modified": c.validators.last_modified if c.validators else None,
                 "learned_at": c.validators.learned_at if c.validators else None}
                for c in checks]
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                self.repo.checked(cur, source_id, rows, now=now)
            conn.commit()


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
        conn = db.session_connection(self.db_url, autocommit=True)
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
