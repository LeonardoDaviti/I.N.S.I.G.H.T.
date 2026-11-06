"""Mark X's incremental decision runs (issue 0116): a run reads again only what changed since the last one, and its
result is a full run's: after each incremental run, a full run of the same snapshot writes nothing (no membership,
connection or News row changes) and its check (the incremental reading of that snapshot against the full one) finds
no difference. A memo gone wrong is caught by that check, with its stories. The DB tests run only on a database whose
name ends in _test."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.markx import decide as D
from insight_core.markx import incremental as I
from insight_core.markx import repo, schemas, tasks
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES

T = datetime(2100, 3, 1, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)
LONG = 30


@requires_test_db
class Incremental(unittest.TestCase):
    """On a test database, in one transaction rolled back after each test."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.addCleanup(I.forget)
        self.cur = self.conn.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas.load_guides(self.cur)
        I.forget()
        self.now = T + 30 * H

    # -- the scene ----------------------------------------------------------------------------------------
    def post(self, hours, title):
        source = insert_scratch_source(self.cur, platform="telegram", settings_json=json.dumps({"display_name": "Example"}))
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
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
                             (m, members[0], f"v{n}", members[n - 1] if n else None, "time" if n else None))
        return members[0]

    def answer(self, kind, answer_of, limit=None):
        self.cur.execute("SELECT id, kind, guide, a, b FROM mx_tasks WHERE kind = %s AND status = 'open' ORDER BY id",
                         (kind,))
        n = 0
        for tid, k, guide, a, b in self.cur.fetchall()[:limit]:
            ans = answer_of(str(a), str(b) if b else None)
            call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=ans)
            repo.answer_task(self.cur, tid)
            tasks.record(self.cur, {"kind": k, "guide": guide, "a": a}, call, ans)
            n += 1
        return n

    def read_all(self, ids):
        for pid in ids:
            tasks.read_task(self.cur, pid)
        self.answer("read", lambda a, b: {"kind": "report", "events": "one", "lang": "en", "items": [], "mentions": [],
                                          "main": {"headline_en": "Acme released Widget", "actors": ["Acme"],
                                                   "object": "Widget", "action": "released"}})

    def scene(self):
        """Two Mark IX stories (one checked), lone posts paired with each other and joined to the stories."""
        a, b, c = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 is out"), self.post(2, "Widget 4 hands-on")
        self.ix_story(a, b, c)
        d, e = self.post(3, "Beta launches Gizmo"), self.post(4, "Gizmo by Beta is here")
        self.ix_story(d, e)
        f, g, h = self.post(5, "Widget 4 review"), self.post(6, "Gizmo price"), self.post(7, "Gamma ships Doohickey")
        k = self.post(8, "Doohickey by Gamma")
        for x, y in ((a, f), (d, g), (h, k), (f, h)):
            repo.add_candidate(self.cur, kind="post_post", a=x, b=y, source="embedding", score=0.8)
        self.read_all([a, b, c, d, e, f, g, h, k])
        return a, b, c, d, e, f, g, h, k

    # -- the runs -----------------------------------------------------------------------------------------
    def go(self, **kw):
        return D.run(self.cur, now=self.now, **kw)

    def full_writes_nothing(self):
        """A full run of this snapshot, in a savepoint undone after: it must change nothing the incremental run left,
        and its check must find no difference. The memo is put back, so the next run is incremental again."""
        db = I._db(self.cur)
        kept = I._memos.get(db)
        self.cur.execute("SAVEPOINT full_check")
        try:
            out = self.go(full=True)
        finally:
            self.cur.execute("ROLLBACK TO SAVEPOINT full_check")
            if kept is not None:
                I._memos[db] = kept
        self.assertEqual(out["run"]["kind"], "full")
        self.assertEqual(out["check"], {"same": True})
        self.assertEqual(out["memberships"], {}, out["memberships"])
        self.assertEqual(out["connections"], {})
        self.assertFalse(out["news"]["written"])
        return out

    def test_every_incremental_run_is_a_full_runs_result(self):
        a, b, c, d, e, f, g, h, k = self.scene()
        first = self.go()
        self.assertEqual(first["run"]["kind"], "full")                 # no memo yet
        self.full_writes_nothing()
        answers = [("check", lambda x, y: {"relation": "different" if x == c else "same_event", "confidence": 90}),
                   ("join", lambda x, y: {"relation": "same_event", "confidence": 90, "reason": "same release"}),
                   ("pair", lambda x, y: {"relation": "same_event", "confidence": 90, "reason": "same launch"}),
                   ("join", lambda x, y: {"relation": "same_event", "confidence": 85, "reason": "same release"}),
                   ("pair", lambda x, y: {"relation": "same_event", "confidence": 80, "reason": "same launch"})]
        kinds = []
        for kind, answer_of in answers:
            self.answer(kind, answer_of, limit=1)
            out = self.go()
            kinds.append(out["run"]["kind"])
            self.full_writes_nothing()
        self.assertEqual(set(kinds), {"incremental"})
        self.cur.execute("SELECT count(*) FROM mx_story_posts WHERE valid_to IS NULL AND reason LIKE 'judge:%%'")
        self.assertGreater(self.cur.fetchone()[0], 0)                   # the answers changed stories

    def test_the_dirty_set_is_the_tasks_answered_since_and_the_closure_their_stories(self):
        a, b, c, d, e, f, g, h, k = self.scene()
        self.go()
        quiet = self.go()
        self.assertEqual((quiet["run"]["kind"], quiet["run"]["dirty_tasks"], quiet["run"]["closure"]),
                         ("incremental", 0, 0))
        self.assertEqual(quiet["run"]["texts_read"], 0)                 # nothing changed: no text read again
        n = self.answer("check", lambda x, y: {"relation": "different", "confidence": 95})
        self.assertEqual(n, 3)                                          # b and c in one story, e in the other
        out = self.go()
        self.assertEqual(out["run"]["dirty_tasks"], 3)
        self.assertEqual(out["run"]["dirty_posts"], 3)
        self.assertEqual(out["changes"], {"remove": 2})                 # e, the second voice of d and e: asked again
        self.assertEqual(out["tasks_reasked"], {"check": 1})
        self.assertGreaterEqual(out["run"]["closure"], 1)
        self.assertEqual(out["news"]["made"], "incremental")

    def test_a_new_post_or_a_changed_text_is_read_again(self):
        a, b, c, d, e, f, g, h, k = self.scene()
        self.go()
        self.cur.execute("UPDATE posts SET title = 'Acme released Widget 4 today' WHERE id = %s", (a,))
        from insight_core.db.repo_post_parts import PostPartsRepository
        PostPartsRepository.write(self.cur, [a])
        out = self.go()
        self.assertEqual(out["run"]["kind"], "incremental")
        self.assertEqual(out["run"]["texts_read"], 1)
        self.assertIn("posts", out["run"]["ix_changed"])
        self.assertEqual(out["news"]["made"], "full")                   # Mark IX's posts changed: News in full
        self.full_writes_nothing()

    def test_the_check_finds_a_memo_gone_wrong_with_its_stories(self):
        a, b, c, d, e, f, g, h, k = self.scene()
        self.go()
        self.answer("check", lambda x, y: {"relation": "different", "confidence": 95})
        self.go()
        memo = I._memos[I._db(self.cur)]
        for tid, calls in memo.calls.items():                          # a bug: the memo forgets every check answer
            if memo.keys.get(tid, ("",))[0] == "check":
                memo.calls[tid] = []
        out = self.go(full=True)
        self.assertFalse(out["check"]["same"])
        self.assertIn("stories", out["check"]["differences"])
        self.assertIn(c, json.dumps(out["check"]["differences"]))      # the stories are named by their posts

    def test_a_run_is_full_without_the_last_runs_memo_and_nightly(self):
        self.scene()
        self.assertEqual(self.go()["run"]["kind"], "full")
        self.assertEqual(self.go()["run"]["kind"], "incremental")
        I.forget()                                                     # a new process
        self.assertEqual(self.go()["run"]["kind"], "full")
        self.assertEqual(D.run(self.cur, now=self.now, config=D.Config(tau_join=0.7))["run"]["kind"], "full")  # a rule
        self.now += timedelta(days=1)                                  # past the night's NIGHTLY_HOUR
        out = D.run(self.cur, now=self.now, config=D.Config(tau_join=0.7))
        self.assertEqual((out["run"]["kind"], out["run"].get("nightly")), ("full", True))
        self.assertEqual(out["check"], {"same": True})
        self.assertEqual(D.run(self.cur, now=self.now, config=D.Config(tau_join=0.7))["run"]["kind"], "incremental")

    def test_a_failed_run_leaves_no_memo(self):
        self.scene()
        self.go()
        self.cur.execute("SAVEPOINT boom")
        with unittest.mock.patch.object(D, "persist", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.go()
        self.cur.execute("ROLLBACK TO SAVEPOINT boom")
        self.assertEqual(self.go()["run"]["kind"], "full")


import unittest.mock  # noqa: E402  (used above)

if __name__ == "__main__":
    unittest.main()
