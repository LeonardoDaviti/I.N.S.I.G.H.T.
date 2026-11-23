"""Reader: the post listing, search, read state, Later and unread counts.

Owns the connections and transactions around ReaderRepository and shapes its results for the API.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Sequence

from insight_core.db import database as db

from insight_core.db.repo_reader import FeedCursor, FeedQuery, FeedScope, ReaderRepository
from insight_core.db.repo_search import SearchQuery, SearchRepository


def _read_state_result(ids: List[str]) -> Dict[str, Any]:
    return {"success": True, "updated": len(ids), "ids": ids}


# what the unread counts read, as kept inputs (markx/kept_pages.changes)
UNREAD_INPUTS = ("posts", "reads", "stories", "parts", "folders")


def unread_inputs(cur: Any) -> List[Any]:
    from insight_core.markx import kept_pages
    return kept_pages.changes(cur, UNREAD_INPUTS)


def unread_missing(cur: Any, repo: ReaderRepository | None = None) -> bool:
    """Whether the unread counts are not kept for their current inputs (the jobs process's check)."""
    from insight_core.markx import kept_pages
    repo = repo or ReaderRepository()
    st = kept_pages.stamp("unread", "counts", unread_inputs(cur))
    return repo.unread_window_days is None and not kept_pages.has(cur, "unread", "counts", kept_pages.NO_RUN, st)


def keep_unread_counts(cur: Any, repo: ReaderRepository | None = None) -> Dict[str, Any]:
    """Count the unread counts (ReaderRepository.unread_counts, the one path) and keep them for their inputs, unless
    kept already; in the caller's snapshot, so the stamp and the counts agree."""
    from insight_core.markx import kept_pages
    repo = repo or ReaderRepository()
    st = kept_pages.stamp("unread", "counts", unread_inputs(cur))
    if repo.unread_window_days is not None or kept_pages.has(cur, "unread", "counts", kept_pages.NO_RUN, st):
        return {"built": []}
    body = kept_pages.encode(repo.unread_counts(cur))
    kept_pages.put(cur, "unread", "counts", kept_pages.NO_RUN, st, body)
    return {"built": ["counts"], "bytes": len(body)}


class ReaderService:
    def __init__(self, db_url: str, *, repo: ReaderRepository | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.db_url = db_url
        self.repo = repo or ReaderRepository()
        self.search_repo = SearchRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _track_scope(cur: Any, scope: FeedScope, all_sources: bool) -> FeedScope:
        """A topic track's folder scope restricted to its items (markx/track_feed), unless `all_sources`; any other
        scope as it came."""
        if all_sources or scope.kind != "folder":
            return scope
        from insight_core.markx import track_feed
        return track_feed.restrict(cur, scope)

    def list_posts(self, query: FeedQuery, *, all_sources: bool = False) -> Dict[str, Any]:
        """FeedPage {items, next_cursor}, or FeedGroupsPage {groups, next_cursor} for view=by_source.
        A topic track lists only its items unless `all_sources`."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            scope = self._track_scope(cur, query.scope, all_sources)
            if scope is not query.scope:
                query = dataclasses.replace(query, scope=scope)
            rows, next_cursor = self.repo.list_posts(cur, query, now=self.clock())
            if query.view != "by_source":   # one post on two channels of a voice shows once
                from insight_core.db.repo_voices import VoicesRepository
                rows = VoicesRepository.also_on(cur, rows, scope_kind=query.scope.kind, scope_id=query.scope.id,
                                                filter=query.filter)
        key = "groups" if query.view == "by_source" else "items"
        return {"success": True, key: rows, "next_cursor": next_cursor.encode() if next_cursor else None}

    def search(self, query: SearchQuery) -> Dict[str, Any]:
        """SearchPage {items (each with its snippet; a story's with its `story`), next_cursor, entities};
        under Classics {classics, next_cursor, entities}. While Mark X is on, a post also matches by its English
        layer and `entities` holds up to 3 entity cards on a first page not of one source; else []."""
        from insight_core.markx import search as mx_search
        markx = mx_search.enabled()
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            items, next_cursor = self.search_repo.search(cur, query, now=self.clock(), markx=markx)
            first = query.cursor is None and query.offset == 0
            one_source = query.scope is not None and query.scope.kind == "source"
            entities = mx_search.entity_cards(cur, query.q) if markx and first and not one_source else []
        key = "classics" if query.filter == "classics" else "items"
        return {"success": True, key: items, "next_cursor": next_cursor, "entities": entities}

    def fill_search_vectors(self) -> int:
        """Fill every missing or outdated search vector, FILL_BATCH posts a transaction so no write waits on a long
        one, until none is left. Returns how many were filled."""
        return db.fill_until_done(self.db_url, self.search_repo.fill_missing_vectors, self.search_repo.missing_vectors)

    def fill_markx_search(self) -> int:
        """Fill Mark X's English search layer for every post missing or outdated, FILL_BATCH posts a transaction."""
        from insight_core.markx import search as mx_search
        return db.fill_until_done(self.db_url, mx_search.fill_batch, mx_search.pending)

    def unread_counts(self) -> bytes:
        """GET /api/feed/unread-counts' bytes: kept while none of their inputs changed, else counted once and kept
        (every open tab polls this)."""
        from insight_core.markx import kept_pages
        with db.transaction(self.db_url) as cur:
            if self.repo.unread_window_days is not None:   # a window reads the clock: counted on every request
                return kept_pages.encode(self.repo.unread_counts(cur))
            return kept_pages.kept_or_build(cur, "unread", "counts", lambda: unread_inputs(cur),
                                            lambda: self.repo.unread_counts(cur))

    def set_read(self, post_ids: Sequence[str], read: bool, keep_later: bool = False) -> Dict[str, Any]:
        """Mark these posts read or unread. `ids` are the ones that changed.

        An explicit mark read finishes a post: it leaves Later and its reading position is cleared. `keep_later`
        is a read that is only an open, which finishes nothing.
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

    def mark_read_through(self, scope: FeedScope, through: FeedCursor, newest: FeedCursor, *,
                          all_sources: bool = False) -> Dict[str, Any]:
        """Mark read every unread post in `scope` from `newest` down to `through`. `ids` undo it. A topic track's
        are only its items unless `all_sources`."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                scope = self._track_scope(cur, scope, all_sources)
                ids = self.repo.mark_read_through(cur, scope, through, newest=newest, now=self.clock())
                self.repo.clear_positions(cur, ids)
            conn.commit()
        return _read_state_result(ids)
