"""Process-wide settings read once from the environment.

INSIGHT_ANALYSIS (default off, spec §9 / reading-finish R3) is the one switch for the
analysis surfaces. Off: saving posts skips entity/event enrichment, daily work skips experts
and briefings, no GeminiProcessor is built, and the analysis endpoints answer 409
{"error": "analysis_disabled"}. On: today's behaviour, unchanged. No data is deleted either way.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping, Optional

_TRUTHY = {"on", "true", "1", "yes"}


@dataclass(frozen=True)
class Settings:
    analysis_enabled: bool = False

    @staticmethod
    def from_env(env: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if env is None else env
        raw = str(env.get("INSIGHT_ANALYSIS", "off")).strip().lower()
        return Settings(analysis_enabled=raw in _TRUTHY)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The settings for this process, read from the environment on first use."""
    return Settings.from_env()
