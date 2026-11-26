"""The track scout (0148): the weekly trigger and the tap, each finder's candidates, the `scout` task, the test read
into the scratch area (nothing followed, nothing in the feed) with stubbed requests, health reasons, ranking by
precision with the 30% floor, Follow through the add path with provenance, the cost guard. DB tests on _test only."""
from __future__ import annotations

import asyncio
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.ingestion.kinds import KindRegistry
from insight_core.markx import repo, schemas, scout, scout_reads, tasks, tracks, validate
from insight_core.tests._db import clear_tables, db_url, insert_scratch_source, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_markx_api import _Api, call

NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = timedelta(days=1)
SCOUT_TABLES = ("mx_scout_items", "mx_scout_candidates", "mx_scout_runs", "mx_source_provenance")
TRACK_TABLES = ("mx_tracks", "mx_track_items", "mx_track_subtopics")


def rss(title="Example Makers", n=5, *, start=NOW, body="A long enough body about a printed part and how it was made. " * 4,
        dated=True, base="https://makers.example/post"):
    items = "".join(
        f"<item><title>Part {k}</title><link>{base}-{k}</link><description>{body}</description>"
        + (f"<pubDate>{(start - k * DAY).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>" if dated else "")
        + "</item>" for k in range(n))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>{items}</channel></rss>'


def item(k=0, *, chars=600, dated=True, lang="en", transcript=None, at=None):
    return {"url": f"https://x.example/{k}", "title": f"t{k}", "text": "w" * chars, "chars": chars,
            "published_at": (at or NOW - k * DAY) if dated else None, "lang": lang, "transcript": transcript}


def verdict(inside=True, conf=0.9):
    # the fit stated before `in`, quoting the tracks' `Belongs:` ("... parts ...")
    return {"id": "x", "subject": "a printable part", "fits": inside, "matches": "parts" if inside else None,
            "excluded": None, "in": inside, "confidence": conf, "subtopic": "parts" if inside else None,
            "why": "A printable part: Acme's Widget."}


class StubReader:
    """A Reader stand-in: {address: ReadResult}; an unknown address can't be read. Records what it was asked."""

    def __init__(self, results=None, default=None):
        self.results = results or {}
        self.default = default
        self.asked = []

    async def read(self, address, *, linked=(), limit=20):
        self.asked.append((address, list(linked)))
        got = self.results.get(address) or (self.default(address) if self.default else None)
        return got or scout_reads.ReadResult(reason="none found", requests=2)


def feed_result(address, n=20, **kw):
    return scout_reads.ReadResult(
        resolved={"platform": "rss", "handle_or_url": address.rstrip("/") + "/feed.xml", "settings": {}, "via": "feed",
                  "title": "Example"},
        items=[dict(item(k, **kw), url=f"{address.rstrip('/')}/p{k}") for k in range(n)], requests=3)


# ---- no database ------------------------------------------------------------------------------------------------

class Pure(unittest.TestCase):
    def test_the_kind_its_guide_and_schema(self):
        self.assertEqual((schemas.KINDS["scout"].guide, schemas.KINDS["scout"].subject), ("scout-v1", "track"))
        self.assertIn("sources", schemas.guide_body("scout-v1"))
        ok = {"sources": [{"platform": "reddit", "address": f"reddit.com/r/sub{k}", "name": f"Sub {k}", "why": "parts"}
                          for k in range(6)]}
        self.assertIsNone(validate.check("scout", ok, "q")[1])
        self.assertIsNotNone(validate.check("scout", {"sources": ok["sources"][:3]}, "q")[1])          # under 5
        self.assertIsNotNone(validate.check("scout", {"sources": ok["sources"] * 6}, "q")[1])          # over 30
        bad_platform = {"sources": [dict(s, platform="myspace") for s in ok["sources"]]}
        self.assertIsNotNone(validate.check("scout", bad_platform, "q")[1])
        twice = {"sources": ok["sources"][:5] + [dict(ok["sources"][0], address="https://www.reddit.com/r/sub0/")]}
        self.assertIn("twice", validate.check("scout", twice, "q")[1])
        spaced = {"sources": [dict(s, address="two words") for s in ok["sources"]]}
        self.assertIn("no spaces", validate.check("scout", spaced, "q")[1])
        two_lines = {"sources": [dict(s, why="a\nb") for s in ok["sources"]]}
        self.assertIn("one line", validate.check("scout", two_lines, "q")[1])

    def test_addresses_normalised_by_platform_class(self):
        n = scout.normal_address
        self.assertEqual(n("reddit", "r/printedparts"), "https://www.reddit.com/r/printedparts")
        self.assertEqual(n("youtube", "@makerchannel"), "https://www.youtube.com/@makerchannel")
        self.assertEqual(n("telegram", "@makerfeed"), "https://t.me/makerfeed")
        self.assertEqual(n("x", "@maker"), "https://x.com/maker")
        self.assertEqual(n("site", "makers.example/blog"), "https://makers.example/blog")
        self.assertEqual(n("site", "https://makers.example/"), "https://makers.example/")
        self.assertIsNone(n("site", "Maker Weekly"))
        self.assertIsNone(n("youtube", "a channel"))

    def test_haiku_candidates_from_an_answer(self):
        got = scout.haiku_candidates({"sources": [
            {"platform": "reddit", "address": "r/printedparts", "name": "Printed parts", "why": "parts"},
            {"platform": "site", "address": "Maker Weekly"}]})
        self.assertEqual([(c["finder"], c["address"]) for c in got], [("haiku", "https://www.reddit.com/r/printedparts")])

    def test_keys_by_discover_and_platform_owners(self):
        self.assertEqual(scout.key_of("https://github.com/makerco/widget")[0], "github.com/makerco")
        self.assertEqual(scout.key_of("https://www.reddit.com/r/printedparts/comments/1/x")[0], "reddit.com/r/printedparts")
        self.assertEqual(scout.key_of("https://blog.makers.example/a-post-here")[0], "blog.makers.example")
        search = "https://www.reddit.com/search.rss?q=printed%20parts&sort=new"
        self.assertEqual(scout.key_of(search)[0], search.split("://", 1)[1])     # a search feed is its own source

    def test_platform_shapes_with_search_feeds(self):
        got = scout.shape_candidates(["printed parts", "parts", "filament"], ["Widget Maker"],
                                     x_bridge="https://nitter.example")
        addresses = [c["address"] for c in got]
        self.assertIn("https://hnrss.org/newest?q=printed%20parts", addresses)
        self.assertIn("https://www.youtube.com/@widgetmaker", addresses)
        self.assertIn("https://x.com/widgetmaker", addresses)
        self.assertTrue(all(c["finder"] == "shape" for c in got))
        no_bridge = [c["address"] for c in scout.shape_candidates(["parts"], ["Widget Maker"], x_bridge=None)]
        self.assertFalse(any("x.com" in a or "nitter" in a for a in no_bridge))   # X only through a bridge

    def test_shapes_build_no_reddit_and_no_x_search(self):
        # every server read of Reddit is refused (0262); the bridge's kind reads accounts' feeds, never a search
        got = [c["address"] for c in scout.shape_candidates(["printed parts", "filament"], ["Widget Maker"],
                                                            x_bridge="https://nitter.example")]
        self.assertFalse([a for a in got if "reddit" in a])
        self.assertFalse([a for a in got if "/search/rss" in a])

    def test_description_terms(self):
        terms = scout.description_terms({"name": "Cool 3D projects", "description": "Printable parts and filament tests",
                                         "excludes": "filament sales"})
        self.assertEqual(terms[0], "3d projects")                              # "cool" says nothing
        self.assertIn("printable", terms)
        self.assertNotIn("filament", terms)                                    # what the excludes name stays out

    def test_description_phrases_are_words_written_side_by_side(self):
        # production's Cool Projects asked Hacker News for "interesting build" and "projects interesting": two words
        # a stop word (or the name's end) stood between
        terms = scout.description_terms({"name": "Cool Projects", "description": (
            "Interesting things people build and share: open-source tools and libraries, weekend hacks, clever apps "
            "and sites, hardware builds, creative uses of AI."), "excludes": None})
        self.assertNotIn("interesting build", terms)
        self.assertNotIn("projects interesting", terms)
        self.assertEqual(terms[:2], ["open-source tools", "weekend hacks"])

    def test_a_link_that_can_be_no_source(self):
        no = ["http://localhost:3000/demo", "http://192.168.1.20/admin", "https://[::1]/x", "https://intranet/wiki",
              "https://www.reddit.com/submit?url=https%3A%2F%2Fmakers.example%2Fa",
              "https://linkedin.com/sharing/share-offsite?url=https%3A%2F%2Fmakers.example%2Fa",
              "https://chat.example.com/share/0f8b1c2d-3e4f-4a5b-8c6d-7e8f9a0b1c2d",
              "https://tool.example/?ref=demo&id=4", "https://arxiv.org/abs/2406.13843"]
        for url in no:
            self.assertFalse(scout.source_link(url), url)
        for url in ("https://makers.example/blog/a-printed-hinge", "https://x.com/jakubantalik",
                    "https://github.com/makerco/widget", "https://makers.example/"):
            self.assertTrue(scout.source_link(url), url)

    def test_a_persons_own_address(self):
        own = scout.own_address
        self.assertEqual(own("Jakub Antalik", "https://x.com/Jakubantalik")[0], "x.com/jakubantalik")
        self.assertEqual(own("Jakub Antalik", "https://x.com/jakubantalik/status/1990000000000000001")[0],
                         "x.com/jakubantalik")
        self.assertEqual(own("Jakub Antalik", "https://github.com/jakubantalik/cursor-mood")[0], "github.com/jakubantalik")
        self.assertEqual(own("Jakub Antalik", "https://jakubantalik.com/posts/a-tiny-model")[0], "jakubantalik.com")
        self.assertIsNone(own("Jakub Antalik", "https://x.com/DataChaz"))                    # someone else's
        self.assertIsNone(own("Jakub Antalik", "https://libraries.dev/cursor-emotion"))     # the find, not its maker
        self.assertIsNone(own("Pierre Deligne", "https://en.wikipedia.org/wiki/Pierre_Deligne"))   # a page about them
        self.assertIsNone(own("Wu", "https://x.com/wu"))                                    # too short to be sure
        self.assertIsNone(own("Иван Петров", "https://x.com/ivanpetrov"))                   # no letters to compare

    def test_web_candidates_from_an_answer(self):
        got = scout.web_candidates(web_answer(
            "https://jakubantalik.com/",                                  # a maker's own site: its front page is asked for
            "https://x.com/jakubantalik",
            "https://github.com/jakubantalik/cursor-mood",                 # a project: its owner
            "https://github.com/jakubantalik/another-thing",               # the same owner again: once
            "https://docs.libraries.example/",                             # a reference's host
            "http://localhost:8080/",
            "https://www.reddit.com/submit?url=https%3A%2F%2Fx.example%2Fa",
            "https://arxiv.org/abs/2406.13843"))
        self.assertEqual([(c["finder"], c["key"], c["address"]) for c in got],
                         [("web", "jakubantalik.com", "https://jakubantalik.com"),
                          ("web", "x.com/jakubantalik", "https://x.com/jakubantalik"),
                          ("web", "github.com/jakubantalik", "https://github.com/jakubantalik")])
        self.assertEqual(got[0]["why"], "a maker's own site; launched a part this week")
        self.assertEqual(got[0]["evidence"]["url"], "https://jakubantalik.com/")

    def test_the_sphere_guide_is_a_websearch_variant_with_its_schema(self):
        self.assertEqual(schemas.GUIDE_VARIANTS["websearch-sphere-v1"], ("websearch", schemas.WEBSEARCH_SCHEMA))
        self.assertIn("OWN address", schemas.guide_body("websearch-sphere-v1"))
        a = web_answer("https://jakubantalik.com/")
        self.assertEqual(validate.check("websearch", a, "q", "websearch-sphere-v1"), (a, None))

    def test_health_reasons(self):
        h = scout_reads.health([item(k) for k in range(10)], NOW)
        self.assertTrue(h["reads_well"])
        self.assertEqual((h["items"], h["dated"], h["lang"]), (10, 10, "en"))
        self.assertEqual(scout_reads.cadence_words(h["per_week"]), "7 a week")
        self.assertEqual(scout_reads.health([], NOW)["reason"], "no items")
        undated = scout_reads.health([item(k, dated=k < 3) for k in range(10)], NOW)
        self.assertEqual(undated["reason"], "undated: 7 of 10 items have no date")
        self.assertIn("titles only", scout_reads.health([item(k, chars=10) for k in range(5)], NOW)["reason"])
        old = scout_reads.health([item(k, at=NOW - (400 + k) * DAY) for k in range(5)], NOW)
        self.assertTrue(old["reason"].startswith("stopped: the newest item is 400 days old"))
        labels = scout_reads.health([item(k, chars=200, lang="de", transcript=False) for k in range(5)], NOW)
        self.assertTrue(labels["reads_well"])
        self.assertEqual(labels["labels"], ["summaries only", "in de", "no transcripts"])
        self.assertEqual(scout_reads.cadence_words(0.5), "2 a month")

    def test_item_of_a_post_draft(self):
        it = scout_reads.item_of({"url": "https://x.example/a", "title": "  A  title ", "content": "Body text here.",
                                  "date": None, "metadata": {"kind": "youtube_video", "transcript_source": ""}})
        self.assertEqual((it["title"], it["published_at"], it["transcript"]), ("A title", None, False))
        self.assertIsNone(scout_reads.item_of({"url": "", "title": "x"}))


class Reads(unittest.TestCase):
    """The test read through the add path, every request stubbed."""

    def test_a_feed_found_by_the_finder_is_read_with_the_fetchers_parser(self):
        page = ('<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head>'
                '<body>makers</body></html>')
        http = FakeHttp({"https://makers.example/": page, "https://makers.example/feed.xml": rss(n=25)})
        got = asyncio.run(scout_reads.Reader(http, KindRegistry.default(http, None), page_gap=0)
                          .read("https://makers.example/"))
        self.assertEqual(got.reason, "")
        self.assertEqual((got.resolved["via"], got.resolved["handle_or_url"]), ("feed", "https://makers.example/feed.xml"))
        self.assertEqual(len(got.items), 20)                                   # up to 20 newest
        self.assertEqual(got.items[0]["url"], "https://makers.example/post-0")
        self.assertGreaterEqual(got.requests, 2)
        self.assertTrue(scout_reads.health(got.items, NOW)["reads_well"])

    def test_an_undated_feed_reads_badly(self):
        http = FakeHttp({"https://makers.example/feed.xml": rss(n=6, dated=False)})
        got = asyncio.run(scout_reads.Reader(http, KindRegistry.default(http, None), page_gap=0)
                          .read("https://makers.example/feed.xml"))
        self.assertEqual(scout_reads.health(got.items, NOW)["reason"], "undated: 6 of 6 items have no date")

    def test_a_platform_account_is_read_through_its_kind(self):
        class Kind:
            name = "reddit_subreddit"

            async def fetch_latest(self, source, limit):
                self.asked = (source, limit)
                return [{"url": f"https://www.reddit.com/r/printedparts/comments/{k}/x", "title": f"p{k}",
                         "content": "text " * 40, "date": NOW - k * DAY} for k in range(30)]

        kind = Kind()
        registry = mock.Mock()
        registry.resolve.return_value = kind
        with mock.patch("insight_core.services.discover_reads.kind_source",
                        return_value={"platform": "reddit", "handle_or_url": "r/printedparts"}):
            got = asyncio.run(scout_reads.Reader(FakeHttp({}), registry).read("https://www.reddit.com/r/printedparts"))
        self.assertEqual(got.resolved, {"platform": "reddit", "handle_or_url": "r/printedparts", "settings": {},
                                        "via": "kind", "title": ""})
        self.assertEqual((len(got.items), kind.asked[1]), (20, 20))

    def test_an_x_account_is_read_through_the_bridge_feed_the_add_path_follows(self):
        # the add path's own mapping (feed_finder.bridge_feed via discover_reads.kind_source): x.com/<h> is
        # <nitter>/<h>/rss, read by the nitter_rss kind, and that address is what Follow adds
        feed = rss("Jakub Antalik / @jakubantalik", n=6, base="https://nitter.local/jakubantalik/status/19900000000000000")
        http = FakeHttp({"https://nitter.local/jakubantalik/rss": feed})
        with mock.patch.dict("os.environ", {"NITTER_HOSTS": "nitter.local"}):
            got = asyncio.run(scout_reads.Reader(http, KindRegistry.default(http, None), page_gap=0)
                              .read("https://x.com/jakubantalik"))
        self.assertEqual(got.reason, "")
        self.assertEqual((got.resolved["platform"], got.resolved["handle_or_url"], got.resolved["via"]),
                         ("rss", "https://nitter.local/jakubantalik/rss", "kind"))
        self.assertEqual(len(got.items), 6)
        self.assertEqual(http.requests[:1], ["https://nitter.local/jakubantalik/rss"])

    def test_none_found_says_why(self):
        http = FakeHttp({"https://quiet.example/": "<html><body>nothing here</body></html>"})
        got = asyncio.run(scout_reads.Reader(http, KindRegistry.default(http, None), page_gap=0)
                          .read("https://quiet.example/"))
        self.assertIsNone(got.resolved)
        self.assertTrue(got.reason)
        self.assertEqual(got.items, [])


# ---- on the test database -------------------------------------------------------------------------------------

@requires_test_db
class _Scout(_Api):
    plan = True

    def setUp(self):
        super().setUp()
        clear_tables(self.cur, (*SCOUT_TABLES, *TRACK_TABLES), cascade=True)
        self.addCleanup(clear_tables, self.cur, (*SCOUT_TABLES, *TRACK_TABLES), cascade=True)
        self.cur.execute("INSERT INTO folders (name, kind) VALUES (%s, 'track') RETURNING id",
                         (f"Cool parts {uuid.uuid4().hex[:6]}",))
        self.folder = str(self.cur.fetchone()[0])
        self.addCleanup(self.cur.execute, "DELETE FROM folders WHERE id = %s", (self.folder,))
        self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (self.folder, self.source))
        with self.conn.transaction():
            tracks.set_topic(self.cur, self.folder, description="Printable parts: useful 3D printed parts and why",
                             excludes=None)
        self.added = []
        self.addCleanup(self._drop_added)
        patcher = mock.patch.object(scout, "_x_bridge", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _drop_added(self):
        for sid in self.added:
            self.cur.execute("DELETE FROM source_folders WHERE source_id = %s", (sid,))
            self.cur.execute("DELETE FROM sources WHERE id = %s", (sid,))

    def add_source(self, platform, handle, settings):
        self.cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, settings) VALUES (%s, %s, true, %s::jsonb) "
                         "RETURNING id", (platform, f"{handle}#{uuid.uuid4().hex[:6]}", json.dumps(settings)))
        sid = str(self.cur.fetchone()[0])
        self.added.append(sid)
        self.calls = getattr(self, "calls", []) + [(platform, handle, settings)]
        return sid

    def in_post(self, title="A printed part", links=(), at=None, label=False):
        p = self.post(title=title, source=self.other, at=at, links=[(u, None) for u in links])
        if label:
            status, body = call("POST", f"/api/markx/tracks/{self.folder}/labels", body={"post": p, "answer": "in"})
            self.assertEqual(status, 200, body)
        else:
            self.judged(p, "passive")
        return p

    def judged(self, p, origin):
        task, _ = repo.add_task(self.cur, kind="track", guide="track-v1", subject_kind="post_track",
                                input=f"q {uuid.uuid4().hex}", a=p, b=self.folder)
        self.cur.execute("""INSERT INTO mx_track_items (track_id, post_id, version, task_id, origin, verdict, confidence)
                            VALUES (%s, %s, 1, %s, %s, true, 0.9)""", (self.folder, p, task, origin))

    def start(self, trigger="tap"):
        with self.conn.transaction():
            return scout.start(self.cur, self.folder, trigger=trigger)

    def advance(self, run_id, reader, now=None):
        return asyncio.run(scout.advance(db_url(), run_id, reader=reader, now=now))

    def cands(self, run_id):
        self.cur.execute("SELECT finder, key, state, address FROM mx_scout_candidates WHERE run_id = %s ORDER BY rank",
                         (run_id,))
        return self.cur.fetchall()

    def web_task(self, run_id):
        self.cur.execute("SELECT stats->>'web_task_id' FROM mx_scout_runs WHERE id = %s", (run_id,))
        return self.cur.fetchone()[0]

    def scout_task(self, run_id):
        self.cur.execute("SELECT scout_task_id FROM mx_scout_runs WHERE id = %s", (run_id,))
        return self.cur.fetchone()[0]

    def judge_all(self, run_id, fits):
        """Answer the run's judge questions: `fits(item url) -> bool`."""
        self.cur.execute("""SELECT i.task_id, i.url, k.input FROM mx_scout_items i
                             JOIN mx_scout_candidates c ON c.id = i.candidate_id JOIN mx_tasks k ON k.id = i.task_id
                             WHERE c.run_id = %s AND i.task_id IS NOT NULL""", (run_id,))
        got = self.cur.fetchall()
        rows = list({t: u for t, u, _ in got}.items())
        # a verdict names its post (validate.track_verdict_error): the why cites the question's title
        titles = {t: next((ln[7:] for ln in (q or "").splitlines() if ln.startswith("Title: ")), "") for t, _, q in got}
        status, body = self.answer(*[(t, dict(verdict(fits(u)), why=f"About {titles[t]}.")) for t, u in rows])
        self.assertEqual(status, 200, body)
        self.assertEqual(body["valid"], len(rows), body)


class Triggers(_Scout):
    def test_the_weekly_trigger_picks_every_track_once_a_week(self):
        with self.conn.transaction():
            self.assertEqual(scout.due_weekly(self.cur, NOW), [self.folder])
        for k in range(5):
            self.in_post(f"part {k}", at=NOW - k * DAY)
        with self.conn.transaction():
            # 5 in in 7 days, not quiet, and still scouted weekly for better sources
            self.assertEqual(scout.due_weekly(self.cur, NOW), [self.folder])
        clear_tables(self.cur, "mx_track_items")
        reader = StubReader()
        with mock.patch.object(scout, "default_reader", return_value=reader), \
                mock.patch.object(scout, "reads_allowed", return_value=True):
            out = asyncio.run(scout.tick(db_url()))
        self.assertEqual(len(out["started"]), 1)
        self.cur.execute("SELECT trigger FROM mx_scout_runs WHERE track_id = %s", (self.folder,))
        self.assertEqual([r[0] for r in self.cur.fetchall()], ["weekly"])
        with self.conn.transaction():
            self.assertEqual(scout.due_weekly(self.cur, NOW), [])            # scouted this week
            self.assertEqual(scout.due_weekly(self.cur, NOW + 8 * DAY), [self.folder])

    def test_a_starving_track_goes_first_and_weekly_runs_follow_each_other(self):
        # two described tracks: the healthy one (5 in this week) and a starving one (none)
        for k in range(5):
            self.in_post(f"part {k}", at=NOW - k * DAY)
        self.cur.execute("INSERT INTO folders (name, kind) VALUES (%s, 'track') RETURNING id",
                         (f"Quiet parts {uuid.uuid4().hex[:6]}",))
        quiet = str(self.cur.fetchone()[0])
        self.addCleanup(self.cur.execute, "DELETE FROM folders WHERE id = %s", (quiet,))
        with self.conn.transaction():
            tracks.set_topic(self.cur, quiet, description="Quiet parts: rarely posted printed parts", excludes=None)
            self.assertEqual(scout.due_weekly(self.cur, NOW), [quiet, self.folder])
        reader = StubReader()
        with mock.patch.object(scout, "default_reader", return_value=reader), \
                mock.patch.object(scout, "reads_allowed", return_value=True), \
                mock.patch.object(scout, "advance", new=mock.AsyncMock(return_value={})):
            first = asyncio.run(scout.tick(db_url()))
            second = asyncio.run(scout.tick(db_url()))   # the first weekly run is still open: none starts
        self.assertEqual(len(first["started"]), 1)
        self.assertEqual(second["started"], [])
        self.cur.execute("SELECT track_id::text FROM mx_scout_runs WHERE trigger = 'weekly'")
        self.assertEqual([r[0] for r in self.cur.fetchall()], [quiet])

    def test_the_tap_starts_a_run_and_reads_in_the_background(self):
        self.in_post(links=["https://makers.example/blog/a-printed-hinge"])
        reader = StubReader(default=lambda a: feed_result(a))
        with mock.patch.object(scout, "default_reader", return_value=reader), \
                mock.patch.object(scout, "reads_allowed", return_value=True):
            status, body = call("POST", f"/api/markx/tracks/{self.folder}/scout")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["candidates"]["match"], 1)
        self.assertIn(("https://makers.example", ["https://makers.example/blog/a-printed-hinge"]), reader.asked)
        self.cur.execute("SELECT trigger, reads FROM mx_scout_runs WHERE id = %s", (body["id"],))
        trig, reads = self.cur.fetchone()
        self.assertEqual(trig, "tap")
        self.assertGreaterEqual(reads, 1)

    def test_a_folder_without_a_description_is_not_scouted(self):
        with self.conn.transaction():
            tracks.set_topic(self.cur, self.folder, description="", excludes=None)
        self.assertEqual(call("POST", f"/api/markx/tracks/{self.folder}/scout")[0], 400)


class Finders(_Scout):
    def test_the_matches_links_by_address_key(self):
        followed = insert_scratch_source(self.cur, platform="rss")
        self.cur.execute("UPDATE sources SET handle_or_url = 'https://followed.example/feed' WHERE id = %s", (followed,))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (followed,))
        self.in_post(links=["https://makers.example/blog/a-printed-hinge", "https://github.com/makerco/hinge",
                            "https://followed.example/a-post-we-read", "https://docs.makers.example/docs/setup"])
        self.in_post(links=["https://makers.example/blog/a-printed-clip", "https://www.reddit.com/r/printedparts/comments/1/x",
                            "http://localhost:3000/demo", "https://www.reddit.com/submit?url=https%3A%2F%2Fmakers.example%2Fa"])
        with self.conn.transaction():
            got = scout.match_candidates(self.cur, self.folder)
        keys = [c["key"] for c in got]
        self.assertEqual(keys[0], "makers.example")                           # linked by two posts: first
        self.assertEqual(got[0]["evidence"]["posts"], 2)
        self.assertIn("github.com/makerco", keys)                              # a code host's thing: its owner
        self.assertIn("reddit.com/r/printedparts", keys)                       # a place; the run adds no Reddit
        self.assertNotIn("localhost", keys)                                    # no public host
        self.assertFalse([k for k in keys if "submit" in k])                   # an action link
        self.assertNotIn("followed.example", keys)                             # followed
        self.assertNotIn("docs.makers.example", keys)                          # a reference place
        self.assertEqual(got[0]["finder"], "match")

    def test_the_matches_read_the_accounts_posts_mention(self):
        # an @mention (post_links kind 'mention', stored as boilerplate) is a link of the account it names
        for k in range(2):
            p = self.in_post(f"part {k}")
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position, kind, boilerplate) "
                             "VALUES (%s, 'https://x.com/hinge_maker', 'x.com', 0, 'mention', true)", (p,))
        with self.conn.transaction():
            got = {c["key"]: c for c in scout.match_candidates(self.cur, self.folder)}
        self.assertEqual(got["x.com/hinge_maker"]["evidence"]["posts"], 2)
        self.assertEqual(got["x.com/hinge_maker"]["platform"], "x")

    def test_the_run_holds_each_finder_and_the_scout_question(self):
        self.in_post(links=["https://makers.example/blog/a-printed-hinge"])
        run = self.start()
        finders = {f for f, *_ in self.cands(run["id"])}
        self.assertEqual(finders, {"match", "shape"})
        self.assertFalse([a for _, _, _, a in self.cands(run["id"]) if "reddit" in a])
        task = repo.get_task(self.cur, self.scout_task(run["id"]))
        self.assertEqual((task["kind"], task["guide"], str(task["a"])), ("scout", "scout-v1", self.folder))
        self.assertIn("Belongs: Printable parts", task["input"])
        self.assertIn("Best posts so far:", task["input"])
        answer = {"sources": [{"platform": "reddit", "address": "r/printedparts"},
                              {"platform": "youtube", "address": "@hingechannel", "why": "hinges"},
                              {"platform": "site", "address": "makers.example"},          # finder 1 named it first
                              {"platform": "site", "address": "parts.example/blog"},
                              {"platform": "x", "address": "@partsguy"}]}
        status, body = self.answer((task["id"], answer))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        got = {k: f for f, k, *_ in self.cands(run["id"])}
        self.assertNotIn("reddit.com/r/printedparts", got)                    # no server read reaches Reddit (0262)
        self.assertEqual(got["x.com/partsguy"], "haiku")
        self.assertEqual(got["makers.example"], "match")
        self.assertEqual(got["youtube.com/@hingechannel"], "haiku")
        self.assertEqual(got["parts.example"], "haiku")

    def test_the_same_question_is_asked_once(self):
        self.in_post()
        a = self.start()
        b = self.start()
        self.assertEqual(self.scout_task(a["id"]), self.scout_task(b["id"]))
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'scout'")
        self.assertEqual(self.cur.fetchone()[0], 1)


class TestReads(_Scout):
    def test_the_read_goes_to_the_scratch_area_and_nothing_is_followed(self):
        self.in_post(links=["https://makers.example/blog/a-printed-hinge"])
        self.cur.execute("SELECT count(*) FROM sources")
        sources = self.cur.fetchone()[0]
        self.cur.execute("SELECT count(*) FROM posts")
        posts = self.cur.fetchone()[0]
        run = self.start()
        reader = StubReader({"https://makers.example": feed_result("https://makers.example")})
        out = self.advance(run["id"], reader)
        self.assertTrue(out["claimed"])
        self.cur.execute("""SELECT c.state, c.resolved->>'via', count(i.id) FROM mx_scout_candidates c
                              LEFT JOIN mx_scout_items i ON i.candidate_id = c.id
                             WHERE c.key = 'makers.example' GROUP BY 1, 2""")
        self.assertEqual(self.cur.fetchone(), ("read", "feed", 20))
        self.cur.execute("SELECT count(*) FROM sources")
        self.assertEqual(self.cur.fetchone()[0], sources)                     # nothing followed
        self.cur.execute("SELECT count(*) FROM posts")
        self.assertEqual(self.cur.fetchone()[0], posts)                       # nothing in the feed
        self.cur.execute("SELECT count(*) FROM source_folders WHERE folder_id = %s", (self.folder,))
        self.assertEqual(self.cur.fetchone()[0], 1)
        # every read item is put to the track's judge (a `track` task of subject scout_item)
        self.cur.execute("""SELECT count(*), count(DISTINCT t.subject_kind), min(t.kind) FROM mx_scout_items i
                              JOIN mx_tasks t ON t.id = i.task_id""")
        self.assertEqual(self.cur.fetchone(), (20, 1, "track"))
        self.cur.execute("""SELECT count(*) FROM mx_tasks t WHERE t.kind = 'track' AND t.subject_kind = 'scout_item'
                              AND NOT EXISTS (SELECT 1 FROM mx_scout_items i WHERE i.id = t.a)""")
        self.assertEqual(self.cur.fetchone()[0], 0)                            # a judge question is about an item
        self.assertEqual(tracks.open_tasks(self.cur), 1)                       # the in post's only: never the cap's

    def test_a_candidate_that_cannot_be_read_says_why_and_is_not_judged(self):
        self.in_post(links=["https://makers.example/blog/a-printed-hinge"])
        run = self.start()
        self.advance(run["id"], StubReader())
        self.cur.execute("SELECT state, reason FROM mx_scout_candidates WHERE key = 'makers.example'")
        self.assertEqual(self.cur.fetchone(), ("unreadable", "none found"))
        self.cur.execute("SELECT count(*) FROM mx_scout_items")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_reads_off_on_a_machine_that_must_not_fetch(self):
        self.in_post(links=["https://makers.example/blog/a-printed-hinge"])
        run = self.start()
        reader = StubReader(default=feed_result)
        with mock.patch.dict("os.environ", {"INSIGHT_DISCOVER_READS": "0"}):
            self.advance(run["id"], reader)
        self.assertEqual(reader.asked, [])


class Ranking(_Scout):
    def run_with(self, results):
        self.in_post(links=[f"https://{h}/blog/a-printed-part" for h in results])
        run = self.start()
        reader = StubReader({f"https://{h}": r for h, r in results.items()})
        self.advance(run["id"], reader)
        return run["id"]

    def test_ranked_by_precision_with_the_30_percent_floor(self):
        rid = self.run_with({"high.example": feed_result("https://high.example"),
                             "mid.example": feed_result("https://mid.example"),
                             "low.example": feed_result("https://low.example"),
                             "undated.example": feed_result("https://undated.example", dated=False)})
        share = {"high.example": 18, "mid.example": 8, "low.example": 4}

        def fits(url):
            host = url.split("/")[2]
            return int(url.rsplit("p", 1)[1]) < share.get(host, 0)
        self.judge_all(rid, fits)
        status, body = call("GET", f"/api/markx/tracks/{self.folder}/scout")
        self.assertEqual(status, 200, body)
        self.assertEqual([(r["key"], r["fits"], r["judged"]) for r in body["suggested"]],
                         [("high.example", 18, 20), ("mid.example", 8, 20)])            # 4 of 20 (20%) is under 30%
        self.assertEqual(body["suggested"][0]["precision"], 0.9)
        self.assertEqual(body["suggested"][0]["cadence"], "7 a week")
        self.assertEqual([(r["key"], r["reason"]) for r in body["reads_badly"]],
                         [("undated.example", "undated: 20 of 20 items have no date")])
        self.assertTrue(body["unreadable"])                                    # the shapes no one answered
        self.assertTrue(all(r["reason"] == "none found" for r in body["unreadable"]))
        status, rows = call("GET", "/api/markx/scout/suggestions")
        self.assertEqual([(r["key"], r["track_name"].startswith("Cool parts")) for r in rows],
                         [("high.example", True), ("mid.example", True)])

    def test_follow_as_active_and_passive_through_the_add_path_with_provenance(self):
        rid = self.run_with({"high.example": feed_result("https://high.example"),
                             "mid.example": feed_result("https://mid.example")})
        self.judge_all(rid, lambda url: True)
        self.cur.execute("SELECT key, id::text FROM mx_scout_candidates WHERE run_id = %s", (rid,))
        ids = dict(self.cur.fetchall())
        with self.conn.transaction():
            a = scout.follow(self.cur, ids["high.example"], "active", add_source=self.add_source)
            b = scout.follow(self.cur, ids["mid.example"], "passive", add_source=self.add_source)
        self.assertEqual([c[:2] for c in self.calls], [("rss", "https://high.example/feed.xml"),
                                                        ("rss", "https://mid.example/feed.xml")])
        self.cur.execute("SELECT source_id::text FROM source_folders WHERE folder_id = %s", (self.folder,))
        members = {r[0] for r in self.cur.fetchall()}
        self.assertIn(a["source_id"], members)                                 # active: in the track's folder
        self.assertNotIn(b["source_id"], members)                              # passive: read, not in it
        self.cur.execute("SELECT source_id::text, kind, run_id::text, track_id::text, as_active FROM mx_source_provenance")
        self.assertEqual(sorted(self.cur.fetchall()), sorted([(a["source_id"], "scout", rid, self.folder, True),
                                                              (b["source_id"], "scout", rid, self.folder, False)]))
        body = call("GET", f"/api/markx/tracks/{self.folder}/scout")[1]
        self.assertEqual(body["suggested"], [])                                # answered: not suggested again
        self.assertEqual({f["as"] for f in body["followed"]}, {"active", "passive"})
        # its later precision: a post of the followed source judged in the track
        p = self.post(title="a later part", source=a["source_id"])
        self.judged(p, "active")
        got = {f["source_id"]: f for f in call("GET", f"/api/markx/tracks/{self.folder}/scout")[1]["followed"]}
        self.assertEqual((got[a["source_id"]]["fits"], got[a["source_id"]]["judged"]), (1, 1))

    def test_not_this_one_is_never_offered_again_for_the_track(self):
        rid = self.run_with({"high.example": feed_result("https://high.example")})
        self.cur.execute("SELECT id::text FROM mx_scout_candidates WHERE run_id = %s AND key = 'high.example'", (rid,))
        cid = self.cur.fetchone()[0]
        self.assertEqual(call("POST", f"/api/markx/scout/candidates/{cid}/not")[0], 200)
        run = self.start()
        self.assertNotIn("high.example", [k for _, k, *_ in self.cands(run["id"])])

    def test_an_unreadable_candidate_cannot_be_followed(self):
        rid = self.run_with({})
        self.cur.execute("SELECT id::text FROM mx_scout_candidates WHERE run_id = %s LIMIT 1", (rid,))
        cid = self.cur.fetchone()[0]
        status, body = call("POST", f"/api/markx/scout/candidates/{cid}/follow", body={"as": "active"})
        self.assertEqual(status, 400, body)


class CostGuard(_Scout):
    def test_reads_judgements_and_requests_are_capped(self):
        self.in_post(links=[f"https://site{k}.example/blog/a-printed-part" for k in range(8)])
        run = self.start()
        reader = StubReader(default=feed_result)
        with mock.patch.object(scout, "MAX_READS", 5), mock.patch.object(scout, "MAX_JUDGEMENTS", 30):
            self.advance(run["id"], reader)
            self.cur.execute("SELECT reads, judgements, requests, status FROM mx_scout_runs WHERE id = %s", (run["id"],))
            reads, judgements, requests, status = self.cur.fetchone()
            self.assertEqual((reads, judgements, requests), (5, 30, 15))
            self.assertEqual(len(reader.asked), 5)
            self.advance(run["id"], reader)                                    # a second advance reads nothing more
            self.assertEqual(len(reader.asked), 5)
        self.assertEqual(status, "waiting")                                    # the scout question and judges are open
        self.cur.execute("SELECT stats->'spent' FROM mx_scout_runs WHERE id = %s", (run["id"],))
        self.assertEqual(self.cur.fetchone()[0], {"reads": 5, "requests": 15, "judgements": 30})

    def test_the_request_budget_stops_the_reads(self):
        self.in_post(links=[f"https://site{k}.example/blog/a-printed-part" for k in range(6)])
        run = self.start()
        reader = StubReader(default=lambda a: scout_reads.ReadResult(reason="blocked", requests=50))
        with mock.patch.object(scout, "MAX_REQUESTS", 120):
            self.advance(run["id"], reader)
        self.assertEqual(len(reader.asked), 3)                                 # 50 + 50 + 50 >= 120

    def test_finder_shares_then_refill(self):
        self.in_post(links=[f"https://site{k}.example/blog/a-printed-part" for k in range(3)])
        run = self.start()
        with mock.patch.dict(scout.READ_SHARE, {"maker": 0, "match": 2, "haiku": 0, "web": 0, "shape": 1}), \
                mock.patch.object(scout, "MAX_READS", 4):
            with self.conn.transaction():
                picked = scout.to_read(self.cur, run["id"])
        self.assertEqual([c["finder"] for c in picked], ["match", "match", "shape", "match"])

    def test_two_advances_never_read_one_run_at_once(self):
        # both claims on one clock (NOW), so the claim cannot expire under a slow suite
        self.in_post(links=["https://makers.example/blog/a-printed-hinge"])
        run = self.start()
        with self.conn.transaction():
            self.assertTrue(scout.claim(self.cur, run["id"], NOW))
        self.assertFalse(self.advance(run["id"], StubReader(), now=lambda: NOW + timedelta(minutes=1))["claimed"])
        self.assertTrue(self.advance(run["id"], StubReader(), now=lambda: NOW + scout.CLAIM + timedelta(minutes=1))["claimed"],
                        "a claim ends after scout.CLAIM")


def web_answer(*urls):
    return {"candidates": [{"url": u, "title": f"Result {k}", "why": "a maker's own site; launched a part this week"}
                           for k, u in enumerate(urls)], "queries": ["new printable parts this week"]}


def sites_answer(prefix="parts", n=5):
    return {"sources": [{"platform": "site", "address": f"{prefix}{k}.example/blog", "why": "parts"} for k in range(n)]}


class Settling(_Scout):
    """Production's Cool Projects run (a17bba84) stayed `running` from 2026-11-20: its 40 reads were spent before the
    scout question's answer came, the answer set it running again, and nothing settles a run with nothing to read;
    the one open weekly run held every other track's."""

    def test_a_run_whose_reads_are_spent_is_done_when_its_late_answer_comes(self):
        self.in_post(links=["https://makers.example/blog/a-printed-hinge"])
        run = self.start(trigger="weekly")
        with mock.patch.object(scout, "MAX_READS", 1), mock.patch.object(scout, "reads_allowed", return_value=True):
            self.advance(run["id"], StubReader())
            self.cur.execute("SELECT status, reads FROM mx_scout_runs WHERE id = %s", (run["id"],))
            self.assertEqual(self.cur.fetchone(), ("waiting", 1))                 # the scout question is open
            status, body = self.answer((self.scout_task(run["id"]), sites_answer()),
                                       (self.web_task(run["id"]), web_answer()))
            self.assertEqual((status, body["valid"]), (200, 2), body)
            self.cur.execute("SELECT status FROM mx_scout_runs WHERE id = %s", (run["id"],))
            self.assertEqual(self.cur.fetchone()[0], "running")                   # as production's: nothing to read
            out = asyncio.run(scout.tick(db_url(), reader=StubReader()))
        self.assertEqual(out["settled"], {run["id"]: "done"})
        self.cur.execute("SELECT status, finished_at IS NOT NULL FROM mx_scout_runs WHERE id = %s", (run["id"],))
        self.assertEqual(self.cur.fetchone(), ("done", True))

    def test_a_stalled_weekly_run_is_closed_and_the_next_track_starts(self):
        self.cur.execute("INSERT INTO folders (name, kind) VALUES (%s, 'track') RETURNING id",
                         (f"Quiet parts {uuid.uuid4().hex[:6]}",))
        quiet = str(self.cur.fetchone()[0])
        self.addCleanup(self.cur.execute, "DELETE FROM folders WHERE id = %s", (quiet,))
        with self.conn.transaction():
            tracks.set_topic(self.cur, quiet, description="Quiet parts: rarely posted printed parts", excludes=None)
        with mock.patch.object(scout, "reads_allowed", return_value=True):
            first = asyncio.run(scout.tick(db_url(), reader=StubReader()))
            self.assertEqual(len(first["started"]), 1)
            self.cur.execute("SELECT status FROM mx_scout_runs WHERE id = %s", (first["started"][0],))
            self.assertEqual(self.cur.fetchone()[0], "waiting")                   # its scout question never answered
            same_day = asyncio.run(scout.tick(db_url(), reader=StubReader(), now=lambda: NOW + DAY))
            self.assertEqual(same_day["started"], [])                             # one weekly run at a time
            later = asyncio.run(scout.tick(db_url(), reader=StubReader(), now=lambda: NOW + scout.STALL + DAY))
        self.assertEqual(later["settled"], {first["started"][0]: "done"})
        self.cur.execute("SELECT stats->>'closed' FROM mx_scout_runs WHERE id = %s", (first["started"][0],))
        self.assertTrue(self.cur.fetchone()[0].startswith("stalled: still waiting"))
        self.assertEqual(len(later["started"]), 1)
        self.cur.execute("SELECT track_id::text FROM mx_scout_runs WHERE trigger = 'weekly'")
        self.assertEqual({r[0] for r in self.cur.fetchall()}, {self.folder, quiet})   # every described track


class Shares(_Scout):
    def test_haikus_share_is_held_until_its_question_is_answered(self):
        # production: haiku 19 candidates, 0 read: match and shape took all 40 reads before the answer came
        self.in_post(links=[f"https://site{k}.example/blog/a-printed-part" for k in range(5)])
        run = self.start()
        reader = StubReader()
        with mock.patch.dict(scout.READ_SHARE, {"maker": 0, "match": 1, "haiku": 2, "shape": 0}, clear=True), \
                mock.patch.object(scout, "MAX_READS", 4), mock.patch.object(scout, "reads_allowed", return_value=True):
            self.advance(run["id"], reader)
            self.assertEqual(len(reader.asked), 2)                               # 4 - haiku's 2 held
            status, body = self.answer((self.scout_task(run["id"]), sites_answer()))
            self.assertEqual((status, body["valid"]), (200, 1), body)
            self.advance(run["id"], reader)
        self.cur.execute("SELECT finder, count(*) FROM mx_scout_candidates WHERE run_id = %s AND state <> 'new' GROUP BY 1",
                         (run["id"],))
        self.assertEqual(dict(self.cur.fetchall()), {"match": 2, "haiku": 2})


class Makers(_Scout):
    def mention(self, post, name, type_, role):
        """Mark X's entity row of `post` (mx_mentions_now)."""
        schemas.ensure_guides(self.cur)
        task, _ = repo.add_task(self.cur, kind="track", guide="track-v1", subject_kind="post_track",
                                input=f"m {uuid.uuid4().hex}", a=post, b=self.folder)
        self.cur.execute("INSERT INTO mx_calls (task_id, executor, model, valid) VALUES (%s, 'api', 'test', true) "
                         "RETURNING id", (task,))
        call = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO mx_mention_sets (post_id, guide, call_id) VALUES (%s, 'track-v1', %s) "
                         "ON CONFLICT (post_id) DO NOTHING", (post, call))
        self.cur.execute("SELECT call_id FROM mx_mention_sets WHERE post_id = %s", (post,))
        call = self.cur.fetchone()[0]
        self.cur.execute("SELECT count(*) FROM mx_mentions WHERE post_id = %s", (post,))
        n = self.cur.fetchone()[0]
        self.cur.execute("""INSERT INTO mx_mentions (post_id, guide, n, call_id, span, name, name_key, type, role)
                            VALUES (%s, 'track-v1', %s, %s, %s, %s, %s, %s, %s)""",
                         (post, n, call, name, name, name.casefold(), type_, role))

    def link(self, post, url, kind="mention"):
        self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position, kind, boilerplate) "
                         "VALUES (%s, %s, %s, 9, %s, %s)", (post, url, url.split("/")[2], kind, kind == "mention"))

    def the_case(self):
        # @DataChaz's repost: "a tiny cursor-emotion model at libraries.dev, created by the great @Jakubantalik"
        p = self.in_post("A tiny model that reads your cursor's mood", links=["https://libraries.dev/cursor-emotion"])
        self.link(p, "https://x.com/Jakubantalik")
        self.mention(p, "Jakub Antalik", "person", "actor")
        self.mention(p, "libraries.dev", "org", "venue")
        return p

    def test_the_maker_of_a_find_is_a_candidate_from_one_post(self):
        self.the_case()
        other = self.in_post("Another find", links=["https://quiet.example/blog/a-thing"])
        self.link(other, "https://x.com/somebody_else")
        self.mention(other, "Ada Lovelace", "person", "actor")               # her handle is not linked here
        run = self.start()
        got = {k: (f, a) for f, k, _, a in self.cands(run["id"])}
        self.assertEqual(got["x.com/jakubantalik"], ("maker", "https://x.com/jakubantalik"))
        self.cur.execute("SELECT why, name, evidence->>'person' FROM mx_scout_candidates WHERE run_id = %s AND key = %s",
                         (run["id"], "x.com/jakubantalik"))
        self.assertEqual(self.cur.fetchone(),
                         ("made something 1 of the track's posts is about", "Jakub Antalik", "Jakub Antalik"))
        self.assertEqual(got["x.com/somebody_else"][0], "match")                # a link, no one's own
        self.assertNotIn("maker", {f for k, (f, _) in got.items() if k != "x.com/jakubantalik"})

    def test_following_the_maker_adds_the_x_bridge_feed_the_add_path_follows(self):
        self.the_case()
        run = self.start()
        feed = rss("Jakub Antalik / @jakubantalik", n=8, base="https://nitter.local/jakubantalik/status/19900000000000000")
        http = FakeHttp(lambda url: feed if url == "https://nitter.local/jakubantalik/rss" else ValueError(f"HTTP 404 {url}"))
        reader = scout_reads.Reader(http, KindRegistry.default(http, None), page_gap=0)
        with mock.patch.dict("os.environ", {"NITTER_HOSTS": "nitter.local"}), \
                mock.patch.object(scout, "reads_allowed", return_value=True):
            self.advance(run["id"], reader)
        self.cur.execute("SELECT id::text, state, resolved->>'handle_or_url' FROM mx_scout_candidates "
                         "WHERE run_id = %s AND key = 'x.com/jakubantalik'", (run["id"],))
        cid, state, address = self.cur.fetchone()
        self.assertEqual((state, address), ("read", "https://nitter.local/jakubantalik/rss"))
        with self.conn.transaction():
            scout.follow(self.cur, cid, "passive", add_source=self.add_source)
        self.assertEqual(self.calls[0][:2], ("rss", "https://nitter.local/jakubantalik/rss"))


class Web(_Scout):
    def test_the_run_asks_one_web_search_of_its_sphere(self):
        with self.conn.transaction():
            tracks.set_topic(self.cur, self.folder, description="Printable parts: useful 3D printed parts and why",
                             excludes="filament sales")
        run = self.start()
        task = repo.get_task(self.cur, self.web_task(run["id"]))
        self.assertEqual((task["kind"], task["guide"], task["subject_kind"], str(task["a"])),
                         ("websearch", "websearch-sphere-v1", "track", self.folder))
        for line in ("Track: Cool parts", "Belongs: Printable parts", "Not: filament sales", "Week of: ",
                     "Searches allowed: at most 5"):
            self.assertIn(line, task["input"])
        again = self.start()                                                  # this week's question is one task
        self.assertEqual(self.web_task(again["id"]), self.web_task(run["id"]))

    def test_a_sphere_answer_reaches_the_scout_never_research(self):
        run = self.start()
        with mock.patch("insight_core.markx.research.after_websearch") as research_after:
            status, body = self.answer((self.web_task(run["id"]), web_answer("https://parts-maker.example/",
                                                                             "https://x.com/partsmaker")))
            self.assertEqual((status, body["valid"]), (200, 1), body)
            research_after.assert_not_called()
            # a maker's research (websearch-v1) still goes to research
            task, _ = repo.add_task(self.cur, kind="websearch", guide="websearch-v1", subject_kind="research_run",
                                    input=f"Maker: Acme {uuid.uuid4().hex}", a=str(uuid.uuid4()))
            self.assertEqual(self.answer((task, web_answer("https://acme.example/")))[0], 200)
            self.assertEqual(research_after.call_count, 1)
        got = {k: (f, w) for f, k, _, w in self._cands_why(run["id"])}
        self.assertEqual(got["parts-maker.example"][0], "web")
        self.assertEqual(got["x.com/partsmaker"], ("web", "a maker's own site; launched a part this week"))

    def _cands_why(self, run_id):
        self.cur.execute("SELECT finder, key, state, why FROM mx_scout_candidates WHERE run_id = %s ORDER BY rank",
                         (run_id,))
        return self.cur.fetchall()

    def test_webs_share_is_held_until_its_search_is_answered(self):
        self.in_post(links=[f"https://site{k}.example/blog/a-printed-part" for k in range(5)])
        run = self.start()
        status, body = self.answer((self.scout_task(run["id"]), sites_answer()))   # haiku answered first
        self.assertEqual(body["valid"], 1, body)
        reader = StubReader()
        with mock.patch.dict(scout.READ_SHARE, {"maker": 0, "match": 1, "haiku": 1, "web": 2, "shape": 0}, clear=True), \
                mock.patch.object(scout, "MAX_READS", 5), mock.patch.object(scout, "reads_allowed", return_value=True):
            self.advance(run["id"], reader)
            self.assertEqual(len(reader.asked), 3)                               # 5 - web's 2 held
            self.cur.execute("SELECT status FROM mx_scout_runs WHERE id = %s", (run["id"],))
            self.assertEqual(self.cur.fetchone()[0], "waiting")                   # the web search is open
            status, body = self.answer((self.web_task(run["id"]), web_answer(
                "https://maker-a.example/", "https://maker-b.example/", "https://maker-c.example/")))
            self.assertEqual(body["valid"], 1, body)
            self.advance(run["id"], reader)
        self.cur.execute("SELECT finder, count(*) FROM mx_scout_candidates WHERE run_id = %s AND state <> 'new' GROUP BY 1",
                         (run["id"],))
        self.assertEqual(dict(self.cur.fetchall()), {"match": 2, "haiku": 1, "web": 2})

    def test_a_late_answer_to_a_closed_run_adds_nothing(self):
        run = self.start()
        self.cur.execute("UPDATE mx_scout_runs SET status = 'done', finished_at = now() WHERE id = %s", (run["id"],))
        self.answer((self.web_task(run["id"]), web_answer("https://maker-a.example/")),
                    (self.scout_task(run["id"]), sites_answer()))
        self.cur.execute("SELECT count(*) FROM mx_scout_candidates WHERE run_id = %s AND finder IN ('web', 'haiku')",
                         (run["id"],))
        self.assertEqual(self.cur.fetchone()[0], 0)
        self.cur.execute("SELECT status FROM mx_scout_runs WHERE id = %s", (run["id"],))
        self.assertEqual(self.cur.fetchone()[0], "done")


class Value(_Scout):
    """GET /api/markx/scout/value: what a followed scout source brought the track that no other source had."""

    def setUp(self):
        super().setUp()
        self.brought = self.add_source("rss", "https://maker.example/feed.xml", {})
        self.cur.execute("INSERT INTO mx_source_provenance (source_id, kind, track_id, as_active, created_at) "
                         "VALUES (%s, 'scout', %s, true, %s)", (self.brought, self.folder, NOW - 10 * DAY))

    def scout_post(self, title, at, links=()):
        p = self.post(title=title, source=self.brought, at=at, links=[(u, None) for u in links])
        self.judged(p, "active")
        return p

    def story(self, *members):
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, %s)", (members[0], NOW, len(members)))
        for m in members:
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice) VALUES (%s, %s, 'report', %s)",
                             (m, members[0], m))

    def test_unique_covered_by_a_story_and_by_a_link(self):
        unique = self.scout_post("A tiny cursor-emotion model", NOW - 3 * DAY)
        by_story = self.scout_post("A printed hinge, version 2", NOW - 4 * DAY)
        self.story(by_story, self.post(title="Hinge v2 is out", source=self.other, at=NOW - 4 * DAY + timedelta(hours=5)))
        by_link = self.scout_post("The launch", NOW - 5 * DAY, links=["https://libraries.example/cursor-emotion"])
        self.post(title="Someone shared it", source=self.other, at=NOW - 5 * DAY + timedelta(hours=9),
                  links=[("https://libraries.example/cursor-emotion", None)])
        far = self.scout_post("Old news again", NOW - 6 * DAY, links=["https://far.example/a-page"])
        self.post(title="Weeks later", source=self.other, at=NOW - 6 * DAY + 20 * DAY,   # outside 14 days: not covered
                  links=[("https://far.example/a-page", None)])
        self.post(title="Not kept by the track", source=self.brought, at=NOW - 2 * DAY)
        self.scout_post("Links only a home page", NOW - 2 * DAY, links=["https://bigsite.example/", "https://x.com/bigsite"])
        self.post(title="Also links the home page", source=self.other, at=NOW - 2 * DAY,
                  links=[("https://bigsite.example/", None), ("https://x.com/bigsite", None)])   # who, not what
        status, body = call("GET", "/api/markx/scout/value", query={"track": self.folder})
        self.assertEqual(status, 200, body)
        row = body["sources"][0]
        self.assertEqual((row["source_id"], row["track"], row["via"]), (self.brought, self.folder, "scout"))
        self.assertEqual((row["posts"], row["in"], row["unique"], row["covered"], row["first"]), (6, 5, 3, 2, 2))
        self.assertEqual(row["lead_hours"], 7.0)                                 # median of 5 and 9 hours
        self.assertEqual({e["title"] for e in row["examples"]},
                         {"A tiny cursor-emotion model", "Old news again", "Links only a home page"})
        self.assertEqual(body["total"]["unique"], 3)
        self.assertEqual(body["tracks"][0]["track"], self.folder)
        self.assertEqual(body["followed_at"], "mx_source_provenance.created_at")
        self.assertNotIn(unique, [])

    def test_a_post_covered_only_by_another_scout_source_is_still_unique(self):
        other_brought = self.add_source("rss", "https://maker-two.example/feed.xml", {})
        self.cur.execute("INSERT INTO mx_source_provenance (source_id, kind, track_id, as_active) "
                         "VALUES (%s, 'scout', %s, false)", (other_brought, self.folder))
        p = self.scout_post("A tool", NOW - DAY, links=["https://tool.example/launch"])
        self.post(title="Same tool", source=other_brought, at=NOW - DAY, links=[("https://tool.example/launch", None)])
        with self.conn.transaction():
            got = scout.value(self.cur, self.folder)
        mine = next(r for r in got["sources"] if r["source_id"] == self.brought)
        self.assertEqual((mine["in"], mine["unique"]), (1, 1))
        self.assertTrue(p)


if __name__ == "__main__":
    unittest.main()
