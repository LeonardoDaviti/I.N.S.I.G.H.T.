"""Stealth v10.13.1, search for a name and its version (the owner's case of 2026-11-10, a model name and its version):

1. A name word followed by a version number in a query ("zorblax 5.2") matches only where the two stand together, one
   or two words apart, in the post's own vector (Russian and English posts) and in Mark X's English layer; a post
   with the name and another model's 5.2 apart does not match. "zorblax" alone and "5.2" alone match as before.
2. Entity first: with Mark X on, best match ranks the posts whose current mentions hold the query's entity (the
   version's, with a version) as subject or actor above the posts that only match its words; best match within each;
   off, or newest first, as before.
3. Entity cards: the version's entity before the family's; a card needs 2+ posts or a subject or actor role.

Rows are committed, so the classes run only against a `_test` database. Every name, post and source is synthetic."""
from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_search import SearchQuery
from insight_core.markx import names
from insight_core.markx import search as mx_search
from insight_core.services.reader_service import ReaderService
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests.test_markx_api import _Api, reading


def _matches(cur, text: str, q: str) -> bool:
    cur.execute("SELECT search_vector_with_parts(to_tsvector('russian', normalize(%s, NFKC))) @@ search_query(%s)",
                (text, q))
    return cur.fetchone()[0]


def _matches_en(cur, text: str, q: str) -> bool:
    cur.execute("SELECT to_tsvector('english', %s) @@ search_pair_versions(websearch_to_tsquery('english', %s))", (text, q))
    return cur.fetchone()[0]


@requires_test_db
class NameAndVersionInSql(unittest.TestCase):
    """The rule itself (migration 0095), on the vectors the index and Mark X's layer write."""

    def setUp(self):
        self.conn = psycopg.connect(db_url(), autocommit=True)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()

    def test_the_query_pairs_a_name_and_its_version(self):
        for q, want in (
                ("zorblax 5.2", "'zorblax' <-> '5.2' | 'zorblax' <2> '5.2'"),
                ("gpt 4o", "'gpt' <-> '4o' | 'gpt' <2> '4o'"),
                ("acme zorblax 5.2 release", "'acm' & ( 'zorblax' <-> '5.2' | 'zorblax' <2> '5.2' ) & 'releas'"),
                ("модель 5.2", "'модел' <-> '5.2' | 'модел' <2> '5.2'"),
                ("zorblax 5", "'zorblax' & '5'"),                 # a plain integer is no version
                ("zorblax", "'zorblax'"), ("5.2", "'5.2'"),       # alone, as before
                ("5.1 5.2", "'5.1' & '5.2'"),
                ("zorblax -5.2", "'zorblax' & !'5.2'"), ("-zorblax 5.2", "!'zorblax' & '5.2'"),
                ("zorblax or 5.2", "'zorblax' | '5.2'"),
                ('"zorblax 5.2"', "'zorblax' <-> '5.2'"),         # a phrase already
                ("kimi k3.1", "'kimi' & ( 'k3.1' | 'k' <-> '3.1' )"),   # a version word holds its name: not paired
                ("gpt-6.1", "'gpt' <-> ( '-6.1' | '6.1' )")):
            with self.subTest(q=q):
                self.cur.execute("SELECT search_query(%s)::text", (q,))
                self.assertEqual(self.cur.fetchone()[0], want)

    def test_the_posts_own_words_russian_and_english(self):
        for text, want in (
                ("Acme выпустила Zorblax 5.2: быстрее и дешевле", True),
                ("Вышел Zorblax версии 5.2", True),                     # two words apart
                ("Acme released Zorblax v5.2 today", True),              # a version word read by its parts
                ("Acme Zorblax 5.2 is out", True),
                ("Kimi K3 против Quillon 5.2, а Zorblax 5 всё ещё лучше", False),   # another model's 5.2
                ("Quillon-5.2 benchmark: not as bad as Zorblax on format", False),
                ("This month: Zorblax 5, Quillon-5.6 and Quillon-5.2", False),
                ("Zorblax is good; its 5.2 score is not", False)):    # three words apart
            with self.subTest(text=text):
                self.assertEqual(_matches(self.cur, text, "zorblax 5.2"), want)
                self.assertTrue(_matches(self.cur, text, "zorblax"))     # alone: as before
        self.assertTrue(_matches(self.cur, "Quillon-5.2 benchmark", "5.2"))
        self.assertTrue(_matches(self.cur, "Qwen3.8-Max released", "qwen 3.8"))
        self.assertTrue(_matches(self.cur, "GPT-6.1 lands", "gpt 6.1"))
        self.assertFalse(_matches(self.cur, "GPT-6 and Quillon 6.1", "gpt 6.1"))

    def test_mark_x_english_layer(self):
        self.assertTrue(_matches_en(self.cur, "Acme released Zorblax 5.2 for robots", "zorblax 5.2"))
        self.assertFalse(_matches_en(self.cur, "Quillon 5.2 beats Zorblax 5 on tests", "zorblax 5.2"))
        self.assertTrue(_matches_en(self.cur, "Quillon 5.2 beats Zorblax 5 on tests", "zorblax"))


# A Russian post the English words cannot meet; Mark X read it in English.
def _ru_reading(headline: str):
    return reading(lang="ru", main={"headline_en": headline, "actors": ["Acme"], "object": "a model", "action": "released"})


class NameAndVersionInSearch(_Api):
    def setUp(self):
        super().setUp()
        self.cur.execute("TRUNCATE mx_post_search")
        self.reader = ReaderService(db_url())
        self.now = datetime.now(timezone.utc)

    def ids(self, q: str, **query):
        return [i["id"] for i in self.reader.search(SearchQuery.parse(q=q, **query))["items"]]

    def read(self, pid: str, headline: str) -> None:
        t = self.task(post=pid)
        self.lease()
        self.assertEqual(self.answer((t, _ru_reading(headline)))[1]["valid"], 1)

    def mentions(self, pid: str, ents) -> None:
        t = self.task("entities", post=pid)
        self.lease("entities")
        self.assertEqual(self.answer((t, {"entities": ents, "relations": []}))[1]["valid"], 1)

    def entity(self, name: str, *, level: str = "thing", version: str | None = None, type_: str = "model") -> str:
        self.cur.execute("INSERT INTO mx_entities (type, name, key, level, version) VALUES (%s, %s, %s, %s, %s)"
                         " RETURNING id::text", (type_, name, names.key(name), level, version))
        return self.cur.fetchone()[0]

    def link(self, pid: str, name: str, entity_id: str) -> None:
        self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND name = %s", (entity_id, pid, name))
        self.assertEqual(self.cur.rowcount, 1)

    def at(self, hours: float):
        return self.now - timedelta(hours=hours)

    # ---- 1. the pair -------------------------------------------------------------------------------------------

    def test_own_words_the_name_and_its_version_stand_together(self):
        ru = self.post("Acme выпустила Zorblax 5.2", "Новая версия модели: быстрее и дешевле.", at=self.at(1))
        en = self.post("Acme ships Zorblax 5.2", "Faster and cheaper than before.", at=self.at(2))
        apart = self.post("Kimi K3 против Quillon 5.2", "А Zorblax 5 всё ещё лучше на фронтенде.", at=self.at(3))
        bench = self.post("Quillon-5.2 benchmark", "It lost less on format than Zorblax did.", at=self.at(4))
        for markx in ("on", "off"):
            os.environ["INSIGHT_MARKX"] = markx
            for order in ("best", "newest"):
                with self.subTest(markx=markx, order=order):
                    got = self.ids("zorblax 5.2", order=order)
                    self.assertEqual(got if order == "newest" else sorted(got), [ru, en] if order == "newest" else sorted([ru, en]))
                    self.assertEqual(sorted(self.ids("zorblax", order=order)), sorted([ru, en, apart, bench]))
                    self.assertEqual(sorted(self.ids("5.2", order=order)), sorted([ru, en, apart, bench]))

    def test_mark_xs_english_layer_and_the_split_keep_the_pair(self):
        found = self.post("Новость дня", "Компания выпустила модель, она быстрее прежней.")
        self.read(found, "Acme released Zorblax 5.2, a faster model.")
        other = self.post("Сравнение моделей", "Другая модель обошла прежнюю в тестах.")
        self.read(other, "Quillon 5.2 beats Zorblax 5 on tests.")
        split = self.post("Новый Zorblax", "Модель стала быстрее.")     # the name in its own words, 5.2 only in Mark X's
        self.read(split, "Acme updated a model to version 5.2.")
        for order in ("best", "newest"):
            with self.subTest(order=order):
                self.assertEqual(self.ids("zorblax 5.2", order=order), [found])
        self.assertEqual(sorted(self.ids("zorblax", order="newest")), sorted([found, other, split]))

    # ---- 2. entity first ----------------------------------------------------------------------------------------

    def test_posts_with_the_versions_entity_as_subject_or_actor_rank_first(self):
        filler = " ".join(["Длинный текст о других делах и новостях недели."] * 30)
        about = self.post("Обзор недели", f"{filler} Acme выпустила Zorblax 5.2 сегодня.", at=self.at(3))
        actor = self.post("Обзор вторника", f"{filler} Zorblax 5.2 решил задачу сам.", at=self.at(4))
        joke = self.post("Zorblax 5.2 Ultra шутка", "Zorblax 5.2 Ultra Max, Zorblax 5.2 и снова Zorblax 5.2.", at=self.at(1))
        words = self.post("Zorblax 5.2 Zorblax 5.2", "Zorblax 5.2 упомянут здесь три раза: Zorblax 5.2.", at=self.at(2))
        self.mentions(about, [{"span": "Zorblax 5.2", "name": "Acme Zorblax 5.2", "type": "model", "role": "subject"}])
        self.mentions(actor, [{"span": "Zorblax 5.2", "name": "Acme Zorblax 5.2", "type": "model", "role": "actor"}])
        self.mentions(joke, [{"span": "Zorblax 5.2 Ultra Max", "name": "Zorblax 5.2 Ultra Max", "type": "model",
                              "role": "compared"}])
        version = self.entity("Acme Zorblax 5.2", level="version", version="5.2")
        variant = self.entity("Zorblax 5.2 Ultra Max", level="variant", version="5.2")
        self.link(about, "Acme Zorblax 5.2", version)
        self.link(actor, "Acme Zorblax 5.2", version)
        self.link(joke, "Zorblax 5.2 Ultra Max", variant)
        self.cur.execute("TRUNCATE mx_post_search")   # the words alone rank, on or off: only the entity moves a post

        os.environ["INSIGHT_MARKX"] = "off"
        by_words = self.ids("zorblax 5.2", order="best")
        self.assertEqual(set(by_words[:2]), {joke, words})              # words alone rank them first
        os.environ["INSIGHT_MARKX"] = "on"
        self.assertEqual(sorted(mx_search.entity_first_posts(self.cur, "zorblax 5.2")), sorted([about, actor]))
        got = self.ids("zorblax 5.2", order="best")
        self.assertEqual(set(got[:2]), {about, actor})                  # the entity's posts first
        self.assertEqual(got[2:], [p for p in by_words if p in (joke, words)])   # then best match as before
        self.assertEqual(got[:2], [p for p in by_words if p in (about, actor)])  # best match within the group
        self.assertEqual(self.ids("zorblax 5.2", order="newest"), [joke, words, about, actor])   # newest: as before
        self.assertEqual(mx_search.entity_first_posts(self.cur, "zorblax -5.2"), [])
        self.assertEqual(mx_search.entity_first_posts(self.cur, "quillon 5.2"), [])

    def test_a_story_with_such_a_post_counts_at_its_shown_post(self):
        filler = " ".join(["Длинный текст о других делах и новостях недели."] * 30)
        about = self.post("Обзор недели", f"{filler} Acme выпустила Zorblax 5.2 сегодня.", at=self.at(3))
        shown = self.post("Zorblax 5.2 Zorblax 5.2", "Zorblax 5.2 вышел: Zorblax 5.2.", at=self.at(2), source=self.other)
        alone = self.post("Zorblax 5.2", "Zorblax 5.2 вышел, Zorblax 5.2 лучше.", at=self.at(1))
        self.mentions(about, [{"span": "Zorblax 5.2", "name": "Acme Zorblax 5.2", "type": "model", "role": "subject"}])
        self.link(about, "Acme Zorblax 5.2", self.entity("Acme Zorblax 5.2", level="version", version="5.2"))
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, 2)", (shown, self.at(3)))
        self.cur.executemany("INSERT INTO story_posts (post_id, story_id, role, voice) VALUES (%s, %s, 'report', %s)",
                             [(about, shown, about), (shown, shown, shown)])
        self.cur.execute("TRUNCATE mx_post_search")
        got = self.ids("zorblax 5.2", order="best")
        self.assertEqual(got[0], shown)          # the story, shown at its best-matching post, ranks first
        self.assertIn(alone, got)
        self.assertNotIn(about, got)

    # ---- 3. cards ------------------------------------------------------------------------------------------------

    def test_cards_prefer_the_version_and_need_two_posts_or_a_lead_role(self):
        a = self.post("Acme выпустила Zorblax 5.2", "Zorblax 5.2 вышел.")
        b = self.post("Zorblax против всех", "Zorblax снова сравнили.")
        c = self.post("Шутка", "Если у них не завалялся Zorblax 5.2 Ultra Max.")
        self.mentions(a, [{"span": "Zorblax 5.2", "name": "Acme Zorblax 5.2", "type": "model", "role": "subject"}])
        self.mentions(b, [{"span": "Zorblax", "name": "Zorblax", "type": "model", "role": "mention"}])
        self.mentions(c, [{"span": "Zorblax 5.2 Ultra Max", "name": "Zorblax 5.2 Ultra Max", "type": "model",
                           "role": "compared"},
                          {"span": "Zorblax", "name": "Zorblax", "type": "model", "role": "mention"}])
        family = self.entity("Zorblax")
        version = self.entity("Acme Zorblax 5.2", level="version", version="5.2")
        variant = self.entity("Zorblax 5.2 Ultra Max", level="variant", version="5.2")
        lonely = self.entity("Zorblax Lonely")   # no post at all
        self.link(a, "Acme Zorblax 5.2", version)
        self.link(b, "Zorblax", family)
        self.link(c, "Zorblax", family)
        self.link(c, "Zorblax 5.2 Ultra Max", variant)

        cards = self.reader.search(SearchQuery.parse(q="zorblax 5.2"))["entities"]
        self.assertEqual([(x["id"], x["posts"]) for x in cards], [(version, 1), (family, 2)])   # the version first
        self.assertEqual([x["id"] for x in self.reader.search(SearchQuery.parse(q="Zorblax5.2"))["entities"]][:1],
                         [version])
        ids = [x["id"] for x in self.reader.search(SearchQuery.parse(q="zorblax"))["entities"]]
        self.assertEqual(ids, [family])          # the variant: one post, compared; the lonely one: none
        self.assertNotIn(variant, ids)
        self.assertNotIn(lonely, ids)


if __name__ == "__main__":
    unittest.main()
