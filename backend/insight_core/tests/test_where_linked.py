"""Follow a site where your sources' links point (issue 0060). No network: FakeHttp.

claude.com's case (2026-10-31): following it from Discover started at the home page and offered
/resources/ (274 articles, guides and webinars too); 95% of the claude.com articles your sources
linked are under /blog/, which redirects to /resources/articles/.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import main
from insight_core.ingestion import where_linked
from insight_core.ingestion.feed_finder import Feed, _feed_items
from insight_core.ingestion.kinds import KindRegistry
from insight_core.services import registry as services_registry
from insight_core.tests._asgi import call
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_feed_finder import page, rss
from insight_core.tests.test_page_watch import article

SITE = "https://lab.example"


def slug(n: int) -> str:
    return f"a-post-about-thing-{n}"


def linked(path: str, count: int, start: int = 0) -> list[str]:
    """count article addresses under path, as post_links keeps them."""
    return [f"{SITE}{path}/{slug(n)}" for n in range(start, start + count)]


def section(path: str, count: int, *, site: str = SITE) -> dict:
    """A listing page of count dated articles (no sitemap), and the articles."""
    links = "".join(f'<a href="{path}/{slug(n)}">Post {n}</a>' for n in range(count))
    return {f"{site}{path}": page(body=f"<main>{links}</main>"),
            **{f"{site}{path}/{slug(n)}": article(f"Post {n}", "2026-10-01T00:00:00Z") for n in range(count)}}


def feed(title: str, links: list[str]) -> str:
    entries = "".join(f"<item><title>{n}</title><link>{url}</link></item>" for n, url in enumerate(links))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>{entries}</channel></rss>'


class FindFeedWithLinks(unittest.TestCase):
    def ask(self, responses, url: str, links: list[str], **fake) -> tuple[dict, FakeHttp]:
        http = FakeHttp(responses, **fake)
        kinds = KindRegistry.default(http, None)
        stories = SimpleNamespace(linked_articles=lambda _address: links)
        self.addCleanup(services_registry.use, services_registry.use(
            SimpleNamespace(source_fetch=SimpleNamespace(kinds=kinds), stories=stories)))
        with mock.patch.object(main, "FEED_FINDER_HTTP", http):
            status, _, body = call(main.app, "POST", "/api/sources/find-feed", json_body={"url": url})
        self.assertEqual(status, 200, body)
        return body, http


class StartWhereTheLinksPoint(FindFeedWithLinks):
    def test_most_links_under_one_section_start_there(self):
        articles = [*linked("/blog", 6), *linked("/news", 3)]           # 6 of 9: 67%
        self.assertEqual(where_linked.start_section(SITE, articles), f"{SITE}/blog")

    def test_under_sixty_percent_starts_at_the_home_page(self):
        articles = [*linked("/blog", 5), *linked("/news", 5)]           # 50%
        self.assertIsNone(where_linked.start_section(SITE, articles))

    def test_a_date_or_a_number_is_no_section(self):
        # A newspaper: its addresses go by date, then desk.
        dated = [f"{SITE}/2026/10/{n:02d}/world/{slug(n)}" for n in range(1, 9)] + [f"{SITE}/{n}/{slug(n)}" for n in range(3)]
        self.assertIsNone(where_linked.start_section(SITE, dated))
        self.assertIsNone(where_linked.start_section(SITE, [f"{SITE}/2026-10-31/{slug(n)}" for n in range(5)]))

    def test_articles_at_the_root_start_at_the_home_page(self):
        self.assertIsNone(where_linked.start_section(SITE, [f"{SITE}/{slug(n)}" for n in range(5)]))

    def test_only_a_home_page_moves_and_only_its_hosts_links_count(self):
        self.assertIsNone(where_linked.start_section(f"{SITE}/news", linked("/blog", 5)))
        other = [f"https://other.example/blog/{slug(n)}" for n in range(5)]
        self.assertEqual(where_linked.on_site(SITE, [*other, *linked("/blog", 1)]), linked("/blog", 1))
        self.assertEqual(where_linked.on_site("https://www.lab.example/", linked("/blog", 2)), linked("/blog", 2))

    def test_the_section_redirects_and_its_articles_moved_with_it(self):
        # /blog lands on /resources/articles/, and so does each /blog/x: one article is asked.
        responses = {f"{SITE}/": page(body='<a href="/resources">Resources</a>'),
                     f"{SITE}/blog/{slug(0)}": "", **section("/resources/articles", 4)}
        responses[f"{SITE}/blog"] = responses[f"{SITE}/resources/articles"]
        redirects = {f"{SITE}/blog": f"{SITE}/resources/articles",
                     f"{SITE}/blog/{slug(0)}": f"{SITE}/resources/articles/{slug(0)}"}
        body, http = self.ask(responses, "lab.example", [*linked("/blog", 19), *linked("/news", 1)], redirects=redirects)
        self.assertEqual((body["status"], body["start"], body["linked"]), ("none", f"{SITE}/blog", 20))
        [offer] = body["pages"]
        self.assertEqual((offer["url"], offer["prefix"], offer["found"], offer["holds"]),
                         (f"{SITE}/resources/articles", "/resources/articles/", 4, 19))
        self.assertEqual(http.requests.count(f"{SITE}/blog/{slug(0)}"), 1, "one article asked where it moved")

    def test_a_feed_in_the_section_is_found_first(self):
        responses = {f"{SITE}/blog": page('<link rel="alternate" type="application/rss+xml" href="/blog/feed">'),
                     f"{SITE}/blog/feed": feed("Lab blog", linked("/blog", 3))}
        body, _ = self.ask(responses, SITE, linked("/blog", 8))
        self.assertEqual((body["status"], body["start"]), ("found", f"{SITE}/blog"))
        self.assertEqual(body["feeds"], [{"url": f"{SITE}/blog/feed", "title": "Lab blog", "holds": 8}])

    def test_the_home_pages_feeds_stand_beside_the_sections(self):
        # scmp.com (2026-10-31): /tech/ holds 63% of the links, and its tech feed 31 of 41; the
        # home page's feed of everything holds 37. Both are shown, the one holding the most first.
        tech = [f"{SITE}/tech/{slug(n)}" for n in range(6)]
        world = [f"{SITE}/news/world/{slug(n)}" for n in range(3)]
        responses = {f"{SITE}/tech": page('<link rel="alternate" type="application/rss+xml" href="/rss/36/feed">'),
                     f"{SITE}/rss/36/feed": feed("Tech", tech[:4]),
                     f"{SITE}/": page('<link rel="alternate" type="application/rss+xml" href="/rss/feed">'),
                     f"{SITE}/rss/feed": feed("Everything", [f"{SITE}/{slug(9)}", world[0], tech[0]])}
        body, _ = self.ask(responses, SITE, [*tech, *world])
        self.assertEqual(body["start"], f"{SITE}/tech")
        self.assertEqual([(f["title"], f["holds"]) for f in body["feeds"]], [("Everything", 9), ("Tech", 6)])

    def test_a_section_that_gives_nothing_falls_back_to_the_home_page(self):
        # /blog cannot be read and names nothing; the home page's news page is offered, as before.
        responses = {f"{SITE}/": page(body='<a href="/news">News</a>'), **section("/news", 3)}
        body, _ = self.ask(responses, SITE, linked("/blog", 5))
        self.assertEqual((body["status"], body["start"], body["homepage"]), ("none", None, True))
        self.assertEqual([(offer["url"], offer["holds"]) for offer in body["pages"]], [(f"{SITE}/news", 0)])

    def test_a_section_with_nothing_to_follow_offers_the_home_pages_pages_without_asking_again(self):
        # /blog is read but builds its list with JavaScript: the home page's "News" is offered,
        # from the home page the finder read beside the section.
        responses = {f"{SITE}/": page(body='<a href="/news">News</a>'), f"{SITE}/blog": page(body="<div id=root></div>"),
                     **section("/news", 3)}
        body, http = self.ask(responses, SITE, linked("/blog", 5))
        self.assertEqual((body["start"], [offer["url"] for offer in body["pages"]]), (None, [f"{SITE}/news"]))
        self.assertEqual(http.requests.count(f"{SITE}/"), 1, "the home page is read once")

    def test_a_section_that_lands_on_the_home_page_is_no_section(self):
        # /share sends you home: the home page's own pages are offered, as before.
        responses = {f"{SITE}/": page(body='<a href="/news">News</a>'), f"{SITE}/share": page(body='<a href="/news">News</a>'),
                     **section("/news", 3)}
        body, _ = self.ask(responses, SITE, linked("/share", 5), redirects={f"{SITE}/share": f"{SITE}/"})
        self.assertEqual((body["start"], [offer["url"] for offer in body["pages"]]), (None, [f"{SITE}/news"]))


class RankByCoverage(FindFeedWithLinks):
    def test_a_feed_holds_its_items_and_the_section_they_share(self):
        items = linked("/blog", 2)
        self.assertEqual(where_linked.feed_place(items), ("lab.example", "/blog/"))
        articles = [*linked("/blog", 5), *linked("/news", 2), f"{SITE}/other/{slug(1)}"]
        self.assertEqual(where_linked.holds(articles, place=where_linked.feed_place(items), items=items), 5)
        # A feed of a dated site holds its dated articles, whatever the date, not the rest of its host.
        dated = [f"{SITE}/2026/10/{slug(1)}", f"{SITE}/2025/01/{slug(2)}"]
        self.assertEqual(where_linked.feed_place(dated), ("lab.example", "/"))
        others = [f"{SITE}/2019/03/04/world/{slug(3)}", f"{SITE}/pricing/{slug(4)}", f"{SITE}/{slug(5)}"]
        self.assertEqual(where_linked.holds(others, place=where_linked.feed_place(dated), items=dated), 1)
        # One whose items share nothing, its items only.
        news = [f"{SITE}/news/{slug(1)}"]
        self.assertEqual(where_linked.holds([*news, *linked("/blog", 3)], items=news), 1)

    def test_a_section_holds_the_articles_under_its_path_on_its_host(self):
        offer = {"url": f"{SITE}/blog", "prefix": "/blog/", "items": [{"url": f"{SITE}/blog/{slug(0)}"}]}
        place = where_linked.page_place(offer)
        articles = [*linked("/blog", 4), *linked("/blogs", 2), f"https://other.example/blog/{slug(1)}"]
        self.assertEqual(where_linked.holds(articles, place=place), 4)

    def test_a_moved_section_is_read_at_its_new_address(self):
        move = where_linked.moved(f"{SITE}/blog/{slug(0)}", f"https://www.lab.example/resources/articles/{slug(0)}")
        self.assertEqual(move, (("lab.example", "/blog/"), ("lab.example", "/resources/articles/")))
        self.assertEqual(where_linked.holds(linked("/blog", 3), place=("lab.example", "/resources/articles/"), move=move), 3)
        # Landing on another page (a home page, a sign-in) says nothing about where it moved.
        self.assertIsNone(where_linked.moved(f"{SITE}/blog/{slug(0)}", f"{SITE}/"))
        self.assertIsNone(where_linked.moved(f"{SITE}/blog/{slug(0)}", f"{SITE}/blog/{slug(0)}"))

    def test_the_most_held_first_and_the_narrower_path_wins_a_tie(self):
        articles = linked("/resources/articles", 5)
        wide = {"url": f"{SITE}/resources", "prefix": "/resources/", "found": 400, "items": []}
        narrow = {"url": f"{SITE}/resources/articles", "prefix": "/resources/articles/", "found": 270, "items": []}
        other = {"url": f"{SITE}/news", "prefix": "/news/", "found": 900, "items": []}
        _, pages = where_linked.rank(articles, [], [other, wide, narrow])
        self.assertEqual([(p["prefix"], p["holds"]) for p in pages],
                         [("/resources/articles/", 5), ("/resources/", 5), ("/news/", 0)])

    def test_a_typed_address_ranks_its_feeds_when_its_site_was_linked(self):
        # A section typed in: its feeds, the one holding the most linked articles first.
        responses = {f"{SITE}/writing": page('<link rel="alternate" type="application/rss+xml" href="/podcast.xml">'
                                             '<link rel="alternate" type="application/rss+xml" href="/writing/feed">'),
                     f"{SITE}/podcast.xml": feed("Podcast", linked("/podcast", 2)),
                     f"{SITE}/writing/feed": feed("Writing", linked("/writing", 2))}
        body, _ = self.ask(responses, f"{SITE}/writing", [*linked("/writing", 4), *linked("/podcast", 1)])
        self.assertEqual((body["start"], body["linked"]), (None, 5))
        self.assertEqual([(f["title"], f["holds"]) for f in body["feeds"]], [("Writing", 4), ("Podcast", 1)])

    def test_a_site_with_no_links_is_found_as_before(self):
        responses = {f"{SITE}/": page(body='<a href="/press">Press</a><a href="/news">News</a>'),
                     **section("/press", 2), **section("/news", 4)}
        body, _ = self.ask(responses, SITE, [])
        self.assertEqual((body["start"], body["linked"]), (None, 0))
        self.assertEqual([(offer["url"], offer["found"]) for offer in body["pages"]], [(f"{SITE}/news", 4), (f"{SITE}/press", 2)])
        self.assertNotIn("holds", body["pages"][0])


class FeedItemsTests(unittest.TestCase):
    def test_rss_and_atom_item_addresses_are_read(self):
        self.assertEqual(_feed_items(rss("X", items=2).encode(), "https://x.example/feed"),
                         ("https://x.example/0", "https://x.example/1"))
        atom = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>'
                '<link href="https://a.example/"/><entry><title>One</title><link rel="replies" href="/c"/>'
                '<link href="/posts/one"/></entry><entry><id>2</id><link rel="alternate" href="https://a.example/posts/two"/>')
        self.assertEqual(_feed_items(atom.encode(), "https://a.example/feed"),
                         ("https://a.example/posts/one",), "a cut entry is left out")
        guid = '<rss><channel><title>G</title><item><guid>https://g.example/p/1</guid></item></channel></rss>'
        self.assertEqual(_feed_items(guid.encode(), "https://g.example/feed"), ("https://g.example/p/1",))

    def test_a_found_feed_carries_its_items_but_compares_by_address(self):
        self.assertEqual(Feed("u", "t", ("a",)), Feed("u", "t"))


if __name__ == "__main__":
    unittest.main()
