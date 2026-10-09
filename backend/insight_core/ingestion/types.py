"""Request/outcome vocabulary shared by the ingestion module and its stores.

B1 ships the three types the fetch schedule and the fetch state store need; B4 adds the
request and report types (SourceSelector, FetchRequest, RunReport, ...).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
