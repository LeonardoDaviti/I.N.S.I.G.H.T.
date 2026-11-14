"""Issue 0206: the requests that still rebuilt per request, kept (markx/kept_pages.py), or paged in SQL.

  - the kept inputs (migration 0139): each committed writing transaction of an input moves its count; what a page
    does not read leaves it; folding the log into the base leaves every count;
  - the unread counts: kept bytes equal to the counted ones, sent kept (the counting patched to fail), counted again
    after a read, a post, a story; built by the jobs process too (the view "unread", also with Mark X off);
  - a topic track's page and the suggestions: built by the jobs process and sent kept; an owner's label (strict)
    builds it again, a worker's verdict (loose) is sent within its bound and makes the jobs process build it;
  - the sources' anatomy: kept KEPT_FOR, made again when a source is added;
  - the entity queue: paged in SQL, the same items and counts as reading every row;
  - the runner with Mark X off: only the reader's views.
Invented names only; a _test database."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import jobs, kept_pages, tracks
from insight_core.tests._db import db_url, insert_scratch_source
from insight_core.tests.test_markx_api import _Api, call
from insight_core.tests.test_markx_tracks import NOW, _Tracks, unit, verdict


class _Registry(_Api):
    def setUp(self):
        super().setUp()
        from insight_core.services import registry
        self.addCleanup(registry.use, registry.use(registry.build_services(db_url())))

    def changes(self, *names):
        return dict(map(tuple, kept_pages.changes(self.cur, names)))


class KeptInputs(_Registry):
    def test_each_writing_transaction_moves_its_inputs_count(self):
        before = self.changes("posts", "reads", "stories", "parts", "folders", "sources")
        p = self.post(title="One")
        after = self.changes("posts", "reads", "stories", "parts", "folders", "sources")
        self.assertEqual(after["posts"], before["posts"] + 1)
        self.assertEqual({k: v for k, v in after.items() if k != "posts"},
                         {k: v for k, v in before.items() if k != "posts"})
        self.cur.execute("INSERT INTO post_reader_state (post_id, read_at) VALUES (%s, now())", (p,))
        self.assertEqual(self.changes("reads")["reads"], before["reads"] + 1)
        reads = self.changes("reads")["reads"]
        self.cur.execute("UPDATE post_reader_state SET resume_block = 3 WHERE post_id = %s", (p,))   # a scroll
        self.assertEqual(self.changes("reads")["reads"], reads)
        posts = self.changes("posts")["posts"]
        self.cur.execute("UPDATE posts SET title = 'Renamed' WHERE id = %s", (p,))                  # not read
        self.assertEqual(self.changes("posts")["posts"], posts)
        self.cur.execute("UPDATE posts SET published_at = published_at - interval '1 hour' WHERE id = %s", (p,))
        self.assertEqual(self.changes("posts")["posts"], posts + 1)
        folders = self.changes("folders")["folders"]
        self.cur.execute("UPDATE sources SET settings = settings WHERE id = %s", (self.source,))    # a fetch's write
        self.assertEqual(self.changes("folders")["folders"], folders)
        self.cur.execute("UPDATE sources SET in_main_digest = NOT in_main_digest WHERE id = %s", (self.source,))
        self.assertEqual(self.changes("folders")["folders"], folders + 1)

    def test_one_transaction_is_one_change_and_folding_keeps_every_count(self):
        before = self.changes("posts")["posts"]
        with self.conn.transaction():
            for i in range(3):
                self.post(title=f"In one transaction {i}")
        self.assertEqual(self.changes("posts")["posts"], before + 1)
        counts = self.changes("posts", "reads", "stories", "parts", "folders", "sources")
        with self.conn.transaction():
            self.assertGreater(kept_pages.compact(self.cur, at_least=1), 0)
        self.assertEqual(self.changes("posts", "reads", "stories", "parts", "folders", "sources"), counts)
        self.cur.execute("SELECT count(*) FROM kept_input_changes")
        self.assertEqual(self.cur.fetchone()[0], 0)


class UnreadCounts(_Registry):
    def setUp(self):
        super().setUp()
        self.cur.execute("DELETE FROM mx_kept_pages WHERE page = 'unread'")
        self.addCleanup(self.cur.execute, "DELETE FROM mx_kept_pages WHERE page = 'unread'")

    def counted(self):
        from insight_core.db.repo_reader import ReaderRepository
        return json.loads(kept_pages.encode(ReaderRepository().unread_counts(self.cur)))

    def get(self):
        status, body = call("GET", "/api/feed/unread-counts")
        self.assertEqual(status, 200, body)
        return body

    def test_kept_while_nothing_changed_counted_again_after_a_change(self):
        from insight_core.db.repo_reader import ReaderRepository
        p = self.post(title="Unread one")
        first = self.get()
        self.assertEqual(first, self.counted())                            # counted and kept
        with mock.patch.object(ReaderRepository, "unread_counts", side_effect=AssertionError("counted")):
            self.assertEqual(self.get(), first)                            # sent kept
        self.cur.execute("INSERT INTO post_reader_state (post_id, read_at) VALUES (%s, now())", (p,))
        got = self.get()                                                   # a read: counted again, exact
        self.assertEqual(got, self.counted())
        self.post(title="Unread two")
        self.assertEqual(self.get(), self.counted())

    def test_the_jobs_process_keeps_them(self):
        from insight_core.services import reader_service
        self.post(title="Unread")
        self.assertTrue(reader_service.unread_missing(self.cur))
        with self.conn.transaction():
            self.assertEqual(reader_service.keep_unread_counts(self.cur)["built"], ["counts"])
        self.assertFalse(reader_service.unread_missing(self.cur))
        from insight_core.db.repo_reader import ReaderRepository
        with mock.patch.object(ReaderRepository, "unread_counts", side_effect=AssertionError("counted")):
            body = self.get()
        self.assertEqual(body, self.counted())

    def test_a_window_is_counted_on_every_request(self):
        from insight_core.services.reader_service import ReaderService
        from insight_core.db.repo_reader import ReaderRepository
        svc = ReaderService(db_url(), repo=ReaderRepository(unread_window_days=30))
        svc.unread_counts()
        self.cur.execute("SELECT count(*) FROM mx_kept_pages WHERE page = 'unread'")
        self.assertEqual(self.cur.fetchone()[0], 0)


class TrackPages(_Tracks):
    def setUp(self):
        super().setUp()
        self.describe()
        self.desc_vector(unit((0, 1)))
        self.cur.execute("DELETE FROM mx_kept_pages WHERE page = 'track'")
        self.addCleanup(self.cur.execute, "DELETE FROM mx_kept_pages WHERE page = 'track'")
        self.a, self.b = self.post(title="active in"), self.post(title="active two")
        self.plan()
        self.judge(self.a, verdict())

    def keep(self):
        with self.conn.transaction():
            return tracks.keep_pages(self.cur, now=NOW)

    def test_built_by_the_jobs_process_and_sent_kept(self):
        self.assertTrue(tracks.kept_missing(self.cur, NOW))
        built = self.keep()["built"]
        self.assertEqual(built, [self.folder, "suggestions"])
        self.assertFalse(tracks.kept_missing(self.cur, NOW))
        with self.conn.transaction():
            live = json.loads(kept_pages.encode(tracks.shown_page(self.cur, self.folder, now=NOW)))
        with mock.patch.object(tracks, "page", side_effect=AssertionError("built in the API")), \
                mock.patch.object(tracks, "suggestions", side_effect=AssertionError("built in the API")):
            self.assertEqual(self.page(), live)
            status, body = call("GET", "/api/markx/tracks/suggestions")
        self.assertEqual((status, body), (200, []))

    def test_an_owners_label_is_shown_at_once_a_workers_verdict_within_the_bound(self):
        self.keep()
        self.label(self.a, "out")                                          # strict: built again, at once
        self.assertNotIn(self.a, [it["post_id"] for s in self.page()["sections"] for it in s["items"]])
        self.keep()
        before = self.page()
        self.judge(self.b, verdict())                                      # loose: the worker's
        with mock.patch.object(tracks, "page", side_effect=AssertionError("built in the API")):
            self.assertEqual(self.page(), before)                          # sent kept, within KEPT_LAG
        self.assertTrue(tracks.kept_missing(self.cur, NOW), "the jobs process builds it again")
        self.keep()
        self.assertIn(self.b, [it["post_id"] for s in self.page()["sections"] for it in s["items"]])

    def test_never_sent_past_its_bound(self):
        self.keep()
        self.cur.execute("UPDATE mx_kept_pages SET until = now() - interval '1 second' WHERE page = 'track'")
        with mock.patch.object(tracks, "page", wraps=tracks.page) as built:
            self.page()
        self.assertEqual(built.call_count, 1)


class Anatomy(_Registry):
    def setUp(self):
        super().setUp()
        self.cur.execute("DELETE FROM mx_kept_pages WHERE page = 'anatomy'")
        self.addCleanup(self.cur.execute, "DELETE FROM mx_kept_pages WHERE page = 'anatomy'")

    def test_kept_its_bound_and_made_again_when_a_source_is_added(self):
        from insight_core.services.source_anatomy_service import SourceAnatomyService
        status, first = call("GET", "/api/sources/anatomy")
        self.assertEqual(status, 200, first)
        with mock.patch.object(SourceAnatomyService, "anatomy", side_effect=AssertionError("made")):
            self.assertEqual(call("GET", "/api/sources/anatomy")[1], first)
        new = insert_scratch_source(self.cur, platform="rss", enabled=True)
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (new,))
        _, again = call("GET", "/api/sources/anatomy")
        self.assertIn(new, [r["source_id"] for r in again["rows"]])
        self.cur.execute("UPDATE mx_kept_pages SET until = now() - interval '1 second' WHERE page = 'anatomy'")
        with mock.patch.object(SourceAnatomyService, "anatomy", wraps=None, return_value={"rows": []}) as made:
            call("GET", "/api/sources/anatomy")
        self.assertEqual(made.call_count, 1, "past KEPT_FOR: made again")


class EntityQueue(_Api):
    def test_paged_in_sql_the_same_items_and_counts(self):
        from insight_core.markx import entity_views
        ents = []
        for i in range(7):
            self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, status)
                                VALUES ('model', %s, %s, 'thing', 'provisional') RETURNING id::text""",
                             (f"Widget Q{i}", f"widget q{i}"))
            ents.append(self.cur.fetchone()[0])
        self.addCleanup(self.cur.execute, "DELETE FROM mx_entities WHERE id = ANY(%s::uuid[])", (ents,))
        self.addCleanup(self.cur.execute, "DELETE FROM mx_entity_queue WHERE a = ANY(%s::uuid[])", (ents,))
        for i in range(6):
            self.cur.execute("""INSERT INTO mx_entity_queue (kind, a, b, proposal, reason, confidence)
                                VALUES ('alias', %s, %s, 'same', 'test', %s)""", (ents[i], ents[i + 1], 0.5 + i / 20))
        with mock.patch.object(entity_views, "named_now", return_value=set(map(str, ents))):
            whole = entity_views.queue(self.cur)
            pages = [entity_views.queue(self.cur, limit=4, offset=o) for o in (0, 4)]
        self.assertEqual([i["id"] for p in pages for i in p["open"]], [i["id"] for i in whole["open"]])
        self.assertEqual([p["counts"]["open"] for p in pages], [6, 6])
        self.assertEqual([p["next_offset"] for p in pages], [4, None])
        self.assertEqual(len(whole["open"]), 6)


class DiscoverWindow(_Registry):
    def test_a_page_read_as_its_window_equals_the_whole_answer_paged(self):
        """0206: an open reads its page's suggestions sliced in Postgres; the same page as paging the whole answer."""
        from insight_core.db.repo_discover import DiscoverRepository
        from insight_core.services.stories_service import StoriesService, code_stamp
        self.cur.execute("SELECT value FROM system_settings WHERE key = 'discover_served'")
        kept = self.cur.fetchone()
        self.addCleanup(self.cur.execute, "DELETE FROM system_settings WHERE key = 'discover_served'")
        if kept:
            self.addCleanup(self.cur.execute, "INSERT INTO system_settings (key, value) VALUES ('discover_served', %s)",
                            (json.dumps(kept[0]),))
        svc = StoriesService(db_url())
        answer = {"success": True, "suggestions": [{"key": f"s{i}.example", "score": 1.0 - i / 10, "voices": 3}
                                                   for i in range(7)],
                  "also": [{"key": "also.example"}], "archives": [], "unnamed": [], "pages": [], "references": [],
                  "first_page": 30, "built_at": datetime.now(timezone.utc).isoformat()}
        with self.conn.transaction():
            inputs = svc.repo.discover_inputs(self.cur) + "|" + code_stamp()
            DiscoverRepository.keep_served(self.cur, inputs, answer["built_at"], answer)
        for offset, limit in ((0, 3), (2, 3), (5, 3), (9, 3)):
            got = svc.discover_served(offset=offset, limit=limit)
            whole = svc._page(answer, offset=offset, limit=limit)
            self.assertEqual({k: v for k, v in got.items() if k != "refreshing"}, whole, (offset, limit))


class TheRunnerWithMarkXOff(_Registry):
    def test_only_the_readers_views(self):
        states = {j: {"job": j, "wanted_at": None, "started_at": None, "stage": None, "stage_at": None,
                      "finished_at": None, "last": None, "failures": 0} for j in jobs.JOBS}
        states["decide"]["wanted_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
        now = datetime.now(timezone.utc)
        self.assertEqual(jobs.due(states, now, kept_missing=["tracks", "unread"], markx=False), "unread")
        self.assertIsNone(jobs.due(states, now, kept_missing=["tracks", "news"], markx=False))
        self.assertEqual(jobs.kept_due(states, ["news", "tracks", "unread"], now, markx=False), ["unread"])
        self.assertEqual(jobs.due(states, now, kept_missing=["unread"]), "decide")

    def test_with_mark_x_off_a_tick_writes_the_readers_rows_only(self):
        """The real-data check's markx.ix_unchanged: with Mark X off the runner keeps the unread counts; every mx_* row
        it writes is the reader's (jobs.reader_rows), and the job is a reader's view (jobs.readers)."""
        import os
        from insight_core.checks.job_checks import _mx_rows
        self.post(title="Unread with Mark X off")
        self.cur.execute("DELETE FROM mx_kept_pages WHERE page = 'unread'")
        self.cur.execute("DELETE FROM mx_jobs WHERE job = ANY(%s)", ([v.job for v in jobs.KEPT_VIEWS if not v.markx],))
        mx, reader = _mx_rows(self.cur), jobs.reader_rows(self.cur)
        with mock.patch.dict(os.environ, {"INSIGHT_MARKX": "off"}):
            ran = jobs.Runner(db_url(), spawn=False, plan_every=None).tick()
        self.assertTrue(jobs.readers(ran), ran)
        self.assertFalse(jobs.readers("decide") or jobs.readers("news") or jobs.readers(None))
        written = jobs.reader_rows(self.cur) - reader
        self.assertGreater(written, 0)
        self.assertEqual(_mx_rows(self.cur) - mx, written)
