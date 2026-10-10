"""Credentials: encrypted secrets per (provider, key) (table credentials, migration 0024).

Write-only by design: list() never selects the ciphertext, and only ciphertexts() (used by
ingestion.credentials.StoredCredentials to decrypt in-process) reads it. Every method takes
the caller's cursor and never commits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from psycopg import Cursor

MAX_TEST_MESSAGE = 500


@dataclass(frozen=True)
class CredentialRow:
    provider: str
    key: str
    last4: Optional[str]
    updated_at: Optional[datetime]
    last_tested_at: Optional[datetime]
    last_test_ok: Optional[bool]
    last_test_message: Optional[str]


class CredentialsRepository:
    def list(self, cur: Cursor) -> List[CredentialRow]:
        cur.execute(
            """
            SELECT provider, key, last4, updated_at, last_tested_at, last_test_ok, last_test_message
              FROM credentials
             ORDER BY provider, key
            """
        )
        return [CredentialRow(*row) for row in cur.fetchall()]

    def ciphertexts(self, cur: Cursor) -> Dict[Tuple[str, str], bytes]:
        cur.execute("SELECT provider, key, ciphertext FROM credentials")
        return {(provider, key): bytes(ciphertext) for provider, key, ciphertext in cur.fetchall()}

    def upsert(self, cur: Cursor, provider: str, key: str, ciphertext: bytes, last4: Optional[str]) -> None:
        """A new value clears its provider's test status: the old result no longer applies."""
        cur.execute(
            """
            INSERT INTO credentials (provider, key, ciphertext, last4, updated_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (provider, key) DO UPDATE
               SET ciphertext = EXCLUDED.ciphertext,
                   last4 = EXCLUDED.last4,
                   updated_at = now()
            """,
            (provider, key, ciphertext, last4),
        )
        self.clear_test(cur, provider)

    def delete(self, cur: Cursor, provider: str, key: str) -> bool:
        cur.execute("DELETE FROM credentials WHERE provider = %s AND key = %s", (provider, key))
        deleted = cur.rowcount > 0
        if deleted:
            self.clear_test(cur, provider)
        return deleted

    def clear_test(self, cur: Cursor, provider: str) -> None:
        cur.execute(
            """
            UPDATE credentials
               SET last_tested_at = NULL, last_test_ok = NULL, last_test_message = NULL
             WHERE provider = %s
            """,
            (provider,),
        )

    def record_test(self, cur: Cursor, provider: str, ok: bool, message: str, tested_at: datetime) -> int:
        cur.execute(
            """
            UPDATE credentials
               SET last_tested_at = %s, last_test_ok = %s, last_test_message = %s
             WHERE provider = %s
            """,
            (tested_at, ok, (message or "")[:MAX_TEST_MESSAGE], provider),
        )
        return cur.rowcount
