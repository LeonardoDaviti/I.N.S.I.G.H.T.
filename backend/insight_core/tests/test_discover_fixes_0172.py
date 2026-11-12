"""Issue 0172: Discover's correctness and speed (v10.15 part F). The answer served is the last one built (built
in the background, keyed on what changes it); suggestions credited, kept or dropped by class: other channels by a
real relation, non-channels by their pages' shape, a moved site's old address, an unlinked row's rank, a site's
declared account, a passing failure asked again soon, its own pages' sections, a link blog's archive row, one card
per domain; a Pages row followed at its section or account. Invented names only.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
import psycopg.types.json

from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import KindRegistry
from insight_core.services import discover_reads
from insight_core.services import stories_service
from insight_core.services.stories_service import REFRESH_AFTER, StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests._stories import insert_source
from insight_core.tests.test_discover_reads import bridge_rss
from insight_core.tests.test_feed_finder import page, rss
from insight_core.utils import discover_rules as R

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


class OtherChannelTests(unittest.TestCase):
    """b2: "Other channels" credited a site to a source by a word shared with its name."""

    def credited(self, key, name, *, account="", publication=""):
        return R.other_channel(key, *R.channel_names(name, account=account, publication=publication))

    def test_a_word_of_a_name_credits_no_site_or_section(self):
        self.assertFalse(self.credited("dailypaper.example/science", "Acme Science Digest",
                                       publication="acmesciencedigest.example"), "a newspaper's section")
        self.assertFalse(self.credited("country.example", "Country Talk", publication="countrytalk.example"),
                         "a portal named by the country")
        self.assertFalse(self.credited("blog.cloudvendor.example", "Jane Roe Cloud Attention",
                                       publication="janeroe.example"), "a cloud company's blog")

    def test_its_own_addresses_and_whole_name_credit_it(self):
        self.assertTrue(self.credited("x.com/countrytalk", "Country Talk", publication="countrytalk.example"),
                        "its site's word as an account")
        self.assertTrue(self.credited("x.com/acmelabs_ai", "Acme Labs", publication="news.acmelabs.example"))
        self.assertTrue(self.credited("acmelabs.example", "Acme Labs", account="x.com/acmelabs"), "its account's name")

    def test_a_brands_own_top_level_domain_names_it(self):
        """v10.15.2: a company's blog at blog.<brand> named nothing of its owner ("blog"), so cloud.<brand>.com left its
        other channels for the suggestions, with the sources named by their feed address that link it."""
        self.assertTrue(self.credited("cloud.acmebrand.example", "News from Acmebrand", publication="blog.acmebrand"))
        self.assertFalse(self.credited("cloud.other.example", "News from Acmebrand", publication="blog.acmebrand"))
        self.assertFalse(self.credited("news.example", "Someone", publication="blog.news"), "a generic suffix names no one")
        self.assertFalse(self.credited("cloud.acmebrand.example", "Acme Notes", publication="acmenotes.example"),
                         "a site whose word names someone: as before")

    def test_an_account_on_a_read_platform_by_a_word_of_the_name(self):
        self.assertTrue(self.credited("x.com/janer", "Jane Roe", publication="janeroe.example"),
                        "a handle the owner chose, starting with a word of the name")
        self.assertFalse(self.credited("hub.example/jane", "Jane Roe", publication="janeroe.example"),
                         "an owner on a platform no kind reads: no name word")


class NotChannelTests(unittest.TestCase):
    """b3: model listings, paper forums, interactive pages, readerless platforms, hub orgs are no channel."""

    def kind(self, key, *paths):
        return R.place_kind(key, [f"https://{key}{p}" for p in paths])

    def test_pages_told_by_their_query_are_interactive(self):
        self.assertEqual(self.kind("papers.example", "/forum?id=abc123", "/forum?id=def456"), "app")
        self.assertEqual(self.kind("tool.example", "/?q=a+b", "/compare?model=a&other=b"), "app")
        self.assertIsNone(self.kind("lab.example", "/blog?id=a-post", "/blog?id=another"),
                          "a blog drawn by its script is a publication (its account may be offered)")

    def test_a_catalogue_of_models_is_a_listing(self):
        self.assertEqual(self.kind("router.example", "/models/acme/a-model", "/models/other/b"), "listing")
        self.assertIsNone(self.kind("news.example", "/2026/11/a-story", "/tech/another"))

    def test_owners_on_a_hub_or_a_readerless_platform(self):
        self.assertTrue(R.not_channel("huggingface.co/acmelabs", None), "a model hub's owner")
        self.assertTrue(R.not_channel("github.com/acmelabs", "headlines"), "a code host's org without a feed")
        self.assertFalse(R.not_channel("github.com/acmelabs", "feed"), "with its activity feed")
        self.assertTrue(R.not_channel("network.example/in/someone", "blocked"))
        self.assertFalse(R.not_channel("x.com/someone", "headlines"), "an account a kind reads: its test decides")
        self.assertFalse(R.not_channel("site.example", "headlines"), "a site stays in the unfollowable section")


class OrderTests(unittest.TestCase):
    def test_an_unlinked_row_never_outranks_a_linked_one(self):
        rows = [{"key": "linked.example", "score": 2.0, "voices": 3},
                {"key": "originals.example", "score": 9.0, "voices": 0}]
        self.assertEqual([s["key"] for s in R.order(rows)], ["linked.example", "originals.example"])


class FollowUrlTests(unittest.TestCase):
    """c3: a Pages row followed its bare domain (a tweet: the platform's home)."""

    def test_its_section_or_its_account(self):
        self.assertEqual(R.follow_url("https://x.com/someone/status/2000000000000000001"), "https://x.com/someone")
        self.assertEqual(R.follow_url("https://lab.example/news/a-model"), "https://lab.example/news/")
        self.assertEqual(R.follow_url("https://lab.example/2026/11/a-story"), "https://lab.example/", "never a year")
        self.assertEqual(R.follow_url("https://lab.example/a-story"), "https://lab.example/")
        self.assertIsNone(R.follow_url("https://youtube.com/watch?v=abc"), "a page naming no account")


def registry(http):
    return KindRegistry.default(http, None)


class FollowTestTests(unittest.TestCase):
    def read(self, http, url, linked=()):
        return asyncio.run(discover_reads.follow_read(http, registry(http), url, list(linked)))

    def test_an_old_domain_landing_on_another_site_says_where(self):
        """b1: an old domain redirecting to the site it moved to."""
        http = FakeHttp({"https://old.example/": page('<link rel="alternate" type="application/rss+xml" href="/feed">'),
                         "https://new.example/feed": rss("New")},
                        redirects={"https://old.example/": "https://new.example/"})
        got = self.read(http, "https://old.example")
        self.assertEqual(got.get("moved_to"), "new.example")

    def test_a_bridge_hiccup_is_asked_again_soon(self):
        """b6: a bridge's 5xx or a timeout labelled an account "headlines" for 30 days."""
        http = FakeHttp(lambda url: HttpError("HTTP 502", status=502))
        got = self.read(http, "https://x.com/someone")
        self.assertEqual(got, {"label": "headlines", "transient": True})
        stored = {**got, "at": NOW.isoformat(), "test": discover_reads.FOLLOW_TEST}
        self.assertFalse(discover_reads.due(stored, NOW + timedelta(hours=1), test=True))
        self.assertTrue(discover_reads.due(stored, NOW + timedelta(hours=discover_reads.TRANSIENT_HOURS), test=True))
        lasting = {"label": "headlines", "at": NOW.isoformat(), "test": discover_reads.FOLLOW_TEST}
        self.assertFalse(discover_reads.due(lasting, NOW + timedelta(days=29), test=True))
        http = FakeHttp({"https://nitter.local/someone/rss": bridge_rss("someone", items=0)})
        self.assertEqual(self.read(http, "https://x.com/someone"), {"label": "headlines"}, "nothing there: not transient")

    def test_a_section_its_own_pages_sit_in(self):
        """b7: the home page's finder found nothing; the section its linked pages are under has a feed."""
        http = FakeHttp({"https://lab.example/": page(),
                         "https://lab.example/articles/": page('<link rel="alternate" type="application/rss+xml" href="/articles/feed">'),
                         "https://lab.example/articles/feed": (
                             '<?xml version="1.0"?><rss version="2.0"><channel><title>Articles</title>'
                             '<item><title>One</title><link>https://lab.example/articles/one</link></item>'
                             '<item><title>Two</title><link>https://lab.example/articles/two</link></item></channel></rss>')})
        got = self.read(http, "https://lab.example", ["https://lab.example/articles/one", "https://lab.example/articles/two"])
        self.assertIn(got["label"], R.FOLLOWABLE, got)

    def test_a_site_that_cant_be_followed_offers_its_declared_account(self):
        """b5: an unfollowable site whose page links its X account, which the bridge reads."""
        home = page(body='<a href="https://x.com/acmelabs">Follow us</a> <a href="https://x.com/acmelabs/status/2000000000000000009">a post</a>'
                         ' <a href="https://x.com/intent/follow?screen_name=acmelabs">follow</a>')
        http = FakeHttp({"https://lab.example/": home, "https://nitter.local/acmelabs/rss": bridge_rss("acmelabs")})
        got = self.read(http, "https://lab.example")
        self.assertEqual(got["label"], "headlines")
        self.assertEqual(got.get("account"), {"url": "https://x.com/acmelabs", "label": "@acmelabs"})

    def test_declared_accounts_are_accounts_only(self):
        page_html = ('<a href="https://x.com/acme">x</a><a href="https://twitter.com/acme">t</a>'
                     '<a href="https://x.com/acme/status/2000000000000000001">post</a><a href="/about">about</a>'
                     '<a href="https://t.me/acmechannel">tg</a>')
        got = discover_reads.declared_accounts(page_html, "https://lab.example/", registry(FakeHttp({})))
        self.assertEqual(got[0], "x.com/acme")
        self.assertIn("t.me/acmechannel", got)
        self.assertNotIn("x.com/acme/status/2000000000000000001", got)


class BackgroundTests(unittest.TestCase):
    def test_a_due_answer_is_rebuilt_in_the_background_even_with_reads_off(self):
        built = []
        stories = SimpleNamespace(refresh=lambda: built.append(1))

        async def run():
            with mock.patch.dict("os.environ", {"INSIGHT_DISCOVER_READS": "0"}):
                self.assertTrue(discover_reads.start(stories, None, None, refresh=True, read=True))
                self.assertFalse(discover_reads.start(stories, None, None, refresh=True), "one run at a time")
                await discover_reads._running
        asyncio.run(run())
        self.assertEqual(built, [1])


@requires_test_db
class ServedTests(unittest.TestCase):
    """c1: every fetch's settings write moved sources.updated_at, which keyed the list, so nearly every open made
    it again (255-300 s on the server; the proxy gave up at 300)."""

    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.addCleanup(self._clean)

    def _clean(self):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM system_settings WHERE key = 'discover_served'")
        self.conn.commit()
        self.conn.close()

    def inputs(self):
        self.conn.commit()
        return stories_service.StoriesRepository.discover_inputs(self.cur)

    def test_a_fetchs_settings_write_keeps_the_inputs(self):
        source = insert_source(self.cur, f"Acme {self.mark}")
        before = self.inputs()
        self.cur.execute("UPDATE sources SET settings = settings || '{\"etag\": \"x\"}'::jsonb, updated_at = now() + interval '1 hour'"
                         " WHERE id = %s", (source,))
        self.assertEqual(self.inputs(), before, "a fetch's write: the same answer")
        self.cur.execute("UPDATE sources SET settings = settings || jsonb_build_object('display_name', 'Renamed ' || %s::text)"
                         " WHERE id = %s", (self.mark, source))
        renamed = self.inputs()
        self.assertNotEqual(renamed, before, "a rename names its voices anew")
        self.cur.execute("UPDATE sources SET enabled = NOT enabled WHERE id = %s", (source,))
        self.assertNotEqual(self.inputs(), renamed, "enabled or not")

    def test_reading_discover_never_writes(self):
        """v10.16: the checks read Discover in a read-only transaction; with its counts to make again (another
        story run's stamp) the read kept them and the list, and failed: "cannot execute INSERT in a read-only
        transaction". A read makes them without writing; the background build keeps them."""
        from insight_core.db import database

        voices = [insert_source(self.cur, f"Voice {n} {self.mark}") for n in range(3)]
        for n, source in enumerate(voices):
            for k in range(2):
                url = f"https://voice{n}-{self.mark}.example/p/{k}"
                self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, url_host, published_at, links_scanned_at)"
                                 " VALUES (%s, %s, %s, %s, now(), now()) RETURNING id", (source, url, url, url.split("/")[2]))
                post = self.cur.fetchone()[0]
                self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, '', 0)",
                                 (post, f"https://linked-{self.mark}.example/2026/10/story-{k}"))
        self.cur.execute("SELECT key, value FROM system_settings WHERE key IN ('discover_counts', 'discover_list')")
        before = dict(self.cur.fetchall())
        self.cur.execute("DELETE FROM system_settings WHERE key IN ('discover_counts', 'discover_list')")
        self.conn.commit()

        def restore():
            for key, value in before.items():
                self.cur.execute("INSERT INTO system_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE "
                                 "SET value = EXCLUDED.value", (key, psycopg.types.json.Jsonb(value)))
            self.conn.commit()
        self.addCleanup(restore)
        plain = database.Database._connect_kwargs

        def read_only(db):
            return {**plain(db), "options": (plain(db).get("options", "") + " -c default_transaction_read_only=on").strip()}
        database.close_all()
        try:
            with mock.patch.object(database.Database, "_connect_kwargs", read_only):
                got = StoriesService(db_url()).discover()
        finally:
            database.close_all()
        self.assertIn("success", got)
        self.cur.execute("SELECT count(*) FROM system_settings WHERE key IN ('discover_counts', 'discover_list')")
        self.assertEqual(self.cur.fetchone()[0], 0, "a read keeps nothing")
        StoriesService(db_url()).refresh()
        self.cur.execute("SELECT count(*) FROM system_settings WHERE key IN ('discover_counts', 'discover_list', 'discover_served')")
        self.assertEqual(self.cur.fetchone()[0], 3, "the background build keeps them")

    def test_an_open_serves_the_last_answer_and_says_when_it_is_due(self):
        built = []
        clock = [NOW]

        def fresh(service):
            built.append(1)
            return {"success": True, "suggestions": [{"key": f"k{len(built)}.example", "score": 1.0, "voices": 1}],
                    "also": [], "archives": [], "unnamed": [], "pages": [], "references": [], "first_page": 30}

        self.conn.commit()
        with mock.patch.object(StoriesService, "_fresh", fresh):
            service = StoriesService(db_url(), clock=lambda: clock[0])
            self.cur.execute("SELECT value FROM system_settings WHERE key = 'discover_list'")
            kept = self.cur.fetchone()
            self.cur.execute("DELETE FROM system_settings WHERE key = 'discover_list'")
            self.conn.commit()
            try:
                page, stale = service.discover_served()
            finally:
                if kept:
                    self.cur.execute("INSERT INTO system_settings (key, value) VALUES ('discover_list', %s)",
                                     (psycopg.types.json.Jsonb(kept[0]),))
                    self.conn.commit()
            self.assertEqual((len(built), stale, page["built_at"], page["suggestions"]), (0, True, None, []),
                             "none built yet: never built on the request, due")
            service.refresh()
            page, stale = StoriesService(db_url(), clock=lambda: clock[0]).discover_served()
            self.assertEqual((len(built), stale, page["suggestions"][0]["key"]), (1, False, "k1.example"),
                             "a fresh process serves the kept answer")
            insert_source(self.cur, f"New {self.mark}")
            self.conn.commit()
            page, stale = service.discover_served()
            self.assertEqual((len(built), stale, page["suggestions"][0]["key"]), (1, True, "k1.example"),
                             "a source added: the last answer, due again")
            service.refresh()
            _, stale = service.discover_served()
            self.assertEqual((len(built), stale), (2, False))
            clock[0] = NOW + REFRESH_AFTER
            _, stale = service.discover_served()
            self.assertTrue(stale, "old: Mark X's rows move between story runs")


if __name__ == "__main__":
    unittest.main()
