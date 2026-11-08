"""Channel profiles (issue 0132 C2): one fetch of each source's profile or about page, monthly, through the normal
fetch path (KindHttp, the host gates and their floors, a limiting host waited out). services/profiles_service.py
picks which sources are due and keeps every answer (migration 0086); this file says where a source's profile is
and reads what it holds.

Where a profile is (`ask_for`), by the source's kind, never by a list of sites:
- **X through Nitter** (nitter_rss): the account's page on the same Nitter, `<origin>/<user>`;
- **YouTube** (youtube_channel): the channel's about page, `youtube.com/channel/<id>/about` (or `/@<handle>/about`);
- **Telegram through the bridge** (telegram_rss): the bridge's feed, whose channel description is the channel's;
- **Telegram through MTProto** (telegram_mtproto): the channel's full info (about, subscribers), no web page;
- **a website** (every other feed kind): its home page.
Reddit, Hacker News and Saved have no profile of their own (their voice is each post's author).

What a profile holds (`Profile`): the name it shows, the bio, the website field, the accounts and addresses it
links (the bio's and the website's, a site's header and footer links to platform accounts and its `rel=me`), and the
subscriber or follower count when the page shows one. Parsers are pure functions over the page's text.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from insight_core.utils.addresses import host_of

PROFILE_MAX_BYTES = 1_500_000    # an about page's start: YouTube's carries its data in the first megabyte
MAX_LINKS = 40                    # a page linking more is a directory: kept, its links the first 40
PLATFORM_KEY_PREFIXES = ("x:", "tg:", "yt:", "ytc:")

NO_PROFILE_KINDS = frozenset({"saved", "reddit_subreddit", "reddit"})


@dataclass
class Profile:
    kind: str                         # nitter | youtube | telegram_bridge | telegram_mtproto | site
    url: str
    name: Optional[str] = None
    bio: Optional[str] = None
    website: Optional[str] = None
    links: List[str] = field(default_factory=list)
    followers: Optional[int] = None
    followers_label: Optional[str] = None   # followers | subscribers

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Ask:
    """One profile request: what to read (`url`, or none for MTProto), the gate's host key, the parser."""

    kind: str
    url: Optional[str]
    host_key: str


# ---- text helpers ------------------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_URL = re.compile(r"https?://[^\s<>\"'\)\]]+")
_HANDLE = re.compile(r"(?<![\w@./])@([A-Za-z0-9_]{2,32})\b")
_COUNT = re.compile(r"([\d][\d.,\s]*)\s*([KkMmBb])?\b")


def text_of(fragment: Optional[str]) -> str:
    """An HTML fragment as one line of text: tags out (a <br> a space), entities read."""
    if not fragment:
        return ""
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    return _WS.sub(" ", html_lib.unescape(_TAG.sub("", fragment))).strip()


def count_of(text: Optional[str]) -> Optional[int]:
    """'1,234' -> 1234, '1.2K' -> 1200, '3.4M subscribers' -> 3400000, '12 345' -> 12345; None when none."""
    if not text:
        return None
    m = _COUNT.search(text)
    if not m:
        return None
    digits, unit = m.group(1).strip(), (m.group(2) or "").upper()
    if unit:
        try:
            value = float(digits.replace(",", ".").replace(" ", ""))
        except ValueError:
            return None
        return int(round(value * {"K": 1e3, "M": 1e6, "B": 1e9}[unit]))
    cleaned = re.sub(r"[.,\s]", "", digits)
    return int(cleaned) if cleaned.isdigit() else None


def _meta(page: str, name: str) -> Optional[str]:
    """A <meta property|name=name content=...> value, either attribute order."""
    for pattern in (rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']',
                    rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(name)}["\']'):
        m = re.search(pattern, page, re.I)
        if m:
            value = html_lib.unescape(m.group(1)).strip()
            if value:
                return value
    return None


def _dedupe(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        u = u.rstrip(".,;:!)")
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out[:MAX_LINKS]


def _absolute(href: str, base: str) -> Optional[str]:
    href = html_lib.unescape(href or "").strip()
    if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
        return None
    url = urllib.parse.urljoin(base, href)
    return url if url.startswith(("http://", "https://")) else None


def _bio_links(bio: str, mention_host: Optional[str]) -> List[str]:
    """The addresses a bio names, and its @handles as accounts on `mention_host` (x.com, t.me)."""
    out = _URL.findall(bio or "")
    out += [f"https://{w}" for w in re.findall(r"(?<![/@\w])((?:[a-z0-9-]+\.)+[a-z]{2,}/[^\s]*|(?:[a-z0-9-]+\.)+(?:com|org|net|io|ai|dev|me|co|app|blog|news))\b",
                                              bio or "", re.I) if not any(w in u for u in out)]
    if mention_host:
        out += [f"https://{mention_host}/{h}" for h in _HANDLE.findall(bio or "")]
    return out


# ---- the parsers ---------------------------------------------------------------------------------------

def parse_nitter(page: str, url: str) -> Profile:
    """A Nitter account page: .profile-card-fullname, .profile-bio, .profile-website, the followers' stat."""
    name = re.search(r'class="profile-card-fullname"[^>]*>(.*?)</a>', page, re.S)
    bio = re.search(r'<div class="profile-bio">(.*?)</div>', page, re.S)
    website = re.search(r'<div class="profile-website">.*?<a [^>]*href="([^"]+)"', page, re.S)
    followers = re.search(r'<li class="followers">.*?<span class="profile-stat-num">([^<]+)</span>', page, re.S)
    bio_html = bio.group(1) if bio else ""
    bio_text = text_of(bio_html)
    links = []
    for href in re.findall(r'<a [^>]*href="([^"]+)"', bio_html):
        if href.startswith("/") and not href.startswith("//"):   # Nitter's own link to an account: x.com/<user>
            seg = href.strip("/").split("/")[0]
            if seg and not seg.startswith(("search", "hashtag", "pic", "i")):
                links.append(f"https://x.com/{seg}")
            continue
        absolute = _absolute(href, url)
        if absolute:
            links.append(absolute)
    links += _bio_links(bio_text, "x.com")
    site = html_lib.unescape(website.group(1)) if website else None
    if site:
        links.insert(0, site)
    return Profile("nitter", url, name=text_of(name.group(1)) if name else None, bio=bio_text or None, website=site,
                   links=_dedupe(links), followers=count_of(followers.group(1)) if followers else None,
                   followers_label="followers" if followers else None)


def _yt_unescape(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


def _redirect_target(url: str) -> str:
    """youtube.com/redirect?...&q=<address>: the address."""
    if "youtube.com/redirect" in url:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("q")
        if q:
            return q[0]
    return url


def parse_youtube(page: str, url: str) -> Profile:
    """A YouTube channel's about page: its og: title and description, the subscriber count its data writes
    ("1.2M subscribers"), the channel's links (channelExternalLinkViewModel's, youtube.com/redirect's q=) and the
    description's own addresses."""
    name = _meta(page, "og:title")
    desc = None
    m = re.search(r'"aboutChannelViewModel":\{"description":"((?:[^"\\]|\\.)*)"', page)
    if m:
        desc = _yt_unescape(m.group(1))
    desc = desc or _meta(page, "og:description") or _meta(page, "description")
    followers = None
    m = re.search(r'"subscriberCountText":(?:\{"simpleText":)?"([^"]+)"', page) \
        or re.search(r'"content":"([\d.,]+\s*[KMB]?) subscribers"', page)
    if m:
        followers = count_of(m.group(1))
    links: List[str] = []
    for block in re.findall(r'"channelExternalLinkViewModel":\{(.*?)\}\}\]?\}', page, re.S):
        c = re.search(r'"link":\{"content":"((?:[^"\\]|\\.)*)"', block)
        if c:
            target = _yt_unescape(c.group(1))
            links.append(target if "://" in target else "https://" + target)
    for r in re.findall(r'https?:(?:\\/|/){2}www\.youtube\.com(?:\\/|/)redirect\?[^"\s<>]+', page):
        links.append(_redirect_target(html_lib.unescape(_yt_unescape(r))))
    links += _bio_links(desc or "", None)
    return Profile("youtube", url, name=name, bio=desc, website=links[0] if links else None, links=_dedupe(links),
                   followers=followers, followers_label="subscribers" if followers is not None else None)


def parse_telegram_bridge(feed: str, url: str) -> Profile:
    """The bridge's feed of a channel: its <channel> title and description (the channel's about) before the
    first item, and the addresses and @channels the description names."""
    head = feed.split("<item", 1)[0]
    title = re.search(r"<title>(.*?)</title>", head, re.S)
    desc = re.search(r"<description>(.*?)</description>", head, re.S)

    def clean(m: Optional[re.Match]) -> Optional[str]:
        if not m:
            return None
        raw = m.group(1).strip()
        if raw.startswith("<![CDATA["):
            raw = raw[9:].removesuffix("]]>")
        return text_of(html_lib.unescape(raw)) or None
    bio = clean(desc)
    return Profile("telegram_bridge", url, name=clean(title), bio=bio, links=_dedupe(_bio_links(bio or "", "t.me")))


def parse_telegram_full(full: Any, url: str) -> Profile:
    """Telethon's GetFullChannelRequest answer: full_chat.about, full_chat.participants_count, chats[0].title."""
    chat = getattr(full, "full_chat", None)
    chats = getattr(full, "chats", None) or []
    about = (getattr(chat, "about", None) or "").strip() or None
    count = getattr(chat, "participants_count", None)
    return Profile("telegram_mtproto", url, name=getattr(chats[0], "title", None) if chats else None, bio=about,
                   links=_dedupe(_bio_links(about or "", "t.me")),
                   followers=int(count) if isinstance(count, int) else None,
                   followers_label="subscribers" if isinstance(count, int) else None)


def parse_site(page: str, url: str) -> Profile:
    """A website's home page: og:site_name (else <title>), the meta description, and the platform accounts it
    links (`rel=me`, its header and footer icons: x.com/<user>, t.me/<channel>, youtube.com/@<handle>, ...). Its
    links to other sites are not kept: a home page links everything it writes about."""
    from insight_core.utils.voice_rules import address_key

    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    name = _meta(page, "og:site_name") or (text_of(title.group(1)) if title else None)
    bio = _meta(page, "og:description") or _meta(page, "description")
    own = host_of(url).removeprefix("www.")
    links: List[str] = []
    for tag in re.findall(r"<(?:a|link)\b[^>]*>", page, re.I):
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        target = _absolute(href.group(1), url) if href else None
        if not target or host_of(target).removeprefix("www.") == own:
            continue
        rel_me = re.search(r'rel=["\'][^"\']*\bme\b', tag, re.I)
        key, is_profile = address_key(target)
        if rel_me or (key and key.startswith(PLATFORM_KEY_PREFIXES) and is_profile):
            links.append(target)
    return Profile("site", url, name=name, bio=bio, links=_dedupe(links))


PARSERS = {"nitter": parse_nitter, "youtube": parse_youtube, "telegram_bridge": parse_telegram_bridge,
           "site": parse_site}


# ---- where a source's profile is ------------------------------------------------------------------------

def _youtube_about(handle: str) -> Optional[str]:
    parsed = urllib.parse.urlsplit(handle if "://" in handle else "https://www.youtube.com/" + handle.lstrip("/"))
    channel = (urllib.parse.parse_qs(parsed.query).get("channel_id") or [None])[0]
    if channel:
        return f"https://www.youtube.com/channel/{channel}/about"
    segs = [s for s in parsed.path.split("/") if s]
    if segs and segs[0].startswith("@"):
        return f"https://www.youtube.com/{segs[0]}/about"
    if len(segs) >= 2 and segs[0] in ("channel", "c", "user"):
        return f"https://www.youtube.com/{segs[0]}/{segs[1]}/about"
    if handle.startswith("@"):
        return f"https://www.youtube.com/{handle}/about"
    if handle.startswith("UC") and "/" not in handle:
        return f"https://www.youtube.com/channel/{handle}/about"
    return None


def ask_for(source: Dict[str, Any], kind_name: str, host_key: str, *, home: Optional[str] = None) -> Optional[Ask]:
    """Where `source`'s profile is, by its kind (`kind_name`: KindRegistry's), or None when it has none.
    `home`: a website's own address when its posts live on another host than its feed (the feed elsewhere)."""
    handle = str(source.get("handle_or_url") or "").strip()
    if kind_name in NO_PROFILE_KINDS or source.get("platform") in ("reddit", "saved", "hn"):
        return None
    if kind_name == "nitter_rss":
        parsed = urllib.parse.urlsplit(handle)
        segs = [s for s in parsed.path.split("/") if s]
        return Ask("nitter", f"{parsed.scheme}://{parsed.netloc}/{segs[0]}", host_key) if segs else None
    if kind_name == "youtube_channel":
        about = _youtube_about(handle)
        return Ask("youtube", about, host_of(about).removeprefix("www.")) if about else None
    if kind_name == "telegram_rss":
        from insight_core.ingestion.kinds.telegram_rss import page_url
        try:
            return Ask("telegram_bridge", page_url(handle, 1), host_key)
        except ValueError:
            return None
    if kind_name == "telegram_mtproto":
        return Ask("telegram_mtproto", None, host_key)
    base = home or handle
    if "://" not in base:
        return None
    parsed = urllib.parse.urlsplit(base)
    if not parsed.netloc:
        return None
    root = f"{parsed.scheme or 'https'}://{parsed.netloc}/"
    return Ask("site", root, (parsed.hostname or "").lower().removeprefix("www."))


__all__ = ["Ask", "Profile", "PARSERS", "PROFILE_MAX_BYTES", "ask_for", "count_of", "parse_nitter", "parse_site",
           "parse_telegram_bridge", "parse_telegram_full", "parse_youtube", "text_of"]
