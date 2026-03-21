"""Durable analyst actions over inbox targets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg

from insight_core.db.repo_inbox import InboxRepository
from insight_core.db.repo_sources import SourcesRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.stories_service import StoriesService


class AnalystActionsService:
    """Validate and persist analyst actions with explicit side effects."""

    ACTION_STATUS_MAP = {
        "accept": "accepted",
        "reject_noise": "rejected_noise",
        "save": "saved",
        "snooze": "snoozed",
        "block_source": "blocked_source",
    }

    def __init__(
        self,
        db_url: str,
        *,
        stories_service: StoriesService | None = None,
        post_detail_service: PostDetailService | None = None,
    ):
        self.db_url = db_url
        self.repo = InboxRepository(db_url)
        self.sources_repo = SourcesRepository(db_url)
        self.stories_service = stories_service or StoriesService(db_url)
        self.post_detail_service = post_detail_service or PostDetailService(db_url)
        self.logger = get_component_logger("analyst_actions_service")

    def record_action(
        self,
        item_id: str,
        action_type: str,
        *,
        actor_id: str | None = None,
        payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if action_type not in self.ACTION_STATUS_MAP:
            raise ValueError(f"Unsupported analyst action: {action_type}")

        actor = actor_id or "analyst"
        now = datetime.now(timezone.utc)
        payload = payload or {}

        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                item = self.repo.get_item_by_id(cur, item_id)
                if not item:
                    raise ValueError(f"Inbox item {item_id} not found")

                status = self.ACTION_STATUS_MAP[action_type]
                item_preview = item.get("target_preview") or {}
                source_context = self._resolve_source_context(item, item_preview)

                side_effects: List[Dict[str, Any]] = []
                if action_type == "block_source":
                    if not source_context or not source_context.get("source_id"):
                        raise ValueError(f"Unable to resolve source for inbox item {item_id}")
                    blocked = self.sources_repo.update_enabled(cur, source_context["source_id"], False)
                    if not blocked:
                        raise ValueError(f"Source {source_context['source_id']} not found")
                    side_effects.append(
                        {
                            "type": "source_blocked",
                            "source_id": source_context["source_id"],
                            "source_display_name": source_context.get("source_display_name"),
                        }
                    )

                action_payload = {
                    **payload,
                    "item_status": status,
                    "target_type": item["target_type"],
                    "target_id": str(item["target_id"]),
                    "side_effects": side_effects,
                }
                if source_context:
                    action_payload["source_context"] = source_context

                action_record = self.repo.insert_action(
                    cur,
                    {
                        "inbox_item_id": item_id,
                        "target_type": item["target_type"],
                        "target_id": str(item["target_id"]),
                        "action_type": action_type,
                        "actor_id": actor,
                        "created_by": actor,
                        "payload": action_payload,
                    },
                )

                metadata_patch = {
                    "last_action_type": action_type,
                    "last_action_at": now.isoformat(),
                    "last_actor_id": actor,
                    "last_action_id": action_record["id"],
                    "last_action_payload": action_payload,
                }
                if action_type == "snooze":
                    snoozed_until = payload.get("snoozedUntil") or payload.get("snoozed_until")
                    if snoozed_until is not None:
                        metadata_patch["snoozed_until"] = snoozed_until
                if action_type == "block_source" and source_context:
                    metadata_patch.update(
                        {
                            "blocked_source_id": source_context.get("source_id"),
                            "blocked_source_display_name": source_context.get("source_display_name"),
                            "blocked_at": now.isoformat(),
                        }
                    )

                updated = self.repo.update_item_after_action(
                    cur,
                    item_id,
                    status=status,
                    metadata_patch=metadata_patch,
                    acted_at=now,
                )
                if not updated:
                    raise ValueError(f"Failed to update inbox item {item_id}")
                updated_item = self.repo.get_item_by_id(cur, item_id)
            conn.commit()

        return {
            "success": True,
            "action": action_record,
            "item": updated_item,
            "side_effects": side_effects,
        }

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

    def get_target_actions(self, target_type: str, target_id: str) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                actions = self.repo.get_actions_for_target(cur, target_type, target_id)
        return {"success": True, "actions": actions, "total": len(actions)}

    def _resolve_source_context(self, item: Dict[str, Any], preview: Dict[str, Any]) -> Dict[str, Any] | None:
        target_type = item.get("target_type")
        if target_type == "post":
            source_id = preview.get("source_id") or (item.get("metadata") or {}).get("source_id")
            if not source_id:
                post = self.post_detail_service.get_post_by_id(str(item["target_id"]))
                if post:
                    source_id = post.get("source_id")
                    preview = {
                        **preview,
                        "source_id": source_id,
                        "source_display_name": post.get("source_display_name") or preview.get("source_display_name"),
                    }
            return {
                "source_id": source_id,
                "source_display_name": preview.get("source_display_name"),
                "platform": preview.get("platform"),
            } if source_id else None

        if target_type == "story":
            source_id = (item.get("metadata") or {}).get("anchor_source_id")
            if not source_id:
                anchor_post = preview.get("anchor_post") or {}
                source_id = anchor_post.get("source_id")
            if not source_id:
                detail = self.stories_service.get_story_detail(str(item["target_id"]))
                if detail:
                    anchor_post = detail.get("anchor_post") or {}
                    if anchor_post.get("source_id"):
                        source_id = anchor_post.get("source_id")
                        preview = {
                            **preview,
                            "anchor_post": {
                                **(preview.get("anchor_post") or {}),
                                "source_id": source_id,
                                "source_display_name": anchor_post.get("source_display_name")
                                or (preview.get("anchor_post") or {}).get("source_display_name"),
                            },
                        }
            anchor_post = preview.get("anchor_post") or {}
            return {
                "source_id": source_id,
                "source_display_name": anchor_post.get("source_display_name"),
                "platform": anchor_post.get("platform"),
            } if source_id else None

        return None

