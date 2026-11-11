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


class Rules(unittest.TestCase):
    def ent(self, type="model", level="thing", version=None, variant=None, build=None, status="confirmed"):
        return later._Ent("e", type, status, "X", "x", level, version, variant, build)

    def test_specific_only(self):
        for t in ("paper", "document", "dataset"):
            self.assertTrue(later.specific(self.ent(t)), t)                       # by their type, always
        self.assertTrue(later.specific(self.ent("model", "version", "5")))
        self.assertTrue(later.specific(self.ent("model", "variant", "6", "Mini")))
        self.assertTrue(later.specific(self.ent("model", "checkpoint", "3.8")))
        self.assertTrue(later.specific(self.ent("model", "thing", "4.1")))       # a thing with a version
        self.assertTrue(later.specific(self.ent("software", "thing", build="2611")))
        self.assertFalse(later.specific(self.ent("model", "thing")))             # "<Assistant> AI": no version
        self.assertFalse(later.specific(self.ent("software", "thing")))          # a programming language
        self.assertFalse(later.specific(self.ent("model", "family", "5")))       # a family, even with a number
        self.assertFalse(later.specific(self.ent("product", "thing", "2")))      # a product: never
        for t in ("org", "person", "event", "place"):
            self.assertFalse(later.specific(self.ent(t, "thing", "1")), t)
        self.assertFalse(later.specific(self.ent("paper", status="not_entity")))
        self.assertFalse(later.specific(None))

    def test_quiet(self):
        t = NOW
        named = sorted([(t - 20 * DAY, "p0", "s0"), (t - 10 * DAY, "p1", "s1"), (t - 9 * DAY, "p2", "s1"),
                        (t - 3 * DAY, "p3", "s2"), (t, "me", "s9")])
        self.assertTrue(later.quiet(named, t, "me", set()))                      # 2 sources in 14 days (s0 is older)
        more = sorted(named + [(t - 1 * DAY, "p4", "s3")])
        self.assertFalse(later.quiet(more, t, "me", set()))                      # 3 sources
        self.assertTrue(later.quiet(more, t, "me", {"p4"}))                      # a story member is not counted

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
        self.assertEqual(later.RULE, 2)


class _Later(_Back):
    def setUp(self):
        super().setUp()
        self.saved = insert_scratch_source(self.cur, platform="saved", settings_json=json.dumps({"display_name": "Saved"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (self.saved,))

    def ent(self, name, type="model", family=None, version=None, level="thing", variant=None, key=None):
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, family_key, version, version_key, variant, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'confirmed') RETURNING id::text""",
                         (type, name, key or tasks.name_key(name), level, family,
                          ".".join(map(str, version)) if version else None, json.dumps(list(version)) if version else None,
                          variant))
        return self.cur.fetchone()[0]

    def release(self, name="Widget 4.1", type="model"):
        """A specific release: its version the name's last word."""
        return self.ent(name, type, version=tuple(int(x) if x.isdigit() else x for x in name.rsplit(" ", 1)[-1].split(".")))

    def subject(self, post, name="Widget 4.1", type="model", entity=None):
        super().subject(post, name, type)
        if entity:
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (entity, post))

    def subjects(self, post, *named):
        """A post whose one answer names several subjects: (name, type, entity or None) each."""
        with self.conn.transaction():
            tid, _ = tasks.entities_task(self.cur, post)
            call_id = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="m", valid=True, answer={})
            repo.add_mentions(self.cur, post_id=post, guide=schemas.KINDS["entities"].guide, call_id=call_id,
                              mentions=[{"span": n, "name": n, "name_key": tasks.name_key(n), "type": t, "role": "subject"}
                                        for n, t, _e in named])
        for n, (_name, _t, e) in enumerate(named):
            if e:
                self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND n = %s", (e, post, n))

    def long(self, *, first=40, last=30, name="Widget 4.1", type="model", entity=None, links=()):
        """A story of two sources about `name`: by default a specific release of it (an entity of its own)."""
        if entity is None and name and type in later.LONG_TYPES:
            entity = self.release(name, type) if type in later.RELEASE_TYPES else self.ent(name, type)
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
        e = self.release("Widget 4.1")
        sid, _ = self.long(first=400, last=390, entity=e)
        alias = self.later_post(1, name="WGT-4.1", entity=e)               # another name, merged into one entity
        self.assertEqual(self.pairs(since_days=2), {(sid, alias): ["E"]})

    def test_e_through_a_merge(self):
        e, other = self.release("Widget 4.1"), self.ent("Widget four point one")
        self.cur.execute("INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic) VALUES (%s, %s, 'owner', false)", (other, e))
        sid, _ = self.long(entity=e)
        p = self.later_post(1, name="Widget four point one", entity=other)
        self.assertEqual(self.pairs(), {(sid, p): ["E"]})

    def test_a_later_version_is_its_own_story_not_a_development(self):
        five = self.ent("Widget 5", family="widget", version=(5,), level="version")
        self.long(name="Widget 5", entity=five)
        self.later_post(2, name="Widget 5.5", entity=self.ent("Widget 5.5", family="widget", version=(5, 5), level="version"))
        self.later_post(1.5, name="Widget 6", entity=self.ent("Widget 6", family="widget", version=(6,), level="version"))
        self.later_post(1, name="Widget 5.5")                                   # unlinked, its own name key
        self.assertEqual(self.pairs(), {})

    def test_a_mere_mention_is_not_its_subject(self):
        e = self.release("Widget 4.1")
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
        e = self.release("Widget 4.1")
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


class Tightened(_Later):
    """v10.13.12: what production showed (the five failure classes) never fires; the gold case still does."""

    def src(self, n):
        out = [insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": f"Example {k}"}))
               for k in range(n)]
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = ANY(%s::uuid[])", (out,))
        return out

    def test_gold_a_paper_story_then_quiet_then_a_lone_post_77_days_later(self):
        doc = self.ent("Programming in Weight Space", type="document")
        self.cur.execute("INSERT INTO mx_entity_addresses (entity_id, url, kind, rule) VALUES (%s, %s, 'paper', 'identifier')",
                         (doc, PAPER))
        srcs = [self.source, self.other] + self.src(3)
        members = []
        for k in range(15):                                       # 15 posts by 5 sources within 8 days (85-78 days back)
            p = self.post(source=srcs[k % 5], at=self.at(85 - k * 0.5), links=[(PAPER, "paper")] if k % 3 == 0 else ())
            self.subject(p, "Programming in Weight Space", "document", doc)
            members.append(p)
        sid = self.story(*members)
        linker = self.later_post(20, source=self.fourth, links=[("https://arxiv.org/pdf/2611.04321v2", "pdf")])
        lone = self.later_post(8, source=self.third, name="Programming in Weight Space", type="document",
                               entity=doc)                         # 77 days after its first post; quiet before it
        self.assertEqual(self.pairs(since_days=90), {(sid, linker): ["L"], (sid, lone): ["E"]})
        got = later.long_lived(self.cur)[sid]
        self.assertEqual((got.subject, got.share), (doc, 1.0))

    def test_1_a_story_whose_main_subject_is_something_else(self):
        model = self.release("Widget 4.1")
        bench = self.ent("Physics Bench", type="other")
        ms = []
        for k, s in enumerate([self.source, self.other] + self.src(2)):   # the benchmark on all four, the model on two
            p = self.post(source=s, at=self.at(40 - k))
            if k < 2:
                self.subjects(p, ("Physics Bench", "other", bench), ("Widget 4.1", "model", model))
            else:
                self.subjects(p, ("Physics Bench", "other", bench))
            ms.append(p)
        self.story(*ms)
        self.later_post(1, name="Widget 4.1", entity=model)
        self.assertEqual(later.long_lived(self.cur), {})
        self.assertEqual(self.pairs(), {})

    def test_1_a_subject_of_fewer_than_half_its_read_members(self):
        model = self.release("Widget 4.1")
        ms = []
        for k, s in enumerate([self.source, self.other] + self.src(3)):   # the model on 2 of 5 read members
            p = self.post(source=s, at=self.at(40 - k))
            if k < 2:
                self.subject(p, "Widget 4.1", "model", model)
            else:
                self.subject(p, f"Topic {k}", "other")
            ms.append(p)
        self.story(*ms)
        self.assertEqual(later.long_lived(self.cur), {})

    def test_2_one_story_per_post_and_subject(self):
        a, b = self.release("Widget 4.1"), self.release("Gadget 9")
        weak = []
        for k, s in enumerate([self.source, self.other] + self.src(2)):   # its subject on 3 of 4 read: share 0.75
            p = self.post(source=s, at=self.at(20 - k))
            if k < 3:
                self.subject(p, "Widget 4.1", "model", a)
            else:
                self.subject(p, "Something", "other")
            weak.append(p)
        weak = self.story(*weak)
        older, _ = self.long(first=60, last=50, entity=a)               # share 1.0, older
        recent, _ = self.long(first=30, last=25, entity=a)              # share 1.0, more recent: the best
        other, _ = self.long(first=30, last=25, name="Gadget 9", entity=b)
        vs = self.post(source=self.third, at=self.at(1))                # "<A> vs <B> 2026"
        self.subjects(vs, ("Widget 4.1", "model", a), ("Gadget 9", "model", b))
        got = self.find()
        self.assertEqual({(c["story"], c["entity"]) for c in got if c["post"] == vs}, {(recent, a), (other, b)})
        self.assertEqual({c["story"] for c in got} & {weak, older}, set())

    def test_3_generic_entities_never_keep_listening(self):
        cases = [self.ent("Helper AI", "model"),                        # an unversioned assistant name
                 self.ent("Widget", "model", level="family"),           # a family
                 self.ent("Snake Lang", "software"),                    # a programming language
                 self.ent("Helper App", "product", version=(2,))]       # a product
        for e in cases:
            self.cur.execute("SELECT name, type FROM mx_entities WHERE id = %s", (e,))
            name, t = self.cur.fetchone()
            self.long(first=1400, last=1316, name=name, type=t, entity=e)
            self.later_post(1, name=name, type=t, entity=e)              # 1,316 days later
        self.assertEqual(later.long_lived(self.cur), {})
        self.assertEqual(self.pairs(since_days=2), {})

    def test_4_a_popular_subject_is_never_quiet(self):
        e = self.release("Widget 4.1")
        sid, _ = self.long(first=60, last=50, entity=e)
        chatter = self.src(5)
        posts = [self.later_post(30 - k * 1.2, source=chatter[k % 5], name="Widget 4.1", entity=e) for k in range(20)]
        got = {p for (_s, p) in self.pairs(since_days=40)}
        self.assertEqual(got, set(posts[:3]))                            # only the first, before the chatter grew
        lone = self.later_post(0.5, source=self.third, name="Widget 4.1", entity=e)
        self.assertNotIn((sid, lone), self.pairs(since_days=1))

    def test_4_quiet_does_not_count_the_storys_own_members(self):
        e = self.release("Widget 4.1")
        ms = []
        for k, s in enumerate([self.source, self.other] + self.src(3)):  # five sources in the story, 8-4 days back
            p = self.post(source=s, at=self.at(8 - k))
            self.subject(p, "Widget 4.1", "model", e)
            ms.append(p)
        sid = self.story(*ms)
        p = self.later_post(1, name="Widget 4.1", entity=e)
        self.assertEqual(self.pairs(since_days=2), {(sid, p): ["E"]})

    def test_l_under_one_story_a_subject_and_no_hub(self):
        page = "https://example.com/papers/widget-report"
        e = self.release("Widget 4.1")
        self.long(first=60, last=50, entity=e, links=[(page, "the report")])
        newer, _ = self.long(first=40, last=30, entity=e, links=[(page, "the report")])
        p = self.later_post(1, links=[(page, "report")])
        self.assertEqual(self.pairs(), {(newer, p): ["L"]})
        hub = "https://example.com/docs/guide"
        self.long(name="Gizmo 7", links=[(hub, "guide")])
        for w in range(6):
            self.post(source=self.fourth, at=self.at(60 + 7 * w), links=[(hub, "guide")])
        q = self.later_post(1, links=[(hub, "guide")])
        self.assertNotIn(q, {x for _s, x in self.pairs(since_days=2)})


class TheStage(_Later):
    def test_old_rule_rows_are_kept_but_not_planned_counted_or_shown(self):
        self.cur.execute("""SELECT column_default FROM information_schema.columns
                             WHERE table_name = 'mx_later' AND column_name = 'rule'""")
        self.assertEqual(self.cur.fetchone()[0], "1")                   # 0103: the rows already there are rule 1
        e = self.release("Widget 4.1")
        sid, members = self.long(entity=e)
        p = self.later_post(1, name="Widget 4.1", entity=e)
        again = self.later_post(2, name="Widget 4.1")             # its name, unlinked
        for post, days in ((p, 1), (again, 2)):                       # found by v10.13.11's loose rule
            self.cur.execute("""INSERT INTO mx_later (story, post, members, entity, trig, post_at, last_at)
                                VALUES (%s, %s, %s::uuid[], %s, '{E}', %s, %s) RETURNING id::text""",
                             (sid, post, list(members), e, self.at(days), self.at(30)))
        old_row = self.cur.fetchone()[0]
        self.assertEqual(call("POST", "/api/markx/labels/later", body={"row": old_row, "answer": "unrelated"})[0], 200)
        out = self.lstage()
        self.assertEqual((out["rule"], out["added"], out["planned"]), (2, 2, 2))   # its own rows; old ones not asked
        self.cur.execute("SELECT rule, count(*), count(task_id) FROM mx_later GROUP BY rule ORDER BY rule")
        self.assertEqual(self.cur.fetchall(), [(1, 2, 0), (2, 2, 2)])          # the old rows kept as they were
        _, page = call("GET", "/api/markx/later", query={"story": sid})
        self.assertEqual(({r["rule"] for r in page["items"]}, page["counts"]["candidates"], page["precision"]["labelled"]),
                         ({2}, 2, 0))
        _, every = call("GET", "/api/markx/later", query={"story": sid, "all": "1"})
        self.assertEqual((len(every["items"]), every["precision"]["labelled"]), (4, 1))
        _, ent = call("GET", f"/api/markx/entities/{e}/later")
        self.assertEqual(len(ent["items"]), 2)
        _, ent = call("GET", f"/api/markx/entities/{e}/later", query={"all": "1"})
        self.assertEqual(len(ent["items"]), 4)

    def test_a_clock_of_the_old_rule_restarts_the_backfill(self):
        self.long(first=400, last=390)
        p = self.later_post(20, name="Widget 4.1")                       # read by the old rule's runs already
        with self.conn.transaction():
            repo.set_setting(self.cur, later.SINCE_KEY, {"at": (NOW - 2 * DAY).isoformat(), "after": None})
        first = self.lstage()
        self.assertEqual((first["since"], first["added"], first["clock"]["rule"]),
                         ((NOW - later.FIRST_SCAN_DAYS * DAY).isoformat(), 1, 2))
        self.cur.execute("SELECT post::text, rule FROM mx_later")
        self.assertEqual(self.cur.fetchall(), [(p, 2)])
        again = self.lstage()
        self.assertEqual((again["since"], again["added"]), ((NOW - later.MARGIN).isoformat(), 0))


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
        self.assertEqual(first["clock"], {"at": self.at(2.5).isoformat(), "after": ps[1], "rule": 2})   # capped: read on from here
        self.assertEqual(self.lstage(limit=2)["added"], 2)
        third = self.lstage(limit=2)
        self.assertEqual((third["added"], third["clock"]), (1, {"at": NOW.isoformat(), "after": None, "rule": 2}))
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
        e = self.release("Widget 4.1")
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
