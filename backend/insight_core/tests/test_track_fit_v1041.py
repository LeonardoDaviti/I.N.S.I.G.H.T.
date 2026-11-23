"""Stealth v10.41: track verdicts and Discover. (FIX 4) a verdict must agree with its own stated fit (track-v3,
track-check-v2: `subject`, `fits`, `matches` quoting `Belongs:`, `excluded` quoting `Not:`, then `in`); a contradiction
is no verdict (asked again, then invalid, never counted); the reader's ✓ examples the judge, asked against the
description alone, says do not fit are flagged on the page, never removed; a join an older check guide let in is
checked again. (FIX 7) Discover keeps each week's DISCOVER_PER_WEEK best, the rest is the blind check's (`checking`,
`checked_out`); the Tools panel counts only posts placed in the track. Invented tracks and posts only; the DB tests run
on a database whose name ends in _test."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import repo, schemas, track_tools, tracks, validate
from insight_core.tests.test_markx_tracks import _Tracks, unit, verdict

DAY = timedelta(days=1)
NOW = datetime.now(timezone.utc)
HEAD = ("TRACK: Cool 3D Projects\nBelongs: 3D-printable projects worth making: functional and clever prints, "
        "upgrades and tools for the printer\nNot: Figurines, decorative models, printer ads and deals\n"
        "Marked in by the reader:\n- A kitchen timer with a buzzer")
Q = HEAD + validate.POST_MARK + ("Platform: rss | Source: Example Blog\nTitle: A Django linter that finds slow queries\n"
                                 "Text: We built a linter for Django projects that flags N+1 queries in code review.")


def answer(**kw):
    a = {"id": "x", "subject": "a Django linter", "fits": False, "matches": None, "excluded": None, "in": False,
         "confidence": 0.85, "subtopic": None, "why": "A Django linter for slow queries; software, not a print."}
    return {**a, **kw}


class Fit(unittest.TestCase):
    def check(self, a, guide=None):
        return validate.check("track", a, Q, guide)[1]

    def test_the_guides_and_their_schema(self):
        self.assertEqual(schemas.KINDS["track"].guide, "track-v3")
        self.assertEqual(tracks.CHECK_GUIDE, "track-check-v2")
        for g in ("track-v3", "track-check-v2"):
            self.assertIn("the verdict follows", schemas.guide_body(g))
            self.assertIs(schemas.schema_for("track", g), schemas.TRACK_SCHEMA_V3)
        self.assertIs(schemas.schema_for("track", "track-v2"), schemas.TRACK_SCHEMA)   # its open questions still answered

    def test_an_out_that_says_it_does_not_fit_is_a_verdict(self):
        self.assertIsNone(self.check(answer()))

    def test_an_in_whose_fit_is_false_is_no_verdict(self):
        """87a9fdda's kind: `in` at 0.9 with "nothing to do with printing"."""
        for guide in (None, tracks.CHECK_GUIDE):
            err = self.check(answer(**{"in": True, "subtopic": "tools"}), guide)
            self.assertIn("fits is false", err)

    def test_an_in_needs_a_quote_of_belongs(self):
        ok = answer(**{"in": True, "fits": True, "matches": "upgrades and tools for the printer", "subtopic": "tools",
                       "why": "A Django linter for slow queries, a printer tool."})
        self.assertIsNone(self.check(ok))
        self.assertIn("copy the words", self.check(dict(ok, matches=None)))
        self.assertIn("its own words", self.check(dict(ok, matches="clever software tools")),
                      "a quote must be the description's words, not the post's")
        self.assertIn("its own words", self.check(dict(ok, matches="kitchen timer")),
                      "an example's words are not the description's")
        self.assertIn("null when fits is false", self.check(answer(matches="functional prints")))

    def test_excluded_is_out_and_quotes_not(self):
        fig = answer(**{"fits": True, "matches": "clever prints", "excluded": "decorative models", "in": True,
                        "subtopic": "x"})
        self.assertIn("Not:", self.check(fig))
        self.assertIsNone(self.check(dict(fig, **{"in": False, "subtopic": None})))
        self.assertIn("its own words", self.check(dict(fig, **{"in": False, "excluded": "Django linters"})))
        no_not = Q.replace("\nNot: Figurines, decorative models, printer ads and deals", "")
        self.assertIn("no `Not:`", validate.check("track", dict(fig, **{"in": False}), no_not)[1])

    def test_the_header_parts(self):
        self.assertEqual(validate.header_part(Q, "Not: "), "Figurines, decorative models, printer ads and deals")
        self.assertTrue(validate.header_part(Q, "Belongs: ").endswith("for the printer"))
        self.assertIsNone(validate.header_part("q", "Belongs: "))


class Lane(unittest.TestCase):
    def item(self, pid, conf, at, check_in=None):
        return {"post_id": pid, "confidence": conf, "at": at, "place": "discover", "check_in": check_in}

    def test_each_weeks_best_stay_the_rest_is_the_checks(self):
        monday = datetime(2026, 11, 16, 9, tzinfo=timezone.utc)
        week = [self.item(f"w{k}", 0.6 + k / 100, monday + timedelta(hours=k)) for k in range(30)]
        last = [self.item(f"l{k}", 0.9, monday - timedelta(days=3, hours=k)) for k in range(3)]
        out = self.item("x", 0.99, monday, check_in=False)
        old = self.item("o", 0.99, monday - timedelta(weeks=4))
        items = week + last + [out, old]
        with mock.patch.object(tracks, "DISCOVER_PER_WEEK", 25), mock.patch.object(tracks, "DISCOVER_WEEKS", 4):
            tracks.review_lane(items, tracks.calibrate([]), now=monday + timedelta(days=2))
        places = {it["post_id"]: it["place"] for it in items}
        self.assertEqual(places["x"], "checked_out", "the check's out leaves Discover")
        self.assertEqual(sorted(p for p, pl in places.items() if pl == "checking"), ["o"] + [f"w{k}" for k in range(5)],
                         "the week's 5 least sure wait for the check, and a week older than the last 4")
        self.assertTrue(all(places[f"l{k}"] == "discover" for k in range(3)), "last week has its own lane")

    def test_with_the_checks_off_discover_is_as_before(self):
        items = [self.item(f"w{k}", 0.7, NOW) for k in range(40)] + [self.item("x", 0.7, NOW, check_in=False)]
        with mock.patch.object(tracks, "checks_on", return_value=False):
            tracks.review_lane(items, tracks.calibrate([]))
        self.assertEqual({it["place"] for it in items}, {"discover"})

    def test_weeks_start_on_monday_utc(self):
        self.assertEqual(tracks.week_of(datetime(2026, 11, 22, 23, tzinfo=timezone.utc)),
                         datetime(2026, 11, 16, tzinfo=timezone.utc).timestamp())
        self.assertEqual(tracks.week_of(datetime(2026, 11, 23, 0, 1, tzinfo=timezone.utc)),
                         datetime(2026, 11, 23, tzinfo=timezone.utc).timestamp())

    def test_tools_come_from_the_track_only(self):
        items = [{"post_id": "a", "place": "track"}, {"post_id": "b", "place": "joined"},
                 {"post_id": "c", "place": "discover"}, {"post_id": "d", "place": "checking"}]
        self.assertEqual(track_tools.judged_in(items), ["a", "b"])


class Examples(_Tracks):
    def setUp(self):
        super().setUp()
        self.describe()
        self.desc_vector(unit((0, 1)))

    def example_task(self, post):
        t = tracks.get(self.cur, self.folder)
        posts = tracks.tasks.load_posts(self.cur, [post])
        q = tracks.example_questions(self.cur, t, [post], posts)[post]
        return repo.task_for(self.cur, kind="track", guide=schemas.KINDS["track"].guide, input=q)

    def test_an_example_the_description_does_not_ask_for_is_flagged_never_removed(self):
        timer = self.post(title="An electronics kitchen timer")
        shelf = self.post(title="A printable wall shelf")
        self.label(timer, "in")
        self.label(shelf, "in")
        self.plan()
        a, b = self.example_task(timer), self.example_task(shelf)
        self.assertIsNotNone(a)
        self.assertNotIn("Marked in by the reader", a["input"], "asked against the description alone")
        self.assertEqual(tracks.page(self.cur, self.folder)["examples"]["misleading"], [],
                         "not answered yet: nothing flagged")   # (built live: the route's kept page may lag KEPT_LAG)
        status, body = self.answer((a["id"], verdict(False, 0.8, why="An electronics kitchen timer, not a print.")),
                                   (b["id"], verdict(True, 0.9, why="A printable wall shelf, a useful print.")))
        self.assertEqual((status, body["valid"]), (200, 2), body)
        page = self.page()
        self.assertEqual([e["post_id"] for e in page["examples"]["misleading"]], [timer])
        self.assertIn(timer, [e["post_id"] for e in page["examples"]["in"]], "still the reader's ✓")
        self.assertIn("Marked in by the reader", tracks.header(self.cur, tracks.get(self.cur, self.folder)),
                      "still in the judge's header")
        n = self.plan()
        self.assertEqual(self.example_task(timer)["id"], a["id"], "asked once a description")
        self.assertGreaterEqual(n, 0)


class Recheck(_Tracks):
    def setUp(self):
        super().setUp()
        self.describe()
        self.desc_vector(unit((0, 1)))

    def test_a_join_of_the_old_check_guide_is_checked_again(self):
        p = self.post(title="A WiFi dongle", source=self.other)
        self.vector(p, unit((0, 1), (3, 0.2)))
        self.plan()
        self.judge(p, verdict(conf=0.8))
        self.plan()
        self.cur.execute("SELECT check_task_id FROM mx_track_items WHERE post_id = %s", (p,))
        old = self.cur.fetchone()[0]
        self.cur.execute("UPDATE mx_tasks SET guide = 'track-check-v1', status = 'answered' WHERE id = %s", (old,))
        self.cur.execute("UPDATE mx_track_items SET check_in = true, check_confidence = 0.9 WHERE post_id = %s", (p,))
        place = lambda: {it["post_id"]: it["place"] for it in tracks.placed(self.cur, tracks.get(self.cur, self.folder))["items"]}[p]
        self.assertEqual(place(), "joined")
        self.plan()
        self.cur.execute("SELECT check_task_id FROM mx_track_items WHERE post_id = %s", (p,))
        new = self.cur.fetchone()[0]
        self.assertNotEqual(new, old, "asked again under the current check guide")
        self.assertEqual(place(), "joined", "the old check holds until the new one is settled")
        status, body = self.answer((new, verdict(False, 0.9, why="A WiFi dongle, not a printable item.")))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        self.assertEqual(place(), "checked_out")
        self.plan()
        self.cur.execute("SELECT check_task_id FROM mx_track_items WHERE post_id = %s", (p,))
        self.assertEqual(self.cur.fetchone()[0], new, "checked once under the new guide")


if __name__ == "__main__":
    unittest.main()
