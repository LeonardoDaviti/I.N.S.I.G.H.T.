"""Issue 0076: a post is read once, when it is saved. The parser's parts say what the read-time rules
say (titles, bodies as cut points, quotes, footers); a save writes them; a raw change drops them; the
catch-up parses what has none and writes only what changed."""
from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.utils import post_fields as pf
from insight_core.utils import stamps
from insight_core.utils.post_parser import Body, body_of, parse, parse_stamp, without_quote
from insight_core.utils.post_parts import shown


class CutPointsTests(unittest.TestCase):
    def check(self, raw, want, **expected):
        stored = body_of(raw, want)
        self.assertEqual(shown(raw, stored), want)
        for key, value in expected.items():
            self.assertEqual(getattr(stored, key), value, key)
        return stored

    def test_a_body_as_it_is_needs_no_cut(self):
        self.check("Plain text.", "Plain text.", cut=None, copy=None)
        self.check(None, None, cut=None)

    def test_a_slice_and_spans_deleted(self):
        self.check("Title. Body here", "Body here", cut=[7, 16])
        self.check("<p>A title<br>The body</p> submitted by x", "<p>The body</p>", cut=[0, 3, 14, 26], copy=None)

    def test_codes_decoded_and_a_cut_left_a_line_break(self):
        self.check("say &quot;hi&quot; now", 'say "hi" now', decode_entities=True, copy=None)
        self.check("mine Name (@a) quoted", "mine\nquoted", cut_leaves_break=True, copy=None)

    def test_what_no_cut_says_is_a_copy(self):
        self.check("abc", "xyz", copy="xyz")
        self.check("abc", "", cut=[])


class ParserTests(unittest.TestCase):
    def test_the_parts_say_what_the_read_time_rules_say(self):
        for title, content, html, url in stamps.PARSED:
            parts = parse(title, content, html, url)
            shown_title, text, body = pf.reading_text(title, content, html)
            self.assertEqual(parts.title, shown_title)
            self.assertEqual(parts.title, pf.post_title(title, content, html))
            self.assertEqual(shown(content, parts.text), text)
            self.assertEqual(shown(html, parts.html), body)
            self.assertEqual(parts.quote_only, pf.quote_only(html))
            self.assertEqual(parts.link_target, pf.link_post_target(html))

    def test_a_quote_footer_reply_and_counts(self):
        quote, only, reddit, hn = (parse(*stamps.PARSED[i]) for i in (4, 5, 7, 8))
        self.assertEqual(quote.quoted, "https://x.com/writer_x/status/1900000000000000101")
        self.assertIsNone(quote.quote_only)
        self.assertEqual(quote.folded["html"], without_quote(stamps.PARSED[4][2]))
        self.assertEqual(only.quote_only, quote.quoted)
        self.assertEqual(only.reply_to, "writer_x")
        self.assertEqual((reddit.author, reddit.link_target, reddit.link_kind), ("sample_user", "https://files.example/models/seven", "page"))
        self.assertEqual(hn.counts, {"points": 120, "comments": 45, "chars": 0})

    def test_a_short_reaction_to_a_quote_leads_news_by_what_it_quotes(self):
        reaction = parse(*stamps.PARSED[6])
        self.assertEqual(reaction.subject, "Writer X: Thread on evaluation methods")
        self.assertEqual(reaction.title, "no! really?!", "its row keeps its own words")
        self.assertIsNone(parse(*stamps.PARSED[0]).subject, "no quote")
        words = '<p>Five whole words of mine <a href="https://nitter.local/writer_x/status/1900000000000000101#m">x</a></p>'
        self.assertIsNone(parse("Five whole words of mine", "Five whole words of mine",
                                words + stamps._CARD.split("</p>", 1)[1]).subject, "five words are its own")

    def test_a_quote_of_its_own_account_with_nothing_of_its_own_folds(self):
        self.assertEqual(parse(*stamps.PARSED[5]).folds_into, "https://x.com/writer_x/status/1900000000000000101")
        self.assertIsNone(parse(*stamps.PARSED[4]).folds_into, "words of its own")
        other = stamps.PARSED[5][:3] + ("https://nitter.local/fan_z/status/1900000000000000152#m",)
        self.assertIsNone(parse(*other).folds_into, "another account's tweet")

    def test_a_whole_title_is_cut_where_the_html_ends_a_line_only(self):
        title = "Lab downloaded 145GB models from us without asking"
        text = "Lab downloaded 145 GB of models from us without asking, the logs say."
        self.assertEqual(pf.post_title(title, text, f"<p>{text}</p>"), title, "a number written two ways ends no line")
        glued = "Лимиты выросли за $500Изменения уже действуют."
        self.assertEqual(pf.post_title(glued, "Лимиты выросли за $500 Изменения уже действуют.",
                                       "<p>Лимиты выросли за $500<br>Изменения уже действуют.</p>"), "Лимиты выросли за $500")

    def test_where_the_title_came_from(self):
        self.assertEqual(parse(*stamps.PARSED[0]).title_from, "feed field")
        placeholder = parse(*stamps.PARSED[2])
        self.assertEqual(placeholder.title_from, "first line")
        self.assertIn("title from the first line", placeholder.warnings)

    def test_the_stamp_is_the_parsers_output(self):
        self.assertRegex(parse_stamp(), r"^[0-9a-f]{12}$")


class DatesTests(unittest.TestCase):
    def test_a_date_says_what_it_knows(self):
        from datetime import datetime, timezone
        from insight_core.db.repo_posts import published_precision
        from insight_core.ingestion.kinds.parsing import date_precision
        self.assertEqual(date_precision("2026-11-03"), "date")
        self.assertIsNone(date_precision("Mon, 03 Nov 2026 14:05:00 +0000"), "a time of day: the saver tells it")
        self.assertEqual(date_precision(None), "none")
        noon, midnight = datetime(2026, 11, 3, 12, tzinfo=timezone.utc), datetime(2026, 11, 3, tzinfo=timezone.utc)
        self.assertEqual(published_precision({"date": noon}), "exact")
        self.assertEqual(published_precision({"date": midnight}), "date", "stored as 00:00:00 UTC, as before")
        self.assertEqual(published_precision({"date": noon, "date_precision": "date"}), "date")
        self.assertEqual(published_precision({}), "none")

    def test_an_undated_post_orders_nothing(self):
        from datetime import datetime, timezone
        from insight_core.utils.story_rules import StoryPost
        at = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
        self.assertTrue(StoryPost(id="a", source_id="s", kind="site", own_site="a.test", t=at).trusted_time)
        self.assertFalse(StoryPost(id="a", source_id="s", kind="site", own_site="a.test", t=at, undated=True).trusted_time)


def _db_url():
    return os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")


def _reachable():
    try:
        with psycopg.connect(_db_url(), connect_timeout=5):
            return True
    except Exception:
        return False


@unittest.skipUnless(_db_url() and _db_url().rsplit("/", 1)[-1].endswith("_test") and _reachable(), "a _test database")
class StoredPartsTests(unittest.TestCase):
    def setUp(self):
        from insight_core.db.repo_post_parts import catch_up
        self.catch_up = catch_up
        self.ids = []
        with psycopg.connect(_db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO sources (platform, handle_or_url) VALUES ('telegram', %s) RETURNING id",
                        (f"https://tg.bridge.example/rss/parts_{uuid.uuid4().hex[:8]}",))
            self.source = str(cur.fetchone()[0])
            for title, content, html, _ in stamps.PARSED[:3]:
                cur.execute("INSERT INTO posts (source_id, url, title, content, content_html) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                            (self.source, f"https://t.me/parts/{uuid.uuid4().hex}", title, content, html))
                self.ids.append(str(cur.fetchone()[0]))

    def tearDown(self):
        with psycopg.connect(_db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sources WHERE id = %s", (self.source,))

    def parts(self):
        with psycopg.connect(_db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT post_id::text, title, digest FROM post_parts WHERE post_id = ANY(%s::uuid[])", (self.ids,))
            return {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    def test_the_catch_up_parses_what_has_no_parts_once(self):
        self.catch_up(_db_url())
        parts = self.parts()
        self.assertEqual(set(parts), set(self.ids))
        self.assertEqual(parts[self.ids[1]][0], "Lab Model Seven вышла")
        self.assertEqual(self.catch_up(_db_url())["written"], 0)

    def test_a_raw_change_drops_the_parts_and_a_save_writes_them(self):
        from insight_core.db.repo_post_parts import PostPartsRepository
        self.catch_up(_db_url())
        with psycopg.connect(_db_url()) as conn, conn.cursor() as cur:
            cur.execute("UPDATE posts SET title = 'Another title for it' WHERE id = %s", (self.ids[0],))
            cur.execute("SELECT count(*) FROM post_parts WHERE post_id = %s", (self.ids[0],))
            self.assertEqual(cur.fetchone()[0], 0)
            self.assertEqual(PostPartsRepository.write(cur, self.ids), 1, "only the post without parts is written")
        self.assertEqual(self.parts()[self.ids[0]][0], "Another title for it")


if __name__ == "__main__":
    unittest.main()
