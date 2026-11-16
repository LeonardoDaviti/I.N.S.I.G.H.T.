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
        start's story job), at most one every RUN_GAP seconds (a steady stream of uploads can't push it back, nor run
        it back to back), and every EVERY seconds. v10.18 (0199): RUN_GAP 15 minutes (was GAP's 5): a worker's answers
        stream in all day, and every run they started cost ~145 s and a ~35 s Labels build on the server (~11 an hour,
        ~60% of a core); the same decisions for the same inputs, at most 15 minutes after the answers instead of 5.
  - **The order of runs** (0121 Decided 3): no decision run while Mark IX's story job holds its lock (a batch): it
    waits, then runs once. Nor while the candidate finder runs; and a run whose own candidate finder failed doesn't
    run on candidates that aren't there: both wait. A rule change's rebuild holds no run (`decision_hold`, the one
    decision: the runner, the story job's stepping aside and /api/status's health ask it): the run goes ahead on the
    stories as stored (each rebuild batch commits whole, so they are always one consistent set; the batches after it
    change some and the next run decides those again), logged and recorded in its `last`. Before, a rebuild held
    every decision run until its end (0121), then until an hour after the last start (0209: on 2026-11-14 neither ran
    for 45 hours, the story job stepping aside for the run the rebuild held); 0215: not at all, the rebuild being
    ~5x faster.
  - **A rule change's rebuild is driven here too** (0209, the job "stories"): while one is due or in progress, the
    story job's next slice (stories_service.recompute: STEP_BUDGET_S, then it rests) STORIES_GAP after the last
    ended, in a process of its own, Mark X on or off. Before, only a fetch that saved posts ran it (hourly: ~3
    minutes of an hour, about two days for the server's 158k posts).
  - **A decision run has a time limit and stage logs** (0112 Decided 12): "Mark X decision run started", each stage
    with its duration (candidates, load, questions and decisions, write, connections, graph, back, headlines, news,
    entities, surges, perspectives_plan), the finish. Past LIMIT seconds it stops before the next stage and logs which;
    its one transaction rolls back (nothing half done) and the run is wanted again. A stage that never ends is killed
    with its process at HARD_LIMIT. 0215: a full run (decide's code changed by a deploy, no kept state, the nightly
    one) and the run after one that stopped over its limit have CATCH_UP_LIMIT instead (`limit_for`): a stopped run
    also rolls back the state the next run starts from, so the next one was the same full run, stopped again, for ever
    (the server after the v10.20 deploy: 121-126 s runs, 92-93 s of them reading the whole window).
  - **A run that dies is a failed run** (v10.13.9): killed at HARD_LIMIT or ended with a non-zero exit code (an OOM
    kill, a segfault), it is recorded with the stage it was in and wanted again. A stage shown for longer than
    HARD_LIMIT + STALE_MARGIN is a dead run's (`stale`): the runner clears it, so nothing waits on it until a restart.
    0209: so is a run that started and never recorded an end (started_at after finished_at, no stage: a restart
    cleared its stage before v10.19.1's `recover` recorded it) older than that: recorded as ended, wanted again.
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
    again after its backoff). v10.18 (0199): only when wanted: a Labels page opened while the newest run's queue is
    not kept marks it (labels.ask: jobs.want), and the view's policy (KEPT_VIEWS, when="wanted") builds it only then,
    so a run nobody labels after costs no build. It is a whole decision reading (labels.population): it was built in insight-api before,
    whose RSS then stayed at the build's high-water mark. The API reads only the kept queue (labels.kept).
  - **Mark X News is kept here too** (0198, the job "news"): its two views (news.keep_pages) built in the same
    after-run step as the Labels queue, and again when what the page reads between runs changed (a label, a
    sectioning or placement, a headline answered, Mark IX's News), at most every REBUILD_GAP seconds. The API sends
    the kept view while its inputs are the same, else builds the page as before (never stale, never fails).
  - **One mechanism, a policy per view** (0198): `KEPT_VIEWS` lists the kept views (`KeptView`: its job, how the
    runner tells it is missing, `when` it is built: "always" or only when "wanted", and how often `between_runs`);
    `due` and the after-run step (`Runner._after_run`) both ask `kept_due`, and the views due are built one after the
    other in one process.
  - **Wave 2 of the kept views** (0206): "tracks" (the topic tracks' pages and suggestions, after placing the changed
    tracks again; at most every 120 s once the worker's verdicts moved them), "unread" (the unread counts, at most
    every UNREAD_GAP once a read, a post or a story moved them), "main_source" (Discover's main-source list and its
    web tests, when an open found it behind) and "discover" (Discover's answer and its first page's web reads, when
    an open found it due): built here, never in the API. The reader's views (KeptView.markx False: unread,
    main_source, discover) are kept with Mark X off too: the loop then runs for them alone.
  - **A job that keeps failing backs off** (0188): mx_jobs.failures counts its failed runs in a row (a run that
    raised, stopped over LIMIT, was killed at HARD_LIMIT, crashed, or was found dead); the next try waits
    GAP x 2^failures seconds after the failed run's end, at most MAX_BACKOFF (6 hours), and goes on at that pace;
    from FAILING_AFTER failures on the job shows as failing (`view`, /api/status's health). One decision makes it:
    `held`, asked by `due` for every job. Before, a failed run was wanted again and ran at the next look (30 s after
    a crash or a kill) or after GAP: the same run over and over.
  - **Official channels** (0196, the job "official"): markx/official.run, every OFFICIAL_EVERY seconds while
    INSIGHT_OFFICIAL is not off, in a process of its own (its reads of the web, its judgements' questions, its adds);
    bounded by its own budgets (events, test reads, web searches a pass) and resumable (its state in Postgres).
  - **No job waits forever behind the others** (0209): `due` takes the jobs in order (plan, decide, the rebuild's
    slice, the kept views, candidates, official), but a candidates run or an official pass due for STARVE_AFTER
    goes before the kept views (which can be due at every look: the unread counts every 30 s).
  - **A decision run over LIMIT twice in a row in the same stage skips it once** (0188): when that stage can be
    deferred (SKIPPABLE: a stage after the run's own decisions), the next run defers it (logged, in the run's
    `deferred` counts and the job's `skipped_stages`) instead of repeating the identical run; the run after it
    tries the stage again.

Both only when INSIGHT_MARKX is on; nothing here raises into the scheduler.
"""
from __future__ import annotations

import logging
import multiprocessing
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from insight_core.utils import peak

log = logging.getLogger(__name__)

POLL = 30.0                      # seconds between the runner's looks (work is picked up within this)
SETTLE = 60.0                    # a decision run waits this long after work arrived, so a burst of uploads is one run
GAP = 300.0                      # a failed job's backoff unit (0188: GAP x 2^failures)
RUN_GAP = 900.0                  # 0199: at most one decision run starts every 15 minutes while uploads stream in (was GAP)
EVERY = 3600.0                   # and runs at least hourly
LIMIT = 120.0                    # a decision run over this stops between stages, writes nothing, retries (Decided 12)
CATCH_UP_LIMIT = 600.0           # 0215: a full run's, and the next run's after one stopped over its limit (`limit_for`)
ENTITY_BUDGET = 45.0             # 0128: the entities stage's own seconds, outside LIMIT; its full pass resumes next run
OWN_BUDGET = ("entities",)       # the stages whose time LIMIT doesn't count
MENTIONS_MARGIN = timedelta(minutes=2)   # entities committed by a transaction that began before the last run's start
FIRST_SINCE = timedelta(days=1)          # the first candidates run looks back this far for new entities
WAIT_PAGE = 1000                 # v10.14: waiting posts a candidates run reads (the rest: the next run, wanted at once)
HARD_LIMIT = 900.0               # a job's process is killed after this (a stage that never ends); the run rolls back
STALE_MARGIN = 120.0             # v10.13.9: a stage older than HARD_LIMIT + this is a dead run's (`stale`): cleared
JOBS = ("candidates", "decide", "plan", "labels", "news", "tracks", "unread", "main_source", "discover", "official",
        "stories")
STORIES_GAP = 120.0              # 0209: a rebuild's next slice starts this long after the last ended (it rests 90 s after a yield)
ORIGINALS_GAP = 1800.0           # 0216: the originals follow a wanted story run at most this often (hourly fetches: each)
STARVE_AFTER = 900.0             # 0209: candidates or official due this long go before the kept views
OFFICIAL_EVERY = 1800.0          # 0196: the official channels' pass at most every 30 minutes
REBUILD_GAP = 60.0               # 0198: News whose inputs changed between runs is built again at most this often
UNREAD_GAP = 30.0                # 0206: the unread counts whose inputs changed are counted again at most this often
PLAN_EVERY = 300.0               # v10.13.4: the background planners (tasks.BACKGROUND_PLANNED) run at most every 5 min
MAX_BACKOFF = 6 * 3600.0         # 0188: a failing job is tried at least every 6 hours, never more often than its backoff
FAILING_AFTER = 3                # 0188: this many failed runs in a row show the job as failing
SKIPPABLE = ("graph", "back", "later", "entities", "surges", "perspectives_plan")   # 0188: stages a run may defer


@dataclass(frozen=True)
class KeptView:
    """0182, 0198: a view the jobs process keeps: one mechanism (the after-run step, `due`'s kept views), a policy per
    view.
      - `job`: its Jobs method and its mx_jobs row (its state, backoff and record);
      - `missing(cur, now)`: whether it is not kept for its inputs now (the runner asks it at every look);
      - `when`: "always" (built after each decision run and whenever missing) or "wanted" (built only when its job is
        wanted since its last build: mx_jobs.wanted_at, set by `want(cur, job)`; the build's start clears it);
      - `between_runs`: None (missing between runs means a new run or a deploy: built at once), or the seconds a view
        whose inputs change between runs waits from its last build's start before it is built again;
      - `markx` (0206): a Mark X view, kept only while Mark X is on; False: a reader's view (the unread counts,
        Discover), kept whether Mark X is on or off (the runner's loop runs for these alone when it is off);
      - `pages`: the kept pages (mx_kept_pages.page) its builds write."""
    job: str
    missing: Callable[[Any, datetime], bool]
    when: str = "always"
    between_runs: Optional[float] = None
    markx: bool = True
    pages: Tuple[str, ...] = ()   # 0206: the mx_kept_pages pages its builds write (a reader's view: the reader's rows)


def _news_missing(cur: Any, now: datetime) -> bool:
    from insight_core.markx import news
    return news.kept_missing(cur, now)


def _labels_missing(cur: Any, now: datetime) -> bool:
    from insight_core.markx import labels
    return labels.missing(cur)


def _tracks_missing(cur: Any, now: datetime) -> bool:
    from insight_core.markx import tracks
    return tracks.kept_missing(cur, now)


def _unread_missing(cur: Any, now: datetime) -> bool:
    from insight_core.services.reader_service import unread_missing
    return unread_missing(cur)


def _main_source_missing(cur: Any, now: datetime) -> bool:
    from insight_core.services.discover_main_source import kept_missing
    return kept_missing(cur, now)


def _wanted(cur: Any, now: datetime) -> bool:
    """A view whose work is its job's being wanted (Discover's: the API marks it when its answer is due again or its
    first page asks for the web's reads); the job itself tells what is left to do."""
    return True


# the kept views, built in this order in one process after a decision run (News first: a page the owner waits on)
KEPT_VIEWS = (KeptView("news", _news_missing, between_runs=REBUILD_GAP),    # 0198
              KeptView("labels", _labels_missing, when="wanted"),           # 0182; 0199: when a Labels page asked
              KeptView("tracks", _tracks_missing, between_runs=120.0),      # 0206: tracks.KEPT_GAP
              KeptView("unread", _unread_missing, between_runs=UNREAD_GAP, markx=False, pages=("unread",)),
              KeptView("main_source", _main_source_missing, when="wanted", markx=False, pages=("main_source",)),
              KeptView("discover", _wanted, when="wanted", markx=False))   # 0206: the reader's views
KEPT = tuple(v.job for v in KEPT_VIEWS)


def reader_rows(cur: Any) -> int:
    """0206: the rows the reader's kept views (KeptView.markx False) hold in the jobs process's tables: their mx_jobs
    rows and their pages' mx_kept_pages rows. The kept views' machinery is shared by Mark X and the reader, so these
    live under mx_ although they are not Mark X's (the real-data check's `markx.ix_unchanged` tells them apart)."""
    jobs = [v.job for v in KEPT_VIEWS if not v.markx] + ["stories"]   # 0209: Mark IX's rebuild slices too
    pages = [p for v in KEPT_VIEWS if not v.markx for p in v.pages]
    cur.execute("""SELECT (SELECT count(*) FROM mx_jobs WHERE job = ANY(%s))
                          + (SELECT count(*) FROM mx_kept_pages WHERE page = ANY(%s))""", (jobs, pages))
    return int(cur.fetchone()[0])


def readers(job: Optional[str]) -> bool:
    """0206: whether `job` is a reader's kept view (KeptView.markx False), not Mark X's; 0209: or Mark IX's rebuild
    slice ("stories")."""
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
    """0216: Mark IX's story job is wanted (a fetch run that saved posts, the API's start, a voice change): the runner
    runs it within POLL seconds (`due`), in a process of its own, with the originals after it (`Jobs.stories`). The
    posts are already queued (migration 0059's triggers). One short transaction; never raises. Returns whether it
    was marked."""
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
    """The jobs as /api/markx/status, /api/status and the /markx page show them: each {running, started_at, stage,
    stage_at (the running stage's start), wanted_at (work waiting for a run), finished_at, last (how the last run
    ended), failures (failed runs in a row), failing (FAILING_AFTER or more), retry_at (a failed job's next try after
    its backoff, or null)}; times ISO 8601 UTC."""
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
    """0188: the seconds a job waits after a failed run's end before it is tried again: GAP x 2^failures, at most
    MAX_BACKOFF; 0 when its last run did not fail."""
    n = int(s.get("failures") or 0)
    return 0.0 if n <= 0 else min(gap * 2 ** min(n, 32), MAX_BACKOFF)


def held(s: Dict[str, Any], now: datetime, gap: float = GAP) -> bool:
    """0188, the one backoff decision: whether a job whose last runs failed is still waiting out its backoff (from the
    failed run's end; its start when no end is recorded). `due` asks it for every job."""
    wait = backoff(s, gap)
    end = s.get("finished_at") or s.get("started_at")
    return bool(wait) and end is not None and (now - end).total_seconds() < wait


def failing(s: Dict[str, Any]) -> bool:
    """0188: a job shown as failing (FAILING_AFTER failed runs in a row or more); it is still tried at its backoff."""
    return int(s.get("failures") or 0) >= FAILING_AFTER


# ---- the runner's side: the jobs (in insight-ingestion) ---------------------------------------------

def mark_ix(cur: Any) -> Dict[str, Any]:
    """Mark IX's story job as a decision run sees it (0121 Decided 3, 0209): {locked: its lock is held now (a batch
    regrouping posts), rebuild: "in progress" (its progress in the story job's setting) | "due" (the stored rows are
    of other rules than this code's) | None, and a rebuild's done, total (posts regrouped, of), phase, started_at}."""
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
        elif value.get("rules") and rebuild_due(value):   # 0216: some part of the rules changed
            out["rebuild"] = "due"
    return out


def mark_ix_busy(cur: Any) -> Optional[str]:
    """Why work that reads Mark IX's stories waits for it now, or None (0121 Decided 3): its story job holds its lock,
    or a rule change's rebuild is in progress or due. The source stats run waits so; a decision run asks
    `decision_hold` (0215: a rebuild holds none)."""
    ix = mark_ix(cur)
    if ix["locked"]:
        return "Mark IX's story job is running"
    return f"a rule change's rebuild is {ix['rebuild']}" if ix["rebuild"] else None


def limit_for(kind: Optional[str], previous: Dict[str, Any], limit: float = LIMIT,
              catch_up: float = CATCH_UP_LIMIT) -> float:
    """0215, a decision run's time limit: `catch_up` for a full run (`kind`: decide.run says which once it has read its
    state; None before) and for the run after one that stopped over its limit (`previous`: the decide job's last
    record), else `limit`. A run over its limit writes nothing, and with it the state the next run starts from (0169),
    so the next run is the same one: after the v10.20 deploy (decide's code changed: a full run) the server's runs read
    their whole window again each time (questions and decisions 92-93 s, two days after the last run) and stopped at
    121-126 s, for ever. A full run reads everything by design; it now has the time to, and the runs after it are
    incremental again."""
    if kind == "full" or previous.get("stopped_before"):
        return max(limit, catch_up)
    return limit


def decision_hold(ix: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """0209, 0215, the one decision on whether Mark IX holds a decision run now: (held, ahead). `held`: the story job's
    lock (a batch, its seconds), else None. `ahead`: during a rule change's rebuild (due or in progress), that the run
    goes ahead on the stories as stored (logged, kept in the run's record), else None. `ix`: mark_ix's.
    0215: a rebuild holds no run (0209 held one until an hour after the last start, 0121 until the rebuild's end).
    Every rebuild batch commits whole, so the stories as stored are always one consistent set, read by a run in one
    snapshot; the next run decides again what later batches change. So a run comes every RUN_GAP, as without a
    rebuild, and the rebuild itself now takes about 1.5-2 h of the server's posts (0215), not 9-10 h."""
    if ix.get("locked"):
        return "Mark IX's story job is running", None
    if not ix.get("rebuild"):
        return None, None
    what = f"a rule change's rebuild is {ix['rebuild']}"
    if ix.get("total"):
        what += f" ({int(ix.get('done') or 0):,} of {int(ix['total']):,} posts regrouped)"
    return None, f"{what}: the decision run goes ahead on the stories as stored"


def held_by_mark_ix(cur: Any) -> Optional[str]:
    """0209: why Mark IX holds a decision run now (`decision_hold`), or None; /api/status's health names it."""
    return decision_hold(mark_ix(cur))[0]


def decision_waits(cur: Any, now: datetime, wait: float) -> bool:
    """v10.13.8, 0209: whether Mark IX's story job steps aside now for a decision run: Mark X is on, the run is wanted,
    not running, not waiting out a failed run's backoff, and has waited `wait` seconds or more (since it was wanted or
    last started). 0209: stepping aside for a run the rebuild held stopped both for 45 hours on 2026-11-14; 0215: no
    rebuild holds a run (`decision_hold`), so the run it steps aside for can start."""
    if not enabled():
        return False
    d = state(cur)["decide"]
    wanted, started = d.get("wanted_at"), d.get("started_at")
    if wanted is None or d.get("stage") is not None or held(d, now):
        return False
    since = max(wanted, started) if started is not None else wanted
    return (now - since).total_seconds() >= wait


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
                 entity_budget: Optional[float] = ENTITY_BUDGET, catch_up: float = CATCH_UP_LIMIT) -> None:
        self.db_url, self.clock, self.limit, self.entity_budget = db_url, clock, limit, entity_budget
        self.catch_up = catch_up

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
        """The run ended: no stage, the outcome in `last`; `again` wants the job once more (a failed run is retried,
        after its backoff). 0188: a failed run (`ok` false, not skipped for another run's lock) counts one more
        failure in a row; a run that ended well clears the count."""
        failed = last.get("ok") is False and not last.get("skipped")
        with self._tx() as cur:
            cur.execute("INSERT INTO mx_jobs (job) VALUES (%s) ON CONFLICT (job) DO NOTHING", (job,))
            cur.execute("""UPDATE mx_jobs SET stage = NULL, stage_at = NULL, finished_at = now(), last = %s::jsonb,
                                  wanted_at = CASE WHEN %s THEN COALESCE(wanted_at, now()) ELSE wanted_at END,
                                  failures = CASE WHEN %s THEN failures + 1 WHEN %s THEN 0 ELSE failures END
                            WHERE job = %s""", (_json(last), again, failed, last.get("ok") is True, job))

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
        out["track_places"] = self._keep_track_places()
        try:   # 0210: the open tasks of the kinds no feature reads, closed (kept, with the reason)
            from insight_core.markx import consumers
            with self._tx() as cur:
                out["not_asked"] = consumers.close_off(cur)
        except Exception as exc:  # noqa: BLE001 - tried again at the next plan
            log.exception("Mark X jobs: closing the tasks no feature reads failed")
            out["not_asked"] = {"error": str(exc)[:300]}
        return out

    def _keep_track_places(self) -> Dict[str, Any]:
        """Issue 0195: after the track planner, the topic tracks whose inputs changed placed again (track_kept.refresh),
        so the sidebar counts, suggestions and track pages read kept placements while a worker answers. In a savepoint
        of its own transaction; a failure is logged and recorded as `failed`, never failing the plan (a track not kept
        is placed live by its readers, never wrong)."""
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
        """0196: one pass of official channels (markx/official.run), its counts and this process's peak memory
        recorded; a failed pass is tried again after its backoff."""
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

    def labels(self) -> Optional[Dict[str, Any]]:
        """0182: the newest decision run's Labels queue, built and kept (labels.keep) in one REPEATABLE READ
        transaction of its own; a failure is recorded and the job tried again after GAP. Its seconds and this
        process's peak memory are recorded with it (mx_label_queues, mx_jobs.last)."""
        from insight_core.markx import decide, labels as mx_labels
        t0 = time.monotonic()
        self._begin("labels", "building")
        try:
            with decide.snapshot(self.db_url) as cur:
                out = mx_labels.keep(cur, now=self.clock(), peak=peak.mb)
        except Exception as exc:
            log.exception("Mark X labels: building the queue failed; tried again later")
            self._finish("labels", {"ok": False, "error": str(exc)[:500], "seconds": round(time.monotonic() - t0, 1)},
                         again=True)   # 0199: still wanted (its start cleared the mark), tried after its backoff
            return None
        seconds = round(time.monotonic() - t0, 1)
        log.info("Mark X labels: the queue of run %s kept in %.1f s (%s items, peak %.0f MB)", out.get("run"), seconds,
                 out.get("items", "already"), peak.mb())
        self._finish("labels", {"ok": True, "seconds": seconds, "peak_mb": peak.mb(),
                                **{k: v for k, v in out.items() if k != "seconds"}})
        return out

    def news(self) -> Optional[Dict[str, Any]]:
        """0198: Mark X News' views not kept for their inputs, built and kept (news.keep_pages) in one REPEATABLE READ
        transaction of its own; a failure is recorded and the job tried again after its backoff (the API builds the
        page meanwhile, as before). Its seconds and this process's peak memory are recorded with it."""
        from insight_core.markx import news as mx_news
        return self._keep("news", lambda cur: mx_news.keep_pages(cur, now=self.clock()))

    def _keep(self, job: str, keep: Callable[[Any], Dict[str, Any]], *, snapshot: bool = True,
              again: bool = False) -> Optional[Dict[str, Any]]:
        """0198, 0206: one kept view's build: `keep(cur)` (the owning module's) in one REPEATABLE READ transaction of
        its own (`snapshot`; else `keep(None)` opens its own); a failure is recorded and the job tried again after its
        backoff (`again`: wanted again; the API builds or sends the older page meanwhile, as before). Its seconds and
        this process's peak memory are recorded with it. Then the kept inputs' logged changes folded
        (kept_pages.compact), in a transaction of their own."""
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
        """0206: the topic tracks whose inputs changed placed again (track_kept.refresh, in its own transaction), then
        the track pages and the suggestions not kept for their inputs built and kept (tracks.keep_pages)."""
        from insight_core.markx import tracks as mx_tracks
        self._keep_track_places()
        subtopics = self._keep_track_subtopics()
        out = self._keep("tracks", lambda cur: mx_tracks.keep_pages(cur, now=self.clock()))
        return None if out is None else {**out, "subtopics": subtopics}

    def _keep_track_subtopics(self) -> Dict[str, Any]:
        """0207: the topic tracks whose posts in the track changed clustered into their sub-topics again
        (track_subtopics.refresh), in a transaction of its own, before the pages are kept. A failure is logged and
        recorded as `failed`, never failing the pages (they show the last sub-topics)."""
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
        """0206: the unread counts counted and kept for their inputs (reader_service.keep_unread_counts)."""
        from insight_core.services.reader_service import keep_unread_counts
        return self._keep("unread", keep_unread_counts)

    def main_source(self) -> Optional[Dict[str, Any]]:
        """0206: Discover's main-source list built and kept, its shown channels tested over the web (at most once in
        CHECK_DAYS each), and kept again with their tests (services/discover_main_source.keep). In this process, never
        the API's."""
        from insight_core.services.discover_main_source import keep
        return self._keep("main_source", lambda _cur: keep(self.db_url), snapshot=False)

    def discover(self) -> Optional[Dict[str, Any]]:
        """0206: Discover's answer built again when it is due (its inputs or code changed, or it is REFRESH_AFTER old)
        and its first page's web reads (the follow tests, the titles), which build it again when they read anything
        (services/discover_reads.keep). In this process, never the API's."""
        from insight_core.services.discover_reads import keep
        return self._keep("discover", lambda _cur: keep(self.db_url), snapshot=False)

    def stories(self) -> Optional[Dict[str, Any]]:
        """Mark IX's story job (stories_service.recompute_safely: its bounded steps for STEP_BUDGET_S, then it yields
        and rests, or steps aside for a waiting decision run), in this process: 0209, the next slice of a rule change's
        rebuild; 0216, its only driver: a run wanted by a fetch that saved posts (`want_stories`; the ingestion run used
        to run it inline, after its fetch, 132-388 s of every hourly run on the server), the API's start or a voice
        change, then the originals the new stories lack and Mark X's scout and research ticks (`after_stories`, in
        that order, as after the fetch before). A wanted run that yielded or stepped aside is wanted again (its queue
        waits). Its summary, the rebuild's progress and this process's peak memory are recorded with it."""
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
        """0216: after a wanted story run, in its process: the originals its stories lack, asked within their budget
        (issues 0114, 0123), then Mark X's scouts and research runs advanced (0148, 0162; markx/scout.with_scouts). They
        read its stories, so they follow it. Never raises. Returns each one's seconds."""
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
        """The candidate finder, then one decision run in its own snapshot, LIMIT seconds at most (both count), each
        stage logged with its duration; a failed or stopped run is wanted again. 0215: a full run, and the run after one
        stopped over its limit, have CATCH_UP_LIMIT (`limit_for`)."""
        from insight_core.markx import decide
        with self._tx() as cur:
            before = state(cur)["decide"]
            ahead = decision_hold(dict(mark_ix(cur), locked=False))[1]   # 0209
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
        current = ["candidates", t0]
        own = [0.0]                           # 0128: the seconds of the stages with a budget of their own
        limit = [limit_for(None, previous, self.limit, self.catch_up)]   # 0215: the kind's, once the run knows it
        if limit[0] > self.limit:
            log.warning("Mark X decision run: the last one stopped over its limit; this one has %.0f s", limit[0])

        def kind(name: str) -> None:
            limit[0] = limit_for(name, previous, self.limit, self.catch_up)
            if name == "full":
                log.info("Mark X decision run: a full run, %.0f s at most", limit[0])

        def stage(name: str) -> None:
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

        if self.candidates() is None:   # 0121 Decided 3: never on candidates that aren't there
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
            # the retry waits out the failed run's backoff (0188: GAP x 2^failures), not the next 30 s look (0124);
            # over the limit in the same deferrable stage as the run before, the next run skips that stage once
            over_in = stages[-1][0] if stages else None
            skip_next = over_in if (over_in in SKIPPABLE and not skip and previous.get("stopped_before")
                                    and previous.get("over_in") == over_in) else None
            log.warning("Mark X decision run %s; nothing written, it runs again after its backoff%s", exc,
                        f"; over the limit in {over_in} twice in a row: the next run skips it" if skip_next else "")
            self._finish("decide", {"ok": False, "error": str(exc), "stopped_before": str(exc).split("stopped before ", 1)[-1],
                                    "over_in": over_in, **({"skip_next": skip_next} if skip_next else {}),
                                    **({"skipped_stages": skip} if skip else {}),
                                    "stages": stages, "seconds": round(time.monotonic() - t0, 1),
                                    "limit": limit[0], "peak_mb": peak.mb()}, again=True)
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
                                "skipped": out.get("skipped"), "stages": stages, "limit": limit[0],
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
    """The job to run now, or None: a decision run SETTLE seconds after work arrived or EVERY seconds after the last
    one started (or never ran), never within RUN_GAP seconds of the last start, never while Mark IX holds it (`busy`:
    why, from `decision_hold`) nor while the candidate finder runs (0121 Decided 3); else the candidate finder when
    vectors arrived. v10.13.4: with `plan_every`, the background planners ("plan") first when they last started that
    long ago (or never), so a decision run that keeps failing never stops the planning; a decision run still follows.
    0209: then, while a rule change's rebuild is due or in progress (`rebuild`), its next slice ("stories") at most
    STORIES_GAP after the last one ended.
    0182, 0198: then a kept view (`KEPT_VIEWS`) not kept for its inputs (`kept_missing`) that its policy lets start
    (`_kept_may`).
    0188: a job whose last runs failed first waits out its backoff (`held`: GAP x 2^failures after the failed run's
    end, at most MAX_BACKOFF), whatever else makes it due.
    0206: `markx` False (Mark X off): only the rebuild's slice and the kept views that are not Mark X's
    (KeptView.markx False).
    0209: the candidate finder or the official channels' pass due for `starve_after` seconds goes before the kept
    views, which can be due at every look: before, they ran only when nothing else was due."""
    slice_due = stories_due(states.get("stories") or {}, now, rebuild=rebuild, gap=gap)
    if not markx:
        if slice_due:
            return "stories"
        return next((v.job for v in KEPT_VIEWS if not v.markx and v.job in kept_missing
                     and _kept_may(v, states.get(v.job) or {}, now, gap)), None)
    p = states.get("plan") or {}
    if plan_every is not None and states["candidates"]["stage"] is None and not held(p, now, gap) and (
            p.get("started_at") is None or (now - p["started_at"]).total_seconds() >= plan_every):
        return "plan"
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
        return "official"     # 0196: after everything else that is due
    return None


def stories_due(s: Dict[str, Any], now: datetime, *, rebuild: bool, gap: float = GAP) -> bool:
    """Mark IX's story job may start now (`s`: its state): not running, not waiting out a failed run's backoff, and
    0216: wanted (posts saved: `want_stories`), at once (within POLL) unless its last run yielded or stepped aside
    (then STORIES_GAP after it, past its rest); 0209: or a rule change's rebuild due or in progress (`rebuild`, the
    lock free), STORIES_GAP after the last run ended."""
    if s.get("stage") is not None or held(s, now, gap):
        return False
    last = s.get("last") or {}
    since = None if s.get("finished_at") is None else (now - s["finished_at"]).total_seconds()
    rested = since is None or since >= STORIES_GAP
    if s.get("wanted_at") is not None and (rested or not (last.get("yielded") or last.get("skipped"))):
        return True
    return rebuild and rested


def _kept_may(view: KeptView, s: Dict[str, Any], now: datetime, gap: float, *, after_run: bool = False) -> bool:
    """A missing kept view's build may start (`s`: its job's state): not running, not waiting out a failed build's
    backoff (0188; was: GAP after its start, every time), wanted when its policy says "wanted"; between runs (not
    `after_run`), a view with `between_runs` at most that often from its last build's start."""
    if s.get("stage") is not None or held(s, now, gap):
        return False
    if view.when == "wanted" and s.get("wanted_at") is None:
        return False
    started = s.get("started_at")
    return (after_run or view.between_runs is None or started is None
            or (now - started).total_seconds() >= view.between_runs)


def kept_due(states: Dict[str, Dict[str, Any]], missing: Iterable[str], now: datetime, gap: float = GAP, *,
             after_run: bool = False, markx: bool = True) -> List[str]:
    """The kept views to build now, in KEPT_VIEWS' order: missing and let start by their policy (`_kept_may`); with
    Mark X off (`markx` False), only those that are not Mark X's (0206)."""
    missing = set(missing)
    return [v.job for v in KEPT_VIEWS if (markx or not v.markx)
            and v.job in missing and _kept_may(v, states.get(v.job) or {}, now, gap, after_run=after_run)]


def stale(states: Dict[str, Dict[str, Any]], now: datetime, *, after: float = HARD_LIMIT + STALE_MARGIN) -> List[str]:
    """v10.13.9: the jobs shown running whose stage began more than `after` seconds ago. No run lives that long (its
    process is killed at HARD_LIMIT), so such a stage is a run that died without a word: due() would wait on it
    forever (the candidate finder's stage holds back every decision run and plan).
    0209: and the runs that started more than `after` seconds ago and never recorded an end, with no stage (`unended`:
    a restart cleared the stage before `recover` recorded the end; the server's decision run of 2026-11-14 09:56)."""
    return [job for job, s in states.items()
            if (s.get("stage") is not None and s.get("stage_at") is not None
                and (now - s["stage_at"]).total_seconds() > after)
            or (unended(s) and (now - s["started_at"]).total_seconds() > after)]


def unended(s: Dict[str, Any]) -> bool:
    """0209: a run that started and recorded no end, shown as not running (no stage): started_at after finished_at."""
    started, finished = s.get("started_at"), s.get("finished_at")
    return s.get("stage") is None and started is not None and (finished is None or finished < started)


def _job_main(db_url: str, *names: str) -> None:
    """A child process: its jobs, one after the other, then exit (what they read goes back to the OS). 0215: each job's
    peak memory counted from its own start (utils/peak: the kept views due together share this process)."""
    from insight_core.logs.core.logger_config import setup_logging
    setup_logging(debug_mode=False)
    for job in names:
        peak.reset()
        getattr(Jobs(db_url), job)()


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

    def _states(self, markx: bool = True) -> Dict[str, Dict[str, Any]]:
        from insight_core.db import database
        with database.transaction(self.db_url) as cur:
            cur.execute("SELECT now()")
            self._db_now = cur.fetchone()[0]
            self._ix = mark_ix(cur)   # 0209: the rebuild's slices run with Mark X off too
            self._kept_missing = self._missing(cur, self._db_now, markx)
            return state(cur)

    @staticmethod
    def _missing(cur: Any, now: datetime, markx: bool = True) -> List[str]:
        """0182, 0198: the kept views (`KEPT_VIEWS`) not kept for their inputs now (a view that can't be told is not
        listed); 0206: with Mark X off, of the views that are not Mark X's only."""
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
        """At the runner's start: a run a restart ended mid-way shows no stage, its end is recorded (0209: before, only
        its stage was cleared, so it showed started after its last end, for ever) and its job is wanted again. Not a
        failure: a restart (a deploy) ended it, not its work."""
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
        """A stale run (`stale`): recorded as dead, wanted again, its stage cleared (only if the row still shows that
        stage, or that start with no end: a run that moved on meanwhile is alive). `s` is updated as due() should see
        it. A stale stage is a failed run; a run with no stage and no end (`unended`, a restart cleared its stage) is
        recorded as ended, not as a failure (its last record kept, with the error)."""
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
        with database.transaction(self.db_url) as cur:
            cur.execute("""UPDATE mx_jobs SET stage = NULL, stage_at = NULL, finished_at = now(), last = %s::jsonb,
                                  wanted_at = COALESCE(wanted_at, now()), failures = failures + 1
                            WHERE job = %s AND stage = %s AND stage_at = %s
                        RETURNING wanted_at, finished_at, failures""",
                        (_json({"ok": False, "error": error, "stage": s["stage"]}), job, s["stage"], s["stage_at"]))
            row = cur.fetchone()
        if row:
            log.error("Mark X jobs: the %s run shown in stage %s since %s is dead (%s); wanted again",
                      job, s["stage"], s["stage_at"], error)
            s.update(stage=None, stage_at=None, wanted_at=row[0], finished_at=row[1], failures=row[2])

    def tick(self) -> Optional[str]:
        """One look: the job that ran, or None."""
        markx = self.on()   # 0206: with Mark X off, the reader's kept views only (KeptView.markx False)
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
            if job is None:
                return None
            if job == "decide" and ahead:
                log.warning("Mark X jobs: %s", ahead)
            if job in KEPT:     # 0198: every kept view due now, in one process
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
        """0196: the official channels' pass's period, None while INSIGHT_OFFICIAL is off."""
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
        """0182, 0198, the one after-run step: right after a decision run, the kept views it left missing that their
        policy builds now (`kept_due(..., after_run=True)`: News always, then the Labels queue), in one process of
        their own (a failed or skipped run leaves none to build). Never raises into the tick."""
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
            # v10.13.9: a crash (an OOM kill's -9, a segfault) is a killed run: recorded, wanted again, its stage
            # cleared. Before, it only logged and the stage stayed set, so due() waited for it until a restart.
            log.error("Mark X jobs: the %s run ended with exit code %s", what, process.exitcode)
            for job in names:   # 0209: one job alone is recorded even when it never began (no stage to find)
                self._dead(job, f"exited with code {process.exitcode}", unended=len(names) == 1)

    def _dead(self, job: str, error: str, *, always: bool = False, unended: bool = False) -> None:
        """A run whose process ended without finishing: {"ok": False, error, the stage it was in}, wanted again, no
        stage; so is the candidate finder a decision run was running inside it. Ended in the entities stage, the full
        pass waits for the next night. Without `always`, a run that recorded its own end (no stage left) stays as is;
        0209: with `unended`, a run that never recorded its start or its end is recorded too (a job whose first write
        failed: before, nothing was recorded and it was due again at the next look, for ever)."""
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
        """The loop in a daemon thread (run_scheduler.py). 0206: it runs with Mark X off too, for the reader's kept
        views alone (the unread counts, Discover); the heartbeat "markx" is written only while Mark X is on."""
        if self.thread is not None:
            return False
        self.recover()

        from insight_core.utils import heartbeat

        def beat() -> None:
            if self.on():
                heartbeat.beat("markx")         # 0188: the loop is alive (the healthcheck, /api/status)

        def loop() -> None:
            beat()
            while not self.stop.wait(poll):
                self.tick()
                beat()
        self.thread = threading.Thread(target=loop, name="markx-jobs", daemon=True)
        self.thread.start()
        log.info("Mark X jobs: running here, every %.0f s (Mark X %s)", poll, "on" if self.on() else "off: kept views only")
        return True
