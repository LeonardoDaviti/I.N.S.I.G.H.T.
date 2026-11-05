"""Mark X Shadow's embeddings (issue 0086 B, the build plan's corrections 6): `embed` tasks, and the vectors' check
and store.

The embedder runs on the owner's device, not on the server: an `embed` task is leased like every other kind
(GET /api/markx/work?kinds=embed), the worker (scripts/markx-worker, --embedder) embeds its input with a local
`llama-server --embedding --pooling cls` (BGE-M3), and posts the vectors to POST /api/markx/embeddings. The server
never embeds anything in Shadow: it plans the tasks, checks and stores the vectors, and finds the candidates
(markx/candidates.py) when they arrive.

  - **The text** (`embed_text`, markx embed text v1): markx text v1's title and first 1,500 characters of the text
    (tasks.load_posts, read from post_parts), the title left out when the text starts with it, web addresses
    removed and spaces squashed, as the prototype embedded its posts (its step 1; it cut at 1,200 characters,
    0086 B says 1,500). The task's input is that text, so two posts with the same text are one task: the second
    post's vector is the first's, copied when the planner meets it again (`plan`).
  - **The vector:** 1,024 little-endian float16, base64 (2 KB a post, not ~9 KB of JSON numbers), scaled to
    length 1 by the worker. The server decodes it, checks its length, its numbers and its norm, and stores it in
    mx_embeddings (halfvec, so float16 is stored as sent) with text_hash = the task's input hash.
  - **One build per database:** every vector names its model (`bge-m3`) and the GGUF's sha256. A vector from
    another build than the one already stored is refused (BuildMismatch, 409), since cosines across builds don't
    compare. A new build is a new database's vectors, or a deliberate re-embed (not in Shadow).
  - **Newest first, at most 500 posts a plan** (0086 B): every post, the newest first (priority = its age in
    days). Embedding costs no Claude usage, so it is not held to the last 30 days (corrections 8 is about Haiku).

An embed task has no mx_calls row: a vector is not a model's answer to audit, and the row it would duplicate is
the vector itself, which records its model and build.
"""
from __future__ import annotations

import base64
import math
import re
import struct
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from psycopg import Cursor

from insight_core.markx import repo, schemas, tasks

KIND = "embed"
MODEL = "bge-m3"
TEXT_VERSION = "markx-embed-text-v1"
TEXT_CHARS = tasks.TEXT_CHARS                  # 1,500 (0086 B)
DIMENSIONS = repo.DIMENSIONS                   # 1,024
VECTOR_BYTES = 2 * DIMENSIONS                  # float16
NORM_TOLERANCE = 0.01                          # a float16 copy of a unit vector is within ~0.001 of 1
PLAN_LIMIT = 500
PLAN_PAGES = 4                                 # rows read per plan: up to 4 x the limit (duplicates are skipped)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
URL_RE = re.compile(r"https?://\S+|\b(?:[\w-]+\.)+[a-z]{2,}/\S*", re.I)
BUILD_LOCK = 0x6D78656D62   # pg_advisory_xact_lock key: one build is decided at a time ('mxemb')


class BuildMismatch(Exception):
    """A vector from another embedder build than the one stored (POST /api/markx/embeddings answers 409)."""


# ---- the text --------------------------------------------------------------------------------------

def embed_text(p: tasks.Post) -> str:
    """markx embed text v1: the text an `embed` task asks for (its input)."""
    title, text = p.title or "", (p.text or "")[:TEXT_CHARS]
    if text.startswith(title[:40]):
        title = ""
    s = re.sub(r"\s+", " ", URL_RE.sub(" ", title + "\n" + text)).strip()
    return s or "(empty)"


# ---- the tasks -------------------------------------------------------------------------------------

def embed_task(cur: Cursor, post_id: Any, priority: int = 0):
    """The embed task of one post: (its id, whether it is new)."""
    p, = tasks._posts(cur, [post_id])
    return tasks.add(cur, KIND, embed_text(p), a=p.id, priority=priority)


def _copy_vector(cur: Cursor, post_id: str, task: Dict[str, Any], model: str) -> bool:
    """Another post with the same text: its vector, already stored, copied to `post_id`."""
    cur.execute("""INSERT INTO mx_embeddings (post_id, model, model_sha256, text_hash, v)
                   SELECT %s, model, model_sha256, text_hash, v FROM mx_embeddings
                    WHERE post_id = %s AND model = %s AND text_hash = %s
                   ON CONFLICT (post_id, model) DO NOTHING""", (post_id, task["a"], model, task["input_hash"]))
    return cur.rowcount == 1


def plan(cur: Cursor, *, days: Optional[int] = None, limit: int = PLAN_LIMIT, now: Optional[datetime] = None,
         model: str = MODEL) -> int:
    """Embed tasks for the newest posts with no vector and no embed task of their own (every post when `days` is
    None), newest first (priority: the post's age in days): how many tasks were added. A post whose text another
    post's task already asks gets that post's vector once it is stored (and goes to the candidates' run), else
    waits for it."""
    from insight_core.markx import jobs
    spec = schemas.KINDS[KIND]
    added = 0
    seen: set = set()
    copied: List[str] = []
    for _page in range(PLAN_PAGES):
        cur.execute(
            """SELECT p.id, GREATEST(0, floor(extract(epoch FROM (COALESCE(%(now)s, now())
                                        - COALESCE(p.surfaced_at, p.published_at, p.fetched_at))) / 86400))::int
                 FROM posts p
                WHERE (%(days)s::int IS NULL OR COALESCE(p.surfaced_at, p.published_at, p.fetched_at)
                                                 >= COALESCE(%(now)s, now()) - make_interval(days => %(days)s))
                  AND NOT EXISTS (SELECT 1 FROM mx_embeddings e WHERE e.post_id = p.id AND e.model = %(model)s)
                  AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = p.id)
                  AND NOT (p.id = ANY(%(seen)s::uuid[]))
                ORDER BY COALESCE(p.surfaced_at, p.published_at, p.fetched_at) DESC, p.id
                LIMIT %(limit)s""",
            {"now": now, "days": days, "model": model, "kind": KIND, "guide": spec.guide, "seen": list(seen),
             "limit": limit})
        rows = cur.fetchall()
        if not rows:
            break
        posts = tasks.load_posts(cur, [r[0] for r in rows])
        for pid, age in rows:
            seen.add(str(pid))
            p = posts.get(str(pid))
            if p is None:
                continue
            task_id, new = tasks.add(cur, KIND, embed_text(p), a=p.id, priority=age)
            if new:
                added += 1
                continue
            task = repo.get_task(cur, task_id)
            if task["status"] == "answered" and _copy_vector(cur, p.id, task, model):
                copied.append(p.id)
        if added >= limit or len(rows) < limit:
            break
    jobs.note_posts(cur, copied)
    return added


# ---- the vectors -----------------------------------------------------------------------------------

def encode(vector: Sequence[float]) -> str:
    """A vector as the worker sends it: 1,024 little-endian float16, base64 (the tests' and the worker's)."""
    return base64.b64encode(struct.pack(f"<{len(vector)}e", *vector)).decode("ascii")


def decode(text: Any) -> List[float]:
    """A posted vector, checked: 1,024 finite float16 of norm 1 (ValueError says why not)."""
    if not isinstance(text, str):
        raise ValueError("vector: a base64 string of 1,024 little-endian float16")
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        raise ValueError("vector: not base64") from None
    if len(raw) != VECTOR_BYTES:
        raise ValueError(f"vector: {len(raw)} bytes, not {VECTOR_BYTES} ({DIMENSIONS} float16)")
    v = list(struct.unpack(f"<{DIMENSIONS}e", raw))
    if not all(math.isfinite(x) for x in v):
        raise ValueError("vector: a number that is not finite")
    norm = math.sqrt(sum(x * x for x in v))
    if abs(norm - 1) > NORM_TOLERANCE:
        raise ValueError(f"vector: norm {norm:.4f}, not 1 (scale it to length 1)")
    return v


def check_build(cur: Cursor, model: str, model_sha256: str) -> None:
    """One embedder build per database: BuildMismatch when vectors of another build are stored under `model`."""
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (BUILD_LOCK,))
    others = {sha: n for sha, n in repo.embedding_builds(cur, model).items() if sha != model_sha256}
    if others:
        sha, n = max(others.items(), key=lambda kv: kv[1])
        raise BuildMismatch(f"this database holds {n} {model} vectors of build {sha or '(unknown)'}; "
                            f"a vector of build {model_sha256} doesn't compare with them")


def store(cur: Cursor, *, model: str, model_sha256: str, vectors: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Check and store posted vectors ({task_id, vector}): {stored, invalid: [{task_id, error}], repeated, posts}.
    A valid vector is stored for its task's post and closes the task; an invalid one puts the task back to open
    with its error (failed at the third try); one for a task already answered changes nothing (repeated).
    `posts`: the posts whose vector is new (for the candidates). ValueError: a model or build that isn't one;
    BuildMismatch: another build's vectors are stored."""
    if model != MODEL:
        raise ValueError(f"model: {MODEL!r} (BGE-M3), not {model!r}")
    if not isinstance(model_sha256, str) or not SHA256_RE.match(model_sha256):
        raise ValueError("model_sha256: the GGUF's sha256, 64 lowercase hex characters")
    check_build(cur, model, model_sha256)
    stored = repeated = 0
    invalid: List[Dict[str, Any]] = []
    posts: List[str] = []
    for item in vectors:
        raw_id = item.get("task_id") if isinstance(item, dict) else None
        try:
            task_id: Optional[UUID] = UUID(str(raw_id))
        except (TypeError, ValueError):
            task_id = None
        task = repo.get_task(cur, task_id) if task_id else None
        if task is None or task["kind"] != KIND:
            invalid.append({"task_id": raw_id, "error": "no such embed task"})
            continue
        try:
            v = decode(item.get("vector"))
        except ValueError as exc:
            invalid.append({"task_id": str(task_id), "error": str(exc)})
            if repo.fail_attempt(cur, task_id, str(exc)) is None:
                repeated += 1
            continue
        if task["status"] in ("answered", "failed"):
            repeated += 1
            continue
        if repo.put_embedding(cur, post_id=task["a"], model=model, text_hash=task["input_hash"], vector=v,
                              model_sha256=model_sha256):
            posts.append(str(task["a"]))
        repo.answer_task(cur, task_id)
        stored += 1
    return {"stored": stored, "invalid": invalid, "repeated": repeated, "posts": posts}
