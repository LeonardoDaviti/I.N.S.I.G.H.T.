"""Request, outcome and report vocabulary shared by the ingestion module and its callers.

Spec: plan/INSIGHT_mark_ix_plan.md §A.1. Import-light (no DB, no kinds): the report types
reference enrichment and save results only by duck type.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

LIST_CAP = 20                 # every list in a run report payload (OperationsService compaction is a no-op)
ERROR_CAP = 500               # characters of an error kept in a report


class Trigger(str, Enum):
    """Who asked for the run. Recorded on the job and on each fetch outcome."""

    SCHEDULER = "scheduler"
    MANUAL = "manual"
    CLI = "cli"


class OutcomeStatus(str, Enum):
    """What happened when a source was fetched.

    healthy: >= 1 post. empty: 0 posts, but the fetch worked. error: the fetch raised.
    unavailable: the process lacks what the kind needs (yt-dlp off, no Telegram session,
    a shared connector that never came up) - never counted as backoff.
    """

    HEALTHY = "healthy"
    EMPTY = "empty"
    ERROR = "error"
    UNAVAILABLE = "unavailable"

    @property
    def is_success(self) -> bool:
        return self in (OutcomeStatus.HEALTHY, OutcomeStatus.EMPTY)


@dataclass(frozen=True)
class FetchOutcome:
    source_id: str
    status: OutcomeStatus
    fetched: int
    error: str | None
    duration_s: float

    @staticmethod
    def from_fetch(source_id: str, *, fetched: int, error: str | None, duration_s: float) -> "FetchOutcome":
        """The healthy/empty/error classification every fetch path shares."""
        if error is not None:
            return FetchOutcome(source_id, OutcomeStatus.ERROR, 0, error, duration_s)
        status = OutcomeStatus.HEALTHY if fetched > 0 else OutcomeStatus.EMPTY
        return FetchOutcome(source_id, status, fetched, None, duration_s)


def _cap(text: Any) -> str:
    text = str(text)
    return text if len(text) <= ERROR_CAP else text[:ERROR_CAP] + "..."


@dataclass(frozen=True)
class SourceSelector:
    """Which sources a fetch request targets: all enabled, one folder's enabled members, or one source."""

    kind: Literal["all", "folder", "source"]
    id: Optional[str] = None

    @staticmethod
    def all() -> "SourceSelector":
        return SourceSelector("all")

    @staticmethod
    def folder(folder_id: str) -> "SourceSelector":
        return SourceSelector("folder", str(folder_id))

    @staticmethod
    def source(source_id: str) -> "SourceSelector":
        return SourceSelector("source", str(source_id))

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind} if self.id is None else {"kind": self.kind, "id": self.id}


@dataclass(frozen=True)
class FetchRequest:
    selector: SourceSelector
    trigger: Trigger
    force: bool = False              # ignore cadence + backoff (never unavailability)
    limit: Optional[int] = None      # per-source post limit (still floored by profile.min_posts_per_fetch)


@dataclass(frozen=True)
class SourceFailure:
    source_id: str
    display_name: str
    stage: Literal["fetch", "save", "connector"]
    error: str

    def as_dict(self) -> dict[str, Any]:
        return {"source_id": self.source_id, "display_name": self.display_name,
                "stage": self.stage, "error": _cap(self.error)}


@dataclass(frozen=True)
class InsertedBySource:
    source_id: str
    display_name: str
    inserted: int


RunStatus = Literal["success", "partial", "failed", "skipped_busy", "nothing_due"]


@dataclass
class RunReport:
    run_id: Optional[str]
    trigger: Trigger
    selector: SourceSelector
    force: bool
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    sources_considered: int = 0
    sources_fetched: int = 0          # attempted
    sources_failed: int = 0
    decisions: dict[str, int] = field(default_factory=dict)   # DecisionKind.value -> count
    posts_fetched: int = 0
    posts_inserted: int = 0           # THE "new posts" number
    posts_updated: int = 0
    posts_failed: int = 0
    failures: list[SourceFailure] = field(default_factory=list)
    post_failures: list[Any] = field(default_factory=list)     # PostSaveFailure
    enrichment: Any = None                                      # EnrichmentReport
    inserted_by_source: list[InsertedBySource] = field(default_factory=list)

    @property
    def deferred(self) -> int:
        return max(0, self.sources_considered - self.sources_fetched)

    @property
    def job_status(self) -> str:
        """The job_runs status: a run with any failure is a failed job (Mark VIII semantics)."""
        return "success" if self.status in ("success", "nothing_due", "skipped_busy") else "failed"

    def summary_line(self) -> str:
        """One line per run, e.g. "12 due, 63 deferred, 1 failed; 48 new posts"."""
        if self.status == "skipped_busy":
            return "Skipped: another full ingestion run is in progress"
        return (
            f"{self.sources_fetched} due, {self.deferred} deferred, {self.sources_failed} failed; "
            f"{self.posts_inserted} new posts"
        )

    def to_payload(self) -> dict[str, Any]:
        enrichment = self.enrichment.as_dict() if self.enrichment is not None else None
        return {
            "run_id": self.run_id,
            "trigger": getattr(self.trigger, "value", self.trigger),
            "selector": self.selector.as_dict(),
            "force": self.force,
            "status": self.status,
            "summary": self.summary_line(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_s": round((self.finished_at - self.started_at).total_seconds(), 3),
            "sources_considered": self.sources_considered,
            "sources_fetched": self.sources_fetched,
            "sources_failed": self.sources_failed,
            "decisions": dict(self.decisions),
            "posts_fetched": self.posts_fetched,
            "posts_inserted": self.posts_inserted,
            "posts_updated": self.posts_updated,
            "posts_failed": self.posts_failed,
            "failures": [f.as_dict() for f in self.failures[:LIST_CAP]],
            "post_failures": [
                {"url": (f.url or "")[:1000] or None, "source_id": f.source_id, "stage": f.stage, "error": _cap(f.error)}
                for f in self.post_failures[:LIST_CAP]
            ],
            "enrichment": enrichment,
            "inserted_by_source": [
                {"source_id": i.source_id, "display_name": i.display_name, "inserted": i.inserted}
                for i in self.inserted_by_source[:LIST_CAP]
            ],
        }
