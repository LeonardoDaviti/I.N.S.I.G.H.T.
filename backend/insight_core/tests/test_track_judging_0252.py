"""Issue 0252 (Stealth v10.28): track judging gaps. (1) a post from a source tied to the track, or linked by 2+ of
the track's sources, is always asked, whatever its probe score (finders' ALWAYS finders); (2) a `track` answer that is
no verdict (confidence 0, or a why naming nothing of the post) fails validation, is asked once more, then stays
invalid, never "out"; (3) a guide change asks the old guide's verdicts of the last REASK_DAYS once more, newest first,
a cap a day, the old answers kept; (4) Discover is newest first within confidence bands; (5) a post is judged per
track. Invented tracks and posts only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import finders, repo, schemas, tasks, track_why, tracks, validate
from insight_core.tests._db import insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import call
from insight_core.tests.test_markx_tracks import _Tracks, unit, verdict

DAY = timedelta(days=1)
NOW = datetime.now(timezone.utc)
FAR = unit((50, 1))           # a vector far from the description's: no probe fires
NEAR = unit((0, 1), (3, 0.2))


def question(title, text, track="TRACK: Agent tooling\nBelongs: tools and methods practitioners use with AI agents"):
    """A track question as tracks.track_input writes it."""
    return (track + validate.POST_MARK + f"Platform: rss | Source: Example Blog\nTitle: {title}\nText: {text}")


class Verdicts(unittest.TestCase):
    """(2) what a verdict is: the guide's `confidence` (how sure) and `why` (what the post is)."""
    Q = question("Wiring harness adapters into a coding agent",
                 "We describe how our adapters translate tool calls between the planner and the sandbox, with tests.")

    def check(self, answer, q=None):
        fit = {"subject": "the post", "fits": answer["in"], "matches": "tools and methods" if answer["in"] else None,
               "excluded": None}   # v10.41 (track-v3): a stated fit that agrees with `in`
        return validate.check("track", dict({"id": "x", "subtopic": None}, **fit, **answer),
                              self.Q if q is None else q)[1]

    def test_a_why_that_names_the_post_is_a_verdict(self):
        self.assertIsNone(self.check({"in": True, "confidence": 0.8, "why": "Harness adapters for tool calls, with tests."}))
        self.assertIsNone(self.check({"in": False, "confidence": 0.3, "why": "A sandbox write-up, too thin on methods."}))

    def test_confidence_zero_judges_nothing(self):
        self.assertIn("confidence", self.check({"in": False, "confidence": 0.0,
                                                "why": "Harness adapters for tool calls."}))

    def test_a_generic_why_names_nothing_of_the_post(self):
        for why in ("Not applicable to this track.", "Does not fit the track.", "Out: not about AI agents tools.",
                    "The post is not relevant to what the reader asks for."):
            self.assertIn("names nothing", self.check({"in": False, "confidence": 0.4, "why": why}), why)

    def test_the_source_line_is_not_the_posts_content(self):
        self.assertIn("names nothing", self.check({"in": False, "confidence": 0.4, "why": "An Example Blog post."}))

    def test_no_post_or_another_script_checks_the_confidence_only(self):
        self.assertIsNone(self.check({"in": False, "confidence": 0.4, "why": "Not applicable."}, q="q"))
        q = question("Агенты и инструменты", "Мы описываем адаптеры между планировщиком и песочницей, с тестами.")
        self.assertIsNone(self.check({"in": True, "confidence": 0.7, "why": "Adapters between planner and sandbox."}, q))
        self.assertIn("confidence", self.check({"in": False, "confidence": 0, "why": "Not applicable."}, q))

    def test_one_retry_for_a_track_question(self):
        self.assertEqual(repo.max_attempts("track"), 2)
        self.assertEqual(repo.max_attempts("read"), repo.MAX_ATTEMPTS)

    def test_the_new_finders_and_the_discover_order(self):
        self.assertEqual(finders.ALWAYS, ("source", "linked"))
        self.assertTrue(set(finders.ALWAYS) <= set(finders.ADOPTED))
        self.assertEqual(finders.fire({"probe": 0.1, "tied": True, "linkers": 2}, {"bar": 0.5}), ["source", "linked"])
        self.assertEqual(finders.fire({"probe": 0.1, "linkers": 1}, {"bar": 0.5}), [])
        a = {"fired": ["source"], "probe": None}
        b = {"fired": ["probe", "domain", "word"], "probe": 0.9}
        self.assertEqual(sorted([b, a], key=finders.order_key, reverse=True), [a, b])   # always first
        cal = tracks.calibrate([])
        old95 = {"post_id": "a", "confidence": 0.95, "at": NOW - 300 * DAY}
        new80 = {"post_id": "b", "confidence": 0.8, "at": NOW}
        new70 = {"post_id": "c", "confidence": 0.7, "at": NOW}
        self.assertEqual([it["post_id"] for it in sorted([old95, new70, new80], key=tracks.discover_order(cal))],
                         ["b", "c", "a"], "v10.41: by week first, then by band within the week")


@requires_test_db
class _Judging(_Tracks):
    def setUp(self):
        super().setUp()
        self.describe("Tools and methods practitioners use or build to work with AI agents")
        self.desc_vector(unit((0, 1)))

    def why(self, post, folder=None):
        status, body = call("GET", f"/api/markx/tracks/{folder or self.folder}/why", query={"post": post})
        self.assertEqual(status, 200, body)
        return body

    def row(self, post, folder=None):
        self.cur.execute("""SELECT i.verdict, i.confidence, i.why, i.found_by, i.task_id::text, i.asked_before,
                                   k.status, k.guide
                              FROM mx_track_items i JOIN mx_tasks k ON k.id = i.task_id
                             WHERE i.track_id = %s AND i.post_id = %s""", (folder or self.folder, post))
        r = self.cur.fetchone()
        return None if r is None else dict(zip(("verdict", "confidence", "why", "found_by", "task", "asked_before",
                                                 "status", "guide"), r))


class AlwaysAsked(_Judging):
    """(1) the finders gate no post of a tied source, nor one the track's sources link."""

    def tie_third(self):
        """The third source made a tied one: 3 of its 4 posts of the month judged in (the suggestion's share)."""
        ps = []
        for k in range(3):
            p = self.post(title=f"Agent harness note {k}", source=self.third)
            self.vector(p, NEAR)
            ps.append(p)
        self.post(title="A holiday photo", source=self.third)   # no vector: never asked before 0252
        self.plan()
        for p in ps:
            self.judge(p, verdict(conf=0.9, why="An agent harness note."))
        self.assertIn(self.third, [s["source_id"] for s in tracks.suggestions(self.cur, self.folder)])

    def test_a_tied_sources_post_is_asked_whatever_its_probe_score_or_vector(self):
        far = self.post(title="A methods write-up", source=self.third)
        self.vector(far, FAR)
        bare = self.post(title="Another methods write-up", source=self.third)   # no vector at all
        self.plan()
        self.assertIsNone(self.row(far), "not tied yet: below the bar, not asked")
        self.assertEqual(self.why(far)["reason"], "below_bar")
        self.tie_third()
        why = self.why(far)
        self.assertEqual((why["reason"], why["found_by"]), ("not_planned", ["source"]))
        self.plan()
        for p in (far, bare):
            self.assertIn("source", self.row(p)["found_by"])
        other = self.post(title="A methods write-up elsewhere", source=self.other)
        self.vector(other, FAR)
        self.plan()
        self.assertIsNone(self.row(other), "an untied source's far post is still not asked")

    def test_a_post_linked_by_two_of_the_tracks_sources_is_asked(self):
        second = insert_scratch_source(self.cur, platform="rss", enabled=True,
                                       settings_json=json.dumps({"display_name": "Second Feed"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (second,))
        self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (self.folder, second))
        once = self.post(title="A methods post linked once", source=self.other)
        twice = self.post(title="A methods post linked twice", source=self.other)
        for p in (once, twice):
            self.vector(p, FAR)
        url = {p: self.cur.execute("SELECT normalized_url FROM posts WHERE id = %s", (p,)).fetchone()[0]
               for p in (once, twice)}
        self.post(title="Read this", links=[(url[once], "a methods post"), (url[twice], "a methods post")])
        self.post(title="And this", source=second, links=[(url[twice], "the methods post")])
        self.plan()
        self.assertIsNone(self.row(once), "one of the track's sources links it: not enough")
        self.assertEqual(self.row(twice)["found_by"], ["linked"])
        self.assertEqual(finders.linked_by(self.cur, twice, [self.source, second]), 2)

    def test_switched_off_turns_the_finders_off(self):
        self.tie_third()
        far = self.post(title="A methods write-up", source=self.third)
        self.vector(far, FAR)
        with mock.patch.dict("os.environ", {finders.FINDERS_ENV: "probe"}):
            self.plan()
        self.assertIsNone(self.row(far))


class NoVerdictNoOut(_Judging):
    """(2) an answer that is no verdict is asked once more, then the post stays unjudged (invalid), never out."""

    def test_asked_once_more_then_invalid(self):
        p = self.post(title="Wiring harness adapters into a coding agent",
                      text="Our adapters translate tool calls between the planner and the sandbox, with tests.")
        self.plan()
        tid = self.row(p)["task"]
        junk = {"id": "x", "subject": "a post", "fits": False, "matches": None, "excluded": None, "in": False,
                "confidence": 0.0, "subtopic": None, "why": "Not applicable to this track."}
        status, body = self.answer((tid, junk))
        self.assertEqual((status, body["valid"]), (200, 0), body)
        self.assertEqual(self.row(p)["status"], "open", "asked once more")
        status, body = self.answer((tid, dict(junk, confidence=0.4)))     # a why naming nothing of the post
        self.assertIn("names nothing", body["invalid"][0]["error"])
        r = self.row(p)
        self.assertEqual((r["status"], r["verdict"]), ("failed", None), "stored invalid, never out")
        self.cur.execute("SELECT count(*), bool_or(valid) FROM mx_calls WHERE task_id = %s", (tid,))
        self.assertEqual(self.cur.fetchone(), (2, False), "both answers kept, as invalid")
        page = self.page()
        self.assertEqual((page["counts"].get("invalid"), page["counts"].get("waiting"), page["counts"].get("out")),
                         (1, 0, None))
        got = self.why(p)
        self.assertEqual(got["state"], "invalid")
        self.assertIn("names nothing", got["error"])

    def test_a_retry_that_is_a_verdict_is_stored(self):
        p = self.post(title="Wiring harness adapters into a coding agent",
                      text="Our adapters translate tool calls between the planner and the sandbox, with tests.")
        self.plan()
        tid = self.row(p)["task"]
        self.answer((tid, {"id": "x", "in": False, "confidence": 0.0, "subtopic": None, "why": "Not applicable."}))
        self.judge(p, verdict(conf=0.85, why="Harness adapters between planner and sandbox, with tests."))
        self.assertEqual((self.row(p)["verdict"], self.why(p)["state"]), (True, "in"))


class GuideUpgrade(_Judging):
    """(3) a verdict answered under an older guide is asked once more under the kind's guide."""

    OLD_WHY = "Acme's Widget agent setup, judged by the old guide."

    def old_verdicts(self, *ages):
        """Posts of the track's own source, judged under track-v1 (their tasks moved to the old guide)."""
        ps = [self.post(title=f"Agent setup {k}", at=NOW - age * DAY) for k, age in enumerate(ages)]
        self.plan(days=None)
        for p in ps:
            self.judge(p, verdict(False, 0.7, why=self.OLD_WHY))
        self.cur.execute("""UPDATE mx_tasks SET guide = 'track-v1'
                             WHERE id IN (SELECT task_id FROM mx_track_items WHERE track_id = %s)""", (self.folder,))
        return ps

    def test_newest_first_once_a_cap_a_day_the_old_answer_kept(self):
        new, mid, old, ancient, labelled = self.old_verdicts(1, 10, 30, tracks.REASK_DAYS + 5, 2)
        self.label(labelled, "in")
        with mock.patch.object(tracks, "REASK_PER_DAY", 2):
            self.plan(days=None)
            first = {p: self.row(p) for p in (new, mid, old, ancient, labelled)}
            self.assertEqual([p for p, r in first.items() if r["guide"] == "track-v3"], [new, mid], "newest first, 2")
            self.plan(days=None)
            self.assertEqual(self.row(old)["guide"], "track-v1", "the day's cap holds")
            self.cur.execute("UPDATE mx_track_items SET reasked_at = reasked_at - interval '25 hours' WHERE track_id = %s",
                             (self.folder,))
            self.plan(days=None)
        self.assertEqual(self.row(old)["guide"], "track-v3", "the next day")
        self.assertEqual(self.row(ancient)["guide"], "track-v1", f"older than {tracks.REASK_DAYS} days: kept as is")
        self.assertEqual(self.row(labelled)["guide"], "track-v1", "the owner's label decides: not asked")
        r = self.row(new)
        self.assertEqual((r["verdict"], r["status"], len(r["asked_before"])), (False, "open", 1),
                         "the old verdict shown until the new answer")
        self.assertTrue(self.why(new)["waiting_again"])
        self.judge(new, verdict(conf=0.9, why="Acme's Widget agent setup, under the new guide."))
        r = self.row(new)
        self.assertEqual((r["verdict"], r["why"]), (True, "Acme's Widget agent setup, under the new guide."))
        self.cur.execute("SELECT c.answer->>'why' FROM mx_calls c WHERE c.task_id = %s", (r["asked_before"][0],))
        self.assertEqual(self.cur.fetchone()[0], self.OLD_WHY, "kept")
        got = self.why(new)
        self.assertEqual((got["guide"], got["waiting_again"]), ("track-v3", False))
        with mock.patch.object(tracks, "REASK_PER_DAY", 100):
            self.cur.execute("UPDATE mx_track_items SET reasked_at = reasked_at - interval '3 days' WHERE track_id = %s",
                             (self.folder,))
            self.plan(days=None)
        self.assertEqual(len(self.row(new)["asked_before"]), 1, "asked once more, once")


class DiscoverOrder(_Judging):
    """(4) Discover shows the newest fits first within a band, the cap the same."""

    def test_newest_first_within_bands(self):
        old = [self.post(title=f"Old sure {k}", source=self.other, at=NOW - 7 * (k + 1) * DAY) for k in range(3)]
        ancient = self.post(title="Ancient sure", source=self.other, at=NOW - 200 * DAY)
        fresh = self.post(title="Fresh fit", source=self.other, at=NOW)
        unsure = self.post(title="Fresh unsure", source=self.other, at=NOW)
        for p in old + [ancient, fresh, unsure]:
            self.vector(p, NEAR)
        self.plan(days=None)
        for p in old + [ancient]:
            self.judge(p, verdict(conf=0.95))
        self.judge(fresh, verdict(conf=0.8))
        self.judge(unsure, verdict(conf=0.65))
        with mock.patch.object(tracks, "DISCOVER_ITEMS", 2):
            disc = [it["post_id"] for it in self.page()["discover"]]
            self.assertEqual(disc, [fresh, unsure], "v10.41: this week's first, by band within it")
            got = self.why(fresh)
            self.assertEqual((got["position"], got["of"], got["shown"]), (1, 5, True))
            got = self.why(old[2])
            self.assertEqual((got["position"], got["shown"]), (5, False))
            self.assertEqual(self.why(ancient)["state"], "checking", "v10.41: older than the last weeks: the check's")


class SeveralTracks(_Judging):
    """(5) one post, two tracks: judged, placed and explained per track."""

    def test_a_post_in_two_tracks_in_different_ways(self):
        self.cur.execute("INSERT INTO folders (name, kind) VALUES (%s, 'track') RETURNING id",
                         (f"Local setups {uuid.uuid4().hex[:6]}",))
        second = str(self.cur.fetchone()[0])
        self.addCleanup(self.cur.execute, "DELETE FROM folders WHERE id = %s", (second,))
        self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (second, self.other))
        with self.conn.transaction():
            tracks.set_topic(self.cur, second, description="Cheap local AI setups")
        p = self.post(title="An agent harness on a cheap local box", source=self.other)
        self.vector(p, NEAR)
        self.plan()
        self.judge(p, verdict(conf=0.85, why="An agent harness on a cheap local box."))
        self.cur.execute("SELECT task_id FROM mx_track_items WHERE track_id = %s AND post_id = %s", (second, p))
        tid = self.cur.fetchone()[0]
        status, body = self.answer((tid, verdict(False, 0.6, why="An agent harness: not a setup of a cheap local box.")))
        self.assertEqual(body["valid"], 1, body)
        mine, theirs = self.why(p), self.why(p, second)
        self.assertEqual((mine["state"], mine["origin"], mine["verdict"]), ("discover", "passive", True))
        self.assertEqual((theirs["state"], theirs["origin"], theirs["verdict"]), ("out", "active", False))
        self.assertIn(p, [it["post_id"] for it in self.page()["discover"]])
        status, page2 = call("GET", f"/api/markx/tracks/{second}")
        self.assertNotIn(p, [it["post_id"] for s in page2["sections"] for it in s["items"]] +
                         [it["post_id"] for it in page2["discover"]])


if __name__ == "__main__":
    unittest.main()
