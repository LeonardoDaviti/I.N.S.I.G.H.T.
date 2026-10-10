"""The Telegram client edge for the telegram_mtproto kind (spec §B8, §3).

This is the only ingestion module that knows Telethon exists, and it imports it lazily:
inside TelethonClientFactory.create() and translate_telethon_error(). Importing ingestion,
the kinds or this module never pulls Telethon into sys.modules.

- TelegramClientPort: the small async surface the kind uses (connect, authorisation check,
  get_entity, get_messages). The test adapter is tests/test_telegram_kind.FakeTelegramClient.
- TelethonClientFactory: builds a TelethonClient (the port over telethon.TelegramClient),
  with flood_sleep_threshold=0 so every FloodWaitError reaches the kind instead of being
  slept inside Telethon. Credentials come through the credential seam (Sources →
  Connections, else TELEGRAM_API_ID / TELEGRAM_API_HASH). The session is the StringSession
  saved by the browser sign-in when there is one, else the file at telegram_session_path()
  (scripts/telegram_login.py). It never calls client.start().
- TelethonLoginClient: the browser sign-in's port (send code, sign in with the code, then
  the 2FA password), its Telethon errors turned into TelegramLoginError messages.
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
LOGIN_HINT = "sign in under Sources → Connections"
CREDENTIALS_HINT = "add it in Sources → Connections"


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


def _provider(env: Optional[Mapping[str, str]], credentials: Any) -> Any:
    if credentials is not None:
        return credentials
    from insight_core.ingestion.credentials import EnvCredentials

    return EnvCredentials(env)


def telegram_credentials(env: Optional[Mapping[str, str]] = None, *,
                         credentials: Any = None) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """(api_id, api_hash, reason): reason names what is missing, None when both are usable.

    Read from `credentials` (a CredentialProvider: Connections, then env) or, without one,
    from `env` / os.environ only.
    """
    provider = _provider(env, credentials)
    raw_id = (provider.get("telegram", "api_id") or "").strip()
    if not raw_id:
        return None, None, f"Telegram API ID (TELEGRAM_API_ID) is not set; {CREDENTIALS_HINT}"
    try:
        api_id = int(raw_id)
    except ValueError:
        return None, None, f"Telegram API ID (TELEGRAM_API_ID) is not an integer; {CREDENTIALS_HINT}"
    api_hash = (provider.get("telegram", "api_hash") or "").strip()
    if not api_hash:
        return None, None, f"Telegram API hash (TELEGRAM_API_HASH) is not set; {CREDENTIALS_HINT}"
    return api_id, api_hash, None


def telegram_session_string(credentials: Any) -> Optional[str]:
    """The StringSession saved by the browser sign-in, or None (then the file is used)."""
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

    async def get_messages(self, entity: Any, *, limit: int, offset_id: int = 0, reverse: bool = False):
        try:
            return await self.telethon.get_messages(entity, limit=limit, offset_id=offset_id, reverse=reverse)
        except Exception as exc:  # noqa: BLE001
            translated = translate_telethon_error(exc, getattr(entity, "username", None))
            if translated is exc:
                raise
            raise translated from exc


class TelethonClientFactory:
    """Builds the real client. Credentials and the session are read at create() time.

    An explicit session_path pins the file (tests, the login script). Otherwise the stored
    StringSession wins over the file.
    """

    def __init__(self, *, api_id: Optional[int] = None, api_hash: Optional[str] = None,
                 session_path: Optional[str] = None, credentials: Any = None) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = session_path
        self.credentials = credentials

    def _credentials(self) -> Any:
        if self.credentials is None:
            from insight_core.ingestion.credentials import default_credentials

            self.credentials = default_credentials()
        return self.credentials

    def create(self) -> TelethonClient:
        api_id, api_hash = self.api_id, self.api_hash
        if api_id is None or not api_hash:
            api_id, api_hash, reason = telegram_credentials(credentials=self._credentials())
            if reason:
                raise KindUnavailable(reason)
        session: Any = None
        if not self.session_path:
            string = telegram_session_string(self._credentials())
            if string:
                from telethon.sessions import StringSession

                session = StringSession(string)
        if session is None:
            path = normalise_session_path(self.session_path) if self.session_path else telegram_session_path()
            if not os.path.exists(path):
                raise KindUnavailable(f"no Telegram session at {path}; {LOGIN_HINT}")
            session = path

        from telethon import TelegramClient

        client = TelegramClient(
            session,
            api_id,
            api_hash,
            flood_sleep_threshold=0,    # every FloodWaitError reaches the kind (bounded rule, §D.2)
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
    "TelegramLoginError",
    "TelegramPasswordNeeded",
    "TelethonClient",
    "TelethonClientFactory",
    "TelethonLoginClient",
    "telegram_credentials",
    "telegram_session_path",
    "telegram_session_string",
    "translate_login_error",
    "translate_telethon_error",
]
