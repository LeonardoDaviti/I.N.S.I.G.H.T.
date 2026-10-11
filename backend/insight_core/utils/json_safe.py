"""Turning values psycopg returns into JSON: ISO time strings, a json.dumps fallback, and a
JSON-safe copy of a nested payload. One copy each, so a fix lands everywhere at once.

Rows come back from psycopg with `id` columns as `uuid.UUID` and times as `datetime`, so a
payload built from a fetched row (a job payload naming a post, a source settings blob) needs
one of these before json.dumps.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID


def iso(value: Any) -> Optional[str]:
    """value.isoformat(), or None for a missing value."""
    return value.isoformat() if value else None


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


def json_safe(value: Any) -> Any:
    """A copy of a nested payload with every time as its ISO string.

    Dicts and lists are walked (a tuple becomes a list); anything with isoformat() becomes
    its ISO string (str() if that fails); every other value is kept as it is.
    """
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value
