"""Stealth v10.42: sub-tracks and a reader's stack (markx/track_subtracks.py, migration 0176).

A sub-track's posts are its parent's posts in the track; a judged one asks the track judge under its own header
(description, stack, parent); with a stack only the posts whose mentions touch it (a thing under one counts); a rest
one takes the others with no question; a post the parent drops leaves its sub-tracks; the parent's page lists them;
the stack and the shape are the owner's (a new version). Invented names only; synthetic data."""
from __future__ import annotations

import unittest
import uuid

from insight_core.markx import repo, track_kept, track_subtracks, tracks
from insight_core.tests.test_markx_api import call
from insight_core.tests.test_markx_tracks import _Tracks, verdict


class SubTracks(_Tracks):
    def setUp(self):
        super().setUp()
        self.describe("Security and privacy of the tools I use and the world's breaches")
        self.mine = self.child("Mine", "Updates, advisories, new protections and guides for the tools the reader uses")
        self.news = self.child("News", "Breaches, hacks and outages worldwide")
        self.zq = self.entity("Zqphone OS")
        self.zq_build = self.entity("Zqphone OS 2026.11", parent=self.zq, level="version")
        self.other_thing = self.entity("Vrrm Cloud")

    def child(self, name, description):
        self.cur.execute("INSERT INTO folders (name, kind) VALUES (%s, 'track') RETURNING id::text", (name + uuid.uuid4().hex[:4],))
        fid = self.cur.fetchone()[0]
        self.addCleanup(self.cur.execute, "DELETE FROM folders WHERE id = %s", (fid,))
        with self.conn.transaction():
            tracks.set_topic(self.cur, fid, description=description)
        return fid

    def entity(self, name, parent=None, level="thing"):
        self.cur.execute("""INSERT INTO mx_entities (name, key, level, parent, type) VALUES (%s, %s, %s, %s, 'software')
                            RETURNING id::text""", (name, name.lower(), level, parent))
        eid = self.cur.fetchone()[0]
        self.addCleanup(self.cur.execute, "DELETE FROM mx_entities WHERE id = %s", (eid,))
        return eid

    def mention(self, post, eid, name):
        tid, _ = repo.add_task(self.cur, kind="entities", guide="ent-v3", subject_kind="post",
                               input=f"e {uuid.uuid4().hex}", a=post)
        cid = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="test", valid=True, answer={})
        repo.add_mentions(self.cur, post_id=post, guide="ent-v3", call_id=cid,
                          mentions=[{"span": name, "name": name, "name_key": name.lower(), "type": "software",
                                     "role": "subject"}])
        self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND entity_id IS NULL", (eid, post))

    def shape(self, fid, **body):
        status, got = call("PUT", f"/api/markx/tracks/{fid}/shape", body=body)
        self.assertEqual(status, 200, got)
        return got

    def task_of(self, fid, post):
        self.cur.execute("SELECT task_id FROM mx_track_items WHERE track_id = %s AND post_id = %s", (fid, post))
        row = self.cur.fetchone()
        return row and row[0]

    def page_of(self, fid):
        status, body = call("GET", f"/api/markx/tracks/{fid}")
        self.assertEqual(status, 200, body)
        return body

    def in_page(self, body):
        return {it["post_id"] for s in body["sections"] for it in s["items"]}

    def test_the_split_the_stack_gate_and_the_rest(self):
        a = self.post(title="Zqphone OS 2026.11 adds a USB lock")
        b = self.post(title="A cloud host lost a billion records")
        c = self.post(title="Vrrm Cloud outage across Europe")
        d = self.post(title="Zqphone OS maker raises money")
        self.mention(a, self.zq_build, "Zqphone OS 2026.11")    # a thing under the stack's touches it
        self.mention(c, self.other_thing, "Vrrm Cloud")
        self.mention(d, self.zq, "Zqphone OS")
        self.plan()
        for p in (a, b, c, d):
            self.judge(p, verdict())                             # all four in the parent
        self.shape(self.mine, parent=self.folder)
        self.shape(self.news, parent=self.folder, rest=True, sort="news")
        status, body = call("PUT", f"/api/markx/tracks/{self.mine}/stack", body={"things": [self.zq]})
        self.assertEqual(status, 200, body)
        self.assertEqual([t["name"] for t in body["track"]["stack"]], ["Zqphone OS"])
        self.assertEqual(body["track"]["parent"]["id"], self.folder)
        self.plan()
        # only the posts whose mentions touch the stack were asked, under the sub-track's own header
        self.assertIsNotNone(self.task_of(self.mine, a))
        self.assertIsNotNone(self.task_of(self.mine, d))
        self.assertIsNone(self.task_of(self.mine, b))
        self.assertIsNone(self.task_of(self.mine, c))
        self.cur.execute("SELECT input FROM mx_tasks WHERE id = %s", (self.task_of(self.mine, a),))
        text = self.cur.fetchone()[0]
        self.assertIn("The reader uses: Zqphone OS", text)
        self.assertIn("Part of: Prints", text)
        # the judge decides: the release is in, the funding story is not something to act on
        self.cur.execute("SELECT id FROM mx_tasks WHERE id = %s", (self.task_of(self.mine, a),))
        status, got = self.answer((self.task_of(self.mine, a), verdict()), (self.task_of(self.mine, d), verdict(False)))
        self.assertEqual(status, 200, got)
        mine = self.page_of(self.mine)
        self.assertEqual(self.in_page(mine), {a})
        self.assertEqual(self.in_page(self.page_of(self.news)), {b, c, d})   # the rest: no question asked
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'track' AND b = %s", (self.news,))
        self.assertEqual(self.cur.fetchone()[0], 0)
        parent = self.page_of(self.folder)
        listed = {s["id"]: s for s in parent["subtracks"]}
        self.assertEqual((listed[self.mine]["count"], listed[self.news]["count"]), (1, 3))
        self.assertTrue(listed[self.news]["rest"])
        self.assertEqual(listed[self.mine]["items"][0]["post_id"], a)
        # the parent drops a post: it leaves its sub-tracks; the owner's ✓ on a sub-track keeps one there
        self.label(b, "out")
        self.assertNotIn(b, self.in_page(self.page_of(self.news)))
        status, _ = call("POST", f"/api/markx/tracks/{self.news}/labels", body={"post": b, "answer": "in"})
        self.assertEqual(status, 200)
        self.assertIn(b, self.in_page(self.page_of(self.news)))

    def test_kept_placements_follow_the_parent(self):
        a = self.post(title="Zqphone OS 2026.11 adds a USB lock")
        b = self.post(title="A cloud host lost a billion records")
        self.mention(a, self.zq, "Zqphone OS")
        self.plan()
        self.judge(a, verdict())
        self.judge(b, verdict())
        self.shape(self.mine, parent=self.folder)
        self.shape(self.news, parent=self.folder, rest=True)
        with self.conn.transaction():
            track_subtracks.set_stack(self.cur, self.mine, [self.zq])
        self.plan()
        self.answer((self.task_of(self.mine, a), verdict()))
        with self.conn.transaction():
            track_kept.refresh(self.cur, gap=0)
        self.cur.execute("SELECT track_id::text, post_id::text, place FROM mx_track_places WHERE track_id = ANY(%s::uuid[])",
                         ([self.mine, self.news],))
        got = {(t, p): pl for t, p, pl in self.cur.fetchall()}
        self.assertEqual(got[(self.mine, a)], "track")
        self.assertEqual(got[(self.news, a)], "out")              # a sibling holds it
        self.assertEqual(got[(self.news, b)], "track")

    def test_the_shape_and_the_stack_are_checked_and_are_new_versions(self):
        v = tracks.get(self.cur, self.mine)["version"]
        self.shape(self.mine, parent=self.folder)
        self.assertEqual(tracks.get(self.cur, self.mine)["version"], v + 1)
        self.assertEqual(call("PUT", f"/api/markx/tracks/{self.news}/shape", body={"parent": self.mine})[0], 400)
        self.assertEqual(call("PUT", f"/api/markx/tracks/{self.folder}/shape", body={"parent": self.folder})[0], 400)
        self.assertEqual(call("PUT", f"/api/markx/tracks/{self.mine}/shape", body={"parent": self.folder,
                                                                               "sort": "loudest"})[0], 400)
        self.assertEqual(call("PUT", f"/api/markx/tracks/{self.mine}/stack",
                              body={"things": [str(uuid.uuid4())]})[0], 400)
        status, found = call("GET", f"/api/markx/tracks/{self.mine}/stack/find", query={"q": "zqphone"})
        self.assertEqual(status, 200)
        self.assertEqual(found[0]["name"], "Zqphone OS")
        self.cur.execute("""INSERT INTO mx_entities (name, key, maker, type) VALUES ('Zq Vault', 'zq vault', 'Zqphone OS',
                            'software') RETURNING id::text""")
        vault = self.cur.fetchone()[0]                           # made by a thing of the stack: in its closure
        self.addCleanup(self.cur.execute, "DELETE FROM mx_entities WHERE id = %s", (vault,))
        closure = track_subtracks.stack_closure(self.cur, [self.zq])
        self.assertEqual(closure, sorted([self.zq, self.zq_build, vault]))
        p, q = self.post(title="Hardening Zqphone OS"), self.post(title="Unrelated")
        self.mention(p, None, "Zqphone OS")                       # not linked yet: matched by the thing's own name
        self.mention(q, None, "Zqphone")
        self.assertEqual(track_subtracks.touching(self.cur, [p, q], closure), {p})
        listed = {t["id"]: t for t in call("GET", "/api/markx/tracks")[1]}
        self.assertEqual(listed[self.mine]["parent"], self.folder)
        self.shape(self.mine, parent=None)
        self.assertIsNone(tracks.get(self.cur, self.mine)["parent_id"])


if __name__ == "__main__":
    unittest.main()
