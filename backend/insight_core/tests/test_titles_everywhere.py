"""Titles everywhere, and one stuck job (issue 0070 C): Discover's articles and stories' outside origins
are titled by one rule (story_rules.origin_title) with the page's own words when a post quotes them
(a quoted tweet's text, a link preview's title), a link post's title and a slug without its leading id;
a job a restart ended is closed when its process starts again.

The rules are tested as pure functions; Discover's titles and the jobs on the database in one
transaction per test, rolled back (the jobs' test commits and cleans up after itself).
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

from insight_core.db.repo_discover import DiscoverRepository
from insight_core.db.repo_stories import SourceFacts
from insight_core.services.operations_service import OperationsService
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import SCRATCH_PREFIX, db_url, requires_test_db
from insight_core.tests._stories import insert_post, insert_source, story_post
from insight_core.utils.post_links import quoted_words
from insight_core.utils.story_rules import StoryPost, origin_title

NOON = datetime(2026, 10, 27, 12, 0, 7, tzinfo=timezone.utc)
TWEET = "https://x.com/claudeai/status/2074548242386178258"
QUOTE = (f'<p>yay</p><hr/><blockquote>\n<b>Claude (@claudeai)</b>\n<p>\n<p>We\'re extending access to Claude Fable 5.<br>\n'
         f'<br>\nMore soon.</p>\n<a href="https://nitter.local/claudeai/status/2074548242386178258#m"><br>Video<br></a>\n</p>\n'
         f'<footer>\n— <cite><a href="https://nitter.local/claudeai/status/2074548242386178258#m">nitter</a>\n</footer>\n</blockquote>')


def preview(url, site, title, description):
    return (f'<br/>Fable 5 <a href="{url}">оставили</a><br/><blockquote cite="{url}"><cite><b>{site}</b></cite></br>'
            + (f"<b>{title}</b></br>" if title is not None else "") + f'{description}</br><img src="x.jpeg"/></blockquote>')


def post(pid, url, *, kind="telegram", text=None, quoted=None, links=None, source=None, **fields):
    """A post of its own source linking `url`, with the link's words `text` or its quote `quoted`."""
    return story_post(pid, source or pid, at=NOON, kind=kind, site=f"{pid}.test", url=f"https://{pid}.test/1",
                      links=links or [(url, None)], texts={url: text} if text else {},
                      quoted_words={url: quoted} if quoted else {}, **fields)


class QuotedWordsTests(unittest.TestCase):
    def test_a_quoted_tweet_is_its_text_a_line_a_line(self):
        words = quoted_words(QUOTE)
        self.assertEqual(list(words), [TWEET])
        self.assertEqual([line for line in words[TWEET].splitlines() if line.strip()],
                         ["We're extending access to Claude Fable 5.", "More soon.", "Video"])

    def test_a_link_preview_is_its_title(self):
        url = "https://arxiv.org/abs/2610.16733"
        self.assertEqual(quoted_words(preview(url, "arXiv.org", "TheoPhysEval: Assessing AI agents", "We present a suite")),
                         {url: "TheoPhysEval: Assessing AI agents"})

    def test_a_posts_preview_is_titled_by_its_account_so_its_description_is_the_text(self):
        self.assertEqual(quoted_words(preview(TWEET + "?s=46", "X (formerly Twitter)", "Claude (@claudeai) on X",
                                              "We're extending access to Claude Fable 5")),
                         {TWEET: "We're extending access to Claude Fable 5"})
        toot = "https://mastodon.social/@tristan/117233413705701198"
        self.assertEqual(quoted_words(preview(toot, "Mastodon", "tristan (@tristan@mastodon.social)", "Three results")),
                         {toot: "Three results"})
        article = "https://x.com/jsuarez/status/2099512196304925161"
        self.assertEqual(quoted_words(preview(article, "Article • FixupX", "The 5 Coolest RL Results", "5. Multitask")),
                         {article: "The 5 Coolest RL Results"}, "an X article's preview has a title")

    def test_a_preview_that_names_only_its_site_has_no_words(self):
        self.assertEqual(quoted_words(preview("https://chatgpt.com/", "ChatGPT", None, "ChatGPT helps you")), {})
        self.assertEqual(quoted_words(preview("https://anthropic.com/", "Anthropic", "Anthropic", "AI research")), {})
        self.assertEqual(quoted_words('<blockquote cite="https://a.test/x"><p>A quote from the page.</p></blockquote>'), {},
                         "a blog's quote of a page is not its preview")


class OriginTitleEvidenceTests(unittest.TestCase):
    URL = "https://anthropic.com/news/claude-fable-5-mythos-5"

    def test_the_pages_own_words_come_first_the_most_quoted(self):
        posts = [post("a", self.URL, text="Claude Fable 5 and Mythos 5"), post("b", self.URL, text="Claude Fable 5 and Mythos 5"),
                 post("c", self.URL, quoted="Introducing Claude Fable 5"), post("d", self.URL, quoted="Introducing Claude Fable 5"),
                 post("e", self.URL, quoted="Claude Fable 5")]
        self.assertEqual(origin_title(self.URL, posts), "Introducing Claude Fable 5")

    def test_a_quoted_tweet_is_titled_as_the_reader_titles_a_tweet(self):
        self.assertEqual(origin_title(TWEET, [post("q", TWEET, kind="x", text="Video", quoted=quoted_words(QUOTE)[TWEET])]),
                         "We're extending access to Claude Fable 5.")

    def test_a_link_post_that_is_only_this_link_gives_its_title(self):
        url = "https://arxiv.org/abs/2610.24365"
        title = "Princeton and Polymathic AI release FlashMap: Flow Map Speculative Decoding"
        self.assertEqual(origin_title(url, [post("r", url, kind="reddit", title=title, words=20)]), title)
        self.assertIsNone(origin_title(url, [post("r", url, kind="reddit", title=title, words=200)]), "a post of its own")
        self.assertIsNone(origin_title(url, [post("r", url, kind="reddit", title=title, words=20,
                                                  links=[(url, None), ("https://b.test/2026/x", None)])]), "two links")
        self.assertIsNone(origin_title(url, [post("t", url, title="This is really clever.")]),
                          "a Telegram post's words are about the link, not its title")

    def test_slug_words_two_voices_agree_on_still_beat_a_link_post(self):
        url = "https://mistral.ai/news/mistral-large-4-oss"
        self.assertEqual(origin_title(url, [post("r", url, kind="reddit", title="Mistral Large 4 is now open weight", words=20),
                                            post("a", url, text="Mistral Large 4 OSS")]), "Mistral Large 4 OSS",
                         "words the slug confirms")
        self.assertEqual(origin_title(url, [post("r", url, kind="reddit", title="Mistral Large 4 is now open weight", words=20)]),
                         "Mistral Large 4 is now open weight", "before the slug made readable")

    def test_a_slugs_leading_id_or_date_is_no_word(self):
        cases = {"https://help.openai.com/en/articles/20001626-api-credits-benefit-for-eligible-chatgpt-subscriptions":
                 "Api credits benefit for eligible chatgpt subscriptions",
                 "https://beren.io/2026-07-26-How-Can-LLM-RL-Work": "How Can LLM RL Work",
                 "https://time.com/16-charts-that-explain-the-ai-boom": "16 charts that explain the ai boom",
                 "https://hai.stanford.edu/ai-index/2025-ai-index-report": "2025 ai index report"}
        for url, title in cases.items():
            self.assertEqual(origin_title(url, [post("a", url, text="here")]), title, url)


@requires_test_db
class DiscoverTitlesTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.mark = uuid.uuid4().hex[:8]
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _source(self, platform="rss", kind=""):
        return insert_source(self.cur, handle=f"{SCRATCH_PREFIX}{kind}{uuid.uuid4().hex}", platform=platform)

    def _post(self, source, *, html="", title=None, content=None, url=None, links=()):
        url = url or f"https://p-{self.mark}.test/{uuid.uuid4().hex}"
        return str(insert_post(self.cur, source, url, at=self.now, title=title, content=content, html=html,
                               normalized=url, links=list(links)))

    def test_an_article_is_titled_by_a_quote_a_stored_post_or_nothing(self):
        quoted, stored, bare = (f"https://x.com/acct{self.mark}/status/{n}" for n in (1, 2, 3))
        x, tg, site = self._source(kind="nitter/"), self._source("telegram"), self._source()
        self._post(x, html=QUOTE.replace("claudeai/status/2074548242386178258", f"acct{self.mark}/status/1"),
                   links=[(quoted, "Video")])
        self._post(tg, html=preview(quoted, "X", "Acct (@acct) on X", "We're extending access to Claude Fable 5."),
                   links=[(quoted, "оставили"), (stored, "tweet")])
        self._post(site, links=[(quoted, "tweet"), (stored, "tweet"), (bare, "tweet")])
        self._post(x, url=stored, title="RT by @acct: We are doubling all usage limits", content="We are doubling all usage limits")
        found = [{"articles": [(quoted, []), (stored, []), (bare, [])]}]
        StoriesService._title_articles(self.cur, SourceFacts(self.cur), found)
        self.assertEqual(found[0]["articles"], [(quoted, [], "We're extending access to Claude Fable 5."),
                                                (stored, [], "We are doubling all usage limits"),
                                                (bare, [], None)],
                         "the quote's words; a stored post's own title as the reader shows it; a link word is none")

    def test_a_stored_origin_reads_as_the_reader_titles_it(self):
        site = self._source()
        root = self._post(site, title="Как я взял золото на ERC3 ☕Это самый полезный пост на канале.",
                          content="Как я взял золото на ERC3 ☕\nЭто самый полезный пост на канале.")
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, 2)", (root, self.now))
        self.cur.execute("INSERT INTO story_posts (story_id, post_id, role, reasons, voice) VALUES (%s, %s, 'report', '{}', 'v')",
                         (root, root))
        sources = SourceFacts(self.cur)
        [origin] = [o for o in DiscoverRepository.story_origins(self.cur, kinds=sources.kind, own_sites={})
                    if o.story_id == root]
        self.assertEqual(origin.title, "Как я взял золото на ERC3 ☕")


@requires_test_db
class InterruptedJobsTests(unittest.TestCase):
    def setUp(self):
        self.ops = OperationsService(db_url())
        self.ids = []

    def tearDown(self):
        with psycopg.connect(db_url()) as conn:
            conn.execute("DELETE FROM job_runs WHERE id = ANY(%s::uuid[])", (self.ids,))

    def _status(self, job_id):
        with psycopg.connect(db_url()) as conn:
            return conn.execute("SELECT status, finished_at IS NOT NULL, payload->'events'->-1->>'message' FROM job_runs "
                                "WHERE id = %s", (job_id,)).fetchone()

    def test_a_process_closes_its_own_jobs_a_restart_left_running(self):
        manual = self.ops.start_job("ingestion_run", trigger="manual", message="Fetch source x")
        scheduler = self.ops.start_job("ingestion_run", trigger="scheduler")
        done = self.ops.start_job("archive_source", trigger="manual")
        self.ids += [manual, scheduler, done]
        self.ops.finish_job(done, status="success", message="Archived 3 posts")
        self.assertGreaterEqual(self.ops.close_interrupted_jobs("manual"), 1)
        self.assertEqual(self._status(manual), ("interrupted", True, "Interrupted by a restart"))
        self.assertEqual(self._status(scheduler)[0], "running", "the scheduler's run is its own process's")
        self.assertEqual(self._status(done), ("success", True, "Archived 3 posts"), "a finished job is left alone")
        self.ops.close_interrupted_jobs("scheduler")
        self.assertEqual(self._status(scheduler)[0], "interrupted")


if __name__ == "__main__":
    unittest.main()
