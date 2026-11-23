"""Sources that stopped without anyone seeing (0242).

- kinds.base.collapsed: a feed fails only when it collapses (most items on a few addresses); a few items sharing one
  are stored as distinct posts, with a warning. parsing._identities: links (or guids) that differ only by what
  normalize_url drops are one shared address, so the item's guid is its identity.
- kinds.reddit: Reddit's OAuth API with the owner's registered app (FakeHttp); without credentials the kind is
  unavailable with the reason, never a backoff.
- operations_service.stalled_fields: the flag for a source whose last success is old or that keeps failing.
- source_doctor.dead_finding: a host with no answer for DEAD_AFTER is marked dead, never switched off.
"""
from __future__ import annotations

import asyncio
import base64
import json
import socket
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.ingestion import http as http_module
from insight_core.ingestion.credentials import MappingCredentials
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import KindUnavailable, checked_fetch, collapsed, shared_addresses
from insight_core.ingestion.kinds.reddit import (
    NO_CREDENTIALS,
    OAUTH_BASE,
    REDDIT_PROFILE,
    REFUSED_CREDENTIALS,
    TOKEN_URL,
    RedditKind,
)
from insight_core.ingestion.schedule import Availability, availability_from_env, unavailable_reason
from insight_core.ingestion.source_doctor import DEAD_AFTER, SourceDoctor, dead_finding, failure_signal
from insight_core.services.credentials_service import CredentialInvalid, normalise_value
from insight_core.services.operations_service import (
    STALLED_FAILURES,
    _doctor_fields,
    stalled_fields,
    summarize_health,
)
from insight_core.tests._ingestion_fakes import FixedClock
from insight_core.tests._kind_fakes import FakeHttp, FakeKind

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
LISTING = (Path(__file__).parent / "fixtures" / "reddit" / "new_listing.json").read_text()
CREDS = MappingCredentials({("reddit", "client_id"): "abcDEF123456", ("reddit", "client_secret"): "s3cret-value-xyz",
                            ("reddit", "username"): "owner_name"})
TOKEN = {"access_token": "tok-1", "token_type": "bearer", "expires_in": 86400, "scope": "*"}


def run(coro):
    return asyncio.run(coro)


def _src(handle: str, platform: str = "reddit") -> dict:
    return {"id": "s1", "platform": platform, "handle_or_url": handle, "settings": {}}


# --------------------------------------------------------------------------- 1. collapsed feeds


def _item(n: int, url: str) -> dict:
    return {"url": url, "guid": f"g{n}", "title": f"Post {n}"}


class CollapsedTests(unittest.TestCase):
    def test_a_few_items_sharing_an_address_are_stored_as_the_distinct_posts(self):
        # 48 items, 2 of which share one address: not a failure
        posts = [_item(n, f"https://blog.example/p/{n}") for n in range(46)]
        posts += [_item(46, "https://blog.example/p/same"), _item(47, "https://blog.example/p/same")]
        self.assertIsNone(collapsed(posts))
        self.assertEqual(shared_addresses(posts), "2 of 48 items share 1 address: 47 posts stored")
        fetched = checked_fetch(posts, 48, {})
        self.assertIsNone(fetched.failure)
        self.assertEqual(fetched.warning, "2 of 48 items share 1 address: 47 posts stored")
        self.assertEqual(len(fetched), 48, "every post goes to the save; the address upsert keeps one")

    def test_a_feed_whose_items_fold_into_a_few_addresses_still_fails(self):
        posts = [_item(n, f"https://tool.example/{'a' if n % 2 else 'b'}") for n in range(888)]
        self.assertEqual(collapsed(posts), "the feed has 888 items but 2 would be stored (888 items share 2 addresses)")
        self.assertIsNone(shared_addresses(posts), "a collapse is the failure, not a warning too")

    def test_the_line_is_half_the_items(self):
        # 4 distinct items: 2 lost of 4 is not over half; 3 lost of 4 is.
        two = [_item(0, "https://a.example/x"), _item(1, "https://a.example/x"), _item(2, "https://a.example/x"),
               _item(3, "https://a.example/y")]
        self.assertIsNone(collapsed(two))
        three = two[:3] + [_item(3, "https://a.example/x")]
        self.assertIsNotNone(collapsed(three))

    def test_no_shared_address_no_warning(self):
        posts = [_item(n, f"https://blog.example/p/{n}") for n in range(5)]
        self.assertIsNone(checked_fetch(posts, 5, {}).warning)


def _feed(items: str) -> str:
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>Changelog</title>{items}</channel></rss>')


class SharedLinkIdentityTests(unittest.TestCase):
    FEED = "https://tool.example/changelog/feed.xml"

    def test_links_that_differ_only_by_a_fragment_are_one_page_the_guid_is_the_item(self):
        items = "".join(f"<item><title>v1.{n}</title><link>https://tool.example/changelog#v1-{n}</link>"
                        f"<guid isPermaLink=\"false\">release-1.{n}</guid></item>" for n in range(6))
        posts = parsing.parse_feed_posts(_feed(items), self.FEED)
        self.assertEqual(len({post["url"] for post in posts}), 6)
        self.assertTrue(all("insight_item=release-1." in post["url"] for post in posts))
        self.assertIsNone(collapsed(posts))

    def test_guids_that_are_the_shared_page_with_fragments_give_each_item_its_token(self):
        items = "".join(f"<item><title>v2.{n}</title><link>https://tool.example/changelog</link>"
                        f"<guid>https://tool.example/changelog#v2-{n}</guid></item>" for n in range(5))
        posts = parsing.parse_feed_posts(_feed(items), self.FEED)
        self.assertEqual(len({post["url"] for post in posts}), 5)
        self.assertIsNone(collapsed(posts))

    def test_a_guid_address_of_its_own_is_kept_when_the_link_is_shared(self):
        items = "".join(f"<item><title>Ep {n}</title><link>https://show.example/</link>"
                        f"<guid>https://show.example/ep/{n}</guid></item>" for n in range(4))
        posts = parsing.parse_feed_posts(_feed(items), self.FEED)
        self.assertEqual(sorted(post["url"] for post in posts), [f"https://show.example/ep/{n}" for n in range(4)])

    def test_two_items_sharing_one_link_stay_one_post_as_before(self):
        items = ("<item><title>A</title><link>https://blog.example/p</link><guid>g1</guid></item>"
                 "<item><title>A again</title><link>https://blog.example/p#more</link><guid>g2</guid></item>"
                 "<item><title>B</title><link>https://blog.example/q</link><guid>g3</guid></item>")
        posts = parsing.parse_feed_posts(_feed(items), "https://blog.example/feed")
        self.assertEqual(sorted({post["url"] for post in posts}),
                         ["https://blog.example/p", "https://blog.example/p#more", "https://blog.example/q"])


# --------------------------------------------------------------------------- 2. Reddit through OAuth


def _answers(**extra):
    return {TOKEN_URL: TOKEN, f"{OAUTH_BASE}/r/examplesub/new?limit=10&raw_json=1": LISTING, **extra}


class RedditOAuthTests(unittest.TestCase):
    def test_without_credentials_the_kind_is_unavailable_with_the_reason_never_a_backoff(self):
        kind = RedditKind(FakeHttp({}), credentials=MappingCredentials())
        with self.assertRaises(KindUnavailable) as raised:
            run(kind.fetch_latest(_src("r/examplesub"), 10))
        self.assertEqual(raised.exception.reason, NO_CREDENTIALS)
        self.assertEqual(NO_CREDENTIALS, "Reddit closed its feeds: add Reddit credentials in Sources → Connections")
        self.assertEqual(kind.archive_refused, NO_CREDENTIALS)
        availability = availability_from_env({}, credentials=MappingCredentials())
        self.assertEqual(availability.reddit_reason, NO_CREDENTIALS)
        self.assertEqual(unavailable_reason(REDDIT_PROFILE, availability), NO_CREDENTIALS)

    def test_with_credentials_it_is_available(self):
        availability = availability_from_env({}, credentials=CREDS)
        self.assertIsNone(availability.reddit_reason)
        self.assertIsNone(unavailable_reason(REDDIT_PROFILE, availability))
        self.assertIsNone(RedditKind(FakeHttp(), credentials=CREDS).archive_refused)
        self.assertIsNone(unavailable_reason(REDDIT_PROFILE, Availability(True, True)), "the default: available")

    def test_the_live_read_asks_a_token_then_reads_new_on_oauth_with_a_descriptive_agent(self):
        http = FakeHttp(_answers())
        posts = run(RedditKind(http, credentials=CREDS).fetch_latest(_src("r/examplesub"), 10))
        self.assertEqual(http.requests, [TOKEN_URL, f"{OAUTH_BASE}/r/examplesub/new?limit=10&raw_json=1"])
        self.assertEqual(http.posts, [(TOKEN_URL, {"grant_type": "client_credentials"})])
        basic = base64.b64encode(b"abcDEF123456:s3cret-value-xyz").decode()
        self.assertEqual(http.headers_for(TOKEN_URL)["Authorization"], f"Basic {basic}")
        listing = f"{OAUTH_BASE}/r/examplesub/new?limit=10&raw_json=1"
        self.assertEqual(http.headers_for(listing), {"Authorization": "bearer tok-1"})
        self.assertEqual(dict(http.user_agents)[listing], "server:insight-reader:1.0 (by /u/owner_name)")
        self.assertEqual([p["external_id"] for p in posts], ["1q2w3e", "4r5t6y"], "the comment (t1) is no post")
        first, link = posts
        self.assertEqual(first["url"], "https://reddit.com/r/examplesub/comments/1q2w3e/"
                                       "benchmarks_a_30b_model_on_two_consumer_cards/")
        self.assertEqual((first["platform"], first["source"]), ("reddit", "r/examplesub"))
        self.assertEqual(first["categories"], ["examplesub", "Discussion"])
        self.assertIn("two cards", first["content"])
        self.assertEqual(first["date"], datetime.fromtimestamp(1795420800, tz=timezone.utc))
        self.assertEqual(link["media_urls"], ["https://lab.example/blog/new-open-model"])
        self.assertEqual(link["content"], link["title"], "a link post with no text reads as its title")

    def test_the_token_is_reused_until_it_nears_its_expiry(self):
        clock = [1000.0]
        http = FakeHttp(_answers())
        kind = RedditKind(http, credentials=CREDS, clock=lambda: clock[0])
        run(kind.fetch_latest(_src("r/examplesub"), 10))
        run(kind.fetch_latest(_src("r/examplesub"), 10))
        self.assertEqual(http.requests.count(TOKEN_URL), 1)
        clock[0] += 86400 - 30
        run(kind.fetch_latest(_src("r/examplesub"), 10))
        self.assertEqual(http.requests.count(TOKEN_URL), 2)

    def test_a_401_asks_a_new_token_once(self):
        listing = f"{OAUTH_BASE}/r/examplesub/new?limit=10&raw_json=1"
        answers = iter([HttpError("HTTP 401 while fetching", status=401), LISTING])
        http = FakeHttp({TOKEN_URL: TOKEN, listing: lambda url: next(answers)})
        posts = run(RedditKind(http, credentials=CREDS).fetch_latest(_src("r/examplesub"), 10))
        self.assertEqual(len(posts), 2)
        self.assertEqual(http.requests.count(TOKEN_URL), 2)

    def test_credentials_reddit_refuses_are_unavailable_with_why(self):
        http = FakeHttp({TOKEN_URL: HttpError("HTTP 401 while posting to", status=401)})
        with self.assertRaises(KindUnavailable) as raised:
            run(RedditKind(http, credentials=CREDS).fetch_latest(_src("r/examplesub"), 10))
        self.assertEqual(raised.exception.reason, REFUSED_CREDENTIALS)
        http = FakeHttp({TOKEN_URL: {"error": "invalid_grant"}})
        with self.assertRaises(KindUnavailable):
            run(RedditKind(http, credentials=CREDS).fetch_latest(_src("r/examplesub"), 10))

    def test_the_archive_pages_top_through_the_same_client(self):
        page = json.loads(LISTING)
        last = json.loads(LISTING)
        last["data"]["after"] = None
        http = FakeHttp({TOKEN_URL: TOKEN,
                         f"{OAUTH_BASE}/r/examplesub/top?limit=100&t=all&raw_json=1": json.dumps(page),
                         f"{OAUTH_BASE}/r/examplesub/top?limit=100&t=all&after=t3_1q2w3e&raw_json=1": json.dumps(last)})

        async def pages():
            return [p async for p in RedditKind(http, credentials=CREDS).archive_pages(_src("r/examplesub"), 500,
                                                                                      None, None)]

        got = run(pages())
        self.assertEqual([len(p.posts) for p in got], [2, 2])
        self.assertEqual(got[0].checkpoint["after"], "t3_1q2w3e")
        self.assertEqual(http.requests.count(TOKEN_URL), 1)

    def test_subreddit_addresses_and_their_old_feeds_are_this_kind(self):
        kind = RedditKind(FakeHttp(), credentials=CREDS)
        for handle in ("https://www.reddit.com/r/examplesub/.rss", "https://old.reddit.com/r/examplesub/",
                       "https://www.reddit.com/r/examplesub/new.xml", "https://reddit.com/r/examplesub"):
            with self.subTest(handle=handle):
                self.assertTrue(kind.matches(_src(handle, platform="rss")))
        for handle in ("https://www.reddit.com/r/examplesub/comments/abc/x/.rss", "https://www.reddit.com/user/x/.rss",
                       "https://blog.example/r/x/feed"):
            with self.subTest(handle=handle):
                self.assertFalse(kind.matches(_src(handle, platform="rss")))

    def test_the_connection_values_are_checked_and_never_echoed(self):
        self.assertEqual(normalise_value("reddit", "username", "/u/owner_name"), "owner_name")
        self.assertEqual(normalise_value("reddit", "client_id", " abcDEF123456 "), "abcDEF123456")
        with self.assertRaises(CredentialInvalid) as raised:
            normalise_value("reddit", "client_secret", "has spaces in it!")
        self.assertNotIn("has spaces", str(raised.exception))


# --------------------------------------------------------------------------- 3. the stalled flag


class StalledTests(unittest.TestCase):
    def _flag(self, *, success_ago=None, failures=0, interval=timedelta(hours=1), enabled=True, created_ago=None,
              platform="rss"):
        state = FetchStateRow(source_id="s1", consecutive_failures=failures,
                              last_success_at=NOW - success_ago if success_ago is not None else None)
        source = {"platform": platform, "created_at": NOW - created_ago if created_ago is not None else None}
        return stalled_fields(source, state, interval, failures, enabled, NOW)

    def test_last_success_older_than_three_days_or_five_intervals(self):
        self.assertIsNone(self._flag(success_ago=timedelta(days=2)))
        flag = self._flag(success_ago=timedelta(days=4), failures=2)
        self.assertEqual(flag, {"since": (NOW - timedelta(days=4)).isoformat(), "days": 4, "failures": 2,
                                "posts": 0, "reason": None})
        # A daily source: 5 intervals is 5 days, past the 3-day floor.
        self.assertIsNone(self._flag(success_ago=timedelta(days=4), interval=timedelta(days=1)))
        self.assertIsNotNone(self._flag(success_ago=timedelta(days=6), interval=timedelta(days=1)))

    def test_failing_five_in_a_row(self):
        self.assertIsNone(self._flag(success_ago=timedelta(hours=5), failures=STALLED_FAILURES - 1))
        self.assertEqual(self._flag(success_ago=timedelta(hours=5), failures=STALLED_FAILURES)["failures"],
                         STALLED_FAILURES)

    def test_never_worked_counts_from_when_it_was_added(self):
        self.assertIsNone(self._flag(created_ago=timedelta(days=1)))
        flag = self._flag(created_ago=timedelta(days=10))
        self.assertEqual((flag["since"], flag["days"]), (None, 10))

    def test_off_and_saved_pages_are_never_flagged(self):
        self.assertIsNone(self._flag(success_ago=timedelta(days=30), enabled=False))
        self.assertIsNone(self._flag(success_ago=timedelta(days=30), platform="saved"))

    def test_the_summary_counts_them(self):
        rows = [{"status": "due", "stalled": {"days": 4}}, {"status": "unavailable", "stalled": {"days": 2}},
                {"status": "due", "stalled": None}]
        self.assertEqual(summarize_health(rows)["stalled"], 2)


# --------------------------------------------------------------------------- 4. dead hosts


def _state(success_ago=None, **kw) -> FetchStateRow:
    return FetchStateRow(source_id="s1", consecutive_failures=9, last_outcome="error",
                         last_success_at=NOW - success_ago if success_ago is not None else None, **kw)


DNS = HttpError("Cannot resolve gone.example: Name or service not known", unreachable=True)
SOURCE = {"id": "s1", "platform": "rss", "handle_or_url": "https://gone.example/feed", "settings": {},
          "created_at": NOW - timedelta(days=200)}


class _Store:
    def __init__(self):
        self.records = []

    def record(self, source_id, *, checked_at, finding):
        self.records.append(finding)

    def items(self, source_id):
        return []

    def switch(self, *args):  # pragma: no cover - a dead host is never switched
        raise AssertionError("switched")


class DeadHostTests(unittest.TestCase):
    def test_unreachable_is_its_own_signal(self):
        self.assertEqual(failure_signal(DNS), "unreachable")
        self.assertIsNone(failure_signal(HttpError("Failed fetching x: [Errno -2] Name or service not known")),
                          "an error without the flag (older) is as before")

    def test_the_http_client_marks_dns_and_no_route_failures(self):
        self.assertTrue(http_module._unreachable(socket.gaierror(-2, "Name or service not known")))
        self.assertTrue(http_module._unreachable(ConnectionRefusedError(111, "refused")))
        self.assertFalse(http_module._unreachable(TimeoutError()))
        guard = http_module.AddressGuard(bridges=(), resolve=lambda host, port: (_ for _ in ()).throw(
            socket.gaierror(-2, "Name or service not known")))
        with self.assertRaises(HttpError) as raised:
            guard.addresses("gone.example", 443)
        self.assertTrue(raised.exception.unreachable)
        with self.assertRaises(HttpError) as raised:
            with http_module._classified("fetching", "https://gone.example/"):
                raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        self.assertTrue(raised.exception.unreachable)

    def test_no_answer_for_fourteen_days_is_dead_with_a_suggestion(self):
        finding = dead_finding(SOURCE, _state(success_ago=DEAD_AFTER + timedelta(days=6)), DNS, NOW)
        self.assertEqual((finding["dead"], finding["host"], finding["reason"]),
                         (True, "gone.example", "does not resolve or has no route"))
        self.assertIn("switch the source off, or replace it", finding["note"])
        self.assertIn("20 days", finding["note"])
        timeout = HttpError("Timed out fetching", timed_out=True)
        self.assertEqual(dead_finding(SOURCE, _state(success_ago=DEAD_AFTER), timeout, NOW)["reason"], "times out")

    def test_not_dead_under_fourteen_days_nor_for_an_answer_nor_when_dismissed(self):
        self.assertIsNone(dead_finding(SOURCE, _state(success_ago=DEAD_AFTER - timedelta(hours=1)), DNS, NOW))
        self.assertIsNone(dead_finding(SOURCE, _state(success_ago=timedelta(days=30)),
                                       HttpError("HTTP 503", status=503), NOW), "a server that answers is no dead host")
        self.assertIsNone(dead_finding(SOURCE, _state(success_ago=timedelta(days=30), doctor_finding={"dismissed": True}),
                                       DNS, NOW))
        self.assertIsNone(dead_finding(SOURCE, _state(success_ago=timedelta(days=30),
                                                      doctor_checked_at=NOW - timedelta(hours=2)), DNS, NOW))
        self.assertIsNone(dead_finding({**SOURCE, "handle_or_url": "r/examplesub"}, _state(), DNS, NOW),
                          "a bare handle has no host")
        never = dead_finding(SOURCE, _state(), DNS, NOW)
        self.assertEqual(never["since"], SOURCE["created_at"].isoformat(), "never worked: since it was added")

    def test_the_doctor_records_it_never_switches_and_any_kind_counts(self):
        store = _Store()
        doctor = SourceDoctor(http=FakeHttp({}), registry=None, store=store, clock=FixedClock(NOW))
        run(doctor.after_failure({**SOURCE, "platform": "youtube"}, FakeKind("youtube_channel"),
                                 _state(success_ago=timedelta(days=40)), DNS))
        self.assertEqual(len(store.records), 1)
        self.assertTrue(store.records[0]["dead"])

    def test_under_fourteen_days_an_unreachable_host_waits_for_the_usual_failures(self):
        store = _Store()
        doctor = SourceDoctor(http=FakeHttp({}), registry=None, store=store, clock=FixedClock(NOW))
        row = FetchStateRow(source_id="s1", consecutive_failures=1, last_outcome="error",
                            last_success_at=NOW - timedelta(days=1))
        run(doctor.after_failure(SOURCE, FakeKind("generic_rss"), row, DNS))
        self.assertEqual(store.records, [], "one DNS blip is no finding")

    def test_health_shows_the_dead_mark(self):
        state = _state(success_ago=timedelta(days=30), doctor_checked_at=NOW,
                       doctor_finding={"replacement": None, "dismissed": False, "dead": True, "host": "gone.example",
                                       "since": "2026-10-20T00:00:00+00:00", "reason": "does not resolve or has no route"})
        fields = _doctor_fields(state, "https://gone.example/feed")
        self.assertEqual(fields["dead"], {"host": "gone.example", "since": "2026-10-20T00:00:00+00:00",
                                          "reason": "does not resolve or has no route", "checked_at": NOW.isoformat()})
        self.assertIsNone(fields["doctor_looked_at"], "not 'no replacement found': nothing was looked for")
        self.assertIsNone(_doctor_fields(_state(), "https://gone.example/feed")["dead"])


if __name__ == "__main__":
    unittest.main()
