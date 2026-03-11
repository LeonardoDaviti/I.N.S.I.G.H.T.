"""
Minimal subset of python-dotenv used by this project.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def find_dotenv(filename: str = ".env") -> str:
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        path = candidate / filename
        if path.exists():
            return str(path)
    return ""


def load_dotenv(dotenv_path: Optional[str] = None, override: bool = False) -> bool:
    path = Path(dotenv_path) if dotenv_path else Path(find_dotenv())
    if not path or not path.exists():
        return False

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if override or key not in os.environ:
            os.environ[key] = value
    return True
