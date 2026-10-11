"""PostsRepository.save_batch: one save path that owns its transaction (spec §B.1, §5.3).

Scratch-source pattern: save_batch commits, so every class here is @requires_test_db and
only runs against a database whose name ends in `_test`. setUp clears leftovers, tearDown
deletes the scratch sources (posts cascade).
"""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_posts import PostDraft, PostsRepository
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db


def _drafts(source_id: str, count: int, *, tag: str) -> list[PostDraft]:
    return [
        PostDraft(source_id, {
            "url": f"https://test.invalid/mark-ix-post/{tag}/{n}",
            "title": f"Post {n}",
            "content": f"Body {n}",
            "date": None,
        })
        for n in range(1, count + 1)
    ]


class _FailingRepo(PostsRepository):
    """upsert_post raises for one url (per-post isolation)."""

    def __init__(self, url: str, fail_url: str):
        super().__init__(url)
        self.fail_url = fail_url

    def upsert_post(self, cur, post, source_id):
        if post["url"] == self.fail_url:
            raise ValueError("injected failure")
        return super().upsert_post(cur, post, source_id)


class _PoisoningRepo(PostsRepository):
    """Aborts the transaction outside any savepoint for one url."""

    def __init__(self, url: str, poison_url: str):
        super().__init__(url)
        self.poison_url = poison_url

    def upsert_post(self, cur, post, source_id):
        if post["url"] == self.poison_url:
            cur.execute("SELECT 1/0")
        return super().upsert_post(cur, post, source_id)


@requires_test_db
class SaveBatchTests(unittest.TestCase):
    def setUp(self):
        self.url = db_url()
        self.repo = PostsRepository(self.url)
        self.tag = uuid.uuid4().hex
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_a = insert_scratch_source(cur)
            self.source_b = insert_scratch_source(cur)
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _save(self, drafts, repo=None, commit_every=20):
        with psycopg.connect(self.url) as conn:
            return (repo or self.repo).save_batch(conn, drafts, commit_every=commit_every)

    def _stored_urls(self, source_id: str) -> set[str]:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT url FROM posts WHERE source_id = %s", (source_id,))
            return {row[0] for row in cur.fetchall()}

    def test_inserts_and_commits_every_draft(self):
        drafts = _drafts(self.source_a, 45, tag=self.tag)
        result = self._save(drafts)
        self.assertEqual(result.inserted, 45)
        self.assertEqual(result.updated, 0)
        self.assertEqual(len(set(result.inserted_ids)), 45)
        self.assertTrue(all(isinstance(i, str) for i in result.inserted_ids))
        # A fresh connection sees every row: the batch committed.
        self.assertEqual(self._stored_urls(self.source_a), {d.post["url"] for d in drafts})

    def test_resaving_reports_updates(self):
        drafts = _drafts(self.source_a, 45, tag=self.tag)
        self._save(drafts)
        again = self._save(drafts)
        self.assertEqual(again.inserted, 0)
        self.assertEqual(again.updated, 45)

    def test_one_failing_post_costs_one_post(self):
        drafts = _drafts(self.source_a, 45, tag=self.tag)
        repo = _FailingRepo(self.url, drafts[6].post["url"])
        result = self._save(drafts, repo=repo)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.failures[0].stage, "upsert")
        self.assertEqual(result.failures[0].url, drafts[6].post["url"])
        self.assertEqual(result.inserted, 44)

    def test_a_poisoned_transaction_discards_only_the_uncommitted_window(self):
        drafts = _drafts(self.source_a, 45, tag=self.tag)
        repo = _PoisoningRepo(self.url, drafts[24].post["url"])
        result = self._save(drafts, repo=repo, commit_every=20)

        stored = self._stored_urls(self.source_a)
        urls = [d.post["url"] for d in drafts]
        self.assertTrue(set(urls[:20]) <= stored, "the first committed batch survives")
        self.assertTrue(set(urls[20:25]).isdisjoint(stored), "21-25 die with the rollback")
        self.assertTrue(set(urls[25:]) <= stored, "26-45 are saved after the rollback")

        stages = {f.url: f.stage for f in result.failures}
        self.assertEqual(stages[urls[24]], "upsert")
        for url in urls[20:24]:
            self.assertEqual(stages[url], "discarded")
        self.assertEqual(result.inserted + result.failed, 45)
        self.assertEqual(result.inserted, 40)
        self.assertEqual(len(result.inserted_ids), 40)

    def test_external_id_collision_is_an_update(self):
        first = PostDraft(self.source_a, {"url": f"https://test.invalid/mark-ix-post/{self.tag}/old",
                                          "external_id": "X1", "title": "t", "content": "c", "date": None})
        moved = PostDraft(self.source_a, {"url": f"https://test.invalid/mark-ix-post/{self.tag}/new",
                                          "external_id": "X1", "title": "t", "content": "c", "date": None})
        self._save([first])
        result = self._save([moved])
        self.assertEqual(result.updated, 1)
        self.assertEqual(result.failed, 0)

    def test_by_source_splits_counts(self):
        drafts = _drafts(self.source_a, 3, tag=self.tag + "a") + _drafts(self.source_b, 2, tag=self.tag + "b")
        self._save(drafts[:1])
        result = self._save(drafts)
        self.assertEqual(result.by_source[self.source_a], {"inserted": 2, "updated": 1, "failed": 0})
        self.assertEqual(result.by_source[self.source_b], {"inserted": 2, "updated": 0, "failed": 0})


if __name__ == "__main__":
    unittest.main()
