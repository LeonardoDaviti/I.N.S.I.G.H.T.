"""Planners and kept-view builds run in the jobs process, never in an API request (0279, pattern 2: heavy work at
request time). Two guards: every call of a planner (tasks.PLANNERS / FRESH_PLANNERS) and of a kept-view build
(news / entity_views / tracks keep_pages, track_kept.refresh) is in a function listed here, read from the source; and
every GET route of the app over a seeded world plans nothing, the lease (GET /api/markx/work) included: since v10.47
(0279 B2) the jobs' lane (markx/jobs.py Jobs.lane) runs the planners a lease ran. A new caller anywhere fails here."""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from unittest import mock

from insight_core.markx import tasks
from insight_core.tests import test_api_no_whole_book as whole_book
from insight_core.tests import test_markx_api as markx_api
from insight_core.tests.test_markx_api import call

ROOT = Path(__file__).resolve().parents[1]
PLANNER_TABLES = ("PLANNERS", "FRESH_PLANNERS")
BUILDS = ("keep_pages", "refresh")              # the kept views' builds (news, entity_views, tracks; track_kept)
BUILD_OWNERS = ("news", "mx_news", "entity_views", "EV", "tracks", "mx_tracks", "track_kept")
# (file, function) allowed to call them: the jobs process only (its lane: the planners a lease ran until v10.47)
JOBS = {("markx/jobs.py", "plan_background"), ("markx/jobs.py", "_keep_track_places"), ("markx/jobs.py", "news"),
        ("markx/jobs.py", "entities"), ("markx/jobs.py", "tracks"), ("markx/jobs.py", "lane")}


def callers():
    """[(file, function, line, what)] of every planner call and kept-view build call outside the tests and the
    planners' own module."""
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        if "tests" in p.parts:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel == "markx/tasks.py":   # the registry itself (a planner composed of planners)
            continue
        stack = []

        class V(ast.NodeVisitor):
            def visit_FunctionDef(self, n):
                stack.append(n.name)
                self.generic_visit(n)
                stack.pop()
            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, n):
                f = n.func
                what = None
                if isinstance(f, ast.Subscript):
                    v = f.value
                    name = v.attr if isinstance(v, ast.Attribute) else getattr(v, "id", None)
                    if name in PLANNER_TABLES:
                        what = name
                elif isinstance(f, ast.Attribute) and f.attr in BUILDS:
                    owner = f.value.id if isinstance(f.value, ast.Name) else None   # a module, not self.news
                    if owner in BUILD_OWNERS:
                        what = f"{owner}.{f.attr}"
                if what:
                    out.append((rel, stack[0] if stack else "", n.lineno, what))
                self.generic_visit(n)
        V().visit(ast.parse(p.read_text()))
    return out


class OnlyTheJobsPlanAndBuild(unittest.TestCase):
    def test_every_planner_and_build_call_is_the_jobs(self):
        found = callers()
        self.assertTrue(any(f == "markx/jobs.py" for f, *_ in found))   # the scan sees the jobs' own calls
        self.assertEqual([c for c in found if (c[0], c[1]) not in JOBS], [])

    def test_the_lane_runs_the_fresh_planners(self):
        self.assertTrue(any((f, fn, what) == ("markx/jobs.py", "lane", "FRESH_PLANNERS") for f, fn, _l, what in callers()))


class NoGetRoutePlans(whole_book.NoRouteReadsTheWholeBook):
    """Every GET route over the seeded world of test_api_no_whole_book, the lease included, each planner recording."""

    def test_no_get_route_plans(self):
        import main
        from insight_core.services import registry
        from insight_core.tests._db import db_url
        self.addCleanup(registry.use, registry.use(registry.build_services(db_url())))
        self.addCleanup(whole_book.forget_voice_suggestions)
        mock.patch.dict("os.environ", {"INSIGHT_DISCOVER_READS": "0"}).start()
        planned = []
        for table in PLANNER_TABLES:
            real = getattr(tasks, table)
            mock.patch.object(tasks, table, {k: (lambda k, f: lambda *a, **kw: planned.append(k) or f(*a, **kw))(k, f)
                                             for k, f in real.items()}).start()
        params = self.params()
        asked = []
        for path, ops in sorted(main.app.openapi()["paths"].items()):
            names = re.findall(r"{(\w+)}", path)
            if "get" not in ops or any(n not in params for n in names) or path.startswith("/api/export"):
                continue
            url = path
            for n in names:
                url = url.replace("{" + n + "}", params[n])
            before = len(planned)
            try:
                call("GET", url, token=self.token)
            except Exception:  # noqa: BLE001 - a route failing for want of a service is not this test's
                pass
            if len(planned) > before:
                asked.append(path)
        self.assertEqual(asked, [])


for _name in [n for n in dir(whole_book.NoRouteReadsTheWholeBook) if n.startswith("test")]:
    setattr(NoGetRoutePlans, _name, None)   # the base's own tests run in their module
del _name


class TheLeaseOnlyLeases(markx_api._Api):
    """v10.47 (0279 B2): a lease and /ready plan nothing, whatever waits (no task, a new post, a changed window); the
    lane plans what the lease used to."""
    plan = True

    def test_a_lease_plans_nothing_and_the_lane_plans_its_new_post(self):
        pid = self.post(title="A deal closed")
        planned = []
        for table in PLANNER_TABLES:
            real = getattr(tasks, table)
            mock.patch.object(tasks, table, {k: (lambda k, f: lambda *a, **kw: planned.append(k) or f(*a, **kw))(k, f)
                                             for k, f in real.items()}).start()
            self.addCleanup(mock.patch.stopall)
        call("POST", "/api/markx/settings/reading-window", body={"days": 120})   # a changed window: the lease waits
        status, body = self.lease("read,entities,embed", limit=20, plan=False)
        self.assertEqual((status, body["tasks"], planned), (200, [], []), body)
        status, body = call("GET", "/api/markx/ready", query={"kinds": "read,entities"}, token=self.token)
        self.assertEqual((status, body["ready"], body["planned"], planned), (200, [], [], []), body)
        out = self.lane()
        self.assertIn("read", planned)
        # v10.48: the process's resident MB before, after and trimmed, in its record (it runs in the scheduler's)
        self.assertEqual(len(out["rss_mb"]), 3)
        self.assertTrue(all(x > 0 for x in out["rss_mb"]), out["rss_mb"])
        status, body = self.lease("read", limit=20, plan=False)
        self.cur.execute("SELECT id::text FROM mx_tasks WHERE kind = 'read' AND a = %s", (pid,))
        self.assertEqual([t["id"] for t in body["tasks"]], [r[0] for r in self.cur.fetchall()])

    def test_ready_says_come_back_soon_while_the_jobs_plan(self):
        from insight_core.markx import jobs

        def soon():
            return call("GET", "/api/markx/ready", query={"kinds": "read"}, token=self.token)[1]["retry_after"]
        self.cur.execute("DELETE FROM mx_jobs")
        self.assertIsNone(soon())                                   # no job planning, no lane row yet: rest
        self.lane()
        self.assertIsNone(soon())                                   # the lane passed just now, nothing wanted
        with self.conn.transaction():
            jobs.want(self.cur, "decide")                           # a decision run is on its way (or a restart's)
        self.assertEqual(soon(), jobs.LANE_EVERY)
        self.cur.execute("UPDATE mx_jobs SET wanted_at = NULL")
        self.cur.execute("UPDATE mx_jobs SET finished_at = now() - interval '5 minutes', "
                         "started_at = now() - interval '5 minutes' WHERE job = 'lane'")
        self.assertEqual(soon(), jobs.LANE_EVERY)                   # the lane not seen lately: the jobs restart
