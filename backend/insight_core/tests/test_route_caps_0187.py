"""Issue 0187: the expensive routes' caps. A fetch's limit, a search's depth, the runs a minute; one export at a
time is test_export's. No database: every refusal here comes before one is asked."""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

from fastapi import HTTPException
from fastapi.routing import APIRoute

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import main
from insight_core.db.repo_search import MAX_SEARCH_OFFSET, SearchQuery
from insight_core.ingestion.types import MAX_FETCH_LIMIT, FetchRequest, SourceSelector, Trigger
from insight_core.tests._asgi import call

RUN_ROUTES = {"/api/ingestion/run", "/api/sources/{source_id}/fetch-now", "/api/folders/{folder_id}/ingest",
              "/api/archive/{source_id}/run", "/api/archive/{source_id}/queue", "/api/archive/{source_id}/linked",
              "/api/archive/resume-interrupted"}


class FetchLimitTests(unittest.TestCase):
    def test_a_fetch_asks_1_to_max_posts_per_source(self):
        for limit in (None, 1, MAX_FETCH_LIMIT):
            FetchRequest(SourceSelector.all(), Trigger.MANUAL, limit=limit)
        for limit in (0, -1, MAX_FETCH_LIMIT + 1, 10**9, "50", 2.5, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                FetchRequest(SourceSelector.all(), Trigger.MANUAL, limit=limit)

    def test_the_routes_answer_400_before_any_run(self):
        main.run_rate.starts.clear()
        status, _, body = call(main.app, "POST", f"/api/sources/{uuid.uuid4()}/fetch-now", json_body={"limit": 10**6})
        self.assertEqual(status, 400)
        self.assertIn(str(MAX_FETCH_LIMIT), body["detail"])
        status, _, _ = call(main.app, "POST", f"/api/folders/{uuid.uuid4()}/ingest", json_body={"limit": "all"})
        self.assertEqual(status, 400)


class SearchDepthTests(unittest.TestCase):
    def test_a_search_page_is_at_most_max_offset_deep(self):
        self.assertEqual(SearchQuery.parse(q="x", order="best", cursor=str(MAX_SEARCH_OFFSET)).offset, MAX_SEARCH_OFFSET)
        with self.assertRaises(ValueError):
            SearchQuery.parse(q="x", order="best", cursor=str(MAX_SEARCH_OFFSET + 1))

    def test_the_routes_refuse_a_deeper_page(self):
        status, _, _ = call(main.app, "GET", "/api/search", query={"q": "x", "order": "best", "cursor": "99999999"})
        self.assertEqual(status, 400)
        status, _, _ = call(main.app, "GET", "/api/sources/suggested", query={"offset": MAX_SEARCH_OFFSET + 1})
        self.assertEqual(status, 422)


class RunRateTests(unittest.TestCase):
    def test_at_most_n_starts_a_minute_then_429_with_retry_after(self):
        now = [1000.0]
        rate = main.RunRate(per_minute=3, clock=lambda: now[0])
        for _ in range(3):
            rate()
            now[0] += 1
        with self.assertRaises(HTTPException) as refused:
            rate()
        self.assertEqual(refused.exception.status_code, 429)
        self.assertEqual(refused.exception.headers["Retry-After"], "57")
        now[0] = 1060.5   # the first start is a minute old
        rate()
        self.assertEqual(len(rate.starts), 3, "only the last n starts are kept")

    def test_every_run_starting_route_takes_it(self):
        guarded = {route.path for route in main.app.routes if isinstance(route, APIRoute)
                   and any(dep.call is main.run_rate for dep in route.dependant.dependencies)}
        self.assertEqual(guarded, RUN_ROUTES)


if __name__ == "__main__":
    unittest.main()
