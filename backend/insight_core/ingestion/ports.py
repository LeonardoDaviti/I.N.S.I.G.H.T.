"""Real adapters behind the ingestion module's ports.

B1 ships the fetch state store only; B4 adds the Protocols (SourceCatalog, FetchStateStore,
PostSaver, InspectionRefresher, RunLock, ProgressSink, Clock) and the other adapters.

Each method opens one connection, does its work and commits, so a caller makes one store
call per phase (through asyncio.to_thread) rather than holding a connection across a fetch.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence

import psycopg

from insight_core.db.repo_fetch_state import FetchStateRepository, FetchStateRow
from insight_core.ingestion.schedule import FetchDecision, backoff_delay
from insight_core.ingestion.types import FetchOutcome, Trigger


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DbFetchStateStore:
    """FetchStateRepository with connection handling, a clock and the backoff ladder."""

    def __init__(
        self,
        db_url: str,
        repo: Optional[FetchStateRepository] = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        backoff: Callable[[int], timedelta] = backoff_delay,
    ) -> None:
        self.db_url = db_url
        self.repo = repo or FetchStateRepository()
        self.clock = clock
        self.backoff = backoff

    def load(self, source_ids: Sequence[str]) -> Dict[str, FetchStateRow]:
        with psycopg.connect(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.load(cur, source_ids)

    def record_decisions(self, decisions: Sequence[tuple[str, FetchDecision]]) -> None:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self.repo.record_decisions(cur, decisions, self.clock())
            conn.commit()

    def record_outcome(self, outcome: FetchOutcome, *, trigger: Trigger | str) -> FetchStateRow:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                row = self.repo.record_outcome(
                    cur, outcome, trigger=trigger, now=self.clock(), backoff=self.backoff
                )
            conn.commit()
        return row

    def record_outcomes(
        self, outcomes: Sequence[FetchOutcome], *, trigger: Trigger | str
    ) -> List[FetchStateRow]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                rows = self.repo.record_outcomes(
                    cur, outcomes, trigger=trigger, now=self.clock(), backoff=self.backoff
                )
            conn.commit()
        return rows

    def refresh_cadence(self) -> int:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                updated = self.repo.refresh_cadence(cur)
            conn.commit()
        return updated
