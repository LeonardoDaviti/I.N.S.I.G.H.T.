"""FetchGates: the one place a politeness profile becomes concurrency acquisitions (spec §D.3).

Moved from scripts/safe_ingest.py, where the same four objects (global semaphore, yt-dlp
semaphore, yt-dlp start spacer, host limiter) travelled as a data clump through every
fetch, and the archive-refresh phase re-implemented the acquisition order by hand.

Gate order is load-bearing: the narrow gate (host lock, yt-dlp budget) is taken BEFORE
the global semaphore. Taken inside it, a run of same-host sources parks every global slot
on tasks that are merely waiting for one host lock or for the 2-slot yt-dlp budget, and
effective concurrency collapses to 1-2. Waiting for a narrow gate must never cost a global
slot. (interleave_by_host attacks the same problem from the other end.)
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import weakref
from typing import AsyncIterator, Awaitable, Callable, Mapping, Optional

from insight_core.ingestion.kinds.base import PolitenessProfile, source_host_key
from insight_core.ingestion.kinds.nitter_rss import NITTER_HOSTS
from insight_core.ingestion.kinds.substack import SUBSTACK_HOST_KEY
from insight_core.ingestion.kinds.telegram_mtproto import TELEGRAM_HOST_KEY
from insight_core.ingestion.kinds.telegram_rss import TELEGRAM_RSS_HOSTS

logger = logging.getLogger("insight.ingestion.gates")

# Seconds between request STARTS to one host key. Keyed by host, not by kind, because many
# kinds share a host: the 10 reddit .rss feeds are generic_rss, r/<sub> handles are
# reddit_subreddit, and both must be spaced. Keys are source_host_key values (www. stripped,
# HOST_ALIASES applied) or "platform:<p>" for bare handles.
HOST_FLOORS: Mapping[str, float] = {
    # The self-hosted bridge answers "Too many requests" even under a sequential cycle.
    **{host: 5.0 for host in TELEGRAM_RSS_HOSTS},
    **{host: 10.0 for host in NITTER_HOSTS},
    "reddit.com": 8.0,                 # the .rss reddit feeds (kind generic_rss)
    "platform:reddit": 8.0,            # bare r/<sub> handles (kind reddit_subreddit)
    TELEGRAM_HOST_KEY: 2.0,            # every telegram_mtproto source (one shared client, B8)
    SUBSTACK_HOST_KEY: 2.0,            # every substack source (one Substack backend, §10)
}

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except ValueError:
        return default


class HostLimiter:
    """One in-flight request per host, request starts spaced by the host's floor.

    A global sleep between sources buys nothing under asyncio.gather - every task sleeps at
    the same time - while sources cluster hard by host (12 github.com, 10 reddit.com, 6
    arxiv). Spacing belongs per host.
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

    host_key = staticmethod(source_host_key)

    @contextlib.asynccontextmanager
    async def slot(self, host: str, min_interval: float = 0.0) -> AsyncIterator[None]:
        min_interval = max(float(min_interval or 0), float(self.host_floors.get(host, 0.0)))
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
    """Minimum wall-clock gap between the *starts* of successive operations.

    Not a HostLimiter: that holds its lock for the whole call, which would serialise the
    youtube.com channels into one at a time and undo the yt-dlp budget. This only hands out
    start slots, so N calls may overlap - they just cannot begin together.
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
    """Round-robin the fetch queue across hosts, keeping priority tiers in order.

    asyncio.gather starts tasks in list order, so a contiguous run of ~32 youtube.com
    channels would have every early task wanting the same gate. Interleaving makes tasks
    that start together mostly want different gates. Within a tier the input order is
    preserved per host, so priority still decides who goes first.
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
    ) -> None:
        self.max_concurrency = max(1, max_concurrency)
        self.ytdlp_concurrency = max(1, ytdlp_concurrency)
        self.global_semaphore = asyncio.Semaphore(self.max_concurrency)
        self.ytdlp_semaphore = asyncio.Semaphore(self.ytdlp_concurrency)
        self.ytdlp_spacer = StartSpacer(ytdlp_min_start_interval_s, clock=clock, sleep=sleep)
        self.host_limiter = HostLimiter(host_floors, clock=clock, sleep=sleep)

    @classmethod
    def from_env(cls) -> "FetchGates":
        # The default executor is min(32, cpu + 4) threads and every kind's I/O runs through
        # asyncio.to_thread, so a global budget far above that only queues invisibly.
        return cls(
            max_concurrency=_env_int("INSIGHT_FETCH_MAX_CONCURRENCY", 8),
            # yt-dlp's budget is per IP, not per channel: 2026-07-23 one video spent 7.5 min
            # retrying "Sign in to confirm you're not a bot" with 22 channels in flight.
            ytdlp_concurrency=_env_int("INSIGHT_YTDLP_CONCURRENCY", 2),
            ytdlp_min_start_interval_s=_env_float("INSIGHT_YTDLP_MIN_INTERVAL", 3.0),
        )

    @classmethod
    def shared(cls) -> "FetchGates":
        """The process-wide gates for the running event loop (env-configured).

        asyncio primitives bind to the loop that first uses them, so the singleton is kept
        per loop: the API process has one loop and therefore one set of gates; a CLI run or a
        test gets its own.
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
        """Hold every gate the profile needs for one fetch (or inspection) of one source."""
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
