"""
sources.json and the database's sources (issue 0071).

The database is the truth. sources.json is its export, rewritten after each change, and a
file can be imported: that only adds the sources the database lacks (issue 0072). It never
deletes one, never changes an existing source's on/off, and never adds back a source that was
removed (or an address a source was switched away from): the database remembers those
(removed_sources), until the source is added again in the app. Removing a source is Remove in
the app.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from insight_core.db import database as db
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.sources_service import SourcesService

# system_settings: when a start first imported sources.json into this database. Later starts
# don't import again, so a stale file can't turn back what the app changed.
IMPORTED_KEY = "sources_json_imported"


def _handle(value: Any) -> str:
    """A source id as SourcesService.add_source stores it."""
    return str(value or "").strip()


class SourceConfigSyncService:
    """Export the database's sources to sources.json, and import a file add-only."""

    def __init__(self, db_url: str, config_path: str | Path | None = None):
        self.db_url = db_url
        self.sources_service = SourcesService(db_url)
        self.config_path = Path(
            config_path
            or os.getenv("INSIGHT_SOURCES_JSON_PATH")
            or (Path(__file__).resolve().parents[1] / "config" / "sources.json")
        )
        self.logger = get_component_logger("source_config_sync")

    def import_json(self) -> Dict[str, Any]:
        """Add the file's sources the database lacks, each on or off as the file says.

        Never deletes, never changes a source the database has, and never adds back a removed
        one (`removed` counts those). A missing, empty or broken file changes nothing; a bad
        entry, or a source another process added meanwhile, is skipped with a line in the log.
        `read` says whether the file could be read at all."""
        stats: Dict[str, Any] = {"read": False, "added": 0, "removed": 0, "skipped": []}
        try:
            document = json.loads(self.config_path.read_text(encoding="utf-8"))
            platforms = document["platforms"]
            if not isinstance(platforms, dict):
                raise ValueError("platforms is not an object")
        except FileNotFoundError:
            self.logger.warning("No sources.json at %s: nothing imported", self.config_path)
            return stats
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.logger.error("sources.json at %s could not be read (%r): nothing imported", self.config_path, exc)
            return stats
        stats["read"] = True
        current = {(s["platform"], _handle(s["handle_or_url"])) for s in self.sources_service.get_all_sources()}
        removed = self.sources_service.removed_sources()

        for platform, handle_or_url, enabled, in_main_digest in self._flatten_sources(platforms, stats["skipped"]):
            key = (platform, handle_or_url)
            if key in current:
                continue        # the app's on/off, digest and settings stand
            if key in removed:
                stats["removed"] += 1
                self.logger.info("sources.json import: %s/%s was removed %s; not added back",
                                 platform, handle_or_url, removed[key].date())
                continue
            try:
                created = self.sources_service.add_source(platform, handle_or_url, in_main_digest=in_main_digest)
                if not enabled:
                    self.sources_service.update_source_status(created["source_id"], False)
                stats["added"] += 1
            except Exception as exc:  # noqa: BLE001 - one source never stops the rest
                stats["skipped"].append(f"{platform}/{handle_or_url}: {exc}")

        for line in stats["skipped"]:
            self.logger.warning("sources.json import skipped %s", line)
        self.logger.info("Imported sources.json: added=%s removed (not added back)=%s skipped=%s",
                         stats["added"], stats["removed"], len(stats["skipped"]))
        return stats

    def import_once(self) -> Dict[str, Any]:
        """import_json, the first time a start reads a file into this database (a new install,
        or the first start after 0071); later starts leave the database as it is."""
        with db.transaction(self.db_url) as cur:
            if SystemSettingsRepository.get(cur, IMPORTED_KEY):
                self.logger.info("sources.json was imported before: the database is the truth")
                return {"read": False, "added": 0, "removed": 0, "skipped": [], "imported_before": True}
        stats = self.import_json()
        if stats["read"]:
            with db.transaction(self.db_url) as cur:
                SystemSettingsRepository.upsert(cur, IMPORTED_KEY, {
                    "at": datetime.now(timezone.utc).isoformat(), "added": stats["added"], "removed": stats["removed"]})
        return stats

    def switch_source(self, source_id: str, url: str, page_watch: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """SourcesService.switch_source (issue 0036), then the export. A file that can't be
        written is logged: the switch stands, since the database is the truth."""
        old = self.sources_service.switch_source(source_id, url, page_watch)
        try:
            self.export_db_to_json()
        except Exception:  # noqa: BLE001
            self.logger.exception("Could not write sources.json after switching %s", source_id)
        return old

    def export_db_to_json(self) -> Dict[str, Any]:
        """Write every source to sources.json: to a temporary file beside it, then renamed over it,
        so a crash mid-write leaves the old file whole."""
        sources = self.sources_service.get_all_sources()

        platforms: Dict[str, Dict[str, Any]] = {}
        for source in sources:
            platform = source["platform"]
            entry = platforms.setdefault(platform, {"enabled": False, "sources": []})
            item = {
                "id": source["handle_or_url"],
                "state": "enabled" if source["enabled"] else "disabled",
            }
            # Written only when off, so the default (true) stays implicit in the file.
            if source.get("in_main_digest") is False:
                item["in_main_digest"] = False
            entry["sources"].append(item)
            if source["enabled"]:
                entry["enabled"] = True

        for platform_data in platforms.values():
            platform_data["sources"].sort(key=lambda item: item["id"])

        document = {**self._default_document(), "platforms": dict(sorted(platforms.items()))}

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.config_path.parent,
                                         prefix=f".{self.config_path.name}.", delete=False) as handle:
            try:
                json.dump(document, handle, indent=4, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            except BaseException:
                os.unlink(handle.name)
                raise
        os.chmod(handle.name, 0o644)
        os.replace(handle.name, self.config_path)

        self.logger.info("Exported DB sources to %s", self.config_path)
        return {
            "success": True,
            "path": str(self.config_path),
            "total_sources": len(sources),
        }

    def sync_db_to_json(self) -> Dict[str, Any]:
        return self.export_db_to_json()

    def _flatten_sources(self, platforms: Dict[str, Any], skipped: List[str]) -> List[Tuple[str, str, bool, bool]]:
        """(platform, handle_or_url, enabled, in_main_digest); in_main_digest is optional, default
        true. An entry that isn't a source is added to `skipped` instead."""
        flattened: List[Tuple[str, str, bool, bool]] = []
        for platform, platform_data in platforms.items():
            entries = platform_data.get("sources") if isinstance(platform_data, dict) else None
            if not isinstance(entries, list):
                skipped.append(f"{platform}: no sources list")
                continue
            for source in entries:
                handle_or_url = _handle(source.get("id")) if isinstance(source, dict) else ""
                if not handle_or_url:
                    skipped.append(f"{platform}: an entry with no id ({str(source)[:80]})")
                    continue
                enabled = source.get("state", "disabled") == "enabled"
                in_main_digest = source.get("in_main_digest", True) is not False
                flattened.append((platform, handle_or_url, enabled, in_main_digest))
        return flattened

    def _default_document(self) -> Dict[str, Any]:
        return {
            "metadata": {
                "name": "I.N.S.I.G.H.T.",
                "description": "The sources, exported from the database after each change (import: "
                               "scripts/sync_sources_json.py json-to-db, which only adds missing sources "
                               "and never one that was removed)",
            },
            "platforms": {},
        }
