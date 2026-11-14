"""Reader: the post listing, search (issue 0040), read state, Later (issue 0022) and unread
counts (Mark IX, B7).

Owns the connection and transaction lifecycle around ReaderRepository and turns its
results into the API shapes (FeedPage, FeedGroupsPage, ReadStateResult, UnreadCounts).
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


# 0206: what the unread counts read, as kept inputs (markx/kept_pages.changes): the posts, the read state (read, Later,
# starred), the stories' members, the folded parts, the folders and a source added, removed or put in or out of the
# main digest
UNREAD_INPUTS = ("posts", "reads", "stories", "parts", "folders")


def unread_inputs(cur: Any) -> List[Any]:
    from insight_core.markx import kept_pages
    return kept_pages.changes(cur, UNREAD_INPUTS)


def unread_missing(cur: Any, repo: ReaderRepository | None = None) -> bool:
    """0206, the jobs process's look (the view "unread"): whether the counts are not kept for their inputs now."""
    from insight_core.markx import kept_pages
    repo = repo or ReaderRepository()
    st = kept_pages.stamp("unread", "counts", unread_inputs(cur))
    return repo.unread_window_days is None and not kept_pages.has(cur, "unread", "counts", kept_pages.NO_RUN, st)


def keep_unread_counts(cur: Any, repo: ReaderRepository | None = None) -> Dict[str, Any]:
    """0206, the jobs process: the unread counts counted (ReaderRepository.unread_counts, the one path) and kept for
    their inputs, unless they are; in the caller's snapshot (the stamp and the counts read one)."""
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
        """A topic track's folder scope restricted to its items while Mark X is on (v10.12.1, markx/track_feed), unless
        `all_sources`; every other scope as it came (Mark X is not imported for them)."""
        if all_sources or scope.kind != "folder":
            return scope
        from insight_core.markx import track_feed
        return track_feed.restrict(cur, scope)

    def list_posts(self, query: FeedQuery, *, all_sources: bool = False) -> Dict[str, Any]:
        """FeedPage {items, next_cursor}, or FeedGroupsPage {groups, next_cursor} for view=by_source.
        A topic track (Mark X on) lists only its items unless `all_sources` (v10.12.1)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            scope = self._track_scope(cur, query.scope, all_sources)
            if scope is not query.scope:
                query = dataclasses.replace(query, scope=scope)
            rows, next_cursor = self.repo.list_posts(cur, query, now=self.clock())
            if query.view != "by_source":   # one post on two channels of a voice shows once (issue 0132 A)
                from insight_core.db.repo_voices import VoicesRepository
                rows = VoicesRepository.also_on(cur, rows, scope_kind=query.scope.kind, scope_id=query.scope.id,
                                                filter=query.filter)
        key = "groups" if query.view == "by_source" else "items"
        return {"success": True, key: rows, "next_cursor": next_cursor.encode() if next_cursor else None}

    def search(self, query: SearchQuery) -> Dict[str, Any]:
        """SearchPage {items (each with its snippet; a story's with its `story`), next_cursor, entities};
        under Classics {classics, next_cursor, entities}, as GET /api/classics shapes them.

        While Mark X is on (issue 0139) a post also matches by its English layer (mx_post_search), and
        `entities` holds up to 3 entity cards the words name, on a first page not of one source; else []."""
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
        """Give every post whose search vector is missing (stored before 0033) or made by an
        older rule (0042's search_version) its vector, FILL_BATCH posts a transaction, so no
        write waits on a long one, until none is left (issue 0069). Returns how many were filled."""
        return db.fill_until_done(self.db_url, self.search_repo.fill_missing_vectors, self.search_repo.missing_vectors)

    def fill_markx_search(self) -> int:
        """Mark X's English layer (issue 0139): every post with a read or entities answer and no row, a row of an
        older rule or older than its answers gets it, FILL_BATCH posts a transaction, until none is left."""
        from insight_core.markx import search as mx_search
        return db.fill_until_done(self.db_url, mx_search.fill_batch, mx_search.pending)

    def unread_counts(self) -> bytes:
        """GET /api/feed/unread-counts' bytes (issue 0206): kept while nothing it reads was written since (the kept
        inputs' counts and the window), else counted as before (ReaderRepository.unread_counts, the one path) and
        kept. Polled every 60 s by every open tab: unchanged, one indexed read and one row (0.4-1.4 s on the server
        before); after a read or a fetch, counted once, by whichever request comes first."""
        from insight_core.markx import kept_pages
        with db.transaction(self.db_url) as cur:
            if self.repo.unread_window_days is not None:   # a window reads the clock: counted on every request
                return kept_pages.encode(self.repo.unread_counts(cur))
            return kept_pages.kept_or_build(cur, "unread", "counts", lambda: unread_inputs(cur),
                                            lambda: self.repo.unread_counts(cur))

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

    def mark_read_through(self, scope: FeedScope, through: FeedCursor, newest: FeedCursor, *,
                          all_sources: bool = False) -> Dict[str, Any]:
        """Mark read every unread post in `scope` from `newest` down to `through`. `ids` undo it. A topic track's
        are the posts its list shows (v10.12.1): only its items unless `all_sources`."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                scope = self._track_scope(cur, scope, all_sources)
                ids = self.repo.mark_read_through(cur, scope, through, newest=newest, now=self.clock())
                self.repo.clear_positions(cur, ids)
            conn.commit()
        return _read_state_result(ids)
