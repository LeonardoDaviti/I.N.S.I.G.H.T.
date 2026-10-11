import json
import tempfile
import unittest
from pathlib import Path

from insight_core.services.source_config_sync_service import SourceConfigSyncService
from insight_core.services.youtube_service import YouTubeService


class FakeSourcesService:
    def __init__(self, sources):
        self.sources = list(sources)
        self.added = []
        self.updated = []
        self.deleted = []

    def get_all_sources(self):
        return list(self.sources)

    def add_source(self, platform, handle, *, in_main_digest=True):
        handle = handle.strip()                      # as SourcesService.add_source
        if any((s["platform"], s["handle_or_url"]) == (platform, handle) for s in self.sources):
            raise ValueError(f"{platform}/{handle} is already a source")
        source_id = f"{platform}:{handle}"
        self.sources.append(
            {
                "id": source_id,
                "platform": platform,
                "handle_or_url": handle,
                "enabled": True,
                "in_main_digest": in_main_digest,
            }
        )
        self.added.append((platform, handle))
        return {"source_id": source_id}

    def set_in_main_digest(self, source_id, in_main_digest):
        raise AssertionError("a sync must never overwrite an existing row's in_main_digest")

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

    def _write(self, config_path, sources):
        config_path.write_text(
            json.dumps({"metadata": {}, "platforms": {"rss": {"enabled": True, "sources": sources}}}),
            encoding="utf-8",
        )

    def test_a_padded_id_syncs_twice_without_a_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "sources.json"
            fake_sources = FakeSourcesService([
                {"id": "keep", "platform": "rss", "handle_or_url": "https://other.example/feed.xml", "enabled": True},
            ])
            self._write(config_path, [{"id": "  https://blog.example/feed.xml\n", "state": "enabled"},
                                      {"id": "https://other.example/feed.xml", "state": "enabled"}])
            service = SourceConfigSyncService("postgresql:///unused", config_path=config_path)
            service.sources_service = fake_sources

            first = service.sync_json_to_db(mirror=True)
            second = service.sync_json_to_db(mirror=True)

            self.assertEqual((first["success"], second["success"]), (True, True), second["stats"]["errors"])
            self.assertEqual(fake_sources.added, [("rss", "https://blog.example/feed.xml")])
            self.assertEqual(fake_sources.deleted, [])

    def test_sync_creates_source_with_in_main_digest_off(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "sources.json"
            self._write(config_path, [
                {"id": "https://rss.arxiv.org/rss/cs.AI", "state": "enabled", "in_main_digest": False},
                {"id": "https://blog.example/feed.xml", "state": "enabled"},
            ])
            fake_sources = FakeSourcesService([])
            service = SourceConfigSyncService("postgresql:///unused", config_path=config_path)
            service.sources_service = fake_sources

            service.sync_json_to_db(mirror=False)

            flags = {s["handle_or_url"]: s["in_main_digest"] for s in fake_sources.sources}
            self.assertEqual(flags, {"https://rss.arxiv.org/rss/cs.AI": False, "https://blog.example/feed.xml": True})

    def test_sync_never_overwrites_an_existing_rows_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "sources.json"
            self._write(config_path, [
                {"id": "https://rss.arxiv.org/rss/cs.AI", "state": "enabled", "in_main_digest": False},
            ])
            existing = {"id": "1", "platform": "rss", "handle_or_url": "https://rss.arxiv.org/rss/cs.AI",
                        "enabled": True, "in_main_digest": True}
            fake_sources = FakeSourcesService([existing])
            service = SourceConfigSyncService("postgresql:///unused", config_path=config_path)
            service.sources_service = fake_sources

            result = service.sync_json_to_db(mirror=True)

            self.assertTrue(result["success"])
            self.assertTrue(fake_sources.sources[0]["in_main_digest"], "the user's re-enable sticks")

    def test_export_round_trips_in_main_digest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "sources.json"
            service = SourceConfigSyncService("postgresql:///unused", config_path=config_path)
            service.sources_service = FakeSourcesService([
                {"id": "1", "platform": "rss", "handle_or_url": "https://rss.arxiv.org/rss/cs.AI",
                 "enabled": True, "in_main_digest": False},
                {"id": "2", "platform": "rss", "handle_or_url": "https://blog.example/feed.xml",
                 "enabled": True, "in_main_digest": True},
            ])

            service.export_db_to_json()

            entries = {e["id"]: e for e in json.loads(config_path.read_text(encoding="utf-8"))["platforms"]["rss"]["sources"]}
            self.assertIs(entries["https://rss.arxiv.org/rss/cs.AI"]["in_main_digest"], False)
            self.assertNotIn("in_main_digest", entries["https://blog.example/feed.xml"], "the default stays implicit")

            fresh = FakeSourcesService([])
            service.sources_service = fresh
            service.sync_json_to_db(mirror=False)
            self.assertEqual({s["handle_or_url"]: s["in_main_digest"] for s in fresh.sources},
                             {"https://rss.arxiv.org/rss/cs.AI": False, "https://blog.example/feed.xml": True})


class YouTubeServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = YouTubeService("postgresql:///unused")

    def test_normalize_channel_ref_from_rss(self):
        result = self.service._normalize_channel_ref(
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCHkYOD-3fZbuGhwsADBd9ZQ"
        )
        self.assertEqual(result["channel_id"], "UCHkYOD-3fZbuGhwsADBd9ZQ")
        self.assertIn("/channel/UCHkYOD-3fZbuGhwsADBd9ZQ", result["channel_url"])


if __name__ == "__main__":
    unittest.main()
