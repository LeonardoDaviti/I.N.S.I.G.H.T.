"""Issue 0139, search that finds: History searched (only opened posts, last open first, paged on it, never folded),
Mark X's English layer (mx_post_search: written by the worker's answer, matched in English for a Russian post, read
only while Mark X is on, its headline as the line marked "Mark X", the fill resumable and versioned), the entity
cards (a name, an alias, a prefix, through a redirect, never a not-entity, off when Mark X is off), and best match
for 2+ words unless an order is asked.

Rows are committed, so the classes run only against a `_test` database. Every post and source is synthetic."""
from __future__ import annotations

import json
import os
import random
import string
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

import main
from insight_core.db.repo_search import SearchQuery, default_order, snippet_parts
from insight_core.markx import search as mx_search
from insight_core.services import registry
from insight_core.services.reader_service import ReaderService
from insight_core.tests._asgi import call as asgi_call
from insight_core.tests._db import clear_tables, db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import _Api, reading


class DefaultOrder(unittest.TestCase):
    def test_two_words_or_more_order_by_best_match_one_word_by_newest(self):
        for q, order in (("robots", "newest"), ("3D library tokens", "best"), ('"servers fell"', "best"),
                         ("robots -phone", "newest"), ("robots or androids", "best"), ("robots ,", "newest")):
            with self.subTest(q=q):
                self.assertEqual(default_order(q), order)
                self.assertEqual(SearchQuery.parse(q=q).order, order)

    def test_an_asked_order_wins(self):
        self.assertEqual(SearchQuery.parse(q="3D library tokens", order="newest").order, "newest")
        self.assertEqual(SearchQuery.parse(q="robots", order="best").order, "best")

    def test_history_is_a_search_filter_that_never_folds(self):
        self.assertIsNone(SearchQuery.parse(q="x", filter="history").folds)
        self.assertIsNone(SearchQuery.parse(q="x", scope="all", filter="history").folds)

    def test_plain_parts_keep_an_unmarked_line(self):
        self.assertIsNone(snippet_parts("Acme released a library"))
        self.assertEqual(snippet_parts("Acme released a library", plain=True), [{"text": "Acme released a library", "mark": False}])


@requires_test_db
class HistorySearch(unittest.TestCase):
    def setUp(self):
        self.env = os.environ.pop("INSIGHT_MARKX", None)
        self.addCleanup(lambda: self.env is not None and os.environ.__setitem__("INSIGHT_MARKX", self.env))
        previous = registry.use(registry.build_services(db_url()))
        self.addCleanup(registry.use, previous)
        self.addCleanup(self._clean)
        self._clean()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.marker = "qz" + "".join(random.choices(string.ascii_lowercase, k=10))
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.source = insert_scratch_source(cur, settings_json='{"display_name": "Scratch Source"}', in_main_digest=False)

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)

    def _post(self, title: str, *, hours_ago: float, url: str | None = None) -> str:
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO posts (source_id, url, published_at, title, content) VALUES (%s, %s, %s, %s, '')"
                        " RETURNING id",
                        (self.source, url or f"https://test.invalid/mark-ix/post/{uuid.uuid4().hex}",
                         self.now - timedelta(hours=hours_ago), f"{title} {self.marker}"))
            return str(cur.fetchone()[0])

    def _open(self, post_id: str, *, hours_ago: float, kind: str = "opened") -> None:
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO post_interactions (post_id, interaction_type, created_at) VALUES (%s, %s, %s)",
                        (post_id, kind, self.now - timedelta(hours=hours_ago)))

    def search(self, **query):
        status, _, body = asgi_call(main.app, "GET", "/api/search", query={"q": self.marker, **query})
        self.assertEqual(status, 200, body)
        return body

    def test_only_the_opened_posts_last_open_first_paged_on_it(self):
        old_post = self._post("Robots", hours_ago=50)        # posted first, opened last
        new_post = self._post("Robots", hours_ago=2)
        read_post = self._post("Robots", hours_ago=10)
        self._post("Robots", hours_ago=1)                    # never opened: not in History
        self._open(old_post, hours_ago=1)
        self._open(old_post, hours_ago=30)
        self._open(new_post, hours_ago=1.5)
        self._open(read_post, hours_ago=5, kind="reading_session")

        body = self.search(filter="history")
        self.assertEqual([i["id"] for i in body["items"]], [old_post, new_post, read_post])
        first = body["items"][0]
        self.assertEqual(first["opened_at"], first["sort_at"])
        self.assertEqual(body["entities"], [])

        seen, cursor = [], None
        while True:
            page = self.search(filter="history", limit=1, **({"cursor": cursor} if cursor else {}))
            seen += [i["id"] for i in page["items"]]
            cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(seen, [old_post, new_post, read_post])

    def test_days_bound_the_open_and_a_story_does_not_fold(self):
        a = self._post("Robots", hours_ago=24 * 20)
        b = self._post("Robots", hours_ago=24 * 20)
        self._open(a, hours_ago=2)
        self._open(b, hours_ago=3)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:   # one story of the two
            cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, now(), 2)", (a,))
            cur.executemany("INSERT INTO story_posts (post_id, story_id, role, voice) VALUES (%s, %s, 'report', %s)",
                            [(a, a, a), (b, a, b)])
        self.assertEqual([i["id"] for i in self.search(filter="history", days=7)["items"]], [a, b])
        self.assertEqual([i["id"] for i in self.search(filter="history", days=7, order="best")["items"]], [a, b])


# A Russian post the English words cannot meet; Mark X read it in English.
RU_TITLE = "Трёхмерные модели для дизайнеров"
RU_TEXT = ("Вышла библиотека widget3d на Python от Acme: модели пишут трёхмерные объекты кодом и тратят в 2–6 раз "
           "меньше токенов. Работает с Modeler.")
RU_READING = reading(lang="ru", main={"headline_en": "Acme released widget3d, a Python 3D-modeling library built for "
                                                      "language models.",
                                      "actors": ["Acme"], "object": "widget3d", "action": "released",
                                      "numbers": ["2-6x fewer tokens"]})


class MarkXLayer(_Api):
    def setUp(self):
        super().setUp()
        clear_tables(self.cur, "mx_post_search")
        self.reader = ReaderService(db_url())

    def found(self, q: str, **query):
        return self.reader.search(SearchQuery.parse(q=q, **query))

    def ru_post(self) -> str:
        pid = self.post(title=RU_TITLE, text=f"{RU_TEXT} ({uuid.uuid4().hex[:8]})")   # the same text is one question
        t = self.task(post=pid)
        self.lease()
        self.assertEqual(self.answer((t, RU_READING))[1]["valid"], 1)
        return pid

    def test_the_answer_writes_the_row_and_english_words_find_the_russian_post(self):
        pid = self.ru_post()
        self.cur.execute("SELECT version, headline FROM mx_post_search WHERE post_id = %s", (pid,))
        self.assertEqual(self.cur.fetchone(), (mx_search.VERSION, RU_READING["main"]["headline_en"]))

        body = self.found("3D library tokens")
        self.assertEqual([i["id"] for i in body["items"]], [pid])
        item = body["items"][0]
        self.assertEqual(item["snippet_from"], "markx")
        self.assertEqual("".join(p["text"] for p in item["snippet"]), RU_READING["main"]["headline_en"].rstrip("."))
        self.assertTrue({"library"} <= {p["text"] for p in item["snippet"] if p["mark"]})
        self.assertEqual([i["id"] for i in self.found("3D library tokens", order="newest")["items"]], [pid])

    def test_off_the_layer_is_not_read(self):
        pid = self.ru_post()
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertEqual(self.found("3D library tokens")["items"], [])
        self.assertEqual([i["id"] for i in self.found("widget3d")["items"]], [pid])   # its own words still match

    def test_words_split_between_its_own_text_and_mark_xs_english_match_together(self):
        pid = self.ru_post()
        other = self.ru_post()   # a second answered post holding only one of the words in each layer
        self.cur.execute("UPDATE posts SET title = 'Заметка', content = 'Другая заметка без нужных слов.' WHERE id = %s", (other,))
        self.cur.execute("UPDATE posts SET search_vector = post_search_vector(title, content, '') WHERE id = %s", (other,))
        q = "трёхмерные library"   # the Russian word only in the post's own text, the English one only in Mark X's
        for order in ("newest", "best"):
            with self.subTest(order=order):
                items = self.found(q, order=order)["items"]
                self.assertEqual([i["id"] for i in items], [pid])
                self.assertNotIn("snippet_from", items[0])   # its own line, its own word marked
                self.assertIn("трёхмерные", [p["text"] for p in items[0]["snippet"] if p["mark"]])
        self.assertEqual(self.found('"трёхмерные library"')["items"], [])   # a phrase is never split
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertEqual(self.found(q)["items"], [])

    def test_a_post_its_own_words_match_keeps_its_own_line(self):
        pid = self.ru_post()
        (item,) = self.found("библиотека")["items"]
        self.assertEqual(item["id"], pid)
        self.assertNotIn("snippet_from", item)
        self.assertIn("библиотека", [p["text"] for p in item["snippet"] if p["mark"]])

    def test_the_entities_answer_adds_its_names(self):
        pid = self.post(title=RU_TITLE, text=RU_TEXT)
        t = self.task("entities", post=pid)
        self.lease("entities")
        ents = [{"span": "widget3d", "name": "widget3d", "type": "software", "role": "subject", "maker": "Acme Labs"},
                {"span": "Modeler", "name": "Modeler", "type": "software", "role": "mention"}]
        self.assertEqual(self.answer((t, {"entities": ents, "relations": []}))[1]["valid"], 1)
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertEqual(self.found("acme labs")["items"], [])   # not its own words
        os.environ["INSIGHT_MARKX"] = "on"
        self.assertEqual([i["id"] for i in self.found("acme labs")["items"]], [pid])

    def test_the_fill_is_resumable_and_versioned(self):
        a, b = self.ru_post(), self.ru_post()
        self.cur.execute("DELETE FROM mx_post_search WHERE post_id = %s", (a,))
        self.cur.execute("UPDATE mx_post_search SET version = 0 WHERE post_id = %s", (b,))
        with self.conn.transaction():
            self.assertTrue(mx_search.pending(self.cur))
            self.assertEqual(mx_search.fill_batch(self.cur, batch=1), 1)   # one batch, then the rest
            self.assertTrue(mx_search.pending(self.cur))
        self.assertEqual(self.reader.fill_markx_search(), 1)
        self.assertEqual(self.reader.fill_markx_search(), 0)
        self.cur.execute("SELECT count(*) FROM mx_post_search WHERE post_id = ANY(%s::uuid[]) AND version = %s",
                         ([a, b], mx_search.VERSION))
        self.assertEqual(self.cur.fetchone()[0], 2)
        # a row older than the post's newest answer is made again
        self.cur.execute("UPDATE mx_post_search SET updated_at = now() - interval '1 day' WHERE post_id = %s", (a,))
        self.assertEqual(self.reader.fill_markx_search(), 1)

    # ---- entity cards -------------------------------------------------------------------------------------------

    def entity(self, name: str, *, type_: str = "software", maker: str | None = None, status: str = "provisional") -> str:
        from insight_core.markx import names
        self.cur.execute("INSERT INTO mx_entities (type, name, key, maker, status) VALUES (%s, %s, %s, %s, %s) RETURNING id::text",
                         (type_, name, names.key(name), maker, status))
        return self.cur.fetchone()[0]

    def test_cards_by_name_alias_prefix_and_redirect_and_off(self):
        from insight_core.markx import names
        pid = self.post(title=RU_TITLE, text=RU_TEXT)
        t = self.task("entities", post=pid)
        self.lease("entities")
        ents = [{"span": "widget3d", "name": "widget3d", "type": "software", "role": "subject", "maker": "Acme"}]
        self.answer((t, {"entities": ents, "relations": []}))
        main_id = self.entity("widget3d", maker="Acme")
        old_id = self.entity("Widget Three D")
        self.entity("Widgetry Nonsense", status="not_entity")
        self.cur.execute("INSERT INTO mx_entity_aliases (key, entity_id, source) VALUES (%s, %s, 'rule')", (names.key("w3d"), main_id))
        self.cur.execute("INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic) VALUES (%s, %s, 'owner', false)",
                         (old_id, main_id))
        self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (old_id, pid))   # linked before the merge

        card = {"id": main_id, "name": "widget3d", "type": "software", "maker": "Acme", "posts": 1, "voices": 1}
        for q in ("widget3d", "w3d", "widget three d", "widg", "3D library w3d"):
            with self.subTest(q=q):
                got = self.found(q)["entities"]
                self.assertEqual([{k: c[k] for k in card} for c in got], [card])
        self.assertEqual(self.found("wi")["entities"], [])                              # a prefix needs 3 letters
        self.assertEqual(self.found("widgetry")["entities"], [])                        # never a not-entity
        self.assertEqual(self.found("w3d", scope=f"source:{self.source}")["entities"], [])   # not in one source
        page = self.found("w3d", order="best", cursor="30")
        self.assertEqual(page["entities"], [])                                          # the first page only
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertEqual(self.found("w3d")["entities"], [])


if __name__ == "__main__":
    unittest.main()
