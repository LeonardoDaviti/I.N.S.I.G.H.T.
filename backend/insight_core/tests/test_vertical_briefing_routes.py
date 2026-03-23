import asyncio
import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import main


DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping route tests")
class VerticalBriefingRouteTests(unittest.TestCase):
    def setUp(self):
        self.original_bridge = main.api_bridge
        self.calls = []

        class FakeBridge:
            def __init__(self, calls):
                self.calls = calls

            async def generate_source_vertical_briefing(self, source_id, start_date=None, end_date=None, refresh=False):
                self.calls.append((source_id, start_date, end_date, refresh))
                return {
                    "success": True,
                    "briefing": "## Executive Summary\nVertical memo",
                    "vertical_briefing": "## Executive Summary\nVertical memo",
                    "format": "markdown",
                    "saved_briefing_id": "vertical-1",
                    "cached": refresh,
                    "scope_type": "source",
                    "scope_id": source_id,
                    "source_id": source_id,
                    "source_label": "Source Label",
                    "start_date": start_date,
                    "end_date": end_date,
                    "subject_key": f"source:{source_id}:{start_date}:{end_date}",
                    "posts_processed": 3,
                    "total_posts_fetched": 3,
                    "estimated_tokens": 120,
                    "tracks": [],
                    "posts": {},
                    "variant": "source",
                }

        main.api_bridge = FakeBridge(self.calls)

    def tearDown(self):
        main.api_bridge = self.original_bridge

    def test_get_source_vertical_briefing_forwards_range(self):
        result = asyncio.run(
            main.get_source_vertical_briefing(
                source_id="source-123",
                background_tasks=main.BackgroundTasks(),
                start="2026-03-01",
                end="2026-03-31",
            )
        )

        self.assertEqual(self.calls[0], ("source-123", "2026-03-01", "2026-03-31", False))
        self.assertEqual(result["source_id"], "source-123")
        self.assertEqual(result["start_date"], "2026-03-01")
        self.assertEqual(result["end_date"], "2026-03-31")
        self.assertFalse(result["cached"])

    def test_refresh_source_vertical_briefing_sets_refresh_flag(self):
        result = asyncio.run(
            main.refresh_source_vertical_briefing(
                source_id="source-123",
                background_tasks=main.BackgroundTasks(),
                start="2026-03-01",
                end="2026-03-31",
            )
        )

        self.assertEqual(self.calls[0], ("source-123", "2026-03-01", "2026-03-31", True))
        self.assertEqual(result["source_id"], "source-123")
        self.assertTrue(result["cached"])

    def test_get_source_vertical_briefing_allows_implicit_full_range(self):
        result = asyncio.run(
            main.get_source_vertical_briefing(
                source_id="source-123",
                background_tasks=main.BackgroundTasks(),
            )
        )

        self.assertEqual(self.calls[0], ("source-123", None, None, False))
        self.assertEqual(result["source_id"], "source-123")


if __name__ == "__main__":
    unittest.main()
