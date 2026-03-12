"""
Bidirectional sync between sources.json and the database-backed source registry.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.sources_service import SourcesService


class SourceConfigSyncService:
    """Keep sources.json and the database source registry in sync."""

    def __init__(self, db_url: str, config_path: str | Path | None = None):
        self.db_url = db_url
        self.sources_service = SourcesService(db_url)
        self.config_path = Path(
            config_path
            or os.getenv("INSIGHT_SOURCES_JSON_PATH")
            or (Path(__file__).resolve().parents[1] / "config" / "sources.json")
        )
        self.logger = get_component_logger("source_config_sync")

    def sync_json_to_db(self, mirror: bool = True) -> Dict[str, Any]:
        document = self.load_json()
        desired_sources = self._flatten_sources(document)
        current_sources = self.sources_service.get_all_sources()
        current_lookup = {
            (source["platform"], source["handle_or_url"]): source
            for source in current_sources
        }

        stats = {"added": 0, "updated": 0, "deleted": 0, "errors": []}
        desired_keys = set()

        for platform, handle_or_url, enabled in desired_sources:
            desired_keys.add((platform, handle_or_url))
            current = current_lookup.get((platform, handle_or_url))

            if not current:
                try:
                    created = self.sources_service.add_source(platform, handle_or_url)
                    if not enabled:
                        self.sources_service.update_source_status(created["source_id"], False)
                    stats["added"] += 1
                except Exception as exc:
                    stats["errors"].append(f"add {platform}/{handle_or_url}: {exc}")
                continue

            if current["enabled"] != enabled:
                try:
                    self.sources_service.update_source_status(current["id"], enabled)
                    stats["updated"] += 1
                except Exception as exc:
                    stats["errors"].append(f"update {platform}/{handle_or_url}: {exc}")

        if mirror:
            for (platform, handle_or_url), current in current_lookup.items():
                if (platform, handle_or_url) in desired_keys:
                    continue
                try:
                    self.sources_service.delete_source(current["id"])
                    stats["deleted"] += 1
                except Exception as exc:
                    stats["errors"].append(f"delete {platform}/{handle_or_url}: {exc}")

        self.logger.info(
            "Synced sources.json to DB: added=%s updated=%s deleted=%s errors=%s",
            stats["added"],
            stats["updated"],
            stats["deleted"],
            len(stats["errors"]),
        )
        return {
            "success": not stats["errors"],
            "stats": stats,
        }

    def export_db_to_json(self) -> Dict[str, Any]:
        current_document = self.load_json() if self.config_path.exists() else self._default_document()
        sources = self.sources_service.get_all_sources()

        platforms: Dict[str, Dict[str, Any]] = {}
        for source in sources:
            platform = source["platform"]
            entry = platforms.setdefault(platform, {"enabled": False, "sources": []})
            entry["sources"].append(
                {
                    "id": source["handle_or_url"],
                    "state": "enabled" if source["enabled"] else "disabled",
                }
            )
            if source["enabled"]:
                entry["enabled"] = True

        for platform_data in platforms.values():
            platform_data["sources"].sort(key=lambda item: item["id"])

        document = {
            "metadata": current_document.get("metadata", self._default_document()["metadata"]),
            "platforms": dict(sorted(platforms.items())),
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4, ensure_ascii=False)
            handle.write("\n")

        self.logger.info("Exported DB sources to %s", self.config_path)
        return {
            "success": True,
            "path": str(self.config_path),
            "total_sources": len(sources),
        }

    def sync_db_to_json(self) -> Dict[str, Any]:
        return self.export_db_to_json()

    def load_json(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return self._default_document()
        with self.config_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _flatten_sources(self, document: Dict[str, Any]) -> List[Tuple[str, str, bool]]:
        flattened: List[Tuple[str, str, bool]] = []
        for platform, platform_data in document.get("platforms", {}).items():
            for source in platform_data.get("sources", []):
                handle_or_url = source.get("id")
                if not handle_or_url:
                    continue
                enabled = source.get("state", "disabled") == "enabled"
                flattened.append((platform, handle_or_url, enabled))
        return flattened

    def _default_document(self) -> Dict[str, Any]:
        return {
            "metadata": {
                "name": "I.N.S.I.G.H.T.",
                "description": "Intelligence Network for Systematic Gathering and Handling of Topics",
                "version": "Mark VI",
            },
            "platforms": {},
        }
