#!/usr/bin/env python3
"""
Long-running scheduler for the ingestion container (Mark IX).

Two clocks:
- the ingestion tick, every scheduler_config.ingest_tick_minutes (default 60, floor 15):
  one run_ingestion over all enabled sources. Cadence decides which are due, so a tick only
  touches the sources whose fetch interval has elapsed (or whose backoff has expired).
- daily work, once interval_hours have passed since system_settings.scheduler_state
  .last_daily_work_at: prune job_runs, refresh source cadence, sync sources.json, experts,
  and the daily / topic briefings - in the Mark VIII order, with the briefing code
  untouched. On the first tick after deploy last_daily_work_at is seeded from the newest
  successful scheduler_cycle job, so a deploy does not produce an extra briefing.
  With INSIGHT_ANALYSIS off only the upkeep runs; experts and briefings are skipped and
  recorded as skipped on the scheduler_cycle job.

tick() is the testable unit: it takes its collaborators as arguments.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion import FetchRequest, SourceSelector, Trigger  # noqa: E402
from insight_core.ingestion.ports import JobProgressSink  # noqa: E402
from insight_core.logs.core.logger_config import get_component_logger, setup_logging  # noqa: E402

if TYPE_CHECKING:
    from insight_core.settings import Settings

logger = get_component_logger("run_scheduler")

RUNNING = True
TICK_MINUTES_FLOOR = 15


def _handle_stop(signum, frame):
    global RUNNING
    RUNNING = False


def _parse(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class SchedulerState:
    """Persisted in system_settings['scheduler_state']; served by GET /api/operations/scheduler."""

    last_tick_at: Optional[datetime] = None
    next_tick_at: Optional[datetime] = None
    last_daily_work_at: Optional[datetime] = None
    next_daily_work_at: Optional[datetime] = None

    @staticmethod
    def from_dict(data: Optional[Dict[str, Any]]) -> "SchedulerState":
        data = data or {}
        return SchedulerState(**{f.name: _parse(data.get(f.name)) for f in fields(SchedulerState)})

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {key: value.isoformat() if value else None for key, value in asdict(self).items()}


def _tick_interval(config: Dict[str, Any]) -> timedelta:
    try:
        minutes = float(config.get("ingest_tick_minutes", 60))
    except (TypeError, ValueError):
        minutes = 60.0
    return timedelta(minutes=max(TICK_MINUTES_FLOOR, minutes))


def _daily_interval(config: Dict[str, Any]) -> timedelta:
    try:
        hours = float(config.get("interval_hours", 20))
    except (TypeError, ValueError):
        hours = 20.0
    return timedelta(hours=max(0.25, hours))


async def tick(
    now: datetime,
    state: SchedulerState,
    config: Dict[str, Any],
    *,
    ingest: Callable[..., Awaitable[Any]],
    daily_work: Callable[[Dict[str, Any]], Awaitable[Optional["DailyWorkSummary"]]],
    ops: Any,
) -> SchedulerState:
    """One scheduler wake-up: an ingestion run, then daily work when it is due."""
    last_daily = state.last_daily_work_at
    if last_daily is None:
        try:
            last_daily = _parse(ops.latest_successful_job_finished_at("scheduler_cycle"))
        except Exception:  # noqa: BLE001
            logger.exception("Could not seed the daily-work gate; daily work runs now")
            last_daily = None

    # 1. The ingestion run. The job is finished in every case: a raise marks it failed
    #    instead of leaving it "running" (E5).
    request = FetchRequest(SourceSelector.all(), Trigger.SCHEDULER)
    job_id = None
    try:
        job_id = ops.start_job("ingestion_run", trigger="scheduler",
                               payload={"selector": request.selector.as_dict(), "force": request.force})
    except Exception:  # noqa: BLE001
        logger.exception("Could not start the ingestion_run job (running untracked)")
    status, message, payload = "failed", "Ingestion run did not finish", {}
    try:
        report = await ingest(request, progress=JobProgressSink(ops, job_id))
        status, message, payload = report.job_status, report.summary_line(), report.to_payload()
        logger.info("Ingestion tick: %s", message)
    except Exception as exc:  # noqa: BLE001
        message = f"Ingestion run failed: {exc}"
        logger.exception("Ingestion tick failed")
    finally:
        if job_id:
            try:
                ops.finish_job(job_id, status=status, message=message, payload=payload, compact=True)
            except Exception:  # noqa: BLE001
                logger.exception("Could not finish the ingestion_run job")

    # 2. Daily work, gated on interval_hours since it last ran.
    daily_interval = _daily_interval(config)
    if last_daily is None or now - last_daily >= daily_interval:
        cycle_job_id = None
        try:
            cycle_job_id = ops.start_job("scheduler_cycle", trigger="scheduler", message="Daily work started",
                                         payload={"scheduler": config})
        except Exception:  # noqa: BLE001
            logger.exception("Could not start the scheduler_cycle job")
        cycle_status, cycle_message = "failed", "Daily work did not finish"
        cycle_payload: Dict[str, Any] = {"scheduler": config}
        try:
            summary = await daily_work(config)
            cycle_status, cycle_message = "success", "Daily work completed"
            if summary:
                cycle_payload["daily_work"] = summary.as_payload()
                cycle_message += summary.message_suffix()
        except Exception as exc:  # noqa: BLE001
            cycle_message = str(exc)
            logger.exception("Daily work failed")
        finally:
            if cycle_job_id:
                try:
                    ops.finish_job(cycle_job_id, status=cycle_status, message=cycle_message,
                                   payload=cycle_payload)
                except Exception:  # noqa: BLE001
                    logger.exception("Could not finish the scheduler_cycle job")
        # Advanced even when it failed: a broken briefing must not retry every tick.
        last_daily = now

    new_state = SchedulerState(
        last_tick_at=now,
        next_tick_at=now + _tick_interval(config),
        last_daily_work_at=last_daily,
        next_daily_work_at=last_daily + daily_interval,
    )
    try:
        ops.set_scheduler_state(new_state.as_dict())
    except Exception:  # noqa: BLE001
        logger.exception("Could not persist the scheduler state")
    return new_state


ANALYSIS_STEPS = ("experts", "daily_briefing", "topic_briefing")


@dataclass(frozen=True)
class DailyWorkSummary:
    """What daily work left out and why, recorded on the scheduler_cycle job."""

    skipped: tuple[str, ...] = ()
    reason: Optional[str] = None

    def __bool__(self) -> bool:
        return bool(self.skipped)

    def message_suffix(self) -> str:
        """Appended to "Daily work completed", e.g. " (analysis off: skipped experts, ...)"."""
        return f" ({self.reason}: skipped {', '.join(self.skipped)})" if self.skipped else ""

    def as_payload(self) -> Dict[str, Any]:
        return {"skipped": list(self.skipped), "reason": self.reason}


async def daily_work(db_url: str, operations_service: Any, scheduler_config: Dict[str, Any], *,
                     settings: Optional["Settings"] = None) -> Optional[DailyWorkSummary]:
    """The Mark VIII cycle minus its ingest: prune, cadence, sync, experts, briefings.

    With INSIGHT_ANALYSIS off it stops after the upkeep (no ExpertsService, BriefingService or
    Gemini client is built) and returns which steps it skipped, for the scheduler_cycle job.
    """
    from insight_core.ingestion.enrichment import ANALYSIS_OFF
    from insight_core.ingestion.ports import DbFetchStateStore
    from insight_core.services.source_config_sync_service import SourceConfigSyncService
    from insight_core.settings import get_settings

    settings = settings or get_settings()

    try:
        pruned = operations_service.prune_job_runs(int(os.environ.get("INSIGHT_JOB_RUNS_RETAIN_DAYS", "30")))
        if pruned:
            logger.info("Pruned %s job_runs rows older than the retention window", pruned)
    except Exception:  # noqa: BLE001
        logger.exception("job_runs prune failed (continuing with the daily work)")

    # Once a day: new sources leave probation and mean gaps follow the posts.
    try:
        refreshed = await asyncio.to_thread(DbFetchStateStore(db_url).refresh_cadence)
        logger.info("Cadence refreshed for %s sources", refreshed)
    except Exception:  # noqa: BLE001
        logger.exception("Cadence refresh failed (continuing with stored tiers)")

    if scheduler_config.get("sync_sources_each_cycle", True):
        sync_service = SourceConfigSyncService(db_url)
        sync_result = sync_service.sync_json_to_db(mirror=True)
        logger.info("sources.json -> DB sync result: %s", sync_result)

    if not settings.analysis_enabled:
        logger.info("Analysis is off: skipping %s", ", ".join(ANALYSIS_STEPS))
        return DailyWorkSummary(skipped=ANALYSIS_STEPS, reason=ANALYSIS_OFF)

    from insight_core.services.briefing_service import BriefingService
    from insight_core.services.experts_service import ExpertsService

    # Scheduled experts: each enabled expert with a non-empty schedule runs every cycle.
    # One failing expert is logged and contained; the briefings still run.
    experts_service = ExpertsService(db_url)
    for expert in experts_service.list_scheduled_experts():
        expert_result = await tracked_job(
            operations_service, "expert_briefing",
            {"expert_id": expert["id"], "expert_name": expert["name"]},
            lambda expert_id=expert["id"]: experts_service.generate_expert_briefing(expert_id),
            reraise=False,
        )
        if expert_result is not None:
            logger.info("expert briefing '%s' result: success=%s", expert["name"], expert_result.get("success"))

    if not scheduler_config.get("generate_daily_briefing", True):
        return

    briefing_service = BriefingService(db_url)
    today = datetime.now(timezone.utc).date().isoformat()
    daily_result = await tracked_job(operations_service, "daily_briefing", {"date": today},
                                     lambda: briefing_service.generate_daily_briefing(today, refresh=True))
    logger.info("daily briefing result for %s: success=%s", today, daily_result.get("success"))

    if scheduler_config.get("generate_topic_briefing", False):
        topics_result = await tracked_job(operations_service, "topic_briefing", {"date": today},
                                          lambda: briefing_service.generate_daily_briefing_with_topics(today))
        logger.info("topic briefing result for %s: success=%s", today, topics_result.get("success"))


async def tracked_job(ops: Any, job_type: str, payload: Dict[str, Any],
                      work: Callable[[], Awaitable[Dict[str, Any]]], *, reraise: bool = True
                      ) -> Optional[Dict[str, Any]]:
    """Run one daily-work step as a job_runs row that is finished in every case (E5).

    The result's `success` decides success/failed. A raise finishes the job as failed, then
    propagates (so the scheduler_cycle job fails too) unless reraise=False, which logs it and
    returns None.
    """
    job_id = ops.start_job(job_type, trigger="scheduler", payload=payload)
    try:
        result = await work()
    except Exception as exc:  # noqa: BLE001
        try:
            ops.finish_job(job_id, status="failed", message=str(exc) or type(exc).__name__)
        except Exception:  # noqa: BLE001
            logger.exception("Could not finish the %s job", job_type)
        if reraise:
            raise
        logger.exception("%s failed", job_type)
        return None
    result = result or {}
    ops.finish_job(
        job_id,
        status="success" if result.get("success") else "failed",
        message=result.get("error") or f"Processed {result.get('posts_processed', 0)} posts",
        payload=result,
        compact=True,
    )
    return result


async def main() -> None:
    from insight_core.db.ensure_db import ensure_database
    from insight_core.ingestion import run_ingestion
    from insight_core.services.operations_service import OperationsService

    setup_logging(debug_mode=False)
    db_url = ensure_database()
    os.environ["DATABASE_URL"] = db_url
    operations_service = OperationsService(db_url)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    logger.info("Starting scheduler")
    try:
        state = SchedulerState.from_dict(operations_service.get_scheduler_state())
    except Exception:  # noqa: BLE001
        logger.exception("Could not read the scheduler state; starting fresh")
        state = SchedulerState()

    while RUNNING:
        now = datetime.now(timezone.utc)
        if state.next_tick_at is None or now >= state.next_tick_at:
            config = operations_service.get_scheduler_config()

            async def daily(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                return await daily_work(db_url, operations_service, cfg)

            state = await tick(now, state, config, ingest=run_ingestion, daily_work=daily, ops=operations_service)
            logger.info("Next ingestion tick at %s", state.next_tick_at.isoformat() if state.next_tick_at else "?")
        # Sleep in 1s steps so SIGTERM is honoured promptly.
        await asyncio.sleep(1)

    logger.info("Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
