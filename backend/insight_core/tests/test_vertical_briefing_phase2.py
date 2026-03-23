import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.processors.ai.gemini_processor import GeminiProcessor
from insight_core.services.briefing_service import BriefingService


class VerticalBriefingPhase2Tests(unittest.TestCase):
    def test_vertical_entity_signature_filters_noise_and_keeps_meaningful_names(self):
        service = BriefingService("postgresql://unused")

        self.assertEqual(
            service._vertical_entity_signature(
                {
                    "confidence": 0.92,
                    "entity": {"canonical_name": "They"},
                    "mention": {"mention_text": "They"},
                }
            ),
            ("", ""),
        )
        self.assertEqual(
            service._vertical_entity_signature(
                {
                    "confidence": 0.92,
                    "entity": {"canonical_name": "Anthropic"},
                    "mention": {"mention_text": "Anthropic"},
                }
            ),
            ("anthropic", "Anthropic"),
        )

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

    def test_normalize_vertical_briefing_result_backfills_uncovered_posts(self):
        service = BriefingService("postgresql://unused")
        posts = [
            {
                "id": "p-1",
                "title": "Agent tools update",
                "content": "Agent tooling keeps improving.",
                "published_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
                "vertical_story_titles": [],
                "vertical_primary_story_title": "",
                "vertical_event_titles": [],
                "vertical_shared_event_titles": [],
                "vertical_entity_names": ["OpenClaw"],
                "vertical_shared_entity_names": ["OpenClaw"],
                "vertical_category_names": ["tooling"],
                "vertical_shared_category_names": ["tooling"],
                "vertical_entity_overlap_count": 1,
                "vertical_evidence_cluster_key": "cluster-1",
                "vertical_evidence_cluster_size": 1,
                "vertical_track_hint": "OpenClaw",
            },
            {
                "id": "p-2",
                "title": "Policy note",
                "content": "A government policy update lands.",
                "published_at": datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc),
                "vertical_story_titles": [],
                "vertical_primary_story_title": "",
                "vertical_event_titles": ["Policy Regulation Update"],
                "vertical_shared_event_titles": ["Policy Regulation Update"],
                "vertical_entity_names": ["Shenzhen"],
                "vertical_shared_entity_names": [],
                "vertical_category_names": ["policy"],
                "vertical_shared_category_names": ["policy"],
                "vertical_entity_overlap_count": 0,
                "vertical_evidence_cluster_key": "cluster-2",
                "vertical_evidence_cluster_size": 1,
                "vertical_track_hint": "Policy Regulation Update",
            },
            {
                "id": "p-3",
                "title": "Research note",
                "content": "A research update arrives.",
                "published_at": datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc),
                "vertical_story_titles": [],
                "vertical_primary_story_title": "",
                "vertical_event_titles": [],
                "vertical_shared_event_titles": [],
                "vertical_entity_names": ["Mouse Cortex"],
                "vertical_shared_entity_names": [],
                "vertical_category_names": ["research"],
                "vertical_shared_category_names": ["research"],
                "vertical_entity_overlap_count": 0,
                "vertical_evidence_cluster_key": "cluster-3",
                "vertical_evidence_cluster_size": 1,
                "vertical_track_hint": "Mouse Cortex",
            },
        ]

        result = service._normalize_vertical_briefing_result(
            posts=posts,
            briefing_result={
                "tracks": [
                    {
                        "title": "Agent tools",
                        "summary": "Tooling thread",
                        "track_kind": "project_thread",
                        "post_ids": ["p-1"],
                        "timeline": [{"date": "2026-03-01", "summary": "Tooling moved", "post_ids": ["p-1"]}],
                    }
                ]
            },
            scope_label="Synthetic Source",
            start_date="2026-03-01",
            end_date="2026-03-03",
        )

        coverage = result["coverage"]
        self.assertTrue(coverage["residual_backfill_used"])
        self.assertEqual(coverage["covered_posts"], 3)
        self.assertEqual(coverage["coverage_ratio"], 1.0)
        all_post_ids = {
            post_id
            for track in result["tracks"]
            for post_id in track["post_ids"]
        }
        self.assertEqual(all_post_ids, {"p-1", "p-2", "p-3"})

    def test_build_vertical_source_profile_prefers_memory_signals(self):
        service = BriefingService("postgresql://unused")
        profile = service._build_vertical_source_profile(
            [
                {
                    "vertical_story_titles": ["Claude Memory Transfer"],
                    "vertical_shared_entity_names": ["Claude", "ChatGPT"],
                    "vertical_shared_event_titles": ["Release Launch"],
                    "vertical_shared_category_names": ["workflow", "agents"],
                    "vertical_track_hint": "Claude / ChatGPT",
                },
                {
                    "vertical_story_titles": ["Claude Memory Transfer"],
                    "vertical_shared_entity_names": ["Claude"],
                    "vertical_shared_event_titles": ["Release Launch"],
                    "vertical_shared_category_names": ["workflow"],
                    "vertical_track_hint": "Claude / ChatGPT",
                },
            ]
        )

        self.assertEqual(profile["posts_total"], 2)
        self.assertEqual(profile["story_linked_posts"], 2)
        self.assertEqual(profile["entity_overlap_posts"], 2)
        self.assertEqual(profile["event_overlap_posts"], 2)
        self.assertIn("Claude Memory Transfer", profile["dominant_story_titles"])
        self.assertIn("Claude", profile["dominant_entities"])
        self.assertIn("Release Launch", profile["dominant_events"])
        self.assertIn("workflow", profile["dominant_categories"])


if __name__ == "__main__":
    unittest.main()
