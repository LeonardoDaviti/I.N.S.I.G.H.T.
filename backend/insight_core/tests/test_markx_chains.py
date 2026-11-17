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
        self.assertEqual((k.guide, k.subject), ("chain-v1", "story_story"))
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
        self.assertEqual(G.chain_config(), {"on": True, "shown": ()})
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
