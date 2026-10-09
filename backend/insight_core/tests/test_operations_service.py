import unittest
from datetime import datetime, timezone

from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.services.operations_service import OperationsService


class _FakeSources:
    def __init__(self, sources):
        self.sources = sources

    def get_all_sources_with_settings(self):
        return self.sources


class OperationsServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = OperationsService("postgresql:///unused")

    def test_json_safe_converts_nested_datetime_payloads(self):
        payload = {
            "started_at": datetime(2026, 3, 19, 12, 30, tzinfo=timezone.utc),
            "nested": {
                "history": [
                    {"at": datetime(2026, 3, 19, 13, 45, tzinfo=timezone.utc)},
                ],
            },
        }

        result = self.service._json_safe(payload)

        self.assertEqual(result["started_at"], "2026-03-19T12:30:00+00:00")
        self.assertEqual(result["nested"]["history"][0]["at"], "2026-03-19T13:45:00+00:00")

    def test_operations_overview_builds_alerts_and_stats(self):
        self.service.get_scheduler_config = lambda: {  # type: ignore[method-assign]
            "interval_hours": 20.0,
            "sync_sources_each_cycle": True,
            "generate_daily_briefing": True,
            "generate_topic_briefing": False,
            "updated_at": None,
        }
        self.service.list_recent_jobs = lambda limit=30: [  # type: ignore[method-assign]
            {
                "id": "job-1",
                "job_type": "fetch_source_now",
                "status": "failed",
                "message": "Gateway timeout",
                "started_at": "2026-03-19T12:00:00+00:00",
                "source_id": "source-1",
            },
            {
                "id": "job-2",
                "job_type": "safe_ingest",
                "status": "success",
                "message": "Completed",
                "started_at": "2026-03-19T11:00:00+00:00",
                "source_id": None,
            },
        ]
        self.service.get_source_health = lambda: [  # type: ignore[method-assign]
            {"source_id": "source-1", "display_name": "PewDiePie", "status": "error"},
            {"source_id": "source-2", "display_name": "karpathy", "status": "healthy"},
        ]
        self.service.get_database_counts = lambda: {  # type: ignore[method-assign]
            "total_posts": 140,
            "total_topics": 12,
            "total_briefings": 7,
            "enabled_sources": 4,
        }

        result = self.service.get_operations_overview()

        self.assertTrue(result["success"])
        self.assertEqual(result["stats"]["recent_failures"], 1)
        self.assertEqual(result["stats"]["sources_in_error"], 1)
        self.assertEqual(result["stats"]["total_posts"], 140)
        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(result["alerts"][0]["title"], "fetch_source_now")

    def test_prepare_payload_preserves_full_result_payloads(self):
        payload = {
            "briefing": "x" * 900,
            "posts": {
                "post-1": {"title": "Anchor"},
                "post-2": {"title": "Commentary"},
            },
        }

        stored = self.service._prepare_payload(payload, compact=False)
        preview = self.service._prepare_payload(payload, compact=True)

        self.assertEqual(stored["briefing"], "x" * 900)
        self.assertIn("post-1", stored["posts"])
        self.assertEqual(preview["posts"]["count"], 2)
        self.assertEqual(preview["posts"]["sample_ids"], ["post-1", "post-2"])


    def test_source_health_reads_the_fetch_state_table(self):
        at = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        self.service.sources_service = _FakeSources([
            {"id": "ok", "handle_or_url": "https://ok", "platform": "rss", "enabled": True,
             "post_count": 4, "settings": {"display_name": "Ok", "archive": {"stored_posts": 4}}},
            {"id": "bad", "handle_or_url": "https://bad", "platform": "rss", "enabled": True,
             "post_count": 0, "settings": {"display_name": "Bad", "archive": {}}},
            {"id": "new", "handle_or_url": "https://new", "platform": "rss", "enabled": True,
             "post_count": 0, "settings": {"archive": {}}},
        ])
        self.service._load_fetch_states = lambda ids: {  # type: ignore[method-assign]
            "ok": FetchStateRow(source_id="ok", last_attempt_at=at, last_success_at=at,
                                last_outcome="empty", last_fetched_posts=0),
            "bad": FetchStateRow(source_id="bad", last_attempt_at=at, last_outcome="error",
                                 last_error="HTTP 503", last_error_at=at, consecutive_failures=2),
        }

        rows = self.service.get_source_health()

        self.assertEqual([r["source_id"] for r in rows], ["bad", "ok", "new"], "errors sort first")
        bad, ok, new = rows
        self.assertEqual(bad["status"], "error")
        self.assertEqual(bad["last_message"], "HTTP 503")
        self.assertEqual(bad["last_error_at"], at.isoformat())
        self.assertEqual(ok["status"], "empty")
        self.assertEqual(ok["last_success_at"], at.isoformat())
        self.assertEqual(ok["last_message"], "Fetched 0 posts")
        self.assertEqual(new["status"], "unknown")
        self.assertEqual(new["display_name"], "https://new")
        self.assertIsNone(new["last_checked_at"])


if __name__ == "__main__":
    unittest.main()
