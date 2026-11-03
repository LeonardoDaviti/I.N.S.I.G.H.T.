"""The real-data checks (issue 0075): the case runner's paths, tests and verdicts, the invariants' own
patterns, the diff's kinds of change, the scratch-only and read-only guards, and refs and story
assertions on the database (one transaction, rolled back). Neutral names only: the real cases, their
posts and the reports stay in plan/research/ (private)."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.checks import cases, diff, invariants, paths, refs, table_rows
from insight_core.checks.job import scratch_only
from insight_core.checks.surfaces import SURFACES, Context
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._stories import insert_post, insert_source

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


class PathsTests(unittest.TestCase):
    ANSWER = {"title": "A title", "story": {"voices": 3, "posts": [{"id": "p1", "title": "One"}, {"id": "p2", "title": "Two"}],
                                           "first": None}, "links": {"https://a.test/x": "p9"}}

    def test_a_path_reads_keys_indexes_every_element_and_lengths(self):
        self.assertEqual(paths.get(self.ANSWER, "story.voices"), 3)
        self.assertEqual(paths.get(self.ANSWER, "story.posts[1].title"), "Two")
        self.assertEqual(paths.get(self.ANSWER, "story.posts[*].id"), ["p1", "p2"])
        self.assertEqual(paths.get(self.ANSWER, "len(story.posts)"), 2)
        self.assertEqual(paths.get(self.ANSWER, "len(title)"), 7)
        self.assertIsNone(paths.get(self.ANSWER, "story.origin.title"), "a missing key reads None")
        self.assertIsNone(paths.get(self.ANSWER, "story.posts[5].title"))

    def test_the_tests(self):
        self.assertTrue(paths.test("A title", "contains", "title")[0])
        self.assertTrue(paths.test(["One", "Two"], "contains", "Tw")[0], "a text element holding it")
        self.assertTrue(paths.test(["One", "Two"], "contains", ["One", "Two"])[0], "every one of a list")
        self.assertFalse(paths.test(["One", "Two"], "not_contains", "One")[0])
        self.assertTrue(paths.test(None, "is_null", True)[0])
        self.assertTrue(paths.test([], "is_null", True)[0])
        self.assertTrue(paths.test(3, "at_least", 3)[0])
        self.assertFalse(paths.test(None, "at_least", 0)[0], "nothing is no number")
        self.assertTrue(paths.test("A title", "matches", r"^A \w+$")[0])
        self.assertTrue(paths.test(["x y", "x", "x y z"], "count", {"of": "x y", "equals": 2})[0])

    def test_a_post_is_held_anywhere_in_the_answer_by_any_of_its_ids(self):
        self.assertTrue(paths.test(self.ANSWER, "has_post", [["p0", "p2"]])[0])
        self.assertTrue(paths.test(self.ANSWER, "has_post", [["p9"]])[0], "a value of a dict")
        self.assertFalse(paths.test(self.ANSWER, "has_post", [["p1"], ["p7"]])[0], "every post named must be there")
        self.assertTrue(paths.test(self.ANSWER, "lacks_post", [["p7"], ["p8"]])[0])
        self.assertFalse(paths.test(self.ANSWER, "lacks_post", [["p7"], ["p1"]])[0])


class FakeContext(Context):
    """A Context whose refs are the ids they name, for surfaces the test stubs."""

    def __init__(self):
        super().__init__("postgresql://unused/none", NOW, cur=None)

    def ids(self, ref):
        if ref == "missing":
            raise refs.RefError("no stored post: missing")
        return [ref if isinstance(ref, str) else ref["url"]]


class CaseRunnerTests(unittest.TestCase):
    def setUp(self):
        self.ctx = FakeContext()
        SURFACES["fake"] = lambda ctx, a: {"title": f"Title of {ctx.one(a['post'])}", "story": {"voices": 2, "posts": [{"id": "b"}]}}
        self.addCleanup(SURFACES.pop, "fake")

    def case(self, now="pass", kind="title", **assertion):
        return {"id": "c1", "kind": kind, "now": now, "expect": [{"on": "fake", "post": "a", **assertion}]}

    def test_every_assertion_holding_passes(self):
        result = cases.run_case(self.ctx, {"id": "c", "kind": "title", "now": "pass", "expect": [
            {"on": "fake", "post": "a", "path": "title", "equals": "Title of a"},
            {"on": "fake", "post": "a", "path": "story", "has_post": "b"}]})
        self.assertEqual(result.status, "pass")
        self.assertFalse(result.broken)

    def test_a_pass_case_failing_is_broken_and_a_fail_case_passing_is_fixed(self):
        broken = cases.run_case(self.ctx, self.case(path="title", equals="Another"))
        self.assertEqual((broken.status, broken.broken), ("fail", True))
        self.assertIn("saw 'Title of a'", broken.details[0])
        fixed = cases.run_case(self.ctx, self.case(now="fail", path="story.voices", at_least=2))
        self.assertTrue(fixed.fixed)
        s = cases.summary([broken, fixed])
        self.assertEqual((s["broken"], s["fixed"]), (["c1"], ["c1"]))

    def test_a_post_the_copy_doesnt_hold_fails_with_its_reason(self):
        result = cases.run_case(self.ctx, {"id": "c", "kind": "title", "now": "pass",
                                           "expect": [{"on": "fake", "post": "missing", "path": "title", "equals": "x"}]})
        self.assertEqual(result.status, "fail")
        self.assertIn("no stored post", result.details[0])

    def test_a_service_that_raises_is_an_error_never_a_crash(self):
        SURFACES["boom"] = lambda ctx, a: 1 / 0
        self.addCleanup(SURFACES.pop, "boom")
        result = cases.run_case(self.ctx, {"id": "c", "kind": "title", "now": "pass",
                                           "expect": [{"on": "boom", "path": "x", "equals": 1}]})
        self.assertEqual(result.status, "error")
        self.assertTrue(result.broken)

    def test_unchecked_kinds_and_cases_without_expect_are_listed_not_skipped(self):
        layout = cases.run_case(self.ctx, {"id": "l", "kind": "layout", "now": "pass"})
        prose = cases.run_case(self.ctx, {"id": "p", "kind": "title", "now": "fail", "why": "waits for the page"})
        self.assertEqual((layout.status, prose.status), ("not checked", "not checked"))
        self.assertIn("waits for the page", prose.details[0])
        out = "\n".join(cases.lines([layout, prose]))
        self.assertIn("not checked, by kind: layout 1, title 1", out)

    def test_a_case_the_runner_cant_read_says_why(self):
        self.assertIn("now must be pass or fail", cases.problems({"id": "x", "kind": "title", "now": "partial (built half)"})[0])
        self.assertTrue(cases.problems({"id": "x", "kind": "title", "now": "pass", "expect": "prose"}))
        self.assertIn("unknown surface", cases.problems({"id": "x", "kind": "title", "now": "pass", "expect": [{"on": "nowhere"}]})[0])
        self.assertIn("one test", cases.problems({"id": "x", "kind": "title", "now": "pass",
                                                   "expect": [{"on": "post", "post": "a", "path": "title"}]})[0])
        self.assertEqual(cases.problems({"id": "x", "kind": "same_story", "now": "pass",
                                         "expect": [{"on": "stories", "together": ["a", "b"]}]}), [])


class InvariantPatternTests(unittest.TestCase):
    """The invariants' own patterns, written apart from the title rules they measure."""

    def run_on(self, titles, text=""):
        run = invariants.Run("postgresql://unused/none", None, NOW)
        run._posts = {f"p{i}": {"title": t, "text": text, "has_words": True, "repeats_title": False, "footer": None, "byline": False}
                      for i, t in enumerate(titles)}
        return run

    def test_an_address_its_words_dont_lead_to(self):
        run = self.run_on(["A new release https://a.test/x", "Notes are at https://a.test/x", "paper: https://a.test/x",
                           "Read it → https://a.test/x", "No address here"])
        ids, of = invariants._title_ends_in_address(run)
        self.assertEqual((ids, of), (["p0"], 5))
        self.assertEqual(invariants._title_label_address(run)[0], ["p2"])

    def test_a_word_that_led_to_an_address_that_went(self):
        run = self.run_on(["The notes are at"], text="The notes are at https://a.test/notes and more")
        self.assertEqual(invariants._title_ends_on_lead(run)[0], ["p0"])
        run = self.run_on(["Where it came from"], text="Where it came from. A story.")
        self.assertEqual(invariants._title_ends_on_lead(run)[0], [], "no address after it")

    def test_a_rise_fails_unless_its_reason_is_named(self):
        found = [invariants.Found("title.over_300", "titles", "", 4, 10), invariants.Found("story.empty", "stories", "", 0, 10),
                 invariants.Found("story.identity", "stories", "", -1, 0)]
        self.assertEqual(invariants.compare(found, {"title.over_300": 2, "story.empty": 0, "story.identity": 0}, {}),
                         ["title.over_300: 2 -> 4"])
        self.assertEqual(invariants.compare(found, {"title.over_300": 2}, {"title.over_300": "0099 B: long names"}), [])


class DiffTests(unittest.TestCase):
    def test_a_titles_change_is_named_by_its_kind(self):
        before = {"a": {"title": "Release notes"}, "b": {"title": "A long title cut here"}, "c": {"title": "Same"},
                  "d": {"title": "Words then https://a.test/x"}, "e": {"title": "Gone soon"}}
        after = {"a": {"title": "Release notes for version 2"}, "b": {"title": "A long title"}, "c": {"title": "Same"},
                 "d": {"title": "Words then"}, "f": {"title": "New"}}
        kinds = {k: [c[0] for c in v] for k, v in diff.titles(before, after).items()}
        self.assertEqual(kinds, {"runs on (longer)": ["a"], "cut (shorter)": ["b"], "an address left": ["d"], "gone": ["e"], "new": ["f"]})

    def test_story_membership_joined_left_split_merged(self):
        member = lambda groups: {p: [[sid, "report", None]] for sid, ps in groups.items() for p in ps}   # noqa: E731
        before = {"member": member({"s1": ["a", "b", "c", "d"], "s2": ["e", "f"], "s3": ["g", "h"], "s4": ["x", "y"]}), "mentions": {}}
        after = {"member": member({"t1": ["a", "b"], "t2": ["c", "d"], "t3": ["e", "f", "g", "h"], "t4": ["x", "y", "z"]}), "mentions": {}}
        found = diff.membership(before, after)
        self.assertEqual([c[0] for c in found["split"]], ["s1"])
        self.assertEqual([c[0] for c in found["merged"]], ["t3"])
        self.assertEqual([c[0] for c in found["joined a story"]], ["z"])
        self.assertEqual([c[0] for c in found["gained or lost posts"]], ["s4"])
        self.assertNotIn("left every story", found)

    def test_news_and_discover(self):
        row = lambda lead, posts, voices=2: {"lead": lead, "title": lead, "posts": posts, "voices": voices, "first_at": "t", "part": "recent", "first": "s"}  # noqa: E731
        found = diff.news({"rows": [row("a", ["a", "b"]), row("c", ["c", "d"])]}, {"rows": [row("a", ["a", "b", "e"], 3), row("f", ["f", "g"])]})
        self.assertEqual(sorted(found), ["gone row", "new row", "posts changed", "voices changed"])
        s = lambda key, voices=3: {"key": key, "voices": voices, "origins": 0, "articles": 1, "names": []}   # noqa: E731
        found = diff.discover({"suggestions": [s("a.test"), s("b.test")]}, {"suggestions": [s("b.test", 4), s("a.test")]})
        self.assertEqual(sorted(found), ["moved", "voices changed"])

    def test_the_report_counts_every_thing_and_says_what_wasnt_compared(self):
        before = {"now": "t", "parts": {"posts": {"a": {"title": "x", "text": "y"}}}, "missing": {}}
        after = {"now": "t", "parts": {"posts": {"a": {"title": "x2", "text": "y"}}}, "missing": {"news": "absent"}}
        found = diff.compare(before, after)
        self.assertEqual(diff.counts(found)["titles"]["changed"], 1)
        self.assertIsNone(found["News"])
        text = diff.report(found, before, after, labels=("main", "branch"))
        self.assertIn("| titles | 1 |", text)
        self.assertIn("| News | not compared |", text)


class GuardTests(unittest.TestCase):
    def test_the_job_writes_only_a_scratch_copy(self):
        for name in ("insight", "insight_lab", "insight_server_copy", "insight_preview", "insight_lab_copy"):
            with self.assertRaises(SystemExit, msg=name):
                scratch_only(f"postgresql://u:p@h:5432/{name}")
        for name in ("insight_lab_check_a", "insight_lab_check_b", "insight_lab_0075a", "insight_run_1_test"):
            scratch_only(f"postgresql://u:p@h:5432/{name}")

    def test_rows_compared_by_table_and_story_ids_by_their_posts(self):
        a = {"stories": {("s1",), ("s2",)}, "story_posts": {("s1", "p1"), ("s1", "p2"), ("s2", "p3")}}
        b = {"stories": {("s1",), ("s9",)}, "story_posts": {("s1", "p1"), ("s1", "p2"), ("s9", "p3")}}
        self.assertEqual(table_rows.by_table(a, b), {"stories": 2, "story_posts": 2})
        self.assertEqual(table_rows.story_ids(b)[frozenset({"p3"})], "s9")


@unittest.skipUnless(db_url(), "no database")
class ReadOnlyTests(unittest.TestCase):
    def test_every_connection_a_check_opens_refuses_writes(self):
        code = (
            "import psycopg, sys\n"
            "from insight_core.checks.session import open_copy\n"
            "from insight_core.db import database as db\n"
            "url = sys.argv[1]\n"
            "refused = 0\n"
            "with open_copy(url) as conn, conn.cursor() as cur:\n"
            "    try:\n"
            "        cur.execute('CREATE TEMP TABLE check_write (a int)')\n"
            "    except psycopg.errors.ReadOnlySqlTransaction:\n"
            "        refused += 1\n"
            "try:\n"
            "    with db.transaction(url) as cur:\n"
            "        cur.execute('CREATE TEMP TABLE check_write (a int)')\n"
            "except psycopg.errors.ReadOnlySqlTransaction:\n"
            "    refused += 1\n"
            "print(refused)\n"
        )
        out = subprocess.run([sys.executable, "-c", code, db_url()], capture_output=True, text=True, cwd=str(BACKEND_DIR),
                             env={**os.environ, "PYTHONPATH": str(BACKEND_DIR)}, timeout=60)
        self.assertEqual(out.stdout.strip(), "2", out.stderr[-500:])


@requires_test_db
class RefsAndStoriesTests(unittest.TestCase):
    """Refs and story assertions on the test's own uncommitted rows (rolled back)."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        mark = uuid.uuid4().hex[:8]
        self.source = insert_source(self.cur, f"Example {mark}")
        self.other = insert_source(self.cur, f"Other {mark}")
        self.a = str(insert_post(self.cur, self.source, f"https://a-{mark}.test/2026/one/", title="First words here"))
        self.b = str(insert_post(self.cur, self.other, f"https://b-{mark}.test/two", title="Second post"))
        self.c = str(insert_post(self.cur, self.other, f"https://b-{mark}.test/three", title="Third post"))
        self.mark = mark
        self.cur.execute("UPDATE posts SET fetched_at = now() - interval '1 hour' WHERE id = %s", (self.b,))   # seen first
        for sid, posts in ((self.a, [self.a, self.b]), (self.c, [self.c])):
            self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, now(), %s)", (sid, len(posts)))
            for pid in posts:
                self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_reason) VALUES (%s, %s, 'report', %s, %s)",
                                 (pid, sid, f"voice:{pid}", None if pid == sid else "citation"))
        self.ctx = Context(db_url(), NOW, self.cur)

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def test_a_ref_by_address_normalized_address_or_source_and_words(self):
        self.assertEqual(self.ctx.ids(f"https://a-{self.mark}.test/2026/one/"), [self.a])
        self.assertEqual(self.ctx.ids(f"https://a-{self.mark}.test/2026/one"), [self.a], "the normalized address")
        self.assertEqual(self.ctx.ids({"source": f"Other {self.mark}", "title": "Third"}), [self.c])
        self.assertEqual(self.ctx.ids({"source": f"Other {self.mark}"}), [self.b, self.c], "first seen first")
        with self.assertRaises(refs.RefError):
            self.ctx.ids(f"https://nowhere-{self.mark}.test/x")

    def test_together_apart_and_via(self):
        together = {"on": "stories", "together": [f"https://a-{self.mark}.test/2026/one/", f"https://b-{self.mark}.test/two"]}
        self.assertTrue(cases.check(self.ctx, together)[0])
        self.assertTrue(cases.check(self.ctx, {**together, "via": "citation"})[0])
        self.assertFalse(cases.check(self.ctx, {**together, "via": "quote"})[0])
        apart = {"on": "stories", "apart": [f"https://a-{self.mark}.test/2026/one/", f"https://b-{self.mark}.test/three"]}
        self.assertTrue(cases.check(self.ctx, apart)[0])
        self.assertFalse(cases.check(self.ctx, {"on": "stories", "together": apart["apart"]})[0])


if __name__ == "__main__":
    unittest.main()
