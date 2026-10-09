"""Enrichment: the follow-on step after a save batch (spec §B.2).

Entity memory and event memory run over the posts a save batch *inserted*, in chunks, each
chunk off the event loop. A failing chunk is counted, never raised: enrichment is
best-effort and must not cost a fetch run its report. Re-enriching updated rows is deferred
to the analysis version (content-hash change detection).

The processors are duck-typed (`process_posts(list[dict])`), so ingestion/ does not import
services/; the real ones are EntityMemoryService and EventMemoryService.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

logger = logging.getLogger("insight.ingestion.enrichment")


def _env_chunk_size() -> int:
    raw = os.getenv("INSIGHT_ENRICH_CHUNK_SIZE") or os.getenv("SAFE_INGEST_ENRICH_CHUNK_SIZE") or "100"
    try:
        return max(1, int(raw))
    except ValueError:
        return 100


class PostProcessor(Protocol):
    def process_posts(self, posts: list[dict]) -> Any: ...


@dataclass(frozen=True)
class StepReport:
    posts: int
    chunks: int
    failed_chunks: int

    def as_dict(self) -> dict[str, int]:
        return {"posts": self.posts, "chunks": self.chunks, "failed_chunks": self.failed_chunks}


@dataclass(frozen=True)
class EnrichmentReport:
    entity: StepReport
    event: StepReport

    @staticmethod
    def empty() -> "EnrichmentReport":
        return EnrichmentReport(StepReport(0, 0, 0), StepReport(0, 0, 0))

    def as_dict(self) -> dict[str, dict[str, int]]:
        return {"entity": self.entity.as_dict(), "event": self.event.as_dict()}


class Enricher:
    def __init__(self, entity: PostProcessor, event: PostProcessor, chunk_size: int | None = None) -> None:
        self.entity = entity
        self.event = event
        self.chunk_size = max(1, int(chunk_size or _env_chunk_size()))

    async def run(self, posts: Sequence[Mapping[str, Any]]) -> EnrichmentReport:
        """Enrich the inserted posts ({**post, id, source_id}); entity memory first."""
        posts = [dict(post) for post in posts]
        if not posts:
            return EnrichmentReport.empty()
        entity = await self._step("entity memory", self.entity, posts)
        event = await self._step("event memory", self.event, posts)
        return EnrichmentReport(entity, event)

    async def _step(self, label: str, processor: PostProcessor, posts: list[dict]) -> StepReport:
        chunks = failed = 0
        for offset in range(0, len(posts), self.chunk_size):
            chunk = posts[offset : offset + self.chunk_size]
            chunks += 1
            try:
                await asyncio.to_thread(processor.process_posts, chunk)
            except Exception as exc:  # noqa: BLE001 - best-effort, counted
                failed += 1
                logger.warning("%s enrichment failed for chunk at %s: %s", label, offset, exc)
        return StepReport(len(posts), chunks, failed)
