"""
Business logic for folders: a grouping layer over sources.
"""
from insight_core.db import database as db
from typing import List, Dict, Any, Optional
from insight_core.db.repo_folders import FoldersRepository
from insight_core.logs.core.logger_config import get_component_logger


class FoldersService:
    """Manages folders and their source membership."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = FoldersRepository(db_url)
        self.logger = get_component_logger("folders_service")

    def list_folders(self) -> List[Dict[str, Any]]:
        """List all folders with source and post counts."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_folders_with_counts(cur)

    def create_folder(
        self,
        name: str,
        description: Optional[str] = None,
        sort_order: int = 999,
        kind: str = "folder",
        exclude_from_main_digest: bool = False,
        match_keywords: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a folder, or a track (kind="track")."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                folder = self.repo.create_folder(
                    cur, name, description, sort_order,
                    kind=kind,
                    exclude_from_main_digest=exclude_from_main_digest,
                    match_keywords=match_keywords,
                )
                conn.commit()
                return folder

    def update_folder(self, folder_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Update folder fields."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                folder = self.repo.update_folder(cur, folder_id, fields)
                conn.commit()
                if folder is None:
                    raise LookupError(f"Folder {folder_id} not found")
                return folder

    def delete_folder(self, folder_id: str) -> bool:
        """Delete a folder (its source links are cascade-removed)."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                deleted = self.repo.delete_folder(cur, folder_id)
                conn.commit()
                return deleted

    def add_source(self, folder_id: str, source_id: str) -> bool:
        """Attach a source to a folder."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                added = self.repo.add_source_to_folder(cur, folder_id, source_id)
                conn.commit()
                return added

    def remove_source(self, folder_id: str, source_id: str) -> bool:
        """Detach a source from a folder."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                removed = self.repo.remove_source_from_folder(cur, folder_id, source_id)
                conn.commit()
                return removed

    def list_folders_for_source(self, source_id: str) -> List[str]:
        """Return the folder UUIDs a source belongs to."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_folder_ids_for_source(cur, source_id)
