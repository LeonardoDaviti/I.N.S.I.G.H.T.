"""The ingestion module (spec §A, §5.4, §5.7): every test goes through a public seam.

All fakes, no DB, no network: the runner is assembled with the §A.1 keyword constructor
from in-memory ports (tests/_ingestion_fakes.py), FakeKinds and real FetchGates with no
delays.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.enrichment import Enricher, EnrichmentReport, StepReport


class RecordingProcessor:
    """An entity/event processor stand-in: records each chunk, optionally fails one."""

    def __init__(self, fail_on_chunk: int | None = None):
        self.fail_on_chunk = fail_on_chunk
        self.chunks: list[list[dict]] = []

    def process_posts(self, posts):
        self.chunks.append(list(posts))
        if self.fail_on_chunk is not None and len(self.chunks) - 1 == self.fail_on_chunk:
            raise RuntimeError("enrichment boom")
        return {"posts_processed": len(posts)}

    @property
    def ids(self) -> list[str]:
        return [post["id"] for chunk in self.chunks for post in chunk]


def _posts(n: int) -> list[dict]:
    return [{"id": f"p{i}", "source_id": "s1", "url": f"https://x.test/{i}"} for i in range(n)]


class EnricherTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_are_chunked(self):
        entity, event = RecordingProcessor(), RecordingProcessor()
        report = await Enricher(entity, event, chunk_size=100).run(_posts(250))
        self.assertEqual([len(c) for c in entity.chunks], [100, 100, 50])
        self.assertEqual([len(c) for c in event.chunks], [100, 100, 50])
        self.assertEqual(report, EnrichmentReport(StepReport(250, 3, 0), StepReport(250, 3, 0)))

    async def test_a_failing_chunk_is_counted_and_the_rest_still_runs(self):
        entity, event = RecordingProcessor(fail_on_chunk=1), RecordingProcessor()
        report = await Enricher(entity, event, chunk_size=100).run(_posts(250))
        self.assertEqual(len(entity.chunks), 3)
        self.assertEqual(report.entity, StepReport(250, 3, 1))
        self.assertEqual(report.event, StepReport(250, 3, 0))

    async def test_empty_input_makes_no_calls(self):
        entity, event = RecordingProcessor(), RecordingProcessor()
        report = await Enricher(entity, event).run([])
        self.assertEqual(entity.chunks, [])
        self.assertEqual(event.chunks, [])
        self.assertEqual(report, EnrichmentReport.empty())


if __name__ == "__main__":
    unittest.main()
