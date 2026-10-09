"""Reader repository: the feed keyset query, read state, bounded mark-through, unread counts.

Read state lives in the `post_reader_state` projection (0020). `post_interactions` stays the
audit log; a list query cannot aggregate it per row cheaply.

Every feed is ordered by the sort key `(COALESCE(published_at, fetched_at), id)` descending,
which `posts_feed_order_idx` / `posts_source_feed_order_idx` serve directly (no Sort node).
"Unread" means no read_at within the unread window (INSIGHT_UNREAD_WINDOW_DAYS,
default 30), so an archive backfill never shows as tens of thousands of unread posts.
"""
from __future__ import annotations

import base64
import binascii
import html
import math
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from psycopg import Cursor

FeedFilter = Literal["all", "unread", "starred"]
FeedView = Literal["stream", "by_source"]
FEED_FILTERS: Tuple[str, ...] = ("all", "unread", "starred")
FEED_VIEWS: Tuple[str, ...] = ("stream", "by_source")
SCOPE_KINDS: Tuple[str, ...] = ("all", "folder", "source")

DEFAULT_UNREAD_WINDOW_DAYS = 30
EXCERPT_CHARS = 280
TITLE_FALLBACK_CHARS = 80
CHARS_PER_READING_MINUTE = 1100  # about 200 words a minute

SORT_KEY = "COALESCE(p.published_at, p.fetched_at)"
# "Unread" as an anti-join, not `rs.read_at IS NULL` on the LEFT JOIN: the planner
# estimates a null-extended LEFT JOIN column at ~0 rows, gives up on the LIMIT, and
# seq-scans + sorts posts. The anti-join keeps the posts_feed_order_idx Index Scan.
UNREAD_SQL = (
    "NOT EXISTS (SELECT 1 FROM post_reader_state r WHERE r.post_id = p.id AND r.read_at IS NOT NULL)"
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def unread_window_days_from_env() -> int:
    try:
        return max(1, int(os.getenv("INSIGHT_UNREAD_WINDOW_DAYS", str(DEFAULT_UNREAD_WINDOW_DAYS))))
    except ValueError:
        return DEFAULT_UNREAD_WINDOW_DAYS


def _require_uuid(value: str, what: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"invalid {what}: {value!r}") from None


@dataclass(frozen=True)
class FeedScope:
    """Which posts a feed shows. 'all' honours sources.in_main_digest; starred is a filter."""

    kind: Literal["all", "folder", "source"]
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in SCOPE_KINDS:
            raise ValueError(f"invalid feed scope kind: {self.kind!r}")
        if self.kind == "all":
            if self.id is not None:
                raise ValueError("scope 'all' takes no id")
        else:
            object.__setattr__(self, "id", _require_uuid(self.id or "", f"{self.kind} id"))

    @staticmethod
    def parse(value: str | None) -> "FeedScope":
        """`all`, `folder:<uuid>` or `source:<uuid>` (the API's `scope=` form)."""
        text = (value or "all").strip()
        if text == "all":
            return FeedScope("all")
        kind, sep, ident = text.partition(":")
        if not sep or kind not in ("folder", "source"):
            raise ValueError(f"invalid feed scope: {value!r}")
        return FeedScope(kind, ident)  # type: ignore[arg-type]

    def key(self) -> str:
        return "all" if self.kind == "all" else f"{self.kind}:{self.id}"


@dataclass(frozen=True)
class FeedCursor:
    """A keyset position: the sort key of the last item served (or of a group's newest post)."""

    sort_at: datetime
    post_id: str

    def encode(self) -> str:
        raw = f"{self.sort_at.isoformat()}|{self.post_id}".encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def decode(s: str) -> "FeedCursor":
        if not s:
            raise ValueError("empty cursor")
        try:
            raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8")
            stamp, sep, post_id = raw.partition("|")
            if not sep:
                raise ValueError("no separator")
            sort_at = datetime.fromisoformat(stamp)
        except (binascii.Error, UnicodeDecodeError, ValueError):
            raise ValueError(f"malformed feed cursor: {s!r}") from None
        if sort_at.tzinfo is None:
            raise ValueError(f"malformed feed cursor: {s!r}")
        return FeedCursor(sort_at, _require_uuid(post_id, "cursor id"))


def _excerpt(content: str | None) -> str:
    text = html.unescape(_TAG_RE.sub(" ", content or ""))
    return _WS_RE.sub(" ", text).strip()[:EXCERPT_CHARS]


# Item columns, in the order _item() reads them. `rs` is the LEFT JOINed projection.
_ITEM_COLUMNS = f"""
    p.id, p.title, left(p.content, 4000), p.url, p.source_id,
    COALESCE(s.settings->>'display_name', s.handle_or_url), s.platform,
    {SORT_KEY}, p.published_at, rs.read_at, rs.starred_at,
    length(p.content), p.metadata->>'duration_seconds', p.media_urls->>0
"""


def _item(row: Sequence[Any]) -> Dict[str, Any]:
    excerpt = _excerpt(row[2])
    title = (row[1] or "").strip() or excerpt[:TITLE_FALLBACK_CHARS]
    platform = row[6]
    duration = row[12]
    try:
        duration_seconds = int(float(duration)) if duration not in (None, "") else None
    except ValueError:
        duration_seconds = None
    content_length = row[11] or 0
    is_video = platform == "youtube"
    return {
        "id": str(row[0]),
        "title": title,
        "excerpt": excerpt,
        "url": row[3],
        "source_id": str(row[4]),
        "source_display_name": row[5],
        "platform": platform,
        "sort_at": row[7],
        "published_at": row[8],
        "read_at": row[9],
        "starred_at": row[10],
        "reading_minutes": None if is_video or not content_length else math.ceil(content_length / CHARS_PER_READING_MINUTE),
        "duration_seconds": duration_seconds if is_video else None,
        "media_thumb": row[13],
    }


class ReaderRepository:
    """SQL for the reader. Every method takes the caller's cursor; the caller owns the commit."""

    def __init__(self, unread_window_days: int | None = None):
        self.unread_window_days = unread_window_days or unread_window_days_from_env()

    # ---- predicates ---------------------------------------------------------------

    @staticmethod
    def _scope_sql(scope: FeedScope) -> Tuple[str, List[Any]]:
        if scope.kind == "all":
            return "s.in_main_digest", []
        if scope.kind == "folder":
            return "p.source_id IN (SELECT sf.source_id FROM source_folders sf WHERE sf.folder_id = %s)", [scope.id]
        return "p.source_id = %s", [scope.id]

    def _filter_sql(self, filter: str) -> Tuple[str, List[Any]]:
        if filter == "unread":
            return (f"{UNREAD_SQL} AND {SORT_KEY} >= now() - make_interval(days => %s)",
                    [self.unread_window_days])
        if filter == "starred":
            return "rs.starred_at IS NOT NULL", []
        if filter == "all":
            return "TRUE", []
        raise ValueError(f"invalid feed filter: {filter!r}")

    # ---- feed ---------------------------------------------------------------------

    def feed(self, cur: Cursor, scope: FeedScope, *, filter: FeedFilter, cursor: FeedCursor | None,
             limit: int = 30, since: datetime | None = None) -> Tuple[List[Dict[str, Any]], FeedCursor | None]:
        scope_sql, params = self._scope_sql(scope)
        filter_sql, filter_params = self._filter_sql(filter)
        where = [scope_sql, filter_sql]
        params += filter_params
        if cursor is not None:
            where.append(f"({SORT_KEY}, p.id) < (%s, %s::uuid)")
            params += [cursor.sort_at, cursor.post_id]
        if since is not None:
            where.append(f"{SORT_KEY} >= %s")
            params.append(since)
        cur.execute(
            f"""
            SELECT {_ITEM_COLUMNS}
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN post_reader_state rs ON rs.post_id = p.id
            WHERE {' AND '.join(where)}
            ORDER BY {SORT_KEY} DESC, p.id DESC
            LIMIT %s
            """,
            [*params, limit + 1],
        )
        rows = cur.fetchall()
        items = [_item(r) for r in rows[:limit]]
        next_cursor = FeedCursor(items[-1]["sort_at"], items[-1]["id"]) if len(rows) > limit else None
        return items, next_cursor

    def feed_by_source(self, cur: Cursor, scope: FeedScope, *, filter: FeedFilter, per_source: int = 3,
                       group_cursor: FeedCursor | None = None, groups: int = 20,
                       since: datetime | None = None
                       ) -> Tuple[List[Dict[str, Any]], FeedCursor | None]:
        """One group per source, newest group first; keyset on (newest_sort_at, source_id).

        `count` honours the filter and the window: the unread window bounds every filter except
        `starred` (an explicit star never ages out), so grouping stays cheap on a big archive.
        `since` (the `days=` window) bounds both the counts and the items. Two queries per
        page whatever its size: the groups, then every group's newest items in one LATERAL.
        """
        scope_sql, scope_params = self._scope_sql(scope)
        filter_sql, filter_params = self._filter_sql(filter)
        window = ["TRUE"]
        window_params: List[Any] = []
        if filter == "all":
            window.append(f"{SORT_KEY} >= now() - make_interval(days => %s)")
            window_params.append(self.unread_window_days)
        if since is not None:
            window.append(f"{SORT_KEY} >= %s")
            window_params.append(since)
        window_sql = " AND ".join(window)
        group_where, group_params = "TRUE", []
        if group_cursor is not None:
            group_where = "(g.newest_sort_at, g.source_id) < (%s, %s::uuid)"
            group_params = [group_cursor.sort_at, group_cursor.post_id]
        cur.execute(
            f"""
            WITH g AS (
                SELECT p.source_id, MAX({SORT_KEY}) AS newest_sort_at, COUNT(*) AS n
                FROM posts p
                JOIN sources s ON s.id = p.source_id
                LEFT JOIN post_reader_state rs ON rs.post_id = p.id
                WHERE {scope_sql} AND {filter_sql} AND {window_sql}
                GROUP BY p.source_id
            )
            SELECT g.source_id, g.newest_sort_at, g.n,
                   COALESCE(s.settings->>'display_name', s.handle_or_url), s.platform
            FROM g JOIN sources s ON s.id = g.source_id
            WHERE {group_where}
            ORDER BY g.newest_sort_at DESC, g.source_id DESC
            LIMIT %s
            """,
            [*scope_params, *filter_params, *window_params, *group_params, groups + 1],
        )
        group_rows = cur.fetchall()
        page = group_rows[:groups]
        items_by_source: Dict[str, List[Dict[str, Any]]] = {str(row[0]): [] for row in page}
        if page:
            cur.execute(
                f"""
                SELECT x.*
                FROM unnest(%s::uuid[]) AS g(source_id)
                CROSS JOIN LATERAL (
                    SELECT {_ITEM_COLUMNS}
                    FROM posts p
                    JOIN sources s ON s.id = p.source_id
                    LEFT JOIN post_reader_state rs ON rs.post_id = p.id
                    WHERE p.source_id = g.source_id AND {filter_sql} AND {window_sql}
                    ORDER BY {SORT_KEY} DESC, p.id DESC
                    LIMIT %s
                ) x
                """,
                [list(items_by_source), *filter_params, *window_params, per_source],
            )
            for row in cur.fetchall():
                item = _item(row)
                items_by_source[item["source_id"]].append(item)
        out: List[Dict[str, Any]] = [
            {
                "source_id": str(source_id),
                "source_display_name": display_name,
                "platform": platform,
                "newest_sort_at": newest,
                "count": int(n),
                # LATERAL keeps each source's rows in its ORDER BY, but say so rather than rely on it.
                "items": sorted(items_by_source[str(source_id)], key=lambda i: (i["sort_at"], i["id"]),
                                reverse=True),
            }
            for source_id, newest, n, display_name, platform in page
        ]
        next_cursor = None
        if len(group_rows) > groups:
            last = out[-1]
            next_cursor = FeedCursor(last["newest_sort_at"], last["source_id"])
        return out, next_cursor

    # ---- read state ---------------------------------------------------------------

    def set_read(self, cur: Cursor, post_ids: Sequence[str], read: bool) -> int:
        """Mark posts read (keeping the first read time) or unread. Returns rows changed."""
        ids = [_require_uuid(pid, "post id") for pid in post_ids]
        if not ids:
            return 0
        if read:
            cur.execute(
                """
                INSERT INTO post_reader_state (post_id, read_at)
                SELECT p.id, now() FROM posts p WHERE p.id = ANY(%s::uuid[])
                ON CONFLICT (post_id) DO UPDATE
                    SET read_at = now(), updated_at = now()
                    WHERE post_reader_state.read_at IS NULL
                """,
                (ids,),
            )
        else:
            cur.execute(
                """
                UPDATE post_reader_state SET read_at = NULL, updated_at = now()
                WHERE post_id = ANY(%s::uuid[]) AND read_at IS NOT NULL
                """,
                (ids,),
            )
        return cur.rowcount

    def set_starred(self, cur: Cursor, post_id: str, starred: bool) -> None:
        post_id = _require_uuid(post_id, "post id")
        if starred:
            cur.execute(
                """
                INSERT INTO post_reader_state (post_id, starred_at)
                SELECT p.id, now() FROM posts p WHERE p.id = %s
                ON CONFLICT (post_id) DO UPDATE
                    SET starred_at = COALESCE(post_reader_state.starred_at, now()), updated_at = now()
                """,
                (post_id,),
            )
        else:
            cur.execute(
                "UPDATE post_reader_state SET starred_at = NULL, updated_at = now() WHERE post_id = %s",
                (post_id,),
            )

    def mark_read_through(self, cur: Cursor, scope: FeedScope, through: FeedCursor, *, newest: FeedCursor,
                          now: datetime) -> List[str]:
        """Mark unread posts in `scope` from `newest` down to `through` (inclusive) read.

        Bounded three ways: posts newer than `newest` (arrived after the page rendered) stay
        unread, only the unread window is touched, and only rows with read_at IS NULL are
        written - scope 'all' can never write one row per archive post. Returns the ids
        marked, so the UI can undo with set_read(ids, False).
        """
        scope_sql, params = self._scope_sql(scope)
        cur.execute(
            f"""
            INSERT INTO post_reader_state (post_id, read_at)
            SELECT p.id, %s
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            WHERE {scope_sql}
              AND {UNREAD_SQL}
              AND ({SORT_KEY}, p.id) <= (%s, %s::uuid)
              AND ({SORT_KEY}, p.id) >= (%s, %s::uuid)
              AND {SORT_KEY} >= %s
            ON CONFLICT (post_id) DO UPDATE
                SET read_at = EXCLUDED.read_at, updated_at = now()
                WHERE post_reader_state.read_at IS NULL
            RETURNING post_id
            """,
            [now, *params, newest.sort_at, newest.post_id, through.sort_at, through.post_id,
             now - timedelta(days=self.unread_window_days)],
        )
        return [str(r[0]) for r in cur.fetchall()]

    def unread_counts(self, cur: Cursor) -> Dict[str, Any]:
        """{total (main digest), by_source: {id: n}, by_folder: {id: n}} over the unread window."""
        cur.execute(
            f"""
            SELECT p.source_id, bool_or(s.in_main_digest), COUNT(*)
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            WHERE {UNREAD_SQL} AND {SORT_KEY} >= now() - make_interval(days => %s)
            GROUP BY p.source_id
            """,
            (self.unread_window_days,),
        )
        by_source: Dict[str, int] = {}
        total = 0
        for source_id, in_main_digest, n in cur.fetchall():
            by_source[str(source_id)] = int(n)
            if in_main_digest:
                total += int(n)
        by_folder: Dict[str, int] = {}
        if by_source:
            cur.execute(
                "SELECT folder_id, source_id FROM source_folders WHERE source_id = ANY(%s::uuid[])",
                (list(by_source),),
            )
            for folder_id, source_id in cur.fetchall():
                key = str(folder_id)
                by_folder[key] = by_folder.get(key, 0) + by_source[str(source_id)]
        return {"total": total, "by_source": by_source, "by_folder": by_folder}
