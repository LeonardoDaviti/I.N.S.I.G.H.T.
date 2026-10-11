"""
Contract tests for PostsRepository.upsert_post.

These exist because of a real incident: on 2026-07-22 two scheduler cycles each
discarded a full 30-minute fetch. `upsert_post` declared `ON CONFLICT (url)`, but
posts carries a SECOND unique index - posts_source_external_unique on
(source_id, external_id) WHERE external_id IS NOT NULL (0002_posts.sql:24). A source
republishing an item at a new URL under the same external_id skipped the url conflict,
hit the uncovered index, and raised. safe_ingest saves every post of a cycle in one
transaction, so the raise put the backend in aborted-transaction state and the terminal
commit was never reached. Nothing in the suite covered that path.

Everything here runs inside ONE transaction that tearDown rolls back, so the tests are
safe against the live DATABASE_URL and leave no rows behind.

The assertions deliberately test the CONTRACT, not the implementation:
  - upsert_post never raises UniqueViolation for posts_source_external_unique
  - the caller's transaction stays usable afterwards
  - (post_id, was_inserted) stays truthful
so they survive any refactor of how the collision is resolved.
"""
from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_posts import PostsRepository


def _db_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")


def _database_reachable() -> bool:
    url = _db_url()
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=5):
            return True
    except Exception:
        return False


@unittest.skipUnless(_database_reachable(), "DATABASE_URL not reachable")
class UpsertPostCollisionTests(unittest.TestCase):
    """One transaction per test, always rolled back."""

    def setUp(self):
        self.repo = PostsRepository(_db_url())
        self.conn = psycopg.connect(_db_url())
        self.cur = self.conn.cursor()
        # Two scratch sources. The suffix keeps them unique against
        # sources_platform_handle_or_url_key even if a previous run died mid-transaction.
        suffix = uuid.uuid4().hex[:12]
        self.source_a = self._make_source(f"https://test.invalid/a/{suffix}")
        self.source_b = self._make_source(f"https://test.invalid/b/{suffix}")

    def tearDown(self):
        # Never commit. The scratch sources, and every post cascaded to them, vanish.
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _make_source(self, handle: str) -> str:
        self.cur.execute(
            "INSERT INTO sources (platform, handle_or_url) VALUES ('rss', %s) RETURNING id",
            (handle,),
        )
        return str(self.cur.fetchone()[0])

    def _post(self, url: str, external_id: str | None = None, **overrides) -> dict:
        post = {
            "url": url,
            "external_id": external_id,
            "title": "Title",
            "content": "Body",
            "date": None,
        }
        post.update(overrides)
        return post

    def _transaction_is_usable(self) -> bool:
        """A poisoned transaction fails every later statement with 25P02."""
        try:
            self.cur.execute("SELECT 1")
            return self.cur.fetchone()[0] == 1
        except psycopg.Error:
            return False

    # ---- baseline ----

    def test_insert_then_update_by_url_reports_inserted_correctly(self):
        post_id, inserted = self.repo.upsert_post(self.cur, self._post("https://x.test/1"), self.source_a)
        self.assertTrue(inserted)

        same_id, inserted_again = self.repo.upsert_post(
            self.cur, self._post("https://x.test/1"), self.source_a
        )
        self.assertEqual(post_id, same_id)
        self.assertFalse(inserted_again, "second upsert of the same url must be an update")

    # ---- the 2026-07-22 incident ----

    def test_same_external_id_at_a_new_url_does_not_raise(self):
        """The exact production failure: same (source_id, external_id), different url."""
        first_id, _ = self.repo.upsert_post(
            self.cur, self._post("https://x.test/original", external_id="XLSWRFPdgPTjLtaj5"), self.source_a
        )

        # Previously raised UniqueViolation on posts_source_external_unique.
        second_id, inserted = self.repo.upsert_post(
            self.cur, self._post("https://x.test/republished", external_id="XLSWRFPdgPTjLtaj5"), self.source_a
        )

        self.assertFalse(inserted, "an item already stored under this external_id is not new")
        self.assertEqual(first_id, second_id, "it must resolve to the existing row, not orphan it")
        self.assertTrue(self._transaction_is_usable())

    def test_collision_leaves_the_batch_usable(self):
        """The property that actually cost the cycle: later posts must still save."""
        self.repo.upsert_post(
            self.cur, self._post("https://x.test/a", external_id="dupe"), self.source_a
        )
        self.repo.upsert_post(
            self.cur, self._post("https://x.test/b", external_id="dupe"), self.source_a
        )

        # In the incident this statement never ran - the transaction was already aborted.
        post_id, inserted = self.repo.upsert_post(
            self.cur, self._post("https://x.test/unrelated", external_id="fresh"), self.source_a
        )
        self.assertTrue(inserted)
        self.assertTrue(self._transaction_is_usable())

    def test_same_external_id_across_different_sources_is_not_a_collision(self):
        """The index is (source_id, external_id) - two sources may share an external_id."""
        a_id, _ = self.repo.upsert_post(
            self.cur, self._post("https://x.test/from-a", external_id="shared"), self.source_a
        )
        b_id, inserted = self.repo.upsert_post(
            self.cur, self._post("https://x.test/from-b", external_id="shared"), self.source_b
        )

        self.assertTrue(inserted)
        self.assertNotEqual(a_id, b_id, "different sources must keep separate rows")

    # ---- the two-row case ----

    def test_url_and_external_id_matching_two_different_rows(self):
        """url matches row A, (source_id, external_id) matches row B. Must converge."""
        row_a, _ = self.repo.upsert_post(
            self.cur, self._post("https://x.test/A", external_id="EA"), self.source_a
        )
        row_b, _ = self.repo.upsert_post(
            self.cur, self._post("https://x.test/B", external_id="EB"), self.source_a
        )
        self.assertNotEqual(row_a, row_b)

        # Hits A by url; setting external_id=EB would violate (source_a, EB) held by B.
        resolved_id, _ = self.repo.upsert_post(
            self.cur, self._post("https://x.test/A", external_id="EB"), self.source_a
        )

        self.assertIn(resolved_id, {row_a, row_b}, "must resolve to one of the two, not a third row")
        self.assertTrue(self._transaction_is_usable())

    def test_conflicting_row_belongs_to_a_different_source(self):
        """The url row may belong to another source than the incoming post.

        The collision is then on (that row's source, external_id) - not on the incoming
        source_id - so a resolver scoped to the incoming source cannot see the blocking
        row and will retry the identical failing UPDATE.
        """
        self.repo.upsert_post(
            self.cur, self._post("https://x.test/owned-by-a", external_id="E1"), self.source_a
        )
        self.repo.upsert_post(
            self.cur, self._post("https://x.test/blocker", external_id="E9"), self.source_a
        )

        # source_b posts at a url already owned by source_a, carrying source_a's E9.
        resolved_id, _ = self.repo.upsert_post(
            self.cur, self._post("https://x.test/owned-by-a", external_id="E9"), self.source_b
        )

        self.assertIsNotNone(resolved_id)
        self.assertTrue(self._transaction_is_usable())

    # ---- regressions ----

    def test_post_with_no_text_does_not_raise(self):
        """_build_content_hash calls hashlib.sha256; the module did not import hashlib.

        Reached whenever title, content and content_html are all empty - image-only
        Telegram/Reddit/Nitter items - and the resulting NameError discarded the same
        full batch as the duplicate-key crash.
        """
        post_id, inserted = self.repo.upsert_post(
            self.cur,
            self._post("https://x.test/image-only", title="", content="", content_html=""),
            self.source_a,
        )
        self.assertTrue(inserted)
        self.assertIsNotNone(post_id)

    def test_update_does_not_blank_existing_values_with_nulls(self):
        """COALESCE semantics: an incoming NULL must not erase a stored value."""
        self.repo.upsert_post(
            self.cur,
            self._post("https://x.test/keep", title="Original title", content="Original body"),
            self.source_a,
        )
        self.repo.upsert_post(
            self.cur,
            self._post("https://x.test/keep", title=None, content=None),
            self.source_a,
        )

        self.cur.execute("SELECT title, content FROM posts WHERE url = %s", ("https://x.test/keep",))
        title, content = self.cur.fetchone()
        self.assertEqual(title, "Original title")
        self.assertEqual(content, "Original body")

    def test_a_re_fetch_keeps_when_the_post_was_first_seen(self):
        """An undated post sorts by fetched_at; a re-fetch must not make it look new again."""
        self.repo.upsert_post(self.cur, self._post("https://x.test/undated"), self.source_a)
        self.cur.execute("UPDATE posts SET fetched_at = now() - interval '40 days' WHERE url = %s",
                         ("https://x.test/undated",))

        self.repo.upsert_post(self.cur, self._post("https://x.test/undated",
                                                   title="Renamed"), self.source_a)

        self.cur.execute("SELECT title, fetched_at < now() - interval '39 days' FROM posts WHERE url = %s",
                         ("https://x.test/undated",))
        title, still_old = self.cur.fetchone()
        self.assertEqual(title, "Renamed")
        self.assertTrue(still_old)


if __name__ == "__main__":
    unittest.main()
