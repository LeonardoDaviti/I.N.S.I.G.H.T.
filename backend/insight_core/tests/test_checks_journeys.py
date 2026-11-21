"""The journeys step of the real-data check (issue 0250 #5), with invented names: the hard set is chosen by its rule
(a bare name three invented companies state), the walks check each page against the one before, a namesake's post is
a wrong row in the breakage format before the split and none after it, and the report shows both versions."""
from __future__ import annotations

import unittest
from unittest import mock

from insight_core.checks import journeys as J
from insight_core.markx import entity_views as EV, identity as I, names as N, repo
from insight_core.tests import test_markx_entities as base
from insight_core.tests import test_markx_shared_names as sn
from insight_core.tests import test_markx_timeline as tl

T0, H, D = base.T0, base.H, base.D
HARD = [{"id": "three-makers", "from": "shared_names", "makers_at_least": 3, "mentions_each": 2}]


@base.requires_test_db
class Journeys(tl._Db):
    say, pairs = sn.Split.say, sn.Split.pairs

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
            self.stage()                                     # v10.28: each maker pair asked, never split alone
            self.assertEqual(sn.Split.answer_pairs(self, lambda a, b: "different"), 3)
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
        default, = J.load_hard("/nonexistent/journeys.json")
        self.assertEqual(default["from"], "shared_names")
        self.assertIsNone(default.get("top"))                # v10.28: every shared bare name, not a top few


class VersionStrings(unittest.TestCase):
    """v10.30 (0259): what a stated version can be that is not one, and the settings a variant can be (invented names)."""

    def test_a_ratio_is_no_version(self):
        self.assertTrue(N.not_a_version("5:1"))
        self.assertFalse(N.not_a_version("5.1"))
        self.assertIsNone(N.clean({"version": "5:1", "variant": None}, "Nimbus 5:1")["version"])
        self.assertIsNone(N.fields_key(N.clean({"family": "nimbus", "version": "16:9"}))[1])

    def test_a_model_id_is_one_version_when_its_family_states_it(self):
        f = {"family": "nimbus", "version": "5", "variant": "1"}
        self.assertEqual(N.clean(f, "kestrel-nimbus-5-1", {N.vt("5"), N.vt("5.1")})["version"], "5.1")
        self.assertIsNone(N.clean(f, "kestrel-nimbus-5-1", {N.vt("5.1")})["variant"])
        self.assertEqual(N.clean(f, "kestrel-nimbus-5-1"), f)                        # no family stating 5.1: as given
        self.assertEqual(N.clean(f, "kestrel-nimbus-5-1", {N.vt("5")}), f)
        self.assertEqual(N.clean(f, "Nimbus 5 1", {N.vt("5.1")}), f)                 # not written as an id
        self.assertIs(N.clean(f, "Nimbus 5"), f)

    def test_settings_are_plain_effort_words_or_bracketed(self):
        self.assertTrue(N.setting("low", "Nimbus 5 low", "model"))
        self.assertTrue(N.setting("xhigh", "Nimbus-5.2-xhigh", "model"))
        self.assertTrue(N.setting("max", "Nimbus 5.2 (max)", "model"))
        self.assertTrue(N.setting("Ultra Max", "Nimbus 5.2 [Ultra Max]", "model"))
        self.assertFalse(N.setting("Max", "Nimbus 5 Max", "model"))                 # a tier as often: left a row
        self.assertFalse(N.setting("Ultra", "Vexa 9 Ultra", "product"))
        self.assertFalse(N.setting("high", "Lumo 3 high", "product"))               # a model's setting only
        self.assertFalse(N.setting("pro", "Nimbus 5 (pro)", "model"))

    def test_the_family_page_lists_settings_under_their_version(self):
        def ent(eid, name, level, version, variant=None):
            return I.Ent(eid, "model", name, N.key(name), level, "f", None, "nimbus", version, N.vt(version), variant)
        ents = [ent("a", "Nimbus 5.2", "version", "5.2"), ent("b", "Nimbus 5.2 (max)", "variant", "5.2", "max"),
                ent("c", "Nimbus 5:1", "version", "5:1"), ent("d", "kestrel-nimbus-5-2", "variant", "5", "2"),
                ent("e", "Nimbus 6 (max)", "variant", "6", "max"), ent("g", "Nimbus 5 Max", "variant", "5", "Max")]
        book = I.Book()
        for e in ents:
            book.ents[e.id] = e
        rows = [{"id": e.id, "name": e.name, "version": e.version, "variant": e.variant, "level": e.level} for e in ents]
        got = EV.family_versions(book, rows)
        self.assertEqual([v["id"] for v in got], ["a", "d", "e", "g"])             # the ratio left out
        self.assertEqual(got[0]["settings"], [{"id": "b", "name": "Nimbus 5.2 (max)", "variant": "max"}])
        self.assertEqual((got[1]["version"], got[1]["variant"]), ("5.2", None))    # the id's numbers: one version
        self.assertNotIn("settings", got[2])                                        # 6 not listed: its setting a row


@base.requires_test_db
class FamilyVersions(tl._Db):
    """v10.30 (0259): the `family_versions` walk over a family page: another maker's thing among the versions and a
    setting listed as a version are wrong rows in the breakage format; the ratio is no longer listed, the bracketed
    setting is listed under its version."""

    def test_each_kind_is_a_wrong_row_and_a_clean_version_is_right(self):
        V = lambda v, var=None: {"family": "Nimbus", "version": v, "variant": var}   # noqa: E731
        p = self.post_at(0, T0 - 9 * D, "Kestrel ships Nimbus")
        self.mentions(p, ("Nimbus 5", "model", "subject", "Kestrel", V("5")),
                      ("Nimbus 5.1", "model", "subject", "Kestrel", V("5.1")),
                      ("Nimbus 5:1", "model", "mention", "Kestrel", V("5:1")),
                      ("Nimbus 5 Max", "model", "mention", "Kestrel", V("5", "Max")),
                      ("Nimbus 5.1 (max)", "model", "mention", "Kestrel", V("5.1", "max")),
                      ("Nimbus 2", "model", "mention", None, V("2")))
        with mock.patch.object(I, "families_on", lambda: {**sn.ON, "split": False}):
            self.stage()
            q = self.post_at(1, T0 - 2 * D, "Lumora's Nimbus 2 is back")
            self.mentions(q, ("Nimbus 2", "model", "subject", "Lumora", V("2")), ("Lumora", "org", "actor"))
            r = self.post_at(2, T0 - D, "Lumora Nimbus 2 review")
            self.mentions(r, ("Nimbus 2", "model", "subject", "Lumora", V("2")))
            self.stage()
        fam = self.ent_named("Nimbus")
        hard = [{"id": "nimbus-like", "from": "family_versions", "family_name_like": "nimbus", "why": "test"}]
        got = J.run(self.cur, T0 + 2 * D, hard=hard, random_stories_n=0, random_things_n=0)
        rows = [r for r in got["rows"] if r["step"] == "family_versions"]
        self.assertEqual(sorted(r["cause"] for r in rows),
                         ["a setting counted as a version", "another maker's thing among the family's versions"])
        bad = next(r for r in rows if r["cause"].startswith("another maker"))
        self.assertEqual((bad["entity"], bad["label"], bad["fix"]), (fam, "wrong", J.FIX["family_versions"]))
        self.assertIn("Lumora", bad["returned"])
        self.assertIn("kestrel", bad["said"].lower())
        found = next(f for f in got["found"] if f["name"] == "journeys.family_versions.hard")
        self.assertEqual((found["count"], found["of"]), (2, 4))      # 5, 5.1 (its setting under it), 5 Max, 2
        page = EV.entity_page(self.cur, fam, now=T0 + 2 * D)
        self.assertNotIn("Nimbus 5:1", [v["name"] for v in page["versions"]])
        v51 = next(v for v in page["versions"] if v["name"] == "Nimbus 5.1")
        self.assertEqual([s["name"] for s in v51["settings"]], ["Nimbus 5.1 (max)"])
        self.assertIn("family_versions, hard", "\n".join(J.lines(None, got, ("main", "branch"))))

    def test_a_family_versions_entry_without_a_pattern_walks_nothing(self):
        got = J.run(self.cur, T0, hard=[{"id": "x", "from": "family_versions"}], random_stories_n=0, random_things_n=0)
        self.assertEqual(next(f for f in got["found"] if f["name"] == "journeys.family_versions.hard")["of"], 0)


if __name__ == "__main__":
    unittest.main()
