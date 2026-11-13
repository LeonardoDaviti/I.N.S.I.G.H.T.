"""Mark X Shadow's jobs: when the candidate finder (markx/candidates.py) and the decision run (markx/decide.py) run.

The rules and the work stay in their modules (`candidates.run`, `decide.run`); this module only decides when they
run, and where: **never in the API process** (0112 Decided 10). On 5 Nov a decision run in the API's one process sat
at 101% CPU and every /api/* request timed out.

  - **The API only marks that work arrived** (`want`, `note_posts`): a stamp in mx_jobs (`wanted_at`, set once until
    a run takes it) and, for new vectors, their posts in mx_candidate_posts. Each is one short statement in the
    request's own transaction; nothing runs in the request or in a thread of the API.
  - **insight-ingestion's scheduler runs them** (`Runner.tick`, every POLL seconds, in a thread beside the ingestion
    ticks; each job in a process of its own, so a run's CPU and memory never touch the scheduler's):
      - the candidate finder, when vectors arrived (the posts waiting in mx_candidate_posts) and before every
        decision run (also the posts whose entities were written since its last run);
      - the decision run: SETTLE seconds after work arrived (answers, vectors, POST /api/markx/decide, the API
        start's story job), at most one every GAP seconds (a steady stream of uploads can't push it back, nor run it
        back to back), and every EVERY seconds.
  - **The order of runs** (0121 Decided 3): no decision run while Mark IX's story job holds its lock or a rule
    change's rebuild is in progress or due (`mark_ix_busy`): it waits, then runs once. Nor while the candidate finder
    runs; and a run whose own candidate finder failed doesn't run on candidates that aren't there: both wait.
  - **A decision run has a time limit and stage logs** (0112 Decided 12): "Mark X decision run started", each stage
    with its duration (candidates, load, questions and decisions, write, connections, graph, back, headlines, news,
    entities, surges, perspectives_plan), the finish. Past LIMIT seconds it stops before the next stage and logs which;
    its one transaction rolls back (nothing half done) and the run is wanted again. A stage that never ends is killed
    with its process at HARD_LIMIT.
  - **A run that dies is a failed run** (v10.13.9): killed at HARD_LIMIT or ended with a non-zero exit code (an OOM
    kill, a segfault), it is recorded with the stage it was in and wanted again. A stage shown for longer than
    HARD_LIMIT + STALE_MARGIN is a dead run's (`stale`): the runner clears it, so nothing waits on it until a restart.
  - **The entities stage has a budget of its own** (0128): ENTITY_BUDGET seconds that LIMIT doesn't count, so its
    nightly full pass (63 s on the server) can't push the other stages over the limit. Past its budget the stage
    stops after a chunk of entities, the run goes on, and the next run resumes the pass (entity_stage).
  - One run at a time: this process runs one job at a time, and `decide.run` holds a Postgres advisory lock across
    processes (a second run is skipped).
  - A decision run is incremental though its process is new (0169): what the next run starts from is kept in Postgres
    (mx_inc_*, markx/incremental.py), written in the run's own transaction, so nothing here keeps state between runs.
  - The state is in mx_jobs, written in short transactions of their own (never inside a run's), so marking work
    never waits for a run.
  - **The Labels tab's queue is built here** (0182, the job "labels"): right after each decision run, in a process
    and a transaction of its own (a failure never touches the run, which is committed already), and on any pass that
    finds the newest run's queue not kept for this code (the first start after a deploy; a failed build is tried
    again after GAP seconds). It is a whole decision reading (labels.population): it was built in insight-api before,
    whose RSS then stayed at the build's high-water mark. The API reads only the kept queue (labels.kept).

Both only when INSIGHT_MARKX is on; nothing here raises into the scheduler.
"""
from __future__ import annotations

import logging
import multiprocessing
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

log = logging.getLogger(__name__)

POLL = 30.0                      # seconds between the runner's looks (work is picked up within this)
SETTLE = 60.0                    # a decision run waits this long after work arrived, so a burst of uploads is one run
GAP = 300.0                      # and at most one starts every 5 minutes while uploads stream in (0112 Decided 12)
EVERY = 3600.0                   # and runs at least hourly
LIMIT = 120.0                    # a decision run over this stops between stages, writes nothing, retries (Decided 12)
ENTITY_BUDGET = 45.0             # 0128: the entities stage's own seconds, outside LIMIT; its full pass resumes next run
OWN_BUDGET = ("entities",)       # the stages whose time LIMIT doesn't count
MENTIONS_MARGIN = timedelta(minutes=2)   # entities committed by a transaction that began before the last run's start
FIRST_SINCE = timedelta(days=1)          # the first candidates run looks back this far for new entities
WAIT_PAGE = 1000                 # v10.14: waiting posts a candidates run reads (the rest: the next run, wanted at once)
HARD_LIMIT = 900.0               # a job's process is killed after this (a stage that never ends); the run rolls back
STALE_MARGIN = 120.0             # v10.13.9: a stage older than HARD_LIMIT + this is a dead run's (`stale`): cleared
JOBS = ("candidates", "decide", "plan", "labels")
PLAN_EVERY = 300.0               # v10.13.4: the background planners (tasks.BACKGROUND_PLANNED) run at most every 5 min


class TooLong(Exception):
    """A decision run past LIMIT seconds, stopped before its next stage."""


def enabled() -> bool:
    from insight_core.markx.api import enabled as on
    return on()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- the API's side: work arrived ------------------------------------------------------------------

def want(cur: Any, job: str) -> None:
    """Work for `job` arrived: stamp wanted_at once (the runner clears it when a run takes it). A row already wanted is
    not written again, so many uploads at once don't queue on the row."""
    cur.execute("UPDATE mx_jobs SET wanted_at = now() WHERE job = %s AND wanted_at IS NULL", (job,))
    if cur.rowcount == 0:
        cur.execute("INSERT INTO mx_jobs (job, wanted_at) VALUES (%s, now()) ON CONFLICT (job) DO NOTHING", (job,))


def note_posts(cur: Any, post_ids: Iterable[str]) -> int:
    """New vectors for these posts: they wait for the candidate finder (mx_candidate_posts), and it is wanted."""
    ids = sorted({str(p) for p in post_ids})
    if not ids:
        return 0
    cur.execute("""INSERT INTO mx_candidate_posts (post_id) SELECT unnest(%s::uuid[])
                   ON CONFLICT (post_id) DO UPDATE SET noted_at = now()""", (ids,))
    want(cur, "candidates")
    return len(ids)


def state(cur: Any) -> Dict[str, Dict[str, Any]]:
    cur.execute("SELECT job, wanted_at, started_at, stage, stage_at, finished_at, last FROM mx_jobs")
    out = {j: {"job": j, "wanted_at": None, "started_at": None, "stage": None, "stage_at": None, "finished_at": None,
               "last": None} for j in JOBS}
    for job, wanted, started, stage, stage_at, finished, last in cur.fetchall():
        out[job] = {"job": job, "wanted_at": wanted, "started_at": started, "stage": stage, "stage_at": stage_at,
                    "finished_at": finished, "last": last}
    return out


def view(cur: Any) -> Dict[str, Dict[str, Any]]:
    """The jobs as /api/markx/status and the /markx page show them: each {running, started_at, stage, stage_at (the
    running stage's start), wanted_at (work waiting for a run), finished_at, last (how the last run ended)}; times
    ISO 8601 UTC."""
    def iso(v: Any) -> Any:
        return v.astimezone(timezone.utc).isoformat() if isinstance(v, datetime) else v
    return {job: {"running": s["stage"] is not None, **{k: iso(v) for k, v in s.items() if k != "job"}}
            for job, s in state(cur).items()}


# ---- the runner's side: the jobs (in insight-ingestion) ---------------------------------------------

def mark_ix_busy(cur: Any) -> Optional[str]:
    """Why a decision run must wait for Mark IX now, or None (0121 Decided 3): its story job holds its lock (a batch
    regrouping posts), or a rule change's rebuild is in progress (its progress in the story job's setting) or due (the
    stored rows are of other rules than this code's). A run then would decide over stories about to change."""
    from insight_core.services.stories_service import LOCK_KEY, SETTINGS_KEY, rules_stamp
    cur.execute("""SELECT (SELECT value FROM system_settings WHERE key = %(key)s),
                          EXISTS (SELECT 1 FROM pg_locks l JOIN pg_database d ON d.oid = l.database
                                   WHERE d.datname = current_database() AND l.locktype = 'advisory'
                                     AND l.objsubid = 1 AND l.granted
                                     AND ((l.classid::bigint << 32) | l.objid::bigint) = hashtext(%(lock)s)::bigint)""",
                {"key": SETTINGS_KEY, "lock": LOCK_KEY})
    value, locked = cur.fetchone()
    if locked:
        return "Mark IX's story job is running"
    if isinstance(value, dict):
        if value.get("rebuild"):
            return "a rule change's rebuild is in progress"
        if value.get("rules") and value["rules"] != rules_stamp():
            return "a rule change's rebuild is due"
    return None


def decision_running(cur: Any) -> bool:
    """v10.14: whether a decision run holds its advisory lock now (decide.LOCK_KEY, pg_try_advisory_xact_lock)."""
    from insight_core.markx.decide import LOCK_KEY
    cur.execute("""SELECT EXISTS (SELECT 1 FROM pg_locks l JOIN pg_database d ON d.oid = l.database
                                   WHERE d.datname = current_database() AND l.locktype = 'advisory' AND l.granted
                                     AND l.objsubid = 1 AND ((l.classid::bigint << 32) | l.objid::bigint) = %s)""",
                (LOCK_KEY,))
    return bool(cur.fetchone()[0])


def waiting_posts(cur: Any, limit: Optional[int] = None) -> List[str]:
    """The posts waiting for the candidate finder, longest waiting first; at most `limit` (None: all)."""
    cur.execute("""SELECT post_id::text FROM mx_candidate_posts WHERE found_at IS NULL OR found_at < noted_at
                    ORDER BY noted_at, post_id LIMIT %s""", (limit,))
    return [r[0] for r in cur.fetchall()]


def _happenings_step(cur: Any) -> Dict[str, Any]:
    """0175: one step of the stored happening keys' backfill (happening.backfill) in a savepoint of the candidates
    run: a failure is logged and leaves the candidates run standing (the next run tries again)."""
    from insight_core.markx import happening
    try:
        with cur.connection.transaction():
            return happening.backfill(cur)
    except Exception as exc:
        log.exception("Mark X candidates: the happenings backfill step failed")
        return {"error": str(exc)[:300]}


def _units_step(cur: Any) -> Dict[str, Any]:
    """0181: one step of the round-up split (units.backfill: new and never-split posts newest first, then the attach
    of the recent round-ups again) in a savepoint of the candidates run: a failure is logged and leaves the
    candidates run standing (the next run tries again)."""
    from insight_core.markx import units
    try:
        with cur.connection.transaction():
            return units.backfill(cur)
    except Exception as exc:
        log.exception("Mark X candidates: the units step failed")
        return {"error": str(exc)[:300]}


def _issues_step(cur: Any, now: datetime) -> Dict[str, Any]:
    """0181 (owner 2026-11-12): the own round-ups of the closed days and weeks not built yet (units.issues_step), after
    the units step, in a savepoint of the candidates run (its own process, never the API): a failure is logged and
    leaves the candidates run standing."""
    from insight_core.markx import units
    try:
        with cur.connection.transaction():
            return units.issues_step(cur, now)
    except Exception as exc:
        log.exception("Mark X candidates: the own round-ups step failed")
        return {"error": str(exc)[:300]}


def _json(value: Any) -> str:
    import json
    return json.dumps(value, default=str)


class Jobs:
    """The two jobs on one database, each run in the calling process (the runner calls them in a child process).
    Every state write is a short transaction of its own."""

    def __init__(self, db_url: str, *, clock: Callable[[], datetime] = _now, limit: float = LIMIT,
                 entity_budget: Optional[float] = ENTITY_BUDGET) -> None:
        self.db_url, self.clock, self.limit, self.entity_budget = db_url, clock, limit, entity_budget

    def _tx(self):
        from insight_core.db import database
        return database.transaction(self.db_url)

    def _begin(self, job: str, stage: str) -> datetime:
        with self._tx() as cur:
            cur.execute("""INSERT INTO mx_jobs (job) VALUES (%s) ON CONFLICT (job) DO NOTHING""", (job,))
            cur.execute("""UPDATE mx_jobs SET wanted_at = NULL, started_at = now(), stage = %s, stage_at = now()
                            WHERE job = %s RETURNING started_at""", (stage, job))
            return cur.fetchone()[0]

    def _stage(self, job: str, stage: str) -> None:
        with self._tx() as cur:
            cur.execute("UPDATE mx_jobs SET stage = %s, stage_at = now() WHERE job = %s", (stage, job))

    def _finish(self, job: str, last: Dict[str, Any], *, again: bool = False) -> None:
        """The run ended: no stage, the outcome in `last`; `again` wants the job once more (a failed run is retried)."""
        with self._tx() as cur:
            cur.execute("INSERT INTO mx_jobs (job) VALUES (%s) ON CONFLICT (job) DO NOTHING", (job,))
            cur.execute("""UPDATE mx_jobs SET stage = NULL, stage_at = NULL, finished_at = now(), last = %s::jsonb,
                                  wanted_at = CASE WHEN %s THEN COALESCE(wanted_at, now()) ELSE wanted_at END
                            WHERE job = %s""", (_json(last), again, job))

    def last(self, job: str) -> Dict[str, Any]:
        with self._tx() as cur:
            return state(cur)[job]

    def candidates(self) -> Optional[Counter]:
        """The candidate finder over the waiting posts and the posts whose entities were written since its last run.
        A failed run leaves its posts waiting and the job wanted."""
        from insight_core.markx import candidates, embed
        previous = (self.last("candidates").get("last") or {})
        started = self._begin("candidates", "candidates")
        since_text = previous.get("mentions_since")
        since = datetime.fromisoformat(since_text) if since_text else started - FIRST_SINCE
        t0 = time.monotonic()
        try:
            with self._tx() as cur:
                embed.set_aside(cur)                           # v1 vectors of texts that say nothing, once
                # v10.14: a page a run, so a burst of vectors (a backfill's) can't make one run too long to finish
                ids = waiting_posts(cur, WAIT_PAGE + 1)
                more, ids = len(ids) > WAIT_PAGE, ids[:WAIT_PAGE]
                counts = candidates.run(cur, ids, since=since)
                cur.execute("UPDATE mx_candidate_posts SET found_at = %s WHERE post_id = ANY(%s::uuid[])", (started, ids))
                backfill = candidates.backfill(cur, started)   # 0144 A2: the story window's next step, newest first
                keyed = _happenings_step(cur)                   # 0175: stored happening keys, a resumable step
                split = _units_step(cur)                        # 0181: round-ups split into units, a resumable step
                built = _issues_step(cur, started)              # 0181: the closed days' and weeks' own round-ups
        except Exception as exc:   # the posts wait for the next run
            log.exception("Mark X candidates: the run failed; the posts wait for the next")
            self._finish("candidates", {"ok": False, "error": str(exc)[:500], "mentions_since": since_text,
                                        "seconds": round(time.monotonic() - t0, 1)}, again=True)
            return None
        seconds = round(time.monotonic() - t0, 1)
        log.info("Mark X candidates: %d posts, %s in %.1f s", len(ids), dict(counts), seconds)
        self._finish("candidates", {"ok": True, "posts": len(ids), "counts": dict(counts), "seconds": seconds,
                                    "mentions_since": (started - MENTIONS_MARGIN).isoformat(),
                                    **({"more": True} if more else {}),
                                    **({"backfill": backfill} if backfill else {}),
                                    **({"happenings": keyed} if keyed else {}),
                                    **({"units": split} if split else {}),
                                    **({"issues": built} if built else {})}, again=more)
        return counts

    def plan(self) -> Dict[str, Any]:
        """v10.13.4: the job "plan", in its own process like the others: plan_background, its outcome recorded."""
        t0 = time.monotonic()
        self._begin("plan", "planning")
        out = self.plan_background()
        self._finish("plan", {"ok": not any("error" in v for v in out.values()),
                              "seconds": round(time.monotonic() - t0, 1), "kinds": out})
        return out

    def plan_background(self) -> Dict[str, Any]:
        """v10.13.2/4: the kinds a lease no longer plans (tasks.BACKGROUND_PLANNED), each in its own transaction before
        the decision run and outside its budget, so they are planned even while a decision run fails. Never fails the
        run: {kind: {added, seconds} | {planned: "by the lease"} | {error}}."""
        from insight_core.markx import tasks, unchanged
        out: Dict[str, Any] = {}
        for kind in tasks.BACKGROUND_PLANNED:
            t = time.monotonic()
            try:
                with self._tx() as cur:
                    if not tasks.planned_in_background(cur, kind, self.clock()):
                        out[kind] = {"planned": "by the lease"}
                        continue
                    # 0183: skipped while what it reads is as it was at its last pass that planned nothing
                    added = unchanged.run(cur, "plan:" + kind, *tasks.background_inputs(cur, kind, self.clock()),
                                          lambda: tasks.PLANNERS[kind](cur))
            except Exception as exc:
                log.exception("Mark X jobs: planning %s failed", kind)
                out[kind] = {"error": str(exc)[:300]}
                continue
            seconds = round(time.monotonic() - t, 1)
            if added is None:
                out[kind] = {"unchanged": True, "seconds": seconds}
                continue
            log.info("Mark X jobs: %d %s tasks planned in %.1f s", added, kind, seconds)
            out[kind] = {"added": added, "seconds": seconds}
        return out

    def labels(self) -> Optional[Dict[str, Any]]:
        """0182: the newest decision run's Labels queue, built and kept (labels.keep) in one REPEATABLE READ
        transaction of its own; a failure is recorded and the job tried again after GAP. Its seconds and this
        process's peak memory are recorded with it (mx_label_queues, mx_jobs.last)."""
        import resource

        from insight_core.markx import decide, labels as mx_labels

        def peak() -> float:
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0      # KiB on Linux
        t0 = time.monotonic()
        self._begin("labels", "building")
        try:
            with decide.snapshot(self.db_url) as cur:
                out = mx_labels.keep(cur, now=self.clock(), peak=peak)
        except Exception as exc:
            log.exception("Mark X labels: building the queue failed; tried again later")
            self._finish("labels", {"ok": False, "error": str(exc)[:500], "seconds": round(time.monotonic() - t0, 1)})
            return None
        seconds = round(time.monotonic() - t0, 1)
        log.info("Mark X labels: the queue of run %s kept in %.1f s (%s items, peak %.0f MB)", out.get("run"), seconds,
                 out.get("items", "already"), peak())
        self._finish("labels", {"ok": True, "seconds": seconds, "peak_mb": round(peak(), 1),
                                **{k: v for k, v in out.items() if k != "seconds"}})
        return out

    def decide(self) -> Optional[Dict[str, Any]]:
        """The candidate finder, then one decision run in its own snapshot, LIMIT seconds at most (both count), each
        stage logged with its duration; a failed or stopped run is wanted again."""
        from insight_core.markx import decide
        log.info("Mark X decision run started")
        t0 = time.monotonic()
        self._begin("decide", "candidates")
        stages: List[List[Any]] = []          # [[stage, seconds]] in order (jsonb keeps no key order)
        current = ["candidates", t0]
        own = [0.0]                           # 0128: the seconds of the stages with a budget of their own

        def stage(name: str) -> None:
            at = time.monotonic()
            stages.append([current[0], round(at - current[1], 1)])
            log.info("Mark X decision run: %s took %.1f s", current[0], at - current[1])
            if current[0] in OWN_BUDGET:
                own[0] += at - current[1]
            if at - t0 - own[0] > self.limit:
                apart = f", the entities stage's {own[0]:.0f} s apart" if own[0] else ""
                raise TooLong(f"over {self.limit:.0f} s ({at - t0 - own[0]:.0f} s{apart}): stopped before {name}")
            current[:] = [name, at]
            self._stage("decide", name)

        if self.candidates() is None:   # 0121 Decided 3: never on candidates that aren't there
            log.warning("Mark X decision run: the candidate finder failed; the run waits for it")
            self._finish("decide", {"ok": False, "error": "waiting for the candidate finder (it failed)",
                                    "stages": [["candidates", round(time.monotonic() - t0, 1)]],
                                    "seconds": round(time.monotonic() - t0, 1)}, again=True)
            return None
        try:
            with decide.snapshot(self.db_url) as cur:
                out = decide.run(cur, stage=stage, entity_budget=self.entity_budget, limit=self.limit, began=t0)
        except TooLong as exc:
            # the retry waits for the 5-minute gap between two starts (GAP), not the next 30 s look (0124)
            log.warning("Mark X decision run %s; nothing written, it runs again within %.0f minutes", exc, GAP / 60)
            self._finish("decide", {"ok": False, "error": str(exc), "stopped_before": str(exc).split("stopped before ", 1)[-1],
                                    "stages": stages, "seconds": round(time.monotonic() - t0, 1)}, again=True)
            return None
        except Exception as exc:
            log.exception("Mark X decisions: the run failed")
            self._finish("decide", {"ok": False, "error": str(exc)[:500], "stages": stages,
                                    "seconds": round(time.monotonic() - t0, 1)}, again=True)
            return None
        end = time.monotonic()
        if "skipped" not in out:
            stages.append([current[0], round(end - current[1], 1)])
            log.info("Mark X decision run: %s took %.1f s", current[0], end - current[1])
        seconds = round(end - t0, 1)
        log.info("Mark X decision run finished in %.1f s: %s", seconds,
                 {k: v for k, v in out.items() if k in ("stories", "changes", "news", "skipped")})
        self._finish("decide", {"ok": "skipped" not in out, "seconds": seconds, "run": out.get("run"),
                                "skipped": out.get("skipped"), "stages": stages,
                                "summary": {k: out.get(k) for k in ("stories", "answered", "changes", "posts")}},
                     again="skipped" in out)
        return out


def due(states: Dict[str, Dict[str, Any]], now: datetime, *, settle: float = SETTLE, every: float = EVERY,
        gap: float = GAP, busy: Optional[str] = None, plan_every: Optional[float] = None,
        labels_missing: bool = False) -> Optional[str]:
    """The job to run now, or None: a decision run SETTLE seconds after work arrived or EVERY seconds after the last
    one started (or never ran), never within GAP seconds of the last start, never while Mark IX is `busy` (why, from
    `mark_ix_busy`) nor while the candidate finder runs (0121 Decided 3); else the candidate finder when vectors
    arrived. v10.13.4: with `plan_every`, the background planners ("plan") first when they last started that long
    ago (or never), so a decision run that keeps failing never stops the planning; a decision run still follows.
    0182: then the Labels queue ("labels") when the newest run's is not kept (`labels_missing`); after a failed build,
    GAP seconds after its start."""
    p = states.get("plan") or {}
    if plan_every is not None and states["candidates"]["stage"] is None and (
            p.get("started_at") is None or (now - p["started_at"]).total_seconds() >= plan_every):
        return "plan"
    d = states["decide"]
    since = None if d["started_at"] is None else (now - d["started_at"]).total_seconds()
    if busy is None and states["candidates"]["stage"] is None and (since is None or since >= gap):
        if d["wanted_at"] is not None and (now - d["wanted_at"]).total_seconds() >= settle:
            return "decide"
        if since is None or since >= every:
            return "decide"
    if labels_missing and states["candidates"]["stage"] is None and _labels_may(states.get("labels") or {}, now, gap):
        return "labels"
    if states["candidates"]["wanted_at"] is not None:
        return "candidates"
    return None


def _labels_may(s: Dict[str, Any], now: datetime, gap: float) -> bool:
    """A labels build may start: never tried, its last ended well (a newer run's queue is missing), or GAP since a
    failed one."""
    if s.get("stage") is not None:
        return False
    if s.get("started_at") is None or (s.get("last") or {}).get("ok", True):
        return True
    return (now - s["started_at"]).total_seconds() >= gap


def stale(states: Dict[str, Dict[str, Any]], now: datetime, *, after: float = HARD_LIMIT + STALE_MARGIN) -> List[str]:
    """v10.13.9: the jobs shown running whose stage began more than `after` seconds ago. No run lives that long (its
    process is killed at HARD_LIMIT), so such a stage is a run that died without a word: due() would wait on it
    forever (the candidate finder's stage holds back every decision run and plan)."""
    return [job for job, s in states.items()
            if s.get("stage") is not None and s.get("stage_at") is not None
            and (now - s["stage_at"]).total_seconds() > after]


def _job_main(db_url: str, job: str) -> None:
    """A child process: one job, then exit (what it read goes back to the OS)."""
    from insight_core.logs.core.logger_config import setup_logging
    setup_logging(debug_mode=False)
    getattr(Jobs(db_url), job)()


class Runner:
    """insight-ingestion's Mark X loop: every POLL seconds, the job that is due, in a process of its own (or inline:
    `spawn=False`, the tests and the real-data check). Only when INSIGHT_MARKX is on; never raises."""

    def __init__(self, db_url: str, *, clock: Callable[[], datetime] = _now, spawn: bool = True,
                 on: Optional[Callable[[], bool]] = None, settle: float = SETTLE, every: float = EVERY,
                 gap: float = GAP, hard_limit: float = HARD_LIMIT, plan_every: Optional[float] = PLAN_EVERY) -> None:
        self.db_url, self.clock, self.spawn = db_url, clock, spawn
        self.plan_every = plan_every
        self.on = on or enabled
        self.settle, self.every, self.gap, self.hard_limit = settle, every, gap, hard_limit
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def _states(self) -> Dict[str, Dict[str, Any]]:
        from insight_core.db import database
        with database.transaction(self.db_url) as cur:
            cur.execute("SELECT now()")
            self._db_now = cur.fetchone()[0]
            self._busy = mark_ix_busy(cur)
            self._labels_missing = self._missing(cur)
            return state(cur)

    @staticmethod
    def _missing(cur: Any) -> bool:
        """0182: whether the newest decision run's Labels queue is not kept (False when that can't be told)."""
        try:
            from insight_core.markx import labels
            with cur.connection.transaction():
                return labels.missing(cur)
        except Exception:
            log.exception("Mark X jobs: could not tell whether the labels queue is kept")
            return False

    def recover(self) -> None:
        """At the runner's start: a run a restart ended mid-way shows no stage, and its job is wanted again."""
        from insight_core.db import database
        try:
            with database.transaction(self.db_url) as cur:
                cur.execute("""UPDATE mx_jobs SET stage = NULL, stage_at = NULL, wanted_at = COALESCE(wanted_at, now())
                                WHERE stage IS NOT NULL""")
                if cur.rowcount:
                    log.info("Mark X jobs: %d runs a restart ended are wanted again", cur.rowcount)
        except Exception:
            log.exception("Mark X jobs: could not recover the runs a restart ended")

    def _reap(self, job: str, s: Dict[str, Any]) -> None:
        """A stale stage (`stale`): the run is recorded as dead, wanted again, its stage cleared (only if the row still
        shows that stage: a run that moved on meanwhile is alive). `s` is updated as due() should see it."""
        from insight_core.db import database
        error = f"no word from the run for over {self.hard_limit + STALE_MARGIN:.0f} s"
        with database.transaction(self.db_url) as cur:
            cur.execute("""UPDATE mx_jobs SET stage = NULL, stage_at = NULL, finished_at = now(), last = %s::jsonb,
                                  wanted_at = COALESCE(wanted_at, now())
                            WHERE job = %s AND stage = %s AND stage_at = %s RETURNING wanted_at""",
                        (_json({"ok": False, "error": error, "stage": s["stage"]}), job, s["stage"], s["stage_at"]))
            row = cur.fetchone()
        if row:
            log.error("Mark X jobs: the %s run shown in stage %s since %s is dead (%s); wanted again",
                      job, s["stage"], s["stage_at"], error)
            s.update(stage=None, stage_at=None, wanted_at=row[0])

    def tick(self) -> Optional[str]:
        """One look: the job that ran, or None."""
        if not self.on():
            return None
        try:
            states = self._states()
            for dead in stale(states, self._db_now, after=self.hard_limit + STALE_MARGIN):
                self._reap(dead, states[dead])
            job = due(states, self._db_now, settle=self.settle, every=self.every, gap=self.gap, busy=self._busy,
                      plan_every=self.plan_every, labels_missing=self._labels_missing)
            if self._busy != getattr(self, "_told", None):
                if self._busy:
                    log.info("Mark X jobs: a decision run waits for Mark IX (%s)", self._busy)
                self._told = self._busy
            if job is None:
                return None
            self._run(job)
            if job == "decide":
                self._labels_after()
            return job
        except Exception:
            log.exception("Mark X jobs: the tick failed")
            return None

    def _run(self, job: str) -> None:
        if self.spawn:
            self._in_own_process(job)
        else:
            getattr(Jobs(self.db_url, clock=self.clock), job)()

    def _labels_after(self) -> None:
        """0182: right after a decision run, its Labels queue in a process of its own (when the run left a new one to
        build: a failed or skipped run leaves none). Never raises into the tick."""
        try:
            states = self._states()
            if self._labels_missing and states["labels"]["stage"] is None:
                self._run("labels")
        except Exception:
            log.exception("Mark X jobs: the labels queue after the decision run failed")

    def _in_own_process(self, job: str) -> None:
        process = multiprocessing.get_context("spawn").Process(target=_job_main, args=(self.db_url, job),
                                                               name=f"markx-{job}", daemon=True)
        process.start()
        process.join(self.hard_limit)
        if process.is_alive():
            process.kill()
            process.join(10)
            log.error("Mark X jobs: the %s run was killed after %.0f s; its transaction rolled back", job, self.hard_limit)
            self._dead(job, f"killed after {self.hard_limit:.0f} s", always=True)
        elif process.exitcode:
            # v10.13.9: a crash (an OOM kill's -9, a segfault) is a killed run: recorded, wanted again, its stage
            # cleared. Before, it only logged and the stage stayed set, so due() waited for it until a restart.
            log.error("Mark X jobs: the %s run ended with exit code %s", job, process.exitcode)
            self._dead(job, f"exited with code {process.exitcode}")

    def _dead(self, job: str, error: str, *, always: bool = False) -> None:
        """A run whose process ended without finishing: {"ok": False, error, the stage it was in}, wanted again, no
        stage; so is the candidate finder a decision run was running inside it. Ended in the entities stage, the full
        pass waits for the next night. Without `always`, a run that recorded its own end (no stage left) stays as is."""
        try:
            from insight_core.db import database
            with database.transaction(self.db_url) as cur:
                cur.execute("SELECT job, stage FROM mx_jobs WHERE stage IS NOT NULL AND job = ANY(%s)",
                            ([job, "candidates"] if job == "decide" else [job],))
                stages = dict(cur.fetchall())
                stage = stages.get(job)
                if job == "decide" and stage == "entities":
                    from insight_core.markx import entity_stage
                    entity_stage.defer_full(cur, f"a decision run ended in the entities stage ({error})")
            for other, at in stages.items():
                if other != job:
                    Jobs(self.db_url)._finish(other, {"ok": False, "error": f"{error} (inside the {job} run)",
                                                      "stage": at}, again=True)
            if stage is not None or always:
                Jobs(self.db_url)._finish(job, {"ok": False, "error": error, "stage": stage}, again=True)
        except Exception:
            log.exception("Mark X jobs: could not record the %s run that ended (%s)", job, error)

    def start(self, poll: float = POLL) -> bool:
        """The loop in a daemon thread (run_scheduler.py); False when Mark X is off at the start."""
        if self.thread is not None or not self.on():
            return False
        self.recover()

        def loop() -> None:
            while not self.stop.wait(poll):
                self.tick()
        self.thread = threading.Thread(target=loop, name="markx-jobs", daemon=True)
        self.thread.start()
        log.info("Mark X jobs: running here, every %.0f s", poll)
        return True
