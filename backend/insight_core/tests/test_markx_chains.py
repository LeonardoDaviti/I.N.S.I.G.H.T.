"""0219 (Stealth v10.24): story chains. Two stories that are both stops of one thing (stored stop answers saying
about) are asked how the later relates to the earlier (chain-v1, two runs that must agree); the verdict is a
story-to-story edge (rule chain_stops), closed never deleted; a story's chain walks them both ways, "as of" any moment,
and shows only the relations that passed their bar. Invented names (0165's second case: one model's launch story and
its weights story a week later); the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import decide, graph as G, repo, schemas, stops as ST, tasks, validate
from insight_core.tests import test_markx_entities as base
from insight_core.tests import test_markx_timeline as TL
from insight_core.tests.test_markx_api import _Api, call

T0, H, D = base.T0, base.H, base.D
SIBLINGS = False   # v10.38: entity_bands.json chains.siblings (its measure there)
GUIDE_SHA256 = "be24941d7e58424f6561ed1866cd5d13ccccebdc8b20e527d88ccf36aa598771"   # frozen before held-out round 2


def line(at, title, role="subject", source="Example"):
    return ST.Line(at, source, title, role)


class Rules(unittest.TestCase):
    """No database: the candidate pairs, the verdict, the question, the kind."""

    def test_a_stop_is_paired_with_the_stops_just_before_it_within_the_window(self):
        s = {"orbit": [(T0, "a"), (T0 + 2 * D, "b"), (T0 + 3 * D, "c"), (T0 + 4 * D, "d"), (T0 + 5 * D, "e"),
                       (T0 + 50 * D, "f")]}
        got = G.chain_pairs(s, days=30, prev=3)
        self.assertIn(("e", "b"), got)                 # three back
        self.assertNotIn(("e", "a"), got)              # four back: not proposed
        self.assertNotIn(("f", "e"), got)              # 45 days apart: not proposed
        self.assertEqual(set(got.values()), {"orbit"})
        self.assertEqual(set(G.chain_pairs(s, {"f"})), set())   # only pairs touching a fresh story
        self.assertEqual(set(G.chain_pairs(s, {"a"})), {("b", "a"), ("c", "a"), ("d", "a")})

    def test_a_pair_two_things_propose_goes_to_the_narrower_thing(self):
        s = {"family": [(T0, "a"), (T0 + D, "b"), (T0 + 2 * D, "x")], "version": [(T0, "a"), (T0 + D, "b")]}
        got = G.chain_pairs(s)
        self.assertEqual(got[("b", "a")], "version")
        self.assertEqual(got[("x", "b")], "family")

    def test_two_sibling_things_stops_are_paired_across_their_lines(self):
        """v10.38: the stops of two things of one family (an adapter and its sibling, launched together) are paired
        across the things, within the window and the cap; a story that is a stop of both, or two stops of one thing
        (its own line pairs them), is no sibling pair; a thing of no family is in none."""
        s = {"pi": [(T0, "p1"), (T0 + D, "p2")], "opencode": [(T0 + H, "o1"), (T0 + 2 * D, "o2")],
             "super": [(T0 + 3 * D, "s1")], "far": [(T0 + 40 * D, "f1")], "lone": [(T0 + D, "l1")],
             "both": [(T0 + 2 * H, "p1")]}
        kin = {"pi": "qwen", "opencode": "qwen", "super": "qwen", "far": "qwen", "both": "qwen"}
        got = G.chain_siblings(s, kin, days=30, prev=3)
        self.assertEqual(got[("o1", "p1")], ("opencode", "pi"))
        self.assertEqual(got[("s1", "o2")], ("super", "opencode"))
        self.assertNotIn(("p2", "p1"), got)                      # one thing's two stops: its own line
        self.assertFalse(any("l1" in k for k in got))            # no family
        self.assertFalse(any("f1" in k for k in got))            # 37 days later: out of the window
        self.assertFalse(any(k[0] == k[1] for k in got))
        self.assertNotIn(("o1", "p1"), G.chain_siblings({**s, "opencode": [(T0 + H, "o1"), (T0 + 3 * H, "p1")]}, kin))
        self.assertEqual(set(G.chain_siblings(s, kin, {"s1"})), {k for k in got if "s1" in k})
        self.assertEqual(len([k for k in got if k[0] == "s1"]), 3)   # the 3 stories just before it, at most

    def test_a_build_is_on_its_versions_line(self):
        """v10.38: a build (GGUF) of a version is matched to the thing of its family stating the same version and
        variant and no build: its stories are paired with the version's (chain_candidates)."""
        from insight_core.markx import identity as I

        class Book:
            def __init__(self, ents):
                self.ents = ents

            def root(self, x):
                return x

            def with_parent_in(self, fam):
                return [x for x, e in self.ents.items() if e.parent == fam]

            def shown_type(self, x):
                return self.ents[x].type
        mk = lambda i, name, **kw: I.Ent(id=i, type="model", name=name, key=name.lower(), **kw)   # noqa: E731
        ents = {"fam": mk("fam", "Qwen", level="family"),
                "oc": mk("oc", "Qwen3.8-27B-opencode-adapted", level="checkpoint", parent="fam", version="3.8",
                         variant="opencode-adapted"),
                "gguf": mk("gguf", "Qwen3.8-27B-opencode-adapted-GGUF", level="checkpoint", parent="fam",
                           version="3.8", variant="opencode-adapted", build="GGUF"),
                "pi": mk("pi", "Qwen3.8-27B-pi-adapted", level="checkpoint", parent="fam", version="3.8",
                         variant="pi-adapted"),
                "pigguf": mk("pigguf", "Qwen3.8-27B-pi-adapted-GGUF", level="checkpoint", parent="fam",
                             version="3.8", variant="pi-adapted", build="GGUF"),
                "lost": mk("lost", "Qwen 9 Q4", level="checkpoint", parent="fam", version="9", build="Q4")}
        # the server's case: the adapters are checkpoints stating no build, their GGUFs checkpoints stating one
        self.assertEqual(G.chain_builds(Book(ents), ents), {"gguf": "oc", "pigguf": "pi"})   # "lost": no version
        ents["snap"] = mk("snap", "Qwen3.8-27B-pi-adapted 0324", level="checkpoint", parent="fam", version="3.8",
                          variant="pi-adapted")
        self.assertEqual(G.chain_builds(Book(ents), ents)["pigguf"], "pi")   # two no-build checkpoints: the lower id
        self.assertNotIn("snap", G.chain_builds(Book(ents), ents))           # a checkpoint is never another's build
        ents["piv"] = mk("piv", "Qwen3.8 pi-adapted", level="variant", parent="fam", version="3.8", variant="pi-adapted")
        self.assertEqual(G.chain_builds(Book(ents), ents)["pigguf"], "piv")  # a variant first
        self.assertEqual(G.chain_builds(Book(ents), ents)["snap"], "piv")    # a dated snapshot on its variant's line
        self.assertEqual(G.chain_kin(Book(ents), ["oc", "pi", "fam"]), {"oc": "fam", "pi": "fam"})

    def test_a_sibling_question_shows_both_things(self):
        text = G.chain_question({"name": "Orbit 2 Small", "type": "model", "maker": "Vantor Labs"},
                                ("Vantor releases Orbit 2 Small", [line(T0, "Introducing Orbit 2 Small and Large")]),
                                ("Vantor releases Orbit 2 Large", [line(T0 + H, "Orbit 2 Large")]),
                                {"name": "Orbit 2 Large", "type": "model", "maker": "Vantor Labs"})
        self.assertEqual(text.splitlines()[:2], ['THING OF THE EARLIER STORY: "Orbit 2 Small" (model, by Vantor Labs)',
                                                 'THING OF THE LATER STORY: "Orbit 2 Large" (model, by Vantor Labs)'])
        self.assertNotIn("\nTHING:", text)

    def test_an_edge_needs_its_runs_to_agree(self):
        one = [("c1", {"relation": "same_release", "reason": "the launch, then its benchmarks"})]
        self.assertIsNone(G.chain_verdict(one, runs=2))
        two = one + [("c2", {"relation": "same_release", "reason": "the same release"})]
        v = G.chain_verdict(two, runs=2)
        self.assertEqual((v["relation"], v["call"], v["reason"], v["runs"]),
                         ("same_release", "c1", "the launch, then its benchmarks", ["same_release", "same_release"]))
        split = one + [("c2", {"relation": "unrelated", "reason": "two things"})]
        self.assertEqual(G.chain_verdict(split, runs=2)["relation"], G.UNKNOWN)

    def test_the_question_shows_both_stories_and_the_gap(self):
        text = G.chain_question({"name": "Orbit 2 Small", "type": "model", "maker": "Vantor Labs"},
                                ("Vantor releases Orbit 2 Small", [line(T0, "Introducing Orbit 2 Small"),
                                                                   line(T0 + H, "Orbit 2 Small scores 31", "actor")]),
                                ("Vantor opens Orbit 2 Small's weights", [line(T0 + 7 * D, "Orbit 2 Small weights")]))
        self.assertEqual(text.splitlines()[0], 'THING: "Orbit 2 Small" (model, by Vantor Labs)')
        self.assertIn('EARLIER STORY: "Vantor releases Orbit 2 Small" (2100-01-05 to 2100-01-05, 2 posts)', text)
        self.assertIn("- 2100-01-05 · Example · actor: Orbit 2 Small scores 31", text)
        self.assertIn('LATER STORY: "Vantor opens Orbit 2 Small\'s weights" (2100-01-12 to 2100-01-12, 1 posts)', text)
        self.assertEqual(text.splitlines()[-1], "GAP: the later story starts 7 days after the earlier one")
        # the stop question shows a story the same way (stops.story_lines)
        self.assertIn('STORY: "Vantor releases Orbit 2 Small" (2100-01-05 to 2100-01-05, 1 posts)',
                      ST.question({"name": "Orbit 2 Small"}, "Vantor releases Orbit 2 Small", [line(T0, "x")]))

    def test_the_kind_its_guide_and_schema(self):
        import hashlib
        import pathlib
        k = schemas.KINDS["chain"]
        self.assertEqual((k.guide, k.subject), ("chain-v3", "story_story"))   # v10.38: v3 (v1, v2 kept, frozen)
        self.assertEqual(G.CHAIN_GUIDE, k.guide)
        self.assertIn("chain-v1", schemas.answer_guides("chain"))             # its tasks kept and read
        self.assertIn("chain-v2", schemas.answer_guides("chain"))
        v3 = (pathlib.Path(G.__file__).parent / "guides" / "chain-v3.md").read_text()
        v2 = (pathlib.Path(G.__file__).parent / "guides" / "chain-v2.md").read_text()
        for v in (v2, v3):
            self.assertIn("a result achieved WITH the thing", v)              # the owner's rule (2026-11-21)
            self.assertIn("demos of what it can do", v)                       # demos and benchmarks stay its release
        self.assertNotIn("same_launch", v3 + " ".join(schemas.CHAIN_RELATIONS))   # one path: same_release
        self.assertIn("One release can launch several sibling things together", v3)   # v10.38: one release, one row
        self.assertIn("its maker's own builds of it", v3)                      # the maker's GGUF is its release
        self.assertNotIn("next_version", schemas.CHAIN_RELATIONS)   # a successor is identity's, never the judge's
        self.assertEqual(tuple(schemas.CHAIN_RELATIONS), G.CHAIN_RELATIONS)
        path = pathlib.Path(G.__file__).parent / "guides" / "chain-v1.md"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), GUIDE_SHA256)
        self.assertIsNone(validate.check("chain", {"reason": "the launch, then its weights",
                                                   "relation": "same_release", "confidence": 80}, "x")[1])
        self.assertIsNotNone(validate.check("chain", {"reason": "  ", "relation": "same_release"}, "x")[1])
        self.assertIsNotNone(validate.check("chain", {"reason": "x", "relation": "next_version"}, "x")[1])
        self.assertIn("chain", tasks.BACKGROUND_PLANNED)
        # measured (0219): asked and stored; no relation passed its bar on the held-out sets, so none is shown
        self.assertEqual(G.chain_config(), {"on": True, "shown": ("same_release",), "one_row": True,
                                            "siblings": SIBLINGS})   # 0267: same_release shown (98.3% [91.1] on 60 stored edges)   # 0236: one row on (owner 2026-11-19: the maker's Q&A is in the row)
        from insight_core.markx import consumers
        self.assertEqual(consumers.feature_of("chain"), "graph")


@base.requires_test_db
class Chains(TL._Db):
    """0165's second case: story A (launch, benchmarks, ranking), story B (weights, a week later), story C (a rival's
    launch that names the model once)."""
    story, read, model, line = TL.OneModelsLine.story, TL.OneModelsLine.read, TL.OneModelsLine.model, TL.OneModelsLine.line

    def setUp(self):
        super().setUp()
        self.switches = {"on": True, "shown": ("same_release",)}
        for patch in (mock.patch.object(G, "chain_config", side_effect=lambda: dict(self.switches)),
                      mock.patch.object(ST, "config", return_value={"stops": True, "stop_types": False,
                                                                    "analysis": False})):
            patch.start()
            self.addCleanup(patch.stop)

    def stops_about(self, x, b_about=True):
        ST.plan(self.cur, now=T0 + 12 * D)
        self.answer_task("stop", {"evidence": "launch", "about": True, "stop": "launch"}, a=x["a"])
        self.answer_task("stop", {"evidence": "weights", "about": b_about, "stop": "weights"}, a=x["b"])

    def chain_tasks(self):
        self.cur.execute("SELECT id, a::text, b::text, input, status FROM mx_tasks WHERE kind = 'chain' ORDER BY created_at")
        return self.cur.fetchall()

    def answer_chain(self, *relations, task=None):
        tid = task or self.chain_tasks()[0][0]
        for rel in relations:
            repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True,
                          answer={"reason": f"{rel}: the launch, then its weights", "relation": rel, "confidence": 80})
        repo.answer_task(self.cur, tid)
        return tid

    def edges(self, current=True):
        self.cur.execute(f"""SELECT a::text, b::text, relation, rule, call_id IS NOT NULL, evidence, valid_to IS NULL
                               FROM mx_connections WHERE a_kind = 'story' AND b_kind = 'story'
                               {"AND valid_to IS NULL" if current else ""} ORDER BY valid_from, relation""")
        return self.cur.fetchall()

    def test_two_stops_of_one_thing_are_asked_once_later_against_earlier(self):
        x = self.line()
        self.assertEqual(G.plan_chains(self.cur)["asked"], 0)          # no stop answer yet: no candidate
        self.stops_about(x)
        out = G.plan_chains(self.cur)
        self.assertEqual((out["pairs"], out["asked"]), (1, 1))
        (_tid, a, b, text, _status), = self.chain_tasks()
        self.assertEqual((a, b), (x["b"], x["a"]))                   # a = the later story, b = the earlier
        self.assertIn('THING: "Orbit 2 Small" (model, by Vantor Labs)', text)
        self.assertIn('EARLIER STORY: "Vantor releases Orbit 2 Small, scoring 31"', text)
        self.assertIn('LATER STORY: "Vantor opens Orbit 2 Small\'s weights"', text)
        self.assertIn("GAP: the later story starts 7 days after the earlier one", text)
        self.assertEqual(G.plan_chains(self.cur)["asked"], 0)          # asked once
        self.switches["on"] = False
        self.cur.execute("DELETE FROM mx_tasks WHERE kind = 'chain'")
        self.assertEqual(G.plan_chains(self.cur), {"pairs": 0, "asked": 0, "again": 0})   # off: nothing asked

    def test_a_story_that_is_not_about_the_thing_is_never_paired(self):
        x = self.line()
        self.stops_about(x, b_about=False)
        self.assertEqual(G.plan_chains(self.cur)["pairs"], 0)

    def test_agreeing_runs_make_an_edge_and_the_chain_reads_it_both_ways(self):
        x = self.line()
        self.stops_about(x)
        G.plan_chains(self.cur)
        self.answer_chain("same_release", "same_release")
        out = G.plan_chains(self.cur)
        self.assertEqual(out["opened"], 1)
        (a, b, rel, rule, called, ev, current), = self.edges()
        self.assertEqual((a, b, rel, rule, called, current), (x["b"], x["a"], "same_release", G.CHAIN_RULE, True, True))
        self.assertEqual(ev["reason"], "same_release: the launch, then its weights")
        self.assertEqual(ev["thing"], self.book().root(x["thing"]))
        later = G.chain(self.cur, x["b"])
        self.assertEqual([(i["story"], i["relation"], i["depth"]) for i in later["before"]], [(x["a"], "same_release", 1)])
        self.assertEqual(later["before"][0]["headline"], "Vantor releases Orbit 2 Small, scoring 31")
        self.assertEqual(later["before"][0]["first_at"], T0.isoformat())
        self.assertEqual(later["after"], [])
        self.assertEqual([i["story"] for i in G.chain(self.cur, x["a"])["after"]], [x["b"]])
        self.assertEqual(G.plan_chains(self.cur)["opened"], 0)        # nothing changed: nothing opened again

    def test_an_earlier_guides_same_release_is_asked_again_under_the_current_guide(self):
        """v10.34 (the black-hole case): chain-v1 joined a result achieved with a model (two open physics problems it
        solved) to the model's release; chain-v2 says such a result is its own happening. A chain-v1 same_release pair
        is asked again under chain-v2 once (a pass under a new guide reads every pair); its edge stands until both of
        the new task's runs are in, then follows them. A chain-v1 pair that made no release edge is not asked again."""
        x = self.line()
        self.stops_about(x)
        G.plan_chains(self.cur)
        (tid, *_), = self.chain_tasks()
        self.cur.execute("UPDATE mx_tasks SET guide = 'chain-v1' WHERE id = %s", (tid,))   # asked before v10.34
        self.answer_chain("same_release", "same_release", task=tid)
        repo.set_setting(self.cur, G.CHAIN_MARK, {"at": (T0 + 12 * D).isoformat()})          # a chain-v1 pass's mark
        out = G.plan_chains(self.cur)
        self.assertEqual((out["opened"], out["asked"]), (1, 1))
        (_v1, *_r), (v2, a, b, _text, status) = self.chain_tasks()
        self.assertEqual((a, b, status), (x["b"], x["a"], "open"))
        self.cur.execute("SELECT guide FROM mx_tasks WHERE id = %s", (v2,))
        self.assertEqual(self.cur.fetchone()[0], G.CHAIN_GUIDE)
        self.assertEqual(repo.get_setting(self.cur, G.CHAIN_MARK)["guide"], G.CHAIN_GUIDE)
        self.assertEqual(G.plan_chains(self.cur)["asked"], 0)                 # asked once
        self.assertEqual([r[2] for r in self.edges()], ["same_release"])      # stands while the new runs wait
        self.answer_chain("unrelated", "unrelated", task=v2)
        G.plan_chains(self.cur)
        self.assertEqual(self.edges(), [])                                    # the new guide's verdict decides
        self.assertEqual([r[2] for r in self.edges(current=False)], ["same_release"])   # closed, kept

    def test_an_earlier_guides_pair_with_no_release_edge_is_not_asked_again(self):
        x = self.line()
        self.stops_about(x)
        G.plan_chains(self.cur)
        (tid, *_), = self.chain_tasks()
        self.cur.execute("UPDATE mx_tasks SET guide = 'chain-v1' WHERE id = %s", (tid,))
        self.answer_chain("development", "development", task=tid)
        repo.set_setting(self.cur, G.CHAIN_MARK, {"at": (T0 + 12 * D).isoformat()})
        self.assertEqual(G.plan_chains(self.cur)["asked"], 0)
        self.assertEqual(len(self.chain_tasks()), 1)

    def test_runs_that_differ_or_unrelated_make_no_edge(self):
        x = self.line()
        self.stops_about(x)
        G.plan_chains(self.cur)
        self.answer_chain("same_release", "development")
        G.plan_chains(self.cur)
        self.assertEqual(self.edges(), [])
        self.cur.execute("DELETE FROM mx_calls WHERE task_id IN (SELECT id FROM mx_tasks WHERE kind = 'chain')")
        self.answer_chain("unrelated", "unrelated")
        G.plan_chains(self.cur)
        self.assertEqual(self.edges(), [])

    def test_a_relation_under_its_bar_is_stored_and_not_shown(self):
        x = self.line()
        self.stops_about(x)
        G.plan_chains(self.cur)
        self.answer_chain("development", "development")
        G.plan_chains(self.cur)
        self.assertEqual([r[2] for r in self.edges()], ["development"])    # stored
        self.assertEqual(G.chain(self.cur, x["b"])["before"], [])           # not shown
        self.assertEqual([i["relation"] for i in G.chain(self.cur, x["b"], relations=["development"])["before"]],
                         ["development"])
        self.assertEqual(G.row_chains(self.cur, {"row": [x["b"]]}), {})     # nor on a News row

    def test_a_news_row_shows_its_earlier_and_later_outside_itself(self):
        """0267: a row's Earlier and Later are the stories one shown edge joins to one of its stories, never its own."""
        x = self.line()
        self.stops_about(x)
        G.plan_chains(self.cur)
        self.answer_chain("same_release", "same_release")
        G.plan_chains(self.cur)
        got = G.row_chains(self.cur, {"weights": [x["b"]], "launch": [x["a"]], "both": [x["a"], x["b"]]})
        self.assertEqual(set(got), {"weights", "launch"})                   # a one-release row holding both: nothing
        (e,) = got["weights"]["before"]
        self.assertEqual((e["story"], e["relation"], e["headline"], e["first_at"]),
                         (x["a"], "same_release", "Vantor releases Orbit 2 Small, scoring 31", T0.isoformat()))
        self.assertEqual(e["reason"], "same_release: the launch, then its weights")
        self.assertEqual((got["weights"]["after"], got["weights"]["before_more"]), ([], 0))
        self.assertEqual([i["story"] for i in got["launch"]["after"]], [x["b"]])
        self.assertEqual(G.row_chains(self.cur, {"weights": [x["b"]]}, shown=0)["weights"]["before_more"], 1)
        self.switches["on"] = False
        self.assertEqual(G.row_chains(self.cur, {"weights": [x["b"]]}), {})

    def test_a_pair_no_longer_proposed_closes_its_edge_and_as_of_still_reads_it(self):
        x = self.line()
        self.stops_about(x)
        G.plan_chains(self.cur)
        self.answer_chain("same_release", "same_release")
        G.plan_chains(self.cur, now=datetime.now(timezone.utc))
        self.cur.execute("SELECT valid_from FROM mx_connections WHERE rule = %s", (G.CHAIN_RULE,))
        opened = self.cur.fetchone()[0]
        # the weights story's stop is asked again and now says it is not about the thing
        tid, _ = tasks.add(self.cur, "stop", "asked again", a=x["b"], b=self.book().root(x["thing"]))
        repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True,
                      answer={"evidence": "about the router", "about": False, "stop": "adoption"})
        repo.answer_task(self.cur, tid)
        self.cur.execute("UPDATE mx_tasks SET created_at = created_at + interval '1 minute' WHERE id = %s", (tid,))
        later = opened + timedelta(minutes=5)
        self.assertEqual(G.sync_chains(self.cur, now=later)["closed"], 1)
        (_a, _b, _rel, _rule, _called, _ev, current), = self.edges(current=False)
        self.assertFalse(current)                                          # closed, kept
        self.assertEqual(G.chain(self.cur, x["b"], as_of=later + timedelta(minutes=1))["before"], [])
        self.assertEqual([i["story"] for i in G.chain(self.cur, x["b"], as_of=opened + timedelta(minutes=1))["before"]],
                         [x["a"]])                                          # what was known then
        self.assertEqual(G.chain(self.cur, x["b"], as_of=opened - timedelta(minutes=1))["before"], [])

    def test_the_chain_walks_several_links_and_never_loops(self):
        x = self.line()
        run = repo.start_run(self.cur, code_version="test", config={})
        c = x["c"]
        now = datetime.now(timezone.utc) - H
        for a, b in ((x["b"], x["a"]), (c, x["b"]), (x["a"], c)):   # a loop a <- b <- c <- a
            repo.open_connection(self.cur, a_kind="story", a=a, b_kind="story", b=b, relation="same_release",
                                 run_id=run, rule=G.CHAIN_RULE, evidence={"reason": "r"}, at=now)
        got = G.chain(self.cur, c)
        self.assertEqual([(i["story"], i["depth"], i["via"]) for i in got["before"]],
                         [(x["b"], 1, c), (x["a"], 2, x["b"])])
        self.assertEqual([(i["story"], i["depth"]) for i in got["after"]], [(x["a"], 1), (x["b"], 2)])
        self.assertEqual(len(G.chain(self.cur, c, depth=1)["before"]), 1)

    def test_the_decision_run_never_closes_a_chain_edge(self):
        x = self.line()
        self.stops_about(x)
        G.plan_chains(self.cur)
        self.answer_chain("same_release", "same_release")
        G.plan_chains(self.cur)
        run = repo.start_run(self.cur, code_version="test", config={})
        decide.persist_connections(self.cur, run, [], {x["a"], x["b"]}, datetime.now(timezone.utc))
        self.assertEqual(len(self.edges()), 1)
        from insight_core.markx import built
        self.assertEqual(built._connected(self.cur, [x["a"], x["b"]]), set())   # nor reads it as decide's own


@base.requires_test_db
class TheWorkerAndThePage(_Api):
    """The worker's path (lease, answer, asked again until two runs) and the story page's `chain` field."""

    def test_a_chain_question_is_asked_twice_and_the_story_page_shows_the_link(self):
        early, late = self.post("Vantor releases Orbit 2 Small"), self.post("Vantor opens Orbit 2 Small's weights")
        with self.conn.transaction():
            sids = []
            for p, head in ((early, "Vantor releases Orbit 2 Small"), (late, "Vantor opens its weights")):
                self.cur.execute("INSERT INTO mx_stories (first_at, headline) VALUES (now(), %s) RETURNING id::text",
                                 (head,))
                sids.append(self.cur.fetchone()[0])
                self.cur.execute("INSERT INTO mx_story_posts (story_id, post_id, role, reason) VALUES (%s, %s, 'member', 'test')",
                                 (sids[-1], p))
            tid, _ = tasks.add(self.cur, "chain", "THING: ...", a=sids[1], b=sids[0])
        ans = {"reason": "the launch, then its weights", "relation": "same_release", "confidence": 80}
        for n in range(2):
            status, body = self.lease("chain")
            self.assertEqual(status, 200)
            self.assertEqual([t["id"] for t in body["tasks"]], [str(tid)])
            self.assertEqual(self.answer((tid, ans))[0], 200)
            self.assertEqual(self.row(tid)["status"], "open" if n == 0 else "answered")   # asked again once
        with self.conn.transaction():
            run = repo.start_run(self.cur, code_version="test", config={})
            repo.open_connection(self.cur, a_kind="story", a=sids[1], b_kind="story", b=sids[0], relation="same_release",
                                 run_id=run, rule=G.CHAIN_RULE, evidence={"reason": "the launch, then its weights"},
                                 at=datetime.now(timezone.utc) - H)
        with mock.patch.object(G, "chain_config", return_value={"on": True, "shown": ("same_release",)}):
            status, body = call("GET", f"/api/markx/stories/{sids[1]}")
            self.assertEqual(status, 200)
            self.assertEqual([(i["story"], i["relation"], i["reason"]) for i in body["chain"]["before"]],
                             [(sids[0], "same_release", "the launch, then its weights")])
            status, body = call("GET", f"/api/markx/stories/{sids[1]}",
                                query={"as_of": (datetime.now(timezone.utc) - 2 * H).isoformat()})
            self.assertEqual(body["chain"]["before"], [])
        with mock.patch.object(G, "chain_config", return_value={"on": False, "shown": ("same_release",)}):
            self.assertEqual(call("GET", f"/api/markx/stories/{sids[1]}")[1]["chain"]["before"], [])


if __name__ == "__main__":
    unittest.main()
