"""Issue 0210, the consumers (markx/consumers.py): a kind whose answers no feature reads is not asked: its tasks are
born closed (kept, with the reason), its open ones closed, its planner skipped; switched on, they open again. Against
the run's own _test database. Every post is synthetic."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.markx import consumers, repo, schemas, tasks
from insight_core.tests.test_markx_api import _Api, call


class Consumers(_Api):
    def setUp(self):
        super().setUp()
        consumers.forget()
        self.addCleanup(consumers.forget)

    def add(self, kind, text):
        with self.conn.transaction():
            return tasks.add(self.cur, kind, text, a=self.post())

    def test_every_kind_names_a_feature(self):
        self.assertEqual(sorted(set(schemas.KINDS) - set(consumers.CONSUMER)), [])
        self.assertEqual(sorted({f for f in consumers.CONSUMER.values()} - set(consumers.FEATURES)), [])

    def test_a_task_no_feature_reads_is_born_closed_and_never_leased(self):
        tid, new = self.add("back", "Back: a back question")
        row = repo.get_task(self.cur, tid)
        self.assertEqual((new, row["status"], row["last_error"]), (False, "failed", consumers.NOT_ASKED))
        _, body = self.lease(kind="back")
        self.assertEqual(body["tasks"], [])
        tid2, new2 = self.add("read", "Title: a reading question")
        self.assertEqual((new2, repo.get_task(self.cur, tid2)["status"]), (True, "open"))

    def test_switched_on_its_closed_tasks_open_and_off_its_open_ones_close(self):
        tid, _ = self.add("back", "Back: a question")
        status, got = call("POST", "/api/markx/settings/consumers", body={"feature": "back", "on": True})
        self.assertEqual((status, got["reopened"]), (200, 1))
        self.assertEqual(repo.get_task(self.cur, tid)["status"], "open")
        tid2, new2 = self.add("back", "Back: another question")
        self.assertTrue(new2)
        status, got = call("POST", "/api/markx/settings/consumers", body={"feature": "back", "on": False})
        self.assertEqual((status, got["closed"]), (200, 2))
        self.assertEqual({repo.get_task(self.cur, t)["last_error"] for t in (tid, tid2)}, {consumers.NOT_ASKED})
        self.assertEqual(call("POST", "/api/markx/settings/consumers", body={"feature": "nope", "on": True})[0], 400)

    def test_close_off_closes_what_was_open_before_the_switch(self):
        with self.conn.transaction():
            consumers.set_on(self.cur, "back", True)
        tid, _ = self.add("back", "Back: a question")
        self.cur.execute("UPDATE mx_settings SET value = '{}'::jsonb WHERE key = %s", (consumers.SETTING,))
        consumers.forget()
        with self.conn.transaction():
            self.assertEqual(consumers.close_off(self.cur), {"back": 1})
        self.assertEqual(repo.get_task(self.cur, tid)["status"], "failed")

    def test_the_overview_lists_the_features(self):
        status, body = call("GET", "/api/markx/overview")
        self.assertEqual(status, 200)
        got = {c["feature"]: c for c in body["consumers"]}
        self.assertEqual((got["back"]["on"], got["perspectives"]["on"], got["news"]["on"]), (False, True, True))
        self.assertIn("back", got["back"]["kinds"])


if __name__ == "__main__":
    unittest.main()
