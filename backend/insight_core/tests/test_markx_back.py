"""0136 (Stealth v10.8): back in the news, in Shadow. The trigger (E, L, V, and V only without E or L), its windows and
exclusions, one candidate per story and window, the `back` kind (planned, capped, asked three times, answered), the
verdicts per post combined as the lab's bk_judge does, "unknown" on a split, and the rows and labels /markx shows.
Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import hashlib
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from insight_core.markx import anchors, back, decide, repo, schemas, tasks, validate
from insight_core.tests._db import insert_scratch_source
from insight_core.tests.test_markx_api import _Api, call
from insight_core.tests.test_markx_graph import unit

NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = timedelta(days=1)
FROZEN_GUIDE_MD5 = "0c748c76706392daf6efae7414da55a7"   # the lab's back_v3c.md, ported unchanged


def ans(*verdicts, old="Widget 4.1", new="The fix shipped."):
    return {"id": "x", "old_thing": old, "posts": [{"n": k + 1, "about": old, "verdict": v} for k, v in enumerate(verdicts)],
            "what_new": new}


class TheKind(unittest.TestCase):
    def test_back_is_the_frozen_guide(self):
        kind = schemas.KINDS["back"]
        self.assertEqual((kind.guide, kind.subject), ("back-v1", "story"))
        body = schemas.guide_body("back-v1")
        self.assertEqual(hashlib.md5(body.encode("utf-8")).hexdigest(), FROZEN_GUIDE_MD5)
        self.assertIn("back", tasks.PLANNERS)
        self.assertEqual(decide.Config().back_open, 50)

    def test_the_answer_is_checked(self):
        q = "OLD STORY:\n- [A, site, 2026-06-01T10:00] t — x\n\nNEW POSTS (one 72-hour window):\n1. [B, x, 2026-07-01T10:00] t — y\n2. [C, x, 2026-07-01T11:00] t — z"
        self.assertEqual(back.numbered(q), 2)
        self.assertIsNone(validate.check("back", ans("development", "retold"), q)[1])
        self.assertIn("post 3", validate.check("back", ans("retold", "retold", "related"), q)[1])
        self.assertIn("verdict", validate.check("back", ans("mixed"), q)[1])
        self.assertIn("posts", validate.check("back", {"old_thing": "x"}, q)[1])
        twice = {"posts": [{"n": 1, "verdict": "retold"}, {"n": 1, "verdict": "related"}]}
        self.assertIn("two verdicts", validate.check("back", twice, q)[1])

    def test_per_post_verdicts_combine_as_the_lab_does(self):
        self.assertEqual(back.relation(ans("retold", "development", "unrelated")), "development")
        self.assertEqual(back.relation(ans("unrelated", "related", "retold")), "retold")
        self.assertEqual(back.relation(ans("unrelated", "related")), "related")
        self.assertEqual(back.relation({"posts": [], "relation": "late_repeat"}), "retold")   # the lab's older word
        self.assertIsNone(back.relation(None))

    def test_the_majority_of_three_and_unknown_on_a_split(self):
        self.assertIsNone(back.verdict([ans("development")] * 2))
        v = back.verdict([ans("retold"), ans("development"), ans("retold", "development")])
        self.assertEqual(v, {"relation": "development", "runs": ["retold", "development", "development"]})
        self.assertEqual(back.verdict([ans("retold"), ans("related"), ans("unrelated")])["relation"], "unknown")

    def test_pages(self):
        self.assertEqual(back.norm("https://www.example.com/a/B/"), "example.com/a/b")
        self.assertIsNone(back.norm("https://example.com/"))
        self.assertIsNone(back.norm("https://x.com/someone"))
        self.assertEqual(back.norm("https://twitter.com/someone/status/1"), "x.com/someone/status/1")
        self.assertIsNone(back.norm("https://reddit.com/r/sub"))
        self.assertEqual(back.norm("https://youtube.com/watch?v=abc_1"), "youtube.com/watch/abc_1")

    def test_the_render_is_the_labs(self):
        P = lambda i, src, at, title, text: tasks.Post(id=i, kind="site", source=src, source_id=src, at=at, title=title, text=text)
        old = [P(f"o{k}", "Example Site", NOW - (40 - k) * DAY, f"Old {k}", "word " * 100) for k in range(5)]
        new = [P("n1", "Example Channel", NOW, "New", "  fresh\n text ")]
        text = back.render(old, new)
        lines = text.split("\n")
        self.assertEqual(lines[0], "OLD STORY:")
        self.assertTrue(lines[1].startswith(f"- [Example Site, site, {old[0].iso[:16]}] Old 0 — word word"))
        self.assertEqual(len(lines[1].split(" — ", 1)[1]), 300)
        self.assertEqual(lines[5], "(+1 more posts)")
        self.assertEqual(lines[6:], ["", "NEW POSTS (one 72-hour window):", f"1. [Example Channel, site, {NOW.isoformat()[:16]}] New — fresh text"])


class _Back(_Api):
    def setUp(self):
        super().setUp()
        self.third = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Example Blog"}))
        self.fourth = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Example News"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = ANY(%s::uuid[])", ([self.third, self.fourth],))
        self.stories = []
        self.addCleanup(self._drop_stories)
        # 0180: these tests are the old engine's; the anchors engine's Shadow rows are test_markx_anchors' (it turns
        # the Shadow back on)
        repo.set_setting(self.cur, anchors.SHADOW_KEY, self.shadow)

    shadow = False

    def _drop_stories(self):
        self.cur.execute("DELETE FROM story_posts WHERE story_id = ANY(%s::uuid[])", (self.stories,))
        self.cur.execute("DELETE FROM stories WHERE id = ANY(%s::uuid[])", (self.stories,))

    def at(self, days):
        return NOW - days * DAY

    def story(self, *members, origin=None):
        self.cur.execute("SELECT min(published_at) FROM posts WHERE id = ANY(%s::uuid[])", (list(members),))
        self.cur.execute("INSERT INTO stories (id, first_at, voices, origin_url) VALUES (%s, %s, %s, %s)",
                         (members[0], self.cur.fetchone()[0], len(members), origin))
        for n, m in enumerate(members):
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_id, parent_reason) "
                             "VALUES (%s, %s, 'report', %s, %s, %s)", (m, members[0], f"v{n}", members[n - 1] if n else None,
                                                                         "citation" if n else None))
        self.stories.append(members[0])
        return members[0]

    def subject(self, post, name="Widget 4.1", type="model"):
        with self.conn.transaction():
            tid, _ = tasks.entities_task(self.cur, post)
            call_id = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="m", valid=True, answer={})
            repo.add_mentions(self.cur, post_id=post, guide=schemas.KINDS["entities"].guide, call_id=call_id,
                              mentions=[{"span": name, "name": name, "name_key": tasks.name_key(name), "type": type,
                                         "role": "subject"}])

    def vector(self, post, v):
        repo.put_embedding(self.cur, post_id=post, model="bge-m3", text_hash=uuid.uuid4().hex, vector=v)

    def old(self, *, first=40, last=30, name="Widget 4.1", links=()):
        """A story of two sources, its first post `first` days back and its last `last`, both about `name`."""
        a = self.post(source=self.source, at=self.at(first), links=links)
        b = self.post(source=self.other, at=self.at(last), links=links)
        for p in (a, b):
            if name:
                self.subject(p, name)
        return self.story(a, b), (a, b)

    def new(self, days, source, name="Widget 4.1", links=()):
        p = self.post(source=source, at=self.at(days), links=links)
        if name:
            self.subject(p, name)
        return p

    def find(self, since_days=60, now=None):
        return back.find(self.cur, now=now or NOW, since=NOW - since_days * DAY)

    def stage(self, now=None, cap=50):
        with self.conn.transaction():
            return back.stage(self.cur, now=now or NOW, open_cap=cap)


class TheTrigger(_Back):
    def test_e_two_outside_sources_name_its_subject_in_72_hours(self):
        sid, _ = self.old()
        n1 = self.new(2, self.third)
        n2 = self.new(1, self.fourth)
        self.new(1, self.third, name="Widget 4.2")                  # another version is another name
        got, = self.find()
        self.assertEqual((got["story"], got["trig"], got["posts"], got["window_at"]), (sid, ["E"], [n1, n2], self.at(2)))
        self.assertEqual(got["post_trig"], {n1: ["E"], n2: ["E"]})

    def test_one_source_twice_or_two_sources_four_days_apart_is_no_burst(self):
        self.old()
        self.new(2, self.third)
        self.new(1, self.third)
        self.assertEqual(self.find(), [])
        self.new(6, self.fourth)
        self.assertEqual(self.find(), [])

    def test_l_a_page_the_story_links_twice_or_its_origin(self):
        page = "https://example.com/papers/widget-report"
        sid, _ = self.old(name=None, links=[(page, "the report")])
        n1 = self.new(2, self.third, name=None, links=[(page + "/", "report")])
        n2 = self.new(1, self.fourth, name=None, links=[(page, "the report")])
        got, = self.find()
        self.assertEqual((got["story"], got["trig"], sorted(got["posts"])), (sid, ["L"], sorted([n1, n2])))

    def test_a_page_only_one_member_links_or_a_home_page_is_not_the_storys(self):
        a = self.post(source=self.source, at=self.at(40), links=[("https://example.com/only-one", "x"),
                                                                ("https://example.com/", "home")])
        b = self.post(source=self.other, at=self.at(30), links=[("https://example.com/", "home")])
        self.story(a, b)
        for s in (self.third, self.fourth):
            self.new(1, s, name=None, links=[("https://example.com/only-one", "x"), ("https://example.com/", "home")])
        self.assertEqual(self.find(), [])

    def test_a_hub_page_linked_in_six_weeks_is_no_trigger(self):
        page = "https://example.com/docs/guide"
        self.old(name=None, links=[(page, "guide")])
        for w in range(6):
            self.post(source=self.third, at=self.at(60 + 7 * w), links=[(page, "guide")])
        for s in (self.third, self.fourth):
            self.new(1, s, name=None, links=[(page, "guide")])
        self.assertEqual(self.find(since_days=200), [])

    def test_v_only_without_e_or_l(self):
        base = unit(1)
        sid, (a, b) = self.old(name=None)
        for p in (a, b):
            self.vector(p, unit(2, 0.01, base))
        v1, v2 = self.new(2, self.third, name=None), self.new(1, self.fourth, name=None)
        far = self.new(1, self.third, name=None)
        for p in (v1, v2):
            self.vector(p, unit(3, 0.01, base))
        self.vector(far, unit(9))
        got, = self.find()
        self.assertEqual((got["trig"], sorted(got["posts"])), (["V"], sorted([v1, v2])))

    def test_an_e_burst_wins_over_an_earlier_v_burst_and_takes_its_window(self):
        base = unit(1)
        sid, (a, b) = self.old()
        for p in (a, b):
            self.vector(p, unit(2, 0.01, base))
        v1, v2 = self.new(10, self.third, name=None), self.new(9, self.fourth, name=None)
        for p in (v1, v2):
            self.vector(p, unit(3, 0.01, base))
        e1, e2 = self.new(2, self.third), self.new(1, self.fourth)
        self.vector(e1, unit(4, 0.01, base))
        got, = self.find()
        self.assertEqual((got["window_at"], got["trig"]), (self.at(2), ["E"]))
        self.assertEqual(got["posts"], [e1, e2])
        self.assertEqual(got["post_trig"][e1], ["E", "V"])

    def test_the_windows_first_14_days_and_last_7_days(self):
        self.old(first=20, last=5)                                  # its last post 5 days back: too fresh
        self.new(2, self.third), self.new(1, self.fourth)
        self.assertEqual(self.find(), [])
        self.old(first=10, last=9, name="Gadget 2")               # its first post 10 days back: too fresh
        self.new(1, self.third, name="Gadget 2"), self.new(0.5, self.fourth, name="Gadget 2")
        self.assertEqual(self.find(), [])

    def test_a_one_source_story_a_member_and_an_org_subject_are_not_counted(self):
        a = self.post(source=self.source, at=self.at(40))
        b = self.post(source=self.source, at=self.at(30))
        for p in (a, b):
            self.subject(p)
        self.story(a, b)                                            # one source
        c = self.post(source=self.source, at=self.at(40))
        d = self.post(source=self.other, at=self.at(30))
        for p in (c, d):
            self.subject(p, "Acme", type="org")
        self.story(c, d)                                            # an org subject
        for s in (self.third, self.fourth):
            self.new(1, s)
            self.new(1, s, name="Acme")
            self.subject(self.post(source=s, at=self.at(1)), "Acme", type="org")
        self.assertEqual(self.find(), [])

    def test_one_candidate_per_story_and_window_and_the_next_waits(self):
        sid, _ = self.old()
        self.new(3, self.third), self.new(2.5, self.fourth)
        first = self.stage(now=self.at(2))
        self.assertEqual((first["found"], first["added"]), (1, 1))
        self.assertEqual(self.stage(now=self.at(2))["added"], 0)    # the same window, once
        self.new(1, self.third), self.new(0.5, self.fourth)          # still within 7 days of its return
        self.assertEqual(self.stage()["added"], 0)
        self.cur.execute("SELECT count(*) FROM mx_back WHERE story = %s", (sid,))
        self.assertEqual(self.cur.fetchone()[0], 1)

    def test_at_most_six_posts_e_and_l_first(self):
        page = "https://example.com/papers/widget-report"
        sid, _ = self.old(links=[(page, "r")])
        srcs = [self.third, self.fourth, self.source, self.other]
        both = self.new(1, self.fourth, links=[(page, "r")])
        for k in range(7):
            self.new(2 - k * 0.1, srcs[k % 4])
        got, = self.find()
        self.assertEqual(len(got["posts"]), 6)
        self.assertEqual(got["posts"][0], both)
        self.assertEqual(got["trig"], ["E"])   # L from one source only: not a trigger


class TheQuestions(_Back):
    def candidate(self):
        sid, _ = self.old()
        self.new(2, self.third), self.new(1, self.fourth)
        self.stage()
        return sid

    def test_back_is_planned_capped_asked_three_times_and_shown(self):
        sid = self.candidate()
        self.cur.execute("SELECT t.kind, t.a::text, t.status, t.input FROM mx_back b JOIN mx_tasks t ON t.id = b.task_id")
        kind, a, status, text = self.cur.fetchone()
        self.assertEqual((kind, a, status), ("back", sid, "open"))
        self.assertEqual(back.numbered(text), 2)
        statuses = []
        for verdicts in (("retold", "development"), ("development", "unrelated"), ("related", "retold")):
            _, body = self.lease("back")
            self.assertEqual(len(body["tasks"]), 1, body)
            tid = body["tasks"][0]["id"]
            self.assertEqual(self.answer((tid, ans(*verdicts)))[1]["valid"], 1)
            statuses.append(self.row(tid)["status"])
        self.assertEqual(statuses, ["open", "open", "answered"])
        status, page = call("GET", "/api/markx/back")
        self.assertEqual(status, 200, page)
        row, = page["items"]
        self.assertEqual((row["story"], row["runs"], row["days_later"]), (sid, ["development", "development", "retold"], 38))
        self.assertEqual([p["verdict"] for p in row["posts"]], [None, None])   # per post no two runs agree here
        self.assertEqual(row["what_new"], ["The fix shipped."])
        self.assertEqual(page["counts"], {"candidates": 1, "development": 1})
        self.assertEqual(page["measured"]["words"], "measured 87% precise (68–96%), about 1 in 8 wrong")

    def test_the_cap(self):
        self.candidate()
        self.cur.execute("UPDATE mx_back SET task_id = NULL")   # synthetic: the candidate unasked again
        self.cur.execute("DELETE FROM mx_tasks WHERE kind = 'back'")
        with self.conn.transaction():
            self.assertEqual(back.plan(self.cur, open_cap=0), 0)
            self.assertEqual(back.plan(self.cur, open_cap=1), 1)
            self.assertEqual(back.plan(self.cur, open_cap=1), 0)

    def test_unknown_on_a_split_is_not_shown(self):
        self.candidate()
        for verdicts in (("retold",), ("related",), ("unrelated",)):
            _, body = self.lease("back")
            self.answer((body["tasks"][0]["id"], ans(*verdicts)))
        _, page = call("GET", "/api/markx/back")
        self.assertEqual((page["items"], page["counts"]), ([], {"candidates": 1, "unknown": 1}))

    def test_the_owners_labels_and_the_running_precision(self):
        self.candidate()
        for _ in range(3):
            _, body = self.lease("back")
            self.answer((body["tasks"][0]["id"], ans("development")))
        _, page = call("GET", "/api/markx/back")
        row = page["items"][0]["id"]
        self.assertEqual(page["precision"], {"labelled": 0, "development": 0, "precision": None})
        status, got = call("POST", "/api/markx/labels/back", body={"row": row, "answer": "retold"})
        self.assertEqual((status, got["label"], got["precision"]["precision"]), (200, "retold", 0.0))
        status, got = call("POST", "/api/markx/labels/back", body={"row": row, "answer": "development"})
        self.assertEqual(got["precision"], {"labelled": 1, "development": 1, "precision": 1.0})
        _, page = call("GET", "/api/markx/back")
        self.assertEqual(page["items"][0]["label"], "development")
        status, got = call("POST", "/api/markx/labels/back", body={"row": row, "answer": "undo"})
        self.assertEqual((got["label"], got["precision"]["labelled"]), (None, 0))
        self.assertEqual(call("POST", "/api/markx/labels/back", body={"row": row, "answer": "maybe"})[0], 400)
        self.assertEqual(call("POST", "/api/markx/labels/back", body={"row": str(uuid.uuid4()), "answer": "retold"})[0], 404)

    def test_mark_ix_is_only_read(self):
        self.old()
        self.new(2, self.third), self.new(1, self.fourth)
        ix = "SELECT (SELECT md5(string_agg(t::text, ',' ORDER BY t::text)) FROM story_posts t), " \
             "(SELECT md5(string_agg(t::text, ',' ORDER BY t::text)) FROM stories t)"
        self.cur.execute(ix)
        before = self.cur.fetchone()
        self.assertEqual(self.stage()["added"], 1)
        self.cur.execute(ix)
        self.assertEqual(self.cur.fetchone(), before)


if __name__ == "__main__":
    unittest.main()
