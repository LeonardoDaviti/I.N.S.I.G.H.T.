"""Mark X Shadow's decisions (issue 0086 E): the prototype's rules on small synthetic stories (rule A, rule B, roundups
as mentions, the two-event guard, joins at 0.6, merges at 0.85, the second pass, typed connections, the late-post
table), then the job on a test database: the questions it asks as tasks, the answers it reads, the stories and
memberships it writes (closed, never deleted), Mark X News and its tags, Mark IX's tables untouched, the switch.

The reproduction on the prototype's recorded answers and v9.12 stories is private (it reads real posts); its numbers
are in 0086 E's Built section. The DB tests run only on a database whose name ends in _test."""
from __future__ import annotations

import json
import os
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest import mock

import psycopg
from psycopg import sql

from insight_core.markx import decide as D
from insight_core.markx import news as N
from insight_core.markx import repo, schemas, tasks
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES

T = datetime(2100, 3, 1, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)
LONG = 30   # words: over rule A's 20


def post(pid, source, hours=0.0, kind="telegram", words=LONG):
    return D.Post(pid, source, kind, T + hours * H, words)


def story(*members, why="citation"):
    """Mark IX's members: the first the root, the others joined by `why`."""
    return [D.Member(m, "report", None if n == 0 else why) for n, m in enumerate(members)]


def v(relation, p, reason="r", call=None):
    return D.Verdict(relation, p, reason, call)


class Rules(unittest.TestCase):
    """The pure rules (plan_pass1, plan_pass2, decide)."""

    def setUp(self):
        self.posts = {p.id: p for p in (post("a", "s1"), post("b", "s2", 1), post("c", "s3", 2), post("d", "s4", 3),
                                        post("short", "s5", 4, words=5), post("e", "s6", 5), post("f", "s7", 6),
                                        post("g", "s8", 7), post("h", "s9", 8))}
        self.stories = {"A": story("a", "b", "c", "short"), "E": story("e", "f")}

    def plan(self, kinds=None, cands=(), pairs=(), config=D.Config()):
        return D.plan_pass1(self.posts, self.stories, kinds or {}, cands, pairs, config)

    def test_rule_a_and_roundups_and_certain_reasons(self):
        tids = {q.tid for q in self.plan()}
        self.assertEqual(tids, {"check:A:b", "check:A:c", "check:E:f"})        # never the origin, never under 20 words
        tids = {q.tid for q in self.plan(kinds={"short": "roundup"})}
        self.assertIn("check:A:short", tids)                                    # a roundup is checked, whatever its length
        self.stories["A"] = [D.Member("a", "report"), D.Member("b", "report", "quote"), D.Member("c", "report", "citation")]
        self.assertEqual({q.tid for q in self.plan() if q.story == "A"}, {"check:A:c"})   # a quote is not a guess

    def test_a_member_joined_by_thread_is_checked_but_not_in_the_prototypes_config(self):
        self.stories["A"] = [D.Member("a", "report"), D.Member("b", "report", "citation"), D.Member("c", "report", "thread")]
        self.assertEqual({q.tid for q in self.plan() if q.story == "A"}, {"check:A:b", "check:A:c"})
        self.assertEqual({q.tid for q in self.plan(config=D.Config.prototype()) if q.story == "A"}, {"check:A:b"})

    def test_a_check_never_shows_an_empty_story(self):
        """0112 bug 2: the checked post as the story's only report showed Haiku "Headline: (empty)" and no member.
        Then it shows the story's other members, any role; with none at all, nothing is asked."""
        self.stories["A"] = [D.Member("a", "share"), D.Member("b", "report", "citation"), D.Member("c", "share", "citation")]
        qs = {q.tid: q for q in self.plan() if q.story == "A"}
        self.assertEqual(qs["check:A:b"].side, ("a", "c"))     # b is the only report: the others, any role
        self.assertEqual(qs["check:A:c"].side, ("b",))         # the reports but the post, as before
        for q in self.plan():
            if q.type == "check":
                self.assertTrue(q.side, q.tid)

    def test_a_near_copy_is_never_checked(self):
        """0112 bug 3: a member that is a near-copy of another member (`copies`, by story) is never a check question,
        so no check removes or demotes it; it stays a member."""
        qs = {q.tid for q in D.plan_pass1(self.posts, self.stories, {}, (), (), D.Config(), copies={"A": {"a", "b"}})}
        self.assertNotIn("check:A:b", qs)
        self.assertIn("check:A:c", qs)

    def test_a_one_voice_story_is_not_checked(self):
        self.posts["b"] = post("b", "s1", 1)
        self.stories = {"A": story("a", "b")}
        self.assertEqual(self.plan(), [])

    def test_candidates_become_joins_pairs_and_merges(self):
        qs = {q.tid: q for q in self.plan(cands=[("a", "g", 0.9), ("g", "h", 0.8), ("b", "e", 0.7), ("g", "h", 0.64),
                                                  ("short", "h", 0.9)], pairs=[("A", "E", 0.75)])}
        self.assertEqual(qs["join:A:g"].anchor, "a")
        self.assertEqual(qs["pair:g:h"].type, "pair")
        self.assertIn("merge:A:E", qs)                     # both in 2+ voice stories: a merge, asked once
        self.assertNotIn("pair:short:h", qs)               # rule A
        self.assertEqual(sum(1 for t in qs if t.startswith("merge")), 1)

    def test_a_roundup_is_never_a_candidate_as_a_whole(self):
        qs = {q.tid for q in self.plan(kinds={"g": "roundup"}, cands=[("a", "g", 0.9)])}
        self.assertNotIn("join:A:g", qs)

    def test_checks_remove_below_030_and_015_in_two_voice_stories(self):
        q3 = D.Question("check:A:b", "check", story="A", post="b", voices=3)
        q2 = D.Question("check:E:f", "check", story="E", post="f", voices=2)
        out = D.decide(self.posts, self.stories, [(q3, v("different", 0.2)), (q2, v("different", 0.2))])
        self.assertNotIn("b", out.about["A"])
        self.assertIn("f", out.about["E"])                  # rule B: 0.2 keeps a 2-voice story's member
        out = D.decide(self.posts, self.stories, [(q2, v("different", 0.1))])
        self.assertNotIn("f", out.about["E"])

    def test_mention_and_digest_item_demote(self):
        q = D.Question("check:A:b", "check", story="A", post="b", voices=3)
        out = D.decide(self.posts, self.stories, [(q, v("digest_item", 0.1))])
        self.assertNotIn("b", out.about["A"])
        self.assertEqual(out.mentions["A"]["b"]["relation"], "digest_item")
        self.assertEqual(out.log[0]["change"], "demote")

    def test_the_two_event_guard_demotes_instead_of_removing(self):
        q = D.Question("check:A:b", "check", story="A", post="b", voices=3)
        out = D.decide(self.posts, self.stories, [(q, v("different", 0.1))], D.Config(), events={"b": "several"})
        self.assertEqual(out.log[0]["change"], "demote")
        self.assertEqual(out.mentions["A"]["b"]["guard"], "two-event")
        out = D.decide(self.posts, self.stories, [(q, v("different", 0.1))], D.Config.prototype(), events={"b": "several"})
        self.assertEqual(out.log[0]["change"], "remove")

    def test_joins_at_06_and_only_about(self):
        q = D.Question("join:A:g", "join", story="A", post="g", anchor="a")
        self.assertNotIn("g", D.decide(self.posts, self.stories, [(q, v("same_event", 0.59))]).about["A"])
        self.assertIn("g", D.decide(self.posts, self.stories, [(q, v("development", 0.6))]).about["A"])
        self.assertNotIn("g", D.decide(self.posts, self.stories, [(q, v("mention", 0.9))]).about["A"])

    def test_pairs_make_new_stories_and_pairs_sharing_a_post_are_one(self):
        p1 = D.Question("pair:g:h", "pair", post="h", anchor="g")
        p2 = D.Question("pair:h:d", "pair", post="d", anchor="h")
        out = D.decide(self.posts, self.stories, [(p1, v("same_event", 0.9)), (p2, v("same_event", 0.9))])
        new = [s for s in out.stories(self.posts) if s["story"] not in out.ix]
        self.assertEqual(len(new), 1)
        self.assertEqual(set(new[0]["posts"]), {"g", "h", "d"})

    def test_merges_at_085_and_a_development_is_a_connection(self):
        m = D.Question("merge:A:E", "merge", story="A", other="E")
        out = D.decide(self.posts, self.stories, [(m, v("same_event", 0.85))])
        self.assertEqual(set(out.about["A"]), {"a", "b", "c", "short", "e", "f"})
        self.assertNotIn("E", out.about)
        self.assertEqual(out.merged_into, {"E": "A"})       # the older (Mark IX) story keeps its key
        out = D.decide(self.posts, self.stories, [(m, v("same_event", 0.84))])
        self.assertIn("E", out.about)
        out = D.decide(self.posts, self.stories, [(m, v("development", 0.9, call="c1"))])
        self.assertIn("E", out.about)
        self.assertEqual([(c["relation"], c["a"], c["b"], c["call"]) for c in out.connections], [("development", "A", "E", "c1")])

    def test_a_new_story_merges_into_a_mark_ix_story_which_keeps_its_key(self):
        p = D.Question("pair:g:h", "pair", post="h", anchor="g")
        m = D.Question("merge2:E:g", "merge", story="E", other="g", second=True)
        out = D.decide(self.posts, self.stories, [(p, v("same_event", 0.9)), (m, v("same_event", 0.9))])
        self.assertEqual(set(out.about["E"]), {"e", "f", "g", "h"})
        self.assertEqual(out.final["g"], "E")

    def test_the_second_pass_compares_new_stories_with_the_others(self):
        p = D.Question("pair:g:h", "pair", post="h", anchor="g")
        first = D.decide(self.posts, self.stories, [(p, v("same_event", 0.9))])
        asked = []

        def cos(pa, pb):
            asked.append((tuple(pa), tuple(pb)))
            return 0.9 if "e" in pb or "e" in pa else 0.5
        qs = D.plan_pass2(self.posts, first, cos)
        self.assertEqual([(q.tid, q.second) for q in qs], [("merge2:E:g", True)])
        self.assertTrue(all("g" in a or "g" in b for a, b in asked))     # only the new story is compared

    def test_the_late_post_table(self):
        self.posts["late"] = post("late", "s10", 100)                   # 4 days after story A began
        q = D.Question("join:A:late", "join", story="A", post="late", anchor="c")
        out = D.decide(self.posts, self.stories, [(q, v("development", 0.9, call="c2"))])
        self.assertNotIn("late", out.about["A"])
        self.assertEqual([(c["relation"], c["a"], c["b"]) for c in out.connections], [("follows_up", "late", "A")])
        out = D.decide(self.posts, self.stories, [(q, v("same_event", 0.85))])
        self.assertIn("late", out.about["A"])                          # the same event, at the merge bar
        out = D.decide(self.posts, self.stories, [(q, v("same_event", 0.8))])
        self.assertEqual(out.connections[0]["relation"], "related")
        out = D.decide(self.posts, self.stories, [(q, v("development", 0.9))], D.Config.prototype())
        self.assertIn("late", out.about["A"])                          # the prototype had no late rule

    def test_checks_come_before_joins_and_merges_after_glue(self):
        c = D.Question("check:A:b", "check", story="A", post="b", voices=3)
        j = D.Question("join:A:b", "join", story="A", post="b", anchor="a")
        out = D.decide(self.posts, self.stories, [(j, v("same_event", 0.9)), (c, v("different", 0.1))])
        self.assertIn("b", out.about["A"])                              # removed by its check, joined again by meaning
        self.assertEqual([x["change"] for x in out.log], ["remove", "join"])

    def test_a_reason_that_says_not_this_story(self):
        """0112 Decided 8's rule by code: an "about" answer whose own reason says the post is not about the story is
        never accepted. The class, from v10.0's recorded answers: the reason names another relation for the post
        (different, a mention, unrelated), says the story's subject is not the post's, or says it is unrelated or
        absent. A different angle on the same event, a missing detail, or "rather than the release itself" (a
        reaction) is not that class."""
        said = ["The post is about a ternary model release, not LFM3; the model family is absent from its text.",
                "The post is a trending entry for another project, not the launch, so it is a different event.",
                "The post's main subject is a benchmark of the tool, so this is closer to a mention.",
                "It uses the review as its opening hook; the main subject is a broader argument, so this is a mention "
                "rather than a retelling of the review.",
                "The post reports a cipher result, a different event from the evaluation story, so this is a mismatch.",
                "Post reports failure modes in a long project; this is a different event, so the relation should be "
                "different.",
                "A pull request for kernel speedups that benefits other models, so the model family is not its subject.",
                "Commentary on a leaked draft bill, which is unrelated to the unreleased model in the story.",
                "A short reaction to the product's comeback, with the store's block not mentioned.",
                "The post reports a release that is a different model from the story's model."]
        for reason in said:
            self.assertTrue(D.contradicts(reason), reason)
        fine = ["The post reports the same release, a different angle on the same launch.",
                "Benchmark results for the model that is the story's subject, though it does not mention the "
                "open-weights status.",
                "A user's hands-on run of the released model rather than the release itself.",
                "The same release as the story, with the paper only as background.",
                "Both stories cover the single release and differ only in headline framing.", "", None]
        for reason in fine:
            self.assertFalse(D.contradicts(reason), reason)

    def test_a_story_changing_answer_counts_only_once_asked_again_and_agreeing(self):
        """0112 Decided 8: a join, pair or merge that would change a story is asked a second time; it counts only when
        the second answer agrees (the same relation, at the bar, its reason not against it). (verdict, ask again)."""
        c = D.Config()
        same, same2 = v("same_event", 0.9, call="c1"), v("same_event", 0.8, call="c2")
        self.assertEqual(D.settle("join", [same], c), (None, True))                      # once: not yet
        got, again = D.settle("join", [same, same2], c)
        self.assertEqual((got.relation, got.p, got.call, again), ("same_event", 0.8, "c1", False))   # the lower p
        no = v("different", 0.2, call="c2")
        self.assertEqual(D.settle("pair", [same, no], c), (no, False))                   # disagrees: the "no" counts
        dev = v("development", 0.9, call="c2")
        self.assertEqual(D.settle("pair", [same, dev], c), (None, True))                 # another relation: a third ask
        self.assertEqual(D.settle("pair", [same, dev, v("development", 0.7, call="c3")], c)[0].relation, "development")
        self.assertEqual(D.settle("pair", [same, dev, same2], c), (None, False))         # three asks at most
        against = v("same_event", 0.9, "unrelated to the story's release", call="c1")
        self.assertEqual(D.settle("join", [against], c), (None, True))                   # never accepted: asked again
        self.assertEqual(D.settle("join", [against, same2], c), (None, True))
        self.assertEqual(D.settle("join", [against, same2, same], c)[0].relation, "same_event")
        self.assertEqual(D.settle("join", [against, same], D.Config(confirm=False)), (same, False))
        # a merge: "same event" at 0.85 changes stories; a development at the bar is a connection, never asked again
        m = v("same_event", 0.9, call="c1")
        self.assertEqual(D.settle("merge", [m], c), (None, True))
        self.assertEqual(D.settle("merge", [m, v("same_event", 0.86)], c)[0].p, 0.86)
        self.assertEqual(D.settle("merge", [v("development", 0.9)], c), (v("development", 0.9), False))
        # an answer that changes nothing is final at once; the prototype asked once and read no reason
        self.assertEqual(D.settle("join", [no], c), (no, False))
        self.assertEqual(D.settle("join", [against], D.Config.prototype()), (against, False))

    def test_a_verdict_reads_the_confidence_as_the_prototype(self):
        self.assertAlmostEqual(D.Verdict.of({"relation": "same_event", "confidence": 70}).p, 0.70)
        self.assertAlmostEqual(D.Verdict.of({"relation": "different", "confidence": 70}).p, 0.30)
        self.assertAlmostEqual(D.Verdict.of({"relation": "mention"}).p, 0.50)


class Tags(unittest.TestCase):
    def test_the_five_tags(self):
        ix_of = {"a": "R1", "b": "R1", "c": "R2", "d": "R2"}
        ix_rows = {"R1": {"a", "b"}, "R2": {"c", "d"}}
        x_of = {"a": "X1", "b": "X1", "c": "X2", "d": "X3", "e": "X4"}
        self.assertEqual(N.tag(["a", "b"], x_of, "X1", ix_of, ix_rows), "SAME")
        self.assertEqual(N.tag(["e", "f"], x_of, "X4", ix_of, ix_rows), "NEW")
        self.assertEqual(N.tag(["a", "c"], x_of, "X5", ix_of, ix_rows), "MERGED")
        self.assertEqual(N.tag(["c", "x"], x_of, "X2", ix_of, ix_rows), "SPLIT")
        self.assertEqual(N.tag(["a", "b", "z"], {**x_of, "z": "X1"}, "X1", ix_of, ix_rows), "CHANGED")


def checksums(cur, skip_prefix="mx_"):
    """{table: md5 of its rows} of every table but Mark X's (0079's per-table checksum)."""
    cur.execute("SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r' ORDER BY 1")
    out = {}
    for (table,) in cur.fetchall():
        if table.startswith(skip_prefix):
            continue
        cur.execute(sql.SQL("SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) "
                            "FROM (SELECT md5(x::text) h FROM {} x) s").format(sql.Identifier(table)))
        out[table] = cur.fetchone()
    return out


@requires_test_db
class Job(unittest.TestCase):
    """The job on a test database, in one transaction rolled back after each test."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas.load_guides(self.cur)
        self.now = T + 30 * H

    def post(self, hours, title, *, platform="telegram"):
        source = insert_scratch_source(self.cur, platform=platform, settings_json=json.dumps({"display_name": "Example"}))
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        # each post a text of its own: posts of one text are near-copies, never checked (0112 bug 3)
        body = title + ". " + " ".join(f"word{k}{url[-6:]}" for k in range(LONG))
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (source, url, url, title, body, T + hours * H))
        pid = str(self.cur.fetchone()[0])
        from insight_core.db.repo_post_parts import PostPartsRepository
        PostPartsRepository.write(self.cur, [pid])
        return pid

    def ix_story(self, *members, reason="citation"):
        self.cur.execute("SELECT min(published_at) FROM posts WHERE id = ANY(%s::uuid[])", (list(members),))
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, %s)",
                         (members[0], self.cur.fetchone()[0], len(members)))
        for n, m in enumerate(members):
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_id, parent_reason) "
                             "VALUES (%s, %s, 'report', %s, %s, %s)",
                             (m, members[0], f"v{n}", members[n - 1] if n else None, reason if n else None))
        return members[0]

    def answer(self, kind, answer_of):
        """Answer every open task of `kind` (answer_of(task) -> the answer) as the worker would, valid calls only."""
        self.cur.execute("SELECT id, kind, guide, input, a FROM mx_tasks WHERE kind = %s AND status = 'open'", (kind,))
        n = 0
        for tid, k, guide, text, a in self.cur.fetchall():
            ans = answer_of({"id": tid, "kind": k, "input": text, "a": a})
            call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=ans)
            repo.answer_task(self.cur, tid)
            tasks.record(self.cur, {"kind": k, "guide": guide, "a": a}, call, ans)
            n += 1
        return n

    def read_all(self, ids, kind="report", events="one"):
        for pid in ids:
            tasks.read_task(self.cur, pid)
        self.answer("read", lambda t: {"kind": kind, "events": events, "lang": "en", "items": [], "mentions": [],
                                       "main": {"headline_en": "Acme released Widget", "actors": ["Acme"],
                                                "object": "Widget", "action": "released"}})

    def go(self):
        return D.run(self.cur, now=self.now)

    def twice(self, kind, answer_of):
        """A story-changing answer counts once asked again (0112 Decided 8): answer, run (the run asks again), answer."""
        n = self.answer(kind, answer_of)
        self.go()
        return n + self.answer(kind, answer_of)

    def current(self):
        self.cur.execute("SELECT story_id::text, post_id::text, role, reason FROM mx_story_posts WHERE valid_to IS NULL")
        return self.cur.fetchall()

    def test_a_run_mirrors_mark_ix_then_checks_remove_with_the_row_kept(self):
        a, b, c = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 is out"), self.post(2, "Widget 4 hands-on")
        self.ix_story(a, b, c)
        first = self.go()
        self.assertEqual(first["stories"], 1)
        self.assertEqual({(p, r) for _, p, _, r in self.current()}, {(a, "rule:none"), (b, "rule:citation"), (c, "rule:citation")})
        self.assertEqual(first["tasks_added"].get("check"), 2)          # b and c are uncertain members
        # the same run again changes nothing
        again = self.go()
        self.assertEqual(again["memberships"], {})
        # c's check says "different": c's membership closes, the row stays
        self.answer("check", lambda t: {"relation": "different" if c in str(t["a"]) else "same_event", "confidence": 90})
        third = self.go()
        self.assertEqual(third["changes"], {"remove": 1})
        self.assertEqual({p for _, p, _, _ in self.current()}, {a, b})
        self.cur.execute("SELECT valid_to IS NOT NULL FROM mx_story_posts WHERE post_id = %s", (c,))
        self.assertEqual(self.cur.fetchall(), [(True,)])

    def test_a_pair_makes_a_new_story_and_news_tags_it(self):
        a, b = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 by Acme is here")
        repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding", score=0.8)
        self.read_all([a, b])
        self.go()
        self.twice("pair", lambda t: {"relation": "same_event", "confidence": 90, "reason": "same release"})
        out = self.go()
        self.assertEqual(out["changes"], {"new_pair": 1})
        self.assertEqual({p for _, p, _, _ in self.current()}, {a, b})
        self.assertEqual({r for _, _, _, r in self.current()}, {"judge:pair"})
        self.assertEqual(out["news"]["tags"], {"NEW": 1})
        self.assertTrue(out["news"]["written"])
        self.assertFalse(self.go()["news"]["written"])                # the same rows are not written again

    def test_removals_made_under_bugs_2_and_3_are_re_decided_by_the_next_run(self):
        """0112 Decided 6: v10.0 removed b on a check that showed an empty story (b its story's only report) and d, a
        copy of a. The next run doesn't trust those answers: b's check is asked again with the story shown, d is never
        asked; both are members again (a new row, the closed ones kept) and b's new answer decides it."""
        a, b, c = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 hands-on"), self.post(2, "Widget 4 price")
        d = self.post(3, "Acme released Widget 4")
        self.cur.execute("UPDATE posts SET content = (SELECT content FROM posts WHERE id = %s) WHERE id = %s", (a, d))
        from insight_core.db.repo_post_parts import PostPartsRepository
        self.cur.execute("DELETE FROM post_parts WHERE post_id = %s", (d,))
        PostPartsRepository.write(self.cur, [d])
        story = self.ix_story(a, b, c, d)
        self.cur.execute("UPDATE story_posts SET role = 'share' WHERE story_id = %s AND post_id <> %s", (story, b))
        first = self.go()
        sid = {s for s, _, _, _ in self.current()}.pop()
        # v10.0's questions and answers: b against an empty story, d against the story, both "different"
        text = tasks.load_posts(self.cur, [a, b, c, d])
        old = {b: tasks.check_input(text[b], []), d: tasks.check_input(text[d], [text[b]])}
        self.assertIn("Headline: \n", old[b])
        for pid, question in old.items():
            tid, new = tasks.add(self.cur, "check", question, a=pid)
            self.assertTrue(new)
            call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True,
                                 answer={"id": "x", "relation": "different", "confidence": 90, "reason": "no relation"})
            repo.answer_task(self.cur, tid)
            repo.close_membership(self.cur, story_id=sid, post_id=pid, at=self.now)   # v10.0's removal
        self.assertEqual({p for _, p, _, _ in self.current()}, {a, c})
        self.cur.execute("SELECT a::text FROM mx_tasks WHERE kind = 'check' AND status = 'open'")
        self.assertEqual({r[0] for r in self.cur.fetchall()}, {b, c})      # d, a copy of a, is never asked
        again = self.go()
        self.assertEqual({p for _, p, _, _ in self.current()}, {a, b, c, d})   # not trusted: members again
        self.assertNotIn("remove", again["changes"])
        self.cur.execute("SELECT count(*) FROM mx_story_posts WHERE post_id = ANY(%s::uuid[]) AND valid_to IS NOT NULL",
                         ([b, d],))
        self.assertEqual(self.cur.fetchone()[0], 2)                        # the closed rows stay
        self.answer("check", lambda t: {"relation": "same_event" if str(t["a"]) == b else "different", "confidence": 90})
        third = self.go()
        self.assertEqual(third["changes"], {"remove": 1})                  # c, asked once, says different
        self.assertEqual({p for _, p, _, _ in self.current()}, {a, b, d})
        self.assertEqual(first["tasks_added"].get("check"), 2)

    def test_a_pair_counts_only_once_asked_again(self):
        """0112 Decided 8: the run asks a story-changing answer again (its task open once more, its first call kept);
        the next answer that agrees makes the story, one that disagrees doesn't."""
        a, b = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 by Acme is here")
        c, d = self.post(2, "Beta shipped Gizmo 2"), self.post(3, "Gizmo 2 by Beta is out")
        repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding", score=0.8)
        repo.add_candidate(self.cur, kind="post_post", a=c, b=d, source="embedding", score=0.8)
        self.read_all([a, b, c, d])
        self.go()
        self.answer("pair", lambda t: {"relation": "same_event", "confidence": 90, "reason": "same release"})
        first = self.go()
        self.assertEqual(first["changes"], {})                         # once is not enough
        self.assertEqual(first["tasks_reasked"], {"pair": 2})
        self.assertEqual(self.current(), [])
        self.cur.execute("SELECT status, (SELECT count(*) FROM mx_calls c WHERE c.task_id = t.id) FROM mx_tasks t "
                         "WHERE kind = 'pair'")
        self.assertEqual(self.cur.fetchall(), [("open", 1), ("open", 1)])
        self.assertEqual(self.go()["tasks_reasked"], {})               # open: not asked again twice
        self.answer("pair", lambda t: {"relation": "same_event" if a in str(t["a"]) else "different",
                                       "confidence": 85, "reason": "same release"})
        out = self.go()
        self.assertEqual(out["changes"], {"new_pair": 1})
        self.assertEqual({p for _, p, _, _ in self.current()}, {a, b})
        self.cur.execute("SELECT sp.p, c.answer->>'confidence' FROM mx_story_posts sp JOIN mx_calls c ON c.id = sp.call_id "
                         "WHERE sp.valid_to IS NULL AND sp.reason = 'judge:pair'")
        self.assertEqual(sorted(self.cur.fetchall()), [(0.85, "90"), (0.85, "90")])   # the lower p, the first call
        self.assertEqual(self.go()["changes"], {"new_pair": 1})        # settled: nothing asked again
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'pair' AND status <> 'answered'")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_an_answer_whose_reason_says_another_story_never_counts(self):
        a, b = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 by Acme is here")
        repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding", score=0.8)
        self.read_all([a, b])
        self.go()
        said = {"relation": "same_event", "confidence": 90, "reason": "a ternary model, not Widget; Acme is absent from it"}
        for _ in range(3):
            self.answer("pair", lambda t: said)
            self.assertEqual(self.go()["changes"], {})
        self.cur.execute("SELECT status FROM mx_tasks WHERE kind = 'pair'")
        self.assertEqual(self.cur.fetchall(), [("answered",)])        # three asks, then it rests

    def test_a_short_pair_is_never_asked(self):
        a = self.post(0, "Widget")
        b = self.post(1, "Acme released Widget 4")
        self.cur.execute("UPDATE posts SET content = 'Image' WHERE id = %s", (a,))
        from insight_core.db.repo_post_parts import PostPartsRepository
        self.cur.execute("DELETE FROM post_parts WHERE post_id = %s", (a,))
        PostPartsRepository.write(self.cur, [a])
        repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding", score=0.95)
        self.read_all([a, b])
        self.assertNotIn("pair", self.go()["tasks_added"])

    def test_mark_ix_tables_are_identical_before_and_after_runs(self):
        a, b, c = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 is out"), self.post(2, "Another thing")
        self.ix_story(a, b)
        repo.add_candidate(self.cur, kind="post_post", a=b, b=c, source="embedding", score=0.8)
        self.read_all([a, b, c])
        before = checksums(self.cur)
        self.go()
        self.answer("check", lambda t: {"relation": "different", "confidence": 95})
        self.twice("join", lambda t: {"relation": "same_event", "confidence": 95})
        self.go()
        self.assertEqual(checksums(self.cur), before)

    def test_every_membership_names_a_rule_or_a_valid_call(self):
        a, b = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 by Acme")
        repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding", score=0.8)
        self.read_all([a, b])
        self.go()
        self.twice("pair", lambda t: {"relation": "same_event", "confidence": 90})
        self.go()
        self.assertEqual({p for _, p, _, _ in self.current()}, {a, b})
        self.cur.execute("""SELECT count(*) FROM mx_story_posts sp LEFT JOIN mx_calls c ON c.id = sp.call_id
                             WHERE sp.valid_to IS NULL AND NOT (sp.reason LIKE 'rule:%%' OR c.valid)""")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def vector(self, pid, k):
        v = [0.0] * 1024
        v[0], v[k] = 1.0, 0.2
        repo.put_embedding(self.cur, post_id=pid, model=D.MODEL, text_hash="h-" + pid, vector=v, model_sha256="a" * 64)

    def test_connect_questions_are_capped_a_run_newest_pairs_first(self):
        keys = []
        for n in range(3):                                   # three 2-voice stories a day apart, all alike
            a, b = self.post(24 * n - 60, f"Story {n} first"), self.post(24 * n - 59, f"Story {n} second")
            self.vector(a, 1 + 2 * n)
            self.vector(b, 2 + 2 * n)
            keys.append((self.ix_story(a, b), b))
        out = D.run(self.cur, config=D.Config(connect_new=1), now=self.now)
        self.assertEqual(out["tasks_added"].get("connect"), 1)
        self.assertEqual(out["tasks_waiting"].get("connect"), 2)
        self.cur.execute("SELECT a::text, b::text FROM mx_tasks WHERE kind = 'connect'")
        self.assertEqual(self.cur.fetchall(), [(keys[1][0], keys[2][0])])     # the newest pair: stories 1 and 2
        self.cur.execute("SELECT config->>'connect_new', config->>'connect_voices' FROM mx_runs")
        self.assertEqual(self.cur.fetchall(), [("1", "2")])                   # the setting is the run's config
        again = D.run(self.cur, config=D.Config(connect_new=1), now=self.now)
        self.assertEqual(again["tasks_added"].get("connect"), 1)              # the next run asks the next newest
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'connect'")
        self.assertEqual(self.cur.fetchone()[0], 2)

    def test_no_new_connect_question_while_the_backlog_is_full(self):
        for n in range(3):                                   # three alike 2-voice stories: three pairs
            a, b = self.post(24 * n - 60, f"Story {n} first"), self.post(24 * n - 59, f"Story {n} second")
            self.vector(a, 1 + 2 * n)
            self.vector(b, 2 + 2 * n)
            self.ix_story(a, b)
        config = D.Config(connect_new=5, connect_open=2)
        first = D.run(self.cur, config=config, now=self.now)
        self.assertEqual((first["tasks_added"].get("connect"), first["tasks_waiting"].get("connect")), (2, 1))
        self.assertNotIn("connect", D.run(self.cur, config=config, now=self.now)["tasks_added"])   # 2 open: full
        self.assertEqual(len(repo.lease_tasks(self.cur, kinds=["connect"], limit=10, worker="w")), 2)   # leased still waits
        self.assertNotIn("connect", D.run(self.cur, config=config, now=self.now)["tasks_added"])
        self.cur.execute("SELECT id FROM mx_tasks WHERE kind = 'connect' LIMIT 1")
        repo.answer_task(self.cur, self.cur.fetchone()[0])                                   # one answered: room for one
        self.assertEqual(D.run(self.cur, config=config, now=self.now)["tasks_added"].get("connect"), 1)
        self.cur.execute("SELECT config->>'connect_open' FROM mx_runs LIMIT 1")
        self.assertEqual(self.cur.fetchone()[0], "2")

    def test_the_lock_skips_a_second_run(self):
        other = psycopg.connect(db_url())
        self.addCleanup(other.close)
        with other.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (D.LOCK_KEY,))
            try:
                self.assertIn("skipped", self.go())
            finally:
                cur.execute("SELECT pg_advisory_unlock(%s)", (D.LOCK_KEY,))


@requires_test_db
class Snapshot(unittest.TestCase):
    """A run reads one snapshot (REPEATABLE READ): a story-job commit landing mid-run is not seen by that run, and a
    task the worker's planner commits mid-run is taken, not a failed run. Committed rows, removed after."""

    def setUp(self):
        self.other = psycopg.connect(db_url(), autocommit=True)
        self.addCleanup(self.other.close)
        self.cur = self.other.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        self.addCleanup(self.cur.execute, f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas.load_guides(self.cur)
        self.now = T + 30 * H
        self.posts, self.sources = [], []
        self.addCleanup(self._clean)
        self.a, self.b, self.c = (self.post(n, f"Acme released Widget {n}") for n in range(3))
        self.story = self.a
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, 2)", (self.story, T))
        self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_id, parent_reason) VALUES "
                         "(%s, %s, 'report', 'v0', NULL, NULL), (%s, %s, 'report', 'v1', %s, 'citation')",
                         (self.a, self.story, self.b, self.story, self.a))

    def _clean(self):
        self.cur.execute("DELETE FROM story_posts WHERE story_id = %s", (self.story,))
        self.cur.execute("DELETE FROM stories WHERE id = %s", (self.story,))
        self.cur.execute("DELETE FROM post_parts WHERE post_id = ANY(%s::uuid[])", (self.posts,))
        self.cur.execute("DELETE FROM posts WHERE id = ANY(%s::uuid[])", (self.posts,))
        self.cur.execute("DELETE FROM sources WHERE id = ANY(%s::uuid[])", (self.sources,))

    def post(self, hours, title):
        source = insert_scratch_source(self.cur, platform="telegram", settings_json=json.dumps({"display_name": "Example"}))
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        # each post a text of its own: posts of one text are near-copies, never checked (0112 bug 3)
        body = title + ". " + " ".join(f"word{k}{url[-6:]}" for k in range(LONG))
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (source, url, url, title, body, T + hours * H))
        pid = str(self.cur.fetchone()[0])
        from insight_core.db.repo_post_parts import PostPartsRepository
        PostPartsRepository.write(self.cur, [pid])
        self.posts.append(pid)
        self.sources.append(str(source))
        return pid

    def run_with(self, transaction, mid_run):
        """One run whose think() first lets `mid_run` commit on another connection, then counts the story's members
        on the run's own cursor: what the rest of the run reads."""
        seen = {}
        real = D.think

        def think(cur, world, config, ask, now, *rest, **kw):
            mid_run()
            cur.execute("SELECT count(*) FROM story_posts WHERE story_id = %s", (self.story,))
            seen["members"] = cur.fetchone()[0]
            return real(cur, world, config, ask, now, *rest, **kw)
        with mock.patch.object(D, "think", think), transaction() as cur:
            seen["out"] = D.run(cur, now=self.now)
        return seen

    def add_member(self):
        self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_id, parent_reason) "
                         "VALUES (%s, %s, 'report', 'v2', %s, 'citation') ON CONFLICT DO NOTHING", (self.c, self.story, self.b))

    def test_a_story_change_committed_mid_run_is_not_seen_by_that_run(self):
        from insight_core.db import database
        seen = self.run_with(lambda: D.snapshot(db_url()), self.add_member)
        self.assertEqual(seen["out"]["isolation"], "repeatable read")
        self.assertEqual(seen["members"], 2)                       # the commit came after the run's snapshot
        self.cur.execute("DELETE FROM story_posts WHERE post_id = %s", (self.c,))
        control = self.run_with(lambda: database.transaction(db_url()), self.add_member)
        self.assertEqual(control["out"]["isolation"], "read committed")
        self.assertEqual(control["members"], 3)                    # what READ COMMITTED would have mixed in

    def test_a_task_the_planner_commits_mid_run_is_not_a_failed_run(self):
        def plan():   # the worker's check planner asks the run's own check first, and commits
            tasks.check_task(self.cur, self.b, [self.a])
        seen = self.run_with(lambda: D.snapshot(db_url()), plan)
        self.assertEqual(seen["out"]["tasks_raced"], {"check": 1})
        self.assertNotIn("check", seen["out"]["tasks_added"])
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'check'")
        self.assertEqual(self.cur.fetchone()[0], 1)
        self.cur.execute("SELECT count(*) FROM mx_runs")
        self.assertEqual(self.cur.fetchone()[0], 1)                # the run committed


class Routes(unittest.TestCase):
    def test_the_page_routes_are_404_when_off(self):
        from insight_core.tests.test_markx_api import call
        with mock.patch.dict(os.environ, {"INSIGHT_MARKX": "off"}):
            for path in ("/api/markx/on", "/api/markx/news", "/api/markx/overview",
                         f"/api/markx/posts/{uuid.uuid4()}"):
                self.assertEqual(call("GET", path)[0], 404, path)


if __name__ == "__main__":
    unittest.main()
