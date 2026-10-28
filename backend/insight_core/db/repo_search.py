"""Search across every post (issue 0040): `posts.search_vector` (0033) over its GIN index.

A query is read by `websearch_to_tsquery('russian', q)`: words match their forms in English
and Russian, "quoted phrases" match in order, `-word` excludes and `or` is either. It matches
the title (weighted most), the source's name and the full text. Read or unread doesn't matter.

Narrowing: a scope (none is every post; `all` is the Main feed, as in the reader), Later or
Kept, and the last N days. Newest first by default, keyset-paged on the feed's sort key like
the reader; `best` orders the newest 5,000 matches by rank and pages by offset (rank is not a
stable keyset).
Each item is the reader's row plus `snippet`, the matching line as parts, the words marked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

from psycopg import Cursor

from insight_core.db.repo_reader import (
    _ITEM_COLUMNS, MAX_FEED_LIMIT, SORT_KEY, FeedCursor, FeedScope, ReaderRepository, _item,
)
from insight_core.utils.content_fingerprints import WHITESPACE_RE, decode_entities

SearchFilter = Literal["all", "later", "starred"]   # starred is Keep ("Kept")
SearchOrder = Literal["newest", "best"]
SEARCH_FILTERS: Tuple[str, ...] = ("all", "later", "starred")
SEARCH_ORDERS: Tuple[str, ...] = ("newest", "best")
MAX_QUERY_CHARS = 500

# The matching line: one fragment of the text around the best cover of the query, its words
# between two control characters (stripped from the text first, so only ts_headline's remain).
MARK_START, MARK_END = "\x01", "\x02"
HEADLINE_OPTIONS = f"StartSel={MARK_START}, StopSel={MARK_END}, MaxWords=28, MinWords=12, MaxFragments=1"
# ts_headline reads the text it is given in full; past this the line is not looked for.
HEADLINE_CHARS = 20000
TSQUERY = "websearch_to_tsquery('russian', %s)"
# Posts stored before search are filled this many a transaction (issue 0040, 0033).
FILL_BATCH = 500
# Best match ranks the newest this many matches (a word in most posts ranks no better).
RANKED_MATCHES = 5000
# The words the line marks: any one of them, so the line shows the text's words even when the
# others matched in the title or the source's name; never an excluded word (querytree drops
# them). Its three %s are the same query.
MARK_TSQUERY = (f"(CASE WHEN querytree({TSQUERY}) = 'T' THEN {TSQUERY}"
                f" ELSE replace(querytree({TSQUERY}), ' & ', ' | ')::tsquery END)")


@dataclass(frozen=True)
class SearchQuery:
    """One page of search results. A bad value is a ValueError (the API's 400).

    `scope` None searches every post. `cursor` is a FeedCursor for newest first and an
    offset for best match."""

    q: str
    scope: Optional[FeedScope] = None
    filter: SearchFilter = "all"
    days: Optional[int] = None
    order: SearchOrder = "newest"
    cursor: Optional[FeedCursor] = None
    offset: int = 0
    limit: int = 30

    def __post_init__(self) -> None:
        if not self.q.strip():
            raise ValueError("q must not be empty")
        if len(self.q) > MAX_QUERY_CHARS:
            raise ValueError(f"q must be at most {MAX_QUERY_CHARS} characters")
        if self.filter not in SEARCH_FILTERS:
            raise ValueError(f"filter must be one of {', '.join(SEARCH_FILTERS)}")
        if self.order not in SEARCH_ORDERS:
            raise ValueError(f"order must be one of {', '.join(SEARCH_ORDERS)}")
        if not 1 <= int(self.limit) <= MAX_FEED_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_FEED_LIMIT}")
        if self.days is not None and int(self.days) < 1:
            raise ValueError("days must be at least 1")
        if self.offset < 0:
            raise ValueError("offset must not be negative")

    @staticmethod
    def parse(*, q: str, scope: str | None = None, filter: str = "all", days: int | None = None,
              order: str = "newest", cursor: str | None = None, limit: int = 30) -> "SearchQuery":
        """The API's query string: no `scope` searches everything; `cursor` is the last page's
        next_cursor (a feed cursor for newest, an offset for best)."""
        feed_cursor, offset = None, 0
        if cursor and order == "best":
            if not cursor.isdigit():
                raise ValueError(f"malformed search cursor: {cursor!r}")
            offset = int(cursor)
        elif cursor:
            feed_cursor = FeedCursor.decode(cursor)
        return SearchQuery(
            q=q, scope=FeedScope.parse(scope) if scope else None, filter=filter,  # type: ignore[arg-type]
            days=int(days) if days is not None else None, order=order,  # type: ignore[arg-type]
            cursor=feed_cursor, offset=offset, limit=int(limit),
        )


def snippet_parts(headline: str | None) -> Optional[List[Dict[str, Any]]]:
    """ts_headline's line as [{text, mark}] parts; None when no word in it is marked (the
    match was in the title or the source's name)."""
    if not headline or MARK_START not in headline:
        return None
    parts: List[Dict[str, Any]] = []
    for i, chunk in enumerate(WHITESPACE_RE.sub(" ", headline).strip().split(MARK_START)):
        marked, _, rest = chunk.partition(MARK_END) if i else ("", "", chunk)
        for text, mark in ((decode_entities(marked), True), (decode_entities(rest), False)):
            if not text:
                continue
            if parts and parts[-1]["mark"] == mark:
                parts[-1]["text"] += text
            else:
                parts.append({"text": text, "mark": mark})
    return parts


class SearchRepository:
    """SQL for search. Takes the caller's cursor; the caller owns the commit."""

    def __init__(self, reader: ReaderRepository | None = None):
        self.reader = reader or ReaderRepository(unread_window_days=None)

    def search(self, cur: Cursor, query: SearchQuery, *, now: datetime
               ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """One page of results and the next page's cursor (encoded), or None at the end."""
        cur.execute("SELECT numnode(websearch_to_tsquery('russian', %s))", (query.q,))
        if not cur.fetchone()[0]:
            return [], None   # only stop words or punctuation: nothing can match
        # The query is written out, not taken from a CTE, so the planner sees its words: a
        # common word walks the feed's order index, a rare one the GIN index.
        where, params = [f"p.search_vector @@ {TSQUERY}"], [query.q]
        if query.scope is not None:
            scope_sql, scope_params = self.reader._scope_sql(query.scope, query.filter)
            where.append(scope_sql)
            params += scope_params
        filter_sql, filter_params = self.reader._filter_sql(query.filter)
        where.append(filter_sql)
        params += filter_params
        if query.days:
            where.append(f"{SORT_KEY} >= %s")
            params.append(now - timedelta(days=query.days))
        limit = query.limit
        if query.order == "best":
            # Ranked among the newest RANKED_MATCHES matches: ranking reads every vector it ranks.
            # Normalisation 1 divides by 1 + log(length): a long text does not win by length.
            matches, rank, rank_params = RANKED_MATCHES, f"ts_rank(search_vector, {TSQUERY}, 1)", [query.q]
            page, page_params = "OFFSET %s", [query.offset]
        else:
            matches, rank, rank_params, page, page_params = limit + 1, "0", [], "", []
            if query.cursor is not None:
                where.append(f"({SORT_KEY}, p.id) < (%s, %s::uuid)")
                params += [query.cursor.sort_at, query.cursor.post_id]
        # A word in a third of the posts looks cheap to find by reading the whole table, but
        # every row read then unpacks its vector (400 ms on 50k posts); the GIN index's bitmap
        # needs none of them. For this transaction only.
        cur.execute("SET LOCAL enable_seqscan = off")
        # The matches newest first (the feed's order index, or the GIN index for a rare word),
        # then the page, then the line for its rows only: ts_headline re-reads each text.
        cur.execute(
            f"""
            WITH matches AS (
                SELECT p.id, {SORT_KEY} AS sort_at, p.search_vector
                FROM posts p
                JOIN sources s ON s.id = p.source_id
                LEFT JOIN post_reader_state rs ON rs.post_id = p.id
                WHERE {' AND '.join(where)}
                ORDER BY sort_at DESC, p.id DESC
                LIMIT %s
            ), hits AS (
                SELECT id, sort_at, {rank} AS rank FROM matches
                ORDER BY rank DESC, sort_at DESC, id DESC
                {page}
                LIMIT %s
            )
            SELECT {_ITEM_COLUMNS},
                   ts_headline('russian', translate(left(p.content, {HEADLINE_CHARS}), %s, ''), {MARK_TSQUERY}, %s)
            FROM hits
            JOIN posts p ON p.id = hits.id
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN post_reader_state rs ON rs.post_id = p.id
            ORDER BY hits.rank DESC, hits.sort_at DESC, hits.id DESC
            """,
            [*params, matches, *rank_params, *page_params, limit + 1, MARK_START + MARK_END,
             query.q, query.q, query.q, HEADLINE_OPTIONS],
            # Never a prepared statement: a generic plan cannot see the words, and walks the
            # feed's order index for a rare word (40 ms became 300 ms on 50k posts).
            prepare=False,
        )
        rows = cur.fetchall()
        items = []
        for row in rows[:limit]:
            item = _item(row[:-1])
            item["snippet"] = snippet_parts(row[-1])
            items.append(item)
        if len(rows) <= limit:
            return items, None
        if query.order == "best":
            return items, str(query.offset + limit)
        return items, FeedCursor(items[-1]["sort_at"], items[-1]["id"]).encode()

    def fill_missing_vectors(self, cur: Cursor, batch: int = FILL_BATCH) -> int:
        """Fill the search vector of up to `batch` posts stored before 0033; how many were."""
        cur.execute(
            """
            WITH batch AS (SELECT id FROM posts WHERE search_vector IS NULL LIMIT %s FOR UPDATE SKIP LOCKED)
            UPDATE posts p
               SET search_vector = post_search_vector(p.title, p.content, source_search_name(s.settings, s.handle_or_url))
              FROM batch, sources s
             WHERE p.id = batch.id AND s.id = p.source_id
            """,
            (batch,),
        )
        return cur.rowcount
