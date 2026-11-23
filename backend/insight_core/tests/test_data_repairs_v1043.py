"""Stealth v10.43: data repairs run themselves after a deploy (services/data_repairs.py, migration 0177) — once per
version, a failure its own, a preview changes nothing, the page's asks run by the jobs process, the routes; and the
"Your interests" picker route. Invented repairs and sites only."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg

from insight_core.services import data_repairs as D
from insight_core.services import registry
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db


class Fake:
    def __init__(self, fail: bool = False):
        self.calls = []
        self.fail = fail

    def __call__(self, url, dry_run):
        self.calls.append(dry_run)
        if self.fail:
            raise SystemExit("No Saved source")   # a script's stop is a failure of this repair only
        return {"counts": {"fixed": 0 if dry_run else 2}, "sample": [{"label": f"p{i}"} for i in range(30)]}


@requires_test_db
class Registry(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url(), autocommit=True)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        self.tag = uuid.uuid4().hex[:8]
        self.addCleanup(self.cur.execute, "DELETE FROM data_repairs WHERE name LIKE %s", (f"t{self.tag}%",))

    def repair(self, n, fn, version="v1"):
        return D.Repair(f"t{self.tag}{n}", version, f"Repair {n}", "about", fn)

    def row(self, r):
        return D.listing(self.cur, [r])[0]

    def test_each_repair_runs_once_per_version_and_a_failure_blocks_no_other(self):
        ok, bad = Fake(), Fake(fail=True)
        a, b = self.repair("a", ok), self.repair("b", bad)
        D.run_due(db_url(), [b, a])
        D.run_due(db_url(), [b, a])
        self.assertEqual(ok.calls, [False])                       # once
        self.assertEqual(bad.calls, [False, False])               # a failure is tried again
        got = self.row(a)
        self.assertEqual((got["ran_version"], got["due"], got["last_run"]["counts"]), ("v1", False, {"fixed": 2}))
        self.assertEqual(len(got["last_run"]["sample"]), D.SAMPLE)
        bad_row = self.row(b)
        self.assertTrue(bad_row["due"])
        self.assertIn("No Saved source", bad_row["last_run"]["error"])
        D.run_due(db_url(), [self.repair("a", ok, version="v2")])  # a new version runs again
        self.assertEqual(ok.calls, [False, False])

    def test_a_preview_is_a_dry_run_and_records_no_version(self):
        fn = Fake()
        r = self.repair("p", fn)
        D.run_one(db_url(), r, dry_run=True)
        got = self.row(r)
        self.assertEqual(fn.calls, [True])
        self.assertEqual((got["ran_version"], got["last_run"], got["last_preview"]["counts"]), (None, None, {"fixed": 0}))
        self.assertTrue(got["last_preview"]["dry_run"])

    def test_the_pages_asks_are_run_by_the_jobs_side_once(self):
        fn = Fake()
        r = self.repair("q", fn)
        self.assertEqual(D.request(self.cur, r.name, "preview", [r])["requested"], "preview")
        self.assertTrue(D.has_requests(self.cur))
        self.assertEqual(fn.calls, [])                            # asking runs nothing
        D.run_requested(db_url(), [r])
        D.run_requested(db_url(), [r])
        self.assertEqual(fn.calls, [True])
        self.assertIsNone(self.row(r)["requested"])
        with self.assertRaises(KeyError):
            D.request(self.cur, "no such", "run", [r])
        with self.assertRaises(ValueError):
            D.request(self.cur, r.name, "undo", [r])

    def test_a_running_repair_is_not_run_twice_and_keeps_an_ask(self):
        fn = Fake()
        r = self.repair("r", fn)
        D.request(self.cur, r.name, "run", [r])
        self.cur.execute("UPDATE data_repairs SET running = 'run', running_since = now() WHERE name = %s", (r.name,))
        self.assertIsNone(D.run_one(db_url(), r, dry_run=False))
        self.assertFalse(D.has_requests(self.cur))                # waits while it runs
        D.run_requested(db_url(), [r])
        self.assertEqual(fn.calls, [])
        self.cur.execute("UPDATE data_repairs SET running_since = now() - interval '7 hours' WHERE name = %s", (r.name,))
        self.assertIsNotNone(D.run_one(db_url(), r, dry_run=False))   # a dead process's claim is taken over


@requires_test_db
class RealRepairs(unittest.TestCase):
    """The registered repairs call their scripts: a preview of the listing pages hides nothing."""

    def setUp(self):
        self.conn = psycopg.connect(db_url(), autocommit=True)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        self.source = insert_scratch_source(self.cur, settings_json=json.dumps({"display_name": "Example Blog"}))
        self.addCleanup(self.cur.execute, "DELETE FROM source_filters WHERE source_id = %s", (self.source,))
        self.addCleanup(self.cur.execute, "DELETE FROM posts WHERE source_id = %s", (self.source,))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (self.source,))
        self.addCleanup(self.cur.execute, "DELETE FROM data_repairs WHERE name = 'hide_listing_pages'")
        url = f"https://{uuid.uuid4().hex[:8]}.example.org/tag/widgets/"
        self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, external_id, title, content, published_at,
                                               metadata) VALUES (%s, %s, %s, '/tag/widgets/', 'Widgets', 'text', %s,
                                               '{"adapter": "generic_rss"}'::jsonb)""",
                         (self.source, url, url, datetime.now(timezone.utc)))
        self.url = url

    def hidden(self):
        self.cur.execute("SELECT count(*) FROM posts WHERE source_id = %s AND filtered_by IS NOT NULL", (self.source,))
        return self.cur.fetchone()[0]

    def test_preview_then_run(self):
        repair = D.by_name("hide_listing_pages")
        got = D.run_one(db_url(), repair, dry_run=True)
        self.assertNotIn("error", got)
        self.assertIn(self.url, [s.get("url") for s in got["sample"]])
        self.assertEqual(self.hidden(), 0)                        # a preview changes nothing
        got = D.run_one(db_url(), repair, dry_run=False)
        self.assertGreaterEqual(got["counts"]["hidden"], 1)
        self.assertEqual(self.hidden(), 1)

    def test_every_registered_repair_has_a_unique_name_and_a_version(self):
        names = [r.name for r in D.REPAIRS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), {"hide_listing_pages", "repair_track_rows", "repair_saved_titles",
                                      "repair_foreign_pages"})
        self.assertTrue(all(r.version and r.title for r in D.REPAIRS))


@requires_test_db
class Routes(unittest.TestCase):
    def setUp(self):
        self.addCleanup(registry.use, registry.use(SimpleNamespace(db_url=db_url())))
        self.conn = psycopg.connect(db_url(), autocommit=True)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        self.addCleanup(self.cur.execute, "DELETE FROM data_repairs WHERE name = 'repair_saved_titles'")

    def test_the_page_lists_and_asks_and_the_api_runs_nothing(self):
        from insight_core.tests.test_markx_api import call
        status, got = call("GET", "/api/operations/repairs")
        self.assertEqual(status, 200)
        self.assertEqual([r["name"] for r in got["repairs"]], [r.name for r in D.REPAIRS])
        status, got = call("POST", "/api/operations/repairs/repair_saved_titles/preview")
        self.assertEqual((status, got["requested"], got["last_preview"]), (200, "preview", None))
        status, got = call("POST", "/api/operations/repairs/repair_saved_titles/run")
        self.assertEqual((status, got["requested"]), (200, "run"))
        self.assertEqual(call("POST", "/api/operations/repairs/nope/run")[0], 404)
        self.cur.execute("SELECT last_run, last_preview, running FROM data_repairs WHERE name = 'repair_saved_titles'")
        self.assertEqual(self.cur.fetchone(), (None, None, None))


@requires_test_db
class InterestsFind(unittest.TestCase):
    def test_the_picker_finds_things_by_name(self):
        from insight_core.tests.test_markx_api import _Api, call

        class T(_Api):
            def runTest(inner):
                inner.cur.execute("""INSERT INTO mx_entities (name, key, type) VALUES ('Zorblax Engine', 'zorblax engine', 'software')
                                     RETURNING id::text""")
                eid = inner.cur.fetchone()[0]
                status, got = call("GET", "/api/markx/interests/find", query={"q": "zorbl"})
                inner.assertEqual((status, [g["id"] for g in got]), (200, [eid]))
                inner.assertEqual(call("GET", "/api/markx/interests/find", query={"q": "z"})[1], [])

        result = unittest.TestResult()
        T().run(result)
        self.assertEqual((result.errors, result.failures), ([], []))


if __name__ == "__main__":
    unittest.main()
