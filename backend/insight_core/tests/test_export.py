"""Export everything (issue 0079): the zip, its routes, and the restore that brings it back equal."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import main
from insight_core.db import import_export
from insight_core.services import registry
from insight_core.services.export_service import LAST_EXPORT_KEY, ExportService, live_bytes
from insight_core.services.source_config_sync_service import SourceConfigSyncService
from insight_core.tests._asgi import call
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db

FAKE_PROVIDER = "export-test"   # a credential row no provider reads


def checksums(url: str) -> dict:
    """{table: (rows, md5 of the rows' md5s in order)} for every table of the database."""
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace "
                    "AND relkind = 'r' ORDER BY 1")
        out = {}
        for (table,) in cur.fetchall():
            cur.execute(sql.SQL("SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) "
                                "FROM (SELECT md5(x::text) h FROM {} x) s").format(sql.Identifier(table)))
            out[table] = cur.fetchone()
        return out


@requires_test_db
class ExportRoundTripTests(unittest.TestCase):
    """Against the run's own database: export it, restore it into a new one, compare every table."""

    @classmethod
    def setUpClass(cls):
        cls.url = db_url()
        params = conninfo_to_dict(cls.url)
        cls.target_name = params["dbname"][: -len("_test")] + "_restored_test"
        cls.target = make_conninfo(cls.url, dbname=cls.target_name)
        cls.admin = make_conninfo(cls.url, dbname="postgres")

    def setUp(self):
        self._drop_target()
        self.addCleanup(self._drop_target)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            source_id = insert_scratch_source(cur)
            cur.execute("INSERT INTO posts (source_id, url, title, content) VALUES (%s, %s, %s, %s)",
                        (source_id, f"https://test.invalid/export/{source_id}", 'A "quoted", title\nover two lines',
                         "Body with a tab\tand a comma, and ünïcode"))
            cur.execute("INSERT INTO credentials (provider, key, ciphertext, last4) VALUES (%s, 'k', %s, 'fake') "
                        "ON CONFLICT DO NOTHING", (FAKE_PROVIDER, b"\x00not-a-real-secret\xff"))
        self.addCleanup(self._clean)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _clean(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            cur.execute("DELETE FROM credentials WHERE provider = %s", (FAKE_PROVIDER,))

    def _drop_target(self):
        with psycopg.connect(self.admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(self.target_name)))

    def export(self, include_logins: bool, *, keep_last: bool = False) -> Path:
        path = Path(self.tmp.name) / "export.zip"
        with path.open("wb") as handle:
            for piece in ExportService(self.url).stream(include_logins=include_logins):
                handle.write(piece)
        if not keep_last:   # the row a whole export keeps for the next estimate (0105) is written after its snapshot
            self._forget_last_export()
        return path

    def _forget_last_export(self):
        with psycopg.connect(self.url) as conn:
            conn.execute("DELETE FROM system_settings WHERE key = %s", (LAST_EXPORT_KEY,))

    def test_the_estimate_counts_live_rows_not_dead_space(self):
        """Issue 0105: the estimate was the tables' size, dead space included (55% high on the lab)."""
        self._forget_last_export()
        service = ExportService(self.url)
        before = service.info()
        self.assertEqual((before["estimate_basis"], before["last_export"]), ("live_rows", None))
        # Dead space and nothing else: a row rewritten many times (no trigger on credentials), ending as it was.
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_table_size('credentials')")
            disk = cur.fetchone()[0]
            for _ in range(200):
                cur.execute("UPDATE credentials SET ciphertext = %s WHERE provider = %s",
                            (os.urandom(4000), FAKE_PROVIDER))
                conn.commit()
            cur.execute("UPDATE credentials SET ciphertext = %s WHERE provider = %s",
                        (b"\x00not-a-real-secret\xff", FAKE_PROVIDER))
            conn.commit()
            cur.execute("SELECT pg_table_size('credentials')")
            self.assertGreater(cur.fetchone()[0], disk + 100_000, "the rewrites left dead space")
        self.assertEqual(service.info()["estimate_bytes"], before["estimate_bytes"])

    def test_after_a_whole_export_the_estimate_is_its_real_size(self):
        """Issue 0105: once an export has run, its real size and time, grown with the live rows since."""
        self._forget_last_export()
        self.addCleanup(self._forget_last_export)
        path = self.export(include_logins=False, keep_last=True)
        service = ExportService(self.url)

        def estimate_now():
            with psycopg.connect(self.url) as conn, conn.cursor() as cur:
                now = live_bytes(cur, import_export.tables_in_load_order(cur))
                cur.execute("SELECT value FROM system_settings WHERE key = %s", (LAST_EXPORT_KEY,))
                kept = cur.fetchone()[0]
            return int(kept["bytes"] * now / kept["stored_bytes"]), kept

        info = service.info()
        expected, kept = estimate_now()
        self.assertEqual(info["estimate_basis"], "last_export")
        self.assertEqual((info["last_export"]["bytes"], kept["bytes"]), (path.stat().st_size, path.stat().st_size))
        self.assertFalse(info["last_export"]["logins_included"])
        self.assertIsNotNone(info["last_export"]["at"])
        self.assertEqual(info["estimate_bytes"], expected)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            source_id = insert_scratch_source(cur)
            cur.execute("INSERT INTO posts (source_id, url, content) VALUES (%s, %s, %s)",
                        (source_id, f"https://test.invalid/grown/{source_id}", uuid.uuid4().hex * 30))
        after = service.info()
        self.assertGreater(after["estimate_bytes"], info["estimate_bytes"], "grown with the rows")
        self.assertEqual(after["estimate_bytes"], estimate_now()[0])

    def test_the_progress_reaches_the_other_api_process(self):
        """0112 Decided 11: two API processes; the export streams from one, its progress is asked of the other."""
        import tempfile
        shared = tempfile.mkdtemp()
        streaming, other = ExportService(self.url, progress_dir=shared), ExportService(self.url, progress_dir=shared)
        self.assertIsNone(other.progress("tok-abcdefgh"))
        stream = streaming.stream(include_logins=False, token="tok-abcdefgh")
        next(stream)
        seen = other.progress("tok-abcdefgh")
        self.assertEqual((seen["done"], seen["error"]), (False, None))
        for _ in stream:
            pass
        done = other.progress("tok-abcdefgh")
        self.assertTrue(done["done"])
        self.assertEqual(done["bytes"], streaming.progress("tok-abcdefgh")["bytes"])
        self.assertIsNone(other.progress("../etc/passwd"))      # a token names a file only when it is one

    def test_a_stopped_export_keeps_no_size(self):
        self._forget_last_export()
        stream = ExportService(self.url).stream(include_logins=False)
        next(stream)
        stream.close()
        self.assertEqual(ExportService(self.url).info()["estimate_basis"], "live_rows")

    def restore(self, path: Path, url: str):
        with contextlib.redirect_stdout(io.StringIO()):
            return import_export.restore(path, url)

    def test_with_logins_every_table_comes_back_equal(self):
        path = self.export(include_logins=True)
        before = checksums(self.url)
        loaded = self.restore(path, self.target)
        self.assertEqual(checksums(self.target), before)
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(archive.namelist()[:2], ["README.txt", "schema.sql"])
            self.assertIn("-- ==== 0001_init.sql ====", archive.read("schema.sql").decode())
        self.assertTrue(manifest["logins_included"])
        self.assertEqual({t["name"]: t["rows"] for t in manifest["tables"]}, loaded)
        self.assertNotIn("schema_migrations", loaded)   # the manifest's migrations instead
        self.assertEqual(manifest["last_migration"], sorted(p.name for p in import_export.MIGRATIONS_DIR.glob("*.sql"))[-1])

    def test_logins_left_out_by_default_and_everything_else_equal(self):
        path = self.export(include_logins=False)
        before = checksums(self.url)
        self.restore(path, self.target)
        after = checksums(self.target)
        self.assertEqual(after.pop("credentials")[0], 0)
        before.pop("credentials")
        self.assertEqual(after, before)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.read("credentials.csv").decode().strip(),
                             "provider,key,ciphertext,last4,updated_at,last_tested_at,last_test_ok,last_test_message")
            self.assertFalse(json.loads(archive.read("manifest.json"))["logins_included"])

    def test_the_restored_database_keeps_its_triggers_on(self):
        self.restore(self.export(include_logins=False), self.target)
        with psycopg.connect(self.target) as conn:
            disabled = conn.execute("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgenabled = 'D'").fetchone()[0]
        self.assertEqual(disabled, 0)

    def test_refuses_a_database_with_data(self):
        path = self.export(include_logins=False)
        with self.assertRaisesRegex(ValueError, "not empty"):
            self.restore(path, self.url)

    def test_refuses_an_export_from_a_newer_insight(self):
        path = self.export(include_logins=False)
        newer = Path(self.tmp.name) / "newer.zip"
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(newer, "w") as out:
            for item in source.infolist():
                data = source.read(item)
                if item.filename == "manifest.json":
                    manifest = json.loads(data)
                    manifest["migrations"].append({"version": "9999_from_the_future.sql", "applied_at": "2030-01-01T00:00:00+00:00"})
                    data = json.dumps(manifest).encode()
                out.writestr(item, data)
        with self.assertRaisesRegex(ValueError, "9999_from_the_future.sql"):
            self.restore(newer, self.target)


class ExportRouteTests(unittest.TestCase):
    def setUp(self):
        self.closed = False

        def stream(include_logins=False, token=None, name=None):
            try:
                yield b"PK-first"
                yield b"-logins" if include_logins else b"-no-logins"
            finally:
                self.closed = True

        export = SimpleNamespace(
            info=lambda: {"database_bytes": 10, "estimate_bytes": 4, "estimate_seconds": 1, "tables": 2,
                          "login_tables": ["credentials"], "logins_include": "the stored logins"},
            file_name=lambda: "insight-2026-11-05-1200.zip",
            stream=stream,
            progress=lambda token: {"file_name": "insight-2026-11-05-1200.zip", "bytes": 3, "done": True,
                                    "error": None} if token == "known-token" else None,
        )
        sync = SourceConfigSyncService.__new__(SourceConfigSyncService)
        sync.sources_service = SimpleNamespace(get_all_sources=lambda: [
            {"platform": "rss", "handle_or_url": "https://b.test.invalid/feed", "enabled": True},
            {"platform": "rss", "handle_or_url": "https://a.test.invalid/feed", "enabled": False, "in_main_digest": False},
        ])
        self.addCleanup(registry.use, registry.use(SimpleNamespace(export=export, source_config_sync=sync)))

    def test_info(self):
        status, _, body = call(main.app, "GET", "/api/export")
        self.assertEqual(status, 200)
        self.assertEqual(body["database_bytes"], 10)

    def test_the_zip_streams_as_an_attachment_and_its_generator_closes(self):
        status, headers, body = call(main.app, "GET", "/api/export/everything", query={"logins": "true"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "application/zip")
        self.assertEqual(headers["content-disposition"], 'attachment; filename="insight-2026-11-05-1200.zip"')
        self.assertEqual(body, b"PK-first-logins")
        self.assertTrue(self.closed)
        self.assertEqual(call(main.app, "GET", "/api/export/everything")[2], b"PK-first-no-logins")

    def test_progress(self):
        self.assertTrue(call(main.app, "GET", "/api/export/progress/known-token")[2]["done"])
        self.assertEqual(call(main.app, "GET", "/api/export/progress/other-token")[0], 404)

    def test_sources_json_in_the_shape_the_import_reads(self):
        status, headers, body = call(main.app, "GET", "/api/export/sources.json")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-disposition"], 'attachment; filename="sources.json"')
        self.assertEqual(body["platforms"]["rss"]["sources"], [
            {"id": "https://a.test.invalid/feed", "state": "disabled", "in_main_digest": False},
            {"id": "https://b.test.invalid/feed", "state": "enabled"},
        ])
        # The importer reads it back as the same sources.
        flat = SourceConfigSyncService._flatten_sources(None, body["platforms"], [])
        self.assertEqual(flat, [("rss", "https://a.test.invalid/feed", False, False),
                                ("rss", "https://b.test.invalid/feed", True, True)])


if __name__ == "__main__":
    unittest.main()
