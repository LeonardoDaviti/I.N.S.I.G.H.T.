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

v10.13.1 (the owner's "fable 5.2"): a query that is a name and its version (`query_version`: its key's last word a
version number, as migration 0095's search_version_number reads it, after a word of letters) names the entities whose
key or alias is the query or ends with it as words ("claude fable 5.2" for "fable 5.2": the version's entity, not the
family's); a card shows them first. A card needs 2+ posts or a subject or actor role in a current entity set: a name
met once in passing gets none. `entity_first_posts(cur, q)`: the posts whose current mentions hold the entity the
whole query names (that version, with one) as subject or actor; best match ranks them above the posts that only match
its words (db/repo_search.py).

v10.13.13: a name and its version also name that version of the family however its entities are spelled
(`_VERSIONS`): the family's versions, variants and checkpoints whose version is the query's less a letter prefix
("Kimi K3.1", "Kimi K3.1 Pro" and an unmerged "Kimi3.1" for "kimi 3.1"), and a key that is the name, a version
letter or not, the version, then any words. Entity first holds all their posts; their cards come first, more posts
first, so an unmerged spelling with one post never stands for the version.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional

from psycopg import Cursor

from insight_core.utils import voice

# The rule that makes a row: a change to what goes in the vector raises it, and the fill remakes every row.
VERSION = 2   # 2: vector_ix, the layer under the posts' index rule (the words split across both)
FILL_BATCH = 500
ENTITY_CARDS = 3
PREFIX_MIN = 3          # a prefix matches from 3 letters
MAX_QUERY_WORDS = 8     # runs of words are read from the first 8
CARD_MIN_POSTS = 2      # a card needs this many posts, or a subject or actor role (v10.13.1)
LEAD_ROLES = ("subject", "actor")
# A version number, as migration 0095's search_version_number reads a query's lexeme (5.2, 3.8, 4o, 70b).
VERSION_NUMBER = re.compile(r"^\d+((\.\d+)+[a-z]{0,2}|[a-z]{1,2})$")
LETTERS = re.compile(r"^[^\W\d_]+$")

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


def query_version(key: str) -> Optional[str]:
    """The version a query's key names after a name (its last word a version number after a word of letters:
    "fable 5.2" -> "5.2", "qwen 3.8" from "Qwen3.8"); None for "fable", "5.2" or "fable 5"."""
    words = key.split()
    if len(words) >= 2 and VERSION_NUMBER.match(words[-1]) and LETTERS.match(words[-2]):
        return words[-1]
    return None


def _suffix(key: str) -> str:
    """LIKE pattern on a reversed key: a key that ends with this one as whole words ("claude fable 5.2" for "fable 5.2"),
    read by the reversed keys' prefix indexes (migration 0095)."""
    return _like((" " + key)[::-1])


def _version_params(key: str) -> Dict[str, Optional[str]]:
    """v10.13.13: for a name and its version ("kimi 3.1"), that version of the family the name names, however its
    entities are spelled: `vname` the name ("kimi"), `version` ("3.1"), `vprefix` a key starting with the name, `vre`
    a key that is the name, a version's letter prefix or not ("kimi k 3.1", from "Kimi K3.1"), the version, then
    any words ("kimi k 3.1 pro"). All None for a query that names no version."""
    version = query_version(key)
    if not version:
        return {"vname": None, "version": None, "vprefix": None, "vre": None}
    name = key[: -len(version)].strip()
    return {"vname": name, "version": version, "vprefix": _like(name + " "),
            "vre": "^" + re.escape(name) + "( [a-z]{1,2})? " + re.escape(version) + "( |$)"}


# v10.13.13: the entities that are the query's version of the family its name names (`versions`, empty for a query
# with no version): an entity the family (its key or alias the name, read through the merges, and every entity merged
# into it) holds as a version, a variant or a checkpoint (`parent`, up to three levels down), whose version is the
# query's once a letter prefix is dropped ("K3.1" = "3.1", as identity's ver_eq reads two versions). "Kimi K3.1",
# "Kimi K3.1 Pro" and an unmerged "Kimi3.1" are all "kimi 3.1": one spelling never stands for the version alone.
_VERSIONS = r"""
WITH RECURSIVE fam AS (
     SELECT e.id FROM mx_entities e WHERE %(vname)s::text IS NOT NULL AND e.key = %(vname)s
     UNION SELECT a.entity_id FROM mx_entity_aliases a WHERE %(vname)s::text IS NOT NULL AND a.key = %(vname)s
), fam_up(start, id, depth) AS (
     SELECT id, id, 0 FROM fam
     UNION ALL
     SELECT fam_up.start, r.to_id, fam_up.depth + 1 FROM fam_up
       JOIN mx_entity_redirects r ON r.from_id = fam_up.id AND r.undone_at IS NULL
      WHERE fam_up.depth < 20
), fam_root AS (
     SELECT DISTINCT ON (start) start, id FROM fam_up ORDER BY start, depth DESC
), fam_members(id, depth) AS (
     SELECT DISTINCT id, 0 FROM fam_root
     UNION ALL
     SELECT r.from_id, fam_members.depth + 1 FROM fam_members
       JOIN mx_entity_redirects r ON r.to_id = fam_members.id AND r.undone_at IS NULL
      WHERE fam_members.depth < 20
), fam_down(id, depth) AS (
     SELECT id, 0 FROM fam_members
     UNION ALL
     SELECT c.id, fam_down.depth + 1 FROM fam_down JOIN mx_entities c ON c.parent = fam_down.id
      WHERE fam_down.depth < 3
), versions AS (
     SELECT DISTINCT e.id, e.key FROM fam_down d JOIN mx_entities e ON e.id = d.id
      WHERE d.depth > 0 AND regexp_replace(lower(btrim(e.version)), '^[[:alpha:]]+([0-9])', '\1') = %(version)s
),
"""

# A name and its version: also a key or alias read by `vre` (from the name's prefix index), and the family's version.
_VERSION_HITS = """
     UNION ALL SELECT e.id{m} FROM mx_entities e
      WHERE %(vre)s::text IS NOT NULL AND e.key LIKE %(vprefix)s AND e.key ~ %(vre)s
     UNION ALL SELECT a.entity_id{am} FROM mx_entity_aliases a
      WHERE %(vre)s::text IS NOT NULL AND a.key LIKE %(vprefix)s AND a.key ~ %(vre)s
     UNION ALL SELECT v.id{vm} FROM versions v
"""

# The entities a query names, as their current targets (through the redirects; never a not-entity), and every entity
# merged into them (`members`): `%(key)s` is the query's key; `%(suffix)s` a key ending with it as words (_suffix, on
# the reversed key), for a name and its version only (else NULL); and that version of the family (_VERSIONS).
_NAMED = _VERSIONS + """
hit AS (
     SELECT e.id FROM mx_entities e WHERE e.key = %(key)s
     UNION ALL SELECT a.entity_id FROM mx_entity_aliases a WHERE a.key = %(key)s
     UNION ALL SELECT e.id FROM mx_entities e WHERE %(suffix)s::text IS NOT NULL AND reverse(e.key) LIKE %(suffix)s
     UNION ALL SELECT a.entity_id FROM mx_entity_aliases a
      WHERE %(suffix)s::text IS NOT NULL AND reverse(a.key) LIKE %(suffix)s
""" + _VERSION_HITS.format(m="", am="", vm="") + """
), up(start, id, depth) AS (
     SELECT DISTINCT id, id, 0 FROM hit
     UNION ALL
     SELECT up.start, r.to_id, up.depth + 1 FROM up
       JOIN mx_entity_redirects r ON r.from_id = up.id AND r.undone_at IS NULL
      WHERE up.depth < 20
), root AS (
     SELECT DISTINCT ON (start) start, id FROM up ORDER BY start, depth DESC
), named AS (
     SELECT DISTINCT root.id FROM root JOIN mx_entities e ON e.id = root.id WHERE e.status <> 'not_entity'
), members(id, depth) AS (
     SELECT id, 0 FROM named
     UNION ALL
     SELECT r.from_id, members.depth + 1 FROM members
       JOIN mx_entity_redirects r ON r.to_id = members.id AND r.undone_at IS NULL
      WHERE members.depth < 20
)
"""


def _plain(q: str) -> bool:
    """A query of words only: no -word, no `or`."""
    return not any(w.startswith("-") or w.lower() == "or" for w in q.split())


def entity_first_posts(cur: Cursor, q: str) -> List[str]:
    """The posts whose current mentions (mx_mentions_now) hold, as subject or actor, the entity the whole query names:
    its key or alias is the query's key; for a name and its version ("fable 5.2"), also a key or alias ending with it
    as words (that version's entity, "Claude Fable 5.2"), and that version of the family however spelled ("Kimi K3.1",
    "Kimi K3.1 Pro", "Kimi3.1" for "kimi 3.1": _VERSIONS, v10.13.13). Read through the merges. A mention identity has
    not linked yet (a post read since its last run) counts by its own name key, by the same rule. [] when the query
    names none."""
    from insight_core.markx import names
    key = names.key(q)
    if len(key) < 2 or not _plain(q):
        return []
    version = query_version(key)
    cur.execute(
        _NAMED + """
        SELECT mm.post_id::text FROM mx_mentions_now mm
         WHERE mm.entity_id IN (SELECT id FROM members) AND mm.role = ANY(%(roles)s)
        UNION
        SELECT mm.post_id::text FROM mx_mentions_now mm
         WHERE mm.entity_id IS NULL AND mm.role = ANY(%(roles)s)
           AND (mm.name_key = %(key)s OR (%(ends)s::text IS NOT NULL AND mm.name_key LIKE %(ends)s)
                OR (%(vre)s::text IS NOT NULL AND mm.name_key LIKE %(vprefix)s AND mm.name_key ~ %(vre)s))
        """,
        {"key": key, "suffix": _suffix(key) if version else None, "ends": "% " + _like(key)[:-1] if version else None,
         "roles": list(LEAD_ROLES), **_version_params(key)},
        prepare=False,
    )
    return [r[0] for r in cur.fetchall()]


def entity_cards(cur: Cursor, q: str, limit: int = ENTITY_CARDS) -> List[Dict[str, Any]]:
    """Up to `limit` entities the query names (its key, a run of its words, or a prefix of 3+ letters of a name or an
    alias), each shown as the entity it redirects to: {id, name, type, maker, posts, voices, matched}. For a name and
    its version, an entity whose key or alias is the query or ends with it as words (the version's, "claude fable 5.2"
    for "fable 5.2") or that version of the family however spelled (_VERSIONS: "Kimi K3.1 Pro" and an unmerged
    "Kimi3.1" for "kimi 3.1", the one with more posts first, v10.13.13) comes first; then the whole query, a run of
    its words, a prefix; more posts first. A card needs
    CARD_MIN_POSTS posts or a subject or actor role in a current entity set (v10.13.1)."""
    from insight_core.markx import names, schemas
    key = names.key(q)
    if len(key) < 2:
        return []
    runs = _runs(key)
    prefix = _like(key) if len(key) >= PREFIX_MIN else None
    suffix = _suffix(key) if query_version(key) else None
    cur.execute(
        _VERSIONS + """
        hit AS (
             SELECT e.id, e.key AS matched, FALSE AS v FROM mx_entities e WHERE e.key = ANY(%(runs)s)
             UNION ALL SELECT a.entity_id, a.key, FALSE FROM mx_entity_aliases a WHERE a.key = ANY(%(runs)s)
             UNION ALL SELECT e.id, e.key, FALSE FROM mx_entities e WHERE %(prefix)s::text IS NOT NULL AND e.key LIKE %(prefix)s
             UNION ALL SELECT a.entity_id, a.key, FALSE FROM mx_entity_aliases a
              WHERE %(prefix)s::text IS NOT NULL AND a.key LIKE %(prefix)s
             UNION ALL SELECT e.id, e.key, FALSE FROM mx_entities e WHERE %(suffix)s::text IS NOT NULL AND reverse(e.key) LIKE %(suffix)s
             UNION ALL SELECT a.entity_id, a.key, FALSE FROM mx_entity_aliases a
              WHERE %(suffix)s::text IS NOT NULL AND reverse(a.key) LIKE %(suffix)s
        """ + _VERSION_HITS.format(m=", e.key, TRUE", am=", a.key, TRUE", vm=", v.key, TRUE") + """
        ), up(start, id, depth) AS (
             SELECT DISTINCT id, id, 0 FROM hit
             UNION ALL
             SELECT up.start, r.to_id, up.depth + 1 FROM up
               JOIN mx_entity_redirects r ON r.from_id = up.id AND r.undone_at IS NULL
              WHERE up.depth < 20
        ), root AS (
             SELECT DISTINCT ON (start) start, id FROM up ORDER BY start, depth DESC
        ), scored AS (
             SELECT root.id, min(CASE WHEN hit.v THEN 0
                                      WHEN %(suffix)s::text IS NOT NULL
                                           AND (hit.matched = %(key)s OR reverse(hit.matched) LIKE %(suffix)s) THEN 0
                                      WHEN hit.matched = %(key)s THEN 1
                                      WHEN hit.matched = ANY(%(runs)s) THEN 2 ELSE 3 END)
                    AS how, min(hit.matched) AS matched
               FROM hit JOIN root ON root.start = hit.id GROUP BY root.id
        ), members(root, id, depth) AS (
             SELECT id, id, 0 FROM scored
             UNION ALL
             SELECT members.root, r.from_id, members.depth + 1 FROM members
               JOIN mx_entity_redirects r ON r.to_id = members.id AND r.undone_at IS NULL
              WHERE members.depth < 20
        ), counts AS (
             SELECT mb.root, count(DISTINCT mm.post_id) AS posts,
                    """ + voice.count_sql("p.source_id", "ps.platform") + """ AS voices,
                    bool_or(mm.role = ANY(%(roles)s)) AS lead
               FROM (SELECT DISTINCT root, id FROM members) mb
               JOIN mx_mentions_now mm ON mm.entity_id = mb.id
               JOIN posts p ON p.id = mm.post_id JOIN sources ps ON ps.id = p.source_id
              GROUP BY mb.root
        )
        SELECT e.id::text, COALESCE(e.shown_name, e.name), COALESCE(e.shown_type, e.type),   -- 0164: as shown
               COALESCE(e.maker, pe.shown_name, pe.name), COALESCE(c.posts, 0), COALESCE(c.voices, 0),
               s.matched
          FROM scored s
          JOIN mx_entities e ON e.id = s.id
          LEFT JOIN mx_entities pe ON pe.id = e.parent AND e.level IN ('family', 'thing')
          LEFT JOIN counts c ON c.root = s.id
         WHERE e.status <> 'not_entity' AND (COALESCE(c.posts, 0) >= %(min_posts)s OR COALESCE(c.lead, FALSE))
         ORDER BY s.how, COALESCE(c.posts, 0) DESC, e.name, e.id
         LIMIT %(limit)s
        """,
        {"runs": runs, "prefix": prefix, "suffix": suffix, "key": key, "limit": limit,
         "roles": list(LEAD_ROLES), "min_posts": CARD_MIN_POSTS, **_version_params(key)},
        prepare=False,
    )
    return [{"id": eid, "name": name, "type": schemas.entity_type(type_), "maker": maker, "posts": int(posts),
             "voices": int(voices), "matched": matched}
            for eid, name, type_, maker, posts, voices, matched in cur.fetchall()]
