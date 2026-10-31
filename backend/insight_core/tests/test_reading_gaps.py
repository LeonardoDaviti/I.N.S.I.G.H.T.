"""What reading v9.9 would show (issue 0068): a thread's replies read as posts, the roundups that
mention a story, a repost by one of your sources as its voice, an outside origin's title by
evidence, and the stored bodies' link labels taken out once.

The rules are tested as pure functions; the job, the reader, the post page and the repair on the
database in one transaction per test, rolled back.
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

from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_posts import PostsRepository
from insight_core.db.repo_reader import FeedQuery, ReaderRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.posts_service import STORED_BODIES_KEY, PostsService
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.utils.content_fingerprints import strip_html
from insight_core.utils.news_rules import news, tally
from insight_core.utils.story_rules import StoryPost, group, origin_title, roles
from insight_core.utils.url_normalization import normalize_url

NOON = datetime(2026, 10, 27, 12, 0, 7, tzinfo=timezone.utc)
ID = 2114444636303364349


def tweet(pid, source, user, *, reposters=(), minutes=0.0):
    return StoryPost(id=pid, source_id=source, kind="x", own_site="x.com", home_site="x.com",
                     t=NOON + timedelta(minutes=minutes), url=f"https://x.com/{user}/status/{ID}", author=user,
                     reposters=tuple(reposters))


def linker(pid, source, url, text, *, hours=0.0, text_hash=None, kind="telegram"):
    return StoryPost(id=pid, source_id=source, kind=kind, own_site=f"{source}.test", t=NOON + timedelta(hours=hours),
                     url=f"https://{source}.test/{pid}", links=[(url, None)], link_texts={url: text} if text else {},
                     content_hash=text_hash, text_chars=200 if text_hash else 0)


class OriginTitleTests(unittest.TestCase):
    URL = "https://anthropic.com/news/claude-fable-5-mythos-5"

    def title(self, *linkers, url=None):
        return origin_title(url or self.URL, list(linkers))

    def test_1_words_two_voices_agree_on_that_read_as_a_title(self):
        self.assertEqual(self.title(linker("a", "a", self.URL, "Claude Fable 5 and Mythos 5"),
                                    linker("b", "b", self.URL, "claude fable 5 and  mythos 5", hours=1),
                                    linker("c", "c", self.URL, "Introducing Fable", hours=2)),
                         "Claude Fable 5 and Mythos 5")

    def test_1_a_bare_word_two_voices_agree_on_is_no_title_and_copies_are_one_voice(self):
        bare = [linker("a", "a", self.URL, "Блогпост"), linker("b", "b", self.URL, "Блогпост", hours=1)]
        self.assertEqual(self.title(*bare), "Claude fable 5 mythos 5", "the slug, not a bare word")
        copies = [linker("a", "a", self.URL, "Read the whole post", text_hash="h"),
                  linker("b", "b", self.URL, "Read the whole post", hours=1, text_hash="h")]
        self.assertEqual(self.title(*copies), "Claude fable 5 mythos 5", "a forward does not agree with itself")

    def test_2_words_the_slug_confirms_keep_their_case(self):
        url = "https://openai.com/index/introducing-chatgpt-images-2-5"
        self.assertEqual(self.title(linker("a", "a", url, "Introducing ChatGPT Images 2.5"),
                                    linker("b", "b", url, "here", hours=1), url=url), "Introducing ChatGPT Images 2.5")
        url = "https://github.com/coddy-project/coddy-agent"
        self.assertEqual(self.title(linker("a", "a", url, "Coddy Agent"), url=url), "Coddy Agent")

    def test_3_the_slug_needs_three_words_of_letters(self):
        self.assertEqual(self.title(linker("a", "a", self.URL, "тут")), "Claude fable 5 mythos 5")
        for url in ("https://ft.com/content/7cab4ec7-4712-4137-b602-119a44f771de",   # an id
                    "https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro",          # two words
                    "https://arxiv.org/abs/2510.27055"):
            self.assertIsNone(self.title(linker("a", "a", url, "статья"), url=url), url)

    def test_4_one_voices_words_that_read_as_a_title(self):
        url = "https://arxiv.org/abs/2510.27055"
        self.assertEqual(self.title(linker("a", "a", url, "Scaling Laws for Agents"), linker("b", "b", url, "paper", hours=1),
                                    url=url), "Scaling Laws for Agents")

    def test_5_else_the_address(self):
        url = "https://shvm.xyz/webinar/ai-evals"
        self.assertIsNone(self.title(linker("a", "a", url, "here"), linker("b", "b", url, None, hours=1), url=url))

    def test_a_stored_page_is_the_root_with_its_own_title(self):
        stored = StoryPost(id="own", source_id="oa", kind="site", own_site="anthropic.com", t=NOON, url=self.URL,
                           title="Claude Fable 5 and Mythos 5")
        cite = StoryPost(id="a", source_id="a", kind="telegram", own_site="a.test", t=NOON + timedelta(hours=1),
                         url="https://a.test/a", links=[(self.URL, "own")], link_texts={self.URL: "Блогпост"})
        [story] = group([stored, cite])
        self.assertEqual((story.origin_url, story.parents["own"]), (None, (None, None, None)),
                         "the stored post is the root; the reader shows its title")


class StoredBodiesTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def test_the_link_labels_leave_the_stored_bodies_and_nothing_else(self):
        source = insert_scratch_source(self.cur)
        labelled = ('<p>We worked with <a href="https://x.test/a">partners<span class="sr-only">(opens in a new window)</span>'
                    '</a> and <span class="visually-hidden">a chart: 66 %</span>.</p>')
        rows = {}
        for name, html in (("labelled", labelled), ("plain", "<p>We worked with <a href=\"https://x.test/a\">partners</a>.</p>")):
            self.cur.execute(
                """INSERT INTO posts (source_id, url, title, content, content_html, content_hash, links_scanned_at)
                   VALUES (%s, %s, %s, %s, %s, 'h', now()) RETURNING id""",
                (source, f"https://x.test/{uuid.uuid4().hex}", name, strip_html(html), html))
            rows[name] = str(self.cur.fetchone()[0])
        self.assertGreaterEqual(PostsRepository.drop_hidden_link_labels(self.cur), 1)
        self.cur.execute("SELECT id, content_html, content, content_hash <> 'h', links_scanned_at IS NULL FROM posts"
                         " WHERE id = ANY(%s::uuid[])", (list(rows.values()),))
        got = {str(r[0]): r[1:] for r in self.cur.fetchall()}
        self.assertEqual(got[rows["labelled"]][0], '<p>We worked with <a href="https://x.test/a">partners</a> and '
                                                   '<span class="visually-hidden">a chart: 66 %</span>.</p>',
                         "the label inside the link goes; hidden text outside a link stays")
        self.assertEqual(got[rows["labelled"]][1], "We worked with partners and a chart: 66 % .")
        self.assertEqual(got[rows["labelled"]][2:], (True, True), "its hash follows; the job reads its links again")
        self.assertEqual(got[rows["plain"]][2:], (False, False), "a body without labels is untouched")
        self.assertEqual(PostsRepository.drop_hidden_link_labels(self.cur), 0, "twice over: nothing more")


@requires_test_db
class StoredBodiesCatchUpTests(unittest.TestCase):
    """The repair runs once, in the background, as a version the stored bodies are brought up to."""

    def setUp(self):
        self.service = PostsService(db_url())
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.saved = SystemSettingsRepository.get(cur, STORED_BODIES_KEY)
            cur.execute("DELETE FROM system_settings WHERE key = %s", (STORED_BODIES_KEY,))

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM system_settings WHERE key = %s", (STORED_BODIES_KEY,))
            if self.saved:
                SystemSettingsRepository.upsert(cur, STORED_BODIES_KEY, self.saved[0])

    def test_once_then_never_again(self):
        self.service.catch_up_stored_bodies()
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(SystemSettingsRepository.get(cur, STORED_BODIES_KEY)[0]["version"], 1)
        self.assertEqual(self.service.catch_up_stored_bodies(), 0, "at the version: nothing is read again")


if __name__ == "__main__":
    unittest.main()
