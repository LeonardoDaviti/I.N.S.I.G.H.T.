"""A thing's timeline (issue 0165), with invented names (the components rule, A, was dropped in v10.18, 0203): a rename is
proposed by shared evidence and only the owner's answer merges it (B), the entity page's timeline (C) and the post
page's "before" from it (D); each with what it must not do (a version bump, an org's word, the owner's answers, no
evidence)."""
from __future__ import annotations

import json
import unittest
import uuid
from unittest import mock

from insight_core.markx import entity_answers, entity_views, identity as I, names as N, rename as RN
from insight_core.markx import repo, schemas, tasks, timeline as TL, validate
from insight_core.tests import test_markx_entities as base

T0, H, D = base.T0, base.H, base.D


def soft(**kw):
    return {"family": None, "version": None, "variant": None, "size": None, "build": None, **kw}


class Rules(unittest.TestCase):
    """No database: the address's compared form, the rename guards."""
    ent, book = base.Rules.ent, base.Rules.book

    def products(self):
        acme = self.ent("o", "Acme", "org")
        forge = self.ent("f", "Acme Forge", "software", maker="Acme", fields=soft())
        other = self.ent("x", "Orbis Forge", "software", maker="Orbis", fields=soft())
        return self.book(acme, forge, other)

    def test_an_address_compares_by_its_repository(self):
        self.assertEqual(RN.address("https://github.com/Acme/Snap/tree/main/docs"), "github.com/acme/snap")
        self.assertEqual(RN.address("https://www.github.com/acme/snap.git"), "github.com/acme/snap")
        self.assertEqual(RN.address("https://huggingface.co/datasets/acme/snapset/blob/x"), "huggingface.co/datasets/acme/snapset")
        self.assertEqual(RN.address("https://acme.example/products/snap/"), "acme.example/products/snap")
        self.assertIsNone(RN.address("https://github.com/acme"))         # an owner's page is no thing's address
        self.assertIsNone(RN.address("https://acme.example/"))           # nor a home page

    def test_the_older_name_is_found_in_a_text_never_inside_the_newer(self):
        key = RN.text_key_of("Start with Acme Snap. Formerly “Forge Snap”; v4.1!")
        self.assertEqual(key, "start with acme snap formerly forge snap v 4.1")
        self.assertEqual(RN.without("try acme snap now", {"acme snap"}), "try | now")
        self.assertFalse(RN.words_in(RN.without("try acme snap now", {"acme snap"}), "snap"))
        book = self.book(self.ent("s", "Acme Forge Snap", "software", maker="Acme", fields=soft()),
                         self.ent("t", "Snap", "software", maker="Acme", fields=soft()))
        self.assertEqual(RN.names_of(book, "s", {"acme"}), {"acme forge snap", "forge snap"})
        self.assertEqual(RN.names_of(book, "t", {"acme"}), set())   # one short word: never searched for

    def test_a_version_bump_or_a_part_is_never_a_rename(self):
        n4 = self.ent("a", "Nimbus 4", "model", maker="Acme")
        n5 = self.ent("b", "Nimbus 5", "model", maker="Acme")
        book = self.book(n4, n5)
        self.assertEqual(RN.guard(book, "a", "b"), "version")
        forge = self.ent("f", "Acme Forge", "software", maker="Acme", fields=soft())
        snap = self.ent("s", "Acme Forge Snap", "software", maker="Acme", fields=soft())
        snap.parent = "f"
        book = self.book(forge, snap)
        self.assertEqual(RN.guard(book, "s", "f"), "part")
        tool = self.ent("t", "Acme Snap", "software", maker="Acme", fields=soft())
        book = self.book(snap, tool)
        self.assertIsNone(RN.guard(book, "s", "t"))
        book.never.add(I.pair("s", "t"))
        self.assertEqual(RN.guard(book, "s", "t"), "owner_apart")

    def test_the_rename_kind_its_guide_and_schema(self):
        k = schemas.KINDS["rename"]
        self.assertEqual((k.guide, k.subject), ("rename-v1", "entity_entity"))
        self.assertTrue((schemas.GUIDES_DIR / "rename-v1.md").is_file())
        ok = {"evidence": "the post says it was renamed", "relation": "renamed", "confidence": 0.9}
        self.assertIsNone(validate.check("rename", ok, "OLD: x\nNEW: y")[1])
        self.assertIsNotNone(validate.check("rename", dict(ok, relation="same"), "OLD: x\nNEW: y")[1])


class _Db(base._Db):
    def post_at(self, src, at, title, text=None, url=None, links=()):
        pid = self.post(src, at, title=title, text=text, links=links)
        if url:
            self.cur.execute("UPDATE posts SET url = %s, normalized_url = %s WHERE id = %s", (url, url, pid))
        return pid

    def ent_named(self, name):
        self.cur.execute("SELECT id::text FROM mx_entities WHERE name = %s ORDER BY created_at LIMIT 1", (name,))
        row = self.cur.fetchone()
        return row[0] if row else None


@base.requires_test_db
class Renames(_Db):
    REPO = "https://github.com/acme/snap"

    def birth_and_launch(self, launch_text=None, gap_days=100):
        birth = self.post_at(0, T0 - gap_days * D, "Acme Forge Snap: fast starts", links=[self.REPO + "/tree/main"])
        self.mentions(birth, ("Acme Forge Snap", "software", "subject", "Acme", soft()))
        outside = self.post_at(3, T0 - 20 * D, "Warm workers with Acme Forge Snap")
        self.mentions(outside, ("Acme Forge Snap", "software", "mention", "Acme", soft()))
        self.stage()
        launch = self.post_at(0, T0, "Start in seconds with Acme Snap", text=launch_text)
        self.mentions(launch, ("Acme Snap", "software", "subject", "Acme", soft()))
        return birth, outside, launch

    def address(self, eid, post):
        self.cur.execute("INSERT INTO mx_entity_addresses (entity_id, url, kind, rule, post_id) VALUES (%s, %s, 'code', 'title', %s)",
                         (eid, self.REPO, post))

    def asked(self):
        self.cur.execute("SELECT a::text, b::text, input FROM mx_tasks WHERE kind = 'rename'")
        return self.cur.fetchall()

    def test_a_shared_address_asks_and_renamed_is_queued_never_merged(self):
        self.queued()

    def queued(self):
        """The birth post links the repository the launch's entity holds: asked, Haiku's `renamed` queued."""
        birth, outside, launch = self.birth_and_launch()
        self.stage(since=self.since)
        old, new = self.entity_of(birth), self.entity_of(launch)
        self.address(new, launch)
        out = self.stage(full=True)                                                   # every thing, its address now
        got = self.asked()
        self.assertEqual([(a, b) for a, b, _ in got], [(old, new)])
        self.assertIn("they share an own address (github.com/acme/snap)", got[0][2])
        self.assertIn('OLD: name "Acme Forge Snap"', got[0][2])
        self.assertEqual(out["renames"]["by_rule"], {"address": 1})
        self.answer_task("rename", {"evidence": "the same repository, renamed", "relation": "renamed", "confidence": 0.9})
        out = self.stage(since=self.since)
        self.assertEqual(out["renames"]["queued"], 1)
        self.cur.execute("SELECT kind, a::text, b::text, proposal, reason FROM mx_entity_queue")
        self.assertEqual(self.cur.fetchall(), [("rename", old, new, "same", "rename")])
        self.assertNotEqual(self.book().root(old), self.book().root(new))             # a question, never a merge
        self.stage(full=True)
        self.assertEqual(len(self.asked()), 1)                                        # asked once
        return old, new, birth, outside, launch

    def test_the_owners_same_renames_and_the_old_name_is_the_earlier_name(self):
        old, new, birth, outside, launch = self.queued()
        q = entity_views.queue(self.cur)["open"]
        self.assertEqual(q[0]["kind"], "rename")
        got = entity_answers.answer(self.cur, q[0]["id"], "same")
        self.assertTrue(got["renamed"])
        self.cur.execute("SELECT from_id::text, to_id::text, kind, by FROM mx_entity_redirects WHERE undone_at IS NULL")
        self.assertEqual(self.cur.fetchall(), [(old, new, "rename", "owner")])
        # the old name has more sources, but the name shown is the new one
        self.stage(full=True)
        page = entity_views.entity_page(self.cur, old, now=T0 + 2 * D)
        self.assertEqual(page["entity"]["name"], "Acme Snap")
        self.assertIn("Acme Forge Snap", page["aliases"])
        tl = page["timeline"]
        self.assertEqual(tl["earlier"][0]["name"], "Acme Forge Snap")
        kinds = [(i["kind"], (i["post"] or {}).get("id")) for i in tl["items"]]
        self.assertEqual(kinds[0], ("birth", birth))
        self.assertIn(("renamed", launch), kinds)
        self.assertIn(("earlier_name", outside), kinds)
        # undone like any merge
        rid = next(m["id"] for m in entity_views.queue(self.cur)["merges"] if m["kind"] == "rename")
        entity_answers.undo(self.cur, rid)
        self.assertNotEqual(self.book().root(old), self.book().root(new))

    def test_the_new_post_naming_the_old_one_formerly(self):
        birth, _, launch = self.birth_and_launch(
            launch_text="Acme Snap, formerly Forge Snap, is now open source. It restores GPU workers.")
        out = self.stage(since=self.since)
        self.assertEqual(out["renames"]["by_rule"], {"named": 1, "formerly": 1})
        self.assertEqual([(a, b) for a, b, _ in self.asked()], [(self.entity_of(birth), self.entity_of(launch))])

    def test_what_is_never_asked(self):
        # overlapping for more than a week: both live, not a rename
        birth, _, launch = self.birth_and_launch(launch_text="Acme Snap works with Acme Forge Snap.", gap_days=100)
        late = self.post_at(4, T0 + 30 * D, "Acme Forge Snap still runs")
        self.mentions(late, ("Acme Forge Snap", "software", "subject", "Acme", soft()))
        out = self.stage(since=self.since)
        self.assertEqual(out["renames"]["candidates"], 0)
        # no evidence: a newer thing of the maker that names nothing of the old one
        other = self.post_at(1, T0 + 40 * D, "Acme Kite is out")
        self.mentions(other, ("Acme Kite", "software", "subject", "Acme", soft()))
        out = self.stage(since=self.since)
        self.assertEqual(out["renames"]["candidates"], 0)
        # a version bump with one address
        n4 = self.post_at(0, T0 - 50 * D, "Acme Nimbus 4", links=[self.REPO])
        self.mentions(n4, ("Acme Nimbus 4", "model", "subject", "Acme", soft(family="Acme Nimbus", version="4")))
        n5 = self.post_at(0, T0 + 50 * D, "Acme Nimbus 5, after Acme Nimbus 4", links=[self.REPO])
        self.mentions(n5, ("Acme Nimbus 5", "model", "subject", "Acme", soft(family="Acme Nimbus", version="5")))
        out = self.stage(full=True)
        self.assertEqual(self.asked(), [])

    def test_haiku_or_the_owner_saying_different_keeps_them_apart_for_good(self):
        birth, _, launch = self.birth_and_launch(launch_text="Acme Snap replaces Acme Forge Snap.")
        self.stage(since=self.since)
        self.answer_task("rename", {"evidence": "a new product", "relation": "successor", "confidence": 0.8})
        out = self.stage(full=True)
        self.assertEqual((out["renames"]["queued"], out["renames"]["apart"]), (0, 1), out["renames"])
        self.assertEqual(len(self.asked()), 1)
        # the owner's `different` on a rename item
        old, new = self.entity_of(birth), self.entity_of(launch)
        I.queue_item(self.cur, kind="rename", a=old, b=new, proposal="same", reason="rename", conf=0.9, evidence={},
                     call_id=None, run_id=None)
        self.cur.execute("SELECT id::text FROM mx_entity_queue WHERE kind = 'rename'")
        entity_answers.answer(self.cur, self.cur.fetchone()[0], "different")
        self.cur.execute("SELECT count(*) FROM mx_entity_redirects")
        self.assertEqual(self.cur.fetchone()[0], 0)


@base.requires_test_db
class Timeline(_Db):
    def thing(self):
        """A maker's tool: its birth on the maker's site, an outside post linking back, two releases, outside posts."""
        maker = lambda path: f"https://dev.acme.example/{path}/{uuid.uuid4().hex[:6]}"
        birth = self.post_at(0, T0 - 200 * D, "Introducing Acme Kite", url=maker("blog"))
        self.mentions(birth, ("Acme Kite", "software", "subject", "Acme", soft()))
        linker = self.post_at(3, T0 - 150 * D, "Restoring workers, the next step")   # names it otherwise
        self.mentions(linker, ("Warmpool", "software", "subject"))
        self.cur.execute("""INSERT INTO mx_connections (a_kind, a, b_kind, b, relation, p, rule, evidence)
                            VALUES ('post', %s, 'post', %s, 'refers_back', 1, 'author_link_other', '{}'::jsonb)""",
                         (linker, birth))
        rel = self.post_at(1, T0 - 100 * D, "Acme Kite 1.0 is out", url=maker("news"))
        self.mentions(rel, ("Acme Kite", "software", "subject", "Acme", soft()))
        outs = []
        for k in range(3):
            o = self.post_at(2 + k % 2, T0 - (90 - 31 * k) * D, f"A look at Acme Kite ({k})")
            self.mentions(o, ("Acme Kite", "software", "mention", "Acme", soft()))
            outs.append(o)
        launch = self.post_at(0, T0, "Acme Kite is open source", url=maker("blog"))
        self.mentions(launch, ("Acme Kite", "software", "subject", "Acme", soft()))
        self.stage()
        return birth, linker, rel, outs, launch

    def test_the_entity_page_timeline(self):
        birth, linker, rel, outs, launch = self.thing()
        kite = self.entity_of(birth)
        tl = entity_views.entity_page(self.cur, kite, now=T0 + 2 * D)["timeline"]
        rows = [(i["kind"], (i["post"] or {}).get("id")) for i in tl["items"]]
        self.assertEqual(rows[0], ("birth", birth))
        self.assertEqual(tl["items"][0].get("also"), ["release"])                     # the birth is the maker's
        self.assertEqual(rows[1], ("first_outside", linker))                          # linking back counts
        self.assertIn(("release", rel), rows)
        self.assertIn(("release", launch), rows)
        months = [i for i in tl["items"] if i["kind"] == "outside"]
        self.assertEqual(sum(i["n"] for i in months), 3)
        self.assertEqual([i["at"] for i in tl["items"]], sorted(i["at"] for i in tl["items"]))
        self.assertEqual(tl["shown"], min(8, tl["total"]))

    def test_the_eight_most_important_are_shown_first(self):
        self.thing()
        evs = [TL._event("outside", T0 + k * D, None) for k in range(10)] + [TL._event("birth", T0 + 20 * D, None)]
        top = TL._top(evs)
        self.assertEqual(len(top), 8)
        self.assertIn(10, top)                                                        # the birth, though last

    def test_no_timeline_under_two_events(self):
        p = self.post_at(0, T0, "Acme Kite")
        self.mentions(p, ("Acme Kite", "software", "mention", "Acme", soft()))
        self.stage()
        self.assertIsNone(entity_views.entity_page(self.cur, self.entity_of(p), now=T0 + 2 * D)["timeline"])

    def test_the_post_pages_before(self):
        birth, linker, rel, outs, launch = self.thing()
        got = TL.before_post(self.cur, launch)
        self.assertEqual(got[0]["entity"]["name"], "Acme Kite")
        rows = [(i["kind"], i["post"]["id"]) for i in got[0]["items"]]
        self.assertEqual(rows, [("birth", birth), ("first_outside", linker), ("release", rel)])
        # an edge the Before list holds already is not repeated; nothing after the post
        got = TL.before_post(self.cur, rel, skip=[linker])
        self.assertEqual([(i["kind"], i["post"]["id"]) for i in got[0]["items"]], [("birth", birth)])
        self.assertEqual(TL.before_post(self.cur, birth), [])


class StopRules(unittest.TestCase):
    """No database: the stop candidate rule, the question, the answer, the analysis rule (0165's second case)."""

    def test_a_story_is_a_candidate_stop_by_its_share_or_its_first_post(self):
        from insight_core.markx import stops as ST
        at = [(T0 + k * H, f"p{k}") for k in range(8)]
        self.assertTrue(ST.candidate(ST.share(at, ["p0"])))                  # its first post is about the thing
        self.assertTrue(ST.candidate(ST.share(at, ["p3", "p5"])))            # a quarter of its members
        self.assertFalse(ST.candidate(ST.share(at, ["p5"])))                 # one of eight, not the first
        self.assertFalse(ST.candidate(ST.share([], [])))

    def test_the_question_and_its_answer(self):
        from insight_core.markx import stops as ST
        q = ST.question({"name": "Orbit 2 Small", "type": "model", "maker": "Vantor Labs"}, "Vantor opens Orbit 2 Small",
                        [ST.Line(T0 + H, "Engine Blog", "Day-0 support for Orbit 2 Small", "subject"),
                         ST.Line(T0, "Vantor Labs", "Orbit 2 Small weights are out", "subject"),
                         ST.Line(T0 + 2 * H, "Router", "Free on our router", None)])
        self.assertIn('THING: "Orbit 2 Small" (model, by Vantor Labs)', q)
        self.assertIn('STORY: "Vantor opens Orbit 2 Small" (', q)
        lines = q.splitlines()[2:]
        self.assertTrue(lines[0].endswith("subject: Orbit 2 Small weights are out"))   # oldest first
        self.assertIn("does not name it: Free on our router", lines[2])
        self.assertEqual(schemas.KINDS["stop"].guide, "stop-v1")
        self.assertIsNone(validate.check("stop", {"evidence": "e", "about": True, "stop": "weights"}, q)[1])
        self.assertIsNotNone(validate.check("stop", {"evidence": "e", "about": True, "stop": "shipped"}, q)[1])
        self.assertEqual(ST.parse({"about": True, "stop": "weights"}, "t").stop, "weights")
        self.assertIsNone(ST.parse({"about": True, "stop": "shipped"}, "t"))
        self.assertEqual(ST.coarse("model_release"), "release")

    def test_an_analysis_is_long_commentary_not_by_the_maker(self):
        self.assertTrue(TL.analysis("commentary", 1800, "other"))
        self.assertTrue(TL.analysis("commentary", 1800, None))
        self.assertFalse(TL.analysis("commentary", 1800, "maker"))
        self.assertFalse(TL.analysis("commentary", 400, "other"))
        self.assertFalse(TL.analysis("report", 5000, "other"))


@base.requires_test_db
class OneModelsLine(_Db):
    """0165's second case, invented names: a lab launches "Orbit 2 Small" (story A: launch and benchmarks), an arena
    ranks it, a week later its weights open (story B), a practitioner's breakdown joins story B; another model's
    launch names it once (story C). The line: A -> B as stops in order, the breakdown as analysis on B, C only named."""

    def setUp(self):
        super().setUp()
        from insight_core.markx import stops as ST
        self.switches = {"stops": True, "stop_types": True}
        patch = mock.patch.object(ST, "config", side_effect=lambda: dict(self.switches))
        patch.start()
        self.addCleanup(patch.stop)

    def story(self, headline, *members):
        self.cur.execute("INSERT INTO mx_stories (first_at, headline) VALUES (now(), %s) RETURNING id::text", (headline,))
        sid = self.cur.fetchone()[0]
        for m in members:
            self.cur.execute("INSERT INTO mx_story_posts (story_id, post_id, role, reason, valid_from) "
                             "VALUES (%s, %s, 'member', 'test', %s)", (sid, m, T0 + 11 * D))
        return sid

    def read(self, pid, kind, origin=None):
        task_id, _ = tasks.add(self.cur, "read3", f"read {pid}", a=pid)
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer={})
        repo.add_reading(self.cur, post_id=pid, guide="read-v3", call_id=call, kind=kind, events="one", lang="en",
                         headline=None, reading={"kind": kind, "event_type": "opinion_analysis", "origin": origin})

    def model(self, *posts):
        for p, role in posts:
            self.mentions(p, ("Orbit 2 Small", "model", role, "Vantor Labs", soft()))

    def line(self):
        launch = self.post_at(0, T0, "Introducing Orbit 2 Small", url="https://vantor.example/blog/orbit-2-small")
        scores = self.post_at(1, T0 + 3 * H, "Orbit 2 Small scores 31 on our index")
        thread = self.post_at(2, T0 + 5 * H, "Orbit 2 Small is out, thoughts?")
        self.model((launch, "subject"), (scores, "subject"), (thread, "subject"))
        ranking = self.post_at(3, T0 + 3 * D, "Orbit 2 Small ranks fourth on the arena")
        weights = self.post_at(0, T0 + 7 * D, "Orbit 2 Small weights, open", url="https://vantor.example/blog/weights")
        engine = self.post_at(1, T0 + 7 * D + H, "Day-0 support for Orbit 2 Small")
        router = self.post_at(2, T0 + 7 * D + 2 * H, "Orbit 2 Small, free on the router")
        breakdown = self.post_at(4, T0 + 8 * D, "Orbit 2 Small's attention, block by block",
                                 text="Orbit 2 Small's attention, block by block. " + "Its residual mixing reads " * 60)
        self.model((ranking, "subject"), (weights, "subject"), (engine, "subject"), (router, "actor"),
                   (breakdown, "subject"))
        rival = self.post_at(1, T0 + 10 * D, "Halcyon 3 launches")
        rival2 = self.post_at(2, T0 + 10 * D + H, "Halcyon 3 is fast")
        rival3 = self.post_at(3, T0 + 10 * D + 2 * H, "Halcyon 3 beats Orbit 2 Small, says its maker")
        rival4 = self.post_at(4, T0 + 10 * D + 3 * H, "Halcyon 3 pricing")
        for p in (rival, rival2, rival4):
            self.mentions(p, ("Halcyon 3", "model", "subject", "Halcyon", soft()))
        self.mentions(rival3, ("Halcyon 3", "model", "subject", "Halcyon", soft()),
                      ("Orbit 2 Small", "model", "mention", "Vantor Labs", soft()))
        self.read(breakdown, "commentary", "other")
        self.read(thread, "commentary", "other")      # short: no analysis
        self.stage()
        a = self.story("Vantor releases Orbit 2 Small, scoring 31", launch, scores, thread, ranking)
        b = self.story("Vantor opens Orbit 2 Small's weights", weights, engine, router, breakdown)
        c = self.story("Halcyon 3 launches", rival, rival2, rival3, rival4)
        return {"a": a, "b": b, "c": c, "launch": launch, "breakdown": breakdown, "thing": self.entity_of(launch)}

    def test_two_stories_are_stops_in_order_the_breakdown_hangs_on_the_second(self):
        x = self.line()
        tl = entity_views.entity_page(self.cur, x["thing"], now=T0 + 12 * D)["timeline"]
        stops = [(i["story"], i["stop"], i["stop_by"]) for i in tl["items"] if i["kind"] == "story"]
        self.assertEqual([s for s, _, _ in stops], [x["a"], x["b"]])
        self.assertEqual({by for _, _, by in stops}, {"type"})                    # nothing asked yet: the story type
        named = [i for i in tl["items"] if i["kind"] == "in_story"]
        self.assertEqual([i["story"] for i in named], [x["c"]])
        self.assertFalse(named[0]["top"])
        ana = [i for i in tl["items"] if i["kind"] == "analysis"]
        self.assertEqual([(i["post"]["id"], i["on"]) for i in ana], [(x["breakdown"], x["b"])])
        birth = tl["items"][0]
        self.assertEqual((birth["kind"], birth["post"]["id"], birth["on"]), ("birth", x["launch"], x["a"]))

    def test_the_stop_question_is_planned_once_and_its_answer_names_the_stop(self):
        from insight_core.markx import stops as ST
        x = self.line()
        out = ST.plan(self.cur, now=T0 + 12 * D)
        self.cur.execute("SELECT a::text, b::text, input FROM mx_tasks WHERE kind = 'stop' ORDER BY input")
        asked = self.cur.fetchall()
        mine = {a for a, b, _ in asked if b == self.book().root(x["thing"])}
        self.assertEqual(mine, {x["a"], x["b"]})                                  # not the story that only names it
        self.assertEqual(out["asked"], len(asked))
        self.assertEqual(ST.plan(self.cur, now=T0 + 12 * D)["asked"], 0)          # nothing new: nothing asked
        self.answer_task("stop", {"evidence": "weights opened", "about": True, "stop": "weights"}, a=x["b"])
        self.answer_task("stop", {"evidence": "launch", "about": True, "stop": "launch"}, a=x["a"])
        tl = entity_views.entity_page(self.cur, x["thing"], now=T0 + 12 * D)["timeline"]
        self.assertEqual([(i["stop"], i["stop_by"]) for i in tl["items"] if i["kind"] == "story"],
                         [("launch", "asked"), ("weights", "asked")])

    def test_the_switches(self):
        """`stop_types` off: the answers are kept, no word shown; `stops` off: every story a stop, nothing planned."""
        from insight_core.markx import stops as ST
        x = self.line()
        ST.plan(self.cur, now=T0 + 12 * D)
        self.answer_task("stop", {"evidence": "weights opened", "about": True, "stop": "weights"}, a=x["b"])
        self.switches["stop_types"] = False
        tl = entity_views.entity_page(self.cur, x["thing"], now=T0 + 12 * D)["timeline"]
        self.assertEqual([i["stop"] for i in tl["items"] if i["kind"] == "story"], [None, None])
        self.switches["stops"] = False
        tl = entity_views.entity_page(self.cur, x["thing"], now=T0 + 12 * D)["timeline"]
        self.assertEqual([i["story"] for i in tl["items"] if i["kind"] == "story"], [x["a"], x["b"], x["c"]])
        self.assertEqual(ST.plan(self.cur, now=T0 + 13 * D)["stories"], 0)

    def test_an_answer_saying_not_about_it_makes_a_named_story(self):
        x = self.line()
        from insight_core.markx import stops as ST
        ST.plan(self.cur, now=T0 + 12 * D)
        self.answer_task("stop", {"evidence": "about the router", "about": False, "stop": "adoption"}, a=x["b"])
        tl = entity_views.entity_page(self.cur, x["thing"], now=T0 + 12 * D)["timeline"]
        self.assertEqual([i["story"] for i in tl["items"] if i["kind"] == "in_story"], [x["b"], x["c"]])


if __name__ == "__main__":
    unittest.main()
