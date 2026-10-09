"""The six site adapters. Each one is a SourceKind (see base_adapter.py); KindRegistry.default
builds them with the shared KindHttp, ahead of the generic kinds in resolution priority."""

from __future__ import annotations

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

__all__ = ["ADAPTER_CLASSES", "BaseSourceAdapter"]
