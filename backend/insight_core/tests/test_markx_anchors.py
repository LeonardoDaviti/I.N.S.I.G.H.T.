"""0180 (Stealth v10.16 slice J): anchors (0166 step 3).

  - Pairing's `develops` row: E6's windows per group (deal 3-120 days, legal 3-30, funding and people never, release
    unmeasured: never), 2+ separate shared parties, no money clash; back's gates (and the long-lived rule's) read
    from the row.
  - anchors.of: Mark IX stories, Mark X stories (current members, not merged), happening anchors (posts of one
    happening no story holds, chained within the first gap); 2+ voices for a story.
  - (The later engine went with Later developments in v10.18, 0203.)
  - The back engine: an H burst, and its first gap instead of 14/7 days.
  - Shadow: back.stage writes both engines' rows (engine, anchor_kind, anchor_id), the pages show the
    engine `anchors.shown` names (old by default), the comparison (only old, only new, both), an error in the anchors
    engine leaves the old rows standing, a concurrent update still defers the stage.
  - Migration 0122: old rows read as ix_story; one story and window may have a row of each engine.
Synthetic data and invented names only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import unittest
from datetime import timedelta
from unittest import mock

from psycopg import errors as psycopg_errors

from insight_core.markx import anchors, back, happening, later, pairing, repo, tasks
from insight_core.tests.test_markx_api import call
from insight_core.tests.test_markx_back import DAY, NOW
from insight_core.tests.test_markx_later import _Later

POL = pairing.policy(pairing.DEVELOPS)


def key(group, parties, numbers=()):
    return happening.Happening(group, frozenset(parties), None, None, tuple(numbers))


class TheDevelopsRow(unittest.TestCase):
    def test_e6_windows_per_group(self):
        a, b = key("deal", {"acme", "widgetco"}), key("deal", {"acme", "widgetco"})
        for days, ok in ((2.9, False), (3, True), (60, True), (120, True), (121, False)):
            self.assertEqual(pairing.develops(POL, a, b, days * DAY), ok, days)
        a, b = key("legal", {"acme", "regulator"}), key("legal", {"acme", "regulator"})
        for days, ok in ((2, False), (3, True), (30, True), (31, False)):
            self.assertEqual(pairing.develops(POL, a, b, days * DAY), ok, days)
        for g in ("funding", "people", "release", "research", "pricing", "announcement"):
            self.assertFalse(pairing.develops(POL, key(g, {"a", "b"}), key(g, {"a", "b"}), 10 * DAY), g)

    def test_parties_groups_and_money(self):
        self.assertFalse(pairing.develops(POL, key("deal", {"acme", "widgetco"}), key("deal", {"acme", "other"}), 10 * DAY))
        self.assertTrue(pairing.develops(POL, key("deal", {"acme", "widgetco"}), key("deal", {"acme", "widgetco", "bank"}),
                                         10 * DAY))
        self.assertFalse(pairing.develops(POL, key("deal", {"a", "b"}), key("legal", {"a", "b"}), 10 * DAY))
        self.assertFalse(pairing.develops(POL, key("deal", {"a", "b"}, [7e9]), key("deal", {"a", "b"}, [2e9]), 10 * DAY))
        self.assertTrue(pairing.develops(POL, key("deal", {"a", "b"}, [7e9]), key("deal", {"a", "b"}, [7.5e9]), 10 * DAY))
        self.assertTrue(pairing.develops(POL, key("deal", {"a", "b"}, [7e9]), key("deal", {"a", "b"}), 10 * DAY))

    def test_back_and_later_read_their_gates_from_the_row(self):
        self.assertEqual((back.FIRST_DAYS, back.LAST_DAYS, back.WINDOW, back.MIN_SOURCES, back.COS, back.HUB_WEEKS),
                         (14, 7, timedelta(hours=72), 2, 0.70, 6))
        self.assertEqual(back.SPECIFIC, ("model", "product", "software", "paper", "document", "dataset", "event", "law",
                                         "other"))
        self.assertEqual((later.MAIN_SHARE, later.AGAIN), (0.5, timedelta(days=30)))
        self.assertEqual(later.LONG_TYPES, ("paper", "document", "dataset", "method", "model", "software"))
        with mock.patch.dict(pairing.POLICIES, {pairing.DEVELOPS: pairing.policy(pairing.DEVELOPS, release_types=())}):
            pol = pairing.policy(pairing.DEVELOPS)
            self.assertFalse(pairing.specific(pol, "model", level="version"))   # the gate is the row's
        self.assertTrue(pairing.specific(POL, "model", level="version"))


class _Anchors(_Later):
    shadow = True        # the anchors engine runs beside the old one (turned on: off by default since v10.17)

    def read(self, post, action, actors, obj, names, numbers=()):
        """A read-v2 reading of the post and its ent-v3 mentions [(name, type, role)], recorded as the worker's
        answers are (the hook stores its happening key)."""
        r = {"kind": "report", "events": "one", "lang": "en", "items": [], "mentions": [],
             "main": {"headline_en": "A headline", "action": action, "actors": list(actors), "object": obj,
                      "numbers": list(numbers), "date": None}}
        with self.conn.transaction():
            tid, _ = tasks.read_task(self.cur, post)
            c = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=r)
            repo.answer_task(self.cur, tid)
            tasks.record(self.cur, {"kind": "read", "guide": "read-v2", "a": post}, c, r)
            ents = [{"span": n, "name": n, "type": t, "role": role, "maker": None, "version": None}
                    for n, t, role in names]
            etid, _ = tasks.entities_task(self.cur, post)
            ec = repo.add_call(self.cur, task_id=etid, executor="claude-code", model="haiku", valid=True,
                               answer={"entities": ents})
            tasks.record(self.cur, {"kind": "entities", "guide": "ent-v3", "a": post, "input": ""}, ec,
                         {"entities": ents})

    def deal(self, days, source, action="acquired", numbers=()):
        """A post of the invented deal: Acme and Widgetco (orgs: no subject later or back would follow)."""
        p = self.post(source=source, at=self.at(days))
        self.read(p, action, ["Acme"], "Widgetco", [("Acme", "org", "actor"), ("Widgetco", "org", "subject")], numbers)
        return p

    def lawsuit(self, days, source, action="sued"):
        p = self.post(source=source, at=self.at(days))
        self.read(p, action, ["Acme"], "Gadgetcorp", [("Acme", "org", "actor"), ("Gadgetcorp", "org", "subject")])
        return p

    def mx_story(self, *members):
        self.cur.execute("INSERT INTO mx_stories (first_at) VALUES (now()) RETURNING id::text")
        sid = self.cur.fetchone()[0]
        for m in members:
            self.cur.execute("INSERT INTO mx_story_posts (story_id, post_id, role, reason) VALUES (%s, %s, 'member', 'test')",
                             (sid, m))
        return sid

class Anchors(_Anchors):
    def test_ix_mx_and_happening_anchors(self):
        a, b = self.deal(80, self.source), self.deal(79, self.other)
        ix = self.story(a, b)
        c = self.post(source=self.source, at=self.at(60))
        d = self.post(source=self.other, at=self.at(59))
        mx = self.mx_story(c, d)
        lone = self.mx_story(self.post(source=self.source, at=self.at(50)), self.post(source=self.source, at=self.at(49)))
        h1, h2 = self.lawsuit(40, self.third), self.lawsuit(39, self.fourth)    # one happening, no story, a day apart
        h3 = self.lawsuit(30, self.third)                                       # 9 days on: a follow-up, not a member
        got = anchors.of(self.cur, near=(self.at(100), NOW))
        self.assertIn((anchors.IX, ix), got)
        self.assertEqual(set(got[(anchors.IX, ix)].happenings), {a, b})        # its members' stored keys
        self.assertIn((anchors.MX, mx), got)
        self.assertNotIn((anchors.MX, lone), got)                               # one voice
        hap = [x for x in got.values() if x.kind == anchors.HAPPENING]
        self.assertEqual(sorted(sorted(x.mids) for x in hap), sorted([sorted([h1, h2]), [h3]]))
        self.assertEqual({x.id for x in hap}, {h1, h3})                         # its earliest post
        self.assertNotIn(a, {m for x in hap for m in x.mids})                   # a story holds a and b

    def test_a_merged_or_left_mark_x_story_is_no_anchor(self):
        c, d = self.post(source=self.source, at=self.at(60)), self.post(source=self.other, at=self.at(59))
        mx = self.mx_story(c, d)
        self.cur.execute("UPDATE mx_story_posts SET valid_to = now() WHERE post_id = %s", (d,))
        self.assertNotIn((anchors.MX, mx), anchors.of(self.cur))
        mx2 = self.mx_story(c, d)
        self.cur.execute("UPDATE mx_stories SET merged_into = %s WHERE id = %s", (mx, mx2))
        self.assertNotIn((anchors.MX, mx2), anchors.of(self.cur))


class TheBackEngine(_Anchors):
    def test_an_h_burst_from_its_first_gap(self):
        a, b = self.deal(12, self.source), self.deal(9, self.other)          # last post 9 days back: old t0 not reached
        sid = self.story(a, b)
        c1, c2 = self.deal(2, self.third, action="completed"), self.deal(1.5, self.fourth, action="closed")
        self.assertEqual(back.find(self.cur, now=NOW, since=NOW - 60 * DAY), [])
        got = anchors.back_find(self.cur, now=NOW, since=NOW - 60 * DAY)
        self.assertEqual([(c["anchor_kind"], c["story"], c["trig"], sorted(c["posts"])) for c in got],
                         [(anchors.IX, sid, ["H"], sorted([c1, c2]))])

    def test_one_voice_is_no_burst(self):
        a, b = self.deal(40, self.source), self.deal(39, self.other)
        self.story(a, b)
        self.deal(2, self.third, action="completed")
        self.deal(1.5, self.third, action="closed")
        self.assertEqual(anchors.back_find(self.cur, now=NOW, since=NOW - 60 * DAY), [])

    def test_the_old_trigger_over_a_mark_x_story(self):
        sid, (a, b) = self.old()
        self.cur.execute("DELETE FROM story_posts WHERE story_id = %s", (sid,))
        self.cur.execute("DELETE FROM stories WHERE id = %s", (sid,))
        self.stories.remove(sid)
        mx = self.mx_story(a, b)
        n1, n2 = self.new(2, self.third), self.new(1, self.fourth)
        got = anchors.back_find(self.cur, now=NOW, since=NOW - 60 * DAY)
        self.assertEqual([(c["anchor_kind"], c["story"], c["trig"], c["posts"]) for c in got],
                         [(anchors.MX, mx, ["E"], [n1, n2])])


class Shadow(_Anchors):
    def world(self):
        sid, _ = self.old()                                  # the old engine's back row (E)
        self.new(2, self.third), self.new(1, self.fourth)
        a, b = self.deal(80, self.source), self.deal(79, self.other)
        deal = self.story(a, b)
        return sid, deal

    def test_both_engines_write_their_back_rows_and_the_pages_show_the_old_by_default(self):
        sid, _deal = self.world()
        with self.conn.transaction():
            b = back.stage(self.cur, now=NOW, open_cap=50)
        self.assertEqual((b["added"], b["anchors"]["added"]), (1, 1))
        self.cur.execute("SELECT engine, anchor_kind, story::text, anchor_id::text FROM mx_back ORDER BY engine")
        self.assertEqual(self.cur.fetchall(), [("anchors", anchors.IX, sid, sid), ("old", anchors.IX, sid, sid)])
        self.cur.execute("SELECT count(*) FROM mx_later")
        self.assertEqual(self.cur.fetchone()[0], 0)          # 0203: no Later row from either engine
        self.assertEqual(anchors.shown(self.cur), anchors.OLD)
        status, body = call("POST", "/api/markx/anchors/shown", body={"engine": "anchors"})
        self.assertEqual((status, body), (200, {"engine": "anchors"}))
        self.assertEqual(call("POST", "/api/markx/anchors/shown", body={"engine": "x"})[0], 400)

    def test_the_comparison(self):
        self.world()
        with self.conn.transaction():
            back.stage(self.cur, now=NOW, open_cap=0)
        got = anchors.compare(self.cur, "back")
        self.assertEqual({k: got["counts"][k] for k in ("old", "new", "only_old", "only_new", "both")},
                         {"old": 1, "new": 1, "only_old": 0, "only_new": 0, "both": 1})
        status, got = call("GET", "/api/markx/anchors/compare", query={"which": "back"})
        self.assertEqual(status, 200, got)
        self.assertEqual(call("GET", "/api/markx/anchors/compare", query={"which": "later"})[0], 400)   # 0203

    def test_an_error_in_the_anchors_engine_leaves_the_old_rows(self):
        self.world()
        with mock.patch.object(anchors, "back_find", side_effect=RuntimeError("boom")), self.conn.transaction():
            b = back.stage(self.cur, now=NOW, open_cap=0)
        self.assertEqual((b["added"], b["anchors"]), (1, {"error": "boom"}))
        self.cur.execute("SELECT engine FROM mx_back")
        self.assertEqual([r[0] for r in self.cur.fetchall()], ["old"])
        self.assertIsNone(repo.get_setting(self.cur, anchors.BACK_SINCE_KEY))   # its clock not moved: read again

    def test_a_concurrent_update_still_defers_the_stage(self):
        self.world()
        with mock.patch.object(anchors, "back_find", side_effect=psycopg_errors.SerializationFailure("raced")):
            with self.assertRaises(psycopg_errors.SerializationFailure), self.conn.transaction():
                back.stage(self.cur, now=NOW, open_cap=0)

    def test_off(self):
        self.world()
        repo.set_setting(self.cur, anchors.SHADOW_KEY, False)
        with self.conn.transaction():
            self.assertEqual(back.stage(self.cur, now=NOW, open_cap=0)["anchors"], {"off": True})

    def test_off_by_default(self):
        """v10.17 (0190): with no setting the anchors engine does not run (0180: 20% against an 85% bar)."""
        self.world()
        self.cur.execute("DELETE FROM mx_settings WHERE key = %s", (anchors.SHADOW_KEY,))
        self.assertFalse(anchors.shadow_on(self.cur))
        with self.conn.transaction():
            self.assertEqual(back.stage(self.cur, now=NOW, open_cap=0)["anchors"], {"off": True})


class TheMigration(_Anchors):
    def test_old_rows_read_as_mark_ix_stories_and_each_engine_has_its_own_row(self):
        sid, (a, b) = self.old()
        self.cur.execute("""INSERT INTO mx_back (story, members, first_at, last_at, window_at, trig, posts)
                            VALUES (%s, %s::uuid[], now(), now(), %s, '{E}', %s::uuid[]) RETURNING engine, anchor_kind,
                                   anchor_id""", (sid, [a, b], NOW, [a]))
        self.assertEqual(self.cur.fetchone(), ("old", "ix_story", None))
        self.cur.execute("""INSERT INTO mx_back (story, members, first_at, last_at, window_at, trig, posts, engine)
                            VALUES (%s, %s::uuid[], now(), now(), %s, '{E}', %s::uuid[], 'anchors')""",
                         (sid, [a, b], NOW, [a]))
        with self.assertRaises(psycopg_errors.UniqueViolation), self.conn.transaction():
            self.cur.execute("""INSERT INTO mx_back (story, members, first_at, last_at, window_at, trig, posts)
                                VALUES (%s, %s::uuid[], now(), now(), %s, '{E}', %s::uuid[])""", (sid, [a, b], NOW, [a]))
        with self.assertRaises(psycopg_errors.CheckViolation), self.conn.transaction():
            self.cur.execute("""INSERT INTO mx_later (story, post, members, trig, post_at, last_at, anchor_kind)
                                VALUES (%s, %s, %s::uuid[], '{E}', now(), now(), 'topic')""", (sid, a, [a, b]))
        got = anchors.compare(self.cur, "back")
        self.assertEqual(got["counts"]["both"], 1)            # the old row's anchor is its story


if __name__ == "__main__":
    unittest.main()
