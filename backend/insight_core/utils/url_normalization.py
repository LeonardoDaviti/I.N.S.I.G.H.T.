"""Deterministic URL normalization helpers for evidence processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "ref",
    "ref_src",
    "spm",
    "si",
    "source",
    "ved",
}

HOST_ALIASES = {
    "m.youtube.com": "youtube.com",
    "music.youtube.com": "youtube.com",
    "www.youtube.com": "youtube.com",
    "youtube.com": "youtube.com",
    "youtu.be": "youtube.com",
    "mobile.twitter.com": "x.com",
    "twitter.com": "x.com",
    "www.twitter.com": "x.com",
    "old.reddit.com": "reddit.com",
    "np.reddit.com": "reddit.com",
    "www.reddit.com": "reddit.com",
    "reddit.com": "reddit.com",
    "www.github.com": "github.com",
    "github.com": "github.com",
}

DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class NormalizedURL:
    """Container for a normalized URL and its derived host."""

    canonical_url: Optional[str]
    normalized_url: Optional[str]
    host: Optional[str]


def normalize_url(value: str | None) -> Optional[str]:
    """Return a machine-normalized URL for comparisons."""
    return _normalize_url(value).normalized_url


def canonicalize_url(value: str | None) -> Optional[str]:
    """Return a canonical URL for display and comparisons."""
    return _normalize_url(value).canonical_url


def extract_url_host(value: str | None) -> Optional[str]:
    """Extract a stable host name from a URL."""
    return _normalize_url(value).host


def _normalize_url(value: str | None) -> NormalizedURL:
    if not isinstance(value, str):
        return NormalizedURL(None, None, None)

    raw = value.strip()
    if not raw:
        return NormalizedURL(None, None, None)

    parsed = _parse_url(raw)
    if not parsed:
        return NormalizedURL(None, None, None)

    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        return NormalizedURL(None, None, None)

    host = HOST_ALIASES.get(host, host)
    if host.startswith("www."):
        host = host[4:]
    path = _normalize_path(parsed.path, host, parsed.query)
    query = _normalize_query(host, parsed.query, parsed.path)
    fragment = ""

    if host == "youtube.com":
        video_id = _extract_youtube_video_id(parsed)
        if video_id:
            path = "/watch"
            query = urlencode([("v", video_id)])
        elif parsed.path == "/feeds/videos.xml":
            path = "/feeds/videos.xml"
        else:
            path = _normalize_path(parsed.path, host, parsed.query)

    netloc = host
    if parsed.port and parsed.port != DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{parsed.port}"

    canonical = urlunparse((scheme, netloc, path, "", query, fragment))
    normalized = canonical
    return NormalizedURL(canonical, normalized, host)


def _parse_url(raw: str):
    if "://" not in raw:
        candidate = f"https://{raw.lstrip('/')}"
    else:
        candidate = raw

    parsed = urlparse(candidate)
    if not parsed.scheme or not parsed.netloc:
        return None
    return parsed


def _normalize_path(path: str, host: str, query: str) -> str:
    cleaned = path or ""
    if not cleaned:
        return "/"

    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"

    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")

    if cleaned != "/":
        cleaned = cleaned.rstrip("/")
        if not cleaned:
            cleaned = "/"

    return cleaned


def _normalize_query(host: str, query: str, path: str) -> str:
    items = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_KEYS:
            continue
        if any(lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        items.append((key, value))

    if host == "youtube.com":
        preferred = []
        seen = set()
        for key, value in items:
            if key not in {"v", "t", "list"}:
                continue
            if key in seen:
                continue
            preferred.append((key, value))
            seen.add(key)
        items = preferred or items

    items.sort(key=lambda item: (item[0], item[1]))
    return urlencode(items, doseq=True)


def _extract_youtube_video_id(parsed) -> Optional[str]:
    path_segments = [segment for segment in parsed.path.split("/") if segment]

    if parsed.netloc.lower() == "youtu.be" and path_segments:
        return path_segments[0]

    if "youtube.com" in parsed.netloc.lower():
        if parsed.path == "/watch":
            for key, value in parse_qsl(parsed.query, keep_blank_values=True):
                if key == "v" and value:
                    return value
        if path_segments and path_segments[0] in {"shorts", "embed"} and len(path_segments) >= 2:
            return path_segments[1]

    return None
