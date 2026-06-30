"""
Defensive Langfuse (v4, OpenTelemetry) tracing for the Gemini processor.

Everything here is wrapped so tracing can NEVER break a briefing: if Langfuse is
disabled, misconfigured, the SDK is missing, or the host is unreachable, every
function degrades to a no-op.

TLS note: self-hosted Langfuse (e.g. https://langfuse.local) typically uses a
self-signed certificate. The v4 SDK exports spans via the OTLP HTTP exporter,
which uses `requests` and ignores per-session `verify=False`. So for self-hosted
hosts (.local / localhost / private IPs) we force `verify=False` at the requests
layer — matching how the JS extension passes `rejectUnauthorized: false`.
"""
from __future__ import annotations

import ipaddress
import logging
import os
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Cap input/output payloads (briefing prompts can be 100k+ chars).
_MAX_IO_CHARS = 50_000

_client: Optional[Any] = None
_initialized = False


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_enabled() -> bool:
    return _truthy(os.environ.get("LANGFUSE_ENABLED", "false"))


def _host() -> str:
    return os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST") or ""


def _is_self_hosted(host: str) -> bool:
    """True for .local / localhost / private-IP hosts that need TLS verify off."""
    try:
        hostname = urlparse(host).hostname or ""
    except Exception:  # noqa: BLE001
        return False
    if not hostname:
        return False
    if hostname == "localhost" or hostname.endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(hostname).is_private
    except ValueError:
        return False


def _disable_requests_tls_verification() -> None:
    """Force verify=False for the `requests` layer (used by the OTLP exporter).

    Scoped by caller to self-hosted hosts only. Idempotent.
    """
    try:
        import requests

        if getattr(requests.Session.merge_environment_settings, "_insight_no_verify", False):
            return
        _orig = requests.Session.merge_environment_settings

        def _patched(self, url, proxies, stream, verify, cert):  # noqa: ANN001
            settings = _orig(self, url, proxies, stream, verify, cert)
            settings["verify"] = False
            return settings

        _patched._insight_no_verify = True  # type: ignore[attr-defined]
        requests.Session.merge_environment_settings = _patched  # type: ignore[assignment]

        try:
            import urllib3

            urllib3.disable_warnings()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not disable requests TLS verification: %s", exc)


def get_client() -> Optional[Any]:
    """Lazily build the Langfuse v4 client. Returns None if disabled/misconfigured."""
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True

    if not is_enabled():
        _client = None
        return None

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    host = _host()
    if not (public_key and secret_key and host):
        logger.warning("Langfuse enabled but public/secret key or host missing; tracing disabled")
        _client = None
        return None

    if _is_self_hosted(host):
        # Must run before the SDK builds its OTLP exporter.
        _disable_requests_tls_verification()

    try:
        import httpx
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=host,
            httpx_client=httpx.Client(verify=False),
        )
        logger.info("Langfuse v4 tracing enabled (host=%s, TLS verification disabled)", host)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse init failed, tracing disabled: %s", exc)
        _client = None
    return _client


def _truncate(value: str) -> str:
    return (value or "")[:_MAX_IO_CHARS]


class trace_operation:
    """Open a Langfuse trace (root observation) for a top-level operation.

    Generations recorded inside attach to it via OpenTelemetry context (which
    propagates across asyncio.to_thread). No-op when tracing is disabled.
    """

    def __init__(self, name: str, **metadata: Any):
        self.name = name
        self.metadata = metadata
        self._cm = None
        self._span = None

    def __enter__(self):
        client = get_client()
        if client is not None:
            try:
                self._cm = client.start_as_current_observation(name=self.name, as_type="span")
                self._span = self._cm.__enter__()
                try:
                    self._span.update(metadata=self.metadata)
                except Exception:  # noqa: BLE001
                    pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("Langfuse trace start failed: %s", exc)
                self._cm = None
                self._span = None
        return self._span

    def __exit__(self, exc_type, exc, tb):
        if self._cm is not None:
            try:
                self._cm.__exit__(exc_type, exc, tb)
            except Exception:  # noqa: BLE001
                pass
        return False


def record_generation(
    *,
    model: str,
    prompt: str,
    output: str,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Record a single Gemini model attempt as a Langfuse generation. No-op when off."""
    client = get_client()
    if client is None:
        return
    try:
        gen = client.start_observation(
            name="gemini.generate",
            as_type="generation",
            model=model,
            input=_truncate(prompt),
            metadata={"latency_ms": latency_ms, "status": status, "error": error},
        )
        gen.update(
            output=_truncate(output),
            usage_details={"input": int(input_tokens), "output": int(output_tokens)},
        )
        gen.end()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Langfuse record_generation failed: %s", exc)
