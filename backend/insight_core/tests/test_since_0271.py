""""Since you looked" (0271): the reader's one look; News rows begun since it and rows a voice joined since it; each
track's new things (track_brief.since_lines, tested in test_track_briefer_0245). The pure part as a function; the
routes over ASGI with a fake service; the look on the database (rolled back)."""
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

from insight_core.services.news_service import since_rows
from insight_core.tests._db import db_url, requires_db

LOOK = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


def at(hours):
    return LOOK + timedelta(hours=hours)


def row(title, first, *posts):
    """A News row as `news_on` answers it: its lead and lines [(source, hours from the look)], the first the lead."""
    (lead_src, lead_h), *lines = posts
    return {"id": str(uuid.uuid4()), "title": title, "source_display_name": lead_src, "sort_at": at(lead_h),
            "news": {"first_at": at(first)},
            "story": {"posts": [{"id": str(uuid.uuid4()), "title": f"{title} ({s})", "source_display_name": s,
                                 "sort_at": at(h)} for s, h in lines]}}


class PureTests(unittest.TestCase):
    def test_new_and_changed_rows(self):
        rows = [
            row("Began after", 2, ("Lab", 2), ("Paper", 3)),
            row("A voice joined", -10, ("Lab", -10), ("Blog", -9), ("Wire", 1)),
            row("Same voice again", -10, ("Lab", -10), ("Blog", -9), ("Lab", 4)),
            row("Benchmarks joined", -30, ("Lab", -30), ("Blog", -20), ("Bench", 5), ("Tester", 6), ("Bench", 7)),
            row("Quiet", -40, ("Lab", -40), ("Blog", -39)),
        ]
        got = since_rows(rows, LOOK)
        self.assertEqual(got["counts"], {"new": 1, "changed": 2})
        self.assertEqual([r["title"] for r in got["new"]], ["Began after"])
        self.assertEqual([r["title"] for r in got["changed"]], ["Benchmarks joined", "A voice joined"],
                         "the most voices joined first; a later post of a voice already there is no change")
        bench = got["changed"][0]["since"]
        self.assertEqual(bench["voices"], ["Bench", "Tester"])
        self.assertEqual(len(bench["lines"]), 3, "every post of the new voices")

    def test_iso_times_and_the_shown_limit(self):
        rows = [row(f"Row {i}", 1, ("Lab", 1), ("Blog", 2)) for i in range(5)]
        for r in rows:
            r["news"]["first_at"] = r["news"]["first_at"].isoformat()
            r["sort_at"] = r["sort_at"].isoformat()
        got = since_rows(rows, LOOK, shown=2)
        self.assertEqual((got["counts"]["new"], len(got["new"])), (5, 2))
        self.assertEqual([r["title"] for r in got["new"]], ["Row 0", "Row 1"], "News's order")


class FakeNews:
    def __init__(self):
        self.calls = []

    def since(self, when):
        self.calls.append(when)
        return {"look": (when or LOOK).isoformat(), "first": when is None, "tracks": [],
                "news": {"counts": {"new": 0, "changed": 0}, "new": [], "changed": []}}

    def look(self):
        self.calls.append("look")
        return {"before": None, "now": LOOK.isoformat()}


class RouteTests(unittest.TestCase):
    def setUp(self):
        import main
        from insight_core.services import registry
        from insight_core.tests._asgi import call
        self.main, self.call = main, call
        self.news = FakeNews()
        previous = registry.use(SimpleNamespace(news=self.news))
        self.addCleanup(registry.use, previous)

    def test_the_view_reads_and_the_look_writes(self):
        status, _, body = self.call(self.main.app, "GET", "/api/news/since")
        self.assertEqual((status, body["first"], self.news.calls), (200, True, [None]))
        status, _, _ = self.call(self.main.app, "GET", "/api/news/since", query={"at": "2026-11-19T12:00:00Z"})
        self.assertEqual((status, self.news.calls[-1]), (200, datetime(2026, 11, 19, 12, tzinfo=timezone.utc)))
        for bad in ("yesterday", "2026-11-19T12:00:00"):
            self.assertEqual(self.call(self.main.app, "GET", "/api/news/since", query={"at": bad})[0], 400, bad)
        status, _, body = self.call(self.main.app, "POST", "/api/news/since/look")
        self.assertEqual((status, body["now"], self.news.calls[-1]), (200, LOOK.isoformat(), "look"))


@requires_db
class LookTests(unittest.TestCase):
    """The reader's one look in mx_track_seen (no track, no sub-topic): one row, moved by each look."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        self.addCleanup(self.conn.rollback)
        self.cur.execute("DELETE FROM mx_track_seen WHERE track_id IS NULL")

    def test_one_look_moved_each_time(self):
        from insight_core.markx import track_subtopics as TS
        self.assertIsNone(TS.reader_look(self.cur))
        first = TS.look_all(self.cur, now=LOOK)
        self.assertEqual(first, {"before": None, "now": LOOK.isoformat()})
        second = TS.look_all(self.cur, now=at(5))
        self.assertEqual(second["before"], LOOK.isoformat())
        self.assertEqual(TS.reader_look(self.cur), at(5))
        self.cur.execute("SELECT count(*) FROM mx_track_seen WHERE track_id IS NULL")
        self.assertEqual(self.cur.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
