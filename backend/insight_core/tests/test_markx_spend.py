"""Issue 0233 (0216 item 1): an answered task's input is spent (markx/tasks.py spend) only for the kinds nothing reads
once answered. The scan below is the guard: every place the code reads mx_tasks.input is listed with the kinds it
reads and when; a new reader fails it until it is placed (and its kinds kept, if it reads them after the answer).
The rest runs against the run's own _test database; every post is synthetic."""
from __future__ import annotations

import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.markx import embed, repo, tasks
from insight_core.tests.test_markx_api import _Api, call

ROOT = Path(__file__).resolve().parents[1]
READ = re.compile(r'\b[a-z]{1,3}\.input\b(?![_(])|\["input"\]|SELECT[^"\n]*[ ,(]input\b(?!_)|\binput (?:!~|~|IS|LIKE)'
                  r'|length\(input\)')
NOT_TASKS = ("kept_input", "k.input", "st.input")   # kept_pages' inputs, perspectives' own `input()`

# file -> (when the input is read, the kinds read after the answer). "lease": a task being asked or answered (open or
# leased: its input is there); "answer": the answer being recorded (the task is leased until then); "open": open or
# leased tasks only; "after": read after the answer, so these kinds are never spent; "window": ent42's first-window
# test (a spent input of entities/reading is a first window: spend keeps later windows); "short": embed.set_aside's
# short inputs (spend keeps embed inputs of SCAN_CHARS or less); "comment": not a read.
READERS = {
    "markx/reading5.py": ("answer", ()),
    "markx/tasks.py": ("answer", ()),
    "markx/api.py": ("lease", ()),
    "markx/repo.py": ("lease", ()),
    "markx/embed.py": ("short", ()),
    "markx/ent42.py": ("window", ()),
    "markx/source_stats.py": ("after", ("stance",)),
    "markx/track_subtopics.py": ("after", ("subtopics", "subtopic_place")),
    "markx/track_things.py": ("after", ("track_schema", "track_things")),   # 0245: the version line, the window
    "markx/rename.py": ("after", ("rename",)),
    "markx/graph.py": ("after", ("relate", "chain")),
    "markx/identity.py": ("after", ("alias", "alias2", "alias3", "alias4", "collide")),
    "markx/entity_brief.py": ("after", ("collide",)),   # 0274: a brief's sense question read back (never spent)
    "checks/invariants.py": ("open", ()),
}
REASKED = ("join", "pair", "merge", "check", "perspective", "collide", "relate", "chain", "back")   # opened again


class TheReaders(unittest.TestCase):
    def test_every_reader_of_a_task_input_is_placed(self):
        found = set()
        for path in sorted(ROOT.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(("tests/", "scripts/prep")) or "/legacy/" in rel:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if READ.search(line) and not any(n in line for n in NOT_TASKS):
                    found.add(rel)
        self.assertEqual(sorted(found - set(READERS)), [], "a new reader of mx_tasks.input: place it in READERS")

    def test_no_kind_read_or_asked_again_after_its_answer_is_spent(self):
        after = {k for _, kinds in READERS.values() for k in kinds}
        self.assertEqual(sorted((after | set(REASKED)) & set(tasks.SPENDS)), [])


class Spend(_Api):
    def make(self, kind, text, *, days, status="answered"):
        tid, _ = tasks.add(self.cur, kind, text, a=self.post())
        self.cur.execute("UPDATE mx_tasks SET status = %s, answered_at = %s WHERE id = %s",
                         (status, datetime.now(timezone.utc) - timedelta(days=days) if status == "answered" else None,
                          tid))
        return str(tid)

    def test_only_old_answers_of_the_spent_kinds_lose_their_input(self):
        long = "x" * (embed.SCAN_CHARS + 1)
        ids = {
            "entities": self.make("entities", "Title: Widget\nText: one window", days=20),
            "window2": self.make("entities", "Title: Widget\nWindow: 2 of 3 of the post's text (characters 1-9 of 9)\n",
                                 days=20),
            "reading": self.make("reading", "Title: Widget\nAddress: x", days=20),
            "embed_long": self.make("embed", long, days=20),
            "embed_short": self.make("embed", "[Photo]", days=20),
            "read_new": self.make("read", "Title: fresh", days=3),
            "read_open": self.make("read", "Title: open", days=20, status="open"),
            "alias": self.make("alias", "A: one\nB: two", days=20),
            "stance": self.make("stance", "Source: x (site)\n\n[1] a", days=20),
        }
        self.cur.execute("SELECT count(*) FROM mx_counts_delta")
        deltas = self.cur.fetchone()[0]
        spent = tasks.spend_all(_db(), batch=3)   # three rows a batch: the keyset pass crosses batches
        self.assertEqual(spent, 3)
        self.cur.execute("SELECT id::text FROM mx_tasks WHERE input IS NULL")
        self.assertEqual({r[0] for r in self.cur.fetchall()}, {ids["entities"], ids["reading"], ids["embed_long"]})
        self.cur.execute("SELECT count(*) FROM mx_counts_delta")
        self.assertEqual(self.cur.fetchone()[0], deltas, "kind and status unchanged: no count moves")
        self.assertEqual(tasks.spend_all(_db()), 0, "a second pass spends nothing")
        # the same question again is the answered task, found by its hash: never asked again
        again, new = tasks.add(self.cur, "entities", "Title: Widget\nText: one window", a=self.post())
        self.assertEqual((str(again), new), (ids["entities"], False))

    def test_a_late_answer_to_a_spent_task_is_a_repeat(self):
        tid = self.make("read", "Title: spent", days=20)
        tasks.spend_all(_db())
        self.assertIsNone(repo.get_task(self.cur, tid)["input"])
        status, body = self.answer((tid, {"anything": True}))
        self.assertEqual((status, body["stored"], body["repeated"], body["invalid"]), (200, 0, 1, []))


def _db():
    from insight_core.tests._db import db_url
    return db_url()


if __name__ == "__main__":
    unittest.main()
