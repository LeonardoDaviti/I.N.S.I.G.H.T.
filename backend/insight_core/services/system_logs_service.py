"""
Helpers for exposing recent backend/scheduler log output through the API.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List


class SystemLogsService:
    """Read recent log lines from the shared INSIGHT log directory."""

    LOG_FILES = {
        "application": ("core", "application.log"),
        "errors": ("core", "errors.log"),
        "rss": ("connectors", "rss.log"),
        "reddit": ("connectors", "reddit.log"),
        "youtube": ("connectors", "youtube.log"),
        "telegram": ("connectors", "telegram.log"),
        "automated": ("operations", "automated.log"),
        "interactive": ("operations", "interactive.log"),
        "recovery": ("operations", "recovery.log"),
    }

    def __init__(self, logs_root: str | None = None):
        configured_root = logs_root or os.getenv("INSIGHT_LOG_DIR", "logs")
        self.logs_root = Path(configured_root)

    def get_log_tail(self, log_name: str = "application", lines: int = 200) -> Dict[str, Any]:
        if log_name not in self.LOG_FILES:
            raise ValueError(f"Unsupported log '{log_name}'. Available: {', '.join(self.available_logs())}")

        lines = max(1, min(int(lines), 1000))
        relative_dir, filename = self.LOG_FILES[log_name]
        log_path = self.logs_root / relative_dir / filename

        return {
            "success": True,
            "log": log_name,
            "available_logs": self.available_logs(),
            "path": str(log_path),
            "exists": log_path.exists(),
            "updated_at": self._updated_at(log_path),
            "lines": self._tail_lines(log_path, lines),
        }

    def available_logs(self) -> List[str]:
        return list(self.LOG_FILES.keys())

    def _tail_lines(self, path: Path, lines: int) -> List[str]:
        if not path.exists():
            return []

        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return content[-lines:]

    def _updated_at(self, path: Path) -> float | None:
        if not path.exists():
            return None
        return path.stat().st_mtime
