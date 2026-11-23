"""A thing's timeline (0165), invented names: a rename proposed by shared evidence and merged only by the owner's
answer, the entity page's timeline and the post page's "before", each with what it must not do."""
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
        self.assertEqual(months, [])                       # posts that only name it are no outside events (0250)
        self.assertEqual([i["at"] for i in tl["items"]], sorted(i["at"] for i in tl["items"]))
        self.assertEqual(tl["shown"], sum(1 for i in tl["items"] if i["top"]))
        for k, o in enumerate(outs[:2]):                   # about it, they are (each in its month)
            self.cur.execute("UPDATE mx_mentions SET role = %s WHERE post_id = %s", (("subject", "compared")[k], o))
        tl = entity_views.entity_page(self.cur, kite, now=T0 + 2 * D)["timeline"]
        months = [i for i in tl["items"] if i["kind"] == "outside"]
        self.assertEqual(sum(i["n"] for i in months), 2)
        self.assertFalse(any(i.get("named_only") for i in months))

    def test_a_post_that_only_names_it_is_never_its_birth_or_first_outside_mention(self):
        birth, linker, rel, outs, launch = self.thing()
        aside = self.post_at(4, T0 - 400 * D, "Ten tools we tried this year")       # names it in passing, long before
        self.mentions(aside, ("Acme Kite", "software", "mention", "Acme", soft()))
        self.stage()
        tl = entity_views.entity_page(self.cur, self.entity_of(birth), now=T0 + 2 * D)["timeline"]
        first = [i for i in tl["items"] if i["kind"] == "birth"][0]
        self.assertEqual(first["post"]["id"], birth)
        self.assertEqual(first["named_since"], T0 - 400 * D)
        self.assertEqual([i["post"]["id"] for i in tl["items"] if i["kind"] == "first_outside"], [linker])
        months = [i for i in tl["items"] if i["kind"] == "outside"]
        self.assertEqual(months, [])                       # only naming it, no outside event either (0250)

    def test_the_eight_most_important_are_shown_first(self):
        self.thing()
        evs = [TL._event("outside", T0 + k * D, None) for k in range(10)] + [TL._event("birth", T0 + 20 * D, None)]
        top = TL._top(evs)
        self.assertEqual(len(top), 8)
        self.assertIn(10, top)                                                        # the birth, though last

    def reading(self, pid, kind, obj, headline, event_type="product_release", origin="other"):
        task_id, _ = tasks.add(self.cur, "read3", f"read {pid}", a=pid)
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer={})
        repo.add_reading(self.cur, post_id=pid, guide="read-v3", call_id=call, kind=kind, events="one", lang="en",
                         headline=headline, reading={"kind": kind, "event_type": event_type, "origin": origin,
                                                     "main": {"object": obj, "actors": [], "headline_en": headline}})

    def test_the_first_outside_mention_is_about_the_thing(self):
        """A post about another thing that the extractor marks as about this one, or one where it is only an actor, is
        never its first outside mention (by_reading off); the first post whose main event is the thing is (0234)."""
        birth = self.post_at(0, T0 - 200 * D, "Introducing Acme Kite", url="https://dev.acme.example/blog/k1")
        self.mentions(birth, ("Acme Kite", "software", "subject", "Acme", soft()))
        method = self.post_at(2, T0 - 150 * D, "A pruning method for Zentra 5")
        self.mentions(method, ("Acme Kite", "software", "subject", "Acme", soft()))
        self.reading(method, "report", "pruning method", "A pruning method shrinks Zentra 5")
        actor = self.post_at(3, T0 - 120 * D, "Ten agents compared")
        self.mentions(actor, ("Acme Kite", "software", "actor", "Acme", soft()))
        review = self.post_at(2, T0 - 100 * D, "Acme Kite, reviewed")
        self.mentions(review, ("Acme Kite", "software", "subject", "Acme", soft()))
        self.reading(review, "commentary", "Acme Kite", "A review of Acme Kite")
        self.stage()
        tl = entity_views.entity_page(self.cur, self.entity_of(birth), now=T0 + 2 * D)["timeline"]
        self.assertEqual([i["post"]["id"] for i in tl["items"] if i["kind"] == "first_outside"], [review])

    def test_a_release_is_the_makers_release_reading(self):
        """A release is a maker post whose reading is a release, never its guide or research post; a round-up is never
        the birth; another's post read as a release by its own maker is no release of this thing and stays outside."""
        maker = lambda path: f"https://dev.acme.example/{path}/{uuid.uuid4().hex[:6]}"
        digest = self.post_at(2, T0 - 300 * D, "Everything this week")
        self.mentions(digest, ("Acme Kite", "software", "subject", "Acme", soft()))
        self.reading(digest, "roundup", "the week", "Ten things happened", event_type="digest")
        launch = self.post_at(0, T0 - 200 * D, "Introducing Acme Kite", url=maker("news"))
        self.mentions(launch, ("Acme Kite", "software", "subject", "Acme", soft()))
        self.reading(launch, "report", "Acme Kite", "Acme releases Acme Kite", event_type="product_release",
                     origin="maker")
        guide = self.post_at(0, T0 - 150 * D, "How teams use Acme Kite", url=maker("blog"))
        self.mentions(guide, ("Acme Kite", "software", "subject", "Acme", soft()))
        self.reading(guide, "report", "Acme Kite", "Teams use Acme Kite", event_type="tutorial_explainer",
                     origin="maker")
        quant = self.post_at(3, T0 - 100 * D, "1-bit Acme Kite is out")
        self.mentions(quant, ("Acme Kite", "software", "subject", "Acme", soft()))
        self.reading(quant, "report", "1-bit Acme Kite quant", "A lab releases a 1-bit Acme Kite",
                     event_type="model_release", origin="maker")
        self.stage()
        tl = entity_views.entity_page(self.cur, self.entity_of(launch), now=T0 + 2 * D)["timeline"]
        kinds = {}
        for i in tl["items"]:
            kinds.setdefault(i["kind"], []).append(i["post"]["id"] if i.get("post") else None)
        self.assertEqual(kinds.get("birth"), [launch])
        self.assertEqual(kinds.get("release", []), [])     # the launch is the birth (also a release)
        self.assertEqual([i.get("also") for i in tl["items"] if i["kind"] == "birth"], [["release"]])
        self.assertEqual(kinds.get("first_outside"), [quant])

    def test_a_round_up_or_a_post_about_another_thing_only_names_it(self):
        """A digest naming everything, or a post about another thing, is by its reading neither the thing's birth,
        first outside mention nor a month's lead (`by_reading`, on here) (0220)."""
        from insight_core.markx import stops as ST
        on = {"stops": True, "stop_types": False, "analysis": False, "by_reading": True}
        with mock.patch.object(ST, "config", side_effect=lambda: dict(on)):
            self.round_up_case()
        self.assertFalse(ST.config()["by_reading"])

    def round_up_case(self):
        birth, linker, rel, outs, launch = self.thing()
        digest = self.post_at(4, T0 - 300 * D, "This week: forty tools")
        self.mentions(digest, ("Acme Kite", "software", "subject", "Acme", soft()))
        self.reading(digest, "roundup", "forty tools", "Forty tools shipped this week", event_type="digest")
        other = self.post_at(2, T0 - 250 * D, "Day-0 support for Zentra 5")
        self.mentions(other, ("Acme Kite", "software", "subject", "Acme", soft()))
        self.reading(other, "report", "Zentra 5", "An engine supports Zentra 5 on day zero")
        self.reading(birth, "report", "Acme Kite", "Acme introduces Kite")       # names it as "Kite": no form; kept below
        self.stage()
        tl = entity_views.entity_page(self.cur, self.entity_of(birth), now=T0 + 2 * D)["timeline"]
        first = [i for i in tl["items"] if i["kind"] == "birth"][0]
        self.assertEqual(first["post"]["id"], birth)                                 # not the digest, not the other
        self.assertEqual(first["named_since"], T0 - 300 * D)                         # they still name it, earlier
        self.assertEqual([i["post"]["id"] for i in tl["items"] if i["kind"] == "first_outside"], [linker])
        self.assertFalse(any(i["top"] for i in tl["items"] if (i.get("post") or {}).get("id") in (digest, other)))

    def test_a_name_whose_posts_span_years_is_asked_whether_it_is_one_thing(self):
        """One name, several things breaks a line; its types and makers agree, so only the span asks the collision
        question, its sample across the years (0220)."""
        old = self.post_at(3, T0 - 4000 * D, "Lumen predicts the election")
        self.mentions(old, ("Lumen", "product", "subject"))
        for k in range(4):
            p = self.post_at(k % 3, T0 - (10 - k) * D, f"Lumen, the capture card ({k})")
            self.mentions(p, ("Lumen", "product", "subject"))
        self.stage(since=self.since)
        self.cur.execute("SELECT a::text, input FROM mx_tasks WHERE kind = 'collide'")
        got = self.cur.fetchall()
        self.assertEqual([a for a, _ in got], [self.entity_of(old)])
        self.assertIn("Lumen predicts the election", got[0][1])                       # the old year is in the sample
        young = self.post_at(0, T0 - 2 * D, "Kestrel ships")                           # a short span: never asked
        self.mentions(young, ("Kestrel", "product", "subject"))
        later = self.post_at(1, T0 - D, "Kestrel, a week in")
        self.mentions(later, ("Kestrel", "product", "subject"))
        self.stage(since=self.since)
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'collide'")
        self.assertEqual(self.cur.fetchone()[0], 1)

    def test_the_collision_sample_spans_the_years(self):
        from datetime import datetime, timezone
        at = lambda y: datetime(y, 6, 1, tzinfo=timezone.utc)
        ms = [(f"p{k}", "Lumen", "product", None, at(2026)) for k in range(12)] + [("old", "Lumen", "product", None, at(2012))]
        pick = I.collide_sample("e1", ms)
        self.assertEqual(len(pick), I.COLLIDE_MENTIONS)
        self.assertIn("old", [m[0] for m in pick])

    def test_whether_a_reading_is_about_the_thing(self):
        forms = {"acmekite", "kite"}
        self.assertTrue(TL.about_by_reading("report", {"main": {"object": "Acme Kite 2", "actors": []}}, None, forms))
        self.assertTrue(TL.about_by_reading("commentary", {"main": {"object": "x", "actors": ["Kite"]}}, None, forms))
        self.assertFalse(TL.about_by_reading("roundup", {"main": {"object": "Acme Kite"}}, None, forms))
        self.assertFalse(TL.about_by_reading("report", {"event_type": "digest"}, "Acme Kite and more", forms))
        self.assertFalse(TL.about_by_reading("report", {"main": {"object": "Zentra 5"}}, "Zentra 5 on day zero", forms))
        self.assertTrue(TL.about_by_reading("report", {}, "Zentra 5", set()))         # nothing to tell by: kept

    def test_the_entity_pages_version_line(self):
        """The family's versions on one line, the page's own version marked, each at its maker's first post about it; a
        version its maker only teased is off (0220, 0234)."""
        ids = {}
        for k, (name, version) in enumerate([("Orbit 2", "2"), ("Orbit 2.5", "2.5"), ("Orbit 3", "3")]):
            for n in range(4):
                p = self.post_at(n % 4, T0 - (300 - 100 * k - n) * D, f"{name} is out ({n})")
                self.mentions(p, (name, "model", "subject" if n < 2 else "mention", "Vantor",
                                  soft(family="Orbit", version=version)))
                if n < 2:
                    self.reading(p, "report", name, f"{name} is out", event_type="model_release",
                                 origin="maker" if n == 1 else "other")
                ids[name] = p
        for n in range(3):
            guess = self.post_at(n, T0 - (3 - n) * D, f"Orbit 9 next year? ({n})")
            self.mentions(guess, ("Orbit 9", "model", "subject", "Vantor", soft(family="Orbit", version="9")))
            self.reading(guess, "report", "Orbit 9", "Orbit 9 teased", event_type="leak_rumour",
                         origin="maker" if n == 0 else "other")
        self.stage()
        from insight_core.markx import stops as ST
        self.assertFalse(ST.config()["version_line"])                                   # off: under its bar
        self.assertIsNone(entity_views.entity_page(self.cur, self.entity_of(ids["Orbit 2.5"]), now=T0 + 2 * D)["version_line"])
        on = dict(ST.config(), version_line=True)
        with mock.patch.object(ST, "config", side_effect=lambda: dict(on)):
            self.version_line_on(ids)

    def version_line_on(self, ids):
        page = entity_views.entity_page(self.cur, self.entity_of(ids["Orbit 2.5"]), now=T0 + 2 * D)
        line = page["version_line"]
        self.assertEqual([[s["name"] for s in ln] for ln in line["lines"]], [["Orbit 2", "Orbit 2.5", "Orbit 3"]])
        self.assertEqual([s["current"] for s in line["lines"][0]], [False, True, False])
        self.assertEqual(line["lines"][0][0]["first"], T0 - 299 * D)                  # its maker's first post about it
        self.assertEqual(line["lines"][0][0]["by"], "maker")
        self.assertEqual((line["words"], line["grid"]), ([""], None))
        self.assertEqual(line["lines"][0][0]["posts"], 4)
        self.assertEqual(line["family"]["name"], "Orbit")
        fam = entity_views.entity_page(self.cur, line["family"]["id"], now=T0 + 2 * D)["version_line"]
        self.assertEqual(fam["lines"], [[dict(s, current=False) for s in line["lines"][0]]])   # the family's page too

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
    """0165's second case: a launch (story A), its weights a week later (story B) with a breakdown, another launch that
    names it once (story C). The line: A -> B as stops, the breakdown as analysis on B, C only named."""

    def setUp(self):
        super().setUp()
        from insight_core.markx import stops as ST
        self.switches = {"stops": True, "stop_types": True, "analysis": True}
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
        self.switches["analysis"] = False
        tl = entity_views.entity_page(self.cur, x["thing"], now=T0 + 12 * D)["timeline"]
        self.assertFalse([i for i in tl["items"] if i["kind"] == "analysis"])

    def test_the_post_pages_before_shows_the_stops_before_it(self):
        """The breakdown's page shows the launch stop before it; unasked stories are not stops there."""
        from insight_core.markx import stops as ST
        x = self.line()
        self.assertFalse([i for g in TL.before_post(self.cur, x["breakdown"]) for i in g["items"] if i["kind"] == "story"])
        ST.plan(self.cur, now=T0 + 12 * D)
        self.answer_task("stop", {"evidence": "launch", "about": True, "stop": "launch"}, a=x["a"])
        self.answer_task("stop", {"evidence": "weights", "about": True, "stop": "weights"}, a=x["b"])
        got = TL.before_post(self.cur, x["breakdown"])
        stops = [(i["story"], i["stop"]) for g in got for i in g["items"] if i["kind"] == "story"]
        self.assertEqual(stops, [(x["a"], "launch")])
        self.switches["stop_types"] = False
        got = TL.before_post(self.cur, x["breakdown"])
        self.assertEqual([i["stop"] for g in got for i in g["items"] if i["kind"] == "story"], [None])

    def test_a_story_read_after_the_pass_that_saw_it_join_is_asked(self):
        """A story whose members' readings came since the last pass is planned even with no new member; its pairs
        already asked are not asked again."""
        from insight_core.markx import stops as ST
        x = self.line()
        late = [self.post_at(3, T0 + 9 * D, "Orbit 2 Small, hands on"),
                self.post_at(4, T0 + 9 * D + H, "Orbit 2 Small tried")]
        d = self.story("Orbit 2 Small, tried", *late)
        first = ST.plan(self.cur, now=T0 + 12 * D)
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'stop' AND a = %s", (d,))
        self.assertEqual(self.cur.fetchone()[0], 0)                                # no roles yet: nothing asked
        self.model(*((p, "subject") for p in late))
        self.stage()
        self.cur.execute("UPDATE mx_mention_sets SET at = %s WHERE post_id = ANY(%s::uuid[])", (T0 + 12 * D + H, late))
        out = ST.plan(self.cur, now=T0 + 13 * D)
        self.cur.execute("SELECT a::text, b::text FROM mx_tasks WHERE kind = 'stop' AND a = %s", (d,))
        self.assertEqual(self.cur.fetchall(), [(d, self.book().root(x["thing"]))])
        self.assertEqual(out["asked"], 1, first)                                    # a and b, asked before: not again
        self.cur.execute("UPDATE mx_mention_sets SET at = %s WHERE post_id = ANY(%s::uuid[])", (T0 + 13 * D + H, late))
        self.assertEqual(ST.plan(self.cur, now=T0 + 14 * D)["asked"], 0)            # read again, asked once

    def test_an_answer_saying_not_about_it_makes_a_named_story(self):
        x = self.line()
        from insight_core.markx import stops as ST
        ST.plan(self.cur, now=T0 + 12 * D)
        self.answer_task("stop", {"evidence": "about the router", "about": False, "stop": "adoption"}, a=x["b"])
        tl = entity_views.entity_page(self.cur, x["thing"], now=T0 + 12 * D)["timeline"]
        self.assertEqual([i["story"] for i in tl["items"] if i["kind"] == "in_story"], [x["b"], x["c"]])


if __name__ == "__main__":
    unittest.main()


def ver(id_, name, key, *, posts=5, about=2, maker=None, first=None, variant=None, said=True, voices=(), report=None):
    """A version as the line reads it; `said`: its maker announced it at `first` (else `voices` report it at `report`)."""
    from insight_core.markx import timeline as TL
    first = first or T0
    return TL.Version(id_, name, key, maker, posts, about, first, None, variant=variant,
                      maker_first=first if said else None, release_first=report if voices else None,
                      voices=frozenset(voices))


class VersionLineRules(unittest.TestCase):
    """No database: a family's versions on lines (invented names), and what keeps a version off them (0220, 0234)."""

    def line(self, vs, family="Orbit", maker=None):
        return TL.version_lines(vs, family_name=family, family_maker=maker, same_maker=lambda a, b: a == b)

    def names(self, lines):
        return [[s.versions[0].name for s in ln] for ln in lines]

    def test_versions_in_release_order_one_stop_a_version(self):
        got = self.line([ver("c", "Orbit 3", (3,), first=T0 + 9 * D), ver("a", "Orbit 2", (2,)),
                         ver("b", "Orbit 2.5", (2, 5), first=T0 + 3 * D), ver("d", "Orbit 3.0", (3, 0), posts=4,
                                                                            first=T0 + 8 * D)])
        self.assertEqual(self.names(got), [["Orbit 2", "Orbit 2.5", "Orbit 3"]])
        three = got[0][2]
        self.assertEqual([v.id for v in three.versions], ["c", "d"])          # 3.0 is 3: one stop, the most named first
        self.assertEqual((three.first, three.by), (T0 + 8 * D, "maker"))       # the maker's first post about either
        self.assertEqual(TL.line_key((3, 0)), ("", (3,)))
        self.assertIsNone(TL.line_key((3, "x")))                                  # "3.x" is no version
        years = self.line([ver("w7", "Orbit 7", (7,), first=T0 + 900 * D), ver("w95", "Orbit 95", (95,), first=T0),
                           ver("w2k", "Orbit 2000", (2000,), first=T0 + 300 * D), ver("w10", "Orbit 10", (10,), first=T0 + 1200 * D),
                           ver("w98", "Orbit 98", (98,), first=T0 + 100 * D)])
        self.assertEqual(self.names(years), [["Orbit 95", "Orbit 98", "Orbit 2000", "Orbit 7", "Orbit 10"]])   # by date

    def test_a_rumour_or_a_nickname_is_no_stop_once_the_maker_speaks(self):
        got = self.line([ver("a", "Orbit 4", (4,), first=T0 + 10 * D), ver("b", "Orbit 4.5", (4, 5), first=T0 + 50 * D),
                         ver("n", "Orbit 4.6", (4, 6), posts=60, said=False, voices=("s1", "s2", "s3"), report=T0 + 60 * D),
                         ver("g", "Orbit 7", (7,), posts=20, said=False)])
        self.assertEqual(self.names(got), [["Orbit 4", "Orbit 4.5"]])           # never announced by its maker: off
        old = self.line([ver("o", "Orbit 1", (1,), said=False, voices=("s1", "s2"), report=T0 - 900 * D),
                         ver("a", "Orbit 4", (4,), first=T0), ver("b", "Orbit 5", (5,), first=T0 + 90 * D)])
        self.assertEqual(self.names(old), [["Orbit 1", "Orbit 4", "Orbit 5"]])   # older than the maker's first post here
        silent = self.line([ver("a", "Lumen 2", (2,), said=False, voices=("s1", "s2"), report=T0),
                            ver("b", "Lumen 3", (3,), said=False, voices=("s1", "s3", "s4"), report=T0 + 40 * D),
                            ver("c", "Lumen 4", (4,), posts=62, said=False, voices=("s1",), report=T0 + 80 * D)],
                           family="Lumen")
        self.assertEqual(self.names(silent), [["Lumen 2", "Lumen 3"]])           # one account's many posts: one voice
        self.assertEqual((silent[0][1].first, silent[0][1].by, silent[0][1].voices), (T0 + 40 * D, "voices", 3))

    def test_a_series_or_a_phrase_is_no_version(self):
        got = self.line([ver("a", "Orbit 40", (40,)), ver("s", "Orbit 40 Series", (40,), posts=90, variant="series"),
                         ver("t", "Orbit 50 Series", (50,), variant="Series"), ver("b", "Orbit 50", (50,), first=T0 + D),
                         ver("p", "Orbit 50 in Copilot", (50,), posts=99, variant="in copilot", first=T0 - D)])
        self.assertEqual(self.names(got), [["Orbit 40", "Orbit 50"]])
        self.assertEqual([v.id for s in got[0] for v in s.versions], ["a", "b"])
        self.assertEqual(TL.name_shape("Orbit 4 vs Lumen 2", "vs lumen 2"), "phrase")
        self.assertEqual(TL.name_shape("Orbit 4 Pro Max", "pro max"), "version")

    def test_product_lines_a_code_name_and_the_tier_grid(self):
        got = self.line([ver("k2", "Kite 2", (2,)), ver("k3", "Kite 3", (3,), first=T0 + 100 * D),
                         ver("c2", "Kite Coder 2", (2,), variant="Coder", first=T0 + 20 * D),
                         ver("c3", "Kite Coder 3", (3,), variant="Coder", first=T0 + 120 * D),
                         ver("p3", "Kite 3 Preview", (3,), variant="Preview", posts=3, first=T0 + 90 * D),
                         ver("s3", "Kite 3 Sierra", (3,), variant="Sierra", posts=2, first=T0 + 95 * D)], family="Kite")
        self.assertEqual(self.names(got), [["Kite 2", "Kite 3"], ["Kite Coder 2", "Kite Coder 3"]])
        self.assertEqual(sorted(v.id for v in got[0][1].versions), ["k3", "p3", "s3"])   # a stage, a code name: 3's
        self.assertEqual([ln[0].word for ln in got], ["", "coder"])
        tiers = self.line([ver(f"{t}{n}", f"Orbit {t.title()} {n}", tuple(int(x) for x in n.split(".")), variant=t,
                               first=T0 + (10 * k + j) * D)
                           for k, n in enumerate(["3", "4", "4.5"]) for j, t in enumerate(["opus", "sonnet"])]
                          + [ver("h45", "Orbit Haiku 4.5", (4, 5), variant="haiku", first=T0 + 22 * D)])
        g = TL.grid(tiers)
        self.assertEqual(g["tiers"], ["opus", "sonnet"])                        # haiku: one stop, no line
        self.assertEqual([(r["generation"], sorted(r["cells"])) for r in g["rows"]],
                         [("3", ["opus", "sonnet"]), ("4", ["opus", "sonnet"]), ("4.5", ["opus", "sonnet"])])
        self.assertIsNone(TL.grid(got))                                          # one product line: no grid

    def test_a_letter_starts_its_own_line_and_a_number_written_without_it_joins_it(self):
        got = self.line([ver("k2", "Kite K2", ("k", 2)), ver("k25", "Kite K2.5", ("k", 2, 5), first=T0 + D),
                         ver("k3", "Kite K3", ("k", 3), first=T0 + 2 * D), ver("x3", "Kite 3", (3,), posts=2, first=T0 + 2 * D),
                         ver("s4", "Kite S4", ("s", 4)), ver("s5", "Kite S5", ("s", 5), first=T0 + D)], family="Kite")
        self.assertEqual(self.names(got), [["Kite K2", "Kite K2.5", "Kite K3"], ["Kite S4", "Kite S5"]])
        self.assertEqual([v.id for v in got[0][2].versions], ["k3", "x3"])      # "Kite 3" is K3 (no other line has 3)
        both = self.line([ver("k3", "Kite K3", ("k", 3)), ver("s3", "Kite S3", ("s", 3)), ver("x3", "Kite 3", (3,)),
                          ver("x4", "Kite 4", (4,), first=T0 + D), ver("k4", "Kite K4", ("k", 4), first=T0 + D)], family="Kite")
        self.assertEqual(self.names(both), [["Kite K3", "Kite K4"]])   # 4 is only K's; 3 is K's and S's: left alone
        self.assertEqual([v.id for v in both[0][1].versions], ["k4", "x4"])
        own = self.line([ver("r1", "Kite R1", ("r", 1)), ver("r2", "Kite R2", ("r", 2), first=T0 + D),
                         ver("v2", "Kite V2", (2,)), ver("v3", "Kite V3", (3,), first=T0 + D),
                         ver("v4", "Kite V4", (4,), first=T0 + 2 * D)], family="Kite")
        self.assertEqual(self.names(own), [["Kite V2", "Kite V3", "Kite V4"], ["Kite R1", "Kite R2"]])   # a line of its own

    def test_another_makers_version_is_off_the_line(self):
        got = self.line([ver("a", "Orbit 4", (4,), maker="Vantor"), ver("b", "Orbit 5", (5,), maker="Vantor", first=T0 + D),
                         ver("y", "Zentra Orbit 5", (5,), maker="Zentra", posts=5), ver("c", "Orbit 6", (6,), first=T0 + 2 * D)],
                        maker="Wrongco")                       # the family's own field was wrong: its posts decide
        self.assertEqual(self.names(got), [["Orbit 4", "Orbit 5", "Orbit 6"]])
        self.assertEqual([v.id for v in got[0][1].versions], ["b"])

    def test_a_version_none_is_about_is_off(self):
        got = self.line([ver("a", "Orbit 2", (2,)), ver("b", "Orbit 3", (3,), first=T0 + D),
                         ver("y", "Orbit 9", (9,), posts=5, about=0, first=T0 + 2 * D)])
        self.assertEqual(self.names(got), [["Orbit 2", "Orbit 3"]])

    def test_a_build_number_or_a_dot_left_out_is_not_a_new_version(self):
        got = self.line([ver("a", "Orbit 4", (4,)), ver("b", "Orbit 4.6", (4, 6), first=T0 + D),
                         ver("c", "Orbit 46", (46,), posts=2, first=T0 + D),
                         ver("d", "Orbit 2512", (2512,), posts=8), ver("e", "Orbit 5", (5,), first=T0 + 2 * D)])
        self.assertEqual(self.names(got), [["Orbit 4", "Orbit 4.6", "Orbit 5"]])
        self.assertEqual([v.id for v in got[0][1].versions], ["b", "c"])          # 46 is 4.6 written without its dot
        eleven = self.line([ver("a", "Orbit 1.1", (1, 1), posts=4), ver("b", "Orbit 3", (3,), first=T0 + D),
                            ver("c", "Orbit 11", (11,), posts=40, first=T0 + 2 * D)])
        self.assertEqual(self.names(eleven), [["Orbit 1.1", "Orbit 3", "Orbit 11"]])   # 11 is the better named: its own
        dated = self.line([ver("a", "Orbit 2407", (2407,)), ver("b", "Orbit 2512", (2512,), first=T0 + D)])
        self.assertEqual(self.names(dated), [["Orbit 2407", "Orbit 2512"]])      # one numbering: a line still

    def test_no_line_for_a_one_letter_family_or_one_stop(self):
        self.assertEqual(self.line([ver("a", "X-33", (33,)), ver("b", "X-45", (45,))], family="x"), [])
        self.assertEqual(self.line([ver("a", "Orbit 2", (2,))]), [])


@base.requires_test_db
class ThingLinks(_Db):
    """The relations a post states between two of its things, as entity edges with their posts, shown on both pages;
    switched-off ones never written; `released` only with the thing's own maker (0220)."""

    def state(self, pid, relations):
        self.cur.execute("UPDATE mx_calls SET answer = %s::jsonb WHERE task_id IN (SELECT id FROM mx_tasks WHERE a = %s)",
                         (json.dumps({"entities": [], "relations": relations}), pid))

    def graph(self, now=T0 + 2 * D):
        from insight_core.markx import graph
        run = repo.start_run(self.cur, code_version="test", config={})
        return graph.stage(self.cur, now=now, run_id=run, budget=None)

    def edges(self, current=True):
        self.cur.execute("""SELECT a::text, b::text, relation, rule, evidence, valid_from, valid_to FROM mx_connections
                             WHERE a_kind = 'entity' AND rule = 'stated'""" + (" AND valid_to IS NULL" if current else ""))
        return self.cur.fetchall()

    def touched(self, pid, at):
        self.cur.execute("UPDATE mx_calls SET created_at = %s WHERE task_id IN (SELECT id FROM mx_tasks WHERE a = %s)",
                         (at, pid))

    def test_stated_relations_become_edges_with_their_posts(self):
        # this test pins partnered_with off, so a switched-off relation is never written
        bands = json.loads(json.dumps(I.bands()))
        bands["relations"]["on"]["partnered_with"] = False
        patcher = mock.patch.object(I, "bands", return_value=bands)
        patcher.start()
        self.addCleanup(patcher.stop)
        tune = self.post_at(0, T0 - 10 * D, "Sabi 2: a fine-tune of Orbit 3")
        self.mentions(tune, ("Sabi 2", "model", "subject", "Kestrel"), ("Orbit 3", "model", "mention", "Vantor"))
        self.state(tune, [{"a": "Sabi 2", "rel": "based_on", "b": "Orbit 3"}])
        again = self.post_at(1, T0 - 5 * D, "Sabi 2 is built on Orbit 3")
        self.mentions(again, ("Sabi 2", "model", "subject", "Kestrel"), ("Orbit 3", "model", "mention", "Vantor"))
        self.state(again, [{"a": "Sabi 2", "rel": "based_on", "b": "Orbit 3"}])
        launch = self.post_at(2, T0 - 3 * D, "Vantor releases Orbit 3")
        self.mentions(launch, ("Vantor", "org", "actor"), ("Orbit 3", "model", "subject", "Vantor"),
                      ("Rehost", "org", "mention"))
        self.state(launch, [{"a": "Vantor", "rel": "released", "b": "Orbit 3"},
                            {"a": "Rehost", "rel": "released", "b": "Orbit 3"},        # not its maker: never
                            {"a": "Vantor", "rel": "partnered_with", "b": "Rehost"},   # switched off: never
                            {"a": "Nobody", "rel": "based_on", "b": "Orbit 3"}])       # not one of its things
        self.stage()
        out = self.graph()
        sabi, orbit, vantor = self.entity_of(tune), self.entity_of(tune, 1), self.entity_of(launch)
        got = {(a, b, rel): (ev, vf) for a, b, rel, _r, ev, vf, _vt in self.edges()}
        self.assertEqual(set(got), {(sabi, orbit, "based_on"), (vantor, orbit, "released")})
        ev, since = got[(sabi, orbit, "based_on")]
        self.assertEqual((ev["posts"], since), ([tune, again], T0 - 10 * D))         # oldest first, from its first post
        self.assertTrue(out["relations"]["backfill"]["done"])
        page = entity_views.entity_page(self.cur, sabi, now=T0 + 2 * D)
        self.assertEqual([(r["relation"], r["direction"], r["other"]["name"], r["posts"]) for r in page["relations"]],
                         [("based_on", "out", "Orbit 3", 2)])
        page = entity_views.entity_page(self.cur, orbit, now=T0 + 2 * D)
        self.assertEqual([(r["relation"], r["direction"], r["other"]["name"]) for r in page["relations"]],
                         [("based_on", "in", "Sabi 2"), ("released", "in", "Vantor")])
        # a post that no longer states it leaves the evidence; the last one closes the edge, kept
        self.state(again, [])
        self.touched(again, T0 + 3 * D)                                               # read again: states nothing
        self.graph(now=T0 + 3 * D)
        now_ev = {(a, b, r): ev for a, b, r, _r, ev, *_ in self.edges()}
        self.assertEqual(now_ev[(sabi, orbit, "based_on")]["posts"], [tune])
        self.state(tune, [])
        self.touched(tune, T0 + 4 * D)
        self.graph(now=T0 + 4 * D)
        self.assertNotIn((sabi, orbit, "based_on"), {(a, b, r) for a, b, r, *_ in self.edges()})
        closed = [row for row in self.edges(current=False) if row[2] == "based_on"]
        self.assertEqual(len(closed), 1)
        self.assertIsNotNone(closed[0][6])

    def test_the_scope_finds_a_read_again_post_by_the_edges_it_is_evidence_of(self):
        """The relation scope reads the stated edges' evidence posts once: a post read again that states nothing now is
        in scope exactly when a current stated edge cites it (0244)."""
        from insight_core.markx import graph
        tune = self.post_at(0, T0 - 10 * D, "Sabi 2: a fine-tune of Orbit 3")
        self.mentions(tune, ("Sabi 2", "model", "subject", "Kestrel"), ("Orbit 3", "model", "mention", "Vantor"))
        self.state(tune, [{"a": "Sabi 2", "rel": "based_on", "b": "Orbit 3"}])
        other = self.post_at(1, T0 - 5 * D, "Kestrel hires")
        self.mentions(other, ("Kestrel", "org", "actor"))
        self.stage()
        self.graph()
        self.state(tune, [])
        self.touched(tune, T0 + 3 * D)
        self.touched(other, T0 + 3 * D)
        counts = {}
        got = graph._relation_scope(self.cur, T0 + 3 * D - graph.MARGIN, counts)
        self.assertIn(tune, got)
        self.assertNotIn(other, got)
        self.assertEqual(counts["since_posts"], 1)

    @mock.patch.object(I, "families_on", lambda: {"maker": True, "stem": True, "namesakes": True})
    def test_a_relation_never_crosses_two_makers_namesakes(self):
        """"Orbit" the exchange is linked to Vantor's model Orbit by its name, but "Orbit released Orbit dollar" is not
        the model's release (0230)."""
        model = self.post_at(0, T0 - 10 * D, "Vantor ships Orbit")
        self.mentions(model, ("Orbit", "model", "subject", "Vantor"), ("Vantor", "org", "actor"))
        self.state(model, [{"a": "Vantor", "rel": "released", "b": "Orbit"}])
        self.stage()                                                             # the model first: the name is its
        coin = self.post_at(1, T0 - 5 * D, "The Orbit exchange launches the Orbit dollar")
        self.mentions(coin, ("Orbit", "org", "actor", None, None, "Orbit exchange"),
                      ("Orbit dollar", "product", "subject", "Orbit"))
        self.state(coin, [{"a": "Orbit", "rel": "released", "b": "Orbit dollar"}])
        self.stage()
        self.graph()
        self.assertEqual(self.entity_of(coin), self.entity_of(model))          # one entity by the name (identity's)
        got = {(a, b, rel) for a, b, rel, *_ in self.edges()}
        self.assertEqual(got, {(self.entity_of(model, 1), self.entity_of(model), "released")})


class DerivedRelations(unittest.TestCase):
    """No database: the relations ent-v5's own fields say (graph.derived), no relation asked (0224)."""

    @staticmethod
    def m(name, type_, role, maker=None, span=None):
        return {"name": name, "span": span or name, "type": type_, "role": role, "maker": maker}

    def test_a_maker_the_reading_names_released_the_thing(self):
        from insight_core.markx import graph
        ms = [self.m("Vantor", "org", "actor"), self.m("Orbit 3", "model", "subject", "Vantor"),
              self.m("Kestrel", "org", "mention"), self.m("Lumen", "product", "subject", "Zentra"),   # maker not named
              self.m("Orbit Set", "dataset", "subject", "Vantor"),                                   # not a thing type
              self.m("Rae Lin", "person", "subject"), self.m("tinyorbit", "software", "subject", "rae lin"),
              self.m("Vantor Cloud", "product", "subject", "Vantor Cloud"),                          # itself: never
              self.m("Orbit Mini", "model", "mention", "Vantor")]                                     # not the subject
        self.assertEqual(graph.derived(ms, on=("released",)), [(0, "released", 1), (5, "released", 6)])
        self.assertEqual(graph.derived(ms, on=("based_on",)), [])
        # the maker named only by a thing (not an org or person), or only in passing (not the subject or actor): never
        self.assertEqual(graph.derived([self.m("Orbit", "software", "mention"),
                                        self.m("Orbit Lite", "product", "subject", "Orbit")]), [])
        self.assertEqual(graph.derived([self.m("Vantor", "org", "mention"),
                                        self.m("Orbit 3", "model", "subject", "Vantor")]), [])
        # the maker matched by its span ("Вантор" written, "Vantor" its name)
        self.assertEqual(graph.derived([self.m("Vantor", "org", "actor", span="Вантор"),
                                        self.m("Orbit 3", "model", "subject", "Вантор")]), [(0, "released", 1)])

    def test_the_subject_is_based_on_each_predecessor(self):
        from insight_core.markx import graph
        ms = [self.m("Sabi 2", "model", "subject", "Kestrel"), self.m("Orbit 3", "model", "predecessor", "Vantor"),
              self.m("Orbit 2", "model", "compared"), self.m("Vantor", "org", "mention"),
              self.m("Old Report", "document", "predecessor"),                                       # not a thing
              self.m("Sabi 2", "model", "subject", span="Sabi-2")]                                    # the same name: once
        self.assertEqual(graph.derived(ms, on=("based_on",)), [(0, "based_on", 1)])
        self.assertEqual(graph.derived(ms), [(0, "based_on", 1)])                # Orbit 3 is not the subject
        apart = [dict(ms[0], call="w1"), dict(ms[1], call="w2")]
        self.assertEqual(graph.derived(apart, on=("based_on",)), [])            # never across two windows (0234)

    def test_the_based_on_question_and_its_verdict(self):
        from insight_core.markx import graph
        window = "Platform: site | Source: Lab\nTitle: Sabi 2\nText: " + "x" * 5000 + " Sabi-2 is a fine-tune of Orbit 3. " + "y" * 5000
        q = graph.derive_question(self.m("Sabi 2", "model", "subject", span="Sabi-2"),
                                  self.m("Orbit 3", "model", "predecessor"), window)
        self.assertTrue(q.startswith('A: "Sabi 2" (model)\nB: "Orbit 3" (model)\nPOST:\n'))  # its span keys as its name
        self.assertIn("Sabi-2 is a fine-tune of Orbit 3.", q)
        self.assertLess(len(q), graph.DERIVE_CHARS + 400)                     # the window cut around both names
        said = lambda *rels: [(f"c{k}", {"relation": r}) for k, r in enumerate(rels)]
        self.assertIsNone(graph.derive_verdict(said("derived"), runs=2))
        self.assertEqual(graph.derive_verdict(said("derived", "derived"), runs=2)["relation"], "derived")
        self.assertEqual(graph.derive_verdict(said("derived", "replaces"), runs=2)["relation"], "unknown")


@base.requires_test_db
class DerivedLinks(_Db):
    """Graph section 4 reads the relations ent-v5's fields say from the post's current mentions (`stated`): off,
    nothing; on, the edges with their posts (0224)."""

    def v5_mentions(self, pid, *ents):
        task_id, _ = tasks.entities_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                             answer={"entities": []})
        rows = [dict({"span": e[0], "name": e[0], "name_key": tasks.name_key(e[0]), "type": e[1], "role": e[2],
                      "maker": e[3] if len(e) > 3 else None}, **{f: None for f in N.FIELDS}) for e in ents]
        repo.add_mentions(self.cur, post_id=pid, guide="ent-v5", call_id=call, mentions=rows)

    def graph(self, derived, now=T0 + 2 * D):
        from insight_core.markx import graph
        bands = json.loads(json.dumps(I.bands()))
        bands["relations"]["derived"] = {r: True for r in derived}
        bands["relations"]["derive"] = {"ask": True, "runs": 1}   # one answer settles a pair here
        run = repo.start_run(self.cur, code_version="test", config={})
        with mock.patch.object(I, "bands", return_value=bands):
            return graph.stage(self.cur, now=now, run_id=run, budget=None)

    def edges(self):
        self.cur.execute("""SELECT a::text, b::text, relation, evidence FROM mx_connections
                             WHERE a_kind = 'entity' AND rule = 'stated' AND valid_to IS NULL""")
        return {(a, b, r): ev for a, b, r, ev in self.cur.fetchall()}

    def test_ent_v5_fields_become_edges_only_when_switched_on(self):
        launch = self.post_at(0, T0 - 3 * D, "Vantor releases Orbit 3")
        self.v5_mentions(launch, ("Vantor", "org", "actor"), ("Orbit 3", "model", "subject", "Vantor"),
                         ("Lumen", "product", "mention", "Zentra"))
        tune = self.post_at(1, T0 - 2 * D, "Sabi 2, fine-tuned from Orbit 3")
        self.v5_mentions(tune, ("Sabi 2", "model", "subject"), ("Orbit 3", "model", "predecessor", "Vantor"))
        self.stage()
        vantor, orbit, sabi = self.entity_of(launch), self.entity_of(launch, 1), self.entity_of(tune)
        self.graph(derived=())
        self.assertEqual(self.edges(), {})                                     # off: nothing from ent-v5's fields
        out = self.graph(derived=("released",), now=T0 + 3 * D)
        self.assertTrue(out["relations"]["backfill"]["done"])
        self.assertEqual(set(self.edges()), {(vantor, orbit, "released")})     # switched on: the backfill reads them
        self.assertEqual(self.edges()[(vantor, orbit, "released")]["posts"], [launch])
        self.graph(derived=("released", "based_on"), now=T0 + 4 * D)
        self.assertEqual(set(self.edges()), {(vantor, orbit, "released")})     # based_on waits for its check
        self.check_based_on(tune, sabi, orbit, vantor)

    def check_based_on(self, tune, sabi, orbit, vantor):
        """The (subject, predecessor) pair asked once (kind derive); `replaces` makes no edge, `derived` does (0234)."""
        from insight_core.markx import graph
        bands = json.loads(json.dumps(I.bands()))
        bands["relations"]["derive"] = {"ask": True, "runs": 1}
        with mock.patch.object(I, "bands", return_value=bands):
            self.assertEqual(graph.plan_derive(self.cur, now=T0 + 4 * D)["asked"], 1)
            self.assertEqual(graph.plan_derive(self.cur, now=T0 + 4 * D)["asked"], 0)   # asked once a pair
        self.cur.execute("SELECT a::text, b::text, input FROM mx_tasks WHERE kind = 'derive'")
        (a, b, text), = self.cur.fetchall()
        self.assertEqual((a, b), (sabi, orbit))
        self.assertIn('A: "Sabi 2" (model)', text)
        self.assertIn('B: "Orbit 3" (model)', text)
        tid, = self.answer_task("derive", {"reason": "It only follows Orbit 3.", "relation": "replaces"}, a=sabi)
        self.graph(derived=("released", "based_on"), now=T0 + 5 * D)
        self.assertNotIn((sabi, orbit, "based_on"), self.edges())
        self.cur.execute("UPDATE mx_calls SET answer = %s::jsonb WHERE task_id = %s",
                         (json.dumps({"reason": "A fine-tune of Orbit 3.", "relation": "derived"}), tid))
        self.cur.execute("UPDATE mx_tasks SET answered_at = %s WHERE id = %s", (T0 + 5 * D + H, tid))   # since the last run
        self.graph(derived=("released", "based_on"), now=T0 + 6 * D)
        got = self.edges()
        self.assertEqual(set(got), {(vantor, orbit, "released"), (sabi, orbit, "based_on")})
        self.assertEqual(got[(sabi, orbit, "based_on")]["posts"], [tune])

    def test_a_predecessor_in_another_window_is_no_candidate(self):
        from insight_core.markx import graph
        long = self.post_at(1, T0 - 2 * D, "This week in models")
        self.v5_mentions(long, ("Sabi 2", "model", "subject"))
        self.v5_mentions(long, ("Orbit 3", "model", "predecessor", "Vantor"))   # another window: another call
        self.stage()
        cands, _ = graph.derive_candidates(self.cur, since=None, limit=10)
        self.assertEqual(cands, [])

    def test_a_new_answer_is_read_by_the_next_run(self):
        self.stage()
        self.graph(derived=("released",))                                      # the backfill done: nothing yet
        launch = self.post_at(0, T0 - 3 * D, "Vantor releases Orbit 3")
        self.v5_mentions(launch, ("Vantor", "org", "actor"), ("Orbit 3", "model", "subject", "Vantor"))
        self.stage()
        self.cur.execute("UPDATE mx_calls SET created_at = %s WHERE task_id IN (SELECT id FROM mx_tasks WHERE a = %s)",
                         (T0 + 2 * D + H, launch))
        self.graph(derived=("released",), now=T0 + 3 * D)                      # its call is new since the last run
        self.assertEqual(set(self.edges()), {(self.entity_of(launch), self.entity_of(launch, 1), "released")})
