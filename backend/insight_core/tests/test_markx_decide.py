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
        body = title + ". " + " ".join(f"word{k}" for k in range(LONG))
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
        self.answer("pair", lambda t: {"relation": "same_event", "confidence": 90, "reason": "same release"})
        out = self.go()
        self.assertEqual(out["changes"], {"new_pair": 1})
        self.assertEqual({p for _, p, _, _ in self.current()}, {a, b})
        self.assertEqual({r for _, _, _, r in self.current()}, {"judge:pair"})
        self.assertEqual(out["news"]["tags"], {"NEW": 1})
        self.assertTrue(out["news"]["written"])
        self.assertFalse(self.go()["news"]["written"])                # the same rows are not written again

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
        self.answer("join", lambda t: {"relation": "same_event", "confidence": 95})
        self.go()
        self.assertEqual(checksums(self.cur), before)

    def test_every_membership_names_a_rule_or_a_valid_call(self):
        a, b = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 by Acme")
        repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding", score=0.8)
        self.read_all([a, b])
        self.go()
        self.answer("pair", lambda t: {"relation": "same_event", "confidence": 90})
        self.go()
        self.cur.execute("""SELECT count(*) FROM mx_story_posts sp LEFT JOIN mx_calls c ON c.id = sp.call_id
                             WHERE sp.valid_to IS NULL AND NOT (sp.reason LIKE 'rule:%%' OR c.valid)""")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_the_lock_skips_a_second_run(self):
        other = psycopg.connect(db_url())
        self.addCleanup(other.close)
        with other.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (D.LOCK_KEY,))
            try:
                self.assertIn("skipped", self.go())
            finally:
                cur.execute("SELECT pg_advisory_unlock(%s)", (D.LOCK_KEY,))


class Switch(unittest.TestCase):
    def test_off_nothing_runs(self):
        ran = []
        s = D.Scheduler(transaction=lambda: ran.append(1), debounce=0.01, every=0.01, enabled=lambda: False)
        s.note()
        self.assertFalse(s.start())
        self.assertIsNone(s.run_now())
        self.assertEqual(ran, [])

    def test_uploads_close_together_make_one_run_after_the_last(self):
        import contextlib
        import threading
        import time
        ran, done = [], threading.Event()

        @contextlib.contextmanager
        def transaction():
            yield "cur"

        def fake_run(cur):
            ran.append(cur)
            done.set()
            return {"stories": 0}
        with mock.patch.object(D, "run", fake_run):
            s = D.Scheduler(transaction=transaction, debounce=0.2, every=None, enabled=lambda: True)
            for _ in range(3):
                s.note()
                time.sleep(0.05)
            self.assertTrue(done.wait(2))
            time.sleep(0.3)
        self.assertEqual(ran, ["cur"])

    def test_on_a_failed_run_never_raises(self):
        def broken():
            raise RuntimeError("no database")
        s = D.Scheduler(transaction=broken, debounce=None, every=None, enabled=lambda: True)
        self.assertIsNone(s.run_now())

    def test_the_page_routes_are_404_when_off(self):
        from insight_core.tests.test_markx_api import call
        with mock.patch.dict(os.environ, {"INSIGHT_MARKX": "off"}):
            for path in ("/api/markx/on", "/api/markx/news", "/api/markx/overview",
                         f"/api/markx/posts/{uuid.uuid4()}"):
                self.assertEqual(call("GET", path)[0], 404, path)


if __name__ == "__main__":
    unittest.main()
