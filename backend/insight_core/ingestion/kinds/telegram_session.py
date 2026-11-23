"""The Telegram client edge for the telegram_mtproto kind: the only module that imports Telethon, lazily.

- TelegramClientPort: the async surface the kind uses (fake: tests/test_telegram_kind.FakeTelegramClient).
- TelethonClientFactory: the real client, flood_sleep_threshold=0 so every flood wait reaches the kind; credentials
  and the browser sign-in's StringSession come from Connections only; never calls client.start().
- TelethonLoginClient: the browser sign-in's port (code, then 2FA password).
- TelegramFloodWait / TelegramChannelError: a channel error is the source's (backoff); a flood wait is the account's.
- PgAdvisorySessionLock: one session is never used by two processes at once.
"""
from __future__ import annotations

import contextlib
import os
from typing import Any, AsyncIterator, Optional, Protocol, Sequence

from insight_core.ingestion.kinds.base import KindUnavailable

SESSION_LOCK_KEY = "insight.telegram_session"
LOGIN_HINT = "sign in under Sources → Connections"
CREDENTIALS_HINT = "add it in Sources → Connections"


def _provider(credentials: Any) -> Any:
    if credentials is not None:
        return credentials
    from insight_core.ingestion.credentials import default_credentials

    return default_credentials()


def telegram_credentials(*, credentials: Any = None) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """(api_id, api_hash, reason): reason names what is missing, None when both are usable. Read from
    `credentials`, default the Connections store.
    """
    provider = _provider(credentials)
    raw_id = (provider.get("telegram", "api_id") or "").strip()
    if not raw_id:
        return None, None, f"Telegram API ID is not set; {CREDENTIALS_HINT}"
    try:
        api_id = int(raw_id)
    except ValueError:
        return None, None, f"Telegram API ID is not an integer; {CREDENTIALS_HINT}"
    api_hash = (provider.get("telegram", "api_hash") or "").strip()
    if not api_hash:
        return None, None, f"Telegram API hash is not set; {CREDENTIALS_HINT}"
    return api_id, api_hash, None


def telegram_session_string(credentials: Any) -> Optional[str]:
    """The StringSession saved by the browser sign-in, or None (no session: unavailable)."""
    if credentials is None:
        return None
    return (credentials.get("telegram", "session") or "").strip() or None


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

    async def get_me(self) -> Any: ...

    async def get_entity(self, handle: str) -> Any: ...       # raises TelegramChannelError / TelegramFloodWait

    async def get_messages(self, entity: Any, *, limit: int, offset_id: int = 0,
                           reverse: bool = False) -> Sequence[Any]: ...   # newest first; `.total` when known

    async def get_full(self, entity: Any) -> Any: ...   # the channel's full info: full_chat.about, participants_count


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

    async def get_me(self) -> Any:
        return await self.telethon.get_me()

    async def get_entity(self, handle: str) -> Any:
        try:
            return await self.telethon.get_entity(handle)
        except Exception as exc:  # noqa: BLE001 - translated, or re-raised unchanged
            translated = translate_telethon_error(exc, handle)
            if translated is exc:
                raise
            raise translated from exc

    async def get_full(self, entity: Any) -> Any:
        """GetFullChannelRequest: the channel's about and subscriber count, one request."""
        from telethon.tl.functions.channels import GetFullChannelRequest
        try:
            return await self.telethon(GetFullChannelRequest(entity))
        except Exception as exc:  # noqa: BLE001
            translated = translate_telethon_error(exc, getattr(entity, "username", None))
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
    """Builds the real client. Credentials and the session are read at create() time."""

    def __init__(self, *, api_id: Optional[int] = None, api_hash: Optional[str] = None,
                 credentials: Any = None) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.credentials = credentials

    def _credentials(self) -> Any:
        if self.credentials is None:
            self.credentials = _provider(None)
        return self.credentials

    def create(self) -> TelethonClient:
        api_id, api_hash = self.api_id, self.api_hash
        if api_id is None or not api_hash:
            api_id, api_hash, reason = telegram_credentials(credentials=self._credentials())
            if reason:
                raise KindUnavailable(reason)
        string = telegram_session_string(self._credentials())
        if not string:
            raise KindUnavailable(f"no Telegram session; {LOGIN_HINT}")
        from telethon.sessions import StringSession

        session = StringSession(string)
        from telethon import TelegramClient

        client = TelegramClient(
            session,
            api_id,
            api_hash,
            flood_sleep_threshold=0,    # every FloodWaitError reaches the kind (its bounded rule)
            receive_updates=False,      # a fetcher, not a chat client
        )
        return TelethonClient(client)


class TelegramLoginError(Exception):
    """A sign-in step failed; `message` is safe to show. retry_after: a flood wait's seconds."""

    def __init__(self, message: str, *, retry_after: Optional[int] = None, restart: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after
        self.restart = restart          # the pending sign-in is dead: start again


class TelegramPasswordNeeded(Exception):
    """The account has two-step verification: the password step comes next."""


def translate_login_error(exc: BaseException) -> BaseException:
    """Telethon's sign-in errors -> TelegramPasswordNeeded / TelegramLoginError."""
    from telethon import errors

    if isinstance(exc, errors.SessionPasswordNeededError):
        return TelegramPasswordNeeded()
    if isinstance(exc, errors.FloodWaitError):
        seconds = int(getattr(exc, "seconds", 0) or 0)
        return TelegramLoginError(f"Telegram asks to wait {seconds} seconds before trying again",
                                  retry_after=seconds)
    if isinstance(exc, errors.PhoneNumberInvalidError):
        return TelegramLoginError("That phone number is not valid; use the international format, e.g. +15551234567")
    if isinstance(exc, errors.PhoneNumberBannedError):
        return TelegramLoginError("Telegram has banned this phone number", restart=True)
    if isinstance(exc, errors.PhoneCodeInvalidError):
        return TelegramLoginError("That code is not right; check it and try again")
    if isinstance(exc, errors.PhoneCodeExpiredError):
        return TelegramLoginError("That code has expired; start the sign-in again", restart=True)
    if isinstance(exc, errors.PasswordHashInvalidError):
        return TelegramLoginError("That password is not right; try again")
    if isinstance(exc, errors.ApiIdInvalidError):
        return TelegramLoginError("Telegram rejected the API ID and hash; check them", restart=True)
    if isinstance(exc, errors.RPCError):
        return TelegramLoginError(f"Telegram refused the sign-in: {type(exc).__name__}", restart=True)
    return exc


class TelethonLoginClient:
    """The browser sign-in's port over a telethon.TelegramClient on a StringSession."""

    def __init__(self, api_id: int, api_hash: str, session: str = "") -> None:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        self.telethon = TelegramClient(StringSession(session or None), api_id, api_hash,
                                       flood_sleep_threshold=0, receive_updates=False)

    async def _call(self, awaitable: Any) -> Any:
        try:
            return await awaitable
        except Exception as exc:  # noqa: BLE001 - translated, or re-raised unchanged
            translated = translate_login_error(exc)
            if translated is exc:
                raise
            raise translated from None

    async def connect(self) -> None:
        await self.telethon.connect()

    async def disconnect(self) -> None:
        await self.telethon.disconnect()

    async def send_code(self, phone: str) -> str:
        sent = await self._call(self.telethon.send_code_request(phone))
        return sent.phone_code_hash

    async def sign_in_code(self, phone: str, code: str, phone_code_hash: str) -> None:
        await self._call(self.telethon.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash))

    async def sign_in_password(self, password: str) -> None:
        await self._call(self.telethon.sign_in(password=password))

    async def get_me(self) -> Any:
        return await self.telethon.get_me()

    def session_string(self) -> str:
        return self.telethon.session.save()


class PgAdvisorySessionLock:
    """The run lock's shape (try_acquire() -> async context yielding bool) on the session key. The database URL is
    resolved when the lock is taken, so building the kind registry needs no database.
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
    "PgAdvisorySessionLock",
    "TelegramChannelError",
    "TelegramClientFactory",
    "TelegramClientPort",
    "TelegramFloodWait",
    "TelegramLoginError",
    "TelegramPasswordNeeded",
    "TelethonClient",
    "TelethonClientFactory",
    "TelethonLoginClient",
    "telegram_credentials",
    "telegram_session_string",
    "translate_login_error",
    "translate_telethon_error",
]
