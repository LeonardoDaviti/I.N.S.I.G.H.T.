"""Mark X entity guards (issue 0164 A-C), with invented names: the owner's `same` never joins a product family to an
org blindly (A: only the two names join, the automatic link that dragged one in undone; the owner's own earlier merge
is never undone: the item stays open with a message), a product account is not an org (B: "Zentra Vela" typed an
org is its family's, "Zentra Labs" stays an org), and the invariant counted each run (C: 0 on a clean book, more on
the shape seen on the server)."""
from __future__ import annotations

import unittest

from insight_core.markx import entity_answers, entity_repair as R, entity_stage, entity_views, identity as I
from insight_core.tests import test_markx_entities as base
from insight_core.tests import test_markx_entity_fixes as F

v = F.v

T0, H, D = base.T0, base.H, base.D


def _book(*ents):
    b = I.Book()
    for e in ents:
        b.ents[e.id] = e
        b.alias[e.key] = e.id
    return b


def _shape():
    """The server's shape: the maker org (Zentra, Zentra AI), its family Vela (Vela 5 its version, maker Zentra AI)
    and the family's account "Zentra Vela", typed an org."""
    ent = base.Rules.ent
    z, zai = ent(None, "z", "Zentra", "org"), ent(None, "zai", "Zentra AI", "org")
    vela = I.Ent("f", "model", "Vela", "vela", "family", maker="Zentra AI")
    v5 = ent(None, "v5", "Vela 5", "model", maker="Zentra AI", fields=v("Vela", "5"))
    v5.level, v5.parent = "version", "f"
    zv = ent(None, "zv", "Zentra Vela", "org")
    labs = ent(None, "zl", "Zentra Labs", "org")
    other = ent(None, "ov", "Orbis Vela", "org")
    return _book(z, zai, vela, v5, zv, labs, other)


class Guards(unittest.TestCase):
    """No database."""

    def test_b_a_product_account_is_its_familys_never_an_org(self):
        book = _shape()
        self.assertEqual(book.product_of("zentra vela"), "f")
        self.assertIsNone(book.product_of("zentra labs"))        # an org's word at the end: an org
        self.assertIsNone(book.product_of("orbis vela"))         # another maker in front: not Vela's account
        book.redirect["zai"] = ("z", True)
        self.assertEqual(book.product_of("zentra vela"), "f")    # the maker's cluster's names count too
        book.redirect["zv"] = ("z", True)                         # merged into the org by a handle rule
        fam, org = book.sides(book.cluster("z"))
        self.assertEqual((fam, org), ({"zv"}, {"z", "zai"}))     # the account is on the family side wherever it is
        book.redirect["zl"] = ("z", True)
        self.assertNotIn("zl", book.sides(book.cluster("z"))[0])   # "Zentra Labs" stays on the org side
        self.assertEqual(I.product_type(book, "f"), "model")

    def test_c_the_invariant_counts_clusters_holding_a_family_and_an_org(self):
        book = _shape()
        book.redirect["zai"] = ("z", True)
        book.redirect["zl"] = ("z", True)
        self.assertEqual(R.family_org(book)["count"], 0)          # a clean book
        book.redirect["zv"] = ("z", True)
        book.redirect["f"] = ("z", False)                         # the server's shape
        got = R.family_org(book)
        self.assertEqual(got["count"], 1)
        self.assertEqual(got["clusters"][0]["family"], ["Vela", "Zentra Vela"])
        self.assertEqual(got["clusters"][0]["org"], ["Zentra", "Zentra AI", "Zentra Labs"])

    def test_a_the_join_plan(self):
        book = _shape()
        book.redirect["zai"] = ("z", True)
        self.assertEqual(entity_answers.join_plan(book, "zl", "zai"), {"mixes": False})   # two orgs: as ever
        book.redirect["zv"] = ("z", True)
        plan = entity_answers.join_plan(book, "f", "zv")
        self.assertEqual((plan["mixes"], plan["kind"]), (True, "family"))
        self.assertEqual(plan["detach"], [("zv", ["z", "zai", "zv"], ["z", "zai"])])
        self.assertIsNone(entity_answers.join_plan(book, "f", "z")["kind"])   # a family and an org: the owner's choice


class OwnerAnswers(base._Db):
    """A, B and C on a test database."""
    ent_named, legacy_owner_same, _org_and_family = F.Fixes.ent_named, F.Fixes.legacy_owner_same, F.Fixes._org_and_family

    def _server_shape(self):
        """Linked as on the server: the account "Zentra Vela" (an org) before its family was known, then merged into
        the maker org by a handle rule; the family Vela and its version."""
        ps = [self.post(n, T0 + n * H) for n in range(5)]
        self.mentions(ps[0], ("Zentra", "org", "actor"))
        self.mentions(ps[1], ("Zentra AI", "org", "actor"))
        self.mentions(ps[2], ("Zentra Vela", "org", "mention", None, None, "@zentravela"))
        self.stage()
        self.mentions(ps[3], ("Vela 5", "model", "subject", "Zentra AI", v("Vela", "5")))
        self.mentions(ps[4], ("Vela", "model", "subject"))
        self.stage()
        z, zai, zv, vela = (self.ent_named(x) for x in ("Zentra", "Zentra AI", "Zentra Vela", "Vela"))
        book = self.book()
        I.merge(self.cur, book, zai, z, by="rule:squash", automatic=True)
        I.merge(self.cur, book, zv, z, by="rule:handle", automatic=True)
        return z, zai, zv, vela

    def _item(self, a, b):
        x, y = I.pair(a, b)
        I.queue_item(self.cur, kind="alias", a=x, b=y, proposal="same", reason="type", conf=0.97, evidence={},
                     call_id=None, run_id=None)
        self.cur.execute("SELECT id::text FROM mx_entity_queue WHERE a = %s AND b = %s AND answer IS NULL", (x, y))
        return self.cur.fetchone()[0]

    def _redirects(self):
        self.cur.execute("SELECT by, undone_by, evidence->'undone'->>'why' FROM mx_entity_redirects ORDER BY at, id")
        return self.cur.fetchall()

    def test_a_same_joins_only_the_two_names_and_undoes_the_automatic_link(self):
        z, zai, zv, vela = self._server_shape()
        qid = self._item(vela, zv)
        item = next(i for i in entity_views.queue(self.cur)["open"] if i["id"] == qid)
        side = item["a"] if item["a"]["id"] == zv else item["b"]
        self.assertEqual(side["group"]["root"], self.book().root(z))         # the card shows the group it is in
        self.assertTrue({"Zentra", "Zentra AI", "Zentra Vela"} <= set(side["group"]["names"]))
        self.assertEqual(side["group"]["sides"], {"family": ["Zentra Vela"], "org": ["Zentra", "Zentra AI"]})
        self.assertEqual(item["join"]["only_names"], True)
        self.assertFalse(item["join"]["needs_choice"])
        self.assertEqual(item["join"]["apart"][0]["from"], "Vela")
        got = entity_answers.answer(self.cur, qid, "same")
        self.assertEqual(got["result"], "joined_names")
        self.assertEqual(len(got["detached"]), 1)
        book = self.book()
        self.assertEqual(book.root(vela), book.root(zv))                       # the owner's answer holds
        self.assertNotEqual(book.root(vela), book.root(z))                     # the family stays out of the org
        self.assertEqual(book.root(zai), book.root(z))                         # the org keeps its own names
        rows = self._redirects()
        self.assertIn(("rule:handle", "owner_answer", "owner_answer"), rows)    # undone, kept, with why
        self.assertIn(("owner", None, None), rows)
        self.assertEqual(len(rows), 3)                                         # nothing deleted
        self.cur.execute("SELECT answer FROM mx_entity_queue WHERE id = %s", (qid,))
        self.assertEqual(self.cur.fetchone()[0], "same")
        out = self.stage(since=self.since)                                     # the run finds nothing to cut
        self.assertEqual(out["repair"]["org_family"]["undone"], 0)
        self.assertEqual(out["invariants"]["family_org"]["count"], 0)

    def test_a_the_owners_own_earlier_merge_is_never_undone_the_item_waits(self):
        z, zai, zv, vela = self._server_shape()
        self.cur.execute("UPDATE mx_entity_redirects SET undone_at = now(), undone_by = 'test' WHERE by = 'rule:handle'")
        self.legacy_owner_same(zv, z)                                          # the owner joined them before
        qid = self._item(vela, zv)
        item = next(i for i in entity_views.queue(self.cur)["open"] if i["id"] == qid)
        self.assertTrue(item["join"]["needs_choice"])
        before = self._redirects()
        got = entity_answers.answer(self.cur, qid, "same")
        self.assertEqual(got["result"], "needs_choice")
        self.assertIn("Zentra Vela", got["message"])
        self.assertEqual(self._redirects(), before)                            # nothing written
        self.cur.execute("SELECT answer, closed_at FROM mx_entity_queue WHERE id = %s", (qid,))
        self.assertEqual(self.cur.fetchone(), (None, None))                    # the item stays open
        book = self.book()
        self.assertNotEqual(book.root(vela), book.root(z))

    def test_a_a_same_that_mixes_nothing_merges_the_roots_as_ever(self):
        z, zai, zv, vela = self._server_shape()
        self.mentions(self.post(0, T0 + D), ("Zentra Inc", "org", "actor"))
        self.stage(since=self.since)
        qid = self._item(self.ent_named("Zentra Inc"), zai)
        got = entity_answers.answer(self.cur, qid, "same")
        self.assertNotIn("result", got)
        self.assertEqual(self.book().root(self.ent_named("Zentra Inc")), self.book().root(z))

    def test_b_a_new_product_account_is_typed_and_joined_as_its_family_an_org_account_stays_an_org(self):
        ps = [self.post(n, T0 + n * H) for n in range(3)]
        self.mentions(ps[0], ("Zentra", "org", "actor"))
        self.mentions(ps[1], ("Vela 5", "model", "subject", "Zentra", v("Vela", "5")))
        self.mentions(ps[2], ("Vela", "model", "subject"))
        self.stage()
        a, b = self.post(3, T0 + D), self.post(4, T0 + D)
        self.mentions(a, ("Zentra Vela", "org", "mention", None, None, "@zentravela"))
        self.mentions(b, ("Zentra Labs", "org", "actor", None, None, "@zentralabs"))
        self.stage(since=self.since)
        book = self.book()
        zv, zl, vela, z = (self.ent_named(x) for x in ("Zentra Vela", "Zentra Labs", "Vela", "Zentra"))
        self.assertEqual(book.ents[zv].type, "model")                          # the family's type, not org
        self.assertEqual(book.root(zv), book.root(vela))                       # it joins the family
        self.assertNotEqual(book.root(zv), book.root(z))
        self.assertEqual(book.ents[zl].type, "org")                            # a real org account stays an org
        self.assertNotEqual(book.root(zl), book.root(vela))
        self.cur.execute("SELECT count(*) FROM mx_entity_redirects WHERE by = 'rule:product_account' AND undone_at IS NULL")
        self.assertEqual(self.cur.fetchone()[0], 1)
        self.assertNotEqual(book.shown_type(zv), "org")

    def test_b_an_account_made_an_org_before_is_repaired_into_its_family(self):
        z, vela, zv, v5 = self._org_and_family()                               # linked before its family was known
        self.assertEqual(self.book().ents[zv].type, "org")
        out = self.stage(since=self.since)
        self.assertEqual(out["repair"]["product_accounts"]["merged"], 1)
        book = self.book()
        self.assertEqual(book.root(zv), book.root(vela))
        self.assertNotEqual(book.shown_type(zv), "org")                        # shown as the family's type
        again = self.stage(since=self.since)
        self.assertEqual(again["repair"]["product_accounts"]["merged"], 0)     # idempotent

    def test_c_the_invariant_is_zero_after_the_repair_and_counts_what_the_owner_holds(self):
        z, zai, zv, vela = self._server_shape()
        out = self.stage(since=self.since)                                     # the repair cuts the handle link
        self.assertEqual(out["invariants"]["family_org"], {"count": 0, "held": 0, "clusters": []})
        self.legacy_owner_same(vela, z)                                        # an owner's merge joins them
        out = self.stage(since=self.since)
        got = out["invariants"]["family_org"]
        self.assertEqual((got["count"], got["held"]), (1, 1))
        self.assertIn("Vela", got["clusters"][0]["family"])
        self.assertIn("Zentra", got["clusters"][0]["org"])
        last = entity_stage.last_invariants(self.cur)                          # what /markx's overview shows
        self.assertEqual(last["family_org"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
