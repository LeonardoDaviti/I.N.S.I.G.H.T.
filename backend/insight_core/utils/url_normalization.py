"""Deterministic URL normalization helpers for saved posts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# A query key that marks who sent a reader or how, not which page (issue 0109 B1: the mail and analytics
# families). On the server's data a newsletter's HubSpot ?_hsenc= made one essay 3 Discover lines and split
# its story's key. A key of a page's own query (id, p, t, v, q, tag, cid, share) is never one.
TRACKING_QUERY_PREFIXES = ("utm_", "hsa_")   # Google's campaign tags; HubSpot's ad tags
BEFORE_0109 = frozenset({"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "mkt_tok", "ref", "ref_src", "spm", "si",
                         "source", "ved"})
TRACKING_QUERY_KEYS = BEFORE_0109 | {
    # mail: HubSpot, Mailchimp, Marketo (above), ConvertKit, beehiiv, Vero, Omeda, Eloqua, MailerLite, Drip, Klaviyo
    "_hsenc", "_hsmi", "__hstc", "__hssc", "__hsfp", "hsctatracking", "ck_subscriber_id", "_bhlid", "vero_id",
    "vero_conv", "oly_anon_id", "oly_enc_id", "elqtrackid", "elqtrack", "elqaid", "elqat", "ml_subscriber",
    "ml_subscriber_hash", "__s", "_kx",
    # analytics handed over between sites (Google's linker), and ad click ids
    "_ga", "_gl", "gclsrc", "dclid", "gbraid", "wbraid", "msclkid", "yclid", "ysclid", "_openstat", "twclid",
    "ttclid", "li_fat_id", "wickedid", "s_cid", "rb_clickid",
}


def is_tracking_key(key: str) -> bool:
    """Whether a query key (lower case) only tracks the reader: the page is the same without it."""
    return key in TRACKING_QUERY_KEYS or key.startswith(TRACKING_QUERY_PREFIXES)


# Issue 0126 (1), the owner 2026-11-07: a gift link's token and a share mark are kept for clicking (posts.url, the
# post's HTML, post_links.shared_url) and ignored for matching: every compared address drops them.
# - An access token: a key naming a token, a gift, an unlock or access, or any key whose value is a signed token (a
#   JWT). A vocabulary, not a list of sites (0123's): on the server's copy (2026-11-05) unlocked_article_code,
#   accessToken, view_token, gift, giftId, access_token, casa_token, pwapi_token, sharing_token ... 25 keys.
#   A page known only by one is walled (originals_rules.tokened): it is never fetched with it.
# - A share mark: who shared the page or from where, never which page (measured on the copy: 59 smid, 49 syn-<hex>,
#   26 reflink, 25 taid, 16 leadSource, 13 srnd, 11 dib_tag, 9 mrfcid). Short names that are a page's own query
#   elsewhere (r, rc, st, sh, share: a route, a view, a region) are not marks.
ACCESS_KEY_RE = re.compile(r"token|gift|unlock|access", re.I)
SIGNED_VALUE_RE = re.compile(r"^eyJ[\w-]+\.[\w-]+\.[\w-]+$")
SHARE_MARK_KEYS = frozenset({"smid", "taid", "mrfcid", "srnd", "leadsource", "reflink", "dib_tag"})
SHARE_MARK_RE = re.compile(r"^syn-[0-9a-f]{8}$", re.I)


def is_access_key(key: str, value: str = "") -> bool:
    """Whether a query pair carries an access or gift token: the page needs it to be read, and is the same page."""
    return bool(ACCESS_KEY_RE.search(key) or SIGNED_VALUE_RE.match(value or ""))


def is_query_mark(key: str, value: str = "") -> bool:
    """Whether a query pair is an access token or a share mark (0126): kept for clicking, dropped for matching."""
    return is_access_key(key, value) or key.lower() in SHARE_MARK_KEYS or bool(SHARE_MARK_RE.match(key))


def has_query_mark(url: str | None) -> bool:
    """Whether an address carries an access token or a share mark (its compared form drops them)."""
    try:
        query = urlparse(url or "").query
    except ValueError:
        return False
    return any(is_query_mark(k, v) for k, v in parse_qsl(query, keep_blank_values=True))


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

# A tweet has one address, whatever the host serving it (issue 0066): x.com, twitter.com, a Nitter
# and the mirrors (xcancel.com, fxtwitter.com, ...) all write /<user>/status/<id>, the id 15+
# digits. A rule on the address's shape, not a list of hosts; the account is lower case (X's
# accounts are), and a tail (/photo/1, /history) or a query is the same tweet.
TWEET_SHAPE = r"/([A-Za-z0-9_]+)/status/(\d{15,})"   # also SQL's (repo_discover.TWEET_HREF)
TWEET_PATH = re.compile("^" + TWEET_SHAPE + r"(?:[/?#]|$)")


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

    tweet = TWEET_PATH.match(parsed.path or "")
    if tweet:
        address = f"https://x.com/{tweet.group(1).lower()}/status/{tweet.group(2)}"
        return NormalizedURL(address, address, "x.com")

    host = HOST_ALIASES.get(host, host)
    if host.startswith("www."):
        host = host[4:]
    path = _normalize_path(parsed.path, host, parsed.query)
    query = _normalize_query(host, parsed.query, parsed.path)
    # A fragment is dropped (#atom-everything, #comments) unless it is the page's own address:
    # a single-page site routes on #/post/1 or #!/post/1.
    fragment = parsed.fragment if parsed.fragment[:1] in ("/", "!") else ""

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
    # http and https name the same post: a source moving to https must not save it again.
    normalized = urlunparse(("https" if scheme == "http" else scheme, netloc, path, "", query, fragment))
    return NormalizedURL(canonical, normalized, host)


def _parse_url(raw: str):
    if "://" not in raw:
        candidate = f"https://{raw.lstrip('/')}"
    else:
        candidate = raw

    try:
        parsed = urlparse(candidate)
        parsed.port  # a port that isn't a number ("host:  some text") is not an address
    except ValueError:
        return None
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
        if is_tracking_key(lowered) or is_query_mark(key, value):
            continue
        # A trailing slash in a value is the same value (issue 0070: ?p=112711/ and ?p=112711).
        items.append((key, value.rstrip("/") if value.strip("/") else value))

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
