"""Issue 0137: new spheres, round 2. No network: every request is a FakeHttp answer, every feed and page a
fixture with invented hosts. B6 (series) is in test_series, B8 (references) in test_reference_links_0137,
B10 (Bluesky) in test_bluesky_0137."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_posts import published_precision
from insight_core.ingestion import full_text
from insight_core.ingestion.feed_finder import (
    EMPTY_FEED, NO_BRIDGE, OTHER_SCOPE, SEARCH_ONLY, STALE, find_feeds, learned_feeds,
)
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import FetchedPosts, checked_fetch, collapsed
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.ingestion.kinds.nitter_rss import nitter_origin
from insight_core.ingestion.kinds.parsing import (
    ITEM_PARAM, author_names, clean_authors, feed_root, parse_feed_posts, repaired_xml,
)
from insight_core.ingestion.where_linked import feed_row, follow
from insight_core.scripts import repair_0137
from insight_core.services.operations_service import sources_failing, summarize_health
from insight_core.tests._kind_fakes import FakeHttp, FakeKind
from insight_core.tests.test_ingestion_runner import _Harness, _source

SHOW = "https://audio.example/show/feed.xml"


def run(coro):
    return asyncio.run(coro)


def rss(title: str, items: str) -> str:
    return (f'<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<channel><title>{title}</title>{items}</channel></rss>")


def item(title: str, *, link: str = "", guid: str = "", enclosure: str = "", date: str = "Mon, 02 Nov 2026 10:00:00 GMT",
         permalink: bool = False) -> str:
    return ("<item>" + f"<title>{title}</title>" + (f"<link>{link}</link>" if link else "")
            + (f'<guid isPermaLink="{str(permalink).lower()}">{guid}</guid>' if guid else "")
            + (f'<enclosure url="{enclosure}" type="audio/mpeg" length="1"/>' if enclosure else "")
            + (f"<pubDate>{date}</pubDate>" if date else "") + "<description>An episode.</description></item>")


def toc(title: str, *links: str, date: str = "Mon, 02 Nov 2026 10:00:00 GMT") -> str:
    return rss(title, "".join(item(f"Item {n}", link=link, date=date) for n, link in enumerate(links)))


def finder(responses, url, known=()):
    http = FakeHttp(responses)
    return run(find_feeds(http, KindRegistry.default(http, None), url, known)), http


def blocked(url: str, status: int = 403) -> HttpError:
    return HttpError(f"HTTP {status} while fetching {url}", status=status)


# --------------------------------------------------------------------------- A1 health counts failures


class HealthSummaryTests(unittest.TestCase):
    def test_errors_counts_every_failing_source_backoff_included(self):
        rows = [{"status": s} for s in ("backoff", "backoff", "backoff", "due", "deferred", "disabled")]
        summary = summarize_health(rows)
        self.assertEqual((summary["errors"], summary["backoff"], summary["due_now"]), (3, 3, 1))
        self.assertEqual(sources_failing(summary), 3)
        summary = summarize_health([{"status": "error"}, {"status": "backoff"}])
        self.assertEqual((summary["errors"], sources_failing(summary)), (2, 2))
        self.assertEqual(summarize_health([{"status": "due"}])["errors"], 0)

    def test_items_stored_as_fewer_posts_than_they_are_is_a_failure_saying_so(self):
        posts = [{"url": SHOW, "guid": f"ep-{n}", "title": f"Episode {n}"} for n in range(282)]
        self.assertEqual(collapsed(posts), "the feed has 282 items but 1 would be stored (282 items share 1 address)")
        # Duplicates (the same guid, or no guid and the same title) are no failure.
        self.assertIsNone(collapsed([{"url": "https://a.example/1", "guid": "g"}, {"url": "https://a.example/1", "guid": "g"}]))
        self.assertIsNone(collapsed([{"url": "https://a.example/1", "title": "T"}, {"url": "https://a.example/1", "title": "T"}]))
        self.assertEqual(checked_fetch(posts, 282, {}).failure, collapsed(posts))

    def test_the_runner_saves_the_posts_and_records_the_fetch_failing(self):
        def collapsing(source, limit):
            posts = FetchedPosts([{"url": source["handle_or_url"], "title": "Episode", "content": "c"}])
            posts.failure = "the feed has 3 items but 1 would be stored (3 items share 1 address)"
            return posts

        source = _source("https://audio.example/feed")
        h = _Harness([source], [FakeKind("fake_rss", behaviour=collapsing, matches=lambda s: True)])
        report = run(h.run(force=True))
        row = h.state.rows[source["id"]]
        self.assertEqual((row.last_outcome, row.consecutive_failures), ("error", 1))
        self.assertEqual(row.last_error, "the feed has 3 items but 1 would be stored (3 items share 1 address)")
        self.assertEqual(report.sources_failed, 1)
        self.assertIn("https://audio.example/feed", h.saver.known)   # its posts are saved all the same


# --------------------------------------------------------------------------- B1 items without a link


class ItemIdentityTests(unittest.TestCase):
    def test_podcast_items_without_a_link_are_each_a_post_by_guid_then_enclosure_then_title(self):
        feed = rss("A show", item("Ep 3", guid="0a1b-3", enclosure="https://cdn.example/3.mp3")
                   + item("Ep 2", enclosure="https://cdn.example/2.mp3")
                   + item("Ep 1", date="Mon, 26 Oct 2026 10:00:00 GMT")
                   + item("Ep 0", guid="https://audio.example/ep/0", permalink=True))
        posts = {p["title"]: p["url"] for p in parse_feed_posts(feed, SHOW)}
        self.assertEqual(posts["Ep 3"], f"{SHOW}?{ITEM_PARAM}=0a1b-3")
        self.assertEqual(posts["Ep 2"], "https://cdn.example/2.mp3")
        self.assertTrue(posts["Ep 1"].startswith(f"{SHOW}?{ITEM_PARAM}=Ep%201%7C"))
        self.assertEqual(posts["Ep 0"], "https://audio.example/ep/0")
        self.assertNotIn(SHOW, posts.values())
        # The same items read again are the same posts.
        self.assertEqual({p["url"] for p in parse_feed_posts(feed, SHOW)}, set(posts.values()))

    def test_a_link_every_episode_shares_is_the_shows_not_an_items(self):
        page = "https://audio.example/show"
        feed = rss("A show", "".join(item(f"Ep {n}", link=page, guid=f"uuid-{n}") for n in range(3)))
        self.assertEqual(len({p["url"] for p in parse_feed_posts(feed, SHOW)}), 3)
        # Two items with one link (the same article posted twice) stay one post, as before.
        twice = rss("News", item("A", link="https://news.example/a", guid="1") + item("A again", link="https://news.example/a", guid="2"))
        self.assertEqual({p["url"] for p in parse_feed_posts(twice, "https://news.example/feed")}, {"https://news.example/a"})

    def test_a_podcast_feed_stores_its_episodes_and_never_reads_their_audio_as_a_page(self):
        feed = rss("A show", "".join(item(f"Ep {n}", guid=f"uuid-{n}", enclosure=f"https://cdn.example/{n}.mp3") for n in range(5)))
        http = FakeHttp({SHOW: feed})
        posts = run(GenericRssKind(http).fetch_latest({"handle_or_url": SHOW}, 20))
        self.assertEqual(len({p["url"] for p in posts}), 5)
        self.assertIsNone(posts.failure)
        self.assertEqual(http.requests, [SHOW])
        self.assertFalse(full_text.page_is_article(f"{SHOW}?{ITEM_PARAM}=x"))
        self.assertFalse(full_text.page_is_article("https://cdn.example/ep.mp3?updated=1"))
        self.assertTrue(full_text.page_is_article("https://news.example/2026/11/a-story"))


# --------------------------------------------------------------------------- B4 the finder parses what it offers


BARE_AMP = rss("Bank & Co", item("Rates & prices", link="https://bank.example/r1") + item("Two", link="https://bank.example/r2"))


class ParseWhatIsOfferedTests(unittest.TestCase):
    def test_a_bare_ampersand_and_a_control_character_are_repaired_in_the_fetcher(self):
        self.assertEqual(repaired_xml("R&D &amp; &#38; &x;\x01"), "R&amp;D &amp; &#38; &x;")
        self.assertEqual([p["title"] for p in parse_feed_posts(BARE_AMP, "https://bank.example/rss.xml")],
                         ["Rates & prices", "Two"])

    def test_a_feed_the_parser_refuses_is_never_offered_and_says_why(self):
        broken = BARE_AMP.replace("</channel>", "<item><title>x</titel></item></channel>")
        page = '<html><head><link rel="alternate" type="application/rss+xml" href="/rss.xml"></head></html>'
        finding, _ = finder({"https://bank.example/": page, "https://bank.example/rss.xml": broken}, "https://bank.example/")
        self.assertEqual((finding.status, finding.feeds), ("none", ()))
        # The parser's own message, as the fetcher would fail with it.
        self.assertRegex(finding.refused, r"^the feed can't be read: not well-formed \(invalid token\): line 1, column \d+$")
        finding, _ = finder({"https://bank.example/": page, "https://bank.example/rss.xml": BARE_AMP}, "https://bank.example/")
        self.assertEqual(finding.feeds[0].url, "https://bank.example/rss.xml")


# --------------------------------------------------------------------------- B5 none says why


class ReasonTests(unittest.TestCase):
    def test_none_says_blocked_rate_limited_needs_login_or_empty(self):
        for status, reason in ((403, "blocked"), (429, "rate-limited"), (401, "needs login"), (410, "gone")):
            finding, _ = finder({"https://shut.example/x": blocked("https://shut.example/x", status)}, "https://shut.example/x")
            self.assertEqual((finding.status, finding.reason), ("none", reason))
        empty = '<?xml version="1.0"?><rss version="2.0"><channel><title>Quiet</title></channel></rss>'
        finding, _ = finder({"https://quiet.example/feed": empty}, "https://quiet.example/feed")
        self.assertEqual((finding.status, finding.reason), ("none", EMPTY_FEED))
        finding, _ = finder({"https://plain.example/": "<html><body>Hello</body></html>"}, "https://plain.example/")
        self.assertEqual(finding.reason, "none found")


# --------------------------------------------------------------------------- A3 / B3 bridges


class BridgeTests(unittest.TestCase):
    def test_a_pasted_channel_uses_the_configured_bridge(self):
        with mock.patch.dict("os.environ", {"TELEGRAM_RSS_HOSTS": "tg.example"}):
            finding, http = finder({"https://tg.example/rss/achannel": toc("A channel", "https://t.me/achannel/5")},
                                   "https://t.me/achannel")
        self.assertEqual((finding.status, [f.url for f in finding.feeds]), ("found", ["https://tg.example/rss/achannel"]))
        self.assertEqual(http.requests, ["https://tg.example/rss/achannel"])
        with mock.patch.dict("os.environ", {"TELEGRAM_RSS_HOSTS": ""}):
            finding, http = finder({}, "https://t.me/achannel")
        self.assertEqual((finding.status, finding.reason, http.requests), ("none", NO_BRIDGE, []))

    def test_a_pasted_account_uses_your_nitter(self):
        self.assertEqual(nitter_origin({}), "https://nitter.local")
        self.assertEqual(nitter_origin({"NITTER_HOSTS": "nitter.example, other.example"}), "https://nitter.example")
        self.assertIsNone(nitter_origin({"NITTER_HOSTS": ""}))
        with mock.patch.dict("os.environ", {"NITTER_HOSTS": "nitter.example"}):
            finding, _ = finder({"https://nitter.example/someone/rss": toc("someone", "https://nitter.example/someone/status/1")},
                                "https://x.com/someone")
        self.assertEqual(finding.feeds[0].url, "https://nitter.example/someone/rss")

    def test_a_nitter_answering_an_error_is_never_direct(self):
        gone = "https://nitter.net/someone/rss"
        finding, _ = finder({gone: blocked(gone, 410)}, gone)
        self.assertEqual((finding.status, finding.reason), ("none", "gone"))
        finding, _ = finder({gone: toc("someone", "https://nitter.net/someone/status/1")}, gone)
        self.assertEqual(finding.status, "direct")

    def test_an_apple_podcasts_page_gives_the_shows_feed(self):
        page = "https://podcasts.apple.com/us/podcast/a-show/id123456789"
        lookup = "https://itunes.apple.com/lookup?id=123456789&entity=podcast"
        finding, _ = finder({lookup: json.dumps({"resultCount": 1, "results": [{"feedUrl": SHOW}]}),
                             SHOW: rss("A show", item("Ep 1", guid="u1"))}, page)
        self.assertEqual((finding.status, finding.feeds[0].url), ("found", SHOW))


# --------------------------------------------------------------------------- B3 feed directories


class DirectoryTests(unittest.TestCase):
    def test_a_feed_directory_is_followed_and_its_feeds_known_by_content(self):
        bank = "https://bank.example"
        page = f'<html><body><a href="/press/">Press</a><a href="/rss/">RSS feeds</a></body></html>'
        directory = (f'<html><body><a href="/rss/press.html">Press releases</a>'
                     f'<a href="/rss/speeches.html">Speeches</a><a href="/about/">About</a></body></html>')
        finding, http = finder({f"{bank}/press/": page, f"{bank}/rss/": directory,
                                f"{bank}/rss/press.html": toc("Press releases", f"{bank}/press/pr1"),
                                f"{bank}/rss/speeches.html": toc("Speeches", f"{bank}/speeches/s1")}, f"{bank}/press/")
        self.assertEqual(finding.status, "found")
        self.assertEqual([f.url for f in finding.feeds], [f"{bank}/rss/press.html", f"{bank}/rss/speeches.html"])
        self.assertNotIn(f"{bank}/about/", http.requests)


# --------------------------------------------------------------------------- A2 blocked pages


class BlockedPageTests(unittest.TestCase):
    def test_a_blocked_page_tries_the_feeds_its_sitemap_names(self):
        pub = "https://pub.example"
        responses = {f"{pub}/journal/jx": blocked(f"{pub}/journal/jx"),
                     f"{pub}/robots.txt": f"User-agent: *\nDisallow: /search\nSitemap: {pub}/sitemap_index.xml\n",
                     f"{pub}/sitemap_index.xml": f"<sitemapindex><sitemap><loc>{pub}/sitemap-feeds.xml</loc></sitemap></sitemapindex>",
                     f"{pub}/sitemap-feeds.xml": f"<urlset><url><loc>{pub}/jx/feed/toc.rss</loc></url><url><loc>{pub}/jx/a1</loc></url></urlset>",
                     f"{pub}/jx/feed/toc.rss": toc("JX current issue", f"{pub}/jx/a1")}
        finding, _ = finder(responses, f"{pub}/journal/jx")
        self.assertEqual((finding.status, [f.url for f in finding.feeds]), ("found", [f"{pub}/jx/feed/toc.rss"]))

    def test_a_blocked_page_tries_the_shape_of_your_other_feeds_at_that_publisher(self):
        pub = "https://pub.example"
        known = [f"{pub}/action/showFeed?type=etoc&feed=rss&jc=alpha", f"{pub}/alpha/current.rss", "https://other.example/feed"]
        self.assertEqual(learned_feeds(f"{pub}/journal/beta", known),
                         [f"{pub}/action/beta?type=etoc&feed=rss&jc=alpha", f"{pub}/action/showFeed?type=etoc&feed=rss&jc=beta",
                          f"{pub}/beta/current.rss"])
        responses = {f"{pub}/journal/beta": blocked(f"{pub}/journal/beta"),
                     f"{pub}/action/showFeed?type=etoc&feed=rss&jc=beta": toc("Beta", f"{pub}/doi/b1")}
        finding, _ = finder(responses, f"{pub}/journal/beta", known)
        self.assertEqual([f.url for f in finding.feeds], [f"{pub}/action/showFeed?type=etoc&feed=rss&jc=beta"])


# --------------------------------------------------------------------------- A5 saved searches


class SearchFeedTests(unittest.TestCase):
    def test_a_saved_search_is_never_the_only_offer_while_the_site_has_its_own(self):
        pub = "https://pub.example"
        page = '<html><head><link rel="alternate" type="application/rss+xml" href="/search/rss?q=x"></head></html>'
        responses = {f"{pub}/": page, f"{pub}/search/rss?q=x": toc("Keyword search for x", f"{pub}/s1"),
                     f"{pub}/feed": toc("Pub", f"{pub}/a1")}
        finding, _ = finder(responses, f"{pub}/")
        self.assertEqual(([f.url for f in finding.feeds], finding.note), ([f"{pub}/feed"], ""))
        del responses[f"{pub}/feed"]
        finding, _ = finder(responses, f"{pub}/")
        self.assertEqual(([f.url for f in finding.feeds], finding.note), ([f"{pub}/search/rss?q=x"], SEARCH_ONLY))


# --------------------------------------------------------------------------- B2 another scope or stale


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tank = "https://tank.example"
        articles = "".join(f'<a href="/blog/an-author/why-rates-rose-{n}">Post {n}</a>' for n in range(4))
        self.page = (f'<html><head><link rel="alternate" type="application/rss+xml" href="/feed"></head><body>'
                     f'<nav><a href="/about-the-whole-tank-here">About</a></nav>{articles}'
                     f'<time datetime="2026-11-06T10:00:00Z">6 Nov</time></body></html>')

    def test_a_site_feed_sharing_no_article_with_the_page_is_flagged_with_page_watching_offered(self):
        site_feed = toc("The tank", f"{self.tank}/research/other-topic-entirely", f"{self.tank}/events/a-panel-talk")
        responses = {f"{self.tank}/blog/an-author": self.page, f"{self.tank}/feed": site_feed}
        finding, _ = finder(responses, f"{self.tank}/blog/an-author")
        self.assertEqual(finding.feeds[0].flag, OTHER_SCOPE)
        self.assertEqual(feed_row(finding.feeds[0])["not_this_page"], OTHER_SCOPE)
        http = FakeHttp(responses)
        offers = mock.AsyncMock(return_value=[{"url": f"{self.tank}/blog/an-author", "found": 4, "items": [{}]}])
        with mock.patch("insight_core.ingestion.where_linked.page_watch.offers", offers):
            answer = run(follow(http, KindRegistry.default(http, None), f"{self.tank}/blog/an-author", []))
        self.assertEqual(answer["watch"]["url"], f"{self.tank}/blog/an-author")

    def test_a_feed_holding_the_pages_articles_is_not_flagged_and_a_stale_one_is(self):
        own = toc("The author", f"{self.tank}/blog/an-author/why-rates-rose-0?rss=yes")
        finding, _ = finder({f"{self.tank}/blog/an-author": self.page, f"{self.tank}/feed": own}, f"{self.tank}/blog/an-author")
        self.assertEqual(finding.feeds[0].flag, "")
        old = toc("The author", f"{self.tank}/blog/an-author/why-rates-rose-0", date="Thu, 18 Apr 2024 10:00:00 GMT")
        finding, _ = finder({f"{self.tank}/blog/an-author": self.page, f"{self.tank}/feed": old}, f"{self.tank}/blog/an-author")
        self.assertEqual(finding.feeds[0].flag, STALE)


# --------------------------------------------------------------------------- B7 authors


class AuthorTests(unittest.TestCase):
    def test_affiliations_and_identifiers_are_dropped_from_the_author_line(self):
        self.assertEqual(author_names("Ann Lee, Bo Kim, Sam B. KimDepartment of Psychology, University of Somewhere"),
                         ["Ann Lee", "Bo Kim", "Sam B. Kim"])
        self.assertEqual(author_names("Jo A. TherrienTerry HuebPat Q. Lanehttps://ror.org/02abc123Some Research Centre, City"),
                         ["Jo A. Therrien", "Terry Hueb", "Pat Q. Lane"])
        self.assertEqual(author_names("Ian VanderWaal"), ["Ian VanderWaal"])
        self.assertEqual(author_names("Mary McDonald and Lee DeLong"), ["Mary McDonald", "Lee DeLong"])
        self.assertEqual(author_names("Ann Lee, Institute for Examples"), ["Ann Lee"])

    def test_one_author_per_name_element_with_its_affiliation_children_dropped(self):
        feed = ('<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                'xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<channel rdf:about="https://j.example/toc"><title>J</title></channel>'
                '<item rdf:about="https://j.example/a1"><title>A paper</title><dc:date>2026-11-02</dc:date>'
                '<dc:creator><name>Ann Lee</name><aff>Department of Examples</aff><orcid>https://orcid.org/0000</orcid></dc:creator>'
                '<dc:creator>Bo Kim<sup>a</sup></dc:creator>'
                '<dc:creator>&lt;span&gt;Cy Park&lt;/span&gt;&lt;span class="aff"&gt;University of X&lt;/span&gt;</dc:creator>'
                '</item></rdf:RDF>')
        (post,) = parse_feed_posts(feed, "https://j.example/toc")
        self.assertEqual(post["metadata"]["authors"], ["Ann Lee", "Bo Kim", "Cy Park"])

    def test_the_repair_finds_glued_lines_once(self):
        rows = [("p1", {"authors": ["Ann Lee, Sam B. KimDepartment of Psychology"]}),
                ("p2", {"authors": ["Ann Lee"]}),
                ("p3", {"authors": ["Bo KimDepartment of X"], repair_0137.AUTHORS_MARK: {"from": []}})]
        self.assertEqual(repair_0137.author_fixes(rows),
                         [("p1", ["Ann Lee, Sam B. KimDepartment of Psychology"], ["Ann Lee", "Sam B. Kim"])])
        self.assertEqual(clean_authors(["Ann Lee", 3, "Ann Lee"]), ["Ann Lee"])


# --------------------------------------------------------------------------- B9 undated items


class UndatedTests(unittest.TestCase):
    def test_an_undated_item_is_dated_when_first_seen(self):
        (post,) = parse_feed_posts(rss("Papers", item("A paper", link="https://papers.example/w1", date="")),
                                   "https://papers.example/new.xml")
        self.assertIsNone(post["date"])
        self.assertEqual((post["date_precision"], published_precision(post)), ("seen", "seen"))
        self.assertEqual(published_precision({"date": None}), "none")

    def test_the_pages_own_date_replaces_seen_when_the_page_is_read(self):
        page_date = datetime(2026, 11, 3, 9, 30, tzinfo=timezone.utc)
        read = full_text.with_full_text({"date": None, "date_precision": "seen", "metadata": {}}, "<p>x</p>", "x",
                                        date=page_date)
        self.assertEqual((read["date"], published_precision(read)), (page_date, "exact"))
        self.assertEqual(feed_root("<rss><channel/></rss>").tag, "rss")


if __name__ == "__main__":
    unittest.main()
