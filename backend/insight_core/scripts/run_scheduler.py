#!/usr/bin/env python3
"""
Long-running ingestion scheduler for the ingestion container.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import get_component_logger, setup_logging
from insight_core.scripts.safe_ingest import safe_ingest_posts
from insight_core.services.briefing_service import BriefingService
from insight_core.services.operations_service import OperationsService
from insight_core.services.source_config_sync_service import SourceConfigSyncService


RUNNING = True


def _handle_stop(signum, frame):
    global RUNNING
    RUNNING = False


async def run_cycle(logger, db_url: str, operations_service: OperationsService, scheduler_config: dict) -> None:
    if scheduler_config.get("sync_sources_each_cycle", True):
        sync_service = SourceConfigSyncService(db_url)
        sync_result = sync_service.sync_json_to_db(mirror=True)
        logger.info("sources.json -> DB sync result: %s", sync_result)

    ingest_job_id = operations_service.start_job("safe_ingest", trigger="scheduler")
    ingest_result = await safe_ingest_posts(trigger="scheduler")
    operations_service.finish_job(
        ingest_job_id,
        status="success" if ingest_result.get("success") else "failed",
        message=ingest_result.get("error") or f"Ingested {ingest_result.get('posts_ingested', 0)} posts",
        payload=ingest_result,
    )
    logger.info("safe_ingest result: %s", ingest_result)

    if not scheduler_config.get("generate_daily_briefing", True):
        return

    briefing_service = BriefingService(db_url)
    today = datetime.now(timezone.utc).date().isoformat()
    daily_job_id = operations_service.start_job("daily_briefing", trigger="scheduler", payload={"date": today})
    daily_result = await briefing_service.generate_daily_briefing(today)
    operations_service.finish_job(
        daily_job_id,
        status="success" if daily_result.get("success") else "failed",
        message=daily_result.get("error") or f"Processed {daily_result.get('posts_processed', 0)} posts",
        payload=daily_result,
    )
    logger.info("daily briefing result for %s: success=%s", today, daily_result.get("success"))

    if scheduler_config.get("generate_topic_briefing", False):
        topics_job_id = operations_service.start_job("topic_briefing", trigger="scheduler", payload={"date": today})
        topics_result = await briefing_service.generate_daily_briefing_with_topics(today)
        operations_service.finish_job(
            topics_job_id,
            status="success" if topics_result.get("success") else "failed",
            message=topics_result.get("error") or f"Processed {topics_result.get('posts_processed', 0)} posts",
            payload=topics_result,
        )
        logger.info("topic briefing result for %s: success=%s", today, topics_result.get("success"))


async def main() -> None:
    setup_logging(debug_mode=False)
    logger = get_component_logger("run_scheduler")

    db_url = ensure_database()
    os.environ["DATABASE_URL"] = db_url
    operations_service = OperationsService(db_url)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    logger.info("Starting scheduler")
    while RUNNING:
        scheduler_config = operations_service.get_scheduler_config()
        interval_hours = float(scheduler_config.get("interval_hours", 20))
        sleep_seconds = max(60, int(interval_hours * 3600))
        cycle_started = datetime.now(timezone.utc).isoformat()
        logger.info("Scheduler cycle started at %s", cycle_started)
        cycle_job_id = operations_service.start_job(
            "scheduler_cycle",
            trigger="scheduler",
            message="Scheduler cycle started",
            payload={"scheduler": scheduler_config},
        )
        try:
            await run_cycle(logger, db_url, operations_service, scheduler_config)
            operations_service.finish_job(
                cycle_job_id,
                status="success",
                message="Scheduler cycle completed",
                payload={"scheduler": scheduler_config},
            )
        except Exception as exc:
            operations_service.finish_job(
                cycle_job_id,
                status="failed",
                message=str(exc),
                payload={"scheduler": scheduler_config},
            )
            logger.exception("Scheduler cycle failed: %s", exc)

        if not RUNNING:
            break

        logger.info("Scheduler sleeping for %ss", sleep_seconds)
        for _ in range(sleep_seconds):
            if not RUNNING:
                break
            await asyncio.sleep(1)

    logger.info("Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
