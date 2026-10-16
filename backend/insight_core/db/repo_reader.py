"""Reader repository: the one post listing, read state, bounded mark-through, unread counts.

Every post list the reader shows (the feed, a source, a track, one day) is `list_posts` with a
`FeedQuery`: scope, read-state filter, an optional time bound (the last N days or one day),
a keyset cursor and a view (a stream, or one group per source).

Read state lives in the `post_reader_state` projection (0020). `post_interactions` stays the
audit log; a list query cannot aggregate it per row cheaply.

Every feed is ordered by the sort key `(COALESCE(published_at, fetched_at), id)` descending,
which `posts_feed_order_idx` / `posts_source_feed_order_idx` serve directly (no Sort node).
"Unread" means no read_at, over every post the source ever gave us: an archived post from
2015 is as unread as this morning's. INSIGHT_UNREAD_WINDOW_DAYS=N narrows unread (and the
grouped "all" view) back to the last N days; unset or 0 means no window.
"""
from __future__ import annotations

import base64
import binascii
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from psycopg import Cursor

from insight_core.utils.content_fingerprints import strip_html
from insight_core.utils.env import env_int
from insight_core.utils.media import feed_thumb
from insight_core.utils.post_fields import display_title

FeedFilter = Literal["all", "unread", "starred"]
FeedView = Literal["stream", "by_source"]
FEED_FILTERS: Tuple[str, ...] = ("all", "unread", "starred")
FEED_VIEWS: Tuple[str, ...] = ("stream", "by_source")
SCOPE_KINDS: Tuple[str, ...] = ("all", "folder", "source")

MAX_FEED_LIMIT = 100
MAX_FEED_GROUPS = 50
DEFAULT_UNREAD_WINDOW_DAYS: Optional[int] = None   # no window: unread is all-time
EXCERPT_CHARS = 280
CHARS_PER_READING_MINUTE = 1100  # about 200 words a minute

SORT_KEY = "COALESCE(p.published_at, p.fetched_at)"
# "Unread" as an anti-join, not `rs.read_at IS NULL` on the LEFT JOIN: the planner
# estimates a null-extended LEFT JOIN column at ~0 rows, gives up on the LIMIT, and
# seq-scans + sorts posts. The anti-join keeps the posts_feed_order_idx Index Scan.
UNREAD_SQL = (
    "NOT EXISTS (SELECT 1 FROM post_reader_state r WHERE r.post_id = p.id AND r.read_at IS NOT NULL)"
)


def unread_window_days_from_env() -> Optional[int]:
    """INSIGHT_UNREAD_WINDOW_DAYS as a positive int, or None (unset, 0 or garbage: no window)."""
    days = env_int("INSIGHT_UNREAD_WINDOW_DAYS", 0)
    return days if days > 0 else DEFAULT_UNREAD_WINDOW_DAYS


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


@dataclass(frozen=True)
class FeedQuery:
    """One page of posts: which posts, and how they are paged.

    `days` keeps the last N days; `day` keeps one calendar day (UTC). `view="by_source"` pages
    groups (one per source, `per_source` newest items each), at most MAX_FEED_GROUPS a page.
    A bad value is a ValueError (the API's 400).
    """

    scope: FeedScope = field(default_factory=lambda: FeedScope("all"))
    filter: FeedFilter = "all"
    view: FeedView = "stream"
    cursor: Optional[FeedCursor] = None
    limit: int = 30
    days: Optional[int] = None
    day: Optional[date] = None
    per_source: int = 3

    def __post_init__(self) -> None:
        if self.filter not in FEED_FILTERS:
            raise ValueError(f"filter must be one of {', '.join(FEED_FILTERS)}")
        if self.view not in FEED_VIEWS:
            raise ValueError(f"view must be one of {', '.join(FEED_VIEWS)}")
        if not 1 <= int(self.limit) <= MAX_FEED_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_FEED_LIMIT}")
        if self.days is not None and int(self.days) < 1:
            raise ValueError("days must be at least 1")
        if self.days is not None and self.day is not None:
            raise ValueError("send days or date, not both")

    @staticmethod
    def parse(*, scope: str | None = None, filter: str = "all", view: str = "stream",
              cursor: str | None = None, limit: int = 30, days: int | None = None,
              date: str | None = None) -> "FeedQuery":
        """The API's query string: `scope=all|source:<uuid>|folder:<uuid>`, `date=YYYY-MM-DD`."""
        day = None
        if date:
            try:
                day = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError(f"date must be YYYY-MM-DD, not {date!r}") from None
        return FeedQuery(
            scope=FeedScope.parse(scope), filter=filter, view=view,  # type: ignore[arg-type]
            cursor=FeedCursor.decode(cursor) if cursor else None,
            limit=int(limit), days=int(days) if days is not None else None, day=day,
        )

    def bounds(self, now: datetime) -> Tuple[Optional[datetime], Optional[datetime]]:
        """(since, until) on the sort key: since inclusive, until exclusive."""
        if self.day is not None:
            start = datetime.combine(self.day, time.min, tzinfo=timezone.utc)
            return start, start + timedelta(days=1)
        if self.days:
            return now - timedelta(days=self.days), None
        return None, None


def _excerpt(content: str | None) -> str:
    return strip_html(content, entities="decode")[:EXCERPT_CHARS]


# Item columns, in the order _item() reads them. `rs` is the LEFT JOINed projection.
_ITEM_COLUMNS = f"""
    p.id, p.title, left(p.content, 4000), p.url, p.source_id,
    COALESCE(s.settings->>'display_name', s.handle_or_url), s.platform,
    {SORT_KEY}, p.published_at, rs.read_at, rs.starred_at,
    length(p.content), p.metadata->>'duration_seconds', jsonb_path_query_array(p.media_urls, '$[0 to 7]')
"""


def _item(row: Sequence[Any]) -> Dict[str, Any]:
    excerpt = _excerpt(row[2])
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
        "title": display_title(row[1], row[2]),
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
        "media_thumb": feed_thumb(row[13], row[3]),
    }


class ReaderRepository:
    """SQL for the reader. Every method takes the caller's cursor; the caller owns the commit."""

    _FROM_ENV = object()

    def __init__(self, unread_window_days: Any = _FROM_ENV):
        """unread_window_days: days, None for no window; omitted reads INSIGHT_UNREAD_WINDOW_DAYS."""
        if unread_window_days is self._FROM_ENV:
            unread_window_days = unread_window_days_from_env()
        self.unread_window_days: Optional[int] = unread_window_days or None

    def _window_sql(self) -> Tuple[str, List[Any]]:
        """The unread window as a predicate on the sort key, or TRUE when there is none."""
        if self.unread_window_days is None:
            return "TRUE", []
        return f"{SORT_KEY} >= now() - make_interval(days => %s)", [self.unread_window_days]

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
            window_sql, window_params = self._window_sql()
            return f"{UNREAD_SQL} AND {window_sql}", window_params
        if filter == "starred":
            return "rs.starred_at IS NOT NULL", []
        if filter == "all":
            return "TRUE", []
        raise ValueError(f"invalid feed filter: {filter!r}")

    # ---- the post listing ----------------------------------------------------------

    @staticmethod
    def _bounds_sql(since: datetime | None, until: datetime | None) -> Tuple[str, List[Any]]:
        where, params = ["TRUE"], []
        if since is not None:
            where.append(f"{SORT_KEY} >= %s")
            params.append(since)
        if until is not None:
            where.append(f"{SORT_KEY} < %s")
            params.append(until)
        return " AND ".join(where), params

    def list_posts(self, cur: Cursor, query: FeedQuery, *, now: datetime
                   ) -> Tuple[List[Dict[str, Any]], FeedCursor | None]:
        """One page of `query`: items (stream) or groups (by_source), and the next page's cursor."""
        since, until = query.bounds(now)
        if query.view == "by_source":
            return self._by_source(cur, query, since=since, until=until)
        return self._stream(cur, query, since=since, until=until)

    def _stream(self, cur: Cursor, query: FeedQuery, *, since: datetime | None, until: datetime | None
                ) -> Tuple[List[Dict[str, Any]], FeedCursor | None]:
        scope_sql, params = self._scope_sql(query.scope)
        filter_sql, filter_params = self._filter_sql(query.filter)
        bounds_sql, bounds_params = self._bounds_sql(since, until)
        where = [scope_sql, filter_sql, bounds_sql]
        params += filter_params + bounds_params
        if query.cursor is not None:
            where.append(f"({SORT_KEY}, p.id) < (%s, %s::uuid)")
            params += [query.cursor.sort_at, query.cursor.post_id]
        limit = query.limit
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

    def _by_source(self, cur: Cursor, query: FeedQuery, *, since: datetime | None, until: datetime | None
                   ) -> Tuple[List[Dict[str, Any]], FeedCursor | None]:
        """One group per source, newest group first; keyset on (newest_sort_at, source_id).

        `count` honours the filter and, when one is set, the unread window: it then bounds every
        filter except `starred` (an explicit star never ages out).
        The time bound (`days` or `day`) bounds both the counts and the items. Two queries per
        page whatever its size: the groups, then every group's newest items in one LATERAL.
        """
        scope, filter, group_cursor = query.scope, query.filter, query.cursor
        groups, per_source = min(query.limit, MAX_FEED_GROUPS), query.per_source
        scope_sql, scope_params = self._scope_sql(scope)
        filter_sql, filter_params = self._filter_sql(filter)
        window = ["TRUE"]
        window_params: List[Any] = []
        if filter == "all":
            all_window_sql, all_window_params = self._window_sql()
            window.append(all_window_sql)
            window_params += all_window_params
        bounds_sql, bounds_params = self._bounds_sql(since, until)
        window.append(bounds_sql)
        window_params += bounds_params
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

    def set_read(self, cur: Cursor, post_ids: Sequence[str], read: bool) -> List[str]:
        """Mark posts read (keeping the first read time) or unread. Returns the ids changed."""
        ids = [_require_uuid(pid, "post id") for pid in post_ids]
        if not ids:
            return []
        if read:
            cur.execute(
                """
                INSERT INTO post_reader_state (post_id, read_at)
                SELECT p.id, now() FROM posts p WHERE p.id = ANY(%s::uuid[])
                ON CONFLICT (post_id) DO UPDATE
                    SET read_at = now(), updated_at = now()
                    WHERE post_reader_state.read_at IS NULL
                RETURNING post_id
                """,
                (ids,),
            )
        else:
            cur.execute(
                """
                UPDATE post_reader_state SET read_at = NULL, updated_at = now()
                WHERE post_id = ANY(%s::uuid[]) AND read_at IS NOT NULL
                RETURNING post_id
                """,
                (ids,),
            )
        return [str(r[0]) for r in cur.fetchall()]

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

        Bounded by the page: posts newer than `newest` (arrived after the page rendered) stay
        unread, nothing older than `through` is touched (nor, with a window set, anything
        outside it), and only rows with read_at IS NULL are written. Returns the ids
        marked, so the UI can undo with set_read(ids, False).
        """
        scope_sql, params = self._scope_sql(scope)
        window_sql, window_params = "TRUE", []
        if self.unread_window_days is not None:
            window_sql, window_params = f"{SORT_KEY} >= %s", [now - timedelta(days=self.unread_window_days)]
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
              AND {window_sql}
            ON CONFLICT (post_id) DO UPDATE
                SET read_at = EXCLUDED.read_at, updated_at = now()
                WHERE post_reader_state.read_at IS NULL
            RETURNING post_id
            """,
            [now, *params, newest.sort_at, newest.post_id, through.sort_at, through.post_id, *window_params],
        )
        return [str(r[0]) for r in cur.fetchall()]

    def unread_counts(self, cur: Cursor) -> Dict[str, Any]:
        """{total (main digest), by_source: {id: n}, by_folder: {id: n}} of unread posts (all-time unless a window is set)."""
        window_sql, window_params = self._window_sql()
        cur.execute(
            f"""
            SELECT p.source_id, bool_or(s.in_main_digest), COUNT(*)
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            WHERE {UNREAD_SQL} AND {window_sql}
            GROUP BY p.source_id
            """,
            window_params,
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
