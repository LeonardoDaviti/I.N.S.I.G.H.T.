"""substack: a Substack publication, paid posts included when the owner's cookie is set.

The public RSS feed truncates paid posts. The publication's JSON API does not when the
request carries a subscriber's session cookie (substack.sid): /api/v1/archive lists posts
newest first (body_html empty), /api/v1/posts/<slug> returns the body the account can read.

The cookie is sent only to the publications the owner pays for (issue 0084): Substack's
subscriptions API (SUBSCRIPTIONS_URL) is asked once per fetch run (kept SUBSCRIPTIONS_TTL_S in
memory) and paid_publication_hosts reads it defensively. A publication you pay for is read as
before; any other is read without the cookie, its paid posts stored as their teaser
(metadata.paywalled=true), never an error. When the subscriptions answer can't be read, or
names no publication as paid, the cookie is sent everywhere and a teaser is stored, never an
error (we can't tell whom you pay). A 401/403 there means the session expired: a publication
with a truncated paid post is UNAVAILABLE, free ones are read without the cookie.

The cookie is read through the credential seam (ingestion/credentials.py): the value saved
in Sources → Connections (never the environment). It is read at request time, so a new cookie
applies on the next fetch without a restart. Without one the public (truncated) body is
stored with metadata.paywalled=true.
For a publication you pay for, a rejected cookie (401/403) or an only_paid post that still
comes back truncated (Substack answers 200 with the teaser for a stale cookie) means the
session expired: the
source is UNAVAILABLE (never backoff) until the owner updates the cookie. The cookie is
never logged or put in an error message.

All Substack publications share one host key (one backend), floored in gates.HOST_FLOORS;
post requests within a source are spaced by the profile's page delay.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Union

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
    start_at,
)
from insight_core.utils.addresses import host_of

SUBSTACK_HOST_KEY = "substack.com"
SUBSTACK_PROFILE = PolitenessProfile(concurrency_pool="host-lock", page_delay_s=1)
ARCHIVE_PAGE_SIZE = 12
EXPIRED_REASON = "Substack session expired — update it in Sources → Connections"
MISSING_NOTICE = "Paid posts arrive as teasers. Add your Substack session in Sources → Connections"
# Without tvOnly Substack answers 400 (seen 2026-10-27); its list can be empty when signed in.
SUBSCRIPTIONS_URL = "https://substack.com/api/v1/subscriptions?tvOnly=false"
PAID_AUDIENCES = frozenset({"only_paid", "founding"})
PREVIEW_NOTICE = "Paid posts: preview only (no subscription)"
# One fetch run asks the subscriptions API once: its answer is kept this long in memory.
SUBSCRIPTIONS_TTL_S = 600
# A subscription is paid when its membership_state (or type/plan) is one of these, or a paid
# flag is true. Anything else, or the field missing, is "not paid".
PAID_STATES = frozenset({"subscribed", "paid", "founding", "comp", "gift"})
PAID_FLAGS = ("paid", "is_paid", "isPaid", "is_paid_subscriber", "is_founding")

# How a source is read (_access):
FULL = "full"          # you pay for it: cookie sent, a truncated paid post means expired
PREVIEW = "preview"    # you don't (or no cookie): no cookie, paid posts stored as their teaser
EXPIRED = "expired"    # the subscriptions API said 401/403: no cookie, a truncated paid post means expired
UNKNOWN = "unknown"    # can't tell whom you pay: cookie sent, a teaser is stored, never an error
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


def _bare_host(value: Any) -> str:
    """"https://www.example.com/x" or "www.example.com" -> "example.com"."""
    text = str(value or "").strip().lower()
    host = host_of(text if "://" in text else f"https://{text}")
    return host[4:] if host.startswith("www.") else host


@dataclass(frozen=True)
class Subscriptions:
    paid_hosts: FrozenSet[str]   # bare hosts of the publications you pay for
    paid_count: int              # how many publications that is


def _is_paid(entry: Dict[str, Any]) -> bool:
    for key in ("membership_state", "type", "subscription_type", "plan"):
        if str(entry.get(key) or "").lower() in PAID_STATES:
            return True
    return any(entry.get(flag) is True for flag in PAID_FLAGS)


def _publication_hosts(publication: Dict[str, Any]) -> FrozenSet[str]:
    hosts = set()
    subdomain = str(publication.get("subdomain") or "").strip().lower()
    if subdomain:
        hosts.add(f"{subdomain}.substack.com")
    for key in ("custom_domain", "base_url"):
        if publication.get(key):
            hosts.add(_bare_host(publication[key]))
    return frozenset(host for host in hosts if host)


def paid_publication_hosts(data: Any) -> Optional[Subscriptions]:
    """The publications you pay for, from SUBSCRIPTIONS_URL's answer; None when unreadable.

    Assumed (not verified against Substack, so read defensively): a dict whose "subscriptions"
    is a list of entries, each with a paid state (membership_state "subscribed"/"founding"/...,
    or a true paid flag) and its publication either embedded ("publication": {subdomain,
    custom_domain}) or by "publication_id" into a top-level "publications" list. An entry
    without a paid state, or whose publication can't be found, is not paid.
    """
    if not isinstance(data, dict) or not isinstance(data.get("subscriptions"), list):
        return None
    by_id = {str(pub["id"]): pub for pub in data.get("publications") or []
             if isinstance(pub, dict) and pub.get("id") is not None}
    hosts: set = set()
    count = 0
    for entry in data["subscriptions"]:
        if not isinstance(entry, dict) or not _is_paid(entry):
            continue
        publication = entry.get("publication")
        if not isinstance(publication, dict):
            publication = by_id.get(str(entry.get("publication_id")), {})
        found = _publication_hosts(publication) or _publication_hosts(entry)
        if found and not found & hosts:
            count += 1
        hosts |= found
    return Subscriptions(frozenset(hosts), count)


class SubstackKind(BaseKind):
    name = "substack"
    reads_posts = True            # read_post: one post from the API (the repair, and issue 0084 B's linked pages)
    available_basis = "unknown"   # /api/v1/archive pages carry no total
    profile = SUBSTACK_PROFILE

    def __init__(self, http: KindHttp, *, sid: Optional[str] = None,
                 credentials: Optional[CredentialProvider] = None) -> None:
        self.http = http
        if sid is not None:
            credentials = MappingCredentials({("substack", "sid"): sid})
        self.credentials = credentials
        self._subscriptions_cache: Optional[tuple] = None   # (cookie hash, monotonic time, answer)

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

    def reading_notice(self, source: Source) -> Optional[str]:
        """The health row's note for a publication read without the cookie (its newest paid post
        was stored as a teaser, `paid_preview` of the schedule view), or None."""
        return PREVIEW_NOTICE if self._sid and source.get("paid_preview") else None

    async def _subscriptions(self, *, fresh: bool = False) -> Union[Subscriptions, str, None]:
        """The publications you pay for (kept SUBSCRIPTIONS_TTL_S per cookie), EXPIRED on a
        401/403, None when the answer can't be read (not kept; `fresh` raises a request error)."""
        key = hashlib.sha256(self._sid.encode()).hexdigest()
        cached = self._subscriptions_cache
        if (not fresh and cached is not None and cached[0] == key
                and time.monotonic() - cached[1] < SUBSCRIPTIONS_TTL_S):
            return cached[2]
        try:
            answer: Union[Subscriptions, str, None] = paid_publication_hosts(
                await self._get_json(SUBSCRIPTIONS_URL, cookie=True))
        except KindUnavailable:
            answer = EXPIRED
        except Exception:  # noqa: BLE001 - unreadable: send the cookie, never an error
            if fresh:      # the connection test reports it
                raise
            return None
        if answer is not None:
            self._subscriptions_cache = (key, time.monotonic(), answer)
        return answer

    async def _access(self, source: Source) -> str:
        """How this source is read: FULL, PREVIEW, EXPIRED or UNKNOWN (see the constants)."""
        if not self._sid:
            return PREVIEW
        subscriptions = await self._subscriptions()
        if subscriptions == EXPIRED:
            return EXPIRED
        if not isinstance(subscriptions, Subscriptions) or not subscriptions.paid_hosts:
            return UNKNOWN
        return FULL if _bare_host(publication_base(source)) in subscriptions.paid_hosts else PREVIEW

    def matches(self, source: Source) -> bool:
        if (source.get("settings") or {}).get("substack") is True:
            return True
        return is_substack_host(host_of(str(source.get("handle_or_url") or "")))

    def host_key(self, source: Source) -> str:
        return SUBSTACK_HOST_KEY

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "substack_offset" and isinstance(
            checkpoint.get("offset"), int
        )

    async def start_checkpoint(self, source: Source, stored) -> Optional[dict]:
        # The archive lists newest first, so the stored posts are the first `stored` positions.
        return start_at(mode="substack_offset", offset=max(0, int(stored["post_count"]) - ARCHIVE_PAGE_SIZE))

    # ------------------------------------------------------------------ SourceKind

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        base = publication_base(source)
        access = await self._access(source)
        try:
            items = await self._archive_items(base, 0, limit, access)
        except KindUnavailable:
            raise
        except Exception:
            items = await self._rss_items(base, limit)
        return await self._full_posts(source, base, items, self.profile.page_delay_s, access)

    async def inspect(self, source: Source) -> Inspection:
        access = await self._access(source)
        items = await self._archive_items(publication_base(source), 0, ARCHIVE_PAGE_SIZE, access)
        return Inspection(available_posts=None, page_size=ARCHIVE_PAGE_SIZE, first_post_date=None,
                          raw={"paid_cookie": access in (FULL, UNKNOWN), "sampled_posts": len(items)})

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        base = publication_base(source)
        access = await self._access(source)
        collected, pages_fetched = resume_counts(checkpoint)
        offset = int((checkpoint or {}).get("offset") or 0)
        while collected < target:
            batch = min(ARCHIVE_PAGE_SIZE, target - collected)
            items = await self._archive_page(base, offset, batch, access)
            if not items:
                break
            posts = await self._full_posts(source, base, items, rate.page_delay_s, access)
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

    async def check_session(self, source: Optional[Source] = None) -> tuple[bool, str]:
        """The connection test: is the cookie set and signed in, and what does it read in full?

        substack.com's subscriptions API says whether the cookie is signed in and how many
        publications you pay for ("Signed in · full text on 1 publication you pay for"). With a
        source you pay for, the newest only_paid post of its archive is read too: a teaser or a
        401/403 is "expired". The message never contains the cookie.
        """
        sid = self._sid
        if not sid:
            return False, "No Substack session set"
        try:
            subscriptions = await self._subscriptions(fresh=True)
            if not isinstance(subscriptions, Subscriptions):
                return False, EXPIRED_REASON
            count = subscriptions.paid_count
            message = ("Signed in · no publication you pay for found" if not count else
                       f"Signed in · full text on {count} publication{'' if count == 1 else 's'} you pay for")
            if source is not None and await self._access(source) == FULL:
                base = publication_base(source)
                items = await self._archive_page(base, 0, ARCHIVE_PAGE_SIZE, FULL)
                paid = next((item for item in items if item.get("audience") == "only_paid"), None)
                if paid is not None:
                    detail = await self._get_json(f"{base}/api/v1/posts/{paid['slug']}", cookie=True)
                    post = self._to_post(source, base, {**paid, **(detail if isinstance(detail, dict) else {})}, FULL)
                    message += f" · “{post['title'] or paid['slug']}” reads in full"
            return True, message
        except KindUnavailable as exc:
            return False, exc.reason
        except Exception as exc:  # noqa: BLE001 - reported, never raised to the route
            message = str(exc).replace(sid, "…") if sid else str(exc)
            return False, f"Could not check the Substack session: {message[:200]}"

    async def read_post(self, source: Source, url: str) -> Optional[Dict[str, Any]]:
        """One stored post again, from /api/v1/posts/<slug> (the full-text repair). None when
        the url is not a /p/<slug> post. Raises KindUnavailable when the session expired."""
        slug = _slug_from_url(url)
        if not slug:
            return None
        base = publication_base(source)
        access = await self._access(source)
        detail = await self._get_json(f"{base}/api/v1/posts/{slug}", cookie=access in (FULL, UNKNOWN))
        return self._to_post(source, base, detail, access) if isinstance(detail, dict) else None

    # ------------------------------------------------------------------ requests

    def _headers(self) -> Dict[str, str]:
        sid = self._sid
        return {"Cookie": f"substack.sid={sid}"} if sid else {}

    async def _get_json(self, url: str, *, cookie: bool) -> Any:
        headers = self._headers() if cookie else {}
        try:
            body, _ = await self.http.get_text(url, headers=headers)
        except ValueError as exc:
            if headers and _AUTH_ERROR_RE.match(str(exc)):
                raise KindUnavailable(EXPIRED_REASON) from None
            raise
        return json.loads(body)

    async def _archive_page(self, base: str, offset: int, limit: int, access: str) -> List[Dict[str, Any]]:
        query = urllib.parse.urlencode({"sort": "new", "offset": offset, "limit": limit})
        data = await self._get_json(f"{base}/api/v1/archive?{query}", cookie=access in (FULL, UNKNOWN))
        if not isinstance(data, list):
            raise ValueError(f"Unexpected Substack archive response from {base}")
        return [item for item in data if isinstance(item, dict) and item.get("slug")]

    async def _archive_items(self, base: str, offset: int, limit: int, access: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        while len(items) < limit:
            batch = min(ARCHIVE_PAGE_SIZE, limit - len(items))
            page = await self._archive_page(base, offset + len(items), batch, access)
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
                          delay: float, access: str) -> List[Dict[str, Any]]:
        posts: List[Dict[str, Any]] = []
        for index, item in enumerate(items):
            if index:
                await self.http.sleep(delay)
            detail: Optional[Dict[str, Any]] = None
            if item.get("slug"):
                try:
                    detail = await self._get_json(f"{base}/api/v1/posts/{item['slug']}",
                                                  cookie=access in (FULL, UNKNOWN))
                except KindUnavailable:
                    raise
                except Exception:
                    detail = None
            if isinstance(detail, dict):
                posts.append(self._to_post(source, base, {**item, **detail}, access))
            elif "_rss" in item:
                posts.append(self._from_rss(source, item["_rss"]))
            else:
                posts.append(self._to_post(source, base, item, access))
        return posts

    # ------------------------------------------------------------------ shaping

    def _to_post(self, source: Source, base: str, data: Dict[str, Any], access: str) -> Dict[str, Any]:
        audience = str(data.get("audience") or "everyone")
        body_html = str(data.get("body_html") or "")
        content = parsing.strip_html(body_html) or _text(data.get("truncated_body_text"))
        paywalled = audience in PAID_AUDIENCES and self._is_truncated(content, data.get("wordcount"))
        if paywalled and audience == "only_paid" and access in (FULL, EXPIRED):
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
