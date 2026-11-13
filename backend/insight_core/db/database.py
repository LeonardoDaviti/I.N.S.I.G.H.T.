"""The one place that opens database connections.

    from insight_core.db import database as db

    with db.connection(url) as conn, conn.cursor() as cur:   # reads (and writes that commit)
        ...
    with db.transaction(url) as cur:                         # one transaction: commit or roll back
        ...

Each process (the API, the ingestion container) keeps one small pool per database URL,
built on first use. A pooled connection behaves like `with psycopg.connect(url) as conn`:
it commits on a clean exit and rolls back on an error, then goes back to the pool. Every
connection runs with a statement timeout.

No code holds a pooled connection across a network fetch: ingestion, archives, Reddit
comments and the image proxy read or store in one short block, then fetch with the
connection back in the pool. The run lock and the admin bootstrap need a session of their
own, so they take a plain `session_connection` instead (no pool, no statement timeout).

Environment (read when a pool is built):
  INSIGHT_DB_POOL_MIN (1), INSIGHT_DB_POOL_MAX (10)  connections per process
  INSIGHT_DB_POOL_TIMEOUT_SECONDS (10)               wait for a free connection, then fail
  INSIGHT_DB_STATEMENT_TIMEOUT_MS (300000)           0 turns the timeout off
  INSIGHT_DB_IDLE_IN_TRANSACTION_MS (by role)        0 turns it off
  INSIGHT_DB_REQUEST_TIMEOUT_MS (30000)              an API request's statements; 0 turns it off
  INSIGHT_DB_ROLE ("jobs", "api" or unset)           see Roles

The statement timeout is 5 minutes, not less: deleting a big source cascades to every
post it collected, and that one DELETE can run for minutes.

Roles (issue 0188): a process says what it is in INSIGHT_DB_ROLE, read when a pool is built; the processes it
spawns inherit it with the environment.
  - "jobs" (insight-ingestion: the scheduler, its archives and Mark X's job processes; run_scheduler.py sets it):
    a statement ends just under a job's HARD_LIMIT (JOBS_STATEMENT_TIMEOUT_MS), and a transaction idle for longer
    than any job lives (JOBS_IDLE_IN_TRANSACTION_MS) is ended by Postgres, its locks freed.
  - "api" (the API's processes; scripts/api_supervisor.py sets it): the process default stays 5 minutes (its
    background tasks: archives, fetches, research), an idle transaction ends after API_IDLE_IN_TRANSACTION_MS, and
    a request's own statements get REQUEST_STATEMENT_TIMEOUT_MS, set by `RequestTimeouts` (main.py's innermost
    middleware) until the response is sent, so the background tasks Starlette runs after it have the process
    default. A request that legitimately runs a long statement says so: `with long_statements():` (deleting a
    source).
  - unset (scripts, tests, the real-data check): as before.
Every connection also has client_connection_check_interval (CLIENT_CHECK_MS): a statement whose client died (a job
process killed at HARD_LIMIT, or by the kernel's OOM killer) is cancelled within seconds, its locks freed, instead
of running to its end.
"""
from __future__ import annotations

import contextvars
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional

import psycopg
from psycopg_pool import ConnectionPool

from insight_core.utils.env import env_int

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 10
STATEMENT_TIMEOUT_MS = 300_000   # 5 minutes: the cascading delete of a big source
LOCKED_WAIT_SECONDS = 1.0        # fill_until_done: a batch found only rows another worker holds
POOL_MAX = 10
CLIENT_CHECK_MS = 10_000                 # 0188: a statement whose client is gone is cancelled within this
JOBS_STATEMENT_TIMEOUT_MS = 840_000      # 0188: just under markx/jobs.HARD_LIMIT (900 s): Postgres ends it first
JOBS_IDLE_IN_TRANSACTION_MS = 960_000    # 0188: longer than any job lives (HARD_LIMIT + a minute)
API_IDLE_IN_TRANSACTION_MS = 120_000     # 0188: no API code holds a transaction across a fetch
REQUEST_STATEMENT_TIMEOUT_MS = 30_000    # 0188: a request's own statements (RequestTimeouts)
ROLES = {
    "jobs": {"statement_timeout_ms": JOBS_STATEMENT_TIMEOUT_MS, "idle_in_transaction_ms": JOBS_IDLE_IN_TRANSACTION_MS},
    "api": {"statement_timeout_ms": STATEMENT_TIMEOUT_MS, "idle_in_transaction_ms": API_IDLE_IN_TRANSACTION_MS},
}
ROLE_ENV = "INSIGHT_DB_ROLE"

# 0188: the statement timeout of the request being served (None: the process default); RequestTimeouts sets it
_request_timeout_ms: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("insight_request_timeout",
                                                                                   default=None)
_TIMEOUT_ATTR = "_insight_statement_timeout"


def role() -> Optional[str]:
    value = (os.getenv(ROLE_ENV) or "").strip().lower()
    return value if value in ROLES else None


def use_role(name: str) -> None:
    """This process, and the processes it spawns, open connections as `name` (ROLES); call it before the first
    pool is built."""
    if name not in ROLES:
        raise ValueError(f"unknown database role {name!r}")
    os.environ[ROLE_ENV] = name


@contextmanager
def long_statements() -> Iterator[None]:
    """0188: inside a request, statements run with the process default (5 minutes), not the request's 30 s: for a
    request that legitimately runs a long one (deleting a big source cascades to every post it collected)."""
    token = _request_timeout_ms.set(None)
    try:
        yield
    finally:
        _request_timeout_ms.reset(token)


class RequestTimeouts:
    """0188: the API's middleware (pure ASGI, added innermost in main.py): an HTTP request's statements get
    REQUEST_STATEMENT_TIMEOUT_MS (INSIGHT_DB_REQUEST_TIMEOUT_MS; 0 turns it off) until its response's last body is
    sent; the background tasks Starlette runs after that have the process default."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.ms = env_int("INSIGHT_DB_REQUEST_TIMEOUT_MS", REQUEST_STATEMENT_TIMEOUT_MS, minimum=0)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not self.ms:
            await self.app(scope, receive, send)
            return
        token = _request_timeout_ms.set(self.ms)

        async def sent(message: Any) -> None:
            await send(message)
            if message.get("type") == "http.response.body" and not message.get("more_body", False):
                _request_timeout_ms.set(None)    # the response is out: what runs after it is background work
        try:
            await self.app(scope, receive, sent)
        finally:
            _request_timeout_ms.reset(token)


class Database:
    def __init__(
        self,
        url: str,
        *,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        timeout: Optional[float] = None,
        statement_timeout_ms: Optional[int] = None,
        idle_in_transaction_ms: Optional[int] = None,
    ) -> None:
        self.url = url
        settings = ROLES.get(role() or "", {})
        self.statement_timeout_ms = (statement_timeout_ms if statement_timeout_ms is not None
                                     else env_int("INSIGHT_DB_STATEMENT_TIMEOUT_MS",
                                                  settings.get("statement_timeout_ms", STATEMENT_TIMEOUT_MS)))
        self.idle_in_transaction_ms = (idle_in_transaction_ms if idle_in_transaction_ms is not None
                                       else env_int("INSIGHT_DB_IDLE_IN_TRANSACTION_MS",
                                                    settings.get("idle_in_transaction_ms", 0), minimum=0))
        max_size = max_size or env_int("INSIGHT_DB_POOL_MAX", POOL_MAX)
        min_size = min(min_size if min_size is not None else env_int("INSIGHT_DB_POOL_MIN", 1), max_size)
        self._pool = ConnectionPool(
            url,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout if timeout is not None else env_int("INSIGHT_DB_POOL_TIMEOUT_SECONDS", 10),
            kwargs=self._connect_kwargs(),
            check=ConnectionPool.check_connection,   # a connection the server dropped is replaced
            name="insight",
            open=False,
        )
        self._opened = False
        self._lock = threading.Lock()

    def _connect_kwargs(self) -> dict:
        # JIT off: INSIGHT's queries are small aggregates the planner overestimates. Measured on the
        # server's data (the lab, 2026-10-30): compiling cost ~300 ms of the Sources list's 370 ms, and
        # no endpoint got slower without it.
        check = env_int("INSIGHT_DB_CLIENT_CHECK_MS", CLIENT_CHECK_MS, minimum=0)
        options = ["-c jit=off", f"-c client_connection_check_interval={check}"]
        if self.statement_timeout_ms > 0:
            options.append(f"-c statement_timeout={self.statement_timeout_ms}")
        if self.idle_in_transaction_ms > 0:
            options.append(f"-c idle_in_transaction_session_timeout={self.idle_in_transaction_ms}")
        return {"connect_timeout": CONNECT_TIMEOUT_SECONDS, "options": " ".join(options)}

    def _ensure_open(self) -> None:
        if not self._opened:
            with self._lock:
                if not self._opened:
                    # wait=False: a database that is down fails the first request after
                    # `timeout`, not the process start.
                    self._pool.open(wait=False)
                    self._opened = True

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """A pooled connection: commit on a clean exit, roll back on an error."""
        self._ensure_open()
        with self._pool.connection() as conn:
            self._timeout_for(conn)
            yield conn

    def _timeout_for(self, conn: psycopg.Connection) -> None:
        """0188: the connection's statement timeout as the code using it needs: a request's (RequestTimeouts) or the
        process default. Set, and committed so a roll back of the block keeps it, only when it differs from what the
        connection has: one round trip when a connection passes between a request and background work."""
        want = _request_timeout_ms.get()
        want = self.statement_timeout_ms if want is None else want
        if getattr(conn, _TIMEOUT_ATTR, self.statement_timeout_ms) == want:
            return
        conn.execute(f"SET statement_timeout = {int(want)}")
        if not conn.autocommit:
            conn.commit()
        setattr(conn, _TIMEOUT_ATTR, want)

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Cursor]:
        """One transaction on a pooled connection: committed if the block ends, rolled back if it raises. What the
        block hands `after_commit` runs once the commit is done, and never after a roll back."""
        with self.connection() as conn:
            setattr(conn, _AFTER_COMMIT, [])
            try:
                with conn.transaction(), conn.cursor() as cur:
                    yield cur
                hooks = getattr(conn, _AFTER_COMMIT)
            finally:
                setattr(conn, _AFTER_COMMIT, None)
        for hook in hooks:
            try:
                hook()
            except Exception:   # noqa: BLE001 - the transaction is committed; a hook never undoes it
                logger.exception("database: a hook after a commit failed")

    def session_connection(self, *, autocommit: bool = False) -> psycopg.Connection:
        """An unpooled connection the caller closes: for session state (an advisory lock)
        that must live exactly as long as the connection."""
        return psycopg.connect(self.url, autocommit=autocommit, **self._connect_kwargs())

    def close(self) -> None:
        with self._lock:
            if self._opened:
                self._pool.close()
                self._opened = False


_AFTER_COMMIT = "_insight_after_commit"


def after_commit(conn: Any, hook: Callable[[], Any]) -> bool:
    """Run `hook` once the transaction `Database.transaction` opened on `conn` commits (never if it rolls back).
    False when `conn` is in no such transaction (a plain connection): the hook is not kept."""
    hooks = getattr(conn, _AFTER_COMMIT, None)
    if hooks is None:
        return False
    hooks.append(hook)
    return True


_databases: Dict[str, Database] = {}
_databases_lock = threading.Lock()


def database(url: str) -> Database:
    """The process's Database for `url`, built on first use."""
    db = _databases.get(url)
    if db is None:
        with _databases_lock:
            db = _databases.get(url)
            if db is None:
                db = _databases[url] = Database(url)
    return db


def connection(url: str):
    return database(url).connection()


def transaction(url: str):
    return database(url).transaction()


def fill_until_done(url: str, fill: Callable[[Any], int], pending: Callable[[Any], bool]) -> int:
    """Run `fill(cur)` a transaction a batch until `pending(cur)` finds nothing left; how many it
    filled. Batches take their rows `FOR UPDATE SKIP LOCKED`, so an empty batch while rows are pending
    means another worker holds them (the search refill and the link reading, issue 0069): wait a
    moment and go on, never stop there."""
    filled = 0
    while True:
        with transaction(url) as cur:
            batch = fill(cur)
            left = batch or pending(cur)
        filled += batch
        if not left:
            return filled
        if not batch:
            time.sleep(LOCKED_WAIT_SECONDS)


def session_connection(url: str, *, autocommit: bool = False) -> psycopg.Connection:
    """A plain connection the caller closes: no pool and no statement timeout (the run lock,
    the admin bootstrap)."""
    return psycopg.connect(url, autocommit=autocommit, connect_timeout=CONNECT_TIMEOUT_SECONDS)


def close_all() -> None:
    with _databases_lock:
        for db in _databases.values():
            db.close()
        _databases.clear()
