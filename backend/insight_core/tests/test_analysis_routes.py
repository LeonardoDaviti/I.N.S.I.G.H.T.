"""The INSIGHT_ANALYSIS switch at the HTTP edge (reading-finish R3): GET /api/config and
the 409 analysis_disabled answer from every mutating analysis endpoint when it is off."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")

if DATABASE_URL:
    import main
    from insight_core.settings import Settings

OFF = "off"
ON = "on"


def _settings(flag: str):
    return mock.patch.object(main, "get_settings", return_value=Settings(analysis_enabled=flag == ON))


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping route tests")
class ConfigRouteTests(unittest.TestCase):
    def test_analysis_is_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INSIGHT_ANALYSIS", None)
            main.get_settings.cache_clear()
            try:
                result = asyncio.run(main.get_config())
            finally:
                main.get_settings.cache_clear()
        self.assertEqual(result, {"analysis_enabled": False})

    def test_config_reports_analysis_on(self):
        with _settings(ON):
            result = asyncio.run(main.get_config())
        self.assertEqual(result, {"analysis_enabled": True})


# Every endpoint that writes analysis output or calls Gemini. Read-only GETs (stored
# briefings, stories, inbox) keep working so the data is there when the flag comes back on.
ANALYSIS_ENDPOINTS = (
    "rebuild_evidence_for_post", "rebuild_evidence_for_date",
    "rebuild_memory_for_post", "rebuild_memory_for_date",
    "rebuild_events_for_post", "rebuild_events_for_date",
    "refresh_post_timeline", "accept_story_candidate", "reject_story_candidate",
    "rebuild_inbox", "record_inbox_action",
    "get_post_summary", "chat_about_post", "get_post_highlights", "get_reddit_comments_briefing",
    "run_expert",
    "generate_daily_briefing", "generate_daily_briefing_with_topics", "generate_weekly_briefing",
    "refresh_source_vertical_briefing",
    "build_youtube_channel_roadmap", "evaluate_youtube_video", "chat_with_youtube_video",
    "model_topics",
)


class _UntouchableBridge:
    """Any use of the bridge fails the test: an off endpoint must answer before it."""

    def __getattr__(self, name):
        raise AssertionError(f"bridge.{name} used while analysis is off")


def _call(endpoint):
    import inspect

    params = inspect.signature(endpoint).parameters
    return asyncio.run(endpoint(*[None] * len(params)))


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping route tests")
class AnalysisDisabledRouteTests(unittest.TestCase):
    def setUp(self):
        self.original_bridge = main.api_bridge
        main.api_bridge = _UntouchableBridge()

    def tearDown(self):
        main.api_bridge = self.original_bridge

    def test_each_analysis_endpoint_answers_409_when_off(self):
        with _settings(OFF):
            for name in ANALYSIS_ENDPOINTS:
                with self.subTest(endpoint=name):
                    response = _call(getattr(main, name))
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(json.loads(response.body)["error"], "analysis_disabled")

    def test_an_analysis_endpoint_runs_when_on(self):
        calls = []

        class Bridge:
            def rebuild_inbox(self, **kwargs):
                calls.append(kwargs)
                return {"success": True}

        main.api_bridge = Bridge()
        with _settings(ON):
            result = asyncio.run(main.rebuild_inbox(None))
        self.assertEqual(result, {"success": True})
        self.assertEqual(len(calls), 1)

    def test_reading_endpoints_stay_open_when_off(self):
        class Bridge:
            def get_stories(self, **kwargs):
                return {"success": True, "stories": []}

        main.api_bridge = Bridge()
        with _settings(OFF):
            result = asyncio.run(main.get_stories(status=None, story_kind=None, limit=100, offset=0))
        self.assertEqual(result["success"], True)


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping route tests")
class NoGeminiAtStartupTests(unittest.TestCase):
    def test_building_the_api_bridge_builds_no_gemini_client(self):
        from insight_api_bridge import InsightApiBridge

        with mock.patch("insight_core.processors.ai.gemini_processor.GeminiProcessor.__init__",
                        side_effect=AssertionError("GeminiProcessor built")):
            InsightApiBridge()


if __name__ == "__main__":
    unittest.main()
