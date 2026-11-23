"""Mark X's jobs: when and where the candidate finder, the decision run, Mark IX's story job, the planners, the
official channels and the kept views run.

The work stays in its modules (`candidates.run`, `decide.run`, ...); this module decides when it runs, never in the
API process (0112 Decided 10). The API only marks that work arrived (`want`, `want_stories`, `note_posts`: one short
statement each); insight-ingestion's `Runner.tick` runs the job that is `due` every POLL seconds, each in a process
of its own (killed at HARD_LIMIT). A decision run waits SETTLE after work arrived, starts at most every RUN_GAP and at
least every EVERY, never while Mark IX's story job holds its lock or the candidate finder runs; past its time limit
(`limit_for`) it stops between stages and rolls back. A job that keeps failing backs off (`held`); a dead run is
recorded and wanted again (`stale`, `_reap`, `_dead`). State lives in mx_jobs, written in short transactions of their
own. Nothing here raises into the scheduler.
"""
from __future__ import annotations

import gc
import logging
import multiprocessing
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from insight_core.utils import peak
from insight_core.utils.idle_trim import libc_trim, rss_mb

log = logging.getLogger(__name__)

POLL = 30.0                      # seconds between the runner's looks
SETTLE = 60.0                    # a decision run waits this long after work arrived, so a burst of uploads is one run
GAP = 300.0                      # a failed job's backoff unit (GAP x 2^failures)
RUN_GAP = 900.0                  # at most one decision run starts this often while uploads stream in (0199)
EVERY = 3600.0                   # and runs at least hourly
LIMIT = 120.0                    # a decision run over this stops between stages, writes nothing, retries
CATCH_UP_LIMIT = 600.0           # a full run's, and the next run's after one stopped over its limit (`limit_for`)
ENTITY_BUDGET = 45.0             # the entities stage's own seconds, outside LIMIT; its full pass resumes next run
OWN_BUDGET = ("entities",)       # the stages whose time LIMIT doesn't count
MENTIONS_MARGIN = timedelta(minutes=2)   # entities committed by a transaction that began before the last run's start
FIRST_SINCE = timedelta(days=1)          # the first candidates run looks back this far for new entities
WAIT_PAGE = 1000                 # waiting posts a candidates run reads (the rest: the next run, wanted at once)
HARD_LIMIT = 900.0               # a job's process is killed after this (a stage that never ends); the run rolls back
STALE_MARGIN = 120.0             # a stage older than HARD_LIMIT + this is a dead run's (`stale`): cleared
JOBS = ("candidates", "decide", "plan", "news", "tracks", "unread", "main_source", "discover", "official",
        "stories", "entities")
STORIES_GAP = 120.0              # a rebuild's next slice starts this long after the last ended
ORIGINALS_GAP = 1800.0           # the originals follow a wanted story run at most this often
STARVE_AFTER = 900.0             # candidates or official due this long go before the kept views
OFFICIAL_EVERY = 1800.0          # the official channels' pass at most this often
REBUILD_GAP = 60.0               # News whose inputs changed between runs is built again at most this often
ENTITIES_GAP = 60.0              # the entity views whose inputs changed, at most this often
UNREAD_GAP = 30.0                # the unread counts whose inputs changed, at most this often
PLAN_EVERY = 300.0               # the background planners (tasks.BACKGROUND_PLANNED) run at most this often
MAX_BACKOFF = 6 * 3600.0         # a failing job is tried at least this often
FAILING_AFTER = 3                # this many failed runs in a row show the job as failing
SKIPPABLE = ("graph", "back", "later", "entities", "surges", "perspectives_plan")   # stages a run may defer


@dataclass(frozen=True)
class KeptView:
    """A view the jobs process keeps (built after decision runs and by `due`), a policy per view.
      - `job`: its Jobs method and mx_jobs row;
      - `missing(cur, now)`: whether it is not kept for its inputs now;
      - `when`: "always" (after each decision run and whenever missing) or "wanted" (only when its job is wanted);
      - `between_runs`: None (built at once when missing), or the seconds between builds while inputs change;
      - `markx`: kept only while Mark X is on; False: a reader's view, kept with Mark X off too;
      - `pages`: the mx_kept_pages pages its builds write;
      - `after_deploy`: built at the runner's first look when missing, before any other job (meanwhile the previous
        code's rows are sent while their inputs are the same)."""
    job: str
    missing: Callable[[Any, datetime], bool]
    when: str = "always"
    between_runs: Optional[float] = None
    markx: bool = True
    pages: Tuple[str, ...] = ()
    after_deploy: bool = False


def _news_missing(cur: Any, now: datetime) -> bool:
    from insight_core.markx import news
    return news.kept_missing(cur, now)


def _entities_missing(cur: Any, now: datetime) -> bool:
    from insight_core.markx import entity_views
    return entity_views.kept_missing(cur, now)


def _tracks_missing(cur: Any, now: datetime) -> bool:
    from insight_core.markx import track_brief, track_kept, tracks
    # and a closed week's issue, and a track placement due again
    return tracks.kept_missing(cur, now) or track_brief.missing(cur, now) or track_kept.due(cur)


def _unread_missing(cur: Any, now: datetime) -> bool:
    from insight_core.services.reader_service import unread_missing
    return unread_missing(cur)


def _main_source_missing(cur: Any, now: datetime) -> bool:
    from insight_core.services.discover_main_source import kept_missing
    return kept_missing(cur, now)


def _wanted(cur: Any, now: datetime) -> bool:
    """A view whose work is its job's being wanted; the job itself tells what is left to do."""
    return True


# the kept views, built in this order in one process after a decision run (News first: a page the owner waits on)
KEPT_VIEWS = (KeptView("news", _news_missing, between_runs=REBUILD_GAP, after_deploy=True),
              KeptView("entities", _entities_missing, between_runs=ENTITIES_GAP, after_deploy=True),
              KeptView("tracks", _tracks_missing, between_runs=120.0),      # tracks.KEPT_GAP
              KeptView("unread", _unread_missing, between_runs=UNREAD_GAP, markx=False, pages=("unread",)),
              KeptView("main_source", _main_source_missing, when="wanted", markx=False, pages=("main_source",)),
              KeptView("discover", _wanted, when="wanted", markx=False))
KEPT = tuple(v.job for v in KEPT_VIEWS)


def reader_rows(cur: Any) -> int:
    """The rows the reader's kept views (and Mark IX's rebuild) hold in mx_jobs and mx_kept_pages: they live under
    mx_ although they are not Mark X's (the real-data check tells them apart)."""
    jobs = [v.job for v in KEPT_VIEWS if not v.markx] + ["stories"]
    pages = [p for v in KEPT_VIEWS if not v.markx for p in v.pages]
    cur.execute("""SELECT (SELECT count(*) FROM mx_jobs WHERE job = ANY(%s))
                          + (SELECT count(*) FROM mx_kept_pages WHERE page = ANY(%s))""", (jobs, pages))
    return int(cur.fetchone()[0])


def readers(job: Optional[str]) -> bool:
    """Whether `job` is a reader's kept view or Mark IX's rebuild ("stories"), not Mark X's."""
    return job == "stories" or any(v.job == job and not v.markx for v in KEPT_VIEWS)


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


def want_stories(db_url: str) -> bool:
    """Mark IX's story job is wanted: the runner runs it within POLL seconds, then the originals (`Jobs.stories`).
    One short transaction; never raises. Returns whether it was marked."""
    from insight_core.db import database
    try:
        with database.transaction(db_url) as cur:
            want(cur, "stories")
        return True
    except Exception:  # noqa: BLE001 - the next fetch that saves posts wants it again
        log.exception("Mark IX's story job could not be marked wanted")
        return False


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
    cur.execute("SELECT job, wanted_at, started_at, stage, stage_at, finished_at, last, failures FROM mx_jobs")
    out = {j: {"job": j, "wanted_at": None, "started_at": None, "stage": None, "stage_at": None, "finished_at": None,
               "last": None, "failures": 0} for j in JOBS}
    for job, wanted, started, stage, stage_at, finished, last, failures in cur.fetchall():
        out[job] = {"job": job, "wanted_at": wanted, "started_at": started, "stage": stage, "stage_at": stage_at,
                    "finished_at": finished, "last": last, "failures": failures}
    return out


def view(cur: Any) -> Dict[str, Dict[str, Any]]:
    """The jobs as the status endpoints and the /markx page show them: each {running, started_at, stage, stage_at,
    wanted_at, finished_at, last, failures, failing, retry_at (a failed job's next try, or null)}; times ISO UTC."""
    def iso(v: Any) -> Any:
        return v.astimezone(timezone.utc).isoformat() if isinstance(v, datetime) else v
    out = {}
    for job, s in state(cur).items():
        wait, end = backoff(s), s.get("finished_at") or s.get("started_at")
        out[job] = {"running": s["stage"] is not None, **{k: iso(v) for k, v in s.items() if k != "job"},
                    "failing": failing(s),
                    "retry_at": iso(end + timedelta(seconds=wait)) if wait and end is not None else None}
    return out


def backoff(s: Dict[str, Any], gap: float = GAP) -> float:
    """The seconds a job waits after a failed run's end: GAP x 2^failures, at most MAX_BACKOFF; 0 if it did not fail."""
    n = int(s.get("failures") or 0)
    return 0.0 if n <= 0 else min(gap * 2 ** min(n, 32), MAX_BACKOFF)


def held(s: Dict[str, Any], now: datetime, gap: float = GAP) -> bool:
    """The one backoff decision: whether a job whose last runs failed is still waiting out its backoff (from the
    failed run's end, else its start)."""
    wait = backoff(s, gap)
    end = s.get("finished_at") or s.get("started_at")
    return bool(wait) and end is not None and (now - end).total_seconds() < wait


def failing(s: Dict[str, Any]) -> bool:
    """FAILING_AFTER failed runs in a row or more; it is still tried at its backoff."""
    return int(s.get("failures") or 0) >= FAILING_AFTER


# ---- the runner's side: the jobs (in insight-ingestion) ---------------------------------------------

def mark_ix(cur: Any) -> Dict[str, Any]:
    """Mark IX's story job as a decision run sees it: {locked (a batch regrouping now), rebuild: "in progress" |
    "due" | None, and a rebuild's done, total, phase, started_at}."""
    from insight_core.services.stories_service import LOCK_KEY, SETTINGS_KEY, rebuild_due
    cur.execute("""SELECT (SELECT value FROM system_settings WHERE key = %(key)s),
                          EXISTS (SELECT 1 FROM pg_locks l JOIN pg_database d ON d.oid = l.database
                                   WHERE d.datname = current_database() AND l.locktype = 'advisory'
                                     AND l.objsubid = 1 AND l.granted
                                     AND ((l.classid::bigint << 32) | l.objid::bigint) = hashtext(%(lock)s)::bigint)""",
                {"key": SETTINGS_KEY, "lock": LOCK_KEY})
    value, locked = cur.fetchone()
    out: Dict[str, Any] = {"locked": bool(locked), "rebuild": None}
    if isinstance(value, dict):
        rebuild = value.get("rebuild")
        if rebuild:
            rebuild = rebuild if isinstance(rebuild, dict) else {}
            out.update(rebuild="in progress", done=rebuild.get("done"), total=rebuild.get("total"),
                       phase=rebuild.get("phase"), started_at=rebuild.get("started_at"))
        elif value.get("rules") and rebuild_due(value):
            out["rebuild"] = "due"
    return out


def mark_ix_busy(cur: Any) -> Optional[str]:
    """Why work that reads Mark IX's stories waits for it now, or None: its lock is held, or a rebuild is in progress
    or due. A decision run asks `decision_hold` instead (a rebuild holds none)."""
    ix = mark_ix(cur)
    if ix["locked"]:
        return "Mark IX's story job is running"
    return f"a rule change's rebuild is {ix['rebuild']}" if ix["rebuild"] else None


def limit_for(kind: Optional[str], previous: Dict[str, Any], limit: float = LIMIT,
              catch_up: float = CATCH_UP_LIMIT) -> float:
    """A decision run's time limit: `catch_up` for a full run (`kind`, known once decide.run read its state) and for
    the run after one that stopped over its limit (`previous`: the job's last record), else `limit`. A stopped run
    rolls back the state too, so without this the next run would be the same full run, stopped again, for ever."""
    if kind == "full" or previous.get("stopped_before"):
        return max(limit, catch_up)
    return limit


def decision_hold(ix: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """The one decision on whether Mark IX holds a decision run now: (held, ahead). `held`: the story job's lock is
    held, else None. `ahead`: during a rebuild (due or in progress), a note that the run goes ahead on the stories as
    stored (each rebuild batch commits whole, so they are one consistent set), else None. `ix`: mark_ix's."""
    if ix.get("locked"):
        return "Mark IX's story job is running", None
    if not ix.get("rebuild"):
        return None, None
    what = f"a rule change's rebuild is {ix['rebuild']}"
    if ix.get("total"):
        what += f" ({int(ix.get('done') or 0):,} of {int(ix['total']):,} posts regrouped)"
    return None, f"{what}: the decision run goes ahead on the stories as stored"


def decision_waits(cur: Any, now: datetime, wait: float) -> bool:
    """Whether Mark IX's story job steps aside now for a decision run: Mark X is on, the run is wanted, not running,
    not in backoff, and has waited `wait` seconds or more since it was wanted or last started."""
    if not enabled():
        return False
    d = state(cur)["decide"]
    wanted, started = d.get("wanted_at"), d.get("started_at")
    if wanted is None or d.get("stage") is not None or held(d, now):
        return False
    since = max(wanted, started) if started is not None else wanted
    return (now - since).total_seconds() >= wait


def decision_running(cur: Any) -> bool:
    """Whether a decision run holds its advisory lock now (decide.LOCK_KEY)."""
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
    """One step of the happening keys' backfill, in a savepoint: a failure is logged and the candidates run stands."""
    from insight_core.markx import happening
    try:
        with cur.connection.transaction():
            return happening.backfill(cur)
    except Exception as exc:
        log.exception("Mark X candidates: the happenings backfill step failed")
        return {"error": str(exc)[:300]}


def _units_step(cur: Any) -> Dict[str, Any]:
    """One step of the round-up split (units.backfill), in a savepoint: a failure is logged and the candidates run
    stands."""
    from insight_core.markx import units
    try:
        with cur.connection.transaction():
            return units.backfill(cur)
    except Exception as exc:
        log.exception("Mark X candidates: the units step failed")
        return {"error": str(exc)[:300]}


def _issues_step(cur: Any, now: datetime) -> Dict[str, Any]:
    """The own round-ups of the closed days and weeks not built yet (units.issues_step), in a savepoint: a failure is
    logged and the candidates run stands."""
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


# every run's end counted where it is recorded (Jobs._finish, Runner._reap): ok and failed runs, the last success, the
# last RECENT runs in brief; GET /metrics reads them
_COUNTED = """runs_ok = runs_ok + CASE WHEN %(ok)s THEN 1 ELSE 0 END,
              runs_failed = runs_failed + CASE WHEN %(failed)s THEN 1 ELSE 0 END,
              ok_at = CASE WHEN %(ok)s THEN now() ELSE ok_at END,
              recent = jsonb_path_query_array(jsonb_build_array(jsonb_build_object('at', now()) || %(entry)s::jsonb)
                                              || recent, %(ring)s::jsonpath)"""
RECENT = 10
BRIEF = ("ok", "seconds", "peak_mb", "cpu_s", "stage")


def _counted(last: Dict[str, Any], failed: bool) -> Dict[str, Any]:
    """`_COUNTED`'s parameters for a run that ended with `last`."""
    return {"ok": last.get("ok") is True, "failed": failed, "ring": f"$[0 to {RECENT - 1}]",
            "entry": _json({k: last[k] for k in BRIEF if last.get(k) is not None})}


class Jobs:
    """The jobs on one database, each run in the calling process (the runner calls them in a child process). Every
    state write is a short transaction of its own."""

    def __init__(self, db_url: str, *, clock: Callable[[], datetime] = _now, limit: float = LIMIT,
                 entity_budget: Optional[float] = ENTITY_BUDGET, catch_up: float = CATCH_UP_LIMIT,
                 measure: bool = False) -> None:
        self.db_url, self.clock, self.limit, self.entity_budget = db_url, clock, limit, entity_budget
        self.catch_up = catch_up
        self.measure = measure   # in a job's own process: its peak memory and CPU go with each run's end

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
        """The run ended: no stage, the outcome in `last`; `again` wants the job once more. A failed run (`ok` false,
        not skipped) counts one more failure in a row, a good one clears the count; with `measure`, peak memory and
        CPU seconds are recorded. The run is counted (`_COUNTED`)."""
        failed = last.get("ok") is False and not last.get("skipped")
        if self.measure:
            last = {**last, "peak_mb": last.get("peak_mb", peak.mb()), "cpu_s": peak.cpu_s()}
        with self._tx() as cur:
            cur.execute("INSERT INTO mx_jobs (job) VALUES (%s) ON CONFLICT (job) DO NOTHING", (job,))
            cur.execute(f"""UPDATE mx_jobs SET stage = NULL, stage_at = NULL, finished_at = now(), last = %(last)s::jsonb,
                                  wanted_at = CASE WHEN %(again)s THEN COALESCE(wanted_at, now()) ELSE wanted_at END,
                                  failures = CASE WHEN %(failed)s THEN failures + 1 WHEN %(ok)s THEN 0 ELSE failures END,
                                  {_COUNTED}
                            WHERE job = %(job)s""", {"last": _json(last), "again": again, **_counted(last, failed), "job": job})

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
                # a page a run, so a burst of vectors can't make one run too long to finish
                ids = waiting_posts(cur, WAIT_PAGE + 1)
                more, ids = len(ids) > WAIT_PAGE, ids[:WAIT_PAGE]
                counts = candidates.run(cur, ids, since=since)
                cur.execute("UPDATE mx_candidate_posts SET found_at = %s WHERE post_id = ANY(%s::uuid[])", (started, ids))
                backfill = candidates.backfill(cur, started)   # the story window's next step, newest first
                keyed = _happenings_step(cur)
                split = _units_step(cur)
                built = _issues_step(cur, started)
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
        """The job "plan": plan_background, its outcome recorded."""
        t0 = time.monotonic()
        self._begin("plan", "planning")
        out = self.plan_background()
        self._finish("plan", {"ok": not any("error" in v for v in out.values()),
                              "seconds": round(time.monotonic() - t0, 1), "kinds": out})
        return out

    def plan_background(self) -> Dict[str, Any]:
        """The kinds planned in the background (tasks.BACKGROUND_PLANNED), each in its own transaction, outside the
        decision run so they are planned even while it fails. Never raises: {kind: {added, seconds} | {planned: "by
        the lease"} | {unchanged} | {error}}."""
        from insight_core.markx import tasks, unchanged
        out: Dict[str, Any] = {}
        for kind in tasks.BACKGROUND_PLANNED:
            t = time.monotonic()
            try:
                with self._tx() as cur:
                    if not tasks.planned_in_background(cur, kind, self.clock()):
                        out[kind] = {"planned": "by the lease"}
                        continue
                    # skipped while what it reads is as it was at its last pass that planned nothing
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
        out["track_places"] = self._keep_track_places()
        try:   # the open tasks of the kinds no feature reads, closed (kept, with the reason)
            from insight_core.markx import consumers
            with self._tx() as cur:
                out["not_asked"] = consumers.close_off(cur)
        except Exception as exc:  # noqa: BLE001 - tried again at the next plan
            log.exception("Mark X jobs: closing the tasks no feature reads failed")
            out["not_asked"] = {"error": str(exc)[:300]}
        return out

    def _keep_track_places(self) -> Dict[str, Any]:
        """The topic tracks whose inputs changed placed again (track_kept.refresh), in a savepoint; a failure is
        recorded as `failed`, never failing the plan (readers place a track live without it)."""
        from insight_core.markx import track_kept
        t = time.monotonic()
        try:
            with self._tx() as cur:
                with cur.connection.transaction():
                    placed = track_kept.refresh(cur)
        except Exception as exc:  # noqa: BLE001 - derived; the readers place a track live without it
            log.exception("Mark X jobs: keeping the track placements failed")
            return {"failed": str(exc)[:300]}
        return {"placed": placed, "seconds": round(time.monotonic() - t, 1)}

    def official(self) -> Optional[Dict[str, Any]]:
        """One pass of official channels (markx/official.run); a failed pass is tried again after its backoff."""
        from insight_core.markx import official as mx_official
        t0 = time.monotonic()
        self._begin("official", "running")
        try:
            out = mx_official.run(self.db_url, now=self.clock())
        except Exception as exc:
            log.exception("Mark X official channels: the pass failed")
            self._finish("official", {"ok": False, "error": str(exc)[:500], "seconds": round(time.monotonic() - t0, 1)})
            return None
        ok = "error" not in out
        self._finish("official", {"ok": ok, "seconds": round(time.monotonic() - t0, 1), **out})
        return out

    def news(self) -> Optional[Dict[str, Any]]:
        """Mark X News' views not kept for their inputs, built and kept (news.keep_pages)."""
        from insight_core.markx import news as mx_news
        return self._keep("news", lambda cur: mx_news.keep_pages(cur, now=self.clock()))

    def entities(self) -> Optional[Dict[str, Any]]:
        """The entity list, the queue's first page and the most opened entity pages, built and kept."""
        from insight_core.markx import entity_views
        return self._keep("entities", lambda cur: entity_views.keep_pages(cur, now=self.clock()))

    def _keep(self, job: str, keep: Callable[[Any], Dict[str, Any]], *, snapshot: bool = True,
              again: bool = False) -> Optional[Dict[str, Any]]:
        """One kept view's build: `keep(cur)` in one REPEATABLE READ transaction (`snapshot`; else `keep(None)` opens
        its own); a failure is recorded and retried after its backoff (`again`: wanted again). Seconds and peak memory
        are recorded; then the kept inputs' logged changes are folded (kept_pages.compact)."""
        from insight_core.markx import decide, kept_pages
        t0 = time.monotonic()
        self._begin(job, "building")
        try:
            if snapshot:
                with decide.snapshot(self.db_url) as cur:
                    out = keep(cur)
            else:
                out = keep(None)
        except Exception as exc:
            log.exception("Kept views: building %s failed; tried again later", job)
            self._finish(job, {"ok": False, "error": str(exc)[:500], "seconds": round(time.monotonic() - t0, 1)},
                         again=again)
            return None
        seconds = round(time.monotonic() - t0, 1)
        try:
            with self._tx() as cur:
                folded = kept_pages.compact(cur)
            if folded:
                out = {**out, "inputs_folded": folded}
        except Exception:  # noqa: BLE001 - the log only grows until the next fold
            log.exception("Kept views: folding the kept inputs' changes failed")
        log.info("Kept views: %s built %s in %.1f s (peak %.0f MB)", job, out.get("built"), seconds, peak.mb())
        self._finish(job, {"ok": True, "seconds": seconds, "peak_mb": peak.mb(), **out})
        return out

    def tracks(self) -> Optional[Dict[str, Any]]:
        """The topic tracks placed again, their sub-topics and briefs, then the track pages and suggestions kept."""
        from insight_core.markx import tracks as mx_tracks
        self._keep_track_places()
        subtopics = self._keep_track_subtopics()
        briefs = self._keep_track_briefs()
        out = self._keep("tracks", lambda cur: mx_tracks.keep_pages(cur, now=self.clock()))
        return None if out is None else {**out, "subtopics": subtopics, "briefs": briefs}

    def _keep_track_briefs(self) -> Dict[str, Any]:
        """The things of each track joined by their entities, then the closed weeks' issues kept, in a transaction of
        its own. Nothing while entity_bands.json `tracks.briefs` is off; a failure is recorded as `failed`."""
        from insight_core.markx import track_brief, track_things
        if not track_things.on():
            return {"off": True}
        t = time.monotonic()
        try:
            with self._tx() as cur:
                joined = track_things.refresh(cur)
                kept = track_brief.keep_issues(cur, now=self.clock())
        except Exception as exc:  # noqa: BLE001 - derived; the issues kept stay as they were
            log.exception("Mark X jobs: the track briefs failed")
            return {"failed": str(exc)[:300]}
        return {"joined": joined, "built": kept["built"], "seconds": round(time.monotonic() - t, 1)}

    def _keep_track_subtopics(self) -> Dict[str, Any]:
        """The tracks whose posts changed clustered into sub-topics again, in a transaction of its own; a failure is
        recorded as `failed` (the pages show the last sub-topics)."""
        from insight_core.markx import track_subtopics
        t = time.monotonic()
        try:
            with self._tx() as cur:
                got = track_subtopics.refresh(cur, now=self.clock())
        except Exception as exc:  # noqa: BLE001 - derived; the pages show the sub-topics as they were
            log.exception("Mark X jobs: clustering the track sub-topics failed")
            return {"failed": str(exc)[:300]}
        return {"tracks": got, "seconds": round(time.monotonic() - t, 1)}

    def unread(self) -> Optional[Dict[str, Any]]:
        """The unread counts counted and kept (reader_service.keep_unread_counts)."""
        from insight_core.services.reader_service import keep_unread_counts
        return self._keep("unread", keep_unread_counts)

    def main_source(self) -> Optional[Dict[str, Any]]:
        """Discover's main-source list built and kept, its shown channels tested over the web. Never in the API."""
        from insight_core.services.discover_main_source import keep
        return self._keep("main_source", lambda _cur: keep(self.db_url), snapshot=False)

    def discover(self) -> Optional[Dict[str, Any]]:
        """Discover's answer built again when due, and its first page's web reads (discover_reads.keep). Never in the
        API."""
        from insight_core.services.discover_reads import keep
        return self._keep("discover", lambda _cur: keep(self.db_url), snapshot=False)

    def stories(self) -> Optional[Dict[str, Any]]:
        """Mark IX's story job (stories_service.recompute_safely: bounded steps, then it yields or steps aside for a
        waiting decision run): a rebuild's next slice, or a wanted run followed by `after_stories` (at most every
        ORIGINALS_GAP). A wanted run that yielded or stepped aside is wanted again. Its summary, the rebuild's progress
        and peak memory are recorded."""
        from insight_core.services.stories_service import StoriesService
        t0 = time.monotonic()
        with self._tx() as cur:
            cur.execute("SELECT wanted_at IS NOT NULL, last->>'after_at' FROM mx_jobs WHERE job = 'stories'")
            row = cur.fetchone() or (False, None)
        wanted, after_at = bool(row[0]), row[1]
        self._begin("stories", "regrouping" if wanted else "rebuilding")
        try:
            out = StoriesService(self.db_url, clock=self.clock).recompute_safely() or {}
            with self._tx() as cur:
                ix = mark_ix(cur)
        except Exception as exc:
            log.exception("Mark IX's story job: the run failed; tried again after its backoff")
            self._finish("stories", {"ok": False, "error": str(exc)[:500], "seconds": round(time.monotonic() - t0, 1)},
                         again=wanted)
            return None
        failed = not out   # recompute_safely logged the failure
        last = {"ok": not failed, "seconds": round(time.monotonic() - t0, 1), "wanted": wanted,
                **{k: out[k] for k in ("skipped", "batches", "yielded", "posts", "changed") if k in out},
                "rebuild": {k: ix.get(k) for k in ("rebuild", "phase", "done", "total")}}
        if failed:
            last["error"] = "the story job failed (its log says why)"
        if wanted and not out.get("skipped") and (
                after_at is None or (self.clock() - datetime.fromisoformat(after_at)).total_seconds() >= ORIGINALS_GAP):
            self._stage("stories", "originals")
            last["after"] = self.after_stories()
            last["after_at"] = self.clock().isoformat()
        elif after_at:
            last["after_at"] = after_at
        last["peak_mb"] = peak.mb()
        log.info("Mark IX's story job: a run in %.1f s: %s", time.monotonic() - t0, last)
        self._finish("stories", {**last, "seconds": round(time.monotonic() - t0, 1)},
                     again=wanted and bool(out.get("yielded") or out.get("skipped")))
        return out

    def after_stories(self) -> Dict[str, Any]:
        """After a wanted story run: the originals its stories lack, then Mark X's scouts and research runs
        (markx/scout.with_scouts); they read its stories, so they follow it. Never raises."""
        import asyncio
        from insight_core.markx.scout import with_scouts
        from insight_core.services.originals_service import run_originals
        t0 = time.monotonic()
        try:
            asyncio.run(with_scouts(run_originals(self.db_url), self.db_url)())
            return {"ok": True, "seconds": round(time.monotonic() - t0, 1)}
        except Exception as exc:  # noqa: BLE001 - the story run stands
            log.warning("Could not ask for the stories' originals: %s", exc)
            return {"ok": False, "error": str(exc)[:300], "seconds": round(time.monotonic() - t0, 1)}

    def decide(self) -> Optional[Dict[str, Any]]:
        """The candidate finder, then one decision run in its own snapshot, within its time limit (`limit_for`), each
        stage logged with its duration; a failed or stopped run is wanted again."""
        from insight_core.markx import decide
        with self._tx() as cur:
            before = state(cur)["decide"]
            ahead = decision_hold(dict(mark_ix(cur), locked=False))[1]
        previous = before.get("last") or {}
        skip = [previous["skip_next"]] if previous.get("skip_next") in SKIPPABLE else []
        log.info("Mark X decision run started")
        if ahead:
            log.warning("Mark X decision run: %s", ahead)
        if skip:
            log.warning("Mark X decision run: the %s stage is skipped this run (over the limit in it twice in a row)",
                        skip[0])
        t0 = time.monotonic()
        self._begin("decide", "candidates")
        stages: List[List[Any]] = []          # [[stage, seconds]] in order (jsonb keeps no key order)
        rss: List[List[Any]] = []             # [[stage, RSS MB at its end, RSS MB after the trim]]
        current = ["candidates", t0]
        own = [0.0]                           # the seconds of the stages with a budget of their own
        limit = [limit_for(None, previous, self.limit, self.catch_up)]   # the kind's, once the run knows it
        if limit[0] > self.limit:
            log.warning("Mark X decision run: the last one stopped over its limit; this one has %.0f s", limit[0])

        def kind(name: str) -> None:
            limit[0] = limit_for(name, previous, self.limit, self.catch_up)
            if name == "full":
                log.info("Mark X decision run: a full run, %.0f s at most", limit[0])

        trim = libc_trim()

        def mb() -> Optional[float]:
            got = rss_mb()
            return None if got is None else round(got)

        def stage(name: str) -> None:
            ended = mb()
            gc.collect()   # what the finished stage let go goes back to the OS before the next one
            if trim is not None:
                trim()
            rss.append([current[0], ended, mb()])
            at = time.monotonic()
            stages.append([current[0], round(at - current[1], 1)])
            log.info("Mark X decision run: %s took %.1f s", current[0], at - current[1])
            if current[0] in OWN_BUDGET:
                own[0] += at - current[1]
            if at - t0 - own[0] > limit[0]:
                apart = f", the entities stage's {own[0]:.0f} s apart" if own[0] else ""
                raise TooLong(f"over {limit[0]:.0f} s ({at - t0 - own[0]:.0f} s{apart}): stopped before {name}")
            current[:] = [name, at]
            self._stage("decide", name)

        if self.candidates() is None:   # never on candidates that aren't there
            log.warning("Mark X decision run: the candidate finder failed; the run waits for it")
            self._finish("decide", {"ok": False, "error": "waiting for the candidate finder (it failed)",
                                    "stages": [["candidates", round(time.monotonic() - t0, 1)]],
                                    "seconds": round(time.monotonic() - t0, 1)}, again=True)
            return None
        try:
            with decide.snapshot(self.db_url) as cur:
                out = decide.run(cur, stage=stage, entity_budget=self.entity_budget, limit=self.limit, began=t0,
                                 skip=skip, on_kind=kind)
        except TooLong as exc:
            # over the limit in the same deferrable stage as the run before: the next run skips that stage once
            over_in = stages[-1][0] if stages else None
            skip_next = over_in if (over_in in SKIPPABLE and not skip and previous.get("stopped_before")
                                    and previous.get("over_in") == over_in) else None
            log.warning("Mark X decision run %s; nothing written, it runs again after its backoff%s", exc,
                        f"; over the limit in {over_in} twice in a row: the next run skips it" if skip_next else "")
            self._finish("decide", {"ok": False, "error": str(exc), "stopped_before": str(exc).split("stopped before ", 1)[-1],
                                    "over_in": over_in, **({"skip_next": skip_next} if skip_next else {}),
                                    **({"skipped_stages": skip} if skip else {}),
                                    "stages": stages, "rss_mb": rss, "seconds": round(time.monotonic() - t0, 1),
                                    "limit": limit[0], "peak_mb": peak.mb()}, again=True)
            return None
        except Exception as exc:
            log.exception("Mark X decisions: the run failed")
            self._finish("decide", {"ok": False, "error": str(exc)[:500], "stages": stages, "rss_mb": rss,
                                    "seconds": round(time.monotonic() - t0, 1)}, again=True)
            return None
        end = time.monotonic()
        if "skipped" not in out:
            stages.append([current[0], round(end - current[1], 1)])
            rss.append([current[0], mb(), None])
            log.info("Mark X decision run: %s took %.1f s", current[0], end - current[1])
        seconds = round(end - t0, 1)
        log.info("Mark X decision run finished in %.1f s: %s", seconds,
                 {k: v for k, v in out.items() if k in ("stories", "changes", "news", "skipped")})
        self._finish("decide", {"ok": "skipped" not in out, "seconds": seconds, "run": out.get("run"),
                                "skipped": out.get("skipped"), "stages": stages, "rss_mb": rss, "limit": limit[0],
                                "peak_mb": peak.mb(),
                                **({"skipped_stages": skip} if skip else {}),
                                **({"mark_ix": ahead} if ahead else {}),
                                "summary": {k: out.get(k) for k in ("stories", "answered", "changes", "posts")}},
                     again="skipped" in out)
        return out


def due(states: Dict[str, Dict[str, Any]], now: datetime, *, settle: float = SETTLE, every: float = EVERY,
        gap: float = GAP, busy: Optional[str] = None, plan_every: Optional[float] = None,
        kept_missing: Iterable[str] = (), run_gap: float = RUN_GAP, markx: bool = True,
        official_every: Optional[float] = None, rebuild: bool = False,
        starve_after: float = STARVE_AFTER) -> Optional[str]:
    """The job to run now, or None, in this order: the background planners ("plan") every `plan_every`; a wanted
    story run (new posts are grouped before they are decided); a decision run SETTLE after work arrived or EVERY
    after the last start, never within RUN_GAP of it, never while Mark IX holds it (`busy`) or the candidate finder
    runs; a rebuild's slice (`stories_due`); the candidate finder or official pass due for `starve_after`; a kept
    view missing and let start (`_kept_may`); then candidates, then official. A job in backoff (`held`) waits,
    whatever makes it due. `markx` False: only the rebuild's slice and the reader's kept views."""
    s = states.get("stories") or {}
    slice_due = stories_due(s, now, rebuild=rebuild, gap=gap)
    if not markx:
        if slice_due:
            return "stories"
        return next((v.job for v in KEPT_VIEWS if not v.markx and v.job in kept_missing
                     and _kept_may(v, states.get(v.job) or {}, now, gap)), None)
    p = states.get("plan") or {}
    if plan_every is not None and states["candidates"]["stage"] is None and not held(p, now, gap) and (
            p.get("started_at") is None or (now - p["started_at"]).total_seconds() >= plan_every):
        return "plan"
    if slice_due and s.get("wanted_at") is not None:
        return "stories"
    d = states["decide"]
    since = None if d["started_at"] is None else (now - d["started_at"]).total_seconds()
    if busy is None and states["candidates"]["stage"] is None and (since is None or since >= run_gap) \
            and not held(d, now, gap):
        if d["wanted_at"] is not None and (now - d["wanted_at"]).total_seconds() >= settle:
            return "decide"
        if since is None or since >= every:
            return "decide"
    if slice_due:
        return "stories"
    c = states["candidates"]
    candidates = c["wanted_at"] is not None and not held(c, now, gap)
    o = states.get("official") or {}
    official_at = None   # since when the official pass is due
    if official_every is not None and o.get("stage") is None and not held(o, now, gap):
        if o.get("started_at") is None:
            official_at = datetime.min.replace(tzinfo=timezone.utc)
        elif (now - o["started_at"]).total_seconds() >= official_every:
            official_at = o["started_at"] + timedelta(seconds=official_every)
    if candidates and (now - c["wanted_at"]).total_seconds() >= starve_after:
        return "candidates"
    if official_at is not None and (now - official_at).total_seconds() >= starve_after:
        return "official"
    if c["stage"] is None:
        for v in KEPT_VIEWS:
            if v.job in kept_missing and _kept_may(v, states.get(v.job) or {}, now, gap):
                return v.job
    if candidates:
        return "candidates"
    if official_at is not None:
        return "official"
    return None


def stories_due(s: Dict[str, Any], now: datetime, *, rebuild: bool, gap: float = GAP) -> bool:
    """Mark IX's story job may start now: not running, not in backoff, and wanted (at once, unless its last run
    yielded or stepped aside: then STORIES_GAP after it), or a rebuild due or in progress (`rebuild`), STORIES_GAP
    after the last run ended."""
    if s.get("stage") is not None or held(s, now, gap):
        return False
    last = s.get("last") or {}
    since = None if s.get("finished_at") is None else (now - s["finished_at"]).total_seconds()
    rested = since is None or since >= STORIES_GAP
    if s.get("wanted_at") is not None and (rested or not (last.get("yielded") or last.get("skipped"))):
        return True
    return rebuild and rested


def _kept_may(view: KeptView, s: Dict[str, Any], now: datetime, gap: float, *, after_run: bool = False) -> bool:
    """A missing kept view's build may start: not running, not in backoff, wanted when its policy says "wanted";
    between runs (not `after_run`), a view with `between_runs` at most that often from its last build's start."""
    if s.get("stage") is not None or held(s, now, gap):
        return False
    if view.when == "wanted" and s.get("wanted_at") is None:
        return False
    started = s.get("started_at")
    return (after_run or view.between_runs is None or started is None
            or (now - started).total_seconds() >= view.between_runs)


def kept_due(states: Dict[str, Dict[str, Any]], missing: Iterable[str], now: datetime, gap: float = GAP, *,
             after_run: bool = False, markx: bool = True) -> List[str]:
    """The kept views to build now, in KEPT_VIEWS' order: missing and let start (`_kept_may`); with Mark X off, only
    the reader's."""
    missing = set(missing)
    return [v.job for v in KEPT_VIEWS if (markx or not v.markx)
            and v.job in missing and _kept_may(v, states.get(v.job) or {}, now, gap, after_run=after_run)]


def stale(states: Dict[str, Dict[str, Any]], now: datetime, *, after: float = HARD_LIMIT + STALE_MARGIN) -> List[str]:
    """The jobs shown running whose stage began more than `after` seconds ago (no live run lasts that long: its
    process is killed at HARD_LIMIT), and the runs started that long ago that never recorded an end (`unended`)."""
    return [job for job, s in states.items()
            if (s.get("stage") is not None and s.get("stage_at") is not None
                and (now - s["stage_at"]).total_seconds() > after)
            or (unended(s) and (now - s["started_at"]).total_seconds() > after)]


def unended(s: Dict[str, Any]) -> bool:
    """A run that started and recorded no end, shown as not running (no stage): started_at after finished_at."""
    started, finished = s.get("started_at"), s.get("finished_at")
    return s.get("stage") is None and started is not None and (finished is None or finished < started)


def _job_main(db_url: str, *names: str) -> None:
    """A child process: its jobs, one after the other, then exit (what they read goes back to the OS). Each job's
    peak memory is counted from its own start."""
    from insight_core.logs.core.logger_config import setup_logging
    setup_logging(debug_mode=False)
    for job in names:
        peak.reset()
        getattr(Jobs(db_url, measure=True), job)()


class Runner:
    """insight-ingestion's Mark X loop: every POLL seconds, the job that is due, in a process of its own (or inline:
    `spawn=False`, the tests and the real-data check). Only when INSIGHT_MARKX is on; never raises."""

    def __init__(self, db_url: str, *, clock: Callable[[], datetime] = _now, spawn: bool = True,
                 on: Optional[Callable[[], bool]] = None, settle: float = SETTLE, every: float = EVERY,
                 gap: float = GAP, hard_limit: float = HARD_LIMIT, plan_every: Optional[float] = PLAN_EVERY,
                 run_gap: float = RUN_GAP) -> None:
        self.db_url, self.clock, self.spawn = db_url, clock, spawn
        self.run_gap = run_gap
        self.plan_every = plan_every
        self.on = on or enabled
        self.settle, self.every, self.gap, self.hard_limit = settle, every, gap, hard_limit
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.fresh = False   # set by `start`: its first look builds the after_deploy views

    def _states(self, markx: bool = True) -> Dict[str, Dict[str, Any]]:
        from insight_core.db import database
        with database.transaction(self.db_url) as cur:
            cur.execute("SELECT now()")
            self._db_now = cur.fetchone()[0]
            self._ix = mark_ix(cur)   # the rebuild's slices run with Mark X off too
            self._kept_missing = self._missing(cur, self._db_now, markx)
            return state(cur)

    @staticmethod
    def _missing(cur: Any, now: datetime, markx: bool = True) -> List[str]:
        """The kept views not kept for their inputs now (a view that can't be told is not listed); with Mark X off,
        the reader's only."""
        out = []
        for v in KEPT_VIEWS:
            if v.markx and not markx:
                continue
            try:
                with cur.connection.transaction():
                    if v.missing(cur, now):
                        out.append(v.job)
            except Exception:
                log.exception("Mark X jobs: could not tell whether the %s view is kept", v.job)
        return out

    def recover(self) -> None:
        """At the runner's start: a run a restart ended mid-way gets its end recorded and is wanted again (not a
        failure)."""
        from insight_core.db import database
        try:
            with database.transaction(self.db_url) as cur:
                cur.execute("""UPDATE mx_jobs SET last = COALESCE(last, '{}'::jsonb)
                                                      || jsonb_build_object('ok', false, 'stage', stage,
                                                                            'error', 'ended by a restart'),
                                                  stage = NULL, stage_at = NULL, finished_at = now(),
                                                  wanted_at = COALESCE(wanted_at, now())
                                WHERE stage IS NOT NULL""")
                if cur.rowcount:
                    log.info("Mark X jobs: %d runs a restart ended are wanted again", cur.rowcount)
        except Exception:
            log.exception("Mark X jobs: could not recover the runs a restart ended")

    def _reap(self, job: str, s: Dict[str, Any]) -> None:
        """A stale run (`stale`): recorded as dead, wanted again, its stage cleared, only if the row still shows that
        stage (or that start with no end); `s` is updated as due() should see it. A stale stage is a failed run; an
        `unended` run is recorded as ended, not as a failure."""
        from insight_core.db import database
        if s.get("stage") is None:
            error = f"started at {s['started_at'].isoformat()} and never finished (a restart or a crash ended it)"
            with database.transaction(self.db_url) as cur:
                cur.execute("""UPDATE mx_jobs SET finished_at = now(), wanted_at = COALESCE(wanted_at, now()),
                                      last = COALESCE(last, '{}'::jsonb) || %s::jsonb
                                WHERE job = %s AND stage IS NULL AND started_at = %s
                                  AND (finished_at IS NULL OR finished_at < started_at)
                            RETURNING wanted_at, finished_at, failures""",
                            (_json({"ok": False, "error": error}), job, s["started_at"]))
                row = cur.fetchone()
            if row:
                log.error("Mark X jobs: the %s run %s; recorded as ended, wanted again", job, error)
                s.update(wanted_at=row[0], finished_at=row[1], failures=row[2])
            return
        error = f"no word from the run for over {self.hard_limit + STALE_MARGIN:.0f} s"
        dead = {"ok": False, "error": error, "stage": s["stage"]}
        with database.transaction(self.db_url) as cur:
            cur.execute(f"""UPDATE mx_jobs SET stage = NULL, stage_at = NULL, finished_at = now(), last = %(last)s::jsonb,
                                  wanted_at = COALESCE(wanted_at, now()), failures = failures + 1, {_COUNTED}
                            WHERE job = %(job)s AND stage = %(stage)s AND stage_at = %(stage_at)s
                        RETURNING wanted_at, finished_at, failures""",
                        {"last": _json(dead), **_counted(dead, True), "job": job, "stage": s["stage"],
                         "stage_at": s["stage_at"]})
            row = cur.fetchone()
        if row:
            log.error("Mark X jobs: the %s run shown in stage %s since %s is dead (%s); wanted again",
                      job, s["stage"], s["stage_at"], error)
            s.update(stage=None, stage_at=None, wanted_at=row[0], finished_at=row[1], failures=row[2])

    def tick(self) -> Optional[str]:
        """One look: the job that ran, or None."""
        markx = self.on()   # with Mark X off, the reader's kept views only
        try:
            states = self._states(markx)
            for dead in stale(states, self._db_now, after=self.hard_limit + STALE_MARGIN):
                self._reap(dead, states[dead])
            held_by, ahead = decision_hold(self._ix) if markx else (None, None)
            job = due(states, self._db_now, settle=self.settle, every=self.every, gap=self.gap, busy=held_by,
                      plan_every=self.plan_every, kept_missing=self._kept_missing, run_gap=self.run_gap, markx=markx,
                      official_every=self.official_every(),
                      rebuild=bool(self._ix.get("rebuild")) and not self._ix.get("locked"))
            told = held_by.split(" (")[0] if held_by else None
            if told != getattr(self, "_told", None):
                if held_by:
                    log.info("Mark X jobs: a decision run waits for Mark IX (%s)", held_by)
                self._told = told
            if self.fresh and markx:   # after a start (a deploy), the pages readers open first, before any job
                self.fresh = False
                first = [v.job for v in KEPT_VIEWS if v.after_deploy and v.job in self._kept_missing
                         and _kept_may(v, states.get(v.job) or {}, self._db_now, self.gap, after_run=True)]
                if first:
                    log.info("Mark X jobs: after a start, the kept views %s first", "+".join(first))
                    self._run(*first)
                    return first[0]
            if job is None:
                return None
            if job == "decide" and ahead:
                log.warning("Mark X jobs: %s", ahead)
            if job in KEPT:     # every kept view due now, in one process
                self._run(*kept_due(states, self._kept_missing, self._db_now, self.gap, markx=markx))
            else:
                self._run(job)
            if job == "decide":
                self._after_run()
            return job
        except Exception:
            log.exception("Mark X jobs: the tick failed")
            return None

    def official_every(self) -> Optional[float]:
        """The official channels' pass's period, None while INSIGHT_OFFICIAL is off."""
        from insight_core.markx import official
        return None if official.mode() == "off" else OFFICIAL_EVERY

    def _run(self, *names: str) -> None:
        if not names:
            return
        if self.spawn:
            self._in_own_process(*names)
        else:
            for job in names:
                getattr(Jobs(self.db_url, clock=self.clock), job)()

    def _after_run(self) -> None:
        """Right after a decision run, the kept views it left missing that their policy builds now, in one process.
        Never raises into the tick."""
        try:
            states = self._states()
            self._run(*kept_due(states, self._kept_missing, self._db_now, self.gap, after_run=True))
        except Exception:
            log.exception("Mark X jobs: keeping the views after the decision run failed")

    def _in_own_process(self, *names: str) -> None:
        what = "+".join(names)
        process = multiprocessing.get_context("spawn").Process(target=_job_main, args=(self.db_url, *names),
                                                               name=f"markx-{what}", daemon=True)
        process.start()
        process.join(self.hard_limit)
        if process.is_alive():
            process.kill()
            process.join(10)
            log.error("Mark X jobs: the %s run was killed after %.0f s; its transaction rolled back", what, self.hard_limit)
            for job in names:   # several: the one shown running is recorded (one not begun is simply due again)
                self._dead(job, f"killed after {self.hard_limit:.0f} s", always=len(names) == 1)
        elif process.exitcode:
            # a crash (an OOM kill, a segfault) is a killed run: recorded, wanted again, its stage cleared
            log.error("Mark X jobs: the %s run ended with exit code %s", what, process.exitcode)
            for job in names:   # one job alone is recorded even when it never began (no stage to find)
                self._dead(job, f"exited with code {process.exitcode}", unended=len(names) == 1)

    def _dead(self, job: str, error: str, *, always: bool = False, unended: bool = False) -> None:
        """A run whose process ended without finishing: recorded failed (with its stage), wanted again, no stage; so is
        the candidate finder a decision run ran inside it. Ended in the entities stage, the full pass waits for the
        next night. Without `always`, a run that recorded its own end stays as is; with `unended`, a run that never
        recorded its start or end is recorded too."""
        try:
            from insight_core.db import database
            with database.transaction(self.db_url) as cur:
                cur.execute("SELECT job, stage FROM mx_jobs WHERE stage IS NOT NULL AND job = ANY(%s)",
                            ([job, "candidates"] if job == "decide" else [job],))
                stages = dict(cur.fetchall())
                stage = stages.get(job)
                if unended and stage is None:
                    cur.execute("SELECT started_at, finished_at FROM mx_jobs WHERE job = %s", (job,))
                    row = cur.fetchone()
                    always = row is None or row[1] is None or (row[0] is not None and row[1] < row[0])
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
        """The loop in a daemon thread (run_scheduler.py). It runs with Mark X off too, for the reader's kept views;
        the "markx" heartbeat is written only while Mark X is on."""
        if self.thread is not None:
            return False
        self.recover()
        self.fresh = True

        from insight_core.utils import heartbeat

        def beat() -> None:
            if self.on():
                heartbeat.beat("markx")

        def loop() -> None:
            beat()
            while not self.stop.wait(poll):
                self.tick()
                beat()
        self.thread = threading.Thread(target=loop, name="markx-jobs", daemon=True)
        self.thread.start()
        log.info("Mark X jobs: running here, every %.0f s (Mark X %s)", poll, "on" if self.on() else "off: kept views only")
        return True
