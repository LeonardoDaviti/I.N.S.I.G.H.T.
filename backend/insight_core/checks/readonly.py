"""Make every connection this process opens read-only (issue 0075: the checks only read the copy they
are given). Postgres refuses any write in a read-only transaction, so a service that tried to write
while a check reads it fails loudly instead of changing the copy."""
from __future__ import annotations

from insight_core.db import database

_READ_ONLY = "-c default_transaction_read_only=on"
_done = False


def read_only() -> None:
    """From now on every connection of this process (pooled or a session's) is read-only. Call it before
    the first query: a pool built earlier keeps its connections."""
    global _done
    if _done:
        return
    _done = True
    kwargs = database.Database._connect_kwargs

    def read_only_kwargs(self) -> dict:
        out = dict(kwargs(self))
        out["options"] = f"{out.get('options', '')} {_READ_ONLY}".strip()
        return out

    database.Database._connect_kwargs = read_only_kwargs
    session = database.session_connection

    def read_only_session(url: str, *, autocommit: bool = False):
        conn = session(url, autocommit=autocommit)
        with conn.cursor() as cur:
            cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        if not autocommit:
            conn.commit()
        return conn

    database.session_connection = read_only_session
    database.close_all()   # a pool built before this call would keep writable connections


def is_read_only(cur) -> bool:
    cur.execute("SHOW transaction_read_only")
    return cur.fetchone()[0] == "on"
