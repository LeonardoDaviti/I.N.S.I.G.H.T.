"""Source health API (spec §F.4, §5.9).

OperationsService.get_source_health over a fake schedule view, a FakeKind registry and a
FixedClock: every row is what cadence_stats + decide_fetch say, the summary buckets are
disjoint and add up to the enabled sources, and the sort puts the worst first. Then the
two routes (a fake OperationsService) and the archive catalog's new fields. No DB, no network.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from types import SimpleNamespace

from fastapi import HTTPException

import main
from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import PolitenessProfile
from insight_core.ingestion.schedule import (
    BACKOFF_DORMANT_AFTER,
    Availability,
    cadence_stats,
    decide_fetch,
)
from insight_core.services import registry as services_registry
from insight_core.services.operations_service import OperationsService
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.tests._asgi import call
from insight_core.tests._ingestion_fakes import FixedClock
from insight_core.tests._kind_fakes import FakeKind

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)

YTDLP = PolitenessProfile(concurrency_pool="ytdlp", requires="ytdlp",
                          cadence_floor=timedelta(hours=168), min_posts_per_fetch=15)


def view_row(source_id: str, *, platform: str = "rss", enabled: bool = True, post_count: int = 5,
             state: FetchStateRow | None = None, override: float | None = None,
             tier: str = "unknown", gap: float | None = None, samples: int = 0,
             settings: dict | None = None, folders: list | None = None) -> dict:
    return {
        "id": source_id,
        "platform": platform,
        "handle_or_url": f"https://test.invalid/{source_id}",
        "enabled": enabled,
        "in_main_digest": True,
        "settings": {"max_posts_per_fetch": 20, "display_name": source_id.title(), **(settings or {})},
        "mean_gap_seconds": gap,
        "cadence_sample_size": samples,
        "cadence_tier": tier,
        "cadence_computed_at": None,
        "fetch_interval_hours_override": override,
        "post_count": post_count,
        "folders": folders or [],
        "state": state,
    }


def state(source_id: str, **kw) -> FetchStateRow:
    return FetchStateRow(source_id=source_id, **kw)


def registry() -> KindRegistry:
    return KindRegistry([
        FakeKind("youtube_channel", YTDLP, matches=lambda s: s.get("platform") == "youtube"),
        FakeKind("generic_rss"),
    ])


AVAILABILITY = Availability(ytdlp_enabled=False, telegram_credentials=False, telegram_reason="no session")


def schedule_view() -> list[dict]:
    return [
        view_row("deferred", state=state("deferred", last_success_at=NOW - H, last_outcome="healthy",
                                         last_fetched_posts=3)),
        view_row("due", state=state("due", last_success_at=NOW - 30 * H, last_outcome="empty")),
        view_row("backoff", state=state("backoff", last_outcome="error", last_error="HTTP 503",
                                        last_error_at=NOW - H, consecutive_failures=2,
                                        next_retry_at=NOW + H)),
        view_row("erroring", state=state("erroring", last_outcome="error", last_error="timeout",
                                         consecutive_failures=BACKOFF_DORMANT_AFTER,
                                         next_retry_at=NOW - H)),
        view_row("tube", platform="youtube", settings={"archive": {"available_posts": 50}},
                 post_count=20),
        view_row("new", post_count=0),
        view_row("off", enabled=False, state=state("off", last_success_at=NOW - 90 * H)),
        view_row("pinned", override=6, tier="medium", gap=86400.0, samples=12,
                 folders=[{"id": "f1", "name": "AI"}],
                 state=state("pinned", last_success_at=NOW - 7 * H, last_outcome="healthy")),
    ]


def make_service(view: list[dict] | None = None) -> OperationsService:
    service = OperationsService("postgresql:///unused", kinds=registry(),
                                availability=lambda: AVAILABILITY, clock=FixedClock(NOW))
    rows = view if view is not None else schedule_view()
    service._load_schedule_view = lambda source_ids=None: [  # type: ignore[method-assign]
        r for r in rows if source_ids is None or r["id"] in source_ids
    ]
    return service


class SourceHealthTests(unittest.TestCase):
    def setUp(self):
        self.service = make_service()
        self.result = self.service.get_source_health()
        self.rows = {r["source_id"]: r for r in self.result["rows"]}

    def test_row_fields_come_from_decide_fetch(self):
        kinds = registry()
        for source in schedule_view():
            with self.subTest(source=source["id"]):
                kind = kinds.resolve(source)
                decision = decide_fetch(cadence_stats(source, source["state"]), kind.profile, NOW,
                                        force=False, availability=AVAILABILITY)
                row = self.rows[source["id"]]
                self.assertEqual(row["kind"], kind.name)
                self.assertEqual(row["interval_hours"], decision.interval.total_seconds() / 3600)
                self.assertEqual(row["interval_basis"], decision.interval_basis)
                if source["enabled"]:
                    self.assertEqual(row["decision"], decision.kind.value)
                    self.assertEqual(row["would_fetch_now"], decision.fetch)
                    expected_due = decision.next_due_at.isoformat() if decision.next_due_at else None
                    self.assertEqual(row["next_due_at"], expected_due)

    def test_row_carries_the_newest_post_time(self):
        view = schedule_view()
        view[0] = {**view[0], "last_post_at": NOW - 5 * H}
        rows = {r["source_id"]: r for r in make_service(view).get_source_health()["rows"]}
        self.assertEqual(rows["deferred"]["last_post_at"], (NOW - 5 * H).isoformat())
        self.assertIsNone(rows["new"]["last_post_at"], "no posts -> None")

    def test_row_carries_the_date_the_source_was_added(self):
        view = schedule_view()
        view[0] = {**view[0], "created_at": NOW - 72 * H}
        rows = {r["source_id"]: r for r in make_service(view).get_source_health()["rows"]}
        self.assertEqual(rows["deferred"]["created_at"], (NOW - 72 * H).isoformat())

    def test_row_shape(self):
        pinned = self.rows["pinned"]
        self.assertEqual(pinned["display_name"], "Pinned")
        self.assertEqual(pinned["interval_basis"], "override")
        self.assertEqual(pinned["override_hours"], 6)
        self.assertEqual(pinned["interval_hours"], 6)
        self.assertEqual(pinned["tier"], "medium")
        self.assertEqual(pinned["mean_gap_hours"], 24)
        self.assertEqual(pinned["folders"], [{"id": "f1", "name": "AI"}])
        self.assertTrue(pinned["would_fetch_now"])
        self.assertEqual(pinned["last_success_at"], (NOW - 7 * H).isoformat())
        self.assertEqual(pinned["last_outcome"], "healthy")

        backoff = self.rows["backoff"]
        self.assertEqual(backoff["decision"], "skip_backoff")
        self.assertEqual(backoff["next_retry_at"], (NOW + H).isoformat())
        self.assertEqual(backoff["consecutive_failures"], 2)
        self.assertEqual(backoff["last_error"], "HTTP 503")
        self.assertFalse(backoff["dormant"])
        self.assertTrue(self.rows["erroring"]["dormant"])

        tube = self.rows["tube"]
        self.assertEqual(tube["decision"], "skip_unavailable")
        self.assertIsNone(tube["next_due_at"])
        self.assertEqual(tube["interval_basis"], "profile_floor")
        self.assertEqual(tube["backlog_posts"], 30, "available 50 - stored 20")
        self.assertIsNone(self.rows["new"]["backlog_posts"], "available unknown -> None, never the plan")
        self.assertEqual(self.rows["new"]["stored_posts"], 0)

        off = self.rows["off"]
        self.assertFalse(off["enabled"])
        self.assertEqual(off["decision"], "skip_disabled")
        self.assertFalse(off["would_fetch_now"])
        self.assertIsNone(off["next_due_at"])

        for row in self.result["rows"]:
            self.assertEqual(set(row) >= {
                "source_id", "display_name", "platform", "kind", "enabled", "in_main_digest", "folders",
                "stored_posts", "backlog_posts", "tier", "mean_gap_hours", "interval_hours",
                "interval_basis", "override_hours", "next_due_at", "would_fetch_now", "decision",
                "last_attempt_at", "last_success_at", "last_outcome", "last_fetched_posts",
                "last_error", "last_error_at", "consecutive_failures", "next_retry_at", "dormant",
                "status",
            }, True, row["source_id"])

    def test_summary_counts_add_up_to_the_enabled_sources(self):
        summary = self.result["summary"]
        self.assertEqual(summary, {"due_now": 3, "deferred": 1, "backoff": 1, "unavailable": 1, "errors": 1})
        enabled = [r for r in schedule_view() if r["enabled"]]
        self.assertEqual(sum(summary.values()), len(enabled))
        self.assertTrue(self.result["success"])
        self.assertEqual(self.result["generated_at"], NOW.isoformat())

    def test_sort_puts_errors_then_backoff_unavailable_due_deferred(self):
        order = [r["source_id"] for r in self.result["rows"]]
        statuses = [r["status"] for r in self.result["rows"]]
        self.assertEqual(statuses, ["error", "backoff", "unavailable", "due", "due", "due", "deferred", "disabled"])
        self.assertEqual(order[0], "erroring")
        self.assertEqual(order[-1], "off")
        # Within "due": the one that has been due longest first.
        self.assertEqual(order[3:6], ["due", "pinned", "new"])

    def test_a_failed_last_attempt_is_an_error_even_with_no_failure_count(self):
        """Mark VIII backfill: last_outcome='error', 0 failures, no retry -> still 'error'."""
        view = [
            view_row("stale", state=state("stale", last_outcome="error", last_error="HTTP 429",
                                          last_error_at=NOW - 240 * H, last_success_at=NOW - 300 * H)),
            view_row("never", state=state("never", last_outcome="error", last_error="HTTP 404",
                                          last_error_at=NOW - 240 * H)),
            view_row("recovered", state=state("recovered", last_outcome="error", last_error="old",
                                              last_error_at=NOW - 300 * H, last_success_at=NOW - 240 * H)),
        ]
        service = make_service(view)
        result = service.get_source_health()
        statuses = {r["source_id"]: r["status"] for r in result["rows"]}
        self.assertEqual(statuses["stale"], "error")
        self.assertEqual(statuses["never"], "error")
        self.assertEqual(statuses["recovered"], "due", "a success after the error clears it")
        self.assertEqual(result["summary"]["errors"], 2)
        self.assertEqual(result["summary"]["due_now"], 1)

    def test_backoff_still_wins_while_a_retry_is_scheduled(self):
        view = [view_row("wait", state=state("wait", last_outcome="error", last_error_at=NOW - H,
                                             consecutive_failures=1, next_retry_at=NOW + H))]
        self.assertEqual(make_service(view).get_source_health()["rows"][0]["status"], "backoff")

    def test_the_status_set_has_one_source(self):
        from insight_core.services.operations_service import (
            EMPTY_SOURCE_HEALTH,
            HEALTH_STATUS_ORDER,
            HealthStatus,
            summarize_health,
        )
        self.assertEqual(HEALTH_STATUS_ORDER, tuple(s.value for s in HealthStatus))
        self.assertEqual(summarize_health([]), EMPTY_SOURCE_HEALTH["summary"])
        self.assertEqual(set(EMPTY_SOURCE_HEALTH["summary"]),
                         {"due_now", "deferred", "backoff", "unavailable", "errors"},
                         "the wire keys are API contract (spec F.4)")

    def test_overview_carries_the_summary_and_the_worst_eight(self):
        many = schedule_view() + [view_row(f"extra{i}", state=state(f"extra{i}", last_success_at=NOW))
                                  for i in range(5)]
        service = make_service(many)
        service.list_recent_jobs = lambda limit=30: []  # type: ignore[method-assign]
        service.get_scheduler_config = lambda: {}  # type: ignore[method-assign]
        service.get_database_counts = lambda: {"total_posts": 1}  # type: ignore[method-assign]
        overview = service.get_operations_overview()
        health = overview["source_health"]
        self.assertEqual(set(health), {"summary", "rows"})
        self.assertEqual(len(health["rows"]), 8)
        self.assertEqual(health["rows"][0]["source_id"], "erroring")
        self.assertEqual(health["summary"]["deferred"], 6)
        self.assertEqual(overview["stats"]["sources_in_error"], 2, "errors + backoff")
        self.assertEqual(overview["stats"]["sources_monitored"], len(many))

    def test_cadence_override_writes_then_returns_the_fresh_row(self):
        written = []

        def write(source_id, hours):
            written.append((source_id, hours))
            view = schedule_view()
            for r in view:
                if r["id"] == source_id:
                    r["fetch_interval_hours_override"] = hours
            self.service._load_schedule_view = lambda source_ids=None: [  # type: ignore[method-assign]
                r for r in view if source_ids is None or r["id"] in source_ids
            ]
            return True

        self.service._write_cadence_override = write  # type: ignore[method-assign]
        row = self.service.set_cadence_override("deferred", 2.0)
        self.assertEqual(written, [("deferred", 2.0)])
        self.assertEqual(row["interval_basis"], "override")
        self.assertEqual(row["override_hours"], 2.0)
        self.assertEqual(row["decision"], "skip_not_due", "fetched 1h ago, due every 2h")
        self.assertEqual(row["next_due_at"], (NOW + H).isoformat())

        self.service._write_cadence_override = lambda source_id, hours: False  # type: ignore[method-assign]
        with self.assertRaises(LookupError):
            self.service.set_cadence_override("missing", None)


S1 = "00000000-0000-4000-8000-000000000001"
MISSING = "00000000-0000-4000-8000-00000000dead"


class FakeOperations:
    def __init__(self):
        self.calls = []

    def get_source_health(self):
        self.calls.append(("get_source_health",))
        return {"success": True, "rows": [], "summary": {}, "generated_at": NOW.isoformat()}

    def set_cadence_override(self, source_id, hours):
        self.calls.append(("set_cadence_override", source_id, hours))
        if source_id == MISSING:
            raise LookupError(f"Source {MISSING} not found")
        return {"source_id": source_id, "override_hours": hours}


def run(coro):
    return asyncio.run(coro)


class SourceHealthRouteTests(unittest.TestCase):
    def setUp(self):
        self.ops = FakeOperations()
        previous = services_registry.use(SimpleNamespace(operations=self.ops))
        self.addCleanup(services_registry.use, previous)

    def put_cadence(self, source_id, payload):
        return call(main.app, "PUT", f"/api/sources/{source_id}/cadence", json_body=payload)

    def test_health_route_returns_the_service_response(self):
        status, _, body = call(main.app, "GET", "/api/sources/health")
        self.assertEqual((status, body["generated_at"]), (200, NOW.isoformat()))

    def test_cadence_route_validates_the_range(self):
        # NaN and infinity are not JSON; the route function itself refuses them.
        for bad in (0, 0.5, 2161, 3000):
            with self.subTest(hours=bad):
                status, _, body = self.put_cadence(S1, {"override_hours": bad})
                self.assertEqual(status, 400, body)
        for bad in (float("nan"), float("inf")):
            with self.subTest(hours=bad):
                with self.assertRaises(HTTPException) as ctx:
                    run(main.set_source_cadence(S1, main.CadenceOverrideRequest(override_hours=bad)))
                self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self.ops.calls, [], "nothing is written for an invalid value")

        for ok in (None, 1, 6.5, 2160):
            with self.subTest(hours=ok):
                status, _, body = self.put_cadence(S1, {"override_hours": ok})
                self.assertEqual((status, body["success"]), (200, True))
                self.assertEqual(self.ops.calls[-1], ("set_cadence_override", S1, ok))

    def test_cadence_route_body_may_omit_the_value(self):
        _, _, body = self.put_cadence(S1, {})
        self.assertIsNone(body["row"]["override_hours"])

    def test_cadence_on_an_unknown_source_is_404(self):
        status, _, body = self.put_cadence(MISSING, {"override_hours": 4})
        self.assertEqual((status, body), (404, {"detail": f"Source {MISSING} not found"}))


class _FakeSourcesService:
    def __init__(self, sources):
        self.sources = sources

    def get_all_sources_with_settings(self):
        return self.sources


class ArchiveCatalogTests(unittest.TestCase):
    def test_entries_carry_kind_backlog_remaining_and_eta(self):
        service = SourceFetchService("postgresql:///unused", kinds=registry())
        service.sources_service = _FakeSourcesService([
            {"id": "a", "platform": "youtube", "handle_or_url": "@a", "enabled": True, "post_count": 10,
             "settings": {"archive": {"available_posts": 40, "stored_posts": 10, "remaining_posts": 25,
                                      "estimated_seconds": 120, "status": "partial"}}},
            {"id": "b", "platform": "rss", "handle_or_url": "https://b", "enabled": True, "post_count": 3,
             "settings": {"archive": {"available_posts": None, "remaining_posts": 99}}},
            {"id": "c", "platform": "rss", "handle_or_url": "https://c", "enabled": False, "post_count": 0,
             "settings": {}},
        ])
        catalog = service.archive_catalog()
        entries = {e["source_id"]: e for e in catalog}
        self.assertEqual(set(entries), {"a", "b"})
        self.assertEqual(entries["a"]["kind"], "youtube_channel")
        self.assertEqual(entries["a"]["backlog_posts"], 30)
        self.assertEqual(entries["a"]["remaining_posts"], 25)
        self.assertEqual(entries["a"]["estimated_seconds"], 120)
        self.assertEqual(entries["b"]["kind"], "generic_rss")
        self.assertIsNone(entries["b"]["backlog_posts"], "available unknown: never the plan's remaining")
        self.assertEqual(entries["b"]["remaining_posts"], 99)
        self.assertIsNone(entries["b"]["estimated_seconds"])


if __name__ == "__main__":
    unittest.main()
