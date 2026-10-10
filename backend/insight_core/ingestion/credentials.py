"""The credential seam (Mark IX §10.1): where a source kind reads a secret.

The owner adds secrets in Sources → Connections; they are stored encrypted in the
`credentials` table (db/repo_credentials.py). That store is the only place a secret is
read from: no API key comes from the environment. A one-off move of an old .env into the
store is scripts/import_env_secrets.py.

- CredentialProvider: get(provider, key) -> the plaintext value, or None. Kinds hold one and
  call it at request time, so a value saved in the UI applies without a restart.
- MappingCredentials: a fixed {(provider, key): value} (tests).
- StoredCredentials: the database only. Decrypted values are cached
  for a few seconds per process; the API process invalidates its cache on every write.
- SecretBox: Fernet over INSIGHT_SECRET_KEY, or a key generated once into
  /app/secrets/secret.key (a named volume shared by the API and ingestion containers).

Never logs a value, never puts one in an exception message. Import-light: cryptography and
psycopg are imported where they are used.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

DEFAULT_SECRET_KEY_PATH = "/app/secrets/secret.key"
CACHE_TTL_S = 15.0
CONNECTIONS_HINT = "Sources → Connections"

class CredentialProvider(Protocol):
    def get(self, provider: str, key: str) -> Optional[str]: ...


def _clean(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


class MappingCredentials:
    def __init__(self, values: Optional[Mapping[Tuple[str, str], str]] = None) -> None:
        self.values = dict(values or {})

    def get(self, provider: str, key: str) -> Optional[str]:
        return _clean(self.values.get((provider, key)))


class SecretKeyMissing(RuntimeError):
    """No INSIGHT_SECRET_KEY and no key file (reads), or the key file cannot be written."""


class SecretBox:
    """Fernet encryption of credential values. The key never leaves this object."""

    def __init__(self, key: bytes) -> None:
        from cryptography.fernet import Fernet

        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        """Raises ValueError (no detail) when the ciphertext was made with another key."""
        from cryptography.fernet import InvalidToken

        try:
            return self._fernet.decrypt(bytes(ciphertext)).decode("utf-8")
        except InvalidToken:
            raise ValueError("credential cannot be decrypted with this secret key") from None

    @staticmethod
    def generate_key() -> bytes:
        from cryptography.fernet import Fernet

        return Fernet.generate_key()

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None, *, create: bool = False) -> "SecretBox":
        """INSIGHT_SECRET_KEY, else the key file (INSIGHT_SECRET_KEY_PATH, default
        /app/secrets/secret.key). With create=True a missing file is generated once
        (O_EXCL, so two containers starting together agree on one key)."""
        env = os.environ if env is None else env
        raw = (env.get("INSIGHT_SECRET_KEY") or "").strip()
        if raw:
            return cls(raw.encode("ascii"))
        path = (env.get("INSIGHT_SECRET_KEY_PATH") or "").strip() or DEFAULT_SECRET_KEY_PATH
        key = _read_key(path)
        if key is None and create:
            key = _create_key(path)
        if key is None:
            raise SecretKeyMissing(f"no INSIGHT_SECRET_KEY and no key file at {path}")
        return cls(key)


def _read_key(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as handle:
            key = handle.read().strip()
    except FileNotFoundError:
        return None
    return key or None


def _create_key(path: str) -> bytes:
    key = SecretBox.generate_key()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existing = _read_key(path)
        if existing:
            return existing
        raise SecretKeyMissing(f"the key file at {path} is empty") from None
    except OSError as exc:
        raise SecretKeyMissing(f"cannot write the key file at {path}: {exc.strerror}") from None
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    logger.info("Generated the credentials secret key at %s", path)
    return key


class StoredCredentials:
    """The database only. Any database or key problem reads as "not stored" (logged without
    values). `env` is read for the secret key (INSIGHT_SECRET_KEY / _PATH) only."""

    def __init__(
        self,
        db_url: Optional[str] = None,
        *,
        box: Optional[SecretBox] = None,
        env: Optional[Mapping[str, str]] = None,
        ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
        load: Optional[Callable[[], Dict[Tuple[str, str], str]]] = None,
    ) -> None:
        self.db_url = db_url
        self.box = box
        self._env_mapping = env
        self.ttl_s = ttl_s
        self.clock = clock
        self._load = load or self._load_from_db
        self._cache: Optional[Dict[Tuple[str, str], str]] = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def get(self, provider: str, key: str) -> Optional[str]:
        return self.stored().get((provider, key)) or None

    def stored(self) -> Dict[Tuple[str, str], str]:
        with self._lock:
            if self._cache is None or self.clock() - self._loaded_at >= self.ttl_s:
                try:
                    self._cache = self._load()
                except Exception as exc:  # noqa: BLE001 - reads as "not set"
                    logger.warning("Stored credentials unavailable (%s); reading as not set",
                                   type(exc).__name__)
                    self._cache = {}
                self._loaded_at = self.clock()
            return self._cache

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None

    def _load_from_db(self) -> Dict[Tuple[str, str], str]:
        db_url = self.db_url or os.getenv("DATABASE_URL")
        if not db_url:
            return {}
        import psycopg

        from insight_core.db.repo_credentials import CredentialsRepository

        with psycopg.connect(db_url, connect_timeout=5) as conn, conn.cursor() as cur:
            rows = CredentialsRepository().ciphertexts(cur)
        if not rows:
            return {}
        box = self.box
        if box is None:
            try:
                box = SecretBox.from_env(self._env_mapping)
            except SecretKeyMissing:
                logger.warning("Stored credentials exist but no secret key is available")
                return {}
            self.box = box
        values: Dict[Tuple[str, str], str] = {}
        for (provider, key), ciphertext in rows.items():
            try:
                values[(provider, key)] = box.decrypt(ciphertext)
            except ValueError:
                logger.warning("Stored credential %s/%s cannot be decrypted; set it again", provider, key)
        return values


_default: Optional[StoredCredentials] = None
_default_lock = threading.Lock()


def default_credentials() -> StoredCredentials:
    """The process-wide provider every real kind uses (built lazily, no I/O until get)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = StoredCredentials()
        return _default


__all__ = [
    "CONNECTIONS_HINT",
    "CredentialProvider",
    "MappingCredentials",
    "SecretBox",
    "SecretKeyMissing",
    "StoredCredentials",
    "default_credentials",
]
