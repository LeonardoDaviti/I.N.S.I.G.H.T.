"""The re-ask guard (0210, markx/holds.py): a kind's tasks planned in a day past the allowance are born held, leased
after every other task, never while stopped; new posts' tasks are never held. On a _test database; synthetic posts."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.markx import holds, repo, tasks
from insight_core.tests.test_markx_api import _Api, call, clear_tables

OLD = datetime.now(timezone.utc) - timedelta(days=20)


class _Holds(_Api):
    def setUp(self):
        super().setUp()
        clear_tables(self.cur, ("mx_holds",))
        holds.forget()
        self.addCleanup(holds.forget)
        with self.conn.transaction():
            holds.set_per_day(self.cur, 3)

    def old_post(self, n: int) -> str:
        """A post fetched and dated 20 days ago: not a new post's task."""
        pid = self.post(title=f"Archive post {n}", text=f"An archived post number {n}, long enough to read once. " * 3,
                        at=OLD - timedelta(minutes=n))
        self.cur.execute("UPDATE posts SET fetched_at = %s WHERE id = %s", (OLD, pid))
        return pid

    def reads(self, posts):
        with self.conn.transaction():
            return [tasks.read_task(self.cur, p)[0] for p in posts]

    def held(self, ids):
        return [repo.get_task(self.cur, t)["hold"] for t in ids]


class TheAllowance(_Holds):
    def test_past_the_days_allowance_an_old_posts_task_is_held_a_new_posts_never(self):
        ids = self.reads([self.old_post(n) for n in range(5)])
        key = holds.key_of("read", datetime.now(timezone.utc).date())
        self.assertEqual(self.held(ids), [None, None, None, key, key])
        fresh = self.reads([self.post(title="Today's news", text="Something happened today, said a source. " * 3)])
        self.assertEqual(self.held(fresh), [None])   # fetched now, dated now: the fresh lane's rule

    def test_the_embedders_kinds_are_never_held_and_no_guard_holds_nothing(self):
        self.assertIsNone(holds.hold_for(self.cur, "embed"))
        with self.conn.transaction():
            holds.set_per_day(self.cur, None)
        ids = self.reads([self.old_post(n) for n in range(5)])
        self.assertEqual(self.held(ids), [None] * 5)

    def test_the_count_is_the_databases_not_a_stale_one_of_this_process(self):
        self.reads([self.old_post(n) for n in range(3)])        # at the allowance on this process's own count
        self.cur.execute("DELETE FROM mx_tasks")                  # (another day, a cleared table: the count is read again)
        ids = self.reads([self.old_post(n) for n in range(10, 12)])
        self.assertEqual(self.held(ids), [None, None])


class TheLease(_Holds):
    def test_held_tasks_go_last_stopped_ones_never_released_ones_in_their_turn(self):
        ids = self.reads([self.old_post(n) for n in range(5)])
        key = repo.get_task(self.cur, ids[3])["hold"]
        _, body = self.lease(limit=3)
        self.assertEqual(sorted(t["id"] for t in body["tasks"]), sorted(map(str, ids[:3])))
        with self.conn.transaction():
            holds.set_state(self.cur, key, "stopped")
        _, body = self.lease(limit=10)
        self.assertEqual(body["tasks"], [])
        status, got = call("POST", "/api/markx/holds", body={"key": key, "state": "released"})
        self.assertEqual((status, got["state"]), (200, "released"))
        _, body = self.lease(limit=10)
        self.assertEqual(sorted(t["id"] for t in body["tasks"]), sorted(map(str, ids[3:])))
        more = self.reads([self.old_post(n) for n in range(20, 22)])   # released: the day's excess is not held
        self.assertEqual(self.held(more), [None, None])

    def test_a_held_task_waits_behind_a_newer_one_that_is_not(self):
        ids = self.reads([self.old_post(n) for n in range(4)])      # the fourth held
        with self.conn.transaction():
            holds.set_per_day(self.cur, 100)
        later = self.reads([self.old_post(30)])                      # planned later, older post, not held
        _, body = self.lease(limit=4)
        self.assertNotIn(str(ids[3]), [t["id"] for t in body["tasks"]])
        _, body = self.lease(limit=4)
        self.assertEqual([t["id"] for t in body["tasks"]], [str(ids[3])])

    def test_a_bad_state_or_key_is_refused(self):
        self.assertEqual(call("POST", "/api/markx/holds", body={"key": "read:2026-11-16", "state": "gone"})[0], 400)
        self.assertEqual(call("POST", "/api/markx/holds", body={"key": "read:yesterday", "state": "low"})[0], 400)


class ThePage(_Holds):
    def test_the_overview_shows_each_hold_with_its_tasks_and_their_price(self):
        done = self.reads([self.old_post(n) for n in range(3)])
        self.answer(*[(t, {"kind": "report", "events": "one", "lang": "en", "items": [], "mentions": [],
                           "main": {"headline_en": "Acme did a thing", "actors": ["Acme"], "object": "thing",
                                    "action": "did"}}) for t in done])
        self.reads([self.old_post(n) for n in range(10, 14)])
        status, body = call("GET", "/api/markx/overview")
        self.assertEqual(status, 200, body)
        got = body["holds"]
        self.assertEqual(got["per_day"], 3)
        (h,) = got["holds"]
        self.assertEqual((h["kind"], h["open"], h["state"]), ("read", 4, "low"))
        each = (100 * 0.10 + 20 * 0.50) / 1e6           # the answers' stored tokens at Haiku's list price
        self.assertAlmostEqual(h["est_usd"], round(each * 4, 2))
        self.assertTrue(h["reason"].startswith("held: 4 readings"), h["reason"])

    def test_the_allowance_is_set_on_the_page(self):
        status, body = call("POST", "/api/markx/settings/reask-guard", body={"per_day": 5000})
        self.assertEqual((status, body["per_day"]), (200, 5000))
        status, body = call("POST", "/api/markx/settings/reask-guard", body={"per_day": None})
        self.assertEqual((status, body["per_day"]), (200, None))


if __name__ == "__main__":
    unittest.main()
