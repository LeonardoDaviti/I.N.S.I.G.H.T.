"""The Telegram client edge for the telegram_mtproto kind (spec §B8, §3).

This is the only ingestion module that knows Telethon exists, and it imports it lazily:
inside TelethonClientFactory.create() and translate_telethon_error(). Importing ingestion,
the kinds or this module never pulls Telethon into sys.modules.

- TelegramClientPort: the small async surface the kind uses (connect, authorisation check,
  get_entity, get_messages). The test adapter is tests/test_telegram_kind.FakeTelegramClient.
- TelethonClientFactory: builds a TelethonClient (the port over telethon.TelegramClient)
  on the session file at telegram_session_path(), with flood_sleep_threshold=0 so every
  FloodWaitError reaches the kind instead of being slept inside Telethon. It never calls
  client.start(): authorisation happens only in scripts/telegram_login.py.
- TelegramFloodWait / TelegramChannelError: what Telethon's errors become. A channel error
  is the channel's problem (source error, backoff applies); a flood wait is the account's.
- PgAdvisorySessionLock: Telethon's SQLite session file cannot be shared by two processes,
  and config/ (where it lives) is bind-mounted into both the API and ingestion containers,
  so a session is only opened under pg_try_advisory_lock(hashtext('insight.telegram_session')).
"""
from __future__ import annotations

import contextlib
import os
from typing import Any, AsyncIterator, Mapping, Optional, Protocol, Sequence

from insight_core.ingestion.kinds.base import KindUnavailable

DEFAULT_SESSION_PATH = "/app/insight_core/config/telegram/insight.session"
SESSION_LOCK_KEY = "insight.telegram_session"
LOGIN_HINT = "run scripts/telegram_login"


SESSION_SUFFIX = ".session"


def normalise_session_path(path: str) -> str:
    """The file Telethon actually uses: SQLiteSession appends ".session" to a bare name.

    The login script, the client factory and the availability probe all go through this,
    so `TELEGRAM_SESSION_PATH=/x/insight` is checked as the /x/insight.session it writes.
    """
    path = path.strip()
    return path if path.endswith(SESSION_SUFFIX) else path + SESSION_SUFFIX


def telegram_session_path(env: Optional[Mapping[str, str]] = None) -> str:
    """TELEGRAM_SESSION_PATH, default inside the bind-mounted config/ (survives rebuilds)."""
    env = os.environ if env is None else env
    return normalise_session_path((env.get("TELEGRAM_SESSION_PATH") or "").strip() or DEFAULT_SESSION_PATH)


def telegram_credentials(env: Optional[Mapping[str, str]] = None) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """(api_id, api_hash, reason): reason names what is missing, None when both are usable."""
    env = os.environ if env is None else env
    raw_id = (env.get("TELEGRAM_API_ID") or "").strip()
    if not raw_id:
        return None, None, "TELEGRAM_API_ID is not set"
    try:
        api_id = int(raw_id)
    except ValueError:
        return None, None, "TELEGRAM_API_ID is not an integer"
    api_hash = (env.get("TELEGRAM_API_HASH") or "").strip()
    if not api_hash:
        return None, None, "TELEGRAM_API_HASH is not set"
    return api_id, api_hash, None


class TelegramFloodWait(Exception):
    """Telegram asked this account to wait `seconds` before the next request."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"flood wait {seconds}s")
        self.seconds = int(seconds)


class TelegramChannelError(Exception):
    """The channel cannot be read (invalid, private, unknown username, API error)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TelegramClientPort(Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def is_user_authorized(self) -> bool: ...

    async def get_entity(self, handle: str) -> Any: ...       # raises TelegramChannelError / TelegramFloodWait

    async def get_messages(self, entity: Any, *, limit: int, offset_id: int = 0,
                           reverse: bool = False) -> Sequence[Any]: ...   # newest first; `.total` when known


class TelegramClientFactory(Protocol):
    def create(self) -> TelegramClientPort: ...


def translate_telethon_error(exc: BaseException, handle: str | None = None) -> BaseException:
    """Telethon's error -> TelegramFloodWait / TelegramChannelError; anything else unchanged."""
    from telethon import errors

    channel = f"@{handle}" if handle else "the channel"
    if isinstance(exc, errors.FloodWaitError):
        return TelegramFloodWait(int(getattr(exc, "seconds", 0) or 0))
    if isinstance(exc, errors.ChannelInvalidError):
        return TelegramChannelError(f"Channel {channel} does not exist or is invalid")
    if isinstance(exc, errors.ChannelPrivateError):
        return TelegramChannelError(f"Channel {channel} is private or requires subscription")
    if isinstance(exc, errors.UsernameInvalidError):
        return TelegramChannelError(f"Invalid username format: {channel}")
    if isinstance(exc, errors.UsernameNotOccupiedError):
        return TelegramChannelError(f"Username not found: {channel}")
    if isinstance(exc, errors.RPCError):
        return TelegramChannelError(f"Telegram API error for {channel}: {exc}")
    return exc


class TelethonClient:
    """TelegramClientPort over a telethon.TelegramClient, translating its errors."""

    def __init__(self, telethon_client: Any) -> None:
        self.telethon = telethon_client

    async def connect(self) -> None:
        await self.telethon.connect()

    async def disconnect(self) -> None:
        await self.telethon.disconnect()

    async def is_user_authorized(self) -> bool:
        return bool(await self.telethon.is_user_authorized())

    async def get_entity(self, handle: str) -> Any:
        try:
            return await self.telethon.get_entity(handle)
        except Exception as exc:  # noqa: BLE001 - translated, or re-raised unchanged
            translated = translate_telethon_error(exc, handle)
            if translated is exc:
                raise
            raise translated from exc

    async def get_messages(self, entity: Any, *, limit: int, offset_id: int = 0, reverse: bool = False):
        try:
            return await self.telethon.get_messages(entity, limit=limit, offset_id=offset_id, reverse=reverse)
        except Exception as exc:  # noqa: BLE001
            translated = translate_telethon_error(exc, getattr(entity, "username", None))
            if translated is exc:
                raise
            raise translated from exc


class TelethonClientFactory:
    """Builds the real client. Credentials and the session path are read at create() time."""

    def __init__(self, *, api_id: Optional[int] = None, api_hash: Optional[str] = None,
                 session_path: Optional[str] = None) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = session_path

    def create(self) -> TelethonClient:
        api_id, api_hash = self.api_id, self.api_hash
        if api_id is None or not api_hash:
            api_id, api_hash, reason = telegram_credentials()
            if reason:
                raise KindUnavailable(reason)
        path = normalise_session_path(self.session_path) if self.session_path else telegram_session_path()
        if not os.path.exists(path):
            raise KindUnavailable(f"no Telegram session at {path}; {LOGIN_HINT}")

        from telethon import TelegramClient

        client = TelegramClient(
            path,
            api_id,
            api_hash,
            flood_sleep_threshold=0,    # every FloodWaitError reaches the kind (bounded rule, §D.2)
            receive_updates=False,      # a fetcher, not a chat client
        )
        return TelethonClient(client)


class PgAdvisorySessionLock:
    """The run lock's shape (try_acquire() -> async context yielding bool) on the session key.

    The database URL is resolved when the lock is taken, so building the default kind
    registry never needs a database.
    """

    def __init__(self, db_url: Optional[str] = None, key: str = SESSION_LOCK_KEY) -> None:
        self.db_url = db_url
        self.key = key

    @contextlib.asynccontextmanager
    async def try_acquire(self) -> AsyncIterator[bool]:
        from insight_core.ingestion.ports import PgAdvisoryRunLock

        db_url = self.db_url or os.getenv("DATABASE_URL")
        if not db_url:
            raise KindUnavailable("no DATABASE_URL for the Telegram session lock")
        async with PgAdvisoryRunLock(db_url, self.key).try_acquire() as acquired:
            yield acquired


__all__ = [
    "DEFAULT_SESSION_PATH",
    "PgAdvisorySessionLock",
    "TelegramChannelError",
    "TelegramClientFactory",
    "TelegramClientPort",
    "TelegramFloodWait",
    "TelethonClient",
    "TelethonClientFactory",
    "telegram_credentials",
    "telegram_session_path",
    "translate_telethon_error",
]
