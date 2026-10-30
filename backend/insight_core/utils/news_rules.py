"""News and Classics (issue 0051): names in titles, News stories and their score, classics.
Pure functions over plain data; the story job (services/news_service.py) loads the posts and
writes what these return.

Ported from the prototype (`plan/research/dedup-prototype/names.py`, `news.py`, `rank.py`,
`report.py`), the reference the real code reproduces. **Every threshold of 0051 is here, in one
place**: tuning on the server is a one-line change.

- **News:** 0050's stories, plus the posts that share a surging name in their titles (for News
  only: a name never folds rows in the Main feed). A story's score is reports + 1/2 shares + 1/2
  roundup mentions, each voice once, in its strongest role (report, then share, then mention).
- **A name** is a phrase of 1 to 3 words from a title, every word capitalised or holding a digit,
  not starting or ending on a small word ("the", "of"); one word only when it mixes letters and
  digits ("GPT-6"). Pure numbers and lowercase words are not names.
- **A name surges** when, within 48 hours, 3+ posts of 2+ voices use it, it was said at most once
  in the 30 days before, and every source involved was followed for those whole 30 days. As the prototype: a name's first burst is the one judged; if a
  source in it is new, the name does not surge. A shorter name whose posts a longer one covers is
  dropped.
  arXiv titles are left out.
- **A classic** is a page linked by 2+ of your voices (not the page's own), with links 180+ days
  apart: a stored post or an outside page. Reference pages (a path segment like `docs`,
  `pricing`, `help`) and home pages are not classics.
"""
from __future__ import annotations

import bisect
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.utils.post_links import bare, is_home, site_of
from insight_core.utils.story_rules import Story, StoryPost, _UnionFind, count_voices, roles

# ---- the thresholds (issue 0051), tune here -------------------------------------------------

NEWS_DAYS = 7                       # News shows the stories whose first post is in the last 7 days ...
NEWS_RECENT = timedelta(hours=48)   # ... in two parts: "Last 48 hours" and "Earlier this week"
NEWS_MIN_VOICES = 2
SHARE_WEIGHT = 0.5
MENTION_WEIGHT = 0.5
NAME_WINDOW = timedelta(hours=48)   # a name surges within 48 hours ...
NAME_MIN_POSTS = 3                  # ... in 3+ posts ...
NAME_MIN_VOICES = 2                 # ... of 2+ voices ...
NAME_MAX_USUAL = 1                  # ... said at most once in the 30 days before (measured on the server's data,
NAME_BASELINE = timedelta(days=30)  # 2026-10-30: never before ~88% real, once ~75%, twice or more ~27%) ...
                                    # ... every source followed for all of those 30 days
NAME_TITLE_DAYS = 32                # the job reads the titles of the last 32 days (a full run: every one)
NAME_MAX_WORDS = 3
NAME_SKIP_KINDS = frozenset({"arxiv"})
CLASSIC_MIN_VOICES = 2
CLASSIC_MIN_SPREAD = timedelta(days=180)   # measured on the server's data, 2026-10-30: at 30 days most were news with legs
CLASSIC_CITED_AGAIN = timedelta(days=7)   # cited in the last 7 days: "cited again this week", first
BACKGROUND_SHOWN = 2
# A reference page's path segment: a vocabulary of page kinds, not a list of sites.
REFERENCE = re.compile(r"/(docs?|documentation|products?|pricing|support|help|api|reference|release-notes"
                       r"|changelog|wiki|articles|collections|download|login|signup)(/|$)")

# ---- names in titles ------------------------------------------------------------------------

TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё0-9][\w\-\.’']*", re.U)
SMALL_WORDS = frozenset("the a an and or of to in on for with is are was be by at from as it its this that how why "
                        "what new you your we our i my vs not".split())
_TRIM = ".’'"


def _words(title: Optional[str]) -> List[str]:
    return TOKEN.findall(title or "")


def _lower(words: Sequence[str]) -> List[str]:
    return [w.lower().strip(_TRIM) for w in words]


def names(title: Optional[str]) -> Set[str]:
    """The names in a title, lowercase ("steam frame", "gpt-6", "opus 5.5")."""
    words = _words(title)
    out = set()
    for n in range(1, NAME_MAX_WORDS + 1):
        for i in range(len(words) - n + 1):
            w = words[i:i + n]
            if w[0].lower() in SMALL_WORDS or w[-1].lower() in SMALL_WORDS:
                continue
            if not all(x[0].isupper() or any(c.isdigit() for c in x) for x in w):
                continue
            if all(x.replace(".", "").replace("$", "").isdigit() for x in w):
                continue
            if n == 1:
                letters = [c for c in w[0] if c.isalpha()]
                if not (letters and any(c.isdigit() for c in w[0])):
                    continue   # one word is a name only when it mixes letters and digits ...
                if w[0][0].isdigit():
                    continue   # ... and doesn't start with one: "30b", "128gb", "2m" are sizes (server data, 2026-10-30)
            out.add(" ".join(_lower(w)))
    return out


def _phrases(title: Optional[str]) -> Set[str]:
    """Every run of 1 to 3 words of a title, lowercase: where a name is said, in any case."""
    words = _lower(_words(title))
    return {" ".join(words[i:i + n]) for n in range(1, NAME_MAX_WORDS + 1) for i in range(len(words) - n + 1)}


@dataclass
class Surge:
    name: str
    at: datetime                 # its first post in the 48 hours
    posts: List[str]             # the posts of those 48 hours, first first
    usual: int                   # posts that used it in the 30 days before


def surges(posts: Sequence[StoryPost], followed_since: Dict[str, datetime]) -> List[Surge]:
    """The names that surge among `posts` (their titles), first surge first.
    `followed_since`: when each source was added."""
    rows = sorted((p for p in posts if p.title and p.kind not in NAME_SKIP_KINDS), key=lambda p: (p.t, p.id))
    named: Dict[str, List[StoryPost]] = defaultdict(list)
    said: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in rows:
        for name in names(p.title):
            named[name].append(p)
        for phrase in _phrases(p.title):
            said[phrase].append(p)
    found = []
    for name, uses in named.items():
        if len(uses) < NAME_MIN_POSTS:
            continue
        every = said[name]           # in time order, as `rows`
        times = [p.t for p in every]
        for start in uses:
            near = every[bisect.bisect_left(times, start.t):bisect.bisect_right(times, start.t + NAME_WINDOW)]
            if len(near) < NAME_MIN_POSTS or len({p.place for p in near}) < NAME_MIN_VOICES:
                continue
            usual = bisect.bisect_left(times, start.t) - bisect.bisect_left(times, start.t - NAME_BASELINE)
            if usual > NAME_MAX_USUAL:
                continue
            # Its first burst. A source added within the 30 days before it makes the burst its
            # archive, not news: the name does not surge (as the prototype; a later burst of the
            # same name is not looked for, so an archive never turns into a surge days later).
            since = start.t - NAME_BASELINE
            if all(followed_since.get(p.source_id) is not None and followed_since[p.source_id] <= since for p in near):
                found.append(Surge(name, start.t, [p.id for p in near], usual))
            break
    return sorted(longest(found), key=lambda s: (s.at, s.name))


def longest(found: Sequence[Surge]) -> List[Surge]:
    """Only the longest name is kept when a shorter one covers the same posts."""
    def inside(short: str, long: str) -> bool:
        return len(long) > len(short) and f" {short} " in f" {long} "

    kept = []
    for s in found:
        posts = set(s.posts)
        if any(inside(s.name, o.name) and posts <= set(o.posts) for o in found):
            continue
        kept.append(s)
    return kept


# ---- News stories ---------------------------------------------------------------------------


@dataclass
class NewsStory:
    id: str                          # its first post
    first_at: datetime
    posts: List[StoryPost]           # first first
    voices: int
    roles: Dict[str, str]            # post id -> report | share
    names: Dict[str, str]            # post id -> the surging name that joined it
    reports: int
    shares: int
    mentions: int

    @property
    def score(self) -> float:
        return score(self.reports, self.shares, self.mentions)


def score(reports: int, shares: int, mentions: int) -> float:
    return reports + SHARE_WEIGHT * shares + MENTION_WEIGHT * mentions


def tally(posts: Sequence[StoryPost], post_roles: Dict[str, str], mentioned_by: Iterable[StoryPost]
          ) -> Tuple[int, int, int]:
    """(reports, shares, mentions): each voice once, in its strongest role (report, share, then a
    roundup's mention)."""
    best: Dict[str, str] = {}
    for p in posts:
        role = post_roles[p.id]
        if best.get(p.voice) != "report":
            best[p.voice] = role
    reports = sum(1 for role in best.values() if role == "report")
    mentions = len({p.voice for p in mentioned_by} - set(best))
    return reports, len(best) - reports, mentions


def news(posts: Sequence[StoryPost], stories: Sequence[Story], found: Sequence[Surge]) -> List[NewsStory]:
    """0050's stories joined by the surging names, those with 2+ voices, first first."""
    by_id = {p.id: p for p in posts}
    uf = _UnionFind()
    for p in posts:
        uf.find(p.id)
    story_of: Dict[str, Story] = {}
    for story in stories:
        for p in story.posts:
            uf.union(p.id, story.id)
            story_of[p.id] = story
    joined_by: Dict[str, str] = {}
    for surge in found:
        members = [pid for pid in surge.posts if pid in by_id]
        for pid in members[1:]:
            uf.union(pid, members[0])
        for pid in members:
            joined_by.setdefault(pid, surge.name)
    groups: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in sorted(posts, key=lambda p: (p.t, p.id)):
        groups[uf.find(p.id)].append(p)
    out = []
    for group in groups.values():
        if len(group) < 2:
            continue
        voices = count_voices(group)
        if voices < NEWS_MIN_VOICES:
            continue
        ids = {p.id for p in group}
        post_roles = roles(group)
        mentioning = {pid for story in {story_of[p.id].id: story_of[p.id] for p in group if p.id in story_of}.values()
                      for pid in story.mentions} - ids
        reports, shares, mentions = tally(group, post_roles, [by_id[pid] for pid in mentioning if pid in by_id])
        out.append(NewsStory(
            id=group[0].id, first_at=group[0].t, posts=group, voices=voices, roles=post_roles,
            names={p.id: joined_by[p.id] for p in group if p.id in joined_by},
            reports=reports, shares=shares, mentions=mentions,
        ))
    return sorted(out, key=lambda s: (s.first_at, s.id))


def lead(posts: Sequence[Tuple[str, str]]) -> Optional[str]:
    """A story's lead, as 0050's: its first report, else its first share. `posts`: (id, role),
    first posted first."""
    for want in ("report", "share"):
        for pid, role in posts:
            if role == want:
                return pid
    return None


# ---- Classics -------------------------------------------------------------------------------


@dataclass
class Citation:
    """One kept link: who linked what, when."""

    voice: str
    name: str                        # the voice as you know it (a source's name, u/<author>)
    source_id: str
    t: datetime
    target: str                      # normalized address
    stored: Optional[str] = None     # the stored post it is, if any
    text: Optional[str] = None       # the link's words


@dataclass
class Classic:
    target: str
    post_id: Optional[str]
    voices: int
    first_at: datetime               # the stored post's date, else the first link
    last_at: datetime                # the last link
    title: Optional[str]
    citers: List[Dict[str, object]] = field(default_factory=list)   # each voice once, first citation first

    @property
    def days(self) -> int:
        return (self.last_at - self.first_at).days


def is_reference(url: str) -> bool:
    """A docs, product, pricing, help ... page, or a home page: a page you look things up in."""
    if is_home(url):
        return True
    _, _, rest = bare(url).partition("/")
    return bool(REFERENCE.search("/" + rest))


def _titled(text: Optional[str]) -> bool:
    """Link words that name a page: 3+ words starting with a capital or a digit, not an address and
    not cut mid-sentence. Measured on the server's data (2026-10-30): link words in the middle of a
    sentence ("over 100,000 commits", "full paper on arXiv") named the top classics badly; with this
    rule 20 of the top 30 titles were right, against 16, and the rest show the page's address."""
    if not text or re.match(r"https?://", text) or len(text.split()) < 3:
        return False
    return (text[0].isupper() or text[0].isdigit()) and not text.rstrip().endswith((",", ";", ":"))


def classics(citations: Iterable[Citation], stored: Dict[str, Tuple[str, datetime, Optional[str]]]) -> List[Classic]:
    """The classics among `citations`, most voices first, then cited longest.
    `stored`: post id -> (its voice, its date, its title) for the stored posts linked."""
    by_target: Dict[str, List[Citation]] = defaultdict(list)
    for c in citations:
        if c.stored is not None and c.stored not in stored:
            continue
        by_target[c.target].append(c)
    out = []
    for target, cites in by_target.items():
        own = {"site:" + site_of(bare(target).split("/", 1)[0])}
        post = stored.get(cites[0].stored) if cites[0].stored else None
        if post is not None:
            own.add(post[0])
        elif is_reference(target):
            continue
        cites = sorted(cites, key=lambda c: (c.t, c.source_id))
        counted = [c for c in cites if c.voice not in own]
        voices = {c.voice for c in counted}
        if len(voices) < CLASSIC_MIN_VOICES:
            continue
        # The spread starts at the stored post's own date, else at the second voice's first link:
        # one voice's date alone can't make a classic (a page rewritten under an old date, like
        # Gwern's, dated a 2026 link 2023 on the server's data).
        firsts = sorted({c.voice: c.t for c in reversed(counted)}.values())
        first = post[1] if post is not None else firsts[1]
        last = cites[-1].t
        if last - first < CLASSIC_MIN_SPREAD:
            continue
        citers: Dict[str, Dict[str, object]] = {}
        for c in counted:
            entry = citers.setdefault(c.voice, {"voice": c.voice, "name": c.name, "at": c.t.isoformat(), "source_ids": []})
            if c.source_id not in entry["source_ids"]:   # type: ignore[operator]
                entry["source_ids"].append(c.source_id)   # type: ignore[union-attr]
        texts = Counter(c.text for c in cites if _titled(c.text))
        title = post[2] if post is not None else (texts.most_common(1)[0][0] if texts else None)
        out.append(Classic(target, cites[0].stored, len(voices), first, last, title, list(citers.values())))
    return sorted(out, key=lambda c: (-c.voices, -c.days, c.target))


def cited_again(classic_last_at: datetime, now: datetime) -> bool:
    return classic_last_at >= now - CLASSIC_CITED_AGAIN


def classic_order(classic_last_at: datetime, voices: int, days: int, target: str, now: datetime) -> Tuple:
    """Cited again this week first, then most voices, then cited longest. Age never counts against."""
    return (not cited_again(classic_last_at, now), -voices, -days, target)


__all__ = ["names", "surges", "longest", "Surge", "news", "NewsStory", "score", "tally", "lead", "Citation", "Classic",
           "classics", "is_reference", "cited_again", "classic_order"]
