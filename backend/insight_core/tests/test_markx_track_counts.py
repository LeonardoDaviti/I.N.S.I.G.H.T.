"""v10.12.1: a topic track's sidebar count (GET /api/markx/tracks/counts): its unread track items plus its Discover
suggestions not yet labelled; a plain folder has no entry; the path is not read as a track id; read-only. Synthetic
data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import uuid

from insight_core.tests.test_markx_api import call
from insight_core.tests.test_markx_tracks import _Tracks, unit, verdict


class TopicCounts(_Tracks):
    def counts(self):
        status, body = call("GET", "/api/markx/tracks/counts")
        self.assertEqual(status, 200, body)
        return body["by_track"]

    def passive(self, title):
        p = self.post(title=title, source=self.other)
        self.vector(p, unit((0, 1), (3, 0.2)))
        return p

    def test_a_plain_folder_has_no_entry(self):
        self.post(title="an active post")
        self.assertEqual(self.counts(), {})

    def test_unread_items_plus_discover(self):
        self.describe()
        self.desc_vector(unit((0, 1)))
        a = self.post(title="active in")
        b = self.post(title="active in, read")
        c = self.post(title="active out")
        d = self.passive("passive in")
        e = self.passive("passive in, labelled out")
        f = self.passive("passive out")
        self.assertEqual(self.counts()[self.folder], {"unread": 0, "discover": 0, "count": 0, "waiting": 3})   # nothing judged yet: 3 active waiting
        self.plan()
        self.judge(a, verdict())
        self.judge(b, verdict())
        self.judge(c, verdict(False, 0.8))
        self.judge(d, verdict(conf=0.7))
        self.judge(e, verdict(conf=0.7))
        self.judge(f, verdict(False, 0.9))
        self.label(e, "out")
        self.cur.execute("INSERT INTO post_reader_state (post_id, read_at) VALUES (%s, now())", (b,))
        self.addCleanup(self.cur.execute, "DELETE FROM post_reader_state WHERE post_id = %s", (b,))
        self.assertEqual(self.counts()[self.folder], {"unread": 1, "discover": 1, "count": 2, "waiting": 0})
        self.label(d, "in")                                                   # labelled in: out of Discover, into the track
        self.assertEqual(self.counts()[self.folder], {"unread": 2, "discover": 0, "count": 2, "waiting": 0})

    def test_the_path_is_not_a_track_id_and_a_track_still_is(self):
        self.describe()
        self.assertEqual(call("GET", f"/api/markx/tracks/{self.folder}")[0], 200)
        self.assertEqual(call("GET", f"/api/markx/tracks/{uuid.uuid4()}")[0], 404)
        self.assertIn(self.folder, self.counts())
