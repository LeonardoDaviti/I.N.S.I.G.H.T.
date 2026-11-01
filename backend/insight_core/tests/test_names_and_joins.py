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

from insight_core.db.repo_posts import PostsRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, requires_db, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.tests.test_news import T0, followed, post
from insight_core.utils.news_rules import names, news, surges, tally
from insight_core.utils.post_links import extract_links
from insight_core.tests import test_story_trees as trees
from insight_core.utils.story_rules import group, page_aliases, title_key
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
        self.assertIn("gpt 6.1 terra", names("OpenAI выпустили GPT-6.1 TerraНемного"))
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


class NameSeparatorsTests(unittest.TestCase):
    """A name's parts are one name whatever separates them; a post joins the News of its first name."""

    def test_hyphen_space_underscore_and_a_dot_that_isnt_a_decimal_are_one(self):
        self.assertTrue(names("GPT-6.1 Terra is here") & names("OpenAI выпустили GPT 6.1 Terra") & {"gpt 6.1 terra"})
        self.assertIn("flux 3 image", names("Welcome FLUX.3 Image Klein") & names("FLUX 3 Image Klein weights"))
        self.assertIn("qwen3.6 27b", names("Qwen3.6-27B is out now!") & names("Can I install Qwen3.6 27b?"))
        self.assertIn("gpt 6.1 sol", names("GPT_6.1 Sol in the API"), "a version's decimal stays")

    def test_terra_in_two_spellings_is_one_news_row(self):
        everyone = followed(*[f"s{i}" for i in range(1, 7)])
        posts = [post("a", "s1", title="Introducing GPT-6.1 Terra"), post("b", "s2", hours=1, title="GPT-6.1 Terra benchmarks"),
                 post("c", "s3", hours=2, title="OpenAI выпустили GPT 6.1 Terra")]
        [row] = news(posts, group(posts), surges(posts, everyone))
        self.assertEqual([p.id for p in row.posts], ["a", "b", "c"], "the hyphen and the space are one name")

    def test_a_post_naming_two_releases_joins_the_first_it_names(self):
        everyone = followed(*[f"s{i}" for i in range(1, 8)])
        posts = [post("g1", "s1", title="Grok 4.7 is out"), post("g2", "s2", hours=1, title="Grok 4.7 benchmarks"),
                 post("g3", "s3", hours=2, title="Grok 4.7 is cheap"),
                 post("o1", "s4", hours=3, title="Opus 5.5 is out"), post("o2", "s5", hours=4, title="Opus 5.5 benchmarks"),
                 post("both", "s6", hours=5, title="Grok 4.7 is a bit better than Opus 5.5")]
        rows = sorted(sorted(p.id for p in s.posts) for s in news(posts, group(posts), surges(posts, everyone)))
        self.assertEqual(rows, [["both", "g1", "g2", "g3"], ["o1", "o2"]], "not one row of two releases")


class PublicationLinksTests(unittest.TestCase):
    def test_a_link_to_another_host_of_its_site_is_kept_its_own_host_is_not(self):
        html = ('<a href="https://gwern.writers.test/p/scaling">Gwern</a> <a href="https://gary.writers.test/p/older">mine</a>'
                ' <a href="https://writers.test/about">the platform</a>')
        self.assertEqual([link.url for link in extract_links(html, "https://gary.writers.test/p/new", "site")],
                         ["https://gwern.writers.test/p/scaling", "https://writers.test/about"])


class PostAboutOneStoryTests(unittest.TestCase):
    """A platform's post with 3+ links whose first link into a story is its origin is a member (A6)."""

    ORIGIN = "https://mistral.ai/news/mistral-large-4-oss"
    MODEL = "https://huggingface.co/mistralai/Mistral-Large-4-1T-A52B"

    def story(self, kind="reddit", extra=()):
        links = [("https://huggingface.co/ggml-org/Mistral-Large-4-GGUF", None), ("https://huggingface.co/unsloth/m-GGUF", None),
                 (self.ORIGIN, None), *extra, (self.MODEL, None)]
        posts = [trees.post("a", "reddit-sub", kind="reddit", links=[(self.ORIGIN, None)]),
                 trees.post("b", "akhaliq", kind="x", hours=0.2, links=[(self.ORIGIN, None), (self.MODEL, None)]),
                 trees.post("c", "reddit-sub2" if kind == "reddit" else "blog", kind=kind, hours=0.3, links=links)]
        return group(posts)

    def test_a_release_post_listing_links_is_a_member(self):
        [story] = self.story()
        self.assertEqual(sorted(p.id for p in story.posts), ["a", "b", "c"])
        self.assertEqual(story.mentions, set())
        self.assertEqual(story.parents["c"], (None, self.ORIGIN, "citation"))

    def test_an_article_or_a_post_linking_another_story_stays_a_mention(self):
        [story] = self.story(kind="site")
        self.assertEqual((sorted(p.id for p in story.posts), story.mentions), (["a", "b"], {"c"}), "an article: a roundup")
        other = [trees.post("d", "d", hours=0.1, links=[("https://other.test/2026/news", None)]),
                 trees.post("e", "e", hours=0.1, links=[("https://other.test/2026/news", None)])]
        stories = group([*other, *[p for s in self.story(extra=[("https://other.test/2026/news", None)]) for p in s.posts]])
        self.assertEqual(sorted(sorted(p.id for p in s.posts) for s in stories), [["a", "b"], ["d", "e"]],
                         "it links two stories: a roundup of both")


class OnePageTwoPathsTests(unittest.TestCase):
    """One page under two paths of its own site joins by address (A7)."""

    OWN = "https://anthropic.com/research/redesigning-source-control"
    OTHER = "https://anthropic.com/engineering/redesigning-source-control"

    def posts(self, link):
        return [trees.post("own", "anthropic", url=self.OWN, home="anthropic.com", site="anthropic.com"),
                trees.post("a", "adel", kind="telegram", hours=1, links=[(link, None)]),
                trees.post("b", "simon", hours=2, links=[(link, None)])]

    def test_another_section_and_a_language_are_the_page(self):
        story = trees.only(self.posts(self.OTHER))
        self.assertEqual((story.origin_url, trees.parents(story)),
                         (None, {"own": (None, None), "a": ("own", "citation"), "b": ("own", "citation")}))
        self.assertEqual(page_aliases(self.posts("https://anthropic.com/ru-RU/news/redesigning-source-control?ref=x")),
                         {"https://anthropic.com/ru-RU/news/redesigning-source-control?ref=x": self.OWN})

    def test_a_reference_page_an_id_or_a_series_are_other_pages(self):
        for link in ("https://anthropic.com/docs/redesigning-source-control", "https://anthropic.com/engineering/2026-10",
                     "https://anthropic.com/research/source-control"):
            self.assertEqual(page_aliases(self.posts(link)), {}, link)
        weekly = [trees.post(f"w{n}", "nesbitt", url=f"https://nesbitt.test/2026/10/{n}/this-week-in-source-control",
                             home="nesbitt.test", site="nesbitt.test") for n in (21, 28)]
        link = trees.post("l", "other", links=[("https://nesbitt.test/2026/10/14/this-week-in-source-control", None)])
        self.assertEqual(page_aliases([*weekly, link]), {}, "another week of a series, under its date")


class SavedIsNoVoiceTests(unittest.TestCase):
    """A Saved page is never a voice; it can be the origin, shown as the page (A8)."""

    PAGE = "https://github.com/unslothai/unsloth"

    def saved(self):
        return trees.post("saved", "saved-source", kind="saved", url=self.PAGE, hours=40, title="GitHub - unslothai/unsloth")

    def test_a_saved_page_and_one_voice_are_no_story(self):
        self.assertEqual(group([self.saved(), trees.post("dh", "danielhanchen", kind="x", links=[(self.PAGE, "saved")])]), [])

    def test_a_saved_origin_is_the_page_never_the_first_post(self):
        posts = [self.saved(), trees.post("dh", "danielhanchen", kind="x", links=[(self.PAGE, "saved")]),
                 trees.post("tg", "toshoseti", kind="telegram", hours=1, links=[(self.PAGE, "saved")])]
        story = trees.only(posts)
        self.assertEqual(story.voices, 2)
        self.assertEqual((story.origin_url, story.origin_title, story.origin_linked_by),
                         (self.PAGE, "GitHub - unslothai/unsloth", 2))
        self.assertEqual(story.parents["saved"], (None, self.PAGE, "address"))
        self.assertEqual({story.parents["dh"][:2], story.parents["tg"][:2]}, {(None, self.PAGE)})
        self.assertEqual(tally(story.posts, story.roles, []), (2, 0, 0), "News counts the two voices")


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
        return insert_source(self.cur, name, handle=handle, platform=platform, in_main_digest=True)

    def post(self, source, url, *, hours_ago, html="", title="A post", text=None, author=None):
        return str(insert_post(self.cur, source, url, at=self.now - timedelta(hours=hours_ago), title=title,
                               content=text or f"Body {uuid.uuid4().hex}", html=html, author=author,
                               content_hash=uuid.uuid4().hex if text is None else f"hash-{text}"))

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


MIGRATION_0052 = BACKEND_DIR / "insight_core" / "db" / "migrations" / "0052_names_and_joins.sql"
BODY = "If the future is to hinge on AI, it stands to reason that AI company CEOs are in a good position. " * 4


class OnePostTwoAddressesTests(JobCase):
    """One source, one title, one body, two addresses is one post (migration 0052 and the saver)."""

    def test_a_trailing_slash_in_a_query_value_is_the_same_address(self):
        self.assertEqual(normalize_url("https://devblogs.test/oldnewthing/20260921-00/?p=112711/"),
                         normalize_url("https://devblogs.test/oldnewthing/20260921-00/?p=112711"))
        self.assertEqual(normalize_url("https://a.test/x?next=/"), "https://a.test/x?next=%2F", "a lone / stays")

    def _row(self, source, url, *, days_ago, title="How an AI company CEO could take over", text=BODY, hash_=None):
        self.cur.execute(
            "INSERT INTO posts (source_id, url, normalized_url, title, content, content_hash, published_at, fetched_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, now() - make_interval(days => 30), now() - make_interval(hours => %s))"
            " RETURNING id", (source, url, normalize_url(url), title, text, hash_ or uuid.uuid4().hex, days_ago * 24))
        return self.cur.fetchone()[0]

    @requires_test_db
    def test_the_migration_keeps_the_newer_address_with_the_reading_state(self):
        blog = self.source("ai futures", f"https://blog.{self.mark}.test/feed")
        tweets = self.source("tweets", f"https://nitter.test/{self.mark}/rss")
        old = self._row(blog, f"https://blog.ai-{self.mark}.test/p/ceo", days_ago=200, hash_="h1")
        new = self._row(blog, f"https://blog.ai{self.mark}.test/p/ceo", days_ago=100, hash_="h1")
        full = self._row(blog, f"https://blog.{self.mark}.test/p/full", days_ago=50, title="Severance")
        teaser = self._row(blog, f"https://blog.{self.mark}.test/p/severance", days_ago=10, title="Severance",
                           text=BODY[:80] + "…")
        slash = self._row(blog, f"https://blog.{self.mark}.test/x?p=1", days_ago=20, title="Filetime", hash_="h2")
        slash2 = self._row(blog, f"https://blog.{self.mark}.test/x?p=1/", days_ago=5, title="Filetime", hash_="h2")
        self.cur.execute("UPDATE posts SET normalized_url = normalized_url || '%%2F' WHERE id = %s", (slash2,))
        series = [self._row(blog, f"https://blog.{self.mark}.test/issues/{n}", days_ago=n, title="not much happened today",
                            text=f"Issue {n}. {BODY}") for n in (1, 2)]
        replies = [self._row(tweets, f"https://x.com/{self.mark}/status/21150008012908014{n}", days_ago=n,
                             title="R to @someone: x.com/someone/status…", hash_="h3") for n in (1, 2)]
        self.cur.execute("INSERT INTO post_reader_state (post_id, read_at, later_at) VALUES (%s, now(), now())", (old,))
        self.cur.execute("INSERT INTO post_notes (post_id, notes_markdown) VALUES (%s, 'mine')", (old,))
        self.cur.execute(MIGRATION_0052.read_text(encoding="utf-8"))
        self.cur.execute("SELECT id, url, length(content) FROM posts WHERE source_id = ANY(%s::uuid[])", ([blog, tweets],))
        left = {r[0]: r[1:] for r in self.cur.fetchall()}
        self.assertEqual(set(left), {new, teaser, slash2, *series, *replies})
        self.assertEqual(left[teaser], (f"https://blog.{self.mark}.test/p/severance", len(BODY)),
                         "the newer address, with the longer text")
        self.cur.execute("SELECT read_at IS NOT NULL, later_at IS NOT NULL FROM post_reader_state WHERE post_id = %s", (new,))
        self.assertEqual(self.cur.fetchone(), (True, True), "read and Later carried over")
        self.cur.execute("SELECT notes_markdown FROM post_notes WHERE post_id = %s", (new,))
        self.assertEqual(self.cur.fetchone(), ("mine",))
        self.cur.execute("SELECT normalized_url FROM posts WHERE id = %s", (slash2,))
        self.assertEqual(self.cur.fetchone(), (f"https://blog.{self.mark}.test/x?p=1",))
        self.cur.execute(MIGRATION_0052.read_text(encoding="utf-8"))
        self.cur.execute("SELECT count(*) FROM posts WHERE source_id = ANY(%s::uuid[])", ([blog, tweets],))
        self.assertEqual(self.cur.fetchone(), (len(left),), "a second run merges nothing")

    def test_the_saver_moves_the_post_to_its_newer_address(self):
        repo = PostsRepository(db_url())
        blog = self.source("lcamtuf", f"https://lcamtuf.{self.mark}.test/feed")
        first, _ = repo.upsert_post(self.cur, {"url": f"https://lcamtuf.{self.mark}.test/p/meta", "title": "Meta: 7,000",
                                               "content": BODY, "date": self.now}, blog)
        again, inserted = repo.upsert_post(self.cur, {"url": f"https://blog.{self.mark}.test/p/meta", "title": "Meta: 7,000",
                                                      "content": BODY[:60], "date": self.now}, blog)
        self.assertEqual((again, inserted), (first, False))
        self.cur.execute("SELECT url, content FROM posts WHERE id = %s", (first,))
        self.assertEqual(self.cur.fetchone(), (f"https://blog.{self.mark}.test/p/meta", BODY),
                         "the newer address; a teaser of the text leaves the text")
        other, inserted = repo.upsert_post(self.cur, {"url": f"https://blog.{self.mark}.test/p/meta-2", "title": "Meta: 7,000",
                                                      "content": "Another text altogether.", "date": self.now}, blog)
        self.assertTrue(inserted, "another body is another post")
        tweets = self.source("tweets", f"https://nitter.test/{self.mark}/rss")
        a, _ = repo.upsert_post(self.cur, {"url": f"https://x.com/{self.mark}/status/211500080129080141", "title": "R to @a: ok",
                                           "content": "x.com/a/status…", "date": self.now}, tweets)
        b, inserted = repo.upsert_post(self.cur, {"url": f"https://x.com/{self.mark}/status/211500080129080142",
                                                  "title": "R to @a: ok", "content": "x.com/a/status…", "date": self.now}, tweets)
        self.assertTrue(inserted and a != b, "two tweets with the same words are two posts")


if __name__ == "__main__":
    unittest.main()
