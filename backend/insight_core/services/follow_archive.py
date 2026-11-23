"""Following a feed queues its archive (0167): a feed lists only its newest items, so a new source would miss its
own recent past.

On follow (`queue_on_follow`), the archive is queued back to the reading window (else FOLLOW_ARCHIVE_DAYS) through
the normal archive queue; the ingestion process runs it, nothing runs in the request. Only a website's own feed of a
kind whose archive goes newest first and can stop at a date (FOLLOW_KINDS: feeds, Substack); never an aggregator's,
X, Telegram or a page watch. A disabled source, or one already queued or running, is left (the answer says why).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from insight_core.db import database as db
from insight_core.utils import own_pages

logger = logging.getLogger("insight.follow_archive")

FOLLOW_ARCHIVE_DAYS = 180                          # the horizon when the reading window is every post or unset
FOLLOW_KINDS = frozenset({"generic_rss", "substack"})
READING_WINDOW_KEY = "reading_window_days"         # mx_settings (markx/tasks.READING_WINDOW), read only


def reading_window(cur: Any) -> Optional[int]:
    """The owner's reading window when it is a number of days, else None (every post, never set, or no Mark X)."""
    cur.execute("SELECT to_regclass('mx_settings') IS NOT NULL")
    if not cur.fetchone()[0]:
        return None
    cur.execute("SELECT value FROM mx_settings WHERE key = %s", (READING_WINDOW_KEY,))
    row = cur.fetchone()
    value = row[0] if row else None
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def horizon(db_url: str, now: Optional[datetime] = None) -> str:
    """The date a follow's archive reaches back to (ISO)."""
    now = now or datetime.now(timezone.utc)
    try:
        with db.connection(db_url) as conn, conn.cursor() as cur:
            days = reading_window(cur) or FOLLOW_ARCHIVE_DAYS
    except Exception:  # noqa: BLE001 - the default depth
        days = FOLLOW_ARCHIVE_DAYS
    return (now - timedelta(days=days)).date().isoformat()


def plan(services: Any, source_id: str) -> Dict[str, Any]:
    """Whether a source's follow archive is queued: {"queue": bool, "reason"}; no network."""
    source = services.sources.get_source_with_settings(source_id)
    if not source:
        return {"queue": False, "reason": "no such source"}
    if not source.get("enabled", True):
        return {"queue": False, "reason": "disabled"}
    if not own_pages.owns(source.get("platform"), source.get("handle_or_url"), source.get("handle_or_url")):
        return {"queue": False, "reason": "not a website's own feed (an aggregator's): archived by hand"}
    fetch = services.source_fetch
    kind = fetch.kinds.resolve(source)
    if kind.name not in FOLLOW_KINDS:
        return {"queue": False, "reason": f"a {kind.name} archive is started by hand"}
    support = fetch.archive_support(source_id)
    if not support.get("archivable"):
        return {"queue": False, "reason": support.get("reason") or "it cannot archive"}
    if not support.get("until"):
        return {"queue": False, "reason": "its archive can't stop at a date"}
    return {"queue": True, "reason": None}


def queue_on_follow(services: Any, jobs: Callable[[], Any], source_id: str, *,
                    now: Optional[datetime] = None) -> Dict[str, Any]:
    """Queue the archive of a source just followed (or asked for), back to `horizon`: {"queued", "until", "status",
    "job_id"} or {"queued": False, "reason"}. `jobs` builds the ArchiveJobs. Blocking (run it in a thread); never
    raises."""
    try:
        planned = plan(services, source_id)
        if not planned["queue"]:
            return {"queued": False, "reason": planned["reason"]}
        until = horizon(services.source_fetch.db_url, now)
        job_id, status = jobs().enqueue(source_id, resume=True, until=until)
        if job_id:
            logger.info("Following %s: its archive is queued back to %s", source_id, until)
        return {"queued": bool(job_id), "until": until, "status": status, "job_id": job_id}
    except Exception as exc:  # noqa: BLE001 - the source is followed; its archive is the button's
        logger.warning("Could not queue the follow archive of %s: %s", source_id, exc)
        return {"queued": False, "reason": "error"}


__all__ = ["FOLLOW_ARCHIVE_DAYS", "FOLLOW_KINDS", "horizon", "plan", "queue_on_follow", "reading_window"]
