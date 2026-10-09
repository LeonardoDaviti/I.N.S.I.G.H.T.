"""Authorise the Telegram MTProto session: the ONLY interactive Telegram path (spec §B8).

The server never prompts. Without an authorised session every telegram_mtproto source is
reported unavailable; run this once, as an operator, to create it:

    docker compose run --rm -it backend python -m insight_core.scripts.telegram_login

It asks for the phone number, the login code Telegram sends, and the 2FA password if the
account has one (getpass, not echoed), and writes the session to telegram_session_path()
(TELEGRAM_SESSION_PATH, default /app/insight_core/config/telegram/insight.session). config/
is bind-mounted into the backend and ingestion containers, so the session survives image
rebuilds and both processes read it. It holds the same Postgres advisory lock as a fetch
run, so it never writes the SQLite session while a run has it open.

Needs TELEGRAM_API_ID and TELEGRAM_API_HASH (https://my.telegram.org). Not run by any test.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import os
import sys

from insight_core.ingestion.kinds.telegram_session import (
    SESSION_LOCK_KEY,
    normalise_session_path,
    telegram_credentials,
    telegram_session_path,
)


@contextlib.asynccontextmanager
async def _session_lock():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        yield True
        return
    from insight_core.ingestion.ports import PgAdvisoryRunLock

    try:
        async with PgAdvisoryRunLock(db_url, SESSION_LOCK_KEY).try_acquire() as acquired:
            yield acquired
    except Exception as exc:  # noqa: BLE001 - the lock is a courtesy; say so and carry on
        print(f"warning: could not take the session lock ({exc}); make sure no fetch run is active")
        yield True


async def login(session_path: str, *, check_only: bool = False) -> int:
    api_id, api_hash, reason = telegram_credentials()
    if reason:
        print(f"error: {reason} (set it in .env)", file=sys.stderr)
        return 2

    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError

    os.makedirs(os.path.dirname(session_path) or ".", exist_ok=True)
    async with _session_lock() as acquired:
        if not acquired:
            print("error: the Telegram session is in use by a fetch run; try again when it finishes",
                  file=sys.stderr)
            return 3
        client = TelegramClient(session_path, api_id, api_hash, receive_updates=False)
        await client.connect()
        try:
            if await client.is_user_authorized():
                me = await client.get_me()
                print(f"Session already authorised as {getattr(me, 'username', None) or getattr(me, 'id', '?')}: "
                      f"{session_path}")
                return 0
            if check_only:
                print(f"Session at {session_path} is not authorised")
                return 1
            phone = input("Phone number (international format, e.g. +15551234567): ").strip()
            sent = await client.send_code_request(phone)
            code = input("Login code Telegram sent you: ").strip()
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
            except SessionPasswordNeededError:
                await client.sign_in(password=getpass.getpass("2FA password: "))
            me = await client.get_me()
            print(f"Authorised as {getattr(me, 'username', None) or getattr(me, 'id', '?')}; "
                  f"session written to {session_path}")
            return 0
        finally:
            await client.disconnect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Authorise the INSIGHT Telegram MTProto session.")
    parser.add_argument("--session-path", default=None,
                        help="session file (default: TELEGRAM_SESSION_PATH or the config/telegram default)")
    parser.add_argument("--check", action="store_true", help="only report whether the session is authorised")
    args = parser.parse_args(argv)
    # Normalised as the fetch path does, so the printed path is the file Telethon writes.
    session_path = normalise_session_path(args.session_path) if args.session_path else telegram_session_path()
    return asyncio.run(login(session_path, check_only=args.check))


if __name__ == "__main__":
    raise SystemExit(main())
