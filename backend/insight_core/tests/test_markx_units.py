"""0181 (Stealth v10.16 slice K): own round-ups. A round-up's items are units (markx/units.py, mx_units), attached
to the stored posts they link by Pairing's `attach` relation (mx_attach), the issue's time read by Pairing's post date
(mx_roundups.issue_at); the digest ranks what round-ups carry by curators.

  - Splitters on fixture HTML: a digest's unclosed list items under headings, malformed nested lists (each topic its
    own item), a Telegram digest's bulleted lines, a link list, headed sections, the reading's items, an essay whose
    paragraphs link (no shape), its own table of contents and its source's signature links (no item).
  - The tag: the reading says so; a digest's shape only from a digest source (most of its posts have it) and only
    when the reading did not see the post whole.
  - Attach precision on fixtures: a link to a stored post in the window attaches; an older post, a round-up, the
    round-up itself, an unstored page never.
  - The issue's time: the latest attached item's within the reach, in Pairing's post date; every ordinary post's date
    and every caller's result identical (a seeded world).
  - NEVER a voice: no module but units.py (and Pairing's post date and attach) reads the units tables (a scan of the
    code), and the decision run (tasks, memberships, connections, News rows, back and later rows) and the anchors'
    voices are the same with the units and attach rows as without them.
  - Migration 0123: the tables, their checks, idempotent.

The DB parts run only on a database whose name ends in _test (they empty the mx_* tables inside their transaction)."""
from __future__ import annotations

import json
import pathlib
import re
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.markx import pairing, repo, tasks, units, validate
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES

H, D = timedelta(hours=1), timedelta(days=1)
T0 = datetime(2100, 6, 1, tzinfo=timezone.utc)
URL = "https://digest.example/issues/2100-06-01"

# ---- the splitters (pure) ------------------------------------------------------------------------------------------

DIGEST = """<h1>Daily recap</h1>
<h3>Releases</h3>
<li><p><b>Acme ships Widget 4.1</b>: faster and cheaper, per the <a href="https://x.com/acme/status/1001">launch</a>.</p>
<li>Pricing is unchanged for existing users.</li>
<li><p><b>Gizmo 2 is open weights</b>: the <a href="https://example.org/blog/gizmo-2">release post</a> has details.</p>
<h3>Research</h3>
<li><p>A <a href="https://arxiv.org/abs/2601.00001">new paper</a> on sparse attention drew attention.</p>
<li><p>Benchmarks moved: <a href="https://example.net/leaderboard-june">the June board</a>.</p>
<li><p>One more: <a href="https://example.com/news/one-more-thing">a small tool</a> for agents.</p>
<p>That's all for today. <a href="https://digest.example/issues/2100-06-01#top">Back to top</a></p>"""

MALFORMED = """<li><b>Topic A</b>: first, as <a href="https://example.com/a">this thread</a> says.
<ul><li>A detail of A with no link.</li>
<li><b>Topic B</b>: second, <a href="https://example.com/b">announced here</a>.
<ul><li>A detail of B.</li>
<li><b>Topic C</b>: third, <a href="https://example.com/c">see the post</a>.</li></ul></ul>"""

TELEGRAM = """<b>Weekly digest (#12)</b><br><br><u>LLM</u><br>- <a href="https://t.me/chan/101">Widget 4.1</a> — faster.<br>
- <a href="https://t.me/chan/102">Gizmo 2</a> — open weights.<br>continued on a second line.<br>
- <a href="https://t.me/chan/103">Sprocket</a> — a new API.<br>- <a href="https://t.me/chan/104">Cog 3</a> — cheaper.<br>
- <a href="https://t.me/chan/105">Lever</a> — a benchmark.<br><br>Thanks for reading!"""

ESSAY = """<p>I have been thinking about tools. As <a href="https://example.com/essay-one">one writer</a> argued, they
shape us more than we shape them, and the argument goes on for a while with many words in it.</p>
<p>A second paragraph with no link at all, long enough to matter, about what that means for how we build things and
why it is hard to see from inside the work itself.</p>
<p>Then <a href="https://example.com/essay-two">another piece</a> made the opposite case, at length and with care.</p>
<p>And <a href="https://example.com/essay-three">a third</a> tried to reconcile them, which mostly failed.</p>
<p>So <a href="https://example.com/essay-four">a fourth</a>, and <a href="https://example.com/essay-five">a fifth</a>.</p>"""

SECTIONS = """<h2>Acme raises a round</h2><p>Acme raised money, says <a href="https://example.com/acme-round">the report</a>.</p>
<h2>Gizmo is sued</h2><p>A lawsuit, <a href="https://example.com/gizmo-suit">filed today</a>.</p>"""

# A newsletter of paragraphs (0181 round 2): a lead story under a heading, numbered bold items whose sentence and
# related links follow on <br> lines, a bold label, fun extras.
NEWSLETTER = """<p><em>This is today's edition of </em><a href="https://letter.example/about">The Brief</a>.</p>
<h3>How a new method keeps agents in check</h3>
<p>A new approach aims to control models by designing incentives.</p>
<p>Researchers believe it could help, but questions remain.</p>
<p><a href="https://letter.example/2100/06/01/method">Here's how the method works</a>.</p>
<p><em>-A Writer</em></p>
<p><strong>The must-reads</strong></p>
<p><em>The stories worth your time today.</em></p>
<p><strong>1 Acme is ordering clients to limit a business</strong><br>It told providers that most sales must be elsewhere. (<a href="https://news.example/acme-order">Paper</a>)<br><em>+ The move follows pressure.</em> (<a href="https://news.example/acme-pressure">Wire</a>)</p>
<p><strong>2 Hackers turned fridges into a risk<br></strong>Attacks put systems on alert. (<a href="https://news.example/fridges">TV</a>)</p>
<p><strong>We can still have nice things</strong></p>
<p>+ Watch <a href="https://zoo.example/cubs">five cubs</a> grow up.<br>+ The <a href="https://photos.example/contest">photo contest</a> winners.</p>"""

# Release notes of paragraphs: each item a paragraph led by its link, a second paragraph with no link, a section
# heading over led paragraphs, a later paragraph with a link of its own (an item or more of the last: the type
# question's `continues` says).
RELEASES = """<p>This week's news, gathered from <a href="https://feeds.example/list">release feeds</a>.</p>
<h2>Releases</h2>
<p><a href="https://code.example/loom/v1">loom 1.0</a> merges feature branches into one integration branch.</p>
<p>Stacked branches are pushed as one pull request each, and the IDs stay the same.</p>
<p><a href="https://code.example/diffy/0.72">diffy 0.72</a> changes its heuristics and drops two parsers.</p>
<p>This release also adds a flag, and <a href="https://code.example/diffy/0.73">0.73</a> fixes a regression.</p>
<p>Also out: <a href="https://code.example/gizmos/0.3.1">gizmos 0.3.1</a>.</p>
<p><a href="https://code.example/gt/1.0">gt 1.0</a> is the first stable release of the command line tool.</p>
<p><a href="https://code.example/butler/0.23">butler 0.23</a> stops commits from disturbing staged files.</p>"""


class Splitters(unittest.TestCase):
    def test_a_newsletters_numbered_items_keep_their_headline_and_their_lines(self):
        s = units.split(NEWSLETTER, None, URL, {"kind": "roundup", "items": []})
        self.assertEqual(s.adapter, "lines")
        by_head = {i.headline: i for i in s.items}
        acme = by_head["Acme is ordering clients to limit a business"]          # its numbering dropped
        self.assertIn("It told providers", acme.text)                            # the sentence under the bold line
        self.assertEqual(acme.links, ("https://news.example/acme-order", "https://news.example/acme-pressure"))
        self.assertFalse(any(i.text.startswith(("It told providers", "+ The move")) for i in s.items))
        self.assertEqual(by_head["Hackers turned fridges into a risk"].links, ("https://news.example/fridges",))
        lead = by_head["How a new method keeps agents in check"]                 # a heading over its paragraphs
        self.assertEqual(lead.links, ("https://letter.example/2100/06/01/method",))
        self.assertIn("Researchers believe", lead.text)
        self.assertNotIn("must-reads", " ".join(i.text for i in s.items))      # a bold label with no link: no item
        extras = by_head["We can still have nice things"]                       # one item, typed by the question
        self.assertEqual(extras.links, ("https://zoo.example/cubs", "https://photos.example/contest"))

    def test_release_notes_keep_a_paragraph_with_no_link_in_its_item(self):
        s = units.split(RELEASES, None, URL, {"kind": "roundup", "items": []})
        self.assertEqual(s.adapter, "lines")
        texts = [i.text for i in s.items]
        self.assertEqual(len(texts), 7)
        self.assertTrue(texts[1].startswith("loom 1.0") and "Stacked branches" in texts[1])
        self.assertFalse(any(t.startswith(("Releases", "Stacked")) for t in texts))   # a heading over leads: a label
        self.assertTrue(texts[3].startswith("This release also adds"))          # its own link: an item (or `continues`)
        self.assertEqual([i.headline for i in s.items], [None] * 7)               # a link lead names no headline

    def test_a_digests_unclosed_items_each_an_item_its_link_less_detail_in_it(self):
        s = units.split(DIGEST, None, URL, None)
        self.assertTrue(s.structured)
        self.assertEqual(s.adapter, "list")
        self.assertEqual([i.links for i in s.items], [("https://x.com/acme/status/1001",),
                                                       ("https://example.org/blog/gizmo-2",),
                                                       ("https://arxiv.org/abs/2601.00001",),
                                                       ("https://example.net/leaderboard-june",),
                                                       ("https://example.com/news/one-more-thing",)])
        self.assertIn("Pricing is unchanged", s.items[0].text)          # the detail bullet stays with its topic
        self.assertNotIn("Research", " ".join(i.text for i in s.items))   # a heading is no item's
        self.assertEqual([i.n for i in s.items], [1, 2, 3, 4, 5])
        a, b = s.items[0].start, s.items[0].stop
        self.assertIn("Widget 4.1", DIGEST[a:b])                          # the span is in the HTML read

    def test_malformed_nested_lists_give_each_topic_its_own_item(self):
        items = units.split(MALFORMED, None, URL, {"kind": "roundup", "items": []}).items
        self.assertEqual([i.links for i in items], [("https://example.com/a",), ("https://example.com/b",),
                                                    ("https://example.com/c",)])
        self.assertIn("A detail of A", items[0].text)
        self.assertNotIn("Topic B", items[0].text)

    def test_a_telegram_digests_bulleted_lines_and_their_continuation(self):
        s = units.split(TELEGRAM, None, "https://t.me/chan/120", None)
        self.assertTrue(s.structured)
        self.assertEqual(s.adapter, "lines")
        self.assertEqual(len(s.items), 5)
        self.assertIn("continued on a second line", s.items[1].text)
        self.assertNotIn("Thanks for reading", s.items[-1].text)

    def test_an_essays_linking_paragraphs_are_no_digest_shape(self):
        s = units.split(ESSAY, None, "https://example.com/essay", None)
        self.assertFalse(s.structured)
        self.assertFalse(s.said)
        self.assertEqual(s.items, ())

    def test_headed_sections_split_a_round_up_the_reading_names(self):
        s = units.split(SECTIONS, None, URL, {"kind": "roundup", "items": []})
        self.assertTrue(s.said)
        self.assertEqual(s.adapter, "sections")
        self.assertEqual([i.links for i in s.items], [("https://example.com/acme-round",), ("https://example.com/gizmo-suit",)])
        self.assertFalse(units.split(SECTIONS, None, URL, {"kind": "report", "items": []}).said)

    def test_the_readings_own_items_when_the_html_gives_too_few(self):
        reading = {"kind": "roundup", "items": [
            {"headline_en": "Acme raises a round", "link": "https://example.com/acme-round"},
            {"headline_en": "A thing with no link", "link": None},
            {"headline_en": "Gizmo is sued", "link": "https://example.com/gizmo-suit"}]}
        s = units.split(None, "Today: Acme raised money https://example.com/acme-round and more.", URL, reading)
        self.assertEqual((s.said, s.adapter), (True, "reading"))
        self.assertEqual([i.headline for i in s.items], ["Acme raises a round", "A thing with no link", "Gizmo is sued"])
        self.assertEqual(s.items[0].links, ("https://example.com/acme-round",))
        self.assertGreaterEqual(s.items[0].start, 0)          # placed on the line linking it
        self.assertEqual(s.items[1].start, -1)
        self.assertEqual(s.items[2].links, ("https://example.com/gizmo-suit",))

    def test_its_own_page_and_its_sources_signature_are_no_item(self):
        toc = "".join(f'<li><a href="https://digest.example/issues/2100-06-01/#s{k}">Section {k}</a></li>' for k in range(6))
        self.assertEqual(units.split(toc, None, URL, {"kind": "roundup", "items": []}).items, ())
        signed = DIGEST.replace("https://example.net/leaderboard-june", "https://digest.example/subscribe")
        s = units.split(signed, None, URL, {"kind": "roundup", "items": []}, skip=["https://digest.example/subscribe"])
        self.assertNotIn(("https://digest.example/subscribe",), [i.links for i in s.items])
        self.assertEqual(len(s.items), 4)

    def test_a_reading_that_saw_the_whole_post_decides(self):
        self.assertTrue(units.split(TELEGRAM, None, URL, {"kind": "report", "items": []}).read_whole)
        self.assertFalse(units.split(DIGEST * 8, None, URL, {"kind": "report", "items": []}).read_whole)
        self.assertEqual(units.READ_SEEN, tasks.TEXT_CHARS)   # what a read task shows of a post

    def test_page_reads_links_as_posts_are_normalized(self):
        self.assertEqual(units.page("t.me/chan/7", URL), "https://t.me/chan/7")
        self.assertEqual(units.page("https://twitter.com/acme/status/1001", URL), "https://x.com/acme/status/1001")
        self.assertIsNone(units.page("https://example.com/pic.png", URL))
        self.assertIsNone(units.page("#top", URL))
        self.assertIsNone(units.page("mailto:a@example.com", URL))


class AttachGate(unittest.TestCase):
    def test_the_attach_rows_gates(self):
        pol = pairing.POLICIES[pairing.ATTACH]
        self.assertEqual(pol.independence, pairing.NEVER_VOICE)
        self.assertEqual((pol.window, pol.after, pol.issue_reach), (14 * D, 2 * D, 2 * D))
        ok = lambda t, **kw: pairing.attaches(pol, T0, t, **{"target_is_roundup": False, "same_post": False, **kw})  # noqa: E731
        self.assertTrue(ok(T0 - 13 * D))
        self.assertTrue(ok(T0 + 47 * H))
        self.assertFalse(ok(T0 - 15 * D))
        self.assertFalse(ok(T0 + 49 * H))
        self.assertFalse(ok(T0, target_is_roundup=True))
        self.assertFalse(ok(T0, same_post=True))


# ---- stored ----------------------------------------------------------------------------------------------------------

@requires_test_db
class _Db(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        from insight_core.markx import schemas
        schemas.load_guides(self.cur)
        self.news = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Example News"}))
        self.other = insert_scratch_source(self.cur, platform="telegram", settings_json=json.dumps({"display_name": "Example Channel"}))
        self.digest = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Example Digest"}))

    def post(self, source, at, *, url=None, html=None, text="A post with enough words to be read as one, about Widget 4.1.",
             title="A post"):
        url = url or f"https://test.invalid/units/{uuid.uuid4().hex}"
        self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, title, content, content_html, published_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""", (source, url, url, title, text, html, at))
        return str(self.cur.fetchone()[0])

    def read(self, pid, kind="roundup", items=()):
        task_id, _ = tasks.read_task(self.cur, pid)
        task = {"kind": "read", "guide": "read-v2", "a": pid}
        ans = {"kind": kind, "events": "several", "lang": "en", "items": list(items), "mentions": [],
               "main": {"headline_en": "A day of news", "actors": [], "object": "", "action": "reported"}}
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer=ans)
        repo.answer_task(self.cur, task_id)
        tasks.record(self.cur, task, call, ans)

    def digest_html(self, targets, extra=()):
        lis = "".join(f'<li><p>Item {k}: <a href="{t}">a link</a> to something new.</p>' for k, t in enumerate(targets))
        lis += "".join(f'<li><p>Extra {k}: <a href="{t}">a page</a>.</p>' for k, t in enumerate(extra))
        return "<h3>Today</h3>" + lis


class Stored(_Db):
    def test_a_reading_landing_splits_the_post_and_attaches_its_items(self):
        a = self.post(self.news, T0 - 5 * H, url="https://test.invalid/units/a")
        b = self.post(self.other, T0 - 30 * H, url="https://test.invalid/units/b")
        old = self.post(self.news, T0 - 20 * D, url="https://test.invalid/units/old")
        rd = self.post(self.digest, T0, html=self.digest_html(["https://test.invalid/units/a", "https://test.invalid/units/b",
                                                               "https://test.invalid/units/old"],
                                                              ["https://example.com/news/unstored-1", "https://example.com/news/unstored-2"]))
        self.read(rd)                                   # tasks.record -> units.note
        self.cur.execute("SELECT roundup, why, adapter, units FROM mx_roundups WHERE post_id = %s", (rd,))
        self.assertEqual(self.cur.fetchone(), (True, "reading", "list", 5))
        self.cur.execute("SELECT u.n, a.target_id::text FROM mx_attach a JOIN mx_units u ON u.id = a.unit_id ORDER BY 1")
        self.assertEqual(self.cur.fetchall(), [(1, a), (2, b)])   # not the 20-day-old post, not an unstored page
        self.assertNotIn(old, [r["carries"][0] for r in units.also_in(self.cur, [old])])
        got = units.also_in(self.cur, [a])
        self.assertEqual([(r["post"], r["n"], r["source"]) for r in got], [(rd, 1, "Example Digest")])

    def test_never_a_round_up_nor_the_round_up_itself(self):
        prev = self.post(self.digest, T0 - D, url="https://test.invalid/units/prev",
                         html=self.digest_html([f"https://example.com/news/p{k}" for k in range(5)]))
        self.read(prev)                                  # yesterday's issue: a round-up
        plain = self.post(self.other, T0 - 2 * H, url="https://test.invalid/units/plain")
        rd = self.post(self.digest, T0, url="https://test.invalid/units/today", html=self.digest_html(
            ["https://test.invalid/units/prev", "https://test.invalid/units/today?ref=self", "https://test.invalid/units/plain"],
            [f"https://example.com/news/q{k}" for k in range(3)]))
        self.read(rd)
        self.cur.execute("SELECT target_id::text FROM mx_attach WHERE roundup_id = %s", (rd,))
        self.assertEqual([r[0] for r in self.cur.fetchall()], [plain])

    def test_the_issue_time_is_its_latest_item_within_the_reach_in_pairings_post_date(self):
        a = self.post(self.news, T0 + 20 * H, url="https://test.invalid/units/a2")     # a daily dated at its day's start
        b = self.post(self.other, T0 + 9 * H, url="https://test.invalid/units/b2")
        far = self.post(self.news, T0 - 10 * D, url="https://test.invalid/units/far")  # attached, out of the reach
        rd = self.post(self.digest, T0, html=self.digest_html(
            ["https://test.invalid/units/a2", "https://test.invalid/units/b2", "https://test.invalid/units/far"],
            ["https://example.com/news/u1", "https://example.com/news/u2"]))
        self.read(rd)
        self.cur.execute(f"SELECT {pairing.post_date('p')}, {pairing.ordinary_date('p')}, p.published_at FROM posts p WHERE id = %s", (rd,))
        self.assertEqual(self.cur.fetchone(), (T0 + 20 * H, T0, T0))      # published_at never rewritten
        self.cur.execute("SELECT count(*) FROM mx_attach WHERE target_id = %s", (far,))
        self.assertEqual(self.cur.fetchone()[0], 1)
        for p, at in ((a, T0 + 20 * H), (b, T0 + 9 * H), (far, T0 - 10 * D)):
            self.cur.execute(f"SELECT {pairing.post_date('p')} FROM posts p WHERE id = %s", (p,))
            self.assertEqual(self.cur.fetchone()[0], at)                    # an ordinary post: its own date

    def test_keep_everything_a_new_split_appends_and_the_old_rows_stay(self):
        rd = self.post(self.digest, T0, html=self.digest_html([f"https://example.com/news/v{k}" for k in range(5)]))
        self.read(rd)
        self.cur.execute("SELECT count(*) FROM mx_units WHERE post_id = %s", (rd,))
        self.assertEqual(self.cur.fetchone()[0], 5)
        self.cur.execute("UPDATE posts SET content_html = content_html || '<li><p>More: <a href=\"https://example.com/news/v9\">x</a>.</p>' WHERE id = %s", (rd,))
        units.note(self.cur, [rd])
        self.cur.execute("SELECT count(*), count(DISTINCT basis) FROM mx_units WHERE post_id = %s", (rd,))
        self.assertEqual(self.cur.fetchone(), (11, 2))
        self.assertEqual(len(units.units_of(self.cur, [rd])[rd]), 6)       # readers read the current split
        units.note(self.cur, [rd])                                         # the same inputs: nothing new
        self.cur.execute("SELECT count(*) FROM mx_units WHERE post_id = %s", (rd,))
        self.assertEqual(self.cur.fetchone()[0], 11)

    def test_a_digests_shape_tags_only_in_a_digest_source_and_the_backfill_is_resumable_newest_first(self):
        long = " ".join(f"word{k}" for k in range(60))
        shaped = [self.post(self.digest, T0 - k * D, title=f"Issue {k}", html="<h3>Today</h3>" + "".join(
            f'<li><p>{long} item {j}: <a href="https://example.com/i{k}-{j}">link</a>.</p>' for j in range(6)))
            for k in range(5)]
        essays_with_lists = [self.post(self.news, T0 - k * D, title=f"Essay {k}", html="<h3>Notes</h3>" + "".join(
            f'<li><p>{long} item {j}: <a href="https://example.com/e{k}-{j}">link</a>.</p>' for j in range(6)))
            for k in range(1)] + [self.post(self.news, T0 - k * D, html=f"<p>{long} {long} {long}</p>") for k in range(1, 5)]
        got = units.backfill(self.cur, limit=3, recheck=0, now=T0)
        self.assertEqual(got["split"], 3)
        self.cur.execute("SELECT post_id::text FROM mx_roundups")
        newest = {r[0] for r in self.cur.fetchall()}
        self.assertTrue({shaped[0], essays_with_lists[0]} <= newest)
        while units.backfill(self.cur, limit=3, recheck=0, now=T0)["left"]:
            pass
        self.cur.execute("SELECT post_id::text, roundup, why FROM mx_roundups WHERE post_id = ANY(%s::uuid[])",
                         (shaped + essays_with_lists,))
        rows = {p: (r, w) for p, r, w in self.cur.fetchall()}
        self.assertTrue(all(rows[p] == (True, "structure") for p in shaped))
        self.assertEqual(rows[essays_with_lists[0]], (False, "structure"))   # the shape, but not a digest source
        self.assertEqual(units.digest_sources(self.cur, [self.digest, self.news]), {self.digest})


class Digest(_Db):
    def test_ranked_by_separate_curators_only_in_round_ups_flagged_day_and_week(self):
        a = self.post(self.news, T0 - 3 * H, url="https://test.invalid/units/da", title="Acme ships Widget 4.1")
        second = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Example Links"}))
        rd1 = self.post(self.digest, T0, html=self.digest_html(["https://test.invalid/units/da", "https://example.com/news/only"],
                                                               [f"https://example.com/news/x{k}" for k in range(3)]))
        rd2 = self.post(second, T0 + H, html=self.digest_html(["https://test.invalid/units/da", "https://example.com/news/only"],
                                                              [f"https://example.com/news/y{k}" for k in range(3)]))
        own = self.post(self.news, T0 + 2 * H, html=self.digest_html(["https://test.invalid/units/da"],
                                                                     [f"https://example.com/news/z{k}" for k in range(4)]))
        for p in (rd1, rd2, own):
            self.read(p)
        d = units.digest(self.cur, "day", T0 + 3 * H)
        top = d["items"][0]
        self.assertEqual((top["kind"], top["headline"], top["curators"], top["only_roundups"]),
                         ("post", "Acme ships Widget 4.1", 2, False))     # its own source's round-up curates nothing
        self.assertEqual(top["issues"], 3)
        only = next(i for i in d["items"] if i["ref"] == "https://example.com/news/only")
        self.assertEqual((only["curators"], only["only_roundups"]), (2, True))
        self.assertEqual(units.digest(self.cur, "week", T0 + 3 * H)["count"], d["count"])
        self.assertEqual(units.digest(self.cur, "day", T0 + 30 * D)["count"], 0)
        with self.assertRaises(ValueError):
            units.digest(self.cur, "month")

    def test_a_sources_signature_link_is_no_item(self):
        for k in range(units.SIGNATURE):
            self.read(self.post(self.digest, T0 - k * D, html=self.digest_html(
                ["https://example.com/profile-of-the-digest/me"], [f"https://example.com/news/s{k}-{j}" for j in range(4)])))
        keys = [i["ref"] for i in units.digest(self.cur, "week", T0 + H)["items"]]
        self.assertNotIn("https://example.com/profile-of-the-digest/me", keys)
        self.assertIn("https://example.com/news/s0-0", keys)


class Types(_Db):
    """0181 round 2: each item is asked its type, a short headline and whether it continues the item before it (kind
    unit_types, ~20 a question); an own round-up keeps the news types; single-curator items rank below and are capped."""

    def answer(self, task_id, units_answer):
        task = repo.get_task(self.cur, task_id)
        answer, error = validate.check("unit_types", {"units": units_answer}, task["input"], task["guide"])
        self.assertIsNone(error)
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer=answer)
        repo.answer_task(self.cur, task_id)
        tasks.record(self.cur, task, call, answer)

    def asked(self):
        self.cur.execute("SELECT id, input FROM mx_tasks WHERE kind = 'unit_types' ORDER BY created_at, id")
        return self.cur.fetchall()

    def test_items_are_asked_once_by_their_words_and_an_issue_keeps_the_news(self):
        self.post(self.news, T0 - 3 * H, url="https://test.invalid/units/ta", title="Acme ships Widget 4.1")
        rd = self.post(self.digest, T0, html=self.digest_html(
            ["https://test.invalid/units/ta", "https://example.com/books/my-novel", "https://example.com/2011/old-story",
             "https://example.com/news/widget-more", "https://example.com/papers/sparse"]))
        self.read(rd)
        self.assertEqual(units.digest(self.cur, "day", T0 + 3 * H)["untyped"], 5)
        self.assertEqual(units.plan_types(self.cur, now=T0 + H), 1)
        self.assertEqual(units.plan_types(self.cur, now=T0 + H), 0)            # asked once
        (tid, text), = self.asked()
        self.assertIn("ROUND-UP: Example Digest", text)
        self.assertEqual(re.findall(r"^\[(u\d+)\] ", text, re.M), ["u1", "u2", "u3", "u4", "u5"])
        task = repo.get_task(self.cur, tid)
        bad = [{"key": "u1", "type": "product_release", "headline": "Acme ships Widget 4.1", "continues": False}]
        self.assertIn("not answered", validate.check("unit_types", {"units": bad}, task["input"], task["guide"])[1])
        self.answer(tid, [
            {"key": "u1", "type": "product_release", "headline": "Acme ships Widget 4.1 to everyone", "continues": False},
            {"key": "u2", "type": "promo", "headline": "The author's novel", "continues": False},
            {"key": "u3", "type": "other", "headline": "A story from 2011", "continues": False},
            {"key": "u4", "type": "product_release", "headline": "More on Widget", "continues": True},
            {"key": "u5", "type": "research_result", "headline": "A paper on sparse attention.", "continues": False}])
        d = units.digest(self.cur, "day", T0 + 3 * H)
        self.assertEqual((d["left_out"], d["untyped"]), ({"continues": 1, "other": 1, "promo": 1}, 0))
        self.assertEqual([i["headline"] for i in d["items"]],
                         ["Acme ships Widget 4.1 to everyone", "A paper on sparse attention"])   # the worker's headline
        # a new split of the same words keeps their answers: only the new item is asked
        self.cur.execute("UPDATE posts SET content_html = content_html || '<li><p>Item new: <a href=\"https://example.com/news/new\">x</a>.</p>' WHERE id = %s", (rd,))
        units.note(self.cur, [rd])
        self.assertEqual(units.digest(self.cur, "day", T0 + 3 * H)["untyped"], 1)
        self.assertEqual(units.plan_types(self.cur, now=T0 + H), 1)
        (_, again), = [t for t in self.asked() if t[0] != tid]
        self.assertEqual(re.findall(r"^\[(u\d+)\] ", again, re.M), ["u1"])
        self.assertIn("(before u1: Item 4", again)                               # the item before, for context

    def test_what_insight_holds_or_two_curators_carry_ranks_first_single_curator_items_capped(self):
        second = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Example Links"}))
        many = [f"https://example.com/news/m{k}" for k in range(units.SOLO_PER_SOURCE + 2)]
        rd1 = self.post(self.digest, T0, html=self.digest_html(many + ["https://example.com/news/shared"]))
        rd2 = self.post(second, T0 + H, html=self.digest_html(["https://example.com/news/shared"],
                                                              [f"https://example.com/news/s{k}" for k in range(4)]))
        for p in (rd1, rd2):
            self.read(p)
        d = units.digest(self.cur, "day", T0 + 3 * H)
        self.assertEqual(d["items"][0]["ref"], "https://example.com/news/shared")       # 2 curators: first
        solo = [i for i in d["items"] if i["tier"] == 2]
        self.assertEqual(sum(1 for i in solo if i["units"][0]["post"] == rd1), units.SOLO_PER_SOURCE)
        self.assertEqual(d["capped"], 2)
        self.assertEqual([i["place"] for i in solo], sorted(i["place"] for i in solo))   # the round-ups' own order

    def test_an_issue_waits_for_its_items_types_then_keeps_the_news(self):
        repo.set_setting(self.cur, units.TZ_KEY, 0)
        rd = self.post(self.digest, T0 + 5 * H, html=self.digest_html([f"https://example.com/news/w{k}" for k in range(5)]))
        self.read(rd)
        units.backfill(self.cur, now=T0 + D + 7 * H)                        # splits, and asks the items' types
        (tid, _), = self.asked()
        units.issues_step(self.cur, T0 + D + 7 * H)
        self.cur.execute("SELECT count(*) FROM mx_roundup_issues WHERE span = 'day' AND period_start = %s", (T0,))
        self.assertEqual(self.cur.fetchone()[0], 0)                          # settled, but its types wait
        self.answer(tid, [{"key": f"u{k}", "type": "promo" if k == 1 else "incident", "headline": f"Item {k} happened",
                           "continues": False} for k in range(1, 6)])
        built = units.issues_step(self.cur, T0 + D + 7 * H)
        issue = units.issue(self.cur, built["day"][-1])
        self.assertEqual((issue["from"], issue["count"], issue["left_out"], issue["untyped"]),
                         (T0.isoformat(), 4, {"promo": 1}, 0))


class Periods(unittest.TestCase):
    def test_the_owners_days_and_weeks_at_the_offset(self):
        plus4 = timedelta(hours=4)
        # 2100-06-01 is a Tuesday; 20:00 UTC is local midnight at UTC+4
        self.assertEqual(units.period("day", datetime(2100, 6, 1, 19, 59, tzinfo=timezone.utc), plus4),
                         (datetime(2100, 5, 31, 20, tzinfo=timezone.utc), datetime(2100, 6, 1, 20, tzinfo=timezone.utc)))
        self.assertEqual(units.period("day", datetime(2100, 6, 1, 20, 0, tzinfo=timezone.utc), plus4)[0],
                         datetime(2100, 6, 1, 20, tzinfo=timezone.utc))
        self.assertEqual(units.period("week", datetime(2100, 6, 3, 12, tzinfo=timezone.utc), plus4),
                         (datetime(2100, 5, 30, 20, tzinfo=timezone.utc), datetime(2100, 6, 6, 20, tzinfo=timezone.utc)))
        self.assertEqual(units.period("day", datetime(2100, 6, 1, 12, tzinfo=timezone.utc), timedelta(0))[0], T0)
        # a database time in another session zone (19:59 UTC = 23:59 at UTC+4) and a naive time (UTC) say the same
        dubai = timezone(timedelta(hours=4))
        self.assertEqual(units.period("day", datetime(2100, 6, 1, 23, 59, tzinfo=dubai), plus4),
                         units.period("day", datetime(2100, 6, 1, 19, 59, tzinfo=timezone.utc), plus4))
        self.assertEqual(units.period("day", datetime(2100, 6, 1, 19, 59), plus4),
                         units.period("day", datetime(2100, 6, 1, 19, 59, tzinfo=timezone.utc), plus4))
        with self.assertRaises(ValueError):
            units.period("month", T0, plus4)

    def test_a_period_is_built_only_after_it_closed_and_settled(self):
        plus4 = timedelta(hours=4)
        now = datetime(2100, 6, 2, 1, tzinfo=timezone.utc)      # local 05:00, 6 h settle: the last closed day is 31 May
        days = units.closed_periods("day", now, plus4, 2)
        self.assertEqual(days[0], (datetime(2100, 5, 30, 20, tzinfo=timezone.utc), datetime(2100, 5, 31, 20, tzinfo=timezone.utc)))
        self.assertEqual(days[1][1], days[0][0])
        later = units.closed_periods("day", now + 2 * H, plus4, 1)[0]   # local 07:00: 1 June has settled
        self.assertEqual(later[0], datetime(2100, 5, 31, 20, tzinfo=timezone.utc))
        week = units.closed_periods("week", now, plus4, 1)[0]
        self.assertEqual(week, (datetime(2100, 5, 23, 20, tzinfo=timezone.utc), datetime(2100, 5, 30, 20, tzinfo=timezone.utc)))


class Issues(_Db):
    def test_each_closed_day_and_week_built_once_kept_and_a_rebuild_is_a_new_version(self):
        repo.set_setting(self.cur, units.TZ_KEY, 0)
        a = self.post(self.news, T0 + 3 * H, url="https://test.invalid/units/ia", title="Acme ships Widget 4.1")
        rd = self.post(self.digest, T0 + 5 * H, html=self.digest_html(["https://test.invalid/units/ia"],
                                                                     [f"https://example.com/news/w{k}" for k in range(4)]))
        self.read(rd)
        now = T0 + 2 * D + 7 * H                                  # 1 and 2 June closed and settled (UTC)
        self.assertEqual(units.issues_step(self.cur, now), {})     # a post never split (the backfill's): it waits
        units.backfill(self.cur, now=now)
        built = units.issues_step(self.cur, now)
        self.assertEqual(len(built["day"]), units.ISSUE_CATCHUP["day"])
        got = units.issues(self.cur)
        self.assertEqual((got["daily"]["from"], got["daily"]["count"]), ((T0 + D).isoformat(), 0))   # 2 June: nothing
        first = next(p for p in got["past"] if p["span"] == "day" and p["from"] == T0.isoformat())
        june1 = units.issue(self.cur, first["id"])
        self.assertEqual(june1["items"][0]["headline"], "Acme ships Widget 4.1")
        self.assertEqual(got["tz_offset_minutes"], 0)
        self.assertEqual(units.issues_step(self.cur, now), {})     # built once: a second run writes nothing
        # a new item for 1 June arrives late: the stored issue stays as it was; a rebuild is version 2
        b = self.post(self.other, T0 + 9 * H, url="https://test.invalid/units/ib", title="Gizmo 2 is out")
        rd2 = self.post(self.digest, T0 + 10 * H, html=self.digest_html(["https://test.invalid/units/ib"],
                                                                       [f"https://example.com/news/g{k}" for k in range(4)]))
        self.read(rd2)
        self.assertEqual(units.issue(self.cur, first["id"]), june1)
        new_id = units.build_issue(self.cur, "day", T0, rebuild=True)
        self.cur.execute("SELECT version, count FROM mx_roundup_issues WHERE span = 'day' AND period_start = %s ORDER BY 1", (T0,))
        self.assertEqual([v for v, _ in self.cur.fetchall()], [1, 2])
        self.assertIn("Gizmo 2 is out", [i["headline"] for i in units.issue(self.cur, new_id)["items"]])
        self.assertIn(new_id, [p["id"] for p in units.issues(self.cur)["past"]])          # readers read the newest
        self.assertNotIn(first["id"], [p["id"] for p in units.issues(self.cur, limit=200)["past"]])
        del a, b

    def test_the_boundary_is_a_setting(self):
        self.assertEqual(units.tz_offset(self.cur), timedelta(hours=4))     # the owner's UTC+4 by default
        repo.set_setting(self.cur, units.TZ_KEY, -300)
        self.assertEqual(units.tz_offset(self.cur), timedelta(hours=-5))
        units.backfill(self.cur, now=T0 + 3 * D)
        units.issues_step(self.cur, T0 + 3 * D)
        self.cur.execute("SELECT DISTINCT extract(hour FROM period_start AT TIME ZONE 'UTC') FROM mx_roundup_issues")
        self.assertEqual([r[0] for r in self.cur.fetchall()], [5])


# ---- never a voice -----------------------------------------------------------------------------------------------------

UNIT_TABLES = re.compile(r"\bmx_(units|attach|roundups|unit_types|unit_type_asks)\b")
READERS = {"markx/units.py", "markx/pairing.py", "markx/event_types.py",   # event_types: of_units, the type seam
           "db/migrations/0123_markx_units.sql", "db/migrations/0125_markx_unit_types.sql"}


class NoOtherReader(unittest.TestCase):
    def test_no_module_but_units_and_pairings_basics_reads_the_units_tables(self):
        """A leak needs a reader: every consumer of voices, News counts and corroboration reads its own tables. Only
        units.py (the units, attach, the digest, "also in round-ups") and Pairing (its post date's issue time, its
        attach source) may name these tables; the tests may."""
        root = pathlib.Path(units.__file__).resolve().parents[1]
        found = set()
        for path in root.rglob("*"):
            if path.suffix not in (".py", ".sql") or "tests" in path.parts:
                continue
            if UNIT_TABLES.search(path.read_text(encoding="utf-8", errors="ignore")):
                found.add(path.relative_to(root).as_posix())
        self.assertEqual(found, READERS)
        from insight_core.markx import event_types
        src = pathlib.Path(event_types.__file__).read_text()
        self.assertEqual(set(UNIT_TABLES.findall(src)), {"unit_types"})     # the seam reads the types only

    def test_pairings_reads_are_the_issue_time_and_the_attach_source_only(self):
        src = pathlib.Path(pairing.__file__).read_text()
        self.assertEqual(set(re.findall(r"\bmx_(?:units|attach|roundups)\b", src)), {"mx_roundups"})
        self.assertIn("issue_at", pairing.POST_DATE)
        self.assertNotIn("mx_roundups", pairing.ORDINARY_DATE)


from insight_core.tests.test_markx_pairing import _World   # noqa: E402  (the seeded world of 0166's equivalence)


class NeverAVoice(_World):
    """The seeded world plus three round-ups (read as round-ups) whose items link its posts: the decision run (its
    tasks, memberships, connections, News rows with their voices and mentions, back and later rows) and the anchors'
    voices are the same with every unit and attach row as with none of them."""

    def setUp(self):
        super().setUp()
        self.digest = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Example Digest"}))
        self.cur.execute("SELECT normalized_url FROM posts WHERE id = ANY(%s::uuid[]) ORDER BY published_at", (self.posts,))
        urls = [r[0] for r in self.cur.fetchall()]
        self.roundups = []
        for k in range(3):
            at = T0 + (2 + 4 * k) * 24 * H
            html = "<h3>Today</h3>" + "".join(f'<li><p>Item {j}: <a href="{u}">a post</a> says something new.</p>'
                                              for j, u in enumerate(urls[k * 20:k * 20 + 8]))
            self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, title, content, content_html, published_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                             (self.digest, f"https://test.invalid/digest/{k}", f"https://test.invalid/digest/{k}",
                              f"Daily digest {k}", "A digest of the day.", html, at))
            rid = str(self.cur.fetchone()[0])
            task_id, _ = tasks.read_task(self.cur, rid)
            ans = {"kind": "roundup", "events": "several", "lang": "en", "items": [], "mentions": [],
                   "main": {"headline_en": "A day", "actors": [], "object": "", "action": "reported"}}
            call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer=ans)
            repo.answer_task(self.cur, task_id)
            tasks.record(self.cur, {"kind": "read", "guide": "read-v2", "a": rid}, call, ans)
            self.roundups.append(rid)
        self.cur.execute("SELECT count(*) FROM mx_attach")
        self.attached = self.cur.fetchone()[0]

    def state(self):
        self.cur.execute("SELECT kind, input, a::text, b::text, status FROM mx_tasks ORDER BY 1, 2, 3, 4")
        t = self.cur.fetchall()
        self.cur.execute("""SELECT sp.post_id::text, sp.role, s.first_at FROM mx_story_posts sp JOIN mx_stories s ON s.id = sp.story_id
                             WHERE sp.valid_to IS NULL ORDER BY 3, 1, 2""")
        m = self.cur.fetchall()
        self.cur.execute("SELECT a_kind, b_kind, relation, rule FROM mx_connections WHERE valid_to IS NULL ORDER BY 1, 2, 3, 4")
        c = self.cur.fetchall()
        self.cur.execute("""SELECT first_at, voices, reports, shares, mentions, score, tag,
                                   (SELECT array_agg((x->>0) || ':' || (x->>1) ORDER BY x->>0, x->>1) FROM jsonb_array_elements(posts) x)
                              FROM mx_news WHERE run_id = (SELECT id FROM mx_runs ORDER BY started_at DESC LIMIT 1)
                             ORDER BY 1, 2, 3, 4, 5, 6""")
        n = [tuple(str(x) for x in r) for r in self.cur.fetchall()]
        self.cur.execute("SELECT story::text, window_at FROM mx_back ORDER BY 1, 2")
        b = self.cur.fetchall()
        self.cur.execute("SELECT story::text, post::text FROM mx_later ORDER BY 1, 2")
        l = self.cur.fetchall()
        return t, m, c, n, b, l

    def test_the_decision_run_and_the_anchors_are_the_same_without_any_unit_or_attach_row(self):
        from insight_core.markx import anchors
        from insight_core.markx import candidates as C
        from insight_core.markx import decide as D_
        from insight_core.tests.test_markx_pairing import DecisionRun
        self.assertGreater(self.attached, 5)
        C.find(self.cur, self.posts + self.roundups)
        for pid in self.posts:
            tasks.read_task(self.cur, pid)
        DecisionRun.answer_all(self)

        def rounds():
            out = []
            for _ in range(2):
                D_.run(self.cur, now=self.now, full=True)
                voices = sorted((a.kind, tuple(sorted(m.id for m in a.members)), a.voices) for a in anchors.of(self.cur).values())
                out.append((self.state(), voices))
                DecisionRun.answer_all(self)
            return out
        self.cur.execute("SAVEPOINT units_leak")
        self.assertTrue(units.also_in(self.cur, self.posts))          # the units are there and attached
        with_units = rounds()
        self.cur.execute("ROLLBACK TO SAVEPOINT units_leak")
        self.cur.execute("DELETE FROM mx_attach")
        self.cur.execute("DELETE FROM mx_units")
        self.assertEqual(units.also_in(self.cur, self.posts), [])
        without = rounds()
        self.cur.execute("ROLLBACK TO SAVEPOINT units_leak")
        names = ("tasks", "memberships", "connections", "news rows", "back rows", "later rows")
        for n, ((sw, vw), (so, vo)) in enumerate(zip(with_units, without)):
            for name, w, o in zip(names, sw, so):
                self.assertEqual(w, o, f"{name}, round {n}")
            self.assertEqual(vw, vo, f"anchors' voices, round {n}")
        self.assertTrue(with_units[-1][0][1])                          # the world made memberships

    def test_a_round_ups_items_never_add_a_voice_to_a_story(self):
        """Pairing's voices are read from posts: a story's voices are its members' sources, whoever lists it."""
        from insight_core.markx import anchors
        self.cur.execute("SELECT DISTINCT target_id::text FROM mx_attach")
        targets = {r[0] for r in self.cur.fetchall()}
        for key, a in anchors.of(self.cur, kinds=(anchors.IX,)).items():
            members = {m.id for m in a.members}
            self.assertNotIn(self.digest, {m.src for m in a.members})
            if members & targets:
                self.assertEqual(a.voices, pairing.voices((m.src, "saved" if m.saved else None) for m in a.members))


class PostDateIdentity(_World):
    """Every caller of Pairing's post date reads the same date for an ordinary post as before 0181 (the old
    expression), and the same results, with a round-up's issue time stored or not."""

    OLD = "COALESCE({p}.surfaced_at, {p}.published_at, {p}.fetched_at)"

    def test_an_ordinary_posts_date_and_every_callers_result_are_the_same(self):
        from insight_core.markx import back, happening
        from insight_core.markx import candidates as C
        self.cur.execute(f"SELECT p.id::text, {self.OLD.format(p='p')}, {pairing.post_date('p')} FROM posts p "
                         "WHERE p.id = ANY(%s::uuid[])", (self.posts,))
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), len(self.posts))
        self.assertTrue(all(old == new for _, old, new in rows))
        digest = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Example Digest"}))
        self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, title, content, published_at)
                            VALUES (%s, 'https://test.invalid/digest/x', 'https://test.invalid/digest/x', 'Digest', 'A digest.', %s)
                            RETURNING id""", (digest, T0 + 3 * 24 * H))
        rd = str(self.cur.fetchone()[0])

        def results():
            self.cur.execute("SAVEPOINT post_date")
            C.find(self.cur, self.posts)
            got = {"find": sorted(r for r in self.rows() if rd not in r[1:3])}
            posts = pairing.Posts(self.cur, extra=self.posts)
            got["at"] = sorted((p, t) for p, t in posts.at.items() if p != rd)
            got["back"] = sorted((i, p.at) for i, p in back.recent_posts(self.cur, now=self.now, since=T0).items() if i != rd)
            got["happenings"] = happening.backfill(self.cur)
            self.cur.execute("ROLLBACK TO SAVEPOINT post_date")
            return got
        before = results()
        self.cur.execute("""INSERT INTO mx_roundups (post_id, source_id, version, basis, roundup, said, why, issue_at)
                            VALUES (%s, %s, 'v', 'b', true, true, 'reading', %s)""", (rd, digest, T0 + 5 * 24 * H))
        self.cur.execute(f"SELECT {pairing.post_date('p')} FROM posts p WHERE id = %s", (rd,))
        self.assertEqual(self.cur.fetchone()[0], T0 + 5 * 24 * H)
        self.assertEqual(results(), before)


# ---- the routes ---------------------------------------------------------------------------------------------------------

from insight_core.tests.test_markx_api import _Api, call   # noqa: E402


class Routes(_Api):
    """The routes read stored rows; none builds a round-up (owner 2026-11-12: never in the API)."""

    def test_issues_settings_and_no_route_builds_a_digest(self):
        status, body = call("GET", "/api/markx/roundups/issues")
        self.assertEqual((status, body["daily"], body["weekly"], body["past"], body["tz_offset_minutes"]),
                         (200, None, None, [], 240))
        self.assertEqual(call("GET", "/api/markx/roundups/issues/999999999")[0], 404)
        self.assertEqual(call("POST", "/api/markx/roundups/settings", body={"tz_offset_minutes": 900})[0], 400)
        self.addCleanup(self.cur.execute, "DELETE FROM mx_settings WHERE key = %s", (units.TZ_KEY,))
        self.assertEqual(call("POST", "/api/markx/roundups/settings", body={"tz_offset_minutes": 180}),
                         (200, {"tz_offset_minutes": 180}))
        self.assertEqual(call("GET", "/api/markx/roundups/settings"), (200, {"tz_offset_minutes": 180}))
        self.assertEqual(call("GET", "/api/markx/roundups/of", query={"posts": str(uuid.uuid4())}),
                         (200, {"roundups": []}))
        self.assertEqual(call("GET", "/api/markx/roundup", query={"span": "day"})[0], 404)


# ---- migration 0123 ----------------------------------------------------------------------------------------------------

@requires_test_db
class Migration(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()

    def test_the_tables_their_checks_and_a_second_run(self):
        self.cur.execute("""SELECT table_name, column_name FROM information_schema.columns
                             WHERE table_name IN ('mx_roundups', 'mx_units', 'mx_attach') ORDER BY 1, 2""")
        cols = {}
        for t, c in self.cur.fetchall():
            cols.setdefault(t, set()).add(c)
        self.assertTrue({"post_id", "source_id", "version", "basis", "roundup", "said", "structured", "read_whole",
                         "why", "adapter", "units", "words", "issue_at"} <= cols["mx_roundups"])
        self.assertTrue({"id", "post_id", "basis", "n", "adapter", "span_start", "span_stop", "links", "text",
                         "headline", "at"} <= cols["mx_units"])
        self.assertTrue({"unit_id", "roundup_id", "target_id", "source", "found_at"} <= cols["mx_attach"])
        sql = (pathlib.Path(units.__file__).resolve().parents[1] / "db/migrations/0123_markx_units.sql").read_text()
        self.cur.execute(sql)                                   # idempotent
        self.cur.execute("SAVEPOINT bad")
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.cur.execute("""INSERT INTO mx_roundups (post_id, source_id, version, basis, roundup, why)
                                VALUES (gen_random_uuid(), gen_random_uuid(), 'v', 'b', false, 'guess')""")
        self.cur.execute("ROLLBACK TO SAVEPOINT bad")
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.cur.execute("""INSERT INTO mx_attach (unit_id, roundup_id, target_id, source)
                                VALUES (-1, gen_random_uuid(), gen_random_uuid(), 'link')""")


if __name__ == "__main__":
    unittest.main()
