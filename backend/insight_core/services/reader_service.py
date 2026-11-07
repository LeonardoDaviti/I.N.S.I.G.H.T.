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
            if query.view != "by_source":   # one post on two channels of a voice shows once (issue 0132 A)
                from insight_core.db.repo_voices import VoicesRepository
                rows = VoicesRepository.also_on(cur, rows, scope_kind=query.scope.kind, scope_id=query.scope.id,
                                                filter=query.filter)
        key = "groups" if query.view == "by_source" else "items"
        return {"success": True, key: rows, "next_cursor": next_cursor.encode() if next_cursor else None}

    def search(self, query: SearchQuery) -> Dict[str, Any]:
        """SearchPage {items (each with its snippet; a story's with its `story`), next_cursor};
        under Classics {classics, next_cursor}, as GET /api/classics shapes them."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            items, next_cursor = self.search_repo.search(cur, query, now=self.clock())
        key = "classics" if query.filter == "classics" else "items"
        return {"success": True, key: items, "next_cursor": next_cursor}

    def fill_search_vectors(self) -> int:
        """Give every post whose search vector is missing (stored before 0033) or made by an
        older rule (0042's search_version) its vector, FILL_BATCH posts a transaction, so no
        write waits on a long one, until none is left (issue 0069). Returns how many were filled."""
        return db.fill_until_done(self.db_url, self.search_repo.fill_missing_vectors, self.search_repo.missing_vectors)

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
