"""Channel profiles (issue 0132 C2): each kind's parser on invented pages, where a source's profile is, the voices'
profile rules (profile_link, the bio's staff line, the beat writer's note), the channels nobody follows, the fetch
run on the database (kept with valid_to, failures, a limiting host, the switch) and the scheduler's hook.

No request leaves this machine: every page is a fixture answered by FakeHttp. Every name and address is invented."""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.ingestion import profiles as P
from insight_core.tests._db import db_url
from insight_core.tests._kind_fakes import FakeHttp, RecordingSleeper
from insight_core.utils.voice_rules import (Channel, PairCounts, bio_names, judge, not_followed, profile_verdicts,
                                            with_profiles)

NITTER_PAGE = """<html><div class="profile-card">
<a class="profile-card-fullname" href="/quillonw" title="Quillon Writer">Quillon Writer</a>
<div class="profile-bio"><p dir="auto">Research engineer at <a href="/orbitlabs">@orbitlabs</a>. Notes at
<a href="https://quillon.example/blog">quillon.example/blog</a></p></div>
<div class="profile-website"><span><a href="https://quillon.example">quillon.example</a></span></div>
<ul class="profile-statlist"><li class="posts"><span class="profile-stat-header">Tweets</span>
<span class="profile-stat-num">4,210</span></li>
<li class="followers"><span class="profile-stat-header">Followers</span><span class="profile-stat-num">12,345</span></li>
</ul></div></html>"""

YOUTUBE_PAGE = """<html><head><meta property="og:title" content="Brightwater Talks">
<meta property="og:description" content="Talks on models. Blog: https://brightwater.example"></head>
<script>var ytInitialData = {"header":{"subscriberCountText":{"simpleText":"1.2M subscribers"}},
"aboutChannelViewModel":{"description":"Talks on models.\\nBlog: https://brightwater.example",
"links":[{"channelExternalLinkViewModel":{"title":{"content":"X"},"link":{"content":"x.com/clearwatertalks"}}},
{"channelExternalLinkViewModel":{"title":{"content":"Site"},"link":{"content":"brightwater.example"}}}]}};</script></html>"""

BRIDGE_FEED = """<?xml version="1.0"?><rss><channel><title>Quiet Channel</title><link>https://t.me/quietchan</link>
<description><![CDATA[News of the field. Our site: https://quiet.example and @quietchat]]></description>
<item><title>A post</title><description>Not the about</description></item></channel></rss>"""

SITE_PAGE = """<html><head><title>Orbit Labs - Home</title><meta name="description" content="We build orbits.">
<meta property="og:site_name" content="Orbit Labs"><link rel="me" href="https://social.example/@orbit"></head>
<body><a href="https://orbitlabs.example/about">About</a><a href="https://x.com/orbitlabs">X</a>
<a href="https://x.com/intent/tweet?text=hi">Share</a><a href="https://t.me/orbitnews">Telegram</a>
<a href="https://www.youtube.com/@orbittalks">YouTube</a><a href="https://elsewhere.example/2026/a-story">a story</a>
</body></html>"""


class ParserTests(unittest.TestCase):
    def test_counts(self):
        self.assertEqual([P.count_of(t) for t in ("12,345", "1.2K", "3.4M subscribers", "12 345", "", "none")],
                         [12345, 1200, 3400000, 12345, None, None])

    def test_nitter(self):
        p = P.parse_nitter(NITTER_PAGE, "https://nitter.local/quillonw")
        self.assertEqual((p.name, p.website, p.followers, p.followers_label),
                         ("Quillon Writer", "https://quillon.example", 12345, "followers"))
        self.assertIn("Research engineer at @orbitlabs", p.bio)
        self.assertIn("https://x.com/orbitlabs", p.links)          # Nitter's own link to an account is X's
        self.assertIn("https://quillon.example/blog", p.links)
        self.assertEqual(p.links[0], "https://quillon.example")     # the website field first

    def test_youtube(self):
        p = P.parse_youtube(YOUTUBE_PAGE, "https://www.youtube.com/channel/UCabc/about")
        self.assertEqual((p.name, p.followers, p.followers_label), ("Brightwater Talks", 1200000, "subscribers"))
        self.assertTrue(p.bio.startswith("Talks on models."))
        self.assertIn("https://x.com/clearwatertalks", p.links)
        self.assertIn("https://brightwater.example", p.links)

    def test_telegram_bridge_and_mtproto(self):
        p = P.parse_telegram_bridge(BRIDGE_FEED, "https://tg.bridge.example/rss/quietchan/1")
        self.assertEqual((p.name, p.followers), ("Quiet Channel", None))
        self.assertEqual(p.bio, "News of the field. Our site: https://quiet.example and @quietchat")
        self.assertEqual(p.links, ["https://quiet.example", "https://t.me/quietchat"])
        full = SimpleNamespace(full_chat=SimpleNamespace(about="Field notes. https://quiet.example", participants_count=5400),
                               chats=[SimpleNamespace(title="Quiet Channel")])
        q = P.parse_telegram_full(full, "t.me/quietchan")
        self.assertEqual((q.name, q.followers, q.followers_label, q.links),
                         ("Quiet Channel", 5400, "subscribers", ["https://quiet.example"]))

    def test_site_keeps_platform_accounts_only(self):
        p = P.parse_site(SITE_PAGE, "https://orbitlabs.example/")
        self.assertEqual((p.name, p.bio), ("Orbit Labs", "We build orbits."))
        self.assertEqual(p.links, ["https://social.example/@orbit", "https://x.com/orbitlabs", "https://t.me/orbitnews",
                                   "https://www.youtube.com/@orbittalks"])   # no share link, no story, not its own

    def test_where_a_profile_is(self):
        ask = lambda h, k, p="rss", **kw: P.ask_for({"platform": p, "handle_or_url": h}, k, "hk", **kw)  # noqa: E731
        self.assertEqual(ask("https://nitter.local/quillonw/rss", "nitter_rss").url, "https://nitter.local/quillonw")
        self.assertEqual(ask("https://www.youtube.com/feeds/videos.xml?channel_id=UCabc", "youtube_channel").url,
                         "https://www.youtube.com/channel/UCabc/about")
        self.assertEqual(ask("https://tg.bridge.example/rss/quietchan?limit=50", "telegram_rss").url,
                         "https://tg.bridge.example/rss/quietchan/1?limit=50")
        self.assertEqual(ask("quietchan", "telegram_mtproto", "telegram").kind, "telegram_mtproto")
        self.assertEqual(ask("https://orbitlabs.example/feed.xml", "generic_rss").url, "https://orbitlabs.example/")
        self.assertEqual(ask("https://feeds.host.example/orbit", "generic_rss", home="https://orbitlabs.example/").url,
                         "https://orbitlabs.example/")
        self.assertIsNone(ask("r/somesub", "reddit_subreddit", "reddit"))
        self.assertIsNone(ask("https://saved.example", "saved", "saved"))


def ch(i, kind="site", name=None, handle=None, keys=(), posts=20, **kw):
    return Channel(id=i, kind=kind, name=name or i, handle=handle or f"{i}.example", keys=set(keys), posts=posts,
                   own=posts, **kw)


def prof(**kw):
    return {"kind": "nitter", "url": "https://nitter.local/x", "fetched_at": "2026-11-08T00:00:00+00:00",
            "links": [], **kw}


def held(channels):
    out = {}
    for c in channels.values():
        for t in c.tokens:
            out[t] = out.get(t, 0) + 1
    return out


class ProfileRuleTests(unittest.TestCase):
    def setUp(self):
        self.c = {
            "blog": ch("blog", name="Quillon Notes", handle="quillon.example", keys={"site:quillon.example"}),
            "xacc": ch("xacc", kind="x", name="Q W", handle="qwrites", keys={"x:qwrites"}),
            "corp": ch("corp", kind="x", name="Orbit Labs", handle="orbitlabs", keys={"x:orbitlabs"}),
            "zine": ch("zine", name="Teal Weekly", handle="teal.example", keys={"site:teal.example"}),
            "subs": ch("subs", kind="reddit", name="r/somesub", handle="somesub", keys={"r:somesub"}),
        }
        self.held = held(self.c)

    def v(self, found, a, b):
        return next((v for v in found if {v.a, v.b} == {a, b}), None)

    def test_a_website_field_with_no_link_back_nor_name_is_related(self):
        found = profile_verdicts(self.c, {"xacc": prof(website="https://quillon.example")}, {}, self.held)
        v = self.v(found, "blog", "xacc")
        self.assertEqual(v.verdict, "related")
        self.assertEqual(v.evidence[0]["rule"], "profile_link")
        self.assertIn("website field", v.evidence[0]["line"])
        self.assertEqual(v.evidence[0]["profile"]["source"], "xacc")

    def test_a_link_back_joins(self):
        posts_back = {("blog", "xacc"): PairCounts(link_posts=1)}
        found = profile_verdicts(self.c, {"xacc": prof(website="https://quillon.example")}, posts_back, self.held)
        self.assertEqual(self.v(found, "blog", "xacc").verdict, "join")
        both = profile_verdicts(self.c, {"xacc": prof(website="https://quillon.example"),
                                         "blog": prof(kind="site", links=["https://x.com/qwrites"])}, {}, self.held)
        self.assertEqual(self.v(both, "blog", "xacc").verdict, "join")

    def test_a_shared_name_joins(self):
        c = dict(self.c, xacc=ch("xacc", kind="x", name="Quillon Writes", handle="quillonw", keys={"x:quillonw"}))
        found = profile_verdicts(c, {"xacc": prof(website="https://quillon.example/blog")}, {}, held(c))
        self.assertEqual(self.v(found, "blog", "xacc").verdict, "join")

    def test_a_directory_and_platforms_say_nothing(self):
        many = {f"s{i}": ch(f"s{i}", kind="x", handle=f"writer{i}", keys={f"x:writer{i}"}) for i in range(7)}
        c = {**self.c, **many}
        page = prof(kind="site", links=[f"https://x.com/writer{i}" for i in range(7)])
        self.assertEqual(profile_verdicts(c, {"zine": page}, {}, held(c)), [])
        self.assertEqual(profile_verdicts(self.c, {"subs": prof(website="https://quillon.example")}, {}, self.held), [])

    def test_the_bio_names_where_its_writer_works(self):
        found = profile_verdicts(self.c, {"xacc": prof(bio="Research engineer at @orbitlabs. Views mine.")}, {}, self.held)
        v = self.v(found, "corp", "xacc")
        self.assertEqual((v.verdict, v.evidence[0]["rule"]), ("related", "profile_bio"))
        self.assertIn("staff", v.evidence[0]["line"])
        self.assertIsNone(bio_names("ex-@orbitlabs, now independent", self.c["corp"], self.held))
        self.assertIsNotNone(bio_names("Works at Orbit Labs", self.c["corp"], self.held))
        self.assertIsNone(bio_names("Writes about orbits and labs", self.c["corp"], self.held))

    def test_a_beat_writer_is_said_so_and_joins_upgrade(self):
        rules = judge(self.c, {("xacc", "corp"): PairCounts(reposts=12)}, {}, {})
        self.assertEqual(rules[0].verdict, "related")
        out = with_profiles(rules, [], self.c, {"xacc": prof(bio="I write about the orbit industry.")}, self.held)
        lines = [e["line"] for e in self.v(out, "corp", "xacc").evidence]
        self.assertTrue(any("beat writer" in line for line in lines), lines)
        extra = profile_verdicts(self.c, {"xacc": prof(website="https://quillon.example"),
                                          "blog": prof(links=["https://x.com/qwrites"])}, {}, self.held)
        merged = with_profiles([], extra, self.c, {}, self.held)
        self.assertEqual(self.v(merged, "blog", "xacc").verdict, "join")


class NotFollowedTests(unittest.TestCase):
    def setUp(self):
        self.c = {
            "blog": ch("blog", name="Quillon Notes", handle="quillon.example", keys={"site:quillon.example"}),
            "corp": ch("corp", kind="x", name="Orbit Labs", handle="orbitlabs", keys={"x:orbitlabs"}),
            "subs": ch("subs", kind="reddit", name="r/somesub", handle="somesub", keys={"r:somesub"}),
        }
        self.held = held(self.c)

    def test_a_profiles_linked_accounts_not_followed(self):
        got = not_followed(self.c, {"corp": prof(links=["https://t.me/orbitnews", "https://x.com/orbitlabs",
                                                        "https://www.reddit.com/r/orbits"])}, {}, [], self.held)
        self.assertEqual([e["key"] for e in got["corp"]], ["tg:orbitnews"])    # followed and Reddit's left out
        self.assertEqual(got["corp"][0]["url"], "https://t.me/orbitnews")
        self.assertEqual(got["corp"][0]["why"][0]["rule"], "profile")

    def test_own_posts_linking_a_profile_need_a_name_or_a_links_section(self):
        own = {("blog", "x:quillon_notes"): (1, ["p1"]), ("blog", "x:someoneelse"): (1, ["p2"]),
               ("corp", "yt:orbittalks"): (8, ["p3"])}
        got = not_followed(self.c, {}, own, [], self.held)
        self.assertEqual([e["key"] for e in got["blog"]], ["x:quillon_notes"])
        self.assertEqual([e["key"] for e in got["corp"]], ["yt:orbittalks"])   # 8 of 20 own posts: a links section
        self.assertEqual(got["blog"][0]["why"][0]["posts"], ["p1"])

    def test_a_site_home_its_posts_link_needs_a_shared_name(self):
        own = {("blog", "site:toolmaker.example"): (1, ["p1"]), ("corp", "site:sponsor.example"): (18, ["p2"]),
               ("corp", "site:orbitlabsnews.example"): (1, ["p3"]), ("blog", "site:shop.quillon.example"): (3, ["p4"])}
        got = not_followed(self.c, {}, own, [{"key": "toolmaker.example", "url": "https://toolmaker.example"}], self.held)
        self.assertNotIn("blog", got)    # a citation (Discover's too), and its own site's other host
        self.assertEqual([e["key"] for e in got["corp"]], ["site:orbitlabsnews.example"])   # the sponsor in 18/20: no

    def test_one_row_per_site(self):
        own = {("corp", f"site:{h}orbitlabs.example"): (1, [f"p{h}"]) for h in ("", "tools.", "shop.")}
        got = not_followed(self.c, {}, own, [], self.held)
        self.assertEqual([(e["key"], e.get("hosts")) for e in got["corp"]], [("site:orbitlabs.example", 3)])

    def test_discover_candidates_by_name_link_or_its_own_word(self):
        discover = [{"key": "orbitlabs.example", "url": "https://orbitlabs.example"},
                    {"key": "x.com/quietnotes", "url": "https://x.com/quietnotes", "of": "Quillon Notes",
                     "source_id": "blog"},
                    {"key": "x.com/unrelated", "url": "https://x.com/unrelated"}]
        got = not_followed(self.c, {}, {}, discover, self.held)
        self.assertEqual([e["key"] for e in got["corp"]], ["site:orbitlabs.example"])
        self.assertIn("shares the name", got["corp"][0]["why"][0]["line"])
        self.assertEqual([e["key"] for e in got["blog"]], ["x:quietnotes"])
        self.assertNotIn("subs", got)

    def test_a_platform_lists_none(self):
        got = not_followed(self.c, {"subs": prof(links=["https://t.me/orbitnews"])}, {}, [], self.held)
        self.assertEqual(got, {})


class _Gates:
    """FetchGates with a recorded sleep: the floors are asked for, never waited out."""

    @staticmethod
    def make():
        from insight_core.ingestion.gates import FetchGates
        return FetchGates(sleep=RecordingSleeper(), budgets=None)


class _OnDb(unittest.TestCase):
    """One transaction rolled back; every page from FakeHttp."""

    def setUp(self):
        from insight_core.ingestion.kinds import KindRegistry
        from insight_core.ingestion.kinds.generic_rss import GenericRssKind
        from insight_core.ingestion.kinds.nitter_rss import NitterRssKind
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.cur.execute("UPDATE sources SET enabled = false")   # rolled back: only this test's sources are due
        self.mark = uuid.uuid4().hex[:8]
        self.http = FakeHttp({})
        self.registry = KindRegistry([NitterRssKind(self.http), GenericRssKind(self.http)])

        @contextlib.contextmanager
        def mine():
            yield self.cur
        self.mine = mine

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def source(self, handle, name):
        self.cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, settings) VALUES ('rss', %s, true, %s::jsonb) "
                         "RETURNING id::text", (handle, json.dumps({"display_name": name})))
        return self.cur.fetchone()[0]

    def service(self, **kw):
        from insight_core.services.profiles_service import ProfilesService
        return ProfilesService(db_url(), http=self.http, gates=_Gates.make(), registry=self.registry,
                               clock=lambda: self.now, cursor=self.mine, **kw)

    def rows(self, sid):
        self.cur.execute("SELECT status, followers, valid_to IS NULL FROM source_profiles WHERE source_id = %s "
                         "ORDER BY fetched_at, status", (sid,))
        return self.cur.fetchall()


class FetchRunTests(_OnDb):
    def test_fetch_keep_and_refetch_a_month_later(self):
        x = self.source(f"https://nitter.local/quillon{self.mark}/rss", "Quillon")
        site = self.source(f"https://orbit{self.mark}.example/feed", "Orbit")
        self.http.responses = {f"https://nitter.local/quillon{self.mark}": NITTER_PAGE,
                               f"https://orbit{self.mark}.example/": SITE_PAGE}
        got = asyncio.run(self.service().run())
        self.assertEqual((got["ok"], got["failed"]), (2, 0))
        self.assertEqual(self.rows(x), [("ok", 12345, True)])
        self.assertEqual(asyncio.run(self.service().run())["planned"], 0, "read: not due for a month")
        self.now += timedelta(days=31)
        asyncio.run(self.service().run())
        self.assertEqual(self.rows(x), [("ok", 12345, False), ("ok", 12345, True)], "the old row closed, kept")
        from insight_core.services.profiles_service import current
        self.assertEqual(current(self.cur, [site])[site]["links"][1], "https://x.com/orbitlabs")

    def test_a_failure_is_kept_and_waits_a_week_and_a_limiting_host_is_left(self):
        from insight_core.ingestion.http import HttpError
        a = self.source(f"https://nitter.local/aaa{self.mark}/rss", "A")
        b = self.source(f"https://nitter.local/bbb{self.mark}/rss", "B")
        self.cur.execute("UPDATE sources SET created_at = created_at - interval '1 day' WHERE id = %s", (a,))   # a first
        self.http.responses = {f"https://nitter.local/aaa{self.mark}": HttpError("HTTP 429", status=429, retry_after=30),
                               f"https://nitter.local/bbb{self.mark}": NITTER_PAGE}
        got = asyncio.run(self.service().run())
        self.assertEqual((got["failed"], got["waiting"], got["ok"]), (1, 1, 0))
        self.assertEqual(self.rows(a), [("failed", None, False)])
        self.assertEqual(self.rows(b), [])
        self.assertEqual(self.http.requests.count(f"https://nitter.local/bbb{self.mark}"), 0)
        self.now += timedelta(days=1)
        planned = [s["id"] for s, _, _ in self.service().plan()]
        self.assertNotIn(a, planned)
        self.assertIn(b, planned)

    def test_the_switch_and_the_cap(self):
        from insight_core.services.profiles_service import set_setting, setting_on
        for i in range(3):
            self.source(f"https://nitter.local/c{i}{self.mark}/rss", f"C{i}")
        self.assertTrue(setting_on(self.cur), "on by default")
        self.assertEqual(len(self.service(per_run=2).plan()), 2)
        set_setting(self.cur, False)
        self.assertEqual(self.service().plan(), [])

    def test_telegram_through_mtproto_on_its_session_and_a_held_session_waits(self):
        from insight_core.ingestion.kinds import KindRegistry
        from insight_core.ingestion.kinds.base import KindUnavailable, PolitenessProfile

        class Session:
            def __init__(self, held):
                self.held, self.events = held, []

            async def open(self):
                if self.held:
                    raise KindUnavailable("in use")
                self.events.append("open")

            async def close(self):
                self.events.append("close")

        class Tg:
            name, profile = "telegram_mtproto", PolitenessProfile(concurrency_pool="host-lock")

            def __init__(self, held):
                self.made = Session(held)

            def matches(self, source):
                return source.get("platform") == "telegram"

            def host_key(self, source):
                return "platform:telegram"

            def session(self):
                return self.made

            async def channel_full(self, source):
                return SimpleNamespace(full_chat=SimpleNamespace(about="Notes", participants_count=77),
                                       chats=[SimpleNamespace(title="Quiet")])
        self.cur.execute("INSERT INTO sources (platform, handle_or_url, enabled) VALUES ('telegram', %s, true) RETURNING id::text",
                         (f"quiet{self.mark}",))
        sid = self.cur.fetchone()[0]
        held = Tg(True)
        self.registry = KindRegistry([held])
        self.assertEqual(asyncio.run(self.service().run())["waiting"], 1)
        self.assertEqual(self.rows(sid), [])
        free = Tg(False)
        self.registry = KindRegistry([free])
        asyncio.run(self.service().run())
        self.assertEqual(self.rows(sid), [("ok", 77, True)])
        self.assertEqual(free.made.events, ["open", "close"])

    def test_the_scheduler_hook_never_raises(self):
        from insight_core.scripts.run_scheduler import profiles_after_tick

        async def boom(_):
            raise RuntimeError("no")

        async def fine(_):
            return {"planned": 0}
        self.assertIsNone(asyncio.run(profiles_after_tick("db", run=boom)))
        self.assertEqual(asyncio.run(profiles_after_tick("db", run=fine)), {"planned": 0})


class SuggestionsFromProfilesTests(_OnDb):
    def test_a_profile_suggests_a_join_and_lists_a_channel_nobody_follows(self):
        from insight_core.services import profiles_service as PS
        from insight_core.services.voices_service import VoicesService
        from insight_core.ingestion.profiles import Ask, Profile
        m = "".join(ch for ch in self.mark if ch.isalpha()) or "zz"
        blog = self.source(f"https://quillon{m}.example/feed", f"Quillon {m}")
        xacc = self.source(f"https://nitter.local/quillon{m}/rss", f"Quillon {m} on X")
        PS.record(self.cur, xacc, Ask("nitter", "u", "h"), self.now,
                  profile=Profile("nitter", "https://nitter.local/q", website=f"https://quillon{m}.example",
                                  links=[f"https://t.me/quillon{m}news"]))
        voices = VoicesService(db_url(), after_change=lambda _: None, clock=lambda: self.now, background=False,
                               cursor=self.mine)
        found = voices.suggestions()
        mine = [g for g in found["voices"] if {s["id"] for s in g["sources"]} == {blog, xacc}]
        self.assertEqual(len(mine), 1, found["voices"])
        self.assertIn("profile_link", {e["rule"] for edge in mine[0]["edges"] for e in edge["evidence"]})
        nf = [g for g in found["not_followed"] if g["subject"]["id"] == xacc]
        self.assertEqual([c["key"] for c in nf[0]["channels"]], [f"tg:quillon{m}news"])
        joined = voices.join([blog, xacc])["voice"]
        self.assertEqual([c["key"] for c in voices.voice(joined["id"])["not_followed"]], [f"tg:quillon{m}news"])


class RouteTests(unittest.TestCase):
    def test_the_switch_routes(self):
        import main
        from insight_core.routers import voices as route
        from insight_core.tests._asgi import call

        class Fake:
            on = True

            def profiles_setting(self):
                return {"success": True, "on": self.on}

            def set_profiles_setting(self, on):
                self.on = on
                return {"success": True, "on": on}
        route.use(Fake())
        try:
            self.assertEqual(call(main.app, "GET", "/api/voices/profiles/setting")[2]["on"], True)
            self.assertEqual(call(main.app, "PUT", "/api/voices/profiles/setting", json_body={"on": False})[2]["on"], False)
        finally:
            route.use(None)


if __name__ == "__main__":
    unittest.main()
