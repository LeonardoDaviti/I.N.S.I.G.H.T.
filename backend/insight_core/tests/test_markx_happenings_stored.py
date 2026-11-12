"""0175 (Stealth v10.16 slice H): stored happenings (mx_happenings, migration 0118).

  - Rows: a reading, then its mentions, then a link each add a row when the key changes; the same key from a new basis
    updates the row in place; old rows stay; the newest is the post's.
  - Equivalence: on seeded random worlds put through links, merges, pins, undone merges, new mention sets and relinks,
    0166's code (tests/legacy/happening_784d232.py) and the recompute (`compute`) give the same keys, `keys` (stored,
    computed again where the basis moved) gives them too, and Pairing's happening source makes the same candidates
    with the old code and the new (default groups and every group).
  - The backfill: resumable, newest first, a sweep catching a merge, a code change keying every post again; the
    candidates job's step in a savepoint.

The DB part runs only on a database whose name ends in _test (it empties the mx_* tables inside its transaction)."""
from __future__ import annotations

import contextlib
import dataclasses
import json
import random
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import psycopg

from insight_core.markx import happening as HP
from insight_core.markx import jobs, pairing, repo, schemas, tasks
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.legacy import happening_784d232 as OLD
from insight_core.tests.test_markx_api import MX_TABLES

T0 = datetime(2100, 9, 1, tzinfo=timezone.utc)
H = timedelta(hours=1)

# (name, type, role, maker)
NAMES = [("Acme", "org", "actor", None), ("Widgetco", "org", "subject", None), ("Otherco", "org", "actor", None),
         ("Example Ventures", "org", "actor", None), ("Jane Example", "person", "subject", None),
         ("Gizmo 4.1", "model", "subject", "Acme"), ("Exampleland", "place", "mention", None),
         ("Example Wire", "org", "venue", None)]
VERBS = ["acquired", "joins", "raised", "sued", "filed", "hired", "merged", "invested", "released", "announced",
         "leaked", "reported", "other", "settled", "Acquired"]
MONEY = [[], [], ["$7B"], ["7 млрд $"], ["$1B"], ["$7.2 billion"]]


def reading(action, actors, obj, *, numbers=(), day=None, kind="report"):
    return {"kind": kind, "events": "one", "lang": "en", "items": [], "mentions": [],
            "main": {"headline_en": "A headline", "action": action, "actors": list(actors), "object": obj,
                     "numbers": list(numbers), "date": day}}


class _Db(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas.load_guides(self.cur)
        self.ents = {}

    def source(self):
        return insert_scratch_source(self.cur, platform="telegram", settings_json=json.dumps({"display_name": "Ex"}))

    def ent(self, name, typ):
        k = tasks.name_key(name)
        if k not in self.ents:
            self.cur.execute("INSERT INTO mx_entities (type, name, key) VALUES (%s, %s, %s) RETURNING id::text",
                             (typ, name, k))
            self.ents[k] = self.cur.fetchone()[0]
        return self.ents[k]

    def post(self, source, hours, r, names, *, hooked=True):
        """A read post with its ent-v3 mentions: through tasks.record (the hook stores its key) or straight into the
        tables (no key stored: the backfill's and the pool's unkeyed posts)."""
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                         (source, url, url, "A post", "Its text.", T0 + hours * H))
        pid = str(self.cur.fetchone()[0])
        tid, _ = tasks.read_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=r)
        repo.answer_task(self.cur, tid)
        ents = [{"span": n, "name": n, "type": t, "role": role, "maker": maker, "version": None}
                for n, t, role, maker in names]
        etid, _ = tasks.entities_task(self.cur, pid)
        ecall = repo.add_call(self.cur, task_id=etid, executor="claude-code", model="haiku", valid=True,
                              answer={"entities": ents})
        if hooked:
            tasks.record(self.cur, {"kind": "read", "guide": "read-v2", "a": pid}, call, r)
            tasks.record(self.cur, {"kind": "entities", "guide": "ent-v3", "a": pid}, ecall, {"entities": ents})
        else:
            repo.add_reading(self.cur, post_id=pid, guide="read-v2", call_id=call, kind=r.get("kind"), events="one",
                             lang="en", headline=None, reading=r)
            repo.add_mentions(self.cur, post_id=pid, guide="ent-v3", call_id=ecall, mentions=[
                dict(e, name_key=tasks.name_key(e["name"])) for e in ents])
        self.calls = getattr(self, "calls", []) + [ecall]
        return pid

    def rows(self, pid):
        self.cur.execute("SELECT grp, parties, basis FROM mx_happenings WHERE post_id = %s ORDER BY id", (pid,))
        return self.cur.fetchall()

    def link(self, pid, name, eid=None):
        self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND name_key = %s",
                         (eid or self.ents[tasks.name_key(name)], pid, tasks.name_key(name)))


@requires_test_db
class Rows(_Db):
    ACME, WIDGETCO, LAND = NAMES[0], NAMES[1], NAMES[6]

    def test_a_reading_its_mentions_and_a_link_each_add_a_row_the_newest_is_the_posts(self):
        for n, t, _r, _m in NAMES:
            self.ent(n, t)
        s = self.source()
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, 'A post', 'Its text.', %s) RETURNING id::text", (s, url, url, T0))
        pid = self.cur.fetchone()[0]
        r = reading("acquired", ["Acme"], "Widgetco")
        tid, _ = tasks.read_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=r)
        tasks.record(self.cur, {"kind": "read", "guide": "read-v2", "a": pid}, call, r)
        self.assertEqual([x[:2] for x in self.rows(pid)], [(None, [])])          # read, no mentions yet: no key
        ents = [{"span": n, "name": n, "type": t, "role": role, "version": None} for n, t, role, _m in
                (self.ACME, self.WIDGETCO, self.LAND)]
        tasks.record(self.cur, {"kind": "entities", "guide": "ent-v3", "a": pid}, call, {"entities": ents})
        self.assertEqual([x[:2] for x in self.rows(pid)], [(None, []), ("deal", ["name:acme", "name:widgetco"])])
        self.cur.execute("SELECT read_group, guide FROM mx_happenings_now WHERE post_id = %s", (pid,))
        self.assertEqual(self.cur.fetchone(), ("deal", "read-v2"))
        self.link(pid, "Acme")
        self.link(pid, "Widgetco")
        k = HP.keys(self.cur, [pid])[pid]
        self.assertEqual(k.parties, frozenset({self.ents["acme"], self.ents["widgetco"]}))
        self.assertEqual(len(self.rows(pid)), 3)                                  # old rows stay
        self.assertEqual(HP.stored(self.cur, [pid]), {pid: k})
        # the place is no party: linking it moves the basis, not the key: the row's basis, in place
        before = self.rows(pid)
        self.link(pid, "Exampleland")
        self.assertEqual(HP.keys(self.cur, [pid]), {pid: k})
        after = self.rows(pid)
        self.assertEqual(len(after), 3)
        self.assertEqual(after[:2], before[:2])
        self.assertNotEqual(after[2][2], before[2][2])
        # a merge of the two: one party, no key (a row saying so)
        self.cur.execute("INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic) VALUES (%s, %s, 'owner', false)",
                         (self.ents["widgetco"], self.ents["acme"]))
        self.assertEqual(HP.keys(self.cur, [pid]), {})
        self.assertEqual(self.rows(pid)[-1][:2], (None, []))
        self.assertEqual(HP.stored(self.cur, [pid]), {})

    def test_a_reading_of_another_guide_stores_nothing(self):
        s = self.source()
        pid = self.post(s, 0, reading("acquired", ["Acme"], "Widgetco"), [self.ACME, self.WIDGETCO])
        n = len(self.rows(pid))
        tasks.record(self.cur, {"kind": "read3", "guide": "read-v3", "a": pid}, self.calls[-1],
                     {**reading("acquired", ["Acme"], "Widgetco"), "event_type": "business_event", "origin": "other"})
        self.assertEqual(len(self.rows(pid)), n)

    def test_the_backfill_is_resumable_newest_first_and_its_sweep_catches_a_merge(self):
        for n, t, _r, _m in NAMES:
            self.ent(n, t)
        s = self.source()
        old, mid, new = (self.post(s, h, reading("acquired", ["Acme"], "Widgetco"), [self.ACME, self.WIDGETCO],
                                   hooked=False) for h in (0, 10, 20))
        self.assertEqual(HP.stored(self.cur, [old, mid, new]), {})
        got = HP.backfill(self.cur, limit=2, sweep=0)
        self.assertEqual(got, {"keyed": 2, "checked": 0, "left": 1})
        self.assertEqual(set(HP.stored(self.cur, [old, mid, new])), {mid, new})
        self.assertEqual(HP.backfill(self.cur, limit=2, sweep=0), {"keyed": 1, "checked": 0, "left": 0})
        self.assertEqual(HP.backfill(self.cur, limit=2, sweep=0), {"keyed": 0, "checked": 0, "left": 0})
        for p in (old, mid, new):
            self.link(p, "Acme")
            self.link(p, "Widgetco")
        self.cur.execute("INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic) VALUES (%s, %s, 'owner', false)",
                         (self.ents["widgetco"], self.ents["acme"]))
        self.assertEqual(len(HP.stored(self.cur, [old, mid, new])), 3)            # stored: as they were
        got = HP.backfill(self.cur, limit=0, sweep=2)
        self.assertEqual(got["checked"], 2)
        HP.backfill(self.cur, limit=0, sweep=2)
        self.assertEqual(HP.stored(self.cur, [old, mid, new]), HP.compute(self.cur, [old, mid, new]))
        self.assertEqual(HP.stored(self.cur, [old, mid, new]), {})

    def test_a_code_change_keys_every_post_again_in_place(self):
        s = self.source()
        ps = [self.post(s, h, reading("acquired", ["Acme"], "Widgetco"), [self.ACME, self.WIDGETCO]) for h in (0, 5)]
        self.cur.execute("SELECT count(*) FROM mx_happenings")
        n = self.cur.fetchone()[0]
        with mock.patch.object(HP, "_version", "happening-v1:changed"):
            self.assertEqual(HP.backfill(self.cur, limit=10, sweep=0), {"keyed": 2, "checked": 0, "left": 0})
            self.cur.execute("SELECT count(*), count(*) FILTER (WHERE version = 'happening-v1:changed') FROM mx_happenings_now")
            self.assertEqual(self.cur.fetchone(), (2, 2))
        self.cur.execute("SELECT count(*) FROM mx_happenings")
        self.assertEqual(self.cur.fetchone()[0], n)                               # the same keys: no new row
        self.assertEqual(HP.stored(self.cur, ps), HP.compute(self.cur, ps))

    def test_the_candidates_jobs_step_runs_in_a_savepoint(self):
        s = self.source()
        self.post(s, 0, reading("acquired", ["Acme"], "Widgetco"), [self.ACME, self.WIDGETCO], hooked=False)
        self.assertEqual(jobs._happenings_step(self.cur), {"keyed": 1, "checked": 0, "left": 0})
        with mock.patch.object(HP, "backfill", side_effect=RuntimeError("boom")):
            got = jobs._happenings_step(self.cur)
        self.assertEqual(got, {"error": "boom"})
        self.cur.execute("SELECT count(*) FROM mx_happenings")                   # the transaction still works
        self.assertEqual(self.cur.fetchone()[0], 1)


@requires_test_db
class Equivalence(_Db):
    """0166's code, the recompute and the stored keys agree through every change a key's inputs see; Pairing's source
    makes the same candidates with the old code and the new."""

    SEEDS = range(10)
    maxDiff = None

    def world(self, rnd):
        repo.put_guide(self.cur, "ent-v3-6k", "entities", "a second entities guide (test)")   # a second mention set
        for n, t, _r, _m in NAMES:
            self.ent(n, t)
        sources = [self.source() for _ in range(3)]
        posts = []
        for _ in range(32):
            # mostly the two companies of one deal (pairs to find), sometimes anything
            names = NAMES[:2] + rnd.sample(NAMES[2:], rnd.randint(0, 2)) if rnd.random() < 0.6 else \
                rnd.sample(NAMES, rnd.randint(1, 5))
            pick = [n for n, *_ in names]
            actors = rnd.sample(pick, rnd.randint(1, min(3, len(pick)))) + (["a small startup"] if rnd.random() < 0.2 else [])
            obj = rnd.choice(pick + ["", "an IPO filing"])
            day = None if rnd.random() < 0.6 else f"2100-09-{rnd.randint(1, 28):02d}"
            kind = rnd.choices(["report", "commentary", "roundup"], [10, 3, 1])[0]
            r = reading(rnd.choice(VERBS), actors, obj, numbers=rnd.choice(MONEY), day=day, kind=kind)
            posts.append(self.post(rnd.choice(sources), rnd.randint(0, 20 * 24), r, names, hooked=rnd.random() < 0.7))
        return posts

    def mentions(self):
        self.cur.execute("SELECT post_id::text, guide, n, name_key FROM mx_mentions ORDER BY post_id, guide, n")
        return self.cur.fetchall()

    def mutate(self, rnd, step, posts):
        ents = sorted(self.ents.values())
        if step == "link":
            for pid, g, n, nk in self.mentions():
                if rnd.random() < 0.7 and nk in self.ents:
                    self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND guide = %s AND n = %s",
                                     (self.ents[nk], pid, g, n))
        elif step == "merge":
            for a, b in rnd.sample([(x, y) for x in ents for y in ents if x != y], 2):
                self.cur.execute("SELECT 1 FROM mx_entity_redirects WHERE undone_at IS NULL AND from_id IN (%s, %s)", (a, b))
                if self.cur.fetchone() is None:
                    self.cur.execute("INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic) "
                                     "VALUES (%s, %s, 'owner', false)", (a, b))
        elif step == "pin":
            for pid, g, n, _nk in rnd.sample(self.mentions(), 3):
                self.cur.execute("SELECT 1 FROM mx_entity_pins WHERE post_id = %s AND guide = %s AND n = %s "
                                 "AND undone_at IS NULL", (pid, g, n))
                if self.cur.fetchone() is None:
                    self.cur.execute("INSERT INTO mx_entity_pins (post_id, guide, n, entity_id) VALUES (%s, %s, %s, %s)",
                                     (pid, g, n, rnd.choice(ents)))
        elif step == "undo":
            self.cur.execute("UPDATE mx_entity_redirects SET undone_at = now() WHERE id = (SELECT id FROM mx_entity_redirects "
                             "WHERE undone_at IS NULL ORDER BY id LIMIT 1)")
        elif step == "new set":
            for pid in rnd.sample(posts, 3):
                names = rnd.sample(NAMES, rnd.randint(2, 6))
                repo.add_mentions(self.cur, post_id=pid, guide="ent-v3-6k", call_id=self.calls[0], mentions=[
                    {"span": n, "name": n, "name_key": tasks.name_key(n), "type": t, "role": role, "maker": maker}
                    for n, t, role, maker in names])
                if rnd.random() < 0.5:
                    self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND guide = 'ent-v3-6k'",
                                     (rnd.choice(ents), pid))
        elif step == "relink":
            for pid, g, n, _nk in rnd.sample(self.mentions(), 4):
                self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND guide = %s AND n = %s",
                                 (rnd.choice(ents + [None]), pid, g, n))

    def candidates(self, new, every, legacy):
        pol = pairing.POLICIES[pairing.SAME_STORY]
        if every:
            pol = dataclasses.replace(pol, happening_groups=HP.GROUPS)
        self.cur.execute("SAVEPOINT c")
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(pairing.POLICIES, {pairing.SAME_STORY: pol}))
            if legacy:
                stack.enter_context(mock.patch.dict(pairing.STORED, {"happening": OLD.pairs}))
            got = pairing.find(self.cur, pairing.SAME_STORY, new, sources=("happening",))
        pairs = {(str(r["a"]), str(r["b"])) for r in repo.candidates(self.cur, pairing.POST_POST, source="happening")}
        self.cur.execute("ROLLBACK TO SAVEPOINT c")
        return got["happening"], pairs

    def check(self, posts, rnd, why):
        def plain(keys):   # the old module's Happening is its own class: compare the values
            return {p: dataclasses.astuple(k) for p, k in keys.items()}
        old = plain(OLD.keys(self.cur, posts))
        self.assertEqual(plain(HP.compute(self.cur, posts)), old, why)
        self.assertEqual(plain(HP.keys(self.cur, posts)), old, why)
        self.assertEqual(plain(HP.stored(self.cur, posts)), old, why)
        for every in (False, True):
            some = rnd.sample(posts, 12)
            want = self.candidates(some, every, legacy=True)
            self.assertEqual(self.candidates(some, every, legacy=False), want, (why, every))
            self.paired += len(want[1])

    def test_old_recompute_and_stored_agree_through_every_change(self):
        self.paired = 0
        keyed = set()
        for seed in self.SEEDS:
            with self.subTest(seed=seed):
                rnd = random.Random(seed)
                self.cur.execute("SAVEPOINT w")
                self.calls = []
                posts = self.world(rnd)
                self.check(posts, rnd, "as read")
                for step in ("link", "merge", "pin", "undo", "new set", "relink", "merge"):
                    self.mutate(rnd, step, posts)
                    self.check(posts, rnd, step)
                    keyed |= {(seed, p) for p in HP.compute(self.cur, posts)}
                # history: a new row only when the key changed; the newest is the post's
                self.cur.execute("""SELECT post_id::text, array_agg(row(grp, parties, stage, at, money, read_group)::text
                                                              ORDER BY id) FROM mx_happenings GROUP BY post_id""")
                for pid, hist in self.cur.fetchall():
                    self.assertTrue(all(a != b for a, b in zip(hist, hist[1:])), (pid, hist))
                self.cur.execute("ROLLBACK TO SAVEPOINT w")
                self.ents = {}
        self.assertGreater(len(keyed), 40)          # the worlds make keys...
        self.assertGreater(self.paired, 10)         # ...and pairs, so the agreement says something


if __name__ == "__main__":
    unittest.main()
