"""0207 (Stealth v10.18): a track's evolving sub-topics, a digest per sub-topic, "new since you looked", the tools in
use, and the track's finders and source suggestions fixed for practitioner tools.

  - sub-topics found from the posts' vectors: groups appear, keep their ids across rebuilds, a quiet one fades, an
    emptied one closes; the owner's rename, merge, split, add and lock are kept by the clustering;
  - named by the worker (subtopics-v2) and digested (digest-v1): asked once per members, citations checked;
  - seen: the reader's looks, each item's joined time and each section's joined times on the page;
  - tools in use: tools named by 2+ voices of the track's posts in, linked to their entities; never an org, a generic
    word or a post the owner marked out;
  - finders: the track's own posts in teach the word finder without any owner label; a passive post naming a tool the
    track's practitioners discuss is put up (`tool`);
  - suggestions: a source is suggested by the share of its posts in the track, not by how many.
Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

from insight_core.markx import finders, repo, schemas, tasks, track_subtopics as TS, track_tools, tracks, validate
from insight_core.tests._db import clear_tables, insert_scratch_source
from insight_core.tests.test_markx_api import call
from insight_core.tests.test_markx_tracks import DAY, NOW, TRACK_TABLES, _Tracks, unit, verdict

import unittest

SUB_TABLES = TRACK_TABLES + ("mx_track_subtopic_members", "mx_track_subtopic_asks", "mx_track_seen",
                             "mx_track_places", "mx_track_places_state", "mx_track_changes", "mx_kept_pages")


class Pure(unittest.TestCase):
    def test_the_kinds_guides_and_planners(self):
        self.assertEqual((schemas.KINDS["subtopics"].guide, schemas.KINDS["digest"].guide), ("subtopics-v2", "digest-v1"))
        for g in ("subtopics-v2", "digest-v1"):
            self.assertTrue(schemas.guide_body(g).startswith("#"))
        for k in ("track", "subtopics", "digest"):
            self.assertIn(k, tasks.PLANNERS)

    def test_how_many_subtopics(self):
        self.assertEqual(TS.target(TS.MIN_POSTS - 1), 0)
        self.assertEqual(TS.target(TS.MIN_POSTS), TS.K_MIN)
        self.assertEqual(TS.target(10_000), TS.K_MAX)
        self.assertLessEqual(TS.target(300), TS.K_MAX)

    def test_a_naming_answer_is_checked(self):
        q = "TRACK: T\nBelongs: b\n\nGROUPS:\n[g1] 5 posts\n- a — x\n[g2] 4 posts\n- b — y"
        self.assertEqual(TS.keys_of(q), ["g1", "g2"])
        ok = {"names": [{"key": "g1", "name": "Terminal tools", "definition": "d"}, {"key": "g2", "name": "Skills"}]}
        self.assertIsNone(validate.check("subtopics", ok, q)[1])
        self.assertIn("g3", validate.check("subtopics", {"names": [{"key": "g3", "name": "S"}]}, q)[1])
        self.assertIn("twice", validate.check("subtopics", {"names": [{"key": "g1", "name": "S"},
                                                                      {"key": "g2", "name": "s"}]}, q)[1])
        self.assertIn("named twice", validate.check("subtopics", {"names": [{"key": "g1", "name": "S"},
                                                                            {"key": "g1", "name": "T"}]}, q)[1])
        self.assertIn("one line", validate.check("subtopics", {"names": [{"key": "g1", "name": "S", "definition": "a\nb"}]}, q)[1])

    def test_a_digest_answer_is_checked(self):
        q = "TRACK: T\nSUB-TOPIC: S\n\nPOSTS:\n[1] a, 2026-11-01: x\n[2] b, 2026-11-02: y"
        self.assertEqual(TS.numbered(q), 2)
        ok = {"points": [{"text": "Two builders ship a terminal for agents.", "cites": [1, 2]},
                         {"text": "One reports it halves context switches.", "cites": [2]}]}
        self.assertIsNone(validate.check("digest", ok, q)[1])
        self.assertIn("post 3", validate.check("digest", {"points": [{"text": "a", "cites": [3]},
                                                                     {"text": "b", "cites": [1]}]}, q)[1])
        self.assertIsNotNone(validate.check("digest", {"points": [{"text": "a", "cites": []},
                                                                  {"text": "b", "cites": [1]}]}, q)[1])
        self.assertIsNotNone(validate.check("digest", {"points": [{"text": "a", "cites": [1]}]}, q)[1])   # 2-4 points

    def test_what_teaches_the_finders(self):
        placed = [{"post_id": "a", "place": "track", "verdict": True, "confidence": 0.9, "label": None},
                  {"post_id": "b", "place": "track", "verdict": True, "confidence": 0.5, "label": None},
                  {"post_id": "c", "place": "track", "verdict": False, "confidence": 0.9, "label": "in"},
                  {"post_id": "d", "place": "discover", "verdict": True, "confidence": 0.95, "label": None},
                  {"post_id": "e", "place": "joined", "verdict": True, "confidence": 0.85, "label": None},
                  {"post_id": "f", "place": "track", "verdict": True, "confidence": 0.95, "label": None}]
        self.assertEqual(sorted(finders.taught(placed, neg=["f"])), ["a", "c", "e"])
        self.assertIn("tool", finders.FINDERS)
        self.assertEqual(track_tools.judged_in(placed), ["a", "b", "c", "d", "e", "f"])


class _Subtopics(_Tracks):
    def setUp(self):
        super().setUp()
        clear_tables(self.cur, SUB_TABLES)
        self.addCleanup(clear_tables, self.cur, SUB_TABLES)
        self.describe("Tools and methods practitioners use or build to work with AI agents")
        self.groups = {}

    def group(self, axis, n, *, at=None, source=None, title="post"):
        """n active posts around one axis of the vector space, judged in: their ids."""
        ps = []
        for k in range(n):
            p = self.post(title=f"{title} {axis}.{k}", source=source, at=at or NOW - k * timedelta(hours=1))
            self.vector(p, unit((axis, 1.0), (100 + (k % 7), 0.25), (200 + axis, 0.1 * (k % 3))))
            ps.append(p)
        self.plan(days=None)
        for k, p in enumerate(ps):
            self.judge(p, verdict(sub=f"group {axis}", why=f"About thing {axis}, number {k}."))
        return ps

    def page(self):
        """The page as the jobs process keeps it after the clustering or an answer (the API alone sends a kept page
        until the owner changes something: 0206)."""
        self.cur.execute("DELETE FROM mx_kept_pages WHERE page = 'track'")
        return super().page()

    def refresh(self, **kw):
        with self.conn.transaction():
            return TS.refresh(self.cur, **kw)

    def sections(self):
        return {s["name"]: s for s in self.page()["sections"]}


class Clustering(_Subtopics):
    def test_groups_appear_keep_their_ids_and_fade(self):
        a, b, c = self.group(1, 10), self.group(2, 9), self.group(3, 8)
        got = self.refresh()
        self.assertEqual(got[self.folder]["new"], 3)
        mem = TS.members(self.cur, self.folder)
        for g in (a, b, c):
            self.assertEqual(len({mem[p] for p in g}), 1, "one group, one sub-topic")
        self.assertEqual(len({mem[a[0]], mem[b[0]], mem[c[0]]}), 3)
        ids = {mem[a[0]], mem[b[0]], mem[c[0]]}
        self.assertEqual(self.refresh(), {}, "nothing changed: not clustered again")
        names = {s["name"] for s in self.page()["sections"]}
        self.assertEqual(names, {"Group 1", "Group 2", "Group 3"})   # until Haiku names them: the judge's words
        # more posts of an old group keep its id; a new group appears
        a2 = self.group(1, 4, title="more")
        d = self.group(4, 8)
        self.refresh()
        mem = TS.members(self.cur, self.folder)
        self.assertEqual({mem[p] for p in a + a2}, {TS.members(self.cur, self.folder)[a[0]]})
        self.assertTrue(ids <= set(mem.values()), "the old sub-topics keep their ids")
        self.assertEqual(len(set(mem.values())), 4)
        self.assertNotIn(mem[d[0]], ids)
        # a sub-topic whose newest post is older than FADE_DAYS is quiet, shown last
        self.cur.execute("UPDATE mx_track_subtopics SET last_member_at = now() - interval '40 days', "
                         "created_at = now() - interval '60 days' WHERE id = %s", (mem[c[0]],))
        secs = self.page()["sections"]
        self.assertEqual(secs[-1]["state"], "quiet")
        self.assertEqual(secs[-1]["id"], mem[c[0]])
        # posts that leave the track leave their sub-topic; one left with none is closed
        for p in c:
            self.label(p, "out")
        self.refresh()
        self.cur.execute("SELECT valid_to IS NOT NULL FROM mx_track_subtopics WHERE id = %s", (mem[c[0]],))
        self.assertTrue(self.cur.fetchone()[0])

    def test_too_few_posts_have_no_subtopics(self):
        self.group(1, TS.MIN_POSTS - 1)
        self.refresh()
        self.assertEqual(TS.current(self.cur, self.folder), [])
        secs = self.page()["sections"]
        self.assertEqual([s["name"] for s in secs], ["In this track"])

    def test_the_owners_edits_are_kept(self):
        a, b = self.group(1, 10), self.group(2, 9)
        self.refresh()
        mem = TS.members(self.cur, self.folder)
        sa, sb = mem[a[0]], mem[b[0]]
        status, subs = call("POST", f"/api/markx/tracks/{self.folder}/subtopics",
                            body={"action": "rename", "id": sa, "name": "Terminal tools"})
        self.assertEqual(status, 200, subs)
        renamed = next(s for s in subs if s["id"] == sa)
        self.assertEqual((renamed["name"], renamed["locked"]), ("Terminal tools", True))   # in place: the same id
        _, subs = call("POST", f"/api/markx/tracks/{self.folder}/subtopics", body={"action": "merge", "id": sa, "ids": [sb]})
        self.assertEqual([s["id"] for s in subs], [sa])
        self.refresh()
        mem = TS.members(self.cur, self.folder)
        self.assertEqual({mem[p] for p in a + b}, {sa}, "the merge is kept by the next clustering")
        _, subs = call("POST", f"/api/markx/tracks/{self.folder}/subtopics",
                       body={"action": "split", "id": sa, "name": "Group two again", "keys": ["group 2"]})
        new = next(s for s in subs if s["name"] == "Group two again")
        self.refresh()
        mem = TS.members(self.cur, self.folder)
        self.assertEqual({mem[p] for p in b}, {new["id"]})
        self.assertEqual({mem[p] for p in a}, {sa})
        t = tracks.get(self.cur, self.folder)
        self.assertIn("Sub-topics: Group two again; Terminal tools", tracks.header(self.cur, t))
        self.assertEqual(call("POST", f"/api/markx/tracks/{self.folder}/subtopics", body={"action": "explode"})[0], 400)


class NamesAndDigests(_Subtopics):
    def setUp(self):
        super().setUp()
        self.a, self.b, self.c = self.group(1, 10), self.group(2, 9), self.group(3, 8)
        self.refresh()

    def test_named_once_by_the_worker_and_never_over_the_owner(self):
        with self.conn.transaction():
            self.assertEqual(TS.plan_names(self.cur), 1)
        _, body = self.lease("subtopics")
        task = body["tasks"][0]
        keys = TS.keys_of(task["input"])
        self.assertEqual(len(keys), 3)
        self.assertIn("GROUPS:", task["input"])
        _, got = self.answer((task["id"], {"names": [{"key": k, "name": f"Name {k}", "definition": "what it holds"}
                                                     for k in keys]}))
        self.assertEqual(got["valid"], 1, got)
        names = {s["name"] for s in self.page()["sections"]}
        self.assertEqual(names, {"Name g1", "Name g2", "Name g3"})
        self.assertEqual({s["named_by"] for s in self.page()["sections"]}, {"haiku"})
        with self.conn.transaction():
            self.assertEqual(TS.plan_names(self.cur), 0, "named, members unchanged: not asked again")
        # most of a sub-topic's members changed since it was named: asked again (a locked one never)
        sid = TS.members(self.cur, self.folder)[self.a[0]]
        self.cur.execute("UPDATE mx_track_subtopics SET named_members = '{}' WHERE id = %s", (sid,))
        with self.conn.transaction():
            self.assertEqual(TS.plan_names(self.cur), 1)
        self.cur.execute("UPDATE mx_tasks SET status = 'answered' WHERE kind = 'subtopics'")
        self.cur.execute("UPDATE mx_track_subtopics SET locked = true WHERE id = %s", (sid,))
        with self.conn.transaction():
            self.assertEqual(TS.plan_names(self.cur), 0)

    def name_all(self):
        with self.conn.transaction():
            TS.plan_names(self.cur)
        _, body = self.lease("subtopics")
        task = body["tasks"][0]
        _, got = self.answer((task["id"], {"names": [{"key": k, "name": f"Name {k}", "definition": "what it holds"}
                                                     for k in TS.keys_of(task["input"])]}))
        self.assertEqual(got["valid"], 1, got)

    def test_haiku_places_the_posts_and_the_clustering_keeps_its_placements(self):
        with self.conn.transaction():
            self.assertEqual(TS.plan_place(self.cur), 0, "nothing named yet: nothing to place into")
        self.name_all()
        with self.conn.transaction():
            self.assertEqual(TS.plan_place(self.cur), 2)                 # 27 posts, 20 a question
        with self.conn.transaction():
            self.assertEqual(TS.plan_place(self.cur), 0, "asked: not again while waiting")
        _, body = self.lease("subtopic_place")
        first = next(t for t in body["tasks"] if t["input"].count("\n[p") == TS.PLACE_ITEMS)
        subs, posts = TS.place_keys(first["input"])
        self.assertEqual((len(subs), len(posts)), (3, TS.PLACE_ITEMS))
        self.cur.execute("SELECT subtopic_ids::text[], post_ids::text[] FROM mx_track_subtopic_asks WHERE task_id = %s",
                         (first["id"],))
        sids, pids = self.cur.fetchone()
        by_key = dict(zip(posts, pids))
        loner = by_key["p1"]
        answer = {"placements": [{"post": p, "subtopic": "none" if p == "p1" else subs[-1]} for p in posts]}
        self.assertIn("not placed", validate.check("subtopic_place", {"placements": answer["placements"][:3]},
                                                   first["input"])[1])
        _, got = self.answer((first["id"], answer))
        self.assertEqual(got["valid"], 1, got)
        mem = TS.members(self.cur, self.folder)
        self.assertNotIn(loner, mem, "placed in none: Other")
        self.assertTrue(all(mem[by_key[p]] == sids[-1] for p in posts if p != "p1"))
        self.refresh(force=True)
        mem = TS.members(self.cur, self.folder)
        self.assertNotIn(loner, mem, "the clustering leaves Haiku's 'none'")
        self.assertTrue(all(mem[by_key[p]] == sids[-1] for p in posts if p != "p1"), "nor its placements")
        self.cur.execute("SELECT by FROM mx_track_subtopic_members WHERE post_id = %s", (by_key["p2"],))
        self.assertEqual(self.cur.fetchone()[0], "haiku")

    def test_a_digest_with_citations_asked_only_when_its_posts_change(self):
        with self.conn.transaction():
            self.assertEqual(TS.plan_digests(self.cur), 3)
        _, body = self.lease("digest")
        self.assertEqual(len(body["tasks"]), 3)
        task = next(t for t in body["tasks"] if "SUB-TOPIC: Group 1" in t["input"])
        n = TS.numbered(task["input"])
        self.assertEqual(n, TS.DIGEST_ITEMS)
        self.assertIn("SUB-TOPIC: Group 1", task["input"])
        _, got = self.answer((task["id"], {"points": [{"text": "Builders ship thing 1.", "cites": [1, 2]},
                                                      {"text": "One measures it.", "cites": [3]}]}))
        self.assertEqual(got["valid"], 1, got)
        sec = self.sections()["Group 1"]
        self.assertEqual(len(sec["digest"]["points"]), 2)
        self.assertFalse(sec["digest"]["stale"])
        shown = [it["post_id"] for it in sec["items"]]
        self.assertEqual(sec["digest"]["points"][0]["cites"], shown[:2], "citations map to the newest posts")
        _, bad = self.answer((next(t for t in body["tasks"] if t["id"] != task["id"])["id"],
                              {"points": [{"text": "x", "cites": [99]}, {"text": "y", "cites": [1]}]}))
        self.assertEqual(bad["valid"], 0)
        self.cur.execute("UPDATE mx_tasks SET status = 'answered' WHERE kind = 'digest'")
        with self.conn.transaction():
            self.assertEqual(TS.plan_digests(self.cur), 0, "within DIGEST_EVERY: not asked")
        self.cur.execute("UPDATE mx_track_subtopic_asks SET created_at = now() - interval '13 hours'")
        with self.conn.transaction():
            self.assertEqual(TS.plan_digests(self.cur), 0, "the same newest posts: not asked again")
        self.group(1, 2, title="newer", at=NOW + timedelta(minutes=5))
        self.refresh()
        self.assertTrue(self.sections()["Group 1"]["digest"]["stale"])
        with self.conn.transaction():
            self.assertEqual(TS.plan_digests(self.cur), 1, "new posts in it: asked again")


class Seen(_Subtopics):
    def test_looks_and_what_joined_since(self):
        a = self.group(1, 10)
        self.refresh()
        sid = TS.members(self.cur, self.folder)[a[0]]
        status, got = call("GET", f"/api/markx/tracks/{self.folder}/seen")
        self.assertEqual((status, got), (200, {"track": None, "subtopics": {}}))
        _, got = call("POST", f"/api/markx/tracks/{self.folder}/seen", body={})
        self.assertIsNone(got["before"]["track"])
        self.assertIsNotNone(got["now"]["track"])
        _, got = call("POST", f"/api/markx/tracks/{self.folder}/seen", body={"subtopic": sid})
        self.assertEqual(set(got["now"]["subtopics"]), {sid})
        self.assertEqual(call("POST", f"/api/markx/tracks/{self.folder}/seen", body={"subtopic": str(uuid.uuid4())})[0], 404)
        self.assertEqual(call("POST", f"/api/markx/tracks/{uuid.uuid4()}/seen", body={})[0], 404)
        sec = self.page()["sections"][0]
        self.assertEqual(len(sec["joined"]), 10)
        self.assertTrue(all(it["joined_at"] for it in sec["items"]))
        self.assertEqual(sec["joined"], sorted(sec["joined"], reverse=True))


class Tools(_Subtopics):
    def mention(self, post, name, etype="software", *, entity=None):
        with self.conn.transaction():
            task_id, _ = tasks.entities_task(self.cur, post)
            cid = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                                answer={"entities": []})
            repo.add_mentions(self.cur, post_id=post, guide="ent-v3", call_id=cid, mentions=[
                {"span": name, "name": name, "name_key": tasks.name_key(name), "type": etype, "role": "subject",
                 "maker": None, "family": None, "version": None, "variant": None, "size": None, "build": None}])
            if entity is None:
                self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, status)
                                    VALUES (%s, %s, %s, 'thing', 'provisional') RETURNING id::text""",
                                 (etype, name, tasks.name_key(name) + uuid.uuid4().hex[:4]))
                entity = self.cur.fetchone()[0]
                self.addCleanup(self.cur.execute, "DELETE FROM mx_entities WHERE id = %s", (entity,))
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (entity, post))
        return entity

    def test_tools_by_voices_linked_and_found(self):
        third = insert_scratch_source(self.cur, platform="rss", enabled=True, settings_json=json.dumps({"display_name": "A builder"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (third,))
        self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (self.folder, third))
        a = self.group(1, 3)
        b = self.group(2, 2, source=third)
        term = self.mention(a[0], "Vexterm")
        self.mention(b[0], "Vexterm", entity=term)            # two voices: the panel
        lone = self.mention(a[1], "Solotool")                  # one voice: not
        self.mention(a[2], "Acme Labs", "org")                 # an org is not a tool
        tools = {t["name"]: t for t in self.page()["tools"]}
        self.assertEqual(set(tools), {"Vexterm"})
        self.assertEqual((tools["Vexterm"]["voices"], tools["Vexterm"]["posts"], tools["Vexterm"]["id"]), (2, 2, term))
        self.assertNotIn(lone, [t["id"] for t in self.page()["tools"]])
        # the tool finder: a passive post naming the tool is put up for judging, found by "tool"
        self.desc_vector(unit((0, 1)))
        far = self.post(title="A note on a terminal", source=self.other)
        self.vector(far, unit((50, 1)))
        self.mention(far, "Vexterm", entity=term)
        self.plan()
        self.cur.execute("SELECT found_by FROM mx_track_items WHERE post_id = %s", (far,))
        self.assertIn("tool", self.cur.fetchone()[0])
        # a post the owner marks out no longer counts
        self.label(b[0], "out")
        self.assertEqual(self.page()["tools"], [])


class Teaching(_Subtopics):
    def test_the_domain_finder_learns_from_the_tracks_posts_without_labels_the_words_do_not(self):
        ps = []
        for k in range(4):
            p = self.post(title=f"Shipping with the zorbulator harness, part {k}",
                          text=f"Our zorbulator harness setup, note {k}: hooks, skills and verification.",
                          links=[(f"https://example.com/zorbulator/{k}", "the harness")])
            ps.append(p)
        self.plan(days=None)
        for p in ps:
            self.judge(p, verdict(conf=0.9))
        rest = [self.post(title=f"Something else entirely {k}", source=self.other) for k in range(80)]
        self.cur.execute("UPDATE posts SET search_vector = to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(content,'')) "
                         "WHERE id = ANY(%s::uuid[])", (ps + rest,))
        t = tracks.get(self.cur, self.folder)
        prep = finders.prepare(self.cur, t, tracks.examples(self.cur, self.folder))
        self.assertEqual(prep["learned"]["pos"], [], "no owner label")
        self.assertEqual(prep["learned"]["taught"], 4)
        self.assertIn("example.com", prep["learned"]["domains"])
        # measured (0207): words taught by a track's own posts were its sources' language, not its topic: owner ✓ only
        self.assertNotIn("zorbulator", prep["learned"]["words"])


class Suggestions(_Subtopics):
    def test_a_source_is_suggested_by_its_share_not_its_count(self):
        big = insert_scratch_source(self.cur, platform="rss", enabled=True, settings_json=json.dumps({"display_name": "Big"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (big,))
        self.desc_vector(unit((0, 1)))
        mine = []
        for k in range(4):
            p = self.post(title=f"fit {k}", source=self.third, at=NOW - k * DAY)
            self.vector(p, unit((0, 1), (3, 0.2)))
            mine.append(p)
        many = []
        for k in range(6):
            p = self.post(title=f"many {k}", source=big, at=NOW - k * DAY)
            self.vector(p, unit((0, 1), (3, 0.2)))
            many.append(p)
        for k in range(80):                                  # the big source posts much else
            self.post(title=f"else {k}", source=big, at=NOW - (k % 20) * DAY)
        self.plan()
        for p in mine + many:
            self.judge(p, verdict(conf=0.9))
        with self.conn.transaction():
            got = tracks.suggestions(self.cur, self.folder, now=NOW + DAY)
        self.assertEqual([s["source_id"] for s in got], [self.third])
        self.assertEqual((got[0]["n"], got[0]["of"]), (4, 4))


if __name__ == "__main__":
    unittest.main()
