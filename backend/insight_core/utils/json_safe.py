"""Shared JSON encoding fallback for values psycopg returns.

Nine repositories each carried their own private `_json_default` that handled
`datetime`/`date` and raised on everything else. Rows come back from psycopg with
`id` columns as `uuid.UUID`, so any payload built from a fetched row - an inbox
action referencing a post_id, a story metadata blob, an evidence artifact - raised
`TypeError: Object of type <class 'uuid.UUID'> is not JSON serializable` at write
time. Fixing it in one place keeps the nine from drifting apart again.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID


def json_default(value: Any) -> Any:
    """Encode values json.dumps cannot handle natively.

    Pass as `json.dumps(obj, default=json_default)`.
    """
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        # float() would silently lose precision on money-like values; str round-trips.
        return str(value)
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, memoryview):
        return value.tobytes().decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(value)} is not JSON serializable")
