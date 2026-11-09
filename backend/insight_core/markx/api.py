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
         leased}], "last_run": {..} | null, "guides": {id: sha256},
         "jobs": {"decide" | "candidates": {running, started_at, stage, stage_at, wanted_at, finished_at, last}}}
    (jobs: added by 0112 Decided 12; a running decision run shows its start and stage)

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

S5's routes, the Mark X page's (added 2026-11-05; the routes above are unchanged; no bearer: the app's own)
--------------------------------------------------------------------------------------------------------
GET /api/markx/on                  200 {"on": true} (404 when off, as every path here: the menu item's probe)
GET /api/markx/news?all=0|1        Mark X News beside Mark IX's (markx/news.py `page`): the newest written run's rows,
                                   only the differences unless all=1, each {id, tag, headline {text, from}, first_at,
                                   voices, score, posts [{id, title, source, kind, at, role, why, ix}], removed, ix};
                                   and `gone`: the Mark IX rows no Mark X row holds.
GET /api/markx/posts/{post_id}     the post page's panel: {reading, entities, stories, connections}; 0131 adds
                                   before [{post_id, relation, rule, p, reason, uncertain, at, title, source, label}]
                                   (the older posts it connects to, oldest first, 10 at most) and before_more
POST /api/markx/labels/edge        0131: {newer, older, answer: right | wrong | undo, note?}: the owner's mark on an edge
GET /api/markx/overview            {worker, briefing, entities}: the page's other tabs
POST /api/markx/decide             asks for a decision run: {"wanted": true, "jobs"}; insight-ingestion runs it within a
                                   minute, as it runs the hourly and after-upload ones (markx/jobs.py, 0112 Decided 10)

S6's routes, the labels tab's (added 2026-11-05; the routes above are unchanged; no bearer: the app's own)
--------------------------------------------------------------------------------------------------------------
GET /api/markx/labels                  the queue (markx/labels.py): {run, cut, total, done, features [{feature, name,
                                       total, done, population}], next [item ids], answered [item ids], pools}
GET /api/markx/labels/items/{id}       one item: {id, feature, name, question, answers, evidence (the judge's input),
                                       extracted (entities), day, split, pool, position, label, verdict}; the verdict
                                       is null until the item has a label
POST /api/markx/labels                 {item, answer, note?} -> {label, verdict, next, done, total}; a changed answer is
                                       a new row
GET /api/markx/labels/precision?labeller=owner   each feature's precision (dev, test, all, the bar swept on dev)
POST /api/markx/labels/news            {post, story, answer: wrong_story | not_about | ok, note?}: one tap on a Mark X
                                       News member, stored as a label

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
from pydantic import BaseModel, Field, StrictInt

from insight_core.markx import embed, jobs, labels, news, repo, schemas, tasks, validate
from insight_core.markx import ent42   # 0133 v4.2

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

# Each worker's last request is kept in mx_workers (0112 Decided 11: with two API processes each saw half of them);
# this process writes a worker's row at most once every CONTACT_EVERY (its own last write, in _contacts).
_contacts: Dict[str, datetime] = {}
CONTACT_EVERY = timedelta(seconds=10)


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
    now = datetime.now(timezone.utc)
    if worker in _contacts and now - _contacts[worker] < CONTACT_EVERY:
        return
    _contacts[worker] = now
    with transaction() as cur:
        cur.execute("INSERT INTO mx_workers (worker, last_contact) VALUES (%s, now()) "
                    "ON CONFLICT (worker) DO UPDATE SET last_contact = GREATEST(mx_workers.last_contact, EXCLUDED.last_contact)",
                    (worker,))


def contacts(cur) -> Dict[str, datetime]:
    """Each worker's last request, whichever API process it reached."""
    cur.execute("SELECT worker, last_contact FROM mx_workers")
    return dict(cur.fetchall())


def _uuid(value: Any) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


# ---- the worker's routes -------------------------------------------------------------------------

@router.get("/work", dependencies=[Depends(_worker_auth)])
def work(kinds: str = Query(...), limit: int = Query(20, ge=1, le=MAX_LIMIT), worker: str = Query(...),
         days: Optional[str] = Query(None)):
    """A lease. With `days` (a number, or "all"; `markx-worker cycle --days`), the read, entities and embed kinds
    asked are planned for that window first, newest first and PLAN_LIMIT a call, whatever the page's reading window
    (0112 Decided 9); without it, the page's window holds and a kind is planned when fewer than `limit` wait, or at
    once when the window it was last planned for is not the page's (0121 Decided 4). Those kinds are leased inside
    the window first, newest first, then the older tasks still queued (a narrowed window drops none)."""
    worker = _name(worker)
    wanted = [k.strip() for k in kinds.split(",") if k.strip()]
    unknown = [k for k in wanted if k not in schemas.KINDS]
    if not wanted or unknown:
        raise HTTPException(status_code=400, detail=f"unknown kind: {unknown[0] if unknown else '(none)'}")
    window = _days(days) if days is not None else tasks.SETTING
    _contact(worker)
    with transaction() as cur:
        ensure_guides(cur)
        queue = repo.queue_counts(cur)
        setting = tasks.reading_window(cur)
        for kind in wanted:
            if kind not in tasks.PLANNERS:
                continue
            if window is not tasks.SETTING and kind in tasks.WINDOWED:
                tasks.PLANNERS[kind](cur, days=window)
            elif kind in tasks.WINDOWED and tasks.planned_window(cur, kind) != setting:
                tasks.PLANNERS[kind](cur, days=setting)          # the page's window changed: at once
                tasks.note_planned(cur, kind, setting)
            elif queue.get(kind, {}).get("open", 0) < limit:
                tasks.PLANNERS[kind](cur)
        leased = repo.lease_tasks(cur, kinds=wanted, limit=limit, worker=worker, windowed=tasks.WINDOWED,
                                  days=setting if window is tasks.SETTING else window)
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
        answer, error = validate.check(task["kind"], a.answer, task["input"], task.get("guide"))
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
        result = store_answers(cur, executor=body.executor, model=body.model.strip(), answers=body.answers)
        if result["valid"]:
            jobs.want(cur, "decide")   # insight-ingestion decides (markx/jobs.py); never here (0112 Decided 10)
    return result


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
        seen_at = contacts(cur)
        run = repo.last_run(cur)
        guide_hashes = {gid: g["sha256"] for gid, g in repo.guides(cur).items()}
        job_view = jobs.view(cur)
    workers = []
    for w in sorted(set(seen_at) | set(leased)):
        seen = seen_at.get(w) or (leased[w][1] - timedelta(minutes=repo.LEASE_MINUTES))
        workers.append({"worker": w, "last_contact": _iso(seen), "leased": leased.get(w, (0, None))[0]})
    return {"queue": queue, "answers_per_day": days,
            "tokens": {"calls": n, "tokens_in": int(ti), "tokens_out": int(to), "cost_usd": round(float(c), 6)},
            "workers": workers,
            "last_run": None if run is None else {k: (_iso(v) if isinstance(v, datetime) else str(v) if isinstance(v, UUID) else v)
                                                  for k, v in run.items()},
            "guides": guide_hashes, "jobs": job_view}


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
            jobs.note_posts(cur, result.pop("posts"))   # their candidates, found by insight-ingestion (markx/jobs.py)
            if result["stored"]:
                jobs.want(cur, "decide")
    except embed.BuildMismatch as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
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


# ---- the Mark X page's routes (S5, 0086 E) -------------------------------------------------------------

MAX_DAYS = 36500


def _days(value: str) -> Optional[int]:
    """A lease's `days`: "all" (every post) or a whole number of days, 1 to MAX_DAYS."""
    v = value.strip().lower()
    if v == "all":
        return None
    if v.isdigit() and 1 <= int(v) <= MAX_DAYS:
        return int(v)
    raise HTTPException(status_code=400, detail='days: a number of days (1 to 36500) or "all"')


class WindowIn(BaseModel):
    days: Optional[StrictInt] = Field(..., ge=1, le=MAX_DAYS)


def _window(cur) -> Dict[str, Any]:
    from insight_core.markx import story_window
    return {"reading_window_days": tasks.reading_window(cur), "default": tasks.PLAN_DAYS,
            "story_window_days": story_window.setting(cur),                               # 0144 A1
            "entities_guide": _entities_guide(cur)}   # 0133


def _entities_guide(cur) -> Dict[str, Any]:   # 0133: the entities guide switch (Worker tab)
    arm = schemas.entities_arm(cur)
    return {"guide": arm.guide, "chars": arm.chars, "rule": arm.rule, "default": schemas.DEFAULT_ARM,
            "arms": [{"guide": a.guide, "chars": a.chars, "rule": a.rule, "ready": not schemas.is_placeholder(a.guide),
                      **({"note": ent42.LAB} if a.guide == ent42.GUIDE else {})}                   # 0133 v4.2
                     for a in schemas.ENTITY_ARMS.values()],
            "labels": ent42.precision(cur)}                                                        # 0133 v4.2


class MentionLabelIn(BaseModel):   # 0133 v4.2
    guide: str
    n: StrictInt
    answer: str


@router.post("/posts/{post_id}/mentions/label")
def mx_label_mention(post_id: str, body: MentionLabelIn):
    """0133 v4.2: the owner's right / wrong on one new entity of the post (a document, a source, a recommended, a
    second-question one); the newest answer counts toward the running precision on the Worker tab."""
    found = _uuid(post_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such post")
    with transaction() as cur:
        try:
            got = ent42.label(cur, post=str(found), guide=body.guide, n=body.n, answer=body.answer)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {**got, "precision": ent42.precision(cur, body.guide)}


class EntitiesGuideIn(BaseModel):   # 0133
    guide: str


@router.post("/settings/entities-guide")
def mx_set_entities_guide(body: EntitiesGuideIn):
    """0133: the entities guide the planner asks new entities tasks under (ent-v3 at 1,500 characters by default;
    ent-v4 at 6,000 with the citation rule; ent-v3-6k, the fallback). Counts from the next planner run; a placeholder
    guide is refused (409) until the lab's frozen guide replaces it."""
    with transaction() as cur:
        try:
            schemas.set_entities_arm(cur, body.guide)
        except ValueError as e:
            raise HTTPException(status_code=409 if "placeholder" in str(e) else 400, detail=str(e))
        return _window(cur)


@router.get("/settings")
def mx_settings():
    """The owner's Mark X settings (0112 Decided 9): the reading window of the read, entities and embed planners."""
    with transaction() as cur:
        return _window(cur)


@router.post("/settings/reading-window")
def mx_set_reading_window(body: WindowIn):
    """The reading window from the page: a number of days, or null for every post. It counts from the next planner
    run (the next lease), with no restart; the decision window is the story window's (0144)."""
    with transaction() as cur:
        tasks.set_reading_window(cur, body.days)
        return _window(cur)


@router.post("/settings/story-window")
def mx_set_story_window(body: WindowIn):
    """0144 A1: the story window from the page: a number of days, or null for every post (the decision run makes Mark
    X's own stories back that far, newest first, a step a run). It counts from the next decision run; News keeps its
    own window."""
    from insight_core.markx import story_window
    with transaction() as cur:
        story_window.set_window(cur, body.days)
        return _window(cur)


def after_start_stories() -> None:
    """When the start's story job has finished (main.py): Mark X's first decision run is wanted, only when Mark X is
    on; insight-ingestion runs it within a minute (markx/jobs.py). Never raises into the start."""
    if not enabled():
        return
    try:
        with transaction() as cur:
            jobs.want(cur, "decide")
    except Exception:   # noqa: BLE001 - the hourly run comes anyway
        import logging
        logging.getLogger(__name__).exception("Mark X: could not ask for the first decision run")


@router.get("/on")
def switched_on():
    return {"on": True}


@router.get("/news")
def mx_news_page(all: int = Query(0, ge=0, le=1)):
    with transaction() as cur:
        return news.page(cur, only_differences=not all)


@router.get("/posts/{post_id}")
def mx_post(post_id: str):
    found = _uuid(post_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such post")
    with transaction() as cur:
        panel = news.post_panel(cur, str(found))
        # 0131: the edges between two posts are the Before list's (the older posts it connects to), not connections
        panel["connections"] = [c for c in panel["connections"] if not (c["from"] == "post" and c["other_kind"] == "post")]
        from insight_core.markx import graph
        got = graph.before(cur, str(found))
        panel["before"], panel["before_more"] = got["items"], got["more"]
        return panel


@router.get("/overview")
def mx_overview():
    with transaction() as cur:
        return {"worker": {**news.worker(cur, contacts(cur)), "jobs": jobs.view(cur)}, "briefing": news.briefings(cur),
                "entities": news.entities(cur),
                "reading_window": {"days": tasks.reading_window(cur), "default": tasks.PLAN_DAYS},
                "story_window": _story_window_view(cur),   # 0144
                "entities_guide": _entities_guide(cur)}   # 0133


def _story_window_view(cur) -> Dict[str, Any]:
    from insight_core.markx import story_window
    return story_window.view(cur)


@router.post("/decide")
def mx_decide():
    """Asks for a decision run: insight-ingestion runs it within a minute (markx/jobs.py). Never one in the request
    (0112 Decided 10): {"wanted": true, "jobs": the jobs' state}."""
    with transaction() as cur:
        jobs.want(cur, "decide")
        return {"wanted": True, "jobs": jobs.view(cur)}


# ---- the labels tab (S6, 0086 F) --------------------------------------------------------------------------

class LabelIn(BaseModel):
    item: str
    answer: str
    note: Optional[str] = None


class FlagIn(BaseModel):
    post: str
    story: str
    answer: str
    note: Optional[str] = None


@router.get("/labels")
def mx_labels_queue():
    with transaction() as cur:
        return labels.queue_view(cur, labels.queue(cur))


@router.get("/labels/precision")
def mx_labels_precision(labeller: str = Query("owner", min_length=1, max_length=40)):
    with transaction() as cur:
        return labels.precision(cur, labels.queue(cur), labeller=labeller)


@router.get("/labels/items/{item_id}")
def mx_labels_item(item_id: str):
    found = _uuid(item_id)
    with transaction() as cur:
        got = labels.item_view(cur, labels.queue(cur), str(found)) if found else None
    if got is None:
        raise HTTPException(status_code=404, detail="No such item in the queue")
    return got


@router.post("/labels")
def mx_labels_answer(body: LabelIn):
    found = _uuid(body.item)
    with transaction() as cur:
        q = labels.queue(cur)
        if found is None or str(found) not in q.items:
            raise HTTPException(status_code=404, detail="No such item in the queue")
        try:
            out = labels.label(cur, q, str(found), body.answer, note=body.note)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        view = labels.queue_view(cur, q)
    return {**out, "next": (view["next"] or [None])[0], "done": view["done"], "total": view["total"]}


@router.post("/labels/news")
def mx_labels_news(body: FlagIn):
    post, story = _uuid(body.post), _uuid(body.story)
    if post is None or story is None:
        raise HTTPException(status_code=404, detail="No such member")
    with transaction() as cur:
        try:
            return labels.flag(cur, post=str(post), story=str(story), answer=body.answer, note=body.note)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such member")


# ---- the entities tab (0119 A3; added 2026-11-06; the routes above are unchanged; no bearer: the app's own) ---------
# GET  /api/markx/entities                    the list (markx/entity_views.py): {window_days, total, items, accuracy, queue}
# GET  /api/markx/entities/queue              the review queue: {open, answered, merges, counts, accuracy}
# POST /api/markx/entities/queue/{id}         {answer: same | other_version | different | not_entity, note?}: applied at
#                                             once (a merge, a split, a merge undone) and stored as a label
# POST /api/markx/entities/merges/{id}/undo   {note?}: one merge undone from the history (a label 'different')
# GET  /api/markx/entities/{id}               the entity's page (a merged entity's id opens its cluster's page)

class EntityAnswerIn(BaseModel):
    answer: str
    note: Optional[str] = None


class UndoIn(BaseModel):
    note: Optional[str] = None


@router.get("/entities")
def mx_entities():
    from insight_core.markx import entity_views
    with transaction() as cur:
        return entity_views.entity_list(cur)


@router.get("/entities/queue")
def mx_entity_queue():
    from insight_core.markx import entity_views
    with transaction() as cur:
        return entity_views.queue(cur)


@router.post("/entities/queue/{item_id}")
def mx_entity_answer(item_id: str, body: EntityAnswerIn):
    from insight_core.markx import entity_answers
    found = _uuid(item_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such item in the queue")
    with transaction() as cur:
        try:
            return entity_answers.answer(cur, str(found), body.answer, note=body.note)
        except entity_answers.NotFound:
            raise HTTPException(status_code=404, detail="No such item in the queue")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.post("/entities/merges/{redirect_id}/undo")
def mx_entity_undo(redirect_id: str, body: UndoIn):
    from insight_core.markx import entity_answers
    found = _uuid(redirect_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such merge")
    with transaction() as cur:
        try:
            return entity_answers.undo(cur, str(found), note=body.note)
        except entity_answers.NotFound:
            raise HTTPException(status_code=404, detail="No such merge, or it is undone already")


@router.get("/entities/{entity_id}")
def mx_entity_page(entity_id: str, by_limit: int = Query(50, ge=0, le=100000)):
    """The entity's page. 0144: `by_limit`, the by posts listed loose (the page's "Show all"); the visit offers the
    old stories to label (10 a page, 30 a day)."""
    from insight_core.markx import entity_views
    found = _uuid(entity_id)
    with transaction() as cur:
        got = entity_views.entity_page(cur, str(found), by_limit=by_limit, offer_sample=True) if found else None
    if got is None:
        raise HTTPException(status_code=404, detail="No such entity")
    return got


class EntitySourcesIn(BaseModel):   # 0144 B1
    source_ids: List[str]
    answer: str


@router.post("/entities/{entity_id}/sources")
def mx_entity_sources(entity_id: str, body: EntitySourcesIn):
    """0144 B1: the owner's yes / no on "These sources are <name>" (a source whose handle or name is the entity's)."""
    from insight_core.markx import identity, person_page
    found = _uuid(entity_id)
    ids = [str(x) for x in (_uuid(s) for s in body.source_ids) if x]
    if found is None or not ids:
        raise HTTPException(status_code=404, detail="No such entity or source")
    with transaction() as cur:
        book = identity.load_book(cur)
        if str(found) not in book.ents:
            raise HTTPException(status_code=404, detail="No such entity")
        try:
            n = person_page.answer_sources(cur, book, str(found), ids, body.answer)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"answered": n, "answer": body.answer}


class SampleLabelIn(BaseModel):   # 0144 C
    answer: str


@router.post("/stories/{story_id}/sample")
def mx_story_sample(story_id: str, body: SampleLabelIn):
    """0144 C: right / wrong / missed on an old story the entity page offered; the old stories' precision decides
    whether the story window stays at everything."""
    from insight_core.markx import person_page, story_window
    found = _uuid(story_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such story")
    with transaction() as cur:
        try:
            got = person_page.label_sample(cur, str(found), body.answer)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {**got, "precision": story_window.precision(cur)}


# ---- perspectives and the story sheet (0119 B6-B7; added 2026-11-07; the routes above are unchanged; no bearer) ------
# GET  /api/markx/stories/{id}             the story view (markx/perspective_views.py): {story, judged, sheet, header,
#                                          members [{post, label, sign, by, worth, facts [{index, fact, span, mine}],
#                                          claims, point, before, copies, mine}], counts, posts}
# POST /api/markx/labels/perspective       {story, post, answer: right | wrong | original | new_facts | opinion | same |
#                                          not_this_story, note?}: a label on a member's line
# POST /api/markx/labels/fact              {story, post, index, answer: right | not_new | not_true | not_about, note?}
# GET  /api/markx/labels/perspectives      the owner's labels on them scored, against the lab's numbers

class PerspectiveLabelIn(BaseModel):
    story: Any = None
    post: Any = None
    answer: str
    note: Optional[str] = None


class FactLabelIn(BaseModel):
    story: Any = None
    post: Any = None
    index: StrictInt
    answer: str
    note: Optional[str] = None


@router.get("/stories/{story_id}")
def mx_story_view(story_id: str):
    from insight_core.markx import perspective_views
    found = _uuid(story_id)
    with transaction() as cur:
        got = perspective_views.story_view(cur, str(found)) if found else None
    if got is None:
        raise HTTPException(status_code=404, detail="No such Mark X story")
    return got


@router.post("/labels/perspective")
def mx_label_perspective(body: PerspectiveLabelIn):
    from insight_core.markx import perspective_views
    story, post = _uuid(body.story), _uuid(body.post)
    if story is None or post is None:
        raise HTTPException(status_code=404, detail="No such member")
    with transaction() as cur:
        try:
            return perspective_views.label_perspective(cur, story=str(story), post=str(post), answer=body.answer,
                                                       note=body.note)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such member, or it has no perspective")


@router.post("/labels/fact")
def mx_label_fact(body: FactLabelIn):
    from insight_core.markx import perspective_views
    story, post = _uuid(body.story), _uuid(body.post)
    if story is None or post is None:
        raise HTTPException(status_code=404, detail="No such fact")
    with transaction() as cur:
        try:
            return perspective_views.label_fact(cur, story=str(story), post=str(post), index=body.index,
                                                answer=body.answer, note=body.note)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such fact")


@router.get("/labels/perspectives")
def mx_label_perspectives():
    from insight_core.markx import perspective_views
    with transaction() as cur:
        return perspective_views.accuracy(cur)


# ---- 0127 (v10.3): the fold's routes (markx/fold_api.py), under this router's prefix and switch ----
from insight_core.markx import fold_api as _fold_api  # noqa: E402
router.include_router(_fold_api.router)
from insight_core.markx import translate as _translate; router.include_router(_translate.router)  # noqa: E402,E702  0130 D: translation


# ---- 0131: the owner's right / wrong on an edge of the Before list (markx/graph.py) ----------------------------

class EdgeLabelIn(BaseModel):
    newer: Any = None
    older: Any = None
    answer: str
    note: Optional[str] = None


@router.post("/labels/edge")
def mx_label_edge(body: EdgeLabelIn):
    from insight_core.markx import graph
    newer, older = _uuid(body.newer), _uuid(body.older)
    if newer is None or older is None:
        raise HTTPException(status_code=404, detail="No such edge")
    with transaction() as cur:
        try:
            return graph.label(cur, newer=str(newer), older=str(older), answer=body.answer, note=body.note)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such edge")


from insight_core.markx import sources_api as _sources_api; router.include_router(_sources_api.router)  # noqa: E402,E702  0132 B: the source analysis page
from insight_core.markx import back_api as _back_api; router.include_router(_back_api.router)  # noqa: E402,E702  0136: back in the news
from insight_core.markx import tracks_api as _tracks_api; router.include_router(_tracks_api.router)  # noqa: E402,E702  0145: tracks as topics
