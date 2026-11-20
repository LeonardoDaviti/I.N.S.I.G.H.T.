"""The journeys step of the real-data check (issue 0250 #5), with invented names: the hard set is chosen by its rule
(a bare name three invented companies state), the walks check each page against the one before, a namesake's post is
a wrong row in the breakage format before the split and none after it, and the report shows both versions."""
from __future__ import annotations

import unittest
from unittest import mock

from insight_core.checks import journeys as J
from insight_core.markx import identity as I, repo
from insight_core.tests import test_markx_entities as base
from insight_core.tests import test_markx_shared_names as sn
from insight_core.tests import test_markx_timeline as tl

T0, H, D = base.T0, base.H, base.D
HARD = [{"id": "three-makers", "from": "shared_names", "makers_at_least": 3, "mentions_each": 2}]


@base.requires_test_db
class Journeys(tl._Db):
    say = sn.Split.say

    def fixture(self):
        posts = {m: [self.say(k, m, T0 - (20 - 4 * k - j) * D) for k in range(n)]
                 for j, (m, n) in enumerate([("Kestrel", 3), ("Lumora", 2), ("Brightwell", 2)])}
        run = repo.start_run(self.cur, code_version="test", config={})
        sid = str(repo.add_story(self.cur, first_at=T0 - 20 * D, run_id=run))
        for p in posts["Kestrel"] + posts["Lumora"][:1]:
            repo.open_membership(self.cur, story_id=sid, post_id=p, role="member", reason="test", run_id=run)
        return posts, sid

    def walk(self):
        return J.run(self.cur, T0 + 2 * D, hard=HARD, random_stories_n=0, random_things_n=0)

    def found(self, got, name):
        return next(f for f in got["found"] if f["name"] == name)

    def test_the_hard_set_comes_from_its_rule_and_a_namesake_is_a_wrong_row_until_the_split(self):
        posts, sid = self.fixture()
        with mock.patch.object(I, "families_on", lambda: {**sn.ON, "split": False}):
            self.stage()
        got = self.walk()
        names = got["sets"]["hard"][0]["names"]
        self.assertEqual([(x["key"], sorted(x["makers"])) for x in names], [("vexa", ["brightwell", "kestrel", "lumora"])])
        self.assertEqual(self.found(got, "journeys.story_things.hard")["count"], 0)       # its subject one click away
        wrong = [r for r in got["rows"] if r["step"] == "story_makers"]
        self.assertTrue(wrong)
        r = wrong[0]
        self.assertEqual((r["story"], r["post"], r["label"]), (sid, posts["Lumora"][0], "wrong"))
        self.assertEqual(r["returned"], "Vexa by Kestrel")
        self.assertIn("by Lumora", r["said"])
        self.assertEqual(r["fix"], J.FIX["story_makers"])
        report = "\n".join(J.lines(None, got, ("main", "branch")))
        self.assertIn("story_makers, hard", report)
        self.assertIn(posts["Lumora"][0], report)
        with mock.patch.object(I, "families_on", lambda: dict(sn.ON)):
            self.stage()
        after = self.walk()
        self.assertEqual(self.found(after, "journeys.story_makers.hard")["count"], 0)
        self.assertEqual(self.found(after, "journeys.story_things.hard")["count"], 0)
        self.assertGreater(self.found(after, "journeys.story_makers.hard")["of"], 0)
        self.assertEqual(len(after["sets"]["hard"][0]["names"][0]["makers"]), 3)          # the same name walked

    def test_a_shared_names_rule_counts_one_companys_aliases_once(self):
        for k, maker in enumerate(["Kestrel", "Kestrel", "Kestrel Labs", "Kestrel Labs", "Lumora", "Lumora"]):
            self.say(k, maker, T0 - (10 - k) * D)
        with mock.patch.object(I, "families_on", lambda: {**sn.ON, "split": False}):
            self.stage()
        copy = J.Copy(self.cur, T0)
        self.assertEqual(J.shared_names(self.cur, copy, makers_at_least=3), [])
        self.assertEqual([sorted(x["makers"]) for x in J.shared_names(self.cur, copy, makers_at_least=2)],
                         [["kestrel", "lumora"]])

    def test_the_hard_set_file_is_read_and_a_missing_one_is_the_rules_default(self):
        self.assertEqual(J.load_hard("/nonexistent/journeys.json")[0]["from"], "shared_names")


if __name__ == "__main__":
    unittest.main()
