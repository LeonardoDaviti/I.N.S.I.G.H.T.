"""Issue 0178: dead sources found, Telegram forwards keep the channel's username, sources named.

1. A source silent far beyond its own rhythm (source_doctor.silent_beyond_rhythm) has where it went looked for
   (where_it_went: redirects, its home page's feeds, its newest posts' pages) and offered, never switched.
2. A Telegram bridge item's forward header (<source url="https://t.me/<channel>/<post>">) is kept as
   metadata.forwarded_from with the channel's username, so Pairing's voice rule matches t.me/<channel>.
3. A source with no name is named by what its feed or page calls itself, at add, at a fetch, and by the one-off
   repair; a name the owner set is never written over.

No network: FakeHttp answers. The DB tests run on the scratch test database.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

import main
from insight_core.db.repo_fetch_state import FetchStateRepository, FetchStateRow
from insight_core.db.repo_sources import SourcesRepository
from insight_core.db.repo_stories import SourceFacts
from insight_core.ingestion import source_doctor, source_names
from insight_core.ingestion.inspection import DbInspectionRefresher
from insight_core.ingestion.kinds import KindRegistry, parsing, telegram_mtproto, telegram_rss
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.ingestion.runner import IngestionRunner
from insight_core.ingestion.schedule import Availability
from insight_core.ingestion.source_doctor import SourceDoctor, silent_beyond_rhythm, where_it_went
from insight_core.ingestion.types import FetchRequest, SourceSelector, Trigger
from insight_core.markx import pairing, tasks
from insight_core.scripts import repair_source_names
from insight_core.services.operations_service import OperationsService, silent_fields, summarize_health
from insight_core.services.source_config_sync_service import SourceConfigSyncService
from insight_core.tests._asgi import call
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests._ingestion_fakes import (
    FakeRunLock,
    FixedClock,
    InMemoryFetchStateStore,
    InMemoryPostSaver,
    InMemorySourceCatalog,
    RecordingInspectionRefresher,
    SpyFetchGates,
)
from insight_core.tests._kind_fakes import FakeHttp, FakeKind

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
DAY = 86400.0
LAST = NOW - timedelta(days=64)          # a daily newsletter's last post, 64 days ago

OLD_FEED = "https://news.old.example/rss.xml"
OLD_HOME = "https://news.old.example/"
NEW_PAGE = "https://new.example/digest/"
NEW_FEED = "https://new.example/digest/feed.xml"


def rss_dated(title: str, *items: tuple[str, str, datetime]) -> str:
    entries = "".join(f"<item><title>{t}</title><link>{u}</link><pubDate>{d.strftime('%a, %d %b %Y %H:%M:%S +0000')}"
                      f"</pubDate><description>x</description></item>" for u, t, d in items)
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{title}</title>'
            f"{entries}</channel></rss>")


def titled(title: str) -> str:
    """A feed of one item, called `title` (the finder reads a feed's title only with an item)."""
    return rss_dated(title, ("https://blog.example/1", "One", LAST))


def html_page(head: str = "", title: str = "A page") -> str:
    return f"<!DOCTYPE html><html><head><title>{title}</title>{head}</head><body><p>hello</p></body></html>"


STALE = rss_dated("Old Digest", ("https://news.old.example/issues/a", "Issue A", LAST))
ALIVE = rss_dated("The Digest", ("https://new.example/digest/b", "Issue B", NOW - timedelta(days=1)),
                  ("https://new.example/digest/c", "Issue C", NOW - timedelta(days=2)))
LINKS_FEED = '<link rel="alternate" type="application/rss+xml" href="{}">'


def moved_site(**extra) -> tuple[dict, dict]:
    """The old site: its feed still answers (stale), its home page now redirects to the new site's page."""
    responses = {OLD_FEED: STALE, OLD_HOME: html_page(), NEW_PAGE: html_page(LINKS_FEED.format(NEW_FEED)),
                 NEW_FEED: ALIVE, **extra}
    return responses, {OLD_HOME: NEW_PAGE}


def went(responses, redirects, address=OLD_FEED, last=LAST, newest=()) -> dict:
    http = FakeHttp(responses, redirects=redirects)
    return asyncio.run(where_it_went(http, KindRegistry.default(http, None), address, last_post_at=last,
                                     newest_posts=newest))


# --------------------------------------------------------------------------- 1. the rule


class SilentRuleTests(unittest.TestCase):
    def test_a_daily_source_is_silent_past_the_floor_not_before(self):
        self.assertIsNone(silent_beyond_rhythm(NOW - timedelta(days=6), DAY, "medium", NOW), "6 days: the floor (14)")
        self.assertIsNone(silent_beyond_rhythm(NOW - timedelta(days=13), DAY, "medium", NOW))
        self.assertEqual(silent_beyond_rhythm(NOW - timedelta(days=15), DAY, "medium", NOW), timedelta(days=15))

    def test_a_slow_source_is_silent_past_five_gaps(self):
        weekly = 7 * DAY
        self.assertIsNone(silent_beyond_rhythm(NOW - timedelta(days=30), weekly, "slow", NOW), "under 5 x 7 days")
        self.assertIsNotNone(silent_beyond_rhythm(NOW - timedelta(days=36), weekly, "slow", NOW))

    def test_an_unmeasured_rhythm_is_never_silent(self):
        long_ago = NOW - timedelta(days=400)
        self.assertIsNone(silent_beyond_rhythm(long_ago, None, "slow", NOW))
        self.assertIsNone(silent_beyond_rhythm(long_ago, DAY, "unknown", NOW))
        self.assertIsNone(silent_beyond_rhythm(None, DAY, "fast", NOW), "no post")


# --------------------------------------------------------------------------- 1. where it went


class WhereItWentTests(unittest.TestCase):
    def test_a_home_page_that_redirects_leads_to_the_new_sites_live_feed(self):
        found = went(*moved_site())
        self.assertEqual(found["moved"], [{"via": "home page", "from": OLD_HOME, "to": NEW_PAGE}])
        replacement = found["replacement"]
        self.assertEqual((replacement["kind"], replacement["url"], replacement["title"]), ("feed", NEW_FEED, "The Digest"))
        self.assertEqual(replacement["latest"], ["Issue B", "Issue C"])
        self.assertEqual(replacement["via"], "its home page now lands at new.example/digest")

    def test_the_address_itself_redirecting_is_recorded(self):
        responses, redirects = moved_site()
        found = went(responses, {**redirects, OLD_FEED: NEW_FEED})
        self.assertEqual(found["moved"][0], {"via": "address", "from": OLD_FEED, "to": NEW_FEED})

    def test_a_newest_posts_page_landing_elsewhere_is_recorded(self):
        post = "https://news.old.example/issues/a"
        responses = {OLD_FEED: STALE, OLD_HOME: html_page(), post: html_page(),
                     NEW_PAGE: html_page(LINKS_FEED.format(NEW_FEED)), NEW_FEED: ALIVE}
        found = went(responses, {post: NEW_PAGE}, newest=[post])
        self.assertEqual(found["moved"], [{"via": "post", "from": post, "to": NEW_PAGE}])
        self.assertEqual(found["replacement"]["url"], NEW_FEED)

    def test_a_feed_no_newer_than_the_last_post_is_never_offered(self):
        dead = rss_dated("The Digest", ("https://new.example/digest/z", "Old", LAST - timedelta(days=3)))
        found = went(*moved_site(**{NEW_FEED: dead}))
        self.assertEqual(len(found["moved"]), 1)
        self.assertIsNone(found["replacement"])

    def test_a_new_feed_on_its_own_site_is_found_from_its_home_page(self):
        new = "https://news.old.example/feed.xml"
        responses = {OLD_FEED: STALE, OLD_HOME: html_page(LINKS_FEED.format(new)),
                     new: rss_dated("Digest", ("https://news.old.example/issues/n", "New", NOW - timedelta(days=1)))}
        found = went(responses, {})
        self.assertEqual(found["moved"], [])
        self.assertEqual((found["replacement"]["url"], found["replacement"]["via"]), (new, "its home page"))

    def test_another_sections_feed_on_its_site_is_not_its_new_feed(self):
        address = "https://blog.old.example/team-a/feed"
        home_feed = "https://blog.old.example/feed"
        responses = {address: STALE, "https://blog.old.example/": html_page(LINKS_FEED.format(home_feed)),
                     home_feed: rss_dated("All teams", ("https://blog.old.example/team-b/x", "B", NOW))}
        self.assertIsNone(went(responses, {}, address=address)["replacement"])

    def test_nothing_answering_is_nothing_found(self):
        self.assertEqual(went({}, {}), {"moved": [], "replacement": None})


# --------------------------------------------------------------------------- 1. the doctor after a fetch


class SilenceStore:
    def __init__(self, last=LAST, items=(("https://news.old.example/issues/a", "Issue A"),)):
        self.last = last
        self.stored = list(items)
        self.silences: list = []
        self.switches: list = []
        self.records: list = []

    def items(self, source_id):
        return self.stored

    def last_post_at(self, source_id):
        return self.last

    def record_silence(self, source_id, *, checked_at, finding):
        self.silences.append((source_id, checked_at, finding))

    def record(self, source_id, *, checked_at, finding):
        self.records.append(finding)

    def switch(self, source_id, url, page_watch):   # never called for a silent source
        self.switches.append((source_id, url))


def newsletter(**over) -> dict:
    return {"id": "s1", "platform": "rss", "handle_or_url": OLD_FEED, "settings": {"display_name": "Digest"},
            "mean_gap_seconds": 1.4 * DAY, "cadence_tier": "medium", **over}


def after_success(source, state=None, store=None, new_posts=0, responses=None, redirects=None, kind="generic_rss"):
    responses, default_redirects = moved_site() if responses is None else (responses, {})
    http = FakeHttp(responses, redirects=default_redirects if redirects is None else redirects)
    store = store or SilenceStore()
    doctor = SourceDoctor(http=http, registry=KindRegistry.default(http, None), store=store, clock=FixedClock(NOW))
    asyncio.run(doctor.after_success(source, FakeKind(kind), state, new_posts))
    return store, http


class DoctorAfterSuccessTests(unittest.TestCase):
    def test_a_silent_newsletter_gets_its_finding_and_is_never_switched(self):
        store, _ = after_success(newsletter())
        self.assertEqual(store.switches, [], "the owner switches; the doctor never does")
        self.assertEqual(store.records, [], "the failure finding is untouched")
        (_, checked_at, finding), = store.silences
        self.assertEqual(checked_at, NOW)
        self.assertEqual((finding["last_post_at"], finding["silent_days"], finding["usual_gap_days"]),
                         (LAST.isoformat(), 64.0, 1.4))
        self.assertTrue(finding["looked"])
        self.assertEqual(finding["replacement"]["url"], NEW_FEED)
        self.assertFalse(finding["stopped"])

    def test_a_source_within_its_rhythm_asks_nothing(self):
        store, http = after_success(newsletter(), store=SilenceStore(last=NOW - timedelta(days=3)))
        self.assertEqual((store.silences, http.requests), ([], []))

    def test_a_fetch_with_new_posts_clears_a_silence(self):
        state = FetchStateRow(source_id="s1", silent_checked_at=NOW - timedelta(days=1), silent_finding={"looked": True})
        store, http = after_success(newsletter(), state=state, new_posts=2)
        self.assertEqual([f for _, _, f in store.silences], [None])
        self.assertEqual(http.requests, [])

    def test_it_looks_at_most_once_a_week(self):
        state = FetchStateRow(source_id="s1", silent_checked_at=NOW - timedelta(days=2), silent_finding={"looked": True})
        store, http = after_success(newsletter(), state=state)
        self.assertEqual((store.silences, http.requests), ([], []))

    def test_the_owners_it_stopped_holds_until_it_posts(self):
        state = FetchStateRow(source_id="s1", silent_checked_at=NOW - timedelta(days=30),
                              silent_finding={"stopped": True, "last_post_at": LAST.isoformat()})
        store, http = after_success(newsletter(), state=state)
        self.assertEqual((store.silences, http.requests), ([], []))

    def test_an_unmeasured_rhythm_is_not_looked_at(self):
        store, http = after_success(newsletter(cadence_tier="unknown"))
        self.assertEqual((store.silences, http.requests), ([], []))

    def test_a_kind_whose_address_cannot_move_is_recorded_without_a_look(self):
        store, http = after_success(newsletter(platform="telegram", handle_or_url="chan"), kind="telegram_mtproto")
        (_, _, finding), = store.silences
        self.assertEqual((finding["looked"], finding["replacement"], http.requests), (False, None, []))


class RunnerShowsSuccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_fetch_that_worked_is_shown_with_its_new_posts(self):
        class Recording:
            def __init__(self):
                self.calls = []

            async def after_failure(self, *args):
                self.calls.append("failure")

            async def after_success(self, source, kind, state, new_posts):
                self.calls.append(("success", source["id"], new_posts))

        doctor = Recording()
        posts = [{"url": "https://x.example/1", "title": "One", "content": "c", "date": NOW}]
        runner = IngestionRunner(
            catalog=InMemorySourceCatalog([newsletter()]), state=InMemoryFetchStateStore(), saver=InMemoryPostSaver(),
            inspections=RecordingInspectionRefresher(), registry=KindRegistry([FakeKind("generic_rss", behaviour=lambda s, n: posts)]),
            gates=SpyFetchGates(), run_lock=FakeRunLock(), availability=lambda: Availability(True, False),
            clock=FixedClock(NOW), rand=lambda: 1.0, doctor=doctor)
        await runner.run(FetchRequest(SourceSelector.all(), Trigger.SCHEDULER, force=True))
        self.assertEqual(doctor.calls, [("success", "s1", 1)])


# --------------------------------------------------------------------------- 1. health


def silent_state(**finding) -> FetchStateRow:
    return FetchStateRow(source_id="s1", silent_checked_at=NOW - timedelta(hours=3),
                         silent_finding={"last_post_at": LAST.isoformat(), "looked": True, "stopped": False,
                                         "moved": [{"via": "home page", "from": OLD_HOME, "to": NEW_PAGE}],
                                         "replacement": {"kind": "feed", "url": NEW_FEED, "title": "The Digest",
                                                         "via": "its home page now lands at new.example/digest"},
                                         **finding})


class HealthSilenceTests(unittest.TestCase):
    def health(self, state=None, status="deferred", last=LAST, **source):
        return silent_fields({**newsletter(), "last_post_at": last, **source}, state, status, NOW)

    def test_a_silent_source_carries_the_doctors_look(self):
        silent = self.health(silent_state())
        self.assertEqual(silent["days"], 64)
        self.assertAlmostEqual(silent["usual_gap_hours"], 1.4 * 24)
        self.assertEqual(silent["replacement"]["url"], NEW_FEED)
        self.assertEqual(silent["moved"][0]["to"], NEW_PAGE)
        self.assertEqual(silent["looked_at"], (NOW - timedelta(hours=3)).isoformat())

    def test_silent_before_the_doctor_looked(self):
        silent = self.health(None)
        self.assertEqual((silent["days"], silent["looked_at"], silent["replacement"]), (64, None, None))

    def test_a_look_made_before_its_newest_post_is_not_shown(self):
        later = LAST + timedelta(days=10)
        silent = self.health(silent_state(), last=later)
        self.assertEqual((silent["looked_at"], silent["replacement"], silent["moved"]), (None, None, []))

    def test_stopped_failing_off_or_within_its_rhythm_is_not_silent(self):
        self.assertIsNone(self.health(silent_state(stopped=True)))
        self.assertIsNone(self.health(silent_state(), status="backoff"))
        self.assertIsNone(self.health(silent_state(), status="disabled"))
        self.assertIsNone(self.health(None, last=NOW - timedelta(days=2)))

    def test_the_summary_counts_silent_sources(self):
        summary = summarize_health([{"status": "deferred", "silent": {"days": 64}}, {"status": "due", "silent": None}])
        self.assertEqual((summary["silent"], summary["deferred"], summary["due_now"]), (1, 1, 1))


@requires_test_db
class SilenceDbTests(unittest.TestCase):
    def setUp(self):
        self.url = db_url()
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur, settings_json='{"display_name": "Digest"}', enabled=True)
            cur.execute("SELECT handle_or_url FROM sources WHERE id = %s", (self.source_id,))
            self.base = cur.fetchone()[0]
            cur.execute("UPDATE sources SET mean_gap_seconds = %s, cadence_tier = 'medium', cadence_sample_size = 20"
                        " WHERE id = %s", (1.4 * DAY, self.source_id))
            cur.execute("INSERT INTO posts (source_id, url, title, content, published_at) VALUES (%s, %s, 'A', 'c', %s)",
                        (self.source_id, f"{self.base}/a", LAST))
            FetchStateRepository().record_silence(cur, self.source_id, checked_at=NOW, finding={
                "last_post_at": LAST.isoformat(), "looked": True, "stopped": False, "moved": [],
                "replacement": {"kind": "feed", "url": f"{self.base}/new/feed.xml", "title": "New", "via": "its home page"}})
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _finding(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT silent_checked_at, silent_finding FROM source_fetch_state WHERE source_id = %s",
                        (self.source_id,))
            return cur.fetchone()

    def test_the_health_row_offers_the_switch_and_it_stopped_hides_it(self):
        ops = OperationsService(self.url)
        ops.clock = lambda: NOW
        row = ops.get_source_health_row(self.source_id)
        self.assertEqual(row["silent"]["replacement"]["url"], f"{self.base}/new/feed.xml")
        status, _, body = call(main.app, "POST", f"/api/sources/{self.source_id}/silence/stopped")
        self.assertEqual(status, 200, body)
        self.assertIsNone(ops.get_source_health_row(self.source_id)["silent"])
        self.assertTrue(self._finding()[1]["stopped"])
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT handle_or_url, enabled FROM sources WHERE id = %s", (self.source_id,))
            self.assertEqual(cur.fetchone(), (self.base, True), "nothing switched, nothing switched off")

    def test_it_stopped_on_no_source_is_404(self):
        status, _, _ = call(main.app, "POST", "/api/sources/00000000-0000-4000-8000-00000000dead/silence/stopped")
        self.assertEqual(status, 404)

    def test_switch_clears_the_silence(self):
        SourceConfigSyncService(self.url, config_path=Path("/tmp") / f"sources-{self.source_id}.json").switch_source(
            self.source_id, f"{self.base}/new/feed.xml")
        self.assertEqual(self._finding(), (None, None))


# --------------------------------------------------------------------------- 2. Telegram forwards


def bridge_page(*items: str) -> str:
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Chan One</title>{"".join(items)}</channel></rss>'


def bridge_item(post: int, source: str = "") -> str:
    return (f"<item><title>Post {post}</title><description>Body {post}</description>"
            f"<pubDate>Wed, 11 Nov 2026 18:18:59 +0000</pubDate><link>https://t.me/chan_one/{post}</link>"
            f"{source}</item>")


class TelegramForwardTests(unittest.TestCase):
    def test_the_bridges_source_element_is_the_forward_with_its_username(self):
        self.assertEqual(telegram_rss.forwarded_from({"url": "https://t.me/other_chan/77", "title": "Other Channel"}),
                         {"post": 77, "url": "https://t.me/other_chan/77", "username": "other_chan", "name": "Other Channel"})

    def test_a_channel_known_by_id_only_has_no_username(self):
        self.assertEqual(telegram_rss.forwarded_from({"url": "https://t.me/1234567890/5", "title": "Private"}),
                         {"post": 5, "url": "https://t.me/1234567890/5", "channel_id": 1234567890, "name": "Private"})

    def test_no_forward_its_own_channel_or_another_site_is_none(self):
        self.assertIsNone(telegram_rss.forwarded_from(None))
        self.assertIsNone(telegram_rss.forwarded_from({"url": "https://t.me/chan_one/3", "title": "Me"}, "chan_one"))
        self.assertIsNone(telegram_rss.forwarded_from({"url": "https://news.example/feed", "title": "News"}))

    def test_a_titleless_header_is_named_by_its_username(self):
        self.assertEqual(telegram_rss.forwarded_from({"url": "https://t.me/other_chan/1", "title": ""})["name"], "@other_chan")

    def test_the_kind_keeps_it_in_metadata(self):
        source = "https://telegram.local/rss/chan_one"
        page = bridge_page(bridge_item(2, '<source url="https://t.me/other_chan/77">Other Channel</source>'), bridge_item(1))
        kind = telegram_rss.TelegramRssKind(FakeHttp({telegram_rss.page_url(source, 1): page}))
        posts = asyncio.run(kind.fetch_page(source, 1))
        by_id = {p["external_id"]: p for p in posts}
        self.assertEqual(by_id["2"]["metadata"]["forwarded_from"]["username"], "other_chan")
        self.assertNotIn("forwarded_from", by_id["1"].get("metadata") or {})
        self.assertTrue(all("origin_item" not in p for p in posts), "the raw element never reaches the store")

    def test_a_generic_feeds_source_element_is_not_stored(self):
        feed = ('<rss version="2.0"><channel><item><title>A</title><link>https://a.example/1</link>'
                '<source url="https://agency.example/rss">Agency</source></item></channel></rss>')
        post = parsing.parse_feed_posts(feed, "https://a.example/rss")[0]
        self.assertEqual(post["origin_item"], {"url": "https://agency.example/rss", "title": "Agency"})
        self.assertEqual(post["metadata"], {})

    def test_mtproto_keeps_the_forwarded_channels_username(self):
        fwd = SimpleNamespace(from_id=SimpleNamespace(channel_id=42), from_name=None, channel_post=7, date=None)
        message = SimpleNamespace(fwd_from=fwd, forward=SimpleNamespace(chat=SimpleNamespace(username="other_chan",
                                                                                            title="Other Channel")))
        self.assertEqual(telegram_mtproto.forwarded_from(message),
                         {"channel_id": 42, "username": "other_chan", "name": "Other Channel", "post": 7})

    def test_pairings_voice_rule_matches_the_followed_channel(self):
        """A forward of a channel a source follows counts as that source's voice (Mark IX's rule); a stranger's stays
        the forwarding feed's."""
        followed = dict(SourceFacts.of([("src-bridge", "rss", "https://telegram.local/rss/other_chan?limit=50", "Other"),
                                        ("src-forwarder", "rss", "https://telegram.local/rss/chan_one?limit=50", "Chan")],
                                       []).of_account)
        fwd = telegram_rss.forwarded_from({"url": "https://t.me/Other_Chan/77", "title": "Other Channel"})
        account = tasks.author_account("telegram", fwd["name"], fwd["username"])
        self.assertEqual(account, "t.me/other_chan")
        self.assertEqual(pairing.counted_voice("src-forwarder", account, followed), "src-bridge")
        stranger = telegram_rss.forwarded_from({"url": "https://t.me/stranger/1", "title": "Stranger"})
        self.assertEqual(pairing.counted_voice("src-forwarder", tasks.author_account("telegram", stranger["name"],
                                                                                     stranger["username"]), followed),
                         "src-forwarder")


# --------------------------------------------------------------------------- 3. names


FEED = "https://blog.example/feed.xml"


class CleanNameTests(unittest.TestCase):
    def test_a_title_is_tidied(self):
        self.assertEqual(source_names.clean_name("  Example &amp; Co  Weekly "), "Example & Co Weekly")
        self.assertEqual(source_names.clean_name("Example Blog | RSS Feed"), "Example Blog")
        self.assertEqual(source_names.clean_name("Example Blog - Atom"), "Example Blog")
        self.assertEqual(source_names.clean_name("Example RSS feed"), "Example")
        self.assertEqual(source_names.clean_name("The Atom"), "The Atom", "a title ending in the word keeps it")

    def test_no_name_from_a_generic_word_or_an_address(self):
        for title in ("", "  ", "RSS", "Feed", "Blog", "Home", "RSS Feed", "https://blog.example/feed.xml",
                      "blog.example/feed.xml", FEED):
            self.assertIsNone(source_names.clean_name(title, FEED), title)

    def test_a_name_with_a_dot_is_still_a_name(self):
        self.assertEqual(source_names.clean_name("Node.js"), "Node.js")
        self.assertEqual(source_names.clean_name("blog.example"), "blog.example")


def own(source, responses) -> str | None:
    return asyncio.run(source_names.own_name(FakeHttp(responses), source))


class OwnNameTests(unittest.TestCase):
    def test_a_feed_by_its_title(self):
        self.assertEqual(own({"platform": "rss", "handle_or_url": FEED}, {FEED: titled("Example Weekly")}),
                         "Example Weekly")

    def test_a_generic_feed_title_takes_the_sites_name(self):
        home = html_page('<meta property="og:site_name" content="Example Labs">', title="Home")
        self.assertEqual(own({"platform": "rss", "handle_or_url": FEED},
                             {FEED: titled("RSS Feed"), "https://blog.example/": home}), "Example Labs")

    def test_a_followed_page_by_its_site(self):
        source = {"platform": "rss", "handle_or_url": "https://lab.example/news", "settings": {"page_watch": {"prefix": "/news/"}}}
        self.assertEqual(own(source, {"https://lab.example/": html_page(title="Example Lab")}), "Example Lab")

    def test_a_subreddit_by_its_address_with_no_request(self):
        self.assertEqual(own({"platform": "reddit", "handle_or_url": "/r/MachineLearning/"}, {}), "r/MachineLearning")

    def test_a_feed_that_does_not_answer_asks_nothing_more(self):
        http = FakeHttp({})
        self.assertIsNone(asyncio.run(source_names.own_name(http, {"platform": "rss", "handle_or_url": FEED})))
        self.assertEqual(http.requests, [FEED])

    def test_saved_pages_and_native_channels_are_not_asked(self):
        self.assertIsNone(own({"platform": "saved", "handle_or_url": "Saved"}, {}))
        self.assertIsNone(own({"platform": "telegram", "handle_or_url": "chan_one"}, {}))


class FetchNamesTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_feed_read_gives_an_unnamed_source_its_title(self):
        kind = GenericRssKind(FakeHttp({FEED: rss_dated("Example Weekly", ("https://blog.example/1", "One", NOW))}))
        got = await kind.fetch_latest({"id": "s1", "platform": "rss", "handle_or_url": FEED, "settings": {}}, 5)
        self.assertEqual(got.title, "Example Weekly")
        named = await kind.fetch_latest({"id": "s1", "platform": "rss", "handle_or_url": FEED,
                                         "settings": {"display_name": "Mine"}}, 5)
        self.assertIsNone(named.title, "a named source is not asked to be renamed")

    async def test_the_refresher_names_only_an_unnamed_source(self):
        sources = mock.Mock()
        refresher = DbInspectionRefresher(writer=SimpleNamespace(sources=sources))
        await refresher.named({"id": "s1", "handle_or_url": FEED, "settings": {}}, "Example Weekly | RSS")
        sources.name_if_unnamed.assert_called_once_with("s1", "Example Weekly")
        sources.reset_mock()
        await refresher.named({"id": "s1", "handle_or_url": FEED, "settings": {"display_name": "Mine"}}, "Example Weekly")
        await refresher.named({"id": "s2", "handle_or_url": FEED, "settings": {}}, "Feed")
        sources.name_if_unnamed.assert_not_called()


@requires_test_db
class NamesDbTests(unittest.TestCase):
    def setUp(self):
        self.url = db_url()
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.unnamed = insert_scratch_source(cur)
            self.named = insert_scratch_source(cur, settings_json='{"display_name": "The owner\'s name"}')
            self.spaces = insert_scratch_source(cur, settings_json='{"display_name": "  "}')
            self.channel = insert_scratch_source(cur, platform="telegram")
            self.bridge = insert_scratch_source(cur, settings_json='{"display_name": "Chan One"}')
            cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s",
                        (f"chan_one_{self.channel[:8]}", self.channel))
            cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s",
                        (f"https://telegram.local/rss/chan_one_{self.channel[:8]}?limit=50", self.bridge))
            cur.execute("SELECT id::text, handle_or_url FROM sources WHERE id = ANY(%s::uuid[])",
                        ([self.unnamed, self.named, self.spaces],))
            self.address = dict(cur.fetchall())
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            cur.execute("DELETE FROM sources WHERE id = ANY(%s::uuid[])", ([self.channel, self.bridge],))
            conn.commit()

    def _names(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT id::text, settings->>'display_name' FROM sources WHERE id = ANY(%s::uuid[])",
                        ([self.unnamed, self.named, self.spaces, self.channel],))
            return dict(cur.fetchall())

    def test_the_guard_never_writes_over_a_name(self):
        repo = SourcesRepository(self.url)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            self.assertTrue(repo.name_if_unnamed(cur, self.unnamed, "Example Weekly"))
            self.assertFalse(repo.name_if_unnamed(cur, self.named, "Example Weekly"))
            self.assertTrue(repo.name_if_unnamed(cur, self.spaces, "Example Weekly"), "spaces are no name")
            self.assertFalse(repo.name_if_unnamed(cur, self.unnamed, "Another"), "named now")
            conn.commit()
        names = self._names()
        self.assertEqual((names[self.unnamed], names[self.named]), ("Example Weekly", "The owner's name"))

    def _repair(self, apply: bool, fetch: bool = True):
        responses = {self.address[self.unnamed]: titled("Example Weekly"),
                     self.address[self.spaces]: titled("Feed"),     # generic: the site is asked, and fails
                     self.address[self.named]: titled("Not this")}
        out = asyncio.run(repair_source_names.run(self.url, apply=apply, fetch=fetch, http=FakeHttp(responses), gap_s=0))
        mine = {self.unnamed, self.named, self.spaces, self.channel}
        out["sources"] = [s for s in out["sources"] if s["source_id"] in mine]
        out["left"] = [s for s in out["left"] if s["source_id"] in mine]
        return out

    def test_the_dry_run_names_nothing(self):
        before = self._names()
        out = self._repair(apply=False)
        self.assertEqual(self._names(), before)
        by_id = {s["source_id"]: s for s in out["sources"]}
        self.assertEqual((by_id[self.unnamed]["name"], by_id[self.unnamed]["came_from"]), ("Example Weekly", "its feed or page"))
        self.assertEqual((by_id[self.channel]["name"], by_id[self.channel]["came_from"]), ("Chan One", "same account"))
        self.assertNotIn(self.named, by_id, "a named source is no candidate")
        self.assertEqual([s["source_id"] for s in out["left"]], [self.spaces])

    def test_apply_names_and_never_writes_over_the_owners_name(self):
        self._repair(apply=True)
        names = self._names()
        self.assertEqual((names[self.unnamed], names[self.channel], names[self.named]),
                         ("Example Weekly", "Chan One", "The owner's name"))
        self.assertEqual(names[self.spaces], "  ", "left as it was")

    def test_no_fetch_asks_nothing(self):
        out = self._repair(apply=False, fetch=False)
        self.assertEqual({s["source_id"] for s in out["sources"]}, {self.channel})

    def test_adding_a_source_with_no_name_names_it_from_its_feed(self):
        address = self.address[self.unnamed].replace("mark-ix/", "mark-ix/added-")
        http = FakeHttp({address: titled("Added Weekly")})
        with mock.patch.object(main, "FEED_FINDER_HTTP", http), \
                mock.patch("insight_core.services.follow_archive.queue_on_follow", return_value=None):
            status, _, body = call(main.app, "POST", "/api/sources", json_body={"platform": "rss", "handle_or_url": address})
            self.assertEqual(status, 200, body)
            self.assertEqual(body.get("display_name"), "Added Weekly")
            named = address + "-named"
            status, _, body = call(main.app, "POST", "/api/sources",
                                   json_body={"platform": "rss", "handle_or_url": named, "display_name": "Mine"})
        self.assertEqual(status, 200, body)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT handle_or_url, settings->>'display_name' FROM sources WHERE handle_or_url IN (%s, %s)",
                        (address, named))
            self.assertEqual(dict(cur.fetchall()), {address: "Added Weekly", named: "Mine"})


if __name__ == "__main__":
    unittest.main()
