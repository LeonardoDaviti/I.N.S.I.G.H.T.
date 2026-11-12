"""A thing's timeline (issue 0165), with invented names: a product's component gets its own entity (A), a rename is
proposed by shared evidence and only the owner's answer merges it (B), the entity page's timeline (C) and the post
page's "before" from it (D); each with what it must not do (a version bump, an org's word, the owner's answers, no
evidence)."""
from __future__ import annotations

import json
import unittest
import uuid
from unittest import mock

from insight_core.markx import components as C, entity_answers, entity_views, identity as I, names as N, rename as RN
from insight_core.markx import repo, schemas, tasks, timeline as TL, validate
from insight_core.tests import test_markx_entities as base

T0, H, D = base.T0, base.H, base.D
_CONFIG = C.config


def soft(**kw):
    return {"family": None, "version": None, "variant": None, "size": None, "build": None, **kw}


def config_with(**over):
    def got():
        return {**_CONFIG(), **over}
    return got


class Rules(unittest.TestCase):
    """No database: the component's shape, the address's compared form, the rename guards."""
    ent, book = base.Rules.ent, base.Rules.book

    def products(self):
        acme = self.ent("o", "Acme", "org")
        forge = self.ent("f", "Acme Forge", "software", maker="Acme", fields=soft())
        other = self.ent("x", "Orbis Forge", "software", maker="Orbis", fields=soft())
        return self.book(acme, forge, other)

    def test_a_component_is_a_product_name_followed_by_its_own_words(self):
        book = self.products()
        self.assertEqual(C.split(book, "acme forge snap", "Acme"), ("f", "acme forge", "snap"))
        self.assertEqual(C.split(book, "acme forge snap planner", None)[0], "f")   # the longest product prefix
        self.assertIsNone(C.split(book, "acme forge 2", "Acme"))        # a version is a version
        self.assertIsNone(C.split(book, "acme forge labs", "Acme"))     # an org's word
        self.assertIsNone(C.split(book, "acme snap", "Acme"))           # an org is no product
        self.assertIsNone(C.split(book, "acme forge snap", "Orbis"))    # another maker's product
        self.assertIsNone(C.split(book, "acme forge", "Acme"))          # the product itself

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
class Components(_Db):
    def forge(self):
        p = self.post_at(0, T0, "Acme ships Forge")
        self.mentions(p, ("Acme Forge", "software", "subject", "Acme", soft()))
        self.stage()
        return self.ent_named("Acme Forge")

    def test_a_component_about_its_post_gets_its_own_entity_under_the_product(self):
        with mock.patch.object(C, "config", config_with(components=True)):
            forge = self.forge()
            p = self.post_at(1, T0 + D, "Introducing Acme Forge Snap")
            self.mentions(p, ("Acme Forge Snap", "software", "subject", "Acme", soft()))
            out = self.stage(since=self.since)
        snap = self.entity_of(p)
        book = self.book()
        self.assertEqual(book.ents[snap].name, "Acme Forge Snap")
        self.assertEqual((book.ents[snap].parent, book.ents[snap].level), (forge, "thing"))
        self.assertEqual(out["components"]["made"], 1)
        page = entity_views.entity_page(self.cur, forge, now=T0 + 2 * D)
        self.assertEqual([(c["name"], c["posts"]) for c in page["components"]], [("Acme Forge Snap", 1)])
        self.assertNotIn(snap, [v["id"] for v in page["versions"]])

    def test_a_span_naming_the_component_moves_its_mention_only_with_evidence(self):
        with mock.patch.object(C, "config", config_with(components=True)):
            forge = self.forge()
            about = self.post_at(1, T0 + D, "Acme Forge Snap restores workers")      # the post is about it
            self.mentions(about, ("Acme Forge", "software", "subject", "Acme", soft(), "Acme Forge Snap"))
            aside = self.post_at(2, T0 + D, "A week of tools")                        # an aside: no evidence
            self.mentions(aside, ("Acme Forge", "software", "mention", "Acme", soft(), "Acme Forge Snap"))
            marked = self.post_at(3, T0 + D, "Serving notes")                          # the answer says part_of
            self.mentions(marked, ("Acme Forge", "software", "mention", "Acme", soft(), "Acme Forge Snap"))
            self.cur.execute("""UPDATE mx_calls SET answer = %s::jsonb WHERE id = (SELECT call_id FROM mx_mentions
                                 WHERE post_id = %s LIMIT 1)""",
                             (json.dumps({"entities": [], "relations": [{"a": "Acme Forge Snap", "rel": "part_of",
                                                                          "b": "Acme Forge"}]}), marked))
            self.stage(since=self.since)
            snap = self.ent_named("Acme Forge Snap")
            self.assertIsNotNone(snap)
            self.assertEqual(self.entity_of(about), snap)
            self.assertEqual(self.entity_of(marked), snap)
            self.assertEqual(self.entity_of(aside), forge)
            self.assertEqual(self.book().ents[snap].parent, forge)
            full = self.stage(full=True)                                              # the full pass agrees
            self.assertEqual(full["check"]["relinked"], 0)
            self.assertEqual(self.entity_of(about), snap)

    def test_off_by_default_and_a_version_stays_a_version(self):
        forge = self.forge()
        p = self.post_at(1, T0 + D, "Acme Forge Snap")
        self.mentions(p, ("Acme Forge", "software", "subject", "Acme", soft(), "Acme Forge Snap"))
        out = self.stage(since=self.since)
        self.assertEqual(out["components"], {"off": True})
        self.assertEqual(self.entity_of(p), forge)                                    # nothing moves while off
        self.assertEqual(C.preview(self.cur)["mentions"], 1)                          # but the preview counts it
        self.assertEqual(C.preview(self.cur)["moved"], 1)
        v2 = self.post_at(2, T0 + D, "Acme Forge 2")
        self.mentions(v2, ("Acme Forge 2", "software", "subject", "Acme", soft(family="Acme Forge", version="2")))
        book = self.book()
        ms = I._mentions(self.cur, schemas.mention_guides(), unlinked=True)
        self.assertEqual(C.plan(self.cur, book, [m for m in ms if m.post_id == v2]), {})

    def test_a_component_made_under_its_maker_is_reparented_and_logged(self):
        forge = self.forge()
        p = self.post_at(1, T0 + D, "Acme Forge Snap")
        self.mentions(p, ("Acme Forge Snap", "software", "subject", "Acme", soft()))
        self.stage(since=self.since)                                                  # off: made under the maker
        snap = self.entity_of(p)
        self.assertEqual(self.book().ents[snap].parent, self.ent_named("Acme"))
        with mock.patch.object(C, "config", config_with(components=True)):
            out = self.stage(full=True)
        self.assertEqual(out["components"]["reparented"], 1)
        self.assertEqual(self.book().ents[snap].parent, forge)
        self.cur.execute("SELECT kind, field, old, new FROM mx_entity_fixes WHERE entity_id = %s", (snap,))
        self.assertEqual(self.cur.fetchall(), [("component", "parent", self.ent_named("Acme"), forge)])


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


if __name__ == "__main__":
    unittest.main()
