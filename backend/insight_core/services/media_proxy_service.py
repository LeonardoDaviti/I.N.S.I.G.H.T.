"""Media proxy: a post's images, fetched when the reader shows them (issue 0006).

Nothing is stored here. GET /api/media streams one image of one post; the frontend nginx
caches the answer for 24 hours (proxy_cache, inactive=24h) and the browser keeps it as
long, so an image is fetched once a day at most and is gone a day after it was last seen.

Only an image the post itself carries can be fetched: one of its media_urls, its feed
thumbnail (a YouTube frame) or an <img> of its body. That and the address check below
keep this from being an open proxy: a host that resolves to a private, loopback or
link-local address is refused unless it is one of the LAN bridges the feeds come from
(telegram.local, nitter.local, RSS_SKIP_TLS_VERIFY_HOSTS, INSIGHT_MEDIA_PRIVATE_HOSTS).
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Sequence, Set

import psycopg

from insight_core.db import database as db
from insight_core.utils.media import clean_url, feed_thumb, post_media

MAX_BYTES = 10 * 1024 * 1024
TIMEOUT_SECONDS = 15
MAX_REDIRECTS = 3
USER_AGENT = "Mozilla/5.0 (compatible; INSIGHT media proxy)"
DEFAULT_PRIVATE_HOSTS = ("telegram.local", "nitter.local")
_IMG_SRC_RE = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")


class MediaNotAllowed(Exception):
    """The URL is not an image of this post, or its host is not one we fetch from (404)."""


class MediaFetchFailed(Exception):
    """The origin failed, answered with something that is not an image, or too much (502)."""


@dataclass(frozen=True)
class MediaResponse:
    body: bytes
    content_type: str


def _env_hosts(*names: str) -> Set[str]:
    hosts: Set[str] = set()
    for name in names:
        hosts |= {h.strip().lower() for h in os.getenv(name, "").split(",") if h.strip()}
    return hosts


def body_image_urls(body: Optional[str]) -> List[str]:
    """Every image of a post body: <img src> and Markdown ![](url), entity-decoded as a
    browser reads them. The post page renders content_html, or content when there is none."""
    urls: List[str] = []
    for match in _IMG_SRC_RE.finditer(body or ""):
        url = clean_url(match.group(1) or match.group(2))
        if url:
            urls.append(url)
    for match in _MD_IMAGE_RE.finditer(body or ""):
        url = clean_url(match.group(1))
        if url:
            urls.append(url)
    return urls


def post_image_urls(post_url: Any, media_urls: Any, content_html: Optional[str],
                    content: Optional[str] = None) -> Set[str]:
    """The images a post may show: what the feed row, the post page and the body render."""
    allowed: Set[str] = {image["url"] for image in post_media(media_urls, post_url)["images"]}
    thumb = feed_thumb(media_urls, post_url)
    if thumb:
        allowed.add(thumb)
    allowed.update(body_image_urls(content_html))
    allowed.update(body_image_urls(content))
    return allowed


def is_public_address(address: str) -> bool:
    """Globally routable: not private, loopback, link-local, CGNAT/Tailscale (100.64/10)..."""
    ip = ipaddress.ip_address(address.split("%")[0])
    return ip.is_global and not ip.is_multicast


class MediaProxyService:
    def __init__(
        self,
        db_url: str,
        *,
        private_hosts: Optional[Iterable[str]] = None,
        resolve: Callable[[str], Sequence[str]] | None = None,
        opener: Callable[[urllib.request.Request, float, bool], Any] | None = None,
    ) -> None:
        self.db_url = db_url
        self.private_hosts = set(private_hosts) if private_hosts is not None else (
            set(DEFAULT_PRIVATE_HOSTS) | _env_hosts("RSS_SKIP_TLS_VERIFY_HOSTS", "INSIGHT_MEDIA_PRIVATE_HOSTS")
        )
        self._resolve = resolve or self._resolve_host
        # opener(request, timeout, insecure_tls) -> response; insecure only for the LAN bridges
        # (self-signed certificates), exactly as ingestion fetches them.
        self._opener = opener or _open

    # ------------------------------------------------------------------ the request

    def fetch(self, post_id: str, url: str) -> MediaResponse:
        """The image `url` of post `post_id`. Raises MediaNotAllowed or MediaFetchFailed."""
        wanted = clean_url(url)
        if not wanted or wanted not in self._allowed(post_id):
            raise MediaNotAllowed("not an image of this post")
        return self._download(wanted)

    def _allowed(self, post_id: str) -> Set[str]:
        try:
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                cur.execute("SELECT url, media_urls, content_html, content FROM posts WHERE id = %s::uuid",
                            (post_id,))
                row = cur.fetchone()
        except (psycopg.errors.InvalidTextRepresentation, psycopg.DataError):
            raise MediaNotAllowed("no such post")
        if not row:
            raise MediaNotAllowed("no such post")
        return post_image_urls(row[0], row[1], row[2], row[3])

    # ------------------------------------------------------------------ the origin

    def check_host(self, url: str) -> urllib.parse.SplitResult:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise MediaNotAllowed("not an http(s) URL")
        host = parts.hostname.lower()
        if host in self.private_hosts:
            return parts
        try:
            addresses = self._resolve(host)
        except OSError:
            raise MediaFetchFailed(f"cannot resolve {host}")
        if not addresses or not all(is_public_address(a) for a in addresses):
            raise MediaNotAllowed(f"{host} is not a public host")
        return parts

    def _download(self, url: str) -> MediaResponse:
        for _ in range(MAX_REDIRECTS + 1):
            parts = self.check_host(url)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
            insecure = parts.scheme == "https" and parts.hostname.lower() in self.private_hosts
            try:
                response = self._opener(request, TIMEOUT_SECONDS, insecure)
            except urllib.error.HTTPError as exc:
                location = exc.headers.get("Location") if exc.code in (301, 302, 303, 307, 308) else None
                if location:
                    url = urllib.parse.urljoin(url, location)   # re-checked at the top of the loop
                    continue
                raise MediaFetchFailed(f"HTTP {exc.code}")
            except (urllib.error.URLError, OSError) as exc:
                raise MediaFetchFailed(str(getattr(exc, "reason", exc)))
            with response:
                content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if not content_type.startswith("image/"):
                    raise MediaFetchFailed(f"not an image ({content_type or 'no type'})")
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise MediaFetchFailed("larger than 10 MB")
                return MediaResponse(body, content_type)
        raise MediaFetchFailed("too many redirects")

    @staticmethod
    def _resolve_host(host: str) -> List[str]:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def _open(request: urllib.request.Request, timeout: float, insecure_tls: bool):
    context = ssl._create_unverified_context() if insecure_tls else ssl.create_default_context()
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=context))
    return opener.open(request, timeout=timeout)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand every redirect back to _download, so its target goes through check_host too."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None
