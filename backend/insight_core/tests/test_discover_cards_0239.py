"""Discover's cards and ranking (0239), on invented names: a company's card is led by its announcing section; a
publishing platform's hosts are sites of their own; a video is its channel's; a repository 2+ voices link is suggested
as its releases feed; the reader-fit term (a switch, off) moves rows linked by sources you read above broad ones.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_discover import DiscoverRepository
from insight_core.ingestion.http import HttpError
from insight_core.markx import source_judge
from insight_core.services import discover_reads
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils import discover_rules as R
from insight_core.utils.discover_rules import Origin

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def row(key, score, voices, *, url=None, **extra):
    return {"key": key, "url": url or "https://" + key, "score": score, "voices": len(voices), "voice_names": list(voices),
            "article_count": 1, "link_count": 1, "classics": 0, "opened": 0, "origins": 0,
            "articles": [{"url": f"https://{key}/a", "title": None, "linked_by": list(voices)}], **extra}


class CardLead(unittest.TestCase):
    """An invented company whose IR host has the most links, whose newsroom host is one of its places."""

    def test_the_newsroom_leads_the_card_and_is_what_the_judge_reads(self):
        found = [row("ir.acme.example", 6.0, ["a", "b", "c", "d"]), row("acme.example", 4.0, ["a", "e"]),
                 row("newsroom.acme.example", 2.0, ["f"])]
        [card] = R.one_card_per_domain(found)
        self.assertEqual(card["key"], "newsroom.acme.example")
        self.assertEqual(card["places"], ["newsroom.acme.example", "ir.acme.example", "acme.example"])
        self.assertEqual(card["url"], "https://newsroom.acme.example")
        self.assertGreaterEqual(card["score"], 6.0, "the card keeps its best place's score")
        self.assertEqual(card["voices"], 6)
        self.assertEqual(source_judge.to_judge([card], [], 15), ["newsroom.acme.example"])

    def test_a_section_its_follow_test_found_announces_by_its_path(self):
        found = [row("ir.acme.example", 6.0, ["a"]), row("acme.example", 4.0, ["b"], url="https://acme.example/en/newsroom/")]
        self.assertEqual(R.one_card_per_domain(found)[0]["key"], "acme.example")

    def test_the_site_itself_the_best_keeps_the_lead(self):
        """A publisher's own host with the most links leads its card over its old blogs. host (0248)."""
        found = [row("press.example", 9.0, ["a", "b", "c"]), row("blogs.press.example", 2.0, ["d"])]
        [card] = R.one_card_per_domain(found)
        self.assertEqual(card["key"], "press.example")
        self.assertEqual(card["places"], ["press.example", "blogs.press.example"])

    def test_without_an_announcing_place_the_best_leads_as_before(self):
        found = [row("ir.acme.example", 6.0, ["a"]), row("acme.example", 4.0, ["b"]), row("shop.acme.example", 5.0, ["c"])]
        self.assertEqual(R.one_card_per_domain(found)[0]["places"], ["ir.acme.example", "shop.acme.example", "acme.example"])

    def test_the_rule_is_official_channels_one(self):
        self.assertTrue(R.announcing_place({"key": "blog.acme.example"}))
        self.assertTrue(R.announcing_place({"key": "press.acme.co.uk"}))
        self.assertFalse(R.announcing_place({"key": "acme.example"}), "a site's own name is no section")
        self.assertFalse(R.announcing_place({"key": "newsroom.example"}), "nor is a site called so")
        self.assertFalse(R.announcing_place({"key": "investors.acme.example"}))


class PublicationSites(unittest.TestCase):
    """On a publishing platform, each host is a site of its own."""

    PUBS = {"letters.example"}

    def test_one_newsletter_followed_hides_no_other(self):
        followed = {"one.letters.example"}
        open_ = lambda key, pubs: R.discover_open(key, R.site_of(key), False, followed=followed, hidden=set(),  # noqa: E731
                                                  followed_accounts=set(), publication_sites=pubs)
        self.assertTrue(open_("two.letters.example", self.PUBS))
        self.assertFalse(open_("one.letters.example", self.PUBS))
        self.assertFalse(R.discover_open("two.letters.example", "letters.example", False, followed={"letters.example"},
                                         hidden=set(), followed_accounts=set()), "elsewhere, as before: the site")
        self.assertEqual(R.site_unit("www.Two.letters.example/p/x", self.PUBS), "two.letters.example")
        self.assertEqual(R.site_unit("blog.company.example", self.PUBS), "company.example")

    def test_the_fold_keeps_publications_apart(self):
        found = [row("one.letters.example", 3.0, ["a"]), row("two.letters.example", 2.0, ["b"])]
        self.assertEqual(len(R.one_card_per_domain(found, federations=self.PUBS)), 2)

    def test_a_story_on_another_publication_is_suggested(self):
        def root(url):
            return Origin("s-" + url, url, None, None, NOW, voices={"v1": "x", "v2": "y"})
        got = R.origins([root("https://two.letters.example/p/news"), root("https://one.letters.example/p/mine")],
                        followed={"one.letters.example"}, held={}, publication_sites=self.PUBS)
        self.assertEqual(sorted(got.suggest), ["two.letters.example"])
        self.assertEqual(sorted(R.origins([root("https://two.letters.example/p/news")], followed={"letters.example"},
                                          held={}).suggest), [], "elsewhere a followed site's page is never suggested")


class Videos(unittest.TestCase):
    VIDEO = "https://youtube.com/watch?v=abcDEF12345"

    def test_a_video_read_is_its_channels(self):
        self.assertEqual(R.discover_address(self.VIDEO), (None, "youtube.com", True), "unread: no account")
        self.assertEqual(R.discover_address(self.VIDEO, channels={self.VIDEO: "youtube.com/@makerchannel"}),
                         ("youtube.com/@makerchannel", "youtube.com", True))
        self.assertEqual(R.discover_place(self.VIDEO, channels={self.VIDEO: "youtube.com/@makerchannel"}),
                         "youtube.com/@makerchannel")

    def test_oembed_names_the_channel(self):
        self.assertEqual(discover_reads.channel_key("https://www.youtube.com/@MakerChannel"), "youtube.com/@makerchannel")
        self.assertIsNone(discover_reads.channel_key("https://maker.example/"))

        class Polite:
            asked = []

            async def get_text(self, url):
                self.asked.append(url)
                if "bad" in url:
                    raise HttpError("gone", status=404)
                return json.dumps({"author_url": "https://www.youtube.com/@MakerChannel", "title": "A talk"}), {}
        polite = Polite()
        self.assertEqual(asyncio.run(discover_reads.read_video(polite, self.VIDEO)), {"channel": "youtube.com/@makerchannel"})
        self.assertIn("url=https%3A%2F%2Fyoutube.com%2Fwatch%3Fv%3DabcDEF12345", polite.asked[0])
        self.assertEqual(asyncio.run(discover_reads.read_video(polite, self.VIDEO + "bad")), {"channel": None})

    def test_the_most_linked_videos_first_bounded_a_found_channel_never_again(self):
        linked = [(f"https://youtube.com/watch?v=v{k}", 10 - k) for k in range(10)]
        reads = {"videos": {"https://youtube.com/watch?v=v0": {"channel": "youtube.com/@c", "at": NOW.isoformat()},
                            "https://youtube.com/watch?v=v1": {"channel": None, "at": NOW.isoformat()},
                            "https://youtube.com/watch?v=v2": {"channel": None,
                                                               "at": (NOW - timedelta(days=40)).isoformat()}}}
        self.assertEqual(discover_reads.videos_due(linked, reads, NOW, limit=3),
                         ["https://youtube.com/watch?v=v2", "https://youtube.com/watch?v=v3",
                          "https://youtube.com/watch?v=v4"])


class Order(unittest.TestCase):
    """The reader-fit term, behind INSIGHT_DISCOVER_READER_FIT (off)."""

    def rows(self):
        return [row("broad.example", 5.0, list("abcdefgh"), reader_fit=0.1),
                row("primary.example", 4.0, list("abc"), reader_fit=0.6),
                row("judged.example", 3.0, list("ab"), fit="maybe", reader_fit=1.0)]

    def test_off_the_order_is_by_score(self):
        with mock.patch.dict("os.environ", {"INSIGHT_DISCOVER_READER_FIT": "0"}):
            self.assertEqual([s["key"] for s in R.order(self.rows())], ["broad.example", "primary.example", "judged.example"])

    def test_on_an_unjudged_row_your_sources_read_climbs_a_judged_one_keeps_its_score(self):
        with mock.patch.dict("os.environ", {"INSIGHT_DISCOVER_READER_FIT": "1"}):
            self.assertEqual([s["key"] for s in R.order(self.rows())], ["primary.example", "broad.example", "judged.example"])
        self.assertEqual(R.fit_score(self.rows()[2], on=True), 3.0)
        self.assertAlmostEqual(R.fit_score(self.rows()[1], on=True), 6.4)

    def test_the_share_of_linking_sources_you_read(self):
        self.assertEqual(R.reader_fit({"s1", "s2", "s3", "s4"}, {"s1", "s9"}), 0.25)
        self.assertEqual(R.reader_fit(set(), {"s1"}), 0.0)


@requires_test_db
class EndToEnd(unittest.TestCase):
    """Videos, repositories and a platform's publications through Discover's whole list on the test database."""

    def setUp(self):
        self.m = uuid.uuid4().hex[:8]
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.cur.execute("SELECT value FROM system_settings WHERE key = 'discover_reads'")
        got = self.cur.fetchone()
        self.reads_before = got[0] if got else None
        self.addCleanup(self._clean)
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM system_settings WHERE key IN ('discover_counts', 'discover_list', 'discover_served')")
        self.conn.commit()

    def _clean(self):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%{self.m}%",))
        self.cur.execute("DELETE FROM system_settings WHERE key IN ('discover_counts', 'discover_list', 'discover_served')")
        if self.reads_before is None:
            self.cur.execute("DELETE FROM system_settings WHERE key = 'discover_reads'")
        else:
            DiscoverRepository.keep_reads(self.cur, self.reads_before)
        self.conn.commit()
        self.conn.close()

    def _source(self, k, links, *, host=None, handle=None):
        source = insert_source(self.cur, f"Voice {k} {self.m}", handle=handle)
        host = host or f"s{k}-{self.m}.example"
        url = f"https://{host}/p/{uuid.uuid4().hex}"
        insert_post(self.cur, source, url, host=host, normalized=url, links=links, at=NOW - timedelta(days=3))
        return source

    def _listed(self):
        return {s["key"]: s for s in StoriesService(db_url()).discover()["suggestions"]}

    def test_three_voices_on_one_channels_videos_make_a_channel_row(self):
        videos = [f"https://youtube.com/watch?v={self.m}{k}" for k in range(3)]
        for k, video in enumerate(videos):
            self._source(k, [video, f"https://youtube.com/watch?v={self.m}x{k}"])
        self.conn.commit()
        channel = f"youtube.com/@chan{self.m}"
        self.assertNotIn(channel, self._listed())
        self.cur.execute("SELECT count(*) FROM discover_addresses WHERE url = ANY(%s) AND key IS NULL", (videos,))
        self.assertEqual(self.cur.fetchone()[0], 3, "unread, a video names no account")
        reads = DiscoverRepository.reads(self.cur)
        reads["videos"] = {**reads.get("videos", {}),
                           **{v: {"channel": channel, "at": NOW.isoformat()} for v in videos}}
        DiscoverRepository.keep_reads(self.cur, reads)
        self.conn.commit()
        self.assertEqual(StoriesService(db_url()).map_videos(DiscoverRepository.video_channels(self.cur)), 3)
        got = self._listed()[channel]
        self.assertEqual(got["voices"], 3)
        self.assertEqual(sorted(a["url"] for a in got["articles"]), sorted(videos))

    def test_a_repository_two_voices_link_is_suggested_as_its_releases(self):
        repo = f"https://github.com/acme{self.m}/widget"
        self._source(0, [repo, f"{repo}/releases/tag/v1.0"])
        self._source(1, [f"{repo}/issues/12"])
        self._source(2, [f"https://github.com/acme{self.m}/lonely"])
        followed = f"https://github.com/acme{self.m}/kept"
        self._source(3, [followed], handle=f"{followed}/releases.atom")
        self._source(4, [followed + "/pull/3"])
        self.conn.commit()
        listed = self._listed()
        got = listed[f"github.com/acme{self.m}/widget"]
        self.assertEqual((got["url"], got["voices"], got["releases"]), (f"{repo}/releases.atom", 2, True))
        self.assertNotIn(f"github.com/acme{self.m}/lonely", listed, "one voice")
        self.assertNotIn(f"github.com/acme{self.m}/kept", listed, "its releases are followed")

    def test_a_newsletter_on_a_platform_you_follow_two_of_is_suggested(self):
        platform = f"letters{self.m}.example"
        for k, pub in enumerate(("one", "uno")):   # two publications followed there
            self._source(10 + k, [], host=f"{pub}.{platform}")
        # and a site of many owners by the data (discover_rules.federation): your sources link 10+ of its hosts
        self._source(20, [f"https://w{n}.{platform}/p/a-post" for n in range(10)])
        other = [f"https://two.{platform}/p/a-long-post-slug-{n}" for n in range(2)]
        for k in range(3):
            self._source(k, other)
        self.cur.execute("UPDATE post_links SET target_site = %s WHERE target_url LIKE %s", (platform, f"%.{platform}/%"))
        self.conn.commit()
        self.assertIn(f"two.{platform}", self._listed())

    def test_a_company_you_follow_two_sections_of_is_followed(self):
        """Two followed hosts of one company are one owner's site, not a site of publications: its other hosts and the
        company itself are followed, never suggested (0248)."""
        company = f"maker{self.m}.example"
        self._source(10, [], host=f"newsroom.{company}")
        self._source(11, [], host=f"engineering.blogs.{company}")
        for k in range(3):
            self._source(k, [f"https://lists.{company}/archives/2007/msg-{n}.html" for n in range(2)]
                         + [f"https://{company}/en/newsroom/press-releases/a-long-release-{n}.html" for n in range(2)])
        self.cur.execute("UPDATE post_links SET target_site = %s WHERE target_url LIKE %s", (company, f"%{company}/%"))
        self.conn.commit()
        listed = self._listed()
        self.assertNotIn(f"lists.{company}", listed)
        self.assertNotIn(company, listed)


if __name__ == "__main__":
    unittest.main()
