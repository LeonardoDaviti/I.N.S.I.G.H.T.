"""Issue 0198: kept pages. Mark X News is built by the jobs process after each decision run (and again when what it
reads between runs changed) and sent as kept; an entity's page is built at its first open and kept. The kept bytes are
the route's own answer, byte for byte; a changed input is never sent stale (the page is built as before); the first
start, with nothing kept, answers as before. Invented names only; a _test database."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import entity_views as EV, jobs, kept_pages, news, repo
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
        self.cur.execute("DELETE FROM mx_page_opens")   # 0232: the opens counted (no other test's table)
        self.addCleanup(self.cur.execute, "DELETE FROM mx_page_opens")
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

    def current(self, only=True, now=None):
        """0232: the view kept for the inputs now by this code (kept_page sends the newest kept one otherwise)."""
        run, st = news.page_inputs(self.cur, now or self.now)
        return kept_pages.get(self.cur, "news", news._view_key(only), run, st)

    def built(self, only=True, now=None):
        return kept_pages.encode(news.reader_view(news.page(self.cur, only_differences=only, now=now or self.now)))


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
        older = self.kept()
        self.assertIsNone(self.current())
        self.assertIsNotNone(older)                                 # 0232: the last run's view meanwhile
        self.assertTrue(news.kept_missing(self.cur, self.now))
        self.assertEqual(self.keep()["run"], str(run))
        self.assertEqual(self.kept(), self.built())

    def test_a_label_a_placement_a_sectioning_a_headline_mark_ixs_news_each_change_the_inputs(self):
        def changed(why, change):
            self.keep()
            before = self.kept()
            self.assertIsNotNone(before, why)
            with self.conn.transaction():
                change()
            self.assertIsNone(self.current(), why)
            with mock.patch.object(news, "page", side_effect=AssertionError("News built in a request")):
                self.assertEqual(self.kept(), before, why)          # 0232: the newest kept while the jobs build
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
        self.assertIsNone(self.current(now=later))
        self.keep(now=later)
        self.assertEqual(self.kept(now=later), self.built(now=later))

    def test_a_deploy_sends_the_previous_codes_view_while_its_inputs_are_the_same(self):
        """0232: a view kept by the code before a deploy is sent while its inputs are the same, and is missing for
        the jobs process (built again by this code); an input changed, the newest is sent until then."""
        self.keep()
        body = self.kept()
        with mock.patch.object(kept_pages, "_code", "another deploy"), \
                mock.patch.object(news, "page", side_effect=AssertionError("News built in a request")):
            self.assertEqual(self.kept(), body)
            self.assertIsNone(self.current())
            self.assertTrue(news.kept_missing(self.cur, self.now))
        with mock.patch.object(kept_pages, "_code", "another deploy"):
            self.assertEqual(self.keep()["built"], ["differences", "all"])
            self.assertFalse(news.kept_missing(self.cur, self.now))

    def test_another_shapes_view_is_never_sent(self):
        """0232: a view kept in another shape (news.SHAPE) is never sent, not even as the newest: built as before."""
        self.keep()
        with mock.patch.object(news, "SHAPE", "another shape"):
            self.assertIsNone(self.kept())

    def test_only_the_first_start_builds_news_in_a_request(self):
        self.assertIsNone(self.kept())                              # nothing ever kept: the route builds it
        self.keep()
        labels_tap(self.cur, self.a, self.s1)
        with mock.patch.object(news, "page", side_effect=AssertionError("News built in a request")):
            self.assertEqual(_raw("/api/markx/news")[0], 200)

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
    """The runner keeps News' views right after a decision run (the one after-run step), and again
    between runs when an input changed, at most every REBUILD_GAP seconds."""

    def runner(self):
        runner = jobs.Runner(self._db(), spawn=False, plan_every=None)
        runner.official_every = lambda: None   # 0209: official channels (never run here) would go first, overdue
        return runner

    def _db(self):
        from insight_core.tests._db import db_url
        return db_url()

    def test_the_first_start_keeps_the_missing_views_then_a_label_keeps_them_again(self):
        self.cur.execute("UPDATE mx_jobs SET started_at = now() WHERE job = 'decide'")   # no decision run due
        self.cur.execute("INSERT INTO mx_jobs (job, started_at) VALUES ('decide', now()) ON CONFLICT DO NOTHING")
        self.assertEqual(self.runner().tick(), "news")
        self.assertIsNotNone(news.kept_page(self.cur))
        s = jobs.state(self.cur)["news"]
        self.assertTrue(s["last"]["ok"], s["last"])
        self.assertEqual(s["last"]["built"], ["differences", "all"])
        self.assertIn("peak_mb", s["last"])
        self.assertIsNone(self.runner().tick())                                   # kept: nothing due
        labels_tap(self.cur, self.a, self.s1)
        self.assertTrue(news.kept_missing(self.cur))
        self.assertIsNone(self.runner().tick())                                   # within REBUILD_GAP
        self.cur.execute("UPDATE mx_jobs SET started_at = started_at - interval '61 seconds' WHERE job = 'news'")
        self.assertEqual(self.runner().tick(), "news")
        self.assertEqual(news.kept_page(self.cur), kept_pages.encode(news.reader_view(news.page(self.cur))))

    def test_due_after_the_decision_run_and_its_gap_between_runs(self):
        t0 = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        states = {j: {"job": j, "wanted_at": None, "started_at": None, "stage": None, "stage_at": None,
                      "finished_at": None, "last": None} for j in jobs.JOBS}
        states["decide"]["started_at"] = t0 - timedelta(minutes=10)
        self.assertEqual(jobs.due(states, t0, kept_missing=["news", "main_source"]), "news")
        states["news"]["started_at"] = t0 - timedelta(seconds=30)
        self.assertIsNone(jobs.due(states, t0, kept_missing=["news", "main_source"]))          # 0199: not asked for
        states["main_source"]["wanted_at"] = t0 - timedelta(minutes=1)
        self.assertEqual(jobs.due(states, t0, kept_missing=["news", "main_source"]), "main_source")
        self.assertIsNone(jobs.due(states, t0, kept_missing=["news"]))
        self.assertEqual(jobs.kept_due(states, ["news", "main_source"], t0, after_run=True), ["news", "main_source"])   # a new run: at once
        states["main_source"]["wanted_at"] = None
        self.assertEqual(jobs.kept_due(states, ["news", "main_source"], t0, after_run=True), ["news"])   # when wanted

    def test_a_view_built_only_when_wanted_is_one_policy(self):
        """0199: a "wanted" view (main_source; the Labels queue's policy before v10.22) is built (after a run or not)
        only when its job was wanted since its last build: the same after-run step, no second path."""
        t0 = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        states = {j: {"job": j, "wanted_at": None, "started_at": t0 - timedelta(hours=1), "stage": None,
                      "stage_at": None, "finished_at": None, "last": None} for j in jobs.JOBS}
        states["decide"]["started_at"] = t0 - timedelta(minutes=10)                  # no decision run due
        self.assertEqual([(v.job, v.when) for v in jobs.KEPT_VIEWS],
                         [("news", "always"), ("entities", "always"), ("tracks", "always"), ("unread", "always"),
                          ("main_source", "wanted"), ("discover", "wanted")])   # 0206
        self.assertEqual(jobs.kept_due(states, ["news", "main_source"], t0, after_run=True), ["news"])
        states["main_source"]["wanted_at"] = t0 - timedelta(minutes=1)
        self.assertEqual(jobs.kept_due(states, ["news", "main_source"], t0, after_run=True), ["news", "main_source"])
        self.assertEqual(jobs.due(states, t0, kept_missing=["main_source"]), "main_source")


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


class OneKeptPageServesEveryLimit(_World):
    """0232 (#13, #23): a request's limits are clamped into their caps, and one kept page an entity (built at the
    caps) is cut to every request's limits, byte for byte the page built at those limits."""

    def setUp(self):
        super().setUp()
        for i in range(4):   # posts naming Widget 5 in no story (the loose ones)
            self.subject(self.post(title=f"Widget 5 review {i}", at=self.now - (i + 2) * H), "Widget 5")

    def test_the_limits_clamp_and_never_error(self):
        self.assertEqual(EV.limits(), (50, 50, 100))
        self.assertEqual(EV.limits(100000, 100000, 100000), (EV.BY_CAP, EV.STORIES_CAP, EV.LOOSE_CAP))
        self.assertEqual(EV.limits(-5, 0, -1), (0, 1, 1))
        query = {"stories_limit": 100000, "loose_limit": 100000, "by_limit": 100000}
        status, body, _ = _raw(f"/api/markx/entities/{self.widget}", query)
        self.assertEqual(status, 200)
        self.assertEqual(body, kept_pages.encode(EV.entity_page(
            self.cur, self.widget, offer_sample=True, by_limit=EV.BY_CAP, stories_limit=EV.STORIES_CAP,
            loose_limit=EV.LOOSE_CAP)))
        self.assertEqual(_raw(f"/api/markx/entities/{self.widget}", {"stories_limit": -3, "by_limit": -1})[0], 200)

    def test_every_limit_is_cut_from_one_kept_page(self):
        asks = [dict(by_limit=50, stories_limit=50, loose_limit=100), dict(by_limit=0, stories_limit=1, loose_limit=1),
                dict(by_limit=1, stories_limit=2, loose_limit=3),
                dict(by_limit=100000, stories_limit=100000, loose_limit=100000)]
        with mock.patch.object(EV, "_entity_page", wraps=EV._entity_page) as built:
            got = [EV.kept_entity_page(self.cur, self.widget, **a) for a in asks]
        self.assertEqual(built.call_count, 1)                       # one build serves them all
        for a, body in zip(asks, got):
            by, stories, loose = EV.limits(a["by_limit"], a["stories_limit"], a["loose_limit"])
            self.assertEqual(body, kept_pages.encode(EV.entity_page(self.cur, self.widget, offer_sample=True,
                                                                    by_limit=by, stories_limit=stories,
                                                                    loose_limit=loose)), a)
        one = json.loads(got[1])
        self.assertEqual((len(one["stories"]), len(one["loose"])), (1, 1))
        self.assertEqual(one["loose_total"], 4)

    def test_the_cut_drops_the_by_posts_past_the_limit_and_counts_as_the_build(self):
        full = {"stories": [{"story": "s1"}, {"story": "s2"}],
                "loose": [{"id": "r1", "roles": ["subject"]}, {"id": "b1", "roles": ["by"]}, {"id": "b2", "roles": ["by"]},
                          {"id": "b3", "roles": ["by"]}, {"id": "m1", "roles": ["mention"]}],
                "loose_counts": {"report": 1, "by": 3, "other": 0, "mention": 1}}
        cut = EV._cut(full, 1, 1, 10)
        self.assertEqual([x["id"] for x in cut["loose"]], ["r1", "b1", "m1"])
        self.assertEqual((cut["loose_total"], len(cut["stories"])), (3, 1))
        self.assertEqual([x["id"] for x in EV._cut(full, 0, 2, 1)["loose"]], ["r1"])
        self.assertEqual(EV._cut(full, 0, 2, 1)["loose_total"], 2)

    def test_opens_are_counted_and_another_shape_is_never_sent(self):
        for _ in range(3):
            EV.kept_entity_page(self.cur, self.widget)
        EV.kept_entity_page(self.cur, self.acme)
        self.assertEqual(kept_pages.most_opened(self.cur, "entity", 5),
                         [f"{self.widget}?replies=0", f"{self.acme}?replies=0"])
        with mock.patch.object(EV, "PAGE_SHAPE", EV.PAGE_SHAPE + "-next"), \
                mock.patch.object(EV, "_entity_page", wraps=EV._entity_page) as built:
            EV.kept_entity_page(self.cur, self.widget)
        self.assertEqual(built.call_count, 1)

    def test_a_deploy_sends_the_previous_codes_page_while_its_inputs_are_the_same(self):
        first = EV.kept_entity_page(self.cur, self.widget)
        key = kept_pages.shaped(f"{self.widget}?replies=0", EV.PAGE_SHAPE)
        with mock.patch.object(kept_pages, "_code", "another deploy"):
            with mock.patch.object(EV, "_entity_page", side_effect=AssertionError("built again")):
                self.assertEqual(EV.kept_entity_page(self.cur, self.widget), first)
            run, parts = EV.page_inputs(self.cur, self.widget)
            self.assertIsNone(kept_pages.get(self.cur, "entity", key, run, kept_pages.stamp("entity", key, parts)))
            labels_tap(self.cur, self.a, self.s1)                   # an input changed: never the old page
            with mock.patch.object(EV, "_entity_page", wraps=EV._entity_page) as built:
                EV.kept_entity_page(self.cur, self.widget)
            self.assertEqual(built.call_count, 1)


class TheEntityListAndQueueKept(_World):
    """0216 item 5: the entity list and the queue's first page kept by the jobs process (job "entities"), sent by the
    routes byte for byte; built as before when nothing is kept for their inputs; with the most opened entity pages."""

    def keep(self):
        with self.conn.transaction():
            return EV.keep_pages(self.cur)

    def test_the_list_kept_byte_for_byte_and_built_again_when_an_input_changes(self):
        self.assertTrue(EV.kept_missing(self.cur))
        out = self.keep()
        self.assertEqual(out["built"], ["entities", "entity_queue"])
        self.assertFalse(EV.kept_missing(self.cur))
        with mock.patch.object(EV, "entity_list", side_effect=AssertionError("built, not sent as kept")):
            status, body, _ = _raw("/api/markx/entities")
        self.assertEqual(status, 200)
        self.assertEqual(body, kept_pages.encode(EV.entity_list(self.cur)))
        self.merge(self.ent("Widget Five", "model"), self.widget)    # an owner's mark: built again, never stale
        self.assertTrue(EV.kept_missing(self.cur))
        with mock.patch.object(EV, "entity_list", wraps=EV.entity_list) as built:
            body = EV.kept_list(self.cur)
        self.assertEqual(built.call_count, 1)
        self.assertEqual(body, kept_pages.encode(EV.entity_list(self.cur)))

    def test_the_queues_first_page_kept_other_pages_built(self):
        self.keep()
        with mock.patch.object(EV, "queue", side_effect=AssertionError("built, not sent as kept")):
            status, body, _ = _raw("/api/markx/entities/queue")
        self.assertEqual(status, 200)
        self.assertEqual(body, kept_pages.encode(EV.queue(self.cur, **EV.QUEUE_KEPT)))
        with mock.patch.object(EV, "queue", wraps=EV.queue) as built:
            self.assertEqual(_raw("/api/markx/entities/queue", {"limit": 10})[0], 200)
        self.assertEqual(built.call_count, 1)

    def test_the_most_opened_pages_are_built_after_a_run(self):
        EV.kept_entity_page(self.cur, self.widget)
        self.keep()
        self.assertFalse(EV.kept_missing(self.cur))
        repo.finish_run(self.cur, repo.start_run(self.cur, code_version="t", config={}), counts={})
        self.assertTrue(EV.kept_missing(self.cur))                  # a new run: the opened page is missing
        out = self.keep()
        self.assertEqual(out["hot"]["pages"], 1)
        self.assertFalse(EV.kept_missing(self.cur))
        with mock.patch.object(EV, "_entity_page", side_effect=AssertionError("built, not sent as kept")):
            EV.kept_entity_page(self.cur, self.widget)


class TheFirstLookAfterADeploy(_World):
    """0232 (#24): at the runner's start (a deploy), its first look builds News and the entity pages before any job."""

    def test_the_after_deploy_views_go_first(self):
        from insight_core.tests._db import db_url
        runner = jobs.Runner(db_url(), spawn=False, plan_every=None)
        runner.official_every = lambda: None
        runner.fresh = True                                          # set by start()
        self.assertEqual(runner.tick(), "news")                      # though a decision run is due (none ran)
        self.assertFalse(runner.fresh)
        self.assertFalse(news.kept_missing(self.cur))
        self.assertFalse(EV.kept_missing(self.cur))
        self.assertEqual([v.job for v in jobs.KEPT_VIEWS if v.after_deploy], ["news", "entities"])


import re  # noqa: E402


def _paths(value, at=""):
    """The JSON's key paths (a list's items as one `[]`), sorted: what a page's shape is made of."""
    out = set()
    if isinstance(value, dict):
        for k, v in value.items():
            k = "<id>" if re.fullmatch(r"[0-9a-f-]{36}", str(k)) else k   # a dict keyed by ids: one path
            out.add(f"{at}.{k}")
            out |= _paths(v, f"{at}.{k}")
    elif isinstance(value, list):
        for v in value:
            out |= _paths(v, f"{at}[]")
    return out


class TheShapesAreNamed(_World):
    """0232: a page kept by the previous code is sent after a deploy only while its key's shape is the same. The shape
    of each such page (on this test's world) is frozen here with its SHAPE: a change of what the page answers fails
    this test until its module's SHAPE is bumped and the new shape recorded (then an older page is never sent)."""

    def setUp(self):
        super().setUp()
        for i in range(4):
            self.subject(self.post(title=f"Widget 5 review {i}", at=self.now - (i + 2) * H), "Widget 5")

    FROZEN = {"news": ("3", "89f3b3d2fda1404e"), "entity": ("4", "fd5ba899b59a4c67"),
              "entities": ("1", "4efd649ca53508be"), "entity_queue": ("1", "aa10ad3c5d2a3012")}

    def shapes(self):
        import hashlib
        with self.conn.transaction():
            news.keep_pages(self.cur, now=self.now)
            EV.keep_pages(self.cur)
        got = {"news": json.loads(self.kept()), "entity": json.loads(EV.kept_entity_page(self.cur, self.widget)),
               "entities": json.loads(EV.kept_list(self.cur)),
               "entity_queue": json.loads(EV.kept_queue(self.cur, **EV.QUEUE_KEPT))}
        return {k: hashlib.sha256("\n".join(sorted(_paths(v))).encode()).hexdigest()[:16] for k, v in got.items()}

    def test_each_kept_shape_is_its_modules_shape(self):
        shapes = self.shapes()
        named = {"news": news.SHAPE, "entity": EV.PAGE_SHAPE, "entities": EV.LIST_SHAPE, "entity_queue": EV.QUEUE_SHAPE}
        self.assertEqual({p: (named[p], shapes[p]) for p in self.FROZEN}, self.FROZEN,
                         "a page's answer changed shape: bump its module's SHAPE and record the new pair here")
