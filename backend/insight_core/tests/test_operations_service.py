import unittest
from datetime import datetime, timezone

from insight_core.services.operations_service import OperationsService


class OperationsServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = OperationsService("postgresql:///unused")

    def test_operations_overview_builds_alerts_and_stats(self):
        self.service.get_scheduler_config = lambda: {  # type: ignore[method-assign]
            "interval_hours": 20.0,
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
        self.service.get_source_health = lambda: {  # type: ignore[method-assign]
            "success": True,
            "rows": [
                {"source_id": "source-1", "display_name": "PewDiePie", "status": "error"},
                {"source_id": "source-2", "display_name": "nn_teacher", "status": "deferred"},
            ],
            "summary": {"due_now": 0, "deferred": 1, "backoff": 0, "unavailable": 0, "errors": 1, "silent": 0},
        }
        self.service.get_database_counts = lambda: {  # type: ignore[method-assign]
            "total_posts": 140,
            "enabled_sources": 4,
        }

        result = self.service.get_operations_overview()

        self.assertTrue(result["success"])
        self.assertEqual(result["stats"]["recent_failures"], 1)
        self.assertEqual(result["stats"]["sources_in_error"], 1)
        self.assertEqual(result["stats"]["sources_monitored"], 2)
        self.assertEqual(result["source_health"]["summary"]["errors"], 1)
        self.assertEqual([r["source_id"] for r in result["source_health"]["rows"]], ["source-1", "source-2"])
        self.assertEqual(result["stats"]["total_posts"], 140)
        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(result["alerts"][0]["title"], "fetch_source_now")

    def test_prepare_payload_preserves_full_result_payloads(self):
        payload = {
            "message": "x" * 900,
            "posts": {
                "post-1": {"title": "Anchor"},
                "post-2": {"title": "Commentary"},
            },
        }

        stored = self.service._prepare_payload(payload, compact=False)
        preview = self.service._prepare_payload(payload, compact=True)

        self.assertEqual(stored["message"], "x" * 900)
        self.assertIn("post-1", stored["posts"])
        self.assertEqual(preview["posts"]["count"], 2)
        self.assertEqual(preview["posts"]["sample_ids"], ["post-1", "post-2"])


    # The schedule-aware get_source_health is covered by test_source_health.py.


if __name__ == "__main__":
    unittest.main()


class SchedulerConfigTests(unittest.TestCase):
    def setUp(self):
        self.service = OperationsService("postgresql:///unused")

    def test_ingest_tick_minutes_defaults_to_an_hour_with_a_15_minute_floor(self):
        self.assertEqual(self.service._normalize_scheduler_config({})["ingest_tick_minutes"], 60)
        self.assertEqual(self.service._normalize_scheduler_config({"ingest_tick_minutes": 5})["ingest_tick_minutes"], 15)
        self.assertEqual(self.service._normalize_scheduler_config({"ingest_tick_minutes": 30})["ingest_tick_minutes"], 30)

    def test_collect_originals_is_on_by_default_and_keeps_an_owner_s_choice(self):
        """Issue 0126 (4): on unless you switched it off. A false written while off was the default (the
        dialog wrote it whether or not you touched it) reads as the default; one this version wrote is kept."""
        normalize = self.service._normalize_scheduler_config
        self.assertTrue(normalize({})["collect_originals"], "never set: on")
        self.assertTrue(normalize({"collect_originals": False})["collect_originals"], "written under the old default")
        self.assertFalse(normalize({"collect_originals": False, "collect_originals_default": "on"})["collect_originals"],
                         "switched off under this default: kept")
        self.assertTrue(normalize({"collect_originals": True})["collect_originals"])

    def test_the_originals_job_reads_the_row_the_dialog_writes(self):
        """Issue 0126: 0123's job read a 'scheduler' row nothing wrote, so the switch never reached it."""
        from insight_core.services import originals_service
        self.assertEqual(originals_service.SCHEDULER_KEY, OperationsService.SETTINGS_KEY_SCHEDULER)

    def test_saving_the_scheduler_marks_the_switch_as_chosen(self):
        from unittest import mock
        written = {}
        service = self.service
        service.get_scheduler_config = lambda: service._normalize_scheduler_config({})  # type: ignore[method-assign]
        with mock.patch("insight_core.services.operations_service.db.connection"), \
                mock.patch("insight_core.services.operations_service.SystemSettingsRepository.upsert",
                           side_effect=lambda cur, key, value: written.update({key: value}) or datetime.now(timezone.utc)):
            merged = service.update_scheduler_config({"collect_originals": False})
        self.assertFalse(merged["collect_originals"])
        self.assertEqual(written["scheduler_config"]["collect_originals"], False)
        self.assertEqual(written["scheduler_config"]["collect_originals_default"], "on")
        self.assertFalse(service._normalize_scheduler_config(written["scheduler_config"])["collect_originals"], "read back: off")
        with mock.patch("insight_core.services.operations_service.db.connection"), \
                mock.patch("insight_core.services.operations_service.SystemSettingsRepository.upsert",
                           side_effect=lambda cur, key, value: written.update({key: value}) or datetime.now(timezone.utc)):
            service.update_scheduler_config({"ingest_tick_minutes": 30})
        self.assertTrue(written["scheduler_config"]["collect_originals"], "a save that doesn't name it keeps the setting (on)")

    def test_malformed_env_defaults_fall_back(self):
        from unittest import mock
        with mock.patch.dict("os.environ", {"INSIGHT_INGEST_INTERVAL_HOURS": "daily",
                                            "INSIGHT_INGEST_TICK_MINUTES": "1h"}):
            config = self.service._default_scheduler_config()
        self.assertEqual((config["interval_hours"], config["ingest_tick_minutes"]), (20, 60))

    def test_job_labels_name_the_current_types_and_keep_old_rows_readable(self):
        from insight_core.services.operations_service import job_label

        self.assertEqual(job_label("ingestion_run"), "Ingestion run")
        self.assertEqual(job_label("safe_ingest"), "Safe ingest")
        self.assertEqual(job_label("folder_ingest"), "Folder ingest")
