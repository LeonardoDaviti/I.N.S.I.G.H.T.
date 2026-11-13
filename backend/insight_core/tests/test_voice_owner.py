"""One owner for voices and for "RT by @" (issue 0189): Voice (utils/voice.py) counts voices and Byline
(utils/byline.py) holds Nitter's repost pattern; no other module counts distinct sources by hand or writes the
pattern again. A grep, no database (as tests/test_dates_owner.py for the dates)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # insight_core/
OWNERS = {"utils/voice.py", "utils/byline.py"}
# A voice count by hand: count(DISTINCT <alias.>source_id) in SQL, len({... source/src ...}) in Python.
SQL_COUNT = re.compile(r"count\(\s*DISTINCT\s+(?:\w+\.)?source_id\s*\)", re.I)
PY_COUNT = re.compile(r"len\(\{[^{}]*\b\w*(?:source|src)\w*\b[^{}]*\}\)")
# "RT by @" written as a pattern: a regex (RT by @\w), a LIKE ('RT by @%'), a startswith.
RT = re.compile(r"""RT by @(?:\\w|\(\\w|%)|startswith\(\s*\(?\s*["']RT by @""")
# Counts of sources that are not voices, each said why (a count, not a voice): pinned per file, so a new one fails.
NOT_VOICES = {
    "utils/story_rules.py": 1,       # is_story: 2+ sources (a reposter is one), by design not a voice count
    "markx/entity_repair.py": 1,     # a name's spread over sources (the repair's evidence)
    "db/repo_folders.py": 1,         # a folder's source count
}


def _found(text: str) -> int:
    return len(SQL_COUNT.findall(text)) + len(PY_COUNT.findall(text))


class OneOwner(unittest.TestCase):
    def test_no_module_but_voice_counts_voices(self):
        found = {}
        for path in sorted(ROOT.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("tests/") or rel in OWNERS:
                continue
            n = _found(path.read_text(encoding="utf-8"))
            if n != NOT_VOICES.get(rel, 0):
                found[rel] = n
        self.assertEqual(found, {}, "a voice count is voice.count / voice.count_sql (utils/voice.py), never by hand")

    def test_no_module_but_byline_writes_the_rt_pattern(self):
        found = {}
        for path in sorted(ROOT.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("tests/") or rel in OWNERS:
                continue
            n = len(RT.findall(path.read_text(encoding="utf-8")))
            if n:
                found[rel] = n
        self.assertEqual(found, {}, 'Nitter\'s "RT by @" is byline.RT_BY / RT_BY_TAG / retweet_sql, never by hand')

    def test_the_guard_sees_them(self):
        self.assertEqual(_found("SELECT count(DISTINCT p.source_id) FROM posts p"), 1)
        self.assertEqual(_found("count(distinct source_id)"), 1)
        self.assertEqual(_found("n = len({m.src for m in ms})"), 1)
        self.assertEqual(_found('len({rows[p]["source"] for p in ps})'), 1)
        self.assertEqual(_found("len({p.id for p in ps})"), 0)
        self.assertEqual(_found("count(DISTINCT m.post_id)"), 0)
        self.assertEqual(len(RT.findall(r're.compile(r"^RT by @(\w+): ")')), 1)
        self.assertEqual(len(RT.findall(r're.sub(r"^RT by @\w+:\s*", "", t)')), 1)
        self.assertEqual(len(RT.findall("AND NOT COALESCE(p.title, '') LIKE 'RT by @%%'")), 1)
        self.assertEqual(len(RT.findall('(title or "").startswith("RT by @")')), 1)
        self.assertEqual(RT.findall('"""Nitter\'s "RT by @x: " title."""'), [])


if __name__ == "__main__":
    unittest.main()
