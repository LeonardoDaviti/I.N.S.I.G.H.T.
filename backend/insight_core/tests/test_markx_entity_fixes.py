"""Mark X entity identity fixes (issue 0164), with invented names: the name and type shown by evidence (1), a product
family never merged into an org and a version's family never an org (2), families split by a maker or brand prefix
joined (3), an org and its suffixed name never joined by a rule (4: the suffix repair dropped, 0203); each with what it must
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


def base_on():
    """0230's switches on (entity_bands.json `families`: off until measured)."""
    return mock.patch.object(I, "families_on", lambda: {"maker": True, "stem": True, "namesakes": True})


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
        self.assertEqual(d.tier, "ask")                              # v10.18: Haiku decides a rule's mixed pair
        d = I.decide_pair(book, p, {"handle"}, set(), self.same(0.97), "c")
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


class _Cur:
    """A cursor for `merge` alone: the redirect's insert answers an id."""
    description = True

    def __init__(self):
        import contextlib
        self.connection = mock.Mock(transaction=contextlib.nullcontext)
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append((sql, params))

    def fetchone(self):
        return ("r1",)


class MergeKeeper(unittest.TestCase):
    """v10.35: a merge keeps the more general thing (a version or variant over its build), then the larger cluster,
    then the older; a merged name's stated maker stays the cluster's."""
    ent, book = base.Rules.ent, base.Rules.book

    def _mini_and_gguf(self):
        mini = self.ent("m", "Inkling 2 Mini", "model", maker="Thinking Machines", fields=v("Inkling", "2", "Mini"))
        mini.level, mini.parent, mini.first_seen = "variant", "f", T0
        gguf = self.ent("g", "Inkling-2-Mini-GGUF", "model", fields={**v("Inkling", "2", "Mini"), "build": "GGUF"})
        gguf.level, gguf.parent, gguf.first_seen = "checkpoint", "f", T0 - D   # older
        q4 = self.ent("q", "Inkling 2 Mini GGUF Q4", "model", fields={**v("Inkling", "2", "Mini"), "build": "GGUF"})
        q4.level, q4.parent = "checkpoint", "f"
        tm = self.ent("o", "Thinking Machines", "org")
        fam = I.Ent("f", "model", "Inkling", "inkling", "family", maker="Thinking Machines")
        book = self.book(mini, gguf, q4, tm, fam)
        book.redirect["q"] = ("g", True)        # the GGUF's cluster is the larger, and it is older
        return book

    def test_the_variant_keeps_over_its_gguf_build_whatever_the_clusters(self):
        for a, b in (("m", "g"), ("g", "m"), ("q", "m")):
            book = self._mini_and_gguf()
            cur = _Cur()
            self.assertEqual(I.merge(cur, book, a, b, by="owner", automatic=False), "r1")
            self.assertEqual(book.root("g"), "m")
            self.assertEqual(book.root("q"), "m")
            self.assertEqual(cur.sql[-1][1][:2], ("g", "m"))          # from the GGUF, into Mini
            view = entity_views._ent_view(book, "m")
            self.assertEqual((view["name"], view["level"], view["build"], view["maker"], view["maker_id"]),
                             ("Inkling 2 Mini", "variant", None, "Thinking Machines", "o"))

    def test_a_name_stating_a_build_is_the_specific_side_at_any_level(self):
        a = self.ent("a", "Lyra 4", "model", fields=v("Lyra", "4"))
        b = self.ent("b", "Lyra 4 NVFP4", "model", fields={**v("Lyra", "4"), "build": "NVFP4"})
        a.level = b.level = "version"
        b.first_seen, a.first_seen = T0 - D, T0
        book = self.book(a, b)
        I.merge(_Cur(), book, "a", "b", by="owner", automatic=False)
        self.assertEqual(book.root("b"), "a")
        self.assertTrue(I.is_build(b) and not I.is_build(a))

    def test_without_a_build_the_larger_cluster_then_the_older_keeps_as_before(self):
        a, b, c = (self.ent(x, n, "model") for x, n in (("a", "Vela"), ("b", "Vela AI model"), ("c", "Vela M")))
        a.first_seen, b.first_seen, c.first_seen = T0, T0 - D, T0
        book = self.book(a, b, c)
        book.redirect["c"] = ("a", True)
        I.merge(_Cur(), book, "a", "b", by="owner", automatic=False)
        self.assertEqual(book.root("b"), "a")                          # the larger
        book = self.book(a, b)
        I.merge(_Cur(), book, "a", "b", by="owner", automatic=False)
        self.assertEqual(book.root("a"), "b")                          # the older

    def test_the_kept_root_shows_the_maker_a_merged_name_stated(self):
        a = self.ent("a", "Vela", "model", maker="Zentra")
        b = self.ent("b", "Vela model", "model")
        b.first_seen, a.first_seen = T0 - D, T0
        z = self.ent("z", "Zentra", "org")
        book = self.book(a, b, z)
        I.merge(_Cur(), book, "a", "b", by="owner", automatic=False)
        self.assertEqual(book.root("a"), "b")                          # the older keeps, stating no maker
        self.assertEqual(I.cluster_maker(book, "b"), "Zentra")
        view = entity_views._ent_view(book, "b")
        self.assertEqual((view["maker"], view["maker_id"]), ("Zentra", "z"))
        self.assertEqual(entity_views._ent_view(book, "a")["maker"], "Zentra")   # a member: its own


class Tick:
    """A clock that moves a second each time it is read (entity_repair's `time`): a sweep given a deadline 3.5 s
    ahead does exactly one step (v10.24, 0221: a step starts only when the last one's seconds are left)."""

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        self.t += 1.0
        return self.t

    def one_step(self):
        return self.t + 3.5


class Fixes(base._Db):
    def linked(self, **kw):
        """A run whose repairs are off: the data as linked before a repair could see it (v10.24, 0221: the repairs
        run after the linking, in the same run; these fixtures are the data they then find)."""
        off = {k: False for k in R.STEPS}
        with mock.patch.object(R, "config", lambda: {**off, "shown": True}):
            return self.stage(**kw)

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
        self.linked()
        self.mentions(ps[1], ("Vela 5", "model", "subject", "Zentra", v("Vela", "5")))
        self.mentions(ps[3], ("Vela", "model", "subject"))
        self.linked()
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
        self.linked()
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

    def test_4_an_org_and_its_suffixed_name_are_never_joined_by_a_rule(self):
        for n in range(2):
            self.mentions(self.post(n, T0 + n * H), ("Vela 5", "model", "subject", "Zentra AI", v("Vela", "5")),
                          ("Zentra", "org", "actor"))
        self.stage()
        self.owner_apart(self.ent_named("Zentra"), self.ent_named("Zentra AI"))
        self.stage(full=True)
        book = self.book()
        self.assertNotEqual(book.root(self.ent_named("Zentra")), book.root(self.ent_named("Zentra AI")))

    # ---- 0218: the shown names' sweep resumes ----------------------------------------------------------------------

    def test_the_shown_sweep_over_every_cluster_resumes_where_it_stopped_single_names_too(self):
        """A sweep with the time for one step does one step (the next clusters of several names and the single names
        before them) and the next run resumes after it: every cluster once, the single names never all at a sweep's
        start; the same names and types as a sweep without a deadline. v10.24 (0221): past its deadline, none."""
        names = ["Kip", "Kip Marlow", "Zentra", "Zentra Devs", "Orbis", "Lumen", "Tarn", "Vesk", "Quill", "Brae"]
        for n, name in enumerate(names):
            self.mentions(self.post(n % 3, T0 + n * H), (name, "org" if n % 3 else "person", "subject"))
        self.stage()
        ids = sorted(I.run_book(self.cur).ids())
        # the first cluster of two names the smallest ids, the second the largest: every single name between them
        for a, b in ((ids[0], ids[1]), (ids[-2], ids[-1])):
            I.merge(self.cur, self.book(), a, b, by="rule:handle", automatic=True)
        self.cur.execute("UPDATE mx_entities SET shown_name = NULL, shown_type = 'event', shown_by = 'evidence'")
        from insight_core.markx import schemas
        guide = schemas.mention_guides()
        roots = sorted(r for r in I.run_book(self.cur).ids() if self.book().root(r) == r)
        self.cur.execute("SAVEPOINT sweep")
        whole = R.shown(self.cur, I.run_book(self.cur), guide, roots=None, after=None, deadline=None)
        self.cur.execute("SELECT id::text, shown_name, shown_type FROM mx_entities ORDER BY id")
        want = self.cur.fetchall()
        self.cur.execute("ROLLBACK TO SAVEPOINT sweep")
        self.assertEqual((whole["clusters"], whole["done"]), (len(roots), True))
        clock = Tick()
        with mock.patch.object(R, "SHOWN_CHUNK", 1), mock.patch.object(R, "time", clock):
            after, steps = None, []
            while True:
                got = R.shown(self.cur, I.run_book(self.cur), guide, roots=None, after=after,
                              deadline=clock.one_step())
                steps.append((got["clusters"], sum(1 for r in roots if (after is None or r > after)
                                                   and (got["done"] or r <= got["after"]))))
                if got["done"]:
                    break
                self.assertGreater(got["after"], after or "")
                after = got["after"]
        self.assertEqual(len(steps), 2)                          # a step for each of the two clusters of two names
        self.assertEqual(steps[0], (1, 1))                       # the first: its cluster alone, no single name yet
        self.assertEqual(steps[1], (len(roots) - 1,) * 2)        # resumed: every cluster after it, single names too
        self.cur.execute("SELECT id::text, shown_name, shown_type FROM mx_entities ORDER BY id")
        self.assertEqual(self.cur.fetchall(), want)


    def test_a_sweep_of_single_names_steps_and_resumes_too(self):
        """0218: no cluster of several names (the server-sized copy has none): SHOWN_SINGLES single names a step."""
        from insight_core.markx import schemas
        for n, name in enumerate(["Kip", "Zentra", "Orbis", "Lumen", "Tarn", "Vesk", "Quill"]):
            self.mentions(self.post(n % 3, T0 + n * H), (name, "org", "subject"))
        self.stage()
        roots = sorted(I.run_book(self.cur).ids())
        after, steps = None, []
        clock = Tick()
        with mock.patch.object(R, "SHOWN_SINGLES", 3), mock.patch.object(R, "time", clock):
            while True:
                got = R.shown(self.cur, I.run_book(self.cur), schemas.mention_guides(), roots=None, after=after,
                              deadline=clock.one_step())
                steps.append(got["clusters"])
                if got["done"]:
                    break
                after = got["after"]
                self.assertEqual(after, roots[sum(steps) - 1])
        self.assertEqual(steps, [3, 3, 1])

    # ---- 4c: a cluster rooted on a build -----------------------------------------------------------------------

    def _rooted_on_a_build(self):
        """The data as merged before v10.35: "Inkling" redirected into "Thinking Machines Inkling", a 975B GGUF
        checkpoint (the older side kept), with a quantisation already under the checkpoint."""
        ps = [self.post(n, T0 + n * H) for n in range(3)]
        self.mentions(ps[0], ("Inkling", "model", "subject"))
        self.mentions(ps[1], ("Thinking Machines Inkling", "model", "subject"))
        self.mentions(ps[2], ("Inkling Q2 quant", "model", "subject"))
        self.linked()
        ink, tmi, q2 = (self.ent_named(x) for x in ("Inkling", "Thinking Machines Inkling", "Inkling Q2 quant"))
        self.cur.execute("UPDATE mx_entities SET level = 'checkpoint', build = 'Dynamic 1-bit GGUF', size = '975B' "
                         "WHERE id = %s", (tmi,))
        self.cur.execute("UPDATE mx_entities SET level = 'checkpoint', build = 'Q2' WHERE id = %s", (q2,))
        for f in (ink, q2):
            self.cur.execute("""INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic, evidence)
                                VALUES (%s, %s, 'rule:maker_prefix', true, '{"rules": ["maker_prefix"]}')""", (f, tmi))
        return ink, tmi, q2

    def test_4c_a_cluster_rooted_on_a_build_re_roots_on_its_general_name_its_facts_with_it(self):
        from insight_core.markx import entity_facts
        ink, tmi, q2 = self._rooted_on_a_build()
        entity_facts.write(self.cur, tmi, by="haiku", kind="model", what="Thinking Machines' language model")
        out = self.stage(since=self.since)
        self.assertEqual({k: out["repair"]["reroot"][k] for k in ("clusters", "rerooted", "redirects", "facts")},
                         {"clusters": 1, "rerooted": 1, "redirects": 1, "facts": 1})
        book = self.book()
        self.assertEqual((book.root(tmi), book.root(q2), book.root(ink)), (ink, ink, ink))   # one thing, Inkling on top
        self.cur.execute("SELECT from_id::text, to_id::text, by, automatic, undone_by, evidence->'undone'->>'why', "
                         "evidence->>'rerooted_from' IS NOT NULL, evidence->'rules' FROM mx_entity_redirects ORDER BY at, id")
        rows = self.cur.fetchall()
        self.assertIn((ink, tmi, "rule:maker_prefix", True, "repair", "reroot", False, ["maker_prefix"]), rows)
        self.assertIn((tmi, ink, "rule:maker_prefix", True, None, None, True, ["maker_prefix"]), rows)
        self.assertEqual(len(rows), 3)                                      # nothing deleted, the quant left as it was
        got = entity_facts.read(self.cur, [ink, tmi], force=True)
        self.assertEqual(got[ink].what, "Thinking Machines' language model")   # the facts go with the root
        self.assertIn(tmi, got)                                              # and stay with the build too
        again = self.stage(full=True)
        self.assertEqual(again["repair"]["reroot"]["rerooted"], 0)        # idempotent

    def test_4c_the_owners_merge_stays_the_owners_and_a_rename_or_an_owners_shown_name_is_left(self):
        ink, tmi, q2 = self._rooted_on_a_build()
        self.cur.execute("UPDATE mx_entity_redirects SET undone_at = now(), undone_by = 'test' WHERE from_id = %s", (ink,))
        x, y = I.pair(ink, tmi)
        I.queue_item(self.cur, kind="alias", a=x, b=y, proposal="same", reason="test", conf=None, evidence={},
                     call_id=None, run_id=None)
        self.cur.execute("UPDATE mx_entity_queue SET answer = 'same', answered_at = now() WHERE a = %s AND b = %s "
                         "RETURNING id::text", (x, y))
        qid = self.cur.fetchone()[0]
        self.cur.execute("""INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic, queue_id, evidence)
                            VALUES (%s, %s, 'owner', false, %s, '{}')""", (ink, tmi, qid))
        self.cur.execute("UPDATE mx_entities SET shown_name = 'Inkling 975B', shown_by = 'owner' WHERE id = %s", (tmi,))
        out = R.repair(self.cur, I.run_book(self.cur), run_id=None, full=False)
        self.assertEqual((out["reroot"]["rerooted"], out["reroot"]["skip_owner_shown"]), (0, 1))   # the owner's name
        self.cur.execute("UPDATE mx_entities SET shown_name = NULL, shown_by = NULL WHERE id = %s", (tmi,))
        out = R.repair(self.cur, I.run_book(self.cur), run_id=None, full=False)
        self.assertEqual(out["reroot"]["rerooted"], 1)
        self.assertEqual(self.book().root(tmi), ink)
        self.cur.execute("SELECT by, automatic, queue_id::text FROM mx_entity_redirects WHERE from_id = %s "
                         "AND undone_at IS NULL", (tmi,))
        self.assertEqual(self.cur.fetchone(), ("owner", False, qid))       # the owner's answer, the keeper changed
        # a rename goes the older name into the newer: never turned round
        self.cur.execute("UPDATE mx_entity_redirects SET undone_at = now(), undone_by = 'test' WHERE from_id = %s", (tmi,))
        self.cur.execute("""INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic, evidence, kind)
                            VALUES (%s, %s, 'owner', false, '{}', 'rename')""", (ink, tmi))
        out = R.repair(self.cur, I.run_book(self.cur), run_id=None, full=False)
        self.assertEqual((out["reroot"]["rerooted"], out["reroot"]["skip_rename"]), (0, 1))
        self.assertEqual(self.book().root(ink), tmi)

    def test_the_repairs_go_a_step_at_a_time_and_the_next_run_resumes_at_the_step_left(self):
        """v10.24 (0221): the repairs run with what the stage's budget has left; a step starts only when the seconds
        it took the last time are left, and the next run begins at the first step this one could not start."""
        z, vela, zv, v5 = self._org_and_family()
        took = {"org_family": 1.0, "product_accounts": 1.0, "reparent": 5.0, "families": 1.0, "family_home": 1.0,
                "names": 1.0, "levels": 1.0, "reroot": 1.0}
        clock = Tick()
        with mock.patch.object(R, "time", clock):
            first = R.repair(self.cur, I.run_book(self.cur), run_id=None, full=False, deadline=clock.t + 6.5,
                             last={"took": took})
        self.assertEqual((first["done"], first["next"]), (False, "reparent"))   # two steps fitted, not the third
        self.assertEqual(set(first) & set(R.STEPS), {"org_family", "product_accounts"})
        self.assertEqual(first["product_accounts"]["merged"], 1)
        self.assertEqual(set(first["took"]), set(R.STEPS))                       # the steps not run keep their seconds
        second = R.repair(self.cur, I.run_book(self.cur), run_id=None, full=False, deadline=None, last=first)
        self.assertEqual((second["done"], second["next"]), (True, None))
        self.assertEqual(set(second) & set(R.STEPS), {"reparent", "families", "family_home", "names", "levels", "reroot"})   # resumed where the first stopped
        third = R.repair(self.cur, I.run_book(self.cur), run_id=None, full=False, deadline=None, last=second)
        self.assertEqual(set(third) & set(R.STEPS), set(R.STEPS))                # done: a new round from the first
        self.assertEqual(third["product_accounts"]["merged"], 0)                 # idempotent

    def test_the_full_pass_leaves_the_steps_after_it_what_they_took_the_last_time(self):
        """v10.24 (0221): a full pass half done lasts days on the server; it stops early by what the repairs' next
        step, a step of the shown names and the invariants took in the last run (a guess for what never ran), and
        each of those leaves the ones after it theirs."""
        from insight_core.markx import entity_stage, repo
        self.assertEqual(entity_stage.after_pass(self.cur), (entity_stage.REPAIR_GUESS, entity_stage.SHOWN_GUESS,
                                                             entity_stage.INVARIANTS_GUESS))
        run = repo.start_run(self.cur, code_version="test", config={})
        repo.finish_run(self.cur, run, counts={"entities": {
            "repair": {"done": False, "next": "reparent", "took": {"org_family": 9.0, "reparent": 4.0}},
            "shown": {"done": False, "after": "x", "steps": 3, "seconds": 6.0},
            "invariants": {"family_org": {"count": 0}, "seconds": 0.5}}})
        self.assertEqual(entity_stage.after_pass(self.cur), (4.0, 2.0, 0.5))

    # ---- 0230: a family is its maker's, and its stem ------------------------------------------------------------

    def _orbit(self):
        """Vantor's family Orbit (three versions and a variant, Orbit Argon) as linked before 0230."""
        ps = [self.post(n % 5, T0 + n * H) for n in range(4)]
        for p, (name, f) in zip(ps, [("Orbit 3", v("Orbit", "3")), ("Orbit 4", v("Orbit", "4")),
                                     ("Orbit 5", v("Orbit", "5")), ("Orbit Argon", v("Orbit", None, "Argon"))]):
            self.mentions(p, (name, "model", "subject", "Vantor", f))
        self.linked()
        return {x: self.ent_named(x) for x in ("Orbit 3", "Orbit 4", "Orbit 5", "Orbit Argon")}

    def edges(self):
        self.cur.execute("""SELECT a::text, b::text, relation FROM mx_connections WHERE a_kind = 'entity'
                             AND rule = %s AND valid_to IS NULL""", (I.FAMILY_RULE,))
        return set(self.cur.fetchall())

    @base_on()
    def test_0230_another_makers_thing_is_based_on_the_family_never_its_member(self):
        got = self._orbit()
        fam = self.book().ents[got["Orbit 3"]].parent
        p = self.post(0, T0 + 9 * H)
        self.mentions(p, ("Orbit 4 Abliterated GGUF", "model", "subject", "Kestrel", v("Orbit", "4", "Abliterated GGUF")),
                      ("Orbit 6", "model", "mention", "Vantor AI", v("Orbit", "6")))
        self.linked(since=self.since)
        book = self.book()
        tune, six = self.entity_of(p), self.entity_of(p, 1)
        self.assertEqual(book.ents[six].parent, fam)                            # its maker's ("Vantor AI" is Vantor)
        e = book.ents[tune]
        self.assertEqual((e.level, book.ents[e.parent].name), ("thing", "Kestrel"))   # a thing of its own maker
        self.assertEqual(self.edges(), {(tune, fam, "based_on")})
        page = entity_views.entity_page(self.cur, tune, now=T0 + 2 * D)
        self.assertEqual([(r["relation"], r["direction"], r["other"]["id"]) for r in page["relations"]],
                         [("based_on", "out", fam)])

    def test_0230_off_by_default_nothing_changes(self):
        got = self._orbit()
        fam = self.book().ents[got["Orbit 3"]].parent
        p = self.post(0, T0 + 9 * H)
        self.mentions(p, ("Orbit 4 Abliterated GGUF", "model", "subject", "Kestrel", v("Orbit", "4", "Abliterated GGUF")))
        self.linked(since=self.since)
        self.assertEqual(self.book().ents[self.entity_of(p)].parent, fam)       # a member, as before 0230
        self.assertEqual(self.edges(), set())
        self.assertTrue(self.stage(since=self.since)["repair"]["family_home"]["off"])

    @base_on()
    def test_0230_a_family_with_too_few_stated_makers_keeps_its_members(self):
        a, b = self.post(0, T0), self.post(1, T0 + H)
        self.mentions(a, ("Lumo 2", "model", "subject", "Vantor", v("Lumo", "2")))
        self.mentions(b, ("Lumo 3", "model", "subject", "Kestrel", v("Lumo", "3")))
        self.linked()
        book = self.book()
        self.assertEqual(book.ents[self.entity_of(b)].parent, book.ents[self.entity_of(a)].parent)
        self.assertEqual(self.edges(), set())

    @base_on()
    def test_0230_a_members_name_is_never_a_family(self):
        got = self._orbit()
        fam = self.book().ents[got["Orbit 3"]].parent
        p = self.post(0, T0 + 9 * H)
        self.mentions(p, ("Orbit Argon 2", "model", "subject", "Vantor", v("Orbit Argon", "2")))
        self.linked(since=self.since)
        book = self.book()
        self.assertEqual(book.ents[self.entity_of(p)].parent, fam)              # the stem, not the variant Orbit Argon

    @base_on()
    def test_0230_the_repair_rehomes_what_was_linked_before(self):
        got = self._orbit()
        fam = self.book().ents[got["Orbit 3"]].parent
        p, q = self.post(0, T0 + 9 * H), self.post(1, T0 + 10 * H)
        self.mentions(p, ("Orbit Argon 2", "model", "subject", "Vantor", v("Orbit Argon", "2")))
        self.mentions(q, ("Orbit 5 Uncensored", "model", "subject", "Kestrel", v("Orbit", "5", "Uncensored")))
        self.linked(since=self.since)
        a2, tune = self.entity_of(p), self.entity_of(q)
        # as linked before 0230: under the variant, and under the family
        self.cur.execute("UPDATE mx_entities SET parent = %s, level = 'version' WHERE id = %s", (got["Orbit Argon"], a2))
        self.cur.execute("UPDATE mx_entities SET parent = %s, level = 'variant' WHERE id = %s", (fam, tune))
        self.cur.execute("DELETE FROM mx_connections WHERE rule = %s", (I.FAMILY_RULE,))
        out = self.stage(since=self.since)
        self.assertEqual(out["repair"]["family_home"], {"stem": 1, "other_maker": 1, "edges": 1})
        book = self.book()
        self.assertEqual(book.ents[a2].parent, fam)
        self.assertEqual(book.ents[tune].level, "thing")
        self.assertEqual(self.edges(), {(tune, fam, "based_on")})
        self.cur.execute("SELECT kind, entity_id::text, old FROM mx_entity_fixes WHERE kind LIKE 'family_%%' ORDER BY kind")
        self.assertEqual(self.cur.fetchall(), [("family_maker", tune, {"level": "variant", "parent": fam}),
                                               ("family_stem", a2, got["Orbit Argon"])])
        self.assertEqual(self.stage(since=self.since)["repair"]["family_home"],
                         {"stem": 0, "other_maker": 0, "edges": 0})              # idempotent


class Namesakes(unittest.TestCase):
    """0230 (no database): the collision question's sample and when it is asked again."""

    def test_the_sample_shows_the_suspects_and_the_oldest_post_first(self):
        from datetime import datetime, timezone
        at = lambda y: datetime(y, 6, 1, tzinfo=timezone.utc)   # noqa: E731
        ms = [(f"p{k}", "Orbit", "model", mk, at(2024 + k % 3)) for k, mk in enumerate(
            ["Vantor", "Vantor AI", "Vantor Labs", "Vantor Cloud", "Vantor Inc", "Vantor Research", "Vantor X", "VT"] * 2)]
        ms += [("old", "Orbit exchange", "org", None, at(2018)), ("odd", "Orbit", "model", "Kestrel", at(2025))]
        e = I.Ent("e", "model", "Orbit", "orbit", maker="Vantor")
        pick = I.collide_sample("e", ms, I.suspect_mention(I.Book(), e))
        self.assertIn("old", [m[0] for m in pick])                       # the oldest, an org: another thing?
        self.assertIn("odd", [m[0] for m in pick])                       # another maker
        self.assertLessEqual(len(pick), I.COLLIDE_MENTIONS)
        self.assertEqual(I.asked_from('NAME "Orbit"\n1. written "Orbit" | type org | maker guess none\n'
                                      '   [site, 2018-09-11] "A title" … text'), 2018)


if __name__ == "__main__":
    unittest.main()
