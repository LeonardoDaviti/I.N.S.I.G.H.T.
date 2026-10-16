"""telegram_mtproto: bare Telegram handles (platform telegram, no "://") read over MTProto.

Built from the Mark VIII Telegram connector (spec §B8, §D.2):
- synthesize_posts: its album grouping (by grouped_id), as a pure function
- fetch_latest / archive_pages: its chunked get_messages(offset_id=...) loop, 100 messages
  a chunk, paced by the profile (page 1s; the 10-request / 18s throttle is the batch cooldown)
- TelegramSession: its connect(), minus the interactive stdin login. One session per run, opened
  lazily by the runner before the first due telegram source and closed in a finally. open()
  takes the session lock, connects and checks is_user_authorized(); it never calls
  client.start(), send_code_request or a stdin prompt. Authorisation is the browser sign-in
  in Sources → Connections, which stores the session encrypted.

Flood wait: the client never sleeps one itself (flood_sleep_threshold=0). A wait of at most
MAX_INLINE_FLOOD_WAIT_S is slept through KindHttp.sleep and the request retried once; a
longer one fails that source (error, normal backoff, "flood wait Ns") and floods the
session, so every later telegram source in the run is unavailable ("Telegram flood wait
until ..."), which is not backoff.

Telethon is never imported here (kinds/telegram_session.py owns that edge).
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    KindUnavailable,
    PolitenessProfile,
    RateLimit,
    Source,
    resume_counts,
    start_at,
)
from insight_core.ingestion.kinds.telegram_session import (
    LOGIN_HINT,
    PgAdvisorySessionLock,
    TelegramClientFactory,
    TelegramClientPort,
    TelegramFloodWait,
    TelethonClientFactory,
)
from insight_core.utils.json_safe import iso

# The connector's 10-request / 18s throttle becomes the batch cooldown. Every MTProto source
# shares one client, so the host key is one constant (2s floor in gates.HOST_FLOORS).
TELEGRAM_MTPROTO_PROFILE = PolitenessProfile(
    concurrency_pool="host-lock",
    page_delay_s=1,
    batch_size=10,
    batch_cooldown_s=18,
    live_pages_rate_limited=True,
    requires="telegram_creds",
)

TELEGRAM_HOST_KEY = "platform:telegram"
MAX_INLINE_FLOOD_WAIT_S = 60
CHUNK_SIZE = 100          # messages per get_messages call (the connector's fetch_chunk_size)
MAX_CHUNKS = 20           # per live fetch (the connector's max_fetches)

NOT_AUTHORISED = f"Telegram session not authorised; {LOGIN_HINT}"
IN_USE = "Telegram session in use by another run"
NOT_OPEN = "Telegram session is not open"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _handle(source: Source) -> str:
    return str(source.get("handle_or_url") or "").strip().lstrip("@")


def synthesize_posts(messages: Iterable[Any], handle: str) -> List[Dict[str, Any]]:
    """Group a chunk of messages into logical posts (moved from _synthesize_messages).

    Messages sharing a grouped_id are one album: the post's text and url come from the
    message that carries text (the last one seen), and every message with media adds a
    `?single` media url. Groups without text (media-only) are dropped.
    """
    handle = handle.lstrip("@")
    groups: Dict[Any, Dict[str, Any]] = {}
    for message in messages:
        if not message:
            continue
        group_id = message.grouped_id or message.id
        group = groups.setdefault(group_id, {"messages": [], "text": None, "main": message})
        group["messages"].append(message)
        if message.text:
            group["text"] = message.text
            group["main"] = message

    posts: List[Dict[str, Any]] = []
    for group in groups.values():
        text = group["text"]
        if not text:
            continue
        main = group["main"]
        posts.append({
            "platform": "telegram",
            "source": f"@{handle}",
            "url": f"https://t.me/{handle}/{main.id}",
            "content": text,
            "date": main.date,
            "media_urls": [f"https://t.me/{handle}/{m.id}?single" for m in group["messages"] if m.media],
            "categories": [],
            "metadata": {},
            # Mark IX addition: (source_id, external_id) dedupe, the same id telegram_rss uses.
            "external_id": str(main.id),
        })
    return posts


class TelegramSession:
    """One run's Telegram client: session lock + connect + authorisation check. Never prompts."""

    def __init__(self, kind: "TelegramKind") -> None:
        self.kind = kind
        self.client: Optional[TelegramClientPort] = None
        self.flooded_until: Optional[datetime] = None
        self._stack: Optional[contextlib.AsyncExitStack] = None

    async def open(self) -> None:
        if self.client is not None:
            return
        stack = contextlib.AsyncExitStack()
        try:
            try:
                acquired = await stack.enter_async_context(self.kind.session_lock.try_acquire())
            except KindUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 - the lock's DB being down is not the sources' fault
                raise KindUnavailable(f"Telegram session lock unavailable: {exc}") from exc
            if not acquired:
                raise KindUnavailable(IN_USE)
            client = self.kind.clients.create()
            try:
                await client.connect()
            except Exception as exc:  # noqa: BLE001
                raise KindUnavailable(f"Telegram connect failed: {exc}") from exc
            stack.push_async_callback(client.disconnect)
            if not await client.is_user_authorized():
                raise KindUnavailable(NOT_AUTHORISED)
        except BaseException:
            await stack.aclose()
            raise
        self.client = client
        self._stack = stack
        self.kind._active = self

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self.client = None
        if self.kind._active is self:
            self.kind._active = None
        if stack is not None:
            await stack.aclose()


class TelegramKind(BaseKind):
    name = "telegram_mtproto"
    available_basis = "exact"
    profile = TELEGRAM_MTPROTO_PROFILE

    def __init__(
        self,
        *,
        clients: Optional[TelegramClientFactory] = None,
        session_lock: Any = None,
        http: Optional[KindHttp] = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.clients = clients or TelethonClientFactory()
        self.session_lock = session_lock or PgAdvisorySessionLock()
        self.http = http or KindHttp()
        self.clock = clock
        self._active: Optional[TelegramSession] = None

    # ------------------------------------------------------------------ seam

    def matches(self, source: Source) -> bool:
        return source.get("platform") == "telegram" and "://" not in str(source.get("handle_or_url") or "")

    def host_key(self, source: Source) -> str:
        return TELEGRAM_HOST_KEY

    def session(self) -> TelegramSession:
        return TelegramSession(self)

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        if not isinstance(checkpoint, dict):
            return False
        offset = checkpoint.get("offset_id")
        return isinstance(offset, int) and not isinstance(offset, bool) and offset > 0

    async def start_checkpoint(self, source: Source, stored) -> Optional[dict]:
        # offset_id returns the messages older than it: exact, no overlap needed.
        try:
            offset_id = int(stored.get("oldest_external_id"))
        except (TypeError, ValueError):
            return None
        return start_at(offset_id=offset_id) if offset_id > 0 else None

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        session = self._open_session()
        handle = _handle(source)
        entity = await self._call(session, lambda c: c.get_entity(handle))
        rate = self.profile.rate_limit()
        collected: List[Dict[str, Any]] = []
        seen: set[str] = set()
        offset_id = 0
        for chunk in range(MAX_CHUNKS):
            if chunk:
                await self.http.sleep(rate.delay_after(chunk))
            messages = await self._call(
                session, lambda c: c.get_messages(entity, limit=CHUNK_SIZE, offset_id=offset_id))
            if not messages:
                break
            for post in synthesize_posts(messages, handle):
                if post["url"] not in seen:
                    seen.add(post["url"])
                    collected.append(post)
            offset_id = messages[-1].id
            if len(collected) >= limit or len(messages) < CHUNK_SIZE:
                break   # enough posts, or a short chunk: the channel has no older messages
        collected.sort(key=lambda p: p["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return collected[:limit]

    async def inspect(self, source: Source) -> Inspection:
        session = self._open_session()
        handle = _handle(source)
        entity = await self._call(session, lambda c: c.get_entity(handle))
        latest = await self._call(session, lambda c: c.get_messages(entity, limit=1))
        oldest = await self._call(session, lambda c: c.get_messages(entity, limit=1, reverse=True))
        total = getattr(latest, "total", None)
        return Inspection(
            available_posts=int(total) if total is not None else None,
            page_size=CHUNK_SIZE,
            first_post_date=iso(oldest[0].date) if oldest else None,
            raw={"latest_message_id": latest[0].id if latest else None},
        )

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        """One ArchivePage per 100-message chunk; checkpoint {"offset_id": last id}; None when empty."""
        session = self._open_session()
        handle = _handle(source)
        collected, pages_fetched = resume_counts(checkpoint)
        offset_id = int((checkpoint or {}).get("offset_id") or 0) if isinstance(checkpoint, dict) else 0
        entity = await self._call(session, lambda c: c.get_entity(handle))
        seen: set[str] = set()
        while collected < target:
            messages = await self._call(
                session, lambda c: c.get_messages(entity, limit=CHUNK_SIZE, offset_id=offset_id))
            if not messages:
                yield ArchivePage([], None)
                return
            posts = [p for p in synthesize_posts(messages, handle) if p["url"] not in seen]
            posts = posts[: max(0, target - collected)]
            seen.update(p["url"] for p in posts)
            collected += len(posts)
            pages_fetched += 1
            offset_id = messages[-1].id
            yield ArchivePage(posts, {
                "offset_id": offset_id,
                "pages_fetched": pages_fetched,
                "collected_posts": collected,
            })

    # ------------------------------------------------------------------ helpers

    def _open_session(self) -> TelegramSession:
        session = self._active
        if session is None or session.client is None:
            raise KindUnavailable(NOT_OPEN)
        return session

    def _check_flood(self, session: TelegramSession) -> None:
        if session.flooded_until is not None and self.clock() < session.flooded_until:
            raise KindUnavailable(f"Telegram flood wait until {session.flooded_until.isoformat()}")

    async def _call(self, session: TelegramSession, request: Callable[[TelegramClientPort], Awaitable[Any]]) -> Any:
        """One client request under the bounded flood-wait rule."""
        self._check_flood(session)
        client = session.client
        if client is None:
            raise KindUnavailable(NOT_OPEN)
        try:
            return await request(client)
        except TelegramFloodWait as flood:
            wait = flood
            if wait.seconds <= MAX_INLINE_FLOOD_WAIT_S:
                await self.http.sleep(wait.seconds)
                try:
                    return await request(client)
                except TelegramFloodWait as again:
                    wait = again
            if wait.seconds > MAX_INLINE_FLOOD_WAIT_S:
                session.flooded_until = self.clock() + timedelta(seconds=wait.seconds)
            raise TelegramFetchError(f"flood wait {wait.seconds}s") from wait


class TelegramFetchError(RuntimeError):
    """A source-level failure (outcome error, backoff applies)."""
