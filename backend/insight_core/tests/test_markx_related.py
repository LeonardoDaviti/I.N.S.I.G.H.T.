"""Related reading (news.related, GET /api/markx/posts/{id}/related) on a _test database: the nearest posts by stored
vector at the floor, never the post, its story's members, its source's thread, a listed title or a source past its
share; a short report's linked page listed first and the list seeded by the two's mean; under RELATED_LOOSE items at
the floor, the nearest under it marked loose. Synthetic posts and vectors only."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from insight_core.markx import news, repo, tasks
from insight_core.tests._db import requires_test_db
from insight_core.tests.test_markx_api import _Api, call
from insight_core.tests.test_markx_embed import BUILD, unit

T0 = datetime(2100, 1, 1, tzinfo=timezone.utc)
D = timedelta(days=1)


class TheTitleKey(unittest.TestCase):
    def test_case_punctuation_spacing_and_a_leading_tag_are_one_title(self):
        self.assertEqual(news.title_key("[Project] How LLMs Work!"), news.title_key("how   LLMs work"))
        self.assertEqual(news.title_key("Как работают LLM?"), "как работают llm")
        self.assertEqual(news.title_key(None), "")


@requires_test_db
class Related(_Api):
    def vec(self, pid, near, *parts):
        """A vector at cosine `near` to the seed's (dimension 0), or of the (dimension, weight) `parts` given."""
        repo.put_embedding(self.cur, post_id=pid, model="bge-m3", text_hash=repo.sha256_hex(pid),
                           vector=unit(*(parts or ((0, near), (1, (1 - near * near) ** 0.5)))), model_sha256=BUILD)

    def made(self, title, near, *parts, source=None, at=None):
        pid = self.post(title, source=source, at=at or T0 - 10 * D)
        self.vec(pid, near, *parts)
        return pid

    def url_of(self, pid):
        self.cur.execute("SELECT normalized_url FROM posts WHERE id = %s", (pid,))
        return self.cur.fetchone()[0]

    def test_the_nearest_first_at_the_floor_with_what_is_left_out(self):
        seed = self.post("How LLMs work, a course", source=self.source, at=T0)
        self.vec(seed, 1.0)
        guide = self.made("What is a transformer model?", 0.9, source=self.other)
        thread = self.made("How LLMs work, part 2", 0.95, source=self.source, at=T0 + timedelta(hours=3))
        repost = self.made("How LLMs Work — a course!", 0.97, source=self.other, at=T0 - 40 * D)
        own_later = self.made("Tokenizers explained", 0.8, source=self.source, at=T0 - 30 * D)
        mate = self.made("Acme's course is out", 0.93, source=self.other, at=T0 - 50 * D)
        below = self.made("A 3D-printed vase", news.RELATED_MIN - 0.05, source=self.other, at=T0 - 60 * D)
        run = repo.start_run(self.cur, code_version="test", config={})
        story = repo.add_story(self.cur, first_at=T0, run_id=run)
        for p in (seed, mate):
            repo.open_membership(self.cur, story_id=story, post_id=p, role="member", reason="test", run_id=run)
        task_id, _ = tasks.read_task(self.cur, guide)
        c = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer={})
        repo.add_reading(self.cur, post_id=guide, guide="read-v3", call_id=c, kind="report", events="one", lang="en",
                         headline="What a transformer is", reading={"kind": "report", "events": "one",
                                                                    "event_type": "tutorial_explainer", "origin": "other"})

        status, body = call("GET", f"/api/markx/posts/{seed}/related")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["vector"])
        got = [(i["id"], i["guide"]) for i in body["items"]]
        # the repost (the post's own title), the thread (its source within a day) and the story's member are left
        # out; the explainer is marked; two at the floor, so the nearest under it fills the third place, loose
        self.assertEqual(got, [(guide, True), (own_later, False), (below, False)])
        self.assertEqual([i["loose"] for i in body["items"]], [False, False, True])
        self.assertIsNone(body["about"])
        self.assertEqual(body["items"][0]["title"], "What is a transformer model?")
        self.assertEqual(body["items"][0]["source"], "Example Site")
        self.assertAlmostEqual(body["items"][0]["cosine"], 0.9, places=2)
        self.assertNotIn(thread, [i["id"] for i in body["items"]])
        self.assertNotIn(repost, [i["id"] for i in body["items"]])

    def test_a_short_report_of_a_page_it_links_is_seeded_by_both_and_lists_the_page_first(self):
        # the report is news (dimension 0) with some of the course (dimension 1); the course page it links is stored
        page = self.made("How LLMs work, the course", None, (0, 0.3), (1, 0.954), source=self.other, at=T0 - 5 * D)
        seed = self.post("Acme released a free course, How LLMs Work", source=self.source, at=T0,
                         links=[(self.url_of(page), "the course")])
        self.vec(seed, None, (0, 0.8), (1, 0.6))
        news_ = self.made("Acme's new model is out", None, (0, 0.95), (2, 0.31), source=self.other, at=T0 - 20 * D)
        explainer = self.made("What a transformer is", None, (1, 0.95), (2, 0.31), source=self.other, at=T0 - 40 * D)
        off = self.made("A 3D-printed vase", None, (3, 1.0), source=self.other, at=T0 - 60 * D)
        before = news.related(self.cur, seed, about=False)["items"]
        self.assertEqual([i["id"] for i in before][:2], [page, news_])   # the news vector: the maker's news first
        body = news.related(self.cur, seed)
        self.assertEqual(body["about"], page)
        got = [(i["id"], i["about"], i["loose"]) for i in body["items"]]
        self.assertEqual(got[0], (page, True, False))
        ids = [i["id"] for i in body["items"]]
        self.assertLess(ids.index(explainer), ids.index(news_))          # the subject's explainer before the news
        self.assertNotIn(off, ids)

    def test_a_link_far_from_the_post_is_not_its_page(self):
        page = self.made("Unrelated page", None, (3, 1.0), source=self.other, at=T0 - 5 * D)
        seed = self.post("Seed", source=self.source, at=T0, links=[(self.url_of(page), "a link")])
        self.vec(seed, 1.0)
        self.assertIsNone(news.related_about(self.cur, seed))
        self.assertIsNone(news.related(self.cur, seed)["about"])

    def test_nothing_at_the_floor_lists_the_nearest_three_loose(self):
        seed = self.post("4x GPUs in a printed chassis", source=self.source, at=T0)
        self.vec(seed, 1.0)
        far = [self.made(f"Far {k}", 0.5 - k / 100, source=self.other, at=T0 - (10 + 3 * k) * D) for k in range(2)]
        far += [self.made(f"Farther {k}", 0.45 - k / 100, source=self.source, at=T0 - (30 + 3 * k) * D)
                for k in range(2)]
        items = news.related(self.cur, seed)["items"]
        self.assertEqual([i["id"] for i in items], far[:3])
        self.assertTrue(all(i["loose"] for i in items))

    def test_one_title_once_and_a_source_its_share(self):
        seed = self.post("Seed", source=self.source, at=T0)
        self.vec(seed, 1.0)
        same = [self.made("Prompt caching, explained", 0.9 - k / 100, source=self.other, at=T0 - (10 + 3 * k) * D)
                for k in range(2)]
        many = [self.made(f"Caching note {k}", 0.85 - k / 100, source=self.other, at=T0 - (40 + 3 * k) * D)
                for k in range(3)]
        got = [i["id"] for i in news.related(self.cur, seed)["items"]]
        self.assertEqual(got, [same[0], many[0]])   # the second copy of a title, then the source's third, left out

    def test_a_post_with_no_vector_has_none_and_a_bad_id_is_404(self):
        seed = self.post("Seed")
        self.assertEqual(call("GET", f"/api/markx/posts/{seed}/related")[1],
                         {"post_id": seed, "vector": False, "about": None, "items": []})
        self.assertEqual(call("GET", "/api/markx/posts/not-a-post/related")[0], 404)


if __name__ == "__main__":
    unittest.main()
