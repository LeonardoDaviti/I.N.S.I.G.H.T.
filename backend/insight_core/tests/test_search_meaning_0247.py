"""Search by meaning (0247): in best order the posts nearest the query's vector join the word matches, merged by
reciprocal rank; a post only meaning found is marked "meaning"; a short post is never a meaning match; with the
switch off or no embedder, search is the word search alone. The query's vector is stubbed. Rows are committed, so only
against a `_test` database; everything is synthetic."""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_search import SearchQuery, SearchRepository
from insight_core.markx import search as mx_search
from insight_core.markx.repo import vector_text
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db


def _unit(i: int) -> list:
    v = [0.0] * 1024
    v[i] = 1.0
    return v


def _near(i: int, j: int, w: float) -> list:   # mostly axis i, a little of j: cosine to axis i = 1/sqrt(1+w^2)
    v = [0.0] * 1024
    v[i], v[j] = 1.0, w
    n = (1 + w * w) ** 0.5
    return [x / n for x in v]


class QueryVector(unittest.TestCase):
    def test_no_embedder_no_vector(self):
        self.assertIsNone(mx_search.query_vector("anything", url=""))

    def test_an_unreachable_embedder_is_no_vector(self):
        self.assertIsNone(mx_search.query_vector("anything", url="http://127.0.0.1:9", timeout=0.5))

    def test_off_without_a_url(self):
        with mock.patch.dict("os.environ", {"INSIGHT_EMBEDDER_URL": ""}):
            self.assertFalse(mx_search.meaning_on())


@requires_test_db
class MeaningMerge(unittest.TestCase):
    def setUp(self):
        self.addCleanup(self._clean)
        self._clean()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.marker = "qz" + uuid.uuid4().hex[:10]
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.source = insert_scratch_source(cur, settings_json='{"display_name": "Scratch Source"}', in_main_digest=False)
            cur.execute("DELETE FROM mx_embeddings")
            body = " ".join(["filler text about nothing in particular"] * 10)
            self.word = self._post(cur, f"Gliders {self.marker} report", body, 1, _near(5, 6, 3.0))     # cosine 0.32
            self.meaning = self._post(cur, "A plane that flies itself for hours", body, 2, _near(5, 7, 0.3))  # 0.96
            self.short = self._post(cur, "Too real", "", 3, _unit(5))                                    # 1.0, short
            self.far = self._post(cur, "Cake recipes", body, 4, _unit(9))                                # 0

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM mx_embeddings")
            delete_scratch_sources(cur)

    def _post(self, cur, title, content, hours_ago, vector) -> str:
        cur.execute("INSERT INTO posts (source_id, url, published_at, title, content) VALUES (%s, %s, %s, %s, %s)"
                    " RETURNING id", (self.source, f"https://test.invalid/0247/{uuid.uuid4().hex}",
                                      self.now - timedelta(hours=hours_ago), title, content))
        pid = str(cur.fetchone()[0])
        cur.execute("INSERT INTO mx_embeddings (post_id, model, text_hash, v) VALUES (%s, 'bge-m3', 'h', %s::halfvec)",
                    (pid, vector_text(vector)))
        return pid

    def _search(self, *, on: bool, order: str = "best"):
        q = f"{self.marker} gliders"
        with mock.patch.object(mx_search, "meaning_on", return_value=on), \
                mock.patch.object(mx_search, "query_vector", return_value=_unit(5)), \
                psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            repo = SearchRepository()
            cur.execute("UPDATE posts SET search_vector = NULL WHERE source_id = %s", (self.source,))
            repo.fill_missing_vectors(cur)
            items, _ = repo.search(cur, SearchQuery.parse(q=q, order=order), now=self.now, markx=True)
            return items

    def test_off_is_the_word_search(self):
        items = self._search(on=False)
        self.assertEqual([i["id"] for i in items], [self.word])
        self.assertNotIn("matched", items[0])

    def test_on_adds_the_nearest_long_posts_marked(self):
        items = self._search(on=True)
        ids = [i["id"] for i in items]
        self.assertIn(self.word, ids)
        self.assertIn(self.meaning, ids)
        self.assertNotIn(self.short, ids)   # a short text's vector is near everything
        self.assertNotIn(self.far, ids)     # below MEANING_MIN
        found = next(i for i in items if i["id"] == self.meaning)
        self.assertEqual((found["matched"], found["snippet_from"]), ("meaning", "meaning"))
        self.assertTrue(found["snippet"])
        self.assertNotIn("matched", next(i for i in items if i["id"] == self.word))

    def test_newest_order_reads_no_meaning(self):
        self.assertEqual([i["id"] for i in self._search(on=True, order="newest")], [self.word])


if __name__ == "__main__":
    unittest.main()
