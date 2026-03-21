import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.processors.ai.gemini_processor import GeminiProcessor


class VerticalBriefingPhase2Tests(unittest.TestCase):
    def test_fallback_collapses_duplicate_clusters_and_uses_story_and_entity_hints(self):
        processor = GeminiProcessor()
        posts = [
            {
                "id": "p-1",
                "title": "Autoresearch update one",
                "content": "Autoresearch continues the same work.",
                "content_html": "<p>Autoresearch continues the same work.</p>",
                "published_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
                "vertical_story_titles": ["Autoresearch Thread"],
                "vertical_primary_story_title": "Autoresearch Thread",
                "vertical_entity_names": ["Autoresearch", "OpenAI"],
                "vertical_shared_entity_names": ["Autoresearch"],
                "vertical_evidence_cluster_key": "cluster-alpha-1",
                "vertical_evidence_cluster_size": 2,
                "vertical_evidence_weight": 0.5,
                "vertical_track_hint": "Autoresearch Thread",
            },
            {
                "id": "p-2",
                "title": "Autoresearch update one repost",
                "content": "Autoresearch continues the same work.",
                "content_html": "<p>Autoresearch continues the same work.</p>",
                "published_at": datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc),
                "vertical_story_titles": ["Autoresearch Thread"],
                "vertical_primary_story_title": "Autoresearch Thread",
                "vertical_entity_names": ["Autoresearch", "OpenAI"],
                "vertical_shared_entity_names": ["Autoresearch"],
                "vertical_evidence_cluster_key": "cluster-alpha-1",
                "vertical_evidence_cluster_size": 2,
                "vertical_evidence_weight": 0.5,
                "vertical_track_hint": "Autoresearch Thread",
            },
            {
                "id": "p-3",
                "title": "Autoresearch update two",
                "content": "A second Autoresearch development lands later in the week.",
                "content_html": "<p>A second Autoresearch development lands later in the week.</p>",
                "published_at": datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc),
                "vertical_story_titles": ["Autoresearch Thread"],
                "vertical_primary_story_title": "Autoresearch Thread",
                "vertical_entity_names": ["Autoresearch", "OpenAI"],
                "vertical_shared_entity_names": ["Autoresearch"],
                "vertical_evidence_cluster_key": "cluster-alpha-2",
                "vertical_evidence_cluster_size": 1,
                "vertical_evidence_weight": 1.0,
                "vertical_track_hint": "Autoresearch Thread",
            },
            {
                "id": "p-4",
                "title": "Karpathy on agents",
                "content": "Karpathy keeps discussing agents and workflows.",
                "content_html": "<p>Karpathy keeps discussing agents and workflows.</p>",
                "published_at": datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc),
                "vertical_story_titles": [],
                "vertical_primary_story_title": "",
                "vertical_entity_names": ["Karpathy", "agents"],
                "vertical_shared_entity_names": ["Karpathy"],
                "vertical_evidence_cluster_key": "cluster-beta-1",
                "vertical_evidence_cluster_size": 1,
                "vertical_evidence_weight": 1.0,
                "vertical_track_hint": "Karpathy",
            },
            {
                "id": "p-5",
                "title": "Karpathy follow-up",
                "content": "Another Karpathy post revisits the same theme.",
                "content_html": "<p>Another Karpathy post revisits the same theme.</p>",
                "published_at": datetime(2026, 3, 11, 12, 0, tzinfo=timezone.utc),
                "vertical_story_titles": [],
                "vertical_primary_story_title": "",
                "vertical_entity_names": ["Karpathy", "agents"],
                "vertical_shared_entity_names": ["Karpathy"],
                "vertical_evidence_cluster_key": "cluster-beta-2",
                "vertical_evidence_cluster_size": 1,
                "vertical_evidence_weight": 1.0,
                "vertical_track_hint": "Karpathy",
            },
            {
                "id": "p-6",
                "title": "Single isolated note",
                "content": "A one-off note that should remain isolated.",
                "content_html": "<p>A one-off note that should remain isolated.</p>",
                "published_at": datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc),
                "vertical_story_titles": [],
                "vertical_primary_story_title": "",
                "vertical_entity_names": [],
                "vertical_shared_entity_names": [],
                "vertical_evidence_cluster_key": "cluster-gamma-1",
                "vertical_evidence_cluster_size": 1,
                "vertical_evidence_weight": 1.0,
                "vertical_track_hint": "Single isolated note",
            },
        ]

        result = processor._fallback_source_vertical_briefing(
            "Synthetic Source",
            "2026-03-01",
            "2026-03-31",
            posts,
        )

        self.assertIn("Synthetic Source", result["vertical_briefing"])
        self.assertEqual(len(result["tracks"]), 3)

        tracks_by_title = {track["title"]: track for track in result["tracks"]}
        autoresearch = tracks_by_title["Autoresearch Thread"]
        karpathy = tracks_by_title["Karpathy"]

        self.assertEqual(autoresearch["track_kind"], "project_thread")
        self.assertEqual(autoresearch["evidence_cluster_count"], 2)
        self.assertEqual(autoresearch["raw_post_count"], 3)
        self.assertEqual(len(autoresearch["timeline"]), 2)
        self.assertIn("story links: Autoresearch Thread", autoresearch["summary"])

        self.assertEqual(karpathy["track_kind"], "recurring_theme")
        self.assertEqual(karpathy["evidence_cluster_count"], 2)
        self.assertEqual(karpathy["raw_post_count"], 2)
        self.assertIn("shared entities: Karpathy", karpathy["summary"])

        all_post_ids = {
            post_id
            for track in result["tracks"]
            for post_id in track["post_ids"]
        }
        self.assertEqual(len(all_post_ids), 6)
        self.assertTrue(any(track["track_kind"] == "one_off_update" for track in result["tracks"]))


if __name__ == "__main__":
    unittest.main()
