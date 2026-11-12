"""The Happening (issue 0166 step 2): a reading as a key (a table of readings and the key each makes, or none), and
Pairing's `happening` source on a test database: off by default, on it pairs two posts of one happening across
languages and days, never a roundup, never one source with itself.

The DB part runs only on a database whose name ends in _test (it empties the mx_* tables inside its transaction)."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg

from insight_core.markx import candidates as C
from insight_core.markx import happening as HP
from insight_core.markx import pairing, repo, schemas, tasks
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES

ACME = {"name": "Acme", "name_key": "acme", "type": "org", "role": "actor"}
WIDGETCO = {"name": "Widgetco", "name_key": "widgetco", "type": "org", "role": "subject"}
GIZMO = {"name": "Gizmo 4.1", "name_key": "gizmo 4.1", "type": "model", "role": "subject"}
GIZMO2 = {"name": "Gizmo 4.2", "name_key": "gizmo 4.2", "type": "model", "role": "subject"}
JANE = {"name": "Jane Example", "name_key": "jane example", "type": "person", "role": "subject"}
FUND = {"name": "Example Ventures", "name_key": "example ventures", "type": "org", "role": "actor"}


def reading(action, actors, obj, *, numbers=(), day=None, kind="report", headline="A headline", lang="en"):
    return {"kind": kind, "events": "one", "lang": lang, "items": [], "mentions": [],
            "main": {"headline_en": headline, "action": action, "actors": list(actors), "object": obj,
                     "numbers": list(numbers), "date": day}}


def parties(*ms):
    return frozenset("name:" + m["name_key"] for m in ms)


class Key(unittest.TestCase):
    """reading -> key (group, parties, stage, date, money), or None."""

    TABLE = [
        # (why, reading, mentions, (group, parties, stage) or None)
        ("a deal: both organisations",
         reading("acquired", ["Acme"], "Widgetco Inc."), [ACME, WIDGETCO], ("deal", parties(ACME, WIDGETCO), "announced")),
        ("direction flipped: B joins A is A acquired B",
         reading("joins", ["Widgetco"], "Acme"), [ACME, WIDGETCO], ("deal", parties(ACME, WIDGETCO), "announced")),
        ("the actors name both, the object one of them, a founder beside them (a person is no deal party)",
         reading("acquired", ["Acme", "Widgetco", "Jane Example"], "Widgetco"), [ACME, WIDGETCO, JANE],
         ("deal", parties(ACME, WIDGETCO), "announced")),
        ("a deal of one resolved organisation: none",
         reading("acquired", ["Acme"], "a small startup"), [ACME], None),
        ("generic actors and a vague object: none",
         reading("found", ["researchers"], "a new way to train models"), [ACME], None),
        ("a release is its thing, whoever the actors are",
         reading("released", ["Acme", "the Acme team"], "Gizmo 4.1"), [ACME, GIZMO], ("release", parties(GIZMO), "released")),
        ("another version is another thing",
         reading("released", ["Acme"], "Gizmo 4.2"), [ACME, GIZMO2], ("release", parties(GIZMO2), "released")),
        ("an object naming its thing among other words resolves to it",
         reading("launched", ["Acme"], "Gizmo 4.1 (open weights on the hub)"), [ACME, GIZMO],
         ("release", parties(GIZMO), "released")),
        ("a leak of a model is its release, rumored",
         reading("leaked", ["someone"], "Gizmo 4.1"), [GIZMO], ("release", parties(GIZMO), "rumored")),
        ("an announcement of a free-text thing: none",
         reading("announced", ["Acme"], "an internal security sprint"), [ACME], None),
        ("a round is its raiser's; the round's text is dropped, the investors are no party",
         reading("raised", ["Widgetco", "Example Ventures"], "$100M Series A", numbers=["$100M"]), [WIDGETCO, FUND],
         ("funding", parties(WIDGETCO), "closed")),
        ("a round whose raiser is unnamed: none",
         reading("raised", ["an unnamed startup", "Example Ventures"], "$100M Series A"), [FUND], None),
        ("a person joining an organisation is a people move",
         reading("joined", ["Jane Example"], "Acme"), [ACME, JANE], ("people", parties(ACME, JANE), "announced")),
        ("a lawsuit between two parties",
         reading("sued", ["Acme"], "Widgetco"), [ACME, WIDGETCO], ("legal", parties(ACME, WIDGETCO), "announced")),
        ("reported names no happening", reading("reported", ["Acme"], "Gizmo 4.1"), [ACME, GIZMO], None),
        ("other names no happening", reading("other", ["Acme"], "Gizmo 4.1"), [ACME, GIZMO], None),
        ("a roundup has no key until units exist",
         reading("released", ["Acme"], "Gizmo 4.1", kind="roundup"), [ACME, GIZMO], None),
        ("commentary on a happening keeps its key",
         reading("acquired", ["Acme"], "Widgetco", kind="commentary"), [ACME, WIDGETCO],
         ("deal", parties(ACME, WIDGETCO), "announced")),
        ("no main: none", {"kind": "report", "main": None}, [ACME], None),
    ]

    def test_the_table(self):
        for why, r, ms, want in self.TABLE:
            got = HP.key(r, ms)
            self.assertEqual(None if got is None else (got.group, got.parties, got.stage), want, why)

    def test_a_linked_mention_is_its_root_entity(self):
        ms = [dict(ACME, root="e-acme"), dict(WIDGETCO, root="e-widgetco")]
        got = HP.key(reading("acquired", ["ACME"], "Widgetco"), ms)
        self.assertEqual(got.parties, frozenset({"e-acme", "e-widgetco"}))

    def test_language_and_headline_are_never_read(self):
        en = HP.key(reading("acquired", ["Acme"], "Widgetco", headline="Acme buys Widgetco", lang="en",
                            numbers=["$7B"]), [ACME, WIDGETCO])
        ru = HP.key(reading("acquired", ["Acme"], "Widgetco", headline="Acme покупает Widgetco", lang="ru",
                            numbers=["7 млрд долларов"]), [ACME, WIDGETCO])
        self.assertEqual(en, ru)
        self.assertTrue(HP.same(en, ru, timedelta(days=14)))

    def test_money_within_tolerance(self):
        self.assertEqual(HP.money("$7B"), 7e9)
        self.assertEqual(HP.money("1,5 млрд $"), 1.5e9)
        self.assertEqual(HP.money("€250 million"), 250e6)
        self.assertEqual(HP.money("$22,299 starting price"), 22299)
        self.assertIsNone(HP.money("10T+ parameters"))           # no currency: not money
        self.assertIsNone(HP.money("80% price cut"))
        k = lambda *n: HP.key(reading("acquired", ["Acme"], "Widgetco", numbers=n), [ACME, WIDGETCO])   # noqa: E731
        w = timedelta(days=14)
        self.assertTrue(HP.same(k("$7B"), k("$7.3 billion"), w))      # within 10%
        self.assertFalse(HP.same(k("$7B"), k("$9B"), w))              # two amounts: two deals
        self.assertTrue(HP.same(k("$7B"), k(), w))                    # one names none: no say
        self.assertTrue(HP.same(k("$7B", "500 employees"), k("$7 billion"), w))

    def test_stated_days(self):
        k = lambda d: HP.key(reading("acquired", ["Acme"], "Widgetco", day=d), [ACME, WIDGETCO])   # noqa: E731
        self.assertEqual(k("2100-03-01").date, date(2100, 3, 1))
        self.assertIsNone(k("March 1").date)                          # not a day: none
        self.assertFalse(HP.same(k("2090-03-01"), k("2100-03-01"), timedelta(days=14)))   # a retelling of an old deal
        self.assertTrue(HP.same(k("2100-03-01"), k("2100-03-05"), timedelta(days=14)))

    def test_groups_come_from_read_v2s_actions(self):
        self.assertEqual(set(HP.ACTION_GROUPS), set(schemas.ACTIONS))
        for g, _stage in list(HP.ACTION_GROUPS.values()) + list(HP.SYNONYMS.values()):
            self.assertTrue(g is None or g in HP.GROUPS, g)


@requires_test_db
class Source(unittest.TestCase):
    T0 = datetime(2100, 9, 1, tzinfo=timezone.utc)
    H = timedelta(hours=1)

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas.load_guides(self.cur)

    def source(self, platform="telegram"):
        return insert_scratch_source(self.cur, platform=platform, settings_json=json.dumps({"display_name": "Example"}))

    def post(self, source, hours, r, mentions):
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                         (source, url, url, "A post", "Its text.", self.T0 + hours * self.H))
        pid = str(self.cur.fetchone()[0])
        tid, _ = tasks.read_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=r)
        repo.answer_task(self.cur, tid)
        tasks.record(self.cur, {"kind": "read", "guide": "read-v2", "a": pid}, call, r)
        tid, _ = tasks.entities_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer={"entities": []})
        repo.add_mentions(self.cur, post_id=pid, guide="ent-v3", call_id=call, mentions=[
            {"span": m["name"], "name": m["name"], "name_key": tasks.name_key(m["name"]), "type": m["type"],
             "role": m["role"], "version": None} for m in mentions])
        return pid

    def pairs(self):
        return {(str(r["a"]), str(r["b"])) for r in repo.candidates(self.cur, pairing.POST_POST, source="happening")}

    def world(self):
        s1, s2, s3 = self.source(), self.source(), self.source()
        ru = self.post(s1, 0, reading("acquired", ["Acme"], "Widgetco Inc.", lang="ru", numbers=["7 млрд $"]),
                       [ACME, WIDGETCO])
        en = self.post(s2, 79.5, reading("joins", ["Widgetco"], "Acme", kind="commentary", numbers=["$7B"]),
                       [ACME, WIDGETCO])
        same_source = self.post(s1, 10, reading("acquired", ["Acme"], "Widgetco", numbers=["$7 billion"]), [ACME, WIDGETCO])
        roundup = self.post(s3, 5, reading("acquired", ["Acme"], "Widgetco", kind="roundup"), [ACME, WIDGETCO])
        later = self.post(s3, 18 * 24, reading("acquired", ["Acme"], "Widgetco"), [ACME, WIDGETCO])   # 14+ days after the last
        other_deal = self.post(s3, 30, reading("acquired", ["Acme"], "Widgetco", numbers=["$1B"]), [ACME, WIDGETCO])
        return ru, en, same_source, roundup, later, other_deal

    def test_off_by_default(self):
        ru, en, *_ = self.world()
        self.assertFalse(pairing.happening_on(self.cur))
        got = C.run(self.cur, [ru, en], since=datetime.now(timezone.utc) - self.H)
        self.assertNotIn("happening", got)
        self.assertEqual(self.pairs(), set())

    def test_on_it_pairs_one_happening_across_languages_and_days(self):
        ru, en, same_source, roundup, later, other_deal = self.world()
        repo.set_setting(self.cur, pairing.HAPPENING_KEY, True)
        got = C.run(self.cur, [], since=datetime.now(timezone.utc) - self.H)   # the posts read since: all of them
        self.assertEqual(self.pairs(), {(ru, en), (same_source, en)})
        self.assertEqual(got["happening"], 2)
        del roundup, later, other_deal   # a roundup, a deal 15 days on, a deal of another amount: none

    def test_a_release_waits_72_hours_at_most(self):
        s1, s2 = self.source(), self.source()
        a = self.post(s1, 0, reading("released", ["Acme"], "Gizmo 4.1"), [ACME, GIZMO])
        b = self.post(s2, 70, reading("leaked", ["someone"], "Gizmo 4.1"), [GIZMO])
        c = self.post(s2, 80, reading("released", ["Acme"], "Gizmo 4.1"), [ACME, GIZMO])
        got = pairing.find(self.cur, pairing.SAME_STORY, [a], sources=("happening",))
        self.assertEqual(self.pairs(), {(a, b)})
        self.assertEqual(got["happening"], 1)
        del c


if __name__ == "__main__":
    unittest.main()
