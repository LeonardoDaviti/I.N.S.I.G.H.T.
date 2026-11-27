"""The story job's memory (0283): the name judging keeps only the titles that say a judged name, as compact rows; the
posts' links are read off the cursor with their stored post in SQL, one (target, stored) pair and one link text
object however many posts hold them; the batch drops its context before News. Every change leaves the rows written
as they were.
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
from insight_core.services.news_service import NewsService, Titled
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils.news_rules import name_surges
from insight_core.utils.story_rules import StoryPost

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


class Facts:
    """The SourceFacts the name rule reads: kind and publication."""
    def __init__(self, kinds):
        self.kind = kinds

    def publication(self, source_id):
        return f"{source_id}.test"


class TitlesRepo:
    """judge_names' reads: the loose matches stream (an iterator), the rest as the repository answers."""
    def __init__(self, rows, named_by):
        self.rows, self.named_by, self.written = rows, named_by, None
        self.streamed = False

    def followed_since(self, cur):
        return {s: NOW - timedelta(days=90) for s in ("s1", "s2", "s3", "s4", "s5", "r1")}

    def named(self, cur, phrases, at_least):
        return {"gpt 6"} & set(phrases)

    def surging(self, cur, phrases):
        return set()

    def naming(self, cur, names):
        return {n: set(self.named_by.get(n, ())) for n in names}

    def titles_saying(self, cur, words):
        self.streamed = True
        return iter([(r["id"], r["source_id"], r["t"], r["title"]) for r in self.rows])

    def titles_of(self, cur, ids):
        return [r for r in self.extra if r["id"] in ids]

    def write_surges(self, cur, found, names=None):
        self.written = (found, names)
        return len(found)


def _row(pid, source, hours, title):
    return {"id": pid, "source_id": source, "t": NOW + timedelta(hours=hours), "title": title}


class JudgeNamesTests(unittest.TestCase):
    """judge_names keeps, of the loose LIKE matches, only the titles that say a judged name or name it (stored keys):
    the surges are those of every match read as StoryPosts (the code before 0283)."""

    def setUp(self):
        says = [_row(f"p{i}", f"s{i % 5 + 1}", i, f"GPT-6 is out, report {i}") for i in range(6)]
        loose = [_row(f"n{i}", "s1", i + 0.5, "Great patterns: 6 tips") for i in range(40)]   # "g%p%t%6", never says it
        reddit = [_row("r", "r1", 2.2, "gpt 6 thread")]
        self.rows = says + loose + reddit
        self.extra = [_row("k", "s2", 3.1, "A title no longer saying it")]   # named by its stored key alone
        self.named_by = {"gpt 6": {"p0", "p1", "p2", "p3", "k"}}
        self.facts = Facts({"s1": "site", "s2": "site", "s3": "x", "s4": "site", "s5": "hn", "r1": "reddit"})

    def _before(self, followed):
        """The surges as the code before 0283 made them: every row a StoryPost."""
        every = {r["id"]: r for r in self.rows + self.extra}
        posts = [StoryPost(id=r["id"], source_id=r["source_id"], kind=self.facts.kind.get(r["source_id"], "site"),
                           own_site=self.facts.publication(r["source_id"]), t=r["t"], title=r["title"])
                 for r in every.values()]
        return name_surges(posts, followed, only={"gpt 6"}, named_by=self.named_by)

    def test_the_surges_are_those_of_every_loose_match(self):
        repo = TitlesRepo(self.rows, self.named_by)
        repo.extra = self.extra
        service = NewsService("unused", repo=repo, clock=lambda: NOW)
        service.judge_names(None, self.facts, ["GPT-6 lands"])
        found, names = repo.written
        self.assertTrue(repo.streamed)
        self.assertEqual(names, {"gpt 6"})
        before = self._before(repo.followed_since(None))
        self.assertTrue(before, "the case makes a surge")
        self.assertEqual([(s.name, s.at, s.posts, s.usual) for s in found],
                         [(s.name, s.at, s.posts, s.usual) for s in before])

    def test_only_the_titles_that_say_or_name_a_judged_name_are_kept(self):
        kept = []
        real = name_surges

        def spy(posts, *a, **k):
            kept.extend(posts)
            return real(posts, *a, **k)
        import insight_core.services.news_service as module
        module.name_surges, was = spy, module.name_surges
        try:
            repo = TitlesRepo(self.rows, self.named_by)
            repo.extra = self.extra
            NewsService("unused", repo=repo, clock=lambda: NOW).judge_names(None, self.facts, ["GPT-6 lands"])
        finally:
            module.name_surges = was
        self.assertEqual(sorted(p.id for p in kept), ["k", "p0", "p1", "p2", "p3", "p4", "p5", "r"],
                         "none of the 40 loose matches that never say it")
        self.assertTrue(all(isinstance(p, Titled) for p in kept))

    def test_a_title_rows_place_is_a_story_posts(self):
        titled = NewsService._titler(self.facts)
        for source in ("s1", "s3", "s5", "r1", "unknown"):
            row = titled("p", source, NOW, "GPT-6")
            post = StoryPost(id="p", source_id=source, kind=self.facts.kind.get(source, "site"),
                             own_site=self.facts.publication(source), t=NOW, title="GPT-6")
            self.assertEqual((row.id, row.source_id, row.kind, row.t, row.title, row.place),
                             (post.id, post.source_id, post.kind, post.t, post.title, post.place), source)


@requires_test_db
class LoadPostsTests(unittest.TestCase):
    """load_posts reads each post's kept links in order with the stored post each is (the first stored at its
    address), and holds one (target, stored) pair and one link text however many posts hold them."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.mark = uuid.uuid4().hex[:8]

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def test_links_in_order_with_their_stored_post_shared_between_posts(self):
        a, b = (insert_source(self.cur, f"{n} {self.mark}") for n in "AB")
        stored_url = f"https://stored-{self.mark}.test/2026/a-page"
        outside = f"https://outside-{self.mark}.test/2026/another-page"
        footer = f"https://a-{self.mark}.test/subscribe"
        first = insert_post(self.cur, a, stored_url, at=NOW - timedelta(days=2), title="The stored page")
        self.cur.execute("UPDATE posts SET fetched_at = %s WHERE id = %s", (NOW - timedelta(days=2), first))
        again = insert_post(self.cur, b, stored_url + "?again", normalized=stored_url, at=NOW - timedelta(days=1),
                            title="A later copy")
        self.cur.execute("UPDATE posts SET fetched_at = %s WHERE id = %s", (NOW - timedelta(days=1), again))
        one = insert_post(self.cur, a, f"https://a-{self.mark}.test/2026/one", at=NOW, title="One",
                          links=[(outside, "Another page"), (stored_url, "The stored page"), (footer, "Subscribe")])
        two = insert_post(self.cur, b, f"https://b-{self.mark}.test/2026/two", at=NOW, title="Two",
                          links=[(footer, "Subscribe"), (stored_url, None)])
        rows = {r["id"]: r for r in StoriesRepository.load_posts(self.cur, SourceFacts(self.cur),
                                                                 [str(one), str(two)])}
        self.assertEqual(rows[str(one)]["links"], [(outside, None), (stored_url, str(first)), (footer, None)],
                         "in order; the stored post is the first fetched at its address")
        self.assertEqual(rows[str(two)]["links"], [(footer, None), (stored_url, str(first))])
        self.assertEqual(rows[str(one)]["link_texts"],
                         {outside: "Another page", stored_url: "The stored page", footer: "Subscribe"})
        self.assertEqual(rows[str(two)]["link_texts"], {footer: "Subscribe"}, "a link without words has none")
        self.assertIs(rows[str(one)]["links"][2], rows[str(two)]["links"][0], "one pair however many posts hold it")
        self.assertIs(rows[str(one)]["link_texts"][footer], rows[str(two)]["link_texts"][footer])
        self.assertEqual(StoriesRepository.load_posts(self.cur, SourceFacts(self.cur), [])[:1], [])


class BatchContextTests(unittest.TestCase):
    """The batch hands News only its scope and seeds: News loads what else its window holds (`load`)."""

    def test_news_gets_the_scope_and_the_seeds_alone(self):
        service = StoriesService.__new__(StoriesService)
        seen = {}

        def update(cur, *, posts, load, **_):
            seen["posts"] = set(posts)
            load(["outside"])
            seen["after_load"] = set(posts)
            return {}
        rows = {pid: {"id": pid} for pid in ("seed", "mate", "context", "outside")}

        class Repo:
            def take_queue(self, cur, limit, redo=False):
                return [] if redo else [("post:seed", None)]

            def load_posts(self, cur, sources, ids):
                return [rows[i] for i in ids]
            mark_boilerplate = lambda self, cur, sources, ids: []
            take_keys = lambda self, cur, keys: 0
            stored_keys = lambda self, cur, ids: {}
            stories_holding = lambda self, cur, ids, besides: {}
            mentioned_by = lambda self, cur, ids: set()
            write_stories = lambda self, cur, stories, **k: 0
            pages_linked = lambda self, cur, ids: []
            write_edges = lambda self, cur, edges, **k: 0
            write_keys = lambda self, cur, keys: 0
            story_mates = lambda self, cur, ids: set()
            linking = lambda self, cur, urls: []

        class News:
            keep = timedelta(days=28)
        News.update = staticmethod(update)
        service.repo, service.news = Repo(), News()
        service._story_post = lambda row, sources: StoryPost(id=row["id"], source_id="s", kind="site",
                                                             own_site="s.test", t=NOW)
        service.stored_keys = lambda post: set()
        service._threads = lambda cur, sources, points, made_by: set()

        class Found:
            stories, root, listed, edges = [], {}, {}, []

        def neighbourhood(cur, posts, load, seeds, moved):
            load({"mate", "context"})
            service.rounds = [(2, 3, 3)]
            return Found(), {"seed", "mate"}
        service._neighbourhood = neighbourhood
        service._batch(None, None, {}, NOW, "x", redo=False, window=True)
        self.assertEqual(seen["posts"], {"seed", "mate"}, "the context read around the scope is gone")
        self.assertEqual(seen["after_load"], {"seed", "mate", "outside"}, "what News asks for is loaded")


if __name__ == "__main__":
    unittest.main()
