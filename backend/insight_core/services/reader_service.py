"""Reader: the post listing, search (issue 0040), read state, Later (issue 0022) and unread
counts (Mark IX, B7).

Owns the connection and transaction lifecycle around ReaderRepository and turns its
results into the API shapes (FeedPage, FeedGroupsPage, ReadStateResult, UnreadCounts).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Sequence

from insight_core.db import database as db

from insight_core.db.repo_reader import FeedCursor, FeedQuery, FeedScope, ReaderRepository
from insight_core.db.repo_search import SearchQuery, SearchRepository


def _read_state_result(ids: List[str]) -> Dict[str, Any]:
    return {"success": True, "updated": len(ids), "ids": ids}


class ReaderService:
    def __init__(self, db_url: str, *, repo: ReaderRepository | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.db_url = db_url
        self.repo = repo or ReaderRepository()
        self.search_repo = SearchRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def list_posts(self, query: FeedQuery) -> Dict[str, Any]:
        """FeedPage {items, next_cursor}, or FeedGroupsPage {groups, next_cursor} for view=by_source."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            rows, next_cursor = self.repo.list_posts(cur, query, now=self.clock())
        key = "groups" if query.view == "by_source" else "items"
        return {"success": True, key: rows, "next_cursor": next_cursor.encode() if next_cursor else None}

    def search(self, query: SearchQuery) -> Dict[str, Any]:
        """SearchPage {items (each with its snippet), next_cursor}."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            items, next_cursor = self.search_repo.search(cur, query, now=self.clock())
        return {"success": True, "items": items, "next_cursor": next_cursor}

    def fill_search_vectors(self) -> int:
        """Give every post stored before search (0033) its search vector, FILL_BATCH posts a
        transaction, so no write waits on a long one. Returns how many were filled."""
        filled = 0
        while True:
            with db.transaction(self.db_url) as cur:
                batch = self.search_repo.fill_missing_vectors(cur)
            filled += batch
            if not batch:
                return filled

    def unread_counts(self) -> Dict[str, Any]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.unread_counts(cur)

    def set_read(self, post_ids: Sequence[str], read: bool, keep_later: bool = False) -> Dict[str, Any]:
        """Mark these posts read or unread. `ids` are the ones that changed.

        An explicit mark read finishes a post, so it also leaves Later (issue 0022) and where it
        was left is cleared (issue 0030); `keep_later` is a read that is only an open (the feed
        marking what it opens), which finishes nothing.
        """
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                ids = self.repo.set_read(cur, post_ids, read)
                if read and not keep_later:
                    self.repo.set_later(cur, post_ids, False)
                    self.repo.clear_positions(cur, post_ids)
            conn.commit()
        return _read_state_result(ids)

    def set_later(self, post_ids: Sequence[str], later: bool, at: datetime | None = None) -> Dict[str, Any]:
        """Put posts in Later (at `at`, default now) or take them out. `ids` are the ones that changed."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                ids = self.repo.set_later(cur, post_ids, later, at=at)
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
