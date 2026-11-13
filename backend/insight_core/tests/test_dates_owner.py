"""One owner for a post's date (v10.17, issue 0190): Pairing names the four meanings (markx/pairing.py, "the dates"),
and no other module writes a COALESCE of a post's date columns. A grep, no database."""
import re
import unittest
from pathlib import Path

from insight_core.markx import pairing

ROOT = Path(__file__).resolve().parents[1]          # insight_core/
OWNER = ROOT / "markx" / "pairing.py"
# A COALESCE of a post's date columns: two of them as consecutive arguments, an alias or a template's {p} before each,
# over lines (a call split across lines counts). An assignment's COALESCE(%(new)s, published_at, ...) is a write.
_COL = r"(?:\w+\.|\{\w*\}\.?)?(?:surfaced_at|published_at|fetched_at)"
INLINE = re.compile(r"COALESCE\([^()]*?" + _COL + r"\s*,\s*" + _COL + r"\b", re.S)
# The Voice slice's files (built beside v10.17's 0190): their Mark IX times move to pairing.ix_date when it merges.
# The counts are pinned, so a new inline date there fails too.
WAITING = {"db/repo_stories.py": 3, "db/repo_voices.py": 4, "markx/source_stats.py": 2}


def _inline(path: Path) -> int:
    return len(INLINE.findall(path.read_text(encoding="utf-8")))


class NoInlineDates(unittest.TestCase):
    def test_no_module_but_pairing_writes_a_post_date(self):
        found = {}
        for path in sorted(ROOT.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("tests/") or path == OWNER:
                continue
            n = _inline(path)
            if n != WAITING.get(rel, 0):
                found[rel] = n
        self.assertEqual(found, {}, "a post's date is pairing.post_date / ordinary_date / published_date / ix_date "
                                    "(markx/pairing.py, 'the dates'), never an inline COALESCE")

    def test_the_guard_sees_an_inline_date(self):
        self.assertEqual(len(INLINE.findall("WHERE COALESCE(p.surfaced_at,\n p.published_at, p.fetched_at) >= %s")), 1)
        self.assertEqual(len(INLINE.findall("max(COALESCE(published_at, fetched_at))")), 1)
        self.assertEqual(len(INLINE.findall("COALESCE(w.changed_at, p.published_at, p.fetched_at)")), 1)
        self.assertEqual(INLINE.findall("published_at = COALESCE(published_at, %(date)s::timestamptz)"), [])
        self.assertEqual(INLINE.findall("COALESCE(pp.title, p.title), p.published_at, p.fetched_at"), [])
        self.assertEqual(len(INLINE.findall('X = "COALESCE({p}.published_at, {p}.fetched_at)"')), 1)
        self.assertEqual(INLINE.findall('f"published_at = COALESCE(%(published_at)s, {row}published_at,"\n'
                                        '            f" CASE WHEN x THEN {row}fetched_at END)"'), [])


class TheMeanings(unittest.TestCase):
    def test_each_meaning_is_its_order(self):
        self.assertEqual(pairing.ordinary_date("p"), "COALESCE(p.surfaced_at, p.published_at, p.fetched_at)")
        self.assertEqual(pairing.ordinary_date(""), "COALESCE(surfaced_at, published_at, fetched_at)")
        self.assertEqual(pairing.published_date("q"), "COALESCE(q.published_at, q.surfaced_at, q.fetched_at)")
        self.assertEqual(pairing.ix_date(""), "COALESCE(published_at, fetched_at)")
        self.assertEqual(pairing.IX_DATE.format(p="x"), pairing.ix_date("x"))   # the template a .format() reads
        self.assertTrue(pairing.post_date("x").endswith(f", {pairing.ordinary_date('x')})"))
        with self.assertRaises(ValueError):
            pairing.post_date("")   # the issue time is looked up by the post's id

    def test_the_feed_index_still_matches_the_ordinary_date(self):
        """posts_feed_order_idx (0037) is on this exact expression: the feed and the planners use it."""
        sql = ROOT / "db" / "migrations" / "0037_page_change_watching.sql"
        self.assertIn(pairing.ordinary_date(""), sql.read_text(encoding="utf-8"))
        sql = ROOT / "db" / "migrations" / "0130_posts_ix_date.sql"   # and Mark IX's time (0190)
        self.assertIn(f"(({pairing.ix_date('')}) DESC, id DESC)", sql.read_text(encoding="utf-8"))

    def test_a_window_bounds_the_own_date_first(self):
        """post_date_within: the own date within the issue reach (indexed), then the post date (the same rows)."""
        got = pairing.post_date_within("p", "%(lo)s", "%(hi)s")
        reach = int(pairing.POLICIES[pairing.ATTACH].issue_reach.total_seconds())
        self.assertEqual(got, f"({pairing.ordinary_date('p')} >= (%(lo)s) - make_interval(secs => {reach}) AND "
                              f"{pairing.post_date('p')} >= (%(lo)s) AND "
                              f"{pairing.ordinary_date('p')} <= (%(hi)s) + make_interval(secs => {reach}) AND "
                              f"{pairing.post_date('p')} <= (%(hi)s))")
        self.assertEqual(pairing.post_date_within("x", "%s").count("%s"), 2)   # a positional bound: its value twice


if __name__ == "__main__":
    unittest.main()
