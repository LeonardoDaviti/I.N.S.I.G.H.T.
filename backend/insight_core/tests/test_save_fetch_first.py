"""Saving a page of a source you follow (issue 0122): the source is fetched first, the page is its post
(found by the fetch, or saved as its post), and a feed that brings it later makes one post, not two.

No network: the fetch job is stubbed (main._run_ingestion_job) and FakeHttp answers the page. The tests
commit rows, so they run only against a `_test` database; they own every source and post on the
example sites below.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

import main
from insight_core.db import repo_linked
from insight_core.db.repo_posts import PostsRepository
from insight_core.services import registry
from insight_core.services.saved_service import REFETCH_WITHIN
from insight_core.tests._asgi import call
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp

BLOG = "https://blog.ffblog.example"
FEED = f"{BLOG}/feed.xml"
LINKBLOG = "https://links.fflinks.example"
ELSEWHERE = "https://pages.ffpages.example"
PAGE = f"{BLOG}/p/the-new-post"
PARAGRAPH = "<p>" + "A paragraph of the new post, the one the feed was not fetched for yet. " * 12 + "</p>"


def article(title: str = "The new post", date: str | None = "2026-11-06T07:00:00Z") -> str:
    dated = f'<meta property="article:published_time" content="{date}"/>' if date else ""
    return (f'<!DOCTYPE html><html><head><title>{title} | Blog</title><meta property="og:title" content="{title}"/>{dated}'
            f'</head><body><article><h1>{title}</h1>{PARAGRAPH}</article></body></html>')


@requires_test_db
class FetchFirstTests(unittest.TestCase):
    def setUp(self):
        previous = registry.use(registry.build_services(db_url()))
        self.addCleanup(registry.use, previous)
        registry.services().saved.source_config_sync = mock.Mock(sync_db_to_json=mock.Mock())
        self.addCleanup(self._clean)
        self._clean()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        registry.services().saved.clock = lambda: self.now
        self.blog = self._source("rss", FEED, enabled=True, name="Example Blog")
        for slug in ("one", "two", "three"):
            self._post(self.blog, f"{BLOG}/p/{slug}", f"Post {slug}", self.now - timedelta(days=3))
        self.job = mock.AsyncMock(return_value={})
        patcher = mock.patch.object(main, "_run_ingestion_job", self.job)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            like = ("http%.ffblog.example%", "http%.ff_____.example%")
            cur.execute("DELETE FROM posts WHERE url LIKE %s OR url LIKE %s", like)
            cur.execute("DELETE FROM job_runs WHERE source_id IN (SELECT id FROM sources WHERE handle_or_url LIKE %s"
                        " OR handle_or_url LIKE %s OR platform = 'saved')", like)
            cur.execute("DELETE FROM sources WHERE handle_or_url LIKE %s OR handle_or_url LIKE %s OR platform = 'saved'", like)

    def _rows(self, sql, *args):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall() if cur.description else None

    def _source(self, platform, handle, *, enabled=True, name=None):
        settings = json.dumps({"display_name": name} if name else {})
        ((source_id,),) = self._rows("INSERT INTO sources (platform, handle_or_url, enabled, settings) "
                                     "VALUES (%s, %s, %s, %s::jsonb) RETURNING id::text", platform, handle, enabled, settings)
        return source_id

    def _post(self, source_id, url, title, at, *, links=(), metadata=None):
        post = {"url": url, "title": title, "content": f"{title}. " + "Words of the post. " * 20, "date": at,
                "external_id": url, "metadata": metadata or {}}
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            post_id, _ = PostsRepository(db_url()).upsert_post(cur, post, source_id)
            for n, target in enumerate(links):
                cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, %s, %s)",
                            (post_id, target, target.split("/")[2], n))
        return str(post_id)

    def save(self, responses=None, url=PAGE, *, after_fetch=False, title="The new post"):
        with mock.patch.object(main, "FEED_FINDER_HTTP", FakeHttp(responses or {})):
            status, _, body = call(main.app, "POST", "/api/saved",
                                   json_body={"url": url, "title": title, "after_fetch": after_fetch})
        self.assertEqual(status, 200, body)
        return body

    def _jobs(self):
        return self._rows("SELECT id::text, status, payload FROM job_runs WHERE job_type = 'ingestion_run' AND source_id = %s",
                          self.blog)

    # ---- whose page it is (0084 B's rule)

    def test_a_page_of_the_shape_of_a_followed_sources_posts_is_its_page(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(repo_linked.page_source(cur, PAGE), self.blog)
            self.assertEqual(repo_linked.page_source(cur, PAGE + "?utm_source=x"), self.blog)
            self.assertIsNone(repo_linked.page_source(cur, f"{BLOG}/about"))
            self.assertIsNone(repo_linked.page_source(cur, f"{ELSEWHERE}/p/the-new-post"))
        status, _, body = call(main.app, "GET", "/api/saved/source", query={"url": PAGE})
        self.assertEqual((status, body["source"]), (200, {"id": self.blog, "name": "Example Blog"}))

    def test_a_disabled_source_owns_nothing(self):
        self._rows("UPDATE sources SET enabled = false WHERE id = %s::uuid", self.blog)
        status, _, body = call(main.app, "GET", "/api/saved/source", query={"url": PAGE})
        self.assertIsNone(body["source"])

    # ---- 1. the click fetches the source, once

    def test_saving_its_page_fetches_the_source_first_and_once(self):
        first = self.save({PAGE: article()})
        self.assertEqual((first["status"], first["source"]), ("fetching", {"id": self.blog, "name": "Example Blog"}))
        ((job_id, status, payload),) = self._jobs()
        self.assertEqual((first["job_id"], status, payload["selector"], payload["force"]),
                         (job_id, "running", {"kind": "source", "id": self.blog}, True))
        self.job.assert_awaited_once()
        (request,), kwargs = self.job.await_args
        self.assertEqual((request.selector.kind, request.selector.id, kwargs["job_id"]), ("source", self.blog, job_id))
        # A second save while it runs waits for the same fetch.
        again = self.save({PAGE: article()})
        self.assertEqual((again["status"], again["job_id"]), ("fetching", job_id))
        self.assertEqual(len(self._jobs()), 1)
        self.job.assert_awaited_once()
        self.assertEqual(self._rows("SELECT count(*) FROM posts WHERE url = %s", PAGE), [(0,)], "nothing saved yet")

    def test_the_fetch_brought_it_the_answer_is_the_sources_post_in_later(self):
        self.save({PAGE: article()})
        fetched = self._post(self.blog, PAGE, "The new post", self.now - timedelta(hours=2))   # what the fetch stored
        body = self.save({PAGE: article()}, after_fetch=True)
        self.assertEqual((body["status"], body["post_id"], body["source"]),
                         ("already", fetched, {"id": self.blog, "name": "Example Blog"}))
        self.assertEqual(self._rows("SELECT count(*) FROM posts WHERE url LIKE %s", PAGE + "%"), [(1,)])
        ((later_at,),) = self._rows("SELECT later_at FROM post_reader_state WHERE post_id = %s::uuid", fetched)
        self.assertEqual(later_at, self.now)

    def test_the_feed_doesnt_list_it_it_is_saved_as_the_sources_post(self):
        self.save({PAGE: article()})
        body = self.save({PAGE: article()}, after_fetch=True)
        self.assertEqual((body["status"], body["source_id"], body["source"]["name"], body["readable"]),
                         ("saved", self.blog, "Example Blog", True))
        ((source_id, published_at, surfaced_at, metadata, later_at),) = self._rows(
            "SELECT p.source_id::text, p.published_at, p.surfaced_at, p.metadata, rs.later_at FROM posts p "
            "LEFT JOIN post_reader_state rs ON rs.post_id = p.id WHERE p.id = %s::uuid", body["post_id"])
        self.assertEqual((source_id, published_at, surfaced_at, later_at),
                         (self.blog, datetime(2026, 11, 6, 7, tzinfo=timezone.utc), self.now, self.now))
        self.assertEqual(metadata["saved_by_owner"], self.now.isoformat())
        self.assertEqual(self._rows("SELECT count(*) FROM sources WHERE platform = 'saved'"), [(0,)], "not the Saved source")
        _, _, feed = call(main.app, "GET", "/api/feed", query={"scope": f"source:{self.blog}", "filter": "all"})
        row = next(item for item in feed["items"] if item["id"] == body["post_id"])
        self.assertEqual((row["source_display_name"], row["saved_by_you"]), ("Example Blog", True))
        self.assertFalse(any(item["saved_by_you"] for item in feed["items"] if item["id"] != body["post_id"]))
        _, _, detail = call(main.app, "GET", f"/api/posts/item/{body['post_id']}")
        self.assertEqual((detail["post"]["source_display_name"], detail["post"]["metadata"]["saved_by_owner"]),
                         ("Example Blog", self.now.isoformat()))

    def test_a_page_that_states_no_date_is_dated_by_the_first_post_linking_it(self):
        other = self._source("rss", f"{ELSEWHERE}/feed.xml")
        first_link = self.now - timedelta(days=5)
        self._post(other, f"{ELSEWHERE}/a-retelling", "A retelling", first_link, links=[PAGE])
        self._post(other, f"{ELSEWHERE}/a-later-retelling", "A later retelling", first_link + timedelta(hours=9), links=[PAGE])
        body = self.save({PAGE: article(date=None)}, after_fetch=True)
        ((published_at, surfaced_at),) = self._rows("SELECT published_at, surfaced_at FROM posts WHERE id = %s::uuid",
                                                    body["post_id"])
        self.assertEqual((published_at, surfaced_at), (first_link, self.now), "dated by its first link, sorted at the save")
        # Linked by nothing: the save time, as every save.
        lone = self.save({f"{BLOG}/p/lone": article("Lone", date=None)}, url=f"{BLOG}/p/lone", after_fetch=True)
        ((published_at,),) = self._rows("SELECT published_at FROM posts WHERE id = %s::uuid", lone["post_id"])
        self.assertEqual(published_at, self.now)

    def test_a_source_tried_in_the_last_15_minutes_is_not_fetched_again(self):
        self._rows("INSERT INTO source_fetch_state (source_id, last_attempt_at, last_success_at, last_outcome) "
                   "VALUES (%s::uuid, %s, %s, 'healthy')", self.blog, self.now - REFETCH_WITHIN + timedelta(minutes=1),
                   self.now - REFETCH_WITHIN + timedelta(minutes=1))
        body = self.save({PAGE: article()})
        self.assertEqual((body["status"], body["source_id"]), ("saved", self.blog))
        self.assertEqual(self._jobs(), [])
        self.job.assert_not_awaited()

    def test_a_source_in_backoff_is_not_fetched(self):
        self._rows("INSERT INTO source_fetch_state (source_id, last_attempt_at, last_outcome, consecutive_failures, next_retry_at) "
                   "VALUES (%s::uuid, %s, 'error', 2, %s)", self.blog, self.now - timedelta(hours=2), self.now + timedelta(hours=1))
        body = self.save({PAGE: article()})
        self.assertEqual((body["status"], body["source_id"]), ("saved", self.blog))
        self.job.assert_not_awaited()

    def test_a_page_no_followed_source_owns_is_saved_as_today(self):
        url = f"{ELSEWHERE}/an-essay"
        body = self.save({url: article("An essay")}, url=url)
        self.assertEqual((body["status"], body["source"]), ("saved", None))
        ((platform, metadata),) = self._rows("SELECT s.platform, p.metadata FROM posts p JOIN sources s ON s.id = p.source_id "
                                             "WHERE p.id = %s::uuid", body["post_id"])
        self.assertEqual(platform, "saved")
        self.assertNotIn("saved_by_owner", metadata)
        self.job.assert_not_awaited()

    def test_a_page_no_source_owns_that_states_no_date_is_dated_by_its_first_link_too(self):
        """Issue 0113 (0122's open point 5): a Saved page with no date of its own takes its first link's, not the
        save time, so its story's 72 hours are its links'. It still sorts at the save."""
        url = f"{ELSEWHERE}/an-undated-essay"
        other = self._source("rss", "https://chan.ffchans.example/feed.xml")
        first_link = self.now - timedelta(days=6)
        self._post(other, "https://chan.ffchans.example/p/1", "A retelling", first_link, links=[url])
        body = self.save({url: article("An undated essay", date=None)}, url=url)
        ((published_at, surfaced_at),) = self._rows("SELECT published_at, surfaced_at FROM posts WHERE id = %s::uuid",
                                                    body["post_id"])
        self.assertEqual((published_at, surfaced_at), (first_link, self.now))

    # ---- 2. the feed brings it later: one post

    def _feed_brings(self, source_id, url, title, at):
        post = {"url": url, "title": title, "content": "The feed's summary. " * 5, "date": at, "external_id": "guid-" + title,
                "metadata": {"adapter": "rss"}}
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            return str(PostsRepository(db_url()).upsert_post(cur, post, source_id)[0])

    def _state(self, post_id):
        return self._rows("SELECT read_at IS NOT NULL, later_at IS NOT NULL, starred_at IS NOT NULL FROM post_reader_state "
                          "WHERE post_id = %s::uuid", post_id)

    def test_the_feed_bringing_a_page_saved_as_its_post_keeps_one_post_and_your_state(self):
        self.save({PAGE: article()})
        saved = self.save({PAGE: article()}, after_fetch=True)["post_id"]
        registry.services().reader.set_read([saved], True, keep_later=True)
        # The feed's form of the address and its own title.
        got = self._feed_brings(self.blog, PAGE + "/?utm_source=rss", "The new post, as the feed titles it", self.now)
        self.assertEqual(got, saved)
        ((url, source_id, title, metadata),) = self._rows(
            "SELECT url, source_id::text, title, metadata FROM posts WHERE id = %s::uuid", saved)
        self.assertEqual((url, source_id, title), (PAGE + "/?utm_source=rss", self.blog, "The new post, as the feed titles it"))
        self.assertEqual((metadata["saved_by_owner"], metadata["adapter"]), (self.now.isoformat(), "rss"))
        self.assertEqual(self._rows("SELECT count(*) FROM posts WHERE url LIKE %s", PAGE + "%"), [(1,)])
        self.assertEqual(self._state(saved), [(True, True, False)])

    def test_a_page_saved_under_saved_moves_to_the_source_that_owns_it(self):
        saved_source = registry.services().saved.saved_source_id()
        old = self._post(saved_source, PAGE, "The new post", self.now - timedelta(hours=1), metadata={"adapter": "saved"})
        registry.services().reader.set_later([old], True, self.now)
        self._rows("INSERT INTO post_reader_state (post_id, starred_at) VALUES (%s::uuid, now()) "
                   "ON CONFLICT (post_id) DO UPDATE SET starred_at = now()", old)
        got = self._feed_brings(self.blog, PAGE, "The new post", self.now - timedelta(hours=3))
        self.assertEqual(got, old)
        ((source_id, metadata, published_at),) = self._rows(
            "SELECT source_id::text, metadata, published_at FROM posts WHERE id = %s::uuid", old)
        self.assertEqual(source_id, self.blog)
        self.assertIn("saved_by_owner", metadata)
        self.assertEqual(published_at, self.now - timedelta(hours=3), "the feed's date")
        self.assertEqual(self._state(old), [(False, True, True)])
        self.assertEqual(self._rows("SELECT count(*) FROM posts WHERE url LIKE %s", PAGE + "%"), [(1,)])

    def test_a_collected_page_moving_to_the_source_that_owns_it_is_that_source_s_post(self):
        """Issue 0126 (2): a page shown only inside its story is a row of the feed once it is a followed source's post."""
        saved_source = registry.services().saved.saved_source_id()
        old = self._post(saved_source, PAGE, "The new post", self.now - timedelta(hours=1),
                         metadata={"adapter": "saved", "collected_original": self.now.isoformat(), "story_only": True})
        for brought in ({}, {"adapter": "rss"}):   # a feed with no metadata of its own, or some
            post = {"url": PAGE, "title": "The new post", "content": "The feed's summary. " * 5,
                    "date": self.now - timedelta(hours=3), "external_id": "guid-collected", "metadata": brought}
            with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
                self.assertEqual(str(PostsRepository(db_url()).upsert_post(cur, post, self.blog)[0]), old)
            ((source_id, metadata),) = self._rows("SELECT source_id::text, metadata FROM posts WHERE id = %s::uuid", old)
            self.assertEqual(source_id, self.blog)
            self.assertNotIn("story_only", metadata, brought)
            self.assertNotIn("saved_by_owner", metadata)
            self.assertIn("collected_original", metadata)

    def test_another_form_and_title_of_a_page_saved_under_saved_is_still_one_post(self):
        saved_source = registry.services().saved.saved_source_id()
        old = self._post(saved_source, PAGE, "The new post | Blog", self.now - timedelta(hours=1), metadata={"adapter": "saved"})
        got = self._feed_brings(self.blog, "http://www.blog.ffblog.example/p/the-new-post/", "The new post", self.now)
        self.assertEqual(got, old)
        self.assertEqual(self._rows("SELECT source_id::text FROM posts WHERE id = %s::uuid", old), [(self.blog,)])
        self.assertEqual(self._rows("SELECT count(*) FROM posts WHERE normalized_url = "
                                    "(SELECT normalized_url FROM posts WHERE id = %s::uuid)", old), [(1,)])

    def test_a_link_blog_bringing_a_saved_page_never_takes_it(self):
        saved_source = registry.services().saved.saved_source_id()
        links = self._source("rss", f"{LINKBLOG}/feed.xml")
        for n in range(3):   # a link blog's items are the pages it links
            self._post(links, f"{ELSEWHERE}/linked-{n}", f"Linked {n}", self.now - timedelta(days=n + 1))
        old = self._post(saved_source, PAGE, "The new post", self.now - timedelta(hours=1), metadata={"adapter": "saved"})
        got = self._feed_brings(links, PAGE, "The new post", self.now)
        self.assertEqual(got, old, "one post, as today")
        self.assertEqual(self._rows("SELECT source_id::text FROM posts WHERE id = %s::uuid", old), [(saved_source,)])


if __name__ == "__main__":
    unittest.main()
