"""reddit_subreddit: a subreddit given as a bare r/<sub> handle or any /r/<sub> address (its old .rss feed too).

Reddit refuses unregistered reads (0242), so the kind uses its OAuth API with the owner's registered "script" app
(client_credentials) and a User-Agent naming the owner's account: live reads /r/<sub>/new, archive pages
/r/<sub>/top?t=all by `after`. Credentials come from Connections (provider "reddit"); without them, or refused, the
kind is unavailable, never backoff. The token is kept per process and renewed TOKEN_MARGIN_S before expiry or once on
a 401. Spacing is a host floor (gates.HOST_FLOORS).
"""
from __future__ import annotations

import base64
import json
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from insight_core.ingestion.credentials import CONNECTIONS_HINT, CredentialProvider
from insight_core.ingestion.http import HttpError, KindHttp
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

PROVIDER = "reddit"
OAUTH_BASE = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_HOSTS = frozenset({"www.reddit.com", "reddit.com", "old.reddit.com", "new.reddit.com"})
LISTING_LIMIT = 100          # Reddit's listing page cap
TOKEN_MARGIN_S = 60          # a token is asked again this long before it expires

NO_CREDENTIALS = f"Reddit closed its feeds: add Reddit credentials in {CONNECTIONS_HINT}"
REFUSED_CREDENTIALS = (f"Reddit refused the app's credentials: check the client id and secret in "
                       f"{CONNECTIONS_HINT}")

REDDIT_PROFILE = PolitenessProfile(concurrency_pool="host-lock", page_delay_s=2, requires="reddit_creds")

_POST_URL_PREFIXES = ("https://reddit.com", "https://www.reddit.com", "http://reddit.com", "http://www.reddit.com")


def subreddit_name(source_handle: str) -> str:
    if "reddit.com" in source_handle:
        segments = parsing.path_segments(source_handle)
        if len(segments) >= 2 and segments[0] == "r":
            return segments[1]
    return source_handle.replace("r/", "").strip("/")


def reddit_credentials(credentials: Optional[CredentialProvider]) -> Tuple[Optional[str], Optional[str],
                                                                           Optional[str], Optional[str]]:
    """(client_id, client_secret, username, reason): reason None when all three are set, else NO_CREDENTIALS."""
    if credentials is None:
        from insight_core.ingestion.credentials import default_credentials

        credentials = default_credentials()
    client_id, secret, username = (credentials.get(PROVIDER, key) for key in ("client_id", "client_secret", "username"))
    return client_id, secret, username, (None if client_id and secret and username else NO_CREDENTIALS)


def user_agent(username: str) -> str:
    """Reddit's asked form: <platform>:<app id>:<version> (by /u/<username>)."""
    return f"server:insight-reader:1.0 (by /u/{username.removeprefix('/u/').removeprefix('u/')})"


def listing_posts(subreddit: str, body: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """A listing answer's posts (its t3 children) and its `after`, the live read's and the archive's."""
    data = (body or {}).get("data", {}) if isinstance(body, dict) else {}
    posts: List[Dict[str, Any]] = []
    for child in data.get("children", []):
        if child.get("kind") != "t3":
            continue
        post_data = child.get("data", {})
        permalink = post_data.get("permalink", "")
        media_urls = []
        if post_data.get("url") and not str(post_data["url"]).startswith(_POST_URL_PREFIXES):
            media_urls.append(post_data["url"])
        posts.append({
            "platform": "reddit",
            "source": f"r/{subreddit}",
            "url": f"https://reddit.com{permalink}" if permalink else post_data.get("url"),
            "external_id": post_data.get("id"),
            "title": post_data.get("title", ""),
            "content": post_data.get("selftext", "") or post_data.get("title", ""),
            "content_html": post_data.get("selftext_html"),
            "date": datetime.fromtimestamp(post_data.get("created_utc", 0), tz=timezone.utc),
            "media_urls": media_urls,
            "categories": [subreddit] + ([post_data["link_flair_text"]] if post_data.get("link_flair_text") else []),
            "metadata": {},
        })
    return posts, data.get("after")


class RedditKind(BaseKind):
    name = "reddit_subreddit"
    available_basis = "listing_cap"
    profile = REDDIT_PROFILE

    def __init__(self, http: KindHttp, *, credentials: Optional[CredentialProvider] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.http = http
        self.credentials = credentials
        self.clock = clock
        self._token: Optional[Tuple[str, float, str]] = None   # (token, expires at on clock, the client id it is for)

    def _provider(self) -> CredentialProvider:
        if self.credentials is None:
            from insight_core.ingestion.credentials import default_credentials

            self.credentials = default_credentials()
        return self.credentials

    @property
    def archive_refused(self) -> Optional[str]:   # type: ignore[override]
        """Without credentials nothing is read, an archive neither (the same reason)."""
        return reddit_credentials(self._provider())[3]

    def matches(self, source: Source) -> bool:
        if source.get("platform") == "reddit":
            return True
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        segments = [segment for segment in parsed.path.split("/") if segment]
        # any /r/<sub> address, its old .rss feed too; not one thread's page
        return ((parsed.hostname or "").lower() in REDDIT_HOSTS and len(segments) >= 2 and segments[0] == "r"
                and "comments" not in segments)

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "reddit_after" and checkpoint.get(
            "after"
        ) is not None

    # ------------------------------------------------------------------ the OAuth client

    async def _bearer(self, *, fresh: bool = False) -> Tuple[str, str]:
        """(the access token, the User-Agent). Raises KindUnavailable without credentials or when Reddit refuses them."""
        client_id, secret, username, reason = reddit_credentials(self._provider())
        if reason:
            raise KindUnavailable(reason)
        agent = user_agent(str(username))
        held = self._token
        if not fresh and held and held[2] == client_id and self.clock() < held[1] - TOKEN_MARGIN_S:
            return held[0], agent
        basic = base64.b64encode(f"{client_id}:{secret}".encode("utf-8")).decode("ascii")
        try:
            answer = await self.http.post_form(TOKEN_URL, {"grant_type": "client_credentials"}, user_agent=agent,
                                               extra_headers={"Authorization": f"Basic {basic}"})
        except HttpError as exc:
            if exc.status in (400, 401, 403):
                raise KindUnavailable(REFUSED_CREDENTIALS) from None
            raise
        token = answer.get("access_token") if isinstance(answer, dict) else None
        if not token:
            raise KindUnavailable(REFUSED_CREDENTIALS)
        self._token = (str(token), self.clock() + float(answer.get("expires_in") or 3600), str(client_id))
        return self._token[0], agent

    async def _get(self, path: str, params: Dict[str, str]) -> Any:
        """One OAuth read: GET oauth.reddit.com<path>?<params>&raw_json=1, a 401 asks a new token once."""
        url = f"{OAUTH_BASE}{path}?{urllib.parse.urlencode({**params, 'raw_json': '1'})}"
        token, agent = await self._bearer()
        try:
            body, _ = await self.http.get_text(url, user_agent=agent, headers={"Authorization": f"bearer {token}"})
        except HttpError as exc:
            if exc.status != 401:
                raise
            token, agent = await self._bearer(fresh=True)
            body, _ = await self.http.get_text(url, user_agent=agent, headers={"Authorization": f"bearer {token}"})
        return json.loads(body)

    # ------------------------------------------------------------------ reads

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        subreddit = subreddit_name(str(source["handle_or_url"]))
        posts, _ = listing_posts(subreddit, await self._get(f"/r/{subreddit}/new",
                                                            {"limit": str(max(1, min(limit, LISTING_LIMIT)))}))
        return posts[:limit]

    async def inspect(self, source: Source) -> Inspection:
        # The listing endpoints stop at ~250 items regardless of the subreddit's real size.
        return Inspection(available_posts=250, page_size=LISTING_LIMIT, first_post_date=None)

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        subreddit = subreddit_name(str(source["handle_or_url"]))
        collected, pages_fetched = resume_counts(checkpoint)
        current_after: Optional[str] = (checkpoint or {}).get("after")

        while collected < target:
            page_limit = min(LISTING_LIMIT, target - collected)
            page_posts, next_after = await self._fetch_listing(subreddit, after=current_after, limit=page_limit)
            if not page_posts:
                break

            pages_fetched += 1
            collected += len(page_posts)
            yield ArchivePage(page_posts, {
                "mode": "reddit_after",
                "after": next_after,
                "last_after": current_after,
                "pages_fetched": pages_fetched,
                "collected_posts": collected,
            })

            if not next_after:
                break
            current_after = next_after

    async def _fetch_listing(
        self,
        subreddit: str,
        after: Optional[str] = None,
        limit: int = LISTING_LIMIT,
        sort_method: str = "top",
        time_filter: Optional[str] = "all",
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        params = {"limit": str(limit)}
        if sort_method == "top" and time_filter:
            params["t"] = time_filter
        if after:
            params["after"] = after
        return listing_posts(subreddit, await self._get(f"/r/{subreddit}/{sort_method}", params))
