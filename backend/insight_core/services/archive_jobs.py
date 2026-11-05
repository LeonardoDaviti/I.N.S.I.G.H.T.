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
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("insight.archive_jobs")

JOB_TYPE = "archive_source"


class ArchiveJobs:
    def __init__(self, ops: Any, archives: Any, *, trigger: str,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.ops = ops
        self.archives = archives
        self.trigger = trigger            # "manual" (the API) or "scheduler"
        self.clock = clock
        self._running: Dict[str, asyncio.Task] = {}   # source id -> its continuation in this process

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
                  rate_limit_overrides: Optional[Dict[str, Any]] = None, job_id: Optional[str] = None) -> Dict[str, Any]:
        """One archive from its plan. With job_id (the route already started the job) progress lands
        on that job; otherwise the run starts its own. An unavailable kind answers
        {success: false, unavailable: true}; any other failure fails the job and raises."""
        from insight_core.ingestion.kinds.base import KindUnavailable

        job_id = job_id or self.ops.try_start_job(
            JOB_TYPE, trigger=self.trigger, source_id=source_id,
            payload={"resume": resume, "rate_limit": rate_limit_overrides or {}},
        )
        self.ops.try_append_job_event(job_id, message="Archive job started", level="info",
                                      payload={"resume": resume, "rate_limit": rate_limit_overrides or {}})
        try:
            result = await self.archives.archive_source(
                source_id, progress_callback=self._progress(job_id), resume=resume,
                rate_limit_overrides=rate_limit_overrides,
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
