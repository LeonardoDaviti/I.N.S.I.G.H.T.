"""What an address says (issue 0071: one definition of each, used everywhere): its host, its site,
its publication, whether it is a tweet and whose, the account it is under on a platform.

- **host**: the address's host name, lower case, without a port (`host_of`).
- **site**: the registrable part of a host, one label under a hosting platform's suffix
  (`site_of`): where a post is. Two addresses are on one site when their sites are one (`same_site`).
- **publication**: the host without `www.` (`publication_of`): who said it, a website's voice.
- **tweet**: an address of the shape /<user>/status/<id> on any host (url_normalization.TWEET_PATH,
  issue 0066), normalized to x.com/<user>/status/<id> (`is_tweet`, `tweet_author`); the account
  `x.com/<user>` (`x_account`).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import FrozenSet, Optional, Tuple
from urllib.parse import urlparse, urlsplit

from insight_core.utils.url_normalization import TWEET_PATH

# A post's links into the platform it came from say where it was posted, not what it is about.
PLATFORM_SITES = {
    "reddit": frozenset({"reddit.com", "redd.it"}),
    "hn": frozenset({"ycombinator.com"}),
    "x": frozenset({"x.com", "twitter.com"}),
    "telegram": frozenset({"t.me", "telegram.me", "telegram.org"}),
    "youtube": frozenset({"youtube.com", "youtu.be"}),
}
# A first path segment that names a kind of account, the account's name following it:
# reddit.com/r/<sub>, reddit.com/u/<user>, youtube.com/channel/<id>, youtube.com/c/<name>.
ACCOUNT_NAMESPACES = frozenset({"r", "u", "user", "c", "channel"})
# The labels a site's own blog or newsroom sits under (feed_finder's blog links, issue 0041).
BLOG_HOSTS = ("blog.", "news.", "newsroom.")


def bare(url: str) -> str:
    """A normalized address without its scheme: `host/path?query`."""
    return url.split("://", 1)[-1]


@lru_cache(maxsize=1 << 16)   # the story job asks for the same addresses' hosts many times
def host_of(url: Optional[str]) -> str:
    """An address's host, lower case, without a port: of a normalized address or any absolute link;
    "" for a relative or malformed one."""
    try:
        return urlsplit(url or "").hostname or ""
    except ValueError:      # a malformed link ("http://[x/")
        return ""


@lru_cache(maxsize=1)
def _hosting_suffixes() -> FrozenSet[str]:
    """The Public Suffix List's private section (public_suffix_private.dat): the hosting platforms
    that register there so each subdomain is its own site (github.io, bearblog.dev). Its rules as
    written: a suffix, `*.` before one, `!` before an exception."""
    path = Path(__file__).with_name("public_suffix_private.dat")
    return frozenset(line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("//"))


def site_of(host: Optional[str]) -> str:
    """The registrable part of a host: one label under a hosting platform's suffix (issue 0068:
    nnteacher.github.io and lilianweng.github.io are two sites), else its last two labels, three for
    a co.uk-like ending. Where a post is (Discover's places, a site's sections, a link to its own
    site); who said it is its publication (publication_of, issue 0069)."""
    host = (host or "").lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    suffixes = _hosting_suffixes()
    for i in range(1, len(parts)):   # the longest suffix first
        suffix = ".".join(parts[i:])
        if "!" + suffix in suffixes:
            return suffix
        if suffix in suffixes or (i + 1 < len(parts) and "*." + ".".join(parts[i + 1:]) in suffixes):
            return ".".join(parts[i - 1:])
    if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_site(a_host: Optional[str], b_host: Optional[str]) -> bool:
    """Two hosts on one site (site_of): blog.x.com and x.com are, two github.io writers aren't."""
    return bool(a_host and b_host) and site_of(a_host) == site_of(b_host)


def blog_site(host: str) -> str:
    """The site a page's blog belongs to, as the feed finder reads a home page's links (issue 0041):
    the host without a www., blog., news. or newsroom. label. Narrower than site_of: another
    subdomain (shop., docs.) is not the blog's."""
    first, _, rest = host.partition(".")
    return rest if rest and f"{first}." in ("www.",) + BLOG_HOSTS else host


def publication_of(host: Optional[str]) -> str:
    """A publication (issue 0069): a host without `www.`. A website source's voice is the one it
    publishes at, so writers on one platform (Substack, github.io) are voices of their own, and two
    sources at one host (a feed and a page watch) are one."""
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def account_key(url: str) -> str:
    """The account an address on a platform is under: `host/first segment`, two segments when the
    first only says what kind of account follows (`reddit.com/r/xreal`). Lowercase."""
    host, _, rest = bare(url).partition("/")
    segments = rest.split("?", 1)[0].split("/")
    first = segments[0].lower()
    if first in ACCOUNT_NAMESPACES and len(segments) > 1 and segments[1]:
        return f"{host.lower()}/{first}/{segments[1].lower()}"
    return f"{host.lower()}/{first}"


def is_tweet(url: Optional[str]) -> bool:
    """A normalized address that is a tweet (issue 0066: every form of one is x.com/<user>/status/<id>)."""
    return host_of(url) == "x.com" and bool(TWEET_PATH.match("/" + bare(url or "").partition("/")[2]))


def tweet_author(url: Optional[str]) -> Optional[str]:
    """A tweet's account, as its address writes it (issue 0066): `user` of /<user>/status/<id>."""
    match = TWEET_PATH.match(urlparse(url or "").path)
    return match.group(1) if match else None


# A paper's id in its address (issue 0106; 0080's paper-source shapes): a preprint's yymm.nnnnn, its
# version and file aside, as the address's last segment; a DOI (10.<registrant>/<suffix>) to the end of
# the path, a version or a file ending aside.
_PREPRINT = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$", re.I)
_DOI_PREFIX = re.compile(r"^10\.\d{4,9}$")
_DOI_END = re.compile(r"(?:\.full)?(?:\.pdf|\+html)?$", re.I)
_FILE_SEGMENTS = frozenset({"pdf", "epdf", "pdfdirect", "download"})


@lru_cache(maxsize=1 << 15)
def paper_id(url: Optional[str]) -> Optional[str]:
    """The paper an address names on its host (issue 0106), whatever the path around it: the abstract,
    its PDF, its HTML and each version are one page (`preprints.example/abs/2005.14165`, `/pdf/2005.14165v2`;
    `/doi/10.1145/123`, `/doi/pdf/10.1145/123`). The id sits in the first three segments; None when the
    address names none."""
    _, _, rest = bare(url or "").partition("/")
    segments = [s for s in re.split(r"[?#]", rest, maxsplit=1)[0].split("/") if s]
    for i, segment in enumerate(segments[:3]):
        found = _PREPRINT.match(segment)
        if found and i == len(segments) - 1:
            return found.group(1)
        if _DOI_PREFIX.match(segment) and i < len(segments) - 1:
            doi = _DOI_END.sub("", "/".join(segments[i:]).lower())
            return re.sub(r"(?<=\d)v\d+$", "", doi)
    return None


def paper_file(url: str) -> bool:
    """An address of a paper's file, not its page: a .pdf, or a pdf or download segment before its id."""
    _, _, rest = bare(url).partition("/")
    path = re.split(r"[?#]", rest, maxsplit=1)[0].lower()
    return path.endswith(".pdf") or any(s in _FILE_SEGMENTS for s in path.split("/"))


def paper_page_order(url: str) -> Tuple[bool, bool, int, str]:
    """Which address of one paper names it (issue 0106): its page before its file, then one without a
    query (a tracking one), then the shortest (no version), then the first in order."""
    return (paper_file(url), "?" in url, len(url), url)


def x_account(user: str) -> str:
    """An X account as the rules key it (account_key's form): x.com/<user>, lower case."""
    return "x.com/" + user.lower()


__all__ = ["PLATFORM_SITES", "ACCOUNT_NAMESPACES", "bare", "host_of", "site_of", "same_site", "blog_site",
           "publication_of", "account_key", "is_tweet", "tweet_author", "x_account", "paper_id", "paper_file",
           "paper_page_order"]
