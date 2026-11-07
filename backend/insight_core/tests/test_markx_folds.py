"""0127 (Mark X v10.3): duplicates folded. The rule (ported from the lab's rv3_rules.rv3_roles), the group and the owner's
answers over it, the `read3` kind (guide read-v3, its input, its answer stored as a reading), its planner (members of
Mark X stories with 2+ members only, once a post), the News page's lines, the answer and count routes, the migration.
Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import hashlib
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from insight_core.markx import folds as F, news, repo, schemas, tasks, validate
from insight_core.tests.test_markx_api import _Api, call, reading

T0 = datetime(2100, 3, 1, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)


def m(n, event_type, origin, hours=None):
    return F.Member(id=f"p{n}", at=T0 + (n if hours is None else hours) * H, event_type=event_type, origin=origin)


def read3(event_type="model_release", origin="other", **over):
    return {**reading(), "type_why": "reports a release; short report rule", "event_type": event_type, "origin": origin, **over}


class TheRule(unittest.TestCase):
    """rv3_roles, as the lab ran it (round 1, F1 0.70 on unseen clusters)."""

    def test_the_makers_post_is_the_original_and_the_others_of_the_storys_type_retell_it(self):
        ms = [m(0, "leak_rumour", "other"), m(1, "model_release", "maker"), m(2, "model_release", "other"),
              m(3, "model_release", "relay"), m(4, "opinion_analysis", "other"), m(5, "model_release", "other")]
        self.assertEqual(F.roles(ms), {"p0": "leak", "p1": "original", "p2": "retelling", "p3": "retelling",
                                       "p4": "reaction", "p5": "retelling"})

    def test_with_no_maker_the_first_relay_is_the_original(self):
        ms = [m(0, "product_release", "other"), m(1, "product_release", "relay"), m(2, "product_release", "relay")]
        self.assertEqual(F.roles(ms), {"p0": "retelling", "p1": "original", "p2": "retelling"})

    def test_the_storys_type_is_the_most_common_news_type_and_a_tie_goes_to_the_first(self):
        ms = [m(0, "business_event", "other"), m(1, "model_release", "other"), m(2, "model_release", "other"),
              m(3, "business_event", "other"), m(4, "digest", "other"), m(5, "digest", "other"), m(6, "digest", "other")]
        self.assertEqual(F.story_type(ms), "business_event")          # 2 against 2: the first; digests don't count
        self.assertEqual(F.roles(ms)["p1"], "reaction")

    def test_a_leak_with_no_later_member_of_the_storys_type_is_a_reaction(self):
        ms = [m(0, "model_release", "other"), m(1, "leak_rumour", "other")]
        self.assertEqual(F.roles(ms)["p1"], "reaction")

    def test_no_news_type_no_story_type_nothing_retells(self):
        ms = [m(0, "opinion_analysis", "other"), m(1, "opinion_analysis", "other")]
        self.assertIsNone(F.story_type(ms))
        self.assertEqual(set(F.roles(ms).values()), {"reaction"})

    def test_published_order_decides_not_the_order_given(self):
        ms = [m(1, "model_release", "relay"), m(0, "model_release", "relay")]
        self.assertEqual(F.roles(ms), {"p0": "original", "p1": "retelling"})


class TheGroup(unittest.TestCase):
    def test_every_retelling_folds_under_the_earliest_original(self):
        ms = [m(0, "model_release", "other"), m(1, "model_release", "maker"), m(2, "model_release", "other"),
              m(3, "opinion_analysis", "other")]
        g = F.group(ms)
        self.assertEqual(g.head, "p1")
        self.assertEqual(g.folded, {"p0": "rule", "p2": "rule"})

    def test_with_no_original_the_earliest_retelling_is_the_head(self):
        ms = [m(0, "incident", "other"), m(1, "incident", "other"), m(2, "incident", "other")]
        g = F.group(ms)
        self.assertEqual((g.head, sorted(g.folded)), ("p0", ["p1", "p2"]))

    def test_one_original_and_no_retelling_has_a_head_and_nothing_folded(self):
        g = F.group([m(0, "model_release", "maker"), m(1, "opinion_analysis", "other")])
        self.assertEqual((g.head, g.folded), ("p0", {}))
        self.assertEqual(F.group([m(0, "opinion_analysis", "other")]).head, None)

    def test_a_member_not_read_yet_never_folds_nor_counts(self):
        ms = [m(0, "model_release", "maker"), m(1, None, None), m(2, "model_release", "other")]
        g = F.group(ms)
        self.assertEqual((g.head, g.folded), ("p0", {"p2": "rule"}))
        self.assertEqual(g.rule["p1"], None)

    def test_the_owners_answer_beats_the_rule_and_undo_returns_it(self):
        ms = [m(0, "model_release", "maker"), m(1, "model_release", "other"), m(2, "opinion_analysis", "other")]
        g = F.group(ms, {"p1": "not_same", "p2": "same"})
        self.assertEqual(g.folded, {"p2": "owner"})
        self.assertEqual(g.state("p1"), "shown")
        self.assertEqual(g.state("p0"), "head")
        self.assertEqual(F.group(ms, {"p0": "not_same"}).head, "p0")      # the head is never answered away
        self.assertEqual(F.group(ms, {"p1": "same"}).folded, {"p1": "rule"})
        # no head: an answer "same" has nothing to fold under
        self.assertEqual(F.group([m(0, "opinion_analysis", "other"), m(1, "opinion_analysis", "other")],
                                 {"p1": "same"}).folded, {})


class TheKind(unittest.TestCase):
    def test_the_guide_is_the_frozen_lab_guide_as_the_spec_records_it(self):
        body = schemas.guide_body("read-v3")
        self.assertEqual(hashlib.md5(body.encode()).hexdigest(), "56c6326c656428ed4b839e3b9bbf6c39")
        self.assertIn("**Consistency rule (enforced):** `main` is null if and only if `events` is `none`.", body)
        self.assertNotIn("confirms_earlier", body.split("\n", 1)[1])
        self.assertEqual(schemas.KINDS["read3"].guide, "read-v3")
        self.assertEqual(schemas.KINDS["read3"].subject, "post")
        self.assertEqual(schemas.guide_ids()["read-v3"], "read3")

    def test_an_answer_needs_its_type_and_origin_and_reads_checks(self):
        self.assertEqual(validate.check("read3", read3(), "x")[1], None)
        self.assertEqual(validate.check("read3", {"reading": read3()}, "x")[1], None)        # unwrapped as read's
        self.assertTrue(validate.check("read3", {k: v for k, v in read3().items() if k != "origin"}, "x")[1]
                        .startswith("answer: origin missing"))
        self.assertTrue(validate.check("read3", read3(event_type="launch"), "x")[1].startswith("answer.event_type:"))
        self.assertEqual(validate.check("read3", read3(events="several", main=None), "x")[1],
                         "main is null but events is several")

    def test_the_input_is_reads_plus_address_repost_and_published(self):
        p = tasks.Post(id="x", kind="telegram", source="Example Channel", source_id="s", at=T0, title="Widget 4.1 is out",
                       text="Acme released Widget 4.1.", links=[("https://acme.example/w41", "post")])
        text = F.read3_input(p, url="https://t.example/c/1", repost={"author": "acme", "by": []})
        lines = text.split("\n")
        self.assertEqual(lines[0], "Platform: telegram | Source: Example Channel")
        self.assertEqual(lines[1:4], ["Address: https://t.example/c/1",
                                      "Repost: written by @acme, reposted by Example Channel",
                                      "Published: 2100-03-01T12:00"])
        self.assertEqual("\n".join([lines[0]] + lines[4:]), tasks.read_input(p))
        self.assertNotIn("Repost:", F.read3_input(p, url=None, repost=None))


class Stored(_Api):
    """The kind on the database: planner, answers, the fold of a story, the News page, the routes."""

    def setUp(self):
        super().setUp()
        self.run = repo.start_run(self.cur, code_version="test", config={})

    def story(self, *posts, at=None):
        sid = repo.add_story(self.cur, first_at=at or datetime.now(timezone.utc), run_id=self.run)
        for p in posts:
            repo.open_membership(self.cur, story_id=sid, post_id=p, role="member", reason="test", run_id=self.run)
        return str(sid)

    def read(self, post, answer):
        with self.conn.transaction():
            task_id, _ = F.read3_task(self.cur, post)
        _, got = self.answer((task_id, answer))
        self.assertEqual(got["valid"], 1, got)
        return task_id

    def test_the_planner_asks_members_of_stories_of_two_or_more_once(self):
        now = datetime.now(timezone.utc)
        a, b, c = self.post(at=now - H), self.post(at=now - 2 * H), self.post(at=now - 3 * H)
        alone, old = self.post(at=now - H), self.post(at=now - timedelta(days=90))
        loose = self.post(at=now - H)
        self.story(a, b)
        self.story(b, c)                                # b in two stories: asked once
        self.story(alone)
        self.story(old, self.post(at=now - timedelta(days=91)))
        with self.conn.transaction():
            self.assertEqual(F.plan(self.cur), 3)
            self.assertEqual(F.plan(self.cur), 0)
        self.cur.execute("SELECT a::text, guide, input FROM mx_tasks WHERE kind = 'read3' ORDER BY priority, a")
        rows = self.cur.fetchall()
        self.assertEqual({r[0] for r in rows}, {a, b, c})
        self.assertEqual({r[1] for r in rows}, {"read-v3"})
        self.assertTrue(all("\nAddress: https://test.invalid/mark-x/" in r[2] for r in rows))
        self.assertNotIn(loose, {r[0] for r in rows})
        with self.conn.transaction():
            self.assertEqual(F.plan(self.cur, days=None), 2)   # every post: the old story too
        self.assertIn("read3", tasks.WINDOWED)

    def test_an_answer_is_stored_as_a_read_v3_reading_beside_read_v2(self):
        p = self.post()
        with self.conn.transaction():
            t2, _ = tasks.read_task(self.cur, p)
        self.answer((t2, reading()))
        self.read(p, read3(origin="maker"))
        got = repo.readings(self.cur, [p], "read-v3")
        self.assertEqual(got[uuid.UUID(p)]["reading"]["origin"], "maker")
        self.assertEqual(repo.readings(self.cur, [p], "read-v2")[uuid.UUID(p)]["reading"].get("origin"), None)

    def test_a_storys_fold_from_its_readings_and_the_news_page(self):
        now = datetime.now(timezone.utc)
        maker = self.post(title="Acme: Widget 4.1 is here", at=now - 5 * H, source=self.other)
        retell = self.post(title="Widget 4.1 вышла", at=now - 4 * H)
        relay = self.post(title="Widget 4.1 (link)", at=now - 3 * H)
        take = self.post(title="Why Widget 4.1 matters", at=now - 2 * H)
        unread = self.post(title="Widget 4.1 again", at=now - H)
        sid = self.story(maker, retell, relay, take, unread, at=now - 5 * H)
        self.read(maker, read3(origin="maker"))
        self.read(retell, read3())
        self.read(relay, read3(origin="relay"))
        self.read(take, read3(event_type="opinion_analysis"))
        g = F.story_folds(self.cur, [sid])[sid]
        self.assertEqual((g.head, g.folded), (maker, {retell: "rule", relay: "rule"}))
        # the News page: each line of the story says its fold
        repo.add_news_rows(self.cur, self.run, [{"id": maker, "first_at": now - 5 * H, "voices": 2, "reports": 2,
                                                  "shares": 0, "mentions": 0, "score": 9, "tag": "NEW",
                                                  "posts": [{"post_id": p, "role": "report", "story": sid}
                                                            for p in (maker, retell, relay, take, unread)]}])
        repo.finish_run(self.cur, self.run, counts={})
        page = news.page(self.cur, now=now)
        lines = {line["id"]: line["fold"] for line in page["items"][0]["posts"]}
        self.assertEqual(lines[maker]["state"], "head")
        self.assertEqual((lines[retell]["state"], lines[retell]["head"], lines[retell]["by"]), ("folded", maker, "rule"))
        self.assertEqual(lines[take]["state"], "shown")
        self.assertIsNone(lines[unread])                             # not read yet: no buttons
        self.assertEqual(page["folds"]["lab"]["f1"], 0.70)

    def test_the_owners_answers_apply_at_once_and_are_labels(self):
        now = datetime.now(timezone.utc)
        maker, retell, take = (self.post(at=now - 3 * H), self.post(at=now - 2 * H), self.post(at=now - H))
        sid = self.story(maker, retell, take)
        self.read(maker, read3(origin="maker"))
        self.read(retell, read3())
        self.read(take, read3(event_type="opinion_analysis"))
        status, got = call("POST", "/api/markx/folds/answer", body={"story": sid, "post": retell, "answer": "not_same"})
        self.assertEqual(status, 200, got)
        self.assertEqual((got["state"], got["answer"]), ("shown", "not_same"))
        status, got = call("POST", "/api/markx/folds/answer", body={"story": sid, "post": take, "answer": "same"})
        self.assertEqual((got["state"], got["head"]), ("folded", maker))
        g = F.story_folds(self.cur, [sid])[sid]
        self.assertEqual(g.folded, {take: "owner"})
        status, got = call("GET", f"/api/markx/stories/{sid}/folds")
        self.assertEqual(status, 200, got)
        self.assertEqual({p["id"]: p["state"] for p in got["posts"]}, {maker: "head", retell: "shown", take: "folded"})
        score = call("GET", "/api/markx/folds/score")[1]
        self.assertEqual((score["folded"]["n"], score["folded"]["right"], score["missed"]), (1, 0, 1))
        status, got = call("POST", "/api/markx/folds/answer", body={"story": sid, "post": retell, "answer": "undo"})
        self.assertEqual((got["state"], got["answer"]), ("folded", None))
        self.cur.execute("SELECT answer, labeller, split, note FROM mx_labels WHERE item_kind = 'fold' AND b = %s "
                         "ORDER BY created_at, ctid", (retell,))
        rows = self.cur.fetchall()
        self.assertEqual([r[0] for r in rows], ["not_same", "undo"])          # keep everything: both rows
        self.assertEqual((rows[0][1], rows[0][2]), ("owner", "test"))
        self.assertEqual(json.loads(rows[0][3]), {"rule": "folded", "head": maker})
        self.assertEqual(call("GET", "/api/markx/folds/score")[1]["folded"]["n"], 0)   # undone: no longer counted
        # refusals
        self.assertEqual(call("POST", "/api/markx/folds/answer", body={"story": sid, "post": retell, "answer": "maybe"})[0], 400)
        self.assertEqual(call("POST", "/api/markx/folds/answer",
                              body={"story": str(uuid.uuid4()), "post": retell, "answer": "same"})[0], 404)
        self.assertEqual(call("POST", "/api/markx/folds/answer", body={"story": sid, "post": maker, "answer": "not_same"})[0], 400)

    def test_mx_labels_takes_fold_and_still_its_other_kinds(self):
        for kind in ("fold", "join", "news_row", "entity"):
            repo.add_label(self.cur, item_kind=kind, a=None, b=None, answer="x")
        q = "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'mx_labels_item_kind_check'"
        self.cur.execute(q)
        before = self.cur.fetchone()[0]
        self.assertIn("'fold'", before)
        self.assertIn("'connection'", before)
        from pathlib import Path
        sql = (Path(__file__).resolve().parents[1] / "db" / "migrations" / "0075_markx_folds.sql").read_text()
        self.cur.execute(sql)                                         # idempotent: the same constraint again
        self.cur.execute(q)
        self.assertEqual(self.cur.fetchone()[0], before)
        self.assertEqual(before.count("'fold'"), 1)

    def test_mark_ix_tables_are_untouched(self):
        from insight_core.tests.test_markx_decide import checksums
        now = datetime.now(timezone.utc)
        a, b = self.post(at=now - 2 * H), self.post(at=now - H)
        sid = self.story(a, b)
        before = checksums(self.cur)
        with self.conn.transaction():
            F.plan(self.cur)
        self.read(a, read3(origin="maker"))
        self.read(b, read3())
        F.story_folds(self.cur, [sid])
        call("POST", "/api/markx/folds/answer", body={"story": sid, "post": b, "answer": "not_same"})
        self.assertEqual(checksums(self.cur), before)


if __name__ == "__main__":
    unittest.main()
