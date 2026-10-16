"""Telegram MTProto source kind (spec §B8, §D.2): all fakes, no network, no Telethon session.

The kind is built with a FakeTelegramClient factory, a FakeRunLock session lock,
FakeHttp(sleep=RecordingSleeper()) and a FixedClock. Runner tests go through the real
IngestionRunner with the in-memory ports, so the session lifecycle, the unavailable
reasons and the flood-wait rule are checked where they matter: in a fetch run.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.credentials import MappingCredentials
from insight_core.ingestion.gates import HOST_FLOORS, FetchGates
from insight_core.ingestion.inspection import DbInspectionRefresher
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import KindSession, KindUnavailable, NullKindSession, PolitenessProfile
from insight_core.ingestion.kinds.telegram_mtproto import (
    MAX_INLINE_FLOOD_WAIT_S,
    TELEGRAM_HOST_KEY,
    TelegramKind,
    synthesize_posts,
)
from insight_core.ingestion.kinds.telegram_session import (
    TelegramChannelError,
    TelegramFloodWait,
    translate_telethon_error,
)
from insight_core.ingestion.runner import IngestionRunner
from insight_core.ingestion.schedule import (
    Availability,
    DecisionKind,
    availability_from_env,
    cadence_stats,
    decide_fetch,
)
from insight_core.ingestion.types import FetchRequest, OutcomeStatus, SourceSelector, Trigger
from insight_core.services.operations_service import health_row
from insight_core.tests._ingestion_fakes import (
    FakeRunLock,
    FixedClock,
    InMemoryFetchStateStore,
    InMemoryPostSaver,
    InMemorySourceCatalog,
    RecordingInspectionRefresher,
    SpyFetchGates,
)
from insight_core.tests._kind_fakes import FakeHttp, FakeKind, RecordingSleeper

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
TG_ON = Availability(ytdlp_enabled=True, telegram_credentials=True)


# --------------------------------------------------------------------------- fakes


def msg(id: int, text: str | None = "post", *, grouped_id: int | None = None, media: bool = False,
        date: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=id, text=text, grouped_id=grouped_id, media=object() if media else None,
                           date=date or NOW - timedelta(minutes=id))


class FakeMessages(list):
    """Telethon's TotalList: a list with the channel's message count in .total."""

    def __init__(self, items, total):
        super().__init__(items)
        self.total = total


def channel(newest_id: int, count: int | None = None) -> list[SimpleNamespace]:
    """Text messages newest first, ids newest_id .. newest_id - count + 1."""
    count = newest_id if count is None else count
    return [msg(i, f"post {i}", date=NOW - timedelta(hours=newest_id - i)) for i in range(newest_id, newest_id - count, -1)]


class FakeTelegramClient:
    def __init__(self, *, authorised: bool = True, channels: dict | None = None,
                 entity_errors: dict | None = None, message_errors: dict | None = None):
        self.authorised = authorised
        self.channels = channels or {}
        self.entity_errors = entity_errors or {}
        # handle -> list of exceptions (or None) raised by successive get_messages calls
        self.message_errors = {k: list(v) for k, v in (message_errors or {}).items()}
        self.calls: list[tuple] = []

    async def connect(self):
        self.calls.append(("connect",))

    async def disconnect(self):
        self.calls.append(("disconnect",))

    async def is_user_authorized(self):
        self.calls.append(("is_user_authorized",))
        return self.authorised

    # The interactive Telethon API: the server must never reach it.
    async def start(self, *a, **k):  # pragma: no cover - asserted never called
        self.calls.append(("start",))
        raise AssertionError("client.start must never be called")

    async def send_code_request(self, *a, **k):  # pragma: no cover - asserted never called
        self.calls.append(("send_code_request",))
        raise AssertionError("send_code_request must never be called")

    async def get_entity(self, handle):
        self.calls.append(("get_entity", handle))
        error = self.entity_errors.get(handle)
        if error is not None:
            raise error
        return SimpleNamespace(handle=handle)

    async def get_messages(self, entity, *, limit, offset_id=0, reverse=False):
        handle = entity.handle
        self.calls.append(("get_messages", handle, limit, offset_id, reverse))
        queue = self.message_errors.get(handle) or []
        if queue:
            error = queue.pop(0)
            if error is not None:
                raise error
        messages = self.channels.get(handle, [])
        if reverse:
            ordered = list(reversed(messages))
            return FakeMessages(ordered[:limit], len(messages))
        if offset_id:
            messages = [m for m in messages if m.id < offset_id]
        return FakeMessages(messages[:limit], len(self.channels.get(handle, [])))

    def count(self, name: str) -> int:
        return sum(1 for call in self.calls if call[0] == name)

    def handles(self, name: str) -> list[str]:
        return [call[1] for call in self.calls if call[0] == name]


class FakeTelegramClientFactory:
    def __init__(self, client: FakeTelegramClient | None = None):
        self.client = client or FakeTelegramClient()
        self.created = 0

    def create(self):
        self.created += 1
        return self.client


def tg_source(handle: str, **extra) -> dict:
    return {"id": f"tg-{handle}", "platform": "telegram", "handle_or_url": handle, "enabled": True,
            "settings": {"display_name": handle}, "post_count": 0, **extra}


def rss_source(name: str) -> dict:
    return {"id": f"rss-{name}", "platform": "rss", "handle_or_url": f"https://{name}.test/feed",
            "enabled": True, "settings": {}, "post_count": 0}


def rss_kind() -> FakeKind:
    return FakeKind(
        "fake_rss",
        matches=lambda s: s.get("platform") == "rss",
        behaviour=lambda s, _limit: [{"url": f"{s['handle_or_url']}/1", "content": "x"}],
    )


class Harness:
    """A TelegramKind on fakes, plus a runner over it and a fake RSS kind."""

    def __init__(self, client: FakeTelegramClient | None = None, *, lock_held: bool = False,
                 availability: Availability = TG_ON, inspections=None):
        self.factory = FakeTelegramClientFactory(client)
        self.client = self.factory.client
        self.lock = FakeRunLock(held=lock_held)
        self.sleeper = RecordingSleeper()
        self.http = FakeHttp(sleep=self.sleeper)
        self.clock = FixedClock(NOW)
        self.kind = TelegramKind(clients=self.factory, session_lock=self.lock, http=self.http, clock=self.clock)
        self.rss = rss_kind()
        self.state = InMemoryFetchStateStore()
        self.saver = InMemoryPostSaver()
        self.availability = availability
        self.inspections = inspections or RecordingInspectionRefresher()
        self.gates = SpyFetchGates()

    async def run(self, sources: list[dict], *, selector: SourceSelector | None = None, force: bool = False):
        runner = IngestionRunner(
            catalog=InMemorySourceCatalog(sources),
            state=self.state,
            saver=self.saver,
            inspections=self.inspections,
            registry=KindRegistry([self.rss, self.kind]),
            gates=self.gates,
            run_lock=FakeRunLock(held=False),
            availability=lambda: self.availability,
            clock=self.clock,
            rand=lambda: 1.0,
        )
        return await runner.run(FetchRequest(selector or SourceSelector.all(), Trigger.SCHEDULER, force=force))

    def outcome(self, source_id: str):
        return next(o for o in self.state.outcomes if o.source_id == source_id)


class _OpenSession:
    """async with: an opened TelegramKind session, closed on exit."""

    def __init__(self, kind):
        self.session = kind.session()

    async def __aenter__(self):
        await self.session.open()
        return self.session

    async def __aexit__(self, *exc):
        await self.session.close()


# --------------------------------------------------------------------------- synthesize_posts


# Captured from the Mark VIII Telegram connector's _synthesize_messages(MESSAGES, "ai_newz", "@ai_newz")
# before the connector was deleted (dates as ISO strings).
def _d(hour: int) -> datetime:
    return datetime(2026, 10, 1, hour, 0, tzinfo=timezone.utc)


FIXTURE_MESSAGES = [
    SimpleNamespace(id=110, grouped_id=None, text="Text only", media=None, date=_d(10)),
    SimpleNamespace(id=109, grouped_id=7, text="", media=object(), date=_d(9)),
    SimpleNamespace(id=108, grouped_id=7, text="Album caption", media=object(), date=_d(9)),
    SimpleNamespace(id=107, grouped_id=7, text=None, media=object(), date=_d(9)),
    SimpleNamespace(id=106, grouped_id=8, text=None, media=object(), date=_d(8)),
    SimpleNamespace(id=105, grouped_id=8, text="", media=object(), date=_d(8)),
    SimpleNamespace(id=104, grouped_id=None, text="Photo post", media=object(), date=_d(7)),
    None,
    SimpleNamespace(id=103, grouped_id=None, text=None, media=object(), date=_d(6)),
]
FIXTURE_POSTS = [
    {"platform": "telegram", "source": "@ai_newz", "url": "https://t.me/ai_newz/110", "content": "Text only",
     "date": "2026-10-01T10:00:00+00:00", "media_urls": [], "categories": [], "metadata": {}},
    {"platform": "telegram", "source": "@ai_newz", "url": "https://t.me/ai_newz/108", "content": "Album caption",
     "date": "2026-10-01T09:00:00+00:00",
     "media_urls": ["https://t.me/ai_newz/109?single", "https://t.me/ai_newz/108?single",
                    "https://t.me/ai_newz/107?single"],
     "categories": [], "metadata": {}},
    {"platform": "telegram", "source": "@ai_newz", "url": "https://t.me/ai_newz/104", "content": "Photo post",
     "date": "2026-10-01T07:00:00+00:00", "media_urls": ["https://t.me/ai_newz/104?single"],
     "categories": [], "metadata": {}},
]


class SynthesizePostsTests(unittest.TestCase):
    def test_an_album_with_one_caption_is_one_post_with_every_media_url(self):
        album = [msg(12, "", grouped_id=5, media=True), msg(11, "Caption", grouped_id=5, media=True),
                 msg(10, None, grouped_id=5, media=True)]
        posts = synthesize_posts(album, "chan")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["url"], "https://t.me/chan/11")
        self.assertEqual(posts[0]["content"], "Caption")
        self.assertEqual(len(posts[0]["media_urls"]), 3)
        self.assertEqual(posts[0]["external_id"], "11")

    def test_a_media_only_group_is_dropped(self):
        self.assertEqual(synthesize_posts([msg(3, None, grouped_id=9, media=True),
                                           msg(2, "", grouped_id=9, media=True)], "chan"), [])

    def test_output_matches_the_mark_viii_connector(self):
        posts = synthesize_posts(FIXTURE_MESSAGES, "ai_newz")
        old_keys = list(FIXTURE_POSTS[0])
        self.assertEqual([{**{k: p[k] for k in old_keys}, "date": p["date"].isoformat()} for p in posts],
                         FIXTURE_POSTS)
        # The one addition: external_id, so (source_id, external_id) dedupe works like telegram_rss.
        self.assertEqual([p["external_id"] for p in posts], ["110", "108", "104"])

    def test_the_handle_is_normalised(self):
        self.assertEqual(synthesize_posts([msg(1, "x")], "@chan")[0]["source"], "@chan")
        self.assertEqual(synthesize_posts([msg(1, "x")], "@chan")[0]["url"], "https://t.me/chan/1")


# --------------------------------------------------------------------------- session lifecycle


class SessionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_due_sources_share_one_connect_and_one_disconnect_after_both_fetches(self):
        h = Harness(FakeTelegramClient(channels={"aaa": channel(5), "bbb": channel(3)}))
        report = await h.run([tg_source("aaa"), tg_source("bbb")])
        self.assertEqual(h.factory.created, 1)
        self.assertEqual(h.client.count("connect"), 1)
        self.assertEqual(h.client.count("disconnect"), 1)
        self.assertEqual(h.client.calls[-1], ("disconnect",))
        self.assertEqual(sorted(h.client.handles("get_entity")), ["aaa", "bbb"])
        self.assertEqual(h.outcome("tg-aaa").status, OutcomeStatus.HEALTHY)
        self.assertEqual(h.outcome("tg-bbb").status, OutcomeStatus.HEALTHY)
        self.assertEqual(report.posts_inserted, 8)
        self.assertEqual(h.lock.entered, 1)

    async def test_a_fetch_raising_still_disconnects(self):
        client = FakeTelegramClient(channels={"aaa": channel(5)},
                                    message_errors={"aaa": [RuntimeError("socket closed")]})
        h = Harness(client)
        await h.run([tg_source("aaa")])
        self.assertEqual(h.outcome("tg-aaa").status, OutcomeStatus.ERROR)
        self.assertEqual(client.count("disconnect"), 1)

    async def test_a_run_with_no_due_telegram_source_never_constructs_a_client(self):
        h = Harness()
        await h.run([rss_source("a")])
        self.assertEqual(h.factory.created, 0)
        self.assertEqual(h.lock.entered, 0)

        unavailable = Harness(availability=Availability(ytdlp_enabled=True, telegram_credentials=False,
                                                        telegram_reason="no Telegram session"))
        await unavailable.run([tg_source("aaa"), rss_source("a")], force=True)
        self.assertEqual(unavailable.factory.created, 0)

    async def test_non_telegram_kinds_have_a_no_op_null_session(self):
        session = rss_kind().session()
        self.assertIsInstance(session, NullKindSession)
        self.assertIsInstance(session, KindSession)
        self.assertIsNone(await session.open())
        self.assertIsNone(await session.close())
        self.assertIsNone(await session.close(), "close is idempotent")

    async def test_a_run_records_archive_metadata_without_measuring_the_channel(self):
        writes = []

        class Writer:
            def record(self, source_id, kind, data, mode):
                writes.append((data, mode))

        client = FakeTelegramClient(channels={"aaa": channel(7)})
        h = Harness(client)
        h.inspections = DbInspectionRefresher(writer=Writer())
        await h.run([tg_source("aaa")])
        self.assertEqual(writes, [({"source_type": "telegram_mtproto", "posts_fetched": 7}, "live")])
        self.assertEqual(client.calls[-1], ("disconnect",))
        self.assertEqual(client.count("connect"), 1)

    async def test_fetching_without_an_open_session_is_unavailable(self):
        h = Harness()
        with self.assertRaises(KindUnavailable):
            await h.kind.fetch_latest(tg_source("aaa"), 5)

    async def test_close_is_idempotent(self):
        h = Harness()
        session = h.kind.session()
        await session.open()
        await session.close()
        await session.close()
        self.assertEqual(h.client.count("disconnect"), 1)


class NonInteractiveAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_unauthorised_session_makes_every_due_source_unavailable_without_prompting(self):
        client = FakeTelegramClient(authorised=False, channels={"aaa": channel(3), "bbb": channel(3)})
        h = Harness(client)
        with mock.patch("builtins.input", side_effect=AssertionError("input() must never be called")) as patched:
            report = await h.run([tg_source("aaa"), tg_source("bbb"), rss_source("a")])
        for source_id in ("tg-aaa", "tg-bbb"):
            outcome = h.outcome(source_id)
            self.assertEqual(outcome.status, OutcomeStatus.UNAVAILABLE)
            self.assertIn("not authorised", outcome.error)
            self.assertEqual(h.state.rows[source_id].consecutive_failures, 0)
            self.assertIsNone(h.state.rows[source_id].next_retry_at)
        self.assertEqual(client.count("start"), 0)
        self.assertEqual(client.count("send_code_request"), 0)
        self.assertEqual(client.count("get_entity"), 0)
        self.assertEqual(client.count("is_user_authorized"), 1, "the session is not retried within the run")
        self.assertEqual(client.count("disconnect"), 1)
        self.assertEqual(h.lock.entered, 1)
        patched.assert_not_called()
        self.assertEqual(h.outcome("rss-a").status, OutcomeStatus.HEALTHY)
        self.assertEqual(report.sources_failed, 0, "unavailable is not a failure")

    async def test_a_held_session_lock_makes_every_source_unavailable_without_connecting(self):
        h = Harness(FakeTelegramClient(channels={"aaa": channel(3)}), lock_held=True)
        await h.run([tg_source("aaa"), tg_source("bbb")])
        for source_id in ("tg-aaa", "tg-bbb"):
            self.assertEqual(h.outcome(source_id).status, OutcomeStatus.UNAVAILABLE)
            self.assertIn("in use by another run", h.outcome(source_id).error)
        self.assertEqual(h.factory.created, 0)
        self.assertEqual(h.client.count("connect"), 0)


# --------------------------------------------------------------------------- availability


class AvailabilityTests(unittest.TestCase):
    STORED = {("telegram", "api_id"): "12345", ("telegram", "api_hash"): "abc", ("telegram", "session"): "1abc"}

    def creds(self, **drop_or_set):
        values = dict(self.STORED)
        for key, value in drop_or_set.items():
            if value is None:
                values.pop(("telegram", key), None)
            else:
                values[("telegram", key)] = value
        return MappingCredentials(values)

    def decide(self, availability: Availability):
        source = tg_source("ai_newz")
        return decide_fetch(cadence_stats(source, None), TelegramKind().profile, NOW, force=True,
                            availability=availability)

    def test_no_api_id_is_unavailable_with_connections_named_even_when_forced(self):
        availability = availability_from_env({}, credentials=self.creds(api_id=None))
        self.assertFalse(availability.telegram_credentials)
        self.assertIn("API ID", availability.telegram_reason)
        self.assertIn("Sources → Connections", availability.telegram_reason)
        decision = self.decide(availability)
        self.assertEqual(decision.kind, DecisionKind.SKIP_UNAVAILABLE)
        self.assertIn("API ID", decision.detail)

    def test_env_variables_are_not_credentials(self):
        env = {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "abc"}
        availability = availability_from_env(env, credentials=MappingCredentials())
        self.assertFalse(availability.telegram_credentials)

    def test_a_non_integer_api_id_is_unavailable(self):
        availability = availability_from_env({}, credentials=self.creds(api_id="abc"))
        self.assertFalse(availability.telegram_credentials)
        self.assertIn("API ID", availability.telegram_reason)

    def test_no_api_hash_is_unavailable(self):
        availability = availability_from_env({}, credentials=self.creds(api_hash=None))
        self.assertIn("API hash", availability.telegram_reason)

    def test_credentials_without_a_stored_session_are_unavailable(self):
        availability = availability_from_env({}, credentials=self.creds(session=None))
        self.assertFalse(availability.telegram_credentials)
        self.assertIn("no Telegram session", availability.telegram_reason)
        decision = self.decide(availability)
        self.assertEqual(decision.kind, DecisionKind.SKIP_UNAVAILABLE)
        self.assertIn("no Telegram session", decision.detail)

    def test_credentials_and_a_stored_session_are_available(self):
        availability = availability_from_env({}, credentials=self.creds())
        self.assertTrue(availability.telegram_credentials)
        self.assertIsNone(availability.telegram_reason)
        self.assertEqual(self.decide(availability).kind, DecisionKind.FETCH_FORCED)

    def test_the_ytdlp_switch_is_still_read(self):
        self.assertFalse(availability_from_env({"INSIGHT_YTDLP_ENABLED": "0"}, credentials=MappingCredentials()).ytdlp_enabled)
        self.assertTrue(availability_from_env({}, credentials=MappingCredentials()).ytdlp_enabled)

    def test_the_health_row_shows_the_unavailable_reason_not_an_error(self):
        availability = availability_from_env({}, credentials=self.creds(session=None))
        kind = TelegramKind()
        enabled = health_row({**tg_source("ai_newz"), "state": None}, kind, availability, NOW)
        self.assertEqual(enabled["status"], "unavailable")
        self.assertIn("no Telegram session", enabled["decision_detail"])
        self.assertIn("no Telegram session", enabled["unavailable_reason"])
        # The 12 bare-handle sources are disabled today: still say why enabling would not help.
        disabled = health_row({**tg_source("ai_newz"), "enabled": False, "state": None}, kind, availability, NOW)
        self.assertEqual(disabled["status"], "disabled")
        self.assertIn("no Telegram session", disabled["unavailable_reason"])
        self.assertIn("no Telegram session", disabled["decision_detail"])
        rss = health_row({**rss_source("a"), "state": None}, rss_kind(), availability, NOW)
        self.assertIsNone(rss["unavailable_reason"])


# --------------------------------------------------------------------------- flood wait and errors


class FloodWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_short_flood_wait_is_slept_and_the_page_retried_once(self):
        client = FakeTelegramClient(channels={"aaa": channel(5)}, message_errors={"aaa": [TelegramFloodWait(5)]})
        h = Harness(client)
        await h.run([tg_source("aaa")])
        self.assertIn(5, h.sleeper.calls)
        self.assertEqual(client.count("get_messages"), 2)
        self.assertEqual(h.outcome("tg-aaa").status, OutcomeStatus.HEALTHY)

    async def test_a_long_flood_wait_fails_the_source_and_makes_the_rest_unavailable(self):
        client = FakeTelegramClient(channels={"aaa": channel(5), "bbb": channel(5)},
                                    message_errors={"aaa": [TelegramFloodWait(600)]})
        h = Harness(client)
        await h.run([tg_source("aaa"), tg_source("bbb"), rss_source("a"), rss_source("b")])

        failed = h.outcome("tg-aaa")
        self.assertEqual(failed.status, OutcomeStatus.ERROR)
        self.assertIn("flood wait 600s", failed.error)
        self.assertEqual(h.state.rows["tg-aaa"].consecutive_failures, 1)
        self.assertIsNotNone(h.state.rows["tg-aaa"].next_retry_at)
        self.assertNotIn(600, h.sleeper.calls, "a long wait is never slept inline")

        skipped = h.outcome("tg-bbb")
        self.assertEqual(skipped.status, OutcomeStatus.UNAVAILABLE)
        self.assertIn("flood wait until", skipped.error)
        self.assertIn((NOW + timedelta(seconds=600)).isoformat(), skipped.error)
        self.assertEqual(h.state.rows["tg-bbb"].consecutive_failures, 0)
        self.assertNotIn("bbb", client.handles("get_entity"))

        self.assertEqual(h.outcome("rss-a").status, OutcomeStatus.HEALTHY)
        self.assertEqual(h.outcome("rss-b").status, OutcomeStatus.HEALTHY)

    async def test_a_second_short_flood_wait_fails_the_source(self):
        client = FakeTelegramClient(channels={"aaa": channel(5)},
                                    message_errors={"aaa": [TelegramFloodWait(5), TelegramFloodWait(7)]})
        h = Harness(client)
        await h.run([tg_source("aaa")])
        self.assertEqual(h.outcome("tg-aaa").status, OutcomeStatus.ERROR)
        self.assertIn("flood wait 7s", h.outcome("tg-aaa").error)
        self.assertEqual(MAX_INLINE_FLOOD_WAIT_S, 60)

    async def test_a_channel_error_fails_that_source_and_the_next_one_uses_the_same_client(self):
        client = FakeTelegramClient(channels={"bbb": channel(4)},
                                    entity_errors={"aaa": TelegramChannelError("Channel @aaa is private")})
        h = Harness(client)
        await h.run([tg_source("aaa"), tg_source("bbb")])
        self.assertEqual(h.outcome("tg-aaa").status, OutcomeStatus.ERROR)
        self.assertIn("private", h.outcome("tg-aaa").error)
        self.assertEqual(h.state.rows["tg-aaa"].consecutive_failures, 1)
        self.assertEqual(h.outcome("tg-bbb").status, OutcomeStatus.HEALTHY)
        self.assertEqual(h.factory.created, 1)
        self.assertEqual(client.count("connect"), 1)


# --------------------------------------------------------------------------- fetch, inspect, archive


class FetchInspectArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_small_limit_fetches_one_chunk(self):
        h = Harness(FakeTelegramClient(channels={"aaa": channel(250)}))
        async with _OpenSession(h.kind):
            posts = await h.kind.fetch_latest(tg_source("aaa"), 20)
        self.assertEqual(len(posts), 20)
        self.assertEqual(h.client.count("get_messages"), 1)
        self.assertEqual([c[2] for c in h.client.calls if c[0] == "get_messages"], [100])
        self.assertEqual(posts[0]["url"], "https://t.me/aaa/250", "newest first")
        self.assertEqual(h.sleeper.calls, [])

    async def test_a_large_limit_fetches_two_chunks_with_the_page_delay_between(self):
        h = Harness(FakeTelegramClient(channels={"aaa": channel(250)}))
        async with _OpenSession(h.kind):
            posts = await h.kind.fetch_latest(tg_source("aaa"), 150)
        self.assertEqual(len(posts), 150)
        offsets = [c[3] for c in h.client.calls if c[0] == "get_messages"]
        self.assertEqual(offsets, [0, 151])
        self.assertEqual(h.sleeper.calls, [h.kind.profile.page_delay_s])

    async def test_archive_pages_resume_from_the_offset_and_end_on_an_empty_chunk(self):
        h = Harness(FakeTelegramClient(channels={"aaa": channel(600)}))
        rate = h.kind.profile.rate_limit({"page_delay_seconds": 3})
        async with _OpenSession(h.kind):
            pages = [p async for p in h.kind.archive_pages(tg_source("aaa"), 10_000, {"offset_id": 500}, rate)]
        offsets = [c[3] for c in h.client.calls if c[0] == "get_messages"]
        self.assertEqual(offsets, [500, 400, 300, 200, 100, 1])
        self.assertEqual([len(p.posts) for p in pages], [100, 100, 100, 100, 99, 0])
        self.assertEqual([p.checkpoint and p.checkpoint["offset_id"] for p in pages], [400, 300, 200, 100, 1, None])
        self.assertIsNone(pages[-1].checkpoint)
        self.assertEqual(h.sleeper.calls, [], "the archive loop paces the chunks")
        self.assertTrue(all(h.kind.checkpoint_resumable(p.checkpoint) for p in pages[:-1]))

    async def test_archive_pages_stop_at_the_target(self):
        h = Harness(FakeTelegramClient(channels={"aaa": channel(600)}))
        async with _OpenSession(h.kind):
            pages = [p async for p in h.kind.archive_pages(tg_source("aaa"), 150, None, h.kind.profile.rate_limit())]
        self.assertEqual([len(p.posts) for p in pages], [100, 50])
        self.assertEqual(pages[-1].checkpoint["collected_posts"], 150)

    def test_checkpoint_resumable_accepts_an_integer_offset_id_only(self):
        kind = TelegramKind()
        self.assertTrue(kind.checkpoint_resumable({"offset_id": 400}))
        self.assertTrue(kind.checkpoint_resumable({"offset_id": 400, "pages_fetched": 2, "collected_posts": 200}))
        for bad in (None, {}, {"offset_id": "400"}, {"offset_id": True}, {"offset_id": 0},
                    {"mode": "telegram_page", "next_page": 2}, [400], 400):
            self.assertFalse(kind.checkpoint_resumable(bad), bad)

    async def test_inspect_reads_the_total_and_the_oldest_date(self):
        h = Harness(FakeTelegramClient(channels={"aaa": channel(42)}))
        async with _OpenSession(h.kind):
            inspection = await h.kind.inspect(tg_source("aaa"))
        self.assertEqual(inspection.available_posts, 42)
        self.assertEqual(inspection.first_post_date, (NOW - timedelta(hours=41)).isoformat())
        self.assertEqual(inspection.page_size, 100)

    def test_every_mtproto_source_shares_the_platform_host_key_and_its_2s_floor(self):
        kind = TelegramKind()
        self.assertEqual(kind.host_key(tg_source("ai_newz")), TELEGRAM_HOST_KEY)
        self.assertEqual(kind.host_key(tg_source("@gonzo_ML")), "platform:telegram")
        self.assertEqual(HOST_FLOORS["platform:telegram"], 2.0)
        self.assertEqual(FetchGates().host_limiter.host_floors[TELEGRAM_HOST_KEY], 2.0)

    def test_the_profile(self):
        profile = TelegramKind().profile
        self.assertIsInstance(profile, PolitenessProfile)
        self.assertEqual(profile.requires, "telegram_creds")
        self.assertTrue(profile.live_pages_rate_limited)
        self.assertEqual((profile.page_delay_s, profile.batch_size, profile.batch_cooldown_s), (1, 10, 18))


# --------------------------------------------------------------------------- imports and Telethon


class ImportTests(unittest.TestCase):
    def test_importing_the_kind_does_not_import_telethon(self):
        script = (
            "import sys\n"
            "import insight_core.ingestion\n"
            "import insight_core.ingestion.kinds\n"
            "import insight_core.ingestion.kinds.telegram_mtproto\n"
            "import insight_core.ingestion.kinds.telegram_session\n"
            "from insight_core.ingestion.schedule import availability_from_env\n"
            "from insight_core.ingestion.kinds import KindRegistry\n"
            "from insight_core.ingestion.http import KindHttp\n"
            "availability_from_env()\n"
            "k = KindRegistry.default(KindHttp(), object()).resolve({'platform': 'telegram', 'handle_or_url': 'x'})\n"
            "k.session()\n"
            "bad = [m for m in sys.modules if m == 'telethon' or m.startswith('telethon.')]\n"
            "assert not bad, bad\n"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=str(BACKEND_DIR), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_the_default_registry_resolves_bare_handles_to_the_real_kind(self):
        from insight_core.ingestion.http import KindHttp

        kind = KindRegistry.default(KindHttp(), object()).resolve(tg_source("ai_newz"))
        self.assertIsInstance(kind, TelegramKind)


try:
    import telethon  # noqa: F401
    HAVE_TELETHON = True
except ImportError:  # pragma: no cover - the image installs it
    HAVE_TELETHON = False


@unittest.skipUnless(HAVE_TELETHON, "telethon is not installed")
class TelethonTranslationTests(unittest.IsolatedAsyncioTestCase):
    def test_flood_wait_and_channel_errors_are_translated(self):
        from telethon.errors import (
            ChannelPrivateError,
            FloodWaitError,
            UsernameNotOccupiedError,
        )

        flood = translate_telethon_error(FloodWaitError(request=None, capture=5))
        self.assertIsInstance(flood, TelegramFloodWait)
        self.assertEqual(flood.seconds, 5)
        self.assertIsInstance(translate_telethon_error(ChannelPrivateError(request=None)), TelegramChannelError)
        self.assertIsInstance(translate_telethon_error(UsernameNotOccupiedError(request=None)), TelegramChannelError)
        other = RuntimeError("x")
        self.assertIs(translate_telethon_error(other), other)

    async def test_the_factory_builds_a_non_sleeping_client_on_the_stored_session(self):
        from telethon.crypto import AuthKey
        from telethon.sessions import StringSession

        from insight_core.ingestion.kinds.telegram_session import TelethonClientFactory

        session = StringSession()
        session.set_dc(2, "149.154.167.51", 443)
        session.auth_key = AuthKey(os.urandom(256))
        creds = MappingCredentials({("telegram", "api_id"): "1", ("telegram", "api_hash"): "abc",
                                    ("telegram", "session"): session.save()})
        client = TelethonClientFactory(credentials=creds).create()
        self.assertEqual(client.telethon.flood_sleep_threshold, 0)

    async def test_the_wrapper_translates_errors_raised_by_telethon(self):
        from telethon.errors import ChannelPrivateError, FloodWaitError

        from insight_core.ingestion.kinds.telegram_session import TelethonClient

        class Inner:
            async def get_entity(self, handle):
                raise ChannelPrivateError(request=None)

            async def get_messages(self, entity, **kwargs):
                raise FloodWaitError(request=None, capture=9)

        client = TelethonClient(Inner())
        with self.assertRaises(TelegramChannelError):
            await client.get_entity("x")
        with self.assertRaises(TelegramFloodWait) as ctx:
            await client.get_messages(object(), limit=1)
        self.assertEqual(ctx.exception.seconds, 9)


if __name__ == "__main__":
    unittest.main()
