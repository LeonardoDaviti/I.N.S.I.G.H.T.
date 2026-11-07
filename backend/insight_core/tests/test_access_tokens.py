"""A gift link's token, and a share mark, are kept for clicking and ignored for matching (issue 0126 (1)).

The rule is url_normalization's: every compared address drops an access token (a key naming a token, gift, unlock or
access, or a signed JWT value) and a share mark (who shared the page, never which). A link keeps the address its
post wrote in post_links.shared_url; a story's outside origin opens it (`href`). Links stored before are read again
from their post's stored HTML, and a post's own address is rewritten (migration 0073); the story sample holds the
case, so the rules' stamp regroups every story once (test_stamps).
"""
from __future__ import annotations

import re
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_reader import ReaderRepository
from insight_core.db.repo_stories import StoriesRepository
from insight_core.services.stories_service import SETTINGS_KEY, StoriesService
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils import url_normalization
from insight_core.utils.originals_rules import tokened
from insight_core.utils.post_links import extract_links

MIGRATION = BACKEND_DIR / "insight_core" / "db" / "migrations" / "0073_access_tokens.sql"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJpZCI6IngifQ.c2lnbmF0dXJl"
PAGE = "https://paper.example.com/2026/11/04/the-budget-story"
# The kinds of key the server's copy holds (0126's measure), on made-up addresses.
KEYED = [
    f"{PAGE}?accessToken={JWT}", f"{PAGE}?unlocked_article_code=1.N1E.abc", f"{PAGE}?gift=5MjK",
    f"{PAGE}?giftId=OWRh", f"{PAGE}?view_token={JWT}", f"{PAGE}?access_token=x", f"{PAGE}?pwapi_token=x",
    f"{PAGE}?sharing_token=x", f"{PAGE}?shareToken=2000", f"{PAGE}?gift_token=3lv", f"{PAGE}?gift_content=a140",
    f"{PAGE}?guestAccessKey=", f"{PAGE}?casa_token=Py", f"{PAGE}?dib={JWT}&dib_tag=se", f"{PAGE}?smid=nytcore-ios-share",
    f"{PAGE}?taid=69c3", f"{PAGE}?mrfcid=2026", f"{PAGE}?srnd=homepage-americas", f"{PAGE}?leadSource=uverify%20wall",
    f"{PAGE}?reflink=desktopwebshare_permalink", f"{PAGE}?syn-25a6b1a6=1", f"{PAGE}?smid=url-share&unlocked_article_code=1.x",
    f"{PAGE}/?utm_source=x&accessToken={JWT}", f"{PAGE}?any_key={JWT}",
]


def _pattern() -> re.Pattern:
    """The migration's pattern of an address holding a key of the rule (Postgres ~* reads it as Python does here)."""
    [pattern] = re.findall(r"target_url ~\* '([^']+)'", MIGRATION.read_text(encoding="utf-8"))
    return re.compile(pattern, re.I)


class RuleTests(unittest.TestCase):
    def test_a_compared_address_drops_access_tokens_and_share_marks(self):
        for url in KEYED:
            self.assertEqual(url_normalization.normalize_url(url), PAGE, url)
            self.assertEqual(url_normalization.canonicalize_url(url), PAGE, url)

    def test_a_page_s_own_query_is_kept(self):
        for kept in ("id=12", "p=4", "v=abc", "share=x", "r=4b7x", "st=image", "sh=7f1", "rc=x8ts", "tag=a", "q=tokens",
                     "page=2", "ga=1"):
            self.assertEqual(url_normalization.normalize_url(f"{PAGE}?{kept}"), f"{PAGE}?{kept}", kept)
        self.assertEqual(url_normalization.normalize_url(f"{PAGE}?id=12&gift=abc&smid=x"), f"{PAGE}?id=12")

    def test_access_tokens_are_walled_share_marks_are_not(self):
        self.assertTrue(tokened(f"{PAGE}?accessToken={JWT}"))
        self.assertTrue(tokened(f"{PAGE}?dib={JWT}"))
        self.assertFalse(tokened(f"{PAGE}?smid=nytcore-ios-share"), "a share mark opens no wall")

    def test_a_link_keeps_the_address_its_post_wrote(self):
        html = (f'<p><a href="{KEYED[0]}">the story</a> and <a href="{PAGE}">again</a> and '
                f'<a href="https://other.example.com/a?smid=x&amp;id=2">another</a> and <a href="https://plain.example.com/b">a plain one</a></p>')
        links = extract_links(html, "https://blog.example.org/p/1", "site")
        self.assertEqual([(link.url, link.shared) for link in links], [
            (PAGE, KEYED[0]),
            ("https://other.example.com/a?id=2", "https://other.example.com/a?smid=x&id=2"),
            ("https://plain.example.com/b", None),
        ], "one page per address; the first link's address as written")

    def test_every_key_of_the_rule_is_one_the_migration_reads_again(self):
        pattern = _pattern()
        for url in KEYED:
            self.assertTrue(pattern.search(url), url)
        for kept in ("id", "p", "share", "r", "st", "sh", "rc", "tag", "access_mode_x"):
            if url_normalization.is_query_mark(kept, "v"):
                continue
            self.assertFalse(pattern.search(f"https://a.example/p?{kept}=v"), kept)


@requires_test_db
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.mark = uuid.uuid4().hex[:8]

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def test_0073_reads_again_the_links_with_a_key_and_rewrites_the_posts_own_addresses(self):
        source = insert_scratch_source(self.cur)
        page = PAGE.replace("paper.example.com", f"paper-{self.mark}.example.com")
        gifted = f"{page}?accessToken={JWT}"
        rows = {}
        for name, url, body, links in [
            ("keyed", f"https://letter-{self.mark}.example/p/weekly", f'<p><a href="{gifted}">the story</a></p>', [gifted]),
            ("plain", f"https://letter-{self.mark}.example/p/other", f'<a href="{page}">t</a>', [page]),
        ]:
            self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, url_host, title, content, content_html, links_scanned_at)
                                VALUES (%s, %s, %s, 'letter.example', %s, 'c', %s, now()) RETURNING id""",
                             (source, url, url, name, body))
            rows[name] = self.cur.fetchone()[0]
            for position, target in enumerate(links):
                self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, %s, %s)",
                                 (rows[name], target, "example.com", position))
        # A post whose own address is a gift link, stored by the rule before (normalized_url kept the token).
        own = {}
        for url in (f"https://www.paper-{self.mark}.example.com/a/b?accessToken={JWT}&id=3",
                    f"https://paper-{self.mark}.example.com/c?smid=x&unlocked_article_code=1.a",
                    f"https://paper-{self.mark}.example.com/d?dib={JWT}&dib_tag=se&q=x"):
            old = url.replace("www.", "")
            self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, canonical_url, url_host, title, content, links_scanned_at)
                                VALUES (%s, %s, %s, %s, 'paper.example.com', 'own', 'c', now()) RETURNING id""",
                             (source, url, old.split("?")[0] + "?" + "&".join(sorted(old.split("?")[1].split("&"))), old))
            own[self.cur.fetchone()[0]] = url
        self.cur.execute(MIGRATION.read_text(encoding="utf-8"))
        self.cur.execute("SELECT id, links_scanned_at IS NULL FROM posts WHERE id = ANY(%s)", (list(rows.values()),))
        self.assertEqual(dict(self.cur.fetchall()), {rows["keyed"]: True, rows["plain"]: False})
        StoriesRepository().save_post_links(self.cur, str(rows["keyed"]))   # as fill_missing_links reads it
        self.cur.execute("SELECT target_url, shared_url FROM post_links WHERE post_id = %s", (rows["keyed"],))
        self.assertEqual(self.cur.fetchall(), [(page, gifted)], "one page; the gift link kept for clicking")
        self.cur.execute("SELECT id, url, normalized_url, canonical_url FROM posts WHERE id = ANY(%s)", (list(own),))
        for post_id, url, normalized, canonical in self.cur.fetchall():
            self.assertEqual(url, own[post_id], "the post's own address keeps its token")
            self.assertEqual(normalized, url_normalization.normalize_url(url), url)
            self.assertEqual(canonical, url_normalization.canonicalize_url(url), url)
        self.cur.execute(MIGRATION.read_text(encoding="utf-8"))
        self.cur.execute("SELECT count(*) FROM posts WHERE id = ANY(%s) AND links_scanned_at IS NULL", (list(rows.values()),))
        self.assertEqual(self.cur.fetchone()[0], 0, "a second run reads nothing again")


@requires_test_db
class StoryTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.mark = uuid.uuid4().hex[:8]
        self.service = StoriesService(db_url(), clock=lambda: self.now)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _two_voices(self, page, first, second, *, links=None):
        sources = [insert_source(self.cur, f"{name} {self.mark}", in_main_digest=True) for name in ("Letter", "Forward")]
        posts = []
        for n, (source, href) in enumerate(zip(sources, (first, second))):
            posts.append(insert_post(self.cur, source, f"https://{n}-{self.mark}.example.org/p/on-the-budget",
                                     at=self.now - timedelta(hours=3 - n), title=("A letter this week", "Notes from the desk")[n],
                                     content="Body", html=f'<p><a href="{href}">the story</a></p>',
                                     content_hash=uuid.uuid4().hex, links=None if links is None else [links[n]]))
        return posts

    def _story(self, post_id):
        self.cur.execute("SELECT st.id, st.origin_url FROM story_posts sp JOIN stories st ON st.id = sp.story_id "
                         "WHERE sp.post_id = %s", (post_id,))
        return self.cur.fetchone()

    def test_a_gift_link_and_a_plain_link_are_one_story_its_origin_opens_the_gift_link(self):
        page = PAGE.replace("paper.example.com", f"paper-{self.mark}.example.com")
        gifted = f"{page}?accessToken={JWT}"
        posts = self._two_voices(page, gifted, page)
        while StoriesRepository().fill_missing_links(self.cur):   # the story job's first step reads their HTML
            pass
        self.service.full_on(self.cur)
        first, second = self._story(posts[0]), self._story(posts[1])
        self.assertIsNotNone(first)
        self.assertEqual(first, second, "one story")
        self.assertEqual(first[1], page, "its origin's address has no token")
        item = {"id": str(posts[1])}
        ReaderRepository.attach_stories(self.cur, [item])
        self.assertIsNotNone(item["story"], item)
        self.assertIsNotNone(item["story"]["origin"], item["story"])
        self.assertEqual(item["story"]["origin"]["url"], page)
        self.assertEqual(item["story"]["origin"]["href"], gifted, "the reader opens the gift link")

    def test_a_deploy_s_first_start_reads_the_old_links_again_and_joins_them(self):
        page = PAGE.replace("paper.example.com", f"paper-{self.mark}.example.com")
        gifts = [f"{page}?accessToken={JWT}", f"{page}?gift=abc"]
        posts = self._two_voices(page, *gifts, links=gifts)   # stored as the rules before 0126 read them
        self.service.full_on(self.cur)
        before = (self._story(posts[0]), self._story(posts[1]))
        self.assertTrue(before[0] is None or before[0] != before[1], "before: two addresses")
        self.cur.execute(MIGRATION.read_text(encoding="utf-8"))
        setting = SystemSettingsRepository.get(self.cur, SETTINGS_KEY)[0]
        SystemSettingsRepository.upsert(self.cur, SETTINGS_KEY, {**setting, "rules": "the rules before 0126"})
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        self.service.update(self.cur)                    # the deploy's first start: the rebuild, to the end
        story = self._story(posts[0])
        self.assertIsNotNone(story)
        self.assertEqual(story, self._story(posts[1]), "after: one story")
        self.assertEqual(story[1], page)
        rebuilt = self.service.full_on(self.cur)
        self.assertEqual(rebuilt["classics_changed"], 0, "a full run after it changes nothing")


if __name__ == "__main__":
    unittest.main()
