"""Query-count guards (0279, pattern 3: N+1 small queries): each key path sends as many statements over a world twice
as big. The News page build, the entity page build, a decision run and each post planner run over one world at two
sizes; code whose statement count grows with the world is an N+1 and fails here, named by module and function (a
planner may add one task's writes per new task, PER_TASK). Invented names; a _test database."""
from __future__ import annotations

from datetime import datetime, timezone

from insight_core.markx import entity_views as EV, news, repo, schemas, tasks, track_things as TT
from insight_core.tests import test_markx_built as built_tests
from insight_core.tests import test_markx_decide as decide_tests
from insight_core.tests import test_track_briefer_0245 as briefer
from insight_core.tests._db import clear_tables
from insight_core.tests._query_budget import grown, statements
from insight_core.tests.test_markx_api import MX_TABLES, _Api
from insight_core.tests.test_markx_built import H
from insight_core.tests.test_markx_folds import read3
from insight_core.tests.test_markx_page_book import Ents

# a new task is a few statements (its INSERT; its kind's guide read; the hold and consumer checks): planned work, not
# an N+1
PER_TASK = 3
TASK_WRITE = {"markx/repo.py:add_task", "markx/repo.py:get_setting", "markx/schemas.py:ensure_guides",
              "markx/holds.py:hold_for", "markx/consumers.py:born_closed"}


def _why(name, small, big):
    return f"{name}: {small.total} -> {big.total} statements; grown: {dict(grown(small, big))}"


class _Pages(Ents, _Api):
    """`n` more stories of two posts each naming Widget 5 (read, News rows) a `world` call, the run finished."""
    story, read, subject = built_tests.Stored.story, built_tests.Stored.read, built_tests.Stored.subject

    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)
        self.ent("Acme")
        self.made = 0

    def world(self, n):
        self.run = repo.start_run(self.cur, code_version="test", config={})
        rows = []
        for i in range(self.made, self.made + n):
            a = self.post(title=f"Acme releases Widget 5 part {i}", at=self.now - (i + 1) * H,
                          links=[(f"https://acme.example/w5/{i}", "post")])
            b = self.post(title=f"Widget 5 part {i} is out", at=self.now - (i + 1) * H, source=self.other,
                          links=[(f"https://acme.example/w5/{i}", "post")])
            sid = self.story(a, b, at=self.now - (i + 1) * H)
            for p in (a, b):
                self.read(p, read3(origin="maker"))
                self.subject(p, "Widget 5")
            rows.append({"id": a, "first_at": self.now - (i + 1) * H, "voices": 2, "reports": 2, "shares": 0,
                         "mentions": 0, "score": 5, "tag": "NEW",
                         "posts": [{"post_id": p, "role": "report", "story": sid} for p in (a, b)]})
        self.made += n
        repo.add_news_rows(self.cur, self.run, rows)
        repo.finish_run(self.cur, self.run, counts={})
        self.cur.execute("SELECT id::text FROM mx_entities WHERE key = 'widget 5'")
        self.widget = self.cur.fetchone()[0]

    def measured(self, path):
        """The path's statements over 3 stories, then over 6."""
        self.world(3)
        with statements() as small:
            path()
        self.world(3)
        with statements() as big:
            path()
        return small, big


class ThePageBuilds(_Pages):
    def test_the_news_page_build_sends_as_many_statements_for_twice_the_rows(self):
        small, big = self.measured(lambda: news.reader_view(news.page(self.cur, only_differences=False, now=self.now)))
        self.assertEqual(dict(grown(small, big)), {}, _why("news page", small, big))

    def test_the_entity_page_build_sends_as_many_statements_for_twice_the_stories(self):
        small, big = self.measured(lambda: EV._full(self.cur, self.widget, now=self.now, replies=False))
        self.assertEqual(dict(grown(small, big)), {}, _why("entity page", small, big))

    def test_the_guard_sees_an_n_plus_one(self):
        def one_by_one():
            self.cur.execute("SELECT id FROM posts")
            for (pid,) in self.cur.fetchall():
                self.cur.execute("SELECT title FROM posts WHERE id = %s", (pid,))
        small, big = self.measured(one_by_one)
        self.assertEqual(dict(grown(small, big)), {"tests/test_query_budgets.py:one_by_one": 6})


class _Run(decide_tests.Job):
    def world(self, n):
        """`n` Mark IX stories of three read posts each, on an empty Mark X (each size starts alike)."""
        clear_tables(self.cur, MX_TABLES)
        schemas.load_guides(self.cur)
        self.cur.execute("DELETE FROM story_posts")
        self.cur.execute("DELETE FROM stories")
        self.cur.execute("DELETE FROM posts")
        for i in range(n):
            a = self.post(i, f"Acme released Widget {i}")
            b = self.post(i, f"Widget {i} is out")
            c = self.post(i, f"Widget {i} hands-on")
            self.ix_story(a, b, c)
            self.read_all([a, b, c])


# What a decision run's statements grow by from 3 stories (9 posts) to 6 (18), measured 2026-11-23 (0279 C1). Writes of
# new rows (a statement per new task, story, member, ask, post's handles) are the run's work; the reads are known
# N+1s, to be batched (0279 B3) and then removed from here. Nothing else may grow, nor these grow more.
RUN_WRITES = {"markx/repo.py:add_task": 15, "markx/schemas.py:ensure_guides": 15, "markx/repo.py:get_setting": 15,
              "markx/repo.py:add_story": 3,
              "markx/repo.py:open_membership": 9, "markx/significance.py:plan": 3, "markx/handles.py:scan_posts": 9}
RUN_KNOWN_READS = {"markx/reading5.py:pick": 3, "markx/news_sections.py:title_rows": 6, "markx/repo.py:task_for": 6,
                   "markx/incremental.py:_last_run": 1}


class ADecisionRun(_Run):
    def test_a_decision_run_grows_only_by_its_writes_and_the_known_reads(self):
        counts = []
        for n in (3, 6):
            self.world(n)
            with statements() as c:
                self.go()
            counts.append(c)
        allowed = {**RUN_WRITES, **RUN_KNOWN_READS}
        more = grown(*counts)
        self.assertEqual({k: v for k, v in more.items() if v > allowed.get(k, 0)}, {}, _why("decision run", *counts))


class ThePostPlanners(_Run):
    def test_each_post_planner_sends_as_many_statements_for_twice_the_posts_but_its_new_tasks(self):
        kinds = [k for k in ("read", "entities", "reading", "cite", "check") if k in tasks.PLANNERS]
        self.assertGreaterEqual(len(kinds), 4)
        for kind in kinds:
            counts, added = [], []
            for n in (3, 6):
                self.world(n)
                self.cur.execute("DELETE FROM mx_tasks WHERE kind <> 'read'")
                with statements() as c:
                    added.append(int(tasks.PLANNERS[kind](self.cur) or 0))
                counts.append(c)
            why = _why(f"planner {kind} (tasks added {added})", *counts)
            more = grown(*counts)
            self.assertEqual({k: v for k, v in more.items() if k not in TASK_WRITE}, {}, why)
            self.assertLessEqual(sum(v for k, v in more.items() if k in TASK_WRITE),
                                 PER_TASK * max(0, added[1] - added[0]), why)


class AThingsAnswer(briefer._Briefer):
    """POST /api/markx/answers for a track's things question (track_things.apply_things, in the API request): the
    track's reports are read once an answer, not once a thing of it (0279 D: was two track-wide reads a thing)."""

    PER_THING = {"markx/track_things.py:apply_things", "markx/track_things.py:reports",
                 "markx/track_things.py:remerge"}   # a thing's own rows: its INSERTs, its reports, its fields

    def test_an_answer_reads_its_track_once_whatever_its_things(self):
        f = self.track("prints")
        self.schema(f, "prints")
        names = [f"wall hook model {c}" for c in "abcde"]
        a = self.in_track(f, "Hooks", "Designs: " + names[0] + ".")
        b = self.in_track(f, "More hooks", "Designs: " + ". ".join(names[1:]) + ".")
        self.run_planner("track_things")
        counts = []
        for post, ns in ((a, names[:1]), (b, names[1:])):
            with statements() as c:
                self.things(f, post, *[{"kind": "print", "fields": {"what": briefer.v(n, n)}} for n in ns])
            counts.append(c)
        self.assertEqual(len(TT.current(self.cur, f, "print")), 5)
        more = grown(*counts)
        self.assertEqual({k: x for k, x in more.items() if k not in self.PER_THING}, {},
                         _why("things answer, 1 thing then 4", *counts))

