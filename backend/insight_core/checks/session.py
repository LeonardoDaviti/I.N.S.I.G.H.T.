"""Opening a copy for the checks: read-only, on the copy's own clock."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import psycopg

from insight_core.checks.readonly import read_only


def open_copy(db_url: str, *, writable: bool = False) -> psycopg.Connection:
    """A connection to the copy, autocommit, read-only unless `writable` (only ever a scratch copy).
    Read-only also makes every pooled connection the services open read-only (readonly.read_only)."""
    if not writable:
        read_only()
    options = "-c jit=off" + ("" if writable else " -c default_transaction_read_only=on")
    return psycopg.connect(db_url, autocommit=True, options=options)


def copy_now(cur, given: Optional[str] = None) -> datetime:
    """The checks' "now": `given` (ISO), else the copy's last fetch, so a copy checked on another day
    shows the same News and the same Classics' "cited again"."""
    if given:
        t = datetime.fromisoformat(given)
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    cur.execute("SELECT max(fetched_at) FROM posts")
    t = cur.fetchone()[0]
    return t or datetime.now(timezone.utc)
