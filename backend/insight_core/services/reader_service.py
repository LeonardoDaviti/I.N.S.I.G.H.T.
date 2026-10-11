"""Reader: the feed, read state and unread counts (Mark IX, B7).

Owns the connection and transaction lifecycle around ReaderRepository and turns its
results into the API shapes (FeedPage, FeedGroupsPage, MarkReadResult, UnreadCounts).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Sequence

from insight_core.db import database as db

from insight_core.db.repo_reader import FeedCursor, FeedScope, ReaderRepository


class ReaderService:
    def __init__(self, db_url: str, *, repo: ReaderRepository | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.db_url = db_url
        self.repo = repo or ReaderRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def feed(self, scope: FeedScope, *, filter: str, view: str, cursor: FeedCursor | None,
             limit: int = 30, days: int | None = None) -> Dict[str, Any]:
        since = self.clock() - timedelta(days=days) if days else None
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            if view == "by_source":
                groups, next_cursor = self.repo.feed_by_source(
                    cur, scope, filter=filter, group_cursor=cursor, groups=min(limit, 50), since=since,
                )
                return {"success": True, "groups": groups,
                        "next_cursor": next_cursor.encode() if next_cursor else None}
            items, next_cursor = self.repo.feed(cur, scope, filter=filter, cursor=cursor, limit=limit, since=since)
            return {"success": True, "items": items,
                    "next_cursor": next_cursor.encode() if next_cursor else None}

    def unread_counts(self) -> Dict[str, Any]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.unread_counts(cur)

    def mark_read_through(self, scope: FeedScope, through: FeedCursor, newest: FeedCursor) -> Dict[str, Any]:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                ids = self.repo.mark_read_through(cur, scope, through, newest=newest, now=self.clock())
            conn.commit()
        return {"success": True, "updated": len(ids), "ids": ids}

    def set_read(self, post_ids: Sequence[str], read: bool) -> int:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                updated = self.repo.set_read(cur, post_ids, read)
            conn.commit()
        return updated
