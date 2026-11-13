"""Stealth v10.13.13, search for a name and its version, the version spelled any way (a model's "K3.1" asked as "3.1"):

1. Rank: a name and its version pair to match (0095) but rank by the query's words unpaired, as before v10.13.1:
   ts_rank reads a lone pair ('x' <-> '3.1' | 'x' <2> '3.1') word by word, so a post repeating the name outranked one
   naming the version once, side by side.
2. Titled: in best order a title naming the name and its version together as the index reads them ("Zentra Z3.1
   Pro", "Zentra3.1") holds the query, as a title holding it word for word does (v10.13.6); a query with no version
   keeps v10.13.6's rule.
3. Entity first and cards (Mark X on): the query's version of the family its name names, however its entities are
   spelled ("Zentra Z3.1", its variant "Zentra Z3.1 Pro", an unmerged "Zentra3.1", a loose "Zentra Z3.1 Flash"): all
   their posts as subject or actor rank first, and the card with the most posts leads, so one spelling never crowds
   out the others.

Rows are committed, so the classes run only against a `_test` database. Every name, post and source is synthetic."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_search import SearchQuery
from insight_core.markx import names
from insight_core.markx import search as mx_search
from insight_core.services.reader_service import ReaderService
from insight_core.tests._db import clear_tables, db_url
from insight_core.tests.test_markx_api import _Api

FILLER = " ".join(["Длинный текст о других делах и новостях недели."] * 30)


class _Search(_Api):
    def setUp(self):
        super().setUp()
        clear_tables(self.cur, "mx_post_search")
        self.reader = ReaderService(db_url())
        self.now = datetime.now(timezone.utc)

    def ids(self, q: str, **query):
        return [i["id"] for i in self.reader.search(SearchQuery.parse(q=q, **query))["items"]]

    def at(self, hours: float):
        return self.now - timedelta(hours=hours)


class RankAndTitle(_Search):
    def setUp(self):
        super().setUp()
        os.environ["INSIGHT_MARKX"] = "off"

    def test_the_pair_matches_and_the_words_rank(self):
        notes = self.post("Zentra Z3.1 Pro tech notes", "Same design as Z3, larger and open.", at=self.at(2))
        live = self.post("Zentra Z3.1 Pro is live in Zentra Chat and Zentra Code!",
                         "Zentra Z3.1 Pro is live in Zentra Chat and Zentra Code! Happy Zentra day!", at=self.at(1))
        apart = self.post("Zentra is good", "Its 3.1 score on the board is not, they say.", at=self.at(3))
        self.assertEqual(self.ids("zentra 3.1", order="best"), [notes, live])   # was [live, notes]
        self.assertNotIn(apart, self.ids("zentra 3.1", order="newest"))
        self.cur.execute("SELECT id::text FROM posts WHERE id = ANY(%s::uuid[])"
                         " ORDER BY ts_rank(search_vector, search_query_words('zentra 3.1'), 1) DESC",
                         ([notes, live],))
        self.assertEqual([r[0] for r in self.cur.fetchall()], [notes, live])

    def test_a_title_naming_the_version_holds_the_query(self):
        digest = self.post("Weekly digest", "Vexlo 3.1 is out.", at=self.at(1))   # no title holds it
        phrase = self.post("Vexlo 3.1 and the others: a long benchmark review of the month", FILLER, at=self.at(2))
        word = self.post("Vexlo V3.1 Pro", "Vexlo V3.1 Pro is out.", at=self.at(3))   # the best rank
        squashed = self.post("Vexlo3.1 on the arena", f"{FILLER} Vexlo3.1.", at=self.at(4))
        got = self.ids("vexlo 3.1", order="best")
        self.assertEqual(got[0], word)          # a title as much as the word-for-word one: best match among them
        self.assertEqual(set(got[:3]), {phrase, word, squashed})
        self.assertEqual(got[3:], [digest])
        self.assertEqual(self.ids("vexlo 3.1", order="newest"), [digest, phrase, word, squashed])   # newest: as before

    def test_a_query_with_no_version_keeps_the_phrase_rule(self):
        # the words in its title, not the phrase; short, so the better rank: a title holding the words only is no title
        words = self.post("Arena: Morvane wins again", "Morvane.", at=self.at(1))
        phrase = self.post("The Morvane arena guide", FILLER, at=self.at(2))
        self.assertEqual(self.ids("morvane arena", order="best"), [phrase, words])


class FamilyVersionFirst(_Search):
    def mentions(self, pid: str, ents) -> None:
        t = self.task("entities", post=pid)
        self.lease("entities")
        self.assertEqual(self.answer((t, {"entities": ents, "relations": []}))[1]["valid"], 1)

    def entity(self, name: str, *, level: str = "version", version: str | None = None, parent: str | None = None,
               variant: str | None = None) -> str:
        self.cur.execute("INSERT INTO mx_entities (type, name, key, level, version, variant, parent)"
                         " VALUES ('model', %s, %s, %s, %s, %s, %s) RETURNING id::text",
                         (name, names.key(name), level, version, variant, parent))
        return self.cur.fetchone()[0]

    def about(self, title: str, text: str, name: str, entity_id: str | None, *, role: str = "subject",
              hours: float = 1) -> str:
        pid = self.post(title, text, at=self.at(hours))
        self.mentions(pid, [{"span": name, "name": name, "type": "model", "role": role}])
        if entity_id:
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND name = %s",
                             (entity_id, pid, name))
            self.assertEqual(self.cur.rowcount, 1)
        return pid

    def setUp(self):
        super().setUp()
        family = self.entity("Zentra", level="family")
        self.version = self.entity("Zentra Z3.1", version="Z3.1", parent=family)
        self.pro = self.entity("Zentra Z3.1 Pro", level="variant", version="Z3.1", variant="Pro", parent=self.version)
        self.dup = self.entity("Zentra3.1", version="3.1", parent=family)          # the same version, unmerged
        self.next = self.entity("Zentra Z3.2", version="Z3.2", parent=family)
        self.flash = self.entity("Zentra Z3.1 Flash", level="variant", version="Z3.1", variant="Flash")   # no family
        other = self.entity("Quillon", level="family")
        self.quillon = self.entity("Quillon 3.1", version="3.1", parent=other)
        self.pros = [self.about(f"Обзор {n}", f"{FILLER} Zentra Z3.1 Pro ({n}).", "Zentra Z3.1 Pro", self.pro,
                                hours=n + 2) for n in range(3)]
        self.dup_post = self.about("Обзор арены", f"{FILLER} Zentra3.1.", "Zentra3.1", self.dup, hours=6)
        self.version_post = self.about("Обзор дня", f"{FILLER} Zentra Z3.1.", "Zentra Z3.1", self.version,
                                       role="actor", hours=7)
        self.flash_post = self.about("Обзор вечера", f"{FILLER} Zentra Z3.1 Flash.", "Zentra Z3.1 Flash", self.flash,
                                     hours=8)
        self.loose = self.about("Обзор ночи", f"{FILLER} Zentra Z3.1 Max.", "Zentra Z3.1 Max", None, hours=9)
        self.compared = self.about("Сравнение", f"{FILLER} Zentra Z3.1 Pro.", "Zentra Z3.1 Pro", self.pro,
                                   role="compared", hours=10)
        self.next_post = self.about("Обзор Z3.2", f"{FILLER} Zentra Z3.2, not 3.1.", "Zentra Z3.2", self.next, hours=11)
        self.other_post = self.about("Обзор Quillon", f"{FILLER} Quillon 3.1.", "Quillon 3.1", self.quillon, hours=12)
        clear_tables(self.cur, "mx_post_search")   # the words alone rank: only the entity moves a post

    def test_every_spelling_of_the_version_is_first(self):
        want = {*self.pros, self.dup_post, self.version_post, self.flash_post, self.loose}
        self.assertEqual(set(mx_search.entity_first_posts(self.cur, "zentra 3.1")), want)
        self.assertEqual(set(mx_search.entity_first_posts(self.cur, "Zentra3.1")), want)
        self.assertEqual(set(mx_search.entity_first_posts(self.cur, "zentra 3.2")), {self.next_post})
        self.assertEqual(mx_search.entity_first_posts(self.cur, "quillon 3.1"), [self.other_post])
        self.assertEqual(mx_search.entity_first_posts(self.cur, "zentra 3.11"), [])

    def test_the_entitys_posts_rank_before_the_words(self):
        dense = self.post("Weekly digest", "Zentra 3.1 is out.", at=self.at(1))   # the best rank by words
        got = self.ids("zentra 3.1", order="best")
        first = {*self.pros, self.dup_post, self.version_post, self.flash_post, self.loose}
        self.assertEqual(set(got[:len(first)]), first)
        self.assertEqual(got[len(first)], dense)
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertEqual(self.ids("zentra 3.1", order="best")[0], dense)

    def test_the_card_with_the_most_posts_leads(self):
        cards = self.reader.search(SearchQuery.parse(q="zentra 3.1"))["entities"]
        self.assertEqual(cards[0]["id"], self.pro)
        self.assertEqual(cards[0]["posts"], 4)
        self.assertNotIn(self.next, [c["id"] for c in cards])


if __name__ == "__main__":
    unittest.main()
