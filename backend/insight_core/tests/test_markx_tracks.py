"""0145 (Stealth v10.11): tracks as topics. A track without a description stays a folder; the profile and its
threshold; the prefilter; the `track` and `subtopics` kinds (schema, validation, an empty answer a failed try); the
routing (active -> the track, passive -> Discover); calibrated ranking; auto-join only at 90% with 20+ labels, and back
off when it drops; source suggestions at 3+ in 30 days; the per-run
cap; labels as examples; the description embedded by the worker's embedder. Synthetic data only; the DB tests run on a
database whose name ends in _test."""
from __future__ import annotations

import base64
import json
import math
import struct
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from insight_core.markx import repo, schemas, tasks, tracks, validate
from insight_core.tests._db import clear_tables, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import _Api, call

NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = timedelta(days=1)
BUILD = "a" * 64
TRACK_TABLES = ("mx_tracks", "mx_track_items", "mx_track_subtopics")


def unit(*parts, n=1024):
    v = [0.0] * n
    for k, w in parts:
        v[k] += w
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def b64(v):
    return base64.b64encode(struct.pack(f"<{len(v)}e", *v)).decode("ascii")


def verdict(inside=True, conf=0.9, sub="storage and organisers", why="A wall storage system to print: modular, cheap."):
    return {"id": "x", "in": inside, "confidence": conf, "subtopic": sub if inside else None, "why": why}


class Pure(unittest.TestCase):
    def test_the_kinds_and_their_guides(self):
        self.assertEqual((schemas.KINDS["track"].guide, schemas.KINDS["track"].subject), ("track-v2", "post_track"))
        self.assertEqual((schemas.KINDS["subtopics"].guide, schemas.KINDS["subtopics"].subject), ("subtopics-v2", "track"))
        self.assertIn("in", schemas.guide_body("track-v2"))
        for k in ("track", "subtopics"):
            self.assertIn(k, tasks.PLANNERS)

    def test_the_track_answer_is_checked(self):
        self.assertIsNone(validate.check("track", verdict(), "q")[1])
        self.assertIsNone(validate.check("track", verdict(False, 0.2), "q")[1])
        self.assertIn("in", validate.check("track", {"confidence": 0.5, "why": "x"}, "q")[1])
        self.assertIn("confidence", validate.check("track", dict(verdict(), confidence=7), "q")[1])
        self.assertIn("one line", validate.check("track", dict(verdict(), why="a\nb"), "q")[1])
        self.assertIn("at most", validate.check("track", dict(verdict(), why="w " * 200), "q")[1])
        self.assertIsNotNone(validate.check("track", {}, "q")[1])          # a refused post's empty answer: a failed try

    def test_the_profile(self):
        d = unit((0, 1))
        self.assertIsNone(tracks.combine(None, [], []))
        self.assertEqual(tracks.combine(d, [], [])[:2], [1.0, 0.0])
        p = tracks.combine(d, [unit((1, 1))], [])
        self.assertAlmostEqual(p[0], p[1])                                  # the ✓ mean pulls it toward the examples
        q = tracks.combine(d, [unit((1, 1))], [unit((1, 1))])
        self.assertGreater(q[0], q[1])                                      # the ✗ mean pulls it back
        self.assertIsNotNone(tracks.combine(None, [unit((2, 1))], []))      # examples alone make a profile

    def test_the_threshold_keeps_98_percent_of_the_examples(self):
        self.assertEqual(tracks.threshold_for([0.9, 0.8]), tracks.DEFAULT_THRESHOLD)   # fewer than 5 ✓: the default
        self.assertEqual(tracks.threshold_for([0.7, 0.62, 0.8, 0.66, 0.9]), 0.62)     # under 50: the lowest passes
        scores = [0.40] + [0.70] * 99                                                 # 100: 2 may fall below it
        self.assertEqual(tracks.threshold_for(scores + [0.41]), 0.70)
        self.assertEqual(sum(s >= tracks.threshold_for(scores) for s in scores), 99)

    def test_leave_one_out(self):
        d = unit((0, 1))
        pos = [unit((0, 1), (k + 1, 1)) for k in range(5)]
        loo = tracks.loo_scores(d, pos, [])
        self.assertEqual(len(loo), 5)
        full = tracks.combine(d, pos, [])
        self.assertTrue(all(s < sum(a * b for a, b in zip(p, full)) for s, p in zip(loo, pos)))

    def test_calibration_ranking_and_the_join_bar(self):
        cal = tracks.calibrate([(0.95, True)] * 5)
        self.assertEqual(cal["labels"], 5)
        self.assertEqual(tracks.rank_of(cal, 0.72), 0.72)                    # under 10 labels: by confidence
        labelled = [(0.95, True)] * 8 + [(0.75, False)] * 4
        cal = tracks.calibrate(labelled)
        self.assertGreater(tracks.rank_of(cal, 0.95), tracks.rank_of(cal, 0.75))
        self.assertIsNone(cal["join_edge"])                                 # 12 labels: never joins
        nineteen = tracks.calibrate([(0.95, True)] * 19)
        self.assertIsNone(nineteen["join_edge"])
        many = tracks.calibrate([(0.95, True)] * 40 + [(0.6, False)] * 10)
        self.assertEqual(many["join_edge"], 0.9)                            # the band at or above 0.9 is 40 of 40
        self.assertGreaterEqual(next(b for b in many["bands"] if b["edge"] == 0.9)["lower"], tracks.JOIN_LOWER)
        dropped = tracks.calibrate([(0.95, True)] * 36 + [(0.95, False)] * 4 + [(0.6, False)] * 10)
        self.assertIsNone(dropped["join_edge"])                             # 90% raw but its lower bound < 0.85


@requires_test_db
class _Tracks(_Api):
    plan = True

    def setUp(self):
        super().setUp()
        clear_tables(self.cur, TRACK_TABLES)
        self.cur.execute("INSERT INTO folders (name, kind) VALUES (%s, 'track') RETURNING id", (f"Prints {uuid.uuid4().hex[:6]}",))
        self.folder = str(self.cur.fetchone()[0])
        self.addCleanup(self.cur.execute, "DELETE FROM folders WHERE id = %s", (self.folder,))
        self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (self.folder, self.source))
        self.third = insert_scratch_source(self.cur, platform="rss", enabled=True, settings_json=json.dumps({"display_name": "Example Blog"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (self.third,))
        self.addCleanup(clear_tables, self.cur, TRACK_TABLES)

    def describe(self, description="Things worth 3D printing: useful prints and why", excludes=None):
        with self.conn.transaction():
            return tracks.set_topic(self.cur, self.folder, description=description, excludes=excludes)

    def vector(self, post, v):
        repo.put_embedding(self.cur, post_id=post, model="bge-m3", text_hash=uuid.uuid4().hex, vector=v,
                           model_sha256=BUILD)

    def desc_vector(self, v):
        t = tracks.get(self.cur, self.folder)
        self.cur.execute("UPDATE mx_tracks SET v = %s::halfvec, v_hash = %s WHERE folder_id = %s",
                         (repo.vector_text(v), tracks._sha(tracks.embed_text(t)), self.folder))

    def plan(self, **kw):
        with self.conn.transaction():
            return tracks.plan(self.cur, **kw)

    def items(self):
        self.cur.execute("SELECT post_id::text, origin, version, task_id FROM mx_track_items WHERE track_id = %s",
                         (self.folder,))
        return {p: (o, v, t) for p, o, v, t in self.cur.fetchall()}

    def judge(self, post, answer):
        tid = self.items()[post][2]
        status, body = self.answer((tid, answer))
        self.assertEqual((status, body["valid"]), (200, 1), body)

    def label(self, post, answer):
        status, body = call("POST", f"/api/markx/tracks/{self.folder}/labels", body={"post": post, "answer": answer})
        self.assertEqual(status, 200, body)

    def page(self):
        status, body = call("GET", f"/api/markx/tracks/{self.folder}")
        self.assertEqual(status, 200, body)
        return body


class AFolder(_Tracks):
    def test_a_track_without_a_description_stays_a_folder(self):
        self.post()
        self.assertEqual(self.plan(), 0)
        body = self.page()
        self.assertFalse(body["track"]["topic"])
        self.assertEqual(body["sections"], [])
        self.describe("   ")
        self.assertEqual(self.plan(), 0)
        self.assertFalse(self.page()["track"]["topic"])
        self.assertEqual(call("GET", f"/api/markx/tracks/{uuid.uuid4()}")[0], 404)

    def test_describing_through_the_api_and_a_new_version(self):
        status, body = call("PUT", f"/api/markx/tracks/{self.folder}", body={"description": "Cheap local AI setups"})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["track"]["topic"])
        self.assertEqual(body["track"]["version"], 1)
        _, body = call("PUT", f"/api/markx/tracks/{self.folder}", body={"description": "Cheap local AI setups"})
        self.assertEqual(body["track"]["version"], 1)                         # the same words: the same version
        _, body = call("PUT", f"/api/markx/tracks/{self.folder}", body={"description": "Cheap local AI setups",
                                                                         "excludes": "cloud GPUs"})
        self.assertEqual((body["track"]["version"], body["track"]["excludes"]), (2, "cloud GPUs"))
        listed = {t["id"]: t for t in call("GET", "/api/markx/tracks")[1]}
        self.assertTrue(listed[self.folder]["topic"])
        # 0191: an edit that changes no word keeps the version (and its history pass); the text shown follows it
        self.cur.execute("UPDATE mx_tracks SET history_done_at = now() WHERE folder_id = %s", (self.folder,))
        _, body = call("PUT", f"/api/markx/tracks/{self.folder}", body={"description": "cheap local AI setups.",
                                                                         "excludes": "Cloud GPUs"})
        self.assertEqual((body["track"]["version"], body["track"]["description"], body["track"]["excludes"]),
                         (2, "cheap local AI setups.", "Cloud GPUs"))
        self.assertIsNotNone(tracks.get(self.cur, self.folder)["history_done_at"], "the history pass is not restarted")
        _, body = call("PUT", f"/api/markx/tracks/{self.folder}", body={"description": "Cheap local AI rigs",
                                                                         "excludes": "Cloud GPUs"})
        self.assertEqual(body["track"]["version"], 3)                         # a word changed: a new version
        self.assertIsNone(tracks.get(self.cur, self.folder)["history_done_at"])
        self.assertEqual(tracks.material(" Cheap, local AI\nsetups! "), "cheap local ai setups")


class Planning(_Tracks):
    def test_active_posts_are_judged_without_the_prefilter(self):
        self.describe()
        a = self.post(title="A modular wall storage system you can print")
        self.post(title="A passive post", source=self.other)
        self.assertEqual(self.plan(), 1)                                    # no profile yet: passive waits
        self.assertEqual(self.items()[a][0], "active")
        self.cur.execute("SELECT kind, subject_kind, a::text, b::text, input FROM mx_tasks WHERE kind = 'track'")
        kind, subject, ta, tb, text = self.cur.fetchone()
        self.assertEqual((kind, subject, ta, tb), ("track", "post_track", a, self.folder))
        self.assertTrue(text.startswith("TRACK: Prints"))
        self.assertIn("Belongs: Things worth 3D printing", text)
        self.assertIn("\n\nPOST\nPlatform: telegram | Source: Example Channel", text)
        self.assertEqual(self.plan(), 0)                                    # asked once a version

    def test_the_prefilter_passes_near_posts_only(self):
        self.describe()
        self.desc_vector(unit((0, 1)))
        near = self.post(title="near", source=self.other)
        far = self.post(title="far", source=self.other)
        self.vector(near, unit((0, 1), (1, 0.3)))
        self.vector(far, unit((5, 1)))
        self.plan()
        got = self.items()
        self.assertIn(near, got)
        self.assertNotIn(far, got)
        self.assertEqual(got[near][0], "passive")
        stats = tracks.get(self.cur, self.folder)["stats"]
        self.assertEqual((stats["last"]["recent"]["scanned"], stats["last"]["recent"]["passed"]), (2, 1))
        self.assertEqual(stats["last"]["threshold"], tracks.DEFAULT_THRESHOLD)

    def test_the_default_bar_passes_a_share_of_the_month_at_most_the_spec_value(self):
        self.describe()
        self.desc_vector(unit((0, 1)))
        coss = []
        for k in range(120):
            p = self.post(title=f"p{k}", source=self.other)
            v = unit((0, 1), (10 + k, 1.6 + k / 40))
            self.vector(p, v)
            coss.append(v[0])
        prof = tracks.profile(self.cur, tracks.get(self.cur, self.folder))
        self.assertLess(prof["threshold"], tracks.DEFAULT_THRESHOLD)
        passed = sum(c >= prof["threshold"] - 1e-3 for c in coss)
        self.assertTrue(34 <= passed <= 40, (passed, prof["threshold"]))    # about 30% of the month
        self.cur.execute("UPDATE mx_embeddings SET v = %s::halfvec", (repo.vector_text(unit((0, 1), (3, 0.2))),))   # all close: 0.55 caps it
        self.assertEqual(tracks.profile(self.cur, tracks.get(self.cur, self.folder))["threshold"], tracks.DEFAULT_THRESHOLD)

    def test_the_history_pass_reads_older_posts_once_resumably(self):
        self.describe()
        self.desc_vector(unit((0, 1)))
        old = [self.post(title=f"old {k}", source=self.other, at=NOW - (30 + k) * DAY) for k in range(5)]
        for p in old:
            self.vector(p, unit((0, 1), (2, 0.2)))
        self.cur.execute("UPDATE mx_tracks SET version_at = %s WHERE folder_id = %s", (NOW, self.folder))
        self.assertEqual(self.plan(cap=2), 2)                                # the cap: two now
        self.assertIsNone(tracks.get(self.cur, self.folder)["history_done_at"])
        self.cur.execute("UPDATE mx_tasks SET status = 'answered' WHERE kind = 'track'")
        self.assertEqual(self.plan(cap=10), 3)                               # resumed where it stopped
        self.assertIsNotNone(tracks.get(self.cur, self.folder)["history_done_at"])
        self.cur.execute("SELECT min(priority) FROM mx_tasks WHERE kind = 'track'")
        self.assertGreaterEqual(self.cur.fetchone()[0], tracks.HISTORY_PRIORITY)
        self.assertEqual(self.plan(cap=10), 0)

    def test_the_per_run_cap_counts_open_tasks_across_tracks(self):
        self.describe()
        for k in range(6):
            self.post(title=f"active {k}")
        self.assertEqual(self.plan(cap=4), 4)
        self.assertEqual(self.plan(cap=4), 0)                                # 4 open: no room
        self.cur.execute("UPDATE mx_tasks SET status = 'answered' WHERE kind = 'track'")
        self.assertEqual(self.plan(cap=4), 2)

    def test_the_env_sets_the_cap(self):
        import os
        old = os.environ.get(tracks.TASKS_PER_RUN_ENV)
        os.environ[tracks.TASKS_PER_RUN_ENV] = "7"
        try:
            self.assertEqual(tracks.tasks_per_run(), 7)
        finally:
            if old is None:
                os.environ.pop(tracks.TASKS_PER_RUN_ENV)
            else:
                os.environ[tracks.TASKS_PER_RUN_ENV] = old

    def test_the_description_is_embedded_by_the_worker(self):
        self.describe()
        status, body = self.lease("embed")
        self.assertEqual(status, 200, body)
        mine = [t for t in body["tasks"] if t["input"].startswith("Prints")]
        self.assertEqual(len(mine), 1)
        self.assertEqual(body["tasks"][0]["id"], mine[0]["id"])            # leased first
        status, got = call("POST", "/api/markx/embeddings", token=self.token,
                           body={"worker": "device-1", "model": "bge-m3", "model_sha256": BUILD,
                                 "vectors": [{"task_id": mine[0]["id"], "vector": b64(unit((0, 1)))}]})
        self.assertEqual((status, got["stored"]), (200, 1), got)
        t = tracks.get(self.cur, self.folder)
        self.assertTrue(t["has_v"])
        self.assertTrue(tracks.profile(self.cur, t)["description"])
        with self.conn.transaction():
            self.assertEqual(tracks.plan_vectors(self.cur), 0)              # embedded: not asked again
        self.describe("Something else entirely")
        with self.conn.transaction():
            self.assertEqual(tracks.plan_vectors(self.cur), 1)              # new words: a new vector


class Routing(_Tracks):
    def setUp(self):
        super().setUp()
        self.describe()
        self.desc_vector(unit((0, 1)))

    def passive(self, title, source=None, at=None):
        p = self.post(title=title, source=source or self.other, at=at)
        self.vector(p, unit((0, 1), (3, 0.2)))
        return p

    def test_active_in_goes_to_the_track_passive_in_to_discover_out_is_kept(self):
        a = self.post(title="active in")
        b = self.post(title="active out")
        c = self.passive("passive in")
        d = self.passive("passive out")
        self.plan()
        self.judge(a, verdict())
        self.judge(b, verdict(False, 0.8))
        self.judge(c, verdict(conf=0.7))
        self.judge(d, verdict(False, 0.9))
        body = self.page()
        in_track = [it["post_id"] for s in body["sections"] for it in s["items"]]
        self.assertEqual(in_track, [a])
        self.assertEqual([it["post_id"] for it in body["discover"]], [c])
        self.assertEqual((body["counts"]["out"], body["counts"]["judged"]), (2, 4))
        self.cur.execute("SELECT count(*) FROM mx_track_items WHERE verdict IS FALSE")
        self.assertEqual(self.cur.fetchone()[0], 2)                         # rejected posts kept with their verdict
        self.label(c, "in")
        self.assertIn(c, [it["post_id"] for s in self.page()["sections"] for it in s["items"]])
        self.label(a, "out")
        self.assertNotIn(a, [it["post_id"] for s in self.page()["sections"] for it in s["items"]])
        self.label(a, "undo")
        self.assertIn(a, [it["post_id"] for s in self.page()["sections"] for it in s["items"]])

    def test_a_repost_shares_the_question_and_its_verdict(self):
        text = "The same post, copied word for word by another channel, with enough words to be a post of its own."
        a = self.post(title="Same", text=text)
        self.plan()
        self.judge(a, verdict())
        self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (self.folder, self.third))
        b = self.post(title="Same", text=text, source=self.third)
        self.cur.execute("UPDATE sources SET settings = (SELECT settings FROM sources WHERE id = %s) WHERE id = %s",
                         (self.source, self.third))
        self.cur.execute("UPDATE sources SET platform = 'telegram' WHERE id = %s", (self.third,))
        self.plan()
        self.cur.execute("SELECT post_id::text, verdict FROM mx_track_items")
        self.assertEqual(dict(self.cur.fetchall()), {a: True, b: True})

    def test_discover_is_ranked_by_calibrated_precision(self):
        posts = [self.passive(f"p{k}") for k in range(14)]
        self.plan()
        for k, p in enumerate(posts):
            self.judge(p, verdict(conf=0.95 if k % 2 == 0 else 0.62))
        hi = [p for k, p in enumerate(posts) if k % 2 == 0]
        lo = [p for k, p in enumerate(posts) if k % 2 == 1]
        for p in hi[:5]:
            self.label(p, "out")                                            # the confident band: wrong
        for p in lo[:5]:
            self.label(p, "in")                                             # the unsure one: right
        disc = self.page()["discover"]
        self.assertEqual(sorted(it["post_id"] for it in disc[:2]), sorted(lo[5:7]))   # calibrated: the 0.6 band leads
        self.assertEqual(sorted(it["post_id"] for it in disc[2:]), sorted(hi[5:7]))
        self.assertTrue(all(it["place"] == "discover" for it in disc))

    def test_auto_join_at_ninety_percent_with_twenty_labels_and_back_off(self):
        posts = [self.passive(f"p{k}") for k in range(30)]
        self.plan()
        for p in posts:
            self.judge(p, verdict(conf=0.95))
        for p in posts[:22]:
            self.label(p, "in")
        body = self.page()
        self.assertEqual(body["calibration"]["join_edge"], 0.9)
        joined = [it for s in body["sections"] for it in s["items"] if it["place"] == "joined"]
        self.assertEqual(sorted(it["post_id"] for it in joined), sorted(posts[22:]))
        self.assertEqual(body["discover"], [])
        for p in posts[:4]:
            self.label(p, "out")                                            # precision drops: back to Discover
        body = self.page()
        self.assertIsNone(body["calibration"]["join_edge"])
        self.assertEqual(sorted(it["post_id"] for it in body["discover"]), sorted(posts[22:]))

    def test_labels_become_examples(self):
        a = self.passive("A printable cable organiser for a desk")
        b = self.passive("A sale on filament")
        self.plan()
        self.judge(a, verdict())
        self.judge(b, verdict())
        self.label(a, "in")
        self.label(b, "out")
        t = tracks.get(self.cur, self.folder)
        head = tracks.header(self.cur, t)
        self.assertIn("Marked in by the reader:\n- A printable cable organiser for a desk", head)
        self.assertIn("Marked out by the reader:\n- A sale on filament", head)
        prof = tracks.profile(self.cur, t)
        self.assertEqual((prof["pos"], prof["neg"]), (1, 1))
        examples = self.page()["examples"]
        self.assertEqual(([e["post_id"] for e in examples["in"]], [e["post_id"] for e in examples["out"]]), ([a], [b]))
        self.assertEqual(call("POST", f"/api/markx/tracks/{self.folder}/labels", body={"post": a, "answer": "maybe"})[0], 400)

    def test_a_source_with_three_in_thirty_days_is_suggested_and_made_active(self):
        posts = [self.passive(f"x{k}", source=self.third) for k in range(3)] + [self.passive("y", source=self.other)]
        old = self.passive("old", source=self.other, at=NOW - 40 * DAY)
        self.plan()
        for p in posts + [old]:
            self.judge(p, verdict())
        sug = self.page()["suggestions"]
        self.assertEqual([(s["source_id"], s["n"]) for s in sug], [(self.third, 3)])
        self.assertEqual(call("GET", "/api/markx/tracks/suggestions")[1][0]["source"], "Example Blog")
        status, body = call("POST", f"/api/markx/tracks/{self.folder}/sources/{self.third}")
        self.assertEqual((status, body), (200, {"added": True}))
        page = self.page()
        self.assertEqual(page["suggestions"], [])
        self.assertTrue(all(it["origin"] == "active" for s in page["sections"] for it in s["items"]
                            if it["source_id"] == self.third))

    def test_cost_and_items_per_day_in_the_footer(self):
        a = self.post(title="active in")
        self.plan()
        self.judge(a, verdict())
        f = self.page()["footer"]
        self.assertEqual((f["tasks"], f["cost_usd"]), (1, 0.0001))
        self.assertEqual(f["items_per_day"], round(1 / 7, 2))


class KeptPlaces(_Tracks):
    """Issue 0195: the page, the suggestions and the sidebar counts read the kept placements (markx/track_kept.py)
    and answer exactly what placing live answers; a change to a track's inputs makes it read live until placed
    again."""

    def setUp(self):
        super().setUp()
        self.describe()
        self.desc_vector(unit((0, 1)))
        self.cur.execute("DELETE FROM mx_track_places_state")
        self.addCleanup(self.cur.execute, "DELETE FROM mx_track_places_state")

    def answers(self):
        from insight_core.markx import track_counts
        with self.conn.transaction():
            return (self.page(), tracks.suggestions(self.cur, now=NOW + DAY), track_counts.topic_counts(self.cur))

    def keep(self):
        from insight_core.markx import track_kept
        with self.conn.transaction():
            return track_kept.refresh(self.cur)

    def kept(self) -> bool:
        from insight_core.markx import track_kept
        return track_kept.calibration(self.cur, self.folder) is not None

    def test_kept_answers_are_the_live_ones(self):
        a, b = self.post(title="active in"), self.post(title="active out")
        passive = []
        for k in range(4):
            p = self.post(title=f"passive {k}", source=self.other, at=NOW - k * DAY)
            self.vector(p, unit((0, 1), (3, 0.2)))
            passive.append(p)
        self.plan()
        self.judge(a, verdict())
        self.judge(b, verdict(False, 0.8))
        for k, p in enumerate(passive):
            self.judge(p, verdict(conf=0.6 + k / 10))
        live = self.answers()
        self.assertFalse(self.kept())
        self.assertEqual(self.keep(), 1)
        self.assertTrue(self.kept())
        self.assertEqual(self.answers(), live)
        self.assertTrue(live[1], "a passive source with 3+ items in: a suggestion")
        self.label(passive[0], "in")                       # the owner's label: read live until placed again
        self.assertFalse(self.kept())
        changed = self.answers()
        self.assertIn(passive[0], [it["post_id"] for s in changed[0]["sections"] for it in s["items"]])
        self.keep()
        self.assertTrue(self.kept())
        self.assertEqual(self.answers(), changed)
        self.cur.execute("DELETE FROM source_folders WHERE folder_id = %s AND source_id = %s", (self.folder, self.source))
        self.assertFalse(self.kept(), "its sources changed")
        self.keep()
        self.assertEqual(self.keep(), 0, "nothing changed since")


class SwitchedOff(_Tracks):
    """Issue 0200 (v10.17.1): a passive source the owner switched off feeds no suggestion of a track: its posts are
    neither in Discover nor joined, it is never a source suggestion, its new posts are not asked, the scout reads none
    of them; switched on again, all come back. Kept placements follow the switch (migration 0135)."""

    def setUp(self):
        super().setUp()
        self.describe()
        self.desc_vector(unit((0, 1)))
        self.cur.execute("DELETE FROM mx_track_places_state")
        self.addCleanup(self.cur.execute, "DELETE FROM mx_track_places_state")

    def passive(self, title, source, at=None):
        p = self.post(title=title, source=source, at=at)
        self.vector(p, unit((0, 1), (3, 0.2)))
        return p

    def switch(self, source, on):
        self.cur.execute("UPDATE sources SET enabled = %s WHERE id = %s", (on, source))

    def keep(self):
        from insight_core.markx import track_kept
        with self.conn.transaction():
            return track_kept.refresh(self.cur)

    def shown(self):
        from insight_core.markx import track_counts
        body = self.page()
        with self.conn.transaction():
            counts = track_counts.topic_counts(self.cur)[self.folder]
            sug = tracks.suggestions(self.cur, now=NOW + DAY)
        return ({it["post_id"] for it in body["discover"]}, [(s["source_id"], s["n"]) for s in sug], counts["discover"],
                {it["post_id"] for s in body["sections"] for it in s["items"]})

    def test_its_posts_leave_discover_and_the_source_suggestions_and_come_back(self):
        farm = [self.passive(f"farm {k}", self.third, at=NOW - k * DAY) for k in range(3)]
        mine = self.passive("kept", self.other)
        self.plan()
        for p in farm + [mine]:
            self.judge(p, verdict(conf=0.95))
        on = self.shown()
        self.assertEqual((on[0], on[1], on[2]), (set(farm) | {mine}, [(self.third, 3)], 4))
        self.switch(self.third, False)
        self.assertEqual(self.shown()[:3], ({mine}, [], 1))
        self.keep()
        self.assertEqual(self.shown()[:3], ({mine}, [], 1), "kept: the same")
        self.cur.execute("SELECT place FROM mx_track_places WHERE post_id = %s", (farm[0],))
        self.assertEqual(self.cur.fetchone()[0], "off")
        self.switch(self.third, True)                       # the trigger: read live again, then kept again
        self.assertEqual(self.shown()[:3], on[:3])
        self.keep()
        self.assertEqual(self.shown()[:3], on[:3])

    def test_never_joined_but_the_owners_check_stays(self):
        posts = [self.passive(f"p{k}", self.other) for k in range(24)]
        farm = [self.passive(f"farm {k}", self.third) for k in range(2)]
        self.plan()
        for p in posts + farm:
            self.judge(p, verdict(conf=0.95))
        for p in posts[:22]:
            self.label(p, "in")
        self.label(farm[0], "in")                           # the owner's ✓ is the owner's: it stays in the track
        self.switch(self.third, False)
        body = self.page()
        self.assertEqual(body["calibration"]["join_edge"], 0.9)
        joined = {it["post_id"] for s in body["sections"] for it in s["items"] if it["place"] == "joined"}
        self.assertEqual(joined, set(posts[22:]))
        in_track = {it["post_id"] for s in body["sections"] for it in s["items"]}
        self.assertIn(farm[0], in_track)
        self.assertNotIn(farm[1], in_track)
        self.assertEqual(body["discover"], [])
        self.assertEqual(body["counts"].get("off"), 1)

    def test_its_posts_are_not_asked_and_the_scout_reads_none(self):
        from insight_core.markx import scout
        self.switch(self.third, False)
        farm = self.passive("farm", self.third)
        mine = self.passive("mine", self.other)
        self.plan()
        self.assertEqual(set(self.items()), {mine})
        self.switch(self.third, True)
        self.plan()
        self.assertEqual(set(self.items()), {mine, farm})
        self.judge(mine, verdict())
        self.judge(farm, verdict())
        self.assertEqual(set(scout.in_posts(self.cur, self.folder)), {mine, farm})
        self.switch(self.third, False)
        self.assertEqual(scout.in_posts(self.cur, self.folder), [mine])
        self.label(farm, "in")
        self.assertEqual(set(scout.in_posts(self.cur, self.folder)), {mine, farm}, "the owner's ✓ is the owner's")


# The sub-topics (0207: found from the posts, named, digested, the owner's edits): test_track_subtopics_0207.


if __name__ == "__main__":
    unittest.main()
