"""Freed memory goes back to the OS when an API process is idle (issue 0202).

A request that reads a lot (a track's page, an entity's page, the overview) frees what it built when it ends, but glibc
keeps the freed pages inside its heaps: only the top of the main heap is ever given back by itself, so an API process's
RSS rose to its largest request's high-water and stayed there (measured on a server-sized copy: 222 MB a process after a
reading session, 142 MB once trimmed; the server's two processes reached 1.2 GB in a day). `malloc_trim(0)` hands every
arena's free pages back (madvise), in a few milliseconds.

Before trimming it collects reference cycles: psycopg's cursors sit in cycles (their Transformer and loaders) and a
closed cursor's Transformer still holds its last result (libpq memory, all its rows), so a big query's rows stayed until
the cyclic GC's next full pass (measured: a track page's process 220 MB, 183-223 MB trimmed alone, 130 MB collected and
trimmed). `freeze_start()` (each process's start) moves what the start built to the GC's permanent generation, so that
collection reads only what requests made: 2-9 ms instead of 40-60 ms (it holds the GIL).

`IdleTrim` (pure ASGI middleware, the outermost) counts the requests in flight; when the last one ends, the trimmer's
thread waits `QUIET` seconds and, if no request started meanwhile and the process grew by `GROW_MB` or more since its
last trim, collects and trims. It never runs during a request, and a poll that leaves nothing behind never trims.
Nothing is kept but two numbers. `INSIGHT_API_TRIM=off` switches it off; where the C library has no malloc_trim
(musl), it does nothing.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import gc
import logging
import os
import threading
import time
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

QUIET = 1.0        # seconds with no request in flight before a trim
GROW_MB = 8.0      # trim only when the process grew by this much since its last trim

_PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def rss_mb(path: str = "/proc/self/statm") -> Optional[float]:
    """This process's resident memory in MB, or None where /proc is not there."""
    try:
        with open(path, "rb") as f:
            return int(f.read().split()[1]) * _PAGE / 2**20
    except (OSError, ValueError, IndexError):
        return None


def libc_trim() -> Optional[Callable[[], Any]]:
    """glibc's malloc_trim(0) as a call (ctypes releases the GIL while it runs), or None without one."""
    try:
        lib = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        trim = lib.malloc_trim
    except (OSError, AttributeError):
        return None
    trim.argtypes, trim.restype = [ctypes.c_size_t], ctypes.c_int
    return lambda: trim(0)


def freeze_start() -> None:
    """What the process's start built (modules, the services, the routes) moved to the GC's permanent generation: it
    lives as long as the process anyway, and a full collection no longer reads it."""
    gc.collect()
    gc.freeze()


def enabled() -> bool:
    return os.getenv("INSIGHT_API_TRIM", "on").strip().lower() not in ("off", "0", "false", "no")


class Trimmer:
    """The requests in flight and the trims. `began`/`ended` run on the event loop; `step` is one look (the thread's,
    and the tests'). `trim`, `rss` and `clock` are seams."""

    def __init__(self, *, trim: Optional[Callable[[], Any]] = None, rss: Callable[[], Optional[float]] = rss_mb,
                 clock: Callable[[], float] = time.monotonic, quiet: float = QUIET, grow_mb: float = GROW_MB,
                 collect: Callable[[], Any] = gc.collect) -> None:
        self.trim, self.rss, self.clock, self.quiet, self.grow_mb = trim, rss, clock, quiet, grow_mb
        self.collect = collect
        self.inflight = 0
        self.idle_at: Optional[float] = None
        self.after_trim: Optional[float] = rss()   # RSS after the last trim (at the start: the start's RSS)
        self.trims = 0
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def began(self) -> None:
        self.inflight += 1
        self.idle_at = None
        if self._thread is None and self.trim is not None:
            self._thread = threading.Thread(target=self._run, name="idle-trim", daemon=True)
            self._thread.start()

    def ended(self) -> None:
        self.inflight -= 1
        if self.inflight <= 0:
            self.inflight = 0
            self.idle_at = self.clock()
            self._wake.set()

    def wait_left(self) -> Optional[float]:
        """Seconds until the quiet spell is long enough (0: now), or None when a request is in flight."""
        idle_at = self.idle_at
        if self.inflight or idle_at is None:
            return None
        return max(0.0, idle_at + self.quiet - self.clock())

    def step(self) -> bool:
        """Collects and trims if the process is idle for `quiet` and grew by `grow_mb` since the last trim. Whether it
        trimmed."""
        if self.trim is None or self.wait_left() != 0.0:
            return False
        now = self.rss()
        if now is not None and self.after_trim is not None and now - self.after_trim < self.grow_mb:
            self.after_trim = min(self.after_trim, now)   # it shrank by itself (an arena freed): count from there
            return False
        self.collect()
        self.trim()
        self.trims += 1
        self.after_trim = self.rss()
        return True

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            while True:
                left = self.wait_left()
                if left is None:          # a request began: its end wakes us again
                    break
                if left > 0:
                    time.sleep(left)
                    continue
                try:
                    self.step()
                except Exception:          # never let the trimmer die on a surprise; the API is unaffected
                    logger.exception("idle trim failed")
                break


class IdleTrim:
    """Pure ASGI middleware: every HTTP request counted in flight from its start to its last byte (and the background
    tasks Starlette runs after it); the trimmer trims when the process is idle."""

    def __init__(self, app: Callable[..., Awaitable[None]], trimmer: Optional[Trimmer] = None) -> None:
        self.app = app
        self.trimmer = trimmer if trimmer is not None else Trimmer(trim=libc_trim() if enabled() else None)

    async def __call__(self, scope: Dict[str, Any], receive: Callable[[], Awaitable[Any]],
                       send: Callable[[Any], Awaitable[None]]) -> None:
        if scope.get("type") != "http" or self.trimmer.trim is None:
            await self.app(scope, receive, send)
            return
        self.trimmer.began()
        try:
            await self.app(scope, receive, send)
        finally:
            self.trimmer.ended()
