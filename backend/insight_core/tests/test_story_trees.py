"""Stories as trees (issue 0064): each post of a story gets a parent, by evidence in order of
certainty, never one signal alone: the address's own site, citation (with in-degree, an outside
page as the origin), copy, then time only as a guarded tiebreaker. One parent per post, no cycles,
each parent's reason recorded.

The rules are tested as pure functions; the job, the feed, the post page and News on the database
in one transaction per test, rolled back.
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

from insight_core.db.repo_reader import FeedQuery, ReaderRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, requires_test_db, scratch_handle
from insight_core.tests._stories import insert_post, insert_source, story_post
from insight_core.utils.news_rules import lead
from insight_core.utils.story_rules import StoryPost, group
from insight_core.utils.tree_rules import PARENT_REASONS

DAY = datetime(2026, 10, 26, tzinfo=timezone.utc)   # 00:00:00: a date alone
NOON = DAY + timedelta(hours=12)
PAGE = "https://openai.com/index/introducing-terra"
LONG = "x" * 200


def post(pid, source, *, at=None, url=None, **fields):
    """story_post at NOON, at its own address unless `url` says."""
    return story_post(pid, source, at=at or NOON, url=url or f"https://{source}.test/{pid}", **fields)


def only(posts):
    stories = group(posts)
    assert len(stories) == 1, [sorted(p.id for p in s.posts) for s in stories]
    return stories[0]


def parents(story):
    """post -> (parent post or page, reason)"""
    return {pid: (p or u, r) for pid, (p, u, r) in story.parents.items()}


def depth(story, pid):
    n = 0
    while story.parents[pid][0]:
        pid, n = story.parents[pid][0], n + 1
    return n + (1 if story.parents[pid][1] else 0)


def terra():
    """GPT-6.1 Terra on the lab: OpenAI's own post (a date alone) and HN's row of it share the
    address; data_secrets and Simon link it (the link resolves to HN's row, the first seen);
    LessWrong links Simon's post."""
    return [
        post("openai", "oa", at=DAY, site="openai.com", url=PAGE, title="Introducing GPT-6.1 Terra"),
        post("hn", "hn", hours=6, kind="hn", site="github.com", url=PAGE, title="GPT-6.1 Terra", links=[(PAGE, "hn")]),
        post("ds", "ds", hours=6.2, kind="telegram", site="t.me", links=[(PAGE, "hn")]),
        post("simon", "sw", hours=11.9, links=[(PAGE, "hn")]),
        post("lw", "lw", hours=40, links=[("https://sw.test/simon", "simon")]),
    ]


class TreeRulesTests(unittest.TestCase):
    # ---- 1. the address's own site -------------------------------------------------------------

    def test_two_posts_at_one_address_are_one_story(self):
        story = only([post("openai", "oa", at=DAY, site="openai.com", url=PAGE, title="Introducing Terra"),
                      post("hn", "hn", hours=6, kind="hn", url=PAGE, title="Terra")])
        self.assertEqual(story.reasons["hn"], ["address"])
        self.assertEqual(parents(story), {"openai": (None, None), "hn": ("openai", "address")})

    def test_two_posts_at_one_address_of_one_source_are_no_story(self):
        self.assertEqual(group([post("a", "df", url=PAGE, title="One"), post("b", "df", hours=1, url=PAGE, title="Two")]), [])

    def test_terra_its_own_post_is_the_origin_and_links_to_the_address_are_links_to_it(self):
        story = only(terra())
        self.assertEqual(parents(story), {
            "openai": (None, None), "hn": ("openai", "address"), "ds": ("openai", "citation"),
            "simon": ("openai", "citation"), "lw": ("simon", "citation"),
        })
        self.assertEqual(depth(story, "lw"), 2, "a tree deeper than one level")
        self.assertIsNone(story.origin_url, "the page is a stored post: no outside origin")

    def test_hacker_news_and_saved_pages_never_claim_an_address(self):
        story = only([post("hn", "hn", kind="hn", site="openai.com", url=PAGE, title="Terra"),
                      post("saved", "sv", hours=1, kind="saved", site="openai.com", url=PAGE, title="Saved Terra"),
                      post("hn2", "hn2", hours=2, kind="hn", site="openai.com", url=PAGE, title="Terra again")])
        self.assertEqual(story.reasons["saved"], ["address"], "still one story")
        self.assertNotIn("address", [r for _, r in parents(story).values()])

    def test_a_source_that_publishes_elsewhere_claims_nothing(self):
        story = only([post("a", "agg", site="openai.com", home="", url=PAGE, title="Terra"),
                      post("b", "b", hours=1, url=PAGE, title="Terra again")])
        self.assertNotIn("address", [r for _, r in parents(story).values()])

    # ---- 2. citation, whatever the dates say -----------------------------------------------------

    def test_a_citation_beats_a_later_date(self):
        # The citer's date is earlier than the post it links (a feed dated by its last update).
        story = only([post("cited", "a", hours=5), post("citer", "b", hours=1, links=[("https://a.test/cited", "cited")])])
        self.assertEqual(parents(story), {"cited": (None, None), "citer": ("cited", "citation")})

    def test_mutual_citations_make_no_cycle(self):
        story = only([post("a", "a", links=[("https://b.test/b", "b")]),
                      post("b", "b", hours=2, links=[("https://a.test/a", "a")])])
        self.assertEqual(parents(story), {"a": (None, None), "b": ("a", "citation")}, "the earlier time is the parent")

    def test_a_citation_beats_a_copy(self):
        story = only([
            post("orig", "a", title="The five words of this title"),
            post("other", "c", hours=1, title="Something else entirely here now"),
            post("copy", "b", hours=2, title="The five words of this title", links=[("https://c.test/other", "other")]),
        ])
        self.assertEqual(parents(story)["copy"], ("other", "citation"))

    def test_the_address_beats_a_citation(self):
        story = only([
            post("own", "oa", site="openai.com", url=PAGE, title="Terra"),
            post("blog", "b", hours=1, links=[(PAGE, "own")]),
            post("hn", "hn", hours=2, kind="hn", url=PAGE, title="Terra on HN", links=[("https://b.test/blog", "blog")]),
        ])
        self.assertEqual(parents(story)["hn"], ("own", "address"))

    # ---- an outside page as the origin, in-degree --------------------------------------------------

    def test_a_page_two_posts_are_about_is_the_origin(self):
        page = "https://anthropic.com/news/claude-fable-5"
        words = {page: "Claude Fable 5 and Mythos 5"}
        story = only([post("a", "a", links=[(page, None)], texts=words),
                      post("b", "b", hours=1, links=[(page, None)], texts={page: "here"}),
                      post("c", "c", hours=2, links=[(page, None), ("https://a.test/a", "a")], texts=words)])
        self.assertEqual((story.origin_url, story.origin_title, story.origin_linked_by),
                         (page, "Claude Fable 5 and Mythos 5", 3))
        self.assertEqual(parents(story), {"a": (page, "citation"), "b": (page, "citation"), "c": (page, "citation")},
                         "the page 3 voices link before the post 1 links")

    def test_a_stored_post_at_the_most_linked_address_is_the_root(self):
        story = only([post("own", "oa", hours=3, site="openai.com", url=PAGE, title="Terra"),
                      post("a", "a", links=[(PAGE, "own")]), post("b", "b", hours=1, links=[(PAGE, "own")])])
        self.assertIsNone(story.origin_url)
        self.assertEqual(parents(story), {"own": (None, None), "a": ("own", "citation"), "b": ("own", "citation")})

    def test_the_node_most_voices_are_about_is_the_origin_though_it_links_a_page(self):
        # Gemini 4 Carbon on the lab: Google's post and its copy link a benchmark page; three
        # others link Google's post.
        bench = "https://bench.test/evaluations/intelligence-index"
        g = "https://google.test/g"
        story = only([post("g", "google", links=[(bench, None)], title="Gemini Carbon our next frontier model"),
                      post("g2", "deepmind", links=[(bench, None)], title="Gemini Carbon our next frontier model"),
                      post("a", "a", hours=0.1, links=[(g, "g")]), post("b", "b", hours=0.2, links=[(g, "g")]),
                      post("c", "c", hours=1, links=[(g, "g")])])
        self.assertIsNone(story.origin_url)
        self.assertEqual(parents(story)["g"], (None, None))
        self.assertEqual(parents(story)["g2"], ("g", "none"), "the page is no origin; one time orders no copy")

    def test_a_roundups_mentions_make_no_origin_and_a_hub_is_no_root(self):
        x, y = "https://x.test/news/the-first-big-news", "https://y.test/news/another-big-news-item"
        hub = [(x, None), (y, None), ("https://z.test/news/a-third-news-item", None)]
        story = only([post("r1", "r1", links=hub), post("p", "p", hours=1, links=[(x, None)]),
                      post("r2", "r2", hours=2, links=[(x, None), (y, None), ("https://w.test/news/one-more-news-item", None)])])
        self.assertEqual(story.origin_url, x, "the roundups' first links count; their mentions (y) do not")
        self.assertTrue(all(page == x for page, _ in parents(story).values()))

    def test_only_the_origin_may_be_a_page(self):
        own = post("own", "oa", site="openai.com", url=PAGE, title="Terra")
        x = "https://x.test/news/a-side-page-of-it"
        story = only([own, post("a", "a", hours=1, links=[(PAGE, "own")]),
                      post("b", "b", hours=2, links=[(PAGE, "own"), (x, None)]),
                      post("c", "c", hours=3, links=[(PAGE, "own")]),
                      post("d", "d", hours=4, links=[(x, None)])])
        self.assertIsNone(story.origin_url)
        self.assertEqual(parents(story)["d"], ("own", "time"), "the side page dissolves; time places d under the origin")

    # ---- 3. copy, 4. time, and the times that can't order ------------------------------------------

    def test_a_copy_hangs_from_the_earlier_trustworthy_time(self):
        story = only([post("orig", "a", text_hash="h"), post("copy", "b", hours=0.05, text_hash="h")])
        self.assertEqual(parents(story), {"orig": (None, None), "copy": ("orig", "copy")})

    def test_a_date_alone_orders_nothing(self):
        story = only([post("day", "a", at=DAY, text_hash="h"), post("timed", "b", hours=-11, text_hash="h")])
        self.assertNotIn("copy", [r for _, r in parents(story).values()])
        self.assertEqual(parents(story)["day"], ("timed", "none"), "no claim of order")

    def test_a_saved_page_orders_nothing(self):
        # (A Saved page is no voice, issue 0070: a second source makes the story.)
        story = only([post("saved", "sv", kind="saved", hours=-24, text_hash="h"), post("orig", "a", text_hash="h"),
                      post("copy", "c", hours=1, text_hash="h")])
        self.assertEqual(parents(story), {"orig": (None, None), "saved": ("orig", "none"), "copy": ("orig", "copy")})

    def test_a_page_updated_since_its_date_orders_nothing(self):
        story = only([post("gwern", "g", hours=-480, updated=True, text_hash="h"), post("orig", "a", text_hash="h")])
        self.assertEqual(parents(story)["gwern"], ("orig", "none"))

    def test_time_needs_ten_minutes(self):
        own = post("own", "oa", site="openai.com", url=PAGE, title="Terra")
        x = "https://x.test/news/a-side-page-of-it"
        base = [own, post("a", "a", hours=1, links=[(PAGE, "own")]), post("b", "b", hours=2, links=[(PAGE, "own"), (x, None)]),
                post("c", "c", hours=3, links=[(PAGE, "own")])]
        story = only(base + [post("d", "d", hours=0.1, links=[(x, None)])])
        self.assertEqual(parents(story)["d"], ("own", "none"), "6 minutes apart: no order")

    # ---- the shape ------------------------------------------------------------------------------

    def test_one_parent_per_post_no_cycles_and_a_reason_each(self):
        stories = group(terra() + [
            post("c1", "c1", hours=1, links=[("https://c2.test/c2", "c2")]),
            post("c2", "c2", hours=2, links=[("https://c3.test/c3", "c3"), (PAGE, "hn")]),
            post("c3", "c3", hours=3, links=[("https://c1.test/c1", "c1")]),
        ])
        for story in stories:
            self.assertEqual(set(story.parents), {p.id for p in story.posts}, "every post, once")
            roots = [pid for pid, (p, u, r) in story.parents.items() if r is None]
            self.assertEqual(len(roots), 1 if story.origin_url is None else 0)
            for pid, (p, u, r) in story.parents.items():
                self.assertIn(r, (None, *PARENT_REASONS))
                seen = {pid}
                while p:
                    self.assertNotIn(p, seen, "no cycle")
                    seen.add(p)
                    p = story.parents[p][0]

    def test_news_leads_with_the_origin(self):
        self.assertEqual(lead([("a", "report"), ("b", "share"), ("c", "report")], ["b"]), "b")
        self.assertEqual(lead([("a", "share"), ("c", "report")]), "c", "no tree: the first report")


@requires_test_db
class TreeJobTests(unittest.TestCase):
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

    def _source(self, name, handle_suffix=""):
        return insert_source(self.cur, name, handle=scratch_handle() + handle_suffix, in_main_digest=True)

    def _post(self, source, url, *, at, title, html=None):
        return str(insert_post(self.cur, source, url, at=at, title=title, content="Body", html=html,
                               content_hash=uuid.uuid4().hex))

    def _terra(self):
        page = f"https://openai-{self.mark}.test/index/introducing-terra"
        day = (self.now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
        link = f'<p><a href="{page}">Introducing GPT-6.1 Terra</a></p>'
        oa, hn, ds, sw = (self._source("OpenAI News"), self._source("Hacker News", "?hnrss"),
                          self._source("data_secrets"), self._source("Simon Willison"))
        self.hn = self._post(hn, page + "/", at=day + timedelta(hours=2), title="GPT-6.1 Terra", html=link)   # first seen
        self.openai = self._post(oa, page, at=day, title="Introducing GPT-6.1 Terra")
        self._post(oa, f"https://openai-{self.mark}.test/index/older", at=day - timedelta(days=3), title="Older")
        self.ds = self._post(ds, f"https://ds-{self.mark}.test/1", at=day + timedelta(hours=3), title="Вышла GPT-6.1 Terra", html=link)
        self.simon = self._post(sw, f"https://simon-{self.mark}.test/terra", at=day + timedelta(hours=5), title="GPT-6.1 Terra notes", html=link)
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        return self.service.regroup(self.cur, cutoff=None)

    def _rows(self):
        self.cur.execute("SELECT post_id, parent_id, parent_reason, parent_url, reasons FROM story_posts WHERE post_id = ANY(%s::uuid[])",
                         ([self.openai, self.hn, self.ds, self.simon],))
        return {str(r[0]): (str(r[1]) if r[1] else None, r[2], r[3], list(r[4])) for r in self.cur.fetchall()}

    def test_the_job_records_each_parent_and_its_reason(self):
        self._terra()
        rows = self._rows()
        self.assertEqual({pid: row[:3] for pid, row in rows.items()}, {
            self.openai: (None, None, None), self.hn: (self.openai, "address", None),
            self.ds: (self.openai, "citation", None), self.simon: (self.openai, "citation", None),
        })
        self.assertIn("address", rows[self.hn][3])
        self.assertEqual(self.service.regroup(self.cur, cutoff=None)["changed"], 0, "a second run changes nothing")

    def test_the_origin_leads_the_row_and_the_post_page_has_the_tree(self):
        self._terra()
        items, _ = ReaderRepository(unread_window_days=None).list_posts(self.cur, FeedQuery(limit=100), now=self.now)
        [row] = [i for i in items if i["id"] in (self.openai, self.hn, self.ds, self.simon)]
        self.assertEqual(row["id"], self.openai, "the origin, though HN's row was seen first")
        story = row["story"]
        self.assertEqual((story["first"], story["parent_id"], story["parent_reason"], story["origin"]),
                         (self.openai, None, None, None))
        self.assertEqual({p["id"]: (p["parent_id"], p["parent_reason"]) for p in story["posts"]}, {
            self.hn: (self.openai, "address"), self.ds: (self.openai, "citation"), self.simon: (self.openai, "citation"),
        })
        page_story = PostDetailService.story(self.cur, self.simon)
        self.assertEqual((page_story["parent_id"], page_story["parent_reason"]), (self.openai, "citation"))

    def test_a_page_origin_is_stored_on_the_story(self):
        page = f"https://anthropic-{self.mark}.test/news/claude-fable-5"
        link = f'<p><a href="{page}">Claude Fable 5 and Mythos 5</a></p>'
        a, b = self._source("A"), self._source("B")
        pa = self._post(a, f"https://a-{self.mark}.test/1", at=self.now - timedelta(hours=3), title="Fable", html=link)
        pb = self._post(b, f"https://b-{self.mark}.test/1", at=self.now - timedelta(hours=2), title="Fable 5", html=link)
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        self.service.regroup(self.cur, cutoff=None)
        self.cur.execute("SELECT origin_url, origin_title, origin_linked_by FROM stories WHERE id = %s", (pa,))
        self.assertEqual(self.cur.fetchone(), (page, "Claude Fable 5 and Mythos 5", 2))
        self.cur.execute("SELECT parent_id, parent_reason, parent_url FROM story_posts WHERE post_id = %s", (pb,))
        self.assertEqual(self.cur.fetchone(), (None, "citation", page))

    def test_a_source_s_home_site(self):
        self._terra()
        facts = SourceFacts(self.cur)
        self.cur.execute("SELECT source_id FROM posts WHERE id = ANY(%s::uuid[]) ORDER BY published_at", ([self.openai, self.hn],))
        oa, hn = [str(r[0]) for r in self.cur.fetchall()]
        self.assertEqual((facts.home_site(oa), facts.home_site(hn)), (f"openai-{self.mark}.test", ""))


if __name__ == "__main__":
    unittest.main()
