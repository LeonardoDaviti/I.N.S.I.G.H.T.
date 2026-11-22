"""v10.36: related reading (news.related, GET /api/markx/posts/{id}/related) against the run's own _test database:
the nearest posts by the stored vector, the nearest first, at the floor; never the post, its story's members, its own
source's posts within a day (a thread), a title already listed, or a source past its share; a reading's explainer
type marked. Synthetic posts and vectors only."""
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
    def vec(self, pid, near):
        """A vector at cosine `near` to the seed's (dimension 0)."""
        repo.put_embedding(self.cur, post_id=pid, model="bge-m3", text_hash=repo.sha256_hex(pid),
                           vector=unit((0, near), (1, (1 - near * near) ** 0.5)), model_sha256=BUILD)

    def made(self, title, near, *, source=None, at=None):
        pid = self.post(title, source=source, at=at or T0 - 10 * D)
        self.vec(pid, near)
        return pid

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
        # the repost (the post's own title), the thread (its source within a day), the story's member and the post
        # under the floor are left out; the explainer is marked
        self.assertEqual(got, [(guide, True), (own_later, False)])
        self.assertEqual(body["items"][0]["title"], "What is a transformer model?")
        self.assertEqual(body["items"][0]["source"], "Example Site")
        self.assertAlmostEqual(body["items"][0]["cosine"], 0.9, places=2)
        self.assertNotIn(thread, [i["id"] for i in body["items"]])
        self.assertNotIn(repost, [i["id"] for i in body["items"]])
        self.assertNotIn(below, [i["id"] for i in body["items"]])

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
        self.assertEqual(call("GET", f"/api/markx/posts/{seed}/related")[1], {"post_id": seed, "vector": False, "items": []})
        self.assertEqual(call("GET", "/api/markx/posts/not-a-post/related")[0], 404)


if __name__ == "__main__":
    unittest.main()
