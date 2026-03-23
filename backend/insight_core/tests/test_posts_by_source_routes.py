import asyncio
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import main


class PostsBySourceRouteTests(unittest.TestCase):
    def setUp(self):
        self.original_bridge = main.api_bridge
        self.calls = []

        class FakeBridge:
            def __init__(self, calls):
                self.calls = calls

            def get_posts_by_source(self, source_id, *, limit=None, offset=0):
                self.calls.append((source_id, limit, offset))
                return {
                    "success": True,
                    "posts": [{"id": "post-1", "title": "Example", "content": "Body", "platform": "rss", "source": "Example"}],
                    "source_id": source_id,
                    "total": 102,
                    "returned": 1,
                    "offset": offset,
                    "limit": limit,
                    "has_more": True,
                }

        main.api_bridge = FakeBridge(self.calls)

    def tearDown(self):
        main.api_bridge = self.original_bridge

    def test_get_posts_by_source_forwards_limit_and_offset(self):
        result = asyncio.run(main.get_posts_by_source("source-123", limit=20, offset=40))

        self.assertEqual(self.calls[0], ("source-123", 20, 40))
        self.assertEqual(result["source_id"], "source-123")
        self.assertEqual(result["total"], 102)
        self.assertEqual(result["returned"], 1)
        self.assertTrue(result["has_more"])


if __name__ == "__main__":
    unittest.main()
