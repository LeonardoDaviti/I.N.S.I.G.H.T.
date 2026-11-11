"""Mark X entity identity fixes (issue 0164), with invented names: the name and type shown by evidence (1), a product
family never merged into an org and a version's family never an org (2), families split by a maker or brand prefix
joined (3), an org and its name with a corporate suffix joined only with posts that say so (4); each with what it must
not do (two makers, a version guard, the owner's answers), and the repair of data already made (undos are redirects
undone, never deletions)."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from insight_core.markx import entity_answers, entity_repair as R, entity_views, identity as I
from insight_core.tests import test_markx_entities as base

T0, H, D = base.T0, base.H, base.D
_CONFIG = R.config


def v(family, version, variant=None):
    return {"family": family, "version": version, "variant": variant, "size": None, "build": None}


class Guards(unittest.TestCase):
    """No database: the org-family guard, the family_version rule, the shown name's choice."""
    ent, book, same = base.Rules.ent, base.Rules.book, base.Rules.same

    def test_an_org_and_a_product_family_are_never_merged_automatically(self):
        org = self.ent("o", "Zentra", "org")
        fam = I.Ent("f", "model", "Vela", "vela", "family")
        kid = self.ent("k", "Vela 5", "model", fields=v("Vela", "5"))
        kid.level, kid.parent = "version", "f"
        alias = self.ent("z", "Zentra Vela", "org")            # Haiku typed it an org; it names the family
        book = self.book(org, fam, kid, alias)
        book.redirect["z"] = ("f", False)                        # the owner merged it into the family
        p = I.Pooled(*I.pair("o", "z"))
        d = I.decide_pair(book, p, {"handle"}, set(), None, None)
        self.assertEqual((d.tier, d.reason), ("queue", "type"))
        self.assertIn("org_family", d.reasons)
        d = I.decide_pair(book, p, set(), set(), self.same(0.97), "c")   # Haiku's `same` too
        self.assertEqual((d.tier, d.reason), ("queue", "type"))
        # two orgs sharing a word are not a family and an org: the rules decide as before
        other = self.ent("x", "Zentra Bank", "org")
        book = self.book(org, other)
        d = I.decide_pair(book, I.Pooled(*I.pair("o", "x")), set(), set(), self.same(0.95), "c")
        self.assertEqual(d.tier, "auto")

    def test_the_family_version_rule(self):
        a = self.ent("a", "Lyra 4", "model", fields=v("Lyra", "4"))
        b = self.ent("b", "Nova Lyra 4", "model", maker="Zentra", fields=v("Nova Lyra", "4"))
        c = self.ent("c", "Nova Lyra 4.1", "model", maker="Zentra", fields=v("Nova Lyra", "4.1"))
        fa, fb = I.Ent("fa", "model", "Lyra", "lyra", "family"), I.Ent("fb", "model", "Nova Lyra", "nova lyra", "family")
        for e, f in ((a, "fa"), (b, "fb"), (c, "fb")):
            e.level, e.parent = "version", f
        book = self.book(a, b, c, fa, fb)
        self.assertFalse(I.family_version(book, a, b))           # two families: not one yet
        book.redirect["fa"] = ("fb", True)
        self.assertTrue(I.family_version(book, a, b))
        self.assertFalse(I.family_version(book, a, c))           # another version: never
        d = I.decide_pair(book, I.Pooled(*I.pair("a", "c")), {"family_version"}, set(), None, None)
        self.assertEqual(d.tier, "apart")
        d = self.ent("d", "Lyra 4", "model", maker="Orbis", fields=v("Lyra", "4"))
        d.level, d.parent = "version", "fa"
        book.ents["d"] = d
        self.assertFalse(I.family_version(book, d, b))           # another maker

    def test_the_shown_name_and_type(self):
        book = self.book(self.ent("a", "Kip", "org"), self.ent("b", "Kip Marlow", "person"))
        book.types = {"a": {"org": 2}, "b": {"person": 2}}
        name, typ = R.choose(book, "a", ["a", "b"], {"a": [("Kip", 1, 1)], "b": [("Kip Marlow", 1, 2)]})
        self.assertEqual((name, typ), ("Kip Marlow", "person"))   # a person's full name, typed a person
        book = self.book(self.ent("a", "Dax Corran", "person"), self.ent("b", "Dax", "person"))
        name, _ = R.choose(book, "a", ["a", "b"], {"b": [("Dax", 3, 3)], "a": [("Dax Corran", 1, 1)]})
        self.assertIsNone(name)                                  # the full name (its own) over the first name alone
        book = self.book(self.ent("a", "Zentra Devs", "org"), self.ent("b", "Zentra", "org"))
        name, typ = R.choose(book, "a", ["a", "b"], {"a": [("Zentra Devs", 1, 9)], "b": [("Zentra", 4, 4)]})
        self.assertEqual((name, typ), ("Zentra", None))          # more sources write it


class Fixes(base._Db):
    def ent_named(self, name):
        self.cur.execute("SELECT id::text FROM mx_entities WHERE name = %s ORDER BY created_at LIMIT 1", (name,))
        return self.cur.fetchone()[0]

    def owner_same(self, a, b):
        I.queue_item(self.cur, kind="alias", a=I.pair(a, b)[0], b=I.pair(a, b)[1], proposal="same", reason="test",
                     conf=None, evidence={}, call_id=None, run_id=None)
        self.cur.execute("SELECT id::text FROM mx_entity_queue WHERE a = %s AND b = %s", I.pair(a, b))
        return entity_answers.answer(self.cur, self.cur.fetchone()[0], "same")

    def owner_apart(self, a, b):
        I.queue_item(self.cur, kind="alias", a=I.pair(a, b)[0], b=I.pair(a, b)[1], proposal="same", reason="test",
                     conf=None, evidence={}, call_id=None, run_id=None)
        self.cur.execute("SELECT id::text FROM mx_entity_queue WHERE a = %s AND b = %s", I.pair(a, b))
        return entity_answers.answer(self.cur, self.cur.fetchone()[0], "different")

    # ---- 1 ----------------------------------------------------------------------------------------------------

    def test_1_the_name_shown_is_the_one_most_sources_write_never_an_account_naming_itself(self):
        own = [self.post(n, T0 + n * H) for n in range(3)]           # the account's own posts name it
        self.cur.execute("UPDATE posts SET author = 'zentradevs' WHERE id = ANY(%s::uuid[])", (own,))
        for p in own:
            self.mentions(p, ("Zentra Devs", "org", "subject"))
        for n in (3, 4):
            self.mentions(self.post(n, T0 + D), ("Zentra", "org", "subject"))
        kip = [self.post(n, T0 + n * H) for n in range(4)]
        self.mentions(kip[0], ("Kip", "org", "mention", None, None, "@kip"))     # a handle: never counted
        self.mentions(kip[1], ("Kip", "org", "mention", None, None, "@kip"))
        self.mentions(kip[2], ("Kip Marlow", "person", "subject"))
        self.mentions(kip[3], ("Kip Marlow", "person", "subject"))
        self.stage()
        book = self.book()
        zd, z, k, km = (self.ent_named(x) for x in ("Zentra Devs", "Zentra", "Kip", "Kip Marlow"))
        I.merge(self.cur, book, zd, z, by="rule:handle", automatic=True)
        I.merge(self.cur, book, k, km, by="rule:handle", automatic=True)
        out = self.stage(since=self.since)
        self.assertGreaterEqual(out["shown"]["names"], 1)
        got = {i["id"]: i for i in entity_views.entity_list(self.cur, now=T0 + D)["items"]}
        book = self.book()
        self.assertEqual(got[book.root(z)]["name"], "Zentra")
        self.assertEqual((got[book.root(k)]["name"], got[book.root(k)]["type"]), ("Kip Marlow", "person"))
        self.assertEqual(book.ents[k].name, "Kip")                   # what it was made as stays (and decides identity)
        # the owner's rename wins and is never replaced
        self.cur.execute("UPDATE mx_entities SET shown_name = 'Zentra Inc', shown_by = 'owner' WHERE id = %s",
                         (book.root(z),))
        self.stage(full=True)
        self.assertEqual(self.book().label(z), "Zentra Inc")

    # ---- 2 ----------------------------------------------------------------------------------------------------

    def legacy_owner_same(self, a, b):
        """The owner's `same` as it was applied before 0164 A: the two roots merged, whatever their clusters."""
        x, y = I.pair(a, b)
        I.queue_item(self.cur, kind="alias", a=x, b=y, proposal="same", reason="test", conf=None, evidence={},
                     call_id=None, run_id=None)
        self.cur.execute("UPDATE mx_entity_queue SET answer = 'same', answered_at = now() WHERE a = %s AND b = %s "
                         "RETURNING id::text", (x, y))
        qid = self.cur.fetchone()[0]
        return I.merge(self.cur, self.book(), a, b, by="owner", automatic=False, queue_id=qid, evidence={"queue": qid})

    def _org_and_family(self):
        """The data as made before 0164 B: the account "Zentra Vela" linked (an org) before its family was known."""
        ps = [self.post(n, T0 + n * H) for n in range(4)]
        self.mentions(ps[0], ("Zentra", "org", "actor"))
        self.mentions(ps[2], ("Zentra Vela", "org", "mention"))
        self.stage()
        self.mentions(ps[1], ("Vela 5", "model", "subject", "Zentra", v("Vela", "5")))
        self.mentions(ps[3], ("Vela", "model", "subject"))
        self.stage()
        return [self.ent_named(x) for x in ("Zentra", "Vela", "Zentra Vela", "Vela 5")]

    def test_2_a_family_merged_into_an_org_is_cut_apart_by_an_undo_never_the_owners_merge(self):
        z, vela, zv, v5 = self._org_and_family()
        book = self.book()
        I.merge(self.cur, book, zv, z, by="rule:handle", automatic=True)     # how the wrong merge came
        self.legacy_owner_same(vela, zv)                                      # the owner: the same family
        book = self.book()
        self.assertEqual(book.root(vela), book.root(z))
        self.assertEqual(entity_views.entity_page(self.cur, v5)["entity"]["family"]["id"], book.root(z))
        out = self.stage(since=self.since)
        self.assertEqual(out["repair"]["org_family"]["undone"], 1)
        book = self.book()
        self.assertNotEqual(book.root(vela), book.root(z))
        self.assertEqual(book.root(vela), book.root(zv))                      # the owner's merge stands
        self.cur.execute("SELECT by, undone_by, evidence->'undone'->>'why', evidence->>'repointed_from' IS NOT NULL "
                         "FROM mx_entity_redirects ORDER BY at")
        rows = self.cur.fetchall()
        self.assertIn(("rule:handle", "repair", "org_family", False), rows)   # kept, undone, with why
        # the owner's redirect went root to root (Vela into Zentra's root): re-pointed between the owner's two names
        self.assertIn(("owner", "repair", "org_family", False), rows)
        self.assertIn(("owner", None, None, True), rows)
        self.assertEqual(len(rows), 3)                                       # nothing deleted
        page = entity_views.entity_page(self.cur, v5)
        self.assertEqual(page["entity"]["family"]["id"], book.root(vela))   # its family is the family again
        again = self.stage(full=True)                                       # and it does not come back
        self.assertEqual(again["repair"]["org_family"]["undone"], 0)
        self.assertNotEqual(self.book().root(vela), self.book().root(z))

    def test_2_a_cluster_the_owner_holds_together_is_left_as_it_is(self):
        z, vela, zv, v5 = self._org_and_family()
        self.legacy_owner_same(vela, z)
        out = self.stage(since=self.since)
        self.assertEqual((out["repair"]["org_family"]["undone"], out["repair"]["org_family"]["held"]), (0, 1))
        self.assertEqual(self.book().root(vela), self.book().root(z))

    def test_2_a_version_named_by_its_makers_name_gets_a_family_under_the_org(self):
        a, b, c = self.post(0, T0), self.post(1, T0 + H), self.post(2, T0 + 2 * H)
        self.mentions(a, ("Zentra", "org", "actor"))
        self.mentions(b, ("Zentra 5", "model", "subject", "Zentra", v("Zentra", "5")))
        self.mentions(c, ("Zentra 6", "model", "subject", "Zentra", v("Zentra", "6")))
        self.stage()
        book = self.book()
        z, z5, z6 = (self.ent_named(x) for x in ("Zentra", "Zentra 5", "Zentra 6"))
        fam = book.ents[z5].parent
        self.assertNotEqual(fam, z)                                         # never the org itself
        self.assertEqual((book.ents[fam].level, book.ents[fam].type, book.ents[fam].parent), ("family", "model", z))
        self.assertEqual(book.ents[z6].parent, fam)                          # one family for its versions
        self.assertEqual(book.root(self.entity_of(a)), z)                   # the org's mentions stay the org's
        # data made before the fix: a version whose parent is the org gets the family, the old value logged
        self.cur.execute("UPDATE mx_entities SET parent = %s WHERE id = %s", (z, z6))
        out = self.stage(since=self.since)
        self.assertEqual(out["repair"]["reparent"]["versions"], 1)
        self.assertEqual(self.book().ents[z6].parent, fam)
        self.cur.execute("SELECT kind, field, old, new FROM mx_entity_fixes WHERE entity_id = %s", (z6,))
        self.assertEqual(self.cur.fetchone(), ("org_family", "parent", z, fam))
        self.assertEqual(self.stage(since=self.since)["repair"]["reparent"]["versions"], 0)   # idempotent

    # ---- 3 ----------------------------------------------------------------------------------------------------

    def _brand(self):
        """Zentra's families all start with its brand Nova; Lyra states no maker; Orbis makes a Cora of its own."""
        rows = [("Nova Lyra 4", "Zentra", v("Nova Lyra", "4")), ("Nova Lyra 5", "Zentra", v("Nova Lyra", "5")),
                ("Nova Cora 1", "Zentra", v("Nova Cora", "1")), ("Nova Mira 2", "Zentra", v("Nova Mira", "2")),
                ("Lyra 4", None, v("Lyra", "4")), ("Lyra 5", None, v("Lyra", "5")), ("Lyra 4.1", None, v("Lyra", "4.1")),
                ("Zentra Mira 2", None, v("Zentra Mira", "2")),
                ("Cora 1", "Orbis", v("Cora", "1")),
                ("Nova Deck 1", "Zentra", v("Nova Deck", "1")), ("Zentra Deck 7", "Zentra", v("Zentra Deck", "7"))]
        for n, (name, maker, f) in enumerate(rows):
            p = self.post(n % 5, T0 + n * H)
            self.mentions(p, (name, "model", "subject", maker, f), ("Zentra", "org", "actor"))
        self.stage()
        return {name: self.ent_named(name) for name, _, _ in rows}

    def test_3_families_split_by_a_brand_or_maker_prefix_join_and_their_versions_follow(self):
        e = self._brand()
        book = self.book()
        fam = lambda name: book.root(book.ents[e[name]].parent)
        self.assertNotEqual(fam("Lyra 5"), fam("Nova Lyra 5"))
        self.owner_same(e["Lyra 5"], e["Nova Lyra 5"])          # the evidence a maker-less Lyra is Zentra's
        out = self.stage(since=self.since)
        book = self.book()
        fam = lambda name: book.root(book.ents[e[name]].parent)
        self.assertEqual(fam("Lyra 4"), fam("Nova Lyra 4"))     # brand Nova, the same maker by a merged version
        self.assertEqual(fam("Zentra Mira 2"), fam("Nova Mira 2"))   # the maker's own name in front
        self.assertNotEqual(fam("Cora 1"), fam("Nova Cora 1"))  # Orbis's Cora: another maker, never
        self.assertNotEqual(fam("Zentra Deck 7"), fam("Nova Deck 1"))   # two prefixes alone, no version both state
        self.assertEqual(book.root(e["Lyra 4"]), book.root(e["Nova Lyra 4"]))           # the same version follows
        self.assertEqual(book.root(e["Zentra Mira 2"]), book.root(e["Nova Mira 2"]))
        self.assertNotEqual(book.root(e["Lyra 4.1"]), book.root(e["Nova Lyra 4"]))      # another version: never
        self.assertGreaterEqual(out["repair"]["families"]["families"], 2)
        self.cur.execute("SELECT DISTINCT by FROM mx_entity_redirects WHERE undone_at IS NULL")
        self.assertTrue({"rule:family_prefix", "rule:family_version"} <= {r[0] for r in self.cur.fetchall()})
        # a new version of the joined family links and merges by the rule as it comes
        a, b = self.post(0, T0 + 2 * D), self.post(1, T0 + 2 * D)
        self.mentions(a, ("Lyra 6", "model", "subject", None, v("Lyra", "6")))
        self.mentions(b, ("Nova Lyra 6", "model", "subject", "Zentra", v("Nova Lyra", "6")))
        self.stage(since=self.since)
        book = self.book()
        self.assertEqual(book.root(self.entity_of(a)), book.root(self.entity_of(b)))

    def test_3_without_evidence_a_makerless_family_stays_and_the_owners_answers_win(self):
        e = self._brand()
        self.stage(since=self.since)
        book = self.book()
        fam = lambda name: book.root(book.ents[e[name]].parent)
        self.assertNotEqual(fam("Lyra 4"), fam("Nova Lyra 4"))  # no version of Lyra merged with Zentra's: unproven
        self.assertEqual(fam("Zentra Mira 2"), fam("Nova Mira 2"))
        # the owner undoes the family merge: a redirect undone, never made again
        self.cur.execute("SELECT id::text FROM mx_entity_redirects WHERE by = 'rule:family_prefix' AND undone_at IS NULL")
        rid = self.cur.fetchone()[0]
        entity_answers.undo(self.cur, rid)
        self.stage(full=True)
        book = self.book()
        fam = lambda name: book.root(book.ents[e[name]].parent)
        self.assertNotEqual(fam("Zentra Mira 2"), fam("Nova Mira 2"))
        self.cur.execute("SELECT count(*) FROM mx_entity_redirects WHERE id = %s AND undone_by = 'owner'", (rid,))
        self.assertEqual(self.cur.fetchone()[0], 1)

    # ---- 4 ----------------------------------------------------------------------------------------------------

    @mock.patch.object(R, "config", lambda: dict(_CONFIG(), suffix=True))   # shipped off until measured: the rule
    def test_4_an_org_and_its_suffixed_name_join_only_when_posts_say_so(self):
        for n in range(2):     # posts naming Zentra beside the thing "Zentra AI" makes
            self.mentions(self.post(n, T0 + n * H), ("Vela 5", "model", "subject", "Zentra AI", v("Vela", "5")),
                          ("Zentra", "org", "actor"))
        self.mentions(self.post(2, T0), ("Orba 2", "model", "subject", "Moonvale AI", v("Orba", "2")))
        self.mentions(self.post(3, T0), ("Moonvale", "org", "subject"))      # never beside Orba: another Moonvale?
        self.stage()
        out = self.stage(full=True)
        got = out["repair"]["suffix"]
        self.assertEqual((got["merged_suffix"], got["no_posts"]), (1, 1))
        book = self.book()
        z, zai = self.ent_named("Zentra"), self.ent_named("Zentra AI")
        self.assertEqual(book.root(z), book.root(zai))
        self.assertNotEqual(book.root(self.ent_named("Moonvale")), book.root(self.ent_named("Moonvale AI")))
        page = entity_views.entity_page(self.cur, self.ent_named("Vela 5"))
        self.assertEqual(page["entity"]["maker_id"], book.root(z))          # the maker shown is the org
        self.cur.execute("SELECT by, automatic, evidence->>'posts' FROM mx_entity_redirects WHERE by = 'rule:corp_suffix'")
        self.assertEqual(self.cur.fetchone(), ("rule:corp_suffix", True, "2"))

    def test_4_an_owner_kept_apart_pair_is_never_joined(self):
        for n in range(2):
            self.mentions(self.post(n, T0 + n * H), ("Vela 5", "model", "subject", "Zentra AI", v("Vela", "5")),
                          ("Zentra", "org", "actor"))
        self.stage()
        self.owner_apart(self.ent_named("Zentra"), self.ent_named("Zentra AI"))
        self.stage(full=True)
        book = self.book()
        self.assertNotEqual(book.root(self.ent_named("Zentra")), book.root(self.ent_named("Zentra AI")))


if __name__ == "__main__":
    unittest.main()
