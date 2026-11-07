"""Archive jobs (the archive_source rows in job_runs): run one, and continue the ones that wait.

An archive that a host limits twice in a row ends its leg waiting (issue 0107): its job's status
becomes `waiting`, with `waiting_until` in the payload, and nothing is finished. The scheduler
process continues each waiting job once its time has come (continue_due, every few seconds), on
the same job row, so the job view tells the whole archive. A Resume by hand continues it at once
(continue_job). A job is claimed atomically (waiting -> running), so only one process continues it;
the claim also makes it that process's job (`trigger`), so a restart of the other process does not
call it interrupted.

`archives` is the SourceFetchService (archive_source / continue_archive); `ops` the
OperationsService.

The queue (issue 0130 B5, C): an archive job can be `queued`, its request (resume, until, pacing) in its payload
with `queued_at` and its `lane`. A lane is "telegram" (every Telegram kind), "nitter" (X through Nitter), else the
source's host: one archive per lane runs at a time (never two Telegram or two Nitter archives at once), at most
QUEUE_PARALLEL from the queue together. The scheduler process starts the queued ones whose lane is free
(start_queued, with continue_due); the API queues an archive whose Telegram or Nitter lane is busy instead of
starting it, and "Resume interrupted archives" queues every source whose last archive a restart interrupted. A
queued archive the scheduler was running when it stopped is queued again at its start, and resumes from its
checkpoint.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("insight.archive_jobs")

JOB_TYPE = "archive_source"
QUEUED = "queued"
QUEUE_PARALLEL = 3          # archives from the queue running at once (the owner's runs of 2026-11-07: 3)
TELEGRAM_KINDS = frozenset({"telegram_mtproto", "telegram_rss"})
NITTER_KINDS = frozenset({"nitter_rss"})
# The jobs of a lane that hold it: running, or waiting out a limit (it goes on by itself).
_HOLDING = ("running", "waiting")


def lane_of(kind_name: str, host: str) -> str:
    """The lane an archive runs in: "telegram", "nitter", else its host ("host:<key>")."""
    if kind_name in TELEGRAM_KINDS:
        return "telegram"
    if kind_name in NITTER_KINDS:
        return "nitter"
    return f"host:{host}"


def exclusive(lane: str) -> bool:
    """A lane the API never starts a second archive in by hand (Telegram's session, Nitter's bridges)."""
    return lane in ("telegram", "nitter")


class ArchiveQueue:
    """The queued archive jobs in job_runs (blocking; call it in a thread). Every check and its write run under
    advisory locks: the source's (the one start_job_unless_running takes), the lane's, and the queue's."""

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url

    @staticmethod
    def _lock(cur: Any, key: str) -> None:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))

    @staticmethod
    def _lane_busy(cur: Any, lane: str) -> bool:
        cur.execute("SELECT 1 FROM job_runs WHERE job_type = %s AND status = ANY(%s) AND payload->>'lane' = %s LIMIT 1",
                    (JOB_TYPE, list(_HOLDING), lane))
        return cur.fetchone() is not None

    def add(self, source_id: str, *, lane: str, payload: Dict[str, Any], trigger: str = "manual",
            queue: bool = True, message: str = "Archive") -> Tuple[Optional[str], str]:
        """A job for the source: queued (`queue`, or its exclusive lane is busy), else running now. (None, status)
        when the source already has one running, waiting or queued."""
        from insight_core.db import database as db
        from insight_core.utils.json_safe import iso

        with db.transaction(self.db_url) as cur:
            self._lock(cur, f"job_runs:{JOB_TYPE}:{source_id}")
            self._lock(cur, f"archive_lane:{lane}")
            cur.execute("SELECT status FROM job_runs WHERE job_type = %s AND source_id = %s AND status = ANY(%s) LIMIT 1",
                        (JOB_TYPE, source_id, [*_HOLDING, QUEUED]))
            held = cur.fetchone()
            if held is not None:
                return None, held[0]
            status = QUEUED if queue or (exclusive(lane) and self._lane_busy(cur, lane)) else "running"
            cur.execute("SELECT now()")
            now = cur.fetchone()[0]
            body = {**payload, "lane": lane, **({"queued_at": iso(now)} if status == QUEUED else {})}
            cur.execute(
                "INSERT INTO job_runs (job_type, status, trigger, source_id, message, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING id::text",
                (JOB_TYPE, status, trigger, source_id, "Queued" if status == QUEUED else message, json.dumps(body)))
            return cur.fetchone()[0], status

    def claim(self, *, trigger: str, parallel: int = QUEUE_PARALLEL) -> List[Dict[str, Any]]:
        """queued -> running, oldest first, for each job whose lane is free, while fewer than `parallel` queued jobs
        run: [{id, source_id, payload}]."""
        from insight_core.db import database as db

        claimed: List[Dict[str, Any]] = []
        with db.transaction(self.db_url) as cur:
            self._lock(cur, "archive_queue")
            cur.execute("SELECT count(*) FROM job_runs WHERE job_type = %s AND status = ANY(%s) AND payload ? 'queued_at'",
                        (JOB_TYPE, list(_HOLDING)))
            running = int(cur.fetchone()[0])
            cur.execute("SELECT id::text, source_id::text, payload FROM job_runs WHERE job_type = %s AND status = %s "
                        "ORDER BY payload->>'queued_at', created_at", (JOB_TYPE, QUEUED))
            taken: set = set()
            for job_id, source_id, payload in cur.fetchall():
                if running >= parallel:
                    break
                lane = str((payload or {}).get("lane") or f"source:{source_id}")
                if lane in taken:
                    continue
                self._lock(cur, f"archive_lane:{lane}")
                if self._lane_busy(cur, lane):
                    continue
                cur.execute("UPDATE job_runs SET status = 'running', trigger = %s, started_at = now(), message = 'Archive' "
                            "WHERE id = %s AND status = %s RETURNING id", (trigger, job_id, QUEUED))
                if cur.fetchone() is None:
                    continue
                taken.add(lane)
                running += 1
                claimed.append({"id": job_id, "source_id": source_id, "payload": payload or {}})
        return claimed

    def requeue(self, trigger: str) -> int:
        """At the scheduler's start: the queued archives it was running when it stopped are queued again (they
        resume from their checkpoints). Returns how many."""
        from insight_core.db import database as db

        with db.transaction(self.db_url) as cur:
            cur.execute("UPDATE job_runs SET status = %s, payload = payload || '{\"resume\": true}'::jsonb "
                        "WHERE job_type = %s AND status = 'running' AND trigger = %s AND payload ? 'queued_at' "
                        "AND NOT payload ? 'waits'", (QUEUED, JOB_TYPE, trigger))
            return cur.rowcount or 0

    def interrupted(self) -> List[Dict[str, Any]]:
        """The sources whose newest archive job a restart interrupted (not a linked fetch): [{source_id, payload}]."""
        from insight_core.db import database as db

        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("""SELECT source_id::text, status, payload FROM (
                               SELECT DISTINCT ON (source_id) source_id, status, payload FROM job_runs
                               WHERE job_type = %s AND source_id IS NOT NULL ORDER BY source_id, started_at DESC) last
                           WHERE status = 'interrupted' AND NOT coalesce((payload->>'linked')::boolean, false)""",
                        (JOB_TYPE,))
            return [{"source_id": row[0], "payload": row[2] or {}} for row in cur.fetchall()]

    def queued(self) -> List[Dict[str, Any]]:
        """The queued jobs, oldest first: [{id, source_id, lane, queued_at}]."""
        from insight_core.db import database as db

        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT id::text, source_id::text, payload->>'lane', payload->>'queued_at' FROM job_runs "
                        "WHERE job_type = %s AND status = %s ORDER BY payload->>'queued_at', created_at", (JOB_TYPE, QUEUED))
            return [{"id": r[0], "source_id": r[1], "lane": r[2], "queued_at": r[3]} for r in cur.fetchall()]


class ArchiveJobs:
    def __init__(self, ops: Any, archives: Any, *, trigger: str,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.ops = ops
        self.archives = archives
        self.trigger = trigger            # "manual" (the API) or "scheduler"
        self.clock = clock
        self._running: Dict[str, asyncio.Task] = {}   # source id -> its continuation in this process
        self._queue: Optional[ArchiveQueue] = None

    @property
    def queue(self) -> ArchiveQueue:
        if self._queue is None:
            self._queue = ArchiveQueue(self.ops.db_url)
        return self._queue

    def _progress(self, job_id: Optional[str]) -> Callable[[Dict[str, Any]], None]:
        def record(event: Dict[str, Any]) -> None:
            self.ops.try_append_job_event(
                job_id,
                message=str(event.get("message") or event.get("stage") or "Archive progress"),
                level=event.get("level") or "info",
                progress=event.get("progress"),
                payload=event,
            )
        return record

    async def run(self, source_id: str, *, resume: bool = True,
                  rate_limit_overrides: Optional[Dict[str, Any]] = None, job_id: Optional[str] = None,
                  linked: bool = False, until: Optional[str] = None) -> Dict[str, Any]:
        """One archive from its plan. With job_id (the route already started the job) progress lands
        on that job; otherwise the run starts its own. An unavailable kind answers
        {success: false, unavailable: true}; any other failure fails the job and raises.

        `linked` (issue 0084 B): instead of the archive, read the source's own pages its stored posts
        link and no post is (SourceFetchService.fetch_linked). It is an archive job of the source, so
        one runs at a time, and a host's limit waits and is continued as any archive's."""
        from insight_core.ingestion.kinds.base import KindUnavailable

        job_id = job_id or self.ops.try_start_job(
            JOB_TYPE, trigger=self.trigger, source_id=source_id,
            payload={"resume": resume, "rate_limit": rate_limit_overrides or {}, **({"linked": True} if linked else {})},
        )
        self.ops.try_append_job_event(job_id, message="Fetching linked pages" if linked else "Archive job started",
                                      level="info", payload={"resume": resume, "rate_limit": rate_limit_overrides or {},
                                                             **({"linked": True} if linked else {})})
        try:
            if linked:
                result = await self.archives.fetch_linked(source_id, progress_callback=self._progress(job_id))
            else:
                result = await self.archives.archive_source(
                    source_id, progress_callback=self._progress(job_id), resume=resume,
                    rate_limit_overrides=rate_limit_overrides, **({"until": until} if until else {}),
                )
        except KindUnavailable as e:
            self.ops.try_finish_job(job_id, status="failed", message=f"Unavailable: {e.reason}",
                                    payload={"source_id": source_id, "unavailable": True})
            return {"success": False, "error": e.reason, "unavailable": True, "source_id": source_id}
        except Exception as e:
            self.ops.try_finish_job(job_id, status="failed", message=str(e), payload={"source_id": source_id})
            raise
        self._end_leg(job_id, result)
        return result

    async def continue_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Claim a waiting job and continue its archive now; None when it is not waiting (another
        process has it, or it ended)."""
        claimed = self.ops.claim_waiting_job(job_id, trigger=self.trigger)
        if not claimed:
            return None
        source_id = claimed["source_id"]
        try:
            result = await self.archives.continue_archive(source_id, claimed["payload"],
                                                          progress_callback=self._progress(job_id))
        except Exception as e:
            self.ops.try_finish_job(job_id, status="failed", message=str(e), payload={"source_id": source_id})
            raise
        self._end_leg(job_id, result)
        return result

    def waiting_job_for(self, source_id: str) -> Optional[str]:
        """The source's archive job when it is waiting, else None."""
        latest = self.ops.latest_job_for_source(JOB_TYPE, source_id)
        return latest["id"] if latest and latest.get("status") == "waiting" else None

    async def continue_due(self) -> List[str]:
        """Start continuing every waiting job whose time has come (the scheduler calls this every
        few seconds); returns the job ids started. Each runs as its own task: an archive leg can
        take hours and must not hold the ingestion tick."""
        started = []
        for job in self.ops.due_waiting_jobs(JOB_TYPE, self.clock()):
            source_id = job["source_id"]
            if source_id in self._running:
                continue
            task = asyncio.create_task(self._continue_logged(job["id"]))
            self._running[source_id] = task
            task.add_done_callback(lambda _t, sid=source_id: self._running.pop(sid, None))
            started.append(job["id"])
        if started:
            await asyncio.sleep(0)   # let them claim their jobs
        return started

    # ------------------------------------------------------------------ the queue (issue 0130)

    def lane(self, source_id: str) -> str:
        """The source's archive lane (lane_of its kind and host); "source:<id>" when the archives can't say."""
        sources, kinds = getattr(self.archives, "sources_service", None), getattr(self.archives, "kinds", None)
        if sources is None or kinds is None:
            return f"source:{source_id}"
        source = sources.get_source_by_id(source_id)
        if not source:
            raise LookupError(f"Source {source_id} not found")
        kind = kinds.resolve(source)
        return lane_of(kind.name, kind.host_key(source))

    def request_payload(self, *, resume: bool, rate_limit: Optional[Dict[str, Any]] = None,
                        until: Optional[str] = None) -> Dict[str, Any]:
        return {"resume": resume, "rate_limit": rate_limit or {}, **({"until": until} if until else {})}

    def enqueue(self, source_id: str, *, resume: bool = True, until: Optional[str] = None,
                rate_limit: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], str]:
        """Queue an archive of the source (blocking): (job id, "queued"), or (None, the status it already has)."""
        return self.queue.add(source_id, lane=self.lane(source_id), trigger=self.trigger,
                              payload=self.request_payload(resume=resume, rate_limit=rate_limit, until=until))

    def resume_interrupted(self) -> List[Dict[str, Any]]:
        """Queue every source whose last archive a restart interrupted, to resume from its checkpoint with the same
        horizon (blocking): [{source_id, job_id, status}]."""
        queued = []
        for row in self.queue.interrupted():
            payload = row["payload"]
            try:
                job_id, status = self.enqueue(row["source_id"], resume=True, until=payload.get("until") or None,
                                              rate_limit=payload.get("rate_limit") or None)
            except LookupError:
                continue
            queued.append({"source_id": row["source_id"], "job_id": job_id, "status": status})
        return queued

    async def start_queued(self) -> List[str]:
        """Start the queued archives whose lane is free (the scheduler calls this with continue_due); each runs as
        its own task, as a continuation does. Returns the job ids started."""
        claimed = await asyncio.to_thread(self.queue.claim, trigger=self.trigger)
        started = []
        for job in claimed:
            payload = job["payload"]
            task = asyncio.create_task(self._run_queued(job["source_id"], job["id"], payload))
            self._running[job["source_id"]] = task
            task.add_done_callback(lambda _t, sid=job["source_id"]: self._running.pop(sid, None))
            started.append(job["id"])
        return started

    async def _run_queued(self, source_id: str, job_id: str, payload: Dict[str, Any]) -> None:
        try:
            await self.run(source_id, resume=bool(payload.get("resume", True)),
                           rate_limit_overrides=payload.get("rate_limit") or None, job_id=job_id,
                           until=payload.get("until") or None)
        except Exception:  # noqa: BLE001 - the job is failed already; the scheduler goes on
            logger.exception("Queued archive job %s failed", job_id)

    async def idle(self) -> None:
        """Wait for every continuation this process started (tests, and a clean stop)."""
        while self._running:
            await asyncio.gather(*list(self._running.values()), return_exceptions=True)
            await asyncio.sleep(0)   # the done callbacks that drop them run on the next loop pass

    async def _continue_logged(self, job_id: str) -> None:
        try:
            await self.continue_job(job_id)
        except Exception:  # noqa: BLE001 - the job is failed already; the scheduler goes on
            logger.exception("Continuing archive job %s failed", job_id)

    def _end_leg(self, job_id: Optional[str], result: Dict[str, Any]) -> None:
        """A leg's end: waiting keeps the job open; anything else finishes it."""
        if not job_id:
            return
        if result.get("waiting"):
            try:
                self.ops.wait_job(job_id, message=result.get("message") or "Waiting", payload=result)
            except Exception:  # noqa: BLE001
                logger.exception("Could not mark archive job %s waiting", job_id)
            return
        # An archive run is not a live fetch: it does not touch source_fetch_state, so paging old
        # posts can neither delay the next live fetch nor reset its backoff. A paused archive
        # (issue 0016) is a success whose message says why it paused.
        self.ops.try_finish_job(
            job_id,
            status="success" if result.get("success") else "failed",
            message=result.get("error") or result.get("message") or f"Archived {result.get('posts_fetched', 0)} posts",
            payload=result,
        )
