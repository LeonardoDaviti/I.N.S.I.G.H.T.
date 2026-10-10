"""The one way a service holds a Gemini client: built on first use, never at construction.

With INSIGHT_ANALYSIS off (reading-finish R3) no path the reading app takes reads
`self.processor`, so no GeminiProcessor is created. Assignable, so tests can set a fake.
"""
from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from insight_core.processors.ai.gemini_processor import GeminiProcessor


def _build_gemini_processor(self: object) -> "GeminiProcessor":
    from insight_core.processors.ai.gemini_processor import GeminiProcessor

    return GeminiProcessor()


def lazy_gemini_processor() -> "cached_property[GeminiProcessor]":
    """`processor = lazy_gemini_processor()` in a class body: a GeminiProcessor built on first
    access and cached on the instance. A new descriptor per class (cached_property binds to
    one attribute name)."""
    prop = cached_property(_build_gemini_processor)
    prop.__doc__ = __doc__
    return prop
