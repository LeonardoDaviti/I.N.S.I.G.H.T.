"""News' two kept views read once (0283): the jobs build the whole page and cut the differences from it, the same
answer as the differences page built apart; the two parts that depend on the other rows (a row's one-release group
and its "came true" links) made again as the cut's own; the members' and the headline inputs' full texts read a
chunk at a time, the same Members and inputs. Invented names; a _test database."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from insight_core.markx import built as B, kept_pages, news, perspectives as P, repo
from insight_core.tests import test_markx_built as built_tests
from insight_core.tests.test_markx_built import D, H
from insight_core.tests.test_markx_folds import read3
from insight_core.tests.test_markx_kept_pages import _World


class Narrowed(unittest.TestCase):

    def test_only_the_links_into_the_world_stay_and_an_untouched_build_is_the_same_dict(self):
        b = {"event_type": "release", "came_true": [{"story": "r1"}, {"story": "r2"}],
             "leaked_before": [{"story": "l1"}]}
        self.assertIs(B.narrowed(b, {"r1", "r2", "l1"}), b)
        got = B.narrowed(b, {"r1"})
        self.assertEqual(got, {"event_type": "release", "came_true": [{"story": "r1"}], "leaked_before": []})
        self.assertEqual(list(got), list(b))                       # the keys keep their order (the page's bytes)
        self.assertEqual(b["came_true"], [{"story": "r1"}, {"story": "r2"}])   # the whole page's build untouched
        self.assertIsNone(B.narrowed(None, set()))


class Released(unittest.TestCase):

    def test_a_row_with_two_stories_of_one_group(self):
        rows = [{"id": "x", "posts": [{"story": "a"}, {"story": "b"}]}, {"id": "y", "posts": [{"story": "a"}]},
                {"id": "z", "posts": [{"story": "c"}, {"story": "d"}]}]
        self.assertEqual(news.released(rows, [["a", "b"], ["c", "e"]]), {"x": ["a", "b"]})
        self.assertEqual(news.released(rows, []), {})


class TheCutsHeadlines(unittest.TestCase):
    """`_differences` names a row again only where the differences' own one-release groups differ."""

    def test_a_row_whose_group_differs_is_named_again_the_others_kept(self):
        rows = [{"id": "x", "tag": "NEW", "posts": [{"story": "a"}, {"story": "b"}]},
                {"id": "y", "tag": "CHANGED", "posts": [{"story": "c"}]},
                {"id": "s", "tag": "SAME", "posts": [{"story": "d"}]}]
        items = [{"id": r["id"], "tag": r["tag"], "headline": {"text": "whole " + r["id"], "from": "haiku"},
                  "built": None} for r in rows]
        asked = []

        def headlines(cur, rows_, *, groups=None):
            asked.append(([r["id"] for r in rows_], groups))
            return {r["id"]: {"text": "apart " + r["id"], "from": "lead title"} for r in rows_}

        whole = [["a", "b", "d"]]                     # the whole page joins a and b through the SAME row's d ...
        with mock.patch.object(news, "release_groups", lambda cur, rows_: []), \
                mock.patch.object(news, "headlines", headlines):   # ... the differences alone join nothing
            got = news._differences(None, items, rows, whole, set())
        self.assertEqual([i["id"] for i in got], ["x", "y"])
        self.assertEqual(asked, [(["x"], [])])
        self.assertEqual(got[0]["headline"], {"text": "apart x", "from": "lead title"})
        self.assertIs(got[1], items[1])                # untouched: the whole page's own item
        self.assertEqual(items[0]["headline"]["text"], "whole x")   # the whole page's item is not changed


class TheWorldOfASubset(built_tests.Stored):
    """build_within's world of a subset is what the subset's own build reads; narrowed to it, a story's build is the
    subset's own, also where the whole build reads a story the subset's never would."""

    def test_the_subsets_world_and_build_are_its_own_builds(self):
        now = datetime.now(timezone.utc)
        r1 = self.post(title="Acme releases Widget 5", at=now - D)
        r2 = self.post(title="Widget 5 is out", at=now - D + H, source=self.other)
        # a leak story whose first post (unread) is 20 days before the release and whose read leaks come 31 days
        # after it: outside the release's window, so the release's own build never reads it
        l0 = self.post(title="Widget 5 hinted", at=now - 20 * D)
        l1 = self.post(title="Widget 5 leaked again", at=now + 30 * D)
        l2 = self.post(title="Rumour: Widget 5 again", at=now + 30 * D + H, source=self.other)
        rel, leak = self.story(r1, r2, at=now - D), self.story(l0, l1, l2, at=now - 20 * D)
        for p in (r1, r2):
            self.read(p, read3())
        for p in (l1, l2):
            self.read(p, read3(event_type="leak_rumour"))
        repo.open_connection(self.cur, a_kind="story", a=leak, b_kind="story", b=rel, relation="development",
                             run_id=self.run, p=0.8, rule="test")
        loaded = []
        load = B._load

        def recorded(cur, ids):
            loaded.extend(ids)
            return load(cur, ids)

        with mock.patch.object(B, "_load", recorded):
            apart = B.build(self.cur, [rel])
        whole, worlds = B.build_within(self.cur, [rel, leak], {"cut": [rel]})
        self.assertEqual(worlds["cut"], set(loaded))
        self.assertEqual(worlds["cut"], {rel})
        self.assertEqual([x["story"] for x in whole[rel]["leaked_before"]], [leak])   # the whole page links it
        self.assertEqual(apart[rel]["leaked_before"], [])                                # the cut's own page doesn't
        self.assertEqual(B.narrowed(whole[rel], worlds["cut"]), apart[rel])
        self.assertEqual(B.build_within(self.cur, [rel, leak])[0], B.build(self.cur, [rel, leak]))


class TheViewsReadOnce(_World):

    def test_the_whole_page_is_read_once_and_each_view_is_its_page_built_apart(self):
        annotate, heads = B.annotate, news.headlines
        calls = {"annotate": 0, "headlines": 0}

        def counted(name, f):
            def g(*a, **k):
                calls[name] += 1
                return f(*a, **k)
            return g
        with mock.patch.object(B, "annotate", counted("annotate", annotate)), \
                mock.patch.object(news, "headlines", counted("headlines", heads)):
            views = news.pages(self.cur, now=self.now)
        self.assertEqual(calls, {"annotate": 1, "headlines": 1})
        self.assertEqual(list(views), ["differences", "all"])
        self.assertEqual([i["id"] for i in views["differences"]["items"]], [self.a])
        self.assertEqual(len(views["all"]["items"]), 2)
        for view, only in news.VIEWS.items():
            self.assertEqual(kept_pages.encode(news.reader_view(views[view])), self.built(only))
        got = self.keep()
        self.assertEqual(got["built"], ["differences", "all"])
        for only in (True, False):
            self.assertEqual(self.current(only), self.built(only))

    def test_one_missing_view_is_built_alone(self):
        self.keep()
        run, st = news.page_inputs(self.cur, self.now)
        self.cur.execute("DELETE FROM mx_kept_pages WHERE page = 'news' AND key = %s", (news._key("differences"),))
        with mock.patch.object(news, "pages", wraps=news.pages) as pages:
            got = self.keep()
        self.assertEqual(got["built"], ["differences"])
        self.assertEqual(pages.call_args.kwargs["views"], ["differences"])
        self.assertEqual(self.current(True), self.built(True))

    def test_chunked_reads_are_the_same_members_and_inputs(self):
        ids = [self.a, self.b]
        whole = P.load_members(self.cur, ids)
        self.assertEqual(sorted(whole), sorted(ids))
        self.assertEqual(P.load_members(self.cur, ids * 2), whole)
        with mock.patch.object(P, "LOAD_CHUNK", 1):
            self.assertEqual(P.load_members(self.cur, ids), whole)
        rows = repo.news_rows(self.cur, news.last_written(self.cur))
        inputs = news.row_headline_inputs(self.cur, rows)
        with mock.patch.object(news, "ROW_CHUNK", 1):
            self.assertEqual(news.row_headline_inputs(self.cur, rows), inputs)
        posts = news._row_posts(self.cur, rows)
        self.assertEqual(inputs, {str(r["id"]): news.row_headline_input(r, posts) for r in rows})
        self.assertTrue(all(inputs.values()))


for _cls in (TheWorldOfASubset,):
    for _name in [n for n in dir(built_tests.Stored) if n.startswith("test")]:   # the seeding base's tests: its module
        setattr(_cls, _name, None)
del _cls, _name


if __name__ == "__main__":
    unittest.main()
