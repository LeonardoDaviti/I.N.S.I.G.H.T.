"""Issue 0185 (3): why a post is, or is not, in a track: a read of the stored verdict (markx/track_why.py,
GET /api/markx/tracks/{id}/why). Read only: no task, no call, no row written. Synthetic data only."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.markx import track_why, tracks  # noqa: E402
from insight_core.tests._db import requires_test_db  # noqa: E402
from insight_core.tests.test_markx_api import call  # noqa: E402
from insight_core.tests.test_markx_tracks import _Tracks, unit, verdict  # noqa: E402

DAY = timedelta(days=1)


@requires_test_db
class TrackWhy(_Tracks):
    def why(self, post):
        status, body = call("GET", f"/api/markx/tracks/{self.folder}/why", query={"post": post})
        self.assertEqual(status, 200, body)
        return body

    def counts(self):
        self.cur.execute("SELECT (SELECT count(*) FROM mx_tasks), (SELECT count(*) FROM mx_calls), "
                         "(SELECT count(*) FROM mx_track_items), (SELECT count(*) FROM mx_labels)")
        return self.cur.fetchone()

    def passive(self, title, vector=True, at=None):
        p = self.post(title=title, source=self.other, at=at)
        if vector:
            self.vector(p, unit((0, 1), (3, 0.2)))
        return p

    def test_a_folder_without_a_description_judges_nothing(self):
        p = self.post()
        self.assertEqual((self.why(p)["state"], self.why(p)["reason"]), ("not_asked", "not_a_topic"))

    def test_judged_posts_say_in_out_and_discover_with_haikus_why(self):
        self.describe()
        self.desc_vector(unit((0, 1)))
        a = self.post(title="active in")
        b = self.post(title="active out")
        c = self.passive("passive in")
        self.plan()
        self.judge(a, verdict(conf=0.92))
        self.judge(b, verdict(False, 0.84, why="A printer review, not a print."))
        self.judge(c, verdict(conf=0.7))
        before = self.counts()
        got = self.why(a)
        self.assertEqual((got["state"], got["origin"], got["verdict"], got["confidence"], got["current"]),
                         ("in", "active", True, 0.92, True))
        self.assertEqual(got["why"], "A wall storage system to print: modular, cheap.")
        got = self.why(b)
        self.assertEqual((got["state"], got["verdict"], got["confidence"], got["why"]),
                         ("out", False, 0.84, "A printer review, not a print."))
        got = self.why(c)
        self.assertEqual((got["state"], got["origin"], got["position"], got["of"], got["shown"]),
                         ("discover", "passive", 1, 1, True))
        self.assertEqual(self.counts(), before, "read only: no task, call, item or label written")
        # the owner's ✗ wins over Haiku's in, and says so
        self.label(a, "out")
        got = self.why(a)
        self.assertEqual((got["state"], got["label"], got["verdict"]), ("out", "out", True))

    def test_below_the_discover_cut(self):
        self.describe()
        self.desc_vector(unit((0, 1)))
        hi, lo = self.passive("passive sure"), self.passive("passive unsure")
        self.plan()
        self.judge(hi, verdict(conf=0.95))
        self.judge(lo, verdict(conf=0.55))
        with mock.patch.object(tracks, "DISCOVER_ITEMS", 1):
            self.assertTrue(self.why(hi)["shown"])
            got = self.why(lo)
        self.assertEqual((got["state"], got["position"], got["of"], got["shown"], got["cut"]), ("discover", 2, 2, False, 1))

    def test_asked_and_waiting(self):
        self.describe()
        a = self.post(title="active, asked")
        self.plan()
        self.assertEqual(self.why(a)["state"], "waiting")

    def test_never_asked_says_why(self):
        self.describe()
        old = self.post(title="active, long ago", at=datetime.now(timezone.utc) - 400 * DAY)
        new = self.post(title="active, not planned yet")
        got = self.why(old)
        self.assertEqual((got["state"], got["reason"]), ("not_asked", "outside_window"))
        self.assertIsInstance(got["days"], int)
        self.assertEqual(self.why(new)["reason"], "not_planned")
        bare = self.passive("passive, no vector", vector=False)
        self.assertEqual(self.why(bare)["reason"], "not_embedded")
        quiet = self.passive("passive, vector, finders never ran")
        self.assertEqual(self.why(quiet)["reason"], "no_profile")
        self.cur.execute("UPDATE mx_tracks SET stats = %s::jsonb WHERE folder_id = %s",
                         (json.dumps({"last": {"threshold": 0.47}}), self.folder))
        got = self.why(quiet)
        self.assertEqual((got["reason"], got["bar"]), ("below_bar", 0.47))
        t = tracks.get(self.cur, self.folder)
        older = self.passive("passive, before the description", at=t["version_at"] - 3 * DAY)
        self.assertEqual(self.why(older)["reason"], "history_pending")          # the history pass never started
        self.cur.execute("UPDATE mx_tracks SET history_at = %s, history_id = %s WHERE folder_id = %s",
                         (t["version_at"] - 5 * DAY, "00000000-0000-0000-0000-000000000000", self.folder))
        self.assertEqual(self.why(older)["reason"], "below_bar")                # its cursor went past it
        self.label(bare, "in")
        got = self.why(bare)
        self.assertEqual((got["state"], got["reason"]), ("in", "labelled"))

    def test_a_post_by_its_address_or_link_and_unknown_ones(self):
        self.describe()
        a = self.post(title="active")
        self.cur.execute("SELECT url FROM posts WHERE id = %s", (a,))
        url = self.cur.fetchone()[0]
        self.assertEqual(self.why(url)["post"], a)
        self.assertEqual(self.why(f"http://insight.local/posts/{a}")["post"], a)
        self.assertEqual(call("GET", f"/api/markx/tracks/{self.folder}/why", query={"post": "https://nowhere.example/x"})[0], 404)
        self.assertEqual(track_why.find_post(self.cur, ""), None)


if __name__ == "__main__":
    unittest.main()
