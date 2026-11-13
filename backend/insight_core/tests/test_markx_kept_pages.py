"""Issue 0198: kept pages. Mark X News is built by the jobs process after each decision run (and again when what it
reads between runs changed) and sent as kept; an entity's page is built at its first open and kept. The kept bytes are
the route's own answer, byte for byte; a changed input is never sent stale (the page is built as before); the first
start, with nothing kept, answers as before. Invented names only; a _test database."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import entity_views as EV, jobs, kept_pages, labels, news, repo
from insight_core.tests import test_markx_built as built_tests
from insight_core.tests.test_markx_api import _Api, call
from insight_core.tests.test_markx_built import H
from insight_core.tests.test_markx_folds import read3
from insight_core.tests.test_markx_page_book import Ents


def _raw(path, query=None):
    """(status, body bytes, headers) of one GET through the app."""
    import asyncio
    import main
    from urllib.parse import urlencode

    async def go():
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(m):
            sent.append(m)
        scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "root_path": "",
                 "query_string": urlencode(query or {}).encode(), "headers": [(b"host", b"testserver")],
                 "scheme": "http", "server": ("testserver", 80), "client": ("127.0.0.1", 1), "http_version": "1.1"}
        await main.app(scope, receive, send)
        start = next(m for m in sent if m["type"] == "http.response.start")
        body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        return start["status"], body, {k.decode(): v.decode() for k, v in start.get("headers", [])}
    return asyncio.run(go())


class _World(Ents, _Api):
    """Two News rows over two stories with an entity named in them; the run finished. (test_markx_built.Stored's
    helpers, not its tests.)"""
    story, read, subject = built_tests.Stored.story, built_tests.Stored.read, built_tests.Stored.subject

    def setUp(self):
        super().setUp()
        self.run = repo.start_run(self.cur, code_version="test", config={})
        self.now = datetime.now(timezone.utc)
        now = self.now
        self.acme = self.ent("Acme")
        a = self.post(title="Acme releases Widget 5", at=now - 2 * H, links=[("https://acme.example/w5", "post")])
        b = self.post(title="Widget 5 is out", at=now - H, source=self.other, links=[("https://acme.example/w5", "post")])
        c = self.post(title="Gadget 2 launched", at=now - 3 * H)
        d = self.post(title="Gadget 2 is here", at=now - 3 * H, source=self.other)
        self.a, self.b = a, b
        self.s1, self.s2 = self.story(a, b, at=now - 2 * H), self.story(c, d, at=now - 3 * H)
        for p in (a, b):
            self.read(p, read3(origin="maker"))
            self.subject(p, "Widget 5")
        self.cur.execute("SELECT id::text FROM mx_entities WHERE key = 'widget 5'")
        self.widget = self.cur.fetchone()[0]
        self.cur.execute("""INSERT INTO mx_entity_surges (entity_id, day, voices, posts, rule, evidence)
                            VALUES (%s, %s, 2, 2, 'test', jsonb_build_object('posts', jsonb_build_array(%s::text)))""",
                         (self.acme, now.date(), a))
        repo.add_news_rows(self.cur, self.run, [
            {"id": a, "first_at": now - 2 * H, "voices": 2, "reports": 2, "shares": 0, "mentions": 0, "score": 5,
             "tag": "NEW", "posts": [{"post_id": p, "role": "report", "story": self.s1} for p in (a, b)]},
            {"id": c, "first_at": now - 3 * H, "voices": 2, "reports": 2, "shares": 0, "mentions": 0, "score": 4,
             "tag": "SAME", "posts": [{"post_id": p, "role": "report", "story": self.s2} for p in (c, d)]}])
        repo.finish_run(self.cur, self.run, counts={})

    def keep(self, now=None):
        with self.conn.transaction():
            return news.keep_pages(self.cur, now=now or self.now)

    def kept(self, only=True, now=None):
        return news.kept_page(self.cur, only_differences=only, now=now or self.now)

    def built(self, only=True, now=None):
        return kept_pages.encode(news.page(self.cur, only_differences=only, now=now or self.now))


class TheNewsPageKept(_World):

    def test_the_kept_views_are_the_built_pages_byte_for_byte(self):
        self.assertIsNone(self.kept())                                   # nothing kept yet
        got = self.keep()
        self.assertEqual(got["built"], ["differences", "all"])
        for only in (True, False):
            self.assertEqual(self.kept(only), self.built(only))
        self.assertEqual(len(json.loads(self.kept(False))["items"]), 2)
        self.assertEqual(len(json.loads(self.kept(True))["items"]), 1)
        self.assertEqual(self.keep()["built"], [])                       # kept already: nothing built again
        self.assertFalse(news.kept_missing(self.cur, self.now))

    def test_the_route_sends_the_kept_view_and_builds_when_none_is_kept(self):
        status, first, _ = _raw("/api/markx/news")                       # the first start: built as before
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(first)["counts"]["rows"], 2)
        self.keep(now=datetime.now(timezone.utc))
        with mock.patch.object(news, "page", side_effect=AssertionError("built, not sent as kept")):
            for query in ({}, {"all": 1}):
                status, body, headers = _raw("/api/markx/news", query)
                self.assertEqual(status, 200)
                self.assertEqual(headers["content-type"], "application/json")
                self.assertTrue(headers["etag"].startswith('W/"'))          # a conditional GET (routers/conditional)
                self.assertEqual(body, news.kept_page(self.cur, only_differences=not query))
        self.assertEqual(_raw("/api/markx/news")[1], self.built(now=datetime.now(timezone.utc)))

    def test_a_new_run_is_not_sent_the_last_runs_view(self):
        self.keep()
        run = repo.start_run(self.cur, code_version="test", config={})
        repo.finish_run(self.cur, run, counts={})
        self.assertIsNone(self.kept())
        self.assertTrue(news.kept_missing(self.cur, self.now))
        self.assertEqual(self.keep()["run"], str(run))
        self.assertEqual(self.kept(), self.built())

    def test_a_label_a_placement_a_sectioning_a_headline_mark_ixs_news_each_change_the_inputs(self):
        def changed(why, change):
            self.keep()
            self.assertIsNotNone(self.kept(), why)
            with self.conn.transaction():
                change()
            self.assertIsNone(self.kept(), why)                     # never sent stale: built as before
            self.assertTrue(news.kept_missing(self.cur, self.now), why)
            self.keep()
            self.assertEqual(self.kept(), self.built(), why)        # kept again, with the change

        changed("a News flag", lambda: labels_tap(self.cur, self.a, self.s1))
        sec_task = self.task("read")
        call_id = repo.add_call(self.cur, task_id=sec_task, executor="claude-code", model="m", valid=True, answer={})
        changed("a sectioning", lambda: self.cur.execute(
            "INSERT INTO mx_news_sections (task_id, call_id, run_id, position, title, row_ids) "
            "VALUES (%s, %s, %s, 0, 'Widgets', %s::uuid[])", (sec_task, call_id, self.run, [self.a])))
        place_task = self.task("read")
        place_call = repo.add_call(self.cur, task_id=place_task, executor="claude-code", model="m", valid=True, answer={})
        changed("a placement", lambda: self.cur.execute(
            "INSERT INTO mx_news_placements (task_id, call_id, base_call, row_id, title) VALUES (%s, %s, %s, %s, 'Widgets')",
            (place_task, place_call, call_id, self.a)))
        from insight_core.markx import schemas
        head, _ = repo.add_task(self.cur, kind="headline", guide=schemas.KINDS["headline"].guide, subject_kind="story",
                                input="Widget 5 headline", a=self.a)
        changed("a headline answered", lambda: self.cur.execute(
            "UPDATE mx_tasks SET status = 'answered', answered_at = now() WHERE id = %s", (head,)))
        changed("Mark IX's News", lambda: self.cur.execute(
            "INSERT INTO news_stories (id, first_at, voices, reports, shares, mentions, score) "
            "VALUES (%s, %s, 2, 2, 0, 0, 3)", (self.b, self.now - H)))
        changed("a merge", lambda: self.merge(self.ent("Acme Inc"), self.acme))

    def test_the_clock_only_changes_the_view_when_a_row_crosses_an_edge(self):
        self.keep()
        self.assertEqual(self.kept(now=self.now + timedelta(minutes=30)), self.built(now=self.now + timedelta(minutes=30)))
        later = self.now + timedelta(hours=46, minutes=30)                     # a row's 48 hours are over
        self.assertIsNone(self.kept(now=later))
        self.keep(now=later)
        self.assertEqual(self.kept(now=later), self.built(now=later))

    def test_another_codes_view_is_never_sent(self):
        self.keep()
        with mock.patch.object(kept_pages, "_code", "another deploy"):
            self.assertIsNone(self.kept())

    def test_only_the_newest_runs_views_stay(self):
        for _ in range(news.KEEP_RUNS + 2):
            run = repo.start_run(self.cur, code_version="test", config={})
            repo.finish_run(self.cur, run, counts={})
            self.keep()
        self.cur.execute("SELECT count(DISTINCT run_id), count(*) FROM mx_kept_pages WHERE page = 'news'")
        self.assertEqual(self.cur.fetchone(), (news.KEEP_RUNS, 2 * news.KEEP_RUNS))


def labels_tap(cur, post, story):
    repo.add_label(cur, item_kind="news_row", a=post, b=story, answer="wrong_story")


class TheJobsKeepNews(_World):
    """The runner keeps News' views right after a decision run (with the Labels queue, one after-run step), and again
    between runs when an input changed, at most every REBUILD_GAP seconds."""

    def runner(self):
        return jobs.Runner(self._db(), spawn=False, plan_every=None)

    def _db(self):
        from insight_core.tests._db import db_url
        return db_url()

    def test_the_first_start_keeps_the_missing_views_then_a_label_keeps_them_again(self):
        self.cur.execute("UPDATE mx_jobs SET started_at = now() WHERE job = 'decide'")   # no decision run due
        self.cur.execute("INSERT INTO mx_jobs (job, started_at) VALUES ('decide', now()) ON CONFLICT DO NOTHING")
        with mock.patch.object(labels, "missing", return_value=False):
            self.assertEqual(self.runner().tick(), "news")
            self.assertIsNotNone(news.kept_page(self.cur))
            s = jobs.state(self.cur)["news"]
            self.assertTrue(s["last"]["ok"], s["last"])
            self.assertEqual(s["last"]["built"], ["differences", "all"])
            self.assertIn("peak_mb", s["last"])
            self.assertIsNone(self.runner().tick())                                   # kept: nothing due
            labels_tap(self.cur, self.a, self.s1)
            self.assertIsNone(news.kept_page(self.cur))
            self.assertIsNone(self.runner().tick())                                   # within REBUILD_GAP
            self.cur.execute("UPDATE mx_jobs SET started_at = started_at - interval '61 seconds' WHERE job = 'news'")
            self.assertEqual(self.runner().tick(), "news")
            self.assertEqual(news.kept_page(self.cur), kept_pages.encode(news.page(self.cur)))

    def test_due_after_the_decision_run_and_its_gap_between_runs(self):
        t0 = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        states = {j: {"job": j, "wanted_at": None, "started_at": None, "stage": None, "stage_at": None,
                      "finished_at": None, "last": None} for j in jobs.JOBS}
        states["decide"]["started_at"] = t0 - timedelta(minutes=10)
        self.assertEqual(jobs.due(states, t0, kept_missing=["news", "labels"]), "news")
        states["news"]["started_at"] = t0 - timedelta(seconds=30)
        self.assertEqual(jobs.due(states, t0, kept_missing=["news", "labels"]), "labels")
        self.assertIsNone(jobs.due(states, t0, kept_missing=["news"]))
        self.assertEqual(jobs.kept_due(states, ["news", "labels"], t0, after_run=True), ["news", "labels"])   # a new run: at once

    def test_a_view_built_only_when_wanted_is_one_policy(self):
        """A view whose policy is "wanted" is built (after a run or not) only when its job was wanted since its last
        build: the same after-run step, no second path."""
        t0 = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        states = {j: {"job": j, "wanted_at": None, "started_at": t0 - timedelta(hours=1), "stage": None,
                      "stage_at": None, "finished_at": None, "last": None} for j in jobs.JOBS}
        states["decide"]["started_at"] = t0 - timedelta(minutes=10)                  # no decision run due
        views = (jobs.KEPT_VIEWS[0], jobs.KeptView("labels", jobs.KEPT_VIEWS[1].missing, when="wanted"))
        with mock.patch.object(jobs, "KEPT_VIEWS", views):
            self.assertEqual(jobs.kept_due(states, ["news", "labels"], t0, after_run=True), ["news"])
            states["labels"]["wanted_at"] = t0 - timedelta(minutes=1)
            self.assertEqual(jobs.kept_due(states, ["news", "labels"], t0, after_run=True), ["news", "labels"])
            self.assertEqual(jobs.due(states, t0, kept_missing=["labels"]), "labels")


class TheEntityPageKept(_World):

    PARAMS = dict(by_limit=50, replies=False, stories_limit=50, loose_limit=100)

    def open(self, eid=None, now=None):
        return EV.kept_entity_page(self.cur, eid or self.widget, now=now, **self.PARAMS)

    def built(self, eid=None, now=None):
        return kept_pages.encode(EV.entity_page(self.cur, eid or self.widget, now=now, offer_sample=True, **self.PARAMS))

    def test_built_at_the_first_open_then_sent_as_kept_byte_for_byte(self):
        first = self.open()
        self.assertEqual(first, self.built())
        with mock.patch.object(EV, "_entity_page", side_effect=AssertionError("built again")):
            self.assertEqual(self.open(), first)
        self.assertIsNone(self.open(eid="00000000-0000-0000-0000-000000000000"))   # no such entity: None (404)

    def test_the_route_answers_as_before(self):
        status, body, _ = _raw(f"/api/markx/entities/{self.widget}")
        self.assertEqual(status, 200)
        self.assertEqual(body, self.built())
        with mock.patch.object(EV, "_entity_page", side_effect=AssertionError("built again")):
            self.assertEqual(_raw(f"/api/markx/entities/{self.widget}")[1], body)
        self.assertEqual(call("GET", f"/api/markx/entities/{self.widget}")[1], json.loads(body))
        self.assertEqual(_raw("/api/markx/entities/00000000-0000-0000-0000-000000000000")[0], 404)

    def test_a_new_run_a_label_a_merge_a_mention_each_build_it_again(self):
        def changed(why, change):
            self.open()
            change()
            with mock.patch.object(EV, "_entity_page", wraps=EV._entity_page) as built:
                got = self.open()
            self.assertEqual(built.call_count, 1, why)
            self.assertEqual(got, self.built(), why)

        changed("a new run", lambda: repo.finish_run(self.cur, repo.start_run(self.cur, code_version="t", config={}),
                                                     counts={}))
        changed("a label", lambda: labels_tap(self.cur, self.a, self.s1))
        changed("a merge", lambda: self.merge(self.ent("Widget Five", "model"), self.widget))
        changed("a mention", lambda: self.subject(self.post(title="Widget 5 review"), "Widget 5"))

    def test_the_clock_edge_and_the_bound(self):
        self.open()
        self.cur.execute("SELECT until FROM mx_kept_pages WHERE page = 'entity'")
        until, = self.cur.fetchone()
        self.assertLessEqual(until, (self.now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                             + timedelta(days=1))
        with mock.patch.object(EV, "_entity_page", wraps=EV._entity_page) as built:
            self.open(now=until + timedelta(seconds=1))                               # its clock moved: built again
        self.assertEqual(built.call_count, 1)
        with mock.patch.object(EV, "ENTITY_PAGES", 2):
            for e in (self.acme, self.widget, self.ent("Gadget 2", "product")):
                self.open(eid=e)
        self.cur.execute("SELECT count(*) FROM mx_kept_pages WHERE page = 'entity'")
        self.assertEqual(self.cur.fetchone()[0], 2)

    def test_a_page_built_while_an_input_changed_is_answered_not_kept(self):
        real = EV._entity_page

        def racing(*a, **k):
            got = real(*a, **k)
            labels_tap(self.cur, self.a, self.s1)       # an answer lands while the page is built
            return got
        with mock.patch.object(EV, "_entity_page", side_effect=racing):
            body = self.open()
        self.assertIsNotNone(body)
        self.cur.execute("SELECT count(*) FROM mx_kept_pages WHERE page = 'entity'")
        self.assertEqual(self.cur.fetchone()[0], 0)
