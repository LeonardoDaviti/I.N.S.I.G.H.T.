"""0132 B (Stealth v10.6): who a source (or a voice) is, by the role rule, in the spec's order, and "official".

    role(facts) -> (role, the rule's line that decided it)

The rule, applied in order (plan/issues/0132, Part B; measured on the lab's 94 read sources: 12 official, all right;
87% of all roles agree with reading):
  1. platform: many voices (Reddit, or a site with 10+ authors);
  2. curator by links: most posts are other sites' pages (a site whose own pages are under 30% of 10+ posts);
  3. official: the source itself is the subject, actor or venue in >= 30% of >= 5 read original posts, matched by
     name, handle, site label or acronym (`official`);
  4. focused, staff or beat: >= 50% of >= 5 read posts about one other maker ("needs a bio": the stored rows can't tell
     staff from a beat writer);
  5. reposter: own share under 60% (10+ posts);
  6. curator: roundups >= 30% (5+ read posts), or link posts >= 40% on X or Telegram (10+ posts);
  7. commentator: commentary >= 40% (5+ read posts);
  8. reporter: reports >= 50% (5+ read posts);
  9. independent author: anything else with 5+ read posts;
 10. too few to tell.

No list of known sites or makers: names come from the source's own name, handle and address, and the posts' entities.
Pure functions; markx/source_stats.py gathers the facts.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

PLATFORM_AUTHORS = 10       # a site with this many authors is a platform
AGGREGATOR_OWN = 0.3        # a site whose own pages are under this share of its posts points at others' pages
AGGREGATOR_POSTS = 10
OFFICIAL_SHARE = 0.3
MIN_READ = 5
FOCUSED_SHARE = 0.5         # raised from 0.3 on the lab: at 0.3 critics were labelled staff
REPOSTER_OWN = 0.6
MIN_POSTS = 10
ROUNDUP_SHARE = 0.3
LINK_POST_SHARE = 0.4
COMMENTARY_SHARE = 0.4
REPORT_SHARE = 0.5
SELF_ROLES = ("subject", "actor", "venue")
MAKER_ROLES = ("subject", "actor")

ROLES = ("platform", "curator", "official", "staff_or_beat", "reposter", "commentator", "reporter", "independent",
         "too_few")
LABELS = {"platform": "platform (many voices)", "curator": "curator", "official": "official",
          "staff_or_beat": "staff or beat", "reposter": "reposter", "commentator": "commentator",
          "reporter": "reporter", "independent": "independent author", "too_few": "too few to tell"}

GENERIC = frozenset("""blog blogs news feed feeds rss atom xml www com org net io dev me the a of and for on in to my
research lab labs engineering tech channel daily weekly monthly notes thoughts official video videos media inc
github gist medium substack bearblog blogspot index main default posts post articles article resources letter
newsletter digest latest recent updates thread from science data learning deep machine page pages everything space
world online home log web site real good things more just links""".split())
STOP = frozenset({"of", "the", "and", "for"})


# ---- names ---------------------------------------------------------------------------------------

def name_tokens(*names: Optional[str]) -> Set[str]:
    """The distinctive words of names: camel case split, 4+ letters, no generic word; and each name squashed (5+)."""
    out: Set[str] = set()
    for n in names:
        if not n:
            continue
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", n)
        for t in re.split(r"[^0-9A-Za-zА-Яа-яёЁ]+", spaced.lower()):
            t = re.sub(r"\d+$", "", t)
            if len(t) >= 4 and t not in GENERIC:
                out.add(t)
        sq = squash(n)
        if len(sq) >= 5 and sq not in GENERIC:
            out.add(sq)
    return out


def squash(name: Optional[str]) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", (name or "").lower())


def acronym(name: Optional[str]) -> Optional[str]:
    """The first letters of a name of 2+ words (short words kept whole): "AI Safety Institute" -> "asi"."""
    words = [w for w in re.split(r"[^a-z0-9]+", (name or "").lower()) if w and w not in STOP]
    return "".join(w if len(w) <= 2 else w[0] for w in words) if len(words) >= 2 else None


def site_label(host: Optional[str]) -> Optional[str]:
    """A host's own label: "blog.example.co.uk" -> "example", "name.substack.com" -> "name"."""
    parts = [p for p in (host or "").lower().split(".") if p]
    if len(parts) < 2:
        return parts[0] if parts else None
    if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) == 2:
        return parts[-3]
    if len(parts) >= 3 and parts[0] not in ("www", "blog", "news", "newsroom", "feeds", "feed", "m"):
        if parts[-2] in ("substack", "github", "bearblog", "medium", "blogspot", "wordpress", "ghost", "beehiiv"):
            return parts[0]
    return parts[-2]


@dataclass(frozen=True)
class Names:
    """What the source calls itself: its name, handle and site labels."""
    tokens: frozenset
    squashed: frozenset

    @staticmethod
    def of(names: Iterable[Optional[str]], handles: Iterable[Optional[str]] = (), hosts: Iterable[Optional[str]] = ()):
        names, handles, labels = list(names), list(handles), [site_label(h) for h in hosts]
        tokens = name_tokens(*names, *handles, *labels)
        squashed = {squash(x) for x in [*names, *handles, *labels] if x and len(squash(x)) >= 3}
        return Names(frozenset(tokens), frozenset(squashed))


def is_self(mention_name: Optional[str], maker: Optional[str], names: Names) -> bool:
    """A mention names the source itself: a shared distinctive word, the same squashed name, or its acronym."""
    for n in (mention_name, maker):
        if not n:
            continue
        if name_tokens(n) & names.tokens:
            return True
        sq = squash(n)
        if len(sq) >= 3 and sq in names.squashed:
            return True
        a = acronym(n)
        if a and len(a) >= 3 and (a in names.tokens or a in names.squashed):
            return True
    return False


# ---- step 3: official ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Mention:
    name: Optional[str]
    maker: Optional[str]
    role: Optional[str]
    type: Optional[str] = None


def official(read_posts: Dict[str, Sequence[Mention]], names: Names) -> Tuple[bool, float, int, List[str]]:
    """(official, the share of read original posts naming the source itself as subject, actor or venue, how many read
    posts, the posts that do). Official: >= 30% of >= 5."""
    hits = [pid for pid, ms in read_posts.items()
            if any(m.role in SELF_ROLES and is_self(m.name, m.maker, names) for m in ms)]
    n = len(read_posts)
    share = len(hits) / n if n else 0.0
    return n >= MIN_READ and share >= OFFICIAL_SHARE, share, n, hits


def norm_maker(name: str) -> str:
    n = re.sub(r"[,.]", " ", name.strip().lower())
    n = re.sub(r"\s+", " ", n).strip()
    return re.sub(r"\s+(ai|inc|labs?|llc|ltd|corp|corporation|research)$", "", n).strip()


def top_maker(read_posts: Dict[str, Sequence[Mention]], names: Names) -> Tuple[Optional[str], float, List[str]]:
    """The maker most read posts are about (a mention's maker, or an org or person named as subject or actor) that is
    not the source itself: (its name, the share of read posts, those posts)."""
    by: Dict[str, List[str]] = {}
    shown: Dict[str, str] = {}
    for pid, ms in read_posts.items():
        seen = set()
        for m in ms:
            if m.role not in MAKER_ROLES:
                continue
            raw = m.maker or (m.name if m.type in ("org", "person") else None)
            if not raw or is_self(raw, None, names):
                continue
            key = norm_maker(raw)
            if key and key not in seen:
                seen.add(key)
                by.setdefault(key, []).append(pid)
                shown.setdefault(key, raw.strip())
    if not by or not read_posts:
        return None, 0.0, []
    key = max(by, key=lambda k: (len(by[k]), k))
    return shown[key], len(by[key]) / len(read_posts), by[key]


# ---- the rule ------------------------------------------------------------------------------------

@dataclass
class Facts:
    kind: str = "site"                 # x, telegram, youtube, reddit, hn, site, ...
    posts: int = 0                     # posts in the window
    authors: int = 0                   # distinct post authors (a site)
    own_pages_share: Optional[float] = None    # a site's posts on its own address (None: not measured)
    read: int = 0                      # read original posts
    official: bool = False
    self_share: float = 0.0
    maker: Optional[str] = None
    maker_share: float = 0.0
    own_share: float = 1.0
    link_post_share: float = 0.0
    kinds: Dict[str, float] = field(default_factory=dict)   # reading-kind shares of read posts


def role(f: Facts) -> Tuple[str, str]:
    """(role, the rule's line that decided it), in the spec's order."""
    if f.kind == "reddit":
        return "platform", "platform: a subreddit, many voices"
    if f.authors >= PLATFORM_AUTHORS:
        return "platform", f"platform: {f.authors} authors"
    if (f.kind == "site" and f.own_pages_share is not None and f.posts >= AGGREGATOR_POSTS
            and f.own_pages_share < AGGREGATOR_OWN):
        return "curator", f"curator by links: only {f.own_pages_share:.0%} of {f.posts} posts are its own pages"
    if f.read >= MIN_READ and f.official:
        return "official", (f"{f.self_share:.0%} of {f.read} read original posts have the source itself as subject, "
                            "actor or venue")
    if f.read >= MIN_READ and f.maker and f.maker_share >= FOCUSED_SHARE:
        return "staff_or_beat", f"{f.maker_share:.0%} of {f.read} read posts are about {f.maker} (needs a bio)"
    if f.posts >= MIN_POSTS and f.own_share < REPOSTER_OWN:
        return "reposter", f"only {f.own_share:.0%} of {f.posts} posts are its own"
    k = f.kinds or {}
    if f.read >= MIN_READ and k.get("roundup", 0) >= ROUNDUP_SHARE:
        return "curator", f"roundups are {k['roundup']:.0%} of {f.read} read posts"
    if f.posts >= MIN_POSTS and f.kind in ("x", "telegram") and f.link_post_share >= LINK_POST_SHARE:
        return "curator", f"link posts are {f.link_post_share:.0%} of {f.posts} posts"
    if f.read >= MIN_READ and k.get("commentary", 0) >= COMMENTARY_SHARE:
        return "commentator", f"commentary is {k['commentary']:.0%} of {f.read} read posts"
    if f.read >= MIN_READ and k.get("report", 0) >= REPORT_SHARE:
        return "reporter", f"reports are {k['report']:.0%} of {f.read} read posts"
    if f.read >= MIN_READ:
        return "independent", f"mixed kinds over {f.read} read posts"
    return "too_few", f"{f.read} read posts (5 needed)"


def kind_shares(kinds: Iterable[Optional[str]]) -> Dict[str, float]:
    c = Counter(k for k in kinds if k)
    n = sum(c.values())
    return {k: v / n for k, v in c.items()} if n else {}
