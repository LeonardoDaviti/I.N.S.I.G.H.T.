"""Needs attention (0280 I, services/attention.py): the rules over invented health rows, Mark X counts and database
totals; a week's history carried in the answer; a page watch that lands elsewhere; the kept answer served by the API
and refreshed only when due. Invented sources and hosts."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from insight_core.ingestion.kinds.page_watch import lands_elsewhere
from insight_core.services import attention as A
from insight_core.tests._db import db_url, requires_test_db

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


def row(sid, *, kind="generic_rss", status="deferred", outcome="success", error=None, server_error=None,
        last_post=NOW - H, gap=24.0, silent=None, stalled=None, lands_at=None, enabled=True, failures=0,
        address=None, last_success=NOW - H):
    return {"source_id": sid, "display_name": sid.title(), "address": address or f"https://{sid}.example/feed",
            "kind": kind, "enabled": enabled, "status": status, "last_outcome": outcome, "last_error": error,
            "server_error": server_error, "last_post_at": last_post.isoformat() if last_post else None,
            "mean_gap_hours": gap, "silent": silent, "stalled": stalled, "lands_at": lands_at,
            "consecutive_failures": failures, "last_success_at": last_success.isoformat() if last_success else None}


def keys(answer, level=None):
    return [i["key"] for i in answer["items"] if level is None or i["level"] == level]


class Sources(unittest.TestCase):
    def test_a_failing_source_is_counted_with_its_error_and_when_it_last_worked(self):
        rows = [row("feeds", status="backoff", outcome="error", failures=4, last_success=NOW - 16 * H,
                    error="HTTP 502 while fetching https://bridge.example/newest: Bad Gateway",
                    server_error={"status": 502, "site": "bridge.example"}), row("fine")]
        answer = A.build(rows, now=NOW)
        self.assertEqual((answer["count"], keys(answer)), (1, ["source:feeds"]))
        item = answer["items"][0]
        self.assertEqual(item["detail"], "bridge.example answers 502; 4 failures in a row; last worked 16 h ago")
        self.assertEqual(item["since"], (NOW - 16 * H).isoformat())
        self.assertEqual(answer["line"], "Needs attention (1): Feeds: bridge.example answers 502")

    def test_silent_is_listed_not_counted_and_a_disabled_source_is_neither(self):
        rows = [row("quiet", silent={"days": 40, "usual_gap_hours": 48.0}),
                row("off", enabled=False, status="backoff", outcome="error", error="HTTP 500")]
        answer = A.build(rows, now=NOW)
        self.assertEqual((answer["count"], keys(answer, "watch")), (0, ["silent:quiet"]))
        self.assertIsNone(answer["line"])

    def test_a_page_watch_that_lands_elsewhere_is_counted(self):
        answer = A.build([row("lab", kind="page_watch", address="https://lab.example/blog",
                              lands_at="https://lab.example/resources/articles")], now=NOW)
        self.assertEqual(keys(answer, "act"), ["lands:lab"])
        self.assertIn("now lands at https://lab.example/resources/articles", answer["items"][0]["detail"])


class Platforms(unittest.TestCase):
    def test_every_source_of_a_kind_failing_is_one_platform_item(self):
        rows = [row(f"acct{i}", kind="bridge_rss", status="backoff", outcome="error", error="HTTP 503")
                for i in range(3)] + [row("blog")]
        answer = A.build(rows, now=NOW)
        self.assertEqual(keys(answer, "act")[0], "platform:bridge_rss")
        self.assertEqual(answer["count"], 4)   # the platform, then each of its sources

    def test_a_kind_quiet_past_its_busiest_sources_rhythm_is_flagged_and_one_lull_is_not(self):
        quiet = [row(f"chan{i}", kind="chat_rss", last_post=NOW - 30 * H, gap=g) for i, g in enumerate((2.0, 9.0, 50.0))]
        self.assertEqual(keys(A.build(quiet, now=NOW), "act"), ["platform:chat_rss"])
        lull = [row(f"chan{i}", kind="chat_rss", last_post=NOW - 20 * H, gap=g) for i, g in enumerate((2.0, 9.0, 50.0))]
        self.assertEqual(keys(A.build(lull, now=NOW)), [])   # under a day: never a platform

    def test_two_sources_of_a_kind_are_no_platform(self):
        rows = [row(f"acct{i}", kind="bridge_rss", status="backoff", outcome="error", error="HTTP 503") for i in range(2)]
        self.assertNotIn("platform:bridge_rss", keys(A.build(rows, now=NOW)))


class BlockedHosts(unittest.TestCase):
    def test_a_host_that_blocked_within_the_week_stays_listed_after_its_source_recovers(self):
        blocked = row("sub", status="backoff", outcome="error", address="https://forum.example/r/sub",
                      error="HTTP 403 while fetching https://forum.example/r/sub: Blocked")
        first = A.build([blocked], now=NOW)
        self.assertEqual(keys(first, "watch"), ["blocked:forum.example"])   # its source is counted now
        later = A.build([row("sub", address="https://forum.example/r/sub")], now=NOW + 2 * 24 * H, previous=first)
        self.assertEqual(keys(later, "act"), ["blocked:forum.example"])
        self.assertIn("answered 403 to Sub", later["items"][0]["detail"])
        gone = A.build([row("sub")], now=NOW + 8 * 24 * H, previous=first)
        self.assertEqual(keys(gone), [])

    def test_a_rate_limit_in_words_is_a_block_and_a_404_is_not(self):
        self.assertEqual(A.blocked_status(row("a", outcome="error", error="Rate limited by host")), 429)
        self.assertIsNone(A.blocked_status(row("b", outcome="error", error="HTTP 404 while fetching x")))
        self.assertEqual(A.blocked_status(row("c", outcome="error", server_error={"status": 429})), 429)


class MarkX(unittest.TestCase):
    def test_new_failed_tasks_against_a_week_ago_and_the_queue_against_a_days_answers(self):
        markx = {"queue": {"read": {"answered": 900, "failed": 10, "open": 50},
                           "check": {"answered": 100, "failed": 3}},
                 "guides": {"read": "read-v2"}, "answers_day": 1000}
        first = A.build([], now=NOW, markx=markx)
        self.assertEqual(keys(first, "watch"), ["failed:check", "failed:read"])   # no baseline yet: listed
        self.assertEqual(first["count"], 0)
        markx2 = {**markx, "queue": {**markx["queue"], "read": {"answered": 950, "failed": 25, "open": 3000}}}
        later = A.build([], now=NOW + 8 * 24 * H, previous=first, markx=markx2)
        self.assertEqual(keys(later, "act"), ["failed:read", "queue"])
        self.assertEqual(later["items"][0]["title"], "Mark X read (read-v2): 15 new failed tasks")


class Database(unittest.TestCase):
    def test_size_and_the_weeks_costliest_statements_against_the_week_before(self):
        def db(size, ms):
            return {"bytes": size, "statements": {"1": [100, ms], "2": [5, 10.0]}, "texts": {"1": "SELECT  count(*)\n FROM posts"}}

        answer = None
        for day, (size, ms) in enumerate([(100 * 2 ** 30, 1000.0)] + [(100 * 2 ** 30, 1000.0 + 500 * d) for d in range(1, 15)]):
            answer = A.build([], now=NOW + day * 24 * H, previous=answer, database=db(size + day * 2 ** 30, ms))
        info = {i["key"]: i for i in answer["items"] if i["level"] == "info"}
        self.assertIn("+7.0 GB", info["db_size"]["detail"])
        self.assertEqual(info["statement:1"]["title"], "4 s in 0 calls this week (the week before 4 s)")
        self.assertEqual(info["statement:1"]["detail"], "SELECT count(*) FROM posts")
        self.assertLessEqual(len(answer["history"]["days"]), A.KEEP_DAYS)


class LandsElsewhere(unittest.TestCase):
    def test_only_another_page_counts(self):
        self.assertIsNone(lands_elsewhere("https://lab.example/blog", "https://www.lab.example/blog/"))
        self.assertIsNone(lands_elsewhere("http://Lab.example/blog", "https://lab.example/blog"))
        self.assertEqual(lands_elsewhere("https://lab.example/blog", "https://lab.example/resources/articles/"),
                         "https://lab.example/resources/articles")
        self.assertEqual(lands_elsewhere("https://red.example/", "https://red.example/research"),
                         "https://red.example/research")
        self.assertIsNone(lands_elsewhere("https://lab.example/blog", ""))


class _Ops:
    def __init__(self, rows):
        self.rows, self.reads = rows, 0

    def get_source_health(self):
        self.reads += 1
        return {"rows": self.rows}


@requires_test_db
class KeptAnswer(unittest.TestCase):
    """Computed when due by the jobs process, kept in system_settings, served as kept by the API."""

    def setUp(self):
        import psycopg

        self.url = db_url()
        with psycopg.connect(self.url) as conn:
            conn.execute("DELETE FROM system_settings WHERE key = %s", (A.KEY,))
        self.addCleanup(self._clear)

    def _clear(self):
        import psycopg

        with psycopg.connect(self.url) as conn:
            conn.execute("DELETE FROM system_settings WHERE key = %s", (A.KEY,))

    def test_checked_when_due_and_served_kept(self):
        import main
        from types import SimpleNamespace

        from insight_core.services import registry as services_registry
        from insight_core.tests._asgi import call

        previous = services_registry.use(SimpleNamespace(operations=SimpleNamespace(db_url=self.url)))
        self.addCleanup(services_registry.use, previous)
        self.assertEqual(call(main.app, "GET", "/api/operations/attention")[2],
                         {"computed_at": None, "count": 0, "items": [], "line": None})
        ops = _Ops([row("feeds", status="backoff", outcome="error", error="HTTP 500", failures=2)])
        self.assertEqual(A.refresh_if_due(self.url, now=NOW, ops=ops), 1)
        self.assertIsNone(A.refresh_if_due(self.url, now=NOW + 10 * 60 * timedelta(seconds=1), ops=ops))
        self.assertEqual(ops.reads, 1)                                   # not due: nothing read
        self.assertEqual(A.refresh_if_due(self.url, now=NOW + A.EVERY, ops=ops), 1)
        status, _, body = call(main.app, "GET", "/api/operations/attention")
        self.assertEqual((status, body["count"], body["items"][0]["key"]), (200, 1, "source:feeds"))
        self.assertNotIn("history", body)


if __name__ == "__main__":
    unittest.main()
