"""Media proxy: a post's images, fetched when the reader shows them (issue 0006).

Nothing is stored here. GET /api/media streams one image of one post; the frontend nginx
caches the answer for 24 hours (proxy_cache, inactive=24h) and the browser keeps it as
long, so an image is fetched once a day at most and is gone a day after it was last seen.

Only an image the post itself carries can be fetched: one of its media_urls, its feed
thumbnail (a YouTube frame) or an <img> of its body. That and the address check keep this
from being an open proxy. The check is KindHttp's own (ingestion/http.py AddressGuard, issue
0187): a host that resolves to a private, loopback or link-local address is refused unless it
is one of the LAN bridges the feeds come from (telegram.local, nitter.local, NITTER_HOSTS,
TELEGRAM_RSS_HOSTS, INSIGHT_MEDIA_PRIVATE_HOSTS, RSS_SKIP_TLS_VERIFY_HOSTS); every redirect hop
is checked the same way, and the connection goes to the address that was checked.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Set

import psycopg

from insight_core.db import database as db
from insight_core.ingestion.http import MAX_BODY_BYTES, AddressGuard, AddressNotAllowed, HttpError
from insight_core.ingestion.http import is_public_address  # noqa: F401 - the guard's rule, named here as before
from insight_core.utils.media import clean_url, feed_thumb, post_media

MAX_BYTES = MAX_BODY_BYTES
TIMEOUT_SECONDS = 15
USER_AGENT = "Mozilla/5.0 (compatible; INSIGHT media proxy)"
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


class MediaProxyService:
    def __init__(
        self,
        db_url: str,
        *,
        guard: Optional[AddressGuard] = None,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.db_url = db_url
        self.guard = guard or AddressGuard()
        # opener(request, timeout=) -> response: the guard's own (tests give theirs)
        self._open = opener or self.guard.opener().open

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
                # A Telegram album's pictures are its post's (issue 0069).
                cur.execute("SELECT url, media_urls, content_html, content FROM posts"
                            " WHERE id = %s::uuid OR album_of = %s::uuid", (post_id, post_id))
                rows = cur.fetchall()
        except (psycopg.errors.InvalidTextRepresentation, psycopg.DataError):
            raise MediaNotAllowed("no such post")
        if not rows:
            raise MediaNotAllowed("no such post")
        return set().union(*(post_image_urls(row[0], row[1], row[2], row[3]) for row in rows))

    # ------------------------------------------------------------------ the origin

    def _download(self, url: str) -> MediaResponse:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise MediaNotAllowed("not an http(s) URL")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
        try:
            response = self._open(request, timeout=TIMEOUT_SECONDS)
        except AddressNotAllowed as exc:   # the host, or a redirect's, is not one we fetch from
            raise MediaNotAllowed(str(exc)) from None
        except HttpError as exc:            # it doesn't resolve; a redirect to a non-web address
            raise MediaFetchFailed(str(exc)) from None
        except urllib.error.HTTPError as exc:   # an error status, or too many redirects
            raise MediaFetchFailed(f"HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise MediaFetchFailed(str(getattr(exc, "reason", exc))) from None
        with response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                raise MediaFetchFailed(f"not an image ({content_type or 'no type'})")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise MediaFetchFailed("larger than 10 MB")
            return MediaResponse(body, content_type)
