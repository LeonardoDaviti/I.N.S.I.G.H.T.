"""Names that surge, joins that hold (issue 0070, part A).

- A name's burst is made of the sources followed for the whole 30 days before it: a newer source's
  posts join it but don't start it, make it or age the name; 2+ of its voices didn't say it then.
- A later burst of 3+ voices new to a name surges too, unless a few voices keep saying it.
- Titles are compared as plain letters (NFKC), and a word glued to another script's capital splits.

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
from insight_core.tests.test_news import T0, followed, post
from insight_core.utils.news_rules import names, surges
from insight_core.utils.post_links import extract_links
from insight_core.utils.story_rules import title_key
from insight_core.utils.url_normalization import normalize_url


def said(source, hours, title="Gemini 4 Carbon is coming", n=1):
    return [post(f"{source}{hours}-{i}", source, hours=hours + i, title=title) for i in range(n)]


def launch(*sources, hours=0, title="Gemini 4 Carbon is here"):
    return [post(f"{s}@{hours}", s, hours=hours + i, title=title) for i, s in enumerate(sources)]


class NameEvidenceTests(unittest.TestCase):
    def test_a_newer_source_joins_a_burst_but_doesnt_make_or_age_it(self):
        # pankajkumar_dev, added 13 days before, leaked the name 11 times; then the launch.
        leaks = said("pankaj", -24 * 9, n=11)
        everyone = {**followed("s1", "s2", "s3"), "pankaj": T0 - timedelta(days=13)}
        [found] = [s for s in surges(leaks + launch("s1", "s2", "s3", "pankaj"), everyone) if s.name == "gemini 4 carbon"]
        self.assertEqual(found.posts, ["s1@0", "s2@0", "s3@0", "pankaj@0"], "the leaks don't age it; the launch post joins")
        self.assertEqual([s.name for s in surges(launch("s1", "s2", "pankaj", "pankaj"), everyone)], [],
                         "a newer source's posts don't make the 3 posts")
        self.assertEqual([s.name for s in surges(leaks + launch("pankaj", "s1", "s2", "s3"), everyone)
                          if s.name == "gemini 4 carbon"], ["gemini 4 carbon"], "nor start it: it starts at s1")

    def test_two_of_its_voices_are_new_to_the_name(self):
        everyone = followed("s1", "s2", "s3")
        once = said("s1", -100)
        self.assertEqual(surges(once + launch("s1", "s2", "s1"), everyone), [], "said once by s1: s2 alone is new")
        self.assertEqual([s.name for s in surges(once + launch("s1", "s2", "s3"), everyone)], ["gemini 4 carbon"])


class NameWaveTests(unittest.TestCase):
    def test_a_later_wave_of_three_new_voices_surges(self):
        # Mistral Large 4: launched on 6 Oct, open weights on 29 Oct.
        everyone = followed(*[f"s{i}" for i in range(1, 8)])
        first = launch("s1", "s2", "s3", title="Mistral Large 4 is out")
        weights = launch("s4", "s5", "s6", "s7", hours=24 * 23, title="Mistral Large 4 is now open weight")
        self.assertEqual([(s.name, s.posts) for s in surges(first + weights, everyone) if s.name == "mistral large 4"],
                         [("mistral large 4", ["s1@0", "s2@0", "s3@0"]),
                          ("mistral large 4", ["s4@552", "s5@552", "s6@552", "s7@552"])])
        self.assertEqual([s.at for s in surges(first + weights[:3], everyone) if s.name == "mistral large 4"], [T0],
                         "3 new voices, as many as the 30 days before: a few voices saying it again")
        two_new = launch("s1", "s4", "s5", hours=24 * 23, title="Mistral Large 4 is now open weight")
        self.assertEqual([s.at for s in surges(first + two_new, everyone) if s.name == "mistral large 4"], [T0],
                         "two new voices and one that said it: no wave")

    def test_a_series_a_few_voices_keep_saying_is_no_wave(self):
        # "Notes from May 2026", "rose bud thorn - may 2026": monthly posts of the same voices.
        everyone = followed(*[f"s{i}" for i in range(1, 9)])
        month = [p for i in range(1, 6) for p in said(f"s{i}", -24 * (25 - i), title="Notes from May 2026")]
        end = launch("s6", "s7", "s8", title="Notes from May 2026")
        self.assertEqual([s.name for s in surges(month + end, everyone) if s.at == T0], [],
                         "3 new voices, but 5 said it in the 30 days before")


class ComparedAsPlainLettersTests(unittest.TestCase):
    def test_styled_letters_are_plain_letters(self):
        self.assertIn("lfm3", names("Introducing 𝙻𝙵𝙼𝟹: our new generation"))
        self.assertEqual(title_key("𝙸𝚗𝚝𝚛𝚘𝚍𝚞𝚌𝚒𝚗𝚐 𝙻𝙵𝙼𝟹 every modality for you"),
                         title_key("Introducing LFM3 every modality for you"))

    def test_a_word_glued_to_another_scripts_capital_splits(self):
        self.assertIn("gemini 4 carbon", names("Google анонсировали Gemini 4 CarbonМодель заняла первое место"))
        self.assertIn("gpt-6.1 terra", names("OpenAI выпустили GPT-6.1 TerraНемного"))
        self.assertIn("openai codex 2", names("OpenAI Codex 2 is out"), "a capital inside one script stays in its word")


@requires_db
class SearchPlainLettersTests(unittest.TestCase):
    def test_the_index_and_the_query_read_plain_letters(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            def finds(title, q):
                cur.execute("SELECT post_search_vector(%s, '', '') @@ search_query(%s)", (title, q))
                return cur.fetchone()[0]
            self.assertTrue(finds("Introducing 𝙻𝙵𝙼𝟹: our new generation", "LFM3"))
            self.assertTrue(finds("Introducing LFM3", "𝙻𝙵𝙼𝟹"))
            self.assertTrue(finds("Kimi\u00a0K3.1 Pro", "kimi 3.1"), "a no-break space is a space")
            cur.execute("SELECT search_vector_version()")
            self.assertEqual(cur.fetchone()[0], 3, "every vector is made again")


class PublicationLinksTests(unittest.TestCase):
    def test_a_link_to_another_host_of_its_site_is_kept_its_own_host_is_not(self):
        html = ('<a href="https://gwern.writers.test/p/scaling">Gwern</a> <a href="https://gary.writers.test/p/older">mine</a>'
                ' <a href="https://writers.test/about">the platform</a>')
        self.assertEqual([link.url for link in extract_links(html, "https://gary.writers.test/p/new", "site")],
                         ["https://gwern.writers.test/p/scaling", "https://writers.test/about"])


@requires_db
class JobCase(unittest.TestCase):
    """The story job on the caller's transaction, rolled back."""

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

    def source(self, name, handle, platform="rss"):
        source = insert_scratch_source(self.cur, platform=platform, in_main_digest=True)
        self.cur.execute("UPDATE sources SET handle_or_url = %s, settings = jsonb_build_object('display_name', %s::text)"
                         " WHERE id = %s", (handle, name, source))
        return source

    def post(self, source, url, *, hours_ago, html="", title="A post", text=None, author=None):
        self.cur.execute(
            """INSERT INTO posts (source_id, url, normalized_url, url_host, title, content, content_html, content_hash,
                                  published_at, author)
               VALUES (%s, %s, %s, split_part(split_part(%s, '://', 2), '/', 1), %s, %s, %s, %s, %s, %s) RETURNING id""",
            (source, url, normalize_url(url), url, title, text or f"Body {uuid.uuid4().hex}", html,
             uuid.uuid4().hex if text is None else f"hash-{text}", self.now - timedelta(hours=hours_ago), author))
        return str(self.cur.fetchone()[0])

    def job(self):
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        self.service.regroup(self.cur, cutoff=None)

    def stories(self, *posts):
        self.cur.execute("SELECT post_id::text, story_id::text, role, parent_id::text, parent_reason, parent_url"
                         " FROM story_posts WHERE post_id = ANY(%s::uuid[])", (list(posts),))
        return {r[0]: r[1:] for r in self.cur.fetchall()}


class PublicationCitesJobTests(JobCase):
    def test_a_writer_linking_another_on_their_platform_cites_them(self):
        platform = f"writers-{self.mark}.test"
        gary = self.source("Gary", f"https://gary.{platform}/feed")
        gwern = self.source("Gwern", f"https://gwern.{platform}/feed")
        essay = self.post(gwern, f"https://gwern.{platform}/p/scaling", hours_ago=10)
        reply = self.post(gary, f"https://gary.{platform}/p/reply", hours_ago=5,
                          html=f'<p>As <a href="https://gwern.{platform}/p/scaling">Gwern says</a></p>')
        self.assertIn(platform, SourceFacts(self.cur).shared_sites, "two of your sources publish at its hosts")
        self.job()
        found = self.stories(essay, reply)
        self.assertEqual(found[reply][0], found[essay][0])
        self.assertEqual(found[reply][2:4], (essay, "citation"))

    def test_a_publishers_other_hosts_are_its_own(self):
        site = f"lab-{self.mark}.test"
        blog = self.source("The lab's blog", f"https://blog.{site}/feed")
        other = self.source("Someone", f"https://someone-{self.mark}.test/feed")
        tools = f"https://tools.{site}/2026/01/a-new-tool-for-you"
        a = self.post(blog, f"https://blog.{site}/2026/01/news", hours_ago=10, html=f'<a href="{tools}">our tool</a>')
        b = self.post(other, f"https://someone-{self.mark}.test/2026/01/x", hours_ago=9, html=f'<a href="{tools}">their tool</a>')
        self.assertNotIn(site, SourceFacts(self.cur).shared_sites)
        self.job()
        self.cur.execute("SELECT boilerplate FROM post_links WHERE post_id = %s", (a,))
        self.assertEqual(self.cur.fetchall(), [(True,)], "stored, and marked its own site's")
        self.assertEqual(self.stories(a, b), {}, "so it joins nothing")


if __name__ == "__main__":
    unittest.main()
