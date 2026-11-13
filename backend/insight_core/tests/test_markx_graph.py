"""0131 (Stealth v10.6): Stalker's first edges. Authors' links as edges (another source's p 1.0, the same source's
p 0.9; none under 30 days, none for boilerplate; a target stored later becomes an edge with no re-read; a link that
stops resolving closes its edge), the `relate` kind (planned and capped, three runs and their majority, "unknown" on
a split; the judge refines an author-link edge and never removes it), next_version from entity identity, the post
panel's Before list with its marks and labels, and the invariant. Synthetic data only; the DB tests run on a database
whose name ends in _test."""
from __future__ import annotations

import hashlib
import math
import random
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from insight_core.checks import invariants
from insight_core.markx import decide, graph, repo, schemas, tasks, validate
from insight_core.tests.test_markx_api import _Api, call

NOW = datetime.now(timezone.utc)
DAY = timedelta(days=1)
FROZEN_JUDGE_MD5 = "5a534f99860e519210c988137298f426"   # G2's g2_judge_v3.md, ported unchanged


def answer(relation, reason="The newer post builds on the older one."):
    return {"reason": reason, "relation": relation, "confidence": 70}


class TheKind(unittest.TestCase):
    def test_relate_is_the_frozen_judge_with_its_seven_relations(self):
        kind = schemas.KINDS["relate"]
        self.assertEqual((kind.guide, kind.subject), ("relate-v1", "post_post"))
        body = schemas.guide_body("relate-v1")
        self.assertEqual(hashlib.md5(body.encode("utf-8")).hexdigest(), FROZEN_JUDGE_MD5)
        for rel in schemas.RELATE_RELATIONS:
            self.assertIn(f"`{rel}`", body)
        self.assertIn("relate", tasks.PLANNERS)

    def test_the_answer_is_checked(self):
        self.assertIsNone(validate.check("relate", answer("builds_on"), "x")[1])
        self.assertIsNone(validate.check("relate", {"reason": "Same launch.", "relation": "same_event"}, "x")[1])
        self.assertIn("relation", validate.check("relate", answer("development"), "x")[1])
        self.assertIn("reason", validate.check("relate", {"relation": "background"}, "x")[1])
        self.assertIn("reason", validate.check("relate", {"reason": "  ", "relation": "background"}, "x")[1])

    def test_the_majority_of_three_and_unknown_on_a_split(self):
        self.assertIsNone(graph.verdict([("c1", answer("builds_on")), ("c2", answer("builds_on"))]))
        v = graph.verdict([("c1", answer("background")), ("c2", answer("builds_on")), ("c3", answer("builds_on"))])
        self.assertEqual((v["relation"], v["p"], v["call"], len(v["reasons"])), ("builds_on", 0.6667, "c2", 3))
        v = graph.verdict([("c1", answer("same_event"))] * 3)
        self.assertEqual((v["relation"], v["p"]), ("same_event", 1.0))
        v = graph.verdict([("c1", answer("background")), ("c2", answer("builds_on")), ("c3", answer("follows_up"))])
        self.assertEqual((v["relation"], v["p"]), ("unknown", None))

    def test_a_first_unrelated_settles_the_pair_alone(self):
        # 0191: ask once; a second and third time only when the first is not "unrelated"
        v = graph.verdict([("c1", answer("unrelated", "Different events."))])
        self.assertEqual((v["relation"], v["p"], v["call"], v["runs"], v["reason"]),
                         ("unrelated", None, "c1", ["unrelated"], "Different events."))
        self.assertIsNone(graph.verdict([("c1", answer("background"))]))
        self.assertIsNone(graph.verdict([("c1", answer("builds_on"))]))
        # three runs already asked keep their majority, whatever the first said
        v = graph.verdict([("c1", answer("unrelated")), ("c2", answer("builds_on")), ("c3", answer("builds_on"))])
        self.assertEqual((v["relation"], v["p"]), ("builds_on", 0.6667))

    def test_the_input_is_g2s_render(self):
        p = tasks.Post(id="1", kind="site", source="Example Site", source_id="s", at=NOW, title="Widget 4.1",
                       text="word " * 400)
        q = tasks.Post(id="2", kind="telegram", source="Example Channel", source_id="t", at=NOW, title="", text="")
        text = graph.relate_input(p, q, newer_at=NOW, older_at=NOW - 40 * DAY, anchor="as I wrote in March", docs=[])
        self.assertTrue(text.startswith(f"NEWER POST — [site | Example Site] {NOW.isoformat()[:10]}\nTitle: Widget 4.1\nText: word"))
        self.assertIn("…\n\nOLDER POST — [telegram | Example Channel]", text)
        self.assertIn("Title: (none)\nText: (no text)", text)
        self.assertTrue(text.endswith('EVIDENCE\n- The newer post links to the older post: yes, around the words '
                                      '"as I wrote in March"\n- Outside pages both posts link: none'))
        self.assertTrue(graph.linked(text))
        self.assertFalse(graph.linked(graph.relate_input(p, q, newer_at=NOW, older_at=NOW, anchor=None,
                                                         docs=["example.com/paper"])))

    def test_versions_order_by_their_numbers(self):
        self.assertEqual(graph._vnorm([4, 1]), (4, 1))
        self.assertEqual(graph._vnorm(["k", 3, 1]), (3, 1))
        self.assertEqual(graph._vnorm([5, 0]), (5,))
        self.assertIsNone(graph._vnorm(["pro"]))
        self.assertIsNone(graph._vnorm(None))


class _Graph(_Api):
    def setUp(self):
        super().setUp()
        self.run = repo.start_run(self.cur, code_version="test", config={})

    def at(self, days):
        return NOW - days * DAY

    def ref(self, post, target_url, *, position=0, reason="As I wrote back then, this is how it works.",
            kind="sentence", boilerplate=False):
        self.cur.execute("""INSERT INTO post_refs (post_id, target_address, href, position, reason, reason_kind, boilerplate)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)""", (post, target_url, target_url, position, reason, kind,
                                                                    boilerplate))

    def url(self, post):
        self.cur.execute("SELECT url FROM posts WHERE id = %s", (post,))
        return self.cur.fetchone()[0]

    def stage(self, now=None, **kw):
        with self.conn.transaction():
            return graph.stage(self.cur, now=now or datetime.now(timezone.utc), run_id=self.run, **kw)

    def edges(self, current=True):
        self.cur.execute(f"""SELECT a::text, b::text, relation, rule, p, call_id IS NOT NULL, evidence, valid_to IS NULL
                               FROM mx_connections WHERE a_kind = 'post' AND b_kind = 'post'
                               {"AND valid_to IS NULL" if current else ""} ORDER BY valid_from, relation""")
        return self.cur.fetchall()


class AuthorLinks(_Graph):
    def test_an_older_stored_post_of_either_source_is_an_edge_none_under_30_days_none_for_boilerplate(self):
        other = self.post(source=self.other, at=self.at(60))
        own = self.post(at=self.at(45))
        recent = self.post(source=self.other, at=self.at(10))
        signed = self.post(source=self.other, at=self.at(90))
        newer = self.post(at=self.at(0))
        self.ref(newer, self.url(other), position=0)
        self.ref(newer, self.url(own), position=1, reason=None, kind=None)
        self.ref(newer, self.url(recent), position=2)
        self.ref(newer, self.url(signed), position=3, boilerplate=True)
        self.ref(newer, "https://test.invalid/nowhere", position=4)
        self.stage()
        got = {(b, rel, rule, p): ev for a, b, rel, rule, p, _call, ev, _cur in self.edges()}
        self.assertEqual(set(got), {(other, "refers_back", "author_link_other", 1.0),
                                    (own, "refers_back", "author_link_own", 0.9)})
        ev = got[(other, "refers_back", "author_link_other", 1.0)]
        self.assertEqual((ev["href"], ev["address"], ev["reason"], ev["reason_kind"]),
                         (self.url(other), self.url(other), "As I wrote back then, this is how it works.", "sentence"))
        self.assertEqual(self.edges()[0][0], newer)
        # the invariant: every current author-link edge's ref exists and resolves
        found, of = invariants._markx_author_links(invariants.Run("", self.cur, NOW))
        self.assertEqual((found, of), ([], 2))

    def test_a_target_stored_later_becomes_an_edge_with_no_re_read(self):
        address = f"https://test.invalid/later/{uuid.uuid4().hex}"
        newer = self.post(at=self.at(0))
        self.ref(newer, address)
        self.stage()
        self.assertEqual(self.edges(), [])
        # nothing of the newer post changes: only the older post is stored
        self.cur.execute("UPDATE posts SET refs_scanned_at = now() - interval '3 days' WHERE id = %s", (newer,))
        self.cur.execute("UPDATE post_refs SET created_at = now() - interval '3 days' WHERE post_id = %s", (newer,))
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, 'The older page', 'Its words.', %s) RETURNING id",
                         (self.other, address, address, self.at(200)))
        older = str(self.cur.fetchone()[0])
        out = self.stage()
        self.assertEqual([(a, b, rule) for a, b, _r, rule, *_ in self.edges()], [(newer, older, "author_link_other")])
        self.assertEqual(out["links"]["opened"], 1)

    def test_a_link_that_stops_resolving_or_becomes_boilerplate_closes_its_edge(self):
        o1, o2 = self.post(source=self.other, at=self.at(60)), self.post(source=self.other, at=self.at(70))
        newer = self.post(at=self.at(0))
        self.ref(newer, self.url(o1), position=0)
        self.ref(newer, self.url(o2), position=1)
        self.stage()
        self.assertEqual(len(self.edges()), 2)
        self.cur.execute("UPDATE post_refs SET valid_to = now() WHERE post_id = %s AND target_address = %s",
                         (newer, self.url(o1)))
        self.cur.execute("UPDATE post_refs SET boilerplate = true WHERE post_id = %s AND target_address = %s",
                         (newer, self.url(o2)))
        found, of = invariants._markx_author_links(invariants.Run("", self.cur, NOW))
        self.assertEqual(of, 2)
        self.assertEqual(len(found), 2)                   # the invariant sees both before the run closes them
        self.stage()
        self.assertEqual(self.edges(), [])
        rows = self.edges(current=False)
        self.assertEqual(len(rows), 2)                    # kept, closed
        self.assertFalse(any(r[7] for r in rows))

    def test_the_backfill_is_resumable_and_runs_once(self):
        olders = [self.post(source=self.other, at=self.at(100 + n)) for n in range(5)]
        for o in olders:
            self.ref(self.post(at=self.at(1)), self.url(o))
        with self.conn.transaction():
            first = graph.backfill(self.cur, now=NOW, run_id=self.run, deadline=0, batch=2)
        self.assertEqual((first["done"], first["opened"]), (False, 2))
        with self.conn.transaction():
            rest = graph.backfill(self.cur, now=NOW, run_id=self.run, batch=2)
        self.assertEqual((rest["done"], rest["opened"], rest["total"]["opened"]), (True, 3, 5))
        with self.conn.transaction():
            self.assertEqual(graph.backfill(self.cur, now=NOW, run_id=self.run), {"done": True, "ran": False})
        self.assertEqual(len(self.edges()), 5)

    def test_the_decision_run_never_closes_the_graphs_edges(self):
        older = self.post(source=self.other, at=self.at(60))
        newer = self.post(at=self.at(0))
        self.ref(newer, self.url(older))
        self.stage()
        with self.conn.transaction():
            decide.persist_connections(self.cur, self.run, [], {newer, older}, NOW)
        self.assertEqual(len(self.edges()), 1)


def unit(seed, noise=0.0, base=None):
    rnd = random.Random(seed)
    v = list(base) if base else [rnd.gauss(0, 1) for _ in range(1024)]
    if noise:
        v = [x + rnd.gauss(0, noise) for x in v]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


class TheJudge(_Graph):
    def entity(self, name, *, level="thing", parent=None, version=None):
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, parent, version_key)
                            VALUES ('model', %s, %s, %s, %s, %s::jsonb) RETURNING id::text""",
                         (name, name.lower(), level, parent, None if version is None else str(list(version))))
        return self.cur.fetchone()[0]

    def subject(self, post, entity, name="Widget"):
        with self.conn.transaction():
            tid, _ = tasks.entities_task(self.cur, post)
            call_id = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="m", valid=True, answer={})
            repo.add_mentions(self.cur, post_id=post, guide=schemas.KINDS["entities"].guide, call_id=call_id,
                              mentions=[{"span": name, "name": name, "name_key": name.lower(), "type": "model",
                                         "role": "subject"}])
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (entity, post))

    def vector(self, post, v):
        repo.put_embedding(self.cur, post_id=post, model="bge-m3", text_hash=uuid.uuid4().hex, vector=v)

    def same_subject(self, *, days=60, cos_noise=0.01):
        e = self.entity("Widget")
        base = unit(1)
        older, newer = self.post(source=self.other, at=self.at(days)), self.post(at=self.at(0))
        for p, n in ((older, 0.0), (newer, cos_noise)):
            self.subject(p, e)
            self.vector(p, unit(2, n, base))
        return newer, older

    def answer_runs(self, kind, relations):
        """Lease and answer the relate task once a run, as the worker does: (task id, the reopen statuses)."""
        statuses = []
        tid = None
        for rel in relations:
            _, body = self.lease(kind)
            self.assertEqual(len(body["tasks"]), 1, body)
            tid = body["tasks"][0]["id"]
            self.assertEqual(self.answer((tid, answer(rel)))[1]["valid"], 1)
            statuses.append(self.row(tid)["status"])
        return tid, statuses

    def test_a_same_subject_pair_is_planned_asked_three_times_and_stored_uncertain(self):
        newer, older = self.same_subject()
        out = self.stage()
        self.assertEqual((out["relate"]["candidates"] + out["relate"]["backfill"].get("candidates", 0) >= 1,
                          out["relate"]["planned"]), (True, 1))
        self.cur.execute("SELECT a::text, b::text, input FROM mx_tasks WHERE kind = 'relate'")
        a, b, text = self.cur.fetchone()
        self.assertEqual((a, b), (newer, older))
        self.assertIn("- The newer post links to the older post: no", text)
        tid, statuses = self.answer_runs("relate", ["follows_up", "background", "follows_up"])
        self.assertEqual(statuses, ["open", "open", "answered"])      # asked again until three answers
        self.stage()
        (a, b, rel, rule, p, has_call, ev, _cur), = self.edges()
        self.assertEqual((a, b, rel, rule, round(p, 4), has_call), (newer, older, "follows_up", None, 0.6667, True))
        self.assertTrue(ev["uncertain"])
        self.assertEqual(len(ev["reasons"]), 3)
        status, panel = call("GET", f"/api/markx/posts/{newer}")
        self.assertEqual(status, 200)
        (row,) = panel["before"]
        self.assertEqual((row["post_id"], row["relation"], row["uncertain"], row["rule"], row["label"]),
                         (older, "follows_up", True, None, None))
        self.assertEqual(row["reason"], "The newer post builds on the older one.")
        self.assertEqual(panel["connections"], [])                    # the graph's edges are the Before list's
        # the owner's ✓ / ✗ on it
        got = call("POST", "/api/markx/labels/edge", body={"newer": newer, "older": older, "answer": "wrong"})[1]
        self.assertEqual((got["label"], got["relation"]), ("wrong", "follows_up"))
        self.assertEqual(call("GET", f"/api/markx/posts/{newer}")[1]["before"][0]["label"], "wrong")
        self.assertEqual(call("POST", "/api/markx/labels/edge", body={"newer": newer, "older": older, "answer": "maybe"})[0], 400)
        self.assertEqual(call("POST", "/api/markx/labels/edge", body={"newer": older, "older": newer, "answer": "right"})[0], 404)

    def test_a_first_unrelated_is_asked_once_and_makes_no_edge(self):
        self.same_subject()
        self.stage()
        tid, statuses = self.answer_runs("relate", ["unrelated"])
        self.assertEqual(statuses, ["answered"])                       # 0191: never asked again
        out = self.stage()
        self.assertEqual(self.edges(), [])
        self.assertEqual(out["relate"]["settled"], 1)

    def test_a_split_is_unknown_and_makes_no_edge(self):
        self.same_subject()
        self.stage()
        self.answer_runs("relate", ["follows_up", "background", "builds_on"])
        out = self.stage()
        self.assertEqual(self.edges(), [])
        self.assertEqual(out["relate"]["settled"], 1)

    def test_no_candidate_outside_the_window_or_below_the_cosine(self):
        self.same_subject(days=200)
        self.same_subject(days=20)
        self.same_subject(cos_noise=0.2)
        out = self.stage()
        self.assertEqual(out["relate"]["planned"], 0)

    def test_the_planner_is_capped_by_the_open_tasks(self):
        for _ in range(3):
            self.same_subject()
        out = self.stage(open_cap=2)
        self.assertEqual(out["relate"]["planned"], 2)
        self.assertEqual(self.stage(open_cap=2)["relate"]["planned"], 0)   # two wait: none more
        self.assertEqual(self.stage(open_cap=3)["relate"]["planned"], 1)

    def test_the_judge_refines_an_author_link_edge_and_never_removes_it(self):
        o1, o2 = self.post(source=self.other, at=self.at(60)), self.post(source=self.other, at=self.at(80))
        n1, n2 = self.post(at=self.at(0)), self.post(at=self.at(1))
        self.ref(n1, self.url(o1))
        self.ref(n2, self.url(o2))
        out = self.stage()
        self.assertEqual(out["relate"]["planned"], 2)                 # every author-link edge is asked
        self.cur.execute("SELECT id::text, a::text, input FROM mx_tasks WHERE kind = 'relate'")
        by = {a: (tid, text) for tid, a, text in self.cur.fetchall()}
        self.assertIn('yes, around the words "As I wrote back then, this is how it works."', by[n1][1])
        for tid, rels in ((by[n1][0], ["builds_on", "builds_on", "background"]),
                          (by[n2][0], ["background", "unrelated", "background"])):
            for rel in rels:
                self.cur.execute("UPDATE mx_tasks SET status = 'leased', lease_until = now() + interval '5 minutes', "
                                 "leased_by = 'device-1' WHERE id = %s", (tid,))
                self.assertEqual(self.answer((tid, answer(rel)))[1]["valid"], 1)
        self.stage()
        got = {(a, b): (rel, rule, p, has_call, ev) for a, b, rel, rule, p, has_call, ev, _c in self.edges()}
        self.assertEqual(got[(n1, o1)][:4], ("builds_on", "author_link_other", 1.0, True))   # refined
        self.assertEqual(got[(n1, o1)][4]["judge"]["runs"], ["builds_on", "builds_on", "background"])
        self.assertEqual(got[(n2, o2)][:3], ("refers_back", "author_link_other", 1.0))     # "background": kept
        closed = [r for r in self.edges(current=False) if not r[7]]
        self.assertEqual([(r[0], r[2]) for r in closed], [(n1, "refers_back")])               # the refined one's past
        self.assertEqual(invariants._markx_author_links(invariants.Run("", self.cur, NOW)), ([], 2))
        before = call("GET", f"/api/markx/posts/{n1}")[1]["before"]
        self.assertEqual([(r["relation"], r["uncertain"], r["reason"]) for r in before],
                         [("builds_on", False, "As I wrote back then, this is how it works.")])

    def test_next_version_from_identity_replaces_a_judges(self):
        fam = self.entity("Widget", level="family")
        v4 = self.entity("Widget 4", level="version", parent=fam, version=(4,))
        v41 = self.entity("Widget 4.1", level="version", parent=fam, version=(4, 1))
        v5 = self.entity("Widget 5", level="version", parent=fam, version=(5,))
        old4 = [self.post(source=self.other, at=self.at(400 + n)) for n in range(5)]
        old41 = self.post(source=self.other, at=self.at(200))
        new5, soon5 = self.post(at=self.at(0)), self.post(at=self.at(190))
        for p in old4:
            self.subject(p, v4)
        self.subject(old41, v41, "Widget 4.1")
        self.subject(new5, v5, "Widget 5")
        self.subject(soon5, v5, "Widget 5")
        # a judge's next_version on the pair first
        with self.conn.transaction():
            tid, _ = tasks.add(self.cur, "relate", "a question", a=new5, b=old41)
            calls = [repo.add_call(self.cur, task_id=tid, executor="claude-code", model="m", valid=True,
                                   answer=answer("next_version")) for _ in range(3)]
            graph._open(self.cur, [{"a": new5, "b": old41, "relation": "next_version", "p": 1.0, "call": calls[0],
                                    "rule": None, "evidence": {"uncertain": True}}], run_id=self.run, now=NOW)
        self.stage()
        got = {(a, b): (rel, rule, ev) for a, b, rel, rule, _p, _c, ev, _cur in self.edges()}
        # 4.1 -> 5 (200 days back); the other 5 is 10 days after 4.1: none; 4 -> 4.1: 4's 3 earliest posts
        self.assertEqual(set(got), {(new5, old41)} | {(old41, o) for o in old4[2:]})
        self.assertEqual(got[(new5, old41)][:2], ("next_version", "entity_next_version"))   # the judge's closed
        self.assertEqual((got[(new5, old41)][2]["newer"], got[(new5, old41)][2]["older"]), ("widget 5", "widget 4.1"))

    def test_next_version_takes_the_predecessors_earliest_posts_30_days_back(self):
        fam = self.entity("Gadget", level="family")
        v1 = self.entity("Gadget 1", level="version", parent=fam, version=(1,))
        v2 = self.entity("Gadget 2", level="version", parent=fam, version=(2,))
        olds = [self.post(source=self.other, at=self.at(100 + n)) for n in range(5)]
        late = self.post(source=self.other, at=self.at(10))
        new = self.post(at=self.at(0))
        for p in olds + [late]:
            self.subject(p, v1, "Gadget 1")
        self.subject(new, v2, "Gadget 2")
        self.stage()
        got = sorted(b for a, b, rel, rule, *_ in self.edges() if rule == "entity_next_version")
        self.assertEqual(got, sorted(olds[2:]))                       # the 3 earliest (102-104 days back)
        before = call("GET", f"/api/markx/posts/{new}")[1]
        self.assertEqual([r["post_id"] for r in before["before"]], [olds[4], olds[3], olds[2]])   # oldest first
        self.assertEqual(before["before"][0]["reason"], "Gadget 2 is the next version after Gadget 1")


class TheBeforeList(_Graph):
    def test_oldest_first_capped_at_ten_with_the_rest_counted(self):
        newer = self.post(at=self.at(0))
        olders = [self.post(source=self.other, at=self.at(40 + n)) for n in range(13)]
        for n, o in enumerate(olders):
            self.ref(newer, self.url(o), position=n)
        self.stage()
        status, panel = call("GET", f"/api/markx/posts/{newer}")
        self.assertEqual(status, 200)
        self.assertEqual(len(panel["before"]), 10)
        self.assertEqual(panel["before_more"], 3)
        self.assertEqual([r["post_id"] for r in panel["before"]], olders[::-1][:10])
        row = panel["before"][0]
        self.assertEqual(set(row), {"post_id", "relation", "rule", "p", "reason", "uncertain", "at", "title", "source",
                                    "label", "byline"})   # 0185: who wrote it, via whom
        self.assertFalse(row["uncertain"])
        self.assertEqual(call("GET", f"/api/markx/posts/{olders[0]}")[1]["before"], [])   # the older post has none


class SeriesNavigation(_Graph):
    """0134: a same-source author link marked series navigation (post_refs.navigation) is next_in_series, rule series,
    never refers_back, and the judge never asks about it; the flag changing re-reads the edge."""

    def test_a_navigation_link_is_next_in_series_and_never_judged(self):
        part1 = self.post("Part 1: the scheduler", at=self.at(60))
        other = self.post(source=self.other, at=self.at(50))
        part2 = self.post("Part 2: the scheduler", at=self.at(0))
        self.ref(part2, self.url(part1), position=0)
        self.ref(part2, self.url(other), position=1)
        self.cur.execute("UPDATE post_refs SET navigation = true, navigation_at = now() WHERE post_id = %s "
                         "AND target_address = %s", (part2, self.url(part1)))
        self.stage()
        got = {(b, rel, rule) for _a, b, rel, rule, *_ in self.edges()}
        self.assertEqual(got, {(part1, "next_in_series", "series"), (other, "refers_back", "author_link_other")})
        self.cur.execute("SELECT b::text FROM mx_tasks WHERE kind = 'relate'")
        self.assertNotIn(part1, [r[0] for r in self.cur.fetchall()])   # the stage planned; never the series edge
        found, of = invariants._markx_author_links(invariants.Run("", self.cur, NOW))
        self.assertEqual((found, of), ([], 2))
        self.assertEqual({r["post_id"]: r["rule"] for r in graph.before(self.cur, part2)["items"]},
                         {part1: "series", other: "author_link_other"})

    def test_the_flag_turning_off_reopens_it_as_refers_back(self):
        part1 = self.post("Part 1: the scheduler", at=self.at(60))
        part2 = self.post("Part 2: the scheduler", at=self.at(0))
        self.ref(part2, self.url(part1))
        self.cur.execute("UPDATE post_refs SET navigation = true WHERE post_id = %s", (part2,))
        self.stage()
        self.cur.execute("UPDATE posts SET refs_scanned_at = now() - interval '3 days' WHERE id = %s", (part2,))
        self.cur.execute("UPDATE post_refs SET created_at = now() - interval '3 days', navigation = false, "
                         "navigation_at = now() + interval '1 minute' WHERE post_id = %s", (part2,))
        self.stage(now=datetime.now(timezone.utc) + timedelta(minutes=2))
        self.assertEqual([(rel, rule) for _a, _b, rel, rule, *_ in self.edges()], [("refers_back", "author_link_own")])
        self.assertEqual(sorted((rel, cur) for _a, _b, rel, _r, _p, _c, _e, cur in self.edges(current=False)),
                         [("next_in_series", False), ("refers_back", True)])   # closed, never deleted


if __name__ == "__main__":
    unittest.main()
