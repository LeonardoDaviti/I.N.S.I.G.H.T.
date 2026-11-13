"""One Voice module (issue 0189): who a post counts as and how many voices posts are, behind utils/voice.py, with
the engines' rules as named policies. Moving every caller behind it changed no output: on seeded random worlds each
policy gives what the code it replaced gave (tests/legacy/voice_v1016.py, the v10.16 code word for word), the keys
are the stored forms, and the SQL fragments say in a query what the Python says. Byline holds who wrote a post: its
one "RT by @" pattern, repost_of and the repost tests."""
from __future__ import annotations

import random
import unittest
from datetime import datetime, timezone

import psycopg

from insight_core.markx import built
from insight_core.tests._db import db_url, requires_db
from insight_core.tests.legacy import voice_v1016 as old
from insight_core.utils import byline, voice
from insight_core.utils.story_rules import StoryPost

T0 = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
KINDS = ("site", "reddit", "x", "telegram", "youtube", "hn", "saved", "arxiv")
SEEDS = 1500


def _owner(rnd: random.Random) -> object:
    return rnd.choice([None, None, None, "site:pub1.example", "source:s1", "source:s4", "voice:v1", "voice:v2",
                       "reddit:alice"])


def world(rnd: random.Random) -> list:
    """A random story: posts of a few sources, sites and posters, copies of one text, reposters, owners."""
    out = []
    for i in range(rnd.randint(1, 9)):
        kind = rnd.choice(KINDS)
        others = tuple(rnd.sample(["s1", "s2", "s3", "s4", "s5"], rnd.randint(0, 2)))
        p = StoryPost(id=f"p{i}", source_id=rnd.choice(["s1", "s2", "s3", "s4", "s5", "s6"]), kind=kind,
                      own_site=rnd.choice(["pub1.example", "pub2.example", ""]), t=T0,
                      author=rnd.choice([None, "alice", "Bob", "carol"]),
                      content_hash=rnd.choice([None, "h1", "h2"]), text_chars=rnd.choice([50, 500]),
                      reposters=others[1:], author_source=others[0] if others else None)
        p.owner = _owner(rnd)
        p.other_owners = tuple(_owner(rnd) for _ in p.other_sources) if rnd.random() < 0.6 else ()
        out.append(p)
    return out


class Policies(unittest.TestCase):
    """Each policy is the rule its callers counted by before (seeded worlds)."""

    def test_mark_ix_stories_and_news_count_as_before(self):
        for seed in range(SEEDS):
            posts = world(random.Random(seed))
            self.assertEqual(voice.count(posts, voice.Policy.STORIES_IX), old.count_voices(posts), seed)
            self.assertEqual(voice.count(posts, voice.Policy.NEWS_IX), old.count_voices(posts, by_owner=True), seed)
            for p in posts:
                self.assertEqual(p.voice, old.voice(p))
                self.assertEqual(p.place, "source:" + p.source_id if p.kind == "reddit" else old.voice(p))
                self.assertEqual(voice.voice_of(p, voice.Policy.STORIES_IX), old.counted_voice(p))
                self.assertEqual(voice.voice_of(p, voice.Policy.NEWS_IX), old.owner_voice(p))
                self.assertEqual(voice.others_of(p, voice.Policy.STORIES_IX), old.other_voices(p))
                self.assertEqual(voice.others_of(p, voice.Policy.NEWS_IX), old.other_voices(p, by_owner=True))

    def test_mark_x_counts_as_pairing_did(self):
        for seed in range(SEEDS):
            rnd = random.Random(seed)
            said = [voice.Said(rnd.choice("abcde"), rnd.choice(KINDS + (None,)),
                               rnd.choice([None, None, "a", "f"])) for _ in range(rnd.randint(0, 8))]
            self.assertEqual(voice.count(said, voice.Policy.MARKX),
                             old.pairing_voices((s.counts_as or s.source_id, s.kind) for s in said), seed)
            a, b = said[:2] if len(said) >= 2 else (voice.Said("a", "x"), voice.Said("b", "saved"))
            self.assertEqual(voice.independent(a.source_id, a.kind, b.source_id, b.kind),
                             old.is_voice(a.kind) and old.is_voice(b.kind) and a.source_id != b.source_id)
            followed = {"x.com/acme": "a", "t.me/chan": "c"}
            for account in (None, "x.com/acme", "x.com/stranger", "t.me/chan"):
                self.assertEqual(voice.counted_source("z", account, followed), old.counted_source("z", account, followed))

    def test_the_policies_differ_where_the_engines_do(self):
        """The differences are the engines' (0189 lists them): a publication's two sources, a Reddit poster, copies of
        one text, a reposter beside the row's source."""
        def sp(i, src, kind, **kw):
            return StoryPost(id=i, source_id=src, kind=kind, own_site=kw.pop("site", ""), t=T0, **kw)
        two_feeds_one_site = [sp("a", "s1", "site", site="pub.example"), sp("b", "s2", "site", site="pub.example")]
        self.assertEqual(voice.count(two_feeds_one_site, voice.Policy.STORIES_IX), 1)
        self.assertEqual(voice.count([voice.Said(p.source_id, p.kind) for p in two_feeds_one_site], voice.Policy.MARKX), 2)
        copies = [sp("a", "s1", "telegram", content_hash="h", text_chars=500),
                  sp("b", "s2", "telegram", content_hash="h", text_chars=500)]
        self.assertEqual(voice.count(copies, voice.Policy.STORIES_IX), 1)
        self.assertEqual(voice.count([voice.Said(p.source_id, p.kind) for p in copies], voice.Policy.MARKX), 2)
        reposted = [sp("a", "s1", "x", author="acme", author_source="s9")]
        self.assertEqual(voice.count(reposted, voice.Policy.STORIES_IX), 2, "the feed and the author's source")
        self.assertEqual(voice.count([voice.Said("s1", "x", "s9")], voice.Policy.MARKX), 1, "the author's source only")


class Keys(unittest.TestCase):
    """The stored forms never change, and every reader reads them as the code it replaced did."""

    def test_the_forms(self):
        self.assertEqual(voice.key("site", "s1", "pub.example"), "site:pub.example")
        self.assertEqual(voice.key("reddit", "s1", "", "alice"), "reddit:alice")
        self.assertEqual(voice.key("reddit", "s1", "", None), "source:s1")
        self.assertEqual(voice.key("x", "s1", "pub.example", "acme"), "source:s1")
        self.assertEqual(voice.confirmed_key("v1"), "voice:v1")
        self.assertEqual(voice.channel_key("s1"), "s:s1")
        self.assertEqual(voice.channel_key("s1", "v1"), "v:v1")
        self.assertEqual(voice.channel_of("v:v1"), ("voice", "v1"))
        self.assertEqual(voice.channel_of("s:s1"), ("source", "s1"))
        self.assertEqual(voice.channel_of("reddit:alice"), ("", "alice"))

    def test_the_readers_read_as_before(self):
        keys = ["site:pub.example", "reddit:Alice", "reddit:alice", "source:s1", "source:", "voice:v1", "", "x"]
        owners = {"reddit:alice": "source:s2", "site:pub.example": "voice:v1", "source:s1": "site:pub2.example"}
        namers = {"site:pub.example": "s7"}
        for k in keys:
            self.assertEqual(voice.owner_of(owners, k), old.owner_of(owners, k), k)
            self.assertEqual(voice.is_confirmed(k), old.confirmed(k), k)
            self.assertEqual(voice.is_poster(k), k.startswith("reddit:"), k)
            if voice.is_poster(k):
                self.assertEqual(voice.poster(k), k.split(":", 1)[1])
            self.assertEqual(voice.is_site(k), k.startswith("site:"), k)
            from insight_core.db.repo_discover import voice_source
            self.assertEqual(voice_source(k, namers), old.voice_source(k, namers), k)
            for vid in (None, "", "v3"):
                self.assertEqual(voice.story_channel_key(k or None, "s5", vid), old.story_voice(k or None, "s5", vid), k)
        for kind in KINDS:
            self.assertEqual(voice.source_key("s1", kind, "pub.example"), old.source_voice(kind, "s1", "pub.example"))
            self.assertEqual(voice.source_key("s1"), old.reposter_voice("s1"))

    @requires_db
    def test_the_sql_says_what_the_python_says(self):
        rows = [(k, s, site, a) for k in KINDS for s in ("s1",) for site in ("pub.example", "") for a in (None, "alice")]
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            for kind, src, site, author in rows:
                cur.execute(f"""SELECT {voice.key_sql("%(k)s::text", "%(site)s::text", "%(a)s::text", "%(s)s")},
                                       {voice.source_key_sql("%(k)s::text", "%(site)s::text", "%(s)s")},
                                       {voice.site_key_sql("%(site)s::text")},
                                       {voice.key_sql("%(k)s::text", "%(site)s::text", "%(a)s::text", "%(s)s")}
                                           LIKE '{voice.POSTER_LIKE}'""",
                            {"k": kind, "s": src, "site": site, "a": author})
                k, sk, site_k, poster = cur.fetchone()
                self.assertEqual(k, voice.key(kind, src, site, author))
                self.assertEqual(sk, voice.source_key(src, kind, site))
                self.assertEqual(site_k, voice.site_key(site))
                self.assertEqual(poster, voice.is_poster(k))


class Byline(unittest.TestCase):
    """Who wrote a post is Byline's: one "RT by @" pattern, repost_of and the repost tests, as before."""

    def test_one_pattern(self):
        from insight_core.ingestion.kinds import x_articles
        from insight_core.markx import handles
        from insight_core.utils import post_fields
        self.assertIs(handles.REPOST, byline.RT_BY)
        self.assertIs(post_fields.REPOST_BY_RE, byline.RT_BY)
        self.assertEqual(x_articles.TITLE_PREFIX_RE.match("RT by @a: R to @b: hi").group(0), "RT by @a: R to @b: ")
        self.assertEqual(byline.RT_BY.match("RT by @acme: hello").group(1), "acme")
        self.assertIsNone(byline.RT_BY.match("rt by @acme: hello"))

    def test_the_repost_tests_read_as_before(self):
        def old_is_repost(kind, platform, handle, own, title, author, reposted_by, forwarded):   # source_stats v10.16
            if forwarded or (title or "").startswith("RT by @"):
                return True
            if byline.repost_of(platform, handle, author, reposted_by) is not None:
                return True
            if kind == "x" and author and own:
                return author.lower().lstrip("@") != own.split("/", 1)[-1]
            return False
        nitter = "https://nitter.local/feedowner/rss"
        for title in (None, "RT by @x: hi", "hello"):
            for author in (None, "feedowner", "@FeedOwner", "acme"):
                for by in (None, ["feedowner"], ["other"]):
                    for fwd in (False, True):
                        for kind, own in (("x", "x.com/feedowner"), ("x", None), ("telegram", None)):
                            args = (kind, "rss", nitter, own, title, author, by, fwd)
                            self.assertEqual(byline.is_repost(*args), old_is_repost(*args), args)
                        rt = bool(title and title.startswith("RT"))
                        self.assertEqual(byline.retold("x", "feedowner", author, bool(by), rt),
                                         bool(by or (title and title.startswith("RT"))
                                              or (author and author.lower().lstrip("@") != "feedowner")))


class BuiltVoices(unittest.TestCase):
    """markx/built.py counts a story's voices by Voice's MARKX rule: a saved page is no voice (0189's one fix; v10.16
    counted every member's source)."""

    def test_a_saved_page_is_no_voice(self):
        P = built.Post
        posts = [P("a", "s1", T0, None), P("b", "s1", T0, None), P("c", "s2", T0, None, kind="saved")]
        self.assertEqual(built.voices(posts), 1)
        self.assertEqual(old.built_voices(posts), 2, "v10.16 counted the saved page")
        self.assertEqual(built.voices(posts[:2] + [P("d", "s3", T0, None, kind="telegram")]), 2)

    def test_a_saved_leak_is_no_coverage_of_its_own(self):
        """Two voices leaking a release more than a day before it are coverage of their own; a saved page is none."""
        from datetime import timedelta
        P = built.Post
        h = timedelta(hours=1)
        release = P("r", "s9", T0, "model_release")
        leak = P("l1", "s1", T0 - 48 * h, built.LEAK)
        saved = P("l2", "s2", T0 - 40 * h, built.LEAK, kind="saved")
        other = P("l3", "s3", T0 - 40 * h, built.LEAK)
        self.assertTrue(all(x["joins"] for x in built.leaks_inside([release, leak, saved])))
        self.assertFalse(any(x["joins"] for x in built.leaks_inside([release, leak, other])))


class StoryGates(unittest.TestCase):
    """back's and later's "Mark IX story of 2+ sources" gate counts voices: a saved page is none (0189's second fix)."""

    def test_a_thread_and_a_saved_page_are_one_voice(self):
        from insight_core.markx import back
        thread = [back._P("a", "s1", T0, None, False), back._P("b", "s1", T0, None, False)]
        self.assertEqual(back.sources(thread + [back._P("c", "s9", T0, None, True)]), 1)
        self.assertEqual(back.sources(thread + [back._P("c", "s9", T0, None, False)]), 2)

    def test_the_sql_count_drops_a_saved_page(self):
        self.assertEqual(voice.count_sql("p.source_id"), "count(DISTINCT p.source_id)")
        self.assertEqual(voice.count_sql("p.source_id", "s.platform"),
                         "count(DISTINCT p.source_id) FILTER (WHERE s.platform IS DISTINCT FROM 'saved')")


if __name__ == "__main__":
    unittest.main()
