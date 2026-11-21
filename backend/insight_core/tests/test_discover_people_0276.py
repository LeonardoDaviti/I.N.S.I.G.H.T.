"""Issue 0276 (Stealth v10.33): Discover's people and makers. Which addresses are a person's or maker's account, the
ranking by the posts that brought them (a post once however it names them), what is skipped, and where each is
followed. Pure: no database. Invented names only."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import discover_people as P

NOW = datetime(2026, 11, 21, tzinfo=timezone.utc)
CODE = "https://" + "git" + "hub.com/"


def hit(pid, key, *, where="track:Agents", word="x", how="quote", days=1, name=""):
    return P.Hit(pid, where, key, word, how, f"https://example.org/{pid}", f"post {pid}", NOW - timedelta(days=days),
                 name)


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
                    "https://news.ycombinator.com/item?id=1", "https://www.youtube.com/playlist?list=PL1", ""):
            self.assertIsNone(P.person_key(url), url)


class Rank(unittest.TestCase):
    def test_posts_rank_once_each(self):
        hits = [hit("p1", "x.com/jane", how="quote"), hit("p1", "x.com/jane", how="mention"),
                hit("p1", "x.com/jane", where="news"), hit("p2", "x.com/jane", where="track:Local"),
                hit("p3", "x.com/bob"), hit("p4", "x.com/bob"), hit("p5", "x.com/bob"),
                hit("p6", "x.com/once")]
        got = P.rank(hits)
        self.assertEqual([s.key for s in got], ["x.com/bob", "x.com/jane"])   # 3 posts, then 2; one post is chance
        jane = got[1]
        self.assertEqual(len(jane.posts), 2)
        self.assertEqual(jane.tracks, {"Agents", "Local"})
        self.assertEqual(jane.news, {"p1"})
        self.assertEqual(dict(jane.hows), {"quote": 2, "mention": 1})
        self.assertEqual([h.post_id for h in jane.evidence], ["p1", "p2"])

    def test_tracks_break_ties_and_skip(self):
        hits = [hit("a1", "x.com/aa"), hit("a2", "x.com/aa"),
                hit("b1", "x.com/bb", where="track:One"), hit("b2", "x.com/bb", where="track:Two"),
                hit("c1", "x.com/cc"), hit("c2", "x.com/cc")]
        got = P.rank(hits, skip=lambda k, w: k == "x.com/cc")
        self.assertEqual([s.key for s in got], ["x.com/bb", "x.com/aa"])

    def test_evidence_newest_first_and_capped(self):
        hits = [hit(f"p{i}", "x.com/jane", days=i) for i in range(1, 9)]
        got = P.rank(hits)[0]
        self.assertEqual([h.post_id for h in got.evidence], ["p1", "p2", "p3", "p4", "p5"])
        self.assertEqual(len(got.posts), 8)


class Shown(unittest.TestCase):
    def test_author_follows_through_the_bridge(self):
        s = P.rank([hit("p1", "x.com/jane"), hit("p2", "x.com/jane", where="news")])[0]
        with mock.patch("insight_core.ingestion.feed_finder.nitter_origin", return_value="https://bridge.local"):
            out = P.shown(s)
        self.assertEqual(out["kind"], "author")
        self.assertEqual(out["follow"]["address"], "https://x.com/jane")
        self.assertEqual(out["follow"]["feed"], "https://bridge.local/jane/rss")
        self.assertTrue(out["follow"]["ready"])
        self.assertIn("Agents", out["why"])
        self.assertIn("News (1)", out["why"])

    def test_no_bridge_is_not_ready(self):
        with mock.patch("insight_core.ingestion.feed_finder.nitter_origin", return_value=None):
            self.assertFalse(P.followable("x.com/jane", "x")["ready"])

    def test_code_owner_and_hub_org(self):
        self.assertEqual(P.followable("github.com/jane", "code")["feed"], CODE + "jane.atom")
        self.assertIn("page watching", P.followable("huggingface.co/acmelab", "hub")["via"])

    def test_maker_carries_official_channels(self):
        s = P.rank([hit("p1", "maker:m1", word="maker", how="maker", name="Acme"),
                    hit("p2", "maker:m1", word="maker", how="maker", name="Acme")])[0]
        out = P.shown(s, [{"key": "x.com/acme", "kind": "x", "state": "would_add", "follow": "https://x.com/acme",
                           "source_id": None}])
        self.assertEqual(out["kind"], "maker")
        self.assertEqual(out["name"], "Acme")
        self.assertEqual(out["channels"][0]["address"], "https://x.com/acme")
        self.assertTrue(out["follow"]["ready"])
        self.assertIsNone(P.shown(s)["follow"])


if __name__ == "__main__":
    unittest.main()
