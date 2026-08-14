"""
Repository for folders and source_folders table operations.
Handles all SQL queries for folder management.
"""
from psycopg import Cursor
from typing import List, Dict, Any, Optional
from insight_core.logs.core.logger_config import get_component_logger


class FoldersRepository:
    """Database access layer for folders and source_folders tables."""

    UPDATABLE_FIELDS = {"name", "description", "sort_order", "kind",
                        "exclude_from_main_digest", "match_keywords"}

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("repo_folders")

    def _folder_from_row(self, row: tuple) -> Dict[str, Any]:
        return {
            "id": str(row[0]),
            "name": row[1],
            "description": row[2],
            "kind": row[3],
            "exclude_from_main_digest": bool(row[4]),
            "match_keywords": list(row[5] or []),
            "sort_order": row[6],
            "created_at": row[7],
            "updated_at": row[8],
        }

    def create_folder(
        self,
        cur: Cursor,
        name: str,
        description: Optional[str] = None,
        sort_order: int = 999,
        kind: str = "folder",
        exclude_from_main_digest: bool = False,
        match_keywords: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Insert a new folder (or track) and return it."""
        query = """
            INSERT INTO folders (name, description, sort_order, kind,
                                 exclude_from_main_digest, match_keywords)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, name, description, kind, exclude_from_main_digest, match_keywords, sort_order, created_at, updated_at
        """
        cur.execute(query, (name, description, sort_order, kind,
                            exclude_from_main_digest, list(match_keywords or [])))
        folder = self._folder_from_row(cur.fetchone())
        self.logger.info(f"Created folder: {name} → {folder['id']}")
        return folder

    def get_folder(self, cur: Cursor, folder_id: str) -> Optional[Dict[str, Any]]:
        """Get a single folder by UUID."""
        query = """
            SELECT id, name, description, kind, exclude_from_main_digest, match_keywords, sort_order, created_at, updated_at
            FROM folders
            WHERE id = %s
        """
        cur.execute(query, (folder_id,))
        row = cur.fetchone()
        return self._folder_from_row(row) if row else None

    def list_folders_with_counts(self, cur: Cursor) -> List[Dict[str, Any]]:
        """List all folders with source and post counts."""
        query = """
            SELECT
                f.id, f.name, f.description, f.kind, f.exclude_from_main_digest,
                f.match_keywords, f.sort_order, f.created_at, f.updated_at,
                COUNT(DISTINCT sf.source_id) AS source_count,
                COUNT(p.id) AS post_count
            FROM folders f
            LEFT JOIN source_folders sf ON sf.folder_id = f.id
            LEFT JOIN posts p ON p.source_id = sf.source_id
            GROUP BY f.id, f.name, f.description, f.kind, f.exclude_from_main_digest,
                     f.match_keywords, f.sort_order, f.created_at, f.updated_at
            ORDER BY f.sort_order, f.name
        """
        cur.execute(query)
        folders = []
        for row in cur.fetchall():
            folder = self._folder_from_row(row)
            folder["source_count"] = row[9]
            folder["post_count"] = row[10]
            folders.append(folder)
        self.logger.debug(f"Retrieved {len(folders)} folders")
        return folders

    def update_folder(self, cur: Cursor, folder_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update folder fields (whitelisted) and return the updated folder."""
        updates = {k: v for k, v in fields.items() if k in self.UPDATABLE_FIELDS}
        if not updates:
            return self.get_folder(cur, folder_id)

        set_clause = ", ".join(f"{key} = %s" for key in updates)
        values = list(updates.values()) + [folder_id]
        query = f"""
            UPDATE folders
            SET {set_clause}, updated_at = now()
            WHERE id = %s
            RETURNING id, name, description, kind, exclude_from_main_digest, match_keywords, sort_order, created_at, updated_at
        """
        cur.execute(query, values)
        row = cur.fetchone()
        if not row:
            self.logger.warning(f"Folder {folder_id} not found")
            return None
        self.logger.info(f"Updated folder {folder_id}")
        return self._folder_from_row(row)

    def delete_folder(self, cur: Cursor, folder_id: str) -> bool:
        """Delete folder (cascade removes source_folders rows)."""
        cur.execute("DELETE FROM folders WHERE id = %s RETURNING id", (folder_id,))
        row = cur.fetchone()
        if row:
            self.logger.info(f"Deleted folder: {folder_id}")
            return True
        self.logger.warning(f"Folder {folder_id} not found")
        return False

    def add_source_to_folder(self, cur: Cursor, folder_id: str, source_id: str) -> bool:
        """Attach a source to a folder (idempotent)."""
        query = """
            INSERT INTO source_folders (folder_id, source_id)
            VALUES (%s, %s)
            ON CONFLICT (source_id, folder_id) DO NOTHING
            RETURNING source_id
        """
        cur.execute(query, (folder_id, source_id))
        added = cur.fetchone() is not None
        if added:
            self.logger.info(f"Added source {source_id} to folder {folder_id}")
        return added

    def remove_source_from_folder(self, cur: Cursor, folder_id: str, source_id: str) -> bool:
        """Detach a source from a folder."""
        query = """
            DELETE FROM source_folders
            WHERE folder_id = %s AND source_id = %s
            RETURNING source_id
        """
        cur.execute(query, (folder_id, source_id))
        removed = cur.fetchone() is not None
        if removed:
            self.logger.info(f"Removed source {source_id} from folder {folder_id}")
        return removed

    def list_sources_in_folder(self, cur: Cursor, folder_id: str) -> List[Dict[str, Any]]:
        """List the sources attached to a folder."""
        query = """
            SELECT s.id, s.platform, s.handle_or_url, s.enabled
            FROM source_folders sf
            JOIN sources s ON s.id = sf.source_id
            WHERE sf.folder_id = %s
            ORDER BY s.platform, s.handle_or_url
        """
        cur.execute(query, (folder_id,))
        return [
            {"id": str(row[0]), "platform": row[1], "handle_or_url": row[2], "enabled": row[3]}
            for row in cur.fetchall()
        ]

    def list_source_ids_in_folder(self, cur: Cursor, folder_id: str) -> List[str]:
        """Return just the source UUIDs attached to a folder."""
        cur.execute("SELECT source_id FROM source_folders WHERE folder_id = %s", (folder_id,))
        return [str(row[0]) for row in cur.fetchall()]

    def list_folder_ids_for_source(self, cur: Cursor, source_id: str) -> List[str]:
        """Return the folder UUIDs a source belongs to."""
        cur.execute("SELECT folder_id FROM source_folders WHERE source_id = %s", (source_id,))
        return [str(row[0]) for row in cur.fetchall()]
