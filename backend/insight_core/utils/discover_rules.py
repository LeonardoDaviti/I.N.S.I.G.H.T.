"""Discover (issues 0050, 0065, 0067): the sites and accounts your sources keep linking, and where
your stories start. Pure functions over plain data; db/repo_discover.py counts the links in SQL by
these rules (`suggestions` is its reference) and services/stories_service.py ranks what it finds.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

from insight_core.utils.addresses import PLATFORM_SITES, account_key, bare, site_of, x_account
from insight_core.utils.post_links import SECTION_MIN, SECTION_SHARE, is_article, section_of
from insight_core.utils.stamps import ADDRESSES, fingerprint
from insight_core.utils.story_rules import ROUNDUP_ANCHORS, StoryPost, anchors
from insight_core.utils.url_normalization import TWEET_PATH

DISCOVER_MIN_VOICES = 3        # the prototype's, not measured (the prototype: plan/research/dedup-prototype)
DISCOVER_MIN_ARTICLES = 2      # the prototype's, not measured
DISCOVER_ARTICLE_SHARE = 0.4   # the prototype's, not measured
# The sites where INSIGHT follows one account, not the whole site: its source kinds (Reddit, X,
# Telegram, YouTube) and the feed finder's platform feeds (GitHub, Medium). Measured on the
# server's data, 2026-10-30: a test by "8+ first path segments" called 249 hosts platforms, split
# publishers by year or section (nytimes.com/2026) and hid blogs whose posts sit at the root.
DISCOVER_PLATFORMS = frozenset(set().union(*(PLATFORM_SITES[k] for k in ("reddit", "x", "telegram", "youtube")))
                               | {"github.com", "medium.com"})
# First path segments of a platform that name a kind of page, not an account.
NOT_ACCOUNT = frozenset({"status", "watch", "pull", "issues", "i", "p", "s", "search", "hashtag", "intent",
                         "share", "home", "explore", "wiki", "posts", "in"})
# A post of a platform account is one of its articles (issue 0065). A tweet by its shape, on any host
# (x.com, a Nitter, xcancel.com, fxtwitter.com: the forms 0066 gives one address), is the account's;
# elsewhere on a platform, /<account>/<number> (a Telegram post, t.me/<channel>/<id>).
TWEET = TWEET_PATH
PLATFORM_POST = re.compile(r"^/[^/?#]+/\d+(?:[?#]|$)")
ORIGIN_MIN_VOICES = 2      # the stories whose origins Discover counts: 2+ voices, the ones 0064 counted; not measured

# ---- Discover --------------------------------------------------------------------------------


@dataclass
class Suggestion:
    key: str                         # a site (openai.com) or a platform account (x.com/karpathy)
    voices: List[str]                # the voices that link it
    articles: List[str]              # its article-like addresses linked
    links: int                       # every address of it linked
    addresses: Set[str] = field(default_factory=set)   # those addresses (0051 counts its classics)
    roundups: Set[str] = field(default_factory=set)    # the voices that link it only in roundups (0067)

    @property
    def weight(self) -> float:
        """Its voices as Discover orders them (issue 0067): one linking it only in roundups counts half."""
        return len(self.voices) - len(self.roundups) / 2


def is_roundup(post: StoryPost) -> bool:
    """A post whose links have 3+ anchors: it lists news, so it joins only the story of its first
    (group) and weighs half in Discover's order (issue 0067)."""
    return len(anchors(post)) >= ROUNDUP_ANCHORS


def discover_address(url: str) -> Tuple[Optional[str], str, bool]:
    """What Discover reads of one address: (its key, its site, whether the site is a platform).
    On a platform the key is the account (account_key), none when the first path segment names a
    kind of page (NOT_ACCOUNT); a tweet, on any host, is its author's (x.com/<user>, TWEET); elsewhere
    it is the host. A function of the address alone, so the database keeps it once per address
    (repo_discover, issue 0062)."""
    host, _, rest = bare(url).partition("/")
    tweet = TWEET.match("/" + rest)
    if tweet:
        user = tweet.group(1).lower()
        return (None if user in NOT_ACCOUNT else x_account(user)), "x.com", True
    site = site_of(host)
    if site in DISCOVER_PLATFORMS:
        return (None if re.split(r"[/?#]", rest)[0].lower() in NOT_ACCOUNT else account_key(url)), site, True
    return host, site, False


def discover_article(url: str) -> bool:
    """What Discover counts as an article: an article-like address (post_links.is_article), or a
    post of a platform account (issue 0065: a tweet in any form, a Telegram post)."""
    host, _, rest = bare(url).partition("/")
    path = "/" + rest
    return is_article(url) or bool(TWEET.match(path)) or (
        site_of(host) in DISCOVER_PLATFORMS and bool(PLATFORM_POST.match(path)))


def discover_open(key: str, site: str, platform: bool, *, followed: Set[str], hidden: Set[str],
                  followed_accounts: Set[str]) -> bool:
    """A key you neither follow nor hid: on a platform as that account, elsewhere as its site."""
    if platform:
        return not (key in followed_accounts or key in hidden)
    return not (site in followed or key in hidden or site in hidden)


def suggestions(links: Iterable[Tuple[str, str, bool]], *, followed: Set[str], hidden: Set[str],
                followed_accounts: Set[str] = frozenset(), mirrors: Set[str] = frozenset()) -> List[Suggestion]:
    """Sites and accounts 3+ of your voices link, in 2+ article-like pages that make 40%+ of their
    links, that you don't follow and did not hide. On a platform the unit is the account: it is
    followed, or hidden, only as that account (`followed_accounts`, addresses.account_key), so
    following one channel hides no other. Elsewhere it is the site (`followed`: sites; `hidden`:
    keys or sites); a tweet mirror's other pages (`mirrors`: hosts where tweets are found, issue
    0067) are X's kinds of page, never a site. `links`: (voice, address, whether the linking post is
    a roundup) for every kept outside link. Most voices first, a voice linking a key only in
    roundups counting half (Suggestion.weight), then all voices."""
    links = list(links)
    found: Dict[str, Tuple[Set[str], Set[str], Set[str], Set[str]]] = defaultdict(lambda: (set(), set(), set(), set()))
    for voice, url, roundup in links:
        key, site, platform = discover_address(url)
        if key is None or (not platform and key in mirrors) or not discover_open(
                key, site, platform, followed=followed, hidden=hidden, followed_accounts=followed_accounts):
            continue
        voices, articles, every, ordinary = found[key]
        voices.add(voice)
        every.add(url)
        if not roundup:
            ordinary.add(voice)
        if discover_article(url):
            articles.add(url)
    out = [
        Suggestion(key, sorted(voices), sorted(articles), len(every), set(every), voices - ordinary)
        for key, (voices, articles, every, ordinary) in found.items()
        if len(voices) >= DISCOVER_MIN_VOICES and len(articles) >= DISCOVER_MIN_ARTICLES
        and len(articles) >= DISCOVER_ARTICLE_SHARE * len(every)
    ]
    return sorted(out, key=lambda s: (-s.weight, -len(s.voices), -len(s.articles), -s.links, s.key))


# ---- Discover: where your stories start (issue 0065) --------------------------------------------


@dataclass
class Origin:
    """A story's root (0064) as Discover reads it."""
    story_id: str
    url: str                         # the outside page (stories.origin_url), else the origin post's address
    title: Optional[str]             # its link words, or the post's title; None: show the address
    source_id: Optional[str]         # the origin post's source; None: a page outside INSIGHT
    first_at: datetime
    voices: Dict[str, str] = field(default_factory=dict)   # the story's voices -> the source naming each
    own: bool = False                # an origin post on the site its source publishes on: held

    @property
    def stored(self) -> bool:
        return self.source_id is not None


@dataclass
class Origins:
    suggest: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # key -> its stories
    missing: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # source -> its stories
    unnamed: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # youtube.com/watch -> them


def discover_place(url: str) -> Optional[str]:
    """Where an address is, as a source holds it: on a platform its account (None for a page that
    names none), elsewhere its host and section (anthropic.com/news; the host alone at the root)."""
    key, _, platform = discover_address(url)
    section = "" if platform else section_of(url)
    return f"{key}/{section}" if key and section else key


def origins(roots: Iterable[Origin], *, followed: Set[str], held: Dict[str, str],
            mirrors: Set[str] = frozenset()) -> Origins:
    """Where your stories start, each story once:
    - at its own source's site (Origin.own), or at a place one of your sources holds (`held`:
      discover_place -> that source): nothing to suggest; a story the
      source misses when its page is not stored (its archive may hold it, 0015);
    - on a site you don't follow, or an account no source holds: that site or account;
    - on a site you follow, in a section none of your sources holds: that section when SECTION_SHARE
      of the site's such stories start there (0060's rule: anthropic.com/news), else the site;
    - on a platform's page that names no account (youtube.com/watch?v=...), or a tweet mirror's page
      that is not a tweet (`mirrors`, issue 0067: nitter.net/i/article/...): only listed."""
    out = Origins()
    elsewhere: Dict[str, List[Origin]] = defaultdict(list)   # a followed site's host -> its unheld stories
    for root in roots:
        key, site, platform = discover_address(root.url)
        place = discover_place(root.url)
        if root.own:
            continue
        if key is None or (not platform and key in mirrors):
            if not root.stored:   # a stored one is its source's
                _, _, rest = bare(root.url).partition("/")
                out.unnamed[f"{site}/{re.split(r'[/?#]', rest)[0]}"].append(root)
        elif place in held:
            if not root.stored:
                out.missing[held[place]].append(root)
        elif platform or site not in followed:
            out.suggest[key].append(root)
        else:
            elsewhere[key].append(root)
    for host, found in elsewhere.items():
        section, n = Counter(section_of(root.url) for root in found).most_common(1)[0]
        if section and n >= max(SECTION_MIN, SECTION_SHARE * len(found)):
            out.suggest[f"{host}/{section}"] = [root for root in found if section_of(root.url) == section]
        else:
            out.suggest[host] = found
    return out


def address_rules() -> str:
    """Which rules wrote a discover_addresses row (issue 0071): what they make of the sample's addresses
    (utils/stamps.py), so a change to discover_address, site_of, account_key or discover_article that
    shows there refills the rows, and a refactor that changes nothing keeps them."""
    return fingerprint([(url, discover_address(url), discover_article(url)) for url in ADDRESSES])


ADDRESS_RULES = address_rules()

__all__ = ["Suggestion", "suggestions", "discover_address", "discover_article", "discover_open", "discover_place",
           "Origin", "Origins", "origins", "is_roundup", "address_rules", "ADDRESS_RULES"]
