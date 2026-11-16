"""0217 (Stealth v10.23): stories grouped into News rows on judged connections, every join checked against the
story's core (utils/grouping.py). Pure: no database."""
from __future__ import annotations

import random
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from insight_core.utils import grouping as G
from insight_core.utils.grouping import Edge, Item, Policy, Post, Thing

T0 = datetime(2100, 6, 1, tzinfo=timezone.utc)
H = timedelta(hours=1)
D = timedelta(days=1)
VELA = Thing("vela5")
QMAX = Thing("orbitmax4", "max")
QBARE = Thing("orbitmax4")


def story(sid, at, n=3, *, things=(), event=None, voices=None, names=(), replies=0):
    posts = tuple(Post(f"{sid}-{k}", at + k * H, tuple(things), event) for k in range(n))
    posts += tuple(Post(f"{sid}-r{k}", at + (n + k) * H, (), None, report=False) for k in range(replies))
    return Item(sid, posts, voices if voices is not None else n, frozenset(names))


def same(a, b, p=0.9, shown=()):
    return Edge(a, b, "judge", "same_event", p, shown=frozenset(shown))


def name(a, b, n):
    return Edge(a, b, "name", name=n)


def partition(g):
    return sorted(sorted(x.members) for x in g.groups)


ALGOS = ("uf", "agg", "cc")


class ThingOf(unittest.TestCase):
    def test_version_and_variant(self):
        self.assertEqual(G.Thing.of(name="Qwen4-Max", family="Qwen", version="4", variant="Max"), Thing("qwen4", "max"))
        self.assertEqual(G.Thing.of(name="Qwen 4", family="Qwen", version="4"), Thing("qwen4"))
        self.assertEqual(G.Thing.of(name="Qwen4", family=None, version="4"), Thing("qwen4"))
        self.assertEqual(G.Thing.of(name="Kimi K3.1 Pro", family="Kimi", version="K3.1", variant="Pro"),
                         Thing("kimik31", "pro"))

    def test_no_version_is_no_exact_thing(self):
        self.assertIsNone(G.Thing.of(name="Claude Code", family=None, version=None))
        self.assertIsNone(G.Thing.of(name="OpenRouter"))

    def test_fits(self):
        self.assertTrue(QBARE.fits(QMAX))
        self.assertFalse(Thing("orbitmax4", "mini").fits(QMAX))
        self.assertFalse(VELA.fits(QMAX))


class Core(unittest.TestCase):
    def test_a_reply_or_late_post_never_leads(self):
        it = Item("s", (Post("a", T0, (VELA,), "model_release"),
                        Post("b", T0 + H, (QMAX,), "business_event", report=False),
                        Post("c", T0 + 2 * H, (VELA,), "model_release"),
                        Post("z", T0 + 9 * D, (QMAX,), "incident")), 4)
        c = G.core_of(it, Policy(k_lead=2))
        self.assertEqual(c.thing, VELA)
        self.assertEqual(c.event, "model_release")
        self.assertEqual(c.lead, ("a", "c"))

    def test_the_most_specific_thing(self):
        it = Item("s", (Post("a", T0, (QBARE, QMAX), "model_release"), Post("b", T0 + H, (QBARE,), None)), 2)
        self.assertEqual(G.core_of(it).thing, QMAX)


class Shapes(unittest.TestCase):
    def release_world(self):
        """A lab's model over six days (0217's case): a teaser and a preview on day 0, the launch on day 5, a model
        router's "live, $1.50/M" thread and an evaluator's "+9 points" thread as separate rule stories; a story that
        only mentions the model, another lab's release the same day, and a deal by the same lab."""
        items = [
            story("teaser", T0, 2, things=(QBARE,), event="leak_rumour"),
            story("preview", T0 + 2 * H, 6, things=(QMAX,), event="model_release"),
            story("launch", T0 + 5 * D, 9, things=(QMAX,), event="model_release", replies=4),
            story("router", T0 + 5 * D + H, 2, things=(QMAX,), event="product_release"),
            story("bench", T0 + 5 * D + 2 * H, 2, things=(QMAX,), event="research_result"),
            story("mentions", T0 + 5 * D + 3 * H, 3, things=(), event="opinion_analysis"),
            story("other", T0 + 5 * D, 5, things=(VELA,), event="model_release"),
            story("deal", T0 + 5 * D + 4 * H, 3, things=(QMAX,), event="business_event"),
        ]
        edges = [name("launch", "mentions", "orbit max 4"), name("launch", "other", "release")]
        return items, edges

    def test_one_release_is_one_row(self):
        items, edges = self.release_world()
        for algo in ALGOS:
            with self.subTest(algo=algo):
                g = G.group(items, edges, policy=Policy(algo=algo))
                row = next(x for x in g.groups if "launch" in x.members)
                self.assertEqual(sorted(row.members), ["bench", "launch", "preview", "router", "teaser"])
                self.assertEqual(row.id, "launch")   # the most voices leads
                self.assertEqual([i for i, _ in row.lines], ["teaser", "preview", "launch", "router", "bench"])
                self.assertEqual(dict(row.lines)["router"], "product_release")
                for out in ("mentions", "other", "deal"):
                    self.assertNotIn(out, row.members)

    def test_the_release_rule_off_keeps_them_apart(self):
        items, edges = self.release_world()
        g = G.group(items, edges, policy=Policy(release=False))
        self.assertNotEqual(g.group_of["router"], g.group_of["launch"])

    def test_beyond_the_span_is_another_release(self):
        items = [story("a", T0, 3, things=(QMAX,), event="model_release"),
                 story("b", T0 + 20 * D, 3, things=(QMAX,), event="model_release")]
        self.assertEqual(len(G.group(items, [], policy=Policy(span_days=7)).groups), 2)

    def test_a_bare_version_joins_no_variant_when_two_are_in_reach(self):
        items = [story("teaser", T0, 2, things=(Thing("gem3"),), event="leak_rumour"),
                 story("pro", T0 + D, 4, things=(Thing("gem3", "pro"),), event="model_release"),
                 story("flash", T0 + D, 4, things=(Thing("gem3", "flash"),), event="model_release")]
        for algo in ALGOS:
            self.assertEqual(partition(G.group(items, [], policy=Policy(algo=algo))), [["flash"], ["pro"], ["teaser"]])

    def runaway_world(self):
        """0203's runaway: a release, a digest that says it and a CEO's resignation, the CEO's stories, a second digest
        saying the CEO and an IPO, the IPO's stories. Every name edge is real; a chain of them reaches everything."""
        items = [
            story("vela", T0, 8, things=(VELA,), event="model_release", names={"vela 5"}),
            story("digest1", T0 + H, 1, event="digest", names={"vela 5", "northwind"}),
            story("ceo", T0 + 2 * H, 6, event="public_statement", names={"northwind"}),
            story("ceo2", T0 + 3 * H, 4, event="opinion_analysis", names={"northwind"}),
            story("digest2", T0 + 4 * H, 1, event="digest", names={"northwind", "orbit"}),
            story("ipo", T0 + 5 * H, 5, event="business_event", names={"orbit"}),
        ]
        edges = [name("vela", "digest1", "vela 5"), name("digest1", "ceo", "northwind"),
                 name("ceo", "ceo2", "northwind"), name("ceo2", "digest2", "northwind"),
                 name("digest2", "ipo", "orbit"), Edge("digest1", "ceo2", "rule", "thread")]
        return items, edges

    def test_the_runaway_does_not_chain(self):
        items, edges = self.runaway_world()
        for algo in ALGOS:
            with self.subTest(algo=algo):
                g = G.group(items, edges, policy=Policy(algo=algo))
                vela = g.group_of["vela"]
                self.assertNotEqual(vela, g.group_of["ceo"])
                self.assertNotEqual(vela, g.group_of["ipo"])
                self.assertNotEqual(g.group_of["ceo"], g.group_of["ipo"])
                self.assertEqual(g.group_of["ceo"], g.group_of["ceo2"])
                self.assertIn("bridge", {why for e, why in g.rejected if e.source == "rule"})

    def test_without_the_core_check_it_chains(self):
        items, edges = self.runaway_world()
        g = G.group(items, edges, policy=Policy(algo="uf", admit=False))
        self.assertEqual(len(g.groups), 1)

    def test_the_ipo_joins(self):
        """0205 2b: three IPO stories the judge called one event, a surge's first post in the release's story; no
        name path reaches all three. They are one row; the release is not in it."""
        items = [story("vela", T0, 8, things=(VELA,), event="model_release", names={"vela 5"}),
                 story("ipo1", T0 + D, 12, event="business_event", names={"orbit"}),
                 story("ipo2", T0 + D + H, 7, event="business_event"),
                 story("ipo3", T0 + D + 2 * H, 5, event="business_event")]
        edges = [same("ipo1", "ipo2", 0.9), same("ipo2", "ipo3", 0.85), name("vela", "ipo1", "orbit")]
        for algo in ALGOS:
            with self.subTest(algo=algo):
                g = G.group(items, edges, policy=Policy(algo=algo))
                self.assertEqual(partition(g), [["ipo1", "ipo2", "ipo3"], ["vela"]])

    def test_a_confident_different_blocks_the_join(self):
        items = [story("a", T0, 3, things=(QMAX,), event="model_release"),
                 story("b", T0 + H, 3, things=(QMAX,), event="model_release")]
        diff = Edge("a", "b", "judge", "different", 0.9)
        for algo in ALGOS:
            g = G.group(items, [diff], policy=Policy(algo=algo))
            self.assertEqual(len(g.groups), 2)
            # off: a `different` weighs against the join, it does not forbid it
            mild = Edge("a", "b", "judge", "different", 0.6)
            g = G.group(items, [mild], policy=Policy(algo=algo, tau_diff=None))
            self.assertEqual(len(g.groups), 1, algo)

    def test_a_different_blocks_a_chain_too(self):
        """A and C judged different; B same as both: B joins one of them, never both (complete link)."""
        items = [story("a", T0, 3, event="business_event"), story("b", T0 + H, 3, event="business_event"),
                 story("c", T0 + 2 * H, 3, event="business_event")]
        edges = [same("a", "b", 0.95), same("b", "c", 0.9), Edge("a", "c", "judge", "different", 0.95)]
        for algo in ALGOS:
            g = G.group(items, edges, policy=Policy(algo=algo))
            self.assertNotEqual(g.group_of["a"], g.group_of["c"], algo)

    def test_a_stale_verdict_does_not_act(self):
        items = [story("a", T0, 3, event="business_event"), story("b", T0 + H, 3, event="business_event")]
        g = G.group(items, [same("a", "b", 0.95, shown={"a-0", "gone"})])
        self.assertEqual(len(g.groups), 2)
        self.assertEqual([w for _, w in g.rejected], ["stale"])
        g = G.group(items, [same("a", "b", 0.95, shown={"a-0", "b-1"})])
        self.assertEqual(len(g.groups), 1)

    def test_a_development_builds_nothing(self):
        items = [story("a", T0, 3, event="business_event"), story("b", T0 + H, 3, event="business_event")]
        g = G.group(items, [Edge("a", "b", "judge", "development", 0.95)])
        self.assertEqual(len(g.groups), 2)


class OrderIndependence(unittest.TestCase):
    def world(self, seed):
        rnd = random.Random(seed)
        things = [Thing(f"m{k}", rnd.choice(["", "pro", "mini"])) for k in range(6)]
        types = ["model_release", "product_release", "leak_rumour", "research_result", "business_event",
                 "opinion_analysis", "digest", None]
        names = ["alpha", "beta", "gamma", "delta"]
        items = []
        for k in range(60):
            items.append(story(f"s{k:02d}", T0 + rnd.randrange(0, 240) * H, rnd.randint(1, 6),
                               things=(rnd.choice(things),) if rnd.random() < 0.6 else (),
                               event=rnd.choice(types), voices=rnd.randint(1, 9),
                               names=set(rnd.sample(names, rnd.randint(0, 2))), replies=rnd.randint(0, 2)))
        edges = []
        for _ in range(140):
            a, b = rnd.sample([i.id for i in items], 2)
            kind = rnd.random()
            if kind < 0.35:
                edges.append(name(a, b, rnd.choice(names)))
            elif kind < 0.65:
                edges.append(same(a, b, round(rnd.uniform(0.4, 0.99), 2)))
            elif kind < 0.75:
                edges.append(Edge(a, b, "judge", "different", round(rnd.uniform(0.5, 0.99), 2)))
            elif kind < 0.85:
                edges.append(Edge(a, b, "judge", "development", 0.8))
            else:
                edges.append(Edge(a, b, "rule", "thread"))
        return items, edges

    def test_twenty_shuffles_give_one_partition(self):
        for seed in range(4):
            items, edges = self.world(seed)
            for pol in (Policy(algo="uf"), Policy(algo="agg"), Policy(algo="cc"), Policy(algo="agg", admit=False),
                        Policy(algo="uf", admit=False, release=False)):
                with self.subTest(seed=seed, policy=pol.algo, admit=pol.admit):
                    want = G.group(items, edges, policy=pol)
                    rnd = random.Random(seed * 100)
                    for _ in range(20):
                        it, ed = items[:], edges[:]
                        rnd.shuffle(it)
                        rnd.shuffle(ed)
                        ed = [replace(e, a=e.b, b=e.a) if rnd.random() < 0.5 else e for e in ed]
                        got = G.group(it, ed, policy=pol)
                        self.assertEqual(partition(got), partition(want))
                        self.assertEqual([x.id for x in got.groups], [x.id for x in want.groups])

    def test_every_item_in_exactly_one_group(self):
        items, edges = self.world(7)
        for algo in ALGOS:
            g = G.group(items, edges, policy=Policy(algo=algo))
            seen = [m for x in g.groups for m in x.members]
            self.assertEqual(sorted(seen), sorted(i.id for i in items))


if __name__ == "__main__":
    unittest.main()
