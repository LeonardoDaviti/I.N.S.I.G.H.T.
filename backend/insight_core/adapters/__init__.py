"""Registry for custom source archive adapters."""

from __future__ import annotations

from typing import Any, Dict, Optional

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.adapters.dario_adapter import DarioAmodeiAdapter
from insight_core.adapters.deeplearning_batch_adapter import DeepLearningBatchAdapter
from insight_core.adapters.gwern_adapter import GwernAdapter
from insight_core.adapters.lesswrong_adapter import LessWrongAdapter
from insight_core.adapters.philschmid_adapter import PhilSchmidCloudAttentionAdapter
from insight_core.adapters.zerotomastery_adapter import ZeroToMasteryMonthlyAdapter


ADAPTER_CLASSES = (
    LessWrongAdapter,
    GwernAdapter,
    DarioAmodeiAdapter,
    DeepLearningBatchAdapter,
    PhilSchmidCloudAttentionAdapter,
    ZeroToMasteryMonthlyAdapter,
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
    "DarioAmodeiAdapter",
    "DeepLearningBatchAdapter",
    "PhilSchmidCloudAttentionAdapter",
    "ZeroToMasteryMonthlyAdapter",
    "create_source_adapter",
]
