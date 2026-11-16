"""Mark X's labels (issue 0086 F): the one tap on Mark X News members and its route, the Wilson interval, and (v10.22,
0216 D) the Labels queue gone: its routes answer 404 and its tables are dropped. Synthetic data only; the DB tests run
on a database whose name ends in _test."""
from __future__ import annotations

import json
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import psycopg

from insight_core.markx import decide as D, labels as L, repo, schemas, tasks
from insight_core.tests._db import clear_tables, db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES, call

T = datetime(2100, 3, 1, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)
LONG = 30


class Wilson(unittest.TestCase):
    def test_wilson(self):
        lo, hi = L.wilson(9, 10)
        self.assertAlmostEqual(lo, 0.5958, places=3)
        self.assertAlmostEqual(hi, 0.9821, places=3)
        self.assertEqual(L.wilson(0, 0), (0.0, 0.0))


@requires_test_db
class Labels(unittest.TestCase):
    """On a test database, in one transaction rolled back after each test: News members from a real decision run."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        clear_tables(self.cur, MX_TABLES)
        schemas.load_guides(self.cur)
        self.now = T + 30 * H

    def post(self, hours, title):
        source = insert_scratch_source(self.cur, platform="telegram", settings_json=json.dumps({"display_name": "Example"}))
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        # each post a text of its own: posts of one text are near-copies, never checked (0112 bug 3)
        body = title + ". " + " ".join(f"word{k}{url[-6:]}" for k in range(LONG))
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (source, url, url, title, body, T + hours * H))
        pid = str(self.cur.fetchone()[0])
        from insight_core.db.repo_post_parts import PostPartsRepository
        PostPartsRepository.write(self.cur, [pid])
        return pid

    def ix_story(self, *members):
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, %s)", (members[0], T, len(members)))
        for n, m in enumerate(members):
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_id, parent_reason) "
                             "VALUES (%s, %s, 'report', %s, %s, %s)",
                             (m, members[0], f"v{n}", members[n - 1] if n else None, "citation" if n else None))

    def answer(self, kind, answer_of):
        self.cur.execute("SELECT id, kind, guide, a FROM mx_tasks WHERE kind = %s AND status = 'open'", (kind,))
        for tid, k, guide, a in self.cur.fetchall():
            ans = answer_of(str(a))
            call_id = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=ans)
            repo.answer_task(self.cur, tid)
            tasks.record(self.cur, {"kind": k, "guide": guide, "a": a}, call_id, ans)

    def scene(self):
        a, b, c = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 is out"), self.post(2, "Widget 4 hands-on")
        self.ix_story(a, b, c)
        d, e = self.post(3, "Beta launches Gizmo"), self.post(4, "Gizmo by Beta is here")
        repo.add_candidate(self.cur, kind="post_post", a=d, b=e, source="embedding", score=0.8)
        for pid in (d, e):
            tasks.read_task(self.cur, pid)
        self.answer("read", lambda a: {"kind": "report", "events": "one", "lang": "en", "items": [], "mentions": [],
                                       "main": {"headline_en": "Beta launched Gizmo", "actors": ["Beta"],
                                                "object": "Gizmo", "action": "launched"}})
        D.run(self.cur, now=self.now)
        self.answer("check", lambda p: {"relation": "same_event" if p == b else "different",
                                        "confidence": 90 if p == b else 75, "reason": "why " + p[:4]})
        self.answer("pair", lambda p: {"relation": "same_event", "confidence": 65, "reason": "same launch"})
        D.run(self.cur, now=self.now)
        # a story-changing answer counts once asked again (0112 Decided 8): the run reopened the pair
        self.answer("pair", lambda p: {"relation": "same_event", "confidence": 65, "reason": "same launch"})
        D.run(self.cur, now=self.now)
        return a, b, c, d, e

    def test_one_tap_on_a_news_member_is_a_label_and_ok_takes_it_back(self):
        a, b, c, d, e = self.scene()
        self.cur.execute("SELECT story_id::text, reason FROM mx_story_posts WHERE post_id = %s AND valid_to IS NULL", (e,))
        story, reason = self.cur.fetchone()
        self.assertEqual(reason, "judge:pair")
        L.flag(self.cur, post=e, story=story, answer="wrong_story")
        self.assertEqual(L.flags(self.cur, [(e, story)]), {(e, story): "wrong_story"})
        L.flag(self.cur, post=e, story=story, answer="ok")
        self.assertEqual(L.flags(self.cur, [(e, story)]), {})
        self.cur.execute("SELECT count(*) FROM mx_labels WHERE item_kind = 'news_row'")
        self.assertEqual(self.cur.fetchone()[0], 2)                    # both rows kept
        with self.assertRaises(KeyError):
            L.flag(self.cur, post=a, story=str(uuid.uuid4()), answer="not_about")
        with self.assertRaises(ValueError):
            L.flag(self.cur, post=e, story=story, answer="maybe")
        page = __import__("insight_core.markx.news", fromlist=["page"]).page(self.cur, now=self.now)
        lines = [p for r in page["items"] for p in r["posts"] if p["id"] == e]
        self.assertTrue(lines and lines[0]["story"] == story and lines[0]["flag"] is None, json.dumps(page, default=str)[:3000])

    def test_the_queue_s_tables_are_gone_and_the_owner_s_labels_stay(self):
        """0150: mx_label_queues and mx_label_queue_items dropped, the jobs' "labels" row and check entry gone;
        mx_labels kept."""
        self.cur.execute("SELECT array_agg(relname ORDER BY relname) FROM pg_class WHERE relkind = 'r' "
                         "AND relname IN ('mx_label_queues', 'mx_label_queue_items', 'mx_labels')")
        self.assertEqual(self.cur.fetchone()[0], ["mx_labels"])
        self.cur.execute("SAVEPOINT s")
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.cur.execute("INSERT INTO mx_jobs (job) VALUES ('labels')")
        self.cur.execute("ROLLBACK TO SAVEPOINT s")


@requires_test_db
class Routes(unittest.TestCase):
    """The labels route through the app."""

    def setUp(self):
        from types import SimpleNamespace

        from insight_core.services import registry
        self.env = os.environ.get("INSIGHT_MARKX")
        os.environ["INSIGHT_MARKX"] = "on"
        self.addCleanup(lambda: os.environ.__setitem__("INSIGHT_MARKX", self.env) if self.env is not None
                        else os.environ.pop("INSIGHT_MARKX", None))
        self.addCleanup(registry.use, registry.use(SimpleNamespace(db_url=db_url())))
        self.conn = psycopg.connect(db_url(), autocommit=True)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        clear_tables(self.cur, MX_TABLES)
        self.addCleanup(clear_tables, self.cur, MX_TABLES)
        self.task = str(uuid.uuid4())

    def test_the_queue_s_routes_are_gone_and_the_news_tap_stays(self):
        for method, path in (("GET", "/api/markx/labels"), ("GET", "/api/markx/labels/precision"),
                             ("GET", f"/api/markx/labels/items/{self.task}")):
            self.assertIn(call(method, path)[0], (404, 405), path)
        self.assertIn(call("POST", "/api/markx/labels", body={"item": self.task, "answer": "same_event"})[0], (404, 405))
        status, body = call("POST", "/api/markx/labels/news",
                            body={"post": str(uuid.uuid4()), "story": str(uuid.uuid4()), "answer": "wrong_story"})
        self.assertEqual(status, 404)

    def test_404_when_off(self):
        with mock.patch.dict(os.environ, {"INSIGHT_MARKX": "off"}):
            self.assertEqual(call("POST", "/api/markx/labels/news", body={})[0], 404)


if __name__ == "__main__":
    unittest.main()
