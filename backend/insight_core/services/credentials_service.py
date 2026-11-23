"""Connections: the secrets the owner adds in Sources → Connections, write-only.

The API shows per field only whether a value is set, its last 4 characters and when it was saved; it never returns
a stored value, a ciphertext or a Telegram session, nothing here logs one, and no secret is read from the
environment. Providers: substack {sid}, telegram {api_id, api_hash, session} (the session from the browser sign-in:
login_start -> login_code -> login_password), reddit {client_id, client_secret, username} (its OAuth API). A row of
an unlisted provider is kept but never shown. Each provider has a test (a paid post or sign-in check, get_me, an
application-only token).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import psycopg

from insight_core.db import database as db
from insight_core.db.repo_credentials import CredentialRow, CredentialsRepository
from insight_core.ingestion.credentials import (
    SecretBox,
    SecretKeyMissing,
    StoredCredentials,
    default_credentials,
)
from insight_core.utils.json_safe import iso

LOGIN_TTL_S = 10 * 60


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    hint: str
    writable: bool = True        # False: set only by a flow (the Telegram session)
    show_last4: bool = True


@dataclass(frozen=True)
class ProviderSpec:
    provider: str
    label: str
    description: str
    fields: Tuple[FieldSpec, ...] = ()
    testable: bool = False
    sign_in: bool = False


PROVIDERS: Tuple[ProviderSpec, ...] = (
    ProviderSpec(
        "substack", "Substack",
        "Full text of paid posts you subscribe to. Without it, paid posts arrive as teasers.",
        (FieldSpec("sid", "Session cookie (substack.sid)",
                   "Log into substack.com, open DevTools → Application → Cookies → substack.com "
                   "and copy the value of substack.sid. It lasts months."),),
        testable=True,
    ),
    ProviderSpec(
        "telegram", "Telegram",
        "Reads Telegram channels by handle. Create an app at my.telegram.org, then sign in.",
        (FieldSpec("api_id", "API ID", "The number shown at my.telegram.org → API development tools."),
         FieldSpec("api_hash", "API hash", "The 32-character hash next to the API ID."),
         FieldSpec("session", "Session", "Created by signing in with your phone number.",
                   writable=False, show_last4=False)),
        testable=True,
        sign_in=True,
    ),
    ProviderSpec(
        "reddit", "Reddit",
        "Reads subreddits. Reddit ended its feeds: register a \"script\" app at reddit.com/prefs/apps, then add it here.",
        (FieldSpec("client_id", "Client ID", "The string under the app's name at reddit.com/prefs/apps."),
         FieldSpec("client_secret", "Secret", "The app's secret, shown next to \"secret\"."),
         FieldSpec("username", "Reddit username", "The account that registered the app (named in the User-Agent).")),
        testable=True,
    ),
)
_SPECS = {spec.provider: spec for spec in PROVIDERS}


class CredentialNotFound(LookupError):
    pass


class CredentialInvalid(ValueError):
    pass


class LoginFailed(Exception):
    def __init__(self, message: str, *, retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _last4(value: str) -> str:
    return value[-4:] if len(value) > 4 else ""


_SID_RE = re.compile(r"^[A-Za-z0-9%._:+/=\-]+$")
_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_PHONE_RE = re.compile(r"^\+?[0-9]{6,15}$")
_REDDIT_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{10,40}$")
_REDDIT_USER_RE = re.compile(r"^[A-Za-z0-9_\-]{3,20}$")


def normalise_value(provider: str, key: str, value: Any) -> str:
    """The value as stored, or CredentialInvalid with a message that never echoes it."""
    if not isinstance(value, str) or not value.strip():
        raise CredentialInvalid("Enter a value")
    text = value.strip().strip('"').strip("'").strip()
    if provider == "substack" and key == "sid":
        if text.startswith("substack.sid="):
            text = text.split("=", 1)[1].split(";", 1)[0].strip()
        if not text or not _SID_RE.match(text):
            raise CredentialInvalid("That does not look like a substack.sid cookie value")
    elif provider == "telegram" and key == "api_id":
        if not text.isdigit():
            raise CredentialInvalid("The API ID is a number")
    elif provider == "telegram" and key == "api_hash":
        if not _HASH_RE.match(text):
            raise CredentialInvalid("The API hash is 32 letters and digits (0-9, a-f)")
        text = text.lower()
    elif provider == "reddit" and key in ("client_id", "client_secret"):
        if not _REDDIT_KEY_RE.match(text):
            raise CredentialInvalid("That does not look like a Reddit app's client id or secret")
    elif provider == "reddit" and key == "username":
        text = text.removeprefix("/u/").removeprefix("u/")
        if not _REDDIT_USER_RE.match(text):
            raise CredentialInvalid("A Reddit username is 3 to 20 letters, digits, - or _")
    return text


@dataclass
class PendingLogin:
    phone: str
    phone_code_hash: str
    session: str
    stage: str                       # "code" | "password"
    expires_at: float


@dataclass
class TestResult:
    ok: bool
    message: str
    tested_at: datetime


@dataclass
class CredentialsService:
    db_url: str
    box: Optional[SecretBox] = None
    env: Optional[Dict[str, str]] = None
    credentials: Optional[StoredCredentials] = None
    substack_checker: Optional[Callable[[Any, Optional[dict]], Any]] = None   # (provider, source) -> (ok, msg)
    telegram_clients: Optional[Callable[[Any], Any]] = None                  # (provider) -> TelegramClientFactory
    telegram_lock: Any = None
    login_clients: Optional[Callable[[int, str, str], Any]] = None           # (api_id, api_hash, session) -> port
    reddit_http: Any = None                                                  # the KindHttp the reddit test asks with
    clock: Callable[[], datetime] = _utc_now
    monotonic: Callable[[], float] = time.monotonic
    repo: CredentialsRepository = field(default_factory=CredentialsRepository)
    _tests: Dict[str, TestResult] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.credentials is None:
            if self.box is None and self.env is None:
                self.credentials = default_credentials()
            else:
                self.credentials = StoredCredentials(self.db_url, box=self.box, env=self.env)

    # ------------------------------------------------------------------ listing

    def list(self) -> Dict[str, Any]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            rows = {(row.provider, row.key): row for row in self.repo.list(cur)}
        readable = self.credentials.stored()
        return {"providers": [self._provider_view(spec, rows, readable) for spec in PROVIDERS]}

    def provider(self, provider: str) -> Dict[str, Any]:
        spec = self._spec(provider)
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            rows = {(row.provider, row.key): row for row in self.repo.list(cur) if row.provider == provider}
        return self._provider_view(spec, rows, self.credentials.stored())

    def _provider_view(self, spec: ProviderSpec, rows: Dict[Tuple[str, str], CredentialRow],
                       readable: Dict[Tuple[str, str], str]) -> Dict[str, Any]:
        fields: List[Dict[str, Any]] = []
        for field_spec in spec.fields:
            ident = (spec.provider, field_spec.key)
            row = rows.get(ident)
            view: Dict[str, Any] = {
                "key": field_spec.key, "label": field_spec.label, "hint": field_spec.hint,
                "writable": field_spec.writable,
                "set": False, "last4": None, "updated_at": None, "source": "none", "error": None,
            }
            if row is not None:
                view.update(set=True, source="db", updated_at=iso(row.updated_at),
                            last4=row.last4 if field_spec.show_last4 else None)
                if ident not in readable:
                    view["error"] = "The saved value cannot be read (the secret key changed); save it again"
                    view["set"] = False
            fields.append(view)
        return {
            "provider": spec.provider, "label": spec.label, "description": spec.description,
            "testable": spec.testable, "sign_in": spec.sign_in,
            "configured": bool(fields) and all(f["set"] for f in fields),
            "fields": fields,
            "test": self._test_view(spec.provider, rows),
            "login": self._login_view() if spec.sign_in else None,
        }

    def _test_view(self, provider: str, rows: Dict[Tuple[str, str], CredentialRow]) -> Optional[Dict[str, Any]]:
        tested = [r for (p, _k), r in rows.items() if p == provider and r.last_tested_at is not None]
        memory = self._tests.get(provider)
        if tested:
            row = max(tested, key=lambda r: r.last_tested_at)
            if memory is None or memory.tested_at <= row.last_tested_at:
                return {"ok": row.last_test_ok, "message": row.last_test_message,
                        "tested_at": iso(row.last_tested_at)}
        if memory is not None:
            return {"ok": memory.ok, "message": memory.message, "tested_at": iso(memory.tested_at)}
        return None

    def _login_view(self) -> Optional[Dict[str, Any]]:
        pending = self._live_pending()
        return {"stage": pending.stage} if pending else None

    @staticmethod
    def _spec(provider: str) -> ProviderSpec:
        spec = _SPECS.get(provider)
        if spec is None:
            raise CredentialNotFound(f"Unknown connection: {provider}")
        return spec

    def _field(self, provider: str, key: str) -> FieldSpec:
        spec = self._spec(provider)
        for field_spec in spec.fields:
            if field_spec.key == key:
                return field_spec
        raise CredentialNotFound(f"{spec.label} has no field {key}")

    # ------------------------------------------------------------------ writes

    def _box(self) -> SecretBox:
        if self.box is None:
            try:
                self.box = SecretBox.from_env(self.env, create=True)
            except SecretKeyMissing as exc:
                raise CredentialInvalid(f"Secrets cannot be stored: {exc}") from None
        if getattr(self.credentials, "box", None) is None:
            self.credentials.box = self.box
        return self.box

    def _store(self, provider: str, key: str, value: str, *, show_last4: bool = True) -> None:
        ciphertext = self._box().encrypt(value)
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            self.repo.upsert(cur, provider, key, ciphertext, _last4(value) if show_last4 else None)
        self._tests.pop(provider, None)
        self._invalidate()

    def _invalidate(self) -> None:
        self.credentials.invalidate()
        shared = default_credentials()
        if shared is not self.credentials:
            shared.invalidate()

    def put(self, provider: str, key: str, value: Any) -> Dict[str, Any]:
        field_spec = self._field(provider, key)
        if not field_spec.writable:
            raise CredentialInvalid("The Telegram session is created by signing in")
        self._store(provider, key, normalise_value(provider, key, value), show_last4=field_spec.show_last4)
        return self.provider(provider)

    def delete(self, provider: str, key: str) -> Dict[str, Any]:
        self._field(provider, key)
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            self.repo.delete(cur, provider, key)
        self._tests.pop(provider, None)
        self._invalidate()
        return self.provider(provider)

    def _record_test(self, provider: str, ok: bool, message: str) -> None:
        tested_at = self.clock()
        self._tests[provider] = TestResult(ok, message, tested_at)
        try:
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                self.repo.record_test(cur, provider, ok, message, tested_at)
        except psycopg.Error:
            pass

    # ------------------------------------------------------------------ tests

    async def test(self, provider: str) -> Dict[str, Any]:
        spec = self._spec(provider)
        if not spec.testable:
            raise CredentialInvalid(f"{spec.label} has nothing to test")
        if provider == "substack":
            ok, message = await self._test_substack()
        elif provider == "reddit":
            ok, message = await self._test_reddit()
        else:
            ok, message = await self._test_telegram()
        self._record_test(provider, ok, message)
        return self.provider(provider)

    def _substack_source(self) -> Optional[dict]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, platform, handle_or_url, settings FROM sources
                 WHERE handle_or_url ~* '^https?://([a-z0-9-]+\\.)*substack\\.com(/|$)'
                    OR (settings->>'substack') = 'true'
                 ORDER BY enabled DESC, created_at
                 LIMIT 1
                """
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {"id": str(row[0]), "platform": row[1], "handle_or_url": row[2], "settings": row[3] or {}}

    async def _test_substack(self) -> Tuple[bool, str]:
        source = self._substack_source()
        if self.substack_checker is not None:
            return await self.substack_checker(self.credentials, source)
        from insight_core.ingestion.http import KindHttp
        from insight_core.ingestion.kinds.substack import SubstackKind

        return await SubstackKind(KindHttp(), credentials=self.credentials).check_session(source)

    async def _test_reddit(self) -> Tuple[bool, str]:
        """Reddit gives the app a token: its credentials work."""
        from insight_core.ingestion.http import HttpError, KindHttp
        from insight_core.ingestion.kinds.base import KindUnavailable
        from insight_core.ingestion.kinds.reddit import RedditKind

        try:
            await RedditKind(self.reddit_http or KindHttp(), credentials=self.credentials)._bearer(fresh=True)
        except KindUnavailable as exc:
            return False, exc.reason
        except HttpError as exc:
            return False, f"Reddit did not answer: {str(exc)[:200]}"
        return True, "Reddit accepted the app"

    async def _test_telegram(self) -> Tuple[bool, str]:
        from insight_core.ingestion.kinds.base import KindUnavailable
        from insight_core.ingestion.kinds.telegram_session import (
            LOGIN_HINT,
            PgAdvisorySessionLock,
            TelethonClientFactory,
        )

        factory = (self.telegram_clients(self.credentials) if self.telegram_clients
                   else TelethonClientFactory(credentials=self.credentials))
        lock = self.telegram_lock or PgAdvisorySessionLock(self.db_url)
        try:
            async with lock.try_acquire() as acquired:
                if not acquired:
                    return False, "The Telegram session is in use by a fetch run; try again shortly"
                client = factory.create()
                await client.connect()
                try:
                    if not await client.is_user_authorized():
                        return False, f"Telegram session not authorised; {LOGIN_HINT}"
                    return True, f"Signed in as {_account(await client.get_me())}"
                finally:
                    await client.disconnect()
        except KindUnavailable as exc:
            return False, exc.reason
        except Exception as exc:  # noqa: BLE001 - reported to the owner, never raised
            return False, f"Could not reach Telegram: {type(exc).__name__}"

    # ------------------------------------------------------------------ Telegram sign-in

    # The pending sign-in lives in the database, encrypted: with two API processes the code can reach the one that
    # never sent it.
    PENDING_PROVIDER, PENDING_KEY = "telegram_sign_in", "pending"

    @property
    def _pending(self) -> Optional[PendingLogin]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            ciphertext = self.repo.ciphertexts(cur).get((self.PENDING_PROVIDER, self.PENDING_KEY))
        if ciphertext is None:
            return None
        try:
            return PendingLogin(**json.loads(self._box().decrypt(bytes(ciphertext))))
        except Exception:  # noqa: BLE001 - another key, or a broken row: no sign-in waiting
            return None

    @_pending.setter
    def _pending(self, pending: Optional[PendingLogin]) -> None:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            if pending is None:
                self.repo.delete(cur, self.PENDING_PROVIDER, self.PENDING_KEY)
            else:
                self.repo.upsert(cur, self.PENDING_PROVIDER, self.PENDING_KEY,
                                 self._box().encrypt(json.dumps(asdict(pending))), None)

    def _live_pending(self) -> Optional[PendingLogin]:
        pending = self._pending
        if pending is not None and self.monotonic() >= pending.expires_at:
            self._pending = pending = None
        return pending

    def _api_credentials(self) -> Tuple[int, str]:
        from insight_core.ingestion.kinds.telegram_session import telegram_credentials

        api_id, api_hash, reason = telegram_credentials(credentials=self.credentials)
        if reason:
            raise LoginFailed("Add the Telegram API ID and API hash first")
        return api_id, api_hash

    def _login_client(self, session: str) -> Any:
        api_id, api_hash = self._api_credentials()
        if self.login_clients is not None:
            return self.login_clients(api_id, api_hash, session)
        from insight_core.ingestion.kinds.telegram_session import TelethonLoginClient

        return TelethonLoginClient(api_id, api_hash, session)

    async def _step(self, session: str, step: Callable[[Any], Any]) -> Dict[str, Any]:
        """Run one sign-in step on a fresh client over `session`, mapping its errors."""
        from insight_core.ingestion.kinds.telegram_session import TelegramLoginError, TelegramPasswordNeeded

        client = self._login_client(session)
        try:
            await client.connect()
        except Exception as exc:  # noqa: BLE001
            raise LoginFailed(f"Could not reach Telegram: {type(exc).__name__}") from None
        try:
            try:
                return await step(client)
            except TelegramPasswordNeeded:
                pending = self._pending
                if pending is None:
                    raise LoginFailed("No sign-in in progress; start again") from None
                pending.stage = "password"
                pending.session = client.session_string()
                pending.expires_at = self.monotonic() + LOGIN_TTL_S
                self._pending = pending
                return {"stage": "password"}
            except TelegramLoginError as exc:
                if exc.restart:
                    self._pending = None
                raise LoginFailed(exc.message, retry_after=exc.retry_after) from None
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def _finish(self, client: Any) -> Dict[str, Any]:
        account = _account(await client.get_me())
        self._store("telegram", "session", client.session_string(), show_last4=False)
        self._pending = None
        self._record_test("telegram", True, f"Signed in as {account}")
        return {"stage": "done", "account": account}

    async def login_start(self, phone: Any) -> Dict[str, Any]:
        number = re.sub(r"[\s()\-]", "", str(phone or ""))
        if not _PHONE_RE.match(number):
            raise LoginFailed("Enter the phone number in international format, e.g. +15551234567")
        if not number.startswith("+"):
            number = "+" + number
        self._pending = None

        async def send(client: Any) -> Dict[str, Any]:
            phone_code_hash = await client.send_code(number)
            self._pending = PendingLogin(number, phone_code_hash, client.session_string(), "code",
                                         self.monotonic() + LOGIN_TTL_S)
            return {"stage": "code"}

        return await self._step("", send)

    async def login_code(self, code: Any) -> Dict[str, Any]:
        pending = self._live_pending()
        if pending is None or pending.stage != "code":
            raise LoginFailed("No sign-in waiting for a code; start again")
        digits = re.sub(r"\D", "", str(code or ""))
        if not digits:
            raise LoginFailed("Enter the code Telegram sent you")

        async def sign_in(client: Any) -> Dict[str, Any]:
            await client.sign_in_code(pending.phone, digits, pending.phone_code_hash)
            return await self._finish(client)

        return await self._step(pending.session, sign_in)

    async def login_password(self, password: Any) -> Dict[str, Any]:
        pending = self._live_pending()
        if pending is None or pending.stage != "password":
            raise LoginFailed("No sign-in waiting for a password; start again")
        if not isinstance(password, str) or not password:
            raise LoginFailed("Enter your two-step verification password")

        async def sign_in(client: Any) -> Dict[str, Any]:
            await client.sign_in_password(password)
            return await self._finish(client)

        return await self._step(pending.session, sign_in)

    def login_cancel(self) -> Dict[str, Any]:
        self._pending = None
        return {"stage": None}


def _account(me: Any) -> str:
    username = getattr(me, "username", None)
    if username:
        return f"@{username}"
    name = " ".join(part for part in (getattr(me, "first_name", None), getattr(me, "last_name", None)) if part)
    return name or "your account"


__all__ = [
    "CredentialInvalid",
    "CredentialNotFound",
    "CredentialsService",
    "LoginFailed",
    "PROVIDERS",
    "normalise_value",
]
