"""
Business logic for folders: a grouping layer over sources.
An expert runs over a folder.
"""
import psycopg
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
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_folders_with_counts(cur)

    def get_folder(self, folder_id: str) -> Optional[Dict[str, Any]]:
        """Get a single folder with its attached sources."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                folder = self.repo.get_folder(cur, folder_id)
                if not folder:
                    return None
                folder["sources"] = self.repo.list_sources_in_folder(cur, folder_id)
                return folder

    def create_folder(
        self,
        name: str,
        description: Optional[str] = None,
        system_prompt_default: Optional[str] = None,
        sort_order: int = 999,
    ) -> Dict[str, Any]:
        """Create a new folder."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                folder = self.repo.create_folder(cur, name, description, system_prompt_default, sort_order)
                conn.commit()
                return folder

    def update_folder(self, folder_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Update folder fields."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                folder = self.repo.update_folder(cur, folder_id, fields)
                conn.commit()
                if folder is None:
                    raise ValueError(f"Folder {folder_id} not found")
                return folder

    def delete_folder(self, folder_id: str) -> bool:
        """Delete a folder (its source links are cascade-removed)."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                deleted = self.repo.delete_folder(cur, folder_id)
                conn.commit()
                return deleted

    def add_source(self, folder_id: str, source_id: str) -> bool:
        """Attach a source to a folder."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                added = self.repo.add_source_to_folder(cur, folder_id, source_id)
                conn.commit()
                return added

    def remove_source(self, folder_id: str, source_id: str) -> bool:
        """Detach a source from a folder."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                removed = self.repo.remove_source_from_folder(cur, folder_id, source_id)
                conn.commit()
                return removed

    def list_sources(self, folder_id: str) -> List[Dict[str, Any]]:
        """List the sources attached to a folder."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_sources_in_folder(cur, folder_id)

    def list_source_ids(self, folder_id: str) -> List[str]:
        """Return just the source UUIDs attached to a folder."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_source_ids_in_folder(cur, folder_id)

    def list_folders_for_source(self, source_id: str) -> List[str]:
        """Return the folder UUIDs a source belongs to."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_folder_ids_for_source(cur, source_id)
