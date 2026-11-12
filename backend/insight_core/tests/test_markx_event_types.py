"""0175 (Stealth v10.16 slice H): the event-type seam (markx/event_types.py). Its pure mapping is the one Happening
used (0166's verbatim copy, tests/legacy/happening_784d232.py), and every consumer moved to it reads what it read
before: folds' story folds, built's members and "came true" neighbours, News sections' row types and Discover's
main-source stories, each run against its old query (copied here verbatim from 784d232) on seeded random worlds.

The DB part runs only on a database whose name ends in _test (it empties the mx_* tables inside its transaction)."""
from __future__ import annotations

import json
import random
import unittest
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.markx import built, event_types as ET, folds, news_sections, repo, schemas
from insight_core.markx import happening as HP
from insight_core.services import discover_main_source as DMS
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.legacy import happening_784d232 as OLD
from insight_core.tests.test_markx_api import MX_TABLES

T0 = datetime(2100, 6, 1, tzinfo=timezone.utc)
H = timedelta(hours=1)


class Mapping(unittest.TestCase):
    def test_the_action_groups_are_happenings_old_ones(self):
        self.assertEqual(ET.ACTION_GROUPS, OLD.ACTION_GROUPS)
        self.assertEqual(ET.SYNONYMS, OLD.SYNONYMS)
        self.assertEqual(ET.GROUPS, OLD.GROUPS)
        self.assertIs(HP.ACTION_GROUPS, ET.ACTION_GROUPS)
        verbs = list(OLD.ACTION_GROUPS) + list(OLD.SYNONYMS) + ["", None, "Acquired", " joins ", "frobbed", "OTHER"]
        for v in verbs:
            self.assertEqual(ET.action_group(v), OLD._group(v), v)
            self.assertEqual(HP._group(v), OLD._group(v), v)

    def test_from_reading_by_guide(self):
        r2 = {"kind": "report", "main": {"action": "acquired"}}
        r3 = {**r2, "event_type": "business_event", "origin": "maker"}
        self.assertEqual(ET.from_reading(r2, "read-v2"), ET.EventType(None, None, "deal", "announced"))
        self.assertEqual(ET.from_reading(r3, "read-v3"), ET.EventType("business_event", "maker", None, None))
        self.assertEqual(ET.from_reading(None, "read-v2"), ET.EventType())
        self.assertEqual(ET.from_reading({"main": None}, "read-v2"), ET.EventType())

    def test_the_pool_groups_are_the_old_verbs(self):
        for gs in ({"deal"}, {"release"}, {"legal", "people"}, set(OLD.GROUPS), set()):
            want = sorted(a for a in OLD._verbs(gs))
            got = sorted(a for a, (g, _s) in {**ET.ACTION_GROUPS, **ET.SYNONYMS}.items() if g in HP._pool_groups(gs))
            self.assertEqual(got, want, gs)
            self.assertEqual(ET.verbs(HP._pool_groups(gs)), want)


# ---- the consumers' old queries (784d232, verbatim but for the function names) ------------------------------------

def old_story_folds(cur, story_ids):
    story_ids = sorted({str(s) for s in story_ids if s})
    if not story_ids:
        return {}
    cur.execute("""SELECT sp.story_id::text, sp.post_id::text, COALESCE(p.published_at, p.surfaced_at, p.fetched_at),
                          r.reading->>'event_type', r.reading->>'origin'
                     FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id
                     LEFT JOIN mx_readings r ON r.post_id = sp.post_id AND r.guide = %s
                    WHERE sp.story_id = ANY(%s::uuid[]) AND sp.valid_to IS NULL AND sp.role = 'member'""",
                (folds.GUIDE, story_ids))
    members = {}
    for sid, pid, at, et, origin in cur.fetchall():
        members.setdefault(sid, []).append(folds.Member(id=pid, at=at, event_type=et, origin=origin))
    answers = folds.owner_answers(cur, [(s, x.id) for s, ms in members.items() for x in ms])
    return {s: folds.group(ms, {p: a for (st, p), a in answers.items() if st == s}) for s, ms in members.items()}


def old_built_load(cur, story_ids):
    if not story_ids:
        return {}
    cur.execute(f"""SELECT sp.story_id::text, sp.post_id::text, p.source_id::text, {built.PUBLISHED},
                           r.reading->>'event_type', r.reading->>'origin'
                      FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id
                      LEFT JOIN mx_readings r ON r.post_id = sp.post_id AND r.guide = %s
                     WHERE sp.story_id = ANY(%s::uuid[]) AND sp.valid_to IS NULL AND sp.role = 'member'""",
                (folds.GUIDE, list(story_ids)))
    out = defaultdict(list)
    for sid, pid, src, at, et, origin in cur.fetchall():
        out[sid].append({"id": pid, "source": src, "at": at, "event_type": et, "origin": origin})
    return dict(out)


def old_neighbours(cur, lo, hi, have):
    cur.execute(f"""SELECT DISTINCT sp.story_id::text FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id
                      JOIN mx_stories s ON s.id = sp.story_id AND s.merged_into IS NULL
                      JOIN mx_readings r ON r.post_id = sp.post_id AND r.guide = %s
                     WHERE sp.valid_to IS NULL AND sp.role = 'member' AND {built.PUBLISHED} BETWEEN %s AND %s
                       AND r.reading->>'event_type' = ANY(%s)""",
                (folds.GUIDE, lo, hi, [built.LEAK, *built.NEWS_TYPES]))
    return sorted({r[0] for r in cur.fetchall()} - have)


def old_types(cur, rows):
    ids = sorted({p["post_id"] for r in rows for p in r.get("posts") or []})
    if not ids:
        return {}
    cur.execute("""SELECT r.post_id::text, COALESCE(p.published_at, p.surfaced_at, p.fetched_at),
                          r.reading->>'event_type', r.reading->>'origin'
                     FROM mx_readings r JOIN posts p ON p.id = r.post_id
                    WHERE r.guide = %s AND r.post_id = ANY(%s::uuid[])""", (folds.GUIDE, ids))
    got = {pid: folds.Member(id=pid, at=at, event_type=et, origin=o) for pid, at, et, o in cur.fetchall() if et}
    return {str(r["id"]): folds.story_type([got[p["post_id"]] for p in r.get("posts") or [] if p["post_id"] in got])
            for r in rows}


def old_discover_stories(cur, since):
    cur.execute(f"""SELECT sp.story_id::text, sp.post_id::text, p.source_id::text, {built.PUBLISHED}, s.headline,
                           s.first_at, r.reading->>'event_type', r.reading->>'origin'
                      FROM mx_story_posts sp JOIN mx_stories s ON s.id = sp.story_id AND s.merged_into IS NULL
                      JOIN posts p ON p.id = sp.post_id
                      LEFT JOIN mx_readings r ON r.post_id = sp.post_id AND r.guide = %s
                     WHERE sp.valid_to IS NULL AND sp.role = 'member' AND s.first_at >= %s""", (folds.GUIDE, since))
    out = {}
    for sid, pid, src, at, headline, first_at, et, origin in cur.fetchall():
        s = out.setdefault(sid, {"headline": headline or "", "first_at": first_at, "posts": {}})
        if pid not in s["posts"] or et is not None:
            s["posts"][pid] = built.Post(id=pid, source=src, at=at, event_type=et, origin=origin)
    return out


@requires_test_db
class Consumers(unittest.TestCase):
    """Each consumer moved to the seam returns what its old query did, on 12 seeded random worlds."""

    SEEDS = range(12)

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas.load_guides(self.cur)
        tid, _ = repo.add_task(self.cur, kind="read", guide="read-v2", subject_kind="post", input="seam test")
        self.call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer={})
        self.run = repo.start_run(self.cur, code_version="test", config={})

    def world(self, seed):
        rnd = random.Random(seed)
        sources = [insert_scratch_source(self.cur, platform="telegram", settings_json=json.dumps({"display_name": "Ex"}))
                   for _ in range(3)]
        posts = []
        for n in range(30):
            at = T0 + rnd.randint(0, 40 * 24) * H
            url = f"https://test.invalid/seam/{uuid.uuid4().hex}"
            pub = None if rnd.random() < 0.2 else at
            self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, title, content, published_at, surfaced_at)
                                VALUES (%s, %s, %s, 'A post', 'Its text.', %s, %s) RETURNING id""",
                             (rnd.choice(sources), url, url, pub, None if rnd.random() < 0.5 else at + H))
            pid = str(self.cur.fetchone()[0])
            posts.append(pid)
            main = {"headline_en": "x", "action": rnd.choice(list(ET.ACTION_GROUPS) + ["filed", "joins", "frobbed"]),
                    "actors": [], "object": ""}
            if rnd.random() < 0.8:
                repo.add_reading(self.cur, post_id=pid, guide="read-v2", call_id=self.call, kind="report", events="one",
                                 lang="en", headline=None, reading={"kind": "report", "main": main})
            if rnd.random() < 0.6:
                r3 = {"kind": "report", "main": main, "origin": rnd.choice(["maker", "relay", "other"])}
                if rnd.random() < 0.9:
                    r3["event_type"] = rnd.choice(schemas.EVENT_TYPES)
                repo.add_reading(self.cur, post_id=pid, guide="read-v3", call_id=self.call, kind="report", events="one",
                                 lang="en", headline=None, reading=r3)
        stories = []
        for s in range(8):
            first = T0 + rnd.randint(0, 20 * 24) * H
            sid = str(repo.add_story(self.cur, first_at=first, run_id=self.run, headline=f"Story {s}"))
            stories.append(sid)
            for p in rnd.sample(posts, rnd.randint(1, 7)):
                repo.open_membership(self.cur, story_id=sid, post_id=p, role=rnd.choice(["member"] * 4 + ["mention"]),
                                     reason="test", run_id=self.run)
                if rnd.random() < 0.1:
                    repo.close_membership(self.cur, story_id=sid, post_id=p)
        if rnd.random() < 0.5:
            repo.merge_story(self.cur, stories[0], into=stories[1])
        for _ in range(3):   # the owner's fold answers
            sid = rnd.choice(stories)
            self.cur.execute("SELECT post_id::text FROM mx_story_posts WHERE story_id = %s LIMIT 1", (sid,))
            row = self.cur.fetchone()
            if row:
                repo.add_label(self.cur, item_kind="fold", a=sid, b=row[0], answer=rnd.choice(["same", "not_same"]))
        rows = [{"id": str(uuid.uuid4()), "posts": [{"post_id": p} for p in rnd.sample(posts, rnd.randint(0, 6))]}
                for _ in range(6)]
        return rnd, posts, stories, rows

    def test_every_consumer_reads_what_it_read(self):
        for seed in self.SEEDS:
            with self.subTest(seed=seed):
                self.cur.execute("SAVEPOINT w")
                rnd, posts, stories, rows = self.world(seed)
                self.assertEqual(folds.story_folds(self.cur, stories), old_story_folds(self.cur, stories))
                self.assertEqual(built._load(self.cur, stories), old_built_load(self.cur, stories))
                for _ in range(3):
                    lo = T0 + rnd.randint(0, 30 * 24) * H
                    hi = lo + rnd.randint(1, 20 * 24) * H
                    have = set(rnd.sample(stories, 2))
                    self.assertEqual(built._neighbours(self.cur, lo, hi, have), old_neighbours(self.cur, lo, hi, have))
                self.assertEqual(news_sections._types(self.cur, rows), old_types(self.cur, rows))
                self.assertEqual(news_sections._types(self.cur, []), old_types(self.cur, []))
                self.assertEqual(DMS._stories(self.cur, T0 + 5 * 24 * H), old_discover_stories(self.cur, T0 + 5 * 24 * H))
                self.cur.execute("ROLLBACK TO SAVEPOINT w")

    def test_of_posts_by_guide(self):
        _rnd, posts, _s, _r = self.world(99)
        got = ET.of_posts(self.cur, posts)
        self.cur.execute("SELECT post_id::text, guide, reading FROM mx_readings")
        by = defaultdict(dict)
        for pid, g, r in self.cur.fetchall():
            by[pid][g] = r
        self.assertEqual(set(got), set(by))
        for pid, rs in by.items():
            r3, r2 = rs.get("read-v3"), rs.get("read-v2")
            self.assertEqual(got[pid].type, (r3 or {}).get("event_type"))
            self.assertEqual(got[pid].origin, (r3 or {}).get("origin"))
            self.assertEqual((got[pid].group, got[pid].stage),
                             ET.action_group(((r2 or {}).get("main") or {}).get("action")) if r2 else (None, None))
        self.assertEqual(ET.of_posts(self.cur, []), {})
        nobody = str(uuid.uuid4())
        self.assertEqual(ET.types_of(self.cur, [nobody]), {nobody: (None, None)})


if __name__ == "__main__":
    unittest.main()
