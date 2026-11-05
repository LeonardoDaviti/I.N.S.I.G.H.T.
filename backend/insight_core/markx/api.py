"""Mark X Shadow's worker API (issue 0086 C): an APIRouter, included by main.py in one line.

INSIGHT_MARKX (default off) switches it: off, every path below answers 404 and nothing here runs (no
guide is loaded, no task is planned, no row is written). On, the worker on the owner's device
(scripts/markx-worker, 0086 D) leases tasks, asks Haiku, and posts the answers; the server checks each
answer (markx/validate.py) and stores it.

The contract (frozen 2026-11-05; scripts/markx-worker is built against it)
--------------------------------------------------------------------------
Every worker request carries `Authorization: Bearer <token>`: the worker token, generated in Sources →
Connections (POST /api/markx/token) and stored encrypted in the credentials table (provider "markx", key
"worker_token"). No token, or another one: 401 {"detail"}. JSON bodies, UTF-8.

GET /api/markx/work?kinds=<k1,k2>&limit=<n>&worker=<name>
    Leases up to n (1-100, default 20) open tasks of those kinds to the worker for 30 minutes, by priority
    (0 first) then age; a task whose lease ran out is leased again. When a kind has fewer than n open tasks
    and the server plans it (read, entities: the newest posts of the last 30 days; check: Mark IX's
    uncertain members), it plans up to 500 more first.
    200 {"lease_until": "<ISO 8601 with offset, UTC: 2026-11-05T12:30:00+00:00>",
         "guides": {"<guide id>": {"sha256": "<hex of body>", "body": "<text>", "schema": {..}}},
         "tasks": [{"id": "<uuid>", "kind": "<kind>", "guide": "<guide id>", "input": "<text>"}]}
    Every task's guide is in "guides". No open task: "tasks": [] and "guides": {}. An unknown kind: 400.

POST /api/markx/answers
    {"worker": "<name>", "executor": "claude-code" | "api" | "api-batch", "model": "<model id>",
     "answers": [{"task_id": "<uuid>", "answer": {..}, "tokens_in"?: int, "tokens_out"?: int, "ms"?: int,
                  "cost_usd"?: float}]}
    200 {"stored": int, "valid": int, "invalid": [{"task_id": "<uuid>", "error": "<why>"}], "repeated": int}
    Each answer is checked (0086 C's table) and stored in mx_calls, valid or not, with its tokens. A valid
    answer closes its task (and writes the post's reading or entities); an invalid one puts the task back to
    open with its error, failed at the third try. An answer to a task already answered or failed is stored as
    a call and changes nothing ("repeated" counts them; a valid one still counts in "valid"). An answer to a
    task whose lease ended, or that another worker now holds, is taken like any other. A task id that names
    no task is listed in "invalid" ("no such task") and not stored.

POST /api/markx/release
    {"worker": "<name>", "task_ids"?: ["<uuid>", ..]}
    200 {"released": int}
    The worker's leased tasks (those of task_ids, or all of them) go back to open; no try is counted.

GET /api/markx/status
    200 {"queue": {kind: {status: n}}, "answers_per_day": [{day, calls, valid, invalid, tokens_in, tokens_out,
         cost_usd}], "tokens": {calls, tokens_in, tokens_out, cost_usd}, "workers": [{worker, last_contact,
         leased}], "last_run": {..} | null, "guides": {id: sha256}}

S4's open points, settled: the answer is posted as {"task_id", "answer"} (and an answer the model wrapped in
one key named for it, {"reading": {..}}, is unwrapped); ids are uuid strings, posted back as leased; "valid"
is a count; release honours task_ids; late answers are taken as above; "schema" is JSON Schema in the
worker's subset (markx/schemas.py), never null for these kinds; tokens are per answer; lease_until always
has its offset.

The owner's routes (no bearer: they are the app's own, like /api/credentials)
--------------------------------------------------------------------------------
GET /api/markx/token    200 {"set": bool, "last4": str | null, "updated_at": ISO | null}
POST /api/markx/token   200 {"token": "<new token, shown once>", "set": true, "last4", "updated_at"}
                        A new token replaces the old one (a worker holding the old one gets 401).

Adding a kind (S2's `embed`): one entry in schemas.KINDS. A route of its own (POST /api/markx/embeddings)
is one more function on `router` below, or a router of S2's own included the same way; neither edits these.

S2's route (added 2026-11-05; the routes above are unchanged)
------------------------------------------------------------
GET /api/markx/work?kinds=embed leases embed tasks as any kind (the server plans 500 more, newest posts first, when
fewer than `limit` are open); each task's input is the exact text to embed (markx/embed.py), its guide `embed-v1`.

POST /api/markx/embeddings
    {"worker": "<name>", "model": "bge-m3", "model_sha256": "<the GGUF's sha256, 64 hex>",
     "vectors": [{"task_id": "<uuid>", "vector": "<base64 of 1,024 little-endian float16, norm 1>", "ms"?: int}]}
    200 {"stored": int, "invalid": [{"task_id", "error"}], "repeated": int}
    Each vector is checked (2,048 bytes, finite, norm 1 within 0.01) and stored for its task's post; the task is
    answered. An invalid one puts its task back to open with its error (failed at the third try). One for a task
    already answered changes nothing. The candidates of the new vectors are found after the uploads go quiet.
    400: another model, or not a sha256. 409 {"detail"}: the database holds vectors of another build (one build per
    database; nothing of the request is stored). An embed task posted to /answers is invalid ("answered at
    POST /api/markx/embeddings").
"""
from __future__ import annotations

import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from insight_core.markx import candidates, embed, repo, schemas, tasks, validate

TOKEN_PROVIDER, TOKEN_KEY = "markx", "worker_token"
MAX_LIMIT = 100
EXECUTORS = ("claude-code", "api", "api-batch")


def enabled() -> bool:
    """INSIGHT_MARKX: on (on, 1, true, yes) or off (anything else; the default)."""
    return os.getenv("INSIGHT_MARKX", "off").strip().lower() in ("on", "1", "true", "yes")


def _switched_on() -> None:
    if not enabled():
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(prefix="/api/markx", tags=["markx"], dependencies=[Depends(_switched_on)])


# ---- the database, the guides, the token ---------------------------------------------------------

def db_url() -> str:
    from insight_core.services.registry import services
    return services().db_url


def transaction():
    from insight_core.db import database
    return database.transaction(db_url())


ensure_guides = schemas.ensure_guides


class TokenStore:
    """The worker token, encrypted in the credentials table like every Connection (never logged)."""

    def __init__(self, box: Any = None) -> None:
        self.box = box

    def _box(self):
        if self.box is None:
            from insight_core.ingestion.credentials import SecretBox, SecretKeyMissing
            try:
                self.box = SecretBox.from_env(create=True)
            except SecretKeyMissing as exc:
                raise HTTPException(status_code=400, detail=f"Secrets cannot be stored: {exc}") from None
        return self.box

    def _row(self, cur):
        cur.execute("SELECT ciphertext, last4, updated_at FROM credentials WHERE provider = %s AND key = %s",
                    (TOKEN_PROVIDER, TOKEN_KEY))
        return cur.fetchone()

    def get(self, cur) -> Optional[str]:
        row = self._row(cur)
        if row is None:
            return None
        try:
            return self._box().decrypt(bytes(row[0]))
        except (ValueError, HTTPException):
            return None

    def view(self, cur) -> Dict[str, Any]:
        row = self._row(cur)
        return {"set": row is not None, "last4": row[1] if row else None,
                "updated_at": row[2].isoformat() if row and row[2] else None}

    def generate(self, cur) -> str:
        from insight_core.db.repo_credentials import CredentialsRepository
        token = secrets.token_urlsafe(32)
        CredentialsRepository().upsert(cur, TOKEN_PROVIDER, TOKEN_KEY, self._box().encrypt(token), token[-4:])
        return token


token_store = TokenStore()

_contacts: Dict[str, datetime] = {}   # the last request of each worker, since this process started


def _worker_auth(authorization: Optional[str] = Header(default=None)) -> None:
    given = (authorization or "").strip()
    if not given.lower().startswith("bearer ") or not given[7:].strip():
        raise HTTPException(status_code=401, detail="A worker token is needed (Sources → Connections → Mark X)")
    with transaction() as cur:
        stored = token_store.get(cur)
    if not stored or not hmac.compare_digest(given[7:].strip().encode(), stored.encode()):
        raise HTTPException(status_code=401, detail="Wrong worker token: generate one in Sources → Connections")


def _name(worker: Any) -> str:
    if not isinstance(worker, str) or not worker.strip() or len(worker) > 200:
        raise HTTPException(status_code=400, detail="worker: a name of 1-200 characters")
    return worker.strip()


def _contact(worker: str) -> None:
    _contacts[worker] = datetime.now(timezone.utc)


def _uuid(value: Any) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


# ---- the worker's routes -------------------------------------------------------------------------

@router.get("/work", dependencies=[Depends(_worker_auth)])
def work(kinds: str = Query(...), limit: int = Query(20, ge=1, le=MAX_LIMIT), worker: str = Query(...)):
    worker = _name(worker)
    wanted = [k.strip() for k in kinds.split(",") if k.strip()]
    unknown = [k for k in wanted if k not in schemas.KINDS]
    if not wanted or unknown:
        raise HTTPException(status_code=400, detail=f"unknown kind: {unknown[0] if unknown else '(none)'}")
    _contact(worker)
    with transaction() as cur:
        ensure_guides(cur)
        queue = repo.queue_counts(cur)
        for kind in wanted:
            if kind in tasks.PLANNERS and queue.get(kind, {}).get("open", 0) < limit:
                tasks.PLANNERS[kind](cur)
        leased = repo.lease_tasks(cur, kinds=wanted, limit=limit, worker=worker)
        guides = repo.guides(cur, sorted({t["guide"] for t in leased})) if leased else {}
    until = max((t["lease_until"] for t in leased), default=datetime.now(timezone.utc)
                + timedelta(minutes=repo.LEASE_MINUTES))
    return {"lease_until": _iso(until),
            "guides": {gid: {"sha256": g["sha256"], "body": g["body"], "schema": g["schema"]} for gid, g in guides.items()},
            "tasks": [{"id": str(t["id"]), "kind": t["kind"], "guide": t["guide"], "input": t["input"]} for t in leased]}


class Answer(BaseModel):
    task_id: Any = None
    answer: Any = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    ms: Optional[int] = None
    cost_usd: Optional[float] = None


class Answers(BaseModel):
    worker: Any = None
    executor: Any = None
    model: Any = None
    answers: List[Answer] = []


def store_answers(cur, *, executor: str, model: str, answers: List[Answer]) -> Dict[str, Any]:
    """Check and store each answer (one call each, valid or not); close, re-open or fail its task."""
    stored = valid = repeated = 0
    invalid: List[Dict[str, Any]] = []
    for a in answers:
        task_id = _uuid(a.task_id)
        task = repo.get_task(cur, task_id) if task_id else None
        if task is None:
            invalid.append({"task_id": a.task_id, "error": "no such task"})
            continue
        answer, error = validate.check(task["kind"], a.answer, task["input"])
        call_id = repo.add_call(cur, task_id=task_id, executor=executor, model=model, valid=error is None,
                                answer=answer, error=error, tokens_in=a.tokens_in, tokens_out=a.tokens_out, ms=a.ms,
                                cost_usd=a.cost_usd)
        stored += 1
        if error is None:
            valid += 1
            if repo.answer_task(cur, task_id):
                tasks.record(cur, task, call_id, answer)
            else:
                repeated += 1
        else:
            invalid.append({"task_id": str(task_id), "error": error})
            if repo.fail_attempt(cur, task_id, error) is None:
                repeated += 1
    return {"stored": stored, "valid": valid, "invalid": invalid, "repeated": repeated}


@router.post("/answers", dependencies=[Depends(_worker_auth)])
def post_answers(body: Answers):
    worker = _name(body.worker)
    if body.executor not in EXECUTORS:
        raise HTTPException(status_code=400, detail=f"executor: one of {', '.join(EXECUTORS)}")
    if not isinstance(body.model, str) or not body.model.strip():
        raise HTTPException(status_code=400, detail="model: the model id that answered")
    _contact(worker)
    with transaction() as cur:
        return store_answers(cur, executor=body.executor, model=body.model.strip(), answers=body.answers)


class Release(BaseModel):
    worker: Any = None
    task_ids: Optional[List[Any]] = None


@router.post("/release", dependencies=[Depends(_worker_auth)])
def release(body: Release):
    worker = _name(body.worker)
    _contact(worker)
    ids = None if body.task_ids is None else [u for u in (_uuid(t) for t in body.task_ids) if u]
    with transaction() as cur:
        return {"released": tasks.release(cur, worker, ids)}


@router.get("/status", dependencies=[Depends(_worker_auth)])
def status():
    with transaction() as cur:
        ensure_guides(cur)
        queue = repo.queue_counts(cur)
        cur.execute("""SELECT created_at::date, count(*), count(*) FILTER (WHERE valid), count(*) FILTER (WHERE NOT valid),
                              COALESCE(sum(tokens_in), 0), COALESCE(sum(tokens_out), 0), COALESCE(sum(cost_usd), 0)
                         FROM mx_calls GROUP BY 1 ORDER BY 1 DESC LIMIT 60""")
        days = [{"day": d.isoformat(), "calls": n, "valid": v, "invalid": i, "tokens_in": int(ti), "tokens_out": int(to),
                 "cost_usd": round(float(c), 6)} for d, n, v, i, ti, to, c in cur.fetchall()]
        cur.execute("SELECT count(*), COALESCE(sum(tokens_in), 0), COALESCE(sum(tokens_out), 0), "
                    "COALESCE(sum(cost_usd), 0) FROM mx_calls")
        n, ti, to, c = cur.fetchone()
        cur.execute("SELECT leased_by, count(*), max(lease_until) FROM mx_tasks WHERE status = 'leased' GROUP BY 1")
        leased = {w: (k, until) for w, k, until in cur.fetchall()}
        run = repo.last_run(cur)
        guide_hashes = {gid: g["sha256"] for gid, g in repo.guides(cur).items()}
    workers = []
    for w in sorted(set(_contacts) | set(leased)):
        seen = _contacts.get(w) or (leased[w][1] - timedelta(minutes=repo.LEASE_MINUTES))
        workers.append({"worker": w, "last_contact": _iso(seen), "leased": leased.get(w, (0, None))[0]})
    return {"queue": queue, "answers_per_day": days,
            "tokens": {"calls": n, "tokens_in": int(ti), "tokens_out": int(to), "cost_usd": round(float(c), 6)},
            "workers": workers,
            "last_run": None if run is None else {k: (_iso(v) if isinstance(v, datetime) else str(v) if isinstance(v, UUID) else v)
                                                  for k, v in run.items()},
            "guides": guide_hashes}


class Vectors(BaseModel):
    worker: Any = None
    model: Any = None
    model_sha256: Any = None
    vectors: List[Dict[str, Any]] = []


@router.post("/embeddings", dependencies=[Depends(_worker_auth)])
def post_embeddings(body: Vectors):
    """S2: an embedder's vectors for embed tasks (markx/embed.py); their candidates follow (markx/candidates.py)."""
    worker = _name(body.worker)
    _contact(worker)
    try:
        with transaction() as cur:
            result = embed.store(cur, model=body.model, model_sha256=body.model_sha256, vectors=body.vectors)
    except embed.BuildMismatch as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    candidates.pending.note(result.pop("posts"))
    return result


# ---- the owner's routes: the worker token ---------------------------------------------------------

@router.get("/token")
def token_view():
    with transaction() as cur:
        return token_store.view(cur)


@router.post("/token")
def token_generate():
    with transaction() as cur:
        token = token_store.generate(cur)
        view = token_store.view(cur)
    return {"token": token, **view}
