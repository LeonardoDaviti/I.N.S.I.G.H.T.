"""Watched pages (issue 0039, migration 0037): which are due, what each check found, and what the
saver does when a watched post's text changes.

When a page is due again (next_check_at): half the time since it last changed (else since it
was published, else first seen), at least CHECK_MIN and at most CHECK_MAX. A page changed
yesterday is looked at daily, one untouched for a month or more every two weeks, so a site's
recently edited pages are re-read most and its old ones still come round.

A meaningful change (utils.text_changes.meaningful) brings the post back: surfaced_at is now
(the feed shows it at the top), metadata.page_update says what changed, and a post the owner
had read becomes unread again. A tiny change keeps the new text silently.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from psycopg import Cursor
from psycopg.types.json import Jsonb

from insight_core.ingestion.kinds.parsing import parse_datetime_value
from insight_core.utils.text_changes import change_summary, meaningful, text_hash

CHECK_MIN = "1 day"
CHECK_MAX = "14 days"
UPDATE_KEY = "page_update"     # posts.metadata: the last meaningful change, {at, words, words_added, ...}


def _next_check(now: str) -> str:
    """The SQL for when a page is next due, given `now`'s SQL; p is the post, w its watch row."""
    return (f"{now} + LEAST(GREATEST(({now} - COALESCE(w.changed_at, p.published_at, p.fetched_at)) / 2,"
            f" interval '{CHECK_MIN}'), interval '{CHECK_MAX}')")


class PageWatchRepository:
    """SQL for post_watch. Takes the caller's cursor; the caller owns the commit."""

    def due(self, cur: Cursor, source_id: str, *, now: datetime, limit: int) -> List[Dict[str, Any]]:
        """Up to `limit` of a source's pages due a check: the longest overdue first, then pages
        never checked (newest first). A page never checked has no row: its hash is its stored text's."""
        cur.execute(
            """
            SELECT p.id, p.url, w.text_hash, CASE WHEN w.post_id IS NULL THEN p.content END,
                   w.modified, w.head_missed, w.etag, w.last_modified, w.learned_at
            FROM posts p
            LEFT JOIN post_watch w ON w.post_id = p.id
            WHERE p.source_id = %s AND (w.post_id IS NULL OR w.next_check_at <= %s)
            ORDER BY w.next_check_at ASC NULLS LAST, p.published_at DESC NULLS LAST, p.id
            LIMIT %s
            """,
            (source_id, now, limit),
        )
        return [
            {"post_id": str(row[0]), "url": row[1], "text_hash": row[2] or text_hash(row[3]),
             "modified": row[4], "head_missed": bool(row[5]), "etag": row[6], "last_modified": row[7],
             "learned_at": row[8]}
            for row in cur.fetchall()
        ]

    def checked(self, cur: Cursor, source_id: str, checks: Sequence[Dict[str, Any]], *, now: datetime) -> None:
        """Record checks ({post_id, text_hash, modified, head_missed, etag, last_modified,
        learned_at}): when each was checked and is due again. The saver has already recorded a
        change (changed_at), so a page that just changed is due again soonest."""
        cur.executemany(
            f"""
            INSERT INTO post_watch (post_id, source_id, text_hash, modified, head_missed, etag, last_modified,
                                    learned_at, checked_at, next_check_at)
            SELECT p.id, %(source_id)s, %(text_hash)s, %(modified)s, %(head_missed)s, %(etag)s, %(last_modified)s,
                   %(learned_at)s, %(now)s, {_next_check('%(now)s::timestamptz')}
            FROM posts p LEFT JOIN post_watch w ON w.post_id = p.id
            WHERE p.id = %(post_id)s::uuid
            ON CONFLICT (post_id) DO UPDATE SET
                text_hash = EXCLUDED.text_hash, modified = EXCLUDED.modified, head_missed = EXCLUDED.head_missed,
                etag = EXCLUDED.etag, last_modified = EXCLUDED.last_modified, learned_at = EXCLUDED.learned_at,
                checked_at = EXCLUDED.checked_at, next_check_at = EXCLUDED.next_check_at
            """,
            [{**check, "source_id": source_id, "now": now} for check in checks],
        )

    def saved(self, cur: Cursor, post_id: str, source_id: str, post: Dict[str, Any],
              old: Optional[Dict[str, Any]]) -> bool:
        """After a watched post was written: keep its text's hash and, when the text changed
        meaningfully since `old` ({content, content_html} before the write; None for a new
        post), bring it back. Returns whether it came back."""
        new_hash = text_hash(post.get("content"))
        stated = parse_datetime_value(str((post.get("metadata") or {}).get("modified") or "")) or None
        modified = stated.isoformat() if stated else None   # as page_changes reads it: parsing.page_modified
        update = None
        if old is not None and text_hash(old.get("content")) != new_hash:
            summary = change_summary(old.get("content"), post.get("content"), old.get("content_html"),
                                     post.get("content_html"))
            if meaningful(summary):
                update = summary
        if update is not None:
            cur.execute(
                f"""
                UPDATE posts SET surfaced_at = now(),
                       metadata = metadata || jsonb_build_object('{UPDATE_KEY}', %s::jsonb || jsonb_build_object('at', now()))
                WHERE id = %s::uuid
                """,
                (Jsonb(update), post_id),
            )
            cur.execute(
                "UPDATE post_reader_state SET read_at = NULL, updated_at = now() WHERE post_id = %s::uuid AND read_at IS NOT NULL",
                (post_id,),
            )
        cur.execute(
            f"""
            INSERT INTO post_watch (post_id, source_id, text_hash, modified, changed_at, next_check_at)
            SELECT p.id, %(source_id)s, %(hash)s, %(modified)s, CASE WHEN %(changed)s THEN now() END,
                   CASE WHEN %(changed)s THEN now() + interval '{CHECK_MIN}' ELSE {_next_check('now()')} END
            FROM posts p LEFT JOIN post_watch w ON w.post_id = p.id
            WHERE p.id = %(post_id)s::uuid
            ON CONFLICT (post_id) DO UPDATE SET
                text_hash = EXCLUDED.text_hash,
                modified = COALESCE(EXCLUDED.modified, post_watch.modified),
                changed_at = COALESCE(EXCLUDED.changed_at, post_watch.changed_at),
                next_check_at = CASE WHEN %(changed)s THEN EXCLUDED.next_check_at ELSE post_watch.next_check_at END
            """,
            {"post_id": post_id, "source_id": source_id, "hash": new_hash, "changed": update is not None,
             "modified": modified},
        )
        return update is not None


__all__ = ["CHECK_MAX", "CHECK_MIN", "PageWatchRepository", "UPDATE_KEY"]
