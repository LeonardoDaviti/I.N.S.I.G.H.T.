"""0173 (Stealth v10.15): "Is this worth it?", a candidate source judged by the worker on the owner's tap. The kind, its
guide, schema and validation (examples are items the question shows); the measured signals (links, stories, the items
in your stories, rate, reads by code with stubbed pages, repeats, the rewriter marks, followed before); the reader's
interests; the question; the cache (30 days, asking again re-asks only after new items); nothing written but the
judgement and its question (no source, no post); the routes. Synthetic names only; the DB tests run on a database whose
name ends in _test."""
from __future__ import annotations

import asyncio
import json
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import repo, schemas, scout, scout_reads, source_judge, validate
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_markx_api import _Api, call

NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = timedelta(days=1)
SITE = "https://judged.example"


def item(k=0, *, chars=2000, lang="en", at=None, url=None, title=None):
    return {"url": url or f"{SITE}/post-{k}", "title": title or f"A judged post number {k} about widgets",
            "text": "Widgets are made of parts. " * (chars // 27 + 1), "chars": chars,
            "published_at": at or NOW - k * DAY, "lang": lang, "transcript": None}


def feed_result(address=SITE, n=10, **kw):
    return scout_reads.ReadResult(
        resolved={"platform": "rss", "handle_or_url": address.rstrip("/") + "/feed.xml", "settings": {}, "via": "feed",
                  "title": "Judged Example"},
        items=[item(k, **kw) for k in range(n)], requests=3)


class StubReader:
    def __init__(self, result=None):
        self.result = result
        self.asked = []
        self.http = None

    async def read(self, address, *, linked=(), limit=20):
        self.asked.append((address, limit))
        return self.result or scout_reads.ReadResult(reason="none found", requests=2)


def good(examples=("i1", "i2")):
    return {"verdict": "follow", "reasons": ["Original reporting on widgets, linked by 2 of your sources."],
            "examples": list(examples), "fits": True, "original": "high"}


# ---- no database ------------------------------------------------------------------------------------------------

class Pure(unittest.TestCase):
    def test_the_kind_its_guide_and_schema(self):
        k = schemas.KINDS["source_judge"]
        self.assertEqual((k.guide, k.subject), ("source-judge-v2", "source_candidate"))
        body = schemas.guide_body("source-judge-v2")
        for word in ("verdict", "reasons", "examples", "fits", "original", "Reads:"):
            self.assertIn(word, body)
        q = "MEASURED:\n- x\nITEMS (newest first):\n[i1] 2026-11-01 · A\n[i2] 2026-11-02 · B"
        self.assertIsNone(validate.check("source_judge", good(), q)[1])
        for bad in (dict(good(), verdict="yes"), dict(good(), original="huge"), dict(good(), fits="true"),
                    {k: v for k, v in good().items() if k != "fits"}, dict(good(), reasons=[]),
                    dict(good(), examples=[]), dict(good(), reasons=["r"] * 5), dict(good(), examples=["post-1"])):
            with self.subTest(bad=bad):
                self.assertIsNotNone(validate.check("source_judge", bad, q)[1])

    def test_examples_are_items_the_question_shows_and_reasons_one_line_each(self):
        q = "ITEMS (newest first):\n[i1] 2026-11-01 · A\n[i2] 2026-11-02 · B"
        self.assertIn("does not show", validate.check("source_judge", good(("i1", "i3")), q)[1])
        self.assertIn("twice", validate.check("source_judge", good(("i1", "i1")), q)[1])
        self.assertIn("one line", validate.check("source_judge", dict(good(), reasons=["a\nb"]), q)[1])
        self.assertIn("twice", validate.check("source_judge", dict(good(), reasons=["Same.", "same."]), q)[1])
        # a free-text answer alone is never valid
        self.assertIsNotNone(validate.check("source_judge", {"text": "Follow it, it's great"}, q)[1])

    def test_the_cache_key_of_an_address(self):
        for a in ("https://www.Judged.example/blog/", "http://judged.example/blog", "judged.example/blog"):
            self.assertEqual(source_judge.cache_key(a), "judged.example/blog")
        self.assertNotEqual(source_judge.cache_key("https://judged.example/"), source_judge.cache_key("https://judged.example/blog"))

    def test_the_rewriter_marks(self):
        none_linked = {"sources": 0}
        never = {"stories": 0}
        no_items = {"started": 0}
        got = source_judge.rewriter(300.0, {"en": 4, "de": 3, "fr": 3}, none_linked, never, no_items)
        self.assertEqual(got, {"marks": ["high rate", "many languages", "never first", "rarely cited"], "pattern": True})
        got = source_judge.rewriter(20.0, {"en": 10}, {"sources": 4}, {"stories": 2}, no_items)
        self.assertEqual(got, {"marks": [], "pattern": False})
        # a fast source your sources cite and that starts stories is no rewriter
        got = source_judge.rewriter(300.0, {"en": 10}, {"sources": 6}, {"stories": 3}, no_items)
        self.assertFalse(got["pattern"])
        # the rate is needed: slow, uncited and never first is not the pattern
        got = source_judge.rewriter(2.0, {"en": 5, "de": 3, "fr": 2}, none_linked, never, no_items)
        self.assertFalse(got["pattern"])

    def test_scratch_items_newest_first_with_ids(self):
        items = source_judge.scratch_items([item(3), item(0), item(7), dict(item(9), published_at=None)] + [item(k) for k in range(10, 20)])
        self.assertEqual(len(items), source_judge.ITEMS)
        self.assertEqual([i["id"] for i in items[:3]], ["i1", "i2", "i3"])
        self.assertEqual(items[0]["url"], f"{SITE}/post-0")
        self.assertTrue(all(isinstance(i["published_at"], (str, type(None))) for i in items))
        json.dumps(items)

    def test_the_question_shows_the_measured_lines_the_reader_and_the_items(self):
        s = {"key": "judged.example", "site": "judged.example", "platform": "site",
             "linked": {"sources": 2, "posts": 5, "recent": 3, "names": ["Example A", "Example B"]},
             "stories": {"stories": 1, "recent": 1, "titles": ["Widgets 4.1 out"]},
             "items_in": {"linked": 2, "started": 1, "ids": ["i1", "i2"]},
             "rate": {"per_week": 3.5, "newest_days": 1, "dated": 10, "items": 10, "cadence": "4 a week"},
             "health": {"reads_well": True, "reason": "", "labels": []}, "languages": {"en": 10},
             "reads": {"mode": "full", "evidence": "full text in the feed (median 2,000 characters)", "median": 2000},
             "repeats": {"items": 1, "from": ["Example A"], "ids": ["i3"], "same_site": []},
             "rewriter": {"marks": [], "pattern": False}, "followed_before": None}
        items = source_judge.scratch_items([item(k) for k in range(3)])
        q = source_judge.question(SITE, feed_result().resolved, items, s, ["Track “Widgets”: widget news", "Follows 3 sources (0 turned off)."])
        for part in ("CANDIDATE: judged.example", "Linked by your sources: 2 sources (5 posts, 3 in the last 90 days)",
                     "Stories of yours that started at its pages: 1", "2 of 10 linked by your sources, 1 started a story",
                     "Reads: full: full text in the feed", "Repeats: 1 of 10 items you already have (from Example A)",
                     "Rewriter marks: none (the pattern: no)", "THE READER:", "Track “Widgets”", "[i1] ", "[i3] "):
            self.assertIn(part, q)
        self.assertIsNone(validate.check("source_judge", good(("i1", "i3")), q)[1])


class Reads(unittest.TestCase):
    """How its items read is measured by code (0149 E8), never asked: the feed's text, else its article pages."""

    def read(self, items, pages=None, *, via="feed", platform="site"):
        http = FakeHttp(pages or {}) if pages is not None else None
        resolved = {"platform": "rss", "handle_or_url": f"{SITE}/feed.xml", "via": via}
        return asyncio.run(source_judge.reads_of(http, items, resolved, platform)), http

    def test_full_text_in_the_feed_asks_nothing(self):
        got, http = self.read([item(k, chars=3000) for k in range(5)], {})
        self.assertEqual(got["mode"], "full")
        self.assertEqual(http.requests, [])

    def test_a_platform_post_is_complete_as_posted(self):
        got, _ = self.read([item(k, chars=200) for k in range(5)], {}, via="kind", platform="x")
        self.assertEqual(got["mode"], "short")

    def test_a_teaser_whose_page_says_it_is_paid_is_paywalled(self):
        paid = ('<html><head><script type="application/ld+json">{"isAccessibleForFree": false}</script></head>'
                '<body><article><p>Widgets are made of parts.</p></article></body></html>')
        items = [item(k, chars=200) for k in range(5)]
        got, http = self.read(items, {i["url"]: (paid, {}) for i in items})
        self.assertEqual(got["mode"], "paywalled")
        self.assertLessEqual(len(http.requests), source_judge.PAGE_CHECKS)

    def test_a_teaser_whose_page_holds_nothing_longer_is_a_teaser(self):
        short = "<html><body><article><p>Widgets are made of parts.</p></article></body></html>"
        items = [item(k, chars=200) for k in range(5)]
        got, http = self.read(items, {i["url"]: (short, {}) for i in items})
        self.assertEqual((got["mode"], got["checked"]), ("teaser", source_judge.PAGE_CHECKS))

    def test_a_teaser_whose_page_holds_the_article_reads_in_full(self):
        items = [item(k, chars=200) for k in range(3)]
        lede = items[0]["text"][:200]
        body = "".join(f"<p>{lede} Paragraph {n} says more about the widget and how its parts fit together.</p>"
                       for n in range(40))
        page = f"<html><head><title>{items[0]['title']}</title></head><body><article><h1>{items[0]['title']}</h1>{body}</article></body></html>"
        got, _ = self.read([dict(i, text=lede) for i in items], {i["url"]: (page, {}) for i in items})
        self.assertEqual(got["mode"], "full_page")

    def test_no_items(self):
        self.assertEqual(self.read([], {})[0]["mode"], "none")


# ---- on the test database -------------------------------------------------------------------------------------

@requires_test_db
class _Judge(_Api):
    def setUp(self):
        super().setUp()
        self.cur.execute("UPDATE sources SET enabled = true WHERE id = ANY(%s::uuid[])", ([self.source, self.other],))
        patcher = mock.patch.object(scout, "_platforms", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def counts(self):
        self.cur.execute("SELECT (SELECT count(*) FROM sources), (SELECT count(*) FROM posts), "
                         "(SELECT count(*) FROM source_folders), (SELECT count(*) FROM post_links)")
        return self.cur.fetchone()

    def judge(self, address=SITE, reader=None, *, again=False, now=None):
        with self.conn.transaction():
            got = source_judge.ask(self.cur, address, again=again, now=now)
        if got["needs_read"]:
            asyncio.run(source_judge.read_and_ask(db_url(), got["id"], reader=reader or StubReader(feed_result()),
                                                  now=(lambda: now) if now else None))
        return source_judge.get(self.cur, got["id"])

    def task_of(self, row):
        return repo.get_task(self.cur, row["task_id"])


class Asking(_Judge):
    def test_a_tap_reads_measures_and_asks_one_question_and_writes_no_source(self):
        before = self.counts()
        reader = StubReader(feed_result())
        row = self.judge(reader=reader)
        self.assertEqual(reader.asked, [(SITE, source_judge.ITEMS)])
        self.assertEqual(row["status"], "asked")
        self.assertEqual(len(row["items"]), 10)
        self.assertEqual(row["resolved"]["via"], "feed")
        t = self.task_of(row)
        self.assertEqual((t["kind"], t["guide"], t["subject_kind"], str(t["a"])),
                         ("source_judge", "source-judge-v2", "source_candidate", row["id"]))
        self.assertLess(t["priority"], 0)
        self.assertIn("[i10] ", t["input"])
        self.assertIn("MEASURED:", t["input"])
        self.assertEqual(self.counts(), before)          # no source, no post, no folder, no link written

    def test_the_measured_signals_from_your_data(self):
        # two of your sources link it, one of its items too; a story started at its page; you already have one item
        p1 = self.post(source=self.source, links=[(f"{SITE}/post-1", None)])
        self.post(source=self.other, links=[(f"{SITE}/elsewhere", None)])
        self.cur.execute("UPDATE post_links SET target_site = 'judged.example' WHERE target_url LIKE %s", (SITE + "%",))
        self.cur.execute("INSERT INTO stories (id, first_at, voices, origin_url, origin_title) VALUES (%s, now(), 3, %s, %s)",
                         (p1, f"{SITE}/post-1", "Widgets 4.1 out"))
        self.addCleanup(self.cur.execute, "DELETE FROM stories WHERE id = %s", (p1,))
        self.post(source=self.other, title="A judged post number 2 about widgets")
        row = self.judge()
        s = row["signals"]
        self.assertEqual((s["linked"]["sources"], s["linked"]["posts"]), (2, 2))
        self.assertEqual(sorted(s["linked"]["names"]), ["Example Channel", "Example Site"])
        self.assertEqual((s["stories"]["stories"], s["stories"]["titles"]), (1, ["Widgets 4.1 out"]))
        self.assertEqual((s["items_in"]["linked"], s["items_in"]["started"]), (1, 1))
        self.assertEqual((s["repeats"]["items"], s["repeats"]["from"]), (1, ["Example Site"]))
        self.assertEqual(s["reads"]["mode"], "full")
        self.assertNotIn("never first", s["rewriter"]["marks"])
        self.assertEqual(s["rate"]["per_week"], 7.0)
        q = self.task_of(row)["input"]
        self.assertIn("Linked by your sources: 2 sources", q)
        self.assertIn("Repeats: 1 of 10 items you already have (from Example Site)", q)

    def test_a_source_you_turned_off_is_followed_before(self):
        self.cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, settings) VALUES ('rss', %s, false, %s) "
                         "RETURNING id", (f"{SITE}/feed.xml", json.dumps({"display_name": "Judged Once"})))
        sid = self.cur.fetchone()[0]
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (sid,))
        self.post(source=sid)
        row = self.judge()
        fb = row["signals"]["followed_before"]
        self.assertEqual((fb["name"], fb["enabled"], fb["posts"]), ("Judged Once", False, 1))
        self.assertIn("Followed before as Judged Once (turned off): 1 posts", self.task_of(row)["input"])

    def test_the_reader_in_the_question(self):
        self.cur.execute("INSERT INTO folders (name, kind) VALUES (%s, 'track') RETURNING id", (f"Widgets {uuid.uuid4().hex[:6]}",))
        folder = self.cur.fetchone()[0]
        self.addCleanup(self.cur.execute, "DELETE FROM folders WHERE id = %s", (folder,))
        self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (folder, self.source))
        from insight_core.markx import tracks
        with self.conn.transaction():
            tracks.set_topic(self.cur, folder, description="Widget releases and how they are built")
        p = self.post(source=self.source)
        self.cur.execute("INSERT INTO post_interactions (post_id, interaction_type) VALUES (%s, 'opened')", (p,))
        lines = source_judge.interests(self.cur)
        self.assertTrue(lines[0].startswith("Track “Widgets"))
        self.assertIn("Reads most (posts opened in 90 days): Example Channel (1)", lines)
        self.assertTrue(any(l.startswith("Folders: Widgets") for l in lines))
        self.assertIn("Track “Widgets", self.task_of(self.judge())["input"])

    def test_the_answer_is_shown_with_its_reasons_and_example_items(self):
        row = self.judge()
        status, body = self.answer((row["task_id"], good(("i1", "i3"))))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        got = source_judge.page(self.cur, SITE)
        self.assertEqual((got["status"], got["verdict"], got["fits"], got["original"]), ("answered", "follow", True, "high"))
        self.assertEqual([e["id"] for e in got["examples"]], ["i1", "i3"])
        self.assertEqual(got["examples"][0]["url"], f"{SITE}/post-0")
        self.assertTrue(got["examples"][0]["title"])
        self.assertTrue(any(m.startswith("Reads: full") for m in got["measured"]))
        self.assertEqual(got["follow_address"], f"{SITE}/feed.xml")

    def test_an_answer_naming_an_item_not_shown_is_refused(self):
        row = self.judge()
        status, body = self.answer((row["task_id"], good(("i1", "i11"))))
        self.assertEqual((status, body["valid"]), (200, 0), body)
        self.assertEqual(source_judge.get(self.cur, row["id"])["status"], "asked")

    def test_a_question_the_worker_gave_up_on_says_so(self):
        row = self.judge()
        self.cur.execute("UPDATE mx_tasks SET status = 'failed', last_error = 'reasons: too long' WHERE id = %s",
                         (row["task_id"],))
        got = source_judge.page(self.cur, SITE)
        self.assertEqual(got["status"], "failed")
        self.assertIn("could not answer", got["reason"])
        with self.conn.transaction():
            self.assertTrue(source_judge.ask(self.cur, SITE)["needs_read"])   # asked again on the next tap

    def test_an_unreadable_candidate_says_why_and_asks_nothing(self):
        row = self.judge(reader=StubReader())
        self.assertEqual((row["status"], row["reason"], row["task_id"]), ("unreadable", "none found", None))
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'source_judge'")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_reads_off_on_a_machine_that_must_not_fetch(self):
        reader = StubReader(feed_result())
        with mock.patch.dict(os.environ, {"INSIGHT_DISCOVER_READS": "0"}):
            row = self.judge(reader=reader)
        self.assertEqual(reader.asked, [])
        self.assertEqual(row["status"], "unreadable")


class Cache(_Judge):
    def answered(self, **kw):
        row = self.judge(**kw)
        self.assertEqual(self.answer((row["task_id"], good()))[1]["valid"], 1)
        return source_judge.get(self.cur, row["id"])

    def test_shown_again_for_30_days_without_a_read(self):
        first = self.answered()
        reader = StubReader(feed_result())
        again = self.judge(reader=reader)
        self.assertEqual((again["id"], reader.asked), (first["id"], []))
        later = NOW + timedelta(days=source_judge.CACHE_DAYS + 1)
        fresh = self.judge(reader=reader, now=later)
        self.assertNotEqual(fresh["id"], first["id"])
        self.assertEqual(len(reader.asked), 1)

    def test_a_judgement_being_made_is_shown_not_asked_twice(self):
        with self.conn.transaction():
            first = source_judge.ask(self.cur, SITE)
            second = source_judge.ask(self.cur, SITE, again=True)
        self.assertTrue(first["needs_read"])
        self.assertEqual((second["id"], second["needs_read"]), (first["id"], False))

    def test_a_read_that_never_finished_is_read_again(self):
        with self.conn.transaction():
            first = source_judge.ask(self.cur, SITE, now=NOW - timedelta(hours=1))
            second = source_judge.ask(self.cur, SITE, now=NOW)
        self.assertNotEqual(second["id"], first["id"])
        self.assertTrue(second["needs_read"])
        self.assertEqual(source_judge.get(self.cur, first["id"])["status"], "failed")

    def test_asking_again_with_the_same_items_keeps_the_answer(self):
        first = self.answered()
        again = self.judge(again=True)
        self.assertNotEqual(again["id"], first["id"])
        self.assertEqual((again["status"], again["verdict"], again["task_id"]), ("answered", "follow", first["task_id"]))
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'source_judge'")
        self.assertEqual(self.cur.fetchone()[0], 1)
        self.assertTrue(source_judge.page(self.cur, SITE)["same_items"])

    def test_asking_again_after_new_items_asks_again(self):
        first = self.answered()
        newer = scout_reads.ReadResult(resolved=feed_result().resolved,
                                       items=[item(-1, url=f"{SITE}/post-new")] + [item(k) for k in range(9)])
        again = self.judge(SITE, StubReader(newer), again=True)
        self.assertEqual(again["status"], "asked")
        self.assertNotEqual(again["task_id"], first["task_id"])
        self.assertFalse(source_judge.page(self.cur, SITE)["same_items"])


class Routes(_Judge):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(scout, "default_reader", return_value=StubReader(feed_result()))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_tap_and_the_look(self):
        before = self.counts()
        self.assertEqual(call("GET", "/api/markx/source-judge", query={"address": SITE}), (200, {"judgement": None}))
        status, body = call("POST", "/api/markx/source-judge", body={"address": "judged.example"})
        self.assertEqual(status, 200, body)
        self.assertIn(body["judgement"]["status"], ("reading", "asked"))      # the read runs after the answer
        status, body = call("GET", "/api/markx/source-judge", query={"address": SITE})
        self.assertEqual((status, body["judgement"]["status"]), (200, "asked"))
        self.assertEqual(self.counts(), before)
        self.assertEqual(call("POST", "/api/markx/source-judge", body={"address": ""})[0], 400)

    def test_off_answers_404(self):
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertEqual(call("POST", "/api/markx/source-judge", body={"address": SITE})[0], 404)
        self.assertEqual(call("GET", "/api/markx/source-judge", query={"address": SITE})[0], 404)


if __name__ == "__main__":
    unittest.main()
