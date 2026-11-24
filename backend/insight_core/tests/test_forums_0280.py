"""Forums (0280 D1): one forum reader for Discourse, Flarum and FluxBB — the software told from a forum's page, its
boards offered by the feed finder, a board's threads read as posts (the first message the text) and a thread's
replies read through the discussions mechanism (paged, quotes cut, parents kept), then the jobs pass storing them.
Fixtures: the real answers of discuss.grapheneos.org (Flarum), community.brave.app (Discourse) and bbs.archlinux.org
(FluxBB), 2026-11-24, trimmed (tests/fixtures/forums). The DB test runs on a _test database."""
from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from insight_core.ingestion import discussions as D
from insight_core.ingestion.feed_finder import find_feeds
from insight_core.ingestion.gates import HostLimiter
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds import forum as F
from insight_core.ingestion.where_linked import feed_row
from insight_core.markx import discussions as MD
from insight_core.tests._db import db_url
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_markx_api import _Api

FIX = Path(__file__).resolve().parent / "fixtures" / "forums"

GOS = "https://discuss.grapheneos.org"
BRAVE = "https://community.brave.app"
ARCH = "https://bbs.archlinux.org"


def text(name: str) -> str:
    return (FIX / name).read_text()


def js(name: str):
    return json.loads(text(name))


def run(coro):
    return asyncio.run(coro)


class Software(unittest.TestCase):
    def test_told_from_the_forums_own_pages(self):
        self.assertEqual(F.detect(text("flarum_page.html")), "flarum")
        self.assertEqual(F.detect(text("discourse_page.html")), "discourse")
        self.assertEqual(F.detect(text("fluxbb_index.html")), "fluxbb")
        self.assertIsNone(F.detect("<html><head><title>Forum of a blog</title></head><body>forum</body></html>"))
        self.assertEqual(F.base_of("flarum", text("flarum_page.html"), f"{GOS}/t/announcements"), GOS)
        self.assertEqual(F.base_of("discourse", text("discourse_page.html"), f"{BRAVE}/c/faq/43"), BRAVE)
        self.assertEqual(F.base_of("fluxbb", "", f"{ARCH}/viewforum.php?id=24"), ARCH)
        self.assertEqual(F.forum_name(text("flarum_page.html")), "GrapheneOS Discussion Forum")
        self.assertEqual(F.forum_name(text("fluxbb_index.html")), "Arch Linux Forums")

    def test_board_addresses_by_the_softwares_listing_shapes(self):
        flarum = F.board_of(f"{GOS}/api/discussions?filter[tag]=announcements")
        self.assertEqual((flarum.software, flarum.base, flarum.tag), ("flarum", GOS, "announcements"))
        self.assertEqual(F.board_of(f"{GOS}/api/discussions?filter%5Btag%5D=development").tag, "development")
        self.assertEqual(F.board_of(f"{ARCH}/extern.php?action=feed&type=atom&fid=24").software, "fluxbb")
        self.assertEqual(F.board_of(f"{BRAVE}/c/faq/release-notes/98.rss").base, BRAVE)
        self.assertEqual(F.board_of("https://example.org/forum/latest.rss").base, "https://example.org/forum")
        for no in ("https://example.org/feed.rss", "https://example.org/c/news.rss", f"{ARCH}/extern.php?action=feed&tid=5",
                   f"{GOS}/t/announcements", "ftp://x.org/api/discussions", None, ""):
            self.assertIsNone(F.board_of(no), no)
        # the registry reads a board with the forum kind, any other feed as before
        registry = KindRegistry.default(FakeHttp(), None)
        self.assertEqual(registry.resolve({"platform": "rss", "handle_or_url": f"{BRAVE}/c/faq/43.rss"}).name, "forum")
        self.assertEqual(registry.resolve({"platform": "rss", "handle_or_url": "https://example.org/feed.rss"}).name,
                         "generic_rss")


class Finder(unittest.TestCase):
    def find(self, responses, url):
        http = FakeHttp(responses)
        return run(find_feeds(http, KindRegistry.default(http, None), url)), http

    def test_a_forum_tag_page_offers_its_own_board_first_then_the_forums(self):
        finding, http = self.find({f"{GOS}/t/announcements": text("flarum_page.html"),
                                   f"{GOS}/api/tags": text("flarum_tags.json")}, f"{GOS}/t/announcements")
        self.assertEqual(finding.status, "found")
        self.assertEqual([f.url for f in finding.feeds[:3]], [
            f"{GOS}/api/discussions?filter[tag]=announcements", f"{GOS}/api/discussions",
            f"{GOS}/api/discussions?filter[tag]=general"])
        self.assertEqual(finding.feeds[0].title, "GrapheneOS Discussion Forum: Announcements")
        self.assertEqual({f.forum for f in finding.feeds}, {"flarum"})
        self.assertEqual(len(http.requests), 2)       # the page and its board list: no feed parsed, no guessing
        self.assertEqual(feed_row(finding.feeds[0])["forum"], "flarum")

    def test_discourse_and_fluxbb(self):
        finding, _ = self.find({f"{BRAVE}/c/faq/43": text("discourse_page.html"),
                                f"{BRAVE}/categories.json?include_subcategories=true": text("discourse_categories.json")},
                               f"{BRAVE}/c/faq/43")
        self.assertEqual([f.url for f in finding.feeds[:3]],
                         [f"{BRAVE}/c/faq/43.rss", f"{BRAVE}/latest.rss", f"{BRAVE}/c/support-and-troubleshooting/48.rss"])
        self.assertEqual(finding.feeds[0].title, "Brave Community: Help Center and Resources")
        finding, _ = self.find({f"{ARCH}/viewforum.php?id=24": text("fluxbb_index.html"),
                                f"{ARCH}/index.php": text("fluxbb_index.html")}, f"{ARCH}/viewforum.php?id=24")
        self.assertEqual(finding.feeds[0].url, f"{ARCH}/extern.php?action=feed&type=atom&fid=24")
        self.assertEqual(finding.feeds[2].title, "Arch Linux Forums: Newbie Corner")

    def test_a_board_address_is_read_directly(self):
        finding, http = self.find({}, f"{BRAVE}/c/faq/43.rss")
        self.assertEqual((finding.status, http.requests), ("direct", []))


class Threads(unittest.TestCase):
    def fetch(self, address, responses, limit=30):
        http = FakeHttp(responses)
        return run(F.ForumKind(http).fetch_latest({"platform": "rss", "handle_or_url": address}, limit)), http

    def test_flarum_a_tags_discussions_with_their_first_post(self):
        board = f"{GOS}/api/discussions?filter[tag]=announcements"
        url = F.flarum_url(F.board_of(board), 0, 5)
        posts, http = self.fetch(board, {url: text("flarum_discussions.json")}, 5)
        self.assertIn("sort=-createdAt", http.requests[0])
        self.assertEqual(len(posts), 5)
        p = next(p for p in posts if "2026111800" in p["title"])
        self.assertEqual(p["url"], f"{GOS}/d/43608-grapheneos-version-2026111800-released")
        self.assertTrue(p["content"].startswith("GrapheneOS version 2026111800 released:"))
        self.assertEqual(p["metadata"]["forum"], {"software": "flarum", "thread": "43608", "replies": 31})
        self.assertEqual((p["metadata"]["authors"], p["categories"]), (["GrapheneOS"], ["Announcements"]))
        self.assertEqual(D.post_thread(p["url"], p["metadata"]), D.Thread("flarum", "43608", p["url"]))

    def test_discourse_the_first_post_whole_without_the_trailer(self):
        board = f"{BRAVE}/c/faq/43.rss"
        posts, _ = self.fetch(board, {board: text("discourse_category.rss")})
        self.assertEqual(len(posts), 3)
        for p in posts:
            self.assertNotIn("Read full topic", p["content"])
            self.assertNotIn("participant", p["content_html"][-200:])
            self.assertEqual(p["metadata"]["forum"]["software"], "discourse")
        p = next(p for p in posts if p["title"] == "Refund Request, desperate")
        self.assertEqual(p["metadata"]["forum"], {"software": "discourse", "thread": "661103", "replies": 4})
        self.assertTrue(p["content"].startswith("Hello, the Auto renew got me"))
        self.assertEqual(p["metadata"]["authors"], ["Need2PayRent"])

    def test_fluxbb_read_in_posting_order(self):
        board = f"{ARCH}/extern.php?action=feed&type=atom&fid=24"
        url = f"{ARCH}/extern.php?action=feed&type=atom&fid=24&order=posted&show=30"
        posts, http = self.fetch(board, {url: text("fluxbb_forum.xml")})
        self.assertEqual(http.requests, [url])
        p = posts[0]
        self.assertEqual(p["url"], f"{ARCH}/viewtopic.php?id=311143")
        self.assertTrue(p["content"].startswith("Peter Jung via arch-announce wrote:"))
        self.assertEqual(p["metadata"], {"authors": ["gromit"], "forum": {"software": "fluxbb", "thread": "311143"}})

    def test_a_feed_that_does_not_say_its_software_gets_no_thread(self):
        doc = text("fluxbb_forum.xml").replace("<generator>FluxBB</generator>", "")
        self.assertFalse(any("forum" in p["metadata"] for p in F.fluxbb_posts(doc, ARCH)))
        doc = text("discourse_category.rss").replace("discourse.org", "example.org")
        self.assertFalse(any("forum" in p["metadata"] for p in F.discourse_posts(doc, BRAVE)))


class Replies(unittest.TestCase):
    def read(self, t, answers):
        asked = []

        async def get(url, text=False):
            asked.append((url, text))
            got = answers[url]
            return got if text else json.loads(got)

        return run(D.read(t, get)), asked

    def test_flarum_paged_mentions_are_parents_and_no_text(self):
        t = D.Thread("flarum", "43522", f"{GOS}/d/43522-grapheneos-version-2026111300-released")
        p1, p2 = D._flarum_page(t, 0), D._flarum_page(t, 50)
        parsed, asked = self.read(t, {p1: text("flarum_posts_page1.json"), p2: text("flarum_posts_page2.json")})
        self.assertEqual([u for u, _ in asked], [p1, p2])
        self.assertEqual(len(parsed.comments), 55)             # 56 posts, the first the thread's own text
        self.assertNotIn("1", {c.id for c in parsed.comments})
        replies = [c for c in parsed.comments if c.parent]
        self.assertGreater(len(replies), 20)
        self.assertTrue(all(c.parent in {x.id for x in parsed.comments} for c in replies))
        self.assertEqual(t.name, "discuss.grapheneos.org")
        self.assertEqual(D.comment_url(t, "8"), f"{GOS}/d/43522/8")

    def test_flarum_one_page(self):
        t = D.Thread("flarum", "43608", f"{GOS}/d/43608-grapheneos-version-2026111800-released")
        parsed, asked = self.read(t, {D._flarum_page(t, 0): text("flarum_posts.json")})
        self.assertEqual(len(asked), 1)
        c = next(c for c in parsed.comments if c.id == "3")
        self.assertEqual((c.parent, c.author, c.score), ("2", "Johnnyloans", 5))
        self.assertTrue(c.text.startswith("No, I'm pretty sure AOSP"))   # the mention's name is no text

    def test_discourse_the_rest_by_id_and_reply_numbers(self):
        t = D.Thread("discourse", "661538", f"{BRAVE}/t/app-crashes-upon-launch/661538")
        first = D.requests(t)[0]
        self.assertEqual(first, f"{BRAVE}/t/661538.json")
        topic = js("discourse_topic.json")
        rest = D.more(t, [topic])
        self.assertEqual(rest, f"{BRAVE}/t/661538/posts.json?post_ids%5B%5D=1380155")
        parsed, asked = self.read(t, {first: text("discourse_topic.json"), rest: text("discourse_topic_rest.json")})
        self.assertEqual(len(asked), 2)
        self.assertEqual((parsed.total, len(parsed.comments)), (20, 20))
        c = next(c for c in parsed.comments if c.id == "21")
        self.assertEqual((c.parent, c.author), ("20", "rstrat"))
        self.assertEqual(D.comment_url(t, "21"), f"{BRAVE}/t/661538/21")

    def test_fluxbb_flat_oldest_first_the_topic_post_left_out(self):
        t = D.Thread("fluxbb", "311143", f"{ARCH}/viewtopic.php?id=311143")
        url = D.requests(t)[0]
        parsed, asked = self.read(t, {url: text("fluxbb_topic.xml")})
        self.assertEqual(asked, [(url, True)])
        self.assertEqual(len(parsed.comments), 7)              # 8 entries, the oldest the announcement itself
        self.assertEqual([c.id for c in parsed.comments], sorted((c.id for c in parsed.comments), key=int))
        self.assertTrue(all(c.author and c.at for c in parsed.comments))
        quoted = [c for c in parsed.comments if "Peter Jung via arch-announce wrote" in c.text]
        self.assertEqual(quoted, [])                            # a quote of the announcement is no reply's text
        self.assertEqual(D.comment_url(t, "2279029"), f"{ARCH}/viewtopic.php?pid=2279029#p2279029")

    def test_quotes_are_cut_nested_too(self):
        self.assertEqual(D.plain(D.unquoted('<div class="quotebox"><cite>a wrote:</cite><blockquote><div><blockquote>'
                                            'inner</blockquote>outer</div></blockquote></div><p>Mine.</p>'))[0], "Mine.")
        self.assertEqual(D.plain(D.unquoted('<aside class="quote"><div class="title">x:</div><blockquote>q</blockquote>'
                                            '</aside><p>Reply.</p>'))[0], "Reply.")

    def test_a_forum_thread_is_told_from_its_post_never_its_address(self):
        url = f"{GOS}/d/43608-x"
        self.assertIsNone(D.post_thread(url, {}))
        self.assertIsNone(D.post_thread(url, {"forum": {"software": "hn", "thread": "1"}}))
        self.assertIsNone(D.post_thread(url, {"forum": {"software": "flarum", "thread": "x"}}))
        self.assertEqual(D.floor("bbs.archlinux.org"), D.FORUM_FLOOR)
        self.assertEqual(D.floor("lobste.rs"), 3.0)


class Pass(_Api):
    """The jobs pass on a forum post: wanted, its replies fetched through the paced GETs (a document for FluxBB),
    stored, the view naming the forum's site."""

    def test_a_fluxbb_thread_through_the_pass(self):
        url = f"{ARCH}/viewtopic.php?id=311143"
        pid = self.post(title="NVIDIA 590 driver drops Pascal and lower support / switch to -open")
        self.cur.execute("UPDATE posts SET url = %s, metadata = %s::jsonb WHERE id = %s",
                         (url, json.dumps({"forum": {"software": "fluxbb", "thread": "311143"}}), pid))
        self.assertTrue(MD.want(self.cur, pid))
        feed = D.requests(D.Thread("fluxbb", "311143", url))[0]
        http = FakeHttp({feed: text("fluxbb_topic.xml")})

        async def no_sleep(_s):
            return None

        out = MD.run(db_url(), now=datetime.now(timezone.utc), http=http, limiter=HostLimiter(D.FLOORS, sleep=no_sleep))
        self.assertEqual((out["fetched"], out["failed"], http.requests), (1, 0, [feed]))
        self.cur.execute("SELECT host, kept, total FROM discussion_threads WHERE post_id = %s", (pid,))
        self.assertEqual(self.cur.fetchone(), ("fluxbb", 7, 7))
        v = MD.view(self.cur, pid)
        self.assertEqual((v["status"], v["thread"]["name"]), ("fetched", "bbs.archlinux.org"))


if __name__ == "__main__":
    unittest.main()
