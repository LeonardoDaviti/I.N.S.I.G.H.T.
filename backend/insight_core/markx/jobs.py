"""Mark X Shadow's jobs: when the candidate finder (markx/candidates.py) and the decision run (markx/decide.py) run.

The rules and the work stay in their modules (`candidates.run`, `decide.run`); this module only decides when they
run and keeps them out of a request:
  - `Pending`, the candidates' debounce: the posts of each upload collected, one run DEBOUNCE seconds after the
    last upload (0086 B);
  - `Scheduler`, the decisions' clock: after the worker's uploads (debounced), hourly, and when the start's story
    job finishes (0086 E, 0112 A); one run at a time (and a Postgres advisory lock across processes, in
    `decide.run`).
Both only when INSIGHT_MARKX is on, and never raise into a request or their thread.
"""
from __future__ import annotations

import logging
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, Optional, Set

from insight_core.markx import candidates, decide

log = logging.getLogger(__name__)

DEBOUNCE = 30.0                   # the candidates: seconds of quiet after the last upload


# ---- the candidates' debounce -----------------------------------------------------------------------

class Pending:
    """The debounce: posts collected after each upload, one run DEBOUNCE seconds after the last (delay None: no
    timer, `flush` runs it; the tests). Never raises into a request; a failed run keeps its posts for the next."""

    def __init__(self, delay: Optional[float] = DEBOUNCE, transaction: Optional[Callable[[], Any]] = None) -> None:
        self.delay = delay
        self.transaction = transaction
        self.posts: Set[str] = set()
        self.last_run: Optional[datetime] = None
        self.lock = threading.Lock()
        self.timer: Optional[threading.Timer] = None

    def note(self, post_ids: Iterable[str]) -> None:
        with self.lock:
            self.posts |= set(map(str, post_ids))
            if self.delay is None or not self.posts:
                return
            if self.timer is not None:
                self.timer.cancel()
            self.timer = threading.Timer(self.delay, self.flush)
            self.timer.daemon = True
            self.timer.start()

    def flush(self) -> Optional[Counter]:
        with self.lock:
            ids, self.posts, self.timer = self.posts, set(), None
            since = self.last_run or datetime.now(timezone.utc) - timedelta(days=1)
            started = datetime.now(timezone.utc)
        try:
            transaction = self.transaction or _candidates_transaction
            with transaction() as cur:
                counts = candidates.run(cur, ids, since=since)
        except Exception:   # never into a request or the timer thread; the posts wait for the next run
            log.exception("Mark X candidates: the run failed; %d posts kept for the next", len(ids))
            with self.lock:
                self.posts |= ids
            return None
        with self.lock:
            self.last_run = started
        log.info("Mark X candidates: %d posts, %s", len(ids), dict(counts))
        return counts


def _candidates_transaction():
    from insight_core.db import database
    from insight_core.services.registry import services
    return database.transaction(services().db_url)


pending = Pending()


# ---- the decisions' clock ---------------------------------------------------------------------------

def _transaction():
    return decide.snapshot()


class Scheduler:
    """After the worker's uploads (`note`, DEBOUNCE seconds after the last) and every EVERY seconds, one run at a
    time; only when INSIGHT_MARKX is on. Never raises into a request or its thread."""
    DEBOUNCE = 60.0
    EVERY = 3600.0

    def __init__(self, transaction: Optional[Callable[[], Any]] = None, debounce: Optional[float] = DEBOUNCE,
                 every: Optional[float] = EVERY, enabled: Optional[Callable[[], bool]] = None) -> None:
        self.transaction = transaction
        self.debounce, self.every = debounce, every
        self.enabled = enabled
        self.lock = threading.Lock()
        self.running = threading.Lock()
        self.timer: Optional[threading.Timer] = None
        self.thread: Optional[threading.Thread] = None
        self.stop = threading.Event()
        self.last: Optional[Dict[str, Any]] = None

    def on(self) -> bool:
        if self.enabled is not None:
            return self.enabled()
        from insight_core.markx.api import enabled
        return enabled()

    def note(self) -> None:
        """An upload arrived: one run DEBOUNCE seconds after the last."""
        if self.debounce is None or not self.on():
            return
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
            self.timer = threading.Timer(self.debounce, self.run_now)
            self.timer.daemon = True
            self.timer.start()

    def start(self) -> bool:
        """The hourly clock, at the API's start: False (nothing runs) when Mark X is off."""
        if self.every is None or self.thread is not None or not self.on():
            return False
        self.thread = threading.Thread(target=self._hourly, name="markx-decide", daemon=True)
        self.thread.start()
        return True

    def after_stories(self) -> Optional[Dict[str, Any]]:
        """The API's start: its story job has finished, so Mark X decides now over Mark IX's new stories (0112 A),
        not up to EVERY seconds later; nothing when Mark X is off."""
        if not self.on():
            return None
        return self.run_now(candidates_first=True)

    def _hourly(self) -> None:
        while not self.stop.wait(self.every):
            self.run_now(candidates_first=True)

    def run_now(self, candidates_first: bool = False) -> Optional[Dict[str, Any]]:
        if not self.on():
            return None
        with self.lock:
            self.timer = None
        if not self.running.acquire(blocking=False):
            return None
        try:
            if candidates_first:   # the posts whose entities arrived since the candidates' last run (S2)
                pending.flush()
            transaction = self.transaction or _transaction
            with transaction() as cur:
                self.last = decide.run(cur)
            log.info("Mark X decisions: %s", {k: v for k, v in self.last.items() if k in ("stories", "changes", "news")})
            return self.last
        except Exception:   # never into a request or the timer thread
            log.exception("Mark X decisions: the run failed")
            return None
        finally:
            self.running.release()


scheduler = Scheduler()
