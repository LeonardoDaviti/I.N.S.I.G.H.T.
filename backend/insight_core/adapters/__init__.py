"""Registry for custom source archive adapters."""

from __future__ import annotations

from typing import Any, Dict, Optional

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.adapters.gwern_adapter import GwernAdapter
from insight_core.adapters.lesswrong_adapter import LessWrongAdapter


ADAPTER_CLASSES = (
    LessWrongAdapter,
    GwernAdapter,
)


def create_source_adapter(service: Any, source: Dict[str, Any]) -> Optional[BaseSourceAdapter]:
    for adapter_class in ADAPTER_CLASSES:
        adapter = adapter_class(service)
        if adapter.matches(source):
            return adapter
    return None


__all__ = [
    "BaseSourceAdapter",
    "LessWrongAdapter",
    "GwernAdapter",
    "create_source_adapter",
]
