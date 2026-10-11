"""substack: a Substack publication, paid posts included when the owner's cookie is set.

The public RSS feed truncates paid posts. The publication's JSON API does not when the
request carries a subscriber's session cookie (substack.sid): /api/v1/archive lists posts
newest first (body_html empty), /api/v1/posts/<slug> returns the body the account can read.

The cookie is read through the credential seam (ingestion/credentials.py): the value saved
in Sources → Connections (never the environment). It is read at request time, so a new cookie
applies on the next fetch without a restart. Without one the public (truncated) body is
stored with metadata.paywalled=true.
With it, a rejected cookie (401/403) or an only_paid post that still comes back truncated
(Substack answers 200 with the teaser for a stale cookie) means the session expired: the
source is UNAVAILABLE (never backoff) until the owner updates the cookie. The cookie is
never logged or put in an error message.

All Substack publications share one host key (one backend), floored in gates.HOST_FLOORS;
post requests within a source are spaced by the profile's page delay.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional

from insight_core.ingestion.credentials import CredentialProvider, MappingCredentials
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    KindUnavailable,
    PolitenessProfile,
    RateLimit,
    Source,
    resume_counts,
)

SUBSTACK_HOST_KEY = "substack.com"
SUBSTACK_PROFILE = PolitenessProfile(concurrency_pool="host-lock", page_delay_s=1)
ARCHIVE_PAGE_SIZE = 12
EXPIRED_REASON = "Substack session expired — update it in Sources → Connections"
MISSING_NOTICE = "Paid posts arrive as teasers. Add your Substack session in Sources → Connections"
SUBSCRIPTIONS_URL = "https://substack.com/api/v1/subscriptions"
PAID_AUDIENCES = frozenset({"only_paid", "founding"})
# A paid body with fewer words than this share of the post's wordcount is the teaser.
TRUNCATED_RATIO = 0.6

_AUTH_ERROR_RE = re.compile(r"^HTTP (401|403)\b")


def is_substack_host(host: str) -> bool:
    host = (host or "").lower()
    return host == "substack.com" or host.endswith(".substack.com")


def publication_base(source: Source) -> str:
    parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
    return f"{parsed.scheme or 'https'}://{parsed.netloc}"


def _slug_from_url(url: str) -> Optional[str]:
    segments = parsing.path_segments(url)
    if len(segments) >= 2 and segments[0] == "p":
        return segments[1]
    return None


def _text(value: Any) -> str:
    return html.unescape(str(value or "")).strip()


class SubstackKind(BaseKind):
    name = "substack"
    available_basis = "unknown"   # /api/v1/archive pages carry no total
    profile = SUBSTACK_PROFILE

    def __init__(self, http: KindHttp, *, sid: Optional[str] = None,
                 credentials: Optional[CredentialProvider] = None) -> None:
        self.http = http
        if sid is not None:
            credentials = MappingCredentials({("substack", "sid"): sid})
        self.credentials = credentials

    @property
    def _sid(self) -> str:
        provider = self.credentials
        if provider is None:
            from insight_core.ingestion.credentials import default_credentials

            provider = self.credentials = default_credentials()
        value = provider.get("substack", "sid") or ""
        # Pasted as "substack.sid=<value>" from a cookie header: keep the value only.
        return value.split("=", 1)[1] if value.startswith("substack.sid=") else value

    def credential_notice(self) -> Optional[str]:
        """Why paid posts would come back as teasers (the health table's notice), or None."""
        return None if self._sid else MISSING_NOTICE

    def matches(self, source: Source) -> bool:
        if (source.get("settings") or {}).get("substack") is True:
            return True
        return is_substack_host(urllib.parse.urlparse(str(source.get("handle_or_url") or "")).hostname or "")

    def host_key(self, source: Source) -> str:
        return SUBSTACK_HOST_KEY

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "substack_offset" and isinstance(
            checkpoint.get("offset"), int
        )

    # ------------------------------------------------------------------ SourceKind

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        base = publication_base(source)
        try:
            items = await self._archive_items(base, 0, limit)
        except KindUnavailable:
            raise
        except Exception:
            items = await self._rss_items(base, limit)
        return await self._full_posts(source, base, items, self.profile.page_delay_s)

    async def inspect(self, source: Source) -> Inspection:
        items = await self._archive_items(publication_base(source), 0, ARCHIVE_PAGE_SIZE)
        return Inspection(available_posts=None, page_size=ARCHIVE_PAGE_SIZE, first_post_date=None,
                          raw={"paid_cookie": bool(self._sid), "sampled_posts": len(items)})

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        base = publication_base(source)
        collected, pages_fetched = resume_counts(checkpoint)
        offset = int((checkpoint or {}).get("offset") or 0)
        while collected < target:
            batch = min(ARCHIVE_PAGE_SIZE, target - collected)
            items = await self._archive_page(base, offset, batch)
            if not items:
                break
            posts = await self._full_posts(source, base, items, rate.page_delay_s)
            pages_fetched += 1
            collected += len(posts)
            offset += len(items)
            yield ArchivePage(posts, {
                "mode": "substack_offset",
                "offset": offset,
                "pages_fetched": pages_fetched,
                "collected_posts": collected,
            })
            if len(items) < batch:
                break
            if collected < target:
                await self.http.sleep(rate.delay_after(pages_fetched))

    async def check_session(self, source: Optional[Source] = None) -> tuple[bool, str]:
        """The connection test: is the cookie set and does it still read paid posts?

        With a source, the newest only_paid post of its archive is read: a full body is ok,
        a teaser or a 401/403 is "expired". Without a source, or when its latest page has no
        paid post, substack.com's subscriptions API says whether the cookie is signed in.
        The message never contains the cookie.
        """
        sid = self._sid
        if not sid:
            return False, "No Substack session set"
        try:
            if source is not None:
                base = publication_base(source)
                items = await self._archive_page(base, 0, ARCHIVE_PAGE_SIZE)
                paid = next((item for item in items if item.get("audience") == "only_paid"), None)
                if paid is not None:
                    detail = await self._get_json(f"{base}/api/v1/posts/{paid['slug']}")
                    post = self._to_post(source, base, {**paid, **(detail if isinstance(detail, dict) else {})})
                    return True, f"Full text readable: “{post['title'] or paid['slug']}”"
            data = await self._get_json(SUBSCRIPTIONS_URL)
            if isinstance(data, dict) and data.get("subscriptions") is not None:
                count = len(data.get("subscriptions") or [])
                return True, f"Signed in to Substack ({count} subscription{'s' if count != 1 else ''})"
            return False, EXPIRED_REASON
        except KindUnavailable as exc:
            return False, exc.reason
        except Exception as exc:  # noqa: BLE001 - reported, never raised to the route
            message = str(exc).replace(sid, "…") if sid else str(exc)
            return False, f"Could not check the Substack session: {message[:200]}"

    # ------------------------------------------------------------------ requests

    def _headers(self) -> Dict[str, str]:
        sid = self._sid
        return {"Cookie": f"substack.sid={sid}"} if sid else {}

    async def _get_json(self, url: str) -> Any:
        try:
            body, _ = await self.http.get_text(url, headers=self._headers())
        except ValueError as exc:
            if self._sid and _AUTH_ERROR_RE.match(str(exc)):
                raise KindUnavailable(EXPIRED_REASON) from None
            raise
        return json.loads(body)

    async def _archive_page(self, base: str, offset: int, limit: int) -> List[Dict[str, Any]]:
        query = urllib.parse.urlencode({"sort": "new", "offset": offset, "limit": limit})
        data = await self._get_json(f"{base}/api/v1/archive?{query}")
        if not isinstance(data, list):
            raise ValueError(f"Unexpected Substack archive response from {base}")
        return [item for item in data if isinstance(item, dict) and item.get("slug")]

    async def _archive_items(self, base: str, offset: int, limit: int) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        while len(items) < limit:
            batch = min(ARCHIVE_PAGE_SIZE, limit - len(items))
            page = await self._archive_page(base, offset + len(items), batch)
            items.extend(page)
            if len(page) < batch:
                break
            await self.http.sleep(self.profile.page_delay_s)
        return items[:limit]

    async def _rss_items(self, base: str, limit: int) -> List[Dict[str, Any]]:
        feed_text, _ = await self.http.get_text(f"{base}/feed")
        items = []
        for post in parsing.parse_feed_posts(feed_text, f"{base}/feed")[:limit]:
            items.append({"slug": _slug_from_url(str(post.get("url") or "")), "_rss": post})
        return items

    async def _full_posts(self, source: Source, base: str, items: List[Dict[str, Any]],
                          delay: float) -> List[Dict[str, Any]]:
        posts: List[Dict[str, Any]] = []
        for index, item in enumerate(items):
            if index:
                await self.http.sleep(delay)
            detail: Optional[Dict[str, Any]] = None
            if item.get("slug"):
                try:
                    detail = await self._get_json(f"{base}/api/v1/posts/{item['slug']}")
                except KindUnavailable:
                    raise
                except Exception:
                    detail = None
            if isinstance(detail, dict):
                posts.append(self._to_post(source, base, {**item, **detail}))
            elif "_rss" in item:
                posts.append(self._from_rss(source, item["_rss"]))
            else:
                posts.append(self._to_post(source, base, item))
        return posts

    # ------------------------------------------------------------------ shaping

    def _to_post(self, source: Source, base: str, data: Dict[str, Any]) -> Dict[str, Any]:
        audience = str(data.get("audience") or "everyone")
        body_html = str(data.get("body_html") or "")
        content = _text(parsing.strip_html(body_html)) or _text(data.get("truncated_body_text"))
        paywalled = audience in PAID_AUDIENCES and self._is_truncated(content, data.get("wordcount"))
        if paywalled and self._sid and audience == "only_paid":
            raise KindUnavailable(EXPIRED_REASON)

        cover = data.get("cover_image")
        media_urls = [cover] if isinstance(cover, str) and cover.startswith("http") else []
        for url in parsing.extract_html_image_urls(body_html):
            if url not in media_urls:
                media_urls.append(url)
        slug = data.get("slug")
        return {
            "platform": "rss",
            "source": str(source.get("handle_or_url") or base),
            "url": data.get("canonical_url") or f"{base}/p/{slug}",
            "external_id": str(data["id"]) if data.get("id") is not None else slug,
            "title": _text(data.get("title")),
            "content": content,
            "content_html": body_html or None,
            "date": parsing.parse_datetime_value(data.get("post_date")),
            "media_urls": media_urls,
            "categories": sorted({_text(tag.get("name")) for tag in data.get("postTags") or []
                                  if isinstance(tag, dict) and tag.get("name")}),
            "metadata": {
                "substack": True,
                "audience": audience,
                "paywalled": paywalled,
                "subtitle": _text(data.get("subtitle")) or None,
            },
        }

    def _from_rss(self, source: Source, post: Dict[str, Any]) -> Dict[str, Any]:
        post = dict(post)
        post["title"] = _text(post.get("title"))
        post["content"] = _text(post.get("content"))
        post["source"] = str(source.get("handle_or_url") or post.get("source"))
        post["metadata"] = {**(post.get("metadata") or {}), "substack": True, "audience": None, "paywalled": None}
        return post

    @staticmethod
    def _is_truncated(content: str, wordcount: Any) -> bool:
        if not content:
            return True
        try:
            expected = int(wordcount or 0)
        except (TypeError, ValueError):
            return False
        return expected > 0 and len(content.split()) < expected * TRUNCATED_RATIO
