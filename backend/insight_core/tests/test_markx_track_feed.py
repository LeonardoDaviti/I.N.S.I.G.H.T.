"""v10.12.1: a topic track's reading views list only the posts in the track (markx/track_feed): its active sources'
posts judged in, posts joined by INSIGHT, the owner's ✓; not a post judged out, not one waiting for its verdict, not
a Discover suggestion. `all_sources` lists the folder's every post as before; a plain folder and Mark X off are
unchanged. Stream, By source, Later, Kept and History; the toolbar's count; mark read up to here; the waiting count.
Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from insight_core.db.repo_reader import FeedCursor, FeedQuery, FeedScope, ReaderRepository
from insight_core.markx import track_feed
from insight_core.services import registry
from insight_core.services.reader_service import ReaderService
from insight_core.tests.test_markx_api import call, db_url
from insight_core.tests.test_markx_tracks import _Tracks, unit, verdict

NOW = datetime.now(timezone.utc)


class TrackFeed(_Tracks):
    def setUp(self):
        super().setUp()
        self.reader = ReaderService(db_url())
        self.addCleanup(self.cur.execute, "DELETE FROM post_reader_state WHERE post_id IN "
                                          "(SELECT id FROM posts WHERE source_id = ANY(%s::uuid[]))",
                        ([self.source, self.other],))

    def passive(self, title, at=None):
        p = self.post(title=title, source=self.other, at=at)
        self.vector(p, unit((0, 1), (3, 0.2)))
        return p

    def world(self):
        """Active: in, in (older), out, waiting. Passive: in (Discover), in then ✓, out."""
        self.describe()
        self.desc_vector(unit((0, 1)))
        w = {"a_in": self.post(title="active in", at=NOW - timedelta(minutes=1)),
             "a_in_old": self.post(title="active in, older", at=NOW - timedelta(minutes=5)),
             "a_out": self.post(title="active out", at=NOW - timedelta(minutes=3)),
             "p_disc": self.passive("passive in", at=NOW - timedelta(minutes=2)),
             "p_ok": self.passive("passive in, labelled in", at=NOW - timedelta(minutes=4)),
             "p_out": self.passive("passive out", at=NOW - timedelta(minutes=6))}
        self.plan()
        self.judge(w["a_in"], verdict())
        self.judge(w["a_in_old"], verdict())
        self.judge(w["a_out"], verdict(False, 0.8))
        self.judge(w["p_disc"], verdict(conf=0.7))
        self.judge(w["p_ok"], verdict(conf=0.7))
        self.judge(w["p_out"], verdict(False, 0.9))
        self.label(w["p_ok"], "in")
        w["a_wait"] = self.post(title="active, not judged yet", at=NOW)
        return w

    def ids(self, all_sources=False, **kw):
        kw.setdefault("filter", "unread")
        page = self.reader.list_posts(FeedQuery(scope=FeedScope("folder", self.folder), limit=100, per_source=10, **kw),
                                      all_sources=all_sources)
        if "groups" in page:
            return [i["id"] for g in page["groups"] for i in g["items"]]
        return [i["id"] for i in page["items"]]

    def test_a_topic_track_lists_only_its_posts(self):
        w = self.world()
        self.assertEqual(self.ids(), [w["a_in"], w["p_ok"], w["a_in_old"]])            # newest first, unread
        self.assertEqual(self.ids(filter="all"), [w["a_in"], w["p_ok"], w["a_in_old"]])
        every = {w["a_wait"], w["a_in"], w["a_out"], w["a_in_old"]}                    # the folder's every post
        self.assertEqual(set(self.ids(all_sources=True)), every)
        self.assertEqual(set(self.ids(view="by_source")), {w["a_in"], w["p_ok"], w["a_in_old"]})
        self.assertEqual(set(self.ids(view="by_source", all_sources=True)), every)

    def test_later_kept_and_history_too(self):
        w = self.world()
        for pid in (w["a_in"], w["a_out"]):
            self.cur.execute("INSERT INTO post_reader_state (post_id, later_at, starred_at, read_at) "
                             "VALUES (%s, now(), now(), now())", (pid,))
            self.cur.execute("INSERT INTO post_interactions (post_id, interaction_type) VALUES (%s, 'opened')", (pid,))
        for f in ("later", "starred", "history"):
            self.assertEqual(self.ids(filter=f), [w["a_in"]], f)
            self.assertEqual(set(self.ids(filter=f, all_sources=True)), {w["a_in"], w["a_out"]}, f)

    def test_a_plain_folder_and_mark_x_off_are_unchanged(self):
        a, b = self.post(title="one"), self.post(title="two")
        self.assertEqual(set(self.ids()), {a, b})                                      # no description: a folder
        w = self.world()
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertEqual(set(self.ids()), {a, b, w["a_wait"], w["a_in"], w["a_out"], w["a_in_old"]})
        self.assertIsNone(track_feed.restrict(self.cur, FeedScope("folder", self.folder)).only)

    def test_other_scopes_are_not_restricted(self):
        self.world()
        for scope in (FeedScope("all"), FeedScope("source", self.source)):
            self.assertIs(track_feed.restrict(self.cur, scope), scope)

    def test_mark_read_up_to_here_marks_only_its_posts(self):
        w = self.world()
        top = FeedCursor(NOW + timedelta(minutes=1), w["a_wait"])
        bottom = FeedCursor(NOW - timedelta(minutes=10), w["p_out"])
        got = self.reader.mark_read_through(FeedScope("folder", self.folder), bottom, top)
        self.assertEqual(set(got["ids"]), {w["a_in"], w["p_ok"], w["a_in_old"]})
        self.assertEqual(self.ids(), [])
        self.assertEqual(set(self.ids(all_sources=True)), {w["a_wait"], w["a_out"]})   # still unread
        got = self.reader.mark_read_through(FeedScope("folder", self.folder), bottom, top, all_sources=True)
        self.assertEqual(set(got["ids"]), {w["a_wait"], w["a_out"]})

    def test_the_api_takes_all_sources(self):
        w = self.world()
        previous = registry.use(SimpleNamespace(db_url=db_url(), reader=self.reader))
        self.addCleanup(registry.use, previous)
        q = {"scope": f"folder:{self.folder}", "limit": 100}
        status, body = call("GET", "/api/feed", query=q)
        self.assertEqual(status, 200, body)
        self.assertEqual([i["id"] for i in body["items"]], [w["a_in"], w["p_ok"], w["a_in_old"]])
        _, body = call("GET", "/api/feed", query={**q, "all_sources": "1"})
        self.assertEqual(len(body["items"]), 4)
        top = FeedCursor(NOW + timedelta(minutes=1), w["a_wait"]).encode()
        bottom = FeedCursor(NOW - timedelta(minutes=10), w["p_out"]).encode()
        status, body = call("PUT", "/api/feed/read", body={"scope": f"folder:{self.folder}", "through_cursor": bottom,
                                                           "newest_cursor": top})
        self.assertEqual((status, len(body["ids"])), (200, 3), body)

    def test_the_count_and_the_waiting(self):
        w = self.world()
        self.assertEqual(self.counts()[self.folder], {"unread": 3, "discover": 1, "count": 4, "waiting": 1})
        scope = track_feed.restrict(self.cur, FeedScope("folder", self.folder))
        self.assertEqual(ReaderRepository().scope_unread(self.cur, scope), 3)
        self.plan()
        self.judge(w["a_wait"], verdict(False, 0.9))
        self.assertEqual(self.counts()[self.folder]["waiting"], 0)

    def counts(self):
        status, body = call("GET", "/api/markx/tracks/counts")
        self.assertEqual(status, 200, body)
        return body["by_track"]
