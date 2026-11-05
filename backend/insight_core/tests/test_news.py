"""News and Classics (issue 0051): the score, the name rule, News stories, classics, cited again,
Hide, Background, Discover's order and track scoping.

The rules are tested as pure functions; the job and the views on the database in one transaction
per test, rolled back (the job regroups every post it sees, the test's own included, and nothing
of it is kept). Assertions are scoped to the test's own rows. Discover's order needs committed
rows (its service opens its own connections): that class runs only on a `_test` database.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_stories import StoriesRepository
from insight_core.services.news_service import NewsService
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_db, requires_test_db
from insight_core.tests._stories import insert_post, insert_source, story_post
from insight_core.utils.classic_rules import Citation, classics
from insight_core.utils.news_rules import lead, names, news, phrases, score, surges, tally
from insight_core.utils.post_links import is_reference
from insight_core.utils.story_rules import StoryPost, group
from insight_core.utils.url_normalization import normalize_url

T0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
LONG_AGO = T0 - timedelta(days=400)


post = partial(story_post, at=T0, chars=0)


def followed(*sources, since=LONG_AGO):
    return {s: since for s in sources}


# ---- the score --------------------------------------------------------------------------------


class ScoreTests(unittest.TestCase):
    def test_reports_shares_and_mentions_each_voice_once_in_its_strongest_role(self):
        posts = [post("a", "lab"), post("b", "tg", kind="telegram", hours=1), post("c", "lab", hours=2),
                 post("d", "blog", hours=3)]
        roles = {"a": "share", "b": "share", "c": "report", "d": "report"}
        digest = post("m1", "tg", kind="telegram", hours=4)      # tg shared it already: not a mention too
        other = post("m2", "weekly", hours=5)
        self.assertEqual(tally(posts, roles, [digest, other, post("m3", "weekly", hours=6)]), (2, 1, 1),
                         "lab once, as its report; weekly's two roundups are one voice")
        self.assertEqual(score(2, 1, 1), 3.0)
        self.assertEqual(score(4, 1, 1), 5.0, "4 sources · 1 share · in 1 roundup")

    def test_the_lead_is_the_first_report_else_the_first_share(self):
        self.assertEqual(lead([("a", "share"), ("b", "report"), ("c", "report")]), "b")
        self.assertEqual(lead([("a", "share"), ("b", "share")]), "a")
        self.assertIsNone(lead([]))

    def test_a_roundup_leads_no_row_with_a_report_but_an_origin_always_leads(self):
        posts = [("digest", "report"), ("a", "share"), ("b", "report")]
        self.assertEqual(lead(posts, roundups=["digest"]), "b", "issue 0083: the weekly digest is passed over")
        self.assertEqual(lead(posts, origins=["digest"], roundups=["digest"]), "digest", "its origin leads")
        self.assertEqual(lead([("digest", "report"), ("a", "share")], roundups=["digest"]), "a",
                         "a vendor's roundup gives way to the share of the release's page")
        self.assertEqual(lead([("r1", "report"), ("r2", "report")], roundups=["r1", "r2"]), "r1")

    def test_without_an_origin_the_first_share_of_its_page_leads(self):
        """Issue 0103: no post roots the row (its stories start at an outside page): the first post
        sharing that page leads, before the first report. An origin still leads; a roundup never does."""
        posts = [("early", "share"), ("hub", "share"), ("talk", "report"), ("blog", "report")]
        self.assertEqual(lead(posts, sharers=["hub", "blog"]), "hub", "the release page's share, not the later complaint")
        self.assertEqual(lead(posts), "talk", "no page shared: the first report, as before")
        self.assertEqual(lead(posts, origins=["blog"], sharers=["hub"]), "blog", "an origin always leads")
        self.assertEqual(lead(posts, roundups=["hub"], sharers=["hub", "blog"]), "talk",
                         "a roundup sharing the page never leads")
        self.assertEqual(lead([("first", "report"), ("hub", "share"), ("blog", "report")], sharers=["hub", "blog"]),
                         "first", "a share after the first report doesn't pass over it")
        self.assertEqual(lead([("hub", "share")], roundups=["hub"], sharers=["hub"]), "hub", "nothing else: as before")


# ---- names in titles --------------------------------------------------------------------------


class NameTests(unittest.TestCase):
    def test_what_is_a_name(self):
        self.assertEqual(names("Valve shows the Steam Frame"), {"steam frame"})
        self.assertIn("gpt 6", names("GPT-6 is out"), "one word mixing letters and digits (its hyphen a space, 0070)")
        self.assertIn("a01", names("the a01 board"))
        self.assertIn("opus 5.5", names("Claude Opus 5.5 today"))
        self.assertNotIn("valve", names("Valve Steam Frame"), "one word without a digit")
        self.assertEqual(names("the first pc with ai"), set(), "lowercase words are not names")
        self.assertEqual(names("2026 10 5"), set(), "pure numbers")
        self.assertEqual(names("128GB laptop, 30B model"), set(), "a word starting with a digit is a size")
        self.assertIn("k3", names("Kimi K3 is out"))
        self.assertNotIn("frame of", names("Frame Of Mind"), "a name never ends on a small word")

    def burst(self, title="Steam Frame is here", *, sources=("s1", "s2", "s3"), hours=(0, 5, 30), kind="site"):
        return [post(f"{source}-{n}", source, hours=h, kind=kind, title=title)
                for n, (source, h) in enumerate(zip(sources, hours))]

    def test_three_posts_of_two_voices_in_48_hours_surge(self):
        found = surges(self.burst(), followed("s1", "s2", "s3"))
        self.assertEqual([(s.name, s.posts) for s in found if s.name == "steam frame"],
                         [("steam frame", ["s1-0", "s2-1", "s3-2"])])

    def test_too_few_posts_or_voices_or_too_slow(self):
        self.assertEqual(surges(self.burst(sources=("s1", "s2"), hours=(0, 5)), followed("s1", "s2")), [], "2 posts")
        self.assertEqual(surges(self.burst(sources=("s1", "s1", "s1")), followed("s1")), [], "one voice")
        self.assertEqual(surges(self.burst(hours=(0, 30, 60)), followed("s1", "s2", "s3")), [], "over 48 hours")

    def test_a_lowercase_word_never_surges(self):
        self.assertEqual(surges(self.burst("the new pc is here"), followed("s1", "s2", "s3")), [])

    def test_a_new_sources_archive_is_no_burst(self):
        posts = self.burst()
        self.assertEqual([s.name for s in surges(posts, {**followed("s1", "s2"), "s3": T0 - timedelta(days=10)})], [],
                         "s3 was added 10 days before: its archive")
        self.assertEqual([s.name for s in surges(posts, followed("s1", "s2", "s3", since=T0 - timedelta(days=31)))],
                         ["steam frame"])

    def test_a_name_already_in_use_does_not_surge(self):
        # Measured on the server's data: a name said twice or more in the 30 days before its burst
        # was a real story about a quarter of the time ("has been", "world cup", "open weights").
        said = [post(f"u{n}", "s1", hours=-78 - 30 * n, title="Steam Frame rumours") for n in range(2)]
        everyone = followed("s1", "s2", "s3")
        self.assertEqual(surges(said + self.burst(), everyone), [], "said twice before")
        self.assertEqual([s.name for s in surges(said[:1] + self.burst(), everyone)], ["steam frame"], "said once")
        long_ago = [post("old", "s1", hours=-24 * 40, title="Steam Frame rumours"),
                    post("old2", "s2", hours=-24 * 35, title="Steam Frame rumours")]
        self.assertEqual([s.name for s in surges(long_ago + self.burst(), everyone)], ["steam frame"],
                         "more than 30 days before does not count")

    def test_a_shorter_name_inside_a_longer_one_is_dropped(self):
        posts = self.burst("Meta VR Glasses are here")
        self.assertEqual([s.name for s in surges(posts, followed("s1", "s2", "s3"))], ["meta vr glasses"],
                         "vr glasses covers the same posts")
        more = posts + [post("s4-9", "s4", hours=6, title="VR Glasses for everyone")]
        self.assertEqual(sorted(s.name for s in surges(more, followed("s1", "s2", "s3", "s4"))),
                         ["meta vr glasses", "vr glasses"], "a longer name covering fewer posts keeps both")

    def test_a_name_said_inside_a_joined_word_is_in_its_burst(self):
        # Issue 0083: a repo's name ("org/Model-V4.1-Flash-1017") says "flash 1017"; it was one word.
        posts = self.burst("Model V4.1 Flash 1017 is out", sources=("s1", "s2", "s3"), hours=(0, 5, 30))
        posts.append(post("slug", "s4", hours=6, title="org/Model-V4.1-Flash-1017 · Weights"))
        self.assertIn("flash 1017", phrases("org/Model-V4.1-Flash-1017 · Weights"))
        self.assertNotIn("flash 1017", names("org/Model-V4.1-Flash-1017 · Weights"), "what names it is unchanged")
        found = {s.name: s.posts for s in surges(posts, followed("s1", "s2", "s3", "s4"))}
        self.assertIn("v4.1 flash 1017", found)
        self.assertTrue(all("slug" in ids for ids in found.values()), found)

    def test_a_date_is_no_name(self):
        # Issue 0111: "<month> <year>" surged and joined a column's dated issue with an unrelated question
        # (the three date surges on the server's copy, all three of unrelated posts).
        for title, date in (("Column: Autodoxing (02 Nov 2026)", ("02 nov", "nov 2026", "02 nov 2026", "autodoxing 02 nov")),
                            ("The best small model at Nov 2026?", ("nov 2026",)), ("Roundup #44: July 2026", ("july 2026",)),
                            ("Notes from March 20, 2026", ("march 20", "march 20 2026")), ("June 10th update", ("june 10th",)),
                            ("Итоги: Ноябрь 2026", ("ноябрь 2026",))):
            self.assertFalse(names(title) & set(date), title)
        self.assertIn("june model 4", names("June Model 4 is out"), "a month word beside no day or year names it")
        self.assertIn("q3 2026", names("Q3 2026 results"), "not a month")
        posts = self.burst("A column (02 Nov 2026)") + [post("q", "s4", hours=6, title="Which model at Nov 2026?")]
        self.assertEqual(surges(posts, followed("s1", "s2", "s3", "s4")), [])

    def test_arxiv_titles_are_left_out(self):
        self.assertEqual(surges(self.burst(kind="arxiv"), followed("s1", "s2", "s3")), [])


class NewsStoriesTests(unittest.TestCase):
    def test_a_name_joins_stories_for_news_only(self):
        page = "https://news.example/2026/10/the-launch"
        posts = [post("a", "s1", title="Steam Frame is here", links=[(page, None)]),
                 post("b", "s2", hours=1, title="Hands on: Steam Frame", links=[(page, None)]),
                 post("c", "s3", hours=5, title="Why Steam Frame matters")]
        stories = group(posts)
        self.assertEqual([sorted(p.id for p in s.posts) for s in stories], [["a", "b"]], "0050 joins by the link only")
        [story] = news(posts, stories, surges(posts, followed("s1", "s2", "s3")))
        self.assertEqual([p.id for p in story.posts], ["a", "b", "c"])
        self.assertEqual((story.reports, story.shares, story.mentions, story.score), (3, 0, 0, 3.0))
        self.assertEqual(story.names, {"a": "steam frame", "b": "steam frame", "c": "steam frame"})

    def test_a_story_needs_two_independent_voices(self):
        posts = [post("a", "s1", text_hash="h", chars=200, title="One two three four five"),
                 post("b", "tg", kind="telegram", hours=1, text_hash="h", chars=200)]
        stories = group(posts)
        self.assertEqual(len(stories), 1)
        self.assertEqual(news(posts, stories, []), [], "a copy is the same voice")

    def test_roundup_mentions_count(self):
        one, two, three = (f"https://news.example/2026/10/story-{n}" for n in (1, 2, 3))
        posts = [post("r", "weekly", links=[(one, None), (two, None), (three, None)]),
                 post("b", "s2", hours=1, links=[(two, None)]), post("c", "s3", hours=2, links=[(two, None)])]
        stories = group(posts)
        [two_story] = [s for s in news(posts, stories, []) if {p.id for p in s.posts} == {"b", "c"}]
        self.assertEqual((two_story.reports, two_story.mentions, two_story.score), (2, 1, 2.5))


# ---- Classics ---------------------------------------------------------------------------------


def cite(voice, days, target, *, stored=None, text=None, source=None):
    return Citation(voice=voice, name=voice, source_id=source or voice, t=T0 + timedelta(days=days), target=target,
                    stored=stored, text=text)


class ClassicRulesTests(unittest.TestCase):
    page = "https://essays.example/essay/machines-of-loving-grace"

    def test_cited_by_two_voices_over_180_days(self):
        [c] = classics([cite("a", 0, self.page, text="Machines of Loving Grace"), cite("b", 10, self.page, text="this essay"),
                        cite("a", 200, self.page)], {})
        self.assertEqual((c.voices, c.days, c.title), (2, 190, "Machines of Loving Grace"))
        self.assertEqual([x["name"] for x in c.citers], ["a", "b"])
        self.assertEqual(classics([cite("a", 0, self.page), cite("b", 10, self.page), cite("a", 189, self.page)], {}), [],
                         "179 days from the second voice")
        self.assertEqual(classics([cite("a", 0, self.page), cite("a", 400, self.page)], {}), [], "one voice")

    def test_one_voices_date_alone_makes_no_classic(self):
        """On the server's data a Gwern page dated 2023 linked a 2026 post: the spread starts at the
        second voice's first link, so one early date can't stretch it."""
        self.assertEqual(classics([cite("gwern", -1300, self.page), cite("b", 0, self.page), cite("c", 30, self.page)], {}),
                         [])

    def test_a_stored_post_counts_from_its_date_and_not_its_own_voice(self):
        stored = {"p": ("site:lab.test", T0 - timedelta(days=200), "Golden Gate Claude")}
        url = "https://lab.test/news/golden-gate-claude"
        [c] = classics([cite("x", 0, url, stored="p"), cite("y", 1, url, stored="p")], stored)
        self.assertEqual((c.post_id, c.days, c.title), ("p", 201, "Golden Gate Claude"))
        self.assertEqual(classics([cite("x", 0, url, stored="p"), cite("site:lab.test", 1, url, stored="p")], stored), [],
                         "the page's own voice does not count")

    def test_link_words_name_a_classic_only_when_they_read_as_a_title(self):
        page = "https://github.com/openclaw/openclaw"
        spread = [cite("a", 0, page, text="over 100,000 commits"), cite("b", 10, page, text="over 100,000 commits"),
                  cite("a", 200, page)]
        [c] = classics(spread, {})
        self.assertIsNone(c.title, "words from inside a sentence: the address is shown")
        [c] = classics(spread + [cite("c", 201, page, text="OpenClaw on GitHub")], {})
        self.assertEqual(c.title, "OpenClaw on GitHub")

    def test_reference_pages_are_not_classics(self):
        for url in ("https://docs.example/docs/intro", "https://claude.example/product/claude-code",
                    "https://example.com/pricing", "https://help.example.com/help/articles/123",
                    "https://example.com/api/reference", "https://example.com/", "https://x.com/karpathy",
                    "https://example.com/release-notes/2026"):
            self.assertTrue(is_reference(url), url)
            self.assertEqual(classics([cite("a", 0, url), cite("b", 10, url), cite("a", 300, url)], {}), [], url)
        for url in ("https://arxiv.org/abs/2001.08361", "https://incompleteideas.net/IncIdeas/BitterLesson.html",
                    "https://example.com/blog/apis-i-like"):
            self.assertFalse(is_reference(url), url)

    def test_most_voices_first_then_cited_longest(self):
        a, b, c = (f"https://essays.example/essay/number-{n}" for n in range(3))
        found = classics([cite("x", 0, a), cite("y", 10, a), cite("x", 200, a),
                          cite("x", 0, b), cite("y", 10, b), cite("x", 600, b),
                          cite("x", 0, c), cite("y", 10, c), cite("z", 11, c), cite("x", 200, c)], {})
        self.assertEqual([f.target for f in found], [c, b, a])


# ---- the job and the views, on the database ---------------------------------------------------


@requires_db
class NewsJobTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc)
        self.mark = uuid.uuid4().hex[:8]
        self.news = NewsService(db_url(), clock=lambda: self.now)
        self.service = StoriesService(db_url(), clock=lambda: self.now, news=self.news)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _source(self, name, *, days_followed=60, main=True):
        return insert_source(self.cur, name, in_main_digest=main, followed_days=days_followed)

    def _post(self, source, *, site, hours_ago=1.0, title="A post", html=None, url=None):
        url = url or f"https://{site}-{self.mark}.test/{uuid.uuid4().hex}"
        return str(insert_post(self.cur, source, url, at=self.now - timedelta(hours=hours_ago), title=title,
                               content="Body", html=html, content_hash=uuid.uuid4().hex, host=f"{site}-{self.mark}.test"))

    def _job(self):
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        return self.service.regroup(self.cur)

    def _link(self, url, text="read"):
        return f'<p><a href="{url}">{text}</a></p>'

    def _folder(self, *sources):
        self.cur.execute("INSERT INTO folders (name) VALUES (%s) RETURNING id", (f"news-{self.mark}",))
        folder = str(self.cur.fetchone()[0])
        for source in sources:
            self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (folder, source))
        return folder

    def _mine(self, items):
        return [i for i in items if self.mark in (i.get("url") or "")]

    # ---- News -------------------------------------------------------------------------------

    def _week(self):
        name = f"Zork{self.mark[:4]} 9"   # a name of its own: letters and digits
        self.a, self.b, self.c = (self._source(n) for n in ("Alpha", "Beta", "Gamma"))
        self.fresh = [self._post(s, site=n, hours_ago=h, title=f"{name} is out") for s, n, h in
                      ((self.a, "alpha", 10), (self.b, "beta", 9), (self.c, "gamma", 8))]
        page = f"https://news-{self.mark}.test/2026/10/the-older-story"
        self.older = [self._post(s, site=n, hours_ago=h, title=t, html=self._link(page)) for s, n, h, t in
                      ((self.a, "alpha", 24 * 4, "What happened on Monday"), (self.b, "beta", 24 * 4 - 1, "Monday, explained"))]
        self._job()

    def test_news_in_two_parts_by_score(self):
        self._week()
        items = self._mine(self.news.news_on(self.cur, "all")["items"])
        self.assertEqual([i["id"] for i in items], [self.fresh[0], self.older[0]])
        first, second = items
        self.assertEqual(first["news"]["part"], "recent")
        self.assertEqual((first["news"]["reports"], first["news"]["score"]), (3, 3.0))
        self.assertEqual([s["name"] for s in first["story"]["sources"]], ["Alpha", "Beta", "Gamma"])
        self.assertEqual([p["id"] for p in first["story"]["posts"]], self.fresh[1:])
        self.assertEqual(second["news"]["part"], "earlier")
        self.cur.execute("SELECT count(*) FROM story_posts WHERE post_id = ANY(%s::uuid[])", (self.fresh,))
        self.assertEqual(self.cur.fetchone()[0], 0, "a name never folds rows in the Main feed")

    def test_a_source_without_a_name_is_named_by_its_address(self):
        """An empty display name falls back like a missing one: the reader derives a name from the
        address (sourceLabel), never a blank."""
        from insight_core.db.repo_stories import SourceFacts
        name = f"Quux{self.mark[:4]} 7"
        empty, missing, named = self._source(""), self._source("x"), self._source("Gamma")
        self.cur.execute("UPDATE sources SET settings = settings - 'display_name' WHERE id = %s", (missing,))
        self.cur.execute("UPDATE sources SET settings = jsonb_build_object('display_name', '  ') WHERE id = %s",
                         (empty,))
        self.cur.execute("SELECT id::text, handle_or_url FROM sources WHERE id = ANY(%s::uuid[])", ([empty, missing],))
        address = dict(self.cur.fetchall())
        fresh = [self._post(s, site=n, hours_ago=h, title=f"{name} is out") for s, n, h in
                 ((empty, "alpha", 10), (missing, "beta", 9), (named, "gamma", 8))]
        self._job()
        items = [i for i in self._mine(self.news.news_on(self.cur, "all")["items"]) if i["id"] == fresh[0]]
        self.assertEqual([s["name"] for s in items[0]["story"]["sources"]],
                         [address[empty], address[missing], "Gamma"])
        self.assertEqual(items[0]["source_display_name"], address[empty])
        facts = SourceFacts(self.cur)
        self.assertEqual((facts.name[empty], facts.name[missing]), (address[empty], address[missing]))

    def test_news_names_every_voice_it_counts(self):
        """Issue 0069 (R6): steipete reposting badlogicgames' tweet is 2 voices, so News names both."""
        accounts = {}
        for name in ("steipete", "badlogicgames"):
            accounts[name] = self._source(name)
            self.cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s",
                             (f"https://nitter.local/{name}{self.mark}/rss", accounts[name]))
        url = f"https://nitter.local/badlogicgames{self.mark}/status/2114444636303364349#m"
        post = self._post(accounts["steipete"], site="x", title=f"RT by @steipete{self.mark}: how i work with agents",
                          url=url)
        self.cur.execute("UPDATE posts SET author = %s, reposted_by = %s WHERE id = %s",
                         (f"badlogicgames{self.mark}", [f"steipete{self.mark}"], post))
        self._job()
        [item] = [i for i in self.news.news_on(self.cur, "all")["items"] if i["id"] == post]
        self.assertEqual(item["story"]["voices"], 2)
        self.assertEqual([s["name"] for s in item["story"]["sources"]], ["steipete", "badlogicgames"])

    def test_news_shows_30_days(self):
        """Issue 0077: News reads 30 days; "recent" is still the last 48 hours."""
        self._week()
        self.now += timedelta(days=20)
        items = self._mine(self.news.news_on(self.cur, "all")["items"])
        self.assertEqual([(i["id"], i["news"]["part"]) for i in items], [(self.fresh[0], "earlier"), (self.older[0], "earlier")])
        self.assertNotIn("scope_role", items[0]["news"], "only on one source")
        self.now += timedelta(days=11)
        self.assertEqual(self._mine(self.news.news_on(self.cur, "all")["items"]), [])

    def _rows(self, ids):
        self.cur.execute("SELECT id::text FROM news_stories WHERE id = ANY(%s::uuid[])", (list(ids),))
        return {r[0] for r in self.cur.fetchall()}

    def test_a_row_before_the_window_is_kept(self):
        """Issue 0077: nothing is deleted. A run past a row's 30 days leaves it as it is, its posts in
        it; a second run changes nothing."""
        self._week()
        self.cur.execute("SELECT * FROM news_stories WHERE id = %s", (self.fresh[0],))
        before = self.cur.fetchone()
        self.now += timedelta(days=40)
        run = self._job()
        self.assertEqual(run["news_removed"], 0)
        self.assertEqual(self._rows([self.fresh[0], self.older[0]]), {self.fresh[0], self.older[0]})
        self.cur.execute("SELECT * FROM news_stories WHERE id = %s", (self.fresh[0],))
        self.assertEqual(self.cur.fetchone(), before, "as it was")
        self.cur.execute("SELECT count(*) FROM news_posts WHERE news_id = %s", (self.fresh[0],))
        self.assertEqual(self.cur.fetchone()[0], 3)
        self.assertEqual(self._job()["news_changed"], 0)

    def test_a_row_inside_the_window_it_no_longer_finds_goes_counted(self):
        self._week()
        self.cur.execute("UPDATE posts SET content_html = NULL WHERE id = %s", (self.older[1],))
        self.cur.execute("DELETE FROM post_links WHERE post_id = %s", (self.older[1],))
        run = self._job()
        self.assertEqual(self._rows([self.older[0]]), set(), "one voice is no News")
        self.assertGreaterEqual(run["news_removed"], 1)

    def test_a_row_before_the_window_with_no_post_left_goes_counted(self):
        self._week()
        lone = self._post(self.a, site="alpha", hours_ago=24 * 60, title="Long ago")
        self.cur.execute("INSERT INTO news_stories (id, first_at, voices, reports, shares, mentions, score) "
                         "VALUES (%s, %s, 2, 2, 0, 0, 2)", (lone, self.now - timedelta(days=60)))
        run = self._job()
        self.assertEqual(self._rows([lone, self.fresh[0]]), {self.fresh[0]})
        self.assertGreaterEqual(run["news_removed"], 1)

    def test_one_source_says_its_part(self):
        """Issue 0077: on one source each row says the source's part, the strongest of its posts:
        origin (its post started the row), report, share, else mention (its roundup lists the story)."""
        page = f"https://press-{self.mark}.test/2026/10/the-press-release"
        press, a, b, weekly = (self._source(n) for n in ("Press", "Alpha", "Beta", "Weekly"))
        own = self._post(press, site="press", url=page, hours_ago=10, title="We ship the thing")
        self._post(a, site="alpha", hours_ago=9, title="They shipped the thing everyone waited for all year long", html=self._link(page))
        self._post(b, site="beta", hours_ago=8, title="They shipped the thing everyone waited for all year long", html=self._link(page))
        others = [f"https://else-{self.mark}.test/2026/10/story-{n}" for n in (1, 2)]
        self._post(weekly, site="weekly", hours_ago=7, title="This week",
                   html=self._link(others[0]) + self._link(page) + self._link(others[1]))
        self._job()

        def part(source):
            items = [i for i in self.news.news_on(self.cur, f"source:{source}")["items"] if i["story"]["id"] == own]
            return [i["news"]["scope_role"] for i in items]
        self.assertEqual(part(press), ["origin"])
        self.assertEqual(part(a), ["report"])
        self.assertEqual(part(b), ["share"], "a copy of Alpha's title")
        self.assertEqual(part(weekly), ["mention"])
        self.assertEqual([i["id"] for i in self._mine(self.news.news_on(self.cur, "all")["items"])], [own])

    def test_a_roundup_leads_no_row_with_a_report(self):
        """Issue 0083: a row with no origin (an outside page) is led by its first report the stories
        list as no roundup, not by a weekly digest that came first."""
        page = f"https://outside-{self.mark}.test/2026/10/the-release"
        weekly, a, b = (self._source(n) for n in ("Weekly", "Alpha", "Beta"))
        others = [f"https://else-{self.mark}.test/2026/10/story-{n}" for n in (1, 2)]
        digest = self._post(weekly, site="weekly", hours_ago=10, title="This week",
                            html=self._link(page) + self._link(others[0]) + self._link(others[1]))
        report = self._post(a, site="alpha", hours_ago=9, title="They shipped the thing everyone waited for", html=self._link(page))
        self._post(b, site="beta", hours_ago=8, title="The thing is out, and it is fast", html=self._link(page))
        for s, n, h in ((self._source("Gamma"), "gamma", 7), (self._source("Delta"), "delta", 6)):   # the story it also lists
            self._post(s, site=n, hours_ago=h, title=f"Another story, by {n}", html=self._link(others[0]))
        self._job()
        self.cur.execute("SELECT count(*) FROM story_mentions WHERE post_id = %s", (digest,))
        self.assertGreater(self.cur.fetchone()[0], 0, "the stories list the digest as a roundup")
        [item] = [i for i in self.news.news_on(self.cur, "all")["items"] if i["story"]["id"] == digest]
        self.assertEqual(item["id"], report)

    def test_a_row_without_an_origin_leads_with_the_share_of_its_page_and_names_followed_sources_first(self):
        """Issue 0103: a row whose story starts at an outside page is led by the first post sharing that
        page (a Reddit link post), not a later report joined by the name; its names list the followed
        sources before the Reddit author, the count and the set unchanged."""
        name = f"Quux{self.mark[:4]} 7"
        page = f"https://hub-{self.mark}.test/org/quux-{self.mark[:4]}-7"
        sub = insert_source(self.cur, "r/sub", platform="reddit", in_main_digest=True, followed_days=60)
        a, b = self._source("Alpha"), self._source("Beta")
        hub = self._post(sub, site="reddit", hours_ago=10, title=f"{name} on the hub",
                         html=f'submitted by <a href="https://www.reddit.com/user/alice"> /u/alice </a> {self._link(page)}')
        talk = self._post(a, site="alpha", hours_ago=9, title=f"{name} is out, and nobody covers it well")
        self._post(b, site="beta", hours_ago=8, title=f"{name} explained", html=self._link(page))
        self._job()
        self.cur.execute("SELECT parent_url IS NOT NULL, parent_reason FROM story_posts WHERE post_id = %s", (hub,))
        self.assertEqual(self.cur.fetchall(), [(True, "citation")], "the Reddit post hangs from the page it shares")
        [item] = [i for i in self.news.news_on(self.cur, "all")["items"] if name in (i["title"] or "")]
        self.assertNotEqual(item["id"], talk, "not the first report")
        self.assertEqual(item["id"], hub, "the share of the page")
        names = [(s["name"], s.get("place")) for s in item["story"]["sources"]]
        self.assertEqual(names, [("Alpha", None), ("Beta", None), ("u/alice", "r/sub")])
        self.assertEqual(item["story"]["voices"], 3)

    def test_a_post_page_names_its_news_row(self):
        """Issue 0083: the post page says the News row a post is in, as the Main feed's News shows it,
        else as its own source's (a source outside the Main feed); nothing for a post in none."""
        self._week()
        row = self.news.row_of(self.cur, self.fresh[1], self.b)
        [item] = [i for i in self.news.news_on(self.cur, "all")["items"] if i["id"] == self.fresh[0]]
        self.assertEqual(row, {"id": self.fresh[0], "title": item["title"], "voices": 3, "lead_id": self.fresh[0], "scope": "all"})
        lone = self._post(self.a, site="alpha", hours_ago=2, title="Nothing to see")
        self.assertIsNone(self.news.row_of(self.cur, lone, self.a))

        name = f"Quux{self.mark[:4]} 7"
        outside = [self._source(n, main=False) for n in ("Delta", "Epsilon", "Zeta")]
        posts = [self._post(s, site=n, hours_ago=h, title=f"{name} is out") for s, n, h in
                 zip(outside, ("delta", "epsilon", "zeta"), (6, 5, 4))]
        self._job()
        self.assertEqual(self.news.row_of(self.cur, posts[2], outside[2])["scope"], f"source:{outside[2]}")

    def test_started_it_only_when_first(self):
        """Issue 0082: a source whose post roots its 0050 story, in a row another post began, didn't start it."""
        name = f"Zork{self.mark[:4]} 9"
        page = f"https://beta-{self.mark}.test/2026/10/the-release"
        a, b, c = (self._source(n) for n in ("Alpha", "Beta", "Gamma"))
        first = self._post(a, site="alpha", hours_ago=10, title=f"{name} is out")
        rooted = self._post(b, site="beta", url=page, hours_ago=9, title=f"{name} ships today")
        self._post(c, site="gamma", hours_ago=8, title=f"{name} explained", html=self._link(page))
        self._job()

        def part(source):
            items = [i for i in self.news.news_on(self.cur, f"source:{source}")["items"] if i["story"]["id"] == first]
            return [i["news"]["scope_role"] for i in items]
        self.cur.execute("SELECT parent_reason FROM story_posts WHERE post_id = %s", (rooted,))
        self.assertEqual(self.cur.fetchall(), [(None,)], "Beta's post roots its 0050 story")
        self.assertEqual((part(a), part(b), part(c)), (["report"], ["report"], ["report"]),
                         "Alpha came first but roots no story; Beta roots one, after Alpha")

    def test_names_are_the_voices_counted(self):
        """Issue 0082: each Reddit author is a voice, named u/<author> in its subreddit, on News, the feed
        row and the post page alike: the count is the names."""
        from insight_core.db.repo_reader import ReaderRepository
        from insight_core.services.post_detail_service import PostDetailService
        page = f"https://blog-{self.mark}.test/2026/10/the-release"
        blog = self._source("Blog One")
        sub = insert_source(self.cur, "r/sub", platform="reddit", in_main_digest=True, followed_days=60)
        own = self._post(blog, site="blog", url=page, hours_ago=10, title="We released the thing")
        for user, hours in (("alice", 9), ("bob", 8), ("alice", 7)):
            self._post(sub, site="reddit", hours_ago=hours, title=f"The thing, by {user}",
                       html=f'submitted by <a href="https://www.reddit.com/user/{user}"> /u/{user} </a> {self._link(page)}')
        self._job()
        [item] = [i for i in self.news.news_on(self.cur, "all")["items"] if i["id"] == own]
        names = [(s["name"], s.get("place")) for s in item["story"]["sources"]]
        self.assertEqual(names, [("Blog One", None), ("u/alice", "r/sub"), ("u/bob", "r/sub")])
        self.assertEqual(item["story"]["voices"], 3)
        row = {"id": own}
        ReaderRepository.attach_stories(self.cur, [row])
        self.assertEqual(([(s["name"], s.get("place")) for s in row["story"]["sources"]], row["story"]["voices"]), (names, 3))
        story = PostDetailService.story(self.cur, own, blog)
        self.assertEqual([(s["name"], s.get("place")) for s in story["sources"]], names)

    def test_a_track_shows_stories_with_one_of_its_posts_scored_over_every_source(self):
        self._week()
        other = self._source("Delta")
        folder = self._folder(self.c, other)
        items = self._mine(self.news.news_on(self.cur, f"folder:{folder}")["items"])
        self.assertEqual([i["id"] for i in items], [self.fresh[2]], "led by the track's own post")
        self.assertEqual(items[0]["news"]["score"], 3.0, "the score counts all your sources")
        self.assertEqual(self._mine(self.news.news_on(self.cur, f"folder:{self._folder(other)}")["items"]), [])

    def test_reading_from_news_reads_like_the_feed(self):
        self._week()
        from insight_core.db.repo_reader import ReaderRepository
        marked = ReaderRepository(unread_window_days=None).set_read(self.cur, [self.older[0]], True)
        self.assertEqual(marked, [self.older[0]], "two reports: the other stays unread, as 0050")
        items = self._mine(self.news.news_on(self.cur, "all")["items"])
        self.assertIsNotNone(items[1]["read_at"])

    def test_a_second_run_changes_nothing(self):
        self._week()
        again = self._job()
        self.assertEqual((again["news_changed"], again["classics_changed"]), (0, 0))

    # ---- Classics ---------------------------------------------------------------------------

    def _classics(self):
        self.x, self.y, self.z = (self._source(n) for n in ("Xeno", "Yolk", "Zinc"))
        self.essay = f"https://essays-{self.mark}.test/essay/machines-of-loving-grace"
        self.docs = f"https://lab-{self.mark}.test/docs/getting-started-with-it"
        self.recent = f"https://papers-{self.mark}.test/abs/scaling-laws-for-models"
        for source, site, days in ((self.x, "xeno", 500), (self.y, "yolk", 400), (self.x, "xeno", 150)):
            self._post(source, site=site, hours_ago=24 * days,
                       html=self._link(self.essay, "Machines of Loving Grace") + self._link(self.docs, "the docs here"))
        for source, site, days in ((self.x, "xeno", 400), (self.y, "yolk", 300)):
            self._post(source, site=site, hours_ago=24 * days, html=self._link(self.recent, "Scaling Laws for Neural Models"))
        self.citing = self._post(self.z, site="zinc", hours_ago=24 * 2,
                                 html=self._link(self.recent, "Scaling Laws for Neural Models"))
        self._job()

    def _mine_classics(self, scope="all"):
        return [c for c in self.news.classics_on(self.cur, scope)["classics"] if self.mark in c["url"]]

    def test_classics_cited_again_first_and_no_reference_pages(self):
        self._classics()
        found = self._mine_classics()
        self.assertEqual([c["url"] for c in found], [normalize_url(self.recent), normalize_url(self.essay)])
        self.assertTrue(found[0]["cited_again"])
        self.assertFalse(found[1]["cited_again"])
        self.assertEqual(found[1]["title"], "Machines of Loving Grace")
        self.assertEqual([c["name"] for c in found[1]["citers"]], ["Xeno", "Yolk"])
        self.assertEqual((found[1]["voices"], found[1]["days"]), (2, 250), "from Yolk's first link (400 days) to the last (150)")

    def test_hide_and_background(self):
        self._classics()
        background = self.news.background(self.cur, self.citing)
        self.assertEqual([(b["url"], b["voices"], b["title"]) for b in background],
                         [(normalize_url(self.recent), 3, "Scaling Laws for Neural Models")])
        plain = self._post(self.z, site="zinc", hours_ago=1, html=self._link(f"https://else-{self.mark}.test/a/b-c-d-e"))
        self.assertEqual(self.news.background(self.cur, plain), [], "nothing without a classic")
        self.news.repo.hide_classic(self.cur, normalize_url(self.recent))
        self.assertEqual([c["url"] for c in self._mine_classics()], [normalize_url(self.essay)])
        self.assertEqual(self.news.background(self.cur, self.citing), [], "a hidden classic never comes back")
        self._job()
        self.assertEqual([c["url"] for c in self._mine_classics()], [normalize_url(self.essay)])

    def test_background_shows_at_most_two(self):
        self._classics()
        pages = [f"https://essays-{self.mark}.test/essay/part-number-{n}" for n in range(3)]
        for source, site, days in ((self.x, "xeno", 500), (self.y, "yolk", 400)):
            self._post(source, site=site, hours_ago=24 * days, html="".join(self._link(p) for p in pages))
        reader = self._post(self.z, site="zinc", hours_ago=1, html="".join(self._link(p) for p in pages))
        self._job()
        self.assertEqual(len(self.news.background(self.cur, reader)), 2)

    def test_two_posts_at_one_address_are_one_anchor(self):
        """Issue 0049: normalized_url is not unique (one address, two titles: Daring Fireball's
        footnote post). A link to it joins one stored post, the first seen, everywhere."""
        from insight_core.db.repo_stories import SourceFacts
        self._classics()
        essays = self._source("Essays")
        first = self._post(essays, site="essays", url=self.essay, title="Machines of Loving Grace", hours_ago=24 * 600)
        second = self._post(essays, site="essays", url=self.essay + "#fn1-2026", title="A footnote", hours_ago=24 * 600)
        self.cur.execute("UPDATE posts SET fetched_at = fetched_at + interval '1 minute' WHERE id = %s", (second,))
        self._job()

        loaded = {p["id"]: p for p in StoriesRepository.load_posts(self.cur, SourceFacts(self.cur), None)}
        for post in loaded.values():
            targets = [t for t, _ in post["links"]]
            self.assertEqual(len(targets), len(set(targets)), "each link once")
            if normalize_url(self.essay) in targets:
                self.assertEqual(dict(post["links"])[normalize_url(self.essay)], first)
        citations = [c for c in self.news.repo.citations(self.cur, reddit=[], saved=[])
                     if c["target"] == normalize_url(self.essay)]
        self.assertEqual(len(citations), 3, "one row per citing post (the fixture has three)")
        self.assertEqual({c["stored"] for c in citations}, {first})
        essay = [c for c in self._mine_classics() if c["url"] == normalize_url(self.essay)]
        self.assertEqual([c["post_id"] for c in essay], [first])
        citer = self._post(self.z, site="zinc", hours_ago=1, html=self._link(self.essay))
        self._job()
        background = [b for b in self.news.background(self.cur, citer) if b["url"] == normalize_url(self.essay)]
        self.assertEqual([b["post_id"] for b in background], [first])

    def test_a_track_shows_classics_its_sources_cited(self):
        self._classics()
        self.assertEqual([c["url"] for c in self._mine_classics(f"folder:{self._folder(self.z)}")],
                         [normalize_url(self.recent)])
        self.assertEqual(self._mine_classics(f"folder:{self._folder(self._source('Nobody'))}"), [])

    def test_one_source_says_its_part_in_a_classic(self):
        """Issue 0077: on one source a classic is its own post (origin) or a page it cites (report)."""
        self._classics()
        essays = self._source("Essays")
        self._post(essays, site="essays", url=self.essay, title="Machines of Loving Grace", hours_ago=24 * 600)
        self._job()
        self.assertEqual([(c["url"], c["scope_role"]) for c in self._mine_classics(f"source:{essays}")],
                         [(normalize_url(self.essay), "origin")])
        self.assertEqual([(c["url"], c["scope_role"]) for c in self._mine_classics(f"source:{self.y}")],
                         [(normalize_url(self.recent), "report"), (normalize_url(self.essay), "report")])
        self.assertNotIn("scope_role", self._mine_classics()[0])

    def test_one_source_is_named_first_among_a_classics_citers(self):
        """Issue 0105: on one source's page its own voices lead a classic's citers (a Reddit author with its
        subreddit as `place`); elsewhere the order stays first citation first, with no place."""
        self._classics()
        sub = insert_source(self.cur, "r/sub", platform="reddit", in_main_digest=True, followed_days=60)
        self._post(sub, site="reddit", hours_ago=24 * 300,
                   html=f'submitted by <a href="https://www.reddit.com/user/alice"> /u/alice </a> {self._link(self.essay)}')
        self._job()

        def citers(scope):
            essay = next(c for c in self._mine_classics(scope) if c["url"] == normalize_url(self.essay))
            return [(c["name"], c.get("place")) for c in essay["citers"]]

        self.assertEqual(citers("all"), [("Xeno", None), ("Yolk", None), ("u/alice", None)])
        self.assertEqual(citers(f"source:{self.y}"), [("Yolk", None), ("Xeno", None), ("u/alice", None)])
        self.assertEqual(citers(f"source:{sub}"), [("u/alice", "r/sub"), ("Xeno", None), ("Yolk", None)])


@requires_test_db
class DiscoverClassicsTests(unittest.TestCase):
    """Discover (0050) leans on Classics: a suggested site that holds classics comes first."""

    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.addCleanup(self._clean)

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            cur.execute("DELETE FROM classics WHERE target_url LIKE %s", (f"%{self.mark}%",))

    def test_a_site_with_classics_comes_first(self):
        many, few = f"many-{self.mark}.test", f"few-{self.mark}.test"
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            for n in range(4):
                source = insert_scratch_source(cur)
                url = f"https://voice{n}-{self.mark}.test/p"
                html = "".join(f'<a href="https://{many}/2026/10/the-story-{k}">Story {k}</a>' for k in range(2))
                if n < 3:
                    html += "".join(f'<a href="https://{few}/2026/10/an-essay-{k}">Essay {k}</a>' for k in range(2))
                cur.execute("INSERT INTO posts (source_id, url, normalized_url, url_host, content_html, published_at) "
                            "VALUES (%s, %s, %s, %s, %s, now())",
                            (source, url, normalize_url(url), f"voice{n}-{self.mark}.test", html))
            cur.execute("INSERT INTO classics (target_url, voices, first_at, last_at) VALUES (%s, 3, now(), now())",
                        (f"https://{few}/2026/10/an-essay-0",))
        service = StoriesService(db_url())
        service.fill_links()
        mine = [s for s in service.discover()["suggestions"] if self.mark in s["key"]]
        self.assertEqual([(s["key"], s["voices"], s["classics"]) for s in mine], [(few, 3, 1), (many, 4, 0)])


@requires_test_db
class NewsRouteTests(unittest.TestCase):
    """GET /api/news, GET /api/classics and POST /api/classics/hide over ASGI."""

    def setUp(self):
        import main
        from insight_core.services import registry
        from insight_core.tests._asgi import call

        self.app, self.call = main.app, call
        previous = registry.use(registry.build_services(db_url()))
        self.addCleanup(registry.use, previous)
        self.url = f"https://hidden-{uuid.uuid4().hex[:8]}.test/essay/a-page-of-old"
        self.addCleanup(self._clean)

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM classic_hidden WHERE target_url = %s", (self.url,))

    def test_the_routes(self):
        status, _, body = self.call(self.app, "GET", "/api/news", query={"scope": "all"})
        self.assertEqual((status, body["next_cursor"]), (200, None))
        self.assertIsInstance(body["items"], list)
        status, _, body = self.call(self.app, "GET", "/api/classics", query={"scope": "all"})
        self.assertEqual(status, 200)
        self.assertIsInstance(body["classics"], list)
        self.assertEqual(self.call(self.app, "GET", "/api/news", query={"scope": "nowhere"})[0], 400)
        self.assertEqual(self.call(self.app, "POST", "/api/classics/hide", json_body={"url": ""})[0], 400)
        status, _, body = self.call(self.app, "POST", "/api/classics/hide", json_body={"url": self.url})
        self.assertEqual((status, body["url"]), (200, self.url))


if __name__ == "__main__":
    unittest.main()
