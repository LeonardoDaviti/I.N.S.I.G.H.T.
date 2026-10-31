"""One voice per publication, and roundups that point at the story (issue 0069, part C).

- A website source's voice is its publication: the host it publishes at, without `www.` (most of
  its posts' hosts, else its address's). Writers on one platform are voices of their own; two
  sources at one host are one. Its site still says where it is (Discover's places, sections).
- Classics: a page's own voices are its publication's and its site's.

The rules as pure functions; the job on the database in one transaction per test, rolled back.
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

from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, insert_scratch_source, requires_db
from insight_core.utils.news_rules import Citation, classics
from insight_core.utils.post_links import publication_of, site_of
from insight_core.utils.url_normalization import normalize_url

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


class PublicationRulesTests(unittest.TestCase):
    def test_a_publication_is_its_host_without_www(self):
        self.assertEqual([publication_of(h) for h in ("www.Example.com", "garymarcus.substack.com", "blog.ncase.me", "")],
                         ["example.com", "garymarcus.substack.com", "blog.ncase.me", ""])
        self.assertEqual(site_of("garymarcus.substack.com"), "substack.com", "its site is still the site")

    def test_a_classics_own_voices_are_its_publication_and_its_site(self):
        def cite(voice, days, target):
            return Citation(voice=voice, name=voice, source_id=voice, t=T0 + timedelta(days=days), target=target)
        page = "https://gwern.substack.test/p/the-scaling-hypothesis"
        [c] = classics([cite("site:a.substack.test", 0, page), cite("site:gwern.substack.test", 5, page),
                        cite("site:b.substack.test", 10, page), cite("site:a.substack.test", 200, page)], {})
        self.assertEqual([x["voice"] for x in c.citers], ["site:a.substack.test", "site:b.substack.test"],
                         "two other writers on the platform count; the page's own publication doesn't")
        paper = "https://cdn.lab.test/papers/the-model-card"
        self.assertEqual(classics([cite("site:lab.test", 0, paper), cite("site:b.test", 10, paper),
                                   cite("site:lab.test", 200, paper)], {}), [],
                         "the site's own publication linking it is no second voice")


@requires_db
class PublicationVoicesJobTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc)
        self.mark = uuid.uuid4().hex[:8]
        self.service = StoriesService(db_url(), clock=lambda: self.now)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _source(self, name, handle_host):
        source = insert_scratch_source(self.cur, in_main_digest=True)
        self.cur.execute("UPDATE sources SET handle_or_url = %s, settings = jsonb_build_object('display_name', %s::text)"
                         " WHERE id = %s", (f"https://{handle_host}/feed?{uuid.uuid4().hex}", name, source))
        return source

    def _post(self, source, host, *, hours_ago, html):
        url = f"https://{host}/p/{uuid.uuid4().hex}"
        self.cur.execute(
            """INSERT INTO posts (source_id, url, normalized_url, url_host, title, content, content_html, content_hash,
                                  published_at)
               VALUES (%s, %s, %s, %s, 'A post', 'Body', %s, %s, %s) RETURNING id""",
            (source, url, normalize_url(url), host, html, uuid.uuid4().hex, self.now - timedelta(hours=hours_ago)))
        return str(self.cur.fetchone()[0])

    def _job(self):
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        self.service.regroup(self.cur, cutoff=None)

    def _voices(self, *posts):
        self.cur.execute("SELECT post_id::text, story_id::text, voice FROM story_posts WHERE post_id = ANY(%s::uuid[])",
                         (list(posts),))
        return {r[0]: (r[1], r[2]) for r in self.cur.fetchall()}

    def test_two_writers_on_one_platform_are_two_voices_and_make_a_story(self):
        platform = f"writers-{self.mark}.test"
        page = f'<p><a href="https://paper-{self.mark}.test/2026/01/the-paper">the paper</a></p>'
        gary, gwern = self._source("Gary", f"gary.{platform}"), self._source("Gwern", f"gwern.{platform}")
        a = self._post(gary, f"gary.{platform}", hours_ago=5, html=page)
        b = self._post(gwern, f"gwern.{platform}", hours_ago=3, html=page)
        self.assertEqual({site_of(f"gary.{platform}"), site_of(f"gwern.{platform}")}, {platform}, "one site")
        facts = SourceFacts(self.cur)
        self.assertEqual((facts.publication(gary), facts.own_site(gary)), (f"gary.{platform}", platform))
        self._job()
        voices = self._voices(a, b)
        self.assertEqual(voices[a][0], voices[b][0], "one story, linked by two voices")
        self.assertEqual({voices[a][1], voices[b][1]}, {f"site:gary.{platform}", f"site:gwern.{platform}"})

    def test_two_sources_at_one_host_are_one_voice(self):
        host = f"one-{self.mark}.test"
        page = f'<p><a href="https://paper-{self.mark}.test/2026/01/the-paper">the paper</a></p>'
        feed, watch = self._source("Its feed", f"feeds.{host}"), self._source("Its page watch", f"www.{host}")
        a = self._post(feed, host, hours_ago=5, html=page)
        b = self._post(watch, f"www.{host}", hours_ago=3, html=page)
        facts = SourceFacts(self.cur)
        self.assertEqual((facts.publication(feed), facts.publication(watch)), (host, host),
                         "its posts' host, not its feed's address; without www.")
        self._job()
        self.assertEqual(self._voices(a, b), {}, "one voice linking a page twice is no story")


if __name__ == "__main__":
    unittest.main()
