"""Discover suggests the sources your stories start from (issue 0065): suggestions ranked by the
stories that start there, then by links; a section of a site you follow; a followed source whose
own pages start stories it doesn't hold; a post on a platform as an article of its account, in any
form; a repost as a voice for the original author.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils.discover_rules import Origin, discover_address, discover_article, discover_place, origins

NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def root(url, *, source=None, voices=3, days=0, own=False):
    return Origin(uuid.uuid4().hex, url, None, source, NOW - timedelta(days=days),
                  {f"source:v{n}": f"v{n}" for n in range(voices)}, own)


class PlatformPostTests(unittest.TestCase):
    def test_a_tweet_in_any_form_is_an_article_of_its_author(self):
        for url in ("https://x.com/OpenAI/status/2111872584338018562", "https://xcancel.com/OpenAI/status/2111872584338018562",
                    "https://nitter.local/OpenAI/status/2111872584338018562#m", "https://fxtwitter.com/OpenAI/status/2111872584338018562/photo/1"):
            self.assertEqual(discover_address(url), ("x.com/openai", "x.com", True), url)
            self.assertTrue(discover_article(url), url)
        self.assertFalse(discover_article("https://x.com/OpenAI"), "a profile is not a post")
        self.assertFalse(discover_article("https://example.com/a/status/12345"), "a short id is no tweet")
        self.assertEqual(discover_address("https://x.com/i/status/2111872584338018562")[0], None, "names no account")

    def test_a_telegram_post_is_an_article_of_its_channel(self):
        self.assertEqual(discover_address("https://t.me/denissexy/11744"), ("t.me/denissexy", "t.me", True))
        self.assertTrue(discover_article("https://t.me/denissexy/11744"))
        self.assertFalse(discover_article("https://example.com/denissexy/11744"), "only on a platform")
        self.assertFalse(discover_article("https://t.me/denissexy"))

    def test_a_page_that_names_no_account_reads_its_first_segment_without_its_query(self):
        self.assertEqual(discover_address("https://youtube.com/watch?v=abc"), (None, "youtube.com", True))


class OriginsTests(unittest.TestCase):
    def test_where_each_story_starts(self):
        roots = [
            root("https://qwen.ai/blog?id=qwen3"),                              # a site you don't follow
            root("https://github.com/openai/codex"),                            # an account on a platform
            root("https://youtube.com/watch?v=abc"),                            # names no account
            root("https://youtube.com/watch?v=def", source="s-yt"),             # a stored video: its channel's
            root("https://openai.com/index/gpt-6", days=20),                    # a place a source holds, not stored
            root("https://openai.com/index/gpt-5", source="s-openai", own=True),  # its own post
            root("https://x.com/sama/status/2111872584338018562"),              # an account a source holds
        ]
        found = origins(roots, followed={"openai.com"}, held={"openai.com/index": "s-openai", "x.com/sama": "s-sama"})
        self.assertEqual(sorted(found.suggest), ["github.com/openai", "qwen.ai"])
        self.assertEqual({k: [r.url for r in v] for k, v in found.missing.items()},
                         {"s-openai": ["https://openai.com/index/gpt-6"], "s-sama": ["https://x.com/sama/status/2111872584338018562"]})
        self.assertEqual({k: len(v) for k, v in found.unnamed.items()}, {"youtube.com/watch": 1})

    def test_a_site_you_follow_is_never_suggested_its_other_sections_are_missed_by_its_source(self):
        """Issue 0080 (decision 6): a section of a followed site none of your sources holds is no suggestion."""
        held = {"anthropic.com/research": "s-research"}
        news = [root(f"https://anthropic.com/news/model-{n}") for n in range(14)]
        other = [root("https://anthropic.com/engineering/a-b"), root("https://anthropic.com/claude-guide")]
        found = origins(news + other, followed={"anthropic.com"}, held=held)
        self.assertFalse(found.suggest)
        self.assertEqual({k: len(v) for k, v in found.missing.items()}, {"s-research": 16})
        self.assertEqual(discover_place("https://anthropic.com/news/model-1"), "anthropic.com/news")
        self.assertEqual(discover_place("https://anthropic.com/claude-guide"), "anthropic.com", "the root: the host alone")
        self.assertEqual(discover_place("https://simonwillison.net/2026/Oct/23/x"), "simonwillison.net", "a date is no section")

    def test_a_followed_site_with_no_main_section_is_not_suggested_whole(self):
        roots = [root(f"https://hub.example/{org}/model-{n}") for org in ("OrgOne", "org-two", "org3") for n in range(3)]
        found = origins(roots, followed={"hub.example"}, held={"hub.example/blog": "s-hub"})
        self.assertFalse(found.suggest, "issue 0080: the whole followed host was suggested")
        self.assertEqual({k: len(v) for k, v in found.missing.items()}, {"s-hub": 9})

    def test_on_a_platform_the_data_finds_the_owners_are_suggested(self):
        roots = [root(f"https://hub.example/{org}/model-{n}") for org in ("OrgOne", "org-two", "org3") for n in range(3)]
        found = origins(roots, followed={"hub.example"}, held={"hub.example/blog": "s-hub"}, platforms={"hub.example": ()})
        self.assertEqual({k: len(v) for k, v in found.suggest.items()},
                         {"hub.example/orgone": 3, "hub.example/org-two": 3, "hub.example/org3": 3})

    def test_a_reference_page_is_only_listed(self):
        roots = [root("https://help.tool.example/articles/1-how"), root("https://tool.example/docs/setup")]
        found = origins(roots, followed=set(), held={})
        self.assertFalse(found.suggest)
        self.assertEqual(sorted(found.references), ["help.tool.example", "tool.example"])


@requires_test_db
class DiscoverOriginsTests(unittest.TestCase):
    """On the database, through the service (it opens its own connections)."""

    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.addCleanup(self._clean)

    def _clean(self):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM sources WHERE handle_or_url LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM stories WHERE origin_url LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM discover_hidden WHERE key LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%{self.mark}%",))
        self.conn.commit()
        self.conn.close()

    # ---- fixture ----------------------------------------------------------------------------

    def _source(self, name, handle=None):
        return insert_source(self.cur, name, handle=handle)

    def _post(self, source, url, links=(), *, days=0):
        return insert_post(self.cur, source, url, at=NOW - timedelta(days=days), normalized=url, links=list(links))

    def _story(self, origin, posts, *, days=0):
        """A story whose root is the page `origin`, outside INSIGHT, and its posts under it."""
        story = posts[0][0]   # a story is keyed by its first post
        self.cur.execute("INSERT INTO stories (id, first_at, voices, origin_url, origin_linked_by) VALUES (%s, %s, %s, %s, %s)",
                         (story, NOW - timedelta(days=days), len(posts), origin, len(posts)))
        for post_id, voice in posts:
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_reason, parent_url) "
                             "VALUES (%s, %s, 'report', %s, 'citation', %s)", (post_id, story, voice, origin))

    def _voices(self, n=3):
        out = []
        for k in range(n):
            source = self._source(f"Voice {k} {self.mark}")
            host = f"voice{k}-{self.mark}.example"
            self._post(source, f"https://{host}/p/home")
            out.append((source, host))
        return out

    def _cite(self, voices, origin, *, days=0):
        """Each voice posts once linking `origin`; the posts make one story rooted at it."""
        posts = [(self._post(source, f"https://{host}/p/{uuid.uuid4().hex}", [origin], days=days), f"site:{host}")
                 for source, host in voices]
        self._story(origin, posts, days=days)

    def _discover(self):
        self.conn.commit()
        return StoriesService(db_url()).discover()

    def _keys(self, result):
        return [s["key"] for s in result["suggestions"] if self.mark in s["key"]]

    # ---- the tests --------------------------------------------------------------------------

    def test_ranked_by_the_stories_that_start_there_then_by_links(self):
        m = self.mark
        voices = self._voices(4)
        for source, host in voices:                                        # linked by 4: today's first
            self._post(source, f"https://{host}/p/x", [f"https://busy-{m}.example/2026/10/story-{n}" for n in range(2)])
        for n in range(2):                                                  # linked by 3, and 2 stories start there
            self._cite(voices[:3], f"https://origin-{m}.example/2026/10/launch-{n}")
        for source, host in voices[:3]:                                     # linked by 3, no story
            self._post(source, f"https://{host}/p/y", [f"https://quiet-{m}.example/2026/10/note-{n}" for n in range(2)])
        result = self._discover()
        self.assertEqual(self._keys(result), [f"origin-{m}.example", f"busy-{m}.example", f"quiet-{m}.example"])
        by_key = {s["key"]: s for s in result["suggestions"]}
        origin = by_key[f"origin-{m}.example"]
        self.assertEqual((origin["origins"], len(origin["origin_stories"]), origin["origin_stories"][0]["voices"]), (2, 2, 3))
        self.assertNotIn("follows", origin)
        self.assertEqual((by_key[f"busy-{m}.example"]["origins"], by_key[f"busy-{m}.example"]["voices"]), (0, 4),
                         "a site with no stories: as today")

    def test_a_section_of_a_site_you_follow(self):
        m = self.mark
        site = f"lab-{m}.example"
        research = self._source(f"Lab research {m}", f"https://{site}/research")
        for n in range(3):
            self._post(research, f"https://{site}/research/paper-{n}")
        voices = self._voices(3)
        for n in range(3):
            self._cite(voices, f"https://{site}/news/model-{n}")
        result = self._discover()
        self.assertFalse([k for k in self._keys(result) if k.startswith(site)], "issue 0080: a site you follow is never suggested")
        [missing] = [a for a in result["archives"] if a["source_id"] == research]
        self.assertEqual((missing["places"], missing["origins"]), ([f"{site}/news"], 3), "missing from a source you follow")

    def test_a_followed_source_whose_own_pages_start_stories_it_does_not_hold(self):
        m = self.mark
        site = f"newsroom-{m}.example"
        feed = self._source(f"Newsroom {m}", f"https://{site}/news/rss.xml")
        for n in range(2):
            self._post(feed, f"https://{site}/index/recent-{n}", days=n)
        voices = self._voices(3)
        for n, days in enumerate((30, 40, 0)):
            self._cite(voices, f"https://{site}/index/older-{n}", days=days)
        result = self._discover()
        [missing] = [a for a in result["archives"] if a["source_id"] == feed]
        self.assertEqual((missing["name"], missing["places"], missing["origins"], missing["older"]),
                         (f"Newsroom {m}", [f"{site}/index"], 3, 2))
        self.assertEqual(missing["since"], (NOW - timedelta(days=1)).isoformat())
        self.assertEqual(len(missing["origin_stories"]), 3)
        self.assertFalse([k for k in self._keys(result) if k.startswith(site)], "not a second source")

    def test_a_missing_row_follows_its_sources_archive(self):
        """Issue 0080: an archive started from Discover shows there, running, then finished."""
        m = self.mark
        site = f"archived-{m}.example"
        feed = self._source(f"Archived {m}", f"https://{site}/feed.xml")
        self._post(feed, f"https://{site}/index/recent")
        voices = self._voices(3)
        pages = [f"https://{site}/index/older-{n}" for n in range(3)]
        for page in pages:
            self._cite(voices, page)

        def row():
            return next(a for a in self._discover()["archives"] if a["source_id"] == feed)

        self.assertEqual(row()["archive"], {"state": None, "found": 0})
        self.assertNotIn("pages", row(), "the pages stay in the service")
        self.cur.execute("INSERT INTO job_runs (job_type, status, trigger, source_id, payload) "
                         "VALUES ('archive_source', 'running', 'manual', %s, '{\"pages_fetched\": 4}')", (feed,))
        self._post(feed, pages[0])   # the archive stored one of them; the story job hasn't run yet
        self.assertEqual(row()["archive"], {"state": "running", "found": 1, "pages_fetched": 4})
        self.cur.execute("UPDATE job_runs SET status = 'success' WHERE source_id = %s", (feed,))
        self.cur.execute("UPDATE sources SET settings = settings || '{\"archive\": {\"checkpoint\": {\"completed_at\": \"2026-11-04\"}}}' "
                         "WHERE id = %s", (feed,))
        self.assertEqual(row()["archive"]["state"], "finished")
        self.cur.execute("DELETE FROM job_runs WHERE source_id = %s", (feed,))

    def test_an_archive_row_counts_the_pages_it_lacks_and_drops_the_stored(self):
        """Issue 0109 W8: the row counted stories ("41 it doesn't hold") while its archive had stored 36 of the pages."""
        m = self.mark
        site = f"counted-{m}.example"
        feed = self._source(f"Counted {m}", f"https://{site}/feed.xml")
        self._post(feed, f"https://{site}/index/recent")
        voices = self._voices(3)
        pages = [f"https://{site}/index/older-{n}" for n in range(3)]
        for page in (*pages, pages[0]):   # two stories start at the first page
            self._cite(voices, page)

        def row():
            return next((a for a in self._discover()["archives"] if a["source_id"] == feed), None)

        self.assertEqual((row()["origins"], row()["stored"]), (3, 0), "pages, not stories")
        self._post(feed, pages[0])   # stored since: the story job hasn't run yet
        got = row()
        self.assertEqual((got["origins"], got["stored"]), (2, 1))
        self.assertNotIn(pages[0], [o["url"] for o in got["origin_stories"]])
        for page in pages[1:]:
            self._post(feed, page)
        self.assertIsNone(row(), "nothing left to miss")

    def test_an_archive_row_says_when_its_feed_stopped(self):
        m = self.mark
        site = f"stopped-{m}.example"
        feed = self._source(f"Stopped {m}", f"https://{site}/atom.xml")
        self._post(feed, f"https://{site}/blog/last", days=400)
        voices = self._voices(3)
        for n in range(2):
            self._cite(voices, f"https://{site}/blog/new-{n}")
        [row] = [a for a in self._discover()["archives"] if a["source_id"] == feed]
        self.assertEqual(row["stopped"], (NOW - timedelta(days=400)).isoformat())
        self.assertEqual(row["archivable"], 0, "an archive can't reach what the feed never had")

    def test_an_archive_row_says_what_its_source_watches_instead(self):
        m = self.mark
        site = f"watched-{m}.example"
        page = self._source(f"Watched {m}", f"https://{site}/blog")
        self.cur.execute("""UPDATE sources SET settings = settings || '{"page_watch": {"prefix": "/resources/articles/"}}' WHERE id = %s""",
                         (page,))
        self._post(page, f"https://{site}/resources/articles/one")
        voices = self._voices(3)
        for n in range(2):
            self._cite(voices, f"https://{site}/blog/post-{n}")
        self._cite(voices, f"https://{site}/resources/articles/missed")
        [row] = [a for a in self._discover()["archives"] if a["source_id"] == page]
        self.assertEqual(row["watches"], {"prefix": "/resources/articles/", "not": ["/blog"]})
        self.assertEqual((row["origins"], row["archivable"]), (3, 1), "an archive reaches only what it watches")
        self.assertNotIn("stopped", row)

    def test_tweets_in_any_form_and_reposts_suggest_an_account(self):
        m = self.mark
        author = f"Auth{m}"
        voices = self._voices(2)
        forms = ("x.com", "xcancel.com", "nitter.net")
        for k, (source, host) in enumerate(voices):
            self._post(source, f"https://{host}/p/t", [f"https://{forms[k]}/{author}/status/21118725843380185{k}{n}" for n in range(2)])
        reposter = self._source(f"Reposter {m}", f"https://nitter-{m}.example/rep{m}/rss")
        self._post(reposter, f"https://nitter-{m}.example/{author}/status/2111872584338018599")   # a repost
        self._post(reposter, f"https://nitter-{m}.example/rep{m}/status/2111872584338018598")    # its own
        result = self._discover()
        [account] = [s for s in result["suggestions"] if s["key"] == f"x.com/{author.lower()}"]
        self.assertEqual((account["voices"], account["article_count"]), (3, 5), "two linkers and the reposter")
        self.assertIn(f"Reposter {m}", account["voice_names"])
        self.assertNotIn(f"x.com/rep{m}", self._keys(result), "its own posts are no repost")

    def test_one_linker_and_one_repost_are_not_enough(self):
        """Extraltodeus on the lab: one source links the tweet, one reposts it."""
        m = self.mark
        [(source, host)] = self._voices(1)
        self._post(source, f"https://{host}/p/t", [f"https://x.com/Extra{m}/status/2111872584338018562",
                                                    f"https://x.com/Extra{m}/status/2111872584338018563"])
        reposter = self._source(f"Reposter {m}", f"https://nitter-{m}.example/rep{m}/rss")
        self._post(reposter, f"https://nitter-{m}.example/Extra{m}/status/2111872584338018562")
        self.assertNotIn(f"x.com/extra{m}", self._keys(self._discover()))


if __name__ == "__main__":
    unittest.main()
