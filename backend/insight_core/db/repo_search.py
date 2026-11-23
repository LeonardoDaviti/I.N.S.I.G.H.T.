"""Search across every post: `posts.search_vector` over its GIN index.

A query is read by `search_query(q)` (websearch_to_tsquery: English and Russian word forms, "phrases", -word,
`or`; version words like "K3.1" also as their parts; a name and its version after it as a pair). It matches
title (weighted most), source name and text; read state doesn't matter. Narrowing: a scope, one of Later,
Kept, History, News and Classics, the last N days. Newest first (keyset on the feed's sort key) or best
(rank over the newest RANKED_MATCHES, paged by offset); 2+ words default to best. Unless the search is of one
source, Later or Kept, a story shows once at its best-matching post. With Mark X on (`markx`) a post also
matches by Mark X's English layer (mx_post_search), and best order puts a title that is the query, then the
posts naming the query's entity, then title phrases first. Stored vectors carry their rule's version
(`posts.search_version`); the background fill refills older ones.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional, Tuple

from psycopg import Cursor

from insight_core.db.repo_news import NewsRepository, _scope_sql as news_scope_sql
from insight_core.db.repo_reader import (
    _ITEM_COLUMNS, _ORDER_RANK, HISTORY_CTE, MAX_FEED_LIMIT, NOT_ALBUM_PIECE, SORT_KEY, FeedCursor, FeedScope, ReaderRepository,
    _item, _on, story_voices, voiced,
)
from insight_core.utils.content_fingerprints import WHITESPACE_RE, decode_entities
from insight_core.utils.classic_rules import cited_again
from insight_core.utils.news_rules import NEWS_RECENT, lead
from insight_core.db.repo_post_parts import shown_title

SearchFilter = Literal["all", "later", "starred", "history", "news", "classics"]   # starred is Keep ("Kept")
SearchOrder = Literal["newest", "best"]
SEARCH_FILTERS: Tuple[str, ...] = ("all", "later", "starred", "history", "news", "classics")
SEARCH_ORDERS: Tuple[str, ...] = ("newest", "best")
MAX_QUERY_CHARS = 500
MAX_SEARCH_OFFSET = 10_000   # a deeper "best" page made the database rank and skip that many rows (0187)

# The matching line: one fragment around the best cover of the query, its words between two control characters
# (stripped from the text first, so only ts_headline's remain).
MARK_START, MARK_END = "\x01", "\x02"
HEADLINE_OPTIONS = f"StartSel={MARK_START}, StopSel={MARK_END}, MaxWords=28, MinWords=12, MaxFragments=1"
# ts_headline reads the text it is given in full; past this the line is not looked for.
HEADLINE_CHARS = 20000
# The query, read as the index is: words, phrases, -word, and version words by their parts.
TSQUERY = "search_query(%s)"
# Posts whose vector is missing or made by an older rule are filled this many a transaction.
FILL_BATCH = 500
# Best match ranks the newest this many matches (a word in most posts ranks no better).
RANKED_MATCHES = 5000
# Rank, normalised by 1 + log(length) so a long text does not win by length. Ranked by the query's words
# unpaired: ts_rank reads a top-level `|` of pairs word by word with no nearness. The pairs decide only matching.
RANK_TSQUERY = "search_query_words(%s)"
RANK = "ts_rank({v}, " + RANK_TSQUERY + ", 1)"
# Mark X's English layer (mx_post_search): the query read as English words, a name and its version together.
MX_TSQUERY = "search_query_english(%s)"
# the words its line marks, each alone (the line's own parse has no version parts)
MX_WORDS = "websearch_to_tsquery('english', %s)"
MX_MARK_TSQUERY = (f"(CASE WHEN querytree({MX_WORDS}) = 'T' THEN {MX_WORDS}"
                   f" ELSE replace(querytree({MX_WORDS}), ' & ', ' | ')::tsquery END)")
# A query of this many words or more orders by best match unless an order is asked.
BEST_FROM_WORDS = 2
# The words the line marks: any one of them, so the line shows the text's words even when others matched in
# the title or source name; never an excluded word (querytree drops them). Its three %s are the same query.
WORDS = "search_query_words(%s)"
MARK_TSQUERY = (f"(CASE WHEN querytree({WORDS}) = 'T' THEN {WORDS}"
                f" ELSE replace(querytree({WORDS}), ' & ', ' | ')::tsquery END)")
# A classic's words: its title and address, read as words but for a dot before a digit, so a version stays one
# ("Qwen3.6"); its title's letters NFKC-plain as the posts' index. Written into a query with parameters: % doubled.
CLASSIC_VECTOR = (
    "search_vector_with_parts("
    "setweight(to_tsvector('russian', normalize(COALESCE(NULLIF(btrim(t.title), ''), c.title, ''), NFKC)), 'A')"
    " || setweight(to_tsvector('russian', regexp_replace(c.target_url, '^https?://(www\\.)?|[/:_?=&#%%+-]+|\\.(?![0-9])', ' ', 'g')), 'B'))"
)


def _rank_sql(vector: str, post_id: str, markx: bool, split: bool = True) -> str:
    """A post's rank: its own vector's; with Mark X's layer, the highest of that, the English layer's and, with
    `split`, the two together (the words split across both). Parameters: _rank_params."""
    if not markx:
        return RANK.format(v=vector)
    if not split:
        return (f"GREATEST({RANK.format(v=vector)}, COALESCE((SELECT ts_rank(mx.vector, {MX_WORDS}, 1)"
                f" FROM mx_post_search mx WHERE mx.post_id = {post_id} AND mx.vector @@ {MX_TSQUERY}), 0))")
    # one read of the layer's row; the two together are ranked only when the post's own words don't match alone
    return (f"GREATEST({RANK.format(v=vector)}, COALESCE((SELECT GREATEST("
            f"CASE WHEN mx.vector @@ {MX_TSQUERY} THEN ts_rank(mx.vector, {MX_WORDS}, 1) ELSE 0 END,"
            f" CASE WHEN NOT {vector} @@ {TSQUERY} AND ({vector} || mx.vector_ix) @@ {TSQUERY}"
            f" THEN ts_rank({vector} || mx.vector_ix, {RANK_TSQUERY}, 1) ELSE 0 END)"
            f" FROM mx_post_search mx WHERE mx.post_id = {post_id}), 0))")


def _rank_params(q: str, markx: bool, split: bool = True) -> List[Any]:
    return ([q] * 6 if split else [q] * 3) if markx else [q]


def _split_match(post: str) -> str:
    """The query's words split between the post's own vector and Mark X's layer: candidates hold one word in each
    (both GIN indexes), then the two together must match the whole query. Parameters: [q] * 7."""
    return (f"({post}.search_vector @@ {MARK_TSQUERY}"
            f" AND {post}.id IN (SELECT mx.post_id FROM mx_post_search mx WHERE mx.vector_ix @@ {MARK_TSQUERY})"
            f" AND ({post}.search_vector || (SELECT mx.vector_ix FROM mx_post_search mx WHERE mx.post_id = {post}.id))"
            f" @@ {TSQUERY})")


def _words(q: str) -> int:
    """How many words a query asks for: `or` and an excluded -word are no words."""
    return len([w for w in q.split() if w.lower() != "or" and not w.startswith("-") and any(c.isalnum() for c in w)])


def default_order(q: str) -> str:
    """Best match for a query of 2+ words, newest for one."""
    return "best" if _words(q) >= BEST_FROM_WORDS else "newest"


# The groups a result folds into: a story or a News story, each post in at most one.
_GROUPS = {"story": ("story_posts", "story_id"), "news": ("news_posts", "news_id")}


@dataclass(frozen=True)
class SearchQuery:
    """One page of search results. A bad value is a ValueError (the API's 400).

    `scope` None searches every post. `cursor` is a FeedCursor for newest first and an offset for best match
    (and for Classics, either order)."""

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
        if not 0 <= self.offset <= MAX_SEARCH_OFFSET:
            raise ValueError(f"the search cursor must be from 0 to {MAX_SEARCH_OFFSET}")

    @property
    def paged_by_offset(self) -> bool:
        return self.order == "best" or self.filter == "classics"

    @property
    def folds(self) -> Optional[str]:
        """Which group a result folds into: News stories under News; stories wherever the feed folds them (not
        one source, Later or Kept); else None."""
        if self.filter == "news":
            return "news"
        if self.filter == "all" and (self.scope is None or ReaderRepository.folds(self.scope, "all")):
            return "story"
        return None

    @staticmethod
    def parse(*, q: str, scope: str | None = None, filter: str = "all", days: int | None = None,
              order: str | None = None, cursor: str | None = None, limit: int = 30) -> "SearchQuery":
        """The API's query string: no `scope` searches everything; `cursor` is the last page's next_cursor. No
        `order`: default_order."""
        order = order or default_order(q)
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


def snippet_parts(headline: str | None, *, plain: bool = False) -> Optional[List[Dict[str, Any]]]:
    """ts_headline's line as [{text, mark}] parts; None when no word in it is marked (the match was in the title
    or source name), unless `plain` (Mark X's headline matched by a name it does not hold): its words unmarked."""
    if not headline or (MARK_START not in headline and not plain):
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


_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:[/?#]\S*)?$", re.IGNORECASE)
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,}$", re.IGNORECASE)


def title_phrase(q: str) -> str:
    """The query as a title phrase: lower case, every run of non-letters one space."""
    return " ".join(re.sub(r"[^\w]+", " ", (q or "").lower().replace("_", " ")).split())


def address_query(q: str) -> Optional[Tuple[str, str]]:
    """("url", its normalized form) for a pasted address, ("slug", it) for a page's slug (3+ hyphenated words, no
    space), else None."""
    from insight_core.utils.url_normalization import normalize_url
    text = (q or "").strip().strip("<>\"'")
    if not text or " " in text:
        return None
    if _URL_RE.match(text) and ("/" in text or text.lower().startswith("http")):
        normalized = normalize_url(text if "://" in text else f"https://{text}")
        return ("url", normalized) if normalized else None
    if _SLUG_RE.match(text) and len(text) >= 12:
        return ("slug", text.lower())
    return None


class SearchRepository:
    """SQL for search. Takes the caller's cursor; the caller owns the commit."""

    def __init__(self, reader: ReaderRepository | None = None):
        self.reader = reader or ReaderRepository(unread_window_days=None)

    def search(self, cur: Cursor, query: SearchQuery, *, now: datetime, markx: bool = False
               ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """One page of results and the next page's cursor (encoded), or None at the end. Under Classics the results
        are classics; else feed rows. `markx`: a post also matches by its Mark X English layer."""
        if query.filter != "classics" and query.cursor is None and query.offset == 0:
            found = self._by_address(cur, query)
            if found is not None:
                return found, None
        # whether the query pairs a name and its version (its reading differs from its words unpaired)
        cur.execute(f"SELECT numnode({TSQUERY}), {TSQUERY}::text <> {WORDS}::text", (query.q, query.q, query.q))
        nodes, paired = cur.fetchone()
        if not nodes:
            return [], None   # only stop words or punctuation: nothing can match
        if query.filter == "classics":
            return self._classics(cur, query, now=now)
        since = now - timedelta(days=query.days) if query.days else None
        history = query.filter == "history"
        # History: the posts it lists, keyed by their last open
        key = "h.opened_at" if history else SORT_KEY
        joins = f"JOIN ({HISTORY_CTE}) h ON h.post_id = p.id" if history else ""
        # The query is written out, not taken from a CTE, so the planner sees its words (a common word walks the
        # feed's order index, a rare one the GIN index). Mark X's layer is a branch of its own joined after: an OR
        # across two tables reads neither index.
        where: List[str] = [NOT_ALBUM_PIECE]
        params: List[Any] = []
        news = query.filter == "news"
        scope_sql, scope_params = "TRUE", []
        if query.scope is not None:
            scope_sql, scope_params = self.reader._scope_sql(query.scope, "all" if news else query.filter)
        if news:
            # a News story with a post in the scope: any of its posts may match
            where.append(f"""EXISTS (SELECT 1 FROM news_posts np JOIN news_posts o ON o.news_id = np.news_id
                             JOIN posts op ON op.id = o.post_id JOIN sources os ON os.id = op.source_id
                             WHERE np.post_id = p.id AND {_on(scope_sql, 'op', 'os')})""")
        else:
            where.append(scope_sql)
            if not history:   # History is its join
                filter_sql, filter_params = self.reader._filter_sql(query.filter)
                where.append(filter_sql)
                scope_params = scope_params + filter_params
        params += scope_params
        if since is not None:
            where.append(f"{key} >= %s")
            params.append(since)
        group = query.folds
        if group:
            best_sql, best_params = self._best_of_group_sql(group, query, scope_sql if not news else "TRUE",
                                                            scope_params if not news else [], since, markx=markx)
            where.append(best_sql)
            params += best_params
        limit = query.limit
        # Entity first: with Mark X on, best match ranks first the posts naming the query's entity as subject or
        # actor, and a group holding one.
        first_ids: List[str] = []
        if markx and query.order == "best":
            from insight_core.markx import search as mx_search
            first_ids = mx_search.entity_first_posts(cur, query.q)
            if first_ids and group:
                table, gkey = _GROUPS[group]
                cur.execute(f"""SELECT DISTINCT o.post_id::text FROM {table} sp JOIN {table} o ON o.{gkey} = sp.{gkey}
                                WHERE sp.post_id = ANY(%s::uuid[])""", (first_ids,))
                first_ids = sorted(set(first_ids) | {r[0] for r in cur.fetchall()})
        # In best order the nearest posts by meaning (markx/search.meaning_posts; [] without an embedder) join the
        # matches, merged with the word ranking by reciprocal rank (RRF_K); marked `matched: "meaning"`.
        meaning_ids: List[str] = []
        if markx and query.order == "best":
            from insight_core.markx import search as mx_search
            meaning_ids = mx_search.meaning_posts(cur, query.q)
        if query.order == "best":
            # ranked among the newest RANKED_MATCHES matches: ranking reads every vector it ranks
            split = _words(query.q) >= 2
            rank, rank_params = _rank_sql("m.search_vector", "m.id", markx, split), _rank_params(query.q, markx, split)
            matches, page, page_params = RANKED_MATCHES, "OFFSET %s", [query.offset]
        else:
            matches, rank, rank_params, page, page_params = limit + 1, "0", [], "", []
            if query.cursor is not None:
                where.append(f"({key}, p.id) < (%s, %s::uuid)")
                params += [query.cursor.sort_at, query.cursor.post_id]
        # in best order a post whose title holds the whole query as a phrase comes before the ranked rest
        phrase = title_phrase(query.q)
        if query.order == "best" and _words(query.q) >= 2 and phrase:
            norm = "btrim(regexp_replace(lower(coalesce(m.title, '')), '[^[:alnum:]]+', ' ', 'g'))"
            titled = f"(' ' || {norm} || ' ') LIKE ('%% ' || %s || ' %%')"
            # a title that IS the query (less a leading article) is the thing's own page: first of all, before the
            # entity's posts; a title that only holds the query stays after them
            bare = re.sub(r"^(the|a|an) ", "", phrase)
            typed = [w for w in query.q.split() if w.lower() not in ("the", "a", "an")]
            if len(typed) >= 3:   # a title's length as typed, not a name's
                exact, exact_params = f"regexp_replace({norm}, '^(the|a|an) ', '') = %s", [bare]
            else:
                exact, exact_params = "false", []
            titled_params = [phrase]
            if paired:
                # a name and its version together in the title (weight A), as the index reads them, hold it too
                titled = f"({titled} OR ts_filter(m.search_vector, '{{a}}') @@ {TSQUERY})"
                titled_params.append(query.q)
        else:
            titled, titled_params, exact, exact_params = "false", [], "false", []
        # A common word looks cheaper by a table scan, but every row read then unpacks its vector; the GIN bitmap
        # needs none. For this transaction only.
        cur.execute("SET LOCAL enable_seqscan = off")
        # Mark X's line: its English headline, for a post its own words did not match
        if markx:
            mx_line = (f"(SELECT ts_headline('english', translate(mx.headline, %s, ''), {MX_MARK_TSQUERY}, %s)"
                       f" FROM mx_post_search mx WHERE mx.post_id = p.id AND mx.headline IS NOT NULL"
                       f" AND NOT p.search_vector @@ {TSQUERY} AND mx.vector @@ {MX_TSQUERY})")
            line_params = [MARK_START + MARK_END, query.q, query.q, query.q, HEADLINE_OPTIONS, query.q, query.q]
        else:
            mx_line, line_params = "NULL::text", []
        # The matches newest first, then the page, then the line for its rows only: ts_headline re-reads each text.
        def branch(match: str, word: bool = True) -> str:   # the matches of one layer, newest first, limited
            return f"""(SELECT p.id, {key} AS sort_at, {'TRUE' if word else 'FALSE'} AS word
                FROM posts p
                JOIN sources s ON s.id = p.source_id
                LEFT JOIN post_reader_state rs ON rs.post_id = p.id
                {joins}
                WHERE {match} AND {' AND '.join(where)}
                ORDER BY sort_at DESC, p.id DESC
                LIMIT %s)"""
        own = branch(f"p.search_vector @@ {TSQUERY}")
        if markx:
            layers = f"{own} UNION {branch(f'p.id IN (SELECT mx.post_id FROM mx_post_search mx WHERE mx.vector @@ {MX_TSQUERY})')}"
            layer_params = [query.q, *params, matches, query.q, *params, matches]
            if _words(query.q) >= 2:   # one word is never split between the two
                layers += f" UNION {branch(_split_match('p'))}"
                layer_params += [*[query.q] * 7, *params, matches]
        else:
            layers, layer_params = own, [query.q, *params, matches]
        if meaning_ids:   # the nearest posts, under the same scope, filter, dates and story rule
            layers += f" UNION {branch('p.id = ANY(%s::uuid[])', word=False)}"
            layer_params += [meaning_ids, *params, matches]
        from insight_core.markx.search import RRF_K
        cur.execute(
            f"""
            WITH matches AS (
                SELECT u.id, max(u.sort_at) AS sort_at, bool_or(u.word) AS word, p.search_vector, p.title
                FROM ({layers}) u
                JOIN posts p ON p.id = u.id
                GROUP BY u.id, p.search_vector, p.title
                ORDER BY bool_or(u.word), max(u.sort_at) DESC, u.id DESC
                LIMIT %s
            ), ranked AS (
                SELECT m.id, m.sort_at, m.word, CASE WHEN m.word THEN {rank} ELSE 0 END AS rank,
                       m.id = ANY(%s::uuid[]) AS first, {titled} AS titled, {exact} AS exact FROM matches m
            ), hits AS (
                SELECT r.*, CASE WHEN r.word THEN 1.0 / ({RRF_K} + row_number() OVER (
                                     ORDER BY r.word DESC, r.rank DESC, r.sort_at DESC, r.id DESC)) ELSE 0 END
                            + COALESCE(1.0 / ({RRF_K} + array_position(%s::uuid[], r.id)), 0) AS fused
                FROM ranked r
                ORDER BY exact DESC, first DESC, titled DESC, fused DESC, rank DESC, sort_at DESC, id DESC
                {page}
                LIMIT %s
            )
            SELECT {_ITEM_COLUMNS},
                   hits.sort_at,
                   hits.word,
                   {mx_line},
                   ts_headline('russian', translate(left(p.content, {HEADLINE_CHARS}), %s, ''), {MARK_TSQUERY}, %s)
            FROM hits
            JOIN posts p ON p.id = hits.id
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN post_reader_state rs ON rs.post_id = p.id
            LEFT JOIN post_parts pp ON pp.post_id = p.id
            ORDER BY hits.exact DESC, hits.first DESC, hits.titled DESC, hits.fused DESC, hits.rank DESC, hits.sort_at DESC,
                     hits.id DESC
            """,
            [*layer_params, matches, *rank_params, first_ids, *titled_params, *exact_params, meaning_ids, *page_params, limit + 1, *line_params, MARK_START + MARK_END,
             query.q, query.q, query.q, HEADLINE_OPTIONS],
            # never a prepared statement: a generic plan cannot see the words and walks the wrong index
            prepare=False,
        )
        rows = cur.fetchall()
        items = []
        for row in rows[:limit]:
            item = _item(row[:-4])
            sort_at, word, markx_line, own_line = row[-4:]
            if history:   # its key is the last open, as History lists it
                item["sort_at"] = item["opened_at"] = sort_at
            if markx_line is not None:   # only Mark X's English layer matched: its headline, marked "Mark X"
                item["snippet"] = snippet_parts(markx_line, plain=True)
                item["snippet_from"] = "markx"
            else:
                item["snippet"] = snippet_parts(own_line)
            if not word:   # found by meaning, not words: its first line, marked "by meaning"
                item["snippet"] = snippet_parts(own_line, plain=True)
                item["snippet_from"] = "meaning"
                item["matched"] = "meaning"
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
                           since: Optional[datetime], *, markx: bool = False) -> Tuple[str, List[Any]]:
        """`p` is its group's best-matching post among the results (or in no group): no other matching post of its
        story, in the scope and dates, ranks higher, or ranks the same and comes first as the feed's lead does.
        With Mark X's layer a post matches and ranks by either vector."""
        table, key = _GROUPS[group]
        shown = [_on(scope_sql, "op", "os")]
        params: List[Any] = [*scope_params]
        if since is not None:
            shown.append(f"{_on(SORT_KEY, 'op', 'os')} >= %s")
            params.append(since)
        # the story's other posts match by own words or Mark X's English, not the split (cheaper); a post matched
        # only that way may show too
        split = False
        if markx:
            matched = (f"(op.search_vector @@ {TSQUERY} OR EXISTS (SELECT 1 FROM mx_post_search mx"
                       f" WHERE mx.post_id = op.id AND mx.vector @@ {MX_TSQUERY}))")
            matched_params = [query.q, query.q]
        else:
            matched, matched_params = f"op.search_vector @@ {TSQUERY}", [query.q]
        sql = f"""NOT EXISTS (
            SELECT 1 FROM {table} sp
            JOIN {table} o ON o.{key} = sp.{key} AND o.post_id <> sp.post_id
            JOIN posts op ON op.id = o.post_id
            JOIN sources os ON os.id = op.source_id
            CROSS JOIN LATERAL (SELECT {_rank_sql('op.search_vector', 'op.id', markx, split)} AS other,
                                       {_rank_sql('p.search_vector', 'p.id', markx, split)} AS this) r
            WHERE sp.post_id = p.id AND {matched} AND {' AND '.join(shown)}
              AND (r.other > r.this
                   OR (r.other = r.this
                       AND ((o.role = 'report' AND sp.role = 'share')
                            OR (o.role = sp.role AND ({_ORDER_RANK.format(sp='o', p='op')})
                                                         < ({_ORDER_RANK.format(sp='sp', p='p')}))))))"""
        ranks = _rank_params(query.q, markx, split)
        return sql, [*ranks, *ranks, *matched_params, *params]

    def _by_address(self, cur: Cursor, query: SearchQuery) -> Optional[List[Dict[str, Any]]]:
        """A pasted address finds its post (normalized address or canonical), a slug the posts whose address holds
        it, in the query's scope and filter; None when the query is no address or nothing has it."""
        kind = address_query(query.q)
        if kind is None or query.filter == "history":   # History lists what you opened: its own path
            return None
        where: List[str] = [NOT_ALBUM_PIECE]
        params: List[Any] = []
        if query.scope is not None:
            scope_sql, scope_params = self.reader._scope_sql(query.scope, query.filter if query.filter != "news" else "all")
            where.append(scope_sql)
            params += scope_params
        if query.filter not in ("news", "history"):
            filter_sql, filter_params = self.reader._filter_sql(query.filter)
            where.append(filter_sql)
            params += filter_params
        if kind[0] == "url":
            match = "p.normalized_url = %s"   # its index; every stored address is kept normalized
            match_params = [kind[1]]
        else:
            match = "p.normalized_url LIKE %s"
            match_params = [f"%/{kind[1]}%"]
        cur.execute(
            f"""SELECT {_ITEM_COLUMNS}, {SORT_KEY}
                  FROM posts p
                  JOIN sources s ON s.id = p.source_id
                  LEFT JOIN post_reader_state rs ON rs.post_id = p.id
                  LEFT JOIN post_parts pp ON pp.post_id = p.id
                 WHERE {match} AND {' AND '.join(where)}
                 ORDER BY {SORT_KEY} DESC, p.id DESC
                 LIMIT %s""",
            [*match_params, *params, query.limit], prepare=False)
        rows = cur.fetchall()
        if not rows:
            return None
        items = []
        for row in rows:
            item = _item(row[:-1])
            item["snippet"] = None
            item["matched"] = "address"
            items.append(item)
        return items

    @staticmethod
    def attach_news(cur: Cursor, items: List[Dict[str, Any]], *, now: datetime) -> None:
        """Give each item its News story, as GET /api/news shapes it: `story` {id, voices, sources, posts (lines, as
        NewsRepository.lines builds them)} and `news` {part, first_at, reports, shares, mentions, score}."""
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
            LEFT JOIN post_parts pp ON pp.post_id = p.id
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
            story["all"].append({**_item(row[:-11]), "role": role, "_quotes": row[21],
                                 "_voiced": voiced(row, voice, content_hash)})
        followed = lru_cache(maxsize=1)(lambda: ReaderRepository.followed_accounts(cur))
        from insight_core.db.repo_news import NewsRepository as _News
        owners = _News.owners(cur)   # News counts one owner's channels once
        for item in items:
            found = stories.get(item["id"])
            item["story"], item["news"] = (found["story"], found["news"]) if found else (None, None)
            if not found:
                continue
            posts = found.pop("all")
            first_report = lead([(p["id"], p["role"]) for p in posts])
            covered = sorted(posts, key=lambda p: p["id"] != first_report)   # stable: time order after
            found["story"]["sources"] = story_voices([p["_voiced"] for p in covered], followed, owners)
            found["story"]["posts"] = NewsRepository.lines(posts, item["id"])

    def _classics(self, cur: Cursor, query: SearchQuery, *, now: datetime
                  ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Classics whose title or address matches, not hidden, a source of the scope among their citers; cited in
        the last N days with `days`. Newest is most recently cited first. Shaped as GET /api/classics."""
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
                   t.id, t.title, r.read_at, r.later_at
            FROM classics c
            LEFT JOIN LATERAL (SELECT tp.id, {shown_title("tp")} AS title FROM posts tp WHERE tp.normalized_url = c.target_url
                               ORDER BY tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            LEFT JOIN post_reader_state r ON r.post_id = t.id
            CROSS JOIN LATERAL (SELECT {CLASSIC_VECTOR} AS vector) w
            CROSS JOIN LATERAL (SELECT ts_rank(w.vector, {RANK_TSQUERY}, 1) AS rank) v
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
        for url, voices, first_at, last_at, title, citers, post_id, stored_title, read_at, later_at in rows[:query.limit]:
            shown = stored_title if post_id else title
            out.append({
                "url": url, "post_id": str(post_id) if post_id else None, "title": shown or None,
                "voices": int(voices), "days": (last_at - first_at).days, "first_at": first_at, "last_at": last_at,
                "cited_again": cited_again(last_at, now),
                "citers": [{"name": c["name"], "at": c["at"]} for c in citers],
                "read_at": read_at, "later_at": later_at,
            })
        return out, (str(query.offset + query.limit) if len(rows) > query.limit else None)

    def fill_missing_vectors(self, cur: Cursor, batch: int = FILL_BATCH) -> int:
        """Fill the search vector of up to `batch` posts whose vector is missing or older than the rule; returns
        how many."""
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
