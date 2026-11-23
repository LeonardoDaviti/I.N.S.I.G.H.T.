"""Mark X's API: an APIRouter under /api/markx, included by main.py.

INSIGHT_MARKX (default off) switches it: off, every path answers 404 and nothing here runs. On, the worker on the
owner's device (scripts/markx-worker) leases tasks, asks Haiku and posts the answers; the server checks each answer
(markx/validate.py) and stores it.

The worker contract (scripts/markx-worker is built against it). Every worker request carries `Authorization: Bearer
<token>` (the worker token, stored encrypted in the credentials table, provider "markx"); no token or another: 401.

GET /api/markx/work?kinds=<k1,k2>&limit=<n>&worker=<name>
    Leases up to n (1-100, default 20) open tasks of those kinds for 30 minutes, by priority then age (an expired
    lease is leased again), planning more first when few are open. 200 {"lease_until": ISO with offset, "guides":
    {id: {sha256, body, schema}}, "tasks": [{id, kind, guide, input, post?}]}. A task of a post's kind (POST_KINDS)
    carries its post, so the worker never asks two tasks of one post in one call. Fresh posts are leased first
    (the fresh lane). An unknown kind: 400.
POST /api/markx/answers
    {"worker", "executor", "model", "answers": [{task_id, answer, tokens_in?, tokens_out?, ms?, cost_usd?}]}
    -> 200 {stored, valid, invalid: [{task_id, error}], repeated}. Every answer is stored in mx_calls, valid or not.
    A valid one closes its task; an invalid one reopens it with its error (failed at the third try). An answer to a
    task already answered or failed changes nothing ("repeated"); a late answer is taken like any other; an unknown
    task id is listed in "invalid" and not stored.
GET /api/markx/ready?kinds=&days=   (v10.42) -> {"ready": kinds with a leasable task, "planned": kinds a lease would
    plan first}: the worker leases only these; an older server's 404: every kind.
POST /api/markx/release   {"worker", "task_ids"?} -> {"released"}: the leases go back to open, no try counted.
GET /api/markx/status     the queue, answers a day, tokens, workers, last run, guides and jobs.
POST /api/markx/embeddings
    {"worker", "model": "bge-m3", "model_sha256", "vectors": [{task_id, vector (base64 of 1,024 float16, norm 1),
    ms?}]} -> 200 {stored, invalid, repeated}; 400 another model; 409 the database holds another build's vectors
    (nothing stored). An embed task posted to /answers is invalid.

The owner's routes (no bearer: the app's own, like /api/credentials) are the rest: the token (GET/POST /token: a new
token replaces the old one), the Mark X page (on, news, posts, overview, decide, settings), labels, the entities tab
and its review queue, stories and perspectives. A new kind is one entry in schemas.KINDS.
"""
from __future__ import annotations

import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, StrictInt

from insight_core.markx import embed, jobs, labels, news, repo, schemas, tasks, validate
from insight_core.markx import ent42
from insight_core.markx import consumers, holds

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

# Each worker's last request is kept in mx_workers (several API processes each see some of them); this process
# writes a worker's row at most once every CONTACT_EVERY (its own last write, in _contacts).
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

# kinds the decision run plans itself, in its one long transaction: a lease planning one meanwhile would wait on the
# run's uncommitted rows until the run ends. The run plans them; the lease leases.
PLANNED_BY_RUNS = ("relate", "back")

PLAN_REST_SECONDS = 60.0   # a planner that found nothing to add rests this long before a lease runs it again
_PLAN_REST: Dict[str, float] = {}   # kind -> monotonic time its planner rests until (per API process)
FRESH = "fresh:"                    # _PLAN_REST's key prefix for a kind's fresh-lane planner
FRESH_REST_SECONDS = 30.0           # a fresh-lane planner that found nothing rests this long (a new post waits at most this)
# kinds whose leased tasks carry their post, by the column it is in (join's `a`, pair's `b`: the judged post), so
# the worker never asks two questions of one post in one call: an answer written for one could pass the other's
# quote check under the other's task id.
POST_KINDS = {"entities": "a", "reading": "a", "join": "a", "pair": "b"}


def _plan_resting(kind: str) -> bool:
    """Most queues run near empty, and a planner that finds nothing still reads its whole window: after a run that
    added nothing, leases skip it for PLAN_REST_SECONDS. New work still arrives within a minute."""
    return _PLAN_REST.get(kind, 0.0) > time.monotonic()


@router.get("/work", dependencies=[Depends(_worker_auth)])
def work(kinds: str = Query(...), limit: int = Query(20, ge=1, le=MAX_LIMIT), worker: str = Query(...),
         days: Optional[str] = Query(None)):
    """A lease. With `days` (a number, or "all"; `markx-worker cycle --days`), the read, entities and embed kinds asked
    are planned for that window first, newest first, PLAN_LIMIT a call; without it, the page's window holds and a kind
    is planned when fewer than `limit` wait, or at once when the page's window changed. Those kinds are leased inside
    the window first, newest first, then the older tasks still queued. Before all that, the fresh lane: posts fetched in
    the last tasks.FRESH_HOURS are planned and get up to tasks.FRESH_SHARE of the lease (repo.lease_tasks)."""
    worker = _name(worker)
    wanted = [k.strip() for k in kinds.split(",") if k.strip()]
    unknown = [k for k in wanted if k not in schemas.KINDS]
    if not wanted or unknown:
        raise HTTPException(status_code=400, detail=f"unknown kind: {unknown[0] if unknown else '(none)'}")
    window = _days(days) if days is not None else tasks.SETTING
    _contact(worker)
    with transaction() as cur:
        ensure_guides(cur)
        waiting = repo.open_counts(cur, wanted)
        setting = tasks.reading_window(cur)
        for kind in wanted:   # the fresh lane is planned on every lease (FRESH_REST_SECONDS after a dry one)
            if kind in tasks.FRESH_PLANNERS and kind in tasks.PLANNERS and not _plan_resting(FRESH + kind):
                if not tasks.FRESH_PLANNERS[kind](cur):
                    _PLAN_REST[FRESH + kind] = time.monotonic() + FRESH_REST_SECONDS
        for kind in wanted:
            if kind not in tasks.PLANNERS or not consumers.wanted(cur, kind):
                continue                                          # no feature reads it: nothing planned
            if tasks.planned_in_background(cur, kind):
                continue                                          # the decision job plans them
            if kind in PLANNED_BY_RUNS and jobs.decision_running(cur):
                continue                                          # never wait on a running decision run
            if window is not tasks.SETTING and kind in tasks.WINDOWED:
                tasks.PLANNERS[kind](cur, days=window)
            elif kind in tasks.WINDOWED and tasks.planned_window(cur, kind) != setting:
                tasks.PLANNERS[kind](cur, days=setting)          # the page's window changed: at once
                tasks.note_planned(cur, kind, setting)
            elif waiting.get(kind, 0) < limit and not _plan_resting(kind):
                if not tasks.PLANNERS[kind](cur):
                    _PLAN_REST[kind] = time.monotonic() + PLAN_REST_SECONDS
        leased = repo.lease_tasks(cur, kinds=wanted, limit=limit, worker=worker, windowed=tasks.WINDOWED,
                                  days=setting if window is tasks.SETTING else window,
                                  fresh=tasks.FRESH_KINDS, fresh_hours=tasks.FRESH_HOURS, fresh_share=tasks.FRESH_SHARE,
                                  fresh_dated_days=tasks.FRESH_DATED_DAYS)
        guides = repo.guides(cur, sorted({t["guide"] for t in leased})) if leased else {}
    until = max((t["lease_until"] for t in leased), default=datetime.now(timezone.utc)
                + timedelta(minutes=repo.LEASE_MINUTES))
    return {"lease_until": _iso(until),
            # the schema the server checks with (schemas.schema_for), not the one stored with the guide's first load: a
            # guide is never edited, so a set widened later would reach the worker without its new values and valid
            # answers be refused.
            "guides": {gid: {"sha256": g["sha256"], "body": g["body"],
                             "schema": schemas.schema_for(g["kind"], gid) or g["schema"]} for gid, g in guides.items()},
            "tasks": [dict({"id": str(t["id"]), "kind": t["kind"], "guide": t["guide"], "input": t["input"]},
                           **({"post": str(t[POST_KINDS[t["kind"]]])} if t.get(POST_KINDS.get(t["kind"], "")) else {}),
                           **_model(t["kind"]))
                      for t in leased]}


@router.get("/ready", dependencies=[Depends(_worker_auth)])
def ready(kinds: str = Query(...), days: Optional[str] = Query(None)):
    """v10.42: which of `kinds` a lease would give work now: {"ready": [kinds with a leasable task],
    "planned": [kinds a lease would plan first (as /work decides: a fresh lane, or a planner the lease runs and that
    is not resting)]}. Cheap (an EXISTS a kind on the queue index), so the worker leases only these instead of every
    kind each cycle; no lease, no plan, no write. An unknown kind: 400."""
    wanted = [k.strip() for k in kinds.split(",") if k.strip()]
    unknown = [k for k in wanted if k not in schemas.KINDS]
    if not wanted or unknown:
        raise HTTPException(status_code=400, detail=f"unknown kind: {unknown[0] if unknown else '(none)'}")
    with transaction() as cur:
        ready_ = set(repo.leasable_kinds(cur, wanted))
        setting = tasks.reading_window(cur)
        planned = set()
        for kind in wanted:
            if kind in tasks.FRESH_PLANNERS and kind in tasks.PLANNERS and not _plan_resting(FRESH + kind):
                planned.add(kind)
            elif kind not in tasks.PLANNERS or not consumers.wanted(cur, kind) or tasks.planned_in_background(cur, kind):
                continue
            elif kind in PLANNED_BY_RUNS and jobs.decision_running(cur):
                continue
            elif days is not None and kind in tasks.WINDOWED:
                planned.add(kind)
            elif kind in tasks.WINDOWED and tasks.planned_window(cur, kind) != setting:
                planned.add(kind)
            elif not _plan_resting(kind):
                planned.add(kind)
    return {"ready": [k for k in wanted if k in ready_], "planned": [k for k in wanted if k in planned and k not in ready_]}


def _model(kind: str) -> Dict[str, str]:
    """{"model": ...} when the kind is asked with another model than the worker's (identity.model_for)."""
    from insight_core.markx import identity
    m = identity.model_for(kind)
    return {"model": m} if m else {}


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
        if task["input"] is None:   # answered long ago, its input spent (tasks.spend): a repeat, not checked
            repeated += 1
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
            if repo.fail_attempt(cur, task_id, error, repo.max_attempts(task["kind"])) is None:
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
            jobs.want(cur, "decide")   # insight-ingestion decides (markx/jobs.py); never in the request
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
                         FROM mx_calls WHERE created_at >= COALESCE(%s, '-infinity'::timestamptz)
                        GROUP BY 1 ORDER BY 1 DESC LIMIT 60""", (repo.calls_days_floor(cur, 60),))
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
        invariants = _entity_invariants(cur)
    workers = []
    for w in sorted(set(seen_at) | set(leased)):
        seen = seen_at.get(w) or (leased[w][1] - timedelta(minutes=repo.LEASE_MINUTES))
        workers.append({"worker": w, "last_contact": _iso(seen), "leased": leased.get(w, (0, None))[0]})
    return {"queue": queue, "answers_per_day": days,
            "tokens": {"calls": n, "tokens_in": int(ti), "tokens_out": int(to), "cost_usd": round(float(c), 6)},
            "workers": workers,
            "last_run": None if run is None else {k: (_iso(v) if isinstance(v, datetime) else str(v) if isinstance(v, UUID) else v)
                                                  for k, v in run.items()},
            "guides": guide_hashes, "jobs": job_view,
            "entity_invariants": None if invariants is None else {**invariants, "at": _iso(invariants.get("at"))}}


class Vectors(BaseModel):
    worker: Any = None
    model: Any = None
    model_sha256: Any = None
    vectors: List[Dict[str, Any]] = []


@router.post("/embeddings", dependencies=[Depends(_worker_auth)])
def post_embeddings(body: Vectors):
    """An embedder's vectors for embed tasks (markx/embed.py); their candidates follow (markx/candidates.py)."""
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


# ---- the Mark X page's routes ----------------------------------------------------------------------------------

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
            "story_window_days": story_window.setting(cur),
            "entities_guide": _entities_guide(cur)}


def _entities_guide(cur) -> Dict[str, Any]:   # the entities guide switch (Worker tab)
    arm = schemas.entities_arm(cur)
    return {"guide": arm.guide, "chars": arm.chars, "rule": arm.rule, "default": schemas.DEFAULT_ARM,
            "arms": [{"guide": a.guide, "chars": a.chars, "rule": a.rule, "ready": not schemas.is_placeholder(a.guide),
                      **({"note": ent42.LAB} if a.guide == ent42.GUIDE else {})}
                     for a in schemas.ENTITY_ARMS.values()],
            "labels": ent42.precision(cur)}


class MentionLabelIn(BaseModel):
    guide: str
    n: StrictInt
    answer: str


@router.post("/posts/{post_id}/mentions/label")
def mx_label_mention(post_id: str, body: MentionLabelIn):
    """The owner's right / wrong on one new entity of the post; the newest answer counts toward the running precision
    on the Worker tab."""
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


class EntitiesGuideIn(BaseModel):
    guide: str


@router.post("/settings/entities-guide")
def mx_set_entities_guide(body: EntitiesGuideIn):
    """The entities guide the planner asks new entities tasks under (ent-v3, ent-v4 with the citation rule, ent-v3-6k).
    Counts from the next planner run; a placeholder guide is refused (409)."""
    with transaction() as cur:
        try:
            schemas.set_entities_arm(cur, body.guide)
        except ValueError as e:
            raise HTTPException(status_code=409 if "placeholder" in str(e) else 400, detail=str(e))
        return _window(cur)


class ReadingGuideIn(BaseModel):
    mode: str


@router.get("/reading5")
def mx_reading5(limit: int = Query(40, ge=1, le=200)):
    """ent-v5's switch and its Shadow comparison: the newest posts it read, each beside the post's current reading and
    entity set, with the agreement over them."""
    from insight_core.markx import reading5
    with transaction() as cur:
        return reading5.compare(cur, limit=limit)


@router.post("/settings/reading-guide")
def mx_set_reading_guide(body: ReadingGuideIn):
    """ent-v5's switch: `off` (nothing asked), `shadow` (read beside the old kinds, only /markx's comparison reads it),
    `on` (ent-v5 first wherever a reading is picked; its mention sets current)."""
    from insight_core.markx import reading5
    with transaction() as cur:
        try:
            return reading5.set_mode(cur, body.mode)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.get("/settings")
def mx_settings():
    """The owner's Mark X settings: the reading window of the read, entities and embed planners."""
    with transaction() as cur:
        return _window(cur)


@router.post("/settings/reading-window")
def mx_set_reading_window(body: WindowIn):
    """The reading window from the page: a number of days, or null for every post. It counts from the next planner run,
    with no restart; the decision window is the story window's."""
    with transaction() as cur:
        tasks.set_reading_window(cur, body.days)
        return _window(cur)


@router.post("/settings/story-window")
def mx_set_story_window(body: WindowIn):
    """The story window from the page: a number of days, or null for every post (the decision run makes Mark X's own
    stories back that far, newest first, a step a run). It counts from the next decision run; News keeps its own."""
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
    """The view the jobs process kept for the page's inputs now (news.kept_page), else built here."""
    with transaction() as cur:
        kept = news.kept_page(cur, only_differences=not all)
        if kept is not None:
            return Response(content=kept, media_type="application/json")
        return news.reader_view(news.page(cur, only_differences=not all))   # what the page reads


@router.get("/posts/{post_id}")
def mx_post(post_id: str):
    found = _uuid(post_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such post")
    with transaction() as cur:
        panel = news.post_panel(cur, str(found))
        # the edges between two posts are the Before list's (the older posts it connects to), not connections
        panel["connections"] = [c for c in panel["connections"] if not (c["from"] == "post" and c["other_kind"] == "post")]
        from insight_core.markx import graph
        got = graph.before(cur, str(found))
        panel["before"], panel["before_more"] = got["items"], got["more"]
        # the post's subjects' previous events (birth, last release, first outside mention), from their timeline
        from insight_core.markx import timeline
        panel["before_timeline"] = timeline.before_post(cur, str(found), skip=[r["post_id"] for r in got["items"]])
        return panel


@router.get("/posts/{post_id}/related")
def mx_post_related(post_id: str):
    """Related reading: the posts nearest this one by its stored vector (news.related), on request."""
    found = _uuid(post_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such post")
    with transaction() as cur:
        return news.related(cur, str(found))


@router.get("/overview")
def mx_overview():
    with transaction() as cur:
        return {"worker": {**news.worker(cur, contacts(cur)), "jobs": jobs.view(cur)}, "briefing": news.briefings(cur),
                "entities": news.entities(cur),
                "reading_window": {"days": tasks.reading_window(cur), "default": tasks.PLAN_DAYS},
                "story_window": _story_window_view(cur),
                "entities_guide": _entities_guide(cur),
                "entity_invariants": _entity_invariants(cur),
                "holds": holds.view(cur),   # the re-ask guard's holds
                "consumers": consumers.view(cur)}   # the features that read each kind's answers


class HoldIn(BaseModel):
    key: str = Field(min_length=3, max_length=80)
    state: str


@router.post("/holds")
def mx_set_hold(body: HoldIn):
    """The owner's word on a hold of the re-ask guard: low (asked last, the default), stopped (not asked) or released
    (asked as any task)."""
    with transaction() as cur:
        try:
            got = holds.set_state(cur, body.key, body.state)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {**got, "holds": holds.view(cur)}


class ConsumerIn(BaseModel):
    feature: str = Field(min_length=1, max_length=40)
    on: bool


@router.post("/settings/consumers")
def mx_set_consumer(body: ConsumerIn):
    """A feature that reads some kinds' answers switched on (its closed tasks open again) or off (its kinds' planners
    add nothing, its open tasks are closed, kept)."""
    with transaction() as cur:
        try:
            got = consumers.set_on(cur, body.feature, body.on)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {**got, "consumers": consumers.view(cur)}


class GuardIn(BaseModel):
    per_day: Optional[StrictInt] = Field(default=None, ge=0, le=10_000_000)


@router.post("/settings/reask-guard")
def mx_set_reask_guard(body: GuardIn):
    """A kind's tasks a day before the rest is held (null: no guard)."""
    with transaction() as cur:
        holds.set_per_day(cur, body.per_day)
        return holds.view(cur)


def _entity_invariants(cur) -> Optional[Dict[str, Any]]:
    from insight_core.markx import entity_stage
    return entity_stage.last_invariants(cur)


def _story_window_view(cur) -> Dict[str, Any]:
    from insight_core.markx import story_window
    return story_window.view(cur)


@router.post("/decide")
def mx_decide():
    """Asks for a decision run: insight-ingestion runs it within a minute (markx/jobs.py), never in the request.
    {"wanted": true, "jobs": the jobs' state}."""
    with transaction() as cur:
        jobs.want(cur, "decide")
        return {"wanted": True, "jobs": jobs.view(cur)}


# ---- the News members' one-tap labels ------------------------------------------------------------------------

class FlagIn(BaseModel):
    post: str
    story: str
    answer: str
    note: Optional[str] = None


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


# ---- the entities tab (markx/entity_views.py; no bearer) ---------------------------------------------------------
# list, review queue (?view=flagged | all), an answer to an item (applied at once, stored as a label), a flag for the
# owner, a merge undone, and the entity's page (a merged entity's id opens its cluster's page)

class EntityAnswerIn(BaseModel):
    answer: str
    note: Optional[str] = None


class UndoIn(BaseModel):
    note: Optional[str] = None


@router.get("/entities")
def mx_entities():
    """The list the jobs process kept (entity_views.kept_list), else built here."""
    from insight_core.markx import entity_views
    with transaction() as cur:
        return Response(content=entity_views.kept_list(cur), media_type="application/json")


@router.get("/entities/queue")
def mx_entity_queue(limit: int = Query(50, ge=1, le=1000), offset: int = Query(0, ge=0),
                    view: str = Query("flagged", pattern="^(flagged|all)$")):
    """`limit` open items from `offset`; `next_offset` the next page's, null at the end. `view`: flagged (the default:
    the items Claude's review flagged for the owner) or all. The first flagged page is the one the jobs process keeps
    (entity_views.kept_queue); any other is built here."""
    from insight_core.markx import entity_views
    with transaction() as cur:
        got = entity_views.kept_queue(cur, limit=limit, offset=offset, view=view)
        return Response(content=got, media_type="application/json") if isinstance(got, bytes) else got


class EntityFlagIn(BaseModel):
    flag: bool = True
    note: Optional[str] = Field(default=None, max_length=2000)
    by: str = "claude"


@router.post("/entities/queue/{item_id}/flag")
def mx_entity_flag(item_id: str, body: EntityFlagIn):
    """An open review item flagged for the owner by Claude's review ({flag: true, note}), or unflagged. The owner's
    queue shows only the flagged items by default."""
    from insight_core.markx import entity_answers
    found = _uuid(item_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such item in the queue")
    with transaction() as cur:
        try:
            return entity_answers.flag(cur, str(found), body.flag, note=body.note, by=body.by)
        except entity_answers.NotFound:
            raise HTTPException(status_code=404, detail="No such item in the queue")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


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
def mx_entity_page(entity_id: str, by_limit: int = 50, replies: bool = False, stories_limit: int = 20,
                   loose_limit: int = 30, whole: bool = Query(False, alias="all")):
    """The entity's page. `by_limit`: the by posts listed loose; `replies`: the posts replying to its handles too;
    `stories_limit` story blocks and `loose_limit` loose posts (with their totals), each clamped (entity_views.limits)
    and cut from the entity's one kept page. `all`: every post of each story, every citing post and work and every
    timeline event (else the first ones and their totals)."""
    from insight_core.markx import entity_views
    found = _uuid(entity_id)
    with transaction() as cur:   # kept while its inputs are the same, else built and kept
        got = entity_views.kept_entity_page(cur, str(found), by_limit=by_limit, replies=replies,
                                            stories_limit=stories_limit, loose_limit=loose_limit,
                                            whole=whole) if found else None
    if got is None:
        raise HTTPException(status_code=404, detail="No such entity")
    return Response(content=got, media_type="application/json")


class EntitySourcesIn(BaseModel):
    source_ids: List[str]
    answer: str


@router.post("/entities/{entity_id}/sources")
def mx_entity_sources(entity_id: str, body: EntitySourcesIn):
    """The owner's yes / no on "These sources are <name>" (a source whose handle or name is the entity's)."""
    from insight_core.markx import identity, person_page
    found = _uuid(entity_id)
    ids = [str(x) for x in (_uuid(s) for s in body.source_ids) if x]
    if found is None or not ids:
        raise HTTPException(status_code=404, detail="No such entity or source")
    with transaction() as cur:
        book = identity.lazy_book(cur)   # the entity's cluster, not the whole book
        if str(found) not in book.ents:
            raise HTTPException(status_code=404, detail="No such entity")
        try:
            n = person_page.answer_sources(cur, book, str(found), ids, body.answer)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"answered": n, "answer": body.answer}


class EntityHandleIn(BaseModel):
    platform: str
    handle: str
    answer: str = "yes"


@router.post("/entities/{entity_id}/handles")
def mx_entity_handle(entity_id: str, body: EntityHandleIn):
    """The owner says (yes) or denies (no) a handle of this person or org on a platform (x, github, telegram, bluesky,
    hf). Never inferred from a name: this, a confirmed pair question, or the entity's own sources."""
    from insight_core.markx import handles, identity
    found = _uuid(entity_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such entity")
    with transaction() as cur:
        book = identity.lazy_book(cur)   # the entity's cluster, not the whole book
        if str(found) not in book.ents:
            raise HTTPException(status_code=404, detail="No such entity")
        try:
            return handles.add_handle(cur, book, str(found), body.platform, body.handle, body.answer)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


class SampleLabelIn(BaseModel):
    answer: str


@router.post("/stories/{story_id}/sample")
def mx_story_sample(story_id: str, body: SampleLabelIn):
    """Right / wrong / missed on an old story the entity page offered; the old stories' precision decides whether the
    story window stays at everything."""
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


# ---- perspectives and the story sheet (markx/perspective_views.py; no bearer) -----------------------------------

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
def mx_story_view(story_id: str, as_of: Optional[datetime] = None):
    """`chain`: what led to the story and what followed (graph.chain), only the edges valid at `as_of` when given;
    empty while the chains switch is off."""
    from insight_core.markx import graph, perspective_views
    found = _uuid(story_id)
    if as_of is not None and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    from insight_core.markx import units
    with transaction() as cur:
        got = perspective_views.story_view(cur, str(found)) if found else None
        if got is not None:   # the round-ups carrying a member, display only (never a voice or a member)
            got["roundups"] = units.also_in_story(cur, got["story"]["id"])
            on = graph.chain_config()["on"]
            got["chain"] = graph.chain(cur, got["story"]["id"], as_of=as_of) if on else \
                {"before": [], "after": [], "before_more": 0, "after_more": 0, "as_of": None}
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


# ---- the fold's routes (markx/fold_api.py), under this router's prefix and switch ---------------------------------
from insight_core.markx import fold_api as _fold_api  # noqa: E402
router.include_router(_fold_api.router)
from insight_core.markx import translate as _translate; router.include_router(_translate.router)  # noqa: E402,E702  0130 D: translation


# ---- the owner's right / wrong on an edge of the Before list (markx/graph.py) -----------------------------------

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
from insight_core.markx import anchors_api as _anchors_api; router.include_router(_anchors_api.router)  # noqa: E402,E702  0180: anchors in Shadow
from insight_core.markx import units_api as _units_api; router.include_router(_units_api.router)  # noqa: E402,E702  0181: own round-ups
from insight_core.markx import track_counts as _track_counts; router.include_router(_track_counts.router)  # noqa: E402,E702  v10.12.1: a topic track's sidebar count (before tracks_api: /tracks/{id})
from insight_core.markx import tracks_api as _tracks_api; router.include_router(_tracks_api.router)  # noqa: E402,E702  0145: tracks as topics
from insight_core.markx import scout_api as _scout_api; router.include_router(_scout_api.router)  # noqa: E402,E702  0148: the track scout
from insight_core.markx import research_api as _research_api; router.include_router(_research_api.router)  # noqa: E402,E702  0162: research
from insight_core.markx import source_judge_api as _source_judge_api; router.include_router(_source_judge_api.router)  # noqa: E402,E702  0173: is this worth it?
from insight_core.markx import questions_api as _questions_api; router.include_router(_questions_api.router)  # noqa: E402,E702  0275: questions with citations
from insight_core.markx import personal_api as _personal_api; router.include_router(_personal_api.router)  # noqa: E402,E702  v10.42: the reader's interest
from insight_core.markx import discussions_api as _discussions_api; router.include_router(_discussions_api.router)  # noqa: E402,E702  0280: discussions
