import unittest
from datetime import datetime, timezone

from insight_core.services.operations_service import OperationsService


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

        result = self.service.get_operations_overview()

        self.assertTrue(result["success"])
        self.assertEqual(result["stats"]["recent_failures"], 1)
        self.assertEqual(result["stats"]["sources_in_error"], 1)
        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(result["alerts"][0]["title"], "fetch_source_now")


if __name__ == "__main__":
    unittest.main()
