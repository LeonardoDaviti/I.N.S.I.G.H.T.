"""Discover from the server's review (issue 0109 A): the order (the tested followable first, then the untested,
the ones that can't be followed in a section of their own, never below the untested), a followed source's other
channels, what isn't a source, one card per owner domain, archive rows by pages, read titles that are the
site's name, "feed found" only for a feed of the linked pages, and voices named once. Neutral names only.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_discover import READS_KEY, DiscoverRepository
from insight_core.services import discover_reads, page_titles
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils import discover_rules

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def card(key, score, label=None):
    s = {"key": key, "score": score, "articles": []}
    if label:
        s["follow_test"] = {"label": label, "at": NOW.isoformat()}
    return s


class OrderTests(unittest.TestCase):
    """W2: an unfollowable suggestion sank below every untested one (the top score at #1254 of 1,275)."""

    def test_tested_followable_first_then_untested_and_the_unfollowable_apart(self):
        found = [card("walled.example", 13.0, "blocked"), card("untested.example", 4.0), card("feed.example", 3.0, "feed"),
                 card("hubowner.example", 1.0, "other_feed"),
                 card("paid.example", 9.0, "headlines"), card("page.example", 2.0, "page"), card("new.example", 6.0)]
        got = discover_rules.order(found)
        self.assertEqual([s["key"] for s in got], ["feed.example", "page.example", "walled.example", "paid.example",
                                                   "hubowner.example", "new.example", "untested.example"],
                         "the section in score order, never below an untested one")
        self.assertEqual([s["key"] for s in got if s.get("section") == "unfollowable"],
                         ["walled.example", "paid.example", "hubowner.example"], "a feed, but not of these pages: can't be followed as one")

    def test_the_reads_test_what_ranks_first_by_score_wherever_it_is_listed(self):
        listed = [card(f"low{k}.example", 1.0, "feed") for k in range(3)] + [card("high.example", 9.0), card("lower.example", 0.5)]
        reads = {"follow": {s["key"]: {**s["follow_test"], "test": discover_reads.FOLLOW_TEST}
                            for s in listed if s.get("follow_test")}}
        page = discover_reads.to_read({"suggestions": listed}, first_page=3)
        got = discover_reads.work(page, reads, NOW)
        self.assertEqual(got["follow"], ["high.example"], "the untested by score among the first page's count")


class OtherChannelTests(unittest.TestCase):
    """W3 A: a suggestion a followed source links, under a name of that source, is its other channel (measured
    on the server's pairs: 21 of 23 right by the review's rule)."""

    def names(self, name, account="", publication="", shared=frozenset()):
        return discover_rules.own_names(name, account=account, publication=publication, shared_sites=shared)

    def test_a_sources_names(self):
        self.assertEqual(self.names("Quiet Codex Weekly", publication="quietcodex.example"),
                         {"quietcodex", "quiet", "codex", "weekly", "quietcodexweekly"})
        self.assertEqual(self.names("https://research.lumen.example/feed", publication="research.lumen.example"), {"lumen"},
                         "an address as a name: its site's word only, never a path's or a section host's")
        self.assertEqual(self.names("Notes", publication="writer.hosted.example", shared={"hosted.example"}), {"writer", "notes"},
                         "on a host of many writers, the writer's own label")
        self.assertEqual(self.names("someone", account="x.com/someone"), {"someone"})
        self.assertEqual(self.names("AI Blog News", publication="ai.example"), set(), "short and generic words name no one")

    def test_the_same_owner_by_a_name_its_key_starts_or_ends_with(self):
        same = discover_rules.same_owner
        self.assertTrue(same("oldcodex.example", {"codex"}), "a moved blog's old name")
        self.assertTrue(same("x.com/janedoe_ai", {"jane"}))
        self.assertTrue(same("x.com/labsupdates", {"labs"}))
        self.assertTrue(same("hub.example/lumen-models", {"lumen"}))
        self.assertTrue(same("news.lumen.example", {"lumen"}), "a site by its registrable word")
        self.assertFalse(same("geoscienceworld.example", {"science"}), "a word inside another is no name")
        self.assertFalse(same("cloud.other.example", {"cloud"}), "a subdomain's word is no owner's")
        self.assertFalse(same("x.com/someoneelse", set()))


class NotSourcesTests(unittest.TestCase):
    """W4: archives and CDNs, apps' shared chats, document and data hosts, paper pages, and a creators'
    platform as one site, told by the address's shape (each measured on the server's suggestions)."""

    def kind(self, key, *paths):
        return discover_rules.place_kind(key, [f"https://{key}{p}" for p in paths])

    def test_another_sites_page_or_a_file_is_an_archive(self):
        self.assertEqual(self.kind("archive.example", "/web/20010926223602/https:/news.example/2001/a.html",
                                   "/2024/http:/other.example/b"), "archive")
        self.assertEqual(self.kind("cdn.example", "/image/fetch/f_auto/https%3A%2F%2Fhost.example%2Fa.png",
                                   "/img/b.jpg"), "archive")

    def test_an_apps_shared_chats_are_no_publication(self):
        self.assertEqual(self.kind("chat.example", "/share/68dd6833-67c4-8007-8f37-331eb5bd9ee0",
                                   "/c/2585c187b059475ab4fbdd09d0278e18"), "app")
        self.assertIsNone(self.kind("paper.example", "/content/5ee49718-c258-4f01-aa32-7e5b76ae5245",
                                    "/content/11632d03-358c-454b-af95-d06d4072932b"),
                          "a newspaper's articles by id are articles: only a share-like page before the id")

    def test_documents_and_data_are_references(self):
        self.assertEqual(self.kind("register.example", "/documents/2022/10/13/2022-21658/a-rule",
                                   "/documents/2023/11/01/2023-24283/another"), "document")
        self.assertEqual(self.kind("stats.example", "/statistics/1105798/spending", "/statistics/1351276/wages"), "document")

    def test_paper_pages_by_their_id_or_a_paper_path(self):
        self.assertEqual(self.kind("proceedings.example", "/paper/2011/hash/5dd9db5e033da9c6fb5ba83c7a7ebea9-Abstract.html",
                                   "/paper/4824-a-title"), "paper")
        self.assertEqual(self.kind("journal.example", "/doi/10.1145/3442188.3445922", "/doi/full/10.1145/1234.5678"), "paper")
        self.assertIsNone(self.kind("news.example", "/2026/10/a-story", "/tech/another-story"))

    def test_a_host_of_owners_by_their_marked_paths_is_a_platform(self):
        rows = discover_rules.platform_rows([(f"v{k}", f"https://creators.example/{owner}/posts/{k}a1b2c3d4")
                                             for k, owner in enumerate(("ann", "bob", "cy", "ann"))])
        marked = discover_rules.MARKED_OWNERS
        self.assertEqual(discover_rules.find_platforms(rows), {"creators.example": marked})
        rows = discover_rules.platform_rows([(f"v{k}", f"https://social.example/@{owner}/{k}")
                                             for k, owner in enumerate(("ann", "bob", "ann"))])
        self.assertEqual(discover_rules.find_platforms(rows), {"social.example": marked})
        key = discover_rules.platform_key
        self.assertEqual(key("https://social.example/@ann/123", marked), "social.example/@ann")
        self.assertEqual(key("https://creators.example/bob/posts/a1b2", marked), "creators.example/bob")
        self.assertIsNone(key("https://social.example/redirect/2/abc", marked),
                          "on a platform of marked owners, an unmarked page names none (a redirect)")
        rows = discover_rules.platform_rows([(f"v{k}", f"https://one.example/ann/posts/{k}") for k in range(4)])
        self.assertEqual(discover_rules.find_platforms(rows), {}, "one owner: a site")
        rows = discover_rules.platform_rows([(f"v{k}", f"https://news.example/{section}/2026/story-{k}")
                                             for k, section in enumerate(("tech", "world", "science"))])
        self.assertEqual(discover_rules.find_platforms(rows), {}, "sections aren't owners")


class OneCardPerDomainTests(unittest.TestCase):
    """W5: one owner's hosts on one registrable domain were several cards (23 owners in 54 on the server)."""

    def suggestion(self, key, score, voices, *, origins=0, articles=()):
        return {"key": key, "url": "https://" + key, "score": score, "voices": len(voices), "voice_names": list(voices),
                "article_count": len(articles), "link_count": len(articles), "classics": 0, "opened": 0, "origins": origins,
                "articles": [{"url": u, "title": None, "linked_by": ["a"]} for u in articles],
                "origin_stories": [{"url": u, "title": None, "voices": 2, "stored": False} for u in articles[:origins]]}

    def test_a_domains_hosts_are_one_card_led_by_the_best(self):
        found = [self.suggestion("lab.example", 3.0, ["a", "b", "c"], articles=["https://lab.example/a"]),
                 self.suggestion("newsletter.lab.example", 5.0, ["b", "c", "d"], origins=1, articles=["https://newsletter.lab.example/p/x"]),
                 self.suggestion("other.example", 4.0, ["a", "b", "c"]),
                 self.suggestion("hub.example/lab", 6.0, ["a", "b", "c"])]
        got = {s["key"]: s for s in discover_rules.one_card_per_domain(found, federations=set())}
        self.assertEqual(sorted(got), ["hub.example/lab", "newsletter.lab.example", "other.example"])
        card = got["newsletter.lab.example"]
        self.assertEqual(card["places"], ["newsletter.lab.example", "lab.example"])
        self.assertEqual((card["voices"], card["origins"], card["article_count"]), (4, 1, 2))
        self.assertEqual(sorted(a["url"] for a in card["articles"]), ["https://lab.example/a", "https://newsletter.lab.example/p/x"])
        self.assertGreaterEqual(card["score"], 5.0)
        self.assertNotIn("places", got["other.example"], "a card of one host names no places")

    def test_a_domain_of_many_owners_keeps_its_cards(self):
        found = [self.suggestion("ann.blogs.example", 3.0, ["a"]), self.suggestion("bob.blogs.example", 2.0, ["b"])]
        got = discover_rules.one_card_per_domain(found, federations={"blogs.example"})
        self.assertEqual([s["key"] for s in got], ["ann.blogs.example", "bob.blogs.example"])

    def test_a_federation_by_its_many_thinly_linked_hosts(self):
        self.assertTrue(discover_rules.federation(hosts=51, posts=100), "a blog host: 51 hosts, 2 posts each")
        self.assertTrue(discover_rules.federation(hosts=47, posts=167), "a school's units")
        self.assertFalse(discover_rules.federation(hosts=49, posts=758), "a company's products: many posts a host")
        self.assertFalse(discover_rules.federation(hosts=4, posts=8), "few hosts: one owner")


class SiteNameTitleTests(unittest.TestCase):
    """W7: a read title that is the site's own name ("The Wall Street Journal" on 5 of its articles) is no title."""

    def test_a_page_whose_title_is_its_sites_name(self):
        page = ('<html><head><meta property="og:site_name" content="The Daily Example">'
                '<title>The Daily Example</title></head></html>')
        self.assertIsNone(discover_reads.page_title(page, "https://daily.example/2026/a"))
        page = ('<html><head><meta property="og:site_name" content="The Daily Example">'
                '<title>A real headline - The Daily Example</title></head></html>')
        self.assertEqual(discover_reads.page_title(page, "https://daily.example/2026/a"), "A real headline")

    def test_a_read_title_two_pages_of_a_host_share_is_no_title(self):
        reads = {"https://daily.example/a": {"title": "The Daily Example"}, "https://www.daily.example/b": {"title": "The Daily Example"},
                 "https://daily.example/c": {"title": "One headline"}, "https://other.example/d": {"title": "The Daily Example"}}
        shared = page_titles.shared_titles(reads)
        self.assertIsNone(page_titles.read(reads, "https://daily.example/a", shared))
        self.assertEqual(page_titles.read(reads, "https://daily.example/c", shared), "One headline")
        self.assertEqual(page_titles.read(reads, "https://other.example/d", shared), "The Daily Example", "one page of its host")


class VoiceTests(unittest.TestCase):
    """W10, W11: an owner named twice in one card; an organisation's handle read as a language code."""

    def test_a_language_segment_is_the_first_part_and_a_language(self):
        self.assertTrue(discover_rules.language_segment("en"))
        self.assertTrue(discover_rules.language_segment("ru-RU"))
        self.assertTrue(discover_rules.language_segment("zh-hant"))
        self.assertFalse(discover_rules.language_segment("ai-sage"), "no language is 'ai', and 'sage' no script")
        self.assertFalse(discover_rules.language_segment("hf"))

    def test_an_owner_whose_handle_looks_like_a_language_tag(self):
        self.assertEqual(discover_rules.platform_key("https://hub.example/ai-sage/a-model", ()), "hub.example/ai-sage")
        self.assertIsNone(discover_rules.platform_key("https://hub.example/en/a-model", ()), "a language first is no owner")
        self.assertIsNone(discover_rules.platform_key("https://store.example/dp/B0123/", ()), "two letters name no owner")
        self.assertEqual(discover_rules.platform_key("https://forum.example/ru/companies/en-garde/blog/1", ("ru", "companies")),
                         "forum.example/ru/companies/en-garde", "past the first part, a language-like handle is an owner")

    def test_the_address_rules_stamp_holds_an_owner_on_a_platform(self):
        self.assertIn("hub.example/ai-sage", repr(discover_rules.platform_sample()))


@requires_test_db
class DiscoverServiceTests(unittest.TestCase):
    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.cur.execute("SELECT value FROM system_settings WHERE key = %s", (READS_KEY,))
        row = self.cur.fetchone()
        self.addCleanup(self._clean, row[0] if row else None)

    def _clean(self, reads):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%{self.mark}%",))
        if reads is None:
            self.cur.execute("DELETE FROM system_settings WHERE key = %s", (READS_KEY,))
        else:
            DiscoverRepository.keep_reads(self.cur, reads)
        self.conn.commit()
        self.conn.close()

    def _voice(self, n, *, name=None, handle=None):
        source = insert_source(self.cur, name or f"Voice {n}", handle=handle)   # no mark: a name a key could hold
        return source, f"voice{n}-{self.mark}.example"

    def _post(self, voice, links):
        source, host = voice
        url = f"https://{host}/p/{uuid.uuid4().hex}"
        insert_post(self.cur, source, url, host=host, normalized=url, links=list(links))

    def _linked(self, host, voices, n=2):
        pages = [f"https://{host}/2026/10/story-{k}" for k in range(n)]
        for voice in voices:
            self._post(voice, pages)
        return pages

    def _tested(self, labels):
        reads = DiscoverRepository.reads(self.cur)
        reads["follow"] = {**reads.get("follow", {}),
                           **{key: {"label": label, "at": NOW.isoformat(), "test": discover_reads.FOLLOW_TEST}
                              for key, label in labels.items()}}
        DiscoverRepository.keep_reads(self.cur, reads)

    def _discover(self, **page):
        self.conn.commit()
        return StoriesService(db_url(), clock=lambda: NOW).discover(q=self.mark, **page)

    def test_an_unfollowable_suggestion_is_in_its_own_section_not_last(self):
        voices = [self._voice(n) for n in range(6)]
        walled, quiet, fed = (f"{name}-{self.mark}.example" for name in ("walled", "quiet", "fed"))
        self._linked(walled, voices)
        self._linked(quiet, voices[:3])
        self._linked(fed, voices[:3])
        self._tested({walled: "blocked", fed: "feed"})
        got = self._discover()["suggestions"]
        self.assertEqual([s["key"] for s in got], [fed, walled, quiet], "below the followable, above the untested")
        self.assertEqual([s.get("section") for s in got], [None, "unfollowable", None])

    def test_an_archive_and_a_document_host_are_no_suggestions(self):
        voices = [self._voice(n) for n in range(3)]
        archive, register = f"archive-{self.mark}.example", f"register-{self.mark}.example"
        for voice in voices:
            self._post(voice, [f"https://{archive}/web/2001092622360{k}/https:/news.example/2001/{k}.html" for k in range(2)])
            self._post(voice, [f"https://{register}/documents/2022/10/1{k}/2022-2165{k}/a-rule" for k in range(2)])
        got = self._discover()
        keys = [s["key"] for s in got["suggestions"]]
        self.assertNotIn(archive, keys)
        self.assertNotIn(register, keys)
        self.assertIn(register, [r["key"] for r in got["references"]], "a document host is a reference")
        self.assertNotIn(archive, [r["key"] for r in got["references"]])

    def test_one_card_for_a_publishers_hosts(self):
        voices = [self._voice(n) for n in range(4)]
        main, letter = f"pub-{self.mark}.example", f"newsletter.pub-{self.mark}.example"
        self._linked(main, voices[:3])
        self._linked(letter, voices, n=3)   # more sources: it leads
        [card] = [s for s in self._discover()["suggestions"] if s["key"] in (main, letter)]
        self.assertEqual(sorted(card["places"]), sorted([letter, main]))
        self.assertEqual(card["places"][0], card["key"], "led by its best")
        self.assertEqual((card["article_count"], card["voices"]), (5, 4))

    def test_classics_read_no_title_a_hosts_pages_share(self):
        m = self.mark
        urls = [f"https://wall-{m}.example/articles/{k}" for k in range(2)]
        reads = DiscoverRepository.reads(self.cur)
        reads["titles"] = {**reads.get("titles", {}), urls[0]: {"title": "The Wall", "at": NOW.isoformat()},
                           urls[1]: {"title": "The Wall", "at": NOW.isoformat()},
                           f"https://wall-{m}.example/x": {"title": "A headline", "at": NOW.isoformat()}}
        DiscoverRepository.keep_reads(self.cur, reads)
        self.assertEqual(DiscoverRepository.read_titles(self.cur, [*urls, f"https://wall-{m}.example/x"]),
                         {f"https://wall-{m}.example/x": "A headline"})

    def test_one_owner_is_named_once(self):
        twins = [self._voice(0, name="samename"), self._voice(1, name="samename")]
        others = [self._voice(n) for n in (2, 3)]
        site = f"named-{self.mark}.example"
        self._linked(site, twins + others)
        [got] = [s for s in self._discover()["suggestions"] if s["key"] == site]
        self.assertEqual(sorted(got["voice_names"]), ["Voice 2", "Voice 3", "samename"])
        self.assertEqual(got["voices"], 3, "two sources of one name are one voice in 'linked by N'")
        self.assertEqual(sorted(got["articles"][0]["linked_by"]), ["Voice 2", "Voice 3", "samename"])

    def test_a_followed_sources_other_channel_is_folded_under_it(self):
        writer = insert_source(self.cur, "Lumen Notes", handle=f"https://lumen{self.mark}.example/feed.xml")
        own = (writer, f"lumen{self.mark}.example")
        others = [self._voice(n) for n in range(2)]
        account = f"x.com/lumen{self.mark}_ai"
        tweets = [f"https://x.com/lumen{self.mark}_ai/status/20{k}0000000000000000" for k in range(2)]
        for voice in (own, *others):
            self._post(voice, tweets)
        stranger = f"x.com/someone{self.mark}"
        for voice in (own, *others):
            self._post(voice, [f"https://x.com/someone{self.mark}/status/20{k}1111111111111111" for k in range(2)])
        got = self._discover()
        self.assertNotIn(account, [s["key"] for s in got["suggestions"]])
        self.assertIn(stranger, [s["key"] for s in got["suggestions"]], "a name the source doesn't hold: a suggestion")
        [also] = [a for a in got["also"] if a["key"] == account]
        self.assertEqual((also["of"], also["source_id"]), ("Lumen Notes", writer))


if __name__ == "__main__":
    unittest.main()
