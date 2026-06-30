"""
Repository for experts table operations.
An expert is a briefing persona scoped to one folder.
"""
from psycopg import Cursor
from typing import List, Dict, Any, Optional
from insight_core.logs.core.logger_config import get_component_logger


class ExpertsRepository:
    """Database access layer for the experts table."""

    UPDATABLE_FIELDS = {
        "name",
        "folder_id",
        "system_prompt",
        "focus_instructions",
        "output_variant",
        "lookback_days",
        "schedule",
        "enabled",
    }

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("repo_experts")

    def _expert_from_row(self, row: tuple) -> Dict[str, Any]:
        return {
            "id": str(row[0]),
            "name": row[1],
            "folder_id": str(row[2]),
            "system_prompt": row[3],
            "focus_instructions": row[4],
            "output_variant": row[5],
            "lookback_days": row[6],
            "schedule": row[7],
            "enabled": row[8],
            "created_at": row[9],
            "updated_at": row[10],
        }

    _SELECT = """
        SELECT id, name, folder_id, system_prompt, focus_instructions,
               output_variant, lookback_days, schedule, enabled, created_at, updated_at
        FROM experts
    """

    def create_expert(self, cur: Cursor, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new expert and return it."""
        query = """
            INSERT INTO experts
                (name, folder_id, system_prompt, focus_instructions,
                 output_variant, lookback_days, schedule, enabled)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, name, folder_id, system_prompt, focus_instructions,
                      output_variant, lookback_days, schedule, enabled, created_at, updated_at
        """
        cur.execute(
            query,
            (
                fields["name"],
                fields["folder_id"],
                fields["system_prompt"],
                fields.get("focus_instructions"),
                fields.get("output_variant", "topics"),
                int(fields.get("lookback_days", 7)),
                fields.get("schedule"),
                bool(fields.get("enabled", True)),
            ),
        )
        expert = self._expert_from_row(cur.fetchone())
        self.logger.info(f"Created expert: {expert['name']} → {expert['id']}")
        return expert

    def get_expert(self, cur: Cursor, expert_id: str) -> Optional[Dict[str, Any]]:
        cur.execute(self._SELECT + " WHERE id = %s", (expert_id,))
        row = cur.fetchone()
        return self._expert_from_row(row) if row else None

    def list_experts(self, cur: Cursor) -> List[Dict[str, Any]]:
        cur.execute(self._SELECT + " ORDER BY name")
        return [self._expert_from_row(row) for row in cur.fetchall()]

    def list_scheduled_experts(self, cur: Cursor) -> List[Dict[str, Any]]:
        """Enabled experts that carry a schedule (for the scheduler)."""
        cur.execute(
            self._SELECT + " WHERE enabled = TRUE AND schedule IS NOT NULL AND schedule <> '' ORDER BY name"
        )
        return [self._expert_from_row(row) for row in cur.fetchall()]

    def update_expert(self, cur: Cursor, expert_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updates = {k: v for k, v in fields.items() if k in self.UPDATABLE_FIELDS}
        if not updates:
            return self.get_expert(cur, expert_id)
        set_clause = ", ".join(f"{key} = %s" for key in updates)
        values = list(updates.values()) + [expert_id]
        cur.execute(
            f"""
            UPDATE experts SET {set_clause}, updated_at = now()
            WHERE id = %s
            RETURNING id, name, folder_id, system_prompt, focus_instructions,
                      output_variant, lookback_days, schedule, enabled, created_at, updated_at
            """,
            values,
        )
        row = cur.fetchone()
        if not row:
            self.logger.warning(f"Expert {expert_id} not found")
            return None
        self.logger.info(f"Updated expert {expert_id}")
        return self._expert_from_row(row)

    def delete_expert(self, cur: Cursor, expert_id: str) -> bool:
        cur.execute("DELETE FROM experts WHERE id = %s RETURNING id", (expert_id,))
        if cur.fetchone():
            self.logger.info(f"Deleted expert: {expert_id}")
            return True
        self.logger.warning(f"Expert {expert_id} not found")
        return False
