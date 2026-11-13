"""One story, many sources (issue 0050): post links, the joining rules, roles, voices, the story
job, the folded feed, read propagation, unread counts and Discover.

The rules are tested as pure functions; the job, the feed and the counts on the database in
one transaction per test, rolled back (the job regroups every post it sees, the test's own
included, and nothing of it is kept). Assertions are scoped to the test's own rows.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_posts import PostDraft, PostsRepository
from insight_core.db.repo_reader import FeedQuery, FeedScope, ReaderRepository, FeedCursor
from insight_core.db.repo_sources import SourcesRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository, source_account
from insight_core.services.stories_service import (LOCK_KEY, SETTINGS_KEY, StoriesService, in_own_process,
                                                     recompute_job, rules_stamp)
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_db, requires_test_db
from insight_core.tests._stories import insert_post, insert_source, story_post
from insight_core.utils.addresses import account_key, site_of
from insight_core.utils.post_links import extract_links, is_home, source_kind
from insight_core.utils.discover_rules import suggestions
from insight_core.utils import voice
from insight_core.utils.story_rules import StoryPost, group, named_voices, roles
from insight_core.utils.url_normalization import normalize_url

T0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
LONG = "x" * 200   # a text long enough to be a copy


post = partial(story_post, at=T0, chars=0)


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
        self.assertTrue(is_home("https://x.com/nn_teacher"))
        self.assertTrue(is_home("https://openai.com/"))
        self.assertFalse(is_home("https://openai.com/index/gpt"))
        self.assertEqual(source_kind("rss", "https://www.reddit.com/r/Xreal/.rss"), "reddit")
        self.assertEqual(source_kind("rss", "https://tg.i-c-a.su/rss/dennis_it"), "telegram")
        self.assertEqual(source_kind("rss", "https://nitter.local/nn_teacher/rss"), "x")
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
        self.assertEqual(voice.count([a, b, c], voice.Policy.STORIES_IX), 2, "the person, not the subreddit")

    def test_a_citation_of_another_voice_within_72_hours(self):
        cited = post("a", "s1")
        self.assertEqual(ids(group([cited, post("b", "s2", hours=10, links=[("https://s1.test/2026/10/a-post", "a")])])),
                         [["a", "b"]])
        self.assertEqual(group([cited, post("b", "s2", hours=100, links=[("https://s1.test/2026/10/a-post", "a")])]), [])
        self.assertEqual(group([cited, post("b", "s3", site="s1.test", hours=10,
                                            links=[("https://s1.test/2026/10/a-post", "a")])]), [], "its own voice")

    def test_a_cited_stored_post_with_a_one_segment_address_still_joins(self):
        """Found on the server's data: @dennis_it cited blog.cloudflare.com/yandex-outage 2.8 hours
        after Cloudflare posted it, and the one-segment address was taken for a profile page."""
        cited = post("cf", "cloudflare", site="cloudflare.com", hours=0)
        citer = post("tg", "dennis_it", kind="telegram", hours=2.8,
                     links=[("https://blog.cloudflare.com/yandex-outage", "cf")])
        self.assertEqual(ids(group([cited, citer])), [["cf", "tg"]])

    def test_home_and_profile_pages_join_nothing(self):
        self.assertEqual(group([post("a", "s1", links=[("https://x.com/nn_teacher", None)]),
                                post("b", "s2", links=[("https://x.com/nn_teacher", None)])]), [])

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


class NamedVoicesTests(unittest.TestCase):
    """Issue 0082: a story's names are the voices its count counts, one each."""

    NAMES = {"r1": "r/sub", "s1": "Blog One", "s2": "Blog One Feed", "s3": "Blog Three", "tg1": "Channel A",
             "tg2": "Channel B", "x1": "Account A", "x2": "Account B", "sv": "Saved"}

    def _named(self, posts, others=None):
        others = others or {}
        shaped = [{"source_id": p.source_id, "name": self.NAMES[p.source_id], "kind": p.kind, "voice": p.voice,
                   "text_key": p.text_key, "others": [{"id": s, "name": self.NAMES[s]} for s in others.get(p.id, ())]}
                  for p in posts]
        return named_voices(shaped)

    def test_each_voice_once_as_counted(self):
        posts = [post("a", "r1", kind="reddit", author="alice"),
                 post("b", "r1", kind="reddit", author="bob", hours=1),
                 post("c", "r1", kind="reddit", author="alice", hours=2),               # alice again: one voice
                 post("d", "s1", site="one.test", hours=3),
                 post("e", "s2", site="one.test", hours=4),                             # the publication's other feed
                 post("f", "tg1", kind="telegram", hours=5, text_hash="h", chars=200),
                 post("g", "tg2", kind="telegram", hours=6, text_hash="h", chars=200),           # a forward of f's text
                 post("h", "sv", kind="saved", hours=7)]                                # a page you saved: no voice
        named = self._named(posts)
        self.assertEqual([(v["id"], v["name"], v.get("place")) for v in named],
                         [("s1", "Blog One", None), ("tg1", "Channel A", None),
                          ("r1", "u/alice", "r/sub"), ("r1", "u/bob", "r/sub")],
                         "followed sources first, then Reddit authors (issue 0103), each by its first post")
        self.assertEqual([[s["id"] for s in v["with"]] for v in named], [["s2"], ["tg2"], [], []])
        self.assertEqual(len(named), voice.count(posts, voice.Policy.STORIES_IX), "the count is the names")

    def test_one_voice_lists_its_sources(self):
        """No count shows for one voice ("also shared by", 0072): its names are who said and shared it."""
        from insight_core.db.repo_reader import story_voices
        row = {"platform": "telegram", "handle": "https://t.me/s/a", "content_hash": "h", "text_chars": 200,
               "author": None, "reposted_by": None, "voice": None}
        forward = [{**row, "source_id": "tg1", "name": "Channel A"}, {**row, "source_id": "tg2", "name": "Channel B"}]
        self.assertEqual(story_voices(forward, dict), [{"id": "tg1", "name": "Channel A"}, {"id": "tg2", "name": "Channel B"}])
        other = {**row, "source_id": "s3", "name": "Blog Three", "content_hash": None, "platform": "rss", "handle": "https://three.test/feed"}
        self.assertEqual([(v["name"], [w["id"] for w in v["with"]]) for v in story_voices([*forward, other], dict)],
                         [("Channel A", ["tg2"]), ("Blog Three", [])])

    def test_a_followed_author_of_a_reposted_tweet_is_a_voice(self):
        repost = post("a", "x2", kind="x", author="accounta", reposted=True, author_source="x1")
        named = self._named([repost], {"a": ["x1"]})
        self.assertEqual([v["name"] for v in named], ["Account B", "Account A"])
        self.assertEqual(len(named), voice.count([repost], voice.Policy.STORIES_IX))
        # The author's own tweet in the story too: one voice, its tweet's source.
        own = post("b", "x1", kind="x", author="accounta", hours=-1)
        named = self._named([own, repost], {"a": ["x1"]})
        self.assertEqual([(v["name"], v["with"]) for v in named], [("Account A", []), ("Account B", [])])
        self.assertEqual(len(named), voice.count([own, repost], voice.Policy.STORIES_IX))


# ---- Discover ---------------------------------------------------------------------------------


class DiscoverRulesTests(unittest.TestCase):
    def links(self, site, voices, paths):
        return [(v, f"https://{site}/{p}", False) for v in voices for p in paths]

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
        links = self.links("x.com", ["v1", "v2", "v3"], ["nn_teacher/2026-10-a-long-post-here",
                                                          "nn_teacher/notes-on-a-new-model-today"])
        links += self.links("x.com", ["v1", "v2", "v3"], ["status/what-a-day-it-has-been"])
        found = suggestions(links, followed=set(), hidden=set())
        self.assertEqual([s.key for s in found], ["x.com/nn_teacher"])

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
        for channel in ("seeall_notes", "dennis_it"):
            links += self.links("t.me", ["v1", "v2", "v3"], [f"{channel}/2026-10-a-long-post-here",
                                                             f"{channel}/notes-on-a-new-model-today"])
        followed = suggestions(links, followed={"t.me"}, hidden=set(), followed_accounts={"t.me/seeall_notes"})
        self.assertEqual([s.key for s in followed], ["t.me/dennis_it"], "following one channel hides no other")
        hidden = suggestions(links, followed=set(), hidden={"t.me", "t.me/dennis_it"})
        self.assertEqual([s.key for s in hidden], ["t.me/seeall_notes"])

    def test_a_source_follows_the_account_its_address_names(self):
        self.assertEqual(source_account("rss", "https://tg.i-c-a.su/rss/Seeall_notes?limit=50"), "t.me/seeall_notes")
        self.assertEqual(source_account("rss", "https://telegram.local/rss/dennis_it?limit=50"), "t.me/dennis_it")
        self.assertEqual(source_account("telegram", "ai_dispatch"), "t.me/ai_dispatch")
        self.assertEqual(source_account("rss", "https://nitter.local/nn_teacher/rss"), "x.com/nn_teacher")
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
        return insert_source(self.cur, name, in_main_digest=True, **kwargs)

    def _post(self, source, *, site, hours_ago=1.0, title="A post", content="Body", html=None, content_hash=None):
        url = f"https://{site}-{self.mark}.test/{uuid.uuid4().hex}"
        post_id = insert_post(self.cur, source, url, at=self.now - timedelta(hours=hours_ago), title=title,
                              content=content, html=html, content_hash=content_hash or uuid.uuid4().hex)
        return str(post_id), normalize_url(url)

    def _link(self, url, text="read"):
        return f'<p><a href="{url}">{text}</a></p>'

    def _job(self, *, full=True):
        """A full run (and the setting that says so), or the incremental job after one."""
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        return self.service.full_on(self.cur) if full else self.service.update(self.cur)

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
        self.cur.execute("UPDATE posts SET created_at = created_at - interval '1 hour' WHERE id = %s", (self.lab,))
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

    def test_a_sites_linked_articles_are_its_hosts_article_links(self):
        # Issue 0060: what Follow ranks a site's findings by.
        site = f"lab-{self.mark}.test"
        source, other = self._source("A"), self._source("B")
        post = (self._link(f"https://www.{site}/blog/a-post-about-the-model") + self._link(f"https://{site}/about")
                + self._link(f"https://docs.{site}/guides/a-guide-to-the-model"))
        self._post(source, site="a", html=post)
        self._post(other, site="b", html=self._link(f"https://{site}/blog/a-post-about-the-model")
                   + self._link(f"https://{site}/2026/10/news"))
        self._job()
        self.assertEqual(StoriesRepository.linked_articles(self.cur, f"www.{site}"),
                         [f"https://{site}/2026/10/news", f"https://{site}/blog/a-post-about-the-model"])
        self.assertEqual(StoriesRepository.linked_articles(self.cur, f"docs.{site}"),
                         [f"https://docs.{site}/guides/a-guide-to-the-model"])

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
        self.assertEqual(story, (self.lab, "report", ["text", "link"]), "keyed by its post stored first")
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
        self.assertEqual(self._job(full=False), {}, "the incremental job after it finds nothing to do")
        self.cur.execute("SELECT * FROM story_posts WHERE story_id = %s ORDER BY post_id", (self.lab,))
        self.assertEqual(self.cur.fetchall(), before)

    def test_an_old_story_is_regrouped_too(self):
        # Issue 0072 A: no window and no frozen stories; a change to a month-old post regroups its story.
        old = self._source("Old")
        other = self._source("Other")
        title = f"An old story told twice {self.mark}"
        a, _ = self._post(old, site="old", hours_ago=24 * 40, title=title)
        b, _ = self._post(other, site="other", hours_ago=24 * 39, title=title)
        self._job()
        self.assertIsNotNone(self._story_of(b))
        self.cur.execute("UPDATE posts SET title = 'Something else entirely now' WHERE id = %s", (b,))
        self.assertGreater(self._job(full=False)["changed"], 0)
        self.assertIsNone(self._story_of(b))
        self.assertEqual(self._job()["changed"], 0, "as a full run makes it")

    # ---- the feed ---------------------------------------------------------------------------

    def _feed(self, **kwargs):
        items, _ = self.reader.list_posts(self.cur, FeedQuery(limit=100, **kwargs), now=self.now)
        return [i for i in items if i["id"] in (self.lab, self.copy, self.take)]

    def test_the_main_feed_shows_a_story_once_at_its_lead(self):
        self._launch()
        [row] = self._feed()
        self.assertEqual(row["id"], self.lab)
        # One name a voice (issue 0082): the channel's copy is the lab's voice, named once with it.
        self.assertEqual([(s["name"], [w["name"] for w in s["with"]]) for s in row["story"]["sources"]],
                         [("Anthropic", ["A channel"]), ("Simon Willison", [])])
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
class StoryJobYieldsTests(unittest.TestCase):
    """v10.13.7: an incremental run stops after STEP_BUDGET_S with work left, then rests REST_AFTER_YIELD_S, so the
    decision run (which waits for the story job's lock) gets its turn; a run with nothing left ends as before."""

    def setUp(self):
        from insight_core.services import stories_service as S
        self.S = S
        self.now = datetime.now(timezone.utc)
        self.service = S.StoriesService(db_url(), clock=lambda: self.now)
        for name in ("catch_up_safely",):
            patcher = mock.patch.object(S, name, lambda *a, **k: None)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("fill_links", "fill_refs", "fill_series"):
            patcher = mock.patch.object(S.StoriesService, name, lambda self_, *a, **k: 0)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self._clear)
        self._clear()

    def _clear(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM system_settings WHERE key = %s", (self.S.YIELD_KEY,))

    def _advance(self, steps):
        left = iter(steps)

        def advance(self_, cur, totals, **kw):
            totals["batches"] += 1
            return next(left)
        return mock.patch.object(self.S.StoriesService, "advance", advance)

    def test_a_run_with_work_left_yields_after_its_budget_then_rests(self):
        with mock.patch.object(self.S, "STEP_BUDGET_S", 0.0), self._advance([True, True, True]):
            first = self.service.recompute()
        self.assertTrue(first.get("yielded"), first)
        self.assertEqual(first["batches"], 1)                              # one batch, then its budget was spent
        with self._advance([True]):
            self.assertEqual(self.service.recompute(), {"skipped": "resting after a yield"})
        self.now += timedelta(seconds=self.S.REST_AFTER_YIELD_S + 1)       # the rest is over
        with mock.patch.object(self.S, "STEP_BUDGET_S", 0.0), self._advance([False]):
            again = self.service.recompute()
        self.assertNotIn("skipped", again)

    def test_a_run_steps_aside_for_a_decision_run_that_waited_ten_minutes(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO mx_jobs (job) VALUES ('decide') ON CONFLICT (job) DO NOTHING")
            cur.execute("SELECT wanted_at, started_at, stage FROM mx_jobs WHERE job = 'decide'")
            saved = cur.fetchone()
            cur.execute("UPDATE mx_jobs SET wanted_at = %s, started_at = %s, stage = NULL WHERE job = 'decide'",
                        (self.now - timedelta(minutes=11), self.now - timedelta(minutes=30)))
        self.addCleanup(self._restore_decide, saved)
        with self._advance([False]):
            self.assertEqual(self.service.recompute(), {"skipped": "a decision run's turn"})
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:   # it started: the job goes on
            cur.execute("UPDATE mx_jobs SET started_at = %s WHERE job = 'decide'", (self.now - timedelta(minutes=1),))
        with self._advance([False]):
            self.assertNotIn("skipped", self.service.recompute())

    def _restore_decide(self, saved):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("UPDATE mx_jobs SET wanted_at = %s, started_at = %s, stage = %s WHERE job = 'decide'", saved)

    def test_a_run_that_empties_its_queue_never_yields(self):
        with self._advance([True, True, False]):
            done = self.service.recompute()
        self.assertNotIn("yielded", done)
        self.assertEqual(done["batches"], 3)
        with self._advance([False]):
            self.assertNotIn("skipped", self.service.recompute())          # no rest without a yield


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
                source = insert_scratch_source(cur, enabled=True)   # on: your sources (issue 0200)
                url = f"https://voice{n}-{self.mark}.test/p"
                html = "".join(f'<a href="https://{self.site}/2026/10/the-story-{k}">The story {k}</a>' for k in range(2))
                cur.execute("INSERT INTO posts (source_id, url, normalized_url, url_host, content_html, published_at) "
                            "VALUES (%s, %s, %s, %s, %s, now())", (source, url, normalize_url(url), f"voice{n}-{self.mark}.test", html))
        service = StoriesService(db_url())
        service.fill_links()
        [found] = [s for s in service.discover()["suggestions"] if s["key"] == self.site]
        self.assertEqual((found["voices"], found["article_count"], found["link_count"]), (3, 2, 2))
        self.assertEqual(found["articles"][0]["title"], "The story 0", "words 3 voices agree on")
        self.assertEqual(len(found["articles"][0]["linked_by"]), 3)
        self.assertIs(service._discover_all(), service._discover_all(), "kept while nothing it reads changed")
        service.hide(self.site)
        self.assertFalse([s for s in service.discover()["suggestions"] if s["key"] == self.site])

    def test_the_kept_list_follows_its_inputs(self):
        service = StoriesService(db_url())
        first = service._discover_all()
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            insert_scratch_source(cur)   # a source added: the list is computed again
        self.assertIsNot(service._discover_all(), first)


def _write_pid(path: str) -> None:
    """A job for in_own_process (module-level: the child imports it by name)."""
    Path(path).write_text(str(os.getpid()))


def _die() -> None:
    raise SystemExit(3)


def _killed() -> None:
    os.kill(os.getpid(), signal.SIGKILL)   # as the out-of-memory killer ends a process


def _killed_in_the_job(url: str) -> None:
    """The story job, killed while it holds its lock, before it writes anything."""
    with mock.patch.object(StoriesService, "step", lambda *args, **kwargs: _killed()):
        recompute_job(url)


class OwnProcessTests(unittest.TestCase):
    """The story job runs in a process of its own (issue 0072), so the API and ingestion keep none
    of what it read."""

    def test_the_job_runs_in_another_process_and_is_waited_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pid")
            in_own_process(_write_pid, path)
            self.assertNotEqual(int(Path(path).read_text()), os.getpid(), "done, by another process")

    def test_a_job_that_dies_is_logged_never_raised(self):
        with self.assertLogs("insight_core.services.stories_service", "ERROR") as logs:
            in_own_process(_die)
        self.assertIn("exit code 3", logs.output[0])

    def test_a_job_killed_is_logged_never_raised(self):
        with self.assertLogs("insight_core.services.stories_service", "ERROR") as logs:
            in_own_process(_killed)
        self.assertIn(f"exit code {-signal.SIGKILL}", logs.output[0])

    def test_the_story_job_after_a_fetch_run_runs_in_its_own_process(self):
        from insight_core.ingestion import default_runner

        async def build():   # the runner's gates belong to a running loop
            return default_runner(url)

        url = "postgresql://insight:insight@nowhere.invalid:5432/none"
        port = asyncio.run(build()).stories
        self.assertEqual((port.func, port.args), (in_own_process, (recompute_job, url)))


@requires_test_db
class KilledJobTests(unittest.TestCase):
    """A story job killed in its process (out of memory, issue 0072) writes nothing and holds
    nothing: the next run recomputes."""

    def _setting(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            return SystemSettingsRepository.get(cur, SETTINGS_KEY)

    def setUp(self):
        kept = self._setting()
        self.addCleanup(self._restore, kept[0] if kept else None)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            SystemSettingsRepository.upsert(cur, SETTINGS_KEY, {"rules": "older rules"})

    def _restore(self, value):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            if value is None:
                cur.execute("DELETE FROM system_settings WHERE key = %s", (SETTINGS_KEY,))
            else:
                SystemSettingsRepository.upsert(cur, SETTINGS_KEY, value)

    def test_the_next_run_recomputes(self):
        with self.assertLogs("insight_core.services.stories_service", "ERROR") as logs:
            in_own_process(_killed_in_the_job, db_url())
        self.assertIn(f"exit code {-signal.SIGKILL}", logs.output[0])
        self.assertEqual(self._setting()[0], {"rules": "older rules"}, "nothing written")
        with psycopg.connect(db_url(), autocommit=True) as conn:   # the server ends the killed session
            for _ in range(600):   # up to 60 s: the server ends the session later on a loaded machine
                if conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,)).fetchone()[0]:
                    conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))
                    break
                time.sleep(0.1)
            else:
                self.fail("the killed job's lock is still held")
        StoriesService(db_url()).recompute()   # the next run: the rule change's rebuild, as the killed one would have
        self.assertEqual(self._setting()[0]["rules"], rules_stamp())
        self.assertNotIn("rebuild", self._setting()[0], "done")


if __name__ == "__main__":
    unittest.main()
