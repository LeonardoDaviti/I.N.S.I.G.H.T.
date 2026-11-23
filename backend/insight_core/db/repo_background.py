"""Background work, read from what the jobs already record: the story job's last summary, rebuild progress and
whether it runs now (pg_locks); posts missing a current search vector; posts whose links were never read.
Read only: nothing here starts, stops or tunes a job.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from psycopg import Cursor

SUMMARY_FIELDS = ("computed_at", "seconds", "full", "posts", "stories", "news", "classics", "links_filled")


def background_work(cur: Cursor, *, stories_key: str, stories_lock: str) -> Dict[str, Any]:
    """`stories_key`, `stories_lock`: the story job's setting and lock (stories_service)."""
    cur.execute(
        """
        SELECT (SELECT value FROM system_settings WHERE key = %(key)s),
               EXISTS (SELECT 1 FROM pg_locks l JOIN pg_database d ON d.oid = l.database
                       WHERE d.datname = current_database() AND l.locktype = 'advisory' AND l.objsubid = 1
                         AND l.granted
                         AND ((l.classid::bigint << 32) | l.objid::bigint) = hashtext(%(lock)s)::bigint),
               count(*),
               count(*) FILTER (WHERE search_vector IS NULL OR search_version IS DISTINCT FROM search_vector_version()),
               count(*) FILTER (WHERE links_scanned_at IS NULL)
        FROM posts
        """,
        {"key": stories_key, "lock": stories_lock},
    )
    summary, running, posts, unindexed, unread = cur.fetchone()
    last: Optional[Dict[str, Any]] = None
    if isinstance(summary, dict) and summary.get("computed_at"):
        last = {field: summary.get(field) for field in SUMMARY_FIELDS}
        rebuild = summary.get("rebuild")   # new rules regroup every post in batches
        last["rebuild"] = {"done": int(rebuild.get("done") or 0), "total": int(rebuild.get("total") or 0)} \
            if isinstance(rebuild, dict) else None
    return {
        "stories": {"running": bool(running), "last_run": last},
        "search": {"total": int(posts), "pending": int(unindexed)},
        "links": {"total": int(posts), "pending": int(unread)},
    }


__all__ = ["background_work"]
