"""Series (issue 0134): the rule (utils/series.py, the lab's frozen series_v1 with the five fixes) on fixed texts,
then the pass (db/repo_series.py): storage, navigation marked in post_refs, the incremental update, the post page's
Series line and Connected's navigation rows, the invariant. Synthetic data only; the DB tests roll back."""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.checks import invariants
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_post_refs import PostRefsRepository
from insight_core.db.repo_series import SeriesRepository
from insight_core.db.repo_stories import StoriesRepository
from insight_core.tests._db import db_url, insert_scratch_source, requires_db
from insight_core.utils import series
from insight_core.utils.series import NavLink, Post
from insight_core.utils.url_normalization import normalize_url

T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def P(n, title, day, kind="site", head=""):
    return Post(f"p{n}", T0 + day * DAY, title, head, kind)


def groups(posts, links=()):
    return [(g.kind, [m for m in g.members], [g.numbers[m] for m in g.members]) for g in series.build(posts, links)]


class Markers(unittest.TestCase):
    def m(self, title, kind="site"):
        got = series.marker(Post("x", T0, title, "", kind))
        return got and (got.style, got.label, got.total, got.stem)

    def test_part_style_in_english_and_russian(self):
        self.assertEqual(self.m("Writing a compiler from scratch, part 28"),
                         ("P", "28", None, "writing a compiler from scratch"))
        self.assertEqual(self.m("Что происходит на рынке — часть 3"), ("P", "3", None, "что происходит на рынке"))
        self.assertEqual(self.m("Part two: the scheduler"), ("P", "2", None, "the scheduler"))
        self.assertEqual(self.m("Глава 4: о планировщике")[:2], ("P", "4"))
        self.assertEqual(self.m("A long road, pt. 3")[:2], ("P", "3"))
        self.assertEqual(self.m("Why the weights win? Part IV")[:2], ("P", "4"))
        self.assertEqual(self.m("A thread on caches (2/5)")[:3], ("F", "2", 5))
        self.assertEqual(self.m("Разбор отчёта 2/3")[:3], ("F", "2", 3))

    def test_issue_style(self):
        self.assertEqual(self.m("Weekly digest #136")[:2], ("K", "136"))
        self.assertEqual(self.m("Дайджест, выпуск 12")[:2], ("K", "12"))
        self.assertEqual(self.m("The Letter No. 7")[:2], ("K", "7"))

    def test_not_a_marker(self):
        self.assertIsNone(self.m("We spent 3/4 of the budget on parts of the plan"))
        self.assertIsNone(self.m("A part 2 of something in the middle of words"))
        self.assertIsNone(self.m("Price: 5/2 split"))

    def test_fix_5_no_cap_and_a_letter(self):
        self.assertEqual(self.m("Writing a compiler, part 31")[:2], ("P", "31"))
        self.assertEqual(self.m("Writing a compiler, part 32a")[:2], ("P", "32a"))
        self.assertEqual(self.m("Writing a compiler, part 140")[:2], ("P", "140"))

    def test_fix_2_on_x_only_at_the_start(self):
        self.assertIsNone(self.m("A shop is promoting the Algebra book Part II, go read it", kind="x"))
        self.assertIsNone(self.m("R to @someone: the book, Part II", kind="x"))
        self.assertEqual(self.m("Part 2: why caches miss", kind="x")[:2], ("P", "2"))
        self.assertEqual(self.m("R to @someone: 2/4 the second reason", kind="x")[:3], ("F", "2", 4))
        # elsewhere a marker at the end counts
        self.assertEqual(self.m("A shop is promoting the Algebra book, Part II")[:2], ("P", "2"))


class Groups(unittest.TestCase):
    def test_e1_numbered_titles_one_series(self):
        posts = [P(1, "Writing a compiler from scratch, part 28", 0), P(2, "Writing a compiler from scratch, part 29", 9),
                 P(3, "Writing a compiler from scratch, part 30", 20), P(4, "Something else entirely", 5)]
        self.assertEqual(groups(posts), [("series", ["p1", "p2", "p3"], ["28", "29", "30"])])

    def test_e1_russian_series(self):
        posts = [P(1, "Что происходит в канале - часть 3", 0), P(2, "Что происходит в канале - часть 4", 2)]
        self.assertEqual(groups(posts), [("series", ["p1", "p2"], ["3", "4"])])

    def test_two_different_stems_are_two_series(self):
        posts = [P(1, "Caches, part 1", 0), P(2, "Caches, part 2", 1), P(3, "Schedulers, part 1", 2),
                 P(4, "Schedulers, part 2", 3)]
        self.assertEqual(sorted(g[1] for g in groups(posts)), [["p1", "p2"], ["p3", "p4"]])

    def test_a_looser_stem_needs_the_posts_near(self):
        near = [P(1, "Notes on the new scheduler design, part 1", 0), P(2, "Notes on the scheduler, part 2", 2)]
        far = [P(1, "Notes on the new scheduler design, part 1", 0), P(2, "Notes on the scheduler, part 2", 20)]
        self.assertEqual(len(groups(near)), 1)
        self.assertEqual(groups(far), [])

    def test_runs_of_short_stem_titles(self):
        run = [P(n, f"PPA {n}: something about it {n}", n) for n in (7, 8, 9)]
        self.assertEqual(groups(run), [("series", ["p7", "p8", "p9"], ["7", "8", "9"])])
        self.assertEqual(groups(run[:2]), [], "two are no run")

    def test_e2_a_navigation_link(self):
        posts = [P(1, "How the planner works", 0), P(2, "Picking it up again", 5)]
        self.assertEqual(groups(posts, [NavLink("p2", "https://b.test/1", "previous part", "p1")]),
                         [("series", ["p1", "p2"], [None, None])])
        # a bare "previous post" is weak: no group alone
        self.assertEqual(groups(posts, [NavLink("p2", "https://b.test/1", "previous post", "p1")]), [])
        # a roundup linking "Part 2" is not itself a part
        self.assertEqual(groups(posts, [NavLink("p2", "https://b.test/1", "Part 2", "p1")]), [])

    def test_e3_a_shared_start_stored_or_not(self):
        posts = [P(2, "Разбор отчёта, продолжение", 0), P(3, "Ещё про отчёт", 1), P(4, "Unrelated", 2)]
        links = [NavLink("p2", "https://t.test/chan/1766", "начало"), NavLink("p3", "https://t.test/chan/1766/", "Начало")]
        self.assertEqual(groups(posts, links), [("series", ["p2", "p3"], [None, None])])

    def test_the_owners_case_parts_2_3_4_with_part_1_unstored(self):
        posts = [P(2, "Отчёт компании, часть 2", 0), P(3, "Отчёт компании, часть 3", 1),
                 P(4, "Отчёт компании, часть 4", 2), P(5, "A follow-up on the report", 3)]
        links = [NavLink(f"p{n}", "https://t.test/other/1766", "начало") for n in (2, 3, 4)]
        self.assertEqual(groups(posts, links), [("series", ["p2", "p3", "p4"], ["2", "3", "4"])])

    def test_fix_1_no_x_self_reply_threads(self):
        posts = [P(1, "R to @me: and another thing", 0, "x"), P(2, "R to @me: and one more", 0.001, "x"),
                 P(3, "R to @me: last one", 0.002, "x")]
        self.assertEqual(groups(posts), [])

    def test_fix_2_a_promoted_books_part_is_no_series_on_x(self):
        posts = [P(1, "Shop promotes the Algebra book Part I today", 0, "x"),
                 P(2, "More on the Algebra book Part II from the shop", 3, "x")]
        self.assertEqual(groups(posts), [])

    def test_fix_3_the_unmarked_first_post_titled_with_the_stem_is_part_1(self):
        posts = [P(1, "Why do the weights beat mine?", 0), P(2, "Why do the weights beat mine? Part two", 10),
                 P(3, "Why do the weights beat mine? Part three", 20),
                 P(4, "Why do the weights beat mine?", 30)]   # after part 2: not part 1
        self.assertEqual(groups(posts), [("series", ["p1", "p2", "p3"], ["1", "2", "3"])])

    def test_fix_4_sixty_days_between_parts(self):
        self.assertEqual(len(groups([P(1, "Object detection, part 1", 0), P(2, "Object detection, part 2", 47)])), 1)
        self.assertEqual(len(groups([P(1, "Object detection, part 1", 0), P(2, "Object detection, part 2", 59)])), 1)
        self.assertEqual(groups([P(1, "Object detection, part 1", 0), P(2, "Object detection, part 2", 75)]), [])
        # a long series joins part by part
        chain = [P(n, f"Object detection, part {n}", 50 * n) for n in range(1, 5)]
        self.assertEqual(len(groups(chain)), 1)

    def test_fix_5_parts_past_30_and_lettered_parts(self):
        posts = [P(n, f"Writing a compiler, part {lab}", n) for n, lab in ((1, "31"), (2, "32a"), (3, "34a"), (4, "34b"))]
        self.assertEqual(groups(posts), [("series", ["p1", "p2", "p3", "p4"], ["31", "32a", "34a", "34b"])])


class Kinds(unittest.TestCase):
    def test_part_style_is_a_series(self):
        self.assertEqual(groups([P(1, "Caches, part 1", 0), P(2, "Caches, part 2", 1)])[0][0], "series")

    def test_issue_style_running_long_is_a_column(self):
        posts = [P(n, f"Дайджест #{100 + n}", 7 * n) for n in range(12)]
        self.assertEqual(groups(posts)[0][0], "column")
        posts = [P(n, f"The Letter No. {n}", 30 * n) for n in range(1, 4)]   # 60+ days, 3 members
        self.assertEqual(groups(posts)[0][0], "column")

    def test_short_issue_style_defaults_to_series(self):
        self.assertEqual(groups([P(1, "Basics of composites #2", 0), P(2, "Basics of composites #3", 5)])[0][0], "series")

    def test_an_issue_stem_that_recurs_is_a_column(self):
        posts = [P(1, "Hack night #1", 0), P(2, "Hack night #2", 5), P(3, "Hack night #3", 300), P(4, "Hack night #4", 305)]
        got = groups(posts)
        self.assertEqual([g[0] for g in got], ["column", "column"])


class Shapes0137(unittest.TestCase):
    """Issue 0137 B6: "#N." and "Name N Title" when the stem recurs with rising numbers; the stem is the segment next
    to the number, a guest's name before or after it is not part of it."""

    def m(self, title, kind="site"):
        got = series.marker(Post("x", T0, title, "", kind))
        return got and (got.style, got.label, got.stem)

    def test_a_number_followed_by_a_full_stop_is_a_marker(self):
        self.assertEqual(self.m("Dull Podcast #34. Guest Person and the long talk"), ("K", "34", "dull podcast"))
        self.assertEqual(self.m("Another Guest on everything. Dull Podcast #36."), ("K", "36", "dull podcast"))
        self.assertIsNone(self.m("Version #3.5 of the tool"), "a decimal is no marker")

    def test_the_stem_is_the_segment_next_to_the_number(self):
        self.assertEqual(self.m("Antitrainer. Some Guest. Dull Podcast #42"), ("K", "42", "dull podcast"))
        self.assertEqual(self.m("Dull Podcast #41. Other Guest"), ("K", "41", "dull podcast"))
        self.assertEqual(self.m("Weekly digest #136")[2], "weekly digest")

    def test_an_episodes_guest_names_do_not_split_the_show(self):
        posts = [P(34, "Dull Podcast #34. Guest One talks", 0), P(36, "Guest Two on maps. Dull Podcast #36.", 14),
                 P(41, "Dull Podcast #41. Guest Three", 49), P(42, "Antitrainer. Guest Four. Dull Podcast #42", 56)]
        got = groups(posts)
        self.assertEqual([(g[1], g[2]) for g in got], [(["p34", "p36", "p41", "p42"], ["34", "36", "41", "42"])])

    def test_name_number_title_with_rising_numbers_is_a_column(self):
        posts = [P(n, f"Newsletter {480 + n} {title}", 7 * n)
                 for n, title in enumerate(("Markets and the vote", "The jobs report", "Rates", "A long week"))]
        self.assertEqual(groups(posts), [("column", ["p0", "p1", "p2", "p3"], ["480", "481", "482", "483"])])
        links = [P(n, f"Top Links {1264 + 3 * n} on the week", 2 * n) for n in range(4)]
        self.assertEqual(groups(links)[0][2], ["1264", "1267", "1270", "1273"])

    def test_name_number_needs_three_rising(self):
        self.assertEqual(groups([P(1, "Newsletter 480 Rates", 0), P(2, "Newsletter 481 Jobs", 7)]), [], "two are no run")
        falling = [P(n, f"Newsletter {500 - n} Rates", 7 * n) for n in range(3)]
        self.assertEqual(groups(falling), [], "numbers falling with the dates")

    def test_name_number_false_positives_stay_out(self):
        self.assertEqual(groups([P(1, "Top 10 tips for sleep", 0), P(2, "Top 5 books of the month", 5),
                                 P(3, "Top 20 cities to visit", 9)]), [], "not rising with the dates")
        self.assertEqual(groups([P(1, "Phone 15 review", 0), P(2, "Phone 15 battery", 3), P(3, "Phone 16 leaks", 9)]), [],
                         "a product's version: one number twice is no issue run")
        self.assertEqual(groups([P(1, "Election 2024 results", 0), P(2, "Election 2025 recap", 200),
                                 P(3, "Election 2026 preview", 400)]), [], "years")
        self.assertEqual(groups([P(1, "On 12 May the vote", 0), P(2, "On 3 June the count", 20),
                                 P(3, "On 30 June the result", 30)]), [], "dates")


class Navigation(unittest.TestCase):
    def test_both_ends_in_one_group_or_navigation_words(self):
        posts = [P(1, "Caches, part 1", 0), P(2, "Caches, part 2", 1), P(3, "Something else", 2)]
        gs = series.build(posts)
        got = series.navigation(gs, [("p2", "a1", "p1", "see the first one"),     # both in the series
                                     ("p3", "a2", "p1", "previous post"),         # navigation words
                                     ("p3", "a3", "p2", "a good read"),            # neither
                                     ("p2", "a4", None, "previous part")])        # not a stored post
        self.assertEqual(got, {("p2", "a1"), ("p3", "a2")})

    def test_link_words_by_address(self):
        html = ('<p>See <a href="/2026/05/part-one">the previous part</a> and '
                '<a href="https://o.test/x?utm_source=y">a page</a></p>')
        self.assertEqual(series.link_words(html, None, "https://b.test/2026/06/part-two"),
                         [("https://b.test/2026/05/part-one", "https://b.test/2026/05/part-one", "the previous part"),
                          ("https://o.test/x", "https://o.test/x?utm_source=y", "a page")])

    def test_navigation_links_are_link_words_navigation_entries(self):
        """0199: the pass's fast read keeps exactly link_words' entries with navigation words, a text holding a marker
        character of its own too (read the long way), and none when no link's words are navigation."""
        base = "https://b.test/2026/06/part-two"
        cases = [
            '<p>See <a href="/2026/05/part-one">the previous part</a> and <a href="/x">a page</a>, '
            '<a href="/2026/05/part-one">part 1</a></p>',
            '<p><a href="/a">a page</a> and <a href="mailto:x@y.z">previous part</a> <a href="/b">Part 2</a></p>',
            '<p>No navigation: <a href="/a">one</a>, <a href="/b">two</a></p>',
            '<p>A stray \ue0003\ue001 marker <a href="/a">previous part</a></p>',
            None,
        ]
        for html in cases:
            want = [e for e in series.link_words(html, "plain https://b.test/c previous part", base)
                    if series.is_navigation(e[2])]
            self.assertEqual(series.navigation_links(html, "plain https://b.test/c previous part", base), want)
        self.assertEqual(series.navigation_links(cases[2], None, base), [])


@requires_db
class ThePass(unittest.TestCase):
    """The story job's pass: storage, keep everything, navigation marked, the line and Connected, the invariant."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.mark = uuid.uuid4().hex[:8]
        self.now = datetime.now(timezone.utc)
        self.mine = insert_scratch_source(self.cur, platform="telegram")
        self.other = insert_scratch_source(self.cur)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _post(self, title, days_ago, html="<p>words</p>", source=None, slug=None):
        url = f"https://{self.mark}.test/{slug or uuid.uuid4().hex}"
        self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, title, content, content_html, published_at)
                            VALUES (%s, %s, %s, %s, 'words', %s, %s) RETURNING id""",
                         (source or self.mine, url, normalize_url(url), title, html, self.now - timedelta(days=days_ago)))
        post = str(self.cur.fetchone()[0])
        StoriesRepository().save_post_links(self.cur, post)
        return post

    def _url(self, post):
        self.cur.execute("SELECT url FROM posts WHERE id = %s", (post,))
        return self.cur.fetchone()[0]

    def run_pass(self, now=None):
        return SeriesRepository.run(self.cur, now or self.now, sources=[self.mine])

    def open_series(self):
        self.cur.execute("""SELECT s.kind, s.name, array_agg(sp.post_id::text ORDER BY sp.position),
                                   array_agg(sp.number ORDER BY sp.position)
                              FROM series s JOIN series_posts sp ON sp.series_id = s.id
                             WHERE s.source_id = %s AND s.valid_to IS NULL GROUP BY s.id ORDER BY s.first_at""", (self.mine,))
        return self.cur.fetchall()

    def nav(self, post):
        self.cur.execute("SELECT target_address, navigation FROM post_refs WHERE post_id = %s ORDER BY position", (post,))
        return self.cur.fetchall()

    def test_stored_marked_and_shown(self):
        p2 = self._post("Отчёт компании, часть 2", 3)
        p3 = self._post("Отчёт компании, часть 3", 2, html=f'<p><a href="https://t.test/x/1">начало</a></p>')
        other = self._post("A reply from someone else", 1, source=self.other)
        p4 = self._post("Отчёт компании, часть 4", 1,
                        html=f'<p>Back to <a href="{self._url(p3)}">the last one</a> and '
                             f'<a href="{self._url(other)}">a reply that argues the other way, worth reading</a></p>')
        counts = self.run_pass()
        self.assertEqual((counts["opened"], counts["closed"]), (1, 0))
        self.assertEqual(self.open_series(), [("series", "Отчёт компании", [p2, p3, p4], ["2", "3", "4"])])
        self.assertEqual(self.nav(p4), [(normalize_url(self._url(p3)), True), (normalize_url(self._url(other)), False)])
        # the line: Part 3 of 4, prev and next
        line = SeriesRepository.line(self.cur, p3)
        self.assertEqual((line["kind"], line["name"], line["number"], line["total"], line["count"]),
                         ("series", "Отчёт компании", "3", 4, 3))
        self.assertEqual((line["prev"]["post_id"], line["next"]["post_id"]), (p2, p4))
        self.assertEqual([p["current"] for p in line["parts"]], [False, True, False])
        self.assertIsNone(SeriesRepository.line(self.cur, other))
        # Connected: the navigation row is under the Series line, not Earlier / Later; the other source's stays
        found = PostRefsRepository.connected(self.cur, p4)
        self.assertEqual([r["post_id"] for r in found["earlier"]], [other])
        self.assertEqual([(r["post_id"], r["group"]) for r in found["navigation"]], [(p3, "earlier")])
        self.assertEqual(found["series"]["number"], "4")
        found = PostRefsRepository.connected(self.cur, p3)
        self.assertEqual((found["later"], [r["post_id"] for r in found["navigation"]]), ([], [p4]))
        # the invariant
        check, = [i for i in invariants.INVARIANTS if i.name == "series.source_posts"]
        bad, of = check.count(invariants.Run("", self.cur, self.now))
        self.assertEqual(bad, [])
        self.assertGreaterEqual(of, 3)

    def test_a_same_source_navigation_link_outside_a_series(self):
        first = self._post("How the planner works", 30)
        later = self._post("Some news today", 1, html=f'<p><a href="{self._url(first)}">previous post</a></p>')
        self.run_pass()
        self.assertEqual(self.open_series(), [])    # a weak link makes no group
        self.assertEqual(self.nav(later), [(normalize_url(self._url(first)), True)])
        self.assertEqual(PostRefsRepository.connected(self.cur, later)["earlier"], [])

    def test_incremental_unchanged_left_changed_closed_never_deleted(self):
        p1 = self._post("Caches, part 1", 3)
        p2 = self._post("Caches, part 2", 2)
        self.run_pass()
        self.cur.execute("SELECT id FROM series WHERE source_id = %s", (self.mine,))
        first = self.cur.fetchall()
        again = {key: value for key, value in self.run_pass().items() if key != "seconds"}   # its clock varies
        self.assertEqual((again["opened"], again["closed"]), (0, 0))   # nothing changed: left
        self.cur.execute("SELECT id FROM series WHERE source_id = %s", (self.mine,))
        self.assertEqual(self.cur.fetchall(), first)
        p3 = self._post("Caches, part 3", 1)
        counts = self.run_pass(self.now + timedelta(minutes=1))
        self.assertEqual((counts["opened"], counts["closed"]), (1, 1))
        self.assertEqual(self.open_series(), [("series", "Caches", [p1, p2, p3], ["1", "2", "3"])])
        self.cur.execute("SELECT count(*), count(valid_to) FROM series WHERE source_id = %s", (self.mine,))
        self.assertEqual(self.cur.fetchone(), (2, 1))

    def test_the_sources_read_again(self):
        self._post("Caches, part 1", 3)
        self.assertIn(self.mine, SeriesRepository.dirty_sources(self.cur, self.now - timedelta(minutes=5)))
        self.cur.execute("UPDATE posts SET created_at = now() - interval '2 days', updated_at = now() - interval '2 days', "
                         "refs_scanned_at = now() - interval '2 days' WHERE source_id = %s", (self.mine,))
        self.assertNotIn(self.mine, SeriesRepository.dirty_sources(self.cur, datetime.now(timezone.utc) - timedelta(days=1)))

    def test_the_whole_pass_keeps_its_clock(self):
        self._post("Caches, part 1", 3)
        self._post("Caches, part 2", 2)
        # the last pass five minutes ago: only the sources changed since are read (this one)
        SystemSettingsRepository.upsert(self.cur, "series", {"version": series.VERSION,
                                                             "since": (self.now - timedelta(minutes=5)).isoformat()})
        counts = SeriesRepository.run(self.cur, self.now)
        self.assertGreaterEqual(counts["opened"], 1)
        self.assertEqual(len(self.open_series()), 1)
        self.cur.execute("SELECT value->>'since' FROM system_settings WHERE key = 'series'")
        self.assertEqual(self.cur.fetchone()[0], self.now.isoformat())


if __name__ == "__main__":
    unittest.main()
