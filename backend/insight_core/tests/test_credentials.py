"""Connections: the encrypted credentials store (Mark IX §10.1).

No network: Substack answers through FakeHttp, Telegram through fake clients. The DB-backed
classes commit rows to `credentials`, so they only run against a *_test database and wipe
the table around each test.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.ingestion.credentials import (
    MappingCredentials,
    SecretBox,
    SecretKeyMissing,
    StoredCredentials,
)
from insight_core.ingestion.kinds.substack import EXPIRED_REASON, MISSING_NOTICE, SubstackKind
from insight_core.ingestion.kinds.telegram_session import (
    TelegramLoginError,
    TelegramPasswordNeeded,
    TelethonClientFactory,
    telegram_credentials,
    translate_login_error,
)
from insight_core.ingestion.schedule import availability_from_env
from insight_core.services.credentials_service import (
    CredentialInvalid,
    CredentialNotFound,
    CredentialsService,
    LoginFailed,
    normalise_value,
)
from insight_core.services.operations_service import _credential_notice
from insight_core.tests._db import db_url, requires_db, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp

BASE = "https://kaitchup.substack.com"
SID = "s%3AsecretCookieValue.abcdefWXYZ"
HASH = "0123456789abcdef0123456789abcdef"


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- crypto


class SecretBoxTests(unittest.TestCase):
    def test_roundtrip_and_the_ciphertext_does_not_contain_the_value(self):
        box = SecretBox(SecretBox.generate_key())
        ciphertext = box.encrypt(SID)
        self.assertNotIn(SID.encode(), ciphertext)
        self.assertEqual(box.decrypt(ciphertext), SID)

    def test_another_key_cannot_decrypt_and_the_error_carries_no_value(self):
        ciphertext = SecretBox(SecretBox.generate_key()).encrypt(SID)
        with self.assertRaises(ValueError) as caught:
            SecretBox(SecretBox.generate_key()).decrypt(ciphertext)
        self.assertNotIn(SID, str(caught.exception))

    def test_env_key_wins_and_a_key_file_is_generated_once(self):
        key = SecretBox.generate_key()
        box = SecretBox.from_env({"INSIGHT_SECRET_KEY": key.decode()})
        self.assertEqual(SecretBox(key).decrypt(box.encrypt("x")), "x")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "secret.key")
            env = {"INSIGHT_SECRET_KEY_PATH": path}
            with self.assertRaises(SecretKeyMissing):
                SecretBox.from_env(env)            # reads never create a key
            first = SecretBox.from_env(env, create=True)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            second = SecretBox.from_env(env, create=True)
            self.assertEqual(second.decrypt(first.encrypt("same key")), "same key")


# --------------------------------------------------------------------------- provider


class ProviderStoreOnlyTests(unittest.TestCase):
    def test_a_stored_value_is_returned(self):
        creds = StoredCredentials(load=lambda: {("substack", "sid"): "from-db"})
        self.assertEqual(creds.get("substack", "sid"), "from-db")

    def test_the_environment_is_never_read(self):
        env = {"SUBSTACK_SID": "from-env", "TELEGRAM_API_ID": "7", "TELEGRAM_API_HASH": HASH}
        creds = StoredCredentials(load=lambda: {}, env=env)
        saved = dict(os.environ)
        os.environ.update(env)
        try:
            self.assertIsNone(creds.get("substack", "sid"))
            self.assertIsNone(creds.get("telegram", "api_id"))
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_a_broken_store_reads_as_not_set(self):
        def boom():
            raise psycopg.OperationalError("db down")

        creds = StoredCredentials(load=boom, env={"SUBSTACK_SID": "env"})
        self.assertIsNone(creds.get("substack", "sid"))

    def test_values_are_cached_until_the_ttl_or_an_invalidate(self):
        now = [0.0]
        loads = []
        creds = StoredCredentials(load=lambda: loads.append(1) or {("substack", "sid"): f"v{len(loads)}"},
                                  env={}, ttl_s=10, clock=lambda: now[0])
        self.assertEqual(creds.get("substack", "sid"), "v1")
        now[0] = 5
        self.assertEqual(creds.get("substack", "sid"), "v1")
        now[0] = 11
        self.assertEqual(creds.get("substack", "sid"), "v2")
        creds.invalidate()
        self.assertEqual(creds.get("substack", "sid"), "v3")


class ValueValidationTests(unittest.TestCase):
    def test_a_pasted_cookie_pair_keeps_only_the_value(self):
        self.assertEqual(normalise_value("substack", "sid", f" substack.sid={SID}; Path=/ "), SID)
        self.assertEqual(normalise_value("substack", "sid", f'"{SID}"'), SID)

    def test_invalid_values_are_rejected_without_echoing_them(self):
        for provider, key, value in [("substack", "sid", "has spaces inside"), ("telegram", "api_id", "12ab"),
                                     ("telegram", "api_hash", "short-secret-hash"), ("substack", "sid", ""),
                                     ("substack", "sid", 123)]:
            with self.assertRaises(CredentialInvalid) as caught:
                normalise_value(provider, key, value)
            if value:
                self.assertNotIn(str(value), str(caught.exception))

    def test_the_api_hash_is_lowercased(self):
        self.assertEqual(normalise_value("telegram", "api_hash", HASH.upper()), HASH)


# --------------------------------------------------------------------------- kinds read through the seam


class SubstackSeamTests(unittest.IsolatedAsyncioTestCase):
    def _post(self, slug, words):
        return {"id": 1, "slug": slug, "audience": "only_paid", "wordcount": 1000, "title": "Paid one",
                "canonical_url": f"{BASE}/p/{slug}", "post_date": "2026-10-09T02:50:52Z",
                "body_html": "<p>" + " ".join(["w"] * words) + "</p>"}

    def _http(self, words=1000, extra=None):
        archive = f"{BASE}/api/v1/archive?sort=new&offset=0&limit=12"
        return FakeHttp({archive: json.dumps([{"slug": "free", "audience": "everyone"}, self._post("paid", 0)]),
                         f"{BASE}/api/v1/posts/paid": json.dumps(self._post("paid", words)), **(extra or {})})

    async def test_the_cookie_is_read_at_request_time(self):
        creds = MappingCredentials()
        kind = SubstackKind(FakeHttp(), credentials=creds)
        self.assertEqual(kind._headers(), {})
        self.assertEqual(kind.credential_notice(), MISSING_NOTICE)
        creds.values[("substack", "sid")] = SID
        self.assertEqual(kind._headers(), {"Cookie": f"substack.sid={SID}"})
        self.assertIsNone(kind.credential_notice())
        self.assertIn("Sources → Connections", MISSING_NOTICE)
        self.assertIn("Sources → Connections", EXPIRED_REASON)

    async def test_check_session_reads_the_newest_paid_post(self):
        http = self._http()
        ok, message = await SubstackKind(http, sid=SID).check_session({"handle_or_url": f"{BASE}/"})
        self.assertTrue(ok)
        self.assertIn("Paid one", message)
        self.assertEqual(http.headers_for(f"{BASE}/api/v1/posts/paid")["Cookie"], f"substack.sid={SID}")

    async def test_a_teaser_means_expired(self):
        ok, message = await SubstackKind(self._http(words=100), sid=SID).check_session({"handle_or_url": f"{BASE}/"})
        self.assertFalse(ok)
        self.assertEqual(message, EXPIRED_REASON)

    async def test_without_a_source_the_subscriptions_api_answers(self):
        url = "https://substack.com/api/v1/subscriptions?tvOnly=false"
        ok, message = await SubstackKind(FakeHttp({url: json.dumps({"subscriptions": [{}, {}]})}),
                                         sid=SID).check_session(None)
        self.assertTrue(ok)
        self.assertEqual(message, "Signed in to Substack")
        ok, message = await SubstackKind(FakeHttp({url: ValueError(f"HTTP 403 while fetching {url}")}),
                                         sid=SID).check_session(None)
        self.assertEqual((ok, message), (False, EXPIRED_REASON))

    async def test_no_cookie_and_errors_never_leak_it(self):
        self.assertEqual(await SubstackKind(FakeHttp(), sid="").check_session(None), (False, "No Substack session set"))
        url = "https://substack.com/api/v1/subscriptions?tvOnly=false"
        ok, message = await SubstackKind(FakeHttp({url: RuntimeError(f"boom {SID}")}), sid=SID).check_session(None)
        self.assertFalse(ok)
        self.assertNotIn(SID, message)

    def test_the_health_row_carries_the_kinds_notice(self):
        self.assertEqual(_credential_notice(SubstackKind(FakeHttp(), sid="")), MISSING_NOTICE)
        self.assertIsNone(_credential_notice(SubstackKind(FakeHttp(), sid=SID)))
        self.assertIsNone(_credential_notice(object()))


def _string_session() -> str:
    from telethon.crypto import AuthKey
    from telethon.sessions import StringSession

    session = StringSession()
    session.set_dc(2, "149.154.167.51", 443)
    session.auth_key = AuthKey(os.urandom(256))
    return session.save()


class TelegramSeamTests(unittest.TestCase):
    def test_credentials_come_from_the_provider_with_connections_hints(self):
        api_id, api_hash, reason = telegram_credentials(
            credentials=MappingCredentials({("telegram", "api_id"): "12", ("telegram", "api_hash"): HASH}))
        self.assertEqual((api_id, api_hash, reason), (12, HASH, None))
        _, _, reason = telegram_credentials(credentials=MappingCredentials())
        self.assertIn("API ID", reason)
        self.assertNotIn("TELEGRAM_API_ID", reason)
        self.assertIn("Sources → Connections", reason)

    def test_a_stored_session_string_makes_telegram_available_without_a_file(self):
        creds = MappingCredentials({("telegram", "api_id"): "12", ("telegram", "api_hash"): HASH,
                                    ("telegram", "session"): "1abc"})
        availability = availability_from_env({}, credentials=creds)
        self.assertTrue(availability.telegram_credentials)
        creds.values.pop(("telegram", "session"))
        availability = availability_from_env({}, credentials=creds)
        self.assertFalse(availability.telegram_credentials)
        self.assertIn("Sources → Connections", availability.telegram_reason)

    def test_the_factory_opens_the_stored_string_session_instead_of_the_file(self):
        from telethon.sessions import StringSession

        creds = MappingCredentials({("telegram", "api_id"): "12", ("telegram", "api_hash"): HASH,
                                    ("telegram", "session"): _string_session()})
        client = TelethonClientFactory(credentials=creds).create()
        self.assertIsInstance(client.telethon.session, StringSession)

    def test_without_a_stored_session_telegram_is_unavailable_even_with_a_session_file(self):
        from insight_core.ingestion.kinds.base import KindUnavailable

        creds = MappingCredentials({("telegram", "api_id"): "12", ("telegram", "api_hash"): HASH})
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.session")
            Path(path).touch()
            os.environ["TELEGRAM_SESSION_PATH"] = path
            try:
                with self.assertRaises(KindUnavailable) as caught:
                    TelethonClientFactory(credentials=creds).create()
                availability = availability_from_env({"TELEGRAM_SESSION_PATH": path}, credentials=creds)
            finally:
                os.environ.pop("TELEGRAM_SESSION_PATH")
        self.assertIn("Sources → Connections", caught.exception.reason)
        self.assertFalse(availability.telegram_credentials)
        self.assertIn("Sources → Connections", availability.telegram_reason)

    def test_telethon_sign_in_errors_become_clear_messages(self):
        from telethon import errors

        self.assertIsInstance(translate_login_error(errors.SessionPasswordNeededError(None)), TelegramPasswordNeeded)
        invalid = translate_login_error(errors.PhoneCodeInvalidError(None))
        self.assertIsInstance(invalid, TelegramLoginError)
        self.assertIn("code is not right", invalid.message)
        self.assertFalse(invalid.restart)
        self.assertIn("password is not right", translate_login_error(errors.PasswordHashInvalidError(None)).message)
        flood = translate_login_error(errors.FloodWaitError(None, capture=42))
        self.assertEqual(flood.retry_after, 42)
        self.assertIn("42 seconds", flood.message)
        self.assertTrue(translate_login_error(errors.PhoneCodeExpiredError(None)).restart)
        other = RuntimeError("x")
        self.assertIs(translate_login_error(other), other)


# --------------------------------------------------------------------------- service (DB)


class FakeLoginClient:
    """The sign-in port. script: {"code": exc|None, "password": exc|None}."""

    instances: list = []

    def __init__(self, api_id, api_hash, session, script):
        self.args = (api_id, api_hash, session)
        self.script = script
        self.calls: list = []
        self.session = session or "fresh"
        FakeLoginClient.instances.append(self)

    async def connect(self):
        self.calls.append("connect")

    async def disconnect(self):
        self.calls.append("disconnect")

    async def send_code(self, phone):
        self.calls.append(("send_code", phone))
        error = self.script.get("send")
        if error:
            raise error
        self.session = "after-send"
        return "hash-1"

    async def sign_in_code(self, phone, code, phone_code_hash):
        self.calls.append(("sign_in_code", phone, code, phone_code_hash))
        error = self.script.get("code")
        if callable(error):
            error = error()
        if error:
            raise error
        self.session = "AUTHORISED-SESSION"

    async def sign_in_password(self, password):
        self.calls.append(("sign_in_password",))
        error = self.script.get("password")
        if callable(error):
            error = error()
        if error:
            raise error
        self.session = "AUTHORISED-SESSION"

    async def get_me(self):
        return SimpleNamespace(username="owner", first_name="O", last_name=None)

    def session_string(self):
        return self.session


class FakeLock:
    def __init__(self, acquired=True):
        self.acquired = acquired

    def try_acquire(self):
        import contextlib

        @contextlib.asynccontextmanager
        async def cm():
            yield self.acquired

        return cm()


class FakeTgClient:
    def __init__(self, authorised=True):
        self.authorised = authorised
        self.calls = []

    async def connect(self):
        self.calls.append("connect")

    async def disconnect(self):
        self.calls.append("disconnect")

    async def is_user_authorized(self):
        return self.authorised

    async def get_me(self):
        return SimpleNamespace(username=None, first_name="Ada", last_name="L")


def _wipe():
    with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM credentials")


@requires_db
class CredentialsMigrationTests(unittest.TestCase):
    def test_the_credentials_table_has_the_spec_columns(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                            WHERE table_name = 'credentials' ORDER BY ordinal_position""")
            columns = dict(cur.fetchall())
            cur.execute("""SELECT a.attname FROM pg_index i
                             JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                            WHERE i.indrelid = 'credentials'::regclass AND i.indisprimary""")
            primary = {row[0] for row in cur.fetchall()}
        self.assertEqual(columns["ciphertext"], "bytea")
        self.assertEqual(columns["last_test_ok"], "boolean")
        self.assertEqual(set(columns), {"provider", "key", "ciphertext", "last4", "updated_at",
                                        "last_tested_at", "last_test_ok", "last_test_message"})
        self.assertEqual(primary, {"provider", "key"})


@requires_test_db
class CredentialsServiceTests(unittest.TestCase):
    def setUp(self):
        _wipe()
        self.addCleanup(_wipe)
        self.env = {}
        self.box = SecretBox(SecretBox.generate_key())
        self.checks = []
        FakeLoginClient.instances = []
        self.script: dict = {}
        self.now = [0.0]
        self.tg_client = FakeTgClient()
        self.service = self._service()

    def _service(self, **overrides):
        async def substack_checker(creds, source):
            self.checks.append((creds.get("substack", "sid"), source))
            return (creds.get("substack", "sid") == SID, "Full text readable" if creds.get("substack", "sid") == SID
                    else EXPIRED_REASON)

        options = dict(
            box=self.box, env=self.env, substack_checker=substack_checker,
            telegram_clients=lambda creds: SimpleNamespace(create=lambda: self.tg_client),
            telegram_lock=FakeLock(),
            login_clients=lambda api_id, api_hash, session: FakeLoginClient(api_id, api_hash, session, self.script),
            monotonic=lambda: self.now[0],
        )
        options.update(overrides)
        return CredentialsService(db_url(), **options)

    def _field(self, view, key):
        return next(f for f in view["fields"] if f["key"] == key)

    def _provider(self, listing, provider):
        return next(p for p in listing["providers"] if p["provider"] == provider)

    def test_listing_names_every_provider_and_public_feeds_need_nothing(self):
        listing = self.service.list()
        self.assertEqual([p["provider"] for p in listing["providers"]],
                         ["substack", "telegram", "reddit", "youtube"])
        reddit = self._provider(listing, "reddit")
        self.assertFalse(reddit["needed"])
        self.assertEqual(reddit["fields"], [])
        sid = self._field(self._provider(listing, "substack"), "sid")
        self.assertEqual((sid["set"], sid["source"], sid["last4"]), (False, "none", None))
        self.assertNotIn("env", sid)

    def test_a_saved_value_is_encrypted_and_never_echoed(self):
        view = self.service.put("substack", "sid", f"substack.sid={SID}")
        sid = self._field(view, "sid")
        self.assertEqual((sid["set"], sid["source"], sid["last4"]), (True, "db", SID[-4:]))
        self.assertIsNotNone(sid["updated_at"])
        dumped = json.dumps([view, self.service.list()])
        self.assertNotIn(SID, dumped)
        self.assertNotIn(SID[:-4], dumped)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT ciphertext FROM credentials WHERE provider = 'substack' AND key = 'sid'")
            ciphertext = bytes(cur.fetchone()[0])
        self.assertNotIn(SID.encode(), ciphertext)
        self.assertEqual(self.box.decrypt(ciphertext), SID)
        self.assertEqual(self.service.credentials.get("substack", "sid"), SID)

    def test_env_values_are_ignored_and_delete_leaves_the_field_not_set(self):
        self.env["SUBSTACK_SID"] = "env-cookie-value-1234"
        service = self._service()
        self.assertEqual(self._field(service.provider("substack"), "sid")["set"], False)
        service.put("substack", "sid", SID)
        self.assertEqual(service.credentials.get("substack", "sid"), SID)
        view = service.delete("substack", "sid")
        self.assertEqual((self._field(view, "sid")["set"], self._field(view, "sid")["source"]), (False, "none"))
        self.assertIsNone(service.credentials.get("substack", "sid"))

    def test_a_value_saved_with_another_key_reads_as_unreadable(self):
        self.service.put("substack", "sid", SID)
        other = self._service(box=SecretBox(SecretBox.generate_key()))
        sid = self._field(other.provider("substack"), "sid")
        self.assertFalse(sid["set"])
        self.assertIn("save it again", sid["error"])
        self.assertIsNone(other.credentials.get("substack", "sid"))

    def test_unknown_fields_and_the_session_are_not_writable(self):
        with self.assertRaises(CredentialNotFound):
            self.service.put("myspace", "sid", "x")
        with self.assertRaises(CredentialNotFound):
            self.service.put("substack", "password", "x")
        with self.assertRaises(CredentialInvalid):
            self.service.put("telegram", "session", "1abc")
        with self.assertRaises(CredentialInvalid):
            run(self.service.test("reddit"))

    def test_the_substack_test_is_recorded_and_a_new_value_clears_it(self):
        self.service.put("substack", "sid", "stale-cookie-value")
        view = run(self.service.test("substack"))
        self.assertEqual((view["test"]["ok"], view["test"]["message"]), (False, EXPIRED_REASON))
        self.service.put("substack", "sid", SID)
        self.assertIsNone(self.service.provider("substack")["test"])
        view = run(self.service.test("substack"))
        self.assertTrue(view["test"]["ok"])
        fresh = self._service()      # persisted, not only in this process
        self.assertTrue(fresh.provider("substack")["test"]["ok"])
        self.assertNotIn(SID, json.dumps(view))

    def test_the_telegram_test_connects_and_names_the_account(self):
        view = run(self.service.test("telegram"))
        self.assertEqual((view["test"]["ok"], view["test"]["message"]), (True, "Signed in as Ada L"))
        self.assertEqual(self.tg_client.calls, ["connect", "disconnect"])
        self.tg_client = FakeTgClient(authorised=False)
        self.assertFalse(run(self.service.test("telegram"))["test"]["ok"])
        busy = self._service(telegram_lock=FakeLock(acquired=False))
        self.assertIn("in use", run(busy.test("telegram"))["test"]["message"])

    def _with_api(self):
        self.service.put("telegram", "api_id", "12345")
        self.service.put("telegram", "api_hash", HASH)

    def test_sign_in_needs_the_api_credentials_first(self):
        with self.assertRaises(LoginFailed) as caught:
            run(self.service.login_start("+15551234567"))
        self.assertIn("API ID", caught.exception.message)

    def test_sign_in_with_a_code_saves_the_session_encrypted_and_never_returns_it(self):
        self._with_api()
        self.assertEqual(run(self.service.login_start("+1 555 123-4567")), {"stage": "code"})
        sender = FakeLoginClient.instances[-1]
        self.assertEqual(sender.args, (12345, HASH, ""))
        self.assertIn(("send_code", "+15551234567"), sender.calls)
        self.assertEqual(self._provider(self.service.list(), "telegram")["login"], {"stage": "code"})
        result = run(self.service.login_code(" 12 345 "))
        self.assertEqual(result, {"stage": "done", "account": "@owner"})
        signer = FakeLoginClient.instances[-1]
        self.assertEqual(signer.args[2], "after-send")       # the auth key the code was sent on
        self.assertIn(("sign_in_code", "+15551234567", "12345", "hash-1"), signer.calls)
        self.assertEqual(self.service.credentials.get("telegram", "session"), "AUTHORISED-SESSION")
        view = self.service.provider("telegram")
        session = self._field(view, "session")
        self.assertEqual((session["set"], session["source"], session["last4"]), (True, "db", None))
        self.assertIsNone(view["login"])
        self.assertTrue(view["test"]["ok"])
        self.assertNotIn("AUTHORISED-SESSION", json.dumps([result, view, self.service.list()]))

    def test_two_step_verification_asks_for_the_password(self):
        self._with_api()
        self.script["code"] = TelegramPasswordNeeded()
        run(self.service.login_start("+15551234567"))
        self.assertEqual(run(self.service.login_code("11111")), {"stage": "password"})
        self.script["password"] = TelegramLoginError("That password is not right; try again")
        with self.assertRaises(LoginFailed) as caught:
            run(self.service.login_password("wrong"))
        self.assertIn("password is not right", caught.exception.message)
        self.script["password"] = None
        self.assertEqual(run(self.service.login_password("right")), {"stage": "done", "account": "@owner"})
        self.assertEqual(self.service.credentials.get("telegram", "session"), "AUTHORISED-SESSION")

    def test_a_wrong_code_can_be_retried_and_an_expired_one_restarts(self):
        self._with_api()
        run(self.service.login_start("+15551234567"))
        self.script["code"] = TelegramLoginError("That code is not right; check it and try again")
        with self.assertRaises(LoginFailed):
            run(self.service.login_code("00000"))
        self.assertEqual(self.service.provider("telegram")["login"], {"stage": "code"})
        self.script["code"] = TelegramLoginError("That code has expired; start the sign-in again", restart=True)
        with self.assertRaises(LoginFailed):
            run(self.service.login_code("00000"))
        self.assertIsNone(self.service.provider("telegram")["login"])
        with self.assertRaises(LoginFailed) as caught:
            run(self.service.login_code("00000"))
        self.assertIn("start again", caught.exception.message)

    def test_a_flood_wait_carries_its_seconds(self):
        self._with_api()
        self.script["send"] = TelegramLoginError("Telegram asks to wait 30 seconds before trying again",
                                                 retry_after=30)
        with self.assertRaises(LoginFailed) as caught:
            run(self.service.login_start("+15551234567"))
        self.assertEqual(caught.exception.retry_after, 30)

    def test_a_pending_sign_in_expires(self):
        self._with_api()
        run(self.service.login_start("+15551234567"))
        self.now[0] = 11 * 60
        with self.assertRaises(LoginFailed):
            run(self.service.login_code("12345"))

    def test_steps_out_of_order_and_bad_input_are_refused(self):
        with self.assertRaises(LoginFailed):
            run(self.service.login_password("pw"))
        self._with_api()
        with self.assertRaises(LoginFailed):
            run(self.service.login_start("not a phone"))
        run(self.service.login_start("+15551234567"))
        with self.assertRaises(LoginFailed):
            run(self.service.login_password("pw"))
        with self.assertRaises(LoginFailed):
            run(self.service.login_code("abc"))


# --------------------------------------------------------------------------- routes


class FakeCredentialsService:
    """CredentialsService as the routes see it; the failures are what Telegram and Substack answer."""

    def __init__(self):
        self.calls = []

    def list(self):
        return {"providers": []}

    def put(self, provider, key, value):
        self.calls.append(("put", provider, key, value))
        if provider == "nope":
            raise CredentialNotFound("Unknown connection: nope")
        if value == "bad":
            raise CredentialInvalid("That does not look like a substack.sid cookie value")
        return {"provider": provider, "fields": [{"key": key, "set": True, "last4": "WXYZ"}]}

    def delete(self, provider, key):
        return {"provider": provider}

    async def test(self, provider):
        raise RuntimeError(f"driver error with {SID}")

    async def login_start(self, phone):
        raise LoginFailed("Telegram asks to wait 30 seconds before trying again", retry_after=30)

    async def login_code(self, code):
        return {"stage": "password"}

    async def login_password(self, password):
        raise LoginFailed("That password is not right; try again")

    def login_cancel(self):
        return {"stage": None}


class CredentialRouteTests(unittest.TestCase):
    def setUp(self):
        import main
        from insight_core.services import registry

        self.main = main
        self.service = FakeCredentialsService()
        self.addCleanup(registry.use, registry.use(SimpleNamespace(credentials=self.service)))

    def call(self, method, path, payload=None):
        from insight_core.tests._asgi import call

        return call(self.main.app, method, path, json_body=payload)

    def test_put_passes_the_value_and_returns_the_view(self):
        status, _, view = self.call("PUT", "/api/credentials/substack/sid", {"value": SID})
        self.assertEqual(status, 200)
        self.assertEqual(self.service.calls, [("put", "substack", "sid", SID)])
        self.assertNotIn(SID, json.dumps(view))

    def test_errors_map_to_status_codes_without_echoing_values(self):
        self.assertEqual(self.call("PUT", "/api/credentials/nope/sid", {"value": "x"})[0], 404)
        status, _, body = self.call("PUT", "/api/credentials/substack/sid", {"value": "bad"})
        self.assertEqual((status, body["detail"]), (400, "That does not look like a substack.sid cookie value"))
        status, headers, _ = self.call("POST", "/api/credentials/telegram/login/start", {"phone": "+1"})
        self.assertEqual((status, headers["retry-after"]), (429, "30"))
        self.assertEqual(self.call("POST", "/api/credentials/telegram/login/password", {"password": "pw"})[0], 400)
        with self.assertLogs("main", "ERROR"):
            status, _, body = self.call("POST", "/api/credentials/substack/test")
        self.assertEqual(status, 500)
        self.assertNotIn(SID, body["detail"])

    def test_the_sign_in_steps_answer_their_stage(self):
        self.assertEqual(self.call("POST", "/api/credentials/telegram/login/code", {"code": "1"})[2], {"stage": "password"})
        self.assertEqual(self.call("POST", "/api/credentials/telegram/login/cancel")[2], {"stage": None})
        self.assertEqual(self.call("GET", "/api/credentials")[2], {"providers": []})


if __name__ == "__main__":
    unittest.main()
