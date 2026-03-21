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
class InboxRouteTests(unittest.TestCase):
    def setUp(self):
        self.original_bridge = main.api_bridge
        self.calls = []

        class FakeBridge:
            def __init__(self, calls):
                self.calls = calls

            def get_inbox_actions(self, **kwargs):
                self.calls.append(("actions", kwargs))
                return {"success": True, "actions": [], "total": 0, "kwargs": kwargs}

            def get_inbox_items(self, **kwargs):
                self.calls.append(("items", kwargs))
                return {"success": True, "items": [], "total": 0, "kwargs": kwargs}

            def get_inbox(self, **kwargs):
                self.calls.append(("inbox", kwargs))
                return {"success": True, "batch": None, "items": [], "total": 0, "kwargs": kwargs}

        main.api_bridge = FakeBridge(self.calls)

    def tearDown(self):
        main.api_bridge = self.original_bridge

    def test_get_inbox_actions_forwards_exact_query_names(self):
        result = asyncio.run(
            main.get_inbox_actions(
                limit=10,
                offset=2,
                targetType="story",
                targetId="abc",
                inboxItemId="xyz",
            )
        )

        self.assertEqual(result["kwargs"]["limit"], 10)
        self.assertEqual(result["kwargs"]["offset"], 2)
        self.assertEqual(result["kwargs"]["target_type"], "story")
        self.assertEqual(result["kwargs"]["target_id"], "abc")
        self.assertEqual(result["kwargs"]["inbox_item_id"], "xyz")
        self.assertEqual(self.calls[0][0], "actions")

    def test_get_inbox_forwards_batch_id(self):
        result = asyncio.run(main.get_inbox(batchId="batch-123", limit=7))

        self.assertEqual(result["kwargs"]["batch_id"], "batch-123")
        self.assertEqual(result["kwargs"]["limit"], 7)
        self.assertEqual(self.calls[0][0], "inbox")

    def test_get_inbox_items_forwards_filters(self):
        result = asyncio.run(
            main.get_inbox_items(
                batchId="batch-123",
                status="pending",
                targetType="story",
                sourceId="source-456",
                generatedForDate="2026-03-21",
                limit=25,
                offset=4,
            )
        )

        self.assertEqual(result["kwargs"]["batch_id"], "batch-123")
        self.assertEqual(result["kwargs"]["status"], "pending")
        self.assertEqual(result["kwargs"]["target_type"], "story")
        self.assertEqual(result["kwargs"]["source_id"], "source-456")
        self.assertEqual(result["kwargs"]["generated_for_date"], "2026-03-21")
        self.assertEqual(result["kwargs"]["limit"], 25)
        self.assertEqual(result["kwargs"]["offset"], 4)
        self.assertEqual(self.calls[0][0], "items")


if __name__ == "__main__":
    unittest.main()
