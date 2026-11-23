"""FetchGates: the one place a politeness profile becomes concurrency acquisitions.

Holds the global semaphore, the yt-dlp pool and start spacer, and the per-host limiter. Gate order is load-bearing:
the narrow gate (host lock, yt-dlp budget) is taken BEFORE the global semaphore, so a run of same-host sources never
parks every global slot on tasks waiting for one host (interleave_by_host attacks the same problem from the other end).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import weakref
from typing import AsyncIterator, Awaitable, Callable, Mapping, Optional

from insight_core.ingestion.host_budgets import HostBudgets
from insight_core.ingestion.kinds.base import PolitenessProfile, source_host_key
from insight_core.ingestion.kinds.bluesky import BLUESKY_HOST_KEY
from insight_core.ingestion.kinds.nitter_rss import NITTER_HOSTS
from insight_core.ingestion.kinds.substack import SUBSTACK_HOST_KEY
from insight_core.ingestion.kinds.telegram_mtproto import TELEGRAM_HOST_KEY
from insight_core.ingestion.kinds.telegram_rss import TELEGRAM_RSS_HOSTS
from insight_core.utils.env import env_float, env_int

logger = logging.getLogger("insight.ingestion.gates")

# Seconds between request STARTS to one host key. Keyed by host, not kind, since kinds share hosts. Keys are
# source_host_key values (www. stripped, HOST_ALIASES applied) or "platform:<p>" for bare handles.
HOST_FLOORS: Mapping[str, float] = {
    # The self-hosted bridge answers "Too many requests" even under a sequential cycle.
    **{host: 5.0 for host in TELEGRAM_RSS_HOSTS},
    **{host: 10.0 for host in NITTER_HOSTS},
    "reddit.com": 8.0,                 # the .rss reddit feeds (kind generic_rss)
    "platform:reddit": 8.0,            # bare r/<sub> handles (kind reddit_subreddit)
    TELEGRAM_HOST_KEY: 2.0,            # every telegram_mtproto source (one shared client)
    SUBSTACK_HOST_KEY: 2.0,            # every substack source (one Substack backend)
    BLUESKY_HOST_KEY: 2.0,             # every bluesky source (one public AppView)
}

# The learned pace: a host that limits us (429) or times out is waited out (Retry-After, else DEFAULT_WAIT_S, at
# most MAX_WAIT_S) and its gap doubles within [MIN_LIMITED_GAP_S, MAX_GAP_S]; SHRINK_AFTER successes in a row take a
# quarter off, never below the floor. Kept for the life of the process.
MAX_WAIT_S = 120.0
DEFAULT_WAIT_S = 60.0
MIN_LIMITED_GAP_S = 5.0
MAX_GAP_S = 120.0
SHRINK_AFTER = 20
SHRINK_FACTOR = 0.75

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class HostLimiter:
    """One in-flight request per host, request starts spaced by the host's learned gap (starting at its floor,
    learning from limited() and succeeded()). Spacing is per host: a global sleep buys nothing under gather.
    """

    def __init__(
        self,
        host_floors: Mapping[str, float] = HOST_FLOORS,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.host_floors = host_floors
        self._clock = clock
        self._sleep = sleep
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request_at: dict[str, float] = {}
        self._gaps: dict[str, float] = {}
        self._successes: dict[str, int] = {}

    host_key = staticmethod(source_host_key)

    def gap(self, host: str) -> float:
        """Seconds between request starts to this host now: the learned gap, else the floor."""
        return self._gaps.get(host, float(self.host_floors.get(host, 0.0)))

    def limited(self, host: str, retry_after_s: Optional[float] = None) -> float:
        """The host limited us (or timed out): double its gap. Returns how long to wait."""
        self._gaps[host] = min(MAX_GAP_S, max(2 * self.gap(host), MIN_LIMITED_GAP_S))
        self._successes[host] = 0
        return min(MAX_WAIT_S, DEFAULT_WAIT_S if retry_after_s is None else max(0.0, retry_after_s))

    def succeeded(self, host: str) -> None:
        """One request went through; every SHRINK_AFTER in a row take a quarter off a learned gap."""
        if host not in self._gaps:
            return
        self._successes[host] = self._successes.get(host, 0) + 1
        if self._successes[host] >= SHRINK_AFTER:
            self._gaps[host] = max(float(self.host_floors.get(host, 0.0)), self._gaps[host] * SHRINK_FACTOR)
            self._successes[host] = 0

    @contextlib.asynccontextmanager
    async def slot(self, host: str, min_interval: float = 0.0) -> AsyncIterator[None]:
        min_interval = max(float(min_interval or 0), self.gap(host))
        lock = self._locks.get(host)
        if lock is None:
            lock = self._locks[host] = asyncio.Lock()

        async with lock:
            last = self._last_request_at.get(host)
            if last is not None:
                wait = min_interval - (self._clock() - last)
                if wait > 0:
                    logger.debug("%s: waiting %.1fs for host spacing", host, wait)
                    await self._sleep(wait)
            try:
                yield
            finally:
                self._last_request_at[host] = self._clock()


class StartSpacer:
    """Minimum wall-clock gap between the *starts* of successive operations; calls may overlap. Not a HostLimiter,
    which would serialise the youtube.com channels and undo the yt-dlp budget.
    """

    def __init__(self, min_interval: float, *, clock: Clock = time.monotonic, sleep: Sleep = asyncio.sleep) -> None:
        self._min_interval = max(0.0, min_interval)
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_start_at = 0.0

    async def wait(self) -> None:
        if not self._min_interval:
            return
        async with self._lock:
            now = self._clock()
            start_at = max(now, self._next_start_at)
            # Reserved before sleeping, so the next caller queues behind this slot.
            self._next_start_at = start_at + self._min_interval
        delay = start_at - self._clock()
        if delay > 0:
            logger.debug("yt-dlp: waiting %.1fs for start spacing", delay)
            await self._sleep(delay)


def interleave_by_host(sources: list[dict], host_key: Callable[[dict], str] = source_host_key) -> list[dict]:
    """Round-robin the fetch queue across hosts, keeping priority tiers in order, so tasks that start together
    mostly want different gates. Within a tier the input order is kept per host.
    """
    tiers: dict = {}
    for source in sources:
        tier = tiers.setdefault((source.get("settings") or {}).get("priority", 999), {})
        tier.setdefault(host_key(source), []).append(source)

    ordered: list[dict] = []
    for priority in sorted(tiers):
        buckets = tiers[priority]
        while buckets:
            for host in list(buckets):
                ordered.append(buckets[host].pop(0))
                if not buckets[host]:
                    del buckets[host]
    return ordered


# One run gives a host at most this much of its spacing: it binds only once a host's learned gap grew; the rest wait
# for the next tick, oldest due first, instead of stretching one tick past the next.
RUN_HOST_BUDGET_S = env_float("INSIGHT_RUN_HOST_BUDGET_SECONDS", 15 * 60, minimum=0.0)


def over_host_budget(
    due: list,
    host_key: Callable[[object], str],
    spacing: Callable[[object, str], float],
    budget_s: float = RUN_HOST_BUDGET_S,
) -> tuple[list, list]:
    """Split `due` (oldest due first) into what this run fetches and what waits for the next one.

    A host's first source always goes; each further one costs its spacing (the seconds its slot
    waits after the one before: the host's gap or the source's own delay), and goes while the host's
    spacing this run stays within budget_s. Order within each part is kept.
    """
    spent: dict[str, float] = {}
    kept, deferred = [], []
    for item in due:
        host = host_key(item)
        if host not in spent:
            spent[host] = 0.0
            kept.append(item)
            continue
        cost = max(0.0, float(spacing(item, host) or 0.0))
        if spent[host] + cost <= budget_s:
            spent[host] += cost
            kept.append(item)
        else:
            deferred.append(item)
    return kept, deferred


class FetchGates:
    """Process-wide fetch politeness: global budget, yt-dlp pool + spacer, per-host limiter."""

    _shared: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, FetchGates]" = weakref.WeakKeyDictionary()

    def __init__(
        self,
        *,
        max_concurrency: int = 8,
        ytdlp_concurrency: int = 2,
        ytdlp_min_start_interval_s: float = 3.0,
        host_floors: Mapping[str, float] = HOST_FLOORS,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        budgets: Optional[HostBudgets] = None,
    ) -> None:
        self.max_concurrency = max(1, max_concurrency)
        self.ytdlp_concurrency = max(1, ytdlp_concurrency)
        self.global_semaphore = asyncio.Semaphore(self.max_concurrency)
        self.ytdlp_semaphore = asyncio.Semaphore(self.ytdlp_concurrency)
        self.ytdlp_spacer = StartSpacer(ytdlp_min_start_interval_s, clock=clock, sleep=sleep)
        self.host_limiter = HostLimiter(host_floors, clock=clock, sleep=sleep)
        self.sleep = sleep   # the wait a limiting host asked for, before the one retry
        self.clock = clock
        # each host's budget, learned from the limits archives meet
        self.budgets = budgets if budgets is not None else HostBudgets()

    @classmethod
    def from_env(cls) -> "FetchGates":
        # every kind's I/O runs through asyncio.to_thread (min(32, cpu + 4) threads): a larger budget only queues
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            from insight_core.ingestion.ports import DbHostBudgetStore   # ports imports the DB layer

            budgets = HostBudgets(DbHostBudgetStore(db_url))
        else:
            budgets = HostBudgets()
        return cls(
            budgets=budgets,
            max_concurrency=env_int("INSIGHT_FETCH_MAX_CONCURRENCY", 8, minimum=1),
            # yt-dlp's budget is per IP, not per channel (too many in flight trigger bot checks)
            ytdlp_concurrency=env_int("INSIGHT_YTDLP_CONCURRENCY", 2, minimum=1),
            ytdlp_min_start_interval_s=env_float("INSIGHT_YTDLP_MIN_INTERVAL", 3.0, minimum=0.0),
        )

    @classmethod
    def shared(cls) -> "FetchGates":
        """The process-wide gates for the running event loop (env-configured); kept per loop, since asyncio
        primitives bind to the loop that first uses them.
        """
        loop = asyncio.get_running_loop()
        gates = cls._shared.get(loop)
        if gates is None:
            gates = cls._shared[loop] = cls.from_env()
        return gates

    @contextlib.asynccontextmanager
    async def slot(
        self, profile: PolitenessProfile, host_key: str, *, per_source_delay_s: float = 0.0
    ) -> AsyncIterator[None]:
        """Hold every gate the profile needs for one fetch of one source, or one archive page."""
        async with contextlib.AsyncExitStack() as stack:
            if profile.concurrency_pool == "ytdlp":
                # No host lock: youtube.com is one host key, and the lock would serialise every
                # channel. The spacer supplies the politeness without the serialisation.
                await stack.enter_async_context(self.ytdlp_semaphore)
                await self.ytdlp_spacer.wait()
            else:
                await stack.enter_async_context(self.host_limiter.slot(host_key, per_source_delay_s))
            await stack.enter_async_context(self.global_semaphore)
            yield
