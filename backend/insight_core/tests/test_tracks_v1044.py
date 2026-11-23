"""v10.44 tracks: a hidden post (posts.filtered_by) leaves every track view (placements, sections, counts, kept pages,
things); a row keyed on several fields is one thing only where they all agree (one model on two machines is two rows:
the report's join, the entity join and the repair); and a things answer reads the track's roots and reports once.
Synthetic data only; DB tests on _test only."""
from __future__ import annotations

import unittest

from insight_core.markx import track_brief as TB, track_kept, track_things as TT, tracks
from insight_core.tests.test_track_briefer_0245 import _Briefer, v

LOCAL = {"kind": "local_setup", "about": "one model run on one machine", "fields": [
    {"name": "setup_name", "type": "text", "key": True}, {"name": "hardware", "type": "text", "key": True},
    {"name": "speed", "type": "number", "unit": "tok/s"}, {"name": "link", "type": "link"}]}


def ident(name, hardware=None):
    vals = {"setup_name": {"value": name}, **({"hardware": {"value": hardware}} if hardware else {})}
    return TT.name_of(LOCAL, vals), TT.other_keys(LOCAL, vals)


class Keys(unittest.TestCase):
    def same(self, a, b, links=frozenset()):
        (an, ak), (bn, bk) = a, b
        return TT.same_identity(an, set(links), bn, set(links), set(), ak, bk)

    def test_one_model_on_two_machines_is_two_things(self):
        model = "Zqwen3.6-35B-A3B"
        self.assertFalse(self.same(ident(model, "RTX 3060 12GB"), ident(model, "Machine with 23GB RAM")))
        self.assertFalse(self.same(ident(model, "5070 ti + 3070"), ident(model, "RTX PRO 4000 Blackwell SFF")))
        self.assertFalse(self.same(ident(model, "RTX 5060 Ti 16GB"), ident(model, "MacBook Air 16GB")),
                         "a shared memory size alone is not one machine")

    def test_the_same_machine_written_two_ways_agrees(self):
        model = "Zqwen3.6-35B-A3B"
        self.assertTrue(self.same(ident(model, "5090 GPU"), ident(model, "RTX 5090")))
        self.assertTrue(self.same(ident(model, "DGX Spark"), ident(model, "DGX Spark (one or two units)")))
        self.assertTrue(self.same(ident(model, "Mac Studio M2 Ultra"), ident(model, "mac-studio M2 Ultra")))
        self.assertTrue(self.same(ident(model), ident(model, "RTX 3090")), "a key one leaves out never disagrees")
        self.assertFalse(self.same(ident("Zqm one"), ident("Zqm two")), "names still decide first")

    def test_a_kind_with_one_key_is_unchanged(self):
        kind = {"kind": "print", "fields": [{"name": "what", "type": "text", "key": True},
                                            {"name": "files", "type": "link", "key": True},
                                            {"name": "material", "type": "enum", "key": True, "values": ["pla"]}]}
        self.assertEqual(TT.other_keys(kind, {"what": {"value": "fan guard"}, "files": {"value": "https://x.y/z"},
                                              "material": {"value": "pla"}}), {},
                         "links and choices are not text keys")


class Rows(_Briefer):
    def local_track(self):
        f = self.track("setups")
        with self.conn.transaction():
            TT._put_schema(self.cur, f, TT.with_practice({"kinds": [LOCAL]}), by="owner", track_version=1)
        return f

    def test_reports_of_one_model_on_two_machines_make_two_rows(self):
        f = self.local_track()
        model = "Zqwen3.6-35B-A3B"
        a = self.in_track(f, "On a 3060", f"{model} on an RTX 3060 12GB at 40 tok/s.")
        b = self.in_track(f, "On 23GB", f"{model} runs on a machine with 23GB RAM.")
        c = self.in_track(f, "Again on a 3060", f"{model} again, RTX 3060 at 42 tok/s.")
        self.run_planner("track_things")
        self.things(f, a, {"kind": "local_setup", "fields": {"setup_name": v(model, model),
                                                            "hardware": v("RTX 3060 12GB", "RTX 3060 12GB")}})
        self.things(f, b, {"kind": "local_setup", "fields": {"setup_name": v(model, model),
                                                            "hardware": v("Machine with 23GB RAM", "23GB RAM")}})
        self.things(f, c, {"kind": "local_setup", "fields": {"setup_name": v(model, model),
                                                            "hardware": v("RTX 3060", "RTX 3060")}})
        rows = TT.current(self.cur, f, "local_setup")
        self.assertEqual(len(rows), 2, "one row a machine")
        rs = TT.reports(self.cur, f)
        posts = sorted(sorted(r["post"] for r in rs[t["id"]]) for t in rows)
        self.assertEqual(posts, sorted([sorted([a, c]), [b]]))

    def test_the_repair_splits_a_row_that_holds_one_model_on_many_machines(self):
        f = self.local_track()
        model = "Zqwen3.6-35B-A3B"
        machines = ("RTX 3060 12GB", "Machine with 23GB RAM", "RTX 3060", "Zqtower 5070 ti")
        posts = [self.in_track(f, f"Box {n}", f"{model} on {m}.") for n, m in enumerate(machines)]
        self.run_planner("track_things")
        for p, m in zip(posts, machines):
            self.things(f, p, {"kind": "local_setup", "fields": {"setup_name": v(model, model),
                                                                "hardware": v(m, m)}})
        rows = TT.current(self.cur, f, "local_setup")
        self.assertEqual(len(rows), 3)
        # the v10.41 row: every report joined to the first row by the name alone
        head = min(rows, key=lambda t: t["found_at"])["id"]
        self.cur.execute("UPDATE mx_track_thing_reports SET thing_id = %s WHERE post_id = ANY(%s::uuid[])",
                         (head, posts))
        self.cur.execute("UPDATE mx_track_things SET status = 'merged', merged_into = %s WHERE id <> %s AND track_id = %s"
                         " AND kind = 'local_setup'", (head, head, f))
        with self.conn.transaction():
            got = TT.repair(self.cur, f, dry_run=False, ask=False)
        self.assertEqual(len(got["splits"]), 1)
        rows = TT.current(self.cur, f, "local_setup")
        self.assertEqual(len(rows), 3, "a row a machine again (the two 3060s one)")
        self.cur.execute("SELECT count(*) FROM mx_track_thing_reports WHERE post_id = ANY(%s::uuid[])", (posts,))
        self.assertEqual(self.cur.fetchone()[0], 4, "every report kept")

    def test_a_hidden_post_leaves_the_track_and_its_things(self):
        f = self.local_track()
        keep = self.in_track(f, "A real setup", "Zqbox 9 runs at 30 tok/s.")
        tag = self.in_track(f, "Tag: zqbox", "Posts tagged zqbox: Zqbox 9 runs at 30 tok/s, more.")
        self.run_planner("track_things")
        self.things(f, keep, {"kind": "local_setup", "fields": {"setup_name": v("Zqbox 9", "Zqbox 9")}})
        self.things(f, tag, {"kind": "local_setup", "fields": {"setup_name": v("Zqbox 9", "Zqbox 9")}},
                    {"kind": "local_setup", "fields": {"setup_name": v("Zqtag only", "zqbox")}})
        with self.conn.transaction():
            track_kept.refresh(self.cur)
        shown = lambda: {it["post_id"] for s in tracks.page(self.cur, f)["sections"] for it in s["items"]}  # noqa: E731
        self.assertEqual(shown(), {keep, tag})
        self.cur.execute("UPDATE posts SET filtered_by = gen_random_uuid() WHERE id = %s", (tag,))
        self.cur.execute("SELECT count(*) FROM mx_track_changes WHERE track_id = %s AND NOT owner", (f,))
        self.assertGreaterEqual(self.cur.fetchone()[0], 1, "hiding a post logs a change of its tracks")
        with self.conn.transaction():
            track_kept.refresh(self.cur, gap=0)
        self.assertEqual(shown(), {keep}, "the kept placement placed again without it")
        self.assertEqual(tracks.page(self.cur, f)["counts"].get("judged"), 1)
        table = TB.table(self.cur, f, "local_setup", {})
        self.assertEqual([[p["id"] for p in t["posts"]] for t in table["things"]], [[keep]],
                         "its reports leave the rows; a row only it reported leaves the table")
