"""Reader: the post listing, read state and unread counts (Mark IX, B7).

Owns the connection and transaction lifecycle around ReaderRepository and turns its
results into the API shapes (FeedPage, FeedGroupsPage, ReadStateResult, UnreadCounts).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Sequence

from insight_core.db import database as db

from insight_core.db.repo_reader import FeedCursor, FeedQuery, FeedScope, ReaderRepository


def _read_state_result(ids: List[str]) -> Dict[str, Any]:
    return {"success": True, "updated": len(ids), "ids": ids}


class ReaderService:
    def __init__(self, db_url: str, *, repo: ReaderRepository | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.db_url = db_url
        self.repo = repo or ReaderRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def list_posts(self, query: FeedQuery) -> Dict[str, Any]:
        """FeedPage {items, next_cursor}, or FeedGroupsPage {groups, next_cursor} for view=by_source."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            rows, next_cursor = self.repo.list_posts(cur, query, now=self.clock())
        key = "groups" if query.view == "by_source" else "items"
        return {"success": True, key: rows, "next_cursor": next_cursor.encode() if next_cursor else None}

    def unread_counts(self) -> Dict[str, Any]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.unread_counts(cur)

    def set_read(self, post_ids: Sequence[str], read: bool) -> Dict[str, Any]:
        """Mark these posts read or unread. `ids` are the ones that changed. Marked read, a
        post is done with: where it was left is cleared (issue 0030)."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                ids = self.repo.set_read(cur, post_ids, read)
                if read:
                    self.repo.clear_positions(cur, post_ids)
            conn.commit()
        return _read_state_result(ids)

    def mark_read_through(self, scope: FeedScope, through: FeedCursor, newest: FeedCursor) -> Dict[str, Any]:
        """Mark read every unread post in `scope` from `newest` down to `through`. `ids` undo it."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                ids = self.repo.mark_read_through(cur, scope, through, newest=newest, now=self.clock())
                self.repo.clear_positions(cur, ids)
            conn.commit()
        return _read_state_result(ids)
