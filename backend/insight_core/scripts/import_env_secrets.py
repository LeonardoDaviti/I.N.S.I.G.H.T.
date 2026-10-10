"""One-off: copy the API keys of an old .env into Sources → Connections (S6).

    docker compose exec backend python -m insight_core.scripts.import_env_secrets

Secrets are read only from the encrypted Connections store now. This copies, from the
process environment, TELEGRAM_API_ID, TELEGRAM_API_HASH, SUBSTACK_SID and GEMINI_API_KEY (or
GOOGLE_API_KEY) into the store, encrypted by
the same service the UI uses. It skips empty values and template placeholders, never
overwrites a value that is already stored, and prints only the names it stored or
skipped, never a value. Afterwards remove those lines from .env.
"""
from __future__ import annotations

import os
import sys
from typing import List, Mapping, Optional, Protocol, Sequence, Tuple

# (provider, key) -> the environment names to read, first non-empty usable one wins.
SECRETS: Sequence[Tuple[str, str, Tuple[str, ...]]] = (
    ("telegram", "api_id", ("TELEGRAM_API_ID",)),
    ("telegram", "api_hash", ("TELEGRAM_API_HASH",)),
    ("substack", "sid", ("SUBSTACK_SID",)),
    ("gemini", "api_key", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
)
PLACEHOLDER_MARKS = ("your_", "xxx", "changeme")


class SecretStore(Protocol):
    def has(self, provider: str, key: str) -> bool: ...

    def put(self, provider: str, key: str, value: str) -> None: ...


def _problem(provider: str, key: str, value: str) -> Optional[str]:
    """Why `value` is not worth storing, or None. Never echoes the value."""
    if not value:
        return "empty"
    lowered = value.lower()
    if any(mark in lowered for mark in PLACEHOLDER_MARKS):
        return "placeholder"
    if (provider, key) == ("telegram", "api_id") and not value.isdigit():
        return "not an integer"
    return None


def import_env_secrets(env: Mapping[str, str], store: SecretStore) -> Tuple[List[str], List[Tuple[str, str]]]:
    """(stored names, [(skipped name, reason)]). Reasons never contain a value."""
    stored: List[str] = []
    skipped: List[Tuple[str, str]] = []
    for provider, key, names in SECRETS:
        present = [name for name in names if name in env]
        if not present:
            continue
        candidate: Optional[Tuple[str, str]] = None
        for name in present:
            value = str(env.get(name) or "").strip().strip('"').strip("'").strip()
            problem = _problem(provider, key, value)
            if problem is None:
                candidate = (name, value)
                break
            skipped.append((name, problem))
        if candidate is None:
            continue
        name, value = candidate
        if store.has(provider, key):
            skipped.append((name, "already stored"))
            continue
        try:
            store.put(provider, key, value)
        except ValueError as exc:      # CredentialInvalid: its message never echoes the value
            skipped.append((name, f"invalid: {exc}"))
            continue
        stored.append(name)
    return stored, skipped


class ServiceStore:
    """The real store: CredentialsService (encrypts, validates) over DATABASE_URL."""

    def __init__(self, db_url: str) -> None:
        from insight_core.services.credentials_service import CredentialsService

        self.service = CredentialsService(db_url)

    def has(self, provider: str, key: str) -> bool:
        view = self.service.provider(provider)
        return any(f["key"] == key and f["source"] == "db" for f in view["fields"])

    def put(self, provider: str, key: str, value: str) -> None:
        self.service.put(provider, key, value)


def main(env: Optional[Mapping[str, str]] = None, store: Optional[SecretStore] = None) -> int:
    env = os.environ if env is None else env
    if store is None:
        db_url = env.get("DATABASE_URL")
        if not db_url:
            print("DATABASE_URL is not set", file=sys.stderr)
            return 1
        store = ServiceStore(db_url)
    stored, skipped = import_env_secrets(env, store)
    for name in stored:
        print(f"stored  {name}")
    for name, reason in skipped:
        print(f"skipped {name} ({reason})")
    if not stored and not skipped:
        print("nothing to import")
    return 0


if __name__ == "__main__":
    sys.exit(main())
