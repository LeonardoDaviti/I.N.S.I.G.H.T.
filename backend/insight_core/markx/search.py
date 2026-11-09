"""Mark X's English layer in search, and the search's entity cards (issue 0139).

`mx_post_search` (migration 0090) holds one row a post that Mark X answered: `to_tsvector('english', …)` of its current
reading (the newest read guide's, as the post page's panel reads it: the English headline, weight A; the main action,
object, actors and numbers, B) and its current entity set (`mx_mentions_now`: each mention's name and its entity's
name, A; the makers and the entities' aliases, B). It is written when a read, entities or cite answer is stored
(`refresh`, from tasks.record) and by a resumable background fill (`fill_batch` / `pending`, like 0033's): a post with
an answer and no row, a row of an older VERSION, or a row older than the post's newest reading or entity set.
`vector_ix` is the same text under the posts' index rule (post_search_vector's: 'russian', NFKC, version parts), so a
query's words split between the post's own text and Mark X's English (one in each) match the two together.

Search reads it only while Mark X is on (`enabled`); Mark IX's `posts.search_vector` and its rule are unchanged.

`entity_cards(cur, q)`: up to 3 entities whose name or alias (identity's key, names.key) is the query or a run of its
words, or starts with the query (3+ letters), read through the merges (redirects) to the entity shown; with each its
type, maker, posts and voices (the current entity sets').
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

from psycopg import Cursor

# The rule that makes a row: a change to what goes in the vector raises it, and the fill remakes every row.
VERSION = 2   # 2: vector_ix, the layer under the posts' index rule (the words split across both)
FILL_BATCH = 500
ENTITY_CARDS = 3
PREFIX_MIN = 3          # a prefix matches from 3 letters
MAX_QUERY_WORDS = 8     # runs of words are read from the first 8

# The current reading (the newest read guide's, as markx/news.post_panel reads it) and the current entity set of each
# post of `ids`, as the row's vector, headline and version. Written for every id given, an empty vector when nothing is
# left to read, so the fill never asks for a post again.
_WRITE = """
INSERT INTO mx_post_search (post_id, vector, vector_ix, headline, version, updated_at)
SELECT ids.id,
       setweight(to_tsvector('english', concat_ws(' ', r.headline, m.names)), 'A')
       || setweight(to_tsvector('english', concat_ws(' ', r.rest, m.rest)), 'B'),
       search_vector_with_parts(
         setweight(to_tsvector('russian', normalize(concat_ws(' ', r.headline, m.names), NFKC)), 'A')
         || setweight(to_tsvector('russian', normalize(concat_ws(' ', r.rest, m.rest), NFKC)), 'B')),
       r.headline, %(version)s, now()
  FROM unnest(%(ids)s::uuid[]) AS ids(id)
  LEFT JOIN LATERAL (
       SELECT NULLIF(btrim(COALESCE(x.reading->'main'->>'headline_en', x.headline)), '') AS headline,
              concat_ws(' ', x.reading->'main'->>'action', x.reading->'main'->>'object',
                        CASE jsonb_typeof(x.reading->'main'->'actors')
                             WHEN 'array' THEN (SELECT string_agg(a #>> '{}', ' ')
                                                  FROM jsonb_array_elements(x.reading->'main'->'actors') a)
                             WHEN 'string' THEN x.reading->'main'->>'actors' END,
                        CASE WHEN jsonb_typeof(x.reading->'main'->'numbers') = 'array'
                             THEN (SELECT string_agg(n #>> '{}', ' ')
                                     FROM jsonb_array_elements(x.reading->'main'->'numbers') n) END) AS rest
         FROM mx_readings x WHERE x.post_id = ids.id
        ORDER BY x.guide DESC LIMIT 1) r ON TRUE
  LEFT JOIN LATERAL (
       SELECT string_agg(concat_ws(' ', mm.name, e.name), ' ') AS names,
              string_agg(concat_ws(' ', mm.maker, e.maker,
                                   (SELECT string_agg(al.key, ' ') FROM mx_entity_aliases al
                                     WHERE al.entity_id = mm.entity_id)), ' ') AS rest
         FROM mx_mentions_now mm
         LEFT JOIN mx_entities e ON e.id = mm.entity_id
        WHERE mm.post_id = ids.id) m ON TRUE
ON CONFLICT (post_id) DO UPDATE
   SET vector = EXCLUDED.vector, vector_ix = EXCLUDED.vector_ix, headline = EXCLUDED.headline, version = EXCLUDED.version, updated_at = now()
"""

# The posts whose row is missing, of an older rule, or older than their newest reading or entity set.
_STALE = """
SELECT a.post_id FROM (
       SELECT x.post_id, max(c.created_at) AS at FROM mx_readings x JOIN mx_calls c ON c.id = x.call_id GROUP BY x.post_id
       UNION ALL
       SELECT post_id, at FROM mx_mention_sets) a
  LEFT JOIN mx_post_search s ON s.post_id = a.post_id
 WHERE s.post_id IS NULL OR s.version <> %s OR s.updated_at < a.at
"""


def enabled() -> bool:
    """Whether Mark X is on (INSIGHT_MARKX, as markx/api.enabled reads it): search reads its layer only then."""
    return os.getenv("INSIGHT_MARKX", "off").strip().lower() in ("on", "1", "true", "yes")


def refresh(cur: Cursor, post_ids: Iterable[Any]) -> int:
    """Write (or rewrite) these posts' rows from their current answers; how many."""
    ids = sorted({str(p) for p in post_ids if p})
    if not ids:
        return 0
    cur.execute(_WRITE, {"ids": ids, "version": VERSION})
    return cur.rowcount


def refresh_safely(cur: Cursor, post_ids: Iterable[Any]) -> None:
    """refresh in a savepoint: a stored answer never fails for its search row (the fill writes it later)."""
    cur.execute("SAVEPOINT mx_post_search")
    try:
        refresh(cur, post_ids)
    except Exception:  # noqa: BLE001 - the answer stays; the background fill retries the row
        cur.execute("ROLLBACK TO SAVEPOINT mx_post_search")
    cur.execute("RELEASE SAVEPOINT mx_post_search")


def fill_batch(cur: Cursor, batch: int = FILL_BATCH) -> int:
    """Up to `batch` posts' rows written (missing, older rule, older than their answers); how many."""
    cur.execute(f"SELECT DISTINCT post_id FROM ({_STALE}) t LIMIT %s", (VERSION, batch))
    return refresh(cur, [r[0] for r in cur.fetchall()])


def pending(cur: Cursor) -> bool:
    """Whether a post still waits for its row."""
    cur.execute(f"SELECT EXISTS ({_STALE})", (VERSION,))
    return bool(cur.fetchone()[0])


# ---- the entity cards ---------------------------------------------------------------------------------------------

def _runs(key: str) -> List[str]:
    """The query's key and every run of its words (of the first MAX_QUERY_WORDS), each of 2+ characters."""
    words = key.split()[:MAX_QUERY_WORDS]
    runs = {" ".join(words[i:j]) for i in range(len(words)) for j in range(i + 1, len(words) + 1)}
    runs.add(key)
    return sorted(r for r in runs if len(r) >= 2)


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def entity_cards(cur: Cursor, q: str, limit: int = ENTITY_CARDS) -> List[Dict[str, Any]]:
    """Up to `limit` entities the query names (its key, a run of its words, or a prefix of 3+ letters of a name or an
    alias), each shown as the entity it redirects to: {id, name, type, maker, posts, voices, matched}. The whole query
    first, then a run of its words, then a prefix; more posts first."""
    from insight_core.markx import names, schemas
    key = names.key(q)
    if len(key) < 2:
        return []
    runs = _runs(key)
    prefix = _like(key) if len(key) >= PREFIX_MIN else None
    cur.execute(
        """
        WITH RECURSIVE hit AS (
             SELECT e.id, e.key AS matched FROM mx_entities e WHERE e.key = ANY(%(runs)s)
             UNION ALL SELECT a.entity_id, a.key FROM mx_entity_aliases a WHERE a.key = ANY(%(runs)s)
             UNION ALL SELECT e.id, e.key FROM mx_entities e WHERE %(prefix)s::text IS NOT NULL AND e.key LIKE %(prefix)s
             UNION ALL SELECT a.entity_id, a.key FROM mx_entity_aliases a
              WHERE %(prefix)s::text IS NOT NULL AND a.key LIKE %(prefix)s
        ), up(start, id, depth) AS (
             SELECT DISTINCT id, id, 0 FROM hit
             UNION ALL
             SELECT up.start, r.to_id, up.depth + 1 FROM up
               JOIN mx_entity_redirects r ON r.from_id = up.id AND r.undone_at IS NULL
              WHERE up.depth < 20
        ), root AS (
             SELECT DISTINCT ON (start) start, id FROM up ORDER BY start, depth DESC
        ), scored AS (
             SELECT root.id, min(CASE WHEN hit.matched = %(key)s THEN 0 WHEN hit.matched = ANY(%(runs)s) THEN 1 ELSE 2 END)
                    AS how, min(hit.matched) AS matched
               FROM hit JOIN root ON root.start = hit.id GROUP BY root.id
        ), members(root, id, depth) AS (
             SELECT id, id, 0 FROM scored
             UNION ALL
             SELECT members.root, r.from_id, members.depth + 1 FROM members
               JOIN mx_entity_redirects r ON r.to_id = members.id AND r.undone_at IS NULL
              WHERE members.depth < 20
        ), counts AS (
             SELECT mb.root, count(DISTINCT mm.post_id) AS posts, count(DISTINCT p.source_id) AS voices
               FROM (SELECT DISTINCT root, id FROM members) mb
               JOIN mx_mentions_now mm ON mm.entity_id = mb.id
               JOIN posts p ON p.id = mm.post_id
              GROUP BY mb.root
        )
        SELECT e.id::text, e.name, e.type, COALESCE(e.maker, pe.name), COALESCE(c.posts, 0), COALESCE(c.voices, 0),
               s.matched
          FROM scored s
          JOIN mx_entities e ON e.id = s.id
          LEFT JOIN mx_entities pe ON pe.id = e.parent AND e.level IN ('family', 'thing')
          LEFT JOIN counts c ON c.root = s.id
         WHERE e.status <> 'not_entity'
         ORDER BY s.how, COALESCE(c.posts, 0) DESC, e.name, e.id
         LIMIT %(limit)s
        """,
        {"runs": runs, "prefix": prefix, "key": key, "limit": limit},
        prepare=False,
    )
    return [{"id": eid, "name": name, "type": schemas.entity_type(type_), "maker": maker, "posts": int(posts),
             "voices": int(voices), "matched": matched}
            for eid, name, type_, maker, posts, voices, matched in cur.fetchall()]
