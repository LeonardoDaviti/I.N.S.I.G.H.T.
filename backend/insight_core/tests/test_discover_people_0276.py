"""Issue 0276 (Stealth v10.33): Discover's people and makers. Which addresses are a person's or maker's account, the
ranking by the posts that brought them (a post once however it names them; 3+ posts or 2+ sources), a person's
accounts folded and a followed person left out only where the handles module links them, where each is followed;
and on a database: the track's own posts only (never its Discover), News, links, mentions, reposts, makers, and the
list kept by the "discover" job and served. Invented names only."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import discover_people as P

NOW = datetime(2026, 11, 21, tzinfo=timezone.utc)
CODE = "https://" + "git" + "hub.com/"


def hit(pid, key, *, where="track:Agents", word="x", how="quote", days=1, name="", source="s1"):
    return P.Hit(pid, where, key, word, how, f"https://example.org/{pid}", f"post {pid}", NOW - timedelta(days=days),
                 name, source)


class PersonKey(unittest.TestCase):
    def test_accounts_are_people(self):
        self.assertEqual(P.person_key("https://x.com/janedoe_dev/status/123"), ("x.com/janedoe_dev", "x"))
        self.assertEqual(P.person_key(CODE + "JaneDoe/agent-kit"), ("github.com/janedoe", "code"))
        self.assertEqual(P.person_key("https://huggingface.co/AcmeLab/Widget-7B"), ("huggingface.co/acmelab", "hub"))
        self.assertEqual(P.person_key("https://www.youtube.com/@JaneBuilds"), ("youtube.com/@janebuilds", "youtube"))
        self.assertEqual(P.person_key("https://t.me/acmenews/12"), ("t.me/acmenews", "telegram"))

    def test_no_person(self):
        for url in ("https://reddit.com/r/somesub/comments/x", "https://janedoe.example/2026/post",
                    "https://x.com/i/status/1", "https://x.com/search?q=widget", CODE + "features/copilot",
                    "https://news.ycombinator.com/item?id=1", "https://www.youtube.com/playlist?list=PL1",
                    "https://www.theverge.com/tech/123/a-story", ""):
            self.assertIsNone(P.person_key(url), url)

    def test_handle_of(self):
        self.assertEqual(P.handle_of("github.com/janedoe"), ("github", "janedoe"))
        self.assertEqual(P.handle_of("huggingface.co/JaneD"), ("hf", "janed"))
        self.assertEqual(P.handle_of("x.com/jane"), ("x", "jane"))
        self.assertIsNone(P.handle_of("youtube.com/@jane"))


class Rank(unittest.TestCase):
    def test_posts_rank_once_each(self):
        hits = [hit("p1", "x.com/jane", how="quote"), hit("p1", "x.com/jane", how="mention"),
                hit("p1", "x.com/jane", where="news"), hit("p2", "x.com/jane", where="track:Local", source="s2"),
                hit("p3", "x.com/bob"), hit("p4", "x.com/bob", source="s3"), hit("p5", "x.com/bob"),
                hit("p6", "x.com/once")]
        got = P.rank(hits)
        self.assertEqual([s.key for s in got], ["x.com/bob", "x.com/jane"])   # 3 posts from 2 sources, then 2 from 2 sources
        jane = got[1]
        self.assertEqual(len(jane.posts), 2)
        self.assertEqual(jane.tracks, {"Agents", "Local"})
        self.assertEqual(jane.news, {"p1"})
        self.assertEqual(dict(jane.hows), {"quote": 2, "mention": 1})
        self.assertEqual([h.post_id for h in jane.evidence], ["p1", "p2"])

    def test_floor_two_posts_one_source_is_out(self):
        got = P.rank([hit("a1", "x.com/oneoff"), hit("a2", "x.com/oneoff"),
                      hit("b1", "x.com/two", source="s1"), hit("b2", "x.com/two", source="s2")])
        self.assertEqual([s.key for s in got], ["x.com/two"])

    def test_tracks_break_ties_and_skip(self):
        hits = [hit(f"a{i}", "x.com/aa", source=f"s{i}") for i in range(3)] + \
               [hit("b0", "x.com/bb", where="track:One"), hit("b1", "x.com/bb", where="track:Two", source="s2"),
                hit("b2", "x.com/bb", where="track:Two")] + [hit(f"c{i}", "x.com/cc", source=f"s{i}") for i in range(3)]
        got = P.rank(hits, skip=lambda k, w: k == "x.com/cc")
        self.assertEqual([s.key for s in got], ["x.com/bb", "x.com/aa"])

    def test_evidence_newest_first_and_capped(self):
        got = P.rank([hit(f"p{i}", "x.com/jane", days=i, source=f"s{i % 2}") for i in range(1, 9)])[0]
        self.assertEqual([h.post_id for h in got.evidence], ["p1", "p2", "p3", "p4", "p5"])
        self.assertEqual(len(got.posts), 8)

    def test_people_fold_and_followed(self):
        people = P.People(handles={("github", "janedoe"): ("e1", "Jane Doe"), ("hf", "jdoe"): ("e1", "Jane Doe"),
                                   ("github", "simon"): ("e2", "Simon Example")}, followed={"e2"})
        hits = [hit("p1", CODE[8:] + "janedoe", word="code", how="link"),
                hit("p2", "huggingface.co/jdoe", word="hub", how="link", source="s2"),
                hit("p3", CODE[8:] + "simon", word="code"), hit("p4", CODE[8:] + "simon", word="code"),
                hit("p5", CODE[8:] + "simon", word="code"),
                hit("p6", "x.com/janedoe"), hit("p7", "x.com/janedoe", source="s2"), hit("p8", "x.com/janedoe")]
        got = {s.key: s for s in P.rank(hits, people=people)}
        self.assertEqual(set(got), {"person:e1", "x.com/janedoe"})   # same handle on X: another account (handles.py)
        self.assertEqual(got["person:e1"].name, "Jane Doe")
        self.assertEqual(got["person:e1"].accounts, {"github.com/janedoe", "huggingface.co/jdoe"})
        out = P.shown(got["person:e1"])
        self.assertEqual(out["follow"]["address"], CODE + "janedoe")


class Shown(unittest.TestCase):
    def test_author_follows_through_the_bridge(self):
        s = P.rank([hit("p1", "x.com/jane"), hit("p2", "x.com/jane", where="news", source="s2")])[0]
        with mock.patch("insight_core.ingestion.feed_finder.nitter_origin", return_value="https://bridge.local"):
            out = P.shown(s)
        self.assertEqual(out["kind"], "author")
        self.assertEqual(out["follow"]["address"], "https://x.com/jane")
        self.assertEqual(out["follow"]["feed"], "https://bridge.local/jane/rss")
        self.assertTrue(out["follow"]["ready"])
        self.assertIn("Agents", out["why"])
        self.assertIn("News (1)", out["why"])
        self.assertEqual(out["sources"], 2)

    def test_no_bridge_is_not_ready(self):
        with mock.patch("insight_core.ingestion.feed_finder.nitter_origin", return_value=None):
            self.assertFalse(P.followable("x.com/jane", "x")["ready"])

    def test_code_owner_and_hub_org(self):
        self.assertEqual(P.followable("github.com/jane", "code")["feed"], CODE + "jane.atom")
        self.assertIn("page watching", P.followable("huggingface.co/acmelab", "hub")["via"])

    def test_maker_carries_official_channels(self):
        s = P.rank([hit(f"p{i}", "maker:m1", word="maker", how="maker", name="Acme", source=f"s{i % 2}") for i in range(3)])[0]
        out = P.shown(s, [{"key": "x.com/acme", "kind": "x", "state": "would_add", "follow": "https://x.com/acme",
                           "source_id": None}])
        self.assertEqual(out["kind"], "maker")
        self.assertEqual(out["name"], "Acme")
        self.assertEqual(out["channels"][0]["address"], "https://x.com/acme")
        self.assertTrue(out["follow"]["ready"])
        self.assertIsNone(P.shown(s)["follow"])


# ---- on a database ---------------------------------------------------------------------------------------------

from insight_core.tests._db import insert_scratch_source, requires_test_db  # noqa: E402
from insight_core.tests.test_markx_scout import _Scout  # noqa: E402


@requires_test_db
class OnTheDatabase(_Scout):
    def setUp(self):
        super().setUp()
        self.cur.execute("DELETE FROM news_posts")
        self.cur.execute("DELETE FROM news_stories")
        self.cur.execute("DELETE FROM system_settings WHERE key = %s", (P.KEY,))
        self.cur.execute("DELETE FROM mx_jobs WHERE job = 'discover'")
        self.third = insert_scratch_source(self.cur, platform="rss", enabled=True)
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (self.third,))
        self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (self.folder, self.third))
        self.addCleanup(self.cur.execute, "DELETE FROM source_folders WHERE source_id = %s", (self.third,))
        self.now = datetime.now(timezone.utc)
        self.cur.execute("SELECT name FROM folders WHERE id = %s", (self.folder,))
        self.where = "track:" + self.cur.fetchone()[0]

    def in_track(self, links=(), *, source=None, title="A printed part", at=None, mention=()):
        p = self.post(title=title, source=source or self.source, at=at, links=[(u, None) for u in links])
        for n, u in enumerate(mention):
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position, kind, boilerplate) "
                             "VALUES (%s, %s, 'x.com', %s, 'mention', true)", (p, u, 100 + n))
        self.judged(p, "active")
        return p

    def news(self, pid):
        self.cur.execute("""INSERT INTO news_stories (id, first_at, voices, reports, shares, mentions, score)
                            VALUES (%s, %s, 2, 1, 1, 0, 1)""", (pid, self.now - timedelta(days=1)))
        self.cur.execute("INSERT INTO news_posts (post_id, news_id, role, voice) VALUES (%s, %s, 'report', 'v')",
                         (pid, pid))

    def entity(self, type_, name):
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, status)
                            VALUES (%s, %s, %s, 'thing', 'provisional') RETURNING id::text""",
                         (type_, name, f"{name.lower()} {uuid.uuid4().hex[:6]}"))
        return self.cur.fetchone()[0]

    def mention(self, post, eid, name):
        from insight_core.markx import repo, tasks
        with self.conn.transaction():
            task_id, _ = tasks.entities_task(self.cur, post)
            cid = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                                answer={"entities": []})
            repo.add_mentions(self.cur, post_id=post, guide="ent-v3", call_id=cid, mentions=[
                {"span": name, "name": name, "name_key": name.lower(), "type": "product", "role": "subject",
                 "maker": None, "family": None, "version": None, "variant": None, "size": None, "build": None}])
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (eid, post))

    def test_window_posts_reads_the_track_never_its_discover(self):
        inside = self.in_track()
        outside = self.post(source=self.other)            # judged in, from a source not in the track: its Discover
        self.judged(outside, "passive")
        old = self.in_track(at=self.now - timedelta(days=40))
        news = self.post(source=self.other)
        self.news(news)
        got = P.window_posts(self.cur, self.now)
        self.assertEqual(got.get(inside), {self.where})
        self.assertNotIn(outside, got)
        self.assertNotIn(old, got)
        self.assertEqual(got.get(news), {"news"})

    def test_hits_links_mentions_reposts_and_makers(self):
        a = self.in_track(["https://x.com/janedoe/status/1890000000000000001", CODE + "JaneDoe/kit"], mention=["https://x.com/bobex"])
        rt = self.post(title="RT by @someone: a thing", source=self.third)
        self.cur.execute("UPDATE posts SET url = 'https://x.com/carol/status/1890000000000000009' WHERE id = %s", (rt,))
        self.judged(rt, "active")
        maker = self.entity("org", "Acme Labs")
        thing = self.entity("product", "Widget")
        from insight_core.markx import entity_facts
        entity_facts.write(self.cur, thing, by="owner", kind="software", maker_id=maker)
        self.mention(a, thing, "Widget")
        rows = P.hits(self.cur, self.now)
        got = {(h.post_id, h.key, h.how) for h in rows}
        self.assertIn((a, "x.com/janedoe", "quote"), got)
        self.assertIn((a, "github.com/janedoe", "link"), got)
        self.assertIn((a, "x.com/bobex", "mention"), got)
        self.assertIn((rt, "x.com/carol", "repost"), got)
        self.assertIn((a, f"maker:{maker}", "maker"), got)
        self.assertEqual({h.source_id for h in rows if h.post_id == rt}, {self.third})

    def test_suggestions_floor_people_and_kept(self):
        for _ in range(3):
            self.in_track(["https://x.com/janedoe/status/1890000000000000001"])                       # 3 posts: in
        self.in_track(["https://x.com/twosrc/status/1890000000000000002"])
        self.in_track(["https://x.com/twosrc/status/1890000000000000003"], source=self.third)        # 2 posts, 2 sources: in
        self.in_track(["https://x.com/oneoff/status/1890000000000000004"])
        self.in_track(["https://x.com/oneoff/status/1890000000000000005"])                           # 2 posts, 1 source: out
        followed = self.entity("person", "Simon Example")
        self.cur.execute("""INSERT INTO mx_entity_handles (entity_id, platform, handle, answer)
                            VALUES (%s, 'github', 'simonex', 'yes')""", (followed,))
        self.cur.execute("INSERT INTO mx_entity_sources (entity_id, source_id, answer) VALUES (%s, %s, 'yes')",
                         (followed, self.third))
        for _ in range(3):
            self.in_track([CODE + "simonex/tool"])                                 # followed as his site: out
        got = P.suggestions(self.cur, self.now)
        self.assertEqual([a["key"] for a in got["authors"]], ["x.com/twosrc"])   # v10.33: 3 posts from 1 source: out
        self.assertEqual(got["authors"][0]["evidence"][0]["where"], self.where)
        first = P.served(self.cur)
        self.assertEqual(first["authors"], [])                                    # nothing kept yet: the job is wanted
        self.assertTrue(first["refreshing"])
        self.cur.execute("SELECT wanted_at IS NOT NULL FROM mx_jobs WHERE job = 'discover'")
        self.assertTrue(self.cur.fetchone()[0])
        out = P.keep(self.cur, self.now)
        self.assertEqual(out["authors"], 1)
        served = P.served(self.cur, limit=1)
        self.assertEqual([a["key"] for a in served["authors"]], ["x.com/twosrc"])
        self.assertFalse(served["refreshing"])
        self.assertFalse(P.due(self.cur))

    def test_the_discover_job_keeps_it(self):
        from insight_core.services import discover_reads
        from insight_core.tests._db import db_url
        self.in_track(["https://x.com/janedoe/status/1890000000000000001"])
        self.in_track(["https://x.com/janedoe/status/1890000000000000009"], source=self.third)   # 2 of your sources
        self.assertTrue(discover_reads.keep_people(db_url())["built"])
        self.assertEqual(discover_reads.keep_people(db_url()), {"built": False})      # KEEP_FOR not over
        self.assertEqual([a["key"] for a in P.served(self.cur)["authors"]], ["x.com/janedoe"])

    def test_the_route_serves_the_kept_list(self):
        from insight_core.tests.test_markx_api import call
        self.cur.execute("INSERT INTO system_settings (key, value, updated_at) VALUES (%s, %s::jsonb, now()) "
                         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                         (P.KEY, json.dumps({"window_days": 30, "posts": 4, "authors": [{"key": "x.com/a"}],
                                             "makers": [], "built_at": "2026-11-21T00:00:00+00:00"})))
        status, body = call("GET", "/api/discover/people")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["authors"], [{"key": "x.com/a"}])
        self.assertFalse(body["refreshing"])


if __name__ == "__main__":
    unittest.main()
