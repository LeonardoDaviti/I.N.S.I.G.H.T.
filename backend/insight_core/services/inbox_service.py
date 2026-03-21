"""Analyst inbox orchestration: batch generation, queue reads, and item detail."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import psycopg

from insight_core.db.repo_inbox import InboxRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.inbox_ranking import (
    INBOX_RANKING_VERSION,
    MIN_POST_PRIORITY_SCORE,
    MIN_STORY_PRIORITY_SCORE,
    score_post_candidate,
    score_story_candidate,
)
from insight_core.services.operations_service import OperationsService
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.stories_service import StoriesService


class InboxService:
    """Generate and serve the analyst inbox queue."""

    def __init__(
        self,
        db_url: str,
        *,
        operations_service: OperationsService | None = None,
        stories_service: StoriesService | None = None,
        post_detail_service: PostDetailService | None = None,
    ):
        self.db_url = db_url
        self.repo = InboxRepository(db_url)
        self.logger = get_component_logger("inbox_service")
        self.operations_service = operations_service or OperationsService(db_url)
        self.stories_service = stories_service or StoriesService(db_url)
        self.post_detail_service = post_detail_service or PostDetailService(db_url)

    # ===============================
    # BATCH GENERATION
    # ===============================

    def rebuild_inbox(
        self,
        *,
        generated_for_date: date | str | None = None,
        scope_type: str = "daily_queue",
        scope_value: str | None = None,
        limit: int = 20,
        actor_id: str | None = None,
    ) -> Dict[str, Any]:
        target_date = self._parse_date(generated_for_date) or datetime.now(timezone.utc).date()
        queue_limit = max(1, min(int(limit or 20), 100))
        now = datetime.now(timezone.utc)
        job_id = self._start_job(target_date, scope_type=scope_type, scope_value=scope_value, limit=queue_limit)

        try:
            self._append_job_event(
                job_id,
                message=f"Starting inbox rebuild for {target_date.isoformat()}",
                level="info",
            )
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    superseded = self.repo.supersede_batches(
                        cur,
                        scope_type=scope_type,
                        generated_for_date=target_date,
                        scope_value=scope_value,
                    )

                    batch_id = self.repo.create_batch(
                        cur,
                        {
                            "scope_type": scope_type,
                            "scope_value": scope_value,
                            "generated_for_date": target_date,
                            "status": "building",
                            "metadata": {
                                "ranking_version": INBOX_RANKING_VERSION,
                                "generated_by": actor_id or "system",
                                "requested_limit": queue_limit,
                                "scope_type": scope_type,
                                "scope_value": scope_value,
                                "generated_for_date": target_date.isoformat(),
                            },
                        },
                    )

                    story_rows = self.repo.list_story_candidates(cur, limit=200)
                    story_candidates = self._score_story_candidates(story_rows, now=now)
                    story_candidates = [
                        candidate
                        for candidate in story_candidates
                        if candidate["priority_score"] >= MIN_STORY_PRIORITY_SCORE
                    ]
                    stories_present = bool(story_candidates)

                    post_rows = self.repo.list_post_candidates(
                        cur,
                        since=now - timedelta(days=7),
                        limit=250,
                    )
                    post_candidates = self._score_post_candidates(
                        post_rows,
                        now=now,
                        stories_present=stories_present,
                    )
                    post_candidates = [
                        candidate
                        for candidate in post_candidates
                        if candidate["priority_score"] >= MIN_POST_PRIORITY_SCORE
                    ]

                    selected_candidates = self._sort_candidates(
                        story_candidates + post_candidates,
                    )[:queue_limit]

                    selected_story_count = sum(1 for candidate in selected_candidates if candidate["target_type"] == "story")
                    selected_post_count = sum(1 for candidate in selected_candidates if candidate["target_type"] == "post")

                    items: List[Dict[str, Any]] = []
                    for position, candidate in enumerate(selected_candidates, start=1):
                        item_payload = {
                            "batch_id": batch_id,
                            "target_type": candidate["target_type"],
                            "target_id": candidate["target_id"],
                            "status": "pending",
                            "priority_score": candidate["priority_score"],
                            "novelty_score": candidate["novelty_score"],
                            "evidence_score": candidate["evidence_score"],
                            "duplication_penalty": candidate["duplication_penalty"],
                            "source_priority_score": candidate["source_priority_score"],
                            "reason_summary": candidate["reason_summary"],
                            "reasons": candidate["reasons"],
                            "surfaced_at": now,
                            "metadata": {
                                **candidate["metadata"],
                                "batch_id": batch_id,
                                "target_type": candidate["target_type"],
                                "target_id": candidate["target_id"],
                                "queue_position": position,
                                "queue_limit": queue_limit,
                            },
                        }
                        item_id = self.repo.insert_item(cur, item_payload)
                        items.append(
                            {
                                "id": item_id,
                                **item_payload,
                            }
                        )

                    batch_metadata = {
                        "ranking_version": INBOX_RANKING_VERSION,
                        "generated_by": actor_id or "system",
                        "requested_limit": queue_limit,
                        "scope_type": scope_type,
                        "scope_value": scope_value,
                        "generated_for_date": target_date.isoformat(),
                        "superseded_previous_batches": superseded,
                        "candidate_counts": {
                            "stories": len(story_rows),
                            "story_selected": len(story_candidates),
                            "posts": len(post_rows),
                            "post_selected": len(post_candidates),
                            "selected_total": len(selected_candidates),
                            "selected_story_items": selected_story_count,
                            "selected_post_items": selected_post_count,
                        },
                    }
                    self.repo.update_batch(
                        cur,
                        batch_id,
                        status="ready",
                        item_count=len(selected_candidates),
                        metadata=batch_metadata,
                    )
                conn.commit()
        except Exception as exc:
            self._finish_job(job_id, status="failed", message=str(exc), payload={"error": str(exc)})
            raise

        self._finish_job(
            job_id,
            status="success",
            message=f"Inbox rebuilt with {len(selected_candidates)} item(s)",
            payload={
                "batch_id": batch_id,
                "item_count": len(selected_candidates),
                "story_candidates": len(story_candidates),
                "post_candidates": len(post_candidates),
            },
        )

        return self.get_batch(batch_id=batch_id)

    # ===============================
    # READ API
    # ===============================

    def get_inbox(self, *, batch_id: str | None = None, limit: int = 20) -> Dict[str, Any]:
        if batch_id is not None:
            return self.get_batch(batch_id=batch_id, limit=limit)
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                batch = self.repo.get_latest_batch(cur)
                if not batch:
                    return {"success": True, "batch": None, "items": [], "total": 0}
                items = self.repo.list_items(cur, batch_id=batch["id"], limit=limit)

        return {
            "success": True,
            "batch": batch,
            "items": items,
            "total": len(items),
        }

    def get_batch(self, *, batch_id: str, limit: int | None = None) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                batch = self.repo.get_batch_by_id(cur, batch_id)
                if not batch:
                    return {"success": False, "error": f"Batch {batch_id} not found", "batch": None, "items": [], "total": 0}
                items = self.repo.list_items(cur, batch_id=batch_id, limit=limit or batch["item_count"] or 100)

        return {
            "success": True,
            "batch": batch,
            "items": items,
            "total": len(items),
        }

    def list_batches(self, *, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                batches = self.repo.list_batches(cur, limit=limit, offset=offset)
        return {"success": True, "batches": batches, "total": len(batches)}

    def get_item_detail(self, item_id: str) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                item = self.repo.get_item_by_id(cur, item_id)
                if not item:
                    return {"success": False, "error": f"Inbox item {item_id} not found", "item": None, "target": None, "actions": []}

                target = self._resolve_target_detail(item)
                actions = self.repo.get_actions_for_target(cur, item["target_type"], str(item["target_id"]))

        return {
            "success": True,
            "item": item,
            "target": target,
            "actions": actions,
        }

    def list_items(
        self,
        *,
        batch_id: str | None = None,
        status: str | None = None,
        target_type: str | None = None,
        source_id: str | None = None,
        generated_for_date: date | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        target_date = self._parse_date(generated_for_date)
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                items = self.repo.list_items(
                    cur,
                    batch_id=batch_id,
                    status=status,
                    target_type=target_type,
                    source_id=source_id,
                    generated_for_date=target_date,
                    limit=limit,
                    offset=offset,
                )
        return {"success": True, "items": items, "total": len(items)}

    def list_actions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        target_type: str | None = None,
        target_id: str | None = None,
        inbox_item_id: str | None = None,
    ) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                actions = self.repo.list_actions(
                    cur,
                    limit=limit,
                    offset=offset,
                    target_type=target_type,
                    target_id=target_id,
                    inbox_item_id=inbox_item_id,
                )
        return {"success": True, "actions": actions, "total": len(actions)}

    # ===============================
    # INTERNAL HELPERS
    # ===============================

    def _resolve_target_detail(self, item: Dict[str, Any]) -> Any:
        target_type = item.get("target_type")
        target_id = str(item.get("target_id"))
        if target_type == "post":
            return self.post_detail_service.get_post_by_id(target_id)
        if target_type == "story":
            return self.stories_service.get_story_detail(target_id)
        return None

    def _score_story_candidates(self, rows: List[Dict[str, Any]], *, now: datetime) -> List[Dict[str, Any]]:
        by_id: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            signals: List[str] = []
            if self._is_new_story(row, now):
                signals.append("new_story")
            if self._is_material_story_update(row, now):
                signals.append("story_update")
            if not signals:
                continue

            candidate = by_id.setdefault(
                str(row["id"]),
                {
                    **row,
                    "target_type": "story",
                    "target_id": str(row["id"]),
                    "signals": [],
                },
            )
            for signal in signals:
                if signal not in candidate["signals"]:
                    candidate["signals"].append(signal)

        scored: List[Dict[str, Any]] = []
        for candidate in by_id.values():
            scored_candidate = score_story_candidate(candidate, now=now)
            if scored_candidate:
                scored.append(self._with_item_metadata(candidate, scored_candidate))
        return scored

    def _score_post_candidates(
        self,
        rows: List[Dict[str, Any]],
        *,
        now: datetime,
        stories_present: bool,
    ) -> List[Dict[str, Any]]:
        scored: List[Dict[str, Any]] = []
        for row in rows:
            candidate = {
                **row,
                "target_type": "post",
                "target_id": str(row["id"]),
            }
            scored_candidate = score_post_candidate(candidate, now=now, stories_present=stories_present)
            if scored_candidate:
                scored.append(self._with_item_metadata(candidate, scored_candidate))
        return scored

    def _with_item_metadata(self, candidate: Dict[str, Any], ranked: Dict[str, Any]) -> Dict[str, Any]:
        source_id = candidate.get("source_id")
        source_display_name = candidate.get("source_display_name")
        if candidate.get("target_type") == "story":
            source_id = source_id or candidate.get("anchor_source_id")
            source_display_name = source_display_name or candidate.get("anchor_source_display_name")
        metadata = {
            **ranked["metadata"],
            "candidate": {
                **ranked["metadata"].get("candidate", {}),
                "source_id": source_id,
                "source_display_name": source_display_name,
            },
        }
        return {
            **candidate,
            **ranked,
            "metadata": metadata,
        }

    def _sort_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        type_order = {"story": 0, "post": 1}
        return sorted(
            candidates,
            key=lambda item: (
                -float(item.get("priority_score", 0.0)),
                -float(item.get("novelty_score", 0.0)),
                type_order.get(item.get("target_type", ""), 9),
                str(item.get("target_id")),
            ),
        )

    def _is_new_story(self, row: Dict[str, Any], now: datetime) -> bool:
        reference = self._latest_datetime(row.get("first_seen_at"), row.get("created_at"))
        if reference is None:
            return False
        return (now - reference).total_seconds() <= 72 * 3600

    def _is_material_story_update(self, row: Dict[str, Any], now: datetime) -> bool:
        latest_update = self._latest_datetime(row.get("latest_update_date"), row.get("last_seen_at"))
        if latest_update is None:
            return False
        if (now - latest_update).total_seconds() > 72 * 3600:
            return False
        update_count = int(row.get("update_count") or 0)
        latest_importance = float(row.get("latest_update_importance") or 0.0)
        return update_count > 0 and (latest_importance >= 0.5 or update_count >= 2)

    def _latest_datetime(self, *values: Any) -> datetime | None:
        datetimes: List[datetime] = []
        for value in values:
            if isinstance(value, datetime):
                datetimes.append(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
            elif isinstance(value, date):
                datetimes.append(datetime(value.year, value.month, value.day, tzinfo=timezone.utc))
        if not datetimes:
            return None
        return max(datetimes)

    def _parse_date(self, value: date | str | None) -> date | None:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)

    def _start_job(self, target_date: date, *, scope_type: str, scope_value: str | None, limit: int) -> str | None:
        try:
            return self.operations_service.start_job(
                "analyst_inbox_rebuild",
                trigger="manual",
                message=f"Rebuild inbox for {target_date.isoformat()}",
                payload={
                    "scope_type": scope_type,
                    "scope_value": scope_value,
                    "generated_for_date": target_date.isoformat(),
                    "limit": limit,
                },
            )
        except Exception:
            return None

    def _append_job_event(self, job_id: str | None, *, message: str, level: str = "info") -> None:
        if not job_id:
            return
        try:
            self.operations_service.append_job_event(job_id, message=message, level=level)
        except Exception:
            return

    def _finish_job(self, job_id: str | None, *, status: str, message: str, payload: Dict[str, Any]) -> None:
        if not job_id:
            return
        try:
            self.operations_service.finish_job(job_id, status=status, message=message, payload=payload)
        except Exception:
            return
