"""Test adapters for the ingestion runner's ports (spec §3). No DB, no network."""
from __future__ import annotations

import contextlib
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Mapping

from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.db.repo_posts import PostSaveFailure, SaveBatchResult
from insight_core.ingestion.gates import FetchGates
from insight_core.ingestion.types import OutcomeStatus


class FixedClock:
    def __init__(self, at: datetime):
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, delta: timedelta) -> None:
        self.at = self.at + delta


class SleepClock:
    """A monotonic clock that only moves when the code under test sleeps (gates' clock and sleep)."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


class InMemorySourceCatalog:
    def __init__(self, sources: list[dict], folders: Mapping[str, list[str]] | None = None):
        self.sources = sources
        self.folders = dict(folders or {})
        self.loads: list[Any] = []

    def load(self, selector):
        self.loads.append(selector)
        if selector.kind == "all":
            return [s for s in self.sources if s.get("enabled", True)]
        if selector.kind == "folder":
            members = set(self.folders.get(selector.id, []))
            return [s for s in self.sources if s["id"] in members and s.get("enabled", True)]
        return [s for s in self.sources if s["id"] == selector.id]


class InMemoryFetchStateStore:
    """Mirrors FetchStateRepository.record_outcome: the counter and backoff come from the same callable."""

    def __init__(self, rows: Mapping[str, FetchStateRow] | None = None):
        self.rows: dict[str, FetchStateRow] = dict(rows or {})
        self.decisions: list[tuple[str, Any]] = []
        self.outcome_calls: list[tuple[list, str]] = []

    def load(self, source_ids):
        return {sid: self.rows[sid] for sid in source_ids if sid in self.rows}

    def record_decisions(self, decisions, *, now=None):
        for source_id, decision in decisions:
            self.decisions.append((source_id, decision))
            row = self.rows.get(source_id) or FetchStateRow(source_id=source_id)
            self.rows[source_id] = replace(row, last_decision_kind=decision.kind.value,
                                           last_decision_at=now, next_due_at=decision.next_due_at)

    def record_outcomes(self, outcomes, *, trigger, now=None, backoff=None):
        trigger = getattr(trigger, "value", trigger)
        self.outcome_calls.append((list(outcomes), trigger))
        written = []
        for outcome in outcomes:
            row = self.rows.get(outcome.source_id) or FetchStateRow(source_id=outcome.source_id)
            row = replace(row, last_attempt_at=now, last_outcome=outcome.status.value, last_trigger=trigger)
            if outcome.status == OutcomeStatus.ERROR:
                count = row.consecutive_failures + 1
                row = replace(row, consecutive_failures=count, last_error=outcome.error,
                              last_error_at=now, next_retry_at=now + backoff(count))
            elif outcome.status == OutcomeStatus.UNAVAILABLE:
                row = replace(row, last_error=outcome.error)
            else:
                row = replace(row, consecutive_failures=0, next_retry_at=None, last_success_at=now,
                              last_fetched_posts=outcome.fetched, last_error=None,
                              doctor_checked_at=None, doctor_finding=None)
            self.rows[outcome.source_id] = row
            written.append(row)
        return written

    @property
    def outcomes(self) -> list:
        return [o for call, _ in self.outcome_calls for o in call]


class InMemoryPostSaver:
    """url-dedupe across saves; urls in failing_urls fail at upsert."""

    def __init__(self, failing_urls: set[str] | None = None):
        self.failing_urls = set(failing_urls or ())
        self.known: dict[str, str] = {}
        self.calls: list[list] = []

    def save(self, drafts):
        self.calls.append(list(drafts))
        result = SaveBatchResult()
        for draft in drafts:
            url = draft.post["url"]
            if url in self.failing_urls:
                result.failures.append(PostSaveFailure(url, draft.source_id, "upsert", "injected"))
                result._count(draft.source_id, "failed")
                continue
            if url in self.known:
                result.updated_ids.append(self.known[url])
                result._count(draft.source_id, "updated")
                continue
            post_id = f"post-{len(self.known) + 1}"
            self.known[url] = post_id
            result.inserted_ids.append(post_id)
            result._count(draft.source_id, "inserted")
        return result


class RecordingInspectionRefresher:
    def __init__(self):
        self.calls: list[tuple[str, str, int]] = []

    async def refresh(self, source, kind, fetched_posts):
        self.calls.append((source["id"], kind.name, fetched_posts))


class FakeRunLock:
    def __init__(self, held: bool = False):
        self.held = held
        self.entered = 0

    @contextlib.asynccontextmanager
    async def try_acquire(self):
        self.entered += 1
        yield not self.held


class RecordingProgressSink:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def event(self, phase, data):
        self.events.append((phase, data))

    @property
    def phases(self) -> list[str]:
        return [phase for phase, _ in self.events]


class SpyFetchGates(FetchGates):
    """Real gates with no host floors or yt-dlp spacing (unless given), recording every slot
    and whether it is currently held."""

    def __init__(self, **kwargs):
        kwargs.setdefault("ytdlp_min_start_interval_s", 0.0)
        kwargs.setdefault("host_floors", {})
        super().__init__(**kwargs)
        self.slots: list[tuple[str, str]] = []
        self.inside = 0

    @contextlib.asynccontextmanager
    async def slot(self, profile, host_key, *, per_source_delay_s: float = 0.0):
        self.slots.append((profile.concurrency_pool, host_key))
        async with super().slot(profile, host_key, per_source_delay_s=per_source_delay_s):
            self.inside += 1
            try:
                yield
            finally:
                self.inside -= 1
