"""Issue 0196 (Stealth v10.18): official channels and the item filter. The rules on plain values, the pass on a database
whose name ends in _test with a fake test read and the worker's answers through the API (invented names only)."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import official as O
from insight_core.markx import schemas, validate
from insight_core.markx.scout_reads import ReadResult
from insight_core.utils import item_filter as F
from insight_core.tests._db import clear_tables, db_url
from insight_core.tests.test_markx_api import _Api
from insight_core.tests.test_markx_folds import read3

import unittest

D = timedelta(days=1)
REL = "https://github.com/acme-labs/widget/releases/tag/"


def rel(n, tag):
    return {"id": f"i{n}", "title": tag, "url": REL + tag}


class ItemFilterRules(unittest.TestCase):
    BUILDS = {"kind": "builds", "hide": [{"field": "tag", "regex": r"^b\d+$", "why": "per-commit builds"}]}

    def items(self):
        return [rel(i, f"b{1000 + i}") for i in range(1, 10)] + [rel(10, "v1.0.0")]

    def test_a_shape_that_hides_builds_and_keeps_the_release_is_kept(self):
        self.assertIsNone(F.check(self.BUILDS, self.items(), keep=["i10"]))
        self.assertTrue(F.hides(self.BUILDS, "b1234", REL + "b1234"))
        self.assertFalse(F.hides(self.BUILDS, "v1.0.0", REL + "v1.0.0"))

    def test_a_literal_version_everything_or_nothing_hidden_is_refused(self):
        lit = {"kind": "mixed", "hide": [{"field": "tag", "regex": r"v1\.2", "why": ""}]}
        self.assertIn("one version", F.check(lit, self.items()))
        every = {"kind": "mixed", "hide": [{"field": "title", "regex": ".*", "why": ""}]}
        self.assertIn("plain release", F.check(every, self.items()))
        none = {"kind": "mixed", "hide": [{"field": "tag", "regex": r"-nightly$", "why": ""}]}
        self.assertIn("none of the items", F.check(none, self.items()))
        keeps = {"kind": "mixed", "hide": [{"field": "tag", "regex": r"^b\d+$", "why": ""}]}
        self.assertIn("keeps", F.check(keeps, self.items(), keep=["i3"]))
        self.assertIn("compile", F.check({"kind": "mixed", "hide": [{"field": "tag", "regex": "(", "why": ""}]}, self.items()))

    def test_alphas_hidden_when_stable_releases_exist(self):
        rule = {"kind": "mixed", "hide": [{"field": "tag", "regex": r"-alpha\.\d+$", "why": "alphas"}]}
        items = [rel(1, "v0.9.0-alpha.3"), rel(2, "v0.9.0-alpha.2"), rel(3, "v0.8.1")]
        self.assertIsNone(F.check(rule, items, keep=["i3"]))

    def test_the_answer_check_reads_the_questions_items_and_tags(self):
        inp = "ITEMS (newest first):\n[i1] 2026-11-01 · b123 tag=b123\n[i2] 2026-11-01 · Widget 1.0 tag=v1.0.0\n"
        ok = {"kind": "mixed", "hide": [{"field": "tag", "regex": r"^b\d+$", "why": "x"}], "keep": ["i2"]}
        self.assertIsNone(validate._item_filter(ok, inp))
        self.assertIn("plain release", validate._item_filter(dict(ok, hide=[{"field": "tag", "regex": "^v", "why": "x"}]), inp))
        self.assertIn("does not show", validate._item_filter(dict(ok, keep=["i9"]), inp))
        answer = {"verdict": "follow", "fits": True, "original": "high", "reasons": ["its own releases"],
                  "examples": ["i2"], "filter": ok}
        _, err = validate.check("source_judge", answer, inp, "source-judge-v2")
        self.assertIsNone(err)

    def test_the_official_lookups_schema_and_checks(self):
        a = {"actor": {"name": "Acme Labs", "site": "https://acme.example", "kind": "org"}, "thing_maker": "Acme Labs",
             "announcement": {"url": "https://acme.example/blog/widget-5", "why": "its post"},
             "channels": [{"url": "https://acme.example/blog/", "kind": "site_section", "why": "its blog"}],
             "official": True, "why_not": None, "queries": ["acme widget 5"]}
        self.assertEqual(validate.check("websearch", a, "", "websearch-official-v1"), (a, None))
        bad = dict(a, channels=a["channels"] * 2)
        self.assertIn("twice", validate.check("websearch", bad, "", "websearch-official-v1")[1])
        self.assertIsNotNone(validate.check("websearch", a, "", "websearch-v1")[1])   # the research guide's own schema


class Channels(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(O.channel("https://github.com/Acme-Labs/widget/releases/tag/b1").address,
                         "https://github.com/Acme-Labs/widget/releases.atom")
        self.assertEqual(O.channel("https://x.com/acmelabs/status/1987654321098765432").key, "x.com/acmelabs")
        self.assertEqual(O.channel("https://acme.example/blog/widget-5").key, "acme.example/blog/")
        self.assertEqual(O.channel("https://forum.acme.example/c/announcements/5").key,
                         "forum.acme.example/c/announcements/")
        for junk in ("https://acme.example/", "https://help.acme.example/articles/1/x", "https://docs.acme.example/a/b",
                     "https://cdn.acme.example/x/y.png", "https://acme.example/pricing", "https://github.com/acme-labs",
                     "https://forum.acme.example/t/widget-is-here/77", "https://huggingface.co/acme/widget"):
            self.assertIsNone(O.channel(junk), junk)

    def test_ownership_by_the_actors_names_and_site_never_an_employees_account(self):
        x = O.channel("https://x.com/acmelabs")
        self.assertTrue(O.owned(x, names=["Acme Labs"]))
        self.assertIsNone(O.owned(O.channel("https://x.com/jdoe_dev"), names=["Acme Labs"]))
        self.assertTrue(O.owned(O.channel("https://news.acme.example/blog/a"), sites=["https://acme.example"]))
        # a code address of the thing is no proof of its owner (a third party's plugin, a fork): the owner's name is
        self.assertIsNone(O.owned(O.channel("https://github.com/someone/widget"), names=["Acme Labs"],
                                  repos=["github.com/someone/widget"]))
        self.assertTrue(O.owned(O.channel("https://github.com/acme-labs/widget"), names=["Acme Labs"]))
        self.assertIsNone(O.owned(O.channel("https://acme.example/c/"), names=["Acme"]) if O.channel(
            "https://acme.example/c/") else None)


class World(_Api):
    """Mark X stories, readings and mentions of an invented lab, Acme, and its product Widget."""

    def setUp(self):
        super().setUp()
        from insight_core.markx import repo
        clear_tables(self.cur, "mx_official_channels, mx_official_events, mx_official_lookups, mx_official_runs")
        self.run = repo.start_run(self.cur, code_version="test", config={})
        self.made = []
        self.addCleanup(lambda: self.cur.execute("DELETE FROM sources WHERE id = ANY(%s::uuid[])", (self.made,)))
        from insight_core.tests._db import insert_scratch_source
        self.third = insert_scratch_source(self.cur, platform="rss", enabled=True,
                                           settings_json=json.dumps({"display_name": "Third Site"}))
        self.made.append(self.third)
        self.acme = self.entity("org", "Acme")
        self.widget = self.entity("product", "Widget")
        for k, v in (("INSIGHT_OFFICIAL", "shadow"), ("INSIGHT_OFFICIAL_ADDS_PER_DAY", "5")):
            old = os.environ.get(k)
            os.environ[k] = v
            self.addCleanup(lambda k=k, old=old: os.environ.pop(k) if old is None else os.environ.__setitem__(k, old))

    def entity(self, type_, name):
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, status)
                            VALUES (%s, %s, %s, 'thing', 'provisional') RETURNING id::text""", (type_, name, name.lower()))
        eid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO mx_entity_aliases (key, entity_id, source) VALUES (%s, %s, 'rule')",
                         (name.lower(), eid))
        return eid

    def site_source(self, handle, *, enabled=True, name="Acme News"):
        self.cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest, settings) "
                         "VALUES ('rss', %s, %s, false, %s::jsonb) RETURNING id::text",
                         (handle, enabled, json.dumps({"display_name": name})))
        sid = self.cur.fetchone()[0]
        self.made.append(sid)
        return sid

    def mention(self, post, eid, name, type_):
        from insight_core.markx import repo, tasks
        with self.conn.transaction():
            task_id, _ = tasks.entities_task(self.cur, post)
            cid = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                                answer={"entities": []})
            repo.add_mentions(self.cur, post_id=post, guide="ent-v3", call_id=cid, mentions=[
                {"span": name, "name": name, "name_key": name.lower(), "type": type_, "role": "subject",
                 "maker": None, "family": None, "version": None, "variant": None, "size": None, "build": None}])
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (eid, post))

    def read(self, post, answer):
        from insight_core.markx import folds as Fo
        with self.conn.transaction():
            task_id, _ = Fo.read3_task(self.cur, post)
        _, got = self.answer((task_id, answer))
        self.assertEqual(got["valid"], 1, got)

    def event(self, event_type="model_release", *, links=(), who=None, voices=2, title="Acme ships Widget 5"):
        from insight_core.markx import repo
        now = datetime.now(timezone.utc)
        srcs = [self.source, self.other, self.third][:voices]
        posts = [self.post(title=f"{title} ({i})", source=s, at=now - (2 - i) * D, links=[(u, "here") for u in links])
                 for i, s in enumerate(srcs)]
        sid = repo.add_story(self.cur, first_at=now - 2 * D, run_id=self.run)
        for p in posts:
            repo.open_membership(self.cur, story_id=sid, post_id=p, role="member", reason="test", run_id=self.run)
            self.read(p, read3(event_type=event_type))
            if who == "widget":
                self.mention(p, self.widget, "Widget", "product")
            elif who != "nobody":
                self.mention(p, self.acme, "Acme", "org")
        return str(sid)

    def channels(self, state=None):
        self.cur.execute("SELECT key, state, why FROM mx_official_channels WHERE superseded_at IS NULL"
                         + (" AND state = %s" if state else "") + " ORDER BY key", (state,) if state else ())
        return self.cur.fetchall()

    def plan(self):
        from collections import Counter
        counts = Counter()
        with self.conn.transaction():
            O.plan(self.cur, datetime.now(timezone.utc), counts)
        return counts

    def judged(self, items, answer, *, via="feed", add=None):
        """advance with a fake test read; the judgement's question answered through the API; advance again."""
        from collections import Counter
        reader = FakeReader(items, via)
        counts = Counter()
        O.advance(db_url(), datetime.now(timezone.utc), counts, reader=reader, add=add)
        self.cur.execute("SELECT task_id::text FROM mx_source_judgements WHERE status = 'asked'")
        for (tid,) in self.cur.fetchall():
            _, got = self.answer((tid, answer))
            self.assertEqual(got["valid"], 1, got)
        O.advance(db_url(), datetime.now(timezone.utc), counts, reader=reader, add=add)
        return counts


class FakeReader:
    """The add path's test read, faked: these items at the address asked."""

    def __init__(self, items, via="feed"):
        self.items, self.via, self.asked = items, via, []

    async def read(self, address, *, linked=(), limit=10):
        self.asked.append(address)
        resolved = {"platform": "rss", "handle_or_url": address if self.via != "page" else address,
                    "settings": {"page_watch": {"prefix": "/blog/"}} if self.via == "page" else {}, "via": self.via,
                    "title": "Acme blog"}
        return ReadResult(resolved=resolved, items=list(self.items)[:limit], requests=1)


def items(urls, *, titles=None):
    now = datetime.now(timezone.utc)
    return [{"url": u, "title": (titles or {}).get(u, f"Post {n}"), "text": "words " * 80, "chars": 480,
             "published_at": now - n * D, "lang": "en"} for n, u in enumerate(urls)]


FOLLOW = {"verdict": "follow", "fits": True, "original": "high", "reasons": ["its own announcements"],
          "examples": ["i1"], "filter": None}


class ThePass(World):
    PAGE = "https://acme.example/blog/widget-5-launch"

    def test_an_events_own_page_becomes_a_proven_wanted_channel_shadow_records_would_add(self):
        story = self.event(links=[self.PAGE], voices=3)
        counts = self.plan()
        self.assertEqual(counts["candidates"], 1, counts)
        self.assertEqual(self.channels(), [("acme.example/blog/", "candidate", "found: own page")])
        self.judged(items([self.PAGE, "https://acme.example/blog/a", "https://acme.example/blog/b"]), FOLLOW)
        self.assertEqual([r[:2] for r in self.channels()], [("acme.example/blog/", "would_add")])
        self.cur.execute("SELECT events, evidence FROM mx_official_channels WHERE superseded_at IS NULL")
        events, evidence = self.cur.fetchone()
        self.assertEqual(events, [story])
        self.assertEqual((evidence["from"], evidence["proof"]["holds"], evidence["judge"]["fits"]), ("own_page", 1, True))
        self.cur.execute("SELECT count(*) FROM mx_official_channels")
        self.assertEqual(self.cur.fetchone()[0], 2)          # keep everything: the candidate row stays, superseded
        self.cur.execute("SELECT count(*) FROM sources WHERE settings->>'added_by' = 'official'")
        self.assertEqual(self.cur.fetchone()[0], 0)          # Shadow adds nothing

    def test_on_adds_under_the_days_cap_and_undo_is_final(self):
        os.environ["INSIGHT_OFFICIAL"] = "on"
        os.environ["INSIGHT_OFFICIAL_ADDS_PER_DAY"] = "1"
        self.event(links=[self.PAGE, "https://x.com/acme/status/1987654321098765432"], voices=3)
        self.plan()
        added = []

        def add(cur, row, j):
            sid = self.site_source(j["resolved"]["handle_or_url"], name=row["key"])
            added.append(sid)
            return {"source_id": sid, "filter_id": None}
        self.judged(items([self.PAGE, "https://acme.example/blog/a", "https://acme.example/blog/b"]), FOLLOW, add=add)
        states = sorted(r[1] for r in self.channels())
        self.assertEqual(states, ["added", "would_add"])     # the second waits: one a day (one section a site:
        # a second section of the same site is refused, so the second channel is the actor's account)
        self.assertEqual(len(added), 1)
        self.assertIn("cap", [r[2] for r in self.channels() if r[1] == "would_add"][0])
        self.cur.execute("SELECT id::text FROM mx_official_channels WHERE superseded_at IS NULL AND state = 'added'")
        cid = self.cur.fetchone()[0]
        with self.conn.transaction():
            O.undo(self.cur, cid)
        self.cur.execute("SELECT enabled FROM sources WHERE id = %s", (added[0],))
        self.assertFalse(self.cur.fetchone()[0])
        self.assertIn("undone", [r[1] for r in self.channels()])
        self.event(links=[self.PAGE], voices=3, title="Acme ships Widget 6")
        self.plan()
        self.assertIn("undone", [r[1] for r in self.channels()])   # never a candidate again

    def test_a_followed_section_is_covered_never_a_new_source(self):
        self.site_source("https://acme.example/blog/feed.xml")
        self.cur.execute("UPDATE sources SET handle_or_url = 'https://acme.example/blog/feed.xml' WHERE id = %s",
                         (self.made[-1],))
        self.event(links=[self.PAGE], voices=3)
        self.plan()
        self.assertEqual([r[1] for r in self.channels()], ["covered"])

    def test_lawsuits_are_not_looked_at(self):
        self.event("policy_legal", links=[self.PAGE])
        counts = self.plan()
        self.assertEqual((counts["events_read"], self.channels()), (0, []))

    def test_no_dated_stream_or_a_skip_is_refused_with_why(self):
        self.event(links=[self.PAGE], voices=3)
        self.plan()
        self.judged(items([self.PAGE])[:1], FOLLOW)
        self.assertEqual([r[1] for r in self.channels()], ["refused"])
        self.assertIn("no dated stream", self.channels()[0][2])

    def test_one_voice_one_event_is_not_yet_wanted(self):
        self.event(links=[self.PAGE], voices=1)
        self.plan()
        self.judged(items([self.PAGE, "https://acme.example/blog/a", "https://acme.example/blog/b"]), FOLLOW)
        self.assertEqual([r[1] for r in self.channels()], ["refused"])
        self.assertIn("not yet", self.channels()[0][2])

    def test_off_topic_for_the_reader_is_refused(self):
        self.event(links=[self.PAGE], voices=3)
        self.plan()
        self.judged(items([self.PAGE, "https://acme.example/blog/a", "https://acme.example/blog/b"]),
                    dict(FOLLOW, verdict="skip", fits=False, reasons=["cars, not your topics"]))
        self.assertIn("not your topics", self.channels()[0][2])


class TheWebSearch(World):
    def answer_lookup(self, answer):
        self.cur.execute("SELECT task_id::text FROM mx_official_lookups")
        (tid,), = self.cur.fetchall()
        _, got = self.answer((tid, answer))
        self.assertEqual(got["valid"], 1, got)

    def test_no_own_link_asks_once_then_its_channels_the_maker_through_identity(self):
        self.event(who="widget", voices=3, title="Widget 5 is here")
        counts = self.plan()
        self.assertEqual(counts["lookups_asked"], 1)
        self.cur.execute("SELECT kind, guide, subject_kind FROM mx_tasks WHERE id = (SELECT task_id FROM mx_official_lookups)")
        self.assertEqual(self.cur.fetchone(), ("websearch", "websearch-official-v1", "official_event"))
        self.plan()
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE guide = 'websearch-official-v1'")
        self.assertEqual(self.cur.fetchone()[0], 1)          # asked once
        self.answer_lookup({
            "actor": {"name": "Acme Labs", "site": "https://acmelabs.example", "kind": "org"},
            "thing_maker": "Acme Labs", "announcement": None, "official": True, "why_not": None,
            "channels": [{"url": "https://github.com/acme-labs/widget/releases", "kind": "releases", "why": "its repo"},
                         {"url": "https://x.com/jdoe_dev", "kind": "x", "why": "its lead developer"},
                         {"url": "https://acmelabs.example/", "kind": "site", "why": "its site"}],
            "queries": ["widget 5 release"]})
        self.plan()
        self.assertEqual([r[:2] for r in self.channels()], [("github.com/acme-labs/widget", "candidate")])
        self.cur.execute("SELECT detail FROM mx_official_events")
        refused = self.cur.fetchone()[0]["refused"]
        self.assertEqual(len(refused), 2)                    # the employee's account and the home page
        self.cur.execute("SELECT maker_name, by FROM mx_entity_facts WHERE entity_id = %s AND superseded_at IS NULL",
                         (self.widget,))
        self.assertEqual(self.cur.fetchone(), ("Acme Labs", "web"))
        self.cur.execute("SELECT maker FROM mx_entities WHERE id = %s", (self.widget,))
        self.assertIsNone(self.cur.fetchone()[0])            # never mx_entities.maker

    def test_not_official_says_so(self):
        self.event("business_event", who="nobody", voices=2, title="Acme cuts jobs")
        self.cur.execute("SELECT 1")
        self.plan()
        self.answer_lookup({"actor": None, "thing_maker": None, "announcement": None, "channels": [],
                            "official": False, "why_not": "reporters' scoop", "queries": ["acme jobs"]})
        self.plan()
        self.cur.execute("SELECT outcome FROM mx_official_events")
        self.assertEqual(self.cur.fetchone()[0], "not_official")


class ReleasesAndTheFilter(World):
    def test_a_releases_feeds_builds_are_kept_but_hidden(self):
        from insight_core.db.repo_posts import PostDraft, PostsRepository
        os.environ["INSIGHT_OFFICIAL"] = "on"
        self.cur.execute("""INSERT INTO mx_entity_addresses (entity_id, url, kind, rule, first_at)
                            VALUES (%s, 'https://github.com/acme/widget', 'code', 'repo', now())""", (self.widget,))
        self.cur.execute("UPDATE mx_entities SET maker = 'Acme' WHERE id = %s", (self.widget,))
        self.event(links=["https://github.com/acme/widget"], who="widget", voices=3)
        self.plan()
        self.assertEqual([r[:2] for r in self.channels()], [("github.com/acme/widget", "candidate")])
        tags = [f"b{900 + i}" for i in range(9)] + ["v1.0.0"]
        rule = {"kind": "builds", "hide": [{"field": "tag", "regex": r"^b\d+$", "why": "per-commit builds"}],
                "keep": ["i10"]}
        made = {}

        def add(cur, row, j):
            sid = self.site_source(j["resolved"]["handle_or_url"], name="Widget releases")
            fid = F.put(cur, sid, j["answer"]["filter"], by="worker")
            made["sid"] = sid
            return {"source_id": sid, "filter_id": fid}
        rel_items = items([f"https://github.com/acme/widget/releases/tag/{t}" for t in tags],
                          titles={f"https://github.com/acme/widget/releases/tag/{t}": t for t in tags})
        self.judged(rel_items, dict(FOLLOW, examples=["i10"], filter=rule), add=add)
        self.assertEqual([r[1] for r in self.channels()], ["added"])
        drafts = [PostDraft(made["sid"], {"url": f"https://github.com/acme/widget/releases/tag/{t}", "title": t,
                                          "content": "notes", "date": datetime.now(timezone.utc)}) for t in tags]
        with self.conn.cursor() as _:
            pass
        import psycopg
        with psycopg.connect(db_url()) as conn:
            PostsRepository(db_url()).save_batch(conn, drafts)
        self.cur.execute("SELECT title, filtered_by IS NOT NULL FROM posts WHERE source_id = %s ORDER BY title",
                         (made["sid"],))
        got = dict(self.cur.fetchall())
        self.assertFalse(got.pop("v1.0.0"))
        self.assertTrue(all(got.values()) and len(got) == 9)
        from insight_core.db.repo_reader import NOT_STORY_ONLY
        self.cur.execute(f"SELECT p.title FROM posts p WHERE p.source_id = %s AND {NOT_STORY_ONLY}", (made["sid"],))
        self.assertEqual([r[0] for r in self.cur.fetchall()], ["v1.0.0"])
        with self.conn.transaction():
            F.put(self.cur, made["sid"], None, by="owner")    # the owner clears it: every post shown again
        self.assertEqual(F.hidden_count(self.cur, [made["sid"]]), {})


class Cited(World):
    def test_pages_two_voices_link_not_front_pages_media_pricing_or_tweets(self):
        now = datetime.now(timezone.utc)
        good, one = "https://report.example/2100/a-finding", "https://single.example/only-one/x"
        junk = ["https://report.example/", "https://www.youtube.com/watch?v=abc", "https://report.example/pricing",
                "https://x.com/someone/status/1987654321098765432", "https://github.com/acme/widget"]
        for s in (self.source, self.other):
            self.post(title="links", source=s, at=now - D, links=[(u, "x") for u in [good, *junk]])
        self.post(title="one", source=self.source, at=now - D, links=[(one, "x")])
        got = [w["url"] for w in O.pages_wanted(self.cur, now)]
        self.assertEqual(got, [good])


class RankedByFit(unittest.TestCase):
    def test_the_workers_fit_comes_before_link_volume_within_a_section(self):
        from insight_core.utils.discover_rules import order
        rows = [{"key": "big-news.example", "score": 9.0, "voices": 12, "fit": "not_fit"},
                {"key": "x.com/practitioner", "score": 2.8, "voices": 2, "fit": "follow"},
                {"key": "middle.example", "score": 5.0, "voices": 4}]
        self.assertEqual([r["key"] for r in order(rows)], ["x.com/practitioner", "middle.example", "big-news.example"])

    def test_the_worker_checks_first_what_the_sources_you_read_most_link(self):
        sgs = [{"key": "big-news.example", "voice_names": ["Wire A", "Wire B", "Wire C"]},
               {"key": "x.com/practitioner", "voice_names": ["Read Most"]},
               {"key": "judged.example", "voice_names": ["Read Most"]}]
        self.assertEqual(O.to_check(sgs, ["Read Most"], {"judged.example"}, 2), ["x.com/practitioner", "big-news.example"])


class TheJob(unittest.TestCase):
    def test_official_is_due_after_everything_else_when_on(self):
        from insight_core.markx import jobs
        now = datetime(2100, 1, 1, tzinfo=timezone.utc)
        states = {j: {"job": j, "wanted_at": None, "started_at": now, "stage": None, "stage_at": None,
                      "finished_at": now, "last": None, "failures": 0} for j in jobs.JOBS}
        later = now + timedelta(seconds=jobs.OFFICIAL_EVERY + 1)
        states["decide"]["started_at"] = later
        self.assertEqual(jobs.due(states, later, official_every=jobs.OFFICIAL_EVERY), "official")
        self.assertIsNone(jobs.due(states, later, official_every=None))


if __name__ == "__main__":
    unittest.main()
