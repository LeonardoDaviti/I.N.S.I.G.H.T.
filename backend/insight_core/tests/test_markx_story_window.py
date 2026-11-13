"""Issue 0144: stories for all history and the person page.

A: the story window (a setting, read by the decision run, the candidate finder's backfill and plan_checks), its
backfill newest first and resumable (old questions in pages, at the backfill's priority), News unchanged.
B: an entity's page lists the posts of the sources that are it (`by`: through its voice, or a handle the owner
confirmed), every Mark X story and, when none, the Mark IX story of its posts with all their posts and the original
first, and its loose posts by role. C: the old stories offered to label (10 a page, 30 a day) and the fallback.

Invented names and example hosts only. Every test rolls back (a database whose name ends in _test)."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.markx import candidates as C
from insight_core.markx import decide as DD
from insight_core.markx import entity_views, person_page as PP, repo, schemas, story_window as W, tasks
from insight_core.tests._db import clear_tables, db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES, _Api, call
from insight_core.tests.test_markx_entities import D as DAY, H as HOUR, T0 as E0, _Db

T = datetime(2100, 6, 1, 12, tzinfo=timezone.utc)
H, DAYS = timedelta(hours=1), timedelta(days=1)
LONG = 30
TABLES = MX_TABLES + ("mx_entity_sources", "mx_story_samples", "mx_story_sample_labels")


# ---- the pure rules -------------------------------------------------------------------------------------

class Rules(unittest.TestCase):
    def test_the_original_is_the_entitys_own_post_else_the_root(self):
        at = {"a": 1, "b": 2, "c": 3}.get
        self.assertEqual(PP.original_of(["c", "b", "a"], at, by={"b", "c"}), {"post": "b", "url": None, "why": "by"},
                         "the earliest post by the entity itself, before the story's root")
        self.assertEqual(PP.original_of(["c", "b", "a"], at, by=set(), root="b"), {"post": "b", "url": None, "why": "root"})
        self.assertEqual(PP.original_of(["b", "a"], at, by=set(), root="b", origin_url="https://e.example/x")["why"],
                         "origin", "Mark IX's outside page")
        self.assertEqual(PP.original_of(["c", "b", "a"], at, by=set())["post"], "a", "Mark X: its earliest member")

    def test_loose_roles_order(self):
        self.assertEqual([PP.loose_order(r) for r in ({"subject"}, {"actor", "mention"}, {"by"}, {"venue"},
                                                      {"mention"}, {"by", "mention"})], [0, 0, 1, 2, 3, 1])

    def test_a_source_names_itself_by_handle_profile_or_site(self):
        self.assertIn("ivokestrel", PP.source_keys("rss", "https://ivokestrel.bearblog.dev/feed/", None))
        self.assertIn("kestrel", PP.source_keys("rss", "https://gist.example.com/kestrel.atom", None))
        self.assertIn("ivokestrel", PP.source_keys("rss", "https://nitter.example/ikes/rss", "Ivo Kestrel"))
        self.assertNotIn("feed", PP.source_keys("rss", "https://news.example/feed.xml", None))

    def test_room_half_the_limit_and_twice_the_entities_budget(self):
        """v10.13.9: the window steps back only after a run under half its limit whose entities stage stayed within
        twice its budget."""
        self.assertIsNone(W.room(59, 120, entities=90, entity_budget=45))
        self.assertEqual(W.room(60, 120), "held: run took 60 s (steps back under 60 s, 50% of 120 s)")
        self.assertIn("held: the entities stage took 441 s", W.room(10, 120, entities=441, entity_budget=45))
        self.assertIsNone(W.room(10, 120, entities=441, entity_budget=None), "no budget: nothing to exceed")


# ---- A: the window --------------------------------------------------------------------------------------

@requires_test_db
class Window(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        clear_tables(self.cur, TABLES)
        schemas.load_guides(self.cur)
        self.now = T + 30 * H

    def post(self, at, title, *, vector=None):
        source = insert_scratch_source(self.cur, platform="telegram", settings_json=json.dumps({"display_name": "Example"}))
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        body = title + ". " + " ".join(f"word{k}{url[-6:]}" for k in range(LONG))
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (source, url, url, title, body, at))
        pid = str(self.cur.fetchone()[0])
        from insight_core.db.repo_post_parts import PostPartsRepository
        PostPartsRepository.write(self.cur, [pid])
        if vector is not None:
            repo.put_embedding(self.cur, post_id=pid, model="bge-m3", text_hash="h-" + pid, vector=vector,
                               model_sha256="a" * 64)
        return pid

    def ix_story(self, *members, reason="time"):
        self.cur.execute("SELECT min(published_at) FROM posts WHERE id = ANY(%s::uuid[])", (list(members),))
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, %s)",
                         (members[0], self.cur.fetchone()[0], len(members)))
        for n, m in enumerate(members):
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_id, parent_reason) "
                             "VALUES (%s, %s, 'report', %s, %s, %s)",
                             (m, members[0], f"v{n}", members[n - 1] if n else None, reason if n else None))

    def answer(self, kind, ans):
        self.cur.execute("SELECT id, kind, guide, a FROM mx_tasks WHERE kind = %s AND status = 'open'", (kind,))
        for tid, k, guide, a in self.cur.fetchall():
            c = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=ans)
            repo.answer_task(self.cur, tid)
            tasks.record(self.cur, {"kind": k, "guide": guide, "a": a}, c, ans)

    def read_all(self, ids):
        for pid in ids:
            tasks.read_task(self.cur, pid)
        self.answer("read", {"kind": "report", "events": "one", "lang": "en", "items": [], "mentions": [],
                             "main": {"headline_en": "Acme released Widget", "actors": ["Acme"], "object": "Widget",
                                      "action": "released"}})

    def test_the_setting_defaults_to_30_and_everything_is_null(self):
        self.assertEqual((W.setting(self.cur), W.days_for_run(self.cur, self.now)), (30, 30))
        W.set_window(self.cur, 120)
        self.assertEqual(W.days_for_run(self.cur, self.now), 30, "the backfill begins at 30 days")
        W.set_window(self.cur, None)
        self.assertIsNone(W.setting(self.cur))
        self.assertEqual(repo.get_setting(self.cur, W.PREVIOUS), 120, "the window everything replaced is kept")
        W.set_window(self.cur, 7)
        self.assertEqual(W.days_for_run(self.cur, self.now), 7, "a narrower window holds at once")

    def test_the_decision_run_reads_the_window_and_old_questions_come_in_pages(self):
        old = T - 60 * DAYS
        a, b = self.post(old, "Acme released Widget 4"), self.post(old + H, "Widget 4 by Acme is here")
        repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding", score=0.8)
        self.read_all([a, b])
        out = DD.run(self.cur, now=self.now)
        self.assertEqual(out["window_since"], (self.now - 30 * DAYS).isoformat())
        self.assertNotIn("pair", out["tasks_added"], "30 days: the old pair is never asked")
        self.assertNotIn("story_window", out, "30 days: no backfill, the run's counts as before")
        W.set_window(self.cur, 90)
        steps = []
        for _ in range(8):
            out = DD.run(self.cur, now=self.now)
            steps.append(out["story_window"]["days"])
            if out["story_window"]["old_added"].get("pair"):
                break
        self.assertEqual(steps, [30, 68], "back from the newest day; the weeks with no post skipped to the pair's week")
        self.cur.execute("SELECT priority FROM mx_tasks WHERE kind = 'pair'")
        self.assertEqual(self.cur.fetchall(), [(W.BACKFILL_PRIORITY,)], "an old question at the backfill's priority")
        self.answer("pair", {"relation": "same_event", "confidence": 90, "reason": "same release"})
        DD.run(self.cur, now=self.now)
        self.answer("pair", {"relation": "same_event", "confidence": 90, "reason": "same release"})
        out = DD.run(self.cur, now=self.now)
        self.assertEqual(out["changes"], {"new_pair": 1}, "Mark X's own story over history")
        self.assertEqual(out["news"]["rows"], 0, "News keeps its window: an old story never enters it")
        self.assertLessEqual(out["story_window"]["days"], 90)

    def test_a_run_adds_a_page_of_old_questions_and_the_rest_wait(self):
        ask = DD.Ask(self.cur, self.now, old_after=30, old_cap=1)
        self.assertIsNone(ask.answer("check", "an old question", priority=40))
        self.assertIsNone(ask.answer("check", "another old question", priority=41))
        self.assertIsNone(ask.answer("check", "a new question", priority=2))
        self.assertEqual((dict(ask.old_added), dict(ask.waiting_old), dict(ask.added)), ({"check": 1}, {"check": 1}, {"check": 1}))
        self.cur.execute("SELECT input, priority FROM mx_tasks ORDER BY input")
        self.assertEqual(self.cur.fetchall(), [("a new question", 2), ("an old question", W.BACKFILL_PRIORITY)])

    def test_the_step_waits_for_old_questions_and_candidates(self):
        W.set_window(self.cur, None)
        self.post(T - 400 * DAYS, "An old post")     # the oldest post: the floor
        self.assertFalse(W.advance(self.cur, self.now, waiting_old=3, candidates_left=0)["stepped"])
        self.assertFalse(W.advance(self.cur, self.now, waiting_old=0, candidates_left=5)["stepped"])
        self.post(T - 33 * DAYS, "A post of the next step")
        got = W.advance(self.cur, self.now, waiting_old=0, candidates_left=0)
        self.assertTrue(got["stepped"])
        self.assertEqual(W.days_for_run(self.cur, self.now), 37)
        W.advance(self.cur, self.now, waiting_old=0, candidates_left=0)
        self.assertGreaterEqual(W.days_for_run(self.cur, self.now), 400,
                                "no post for a year: one step on to the older post's week, not 52 empty ones")

    def test_a_step_needs_room_else_the_window_holds_and_says_why(self):
        """v10.13.9: every step makes the next run bigger, so a run that used half its limit (or twice the entities
        budget) holds the window, all else ready."""
        W.set_window(self.cur, None)
        self.post(T - 400 * DAYS, "An old post")
        self.post(T - 33 * DAYS, "A post of the next step")
        got = W.advance(self.cur, self.now, waiting_old=0, candidates_left=0, held="held: run took 70 s")
        self.assertEqual((got["stepped"], got["held"]), (False, "held: run took 70 s"))
        self.assertEqual(W.days_for_run(self.cur, self.now), 30)
        self.assertTrue(W.advance(self.cur, self.now, waiting_old=0, candidates_left=0, held=None)["stepped"])

    def test_the_decision_run_holds_the_window_when_it_left_no_room(self):
        old = T - 60 * DAYS
        a, b = self.post(old, "Acme released Widget 4"), self.post(old + H, "Widget 4 by Acme is here")
        repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding", score=0.8)
        self.read_all([a, b])
        W.set_window(self.cur, 90)
        out = DD.run(self.cur, now=self.now, limit=1e-6)       # any run is over half of a millionth of a second
        self.assertFalse(out["story_window"]["stepped"])
        self.assertTrue(out["story_window"]["held"].startswith("held: run took"), out["story_window"])
        self.assertEqual(W.days_for_run(self.cur, self.now), 30)
        out = DD.run(self.cur, now=self.now)                   # the default limit (120 s): room, it steps
        self.assertTrue(out["story_window"]["stepped"])
        self.assertNotIn("held", out["story_window"])

    def test_the_candidate_backfill_is_newest_first_and_resumes(self):
        from insight_core.tests.test_markx_candidates import at_cos
        W.set_window(self.cur, 60)
        ps = [self.post(T - (31 + n) * DAYS, f"Widget {n}", vector=at_cos(0.9, axis=n + 1)) for n in range(4)]
        recent = self.post(T - DAYS, "Widget now", vector=at_cos(0.9))
        got = C.backfill(self.cur, self.now, limit=2)
        self.assertEqual((got["posts"], got["left"]), (2, 3), "the step's posts, two a run: the newest first")
        self.cur.execute("SELECT post_id::text FROM mx_candidate_posts WHERE found_at IS NOT NULL")
        self.assertEqual({r[0] for r in self.cur.fetchall()}, {recent, ps[0]})
        got = C.backfill(self.cur, self.now, limit=2)
        self.assertEqual((got["posts"], got["left"]), (2, 1))
        W.set_window(self.cur, 30)
        self.assertEqual(C.backfill(self.cur, self.now), {}, "30 days: no backfill")

    def test_plan_checks_follow_the_window(self):
        old = self.now - 60 * DAYS
        ids = [self.post(old + n * H, f"Widget 4 news {n}") for n in range(3)]
        self.ix_story(*ids)
        self.assertEqual(tasks.plan_checks(self.cur, now=self.now), 0, "30 days: an old story is not checked")
        W.set_window(self.cur, None)
        repo.set_setting(self.cur, W.BACKFILL, {"reached": (self.now - 70 * DAYS).date().isoformat()})
        self.assertEqual(tasks.plan_checks(self.cur, now=self.now), 2)
        self.cur.execute("SELECT DISTINCT priority FROM mx_tasks WHERE kind = 'check'")
        self.assertEqual(self.cur.fetchall(), [(W.BACKFILL_PRIORITY,)])

    def test_the_fallback_needs_enough_old_labels_under_the_bar(self):
        W.set_window(self.cur, 120)
        W.set_window(self.cur, None)
        for n in range(W.MIN_LABELS):
            sid = str(uuid.uuid4())
            self.cur.execute("INSERT INTO mx_story_samples (story_id, first_at, offered_at) VALUES (%s, %s, %s)",
                             (sid, self.now - 90 * DAYS, self.now))
            PP.label_sample(self.cur, sid, "wrong" if n == 0 else "right")
            if n == W.MIN_LABELS - 2:
                self.assertIsNone(W.fallback(self.cur), "too few labels: no fallback yet")
        fb = W.fallback(self.cur)
        self.assertEqual(fb["days"], 120, "back to the window set before everything")
        self.assertIn("19 of 20", fb["why"])
        self.assertEqual(W.window(self.cur), 120)
        self.cur.execute("SELECT story_id FROM mx_story_sample_labels WHERE answer = 'wrong'")
        PP.label_sample(self.cur, str(self.cur.fetchone()[0]), "missed")
        self.assertIsNone(W.fallback(self.cur), "a missed post is no wrong story")



class Api(_Api):
    def setUp(self):
        super().setUp()
        clear_tables(self.cur, "mx_entity_sources, mx_story_samples, mx_story_sample_labels")

    def test_the_page_sets_the_story_window(self):
        self.assertEqual(call("GET", "/api/markx/settings")[1]["story_window_days"], 30, "no row: 30")
        status, body = call("POST", "/api/markx/settings/story-window", body={"days": None})
        self.assertEqual((status, body["story_window_days"]), (200, None))
        view = call("GET", "/api/markx/overview")[1]["story_window"]
        self.assertEqual((view["days"], view["run_days"], view["fallback"]), (None, 30, None))
        status, body = call("POST", "/api/markx/settings/story-window", body={"days": 365})
        self.assertEqual((status, body["story_window_days"]), (200, 365))
        self.assertEqual(call("POST", "/api/markx/settings/story-window", body={"days": 0})[0], 422)
        self.assertEqual(call("GET", "/api/markx/settings")[1]["reading_window_days"], 30, "the reading window apart")

    def test_a_sample_label_and_a_sources_answer(self):
        sid = str(uuid.uuid4())
        self.assertEqual(call("POST", f"/api/markx/stories/{sid}/sample", body={"answer": "right"})[0], 404, "never offered")
        self.cur.execute("INSERT INTO mx_story_samples (story_id, first_at) VALUES (%s, now() - interval '90 days')", (sid,))
        status, body = call("POST", f"/api/markx/stories/{sid}/sample", body={"answer": "right"})
        self.assertEqual((status, body["precision"]["old"]["right"]), (200, 1))
        self.assertEqual(call("POST", f"/api/markx/stories/{sid}/sample", body={"answer": "maybe"})[0], 400)
        self.assertEqual(call("POST", f"/api/markx/entities/{uuid.uuid4()}/sources",
                              body={"source_ids": [self.other], "answer": "yes"})[0], 404, "no such entity")


# ---- B and C: the page ----------------------------------------------------------------------------------

class Page(_Db):
    def setUp(self):
        super().setUp()
        clear_tables(self.cur, TABLES)
        schemas.load_guides(self.cur)
        self.self_src = insert_scratch_source(self.cur, platform="rss",
                                              settings_json=json.dumps({"display_name": "Notes"}))
        self.cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s",
                         (f"https://ivokestrel.bearblog.dev/feed/?t={uuid.uuid4().hex}", self.self_src))
        self.sources.append(self.self_src)          # index 5: the person's own blog

    def person(self):
        a = self.post(0, E0, title="Ivo Kestrel joins Acme")
        b = self.post(1, E0 + HOUR, title="Ivo Kestrel talks about Nimbus")
        self.mentions(a, ("Ivo Kestrel", "person", "subject"))
        self.mentions(b, ("Ivo Kestrel", "person", "mention"))
        self.stage()
        return self.entity_of(a), a, b

    def test_by_through_a_confirmed_handle_and_his_own_post_on_his_page(self):
        eid, a, b = self.person()
        own = self.post(5, E0 + 2 * HOUR, title="Weekend hack: a small tool")
        page = entity_views.entity_page(self.cur, eid, now=E0 + DAY)
        self.assertEqual([s["id"] for s in page["by"]["proposed"]], [self.self_src], "offered, not yet by")
        self.assertNotIn(own, [p["id"] for p in page["loose"]])
        self.assertEqual(page["posts"], 2)
        PP.answer_sources(self.cur, self.book(), eid, [self.self_src], "yes")
        page = entity_views.entity_page(self.cur, eid, now=E0 + DAY)
        self.assertEqual([(s["id"], s["via"]) for s in page["by"]["sources"]], [(self.self_src, "owner")])
        self.assertEqual((page["posts"], page["voices"], page["by"]["posts"]), (3, 3, 1), "counted in posts and voices")
        self.assertEqual([p["id"] for p in page["loose"]], [a, own, b], "subject, then by, then mentions")
        self.assertEqual(page["loose_counts"], {"report": 1, "by": 1, "other": 0, "mention": 1})
        self.assertEqual(next(p for p in page["loose"] if p["id"] == own)["roles"], ["by"])
        PP.answer_sources(self.cur, self.book(), eid, [self.self_src], "no")
        page = entity_views.entity_page(self.cur, eid, now=E0 + DAY)
        self.assertEqual((page["by"]["sources"], page["by"]["proposed"]), ([], []), "the newest answer counts")

    def test_by_through_the_voice_and_never_for_a_thing(self):
        eid, a, b = self.person()
        self.cur.execute("INSERT INTO voices (name, kind, entity_id, confirmed_at) VALUES ('Kestrel', 'person', %s, now()) "
                         "RETURNING id", (eid,))
        voice = self.cur.fetchone()[0]
        self.cur.execute("UPDATE sources SET voice_id = %s WHERE id = %s", (voice, self.sources[4]))
        own = self.post(4, E0 + 3 * HOUR, title="My thoughts")
        page = entity_views.entity_page(self.cur, eid, now=E0 + DAY)
        self.assertIn((self.sources[4], "voice"), [(s["id"], s["via"]) for s in page["by"]["sources"]])
        self.assertIn(own, [p["id"] for p in page["loose"]])
        thing = self.post(2, E0, title="Nimbus 5 is out")
        self.mentions(thing, ("Notes", "product", "subject"))
        self.stage()
        tp = entity_views.entity_page(self.cur, self.entity_of(thing), now=E0 + DAY)
        self.assertEqual(tp["by"], {"sources": [], "proposed": [], "posts": 0}, "a product has no by")

    def test_a_mark_ix_story_with_all_its_posts_and_the_original_first(self):
        eid, a, b = self.person()
        PP.answer_sources(self.cur, self.book(), eid, [self.self_src], "yes")
        own = self.post(5, E0 - HOUR, title="Personal update")
        other = self.post(3, E0 + HOUR / 2, title="A channel repeats it")
        root = self.post(2, E0 - 2 * HOUR, title="First word of it")
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, 4)", (root, E0 - 2 * HOUR))
        for n, pid in enumerate([root, own, a, other]):
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice) VALUES (%s, %s, 'report', %s)",
                             (pid, root, f"v{n}"))
        page = entity_views.entity_page(self.cur, eid, now=E0 + DAY)
        ix = [s for s in page["stories"] if s["mark"] == "ix"]
        self.assertEqual(len(ix), 1)
        self.assertEqual({p["id"] for p in ix[0]["posts"]}, {root, own, a, other}, "every post of it, not only his")
        self.assertEqual((ix[0]["original"]["post"], ix[0]["original"]["why"]), (own, "by"))
        self.assertEqual(ix[0]["posts"][0]["id"], own, "the original first")
        self.assertNotIn(a, [p["id"] for p in page["loose"]])
        # a Mark X story holding the post wins: no Mark IX block for it
        sx = repo.add_story(self.cur, first_at=E0, run_id=None)
        for pid in (a, other):
            repo.open_membership(self.cur, story_id=sx, post_id=pid, role="member", reason="judge:pair", p=0.9,
                                 call_id=None, run_id=None, at=E0)
        page = entity_views.entity_page(self.cur, eid, now=E0 + DAY)
        self.assertEqual([s["mark"] for s in page["stories"]], ["ix", "x"],
                         "the Mark X story of a, and the Mark IX story of his own post (in no Mark X story); most voices first")
        x = page["stories"][1]
        self.assertEqual((x["original"]["post"], x["original"]["why"]), (a, "root"))

    def test_the_sample_offers_ten_a_page_and_thirty_a_day(self):
        eid, a, b = self.person()
        old = {str(uuid.uuid4()): E0 - (40 + n) * DAY for n in range(45)}
        old[str(uuid.uuid4())] = E0 - DAY        # a recent story is never offered
        now = E0 + DAY
        first = PP.offer(self.cur, eid, old, now)
        self.assertEqual(len(first), PP.SAMPLE_PAGE)
        self.assertEqual(PP.offer(self.cur, eid, old, now), first, "the same page offers the same stories again")
        PP.label_sample(self.cur, first[0]["story"], "right")
        again = PP.offer(self.cur, eid, old, now)
        self.assertEqual((again[-1]["story"], again[-1]["answer"]), (first[0]["story"], "right"), "the labelled last")
        pages = [{str(uuid.uuid4()): E0 - (40 + n) * DAY for n in range(10)} for _ in range(3)]
        got = [PP.offer(self.cur, eid, stories, now) for stories in pages]
        self.cur.execute("SELECT count(*) FROM mx_story_samples")
        self.assertEqual(self.cur.fetchone()[0], PP.SAMPLE_DAY, "30 a day, every page together")
        self.assertEqual([len(g) for g in got], [10, 10, 0], "the third page: the day is full")
        self.assertEqual(PP.offer(self.cur, eid, {str(uuid.uuid4()): E0 - 50 * DAY}, now), [], "the day is full")
        self.assertEqual(len(PP.offer(self.cur, eid, {str(uuid.uuid4()): E0 - 50 * DAY}, now + DAY)), 1, "a new day")
        with self.assertRaises(LookupError):
            PP.label_sample(self.cur, str(uuid.uuid4()), "right")


if __name__ == "__main__":
    unittest.main()
