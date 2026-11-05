"""Mark X Shadow's storage (issue 0086 A, migration 0066): every insert and read of the mx_* tables.

Each function takes an open cursor and leaves the transaction to its caller (one batch, one
transaction). Ids are uuids; rows come back as dicts.

The rules the tables keep (0086, the build plan's corrections):
  - **Keyed by posts and content, never by a Mark IX story id.** A task is unique per
    (kind, guide, input_hash), and input_hash is the sha256 of the input alone, so a question built
    from the same content is asked once whatever the subject ids passed with it.
  - **Keep everything.** Nothing here deletes. A membership or connection that changes is closed
    with valid_to (`close_membership`, `close_connection`) and a new one opened; a guide is never
    edited (a changed guide is a new id); a second answer to an answered task is a call that changes
    nothing; a reading or a post's mentions under one guide are written once.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from psycopg import Cursor

LEASE_MINUTES = 30     # 0086 C
MAX_ATTEMPTS = 3       # an invalid answer goes back to open; after 3 the task fails (0086 C)
DIMENSIONS = 1024      # halfvec(1024): BGE-M3

Id = Any   # a uuid, or its text


def sha256_hex(text: str) -> str:
    """The hex sha256 of `text` in UTF-8: a guide's sha256 and a task's input_hash (the tables check it)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def _rows(cur: Cursor) -> List[Dict[str, Any]]:
    names = [d.name for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _one(cur: Cursor) -> Optional[Dict[str, Any]]:
    rows = _rows(cur)
    return rows[0] if rows else None


# ---- guides ---------------------------------------------------------------------------------------

def put_guide(cur: Cursor, guide_id: str, kind: str, body: str, schema: Optional[dict] = None) -> str:
    """Load a guide (at start, every time): its sha256. The same id with another body is refused
    (ValueError): a changed guide is a new id, never an edit."""
    sha = sha256_hex(body)
    cur.execute("INSERT INTO mx_guides (id, kind, sha256, body, schema) VALUES (%s, %s, %s, %s, %s::jsonb) "
                "ON CONFLICT (id) DO NOTHING", (guide_id, kind, sha, body, _json(schema)))
    if cur.rowcount == 0:
        cur.execute("SELECT kind, sha256 FROM mx_guides WHERE id = %s", (guide_id,))
        stored_kind, stored_sha = cur.fetchone()
        if (stored_kind, stored_sha) != (kind, sha):
            raise ValueError(f"guide {guide_id} is stored with another body or kind: a changed guide is a new id")
    return sha


def guides(cur: Cursor, ids: Optional[Sequence[str]] = None) -> Dict[str, Dict[str, Any]]:
    """{id: {kind, sha256, body, schema, created_at}}, of `ids` or every guide."""
    if ids is None:
        cur.execute("SELECT * FROM mx_guides ORDER BY id")
    else:
        cur.execute("SELECT * FROM mx_guides WHERE id = ANY(%s) ORDER BY id", (list(ids),))
    return {row.pop("id"): row for row in _rows(cur)}


# ---- tasks ----------------------------------------------------------------------------------------

def add_task(cur: Cursor, *, kind: str, guide: str, subject_kind: str, input: str, a: Id = None, b: Id = None,
             day: Optional[date] = None, priority: int = 0) -> Tuple[UUID, bool]:
    """A question: (its id, whether it is new). The same (kind, guide, input) is one task, whatever
    `a`, `b` and `priority` say: the existing one is returned unchanged."""
    input_hash = sha256_hex(input)
    cur.execute("""INSERT INTO mx_tasks (kind, guide, subject_kind, a, b, day, input, input_hash, priority)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (kind, guide, input_hash) DO NOTHING RETURNING id""",
                (kind, guide, subject_kind, a, b, day, input, input_hash, priority))
    row = cur.fetchone()
    if row:
        return row[0], True
    cur.execute("SELECT id FROM mx_tasks WHERE kind = %s AND guide = %s AND input_hash = %s", (kind, guide, input_hash))
    return cur.fetchone()[0], False


def get_task(cur: Cursor, task_id: Id) -> Optional[Dict[str, Any]]:
    cur.execute("SELECT * FROM mx_tasks WHERE id = %s", (task_id,))
    return _one(cur)


def task_for(cur: Cursor, *, kind: str, guide: str, input: str) -> Optional[Dict[str, Any]]:
    """The task already asking this question, if any."""
    cur.execute("SELECT * FROM mx_tasks WHERE kind = %s AND guide = %s AND input_hash = %s",
                (kind, guide, sha256_hex(input)))
    return _one(cur)


def lease_tasks(cur: Cursor, *, kinds: Sequence[str], limit: int, worker: str,
                minutes: int = LEASE_MINUTES) -> List[Dict[str, Any]]:
    """Lease up to `limit` open tasks of `kinds` (and leased ones whose lease ran out) to `worker` for
    `minutes`, by priority then age: [{id, kind, guide, input, lease_until}] in that order. Rows another
    transaction is leasing are skipped, never waited on."""
    cur.execute("""WITH picked AS (
                     SELECT id FROM mx_tasks
                      WHERE kind = ANY(%s) AND (status = 'open' OR (status = 'leased' AND lease_until < now()))
                      ORDER BY priority, created_at, id
                      LIMIT %s FOR UPDATE SKIP LOCKED)
                   UPDATE mx_tasks t SET status = 'leased', leased_by = %s,
                          lease_until = now() + make_interval(mins => %s)
                     FROM picked WHERE t.id = picked.id
                   RETURNING t.id, t.kind, t.guide, t.input, t.lease_until, t.priority, t.created_at""",
                (list(kinds), limit, worker, minutes))
    rows = sorted(_rows(cur), key=lambda r: (r["priority"], r["created_at"], str(r["id"])))
    return [{k: r[k] for k in ("id", "kind", "guide", "input", "lease_until")} for r in rows]


def release_tasks(cur: Cursor, worker: str) -> int:
    """Hand back `worker`'s leased tasks (POST /api/markx/release, a worker that stops): how many."""
    cur.execute("UPDATE mx_tasks SET status = 'open', lease_until = NULL, leased_by = NULL "
                "WHERE status = 'leased' AND leased_by = %s", (worker,))
    return cur.rowcount


def expire_leases(cur: Cursor) -> int:
    """Leases past their end back to open: how many (0086 Safety 5: no task stays leased past its lease)."""
    cur.execute("UPDATE mx_tasks SET status = 'open', lease_until = NULL, leased_by = NULL "
                "WHERE status = 'leased' AND lease_until < now()")
    return cur.rowcount


def answer_task(cur: Cursor, task_id: Id) -> bool:
    """A valid answer closes its task: False when it was already answered or failed (nothing changes)."""
    cur.execute("UPDATE mx_tasks SET status = 'answered', answered_at = now(), lease_until = NULL, leased_by = NULL "
                "WHERE id = %s AND status IN ('open', 'leased')", (task_id,))
    return cur.rowcount == 1


def fail_attempt(cur: Cursor, task_id: Id, error: str, max_attempts: int = MAX_ATTEMPTS) -> Optional[str]:
    """An invalid answer: the task back to open with its error, or failed at its `max_attempts`-th.
    Its status after, or None when it was already answered or failed (nothing changes)."""
    cur.execute("""UPDATE mx_tasks SET attempts = attempts + 1, last_error = %s, lease_until = NULL, leased_by = NULL,
                          status = CASE WHEN attempts + 1 >= %s THEN 'failed' ELSE 'open' END
                    WHERE id = %s AND status IN ('open', 'leased') RETURNING status""", (error, max_attempts, task_id))
    row = cur.fetchone()
    return row[0] if row else None


def queue_counts(cur: Cursor) -> Dict[str, Dict[str, int]]:
    """{kind: {status: tasks}} (GET /api/markx/status)."""
    cur.execute("SELECT kind, status, count(*) FROM mx_tasks GROUP BY kind, status ORDER BY kind, status")
    out: Dict[str, Dict[str, int]] = {}
    for kind, status, n in cur.fetchall():
        out.setdefault(kind, {})[status] = n
    return out


# ---- calls ----------------------------------------------------------------------------------------

def add_call(cur: Cursor, *, task_id: Id, executor: str, model: str, valid: bool, answer: Any,
             error: Optional[str] = None, tokens_in: Optional[int] = None, tokens_out: Optional[int] = None,
             ms: Optional[int] = None, cost_usd: Optional[float] = None) -> UUID:
    """One answer from one model, stored valid or not: its id."""
    cur.execute("""INSERT INTO mx_calls (task_id, executor, model, valid, error, tokens_in, tokens_out, ms, cost_usd, answer)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING id""",
                (task_id, executor, model, valid, error, tokens_in, tokens_out, ms, cost_usd, _json(answer)))
    return cur.fetchone()[0]


def calls(cur: Cursor, task_id: Id) -> List[Dict[str, Any]]:
    """A task's calls, oldest first."""
    # created_at is its transaction's time; calls are never updated, so ctid keeps one transaction's in insert order
    cur.execute("SELECT * FROM mx_calls WHERE task_id = %s ORDER BY created_at, ctid", (task_id,))
    return _rows(cur)


def valid_call(cur: Cursor, task_id: Id) -> Optional[Dict[str, Any]]:
    """The task's first valid call (the answer that counts), if any."""
    cur.execute("SELECT * FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at, ctid LIMIT 1", (task_id,))
    return _one(cur)


# ---- readings and mentions ------------------------------------------------------------------------

def add_reading(cur: Cursor, *, post_id: Id, guide: str, call_id: Id, kind: Optional[str], events: Optional[str],
                lang: Optional[str], headline: Optional[str], reading: dict) -> bool:
    """A post's reading under `guide`: False when it already has one (the first stays)."""
    cur.execute("""INSERT INTO mx_readings (post_id, guide, call_id, kind, events, lang, headline, reading)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb) ON CONFLICT (post_id, guide) DO NOTHING""",
                (post_id, guide, call_id, kind, events, lang, headline, _json(reading)))
    return cur.rowcount == 1


def readings(cur: Cursor, post_ids: Iterable[Id], guide: str) -> Dict[UUID, Dict[str, Any]]:
    """{post_id: reading row} for the posts read under `guide`."""
    cur.execute("SELECT * FROM mx_readings WHERE post_id = ANY(%s::uuid[]) AND guide = %s",
                ([str(p) for p in post_ids], guide))
    return {row["post_id"]: row for row in _rows(cur)}


MENTION_FIELDS = ("span", "name", "name_key", "type", "role", "maker", "family", "version", "variant", "size", "build")


def add_mentions(cur: Cursor, *, post_id: Id, guide: str, call_id: Id, mentions: Sequence[dict]) -> int:
    """A post's entities under `guide`, numbered in their order (n from 0): how many were written. A
    post's mentions under one guide are written once: a later call adds none."""
    cur.execute("SELECT 1 FROM mx_mentions WHERE post_id = %s AND guide = %s LIMIT 1", (post_id, guide))
    if cur.fetchone():
        return 0
    rows = [(post_id, guide, n, call_id, *(m.get(f) for f in MENTION_FIELDS)) for n, m in enumerate(mentions)]
    if rows:
        cur.executemany(f"INSERT INTO mx_mentions (post_id, guide, n, call_id, {', '.join(MENTION_FIELDS)}) "
                        f"VALUES ({', '.join(['%s'] * (4 + len(MENTION_FIELDS)))}) ON CONFLICT DO NOTHING", rows)
    return len(rows)


def mentions(cur: Cursor, post_id: Id, guide: Optional[str] = None) -> List[Dict[str, Any]]:
    if guide is None:
        cur.execute("SELECT * FROM mx_mentions WHERE post_id = %s ORDER BY guide, n", (post_id,))
    else:
        cur.execute("SELECT * FROM mx_mentions WHERE post_id = %s AND guide = %s ORDER BY n", (post_id, guide))
    return _rows(cur)


def posts_naming(cur: Cursor, name_key: str, *, version: Optional[str] = None, role: Optional[str] = None,
                 guide: Optional[str] = None) -> List[UUID]:
    """The posts that name `name_key` (with this exact version, role, guide when given), in id order."""
    where, params = ["name_key = %s"], [name_key]
    for column, value in (("version", version), ("role", role), ("guide", guide)):
        if value is not None:
            where.append(f"{column} = %s")
            params.append(value)
    cur.execute(f"SELECT DISTINCT post_id FROM mx_mentions WHERE {' AND '.join(where)} ORDER BY post_id", params)
    return [r[0] for r in cur.fetchall()]


# ---- embeddings and candidates ---------------------------------------------------------------------

def vector_text(vector: Sequence[float]) -> str:
    """A vector as pgvector's text ('[0.1,0.2,…]'), checked for its 1,024 dimensions."""
    if len(vector) != DIMENSIONS:
        raise ValueError(f"an embedding has {DIMENSIONS} dimensions, not {len(vector)}")
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def put_embedding(cur: Cursor, *, post_id: Id, model: str, text_hash: str, vector: Sequence[float],
                  model_sha256: Optional[str] = None) -> bool:
    """A post's vector under `model` (from the embedder build `model_sha256`): False when it is already
    stored for this text and build; a changed text replaces the vector (a derived value, recomputed from
    the post). Refusing a build other than the stored one is the caller's (`embedding_builds`)."""
    cur.execute("""INSERT INTO mx_embeddings (post_id, model, model_sha256, text_hash, v) VALUES (%s, %s, %s, %s, %s::halfvec)
                   ON CONFLICT (post_id, model) DO UPDATE
                      SET text_hash = EXCLUDED.text_hash, model_sha256 = EXCLUDED.model_sha256, v = EXCLUDED.v
                   WHERE (mx_embeddings.text_hash, mx_embeddings.model_sha256)
                         IS DISTINCT FROM (EXCLUDED.text_hash, EXCLUDED.model_sha256)""",
                (post_id, model, model_sha256, text_hash, vector_text(vector)))
    return cur.rowcount == 1


def embedding_builds(cur: Cursor, model: str) -> Dict[Optional[str], int]:
    """{model_sha256: vectors} stored under `model` (one build per database: build plan corrections 6)."""
    cur.execute("SELECT model_sha256, count(*) FROM mx_embeddings WHERE model = %s GROUP BY 1", (model,))
    return dict(cur.fetchall())


def embedding_hashes(cur: Cursor, post_ids: Iterable[Id], model: str) -> Dict[UUID, str]:
    """{post_id: text_hash} of the posts embedded under `model` (what a run needn't embed again)."""
    cur.execute("SELECT post_id, text_hash FROM mx_embeddings WHERE post_id = ANY(%s::uuid[]) AND model = %s",
                ([str(p) for p in post_ids], model))
    return dict(cur.fetchall())


def embedding(cur: Cursor, post_id: Id, model: str) -> Optional[List[float]]:
    cur.execute("SELECT v::text FROM mx_embeddings WHERE post_id = %s AND model = %s", (post_id, model))
    row = cur.fetchone()
    return json.loads(row[0]) if row else None


def nearest(cur: Cursor, vector: Sequence[float], *, model: str, limit: int = 10,
            exclude: Iterable[Id] = ()) -> List[Tuple[UUID, float]]:
    """The `limit` posts nearest `vector` under `model`, by cosine distance (1 - cosine), nearest first,
    through the HNSW index."""
    cur.execute("""SELECT post_id, v <=> %s::halfvec AS distance FROM mx_embeddings
                    WHERE model = %s AND NOT (post_id = ANY(%s::uuid[]))
                    ORDER BY v <=> %s::halfvec LIMIT %s""",
                (vector_text(vector), model, [str(p) for p in exclude], vector_text(vector), limit))
    return [(post_id, float(distance)) for post_id, distance in cur.fetchall()]


def add_candidate(cur: Cursor, *, kind: str, a: Id, b: Id, source: str, score: Optional[float]) -> bool:
    """A pair worth a question, written once per source: False when this source already has it."""
    cur.execute("INSERT INTO mx_candidates (kind, a, b, source, score) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING", (kind, a, b, source, score))
    return cur.rowcount == 1


def candidates(cur: Cursor, kind: str, *, source: Optional[str] = None, post: Id = None,
               since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The candidate pairs of `kind` (of one source, touching one post or story, written since), oldest first."""
    where, params = ["kind = %s"], [kind]
    if source is not None:
        where.append("source = %s")
        params.append(source)
    if post is not None:
        where.append("(a = %s OR b = %s)")
        params += [post, post]
    if since is not None:
        where.append("created_at >= %s")
        params.append(since)
    cur.execute(f"SELECT * FROM mx_candidates WHERE {' AND '.join(where)} ORDER BY created_at, a, b, source", params)
    return _rows(cur)


# ---- runs and stories -----------------------------------------------------------------------------

def start_run(cur: Cursor, *, code_version: Optional[str], config: dict) -> UUID:
    cur.execute("INSERT INTO mx_runs (code_version, config) VALUES (%s, %s::jsonb) RETURNING id",
                (code_version, _json(config)))
    return cur.fetchone()[0]


def finish_run(cur: Cursor, run_id: Id, *, counts: dict) -> None:
    cur.execute("UPDATE mx_runs SET finished_at = clock_timestamp(), counts = %s::jsonb WHERE id = %s",
                (_json(counts), run_id))


def last_run(cur: Cursor) -> Optional[Dict[str, Any]]:
    cur.execute("SELECT * FROM mx_runs ORDER BY started_at DESC, ctid DESC LIMIT 1")
    return _one(cur)


def add_story(cur: Cursor, *, first_at: Optional[datetime], run_id: Id, headline: Optional[str] = None,
              headline_call: Id = None, card_call: Id = None) -> UUID:
    cur.execute("INSERT INTO mx_stories (first_at, created_run, headline, headline_call, card_call) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id", (first_at, run_id, headline, headline_call, card_call))
    return cur.fetchone()[0]


def get_story(cur: Cursor, story_id: Id) -> Optional[Dict[str, Any]]:
    cur.execute("SELECT * FROM mx_stories WHERE id = %s", (story_id,))
    return _one(cur)


def merge_story(cur: Cursor, story_id: Id, *, into: Id) -> None:
    """`story_id` merged into `into`: the row stays, pointing at it (its memberships are closed by the caller)."""
    cur.execute("UPDATE mx_stories SET merged_into = %s WHERE id = %s", (into, story_id))


def set_story_headline(cur: Cursor, story_id: Id, *, headline: Optional[str], headline_call: Id = None) -> None:
    cur.execute("UPDATE mx_stories SET headline = %s, headline_call = %s WHERE id = %s",
                (headline, headline_call, story_id))


def set_story_card(cur: Cursor, story_id: Id, card_call: Id) -> None:
    cur.execute("UPDATE mx_stories SET card_call = %s WHERE id = %s", (card_call, story_id))


# ---- memberships (valid_to: null = current) -------------------------------------------------------

def open_membership(cur: Cursor, *, story_id: Id, post_id: Id, role: str, reason: str, run_id: Id,
                    p: Optional[float] = None, call_id: Id = None, at: Optional[datetime] = None) -> bool:
    """A post in a Mark X story from now (or `at`): False when it is already current there (one current
    membership per story and post; close it first to change its role)."""
    cur.execute("""INSERT INTO mx_story_posts (story_id, post_id, role, reason, p, call_id, run_id, valid_from)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()))
                   ON CONFLICT (story_id, post_id) WHERE valid_to IS NULL DO NOTHING""",
                (story_id, post_id, role, reason, p, call_id, run_id, at))
    return cur.rowcount == 1


def close_membership(cur: Cursor, *, story_id: Id, post_id: Id, at: Optional[datetime] = None) -> bool:
    """Close the post's current membership of the story at now (or `at`): the row stays. False when
    nothing was current."""
    cur.execute("UPDATE mx_story_posts SET valid_to = COALESCE(%s, now()) "
                "WHERE story_id = %s AND post_id = %s AND valid_to IS NULL", (at, story_id, post_id))
    return cur.rowcount == 1


def current_members(cur: Cursor, story_id: Id) -> List[Dict[str, Any]]:
    cur.execute("SELECT * FROM mx_story_posts WHERE story_id = %s AND valid_to IS NULL ORDER BY valid_from, post_id",
                (story_id,))
    return _rows(cur)


def stories_of_post(cur: Cursor, post_id: Id) -> List[UUID]:
    """The Mark X stories the post is current in (a post may be in several: 0074's edge model)."""
    cur.execute("SELECT story_id FROM mx_story_posts WHERE post_id = %s AND valid_to IS NULL ORDER BY valid_from, story_id",
                (post_id,))
    return [r[0] for r in cur.fetchall()]


def membership_history(cur: Cursor, story_id: Id, post_id: Id) -> List[Dict[str, Any]]:
    """Every membership the post has had in the story, closed ones included, oldest first."""
    cur.execute("SELECT * FROM mx_story_posts WHERE story_id = %s AND post_id = %s "
                "ORDER BY valid_from, valid_to NULLS LAST", (story_id, post_id))
    return _rows(cur)


# ---- connections (valid_to: null = current) -------------------------------------------------------

def open_connection(cur: Cursor, *, a_kind: str, a: Id, b_kind: str, b: Id, relation: str, run_id: Id,
                    p: Optional[float] = None, call_id: Id = None, rule: Optional[str] = None,
                    evidence: Optional[dict] = None, at: Optional[datetime] = None) -> bool:
    """A typed connection from now (or `at`), naming a call or a rule: False when the same one
    (a, b, relation) is already current."""
    cur.execute("""INSERT INTO mx_connections (a_kind, a, b_kind, b, relation, p, call_id, rule, run_id, evidence, valid_from)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, COALESCE(%s, now()))
                   ON CONFLICT (a_kind, a, b_kind, b, relation) WHERE valid_to IS NULL DO NOTHING""",
                (a_kind, a, b_kind, b, relation, p, call_id, rule, run_id, _json(evidence), at))
    return cur.rowcount == 1


def close_connection(cur: Cursor, *, a_kind: str, a: Id, b_kind: str, b: Id, relation: str,
                     at: Optional[datetime] = None) -> bool:
    """Close the current connection at now (or `at`): the row stays. False when nothing was current."""
    cur.execute("""UPDATE mx_connections SET valid_to = COALESCE(%s, now())
                    WHERE a_kind = %s AND a = %s AND b_kind = %s AND b = %s AND relation = %s AND valid_to IS NULL""",
                (at, a_kind, a, b_kind, b, relation))
    return cur.rowcount == 1


def current_connections(cur: Cursor, kind: str, thing: Id) -> List[Dict[str, Any]]:
    """The current connections touching a post or story, either end."""
    cur.execute("""SELECT * FROM mx_connections WHERE valid_to IS NULL
                     AND ((a_kind = %s AND a = %s) OR (b_kind = %s AND b = %s))
                   ORDER BY valid_from, relation""", (kind, thing, kind, thing))
    return _rows(cur)


# ---- News, briefings, labels ----------------------------------------------------------------------

NEWS_FIELDS = ("id", "first_at", "voices", "reports", "shares", "mentions", "score", "tag")


def add_news_rows(cur: Cursor, run_id: Id, rows: Sequence[dict]) -> int:
    """A run's Mark X News rows (Mark IX's news_stories shape, its news_posts rows in `posts`): how many."""
    params = [(run_id, *(r.get(f) for f in NEWS_FIELDS), _json(r.get("posts") or [])) for r in rows]
    if params:
        cur.executemany(f"INSERT INTO mx_news (run_id, {', '.join(NEWS_FIELDS)}, posts) "
                        f"VALUES (%s, {', '.join(['%s'] * len(NEWS_FIELDS))}, %s::jsonb)", params)
    return len(params)


def news_rows(cur: Cursor, run_id: Id) -> List[Dict[str, Any]]:
    """A run's News rows, highest score first."""
    cur.execute("SELECT * FROM mx_news WHERE run_id = %s ORDER BY score DESC, first_at DESC, id", (run_id,))
    return _rows(cur)


def add_briefing(cur: Cursor, *, day: date, call_id: Id, lines: Sequence[dict]) -> None:
    cur.execute("INSERT INTO mx_briefings (day, call_id, lines) VALUES (%s, %s, %s::jsonb) ON CONFLICT DO NOTHING",
                (day, call_id, _json(list(lines))))


def briefings(cur: Cursor, day: date) -> List[Dict[str, Any]]:
    """A day's briefings, newest first."""
    cur.execute("SELECT * FROM mx_briefings WHERE day = %s ORDER BY created_at DESC, ctid DESC", (day,))
    return _rows(cur)


def add_label(cur: Cursor, *, item_kind: str, a: Id, b: Id, answer: str, split: Optional[str] = None,
              note: Optional[str] = None, labeller: str = "owner") -> UUID:
    cur.execute("INSERT INTO mx_labels (item_kind, a, b, answer, labeller, split, note) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id", (item_kind, a, b, answer, labeller, split, note))
    return cur.fetchone()[0]


def labels(cur: Cursor, item_kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """The labels (of one kind), oldest first."""
    if item_kind is None:
        cur.execute("SELECT * FROM mx_labels ORDER BY created_at, ctid")
    else:
        cur.execute("SELECT * FROM mx_labels WHERE item_kind = %s ORDER BY created_at, ctid", (item_kind,))
    return _rows(cur)
