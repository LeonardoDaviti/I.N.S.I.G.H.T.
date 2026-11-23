"""Stealth v10.41: a track's rows, one a thing, dated by publication (the general track briefer, track_things).

  - joins: two reports are one thing only on a strong identity: the same name, or a shared link and names that agree
    (a rare word of the kind's names in both); a shared link alone or another key (the hardware) is not; no chain
    through a weak key;
  - a row's fields: each the value most of its posts give (a tie: the earliest post's), value and quote one post's;
  - the same-thing question covers every kind and a pair one post gave (track-same-v2);
  - the repair: a row that absorbed unrelated reports is split (dry run first), nothing deleted; a catalog post is
    asked again under track-things-v3 and its answer folds its item rows into one;
  - dates: a thing's first and last dates and the quick look's "also" by the post's publication, not by the day a feed
    surfaced it.
Synthetic data only (invented tracks); the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from insight_core.markx import track_brief as TB, track_things as TT
from insight_core.tests.test_track_briefer_0245 import _Briefer, v

SETUP = TT.with_practice({"kinds": [{"kind": "setup", "about": "one machine", "fields": [
    {"name": "name", "type": "text", "key": True}, {"name": "hardware", "type": "text", "key": True},
    {"name": "speed", "type": "number", "unit": "tok/s"}, {"name": "page", "type": "link"}]}]})["kinds"][0]


class Pure(unittest.TestCase):
    def test_a_strong_identity_only(self):
        name = lambda s: TT.name_of(SETUP, {"name": {"value": s}})   # noqa: E731
        self.assertEqual(name("Private spaces"), name("Private Space"), "a plural s folded")
        rare = TT.rare_words([name(n) for n in ("Zq box alpha", "Zq box beta", "Zq box gamma", "Zq box delta",
                                                 "Lockdown Mode", "Screen security", "Zqclip remix", "desk zqclip")])
        self.assertNotIn("box", rare, "a word most names share names no one")
        link = {"link:zq.example/features"}
        self.assertFalse(TT.same_identity(name("Lockdown Mode"), link, name("Screen security"), link, rare),
                         "a shared link alone")
        self.assertFalse(TT.same_identity(name("Zq box alpha"), link, name("Zq box beta"), link, rare),
                         "names agreeing only on a common word")
        self.assertTrue(TT.same_identity(name("desk zqclip"), link, name("Zqclip remix"), link, rare))
        self.assertFalse(TT.same_identity(name("desk zqclip"), set(), name("Zqclip remix"), set(), rare),
                         "names that agree without a shared link are a same-thing question, not a join")
        self.assertTrue(TT.same_identity(name("Lockdown Mode"), set(), name("lockdown-mode"), set(), rare))

    def test_fields_from_the_rows_own_posts(self):
        rs = [{"post": "p1", "values": {"name": v("Zq", "Zq"), "speed": v({"number": 30.0}, "30 tok/s")}},
              {"post": "p2", "values": {"name": v("Zq", "Zq"), "speed": v({"number": 28.0}, "28 tok/s")}},
              {"post": "p3", "values": {"name": v("Zq", "Zq"), "speed": v({"number": 28.0}, "does 28 tok/s")}}]
        got = TT.merged_fields(rs)
        self.assertEqual((got["speed"]["value"], got["speed"]["post"], got["speed"]["quote"]),
                         ({"number": 28.0}, "p2", "28 tok/s"), "most posts' value, its earliest report's quote")
        self.assertEqual(TT.merged_fields(rs[:2])["speed"]["post"], "p1", "a tie: the earliest post")


class Rows(_Briefer):
    def setup_track(self):
        f = self.track("setups")
        self.schema(f, "setups")
        return f

    def test_a_shared_link_or_hardware_does_not_make_one_row(self):
        f = self.setup_track()
        hub = "https://zq.example/models"
        a = self.in_track(f, "Box A", f"Zqbox 9 runs at 30 tok/s. {hub}", links=[(hub, "models")])
        b = self.in_track(f, "Box B", f"A Zqtower 2 does 12 tok/s. {hub}", links=[(hub, "models")])
        c = self.in_track(f, "Box C", "Zqbox 9 again: 31 tok/s.")
        self.run_planner("track_things")
        self.things(f, a, {"kind": "setup", "fields": {"hardware": v("Zqbox 9", "Zqbox 9 runs"),
                                                      "speed": v({"number": 30}, "30 tok/s"), "page": v(hub, hub)}})
        self.things(f, b, {"kind": "setup", "fields": {"hardware": v("Zqtower 2", "A Zqtower 2"),
                                                      "speed": v({"number": 12}, "12 tok/s"), "page": v(hub, hub)}})
        self.things(f, c, {"kind": "setup", "fields": {"hardware": v("Zqbox 9", "Zqbox 9 again"),
                                                      "speed": v({"number": 31}, "31 tok/s")}})
        rows = TT.current(self.cur, f, "setup")
        self.assertEqual(len(rows), 2, "the shared hub link joins nothing; the same name does")
        rs = TT.reports(self.cur, f)
        box = next(t for t in rows if t["fields"]["hardware"]["value"] == "Zqbox 9")
        self.assertEqual({r["post"] for r in rs[box["id"]]}, {a, c})
        self.assertEqual(box["fields"]["speed"]["post"], a, "the earliest post's value on a tie, never b's")

    def test_same_thing_questions_for_every_kind_and_one_posts_pairs(self):
        f = self.setup_track()
        a = self.in_track(f, "Two boxes", "The Zqbox nine runs 30 tok/s; later the Zqbox nine build does 31 tok/s.")
        self.run_planner("track_things")
        self.things(f, a, {"kind": "setup", "fields": {"hardware": v("Zqbox nine", "The Zqbox nine runs")}},
                    {"kind": "setup", "fields": {"hardware": v("Zqbox nine build", "the Zqbox nine build")}})
        self.assertEqual(len(TT.current(self.cur, f, "setup")), 2)
        self.assertEqual(self.run_planner("track_same"), 1, "one post's pair, of a kind not practices")
        (tid, _x, _y, text), = self.open_tasks("track_same", TT.SAME_GUIDE)
        self.assertIn("KIND: setup", text)
        self.assertIn("FROM: one post gave both", text)
        self.assertIn("A: hardware: Zqbox nine", text)
        status, body = self.answer((tid, {"id": "x", "same": True, "why": "One box named twice."}))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        self.assertEqual(len(TT.current(self.cur, f, "setup")), 1)
        self.assertEqual(self.run_planner("track_same"), 0)

    def test_repair_splits_a_row_that_absorbed_others_and_keeps_every_report(self):
        f = self.setup_track()
        hub = "https://zq.example/models"
        posts = [self.in_track(f, f"Box {n}", f"{n} runs at {9 + i} tok/s. {hub}", links=[(hub, "models")])
                 for i, n in enumerate(("Zqbox 9", "Zqtower 2", "Zqbox 9", "Zqmini 4"))]
        self.run_planner("track_things")
        for p, n in zip(posts, ("Zqbox 9", "Zqtower 2", "Zqbox 9", "Zqmini 4")):
            self.things(f, p, {"kind": "setup", "fields": {"hardware": v(n, n), "page": v(hub, hub)}})
        # the pre-v10.41 black hole: every report joined to the first row (as a shared link did)
        rows = TT.current(self.cur, f, "setup")
        self.assertEqual(len(rows), 3)
        hole = min(rows, key=lambda t: t["found_at"])["id"]
        self.cur.execute("UPDATE mx_track_thing_reports SET thing_id = %s WHERE post_id = ANY(%s::uuid[])",
                         (hole, posts))
        other = [t["id"] for t in rows if t["id"] != hole]
        with self.conn.transaction():
            self.cur.execute("""UPDATE mx_track_things SET status = 'merged', merged_into = %s, merged_by = 'key'
                                 WHERE id = ANY(%s::uuid[])""", (hole, other))
            TT.remerge(self.cur, f, hole)
        self.assertEqual(len(TT.current(self.cur, f, "setup")), 1)
        dry = TT.repair(self.cur, f, dry_run=True)
        (sp,) = dry["splits"]
        self.assertEqual((sp["thing"], len(sp["groups"])), (hole, 2))
        self.assertEqual(len(TT.current(self.cur, f, "setup")), 1, "a dry run changes nothing")
        self.cur.execute("SELECT count(*) FROM mx_track_thing_reports")
        before = self.cur.fetchone()[0]
        with self.conn.transaction():
            got = TT.repair(self.cur, f, dry_run=False)
        self.assertTrue(got["done"])
        rows = TT.current(self.cur, f, "setup")
        self.assertEqual(sorted(t["fields"]["hardware"]["value"] for t in rows), ["Zqbox 9", "Zqmini 4", "Zqtower 2"])
        rs = TT.reports(self.cur, f)
        box = next(t for t in rows if t["fields"]["hardware"]["value"] == "Zqbox 9")
        self.assertEqual({r["post"] for r in rs[box["id"]]}, {posts[0], posts[2]})
        self.cur.execute("SELECT count(*), count(moved_from) FROM mx_track_thing_reports")
        self.assertEqual(self.cur.fetchone(), (before, 2), "every report kept; the moved ones say where from")
        self.cur.execute("SELECT count(*) FROM mx_track_things WHERE track_id = %s AND split_from = %s", (f, hole))
        self.assertEqual(self.cur.fetchone()[0], 2)
        self.assertEqual(TT.repair_plan(self.cur, f)["splits"], [], "repaired once")

    def test_a_catalog_post_asked_again_folds_its_item_rows(self):
        f = self.setup_track()
        p = self.in_track(f, "The Zq rack", "The Zq rack: Zqa 1, Zqb 2, Zqc 3, Zqd 4 and Zqe 5, each at 10 tok/s.")
        self.run_planner("track_things")
        (tid, _a, _b, text), = [r for r in self.open_tasks("track_things") if r[1] == p]
        self.cur.execute("UPDATE mx_tasks SET guide = 'track-things-v2' WHERE id = %s", (tid,))   # asked under v2
        self.things(f, p, *[{"kind": "setup", "fields": {"hardware": v(n, n)}}
                            for n in ("Zqa 1", "Zqb 2", "Zqc 3", "Zqd 4", "Zqe 5")])
        self.assertEqual(len(TT.current(self.cur, f, "setup")), 5)
        self.assertEqual(TT.repair_plan(self.cur, f)["catalogs"], [{"post": p, "kind": "setup", "rows": 5}])
        with self.conn.transaction():
            got = TT.repair(self.cur, f, dry_run=False)
        self.assertEqual(got["asked"], 1)
        (tid2, _a, _b, text2), = [r for r in self.open_tasks("track_things", TT.THINGS_GUIDE) if r[1] == p]
        self.assertEqual(text2, text)
        self.things(f, p, {"kind": "setup", "fields": {"hardware": v("The Zq rack", "The Zq rack")}})
        (row,) = TT.current(self.cur, f, "setup")
        self.assertEqual(row["fields"]["hardware"]["value"], "The Zq rack")
        self.cur.execute("SELECT count(*), count(*) FILTER (WHERE merged_by = 'haiku') FROM mx_track_things "
                         "WHERE track_id = %s AND status = 'merged'", (f,))
        self.assertEqual(self.cur.fetchone(), (5, 5), "the item rows folded, none deleted")

    def test_dates_are_the_posts_publication(self):
        f = self.track("recipes")
        self.schema(f, "recipes")
        now = datetime.now(timezone.utc)
        old = self.in_track(f, "Old soup", "Zq soup in 20 minutes.", at=datetime(2017, 3, 1, tzinfo=timezone.utc))
        chat = self.in_track(f, "Old chat", "What do you cook?", at=datetime(2016, 1, 2, tzinfo=timezone.utc))
        self.cur.execute("UPDATE posts SET surfaced_at = %s WHERE id = ANY(%s::uuid[])", (now, [old, chat]))
        self.run_planner("track_things")
        self.things(f, old, {"kind": "recipe", "fields": {"dish": v("zq soup", "Zq soup")}})
        self.things(f, chat)
        (row,) = TT.current(self.cur, f, "recipe")
        self.assertEqual((row["first_at"].year, row["last_at"].year), (2017, 2017), "published, not surfaced")
        look = TB.quick_look(self.cur, f, now - timedelta(days=1), now=now)
        self.assertEqual(look["counts"], {"things": 0, "also": 0}, "a 2016 post surfaced today is not new")


if __name__ == "__main__":
    unittest.main()
