"""One story, many sources (issue 0050): post links, the joining rules, roles, voices, the story
job, the folded feed, read propagation, unread counts and Discover.

The rules are tested as pure functions; the job, the feed and the counts on the database in
one transaction per test, rolled back (the job regroups every post it sees, the test's own
included, and nothing of it is kept). Assertions are scoped to the test's own rows.
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

from insight_core.db.repo_posts import PostDraft, PostsRepository
from insight_core.db.repo_reader import FeedQuery, FeedScope, ReaderRepository, FeedCursor
from insight_core.db.repo_sources import SourcesRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository, source_account
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_db, requires_test_db
from insight_core.utils.post_links import account_key, extract_links, is_home, site_of, source_kind
from insight_core.utils.story_rules import StoryPost, count_voices, group, roles, suggestions
from insight_core.utils.url_normalization import normalize_url

T0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
LONG = "x" * 200   # a text long enough to be a copy


def post(pid, source, *, hours=0.0, kind="site", site=None, title=None, text_hash=None, chars=0,
         links=(), author=None, words=None):
    return StoryPost(id=pid, source_id=source, kind=kind, own_site=site or f"{source}.test",
                     t=T0 + timedelta(hours=hours), title=title, content_hash=text_hash, text_chars=chars,
                     words=words, author=author, links=[(u, s) for u, s in links])


def ids(stories):
    return [sorted(p.id for p in story.posts) for story in stories]


# ---- the links of a post -------------------------------------------------------------------


class PostLinksTests(unittest.TestCase):
    def test_outside_links_in_order_normalized_with_their_text(self):
        html = ('<p><a href="https://Other.example/a/?utm_source=x">The <b>first</b></a> '
                '<a href="/same-site">ours</a> <a href="https://www.blog.example/p/1">two</a> '
                '<a href="https://other.example/a">again</a> <a href="mailto:x@y.z">mail</a> '
                '<a href="https://cdn.example/pic.JPG">pic</a></p>')
        links = extract_links(html, "https://blog.example/post", "site")
        self.assertEqual([(l.url, l.position, l.text) for l in links],
                         [("https://other.example/a", 0, "The first")])

    def test_links_back_into_the_platform_are_not_kept(self):
        html = ('submitted by <a href="https://www.reddit.com/user/alice"> /u/alice </a> '
                '<a href="https://news.example/story-of-the-day">[link]</a> '
                '<a href="https://www.reddit.com/r/x/comments/1/t/">[comments]</a> <a href="https://i.redd.it/a.png">i</a>')
        links = extract_links(html, "https://www.reddit.com/r/x/comments/1/t/", "reddit")
        self.assertEqual([l.url for l in links], ["https://news.example/story-of-the-day"])

    def test_a_malformed_link_is_skipped_not_fatal(self):
        html = '<a href="http://example.com:  some prose here/">x</a> <a href="https://b.example/post">B post</a>'
        links = extract_links(html, "https://blog.example/post", "site")
        self.assertEqual([link.url for link in links], ["https://b.example/post"])

    def test_no_html_no_links(self):
        self.assertEqual(extract_links(None, "https://a.example/x", "youtube"), [])

    def test_sites_homes_and_kinds(self):
        self.assertEqual(site_of("news.bbc.co.uk"), "bbc.co.uk")
        self.assertEqual(site_of("www.roadtovr.com"), "roadtovr.com")
        self.assertTrue(is_home("https://x.com/karpathy"))
        self.assertTrue(is_home("https://openai.com/"))
        self.assertFalse(is_home("https://openai.com/index/gpt"))
        self.assertEqual(source_kind("rss", "https://www.reddit.com/r/Xreal/.rss"), "reddit")
        self.assertEqual(source_kind("rss", "https://tg.i-c-a.su/rss/denissexy"), "telegram")
        self.assertEqual(source_kind("rss", "https://nitter.local/karpathy/rss"), "x")
        self.assertEqual(source_kind("rss", "https://simonwillison.net/atom/everything/"), "site")


# ---- when posts are one story -----------------------------------------------------------------


class JoiningRulesTests(unittest.TestCase):
    def test_same_text_joins_within_30_days_only(self):
        self.assertEqual(ids(group([post("a", "s1", text_hash="h", chars=200),
                                    post("b", "s2", hours=24 * 29, text_hash="h", chars=200)])), [["a", "b"]])
        self.assertEqual(group([post("a", "s1", text_hash="h", chars=200),
                                post("b", "s2", hours=24 * 31, text_hash="h", chars=200)]), [])
        self.assertEqual(group([post("a", "s1", text_hash="h", chars=119),
                                post("b", "s2", text_hash="h", chars=119)]), [], "too short to be a copy")

    def test_same_title_of_five_words_joins_within_7_days(self):
        title = "Snap shows its new AR glasses"
        self.assertEqual(ids(group([post("a", "s1", title=title), post("b", "s2", hours=24 * 6, title=title.upper())])),
                         [["a", "b"]])
        self.assertEqual(group([post("a", "s1", title=title), post("b", "s2", hours=24 * 8, title=title)]), [])
        self.assertEqual(group([post("a", "s1", title="Snap shows AR glasses"),
                                post("b", "s2", title="Snap shows AR glasses")]), [], "four words")

    def test_a_page_linked_by_two_voices_within_72_hours(self):
        page = "https://news.example/2026/10/the-launch"
        self.assertEqual(ids(group([post("a", "s1", links=[(page, None)]), post("b", "s2", hours=70, links=[(page, None)])])),
                         [["a", "b"]])
        self.assertEqual(group([post("a", "s1", links=[(page, None)]), post("b", "s2", hours=80, links=[(page, None)])]), [])

    def test_one_voice_never_joins_itself_through_links(self):
        page = "https://news.example/2026/10/the-launch"
        # Two sources of one site (two roadtovr feeds) are one voice.
        self.assertEqual(group([post("a", "s1", site="roadtovr.com", links=[(page, None)]),
                                post("b", "s2", site="roadtovr.com", links=[(page, None)])]), [])

    def test_a_reddit_cross_post_is_one_story_of_one_voice(self):
        page = "https://news.example/2026/10/the-launch"
        a = post("a", "r1", kind="reddit", author="alice", title="XREAL 1S is one of my favourites", links=[(page, None)],
                 words=10)
        b = post("b", "r2", kind="reddit", author="alice", hours=1, title="I'm really enjoying hand gestures",
                 links=[(page, None)], words=10)
        [story] = group([a, b])
        self.assertEqual((ids([story]), story.voices), ([["a", "b"]], 1), "links join by subreddit, voices count people")
        self.assertEqual(story.roles, {"a": "share", "b": "share"})
        same_sub = post("c", "r1", kind="reddit", author="bob", hours=2, links=[(page, None)], words=10)
        self.assertEqual(group([a, same_sub]), [], "one subreddit, one story source: no join through the link")
        c = post("c", "r1", kind="reddit", author="bob", title="XREAL 1S is one of my favourites", hours=1)
        self.assertEqual(count_voices([a, b, c]), 2, "the person, not the subreddit")

    def test_a_citation_of_another_voice_within_72_hours(self):
        cited = post("a", "s1")
        self.assertEqual(ids(group([cited, post("b", "s2", hours=10, links=[("https://s1.test/2026/10/a-post", "a")])])),
                         [["a", "b"]])
        self.assertEqual(group([cited, post("b", "s2", hours=100, links=[("https://s1.test/2026/10/a-post", "a")])]), [])
        self.assertEqual(group([cited, post("b", "s3", site="s1.test", hours=10,
                                            links=[("https://s1.test/2026/10/a-post", "a")])]), [], "its own voice")

    def test_a_cited_stored_post_with_a_one_segment_address_still_joins(self):
        """Found on the server's data: @denissexy cited blog.cloudflare.com/yandex-outage 2.8 hours
        after Cloudflare posted it, and the one-segment address was taken for a profile page."""
        cited = post("cf", "cloudflare", site="cloudflare.com", hours=0)
        citer = post("tg", "denissexy", kind="telegram", hours=2.8,
                     links=[("https://blog.cloudflare.com/yandex-outage", "cf")])
        self.assertEqual(ids(group([cited, citer])), [["cf", "tg"]])

    def test_home_and_profile_pages_join_nothing(self):
        self.assertEqual(group([post("a", "s1", links=[("https://x.com/karpathy", None)]),
                                post("b", "s2", links=[("https://x.com/karpathy", None)])]), [])

    def test_a_roundup_joins_its_first_link_and_mentions_the_rest(self):
        one, two, three = (f"https://news.example/2026/10/story-{n}" for n in (1, 2, 3))
        posts = [post("r", "weekly", links=[(one, None), (two, None), (three, None)]),
                 post("a", "s1", hours=1, links=[(one, None)]), post("b", "s2", hours=1, links=[(two, None)]),
                 post("c", "s3", hours=2, links=[(two, None)])]
        stories = group(posts)
        self.assertEqual(ids(stories), [["a", "r"], ["b", "c"]])
        self.assertEqual(stories[1].mentions, {"r"}, "the roundup counts for story 2 but is not in it")
        self.assertEqual(stories[0].mentions, set())

    def test_a_story_needs_two_sources(self):
        self.assertEqual(group([post("a", "s1", title="One two three four five"),
                                post("b", "s1", hours=1, title="One two three four five")]), [])


class RolesTests(unittest.TestCase):
    def test_reports_shares_and_link_posts(self):
        title = "Introducing the model we built this year"
        posts = [post("a", "s1", title=title, text_hash="h", chars=200),
                 post("b", "tg", kind="telegram", hours=1, text_hash="h", chars=200),          # a forward
                 post("c", "s2", hours=2, title=title),                                        # a copied title
                 post("d", "r1", kind="reddit", author="bob", hours=3, words=12),              # a link post
                 post("e", "r2", kind="reddit", author="eve", hours=4, words=400),             # its own take
                 post("f", "s3", hours=5, title="What I think of it")]
        self.assertEqual(roles(posts), {"a": "report", "b": "share", "c": "share", "d": "share", "e": "report",
                                        "f": "report"})


# ---- Discover ---------------------------------------------------------------------------------


class DiscoverRulesTests(unittest.TestCase):
    def links(self, site, voices, paths):
        return [(v, f"https://{site}/{p}") for v in voices for p in paths]

    def test_three_voices_and_article_like_pages(self):
        articles = ["2026/10/a-thing", "blog/how-we-built-the-thing"]
        links = (self.links("good.example", ["v1", "v2", "v3"], articles)
                 + self.links("two.example", ["v1", "v2"], articles)
                 + self.links("shop.example", ["v1", "v2", "v3"], ["product", "cart", "about", "p/12", "a-very-long-slug-here",
                                                                  "2026/01/x"])
                 + self.links("mine.example", ["v1", "v2", "v3"], articles)
                 + self.links("nope.example", ["v1", "v2", "v3"], articles))
        found = suggestions(links, followed={"mine.example"}, hidden={"nope.example"})
        self.assertEqual([s.key for s in found], ["good.example"])
        self.assertEqual((len(found[0].voices), len(found[0].articles), found[0].links), (3, 2, 2))

    def test_a_platform_suggests_accounts(self):
        links = self.links("x.com", ["v1", "v2", "v3"], ["karpathy/2026-10-a-long-post-here",
                                                          "karpathy/notes-on-a-new-model-today"])
        links += self.links("x.com", ["v1", "v2", "v3"], ["status/what-a-day-it-has-been"])
        found = suggestions(links, followed=set(), hidden=set())
        self.assertEqual([s.key for s in found], ["x.com/karpathy"])

    def test_a_blog_with_posts_at_its_root_is_one_site(self):
        """On the server's data blog.cloudflare.com (16 voices) was never suggested: its root-level
        posts made it look like a platform of one-post "accounts". Publishers by year, likewise."""
        links = []
        for n in range(10):
            links += self.links("blog.cloudflare.com", ["v1", "v2", "v3"], [f"post-number-{n}-about-something"])
        links += self.links("nytimes.com", ["v1", "v2", "v3"], ["2026/10/01/tech/a-story-about-it",
                                                                "2025/03/02/world/another-story-here"])
        self.assertEqual(sorted(s.key for s in suggestions(links, followed=set(), hidden=set())),
                         ["blog.cloudflare.com", "nytimes.com"])

    def test_on_a_platform_only_the_account_you_follow_is_followed(self):
        links = []
        for channel in ("seeallochnaya", "denissexy"):
            links += self.links("t.me", ["v1", "v2", "v3"], [f"{channel}/2026-10-a-long-post-here",
                                                             f"{channel}/notes-on-a-new-model-today"])
        followed = suggestions(links, followed={"t.me"}, hidden=set(), followed_accounts={"t.me/seeallochnaya"})
        self.assertEqual([s.key for s in followed], ["t.me/denissexy"], "following one channel hides no other")
        hidden = suggestions(links, followed=set(), hidden={"t.me", "t.me/denissexy"})
        self.assertEqual([s.key for s in hidden], ["t.me/seeallochnaya"])

    def test_a_source_follows_the_account_its_address_names(self):
        self.assertEqual(source_account("rss", "https://tg.i-c-a.su/rss/SeeAllOchnaya?limit=50"), "t.me/seeallochnaya")
        self.assertEqual(source_account("rss", "https://telegram.local/rss/denissexy?limit=50"), "t.me/denissexy")
        self.assertEqual(source_account("telegram", "ai_newz"), "t.me/ai_newz")
        self.assertEqual(source_account("rss", "https://nitter.local/karpathy/rss"), "x.com/karpathy")
        self.assertEqual(source_account("rss", "https://www.reddit.com/r/Xreal/.rss"), "reddit.com/r/xreal")
        self.assertEqual(source_account("reddit", "r/LocalLLaMA"), "reddit.com/r/localllama")
        self.assertEqual(source_account("rss", "https://github.com/anthropics/claude-code/releases.atom"),
                         "github.com/anthropics")
        self.assertEqual(source_account("youtube", "https://www.youtube.com/feeds/videos.xml?channel_id=UCabc"),
                         "youtube.com/channel/ucabc")
        self.assertEqual(account_key(normalize_url("https://www.reddit.com/r/Xreal/comments/1/x")), "reddit.com/r/xreal")


# ---- the job, the feed and the counts, on the database ----------------------------------------


@requires_db
class StoryJobTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc)
        self.mark = uuid.uuid4().hex[:8]
        self.service = StoriesService(db_url(), clock=lambda: self.now)
        self.reader = ReaderRepository(unread_window_days=None)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _source(self, name, **kwargs):
        source = insert_scratch_source(self.cur, in_main_digest=True, **kwargs)
        self.cur.execute("UPDATE sources SET settings = jsonb_build_object('display_name', %s::text) WHERE id = %s",
                         (name, source))
        return source

    def _post(self, source, *, site, hours_ago=1.0, title="A post", content="Body", html=None, content_hash=None):
        url = f"https://{site}-{self.mark}.test/{uuid.uuid4().hex}"
        self.cur.execute(
            """INSERT INTO posts (source_id, url, normalized_url, url_host, title, content, content_html, content_hash,
                                  published_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (source, url, normalize_url(url), f"{site}-{self.mark}.test", title, content, html,
             content_hash or uuid.uuid4().hex, self.now - timedelta(hours=hours_ago)),
        )
        return str(self.cur.fetchone()[0]), normalize_url(url)

    def _link(self, url, text="read"):
        return f'<p><a href="{url}">{text}</a></p>'

    def _job(self, *, full=True):
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        return self.service.regroup(self.cur, cutoff=None if full else self.now - timedelta(days=30))

    def _story_of(self, post_id):
        self.cur.execute("SELECT story_id, role, reasons FROM story_posts WHERE post_id = %s", (post_id,))
        row = self.cur.fetchone()
        return (str(row[0]), row[1], list(row[2])) if row else None

    def _launch(self):
        """A report, a copy of it on another site, and someone's own take, all linking one page."""
        page = f"https://launch-{self.mark}.test/2026/10/the-launch"
        self.anthropic = self._source("Anthropic")
        self.simon = self._source("Simon Willison")
        self.channel = self._source("A channel")
        self.lab, _ = self._post(self.anthropic, site="anthropic", hours_ago=5, title="Introducing the new model today",
                                 content=LONG, html=self._link(page), content_hash="same-" + self.mark)
        self.copy, _ = self._post(self.channel, site="channel", hours_ago=4, content=LONG, html=self._link(page),
                                  content_hash="same-" + self.mark)
        self.take, _ = self._post(self.simon, site="simon", hours_ago=3, title="My notes on the new model",
                                  html=self._link(page))
        self._job()

    def test_the_saver_reads_the_links_of_what_it_saved(self):
        source = self._source("Saver")
        repo = PostsRepository(db_url())
        page = f"https://elsewhere-{self.mark}.test/2026/10/a-page"
        own = f"https://saver-{self.mark}.test/about"
        # save_batch's two steps for one post, on the test's transaction (save_batch commits).
        post_id, was_inserted = repo.upsert_post(self.cur, {
            "url": f"https://saver-{self.mark}.test/p/1", "title": "t", "content": "c",
            "content_html": f'{self._link(page, "A page")}{self._link(own)}'}, source)
        repo._after_save(self.cur, PostDraft(source, {}), {}, post_id, was_inserted, None, surface=False)
        self.cur.execute("SELECT target_url, target_site, position, link_text FROM post_links WHERE post_id = %s",
                         (post_id,))
        self.assertEqual(self.cur.fetchall(), [(normalize_url(page), f"elsewhere-{self.mark}.test", 0, "A page")])
        self.cur.execute("SELECT links_scanned_at IS NOT NULL FROM posts WHERE id = %s", (post_id,))
        self.assertTrue(self.cur.fetchone()[0])

    def test_the_job_fills_old_posts_and_marks_a_signature(self):
        source = self._source("Newsletter")
        signature = f"https://sub-{self.mark}.test/subscribe-to-the-newsletter-now"
        posts = [self._post(source, site="news", hours_ago=n, html=self._link(signature) + self._link(
            f"https://x-{self.mark}.test/2026/10/story-number-{n}"))[0] for n in range(1, 5)]
        self._job()
        self.cur.execute("SELECT count(*) FILTER (WHERE boilerplate), count(*) FROM post_links WHERE post_id = ANY(%s::uuid[])",
                         (posts,))
        self.assertEqual(self.cur.fetchone(), (4, 8), "in 4 of 4 posts: the source's signature")

    def test_stories_roles_and_reasons(self):
        self._launch()
        story = self._story_of(self.lab)
        self.assertEqual(story, (self.lab, "report", ["text", "link"]), "keyed by its first post")
        self.assertEqual(self._story_of(self.copy), (self.lab, "share", ["text", "link"]))
        self.assertEqual(self._story_of(self.take), (self.lab, "report", ["link"]))
        self.cur.execute("SELECT voices FROM stories WHERE id = %s", (self.lab,))
        self.assertEqual(self.cur.fetchone()[0], 2, "the copy is the lab's voice again")

    def test_a_second_run_changes_nothing(self):
        self._launch()
        self.cur.execute("SELECT * FROM story_posts WHERE story_id = %s ORDER BY post_id", (self.lab,))
        before = self.cur.fetchall()
        again = self._job()
        self.assertEqual((again["changed"], again["boilerplate_changed"]), (0, 0))
        windowed = self._job(full=False)
        self.assertEqual((windowed["changed"], windowed["boilerplate_changed"]), (0, 0))
        self.cur.execute("SELECT * FROM story_posts WHERE story_id = %s ORDER BY post_id", (self.lab,))
        self.assertEqual(self.cur.fetchall(), before)

    def test_an_old_story_is_frozen(self):
        old = self._source("Old")
        other = self._source("Other")
        title = f"An old story told twice {self.mark}"
        a, _ = self._post(old, site="old", hours_ago=24 * 40, title=title)
        b, _ = self._post(other, site="other", hours_ago=24 * 39, title=title)
        self._job()
        self.cur.execute("UPDATE posts SET title = 'Something else entirely now' WHERE id = %s", (b,))
        self.assertEqual(self._job(full=False)["changed"], 0, "a story begun before the window is not recomputed")
        self.assertEqual(self._story_of(b)[0], a)
        self._job()
        self.assertIsNone(self._story_of(b), "a full run regroups it")

    # ---- the feed ---------------------------------------------------------------------------

    def _feed(self, **kwargs):
        items, _ = self.reader.list_posts(self.cur, FeedQuery(limit=100, **kwargs), now=self.now)
        return [i for i in items if i["id"] in (self.lab, self.copy, self.take)]

    def test_the_main_feed_shows_a_story_once_at_its_lead(self):
        self._launch()
        [row] = self._feed()
        self.assertEqual(row["id"], self.lab)
        self.assertEqual([s["name"] for s in row["story"]["sources"]], ["Anthropic", "A channel", "Simon Willison"])
        self.assertEqual([(p["id"], p["role"]) for p in row["story"]["posts"]], [(self.copy, "share"), (self.take, "report")])
        source_view = self.reader.list_posts(self.cur, FeedQuery(scope=FeedScope("source", self.channel)), now=self.now)[0]
        self.assertEqual([i["id"] for i in source_view], [self.copy], "a source's own view shows every post")
        self.assertNotIn("story", source_view[0])

    def test_the_lead_is_the_first_report_the_view_shows(self):
        self._launch()
        self.cur.execute("UPDATE sources SET in_main_digest = false WHERE id = %s", (self.anthropic,))
        self.assertEqual([r["id"] for r in self._feed()], [self.take], "a report before an earlier share")
        self.cur.execute("UPDATE sources SET in_main_digest = true WHERE id = %s", (self.anthropic,))
        self.reader.set_read(self.cur, [self.lab], True)
        self.assertEqual([r["id"] for r in self._feed(filter="unread")], [self.take], "the other report stays unread")
        self.assertEqual([r["id"] for r in self._feed(filter="all")], [self.lab])

    def test_history_does_not_fold_a_story(self):
        self._launch()
        for post_id in (self.lab, self.copy, self.take):
            self.cur.execute("INSERT INTO post_interactions (post_id, interaction_type) VALUES (%s, 'opened')", (post_id,))
        self.assertEqual(sorted(r["id"] for r in self._feed(filter="history")), sorted([self.lab, self.copy, self.take]))

    def test_reading_the_lead_reads_its_shares_not_other_reports(self):
        self._launch()
        marked = self.reader.set_read(self.cur, [self.lab], True)
        self.assertEqual(sorted(marked), sorted([self.lab, self.copy]))
        self.cur.execute("SELECT post_id FROM post_reader_state WHERE read_at IS NOT NULL AND post_id = ANY(%s::uuid[])",
                         ([self.lab, self.copy, self.take],))
        self.assertEqual(sorted(str(r[0]) for r in self.cur.fetchall()), sorted([self.lab, self.copy]))

    def test_mark_read_through_marks_rows_and_their_shares(self):
        self._launch()
        newest = FeedCursor(self.now, "ffffffff-ffff-ffff-ffff-ffffffffffff")
        through = FeedCursor(self.now - timedelta(hours=6), "00000000-0000-0000-0000-000000000000")
        folder = self._folder()
        marked = self.reader.mark_read_through(self.cur, FeedScope("folder", folder), through, newest=newest, now=self.now)
        self.assertEqual(sorted(marked), sorted([self.lab, self.copy]), "the folded report is no row of its own")

    def _folder(self):
        self.cur.execute("INSERT INTO folders (name) VALUES (%s) RETURNING id", (f"stories-{self.mark}",))
        folder = str(self.cur.fetchone()[0])
        for source in (self.anthropic, self.simon, self.channel):
            self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (folder, source))
        return folder

    def test_unread_counts_count_rows(self):
        self._launch()
        folder = self._folder()
        counts = self.reader.unread_counts(self.cur)
        self.assertEqual(counts["by_folder"][folder], 1, "one story, one row")
        self.assertEqual(counts["by_source"][self.channel], 1, "a source counts its posts")
        self.reader.set_read(self.cur, [self.lab], True)
        self.assertEqual(self.reader.unread_counts(self.cur)["by_folder"][folder], 1, "the other report is still unread")
        self.reader.set_read(self.cur, [self.take], True)
        self.assertNotIn(folder, self.reader.unread_counts(self.cur)["by_folder"])

    # ---- Discover and removed sources -------------------------------------------------------

    def test_a_removed_source_is_never_suggested(self):
        source = self._source("Gone")
        self._post(source, site="gone", hours_ago=1)
        SourcesRepository(db_url()).delete_source(self.cur, source)
        self.cur.execute("SELECT reason FROM discover_hidden WHERE key = %s", (f"gone-{self.mark}.test",))
        self.assertEqual(self.cur.fetchone(), ("removed",))
        self.assertIn(f"gone-{self.mark}.test", StoriesRepository.hidden(self.cur))
        sources = SourceFacts(self.cur)
        self.assertNotIn(f"gone-{self.mark}.test", sources.followed())


@requires_test_db
class DiscoverServiceTests(unittest.TestCase):
    """GET /api/sources/suggested's service on committed rows (the service opens its own connections)."""

    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.site = f"cited-{self.mark}.test"
        self.addCleanup(self._clean)

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            cur.execute("DELETE FROM discover_hidden WHERE key LIKE %s", (f"%{self.mark}%",))

    def test_suggested_then_hidden(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            for n in range(3):
                source = insert_scratch_source(cur)
                url = f"https://voice{n}-{self.mark}.test/p"
                html = "".join(f'<a href="https://{self.site}/2026/10/the-story-{k}">Story {k}</a>' for k in range(2))
                cur.execute("INSERT INTO posts (source_id, url, normalized_url, url_host, content_html, published_at) "
                            "VALUES (%s, %s, %s, %s, %s, now())", (source, url, normalize_url(url), f"voice{n}-{self.mark}.test", html))
        service = StoriesService(db_url())
        service.fill_links()
        [found] = [s for s in service.discover()["suggestions"] if s["key"] == self.site]
        self.assertEqual((found["voices"], found["article_count"], found["link_count"]), (3, 2, 2))
        self.assertEqual(found["articles"][0]["title"], "Story 0")
        self.assertEqual(len(found["articles"][0]["linked_by"]), 3)
        service.hide(self.site)
        self.assertFalse([s for s in service.discover()["suggestions"] if s["key"] == self.site])


if __name__ == "__main__":
    unittest.main()
