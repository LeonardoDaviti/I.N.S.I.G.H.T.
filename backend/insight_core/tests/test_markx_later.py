"""0163 (Stealth v10.13.11): later developments, in Shadow. Long-lived stories (their subject's type), the follow-up
trigger (E' by entity and by a later version of its family, L' by the story's pages and the subject's addresses in
their paper forms; V alone never; one source enough; no age limit; members, saved posts and a story source's repost
of a member out), the owner's "Stop following", the incremental clock and its per-run cap, the back judge planned
under back's cap and its verdicts stored, the API the story and entity pages read, a long-lived story's second wave
after 30 days, and Mark IX only read. Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import json
import unittest
import uuid

from insight_core.markx import back, later, repo, schemas, tasks
from insight_core.tests._db import insert_scratch_source
from insight_core.tests.test_markx_api import call
from insight_core.tests.test_markx_back import DAY, NOW, _Back, ans
from insight_core.tests.test_markx_graph import unit

PAPER = "https://arxiv.org/abs/2611.04321"


class Versions(unittest.TestCase):
    def test_later_or_same(self):
        self.assertTrue(later.later_or_same((4, 1), (4,)))
        self.assertTrue(later.later_or_same((4,), (4,)))
        self.assertTrue(later.later_or_same((5,), (4, 9)))
        self.assertFalse(later.later_or_same((4,), (4, 1)))
        self.assertFalse(later.later_or_same((3, 9), (4,)))
        self.assertFalse(later.later_or_same(("mini",), ("pro",)))
        self.assertFalse(later.later_or_same(None, (4,)))

    def test_a_papers_forms_are_one_page(self):
        keys = {later.page_key(u) for u in (PAPER, "https://arxiv.org/pdf/2611.04321v2", "https://arxiv.org/html/2611.04321v1",
                                             "https://www.arxiv.org/abs/2611.04321v3")}
        self.assertEqual(len(keys), 1, keys)
        self.assertTrue(keys.pop().startswith("paper "))
        self.assertEqual(later.page_key("https://www.example.com/a/B/"), "example.com/a/b")
        self.assertIsNone(later.page_key("https://example.com/"))

    def test_the_news_flag_is_off_and_the_types(self):
        self.assertEqual(set(later.LONG_TYPES) & {"event", "product", "org", "person", "place", "law"}, set())
        self.assertTrue({"paper", "document", "model", "software", "dataset"} <= set(later.LONG_TYPES))


class _Later(_Back):
    def setUp(self):
        super().setUp()
        self.saved = insert_scratch_source(self.cur, platform="saved", settings_json=json.dumps({"display_name": "Saved"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (self.saved,))

    def ent(self, name, type="model", family=None, version=None):
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, family_key, version_key, status)
                            VALUES (%s, %s, %s, 'thing', %s, %s::jsonb, 'confirmed') RETURNING id::text""",
                         (type, name, tasks.name_key(name), family, json.dumps(list(version)) if version else None))
        return self.cur.fetchone()[0]

    def subject(self, post, name="Widget 4.1", type="model", entity=None):
        super().subject(post, name, type)
        if entity:
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (entity, post))

    def long(self, *, first=40, last=30, name="Widget 4.1", type="model", entity=None, links=()):
        a = self.post(source=self.source, at=self.at(first), links=links)
        b = self.post(source=self.other, at=self.at(last), links=links)
        for p in (a, b):
            if name:
                self.subject(p, name, type, entity)
        return self.story(a, b), (a, b)

    def later_post(self, days, source=None, name=None, type="model", entity=None, links=()):
        p = self.post(source=source or self.third, at=self.at(days), links=links)
        if name:
            self.subject(p, name, type, entity)
        return p

    def find(self, since_days=60, now=None, limit=later.PER_RUN):
        got, _ = later.find(self.cur, now=now or NOW, since=NOW - since_days * DAY, limit=limit)
        return got

    def pairs(self, **kw):
        return {(c["story"], c["post"]): c["trig"] for c in self.find(**kw)}

    def lstage(self, now=None, cap=50, limit=later.PER_RUN):
        with self.conn.transaction():
            return later.stage(self.cur, now=now or NOW, open_cap=cap, limit=limit)


class LongLived(_Later):
    def test_only_a_paper_document_model_software_or_dataset_subject_keeps_listening(self):
        kept = {t: self.long(name=f"Thing {t}", type=t)[0] for t in ("model", "software", "dataset", "document")}
        dropped = {t: self.long(name=f"Thing {t}", type=t)[0] for t in ("event", "product", "org")}
        got = later.long_lived(self.cur)
        self.assertEqual(set(got) & set(kept.values()), set(kept.values()))
        self.assertEqual(set(got) & set(dropped.values()), set())
        for t, sid in dropped.items():   # their follow-ups find nothing: today's once-only back
            self.later_post(1, name=f"Thing {t}", type=t)
        self.assertEqual({s for s, _ in self.pairs()} & set(dropped.values()), set())

    def test_a_subject_of_one_post_of_two_read_is_no_subject(self):
        a, b = self.post(source=self.source, at=self.at(40)), self.post(source=self.other, at=self.at(30))
        self.subject(a, "Widget 4.1")
        self.subject(b, "Something Else", type="org")
        self.story(a, b)
        self.assertEqual(later.long_lived(self.cur), {})


class TheTrigger(_Later):
    def test_e_one_source_its_subject_by_entity_id_at_any_age(self):
        e = self.ent("Widget 4.1")
        sid, _ = self.long(first=400, last=390, entity=e)
        alias = self.later_post(1, name="WGT-4.1", entity=e)               # another name, merged into one entity
        self.assertEqual(self.pairs(since_days=2), {(sid, alias): ["E"]})

    def test_e_through_a_merge(self):
        e, other = self.ent("Widget 4.1"), self.ent("Widget four point one")
        self.cur.execute("INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic) VALUES (%s, %s, 'owner', false)", (other, e))
        sid, _ = self.long(entity=e)
        p = self.later_post(1, name="Widget four point one", entity=other)
        self.assertEqual(self.pairs(), {(sid, p): ["E"]})

    def test_e_a_later_version_of_its_family_not_an_earlier_one(self):
        four = self.ent("Widget 4", family="widget", version=(4,))
        sid, _ = self.long(name="Widget 4", entity=four)
        newer = self.later_post(2, name="Widget 4.1", entity=self.ent("Widget 4.1", family="widget", version=(4, 1)))
        five = self.later_post(1.5, name="Widget 5", entity=self.ent("Widget 5", family="widget", version=(5,)))
        self.later_post(1, name="Widget 3", entity=self.ent("Widget 3", family="widget", version=(3,)))
        self.later_post(1, name="Gadget 9", entity=self.ent("Gadget 9", family="gadget", version=(9,)))
        self.assertEqual(self.pairs(), {(sid, newer): ["E"], (sid, five): ["E"]})

    def test_a_mere_mention_is_not_its_subject(self):
        e = self.ent("Widget 4.1")
        self.long(entity=e)
        p = self.post(source=self.third, at=self.at(1))
        with self.conn.transaction():
            tid, _ = tasks.entities_task(self.cur, p)
            call_id = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="m", valid=True, answer={})
            repo.add_mentions(self.cur, post_id=p, guide=schemas.KINDS["entities"].guide, call_id=call_id,
                              mentions=[{"span": "Widget 4.1", "name": "Widget 4.1", "name_key": tasks.name_key("Widget 4.1"),
                                         "type": "model", "role": "mentioned"}])
        self.assertEqual(self.pairs(), {})

    def test_l_the_subjects_address_in_its_other_forms(self):
        e = self.ent("A Study of Widgets", type="document")
        self.cur.execute("""INSERT INTO mx_entity_addresses (entity_id, url, kind, rule) VALUES (%s, %s, 'paper', 'identifier')""",
                         (e, PAPER))
        sid, _ = self.long(name="A Study of Widgets", type="document", entity=e)
        pdf = self.later_post(2, links=[("https://arxiv.org/pdf/2611.04321v2", "pdf")])
        html = self.later_post(1, source=self.fourth, links=[("https://arxiv.org/html/2611.04321v1", "html")])
        self.later_post(1, links=[("https://arxiv.org/abs/2611.09999", "another paper")])
        self.assertEqual(self.pairs(), {(sid, pdf): ["L"], (sid, html): ["L"]})

    def test_l_a_page_two_members_link_but_not_a_hub(self):
        page = "https://example.com/papers/widget-report"
        sid, _ = self.long(links=[(page, "the report")])
        p = self.later_post(1, links=[(page + "/", "report")])
        self.assertEqual(self.pairs(), {(sid, p): ["L"]})
        hub = "https://example.com/docs/guide"
        sid2, _ = self.long(name="Widget 7", links=[(hub, "guide")])
        for w in range(6):
            self.post(source=self.fourth, at=self.at(60 + 7 * w), links=[(hub, "guide")])
        q = self.later_post(1, links=[(hub, "guide")])
        self.assertNotIn((sid2, q), self.pairs(since_days=2))

    def test_v_alone_never(self):
        base = unit(1)
        sid, (a, b) = self.long()
        for x in (a, b):
            self.vector(x, unit(2, 0.01, base))
        near = self.later_post(1)
        self.vector(near, unit(3, 0.01, base))
        self.assertEqual(self.pairs(), {})

    def test_members_saved_posts_older_posts_and_a_story_sources_repost_are_out(self):
        e = self.ent("Widget 4.1")
        sid, (a, b) = self.long(entity=e)
        self.later_post(1, source=self.saved, name="Widget 4.1", entity=e)        # saved
        self.later_post(35, name="Widget 4.1", entity=e)                          # before the story's last post
        self.cur.execute("SELECT url FROM posts WHERE id = %s", (a,))
        member_url = self.cur.fetchone()[0]
        self.later_post(1, source=self.other, name="Widget 4.1", entity=e, links=[(member_url, "again")])   # a repost
        kept = self.later_post(1, source=self.other, name="Widget 4.1", entity=e)  # its own source, new words: kept
        self.assertEqual(self.pairs(), {(sid, kept): ["E"]})

    def test_e_and_l_together(self):
        page = "https://example.com/papers/widget-report"
        sid, _ = self.long(links=[(page, "r")])
        p = self.later_post(1, name="Widget 4.1", links=[(page, "r")])
        self.assertEqual(self.pairs(), {(sid, p): ["E", "L"]})


class TheStage(_Later):
    def test_stop_following_and_follow_again(self):
        sid, _ = self.long()
        p = self.later_post(1, name="Widget 4.1")
        status, got = call("POST", "/api/markx/later/follow", body={"story": sid, "following": False})
        self.assertEqual((status, got), (200, {"story": sid, "following": False}))
        self.assertEqual(self.pairs(), {})
        _, page = call("GET", "/api/markx/later", query={"story": sid})
        self.assertEqual(page["stories"][0]["following"], False)
        call("POST", "/api/markx/later/follow", body={"story": sid, "following": True})
        self.assertEqual(self.pairs(), {(sid, p): ["E"]})
        self.cur.execute("SELECT count(*) FROM mx_later_stops WHERE story = %s", (sid,))
        self.assertEqual(self.cur.fetchone()[0], 2)   # both kept
        self.assertEqual(call("POST", "/api/markx/later/follow", body={"story": str(uuid.uuid4()), "following": False})[0], 404)

    def test_incremental_with_a_per_run_cap_and_rows_once(self):
        sid, _ = self.long(first=60, last=45)
        ps = [self.later_post(3 - k * 0.5, name="Widget 4.1") for k in range(5)]
        first = self.lstage(limit=2)
        self.assertEqual((first["found"], first["added"]), (2, 2))
        self.assertEqual(first["clock"], {"at": self.at(2.5).isoformat(), "after": ps[1]})   # capped: read on from here
        self.assertEqual(self.lstage(limit=2)["added"], 2)
        third = self.lstage(limit=2)
        self.assertEqual((third["added"], third["clock"]), (1, {"at": NOW.isoformat(), "after": None}))
        self.assertEqual(self.lstage(limit=2)["added"], 0)                            # read again: rows once
        self.cur.execute("SELECT post::text FROM mx_later WHERE story = %s ORDER BY post_at", (sid,))
        self.assertEqual([r[0] for r in self.cur.fetchall()], ps)

    def test_a_capped_run_never_stalls_on_one_date(self):
        self.long(first=60, last=45)
        same = [self.later_post(2, name="Widget 4.1") for _ in range(5)]
        for _ in range(3):
            self.lstage(limit=2)
        self.cur.execute("SELECT count(*) FROM mx_later")
        self.assertEqual(self.cur.fetchone()[0], len(same))

    def test_the_first_run_reads_its_backfill_only(self):
        self.long(first=400, last=390)
        self.later_post(later.FIRST_SCAN_DAYS + 5, name="Widget 4.1")   # older than the first run's backfill
        recent = self.later_post(1, name="Widget 4.1")
        self.assertEqual(self.lstage()["added"], 1)
        self.cur.execute("SELECT post::text FROM mx_later")
        self.assertEqual([r[0] for r in self.cur.fetchall()], [recent])

    def test_planned_under_backs_cap_asked_three_times_settled_and_shown(self):
        e = self.ent("Widget 4.1")
        sid, members = self.long(entity=e)
        p = self.later_post(1, name="Widget 4.1", entity=e)
        self.assertEqual(self.lstage(cap=0)["planned"], 0)                        # the cap: none while 0 may wait
        self.assertEqual(self.lstage(cap=1)["planned"], 1)
        self.cur.execute("SELECT t.kind, t.a::text, t.input FROM mx_later l JOIN mx_tasks t ON t.id = l.task_id")
        kind, a, text = self.cur.fetchone()
        self.assertEqual((kind, a, back.numbered(text)), ("back", sid, 1))
        self.assertTrue(text.startswith("OLD STORY:\n- ["))
        for verdicts in (("development",), ("development",), ("retold",)):
            _, body = self.lease("back")
            self.answer((body["tasks"][0]["id"], ans(*verdicts)))
        _, page = call("GET", "/api/markx/later", query={"story": sid})
        row, = page["items"]                                                      # the live verdict, before settling
        self.assertEqual((row["verdict"], row["post"], row["days_after"], row["trig"]), ("development", p, 29, ["E"]))
        self.assertEqual(self.lstage()["settled"], 1)
        self.cur.execute("SELECT verdict, runs FROM mx_later")
        self.assertEqual(self.cur.fetchone(), ("development", ["development", "development", "retold"]))
        self.assertEqual(page["stories"], [{"story": sid, "headline": "Acme released Widget 4.1", "long_lived": True,
                                            "following": True, "subjects": [{"id": e, "name": "Widget 4.1"}]}])
        self.assertFalse(page["news"])
        status, ent = call("GET", f"/api/markx/entities/{e}/later")
        self.assertEqual((status, [r["id"] for r in ent["items"]], ent["counts"]), (200, [row["id"]], {"candidates": 1, "development": 1}))
        status, got = call("POST", "/api/markx/labels/later", body={"row": row["id"], "answer": "retold"})
        self.assertEqual((status, got["label"], got["precision"]), (200, "retold", {"labelled": 1, "development": 0, "precision": 0.0}))
        _, page = call("GET", "/api/markx/later", query={"story": sid})
        self.assertEqual(page["items"][0]["label"], "retold")
        self.assertEqual(call("POST", "/api/markx/labels/later", body={"row": row["id"], "answer": "maybe"})[0], 400)
        self.assertEqual(call("POST", "/api/markx/labels/later", body={"row": str(uuid.uuid4()), "answer": "retold"})[0], 404)

    def test_a_mark_x_story_page_reads_its_members_mark_ix_stories(self):
        sid, (a, b) = self.long()
        self.later_post(1, name="Widget 4.1")
        self.lstage()
        self.cur.execute("INSERT INTO mx_stories (first_at) VALUES (%s) RETURNING id::text", (self.at(40),))
        mx = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO mx_story_posts (story_id, post_id, role, reason) VALUES (%s, %s, 'member', 'test')", (mx, a))
        _, page = call("GET", "/api/markx/later", query={"story": mx})
        self.assertEqual(([s["story"] for s in page["stories"]], len(page["items"])), ([sid], 1))

    def test_a_second_wave_for_a_long_lived_story_after_30_days_only(self):
        lived, _ = self.long(first=120, last=110)
        once, _ = self.long(first=120, last=110, name="Big Summit", type="event")

        def wave(days, name):
            for s in (self.third, self.fourth):
                self.later_post(days, source=s, name=name, type="model" if name.startswith("Widget") else "event")

        for name in ("Widget 4.1", "Big Summit"):
            wave(80, name)
        with self.conn.transaction():
            back.stage(self.cur, now=self.at(78))
        for name in ("Widget 4.1", "Big Summit"):
            wave(60, name)                                    # 20 days after: neither fires
        with self.conn.transaction():
            back.stage(self.cur, now=self.at(58))
        for name in ("Widget 4.1", "Big Summit"):
            wave(20, name)                                    # 60 days after: the long-lived story fires again
        with self.conn.transaction():
            back.stage(self.cur, now=self.at(18))
        self.cur.execute("SELECT story::text, count(*) FROM mx_back GROUP BY story")
        self.assertEqual(dict(self.cur.fetchall()), {lived: 2, once: 1})
        call("POST", "/api/markx/later/follow", body={"story": lived, "following": False})
        wave(1, "Widget 4.1")                                 # stopped: no third wave
        with self.conn.transaction():
            back.stage(self.cur, now=NOW)
        self.cur.execute("SELECT count(*) FROM mx_back WHERE story = %s", (lived,))
        self.assertEqual(self.cur.fetchone()[0], 2)

    def test_mark_ix_is_only_read(self):
        self.long()
        self.later_post(1, name="Widget 4.1")
        ix = "SELECT (SELECT md5(string_agg(t::text, ',' ORDER BY t::text)) FROM story_posts t), " \
             "(SELECT md5(string_agg(t::text, ',' ORDER BY t::text)) FROM stories t), " \
             "(SELECT md5(string_agg(t::text, ',' ORDER BY t::text)) FROM posts t)"
        self.cur.execute(ix)
        before = self.cur.fetchone()
        self.assertEqual(self.lstage()["added"], 1)
        call("POST", "/api/markx/later/follow", body={"story": self.stories[0], "following": False})
        self.cur.execute(ix)
        self.assertEqual(self.cur.fetchone(), before)


if __name__ == "__main__":
    unittest.main()
