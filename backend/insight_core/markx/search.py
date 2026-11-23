"""Mark X's English layer in search, its entity cards and search by meaning (issue 0139).

`mx_post_search` holds one row a post Mark X answered: tsvectors of its current reading and current entity set
(`vector_ix` under the posts' own index rule, so a query's words may split between the post's text and Mark X's
English). Written when an answer is stored (`refresh`) and by a resumable fill (`fill_batch`, `pending`). Search reads
it only while Mark X is on (`enabled`); Mark IX's search is unchanged. `entity_cards` and `entity_first_posts` read
the entities a query names, through the merges, a name and its version naming that version however it is spelled
(`query_version`, `_VERSIONS`). `meaning_posts` adds the query's nearest posts by vector when switched on.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional

from insight_core.markx import reading5

from psycopg import Cursor

from insight_core.utils import voice

# The rule that makes a row: a change to what goes in the vector raises it, and the fill remakes every row.
VERSION = 2
FILL_BATCH = 500
ENTITY_CARDS = 3
PREFIX_MIN = 3          # a prefix matches from 3 letters
MAX_QUERY_WORDS = 8     # runs of words are read from the first 8
CARD_MIN_POSTS = 2      # a card needs this many posts, or a subject or actor role
LEAD_ROLES = ("subject", "actor")
# A version number, as migration 0095's search_version_number reads a query's lexeme (5.2, 3.8, 4o, 70b).
VERSION_NUMBER = re.compile(r"^\d+((\.\d+)+[a-z]{0,2}|[a-z]{1,2})$")
LETTERS = re.compile(r"^[^\W\d_]+$")

# each post's current reading and entity set as its row; an empty vector when nothing is left to read, so the fill
# never asks for a post again
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
         FROM mx_readings x WHERE x.post_id = ids.id AND {RANK} IS NOT NULL
        ORDER BY {RANK} LIMIT 1) r ON TRUE
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
_WRITE = _WRITE.replace("{RANK}", reading5.rank_sql("x.guide"))   # the preferred reading

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
    """For a name and its version ("kimi 3.1"), that version of the family however its entities are spelled: `vname`
    the name, `version`, `vprefix` a key starting with the name, `vre` a key that is the name, a version's letter
    prefix or not, the version, then any words ("kimi k 3.1 pro"). All None for a query that names no version."""
    version = query_version(key)
    if not version:
        return {"vname": None, "version": None, "vprefix": None, "vre": None}
    name = key[: -len(version)].strip()
    return {"vname": name, "version": version, "vprefix": _like(name + " "),
            "vre": "^" + re.escape(name) + "( [a-z]{1,2})? " + re.escape(version) + "( |$)"}


# the entities that are the query's version of the family its name names: the family's versions, variants and
# checkpoints (up to three levels down) whose version is the query's once a letter prefix is dropped ("K3.1" = "3.1")
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

# the entities a query names, as their current targets (through the redirects; never a not-entity), and every entity
# merged into them (`members`); `%(suffix)s` only for a name and its version (else NULL)
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
    """The posts whose current mentions hold, as subject or actor, the entity the whole query names (its key or
    alias; for a name and its version also a key ending with it as words and that version of the family however
    spelled). Read through the merges; a mention not linked yet counts by its own name key. [] when none."""
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
    """Up to `limit` entities the query names (its key, a run of its words, or a 3+ letter prefix of a name or alias),
    each shown as the entity it redirects to: {id, name, type, maker, posts, voices, matched}. For a name and its
    version, that version's entities come first (more posts first); then the whole query, a run of its words, a
    prefix; more posts first. A card needs CARD_MIN_POSTS posts or a subject or actor role in a current entity set."""
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
    cards = [{"id": eid, "name": name, "type": schemas.entity_type(type_), "maker": maker, "posts": int(posts),
              "voices": int(voices), "matched": matched}
             for eid, name, type_, maker, posts, voices, matched in cur.fetchall()]
    return with_senses(cur, cards)


def with_senses(cur: Cursor, cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One card a name: each card's `what`, its maker from the facts when it has none, and the other senses of its
    name ("Vexa — terminal app (3) · voice mode (1)"); a card that is another card's sense is folded into it."""
    from insight_core.markx import entity_facts
    facts = entity_facts.read(cur, [c["id"] for c in cards], senses=True)
    if not facts:
        return cards
    out, folded = [], set()
    for c in cards:
        if c["id"] in folded:
            continue
        f = facts.get(c["id"])
        if f is not None:
            c["what"] = f.what
            c["maker"] = c["maker"] or f.maker
            if f.senses:
                c["senses"] = [{"id": c["id"], "what": f.what, "posts": c["posts"]}] + f.senses
                folded |= {s["id"] for s in f.senses}
        out.append(c)
    return out


# ---- search by meaning (issue 0247) ----------------------------------------------------------------------------
# The query's vector comes from the embedder at INSIGHT_EMBEDDER_URL (a query has no task to wait for); no URL, the
# embedder down or slow, or the switch off: the word search alone. The vector is never kept; the nearest posts are an
# exact scan in Postgres, so the API holds no vectors.

MEANING_SWITCH = ("search", "meaning")
MEANING_TIMEOUT = 2.0      # seconds the API waits for the query's vector
MEANING_K = 30             # the nearest posts merged with the word ranking
MEANING_MIN = 0.55         # a post less near than this cosine is no meaning match (measured: 0247)
MEANING_MIN_CHARS = 200    # a post this short is found by its words only (its vector is near everything)
RRF_K = 60                 # reciprocal rank fusion's constant (Cormack et al. 2009)


def embedder_url() -> str:
    return os.getenv("INSIGHT_EMBEDDER_URL", "").strip().rstrip("/")


def meaning_on() -> bool:
    """entity_bands.json `search.meaning` and an embedder configured (INSIGHT_EMBEDDER_URL)."""
    from insight_core.markx import identity
    return bool((identity.bands().get(MEANING_SWITCH[0]) or {}).get(MEANING_SWITCH[1], False)) and bool(embedder_url())


def query_vector(q: str, *, url: Optional[str] = None, timeout: float = MEANING_TIMEOUT) -> Optional[List[float]]:
    """The query's vector scaled to length 1, or None (no embedder, down, slow, or an answer without a vector)."""
    import json
    import math
    import urllib.request
    url = url if url is not None else embedder_url()
    text = " ".join((q or "").split())
    if not url or not text:
        return None
    req = urllib.request.Request(f"{url}/embedding", data=json.dumps({"content": [text]}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = json.loads(res.read())
    except Exception:  # noqa: BLE001 - the embedder down or slow: the word search alone
        return None
    e = body[0] if isinstance(body, list) and body else body
    v = e.get("embedding") if isinstance(e, dict) else None
    if isinstance(v, list) and len(v) == 1 and isinstance(v[0], list):
        v = v[0]
    if not isinstance(v, list) or len(v) != 1024 or not all(isinstance(x, (int, float)) for x in v):
        return None
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm > 0 else None


def nearest_posts(cur: Cursor, vector: List[float], *, limit: int = MEANING_K,
                  floor: float = MEANING_MIN) -> List[str]:
    """The posts whose current vector (embed.MODEL) is nearest the query's, nearest first, at cosine `floor` or more."""
    from insight_core.markx import embed, repo
    # a short text's vector is near every query: a post of fewer than MEANING_MIN_CHARS is found by its words only
    cur.execute("""SELECT n.post_id::text FROM (
                       SELECT e.post_id, e.v <=> %s::halfvec AS d FROM mx_embeddings e
                         JOIN posts p ON p.id = e.post_id
                        WHERE e.model = %s AND length(coalesce(p.content, '')) >= %s
                        ORDER BY d LIMIT %s) n
                   WHERE 1 - n.d >= %s ORDER BY n.d""",
                (repo.vector_text(vector), embed.MODEL, MEANING_MIN_CHARS, limit, floor), prepare=False)
    return [r[0] for r in cur.fetchall()]


def meaning_posts(cur: Cursor, q: str) -> List[str]:
    """The nearest posts to the query by meaning while the switch is on and the embedder answers, else []."""
    if not meaning_on():
        return []
    vector = query_vector(q)
    return nearest_posts(cur, vector) if vector else []
