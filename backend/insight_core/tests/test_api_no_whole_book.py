"""v10.17 (issue 0186): no API request reads the whole entity book. The News page read it twice a load (250k entities
on the server, 20 s), the entity, post and story pages, Discover's main source and the entity queue once each. A
request asks a page's book (identity.lazy_book) for what it shows; only the jobs (the decision run's stages, the
planners, the command line) read the whole book. Two guards, so a new route that reads it fails here:

  - every call of identity.load_book (and of read_ents without ids, the whole read) is in a job function listed in
    JOBS, read from the source;
  - every GET route of the app (its OpenAPI paths), and the owner's entity answers, run over a seeded world with
    load_book and the whole read recording: none is called.
Invented names only; a _test database."""
from __future__ import annotations

import ast
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from insight_core.markx import identity as I, repo
from insight_core.tests.test_markx_api import call
from insight_core.tests import test_markx_built as built_tests
from insight_core.tests.test_markx_built import H
from insight_core.tests.test_markx_folds import read3
from insight_core.tests.test_markx_page_book import Ents

ROOT = Path(__file__).resolve().parents[1]
# (file, function): the jobs that read the whole book (insight-ingestion's decision run and its stages, the command
# line, the components measurement). Never an API route's.
JOBS = {
    ("markx/decide.py", "run"),
    ("markx/entity_stage.py", "entities"),
    ("markx/entity_stage.py", "repairs"),
    ("markx/identity.py", "stage"),
    ("markx/entity_addresses.py", "stage"),
    ("markx/perspectives.py", "stage"),
    ("markx/surges.py", "stage"),
    ("markx/handles.py", "main"),
}


def whole_reads():
    """[(file, function, line)] of every load_book call and every read_ents call without ids, outside the tests."""
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        if "tests" in p.parts:
            continue
        rel = p.relative_to(ROOT).as_posix()
        stack = []

        class V(ast.NodeVisitor):
            def visit_FunctionDef(self, n):
                stack.append(n.name)
                self.generic_visit(n)
                stack.pop()
            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, n):
                f = n.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if name == "load_book" or (name == "read_ents" and len(n.args) + len(n.keywords) < 3
                                            and (rel, stack[-1] if stack else "") != ("markx/identity.py", "load_book")):
                    out.append((rel, stack[0] if stack else "", n.lineno))
                self.generic_visit(n)

        V().visit(ast.parse(p.read_text()))
    return out


def forget_voice_suggestions():
    """GET /api/voices/suggestions computes the suggestions in the background and keeps them, committed, for a day:
    a later module's suggestions() would read those (its own new sources not in them) instead of computing again.
    Wait for that run, drop the route's service and the kept suggestions."""
    import psycopg
    from insight_core.routers import voices as route
    from insight_core.services.voices_service import SUGGESTIONS_KEY
    from insight_core.tests._db import db_url
    svc = route._service
    if svc is not None and svc._computing.acquire(timeout=300):
        svc._computing.release()
    route.use(None)
    with psycopg.connect(db_url(), autocommit=True) as conn:
        conn.execute("DELETE FROM system_settings WHERE key = %s", (SUGGESTIONS_KEY,))


class OnlyJobsReadTheWholeBook(unittest.TestCase):
    def test_every_whole_read_is_a_jobs(self):
        found = whole_reads()
        self.assertTrue(found)                               # the scan sees the jobs' own reads
        self.assertEqual([(f, fn, line) for f, fn, line in found if (f, fn) not in JOBS], [])


class NoRouteReadsTheWholeBook(Ents, built_tests.Stored):
    """Every GET route over a seeded world (an entity with posts, a merge, a version, a News row, a story, a queue
    item, a surge, an address), and the owner's entity answers, with the whole book's reads recorded."""

    def setUp(self):
        super().setUp()
        now = datetime.now(timezone.utc)
        self.acme = self.ent("Acme")
        self.posts = [self.post(title=f"Acme releases Widget 5 ({i})", at=now - i * H,
                                source=(self.source, self.other)[i % 2],
                                links=[("https://acme.example/blog/widget-5", "post")]) for i in range(1, 4)]
        for p in self.posts:
            self.subject(p, "Widget 5")
            self.read(p, read3(origin="maker"))
        self.cur.execute("SELECT id::text FROM mx_entities WHERE key = 'widget 5'")
        self.widget = self.cur.fetchone()[0]
        self.cur.execute("UPDATE mx_entities SET maker = 'Acme' WHERE id = %s", (self.widget,))
        v = self.ent("Widget 5.1", "model", parent=self.widget)
        self.cur.execute("UPDATE mx_entities SET level = 'version', version = '5.1' WHERE id = %s", (v,))
        dup = self.ent("Widget Five", "model")
        self.merge(dup, self.widget)
        self.other_ent = self.ent("Widget V", "model")
        self.cur.execute("""INSERT INTO mx_entity_queue (kind, a, b, proposal, reason, confidence)
                            VALUES ('alias', %s, %s, 'same', 'test', 0.7) RETURNING id::text""",
                         (self.other_ent, self.widget))
        self.item = self.cur.fetchone()[0]
        self.cur.execute("""INSERT INTO mx_entity_surges (entity_id, day, voices, posts, rule, evidence)
                            VALUES (%s, %s, 2, 2, 'test', jsonb_build_object('posts', jsonb_build_array(%s::text)))""",
                         (self.widget, now.date(), self.posts[0]))
        self.sid = self.story(*self.posts, at=now - 3 * H)
        repo.add_news_rows(self.cur, self.run, [{"id": self.posts[0], "first_at": now - 3 * H, "voices": 2,
                                                  "reports": 3, "shares": 0, "mentions": 0, "score": 5, "tag": "NEW",
                                                  "posts": [{"post_id": p, "role": "report", "story": self.sid}
                                                            for p in self.posts]}])
        repo.finish_run(self.cur, self.run, counts={})
        self.reads = []
        whole = I.load_book
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(I, "load_book", lambda *a, **k: self.reads.append("load_book") or whole(*a, **k)).start()

    def params(self):
        return {"entity_id": self.widget, "post_id": self.posts[0], "story_id": self.sid, "item_id": self.item,
                "source_id": self.source, "subject_id": self.source}

    def test_no_get_route_reads_the_whole_book(self):
        import main
        from insight_core.services import registry
        from insight_core.tests._db import db_url
        self.addCleanup(registry.use, registry.use(registry.build_services(db_url())))   # every route's services
        self.addCleanup(forget_voice_suggestions)
        mock.patch.dict("os.environ", {"INSIGHT_DISCOVER_READS": "0"}).start()   # no web reads in the background
        params = self.params()
        asked = []
        for path, ops in sorted(main.app.openapi()["paths"].items()):
            names = re.findall(r"{(\w+)}", path)
            if "get" not in ops or any(n not in params for n in names) or path.startswith("/api/export"):
                continue
            url = path
            for n in names:
                url = url.replace("{" + n + "}", params[n])
            before = len(self.reads)
            try:
                call("GET", url, token=self.token)
            except Exception:  # noqa: BLE001 - a route failing for want of a service is not this test's
                pass
            if len(self.reads) > before:
                asked.append(path)
        self.assertGreater(len(main.app.openapi()["paths"]), 50)
        self.assertEqual(asked, [])

    def test_the_guard_sees_a_route_that_reads_it(self):
        from insight_core.markx import entity_views
        real = entity_views.post_entities
        with mock.patch.object(entity_views, "post_entities", lambda cur, pid: (I.load_book(cur), real(cur, pid))[1]):
            call("GET", f"/api/markx/posts/{self.posts[0]}")
        self.assertEqual(self.reads, ["load_book"])

    def test_the_owners_entity_answers_read_no_whole_book(self):
        status, body = call("POST", f"/api/markx/entities/{self.widget}/sources",
                            body={"source_ids": [self.source], "answer": "no"})
        self.assertEqual(status, 200, body)
        status, body = call("POST", f"/api/markx/entities/{self.acme}/handles",
                            body={"platform": "x", "handle": "acme", "answer": "yes"})
        self.assertEqual(status, 200, body)
        status, body = call("POST", f"/api/markx/entities/queue/{self.item}", body={"answer": "same"})
        self.assertEqual(status, 200, body)
        from insight_core.markx import research
        with mock.patch.object(research, "seed_links", return_value=[]):
            research.start(self.cur, "Widget 5", kind="name")
        self.assertEqual(self.reads, [])
        self.cur.execute("""SELECT count(*) FROM mx_entity_redirects WHERE undone_at IS NULL
                              AND ((from_id = %(a)s AND to_id = %(b)s) OR (from_id = %(b)s AND to_id = %(a)s))""",
                         {"a": self.other_ent, "b": self.widget})
        self.assertEqual(self.cur.fetchone()[0], 1)   # the answer merged them, through a page's book


for _name in [n for n in dir(built_tests.Stored) if n.startswith("test")]:   # the seeding base's own tests run in their module
    setattr(NoRouteReadsTheWholeBook, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
