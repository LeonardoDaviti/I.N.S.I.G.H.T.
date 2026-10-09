"""IngestionRunner: one algorithm for every fetch run (spec §A.2).

Orchestration only. Every collaborator is a port injected through the keyword
constructor, so the scheduler tick, the manual "Run cycle", track fetch, fetch-now and the
CLI all apply the same policy: the yt-dlp switch, backoff (read and write), politeness
gates, status recording, save isolation, enrichment and the inspection refresh.

Steps: run lock (selector all only) -> load sources -> load fetch state -> decide ->
record decisions -> fetch under the gates -> record outcomes -> one save batch -> enrich ->
refresh inspections -> report. Kind sessions (B8, telegram_mtproto) are opened lazily
inside the gate slot of a kind's first due source and closed in a finally after the
inspection refresh; a session that cannot open makes that kind's sources unavailable. A fetch never raises out of the runner; a failing store
write is logged and the run carries on.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import random
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from insight_core.db.repo_posts import PostDraft, SaveBatchResult
from insight_core.ingestion.enrichment import Enricher, EnrichmentReport
from insight_core.ingestion.gates import FetchGates, interleave_by_host
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import KindSession, KindUnavailable, SourceKind
from insight_core.ingestion.ports import (
    NULL_PROGRESS,
    FetchStateStore,
    InspectionRefresher,
    PostSaver,
    ProgressSink,
    RunLock,
    SourceCatalog,
)
from insight_core.ingestion.schedule import (
    Availability,
    DecisionKind,
    FetchDecision,
    backoff_delay,
    cadence_stats,
    decide_fetch,
)
from insight_core.ingestion.types import (
    LIST_CAP,
    FetchOutcome,
    FetchRequest,
    InsertedBySource,
    OutcomeStatus,
    RunReport,
    SourceFailure,
)

logger = logging.getLogger("insight.ingestion.runner")


def _display_name(source: Dict[str, Any]) -> str:
    return str((source.get("settings") or {}).get("display_name") or source.get("handle_or_url") or source.get("id"))


@dataclasses.dataclass
class _Fetched:
    source: Dict[str, Any]
    kind: SourceKind
    outcome: FetchOutcome
    posts: List[dict]


class _RunSessions:
    """The kind sessions of one run: opened at most once per kind, all closed at the end.

    A session whose open() raised is not retried within the run: every later source of
    that kind gets the same KindUnavailable reason (UNAVAILABLE, never backoff).
    """

    def __init__(self) -> None:
        self._opened: Dict[int, tuple[SourceKind, KindSession]] = {}
        self._failed: Dict[int, str] = {}
        self._locks: Dict[int, asyncio.Lock] = {}

    async def ensure(self, kind: SourceKind) -> None:
        key = id(kind)
        if key in self._opened:
            return
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self._opened:
                return
            if key in self._failed:
                raise KindUnavailable(self._failed[key])
            session = kind.session()
            try:
                await session.open()
            except KindUnavailable as exc:
                self._failed[key] = exc.reason
                raise
            except Exception as exc:  # noqa: BLE001 - a session that cannot open is unavailability
                reason = f"{kind.name} session could not be opened: {exc}"
                self._failed[key] = reason
                raise KindUnavailable(reason) from exc
            self._opened[key] = (kind, session)

    async def close_all(self) -> None:
        opened, self._opened = list(self._opened.values()), {}
        for kind, session in opened:
            try:
                await session.close()
            except Exception as exc:  # noqa: BLE001 - closing must not cost the report
                logger.warning("Could not close the %s session: %s", kind.name, exc)


class IngestionRunner:
    def __init__(
        self,
        *,
        catalog: SourceCatalog,
        state: FetchStateStore,
        saver: PostSaver,
        enricher: Enricher,
        inspections: InspectionRefresher,
        registry: KindRegistry,
        gates: FetchGates,
        run_lock: RunLock,
        availability: Callable[[], Availability],
        clock: Callable[[], datetime],
        rand: Callable[[], float] = random.random,
    ) -> None:
        self.catalog = catalog
        self.state = state
        self.saver = saver
        self.enricher = enricher
        self.inspections = inspections
        self.registry = registry
        self.gates = gates
        self.run_lock = run_lock
        self.availability = availability
        self.clock = clock
        self.rand = rand

    async def run(self, request: FetchRequest, *, progress: ProgressSink = NULL_PROGRESS) -> RunReport:
        started = self.clock()
        if request.selector.kind == "all":
            async with self.run_lock.try_acquire() as acquired:
                if not acquired:
                    logger.info("Another full ingestion run holds the run lock; skipping")
                    return self._report(request, started, status="skipped_busy")
                return await self._run(request, progress, started)
        return await self._run(request, progress, started)

    # ------------------------------------------------------------------ the run

    async def _run(self, request: FetchRequest, progress: ProgressSink, started: datetime) -> RunReport:
        run_id = uuid.uuid4().hex[:12]
        sources = await asyncio.to_thread(self.catalog.load, request.selector)
        if request.selector.kind == "source" and not sources:
            failure = SourceFailure(str(request.selector.id), str(request.selector.id), "fetch", "Source not found")
            return self._report(request, started, run_id=run_id, status="failed", failures=[failure])

        states = await asyncio.to_thread(self.state.load, [s["id"] for s in sources])

        # Decide.
        availability = self.availability()
        now = self.clock()
        decisions: List[tuple[str, FetchDecision]] = []
        due: List[tuple[Dict[str, Any], SourceKind, FetchDecision]] = []
        counts: Dict[str, int] = {}
        for source in sources:
            kind = self.registry.resolve(source)
            decision = decide_fetch(
                cadence_stats(source, states.get(source["id"])),
                kind.profile,
                now,
                force=request.force,
                availability=availability,
                requested_limit=request.limit,
            )
            if request.selector.kind != "source" and not source.get("enabled", True):
                # Defensive: the catalog only returns enabled sources for all/folder.
                decision = dataclasses.replace(decision, kind=DecisionKind.SKIP_DISABLED, fetch=False,
                                               next_due_at=None, detail="Source is disabled")
            decisions.append((source["id"], decision))
            counts[decision.kind.value] = counts.get(decision.kind.value, 0) + 1
            logger.info("%s %s: %s", "fetch" if decision.fetch else "skip", _display_name(source), decision.detail)
            if decision.fetch:
                due.append((source, kind, decision))

        await self._safely("record decisions", self.state.record_decisions, decisions, now=now)
        progress.event("decided", {"sources_considered": len(sources), "decisions": dict(counts)})

        if not due:
            return self._report(request, started, run_id=run_id, status="nothing_due",
                                sources_considered=len(sources), decisions=counts)

        sessions = _RunSessions()
        try:
            return await self._fetch_save_enrich(request, progress, started, run_id, sources, due, counts,
                                                 sessions)
        finally:
            await sessions.close_all()

    async def _fetch_save_enrich(self, request: FetchRequest, progress: ProgressSink, started: datetime,
                                 run_id: str, sources: List[Dict[str, Any]],
                                 due: List[tuple[Dict[str, Any], SourceKind, FetchDecision]],
                                 counts: Dict[str, int], sessions: _RunSessions) -> RunReport:
        # Fetch: priority first, then round-robin across hosts so tasks that start together
        # mostly want different gates.
        by_id = {source["id"]: (source, kind, decision) for source, kind, decision in due}
        ordered = sorted((s for s, _, _ in due),
                         key=lambda s: ((s.get("settings") or {}).get("priority", 999), str(s.get("handle_or_url"))))
        ordered = interleave_by_host(ordered, host_key=lambda s: by_id[s["id"]][1].host_key(s))
        fetched: List[_Fetched] = list(await asyncio.gather(
            *(self._fetch(*by_id[s["id"]], sessions) for s in ordered)
        ))
        posts_fetched = sum(len(f.posts) for f in fetched)
        progress.event("fetched", {
            "sources_fetched": len(fetched),
            "posts_fetched": posts_fetched,
            "outcomes": self._outcome_counts([f.outcome for f in fetched]),
        })

        # Save: one batch for the run.
        failures: List[SourceFailure] = [
            SourceFailure(f.source["id"], _display_name(f.source), "fetch", f.outcome.error or "error")
            for f in fetched if f.outcome.status == OutcomeStatus.ERROR
        ]
        drafts = [PostDraft(f.source["id"], post) for f in fetched for post in f.posts]
        for f in fetched:
            f.posts = []  # the drafts own the bodies now; release them after the save
        saved = SaveBatchResult()
        if drafts:
            try:
                saved = await asyncio.to_thread(self.saver.save, drafts)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Save batch failed")
                for source_id in {d.source_id for d in drafts}:
                    source = by_id[source_id][0]
                    failures.append(SourceFailure(source_id, _display_name(source), "save", str(exc)))
            else:
                for source_id, c in saved.by_source.items():
                    if c.get("failed") and not c.get("inserted") and not c.get("updated"):
                        source = by_id[source_id][0]
                        failures.append(SourceFailure(source_id, _display_name(source), "save",
                                                      f"all {c['failed']} posts failed to save"))
        drafts.clear()
        progress.event("saved", {"inserted": saved.inserted, "updated": saved.updated, "failed": saved.failed})

        # Outcomes are recorded after the save: a source none of whose posts reached the
        # database is failing (its failure count grows, it retries on backoff), not healthy
        # with its failures reset and its next fetch a whole cadence away.
        save_errors = {f.source_id: f.error for f in failures if f.stage == "save"}
        outcomes = [
            dataclasses.replace(f.outcome, status=OutcomeStatus.ERROR, error=f"save: {save_errors[f.source['id']]}")
            if f.source["id"] in save_errors and f.outcome.status != OutcomeStatus.ERROR else f.outcome
            for f in fetched
        ]
        await self._safely(
            "record outcomes", self.state.record_outcomes, outcomes, trigger=request.trigger,
            now=self.clock(), backoff=lambda n: backoff_delay(n, rand=self.rand),
        )

        # Enrich the inserted posts.
        try:
            enrichment = await self.enricher.run(saved.inserted_posts)
        except Exception as exc:  # noqa: BLE001 - Enricher counts chunk failures; this is belt and braces
            logger.exception("Enrichment failed: %s", exc)
            enrichment = EnrichmentReport.empty()
        counts_by_source = dict(saved.by_source)
        saved.inserted_posts.clear()
        progress.event("enriched", enrichment.as_dict())

        # Refresh inspections for every source that fetched at least one post.
        refreshable = [f for f in fetched if f.outcome.status == OutcomeStatus.HEALTHY]
        results = await asyncio.gather(
            *(self.inspections.refresh(f.source, f.kind, f.outcome.fetched) for f in refreshable),
            return_exceptions=True,
        )
        inspection_failures = sum(1 for r in results if isinstance(r, BaseException))
        for f, r in zip(refreshable, results):
            if isinstance(r, BaseException):
                logger.warning("Inspection refresh failed for %s: %s", _display_name(f.source), r)
        progress.event("inspected", {"refreshed": len(refreshable) - inspection_failures,
                                     "failed": inspection_failures})

        failed_sources = {f.source_id for f in failures}
        if failed_sources and len(failed_sources) >= len(fetched):
            status = "failed"
        elif failed_sources or saved.failed:
            status = "partial"
        else:
            status = "success"
        inserted_by_source = sorted(
            (InsertedBySource(sid, _display_name(by_id[sid][0]), c.get("inserted", 0))
             for sid, c in counts_by_source.items() if c.get("inserted")),
            key=lambda i: (-i.inserted, i.display_name),
        )[:LIST_CAP]
        return self._report(
            request, started, run_id=run_id, status=status,
            sources_considered=len(sources), sources_fetched=len(fetched),
            sources_failed=len(failed_sources), decisions=counts,
            posts_fetched=posts_fetched, posts_inserted=saved.inserted, posts_updated=saved.updated,
            posts_failed=saved.failed, failures=failures[:LIST_CAP],
            post_failures=saved.failures[:LIST_CAP], enrichment=enrichment,
            inserted_by_source=inserted_by_source,
        )

    async def _fetch(self, source: Dict[str, Any], kind: SourceKind, decision: FetchDecision,
                     sessions: _RunSessions) -> _Fetched:
        """Fetch one source under its gates. Never raises."""
        started = time.monotonic()
        posts: List[dict] = []
        try:
            delay = (source.get("settings") or {}).get("fetch_delay_seconds") or 0
            async with self.gates.slot(kind.profile, kind.host_key(source), per_source_delay_s=delay):
                await sessions.ensure(kind)
                logger.info("Fetching up to %s posts from %s", decision.post_limit, _display_name(source))
                posts = list(await kind.fetch_latest(source, decision.post_limit) or [])
            outcome = FetchOutcome.from_fetch(source["id"], fetched=len(posts), error=None,
                                              duration_s=time.monotonic() - started)
        except KindUnavailable as exc:
            logger.warning("%s: unavailable (%s)", _display_name(source), exc.reason)
            outcome = FetchOutcome(source["id"], OutcomeStatus.UNAVAILABLE, 0, exc.reason, time.monotonic() - started)
            posts = []
        except BaseException as exc:  # noqa: BLE001 - one source must never cost the run
            if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                raise
            logger.error("Failed to fetch %s: %s", source.get("handle_or_url"), str(exc)[:300])
            outcome = FetchOutcome.from_fetch(source["id"], fetched=0, error=str(exc) or type(exc).__name__,
                                              duration_s=time.monotonic() - started)
            posts = []
        return _Fetched(source, kind, outcome, posts)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _outcome_counts(outcomes: List[FetchOutcome]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for outcome in outcomes:
            counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1
        return counts

    async def _safely(self, label: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Optional[Any]:
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - state writes are not worth the run
            logger.warning("Could not %s: %s", label, exc)
            return None

    def _report(self, request: FetchRequest, started: datetime, *, run_id: Optional[str] = None,
                status: str, **fields: Any) -> RunReport:
        return RunReport(
            run_id=run_id,
            trigger=request.trigger,
            selector=request.selector,
            force=request.force,
            status=status,  # type: ignore[arg-type]
            started_at=started,
            finished_at=self.clock(),
            enrichment=fields.pop("enrichment", EnrichmentReport.empty()),
            **fields,
        )
