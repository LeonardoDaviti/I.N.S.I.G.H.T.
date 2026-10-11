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

Ingestion holds a pooled connection only for one store call, never across a fetch. The
run lock needs a session of its own for the whole run, so it takes an unpooled
`session_connection` instead.

Environment (read when a pool is built):
  INSIGHT_DB_POOL_MIN (1), INSIGHT_DB_POOL_MAX (5)   connections per process
  INSIGHT_DB_POOL_TIMEOUT_SECONDS (10)               wait for a free connection, then fail
  INSIGHT_DB_STATEMENT_TIMEOUT_MS (60000)            0 turns the timeout off
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Dict, Iterator, Optional

import psycopg
from psycopg_pool import ConnectionPool

from insight_core.utils.env import env_int

CONNECT_TIMEOUT_SECONDS = 10


class Database:
    def __init__(
        self,
        url: str,
        *,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        timeout: Optional[float] = None,
        statement_timeout_ms: Optional[int] = None,
    ) -> None:
        self.url = url
        self.statement_timeout_ms = (statement_timeout_ms if statement_timeout_ms is not None
                                     else env_int("INSIGHT_DB_STATEMENT_TIMEOUT_MS", 60_000))
        max_size = max_size or env_int("INSIGHT_DB_POOL_MAX", 5)
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
        kwargs: dict = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
        if self.statement_timeout_ms > 0:
            kwargs["options"] = f"-c statement_timeout={self.statement_timeout_ms}"
        return kwargs

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
            yield conn

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Cursor]:
        """One transaction on a pooled connection: committed if the block ends, rolled back if it raises."""
        with self.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                yield cur

    def session_connection(self, *, autocommit: bool = False) -> psycopg.Connection:
        """An unpooled connection the caller closes: for session state (an advisory lock)
        that must live exactly as long as the connection."""
        return psycopg.connect(self.url, autocommit=autocommit, **self._connect_kwargs())

    def close(self) -> None:
        with self._lock:
            if self._opened:
                self._pool.close()
                self._opened = False


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


def session_connection(url: str, *, autocommit: bool = False) -> psycopg.Connection:
    return database(url).session_connection(autocommit=autocommit)


def close_all() -> None:
    with _databases_lock:
        for db in _databases.values():
            db.close()
        _databases.clear()
