"""
Operational controls for scheduler config, job history, alerts, and source health.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.sources_service import SourcesService


class OperationsService:
    """Manage operational configuration and runtime telemetry."""

    SETTINGS_KEY_SCHEDULER = "scheduler_config"

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("operations_service")
        self.sources_service = SourcesService(db_url)

    def get_scheduler_config(self) -> Dict[str, Any]:
        defaults = self._default_scheduler_config()
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value, updated_at FROM system_settings WHERE key = %s",
                    (self.SETTINGS_KEY_SCHEDULER,),
                )
                row = cur.fetchone()

        if not row:
            return defaults

        stored = row[0] or {}
        merged = {
            **defaults,
            **stored,
            "updated_at": row[1].isoformat() if row[1] else defaults.get("updated_at"),
        }
        return self._normalize_scheduler_config(merged)

    def update_scheduler_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.get_scheduler_config()
        merged = self._normalize_scheduler_config({**existing, **(config or {})})

        payload = {
            "interval_hours": merged["interval_hours"],
            "sync_sources_each_cycle": merged["sync_sources_each_cycle"],
            "generate_daily_briefing": merged["generate_daily_briefing"],
            "generate_topic_briefing": merged["generate_topic_briefing"],
        }

        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO system_settings (key, value, updated_at)
                    VALUES (%s, %s::jsonb, now())
                    ON CONFLICT (key) DO UPDATE SET
                      value = EXCLUDED.value,
                      updated_at = now()
                    RETURNING updated_at
                    """,
                    (self.SETTINGS_KEY_SCHEDULER, json.dumps(payload)),
                )
                updated_at = cur.fetchone()[0]
            conn.commit()

        merged["updated_at"] = updated_at.isoformat()
        return merged

    def start_job(
        self,
        job_type: str,
        *,
        trigger: str = "manual",
        source_id: Optional[str] = None,
        message: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO job_runs (job_type, status, trigger, source_id, message, payload)
                    VALUES (%s, 'running', %s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (job_type, trigger, source_id, message, json.dumps(self._prepare_payload(payload or {}))),
                )
                job_id = str(cur.fetchone()[0])
            conn.commit()
        return job_id

    def finish_job(
        self,
        job_id: str,
        *,
        status: str,
        message: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE job_runs
                    SET status = %s,
                        message = COALESCE(%s, message),
                        payload = CASE
                          WHEN %s::jsonb = '{}'::jsonb THEN payload
                          ELSE payload || %s::jsonb
                        END,
                        finished_at = now()
                    WHERE id = %s
                    """,
                    (
                        status,
                        message,
                        json.dumps(self._prepare_payload(payload or {})),
                        json.dumps(self._prepare_payload(payload or {})),
                        job_id,
                    ),
                )
            conn.commit()

    def list_recent_jobs(self, limit: int = 30) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      jr.id,
                      jr.job_type,
                      jr.status,
                      jr.trigger,
                      jr.source_id,
                      COALESCE(s.settings->>'display_name', s.handle_or_url),
                      s.platform,
                      jr.message,
                      jr.payload,
                      jr.started_at,
                      jr.finished_at
                    FROM job_runs jr
                    LEFT JOIN sources s ON s.id = jr.source_id
                    ORDER BY jr.started_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()

        jobs: List[Dict[str, Any]] = []
        for row in rows:
            jobs.append(
                {
                    "id": str(row[0]),
                    "job_type": row[1],
                    "status": row[2],
                    "trigger": row[3],
                    "source_id": str(row[4]) if row[4] else None,
                    "source_display_name": row[5],
                    "source_platform": row[6],
                    "message": row[7],
                    "payload": row[8] or {},
                    "started_at": row[9].isoformat() if row[9] else None,
                    "finished_at": row[10].isoformat() if row[10] else None,
                }
            )
        return jobs

    def record_source_status(
        self,
        source_id: str,
        *,
        status: str,
        message: Optional[str] = None,
        trigger: str = "manual",
        fetched_posts: Optional[int] = None,
    ) -> None:
        source = self.sources_service.get_source_with_settings(source_id)
        ops = (source.get("settings") or {}).get("ops", {})
        now_iso = datetime.now(timezone.utc).isoformat()

        next_ops = {
            "last_status": status,
            "last_message": message,
            "last_trigger": trigger,
            "last_checked_at": now_iso,
            "last_fetched_posts": fetched_posts if fetched_posts is not None else ops.get("last_fetched_posts"),
            "last_success_at": now_iso if status == "healthy" else ops.get("last_success_at"),
            "last_error_at": now_iso if status == "error" else ops.get("last_error_at"),
        }
        self.sources_service.merge_source_settings(source_id, {"ops": next_ops})

    def get_operations_overview(self) -> Dict[str, Any]:
        jobs = self.list_recent_jobs(40)
        source_health = self.get_source_health()
        alerts = [
            {
                "id": job["id"],
                "severity": "high",
                "title": job["job_type"],
                "message": job.get("message") or "Job failed",
                "started_at": job["started_at"],
                "source_id": job.get("source_id"),
            }
            for job in jobs
            if job["status"] == "failed"
        ][:8]

        return {
            "success": True,
            "scheduler": self.get_scheduler_config(),
            "jobs": jobs,
            "source_health": source_health,
            "alerts": alerts,
            "stats": {
                "recent_failures": len([job for job in jobs if job["status"] == "failed"]),
                "sources_in_error": len([source for source in source_health if source["status"] == "error"]),
                "sources_monitored": len(source_health),
            },
        }

    def get_source_health(self) -> List[Dict[str, Any]]:
        sources = self.sources_service.get_all_sources_with_settings()
        health_rows: List[Dict[str, Any]] = []
        for source in sources:
            settings = source.get("settings") or {}
            ops = settings.get("ops", {})
            archive = settings.get("archive", {})
            status = ops.get("last_status") or ("healthy" if archive.get("stored_posts") else "unknown")
            health_rows.append(
                {
                    "source_id": source["id"],
                    "display_name": settings.get("display_name") or source["handle_or_url"],
                    "platform": source["platform"],
                    "enabled": source["enabled"],
                    "stored_posts": source.get("post_count", 0),
                    "archive_status": archive.get("status"),
                    "status": status,
                    "last_checked_at": ops.get("last_checked_at") or archive.get("last_live_fetch_at"),
                    "last_success_at": ops.get("last_success_at") or archive.get("last_live_fetch_at"),
                    "last_error_at": ops.get("last_error_at"),
                    "last_message": ops.get("last_message"),
                }
            )

        order = {"error": 0, "running": 1, "healthy": 2, "unknown": 3}
        health_rows.sort(key=lambda row: (order.get(row["status"], 9), row["display_name"].lower()))
        return health_rows

    def _default_scheduler_config(self) -> Dict[str, Any]:
        return self._normalize_scheduler_config(
            {
                "interval_hours": float(os.getenv("INSIGHT_INGEST_INTERVAL_HOURS", "20")),
                "sync_sources_each_cycle": os.getenv("INSIGHT_SYNC_SOURCES_EACH_CYCLE", "true").lower() == "true",
                "generate_daily_briefing": os.getenv("INSIGHT_GENERATE_DAILY_BRIEFING", "true").lower() == "true",
                "generate_topic_briefing": os.getenv("INSIGHT_GENERATE_TOPIC_BRIEFING", "false").lower() == "true",
                "updated_at": None,
            }
        )

    def _normalize_scheduler_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        interval_hours = float(config.get("interval_hours", 20))
        interval_hours = max(0.25, min(interval_hours, 168))
        return {
            "interval_hours": interval_hours,
            "sync_sources_each_cycle": bool(config.get("sync_sources_each_cycle", True)),
            "generate_daily_briefing": bool(config.get("generate_daily_briefing", True)),
            "generate_topic_briefing": bool(config.get("generate_topic_briefing", False)),
            "updated_at": config.get("updated_at"),
        }

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [self._json_safe(item) for item in value]
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:
                return str(value)
        return value

    def _prepare_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._json_safe(self._compact_payload(payload))

    def _compact_payload(self, value: Any, *, parent_key: str | None = None) -> Any:
        if isinstance(value, dict):
            compacted: Dict[str, Any] = {}
            for key, item in value.items():
                if key == "posts":
                    if isinstance(item, dict):
                        compacted[key] = {
                            "count": len(item),
                            "sample_ids": list(item.keys())[:5],
                        }
                    elif isinstance(item, list):
                        compacted[key] = {"count": len(item)}
                    else:
                        compacted[key] = self._compact_payload(item, parent_key=key)
                    continue
                compacted[key] = self._compact_payload(item, parent_key=key)
            return compacted

        if isinstance(value, list):
            if parent_key == "topics":
                summarized = []
                for item in value[:12]:
                    if isinstance(item, dict):
                        summarized.append(
                            {
                                "id": item.get("id"),
                                "title": item.get("title"),
                                "post_count": len(item.get("post_ids", []) or []),
                                "is_outlier": item.get("is_outlier", False),
                            }
                        )
                    else:
                        summarized.append(self._compact_payload(item, parent_key=parent_key))
                if len(value) > 12:
                    summarized.append({"truncated_topics": len(value) - 12})
                return summarized

            if len(value) > 20:
                preview = [self._compact_payload(item, parent_key=parent_key) for item in value[:10]]
                preview.append({"truncated_items": len(value) - 10})
                return preview
            return [self._compact_payload(item, parent_key=parent_key) for item in value]

        if isinstance(value, str):
            limit = 1200 if parent_key not in {"briefing", "summary_markdown", "content", "content_html"} else 600
            if len(value) > limit:
                return value[:limit] + "... [truncated]"
            return value

        return value
