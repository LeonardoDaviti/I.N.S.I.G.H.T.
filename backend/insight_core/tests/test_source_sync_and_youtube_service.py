import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import psycopg

from insight_core.services.source_config_sync_service import IMPORTED_KEY, SourceConfigSyncService
from insight_core.services.youtube_service import YouTubeService
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db, scratch_handle


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
        self.deleted.append(source_id)
        raise AssertionError("an import never deletes a source")


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

    def test_an_import_adds_and_updates_and_a_file_missing_sources_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "sources.json"
            self._write(config_path, [{"id": "https://new.example/feed.xml", "state": "enabled"},
                                      {"id": "https://off.example/feed.xml", "state": "disabled"}])
            fake_sources = FakeSourcesService([
                {"id": "kept", "platform": "rss", "handle_or_url": "https://kept.example/feed.xml", "enabled": True},
                {"id": "off-1", "platform": "rss", "handle_or_url": "https://off.example/feed.xml", "enabled": True},
            ])
            service = SourceConfigSyncService("postgresql:///unused", config_path=config_path)
            service.sources_service = fake_sources

            result = service.import_json()

            self.assertEqual((result["read"], result["added"], result["updated"], result["skipped"]), (True, 1, 1, []))
            self.assertEqual(fake_sources.added, [("rss", "https://new.example/feed.xml")])
            self.assertIn(("off-1", False), fake_sources.updated)
            self.assertEqual(fake_sources.deleted, [])
            self.assertIn("https://kept.example/feed.xml", {s["handle_or_url"] for s in fake_sources.sources})

    def test_a_missing_empty_or_broken_file_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "sources.json"
            fake_sources = FakeSourcesService([
                {"id": "kept", "platform": "rss", "handle_or_url": "https://kept.example/feed.xml", "enabled": True},
            ])
            service = SourceConfigSyncService("postgresql:///unused", config_path=config_path)
            service.sources_service = fake_sources
            for text in (None, "", '{"platforms": {"rss": {"sources": [{"id": "https://cut.exa', "[]", '{"platforms": 3}'):
                if text is not None:
                    config_path.write_text(text, encoding="utf-8")
                with self.subTest(text=text):
                    result = service.import_json()
                    self.assertEqual((result["read"], result["added"], result["updated"]), (False, 0, 0))
            self.assertEqual((fake_sources.added, fake_sources.updated, fake_sources.deleted), ([], [], []))

    def test_a_bad_entry_or_a_source_added_meanwhile_is_skipped_and_the_rest_imported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "sources.json"
            config_path.write_text(json.dumps({"platforms": {
                "rss": {"sources": ["not an entry", {"state": "enabled"}, {"id": "https://raced.example/feed.xml"},
                                    {"id": "https://good.example/feed.xml", "state": "enabled"}]},
                "youtube": {"sources": "not a list"},
            }}), encoding="utf-8")
            fake_sources = FakeSourcesService([])
            # Another container's start added this one between the read and the add.
            fake_sources.get_all_sources = lambda: []
            fake_sources.sources.append({"id": "r", "platform": "rss", "handle_or_url": "https://raced.example/feed.xml",
                                         "enabled": True})
            service = SourceConfigSyncService("postgresql:///unused", config_path=config_path)
            service.sources_service = fake_sources

            result = service.import_json()

            self.assertEqual(fake_sources.added, [("rss", "https://good.example/feed.xml")])
            self.assertEqual(len(result["skipped"]), 4, result["skipped"])
            self.assertTrue(any("already a source" in line for line in result["skipped"]))

    def test_the_export_is_atomic_a_failed_write_leaves_the_old_file_whole(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "sources.json"
            config_path.write_text('{"platforms": {}}\n', encoding="utf-8")
            service = SourceConfigSyncService("postgresql:///unused", config_path=config_path)
            service.sources_service = FakeSourcesService([
                {"id": "1", "platform": "rss", "handle_or_url": "https://example.com/feed.xml", "enabled": True},
            ])

            def cut_short(document, handle, **kwargs):
                handle.write('{"platforms": {"rss"')
                raise OSError("disk full")

            with mock.patch("insight_core.services.source_config_sync_service.json.dump", side_effect=cut_short):
                with self.assertRaises(OSError):
                    service.export_db_to_json()

            self.assertEqual(config_path.read_text(encoding="utf-8"), '{"platforms": {}}\n')
            self.assertEqual(sorted(p.name for p in Path(tmpdir).iterdir()), ["sources.json"], "no temporary file left")
            service.export_db_to_json()
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["platforms"]["rss"]["sources"],
                             [{"id": "https://example.com/feed.xml", "state": "enabled"}])

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

            first = service.import_json()
            second = service.import_json()

            self.assertEqual((first["skipped"], second["skipped"]), ([], []))
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

            service.import_json()

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

            result = service.import_json()

            self.assertEqual(result["skipped"], [])
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
            service.import_json()
            self.assertEqual({s["handle_or_url"]: s["in_main_digest"] for s in fresh.sources},
                             {"https://rss.arxiv.org/rss/cs.AI": False, "https://blog.example/feed.xml": True})


@requires_test_db
class ImportOnceDbTests(unittest.TestCase):
    """The containers' start imports a file once per database (issue 0071)."""

    def setUp(self):
        self.url = db_url()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_path = Path(self.tmp.name) / "sources.json"
        self.handle = scratch_handle()
        self._clean()
        self.addCleanup(self._clean)
        self.service = SourceConfigSyncService(self.url, config_path=self.config_path)

    def _clean(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            cur.execute("DELETE FROM system_settings WHERE key = %s", (IMPORTED_KEY,))

    def _write(self):
        self.config_path.write_text(json.dumps({"platforms": {"rss": {"sources": [
            {"id": self.handle, "state": "disabled"}]}}}), encoding="utf-8")

    def _count(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM sources WHERE handle_or_url = %s", (self.handle,))
            return cur.fetchone()[0]

    def test_the_first_start_imports_and_a_later_one_leaves_the_database_as_it_is(self):
        self._write()
        self.assertEqual(self.service.import_once()["added"], 1)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:   # Remove in the app
            delete_scratch_sources(cur)

        later = self.service.import_once()

        self.assertTrue(later["imported_before"])
        self.assertEqual(self._count(), 0, "a file still naming a removed source doesn't bring it back")

    def test_a_start_with_no_file_imports_the_file_a_later_start_finds(self):
        self.assertFalse(self.service.import_once()["read"])
        self._write()
        self.assertEqual(self.service.import_once()["added"], 1)
        self.assertEqual(self._count(), 1)


class YouTubeServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = YouTubeService("postgresql:///unused")

    def test_normalize_channel_ref_from_rss(self):
        result = self.service._normalize_channel_ref(
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCHkYOD-3fZbuGhwsADBd9ZQ"
        )
        self.assertEqual(result["channel_id"], "UCHkYOD-3fZbuGhwsADBd9ZQ")
        self.assertIn("/channel/UCHkYOD-3fZbuGhwsADBd9ZQ", result["channel_url"])

    def test_an_archive_lists_from_its_start_to_the_channels_end_on_the_scan_budget(self):
        """Issue 0015: an archive runs until the channel ends, so its listing is a channel scan."""
        runs = []
        self.service._run_ytdlp_json = lambda args, timeout: runs.append((args, timeout)) or {"entries": []}
        self.service.archive_channel_posts("https://www.youtube.com/@chan", start=106)
        args, timeout = runs[0]
        self.assertEqual(args[args.index("--playlist-start") + 1], "106")
        self.assertNotIn("--playlist-end", args)
        self.assertEqual(timeout, self.service.ytdlp_channel_scan_timeout_seconds)


if __name__ == "__main__":
    unittest.main()
