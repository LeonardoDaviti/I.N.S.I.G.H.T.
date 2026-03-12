import json
import tempfile
import unittest
from pathlib import Path

from backend.insight_core.services.source_config_sync_service import SourceConfigSyncService
from backend.insight_core.services.youtube_service import YouTubeService


class FakeSourcesService:
    def __init__(self, sources):
        self.sources = list(sources)
        self.added = []
        self.updated = []
        self.deleted = []

    def get_all_sources(self):
        return list(self.sources)

    def add_source(self, platform, handle):
        source_id = f"{platform}:{handle}"
        self.sources.append(
            {
                "id": source_id,
                "platform": platform,
                "handle_or_url": handle,
                "enabled": True,
            }
        )
        self.added.append((platform, handle))
        return {"source_id": source_id}

    def update_source_status(self, source_id, enabled):
        for source in self.sources:
            if source["id"] == source_id:
                source["enabled"] = enabled
        self.updated.append((source_id, enabled))
        return {"source_id": source_id, "enabled": enabled}

    def delete_source(self, source_id):
        self.sources = [source for source in self.sources if source["id"] != source_id]
        self.deleted.append(source_id)
        return True


class SourceConfigSyncServiceTests(unittest.TestCase):
    def test_export_db_to_json_writes_platform_document(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "sources.json"
            service = SourceConfigSyncService("postgresql:///unused", config_path=config_path)
            service.sources_service = FakeSourcesService(
                [
                    {"id": "1", "platform": "rss", "handle_or_url": "https://example.com/feed.xml", "enabled": True},
                    {"id": "2", "platform": "youtube", "handle_or_url": "UC1234567890123456789012", "enabled": False},
                ]
            )

            result = service.export_db_to_json()

            self.assertTrue(result["success"])
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["platforms"]["rss"]["sources"][0]["state"], "enabled")
            self.assertEqual(payload["platforms"]["youtube"]["sources"][0]["state"], "disabled")

    def test_sync_json_to_db_mirrors_add_update_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "sources.json"
            config_path.write_text(
                json.dumps(
                    {
                        "metadata": {},
                        "platforms": {
                            "rss": {
                                "enabled": True,
                                "sources": [
                                    {"id": "https://new.example/feed.xml", "state": "enabled"},
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            fake_sources = FakeSourcesService(
                [
                    {"id": "old-1", "platform": "rss", "handle_or_url": "https://old.example/feed.xml", "enabled": True},
                    {"id": "old-2", "platform": "rss", "handle_or_url": "https://new.example/feed.xml", "enabled": False},
                ]
            )
            service = SourceConfigSyncService("postgresql:///unused", config_path=config_path)
            service.sources_service = fake_sources

            result = service.sync_json_to_db(mirror=True)

            self.assertTrue(result["success"])
            self.assertIn(("old-2", True), fake_sources.updated)
            self.assertIn("old-1", fake_sources.deleted)


class YouTubeServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = YouTubeService("postgresql:///unused")

    def test_normalize_channel_ref_from_rss(self):
        result = self.service._normalize_channel_ref(
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCHkYOD-3fZbuGhwsADBd9ZQ"
        )
        self.assertEqual(result["channel_id"], "UCHkYOD-3fZbuGhwsADBd9ZQ")
        self.assertIn("/channel/UCHkYOD-3fZbuGhwsADBd9ZQ", result["channel_url"])

    def test_group_videos_clusters_series_titles(self):
        videos = [
            {"video_id": "aaa111bbb22", "title": "Agent Systems: Part 1", "published_at": "2025-01-01T00:00:00+00:00"},
            {"video_id": "ccc333ddd44", "title": "Agent Systems: Part 2", "published_at": "2025-01-02T00:00:00+00:00"},
            {"video_id": "eee555fff66", "title": "Random Office Tour", "published_at": "2025-01-03T00:00:00+00:00"},
        ]

        groups = self.service._group_videos(videos)

        self.assertEqual(len(groups), 2)
        clustered = next(group for group in groups if group["group_type"] == "topic_cluster")
        self.assertEqual(clustered["title"], "Agent Systems")
        self.assertEqual(len(clustered["videos"]), 2)


if __name__ == "__main__":
    unittest.main()
