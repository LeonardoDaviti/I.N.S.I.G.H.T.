"""The Happening (issue 0166 step 2): a reading as a key (a table of readings and the key each makes, or none), and
Pairing's `happening` source on a test database: off by default, on it pairs two posts of one happening across
languages and days, never a roundup, never one source with itself.

The DB part runs only on a database whose name ends in _test (it empties the mx_* tables inside its transaction)."""
from __future__ import annotations

import dataclasses
import json
import unittest
import uuid
from unittest import mock
from datetime import date, datetime, timedelta, timezone

import psycopg

from insight_core.markx import candidates as C
from insight_core.markx import happening as HP
from insight_core.markx import pairing, repo, schemas, tasks
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES

ACME = {"name": "Acme", "name_key": "acme", "type": "org", "role": "actor"}
WIDGETCO = {"name": "Widgetco", "name_key": "widgetco", "type": "org", "role": "subject"}
GIZMO = {"name": "Gizmo 4.1", "name_key": "gizmo 4.1", "type": "model", "role": "subject", "maker": "Acme"}
OTHERCO = {"name": "Otherco", "name_key": "otherco", "type": "org", "role": "actor"}
JANE = {"name": "Jane Example", "name_key": "jane example", "type": "person", "role": "subject"}
FUND = {"name": "Example Ventures", "name_key": "example ventures", "type": "org", "role": "actor"}
LAND = {"name": "Exampleland", "name_key": "exampleland", "type": "place", "role": "mention"}
WIRE = {"name": "Example Wire", "name_key": "example wire", "type": "org", "role": "venue"}


def reading(action, actors, obj, *, numbers=(), day=None, kind="report", headline="A headline", lang="en"):
    return {"kind": kind, "events": "one", "lang": lang, "items": [], "mentions": [],
            "main": {"headline_en": headline, "action": action, "actors": list(actors), "object": obj,
                     "numbers": list(numbers), "date": day}}


def parties(*ms):
    return frozenset("name:" + m["name_key"] for m in ms)


class Key(unittest.TestCase):
    """reading -> key (group, parties, stage), or None. E1's rules: 2+ separate parties, a company and its own product
    one party, places and venues none, a roundup none."""

    TABLE = [
        # (why, reading, mentions, (group, parties, stage) or None)
        ("a deal: both organisations",
         reading("acquired", ["Acme"], "Widgetco Inc."), [ACME, WIDGETCO], ("deal", parties(ACME, WIDGETCO), "announced")),
        ("direction flipped: B joins A is A acquired B (no person: a deal)",
         reading("joins", ["Widgetco"], "Acme"), [ACME, WIDGETCO], ("deal", parties(ACME, WIDGETCO), "announced")),
        ("a founder beside the two companies is a third party",
         reading("acquired", ["Acme", "Widgetco", "Jane Example"], "Widgetco"), [ACME, WIDGETCO, JANE],
         ("deal", parties(ACME, WIDGETCO, JANE), "announced")),
        ("one resolved party and free text: none",
         reading("acquired", ["Acme"], "a small startup"), [ACME], None),
        ("generic actors and a vague object: none",
         reading("found", ["researchers"], "a new way to train models"), [ACME], None),
        ("a free-text object beside two named parties is no party; the key stands",
         reading("sued", ["Acme", "Widgetco"], "a patent lawsuit"), [ACME, WIDGETCO],
         ("legal", parties(ACME, WIDGETCO), "announced")),
        ("a maker's release of its own model is one party: none (left to the 72-hour sources)",
         reading("released", ["Acme"], "Gizmo 4.1"), [ACME, GIZMO], None),
        ("a release by a partner of the maker: two parties",
         reading("launched", ["Otherco"], "Gizmo 4.1 (on its cloud)"), [OTHERCO, GIZMO, ACME],
         ("release", parties(OTHERCO, GIZMO), "released")),
        ("a leak of a model by another party is its release, rumored",
         reading("leaked", ["Otherco"], "Gizmo 4.1"), [OTHERCO, GIZMO], ("release", parties(OTHERCO, GIZMO), "rumored")),
        ("an announcement of a free-text thing: none",
         reading("announced", ["Acme"], "an internal security sprint"), [ACME], None),
        ("a round: its raiser and its investor; the round's text is no party",
         reading("raised", ["Widgetco", "Example Ventures"], "$100M Series A", numbers=["$100M"]), [WIDGETCO, FUND],
         ("funding", parties(WIDGETCO, FUND), "closed")),
        ("a round whose raiser is unnamed: one party, none",
         reading("raised", ["an unnamed startup", "Example Ventures"], "$100M Series A"), [FUND], None),
        ("a person joining an organisation is a people move",
         reading("joined", ["Jane Example"], "Acme"), [ACME, JANE], ("people", parties(ACME, JANE), "announced")),
        ("a place is no party",
         reading("sued", ["Exampleland"], "Acme"), [ACME, LAND], None),
        ("an outlet that reported it is no party",
         reading("acquired", ["Example Wire", "Acme"], "Widgetco"), [ACME, WIDGETCO, WIRE],
         ("deal", parties(ACME, WIDGETCO), "announced")),
        ("reported names no happening", reading("reported", ["Acme"], "Widgetco"), [ACME, WIDGETCO], None),
        ("other names no happening", reading("other", ["Acme"], "Widgetco"), [ACME, WIDGETCO], None),
        ("a roundup has no key until units exist",
         reading("acquired", ["Acme"], "Widgetco", kind="roundup"), [ACME, WIDGETCO], None),
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
        self.assertEqual(HP.money("$12,930,300,000"), 12930300000)
        self.assertIsNone(HP.money("10T+ parameters"))           # no currency: not money
        self.assertIsNone(HP.money("80% price cut"))
        k = lambda *n: HP.key(reading("acquired", ["Acme"], "Widgetco", numbers=n), [ACME, WIDGETCO])   # noqa: E731
        w = timedelta(days=14)
        self.assertTrue(HP.same(k("$7B"), k("$8.5 billion"), w))      # within 30%
        self.assertFalse(HP.same(k("$7B"), k("$12B"), w))             # 42% apart: two deals
        self.assertTrue(HP.same(k("$7B"), k(), w))                    # one names none: no say
        self.assertTrue(HP.same(k("$7B", "500 employees"), k("$7 billion"), w))

    def test_two_shared_parties_are_enough(self):
        three = HP.key(reading("acquired", ["Acme", "Jane Example"], "Widgetco"), [ACME, WIDGETCO, JANE])
        two = HP.key(reading("acquired", ["Acme"], "Widgetco"), [ACME, WIDGETCO])
        other = HP.key(reading("acquired", ["Acme"], "Otherco"), [ACME, OTHERCO])
        w = timedelta(days=30)
        self.assertTrue(HP.same(three, two, w))
        self.assertFalse(HP.same(two, other, w))                      # one shared party: two deals
        self.assertIn(("deal", parties(ACME, WIDGETCO)), three.indexes())

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
        later = self.post(s3, 40 * 24, reading("acquired", ["Acme"], "Widgetco"), [ACME, WIDGETCO])   # 30+ days after the last
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
        del roundup, later, other_deal   # a roundup, a deal 37 days on, a deal of another amount: none

    def test_each_group_its_window_and_only_measured_groups(self):
        """legal: 7 days; a release (E1 did not measure it) is not paired by default; on, 72 hours."""
        s1, s2, s3 = self.source(), self.source(), self.source()
        a = self.post(s1, 0, reading("sued", ["Acme"], "Widgetco"), [ACME, WIDGETCO])
        b = self.post(s2, 6 * 24, reading("sued", ["Widgetco", "Acme"], "a patent case"), [ACME, WIDGETCO])
        c = self.post(s3, 8 * 24, reading("sued", ["Acme"], "Widgetco"), [ACME, WIDGETCO])            # 8 days: no
        r1 = self.post(s1, 1, reading("launched", ["Otherco"], "Gizmo 4.1"), [OTHERCO, GIZMO])
        r2 = self.post(s2, 70, reading("announced", ["Otherco"], "Gizmo 4.1"), [OTHERCO, GIZMO])
        r3 = self.post(s3, 80, reading("launched", ["Otherco"], "Gizmo 4.1"), [OTHERCO, GIZMO])        # 79 hours: no
        own = self.post(s3, 5, reading("released", ["Acme"], "Gizmo 4.1"), [ACME, GIZMO])               # one party
        got = pairing.find(self.cur, pairing.SAME_STORY, [a, r1, own], sources=("happening",))
        self.assertEqual(self.pairs(), {(a, b)})
        self.assertEqual(got["happening"], 1)
        every = dataclasses.replace(pairing.POLICIES[pairing.SAME_STORY], happening_groups=HP.GROUPS)
        with mock.patch.dict(pairing.POLICIES, {pairing.SAME_STORY: every}):
            pairing.find(self.cur, pairing.SAME_STORY, [r1, own], sources=("happening",))
        self.assertEqual(self.pairs(), {(a, b), (r1, r2)})
        del c, r3


if __name__ == "__main__":
    unittest.main()
