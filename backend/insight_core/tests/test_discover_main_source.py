"""Issue 0170 (v10.15 D): Discover's "main source missing": the events whose actor's own channel you don't hold, the
channel's section to follow, a followed site's other section, a disabled source that was the event's. The rules on
plain rows, the test with a fake finder, and the scan on a database whose name ends in _test (synthetic data only)."""
from __future__ import annotations

import asyncio
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from insight_core.services import discover_main_source as M
from insight_core.tests._db import clear_tables
from insight_core.tests.test_markx_api import _Api, call, reading
from insight_core.tests.test_markx_folds import read3

T0 = datetime(2100, 4, 1, 12, tzinfo=timezone.utc)
D = timedelta(days=1)


class Channels(unittest.TestCase):
    def test_a_sites_page_is_followed_by_its_section_never_the_home_page(self):
        ch = M.channel_of("https://www.acme.example/blog/widget-5-is-here")
        self.assertEqual((ch.key, ch.kind, ch.prefix), ("acme.example/blog/", "site", "/blog/"))
        self.assertRegex(ch.url, r"^https://(www\.)?acme\.example/blog$")
        self.assertEqual(M.channel_of("https://acme.example/newsroom/2100/04/widget-5").prefix, "/newsroom/")
        self.assertEqual(M.channel_of("https://acme.example/en/blog/widget-5").prefix, "/en/blog/")   # a language first
        self.assertEqual(M.channel_of("https://blog.acme.example/2100/04/widget-5").key, "blog.acme.example/")  # by date
        root = M.channel_of("https://acme.example/widget-5-launch")       # a launch page at the root: the site's root
        self.assertEqual((root.key, root.prefix, root.url), ("acme.example/", "/", "https://acme.example/"))
        self.assertIsNone(M.channel_of("https://acme.example/"))           # a home page says who, not what

    def test_a_post_on_x_or_telegram_is_its_account(self):
        x = M.channel_of("https://nitter.local/AcmeLabs/status/2112345678901234567#m")
        self.assertEqual((x.key, x.kind, x.platform, x.url), ("x.com/acmelabs", "account", "x", "https://x.com/acmelabs"))
        tg = M.channel_of("https://t.me/acme_news/42")
        self.assertEqual((tg.key, tg.platform), ("t.me/acme_news", "telegram"))
        self.assertIsNone(M.channel_of("https://x.com/acmelabs"))         # a profile is no post

    def test_platforms_code_hubs_papers_references_and_product_pages_are_nobodys_channel(self):
        for url in ("https://github.com/acme/widget", "https://huggingface.co/acme/widget-5", "https://arxiv.org/abs/2604.01234",
                    "https://www.reddit.com/r/acme/comments/abc/widget/", "https://www.youtube.com/watch?v=abc",
                    "https://docs.acme.example/widget/start", "https://acme.example/docs/widget-5",
                    "https://acme.example/pricing", "https://acme.example/legal/terms", "https://help.acme.example/en/articles/1"):
            self.assertIsNone(M.channel_of(url), url)

    def test_owner_reads_a_hosting_platforms_writer_and_a_two_part_ending(self):
        self.assertEqual(M.owner("writer.github.io/blog/post"), "writer")
        self.assertEqual(M.owner("news.acme.co.uk/2100/04/x"), "acme")
        self.assertEqual(M.owner("x.com/acmelabs/status/2112345678901234567"), "acmelabs")


def src(sid, *, kind="site", host="", account=None, enabled=True, watch=None, sections=(), name=None):
    return M.Src(sid, name or sid, enabled, kind, account, host, watch, frozenset(sections))


BLOG = M.channel_of("https://acme.example/blog/widget-5")
PAGE = "https://acme.example/blog/widget-5"


class Covers(unittest.TestCase):
    def test_a_page_watch_covers_what_is_under_its_prefix(self):
        self.assertTrue(M.covers(src("a", host="acme.example", watch="/blog/"), BLOG, PAGE))
        self.assertFalse(M.covers(src("a", host="acme.example", watch="/news/"), BLOG, PAGE))
        self.assertTrue(M.covers(src("a", host="acme.example", watch="/"), BLOG, PAGE))
        self.assertFalse(M.covers(src("a", host="safety.acme.example", watch="/"), BLOG, PAGE))   # another host

    def test_a_feed_covers_the_sections_its_posts_are_in_and_unknown_when_it_holds_none(self):
        self.assertTrue(M.covers(src("a", host="acme.example", sections=[("acme.example", "/blog/")]), BLOG, PAGE))
        self.assertFalse(M.covers(src("a", host="acme.example", sections=[("acme.example", "/news/")]), BLOG, PAGE))
        self.assertIsNone(M.covers(src("a", host="acme.example"), BLOG, PAGE))

    def test_on_the_channel_by_account_or_by_the_sources_own_site(self):
        x = M.channel_of("https://x.com/acmelabs/status/2112345678901234567")
        self.assertTrue(M.on_channel(src("a", kind="x", account="x.com/acmelabs"), x))
        self.assertFalse(M.on_channel(src("a", kind="x", account="x.com/other"), x))
        self.assertTrue(M.on_channel(src("a", host="safety.acme.example"), BLOG))     # one site
        # a link blog whose posts sit at the actor's addresses is not the actor's channel
        self.assertFalse(M.on_channel(src("a", host="linkblog.example", sections=[("acme.example", "/blog/")]), BLOG))
        self.assertFalse(M.on_channel(src("a", kind="hn", host="acme.example"), BLOG))


def ev(story="s1", pages=(("https://acme.example/blog/widget-5", "linked"),), members=("m1", "m2"), mine=(),
       at=T0, actor="acme"):
    return M.Event(story=story, headline=f"Acme ships {story}", event_type="model_release", voices=len(members),
                   first_at=at, actor=actor, actor_name="Acme", pages=[M.OwnPage(u, how) for u, how in pages],
                   member_sources=set(members), actor_sources=set(mine),
                   posts=[{"id": "p1", "title": "Widget 5", "source": "m1", "source_id": "m1", "url": None, "at": None}])


MEMBERS = {"m1": src("m1", kind="telegram", account="t.me/m1"), "m2": src("m2", host="reporter.example")}


class Judge(unittest.TestCase):
    def test_no_source_on_the_channel_is_missing_its_section_to_follow(self):
        rows = M.judge([ev()], MEMBERS)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["kind"], r["key"], r["channel"]["url"], r["channel"]["prefix"]),
                         ("missing", "main:acme.example/blog/", "https://acme.example/blog", "/blog/"))
        self.assertEqual(r["actor"], {"id": "acme", "name": "Acme"})
        self.assertEqual(r["events"][0]["own_page"]["url"], "https://acme.example/blog/widget-5")

    def test_a_followed_site_whose_section_misses_the_page_is_a_second_section(self):
        news = src("news", host="acme.example", sections=[("acme.example", "/news/")], name="Acme News")
        r = M.judge([ev()], {**MEMBERS, "news": news})[0]
        self.assertEqual((r["kind"], r["source"]["name"], r["channel"]["prefix"]), ("wrong_section", "Acme News", "/blog/"))
        watch = src("watch", host="acme.example", watch="/news/")
        self.assertEqual(M.judge([ev()], {**MEMBERS, "watch": watch})[0]["kind"], "wrong_section")

    def test_a_followed_section_that_covers_the_page_is_no_row(self):
        for s in (src("w", host="acme.example", watch="/blog/"), src("f", host="acme.example"),   # unknown: no claim
                  src("f", host="acme.example", sections=[("acme.example", "/blog/")])):
            self.assertEqual(M.judge([ev()], {**MEMBERS, s.id: s}), [], s)

    def test_one_covering_channel_makes_the_whole_event_followed(self):
        x = src("x", kind="x", account="x.com/acmelabs")
        e = ev(pages=(("https://acme.example/blog/widget-5", "held"), ("https://x.com/acmelabs/status/2112345678901234567", "linked")))
        self.assertEqual(M.judge([e], {**MEMBERS, "x": x}), [])

    def test_a_switched_off_source_covering_the_page_is_never_suggested(self):
        """Issue 0200 (v10.17.1): the owner switched it off; before, a `disabled` row asked to switch it on."""
        off = src("off", host="acme.example", watch="/blog/", enabled=False, name="Acme Blog")
        self.assertEqual(M.judge([ev()], {**MEMBERS, "off": off}), [])
        # the same source on: followed, no row either; nothing is ever `disabled`
        on = src("off", host="acme.example", watch="/blog/", enabled=True, name="Acme Blog")
        self.assertEqual(M.judge([ev()], {**MEMBERS, "off": on}), [])

    def test_a_switched_off_source_named_for_the_actor_is_not_surfaced(self):
        off = src("sub", kind="reddit", enabled=False, name="r/acme")
        rows = M.judge([ev(mine=("sub",))], {**MEMBERS, "sub": off})
        self.assertEqual([(r["kind"], r["channel"]["key"]) for r in rows], [("missing", "acme.example/blog/")])
        on = src("sub", kind="reddit", enabled=True, name="r/acme")
        self.assertEqual([r["kind"] for r in M.judge([ev(mine=("sub",))], {**MEMBERS, "sub": on})], ["missing"])

    def test_the_actors_own_post_in_the_story_is_no_row(self):
        own = src("own", host="acme.example", sections=[("acme.example", "/news/")])
        self.assertEqual(M.judge([ev(members=("m1", "own"))], {**MEMBERS, "own": own}), [])   # its site's source
        self.assertEqual(M.judge([ev(mine=("m1",))], MEMBERS), [])                             # a source named for it

    def test_one_channel_an_event_the_best_evidenced(self):
        e = ev(pages=(("https://x.com/acmelabs/status/2112345678901234567", "held"), ("https://acme.example/blog/widget-5", "linked")))
        self.assertEqual([r["channel"]["key"] for r in M.judge([e], MEMBERS)], ["x.com/acmelabs"])

    def test_events_of_one_channel_are_one_row_the_most_events_first_then_the_latest(self):
        rows = M.judge([ev("s1", at=T0), ev("s2", at=T0 + D),
                        ev("s3", pages=(("https://x.com/other/status/2112345678901234567", "held"),), at=T0 + 5 * D)], MEMBERS)
        self.assertEqual([(r["channel"]["key"], [e["story"] for e in r["events"]]) for r in rows],
                         [("acme.example/blog/", ["s2", "s1"]), ("x.com/other", ["s3"])])

    def test_pages_on_no_channel_give_no_row(self):
        self.assertEqual(M.judge([ev(pages=(("https://github.com/acme/widget", "held"),))], MEMBERS), [])


class NamedActor(unittest.TestCase):
    def test_the_readings_name_it_first_once_and_among_the_actors_in_half(self):
        is_acme = lambda name: name == "Acme"   # noqa: E731
        self.assertTrue(M.named_actor([["Acme"], ["Acme", "Other"]], is_acme))
        self.assertTrue(M.named_actor([["Acme"], []], is_acme))                       # half
        self.assertFalse(M.named_actor([["Agency", "Acme"], ["Agency"], []], is_acme))  # cited beside, a third
        self.assertFalse(M.named_actor([["Agency", "Acme"], ["Agency", "Acme"]], is_acme))   # never first: a reporter
        self.assertFalse(M.named_actor([], is_acme))


class ThePage(unittest.TestCase):
    def test_hidden_rows_go_and_tests_are_joined(self):
        found = {"rows": M.judge([ev("s1"), ev("s3", pages=(("https://x.com/other/status/2112345678901234567", "held"),))], MEMBERS),
                 "checked": 9, "events": 2}
        got = M.page(found, {"x.com/other": {"label": "feed", "at": T0.isoformat()}}, {"main:acme.example/blog/"})
        self.assertEqual([(r["channel"]["key"], r["test"]) for r in got["rows"]],
                         [("x.com/other", {"label": "feed", "at": T0.isoformat()})])
        self.assertEqual((got["total"], got["checked"], got["events"]), (1, 9, 2))

    def test_to_test_the_shown_channels_not_tested_lately_never_a_disabled_one(self):
        off = src("off", host="acme.example", watch="/blog/", enabled=False)
        rows = M.judge([ev("s1"), ev("s2", pages=(("https://x.com/other/status/2112345678901234567", "held"),))], MEMBERS)
        rows += M.judge([ev("s3", pages=(("https://acme.example/blog/w", "held"),))], {**MEMBERS, "off": off})
        todo = M.to_test({"rows": rows}, {"x.com/other": {"label": "feed", "at": T0.isoformat()}}, T0 + D)
        self.assertEqual([(c["key"], c["pages"]) for c in todo], [("acme.example/blog/", ["https://acme.example/blog/widget-5"])])
        self.assertEqual(len(M.to_test({"rows": rows}, {}, T0 + D)), 2)
        self.assertTrue(M.due({"label": "feed", "at": T0.isoformat()}, T0 + 31 * D))


class TheTest(unittest.TestCase):
    def test_the_finder_runs_on_the_section_then_page_watching_when_it_found_nothing(self):
        ch = {"key": "acme.example/blog/", "kind": "site", "url": "https://acme.example/blog", "prefix": "/blog/"}
        follow = mock.AsyncMock(return_value={"status": "none", "feeds": [], "pages": [], "linked": 1})
        preview = mock.AsyncMock(return_value={"prefix": "/blog/", "found": 12, "sitemap": False,
                                               "items": [{"url": "https://acme.example/blog/widget-5", "title": "Widget 5",
                                                          "published_at": None}]})
        with mock.patch("insight_core.ingestion.where_linked.follow", follow), \
                mock.patch("insight_core.ingestion.kinds.page_watch.preview", preview):
            got = asyncio.run(M.test_channel(object(), object(), ch, ["https://acme.example/blog/widget-5"],
                                             clock=lambda: T0))
        self.assertEqual(follow.call_args.args[2:], ("https://acme.example/blog", ["https://acme.example/blog/widget-5"]))
        self.assertEqual(preview.call_args.args[1:], ("https://acme.example/blog", "/blog/"))
        self.assertEqual((got["label"], got["preview"]["found"], got["preview"]["items"][0]["title"], got["at"]),
                         ("page", 12, "Widget 5", T0.isoformat()))

    def test_a_feed_holding_the_page_is_feed_and_no_preview(self):
        ch = {"key": "acme.example/blog/", "kind": "site", "url": "https://acme.example/blog", "prefix": "/blog/"}
        follow = mock.AsyncMock(return_value={"status": "found", "feeds": [{"url": "https://acme.example/blog/rss",
                                                                            "title": "Acme", "holds": 1}],
                                              "pages": [], "linked": 1})
        preview = mock.AsyncMock()
        with mock.patch("insight_core.ingestion.where_linked.follow", follow), \
                mock.patch("insight_core.ingestion.kinds.page_watch.preview", preview):
            got = asyncio.run(M.test_channel(object(), object(), ch, ["https://acme.example/blog/widget-5"], clock=lambda: T0))
        self.assertEqual((got["label"], got["holds"], got["of"]), ("feed", 1, 1))
        preview.assert_not_called()

    def test_an_account_through_its_kind(self):
        kind = SimpleNamespace(name="nitter_rss", fetch_latest=mock.AsyncMock(return_value=[{"id": 1}]))
        registry = SimpleNamespace(resolve=lambda source: kind)
        ch = {"key": "x.com/acmelabs", "kind": "account", "url": "https://x.com/acmelabs", "prefix": None}
        got = asyncio.run(M.test_channel(object(), registry, ch, [], clock=lambda: T0))
        self.assertEqual(got, {"label": "feed", "at": T0.isoformat()})


class Scanned(_Api):
    """The scan on the database: Mark X's stories, readings, mentions and the sources, read only."""

    def setUp(self):
        super().setUp()
        from insight_core.markx import repo
        self.run = repo.start_run(self.cur, code_version="test", config={})
        self.host = "acme.example"
        self.made = []
        self.addCleanup(lambda: self.cur.execute("DELETE FROM sources WHERE id = ANY(%s::uuid[])", (self.made,)))
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, status)
                            VALUES ('org', 'Acme', 'acme', 'thing', 'provisional') RETURNING id::text""")
        self.acme = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO mx_entity_aliases (key, entity_id, source) VALUES ('acme', %s, 'rule')", (self.acme,))

    def site_source(self, handle, *, enabled=True, settings=None, name="Acme News"):
        self.cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest, settings) "
                         "VALUES ('rss', %s, %s, false, %s::jsonb) RETURNING id::text",
                         (handle, enabled, json.dumps({"display_name": name, **(settings or {})})))
        sid = self.cur.fetchone()[0]
        self.made.append(sid)
        return sid

    def subject(self, post):
        from insight_core.markx import repo, tasks
        with self.conn.transaction():
            task_id, _ = tasks.entities_task(self.cur, post)
            cid = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                                answer={"entities": []})
            repo.add_mentions(self.cur, post_id=post, guide="ent-v3", call_id=cid, mentions=[
                {"span": "Acme", "name": "Acme", "name_key": "acme", "type": "org", "role": "subject",
                 "maker": None, "family": None, "version": None, "variant": None, "size": None, "build": None}])
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (self.acme, post))

    def read(self, post, answer):
        from insight_core.markx import folds as F
        with self.conn.transaction():
            task_id, _ = F.read3_task(self.cur, post)
        _, got = self.answer((task_id, answer))
        self.assertEqual(got["valid"], 1, got)

    def event(self, event_type="model_release", *, page="https://acme.example/blog/widget-5-launch", sources=None):
        from insight_core.markx import repo
        now = datetime.now(timezone.utc)
        a, b = sources or (self.source, self.other)
        p1 = self.post(title="Acme ships Widget 5", source=a, at=now - 2 * D, links=[(page, "the launch")])
        p2 = self.post(title="Widget 5 is out", source=b, at=now - D, links=[(page, "Acme's post")])
        sid = repo.add_story(self.cur, first_at=now - 2 * D, run_id=self.run)
        for p in (p1, p2):
            repo.open_membership(self.cur, story_id=sid, post_id=p, role="member", reason="test", run_id=self.run)
            self.read(p, read3(event_type=event_type))
            self.subject(p)
        return str(sid)

    def rows(self):
        got = M.scan(self.cur, datetime.now(timezone.utc))
        return [r for r in got["rows"] if r["actor"]["id"] == self.acme]

    def test_an_event_linking_the_actors_page_with_no_source_on_it_is_missing(self):
        story = self.event()
        rows = self.rows()
        self.assertEqual([(r["kind"], r["channel"]["key"], r["channel"]["url"]) for r in rows],
                         [("missing", "acme.example/blog/", "https://acme.example/blog")])
        e = rows[0]["events"][0]
        self.assertEqual((e["story"], e["event_type"], e["voices"], e["own_page"]["how"]), (story, "model_release", 2, "linked"))
        self.assertEqual(len(e["posts"]), 2)

    def test_lawsuits_regulators_filings_and_scoops_never(self):
        self.event("policy_legal")
        self.assertEqual(self.rows(), [])
        clear_tables(self.cur, "mx_story_posts, mx_stories", cascade=True)
        self.event("leak_rumour")
        self.assertEqual(self.rows(), [])

    def test_a_followed_other_section_is_a_second_section_and_a_watch_on_it_none(self):
        news = self.site_source("https://acme.example/news/feed.xml")
        self.post(title="Older news", source=news, at=datetime.now(timezone.utc) - 40 * D)
        self.cur.execute("UPDATE posts SET url = 'https://acme.example/news/older', normalized_url = "
                         "'https://acme.example/news/older' WHERE source_id = %s", (news,))
        self.event()
        self.assertEqual([(r["kind"], r["source"]["id"]) for r in self.rows()], [("wrong_section", news)])
        self.site_source("https://acme.example/blog", settings={"page_watch": {"prefix": "/blog/"}}, name="Acme Blog")
        self.assertEqual(self.rows(), [])

    def test_a_switched_off_source_on_the_section_is_never_suggested(self):
        """Issue 0200: its channel is the owner's, switched off; the event is no row."""
        self.site_source("https://acme.example/blog", enabled=False, settings={"page_watch": {}}, name="Acme Blog")
        self.event()
        self.assertEqual(self.rows(), [])

    def test_a_switched_off_sources_posts_are_no_voice_of_an_event(self):
        """Issue 0200: a story of two voices, one of them switched off, is one voice here: no event, no row. The story
        itself is unchanged (its members stay)."""
        off = self.site_source("https://reporter-off.example/feed.xml", enabled=False, name="Reporter")
        story = self.event(sources=(self.source, off))
        self.assertEqual(self.rows(), [])
        self.cur.execute("SELECT count(*) FROM mx_story_posts WHERE story_id = %s AND valid_to IS NULL", (story,))
        self.assertEqual(self.cur.fetchone()[0], 2)
        self.cur.execute("UPDATE sources SET enabled = true WHERE id = %s", (off,))
        self.assertEqual([r["kind"] for r in self.rows()], ["missing"])

    def test_the_route_answers_and_a_hidden_row_goes(self):
        from insight_core.routers import discover_main_source as R
        self.addCleanup(R.use)
        R.use(M.MainSource(self.dsn()))
        self.event()
        status, body = call("GET", "/api/discover/main-source", query={"test": "false"})
        self.assertEqual(status, 200, body)
        mine = [r for r in body["rows"] if r["actor"]["id"] == self.acme]
        self.assertEqual([r["key"] for r in mine], ["main:acme.example/blog/"])
        self.assertIsNone(mine[0]["test"])
        # Not interested (POST /api/sources/suggested/hide keeps the key, lower case, in discover_hidden)
        self.cur.execute("INSERT INTO discover_hidden (key, reason) VALUES ('main:acme.example/blog/', 'not_interested') "
                         "ON CONFLICT DO NOTHING")
        self.addCleanup(self.cur.execute, "DELETE FROM discover_hidden WHERE key = 'main:acme.example/blog/'")
        _, body = call("GET", "/api/discover/main-source", query={"test": "false"})
        self.assertEqual([r for r in body["rows"] if r["actor"]["id"] == self.acme], [])

    def test_the_scan_never_reads_the_whole_entity_book(self):
        """v10.17 (0186): the scan asks the book for what its stories name (identity.lazy_book)."""
        from insight_core.markx import identity
        self.event()
        with mock.patch.object(identity, "load_book", side_effect=AssertionError("the whole book")):
            got = [r for r in self.rows() if r["actor"]["id"] == self.acme]
        self.assertEqual([r["key"] for r in got], ["main:acme.example/blog/"])

    def test_the_list_is_kept_until_what_it_is_made_of_changes(self):
        """v10.17 (0186): a read-v3 answer of a post in no announced story keeps the list (it was made again on every
        answer anywhere); one of a picked story's member, a new member, or a source changed makes it again."""
        from insight_core.markx import repo
        ms = M.MainSource(self.dsn())
        sid = self.event()
        scans = []
        real = M.scan

        def counted(*a, **k):
            scans.append(1)
            return real(*a, **k)

        with mock.patch.object(M, "scan", counted):
            first = ms.found()
            elsewhere = self.post(title="Unrelated", at=datetime.now(timezone.utc) - 3 * D)
            self.read(elsewhere, read3(event_type="research_result"))                  # in no story
            self.assertEqual((ms.found(), len(scans)), (first, 1))
            now = datetime.now(timezone.utc)
            p3 = self.post(title="Widget 5 hands-on", source=self.other, at=now - D / 2)
            repo.open_membership(self.cur, story_id=sid, post_id=p3, role="member", reason="test", run_id=self.run)
            ms.found()
            self.assertEqual(len(scans), 2)                                             # a member joined the story
            self.read(p3, read3(event_type="model_release"))
            ms.found()
            self.assertEqual(len(scans), 3)                                             # its reading
            self.site_source("https://example.org/feed", name="Another")
            ms.found()
            self.assertEqual(len(scans), 4)                                             # a source added

    def test_mark_x_tables_are_untouched(self):
        from insight_core.tests.test_markx_decide import checksums
        self.event()
        before = checksums(self.cur)
        M.scan(self.cur, datetime.now(timezone.utc))
        self.assertEqual(checksums(self.cur), before)

    def dsn(self):
        from insight_core.tests._db import db_url
        return db_url()


if __name__ == "__main__":
    unittest.main()
