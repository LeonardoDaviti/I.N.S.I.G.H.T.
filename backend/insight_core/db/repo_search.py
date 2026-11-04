"""Search across every post (issue 0040): `posts.search_vector` (0033) over its GIN index.

A query is read by `search_query(q)` (0042): `websearch_to_tsquery('russian', q)`, so words match
their forms in English and Russian, "quoted phrases" match in order, `-word` excludes and `or` is
either; and a version word of it ("K3.1", "GPT-6.1") is also read as its parts, as the index
holds them (issue 0056). It matches the title (weighted most), the source's name and the full
text. Read or unread doesn't matter.

Narrowing: a scope (none is every post; `all` is the Main feed, as in the reader), one of Later,
Kept, News and Classics, and the last N days. Newest first by default, keyset-paged on the feed's
sort key like the reader; `best` orders the newest 5,000 matches by rank and pages by offset (rank
is not a stable keyset).
Each item is the reader's row plus `snippet`, the matching line as parts, the words marked.

Stories (issue 0056): unless the search is of one source, Later or Kept, a story shows once, at
its best-matching post (the highest rank, then its report before a share, then the first
posted), with its `story` as the Main feed's lead carries it ("covered by"). News searches the
News stories (any date): a story whose posts match, with a post in the scope, once, at its
best-matching post, with `story` (its News posts) and `news`. Classics searches the classics'
titles and addresses and answers classics, as GET /api/classics does, paged by offset.

The stored vectors carry the rule that made them (`posts.search_version`, 0042): the background
fill refills every post whose vector is missing or older than `search_vector_version()`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional, Tuple

from psycopg import Cursor

from insight_core.db.repo_news import NewsRepository, _scope_sql as news_scope_sql
from insight_core.db.repo_reader import (
    _ITEM_COLUMNS, _ORDER_RANK, MAX_FEED_LIMIT, NOT_ALBUM_PIECE, SORT_KEY, FeedCursor, FeedScope, ReaderRepository,
    _item, _on, story_voices, voiced,
)
from insight_core.utils.content_fingerprints import WHITESPACE_RE, decode_entities
from insight_core.utils.classic_rules import cited_again
from insight_core.utils.news_rules import NEWS_RECENT, lead
from insight_core.utils.post_fields import post_title, quote_only, title_columns

SearchFilter = Literal["all", "later", "starred", "news", "classics"]   # starred is Keep ("Kept")
SearchOrder = Literal["newest", "best"]
SEARCH_FILTERS: Tuple[str, ...] = ("all", "later", "starred", "news", "classics")
SEARCH_ORDERS: Tuple[str, ...] = ("newest", "best")
MAX_QUERY_CHARS = 500

# The matching line: one fragment of the text around the best cover of the query, its words
# between two control characters (stripped from the text first, so only ts_headline's remain).
MARK_START, MARK_END = "\x01", "\x02"
HEADLINE_OPTIONS = f"StartSel={MARK_START}, StopSel={MARK_END}, MaxWords=28, MinWords=12, MaxFragments=1"
# ts_headline reads the text it is given in full; past this the line is not looked for.
HEADLINE_CHARS = 20000
# The query, read as the index is (0042): words, phrases, -word, and version words by their parts.
TSQUERY = "search_query(%s)"
# Posts whose vector is missing or made by an older rule are filled this many a transaction (0033, 0042).
FILL_BATCH = 500
# Best match ranks the newest this many matches (a word in most posts ranks no better).
RANKED_MATCHES = 5000
# Rank, normalised by 1 + log(length): a long text does not win by length.
RANK = "ts_rank({v}, " + TSQUERY + ", 1)"
# The words the line marks: any one of them, so the line shows the text's words even when the
# others matched in the title or the source's name; never an excluded word (querytree drops
# them). Its three %s are the same query.
MARK_TSQUERY = (f"(CASE WHEN querytree({TSQUERY}) = 'T' THEN {TSQUERY}"
                f" ELSE replace(querytree({TSQUERY}), ' & ', ' | ')::tsquery END)")
# A classic's words: its title (the stored post's, else its link words) and its address, read as
# words but for a dot before a digit, so a version stays one (huggingface.co/Qwen/Qwen3.6-35B-A3B
# reads "huggingface co Qwen Qwen3.6 35B A3B"); its title's letters plain (NFKC, issue 0070), as the
# posts' index. Written into a query with parameters: % doubled.
CLASSIC_VECTOR = (
    "search_vector_with_parts("
    "setweight(to_tsvector('russian', normalize(COALESCE(NULLIF(btrim(t.title), ''), c.title, ''), NFKC)), 'A')"
    " || setweight(to_tsvector('russian', regexp_replace(c.target_url, '^https?://(www\\.)?|[/:_?=&#%%+-]+|\\.(?![0-9])', ' ', 'g')), 'B'))"
)
# The groups a result folds into: a story (0050) or a News story (0051), each post in at most one.
_GROUPS = {"story": ("story_posts", "story_id"), "news": ("news_posts", "news_id")}


@dataclass(frozen=True)
class SearchQuery:
    """One page of search results. A bad value is a ValueError (the API's 400).

    `scope` None searches every post. `cursor` is a FeedCursor for newest first and an
    offset for best match (and for Classics, either order)."""

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

    @property
    def paged_by_offset(self) -> bool:
        return self.order == "best" or self.filter == "classics"

    @property
    def folds(self) -> Optional[str]:
        """Which group a result folds into: News stories under News; stories wherever the feed
        folds them (not one source, Later or Kept); else None."""
        if self.filter == "news":
            return "news"
        if self.filter == "all" and (self.scope is None or ReaderRepository.folds(self.scope, "all")):
            return "story"
        return None

    @staticmethod
    def parse(*, q: str, scope: str | None = None, filter: str = "all", days: int | None = None,
              order: str = "newest", cursor: str | None = None, limit: int = 30) -> "SearchQuery":
        """The API's query string: no `scope` searches everything; `cursor` is the last page's
        next_cursor (a feed cursor for newest, an offset for best and for Classics)."""
        feed_cursor, offset = None, 0
        if cursor and (order == "best" or filter == "classics"):
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
        """One page of results and the next page's cursor (encoded), or None at the end. Under
        Classics the results are classics; else feed rows."""
        cur.execute(f"SELECT numnode({TSQUERY})", (query.q,))
        if not cur.fetchone()[0]:
            return [], None   # only stop words or punctuation: nothing can match
        if query.filter == "classics":
            return self._classics(cur, query, now=now)
        since = now - timedelta(days=query.days) if query.days else None
        # The query is written out, not taken from a CTE, so the planner sees its words: a
        # common word walks the feed's order index, a rare one the GIN index.
        where, params = [f"p.search_vector @@ {TSQUERY}", NOT_ALBUM_PIECE], [query.q]
        news = query.filter == "news"
        scope_sql, scope_params = "TRUE", []
        if query.scope is not None:
            scope_sql, scope_params = self.reader._scope_sql(query.scope, "all" if news else query.filter)
        if news:
            # A News story with a post in the scope: any of its posts may match.
            where.append(f"""EXISTS (SELECT 1 FROM news_posts np JOIN news_posts o ON o.news_id = np.news_id
                             JOIN posts op ON op.id = o.post_id JOIN sources os ON os.id = op.source_id
                             WHERE np.post_id = p.id AND {_on(scope_sql, 'op', 'os')})""")
        else:
            where.append(scope_sql)
            filter_sql, filter_params = self.reader._filter_sql(query.filter)
            where.append(filter_sql)
            scope_params = scope_params + filter_params
        params += scope_params
        if since is not None:
            where.append(f"{SORT_KEY} >= %s")
            params.append(since)
        group = query.folds
        if group:
            best_sql, best_params = self._best_of_group_sql(group, query, scope_sql if not news else "TRUE",
                                                            scope_params if not news else [], since)
            where.append(best_sql)
            params += best_params
        limit = query.limit
        if query.order == "best":
            # Ranked among the newest RANKED_MATCHES matches: ranking reads every vector it ranks.
            matches, rank, rank_params = RANKED_MATCHES, RANK.format(v="search_vector"), [query.q]
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
        if group == "story":
            self.reader.attach_stories(cur, items)
        elif group == "news":
            self.attach_news(cur, items, now=now)
        if len(rows) <= limit:
            return items, None
        if query.order == "best":
            return items, str(query.offset + limit)
        return items, FeedCursor(items[-1]["sort_at"], items[-1]["id"]).encode()

    @staticmethod
    def _best_of_group_sql(group: str, query: SearchQuery, scope_sql: str, scope_params: List[Any],
                           since: Optional[datetime]) -> Tuple[str, List[Any]]:
        """`p` is its group's best-matching post among the results (or in no group): no other
        matching post of its story, in the scope and the dates, ranks higher, or ranks the same and
        comes first as the feed's lead does (a report before a share, then the first posted)."""
        table, key = _GROUPS[group]
        shown = [_on(scope_sql, "op", "os")]
        params: List[Any] = [query.q, *scope_params]
        if since is not None:
            shown.append(f"{_on(SORT_KEY, 'op', 'os')} >= %s")
            params.append(since)
        sql = f"""NOT EXISTS (
            SELECT 1 FROM {table} sp
            JOIN {table} o ON o.{key} = sp.{key} AND o.post_id <> sp.post_id
            JOIN posts op ON op.id = o.post_id
            JOIN sources os ON os.id = op.source_id
            CROSS JOIN LATERAL (SELECT {RANK.format(v='op.search_vector')} AS other,
                                       {RANK.format(v='p.search_vector')} AS this) r
            WHERE sp.post_id = p.id AND op.search_vector @@ {TSQUERY} AND {' AND '.join(shown)}
              AND (r.other > r.this
                   OR (r.other = r.this
                       AND ((o.role = 'report' AND sp.role = 'share')
                            OR (o.role = sp.role AND ({_ORDER_RANK.format(sp='o', p='op')})
                                                         < ({_ORDER_RANK.format(sp='sp', p='p')}))))))"""
        return sql, [query.q, query.q, *params]

    @staticmethod
    def attach_news(cur: Cursor, items: List[Dict[str, Any]], *, now: datetime) -> None:
        """Give each item its News story, as GET /api/news shapes it: `story` {id, voices, sources
        (the first report's first, then in the order they covered it), posts: its lines, built as News
        builds them (NewsRepository.lines, issue 0072 D1)} and `news` {part, first_at, reports, shares,
        mentions, score}."""
        if not items:
            return
        cur.execute(
            f"""
            SELECT {_ITEM_COLUMNS}, np.post_id, ns.id, ns.first_at, ns.voices, ns.reports, ns.shares, ns.mentions,
                   ns.score, o.role, o.voice, p.content_hash
            FROM news_posts np
            JOIN news_stories ns ON ns.id = np.news_id
            JOIN news_posts o ON o.news_id = np.news_id
            JOIN posts p ON p.id = o.post_id
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN post_reader_state rs ON rs.post_id = p.id
            WHERE np.post_id = ANY(%s::uuid[])
            ORDER BY np.post_id, {_ORDER_RANK.format(sp='o', p='p')}
            """,
            ([item["id"] for item in items],),
        )
        stories: Dict[str, Dict[str, Any]] = {}
        for row in cur.fetchall():
            shown, news_id, first_at, voices, reports, shares, mentions, score, role, voice, content_hash = row[-11:]
            story = stories.setdefault(str(shown), {
                "story": {"id": str(news_id), "voices": int(voices), "sources": [], "posts": []},
                "news": {"part": "recent" if first_at >= now - NEWS_RECENT else "earlier", "first_at": first_at,
                         "reports": int(reports), "shares": int(shares), "mentions": int(mentions),
                         "score": float(score)},
                "all": [],
            })
            story["all"].append({**_item(row[:-11]), "role": role, "_quotes": quote_only(row[21]),
                                 "_voiced": voiced(row, voice, content_hash)})
        followed = lru_cache(maxsize=1)(lambda: ReaderRepository.followed_accounts(cur))
        for item in items:
            found = stories.get(item["id"])
            item["story"], item["news"] = (found["story"], found["news"]) if found else (None, None)
            if not found:
                continue
            posts = found.pop("all")
            first_report = lead([(p["id"], p["role"]) for p in posts])
            covered = sorted(posts, key=lambda p: p["id"] != first_report)   # stable: time order after
            found["story"]["sources"] = story_voices([p["_voiced"] for p in covered], followed)   # as News (0082)
            found["story"]["posts"] = NewsRepository.lines(posts, item["id"])

    def _classics(self, cur: Cursor, query: SearchQuery, *, now: datetime
                  ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Classics whose title or address matches, you did not hide, a source of the scope among
        their citers (every classic with no scope); cited in the last N days with `days`. Newest
        is the most recently cited first; best, the best match. Shaped as GET /api/classics."""
        where, params = [], []
        if query.scope is not None:
            scope_sql, scope_params = news_scope_sql(query.scope)
            where.append(f"""EXISTS (SELECT 1 FROM jsonb_array_elements(c.citers) ci
                          CROSS JOIN LATERAL jsonb_array_elements_text(ci->'source_ids') x(sid)
                          JOIN sources s ON s.id = x.sid::uuid
                          WHERE {scope_sql})""")
            params += scope_params
        if query.days:
            where.append("c.last_at >= %s")
            params.append(now - timedelta(days=query.days))
        order = "v.rank DESC, c.last_at DESC, c.target_url" if query.order == "best" else "c.last_at DESC, c.target_url"
        cur.execute(
            f"""
            SELECT c.target_url, c.voices, c.first_at, c.last_at, c.title, c.citers,
                   t.id, {title_columns("t")}, r.read_at, r.later_at
            FROM classics c
            LEFT JOIN LATERAL (SELECT tp.id, tp.title, tp.content, tp.content_html FROM posts tp WHERE tp.normalized_url = c.target_url
                               ORDER BY tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            LEFT JOIN post_reader_state r ON r.post_id = t.id
            CROSS JOIN LATERAL (SELECT {CLASSIC_VECTOR} AS vector) w
            CROSS JOIN LATERAL (SELECT ts_rank(w.vector, {TSQUERY}, 1) AS rank) v
            WHERE w.vector @@ {TSQUERY}
              AND NOT EXISTS (SELECT 1 FROM classic_hidden h WHERE h.target_url = c.target_url)
              AND {' AND '.join(where) or 'TRUE'}
            ORDER BY {order}
            OFFSET %s LIMIT %s
            """,
            [query.q, query.q, *params, query.offset, query.limit + 1],
            prepare=False,
        )
        rows = cur.fetchall()
        out = []
        for url, voices, first_at, last_at, title, citers, post_id, stored_title, content, html, read_at, later_at in rows[:query.limit]:
            shown = post_title(stored_title, content, html) if post_id else title
            out.append({
                "url": url, "post_id": str(post_id) if post_id else None, "title": shown or None,
                "voices": int(voices), "days": (last_at - first_at).days, "first_at": first_at, "last_at": last_at,
                "cited_again": cited_again(last_at, now),
                "citers": [{"name": c["name"], "at": c["at"]} for c in citers],
                "read_at": read_at, "later_at": later_at,
            })
        return out, (str(query.offset + query.limit) if len(rows) > query.limit else None)

    def fill_missing_vectors(self, cur: Cursor, batch: int = FILL_BATCH) -> int:
        """Fill the search vector of up to `batch` posts whose vector is missing (stored before
        0033) or made by an older rule (`search_version`, 0042); how many were."""
        cur.execute(
            """
            WITH batch AS (SELECT id FROM posts
                           WHERE search_vector IS NULL OR search_version IS DISTINCT FROM search_vector_version()
                           LIMIT %s FOR UPDATE SKIP LOCKED)
            UPDATE posts p
               SET search_vector = post_search_vector(p.title, p.content, source_search_name(s.settings, s.handle_or_url)),
                   search_version = search_vector_version()
              FROM batch, sources s
             WHERE p.id = batch.id AND s.id = p.source_id
            """,
            (batch,),
        )
        return cur.rowcount

    @staticmethod
    def missing_vectors(cur: Cursor) -> bool:
        """Whether a post still waits for its vector (fill_missing_vectors), locked rows too."""
        cur.execute("SELECT EXISTS (SELECT 1 FROM posts"
                    " WHERE search_vector IS NULL OR search_version IS DISTINCT FROM search_vector_version())")
        return cur.fetchone()[0]
