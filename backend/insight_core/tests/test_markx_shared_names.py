"""One name, many things (issue 0250), with invented names only: a bare name three invented companies use ("Vexa" by
Kestrel, Lumora and Brightwell) is never split by its makers alone (v10.28): each pair of maker groups is asked once
(the collide kind, identity.PAIR_GUIDE) and split only when every run says "different" (identity.split_names, 0230's
maker rule deepened); an owner change, a founder and a legal name asked and kept one thing; one company's aliases never
asked, the mentions with no maker go by their post (its other makers, its links, the settled
collision answer, else unsure), the links follow the split and a single contradicted `released` is held, the timeline's
outside events are posts about the thing, and a story page lists its things."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from insight_core.markx import entity_views, identity as I, repo, schemas, timeline as TL
from insight_core.tests import test_markx_entities as base
from insight_core.tests import test_markx_timeline as tl

T0, H, D = base.T0, base.H, base.D
ON = {"maker": False, "stem": False, "namesakes": False, "split": True, "released_held": True}


def split_on():
    return mock.patch.object(I, "families_on", lambda: dict(ON))


def apart(*pairs):
    """A `said` for split_plan: the named maker pairs (by a group's top name, either way round) are 'different',
    every other pair 'same'."""
    sep = {frozenset(p) for p in pairs}
    return lambda a, b: "different" if frozenset((a.name, b.name)) in sep else "same"


def all_apart(a, b):
    return "different"


class Plan(unittest.TestCase):
    """identity.split_plan, no database: maker groups are candidates, never a split by themselves (v10.28); which
    maker each mention is once a pair is settled apart, and when a name is one thing."""
    ent, book = base.Rules.ent, base.Rules.book

    def rows(self, *makers, **kw):
        return [I.NameRow(f"p{k}", "ent-v3", 0, "vexa", m, **kw) for k, m in enumerate(makers)]

    def three(self):
        vexa = self.ent("vexa", "Vexa", "model", "Lumora")
        book = self.book(vexa, self.ent("k", "Kestrel", "org"), self.ent("l", "Lumora", "org"), self.ent("b", "Brightwell", "org"))
        return vexa, book, self.rows("Kestrel", "Kestrel", "Kestrel", "Lumora", "Lumora", "Brightwell", "Brightwell", "Quell")

    def test_maker_groups_alone_never_split_each_pair_is_a_question(self):
        vexa, book, rows = self.three()
        plan = I.split_plan(book, vexa, rows)
        self.assertEqual(plan["rows"], {})                                   # nothing settled: one thing
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual([g.name for g in plan["big"]], ["Kestrel", "Brightwell", "Lumora"])
        self.assertEqual(plan["ask"], [(0, 1), (0, 2), (1, 2)])              # each pair asked once

    def test_three_companies_settled_apart_make_three_things_and_the_entitys_own_maker_keeps_it(self):
        vexa, book, rows = self.three()
        plan = I.split_plan(book, vexa, rows, all_apart)
        self.assertEqual(plan["ask"], [])
        self.assertEqual([g.name for g in plan["groups"]], ["Kestrel", "Brightwell", "Lumora"])
        self.assertEqual(plan["groups"][plan["home"]].name, "Lumora")      # its own stated maker, not the most stated
        got = {p: (k if k is None else plan["groups"][k].name, how) for (p, _g, _n), (k, how) in plan["rows"].items()}
        self.assertEqual(got["p0"], ("Kestrel", "rule:maker"))
        self.assertEqual(got["p5"], ("Brightwell", "rule:maker"))
        self.assertEqual(got["p7"], (None, "unsure"))                       # a maker one mention names: no thing of its own

    def test_a_pair_still_waiting_keeps_its_two_groups_one_thing(self):
        vexa, book, rows = self.three()
        settled = {frozenset(("Kestrel", "Lumora")): "different", frozenset(("Brightwell", "Lumora")): "same"}
        plan = I.split_plan(book, vexa, rows, lambda a, b: settled.get(frozenset((a.name, b.name))))
        self.assertEqual(plan["ask"], [(0, 1)])                              # Kestrel / Brightwell not answered
        self.assertEqual(plan["rows"], {})                                   # Kestrel ~ Brightwell = Lumora: one thing
        self.assertEqual(len(plan["groups"]), 1)
        # a group settled apart from every other is its own thing while the others' pair waits
        settled = {frozenset(("Kestrel", "Lumora")): "different", frozenset(("Kestrel", "Brightwell")): "different"}
        plan = I.split_plan(book, vexa, rows, lambda a, b: settled.get(frozenset((a.name, b.name))))
        self.assertEqual(plan["ask"], [(1, 2)])
        self.assertEqual([sorted(g.names) for g in plan["groups"]], [["Brightwell", "Lumora"], ["Kestrel"]])

    def test_an_owner_change_a_founder_and_legal_names_are_one_thing_a_namesake_apart(self):
        # Pellum: made by Corvane, sold to Ostrava Holdings; its founder Iris Vandel named as maker; Corvane's legal
        # name "Nordhaven Software Oy" (no alias known, no word shared); and Quell's unrelated game of the name
        pellum = self.ent("pellum", "Pellum", "software", "Corvane")
        book = self.book(pellum, self.ent("c", "Corvane", "org"), self.ent("o", "Ostrava Holdings", "org"),
                         self.ent("i", "Iris Vandel", "person"), self.ent("q", "Quell", "org"))
        rows = self.rows("Corvane", "Corvane", "Corvane", "Ostrava Holdings", "Ostrava Holdings", "Iris Vandel",
                         "Iris Vandel", "Nordhaven Software Oy", "Nordhaven Software Oy", "Quell", "Quell")
        plan = I.split_plan(book, pellum, rows)
        self.assertEqual(len(plan["big"]), 5)                                # a legal name, a founder: each a group
        self.assertEqual(len(plan["ask"]), 10)
        plan = I.split_plan(book, pellum, rows, apart(("Corvane", "Quell"), ("Ostrava Holdings", "Quell"),
                                                      ("Iris Vandel", "Quell"), ("Nordhaven Software Oy", "Quell")))
        self.assertEqual(len(plan["groups"]), 2)
        one, other = plan["groups"]
        self.assertEqual(sorted(one.names), ["Corvane", "Iris Vandel", "Nordhaven Software Oy", "Ostrava Holdings"])
        self.assertEqual(other.names, ["Quell"])
        self.assertEqual(plan["groups"][plan["home"]].name, "Corvane")
        got = {p: k for (p, _g, _n), (k, _how) in plan["rows"].items()}
        self.assertEqual({got[f"p{k}"] for k in range(9)}, {0})              # the owner, founder, legal name: one thing
        self.assertEqual({got["p9"], got["p10"]}, {1})

    def test_a_pair_settled_same_or_cant_tell_is_one_thing(self):
        vexa = self.ent("vexa", "Vexa", "model")
        book = self.book(vexa, self.ent("k", "Kestrel", "org"), self.ent("l", "Lumora", "org"))
        for v in ("same", "cant_tell"):
            plan = I.split_plan(book, vexa, self.rows("Kestrel", "Kestrel", "Lumora", "Lumora"), lambda a, b: v)
            self.assertEqual((plan["rows"], plan["ask"], len(plan["groups"])), ({}, [], 1))
            self.assertEqual(plan["pairs"], {(0, 1): v})

    def test_one_companys_aliases_are_one_maker_never_a_question(self):
        vexa = self.ent("vexa", "Vexa", "model")
        k, h = self.ent("k", "Kestrel", "org"), self.ent("h", "Halcyon", "org")
        book = self.book(vexa, k, h)
        book.redirect["h"] = ("k", True)                                     # Halcyon is Kestrel (one cluster)
        plan = I.split_plan(book, vexa, self.rows("Kestrel", "Kestrel", "Kestrel Labs", "Kestrel Labs", "Halcyon",
                                                  "Halcyon", "Vexa Team"), all_apart)
        self.assertEqual((plan["rows"], plan["ask"]), ({}, []))              # one maker: nothing to ask, no split
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual(sorted(plan["groups"][0].names), ["Halcyon", "Kestrel", "Kestrel Labs", "Vexa Team"])

    def test_two_companies_settled_apart_are_two_things(self):
        vexa = self.ent("vexa", "Vexa", "model")
        book = self.book(vexa, self.ent("k", "Kestrel", "org"), self.ent("l", "Lumora", "org"))
        plan = I.split_plan(book, vexa, self.rows("Kestrel", "Kestrel", "Lumora", "Lumora"), all_apart)
        self.assertEqual(len(plan["groups"]), 2)
        self.assertNotEqual(plan["rows"][("p0", "ent-v3", 0)][0], plan["rows"][("p2", "ent-v3", 0)][0])

    def test_a_mention_with_no_maker_goes_by_its_post_its_links_or_the_answer_else_unsure(self):
        vexa = self.ent("vexa", "Vexa", "model", "Kestrel")
        book = self.book(vexa, self.ent("k", "Kestrel", "org"), self.ent("l", "Lumora", "org"))
        rows = self.rows("Kestrel", "Kestrel", "Lumora", "Lumora")
        rows += [I.NameRow("near", "ent-v3", 0, "vexa", None, near=["Lumora", "Orbit Cloud"]),
                 I.NameRow("both", "ent-v3", 0, "vexa", None, near=["Lumora", "Kestrel"]),
                 I.NameRow("link", "ent-v3", 0, "vexa", None, sites=["blog.lumora.ai", "github.com"]),
                 I.NameRow("asked", "ent-v3", 0, "vexa", None, asked="Kestrel"),
                 I.NameRow("none", "ent-v3", 0, "vexa", None, sites=["github.com"])]
        plan = I.split_plan(book, vexa, rows, all_apart)
        name = lambda k: None if k is None else plan["groups"][k].name   # noqa: E731
        got = {p: (name(k), how) for (p, _g, _n), (k, how) in plan["rows"].items()}
        self.assertEqual(got["near"], ("Lumora", "rule:post"))
        self.assertEqual(got["link"], ("Lumora", "rule:link"))
        self.assertEqual(got["asked"], ("Kestrel", "facts"))
        self.assertEqual(got["both"], (None, "unsure"))                     # two makers named: not told by the post
        self.assertEqual(got["none"], (None, "unsure"))

    def test_only_a_bare_thing_is_split(self):
        self.assertTrue(I.bare_thing(self.ent("a", "Vexa", "model")))
        for e in (self.ent("b", "Vexa 2", "model"), self.ent("c", "Vexa Studio", "product"), self.ent("d", "Vexa", "org")):
            self.assertFalse(I.bare_thing(e))

    def test_a_pair_is_apart_only_when_every_run_says_different(self):
        d, s, c = {"verdict": "different"}, {"verdict": "same"}, {"verdict": "cant_tell"}
        self.assertIsNone(I.pair_verdict([]))
        self.assertIsNone(I.pair_verdict([d]))                               # one run: the next is asked
        self.assertEqual(I.pair_verdict([d] * I.PAIR_RUNS), "different")
        self.assertEqual(I.pair_verdict([d, s]), "same")
        self.assertEqual(I.pair_verdict([c]), "cant_tell")                   # kept: one thing
        self.assertEqual(I.pair_verdict([{"verdict": None}]), "cant_tell")

    def test_the_question_shows_each_group_its_types_dates_neighbours_and_three_to_five_samples(self):
        vexa = self.ent("vexa", "Vexa", "software")
        book = self.book(vexa, self.ent("k", "Kestrel", "org"), self.ent("b", "Brightwell", "org"))
        rows = [I.NameRow(f"k{k}", "ent-v3", 0, "vexa", "Kestrel", span="Vexa", type="software", at=T0 - (30 - k) * D)
                for k in range(7)]
        rows += [I.NameRow(f"b{k}", "ent-v3", 0, "vexa", "Brightwell Games", span="VEXA", type="product",
                           at=T0 - (900 - k) * D) for k in range(3)]
        big = I.name_groups(book, vexa, rows)
        self.assertEqual([g.name for g in big], ["Kestrel", "Brightwell Games"])
        self.assertEqual(len(I.pair_samples(big[0], rows, "s")), I.PAIR_SAMPLES)
        self.assertEqual([r.post_id for r in I.pair_samples(big[0], rows, "s")][:2], ["k0", "k6"])   # oldest, newest
        self.assertEqual(len(I.pair_samples(big[1], rows, "s")), 3)
        text = I.maker_pair_input(vexa, 10, [(big[0], rows, ["Orbit"]), (big[1], rows, [])], {})
        self.assertIn('A makers: ["Kestrel"] (7 mentions) | types: software 7 |', text)
        self.assertIn('B makers: ["Brightwell Games"] (3 mentions) | types: product 3 |', text)
        self.assertIn("named with: Orbit", text)
        self.assertEqual(text.count("\n  A"), 5)
        self.assertEqual(text.count("\n  B"), 3)
        self.assertEqual(I.pair_sides(text), ({"Kestrel"}, {"Brightwell Games"}))
        ok = {"evidence": "A: a code tool; B: a 1990s game", "verdict": "different", "why": "different_things"}
        from insight_core.markx import validate
        self.assertIsNone(validate.check("collide", ok, text, guide=I.PAIR_GUIDE)[1])
        self.assertIsNotNone(validate.check("collide", dict(ok, evidence=" "), text, guide=I.PAIR_GUIDE)[1])
        self.assertIsNotNone(validate.check("collide", dict(ok, verdict="maybe"), text, guide=I.PAIR_GUIDE)[1])
        self.assertEqual(schemas.GUIDE_VARIANTS[I.PAIR_GUIDE][0], "collide")   # the collide kind deepened, no new kind
        self.assertIn(I.PAIR_GUIDE, schemas.guide_ids())


@base.requires_test_db
class Split(tl._Db):
    """The split over the database: each maker pair asked once (the collide kind, PAIR_GUIDE), split only on
    "different" from every run; made, pinned, idempotent, nothing deleted; off by default."""

    def say(self, n, maker, at, *, org=True, title=None, links=(), type_="model"):
        p = self.post_at(n % 5, at, title or f"{maker or 'Someone'} shows Vexa")
        ents = [("Vexa", type_, "subject", maker)] + ([(maker, "org", "actor")] if org and maker else [])
        self.mentions(p, *ents)
        for k, site in enumerate(links):
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, %s, %s)",
                             (p, f"https://{site}/vexa", site, k))
        return p

    def three(self):
        posts = {"Kestrel": [self.say(k, "Kestrel", T0 - (20 - k) * D) for k in range(3)],
                 "Lumora": [self.say(k, "Lumora", T0 - (10 - k) * D) for k in range(2)],
                 "Brightwell": [self.say(k, "Brightwell", T0 - (5 - k) * D) for k in range(2)]}
        return posts

    def count(self, table):
        self.cur.execute(f"SELECT count(*) FROM {table}")
        return self.cur.fetchone()[0]

    def pairs(self):
        self.cur.execute("SELECT id::text, status, input FROM mx_tasks WHERE kind = 'collide' AND guide = %s "
                         "ORDER BY created_at, id", (I.PAIR_GUIDE,))
        return self.cur.fetchall()

    def answer_pairs(self, verdict, runs=I.PAIR_RUNS):
        """Each open pair question answered `runs` times: verdict(A's makers, B's makers)."""
        n = 0
        for tid, status, text in self.pairs():
            if status != "open":
                continue
            a, b = I.pair_sides(text)
            for _ in range(runs):
                repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True,
                              answer={"evidence": "-", "verdict": verdict(a, b)})
            repo.answer_task(self.cur, tid)
            n += 1
        return n

    def test_off_by_default_nothing_changes(self):
        posts = self.three()
        out = self.stage()
        self.assertTrue(out["repair"]["names"]["off"])
        self.assertEqual(self.pairs(), [])
        self.assertEqual(len({self.entity_of(p) for ps in posts.values() for p in ps}), 1)

    @split_on()
    def test_a_bare_name_of_three_companies_is_asked_then_three_things_the_old_id_kept_nothing_deleted(self):
        posts = self.three()
        out = self.stage()["repair"]["names"]
        self.assertEqual((out["asked"], out["split"], out["made"]), (3, 0, 0))   # asked, never split by maker alone
        self.assertEqual(len({self.entity_of(p) for ps in posts.values() for p in ps}), 1)
        again = self.stage(since=self.since)["repair"]["names"]
        self.assertEqual((again["asked"], again["waiting"]), (0, 3))           # each pair asked once
        self.assertEqual(self.answer_pairs(lambda a, b: "different"), 3)
        got = self.stage(since=self.since)["repair"]["names"]
        self.assertEqual((got["split"], got["made"], got["pinned"], got["apart"]), (1, 2, 4, 3))
        home = {self.entity_of(p) for p in posts["Kestrel"]}
        self.assertEqual(len(home), 1)
        home = home.pop()
        book = self.book()
        self.assertEqual(book.ents[home].name, "Vexa")                       # the old id is the most stated maker's
        self.assertEqual(book.ents[home].shown_name, "Vexa (Kestrel)")
        for maker in ("Lumora", "Brightwell"):
            things = {self.entity_of(p) for p in posts[maker]}
            self.assertEqual(len(things), 1)
            t = book.ents[things.pop()]
            self.assertEqual((t.name, t.maker, t.level), (f"Vexa ({maker})", maker, "thing"))
            self.assertEqual(book.ents[t.parent].name, maker)                # under its maker
        self.cur.execute("SELECT count(*), count(*) FILTER (WHERE by = 'facts' AND from_entity = %s) FROM mx_entity_pins",
                         (home,))
        self.assertEqual(self.cur.fetchone(), (4, 4))                        # undoable: the link each left is kept
        self.assertEqual(self.count("mx_entity_redirects"), 0)
        entities, mentions = self.count("mx_entities"), self.count("mx_mentions")
        again = self.stage()["repair"]["names"]
        self.assertEqual((again["split"], again["made"], again["pinned"], again["asked"]), (0, 0, 0, 0))   # idempotent
        self.assertEqual((self.count("mx_entities"), self.count("mx_mentions")), (entities, mentions))

    @split_on()
    def test_two_unrelated_companies_of_different_types_are_asked_with_their_types_and_split_on_different(self):
        tool = [self.say(k, "Kestrel", T0 - (20 - k) * D, type_="software", title="Kestrel's Vexa, a code tool")
                for k in range(3)]
        game = [self.say(k, "Brightwell", T0 - (400 - k) * D, type_="product", title="Brightwell's Vexa, a puzzle game")
                for k in range(2)]
        self.stage()
        (tid, _st, text), = self.pairs()
        self.assertIn("types: software 3", text)
        self.assertIn("types: product 2", text)
        self.assertIn("a puzzle game", text)                                 # the samples' contexts
        self.assertEqual(self.answer_pairs(lambda a, b: "different", runs=1), 1)
        got = self.stage(since=self.since)["repair"]["names"]
        self.assertEqual((got["split"], got["asked_again"]), (0, 1))         # one run apart: asked again, not split
        self.cur.execute("SELECT status FROM mx_tasks WHERE id = %s", (tid,))
        self.assertEqual(self.cur.fetchone()[0], "open")
        self.answer_pairs(lambda a, b: "different", runs=1)
        got = self.stage(since=self.since)["repair"]["names"]
        self.assertEqual((got["split"], got["made"]), (1, 1))                # every run says apart: split
        self.assertNotEqual(self.entity_of(tool[0]), self.entity_of(game[0]))

    @split_on()
    def test_a_product_whose_maker_changed_owner_is_asked_and_kept_one_thing(self):
        old = [self.say(k, "Corvane", T0 - (300 - k) * D) for k in range(3)]
        new = [self.say(k, "Ostrava Holdings", T0 - (10 - k) * D, title="Ostrava Holdings, Vexa's new owner")
               for k in range(2)]
        self.stage()
        self.assertEqual(len(self.pairs()), 1)
        self.answer_pairs(lambda a, b: "same", runs=1)                     # the first run: one thing
        got = self.stage(since=self.since)["repair"]["names"]
        self.assertEqual((got["split"], got["made"], got["one_thing"], got["asked_again"]), (0, 0, 1, 0))
        self.assertEqual(len({self.entity_of(p) for p in old + new}), 1)
        self.assertEqual(self.count("mx_entity_fixes WHERE kind = 'maker_split'"), 0)

    @split_on()
    def test_a_founder_and_legal_names_with_a_namesake_split_only_the_namesake(self):
        firm = [self.say(k, "Corvane", T0 - (30 - k) * D) for k in range(3)]
        founder = [self.say(k, "Iris Vandel", T0 - (25 - k) * D, org=False) for k in range(2)]
        legal = [self.say(k, "Nordhaven Software Oy", T0 - (22 - k) * D) for k in range(2)]
        other = [self.say(k, "Quell", T0 - (15 - k) * D, type_="product") for k in range(2)]
        self.stage()
        self.answer_pairs(lambda a, b: "different" if "Quell" in a | b else "same")
        self.stage(since=self.since)
        ours = {self.entity_of(p) for p in firm + founder + legal}
        self.assertEqual(len(ours), 1)
        theirs = {self.entity_of(p) for p in other}
        self.assertEqual(len(theirs), 1)
        self.assertNotEqual(ours, theirs)
        self.assertEqual(self.book().ents[theirs.pop()].name, "Vexa (Quell)")

    @split_on()
    def test_one_companys_aliases_are_never_split(self):
        for k, maker in enumerate(["Kestrel", "Kestrel", "Kestrel Labs", "Kestrel Labs", "Halcyon", "Halcyon"]):
            self.say(k, maker, T0 - (10 - k) * D)
        with mock.patch.object(I, "families_on", lambda: {**ON, "split": False}):
            self.stage()                                                    # linked before Halcyon is known as Kestrel
        book = self.book()
        I.merge(self.cur, book, book.by_key("halcyon"), book.by_key("kestrel"), by="test", automatic=False)
        out = self.stage()["repair"]["names"]
        self.assertEqual((out["split"], out["made"], out["asked"]), (0, 0, 0))
        self.cur.execute("SELECT count(DISTINCT entity_id) FROM mx_mentions WHERE name_key = 'vexa'")
        self.assertEqual(self.cur.fetchone()[0], 1)

    @split_on()
    def test_mentions_with_no_maker_go_by_their_post_and_new_ones_follow_the_split(self):
        posts = self.three()
        self.stage()
        self.answer_pairs(lambda a, b: "different")
        self.stage(since=self.since)
        by_org = self.post_at(0, T0 - D, "Vexa, now on Brightwell's cloud")
        self.mentions(by_org, ("Vexa", "model", "subject", None), ("Brightwell", "org", "actor"))
        by_link = self.say(1, None, T0 - D, links=["blog.lumora.ai"])
        nothing = self.say(2, None, T0 - D)
        later = self.say(3, "Lumora", T0)
        out = self.stage(since=self.since)["repair"]["names"]
        lum, bri = self.entity_of(posts["Lumora"][0]), self.entity_of(posts["Brightwell"][0])
        home = self.entity_of(posts["Kestrel"][0])
        self.assertEqual((out["made"], out["asked"]), (0, 0))
        self.assertEqual((self.entity_of(by_org), self.entity_of(by_link), self.entity_of(later)), (bri, lum, lum))
        self.assertEqual(self.entity_of(nothing), home)                      # unsure: stays on the name's entity
        self.cur.execute("SELECT post_id::text, placed FROM mx_mentions WHERE name_key = 'vexa' AND post_id = ANY(%s::uuid[])",
                         ([by_org, by_link, nothing, later],))
        self.assertEqual(dict(self.cur.fetchall()), {by_org: "rule:post", by_link: "rule:link", nothing: "unsure",
                                                     later: "rule:maker"})


@base.requires_test_db
class Links(tl._Db):
    """0250 #2: the links follow the split; a single `released` another maker states is held."""
    state, graph, edges, touched = tl.ThingLinks.state, tl.ThingLinks.graph, tl.ThingLinks.edges, tl.ThingLinks.touched
    pairs, answer_pairs = Split.pairs, Split.answer_pairs

    def setUp(self):
        super().setUp()
        bands = json.loads(json.dumps(I.bands()))
        bands["families"].update(ON)
        patcher = mock.patch.object(I, "bands", return_value=bands)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_released_and_a_based_on_land_on_their_makers_thing(self):
        ks = []
        for k in range(3):
            p = self.post_at(k, T0 - (20 - k) * D, "Kestrel ships Vexa")
            self.mentions(p, ("Vexa", "model", "subject", "Kestrel"), ("Kestrel", "org", "actor"))
            self.state(p, [{"a": "Kestrel", "rel": "released", "b": "Vexa"}])
            ks.append(p)
        ls = []
        for k in range(2):
            p = self.post_at(k, T0 - (5 - k) * D, "Lumora's Vexa, a fine-tune of Orbit 3")
            self.mentions(p, ("Vexa", "model", "subject", "Lumora"), ("Lumora", "org", "actor"),
                          ("Orbit 3", "model", "mention", "Vantor"))
            self.state(p, [{"a": "Lumora", "rel": "released", "b": "Vexa"}, {"a": "Vexa", "rel": "based_on", "b": "Orbit 3"}])
            ls.append(p)
        with mock.patch.object(I, "families_on", lambda: {**ON, "split": False}):
            self.stage()                                                    # linked as before the split: one Vexa
        self.graph()
        one = self.entity_of(ks[0])
        self.assertEqual({(a, rel) for a, b, rel, *_ in self.edges() if b == one or a == one},
                         {(self.entity_of(ks[0], 1), "released"), (self.entity_of(ls[0], 1), "released"), (one, "based_on")})
        self.stage()                                                         # the pair asked (never split alone)
        self.assertEqual(self.answer_pairs(lambda a, b: "different"), 1)
        self.stage()                                                         # the split
        self.cur.execute("UPDATE mx_entity_pins SET created_at = %s", (T0 + 2 * D,))   # pinned after the graph's clock
        self.graph(now=T0 + 3 * D)
        vk, vl = self.entity_of(ks[0]), self.entity_of(ls[0])
        self.assertNotEqual(vk, vl)
        got = {(a, b, rel) for a, b, rel, *_ in self.edges()}
        kestrel, lumora, orbit = self.entity_of(ks[0], 1), self.entity_of(ls[0], 1), self.entity_of(ls[0], 2)
        self.assertEqual(got, {(kestrel, vk, "released"), (lumora, vl, "released"), (vl, orbit, "based_on")})
        page = entity_views.entity_page(self.cur, vk, now=T0 + 3 * D)
        self.assertEqual([(r["relation"], r["other"]["id"]) for r in page["relations"]], [("released", kestrel)])

    @mock.patch.object(I, "families_on", lambda: {**ON, "split": False})
    def test_a_single_posts_released_by_another_maker_is_held_until_a_second_post_says_it(self):
        vexa = []
        for k in range(2):
            p = self.post_at(k, T0 - (10 - k) * D, "Kestrel ships Vexa")
            self.mentions(p, ("Vexa", "model", "subject", "Kestrel"), ("Kestrel", "org", "actor"))
            vexa.append(p)
        odd = self.post_at(2, T0 - 2 * D, "Quell released Vexa")
        self.mentions(odd, ("Vexa", "model", "subject", "Quell"), ("Quell", "org", "actor"))
        self.state(odd, [{"a": "Quell", "rel": "released", "b": "Vexa"}])
        self.stage()
        self.graph()
        thing, quell = self.entity_of(vexa[0]), self.entity_of(odd, 1)
        self.assertIn((quell, thing, "released"), {(a, b, rel) for a, b, rel, *_ in self.edges()})   # kept
        page = lambda: entity_views.entity_page(self.cur, thing, now=T0 + 3 * D)["relations"]   # noqa: E731
        self.assertEqual(page(), [])                                                             # held
        again = self.post_at(3, T0 - D, "Quell released Vexa, again")
        self.mentions(again, ("Vexa", "model", "subject", "Quell"), ("Quell", "org", "actor"))
        self.state(again, [{"a": "Quell", "rel": "released", "b": "Vexa"}])
        self.touched(again, T0 + 2 * D)
        self.stage()
        self.graph(now=T0 + 3 * D)
        self.assertEqual([(r["relation"], r["other"]["id"], r["posts"]) for r in page()], [("released", quell, 2)])


@base.requires_test_db
class Outside(tl._Db):
    """0250 #3: an outside event is a post about the thing, never one that only names it."""

    def test_a_post_that_only_names_the_thing_is_no_outside_event(self):
        own = self.post_at(0, T0 - 30 * D, "Kestrel ships Vexa")
        self.mentions(own, ("Vexa", "model", "subject", "Kestrel"), ("Kestrel", "org", "actor"))
        about = self.post_at(1, T0 - 20 * D, "A week with Vexa")
        self.mentions(about, ("Vexa", "model", "subject", None))
        vs = self.post_at(2, T0 - 10 * D, "Orbit 3 against Vexa")
        self.mentions(vs, ("Orbit 3", "model", "subject", "Vantor"), ("Vexa", "model", "compared", None))
        named = self.post_at(3, T0 - 60 * D, "A list of tools: Vexa, among others")
        self.mentions(named, ("Vexa", "model", "mention", None))
        self.stage()
        book = I.load_book(self.cur)
        evs = TL.events(self.cur, book, book.root(self.entity_of(own)))
        posts = {e["post"] for e in evs if e["kind"] in ("outside", "first_outside")}
        self.assertNotIn(named, posts)
        self.assertTrue({about, vs} & posts)
        from insight_core.markx import stops as ST
        off = {**ST.config(), "outside_roles": False}
        with mock.patch.object(ST, "config", lambda: off):                  # off: as before 0250
            evs = TL.events(self.cur, I.load_book(self.cur), book.root(self.entity_of(own)))
        self.assertIn(named, {e["post"] for e in evs if e["kind"] in ("outside", "first_outside", "birth")})


@base.requires_test_db
class StoryThings(tl._Db):
    """0250 #4: a story page's things, ranked by role then count, through the split."""

    def test_the_things_rank_by_role_then_count(self):
        a = self.post_at(0, T0 - 2 * D, "Kestrel opens Vexa")
        self.mentions(a, ("Vexa", "model", "subject", "Kestrel"), ("Kestrel", "org", "actor"), ("Orbit 3", "model", "compared"))
        b = self.post_at(1, T0 - D, "Vexa, Kestrel's agent, against Orbit 3")
        self.mentions(b, ("Orbit 3", "model", "compared"), ("Vexa", "model", "actor", "Kestrel"), ("Lumora", "org", "mention"))
        self.stage()
        got = entity_views.story_things(self.cur, [a, b])
        self.assertEqual([(t["name"], t["role"], t["posts"]) for t in got],
                         [("Vexa", "subject", 2), ("Kestrel", "actor", 1), ("Orbit 3", "compared", 2), ("Lumora", "mention", 1)])
        self.assertEqual(got[0]["id"], I.load_book(self.cur).root(self.entity_of(a)))
        self.assertEqual(entity_views.story_things(self.cur, []), [])


if __name__ == "__main__":
    unittest.main()
