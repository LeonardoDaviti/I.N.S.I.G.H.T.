"""News (issue 0051): names in titles, News stories and their score. Pure functions over plain
data; the story job (services/news_service.py) loads the posts and writes what these return.
Classics are classic_rules.py (issue 0071 split them out of this file).

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
  in the 30 days before, and 2+ of the burst's voices didn't say it then. Only the sources followed
  for those whole 30 days are evidence (issue 0070): a newer source's posts (its archive, a history
  that starts late) join a burst but never start it, make it or age the name. After a surge the
  name is judged again: a later burst of 3+ voices new to it surges too, when it holds more voices
  than the 30 days before (a series a few voices keep saying doesn't). A shorter name whose posts
  a longer one covers is dropped. Titles are compared as plain letters (NFKC) and with a word glued
  to the next line's capital in another script split. arXiv titles are left out.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.utils.story_rules import Story, StoryPost, _UnionFind, count_voices, reposter_voice, roles

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
NAME_MIN_NEW_VOICES = 2             # ... by 2+ voices that didn't say it then (issue 0070) ...
                                    # ... only sources followed for all of those 30 days counting
NAME_WAVE_VOICES = 3                # a later burst of 3+ voices new to the name is judged as a first (issue 0070)
NAME_TITLE_DAYS = 32                # the job reads the titles of the last 32 days (a full run: every one)
NAME_MAX_WORDS = 3
NAME_SKIP_KINDS = frozenset({"arxiv"})

# ---- names in titles ------------------------------------------------------------------------

TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё0-9][\w\-\.’']*", re.U)
SMALL_WORDS = frozenset("the a an and or of to in on for with is are was be by at from as it its this that how why "
                        "what new you your we our i my vs not".split())
_TRIM = ".’'"


# A word glued to the next line's capital in another script ("Gemini 4 CarbonМодель", a Telegram
# title the bridge glued from two lines) is two words; within one script a capital is a name's own
# ("OpenAI"). Measured on the lab (issue 0070): 871 titles, none a word of two scripts.
GLUED = re.compile(r"(?<=[A-Za-z0-9])(?=[А-ЯЁ])|(?<=[а-яёА-ЯЁ])(?=[A-Z])")


def comparable(text: Optional[str]) -> str:
    """Text as it is compared, never as it is shown (issue 0070): styled letters as plain ones
    (NFKC: "𝙻𝙵𝙼𝟹" is "LFM3", a no-break space a space)."""
    return unicodedata.normalize("NFKC", text or "")


def _words(title: Optional[str]) -> List[str]:
    return TOKEN.findall(GLUED.sub(" ", comparable(title)))


# The separators between a name's parts are one (issue 0070, as search's version names, 0042): a
# hyphen, an underscore or a dot that is no decimal point reads as a space, so "GPT-6.1 Terra",
# "GPT 6.1 Terra" and "FLUX.3 Image" / "FLUX 3 Image" are one name each (an en dash already splits words).
SEPARATOR = re.compile(r"[-_]+|\.(?!\d)|(?<!\d)\.")


def _lower(words: Sequence[str]) -> List[str]:
    return [" ".join(SEPARATOR.sub(" ", w.lower().strip(_TRIM)).split()) for w in words]


def names(title: Optional[str]) -> Set[str]:
    """The names in a title, lowercase, its parts' separators one ("steam frame", "gpt 6", "opus 5.5")."""
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
        after = None                 # the last post of its last surge: a later burst is judged after it
        for start in uses:
            since = start.t - NAME_BASELINE

            def heard(p: StoryPost) -> bool:
                """Evidence: a post of a source followed for the whole 30 days before the burst. A newer
                source's posts are its archive or a history that starts late (issue 0051, 0070)."""
                return followed_since.get(p.source_id) is not None and followed_since[p.source_id] <= since

            if (after is not None and start.t <= after) or not heard(start):
                continue
            near = every[bisect.bisect_left(times, start.t):bisect.bisect_right(times, start.t + NAME_WINDOW)]
            burst = [p for p in near if heard(p)]
            voices = {p.place for p in burst}
            if len(burst) < NAME_MIN_POSTS or len(voices) < NAME_MIN_VOICES:
                continue
            before = [p for p in every[bisect.bisect_left(times, since):bisect.bisect_left(times, start.t)] if heard(p)]
            usual = {p.place for p in before}
            new = len(voices - usual)
            if not (len(before) <= NAME_MAX_USUAL and new >= NAME_MIN_NEW_VOICES or new >= NAME_WAVE_VOICES):
                continue
            if len(voices) <= len(usual):
                continue   # a series a few voices keep saying ("May 2026"), not a wave
            found.append(Surge(name, start.t, [p.id for p in near], len(before)))
            after = near[-1].t
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
    roundup's mention). A source that reposted a tweet is a share, the tweet's author a report (issue 0068)."""
    best: Dict[str, str] = {}
    posts = [p for p in posts if p.kind != "saved"]   # a page you saved is no voice (issue 0070)
    for p in posts:
        role = post_roles[p.id]
        if best.get(p.voice) != "report":
            best[p.voice] = role
    for p in posts:
        if p.author_source:
            best[reposter_voice(p.author_source)] = "report"
        for source_id in p.reposters:
            best.setdefault(reposter_voice(source_id), "share")
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
    # A post two surging names say joins the one it says first, with the names inside that one or
    # around it, never another (issue 0070): "Вышел Grok-4.7… как будто чуть лучше Sol" is Grok 4.7's,
    # not GPT-6 Sol's too; a post naming two releases no longer makes them one News row.
    surges_of: Dict[str, List[Surge]] = defaultdict(list)
    for surge in found:
        for pid in surge.posts:
            surges_of[pid].append(surge)

    def first_said(pid: str) -> Surge:
        text = f" {' '.join(_lower(_words(by_id[pid].title)))} "

        def at(s: Surge) -> Tuple[int, int]:
            i = text.find(f" {s.name} ")
            return (i if i >= 0 else len(text), -len(s.name))
        return min(surges_of[pid], key=at)

    def nested(a: str, b: str) -> bool:
        return f" {a} " in f" {b} " or f" {b} " in f" {a} "

    for surge in found:
        members = [pid for pid in surge.posts if pid in by_id and nested(surge.name, first_said(pid).name)]
        for pid in members[1:]:
            uf.union(pid, members[0])
        for pid in members:
            joined_by.setdefault(pid, surge.name)
    groups: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in sorted(posts, key=lambda p: (p.t, p.id)):
        groups[uf.find(p.id)].append(p)
    out = []
    for group in groups.values():
        if len(group) < 2 and not group[0].other_sources:   # one tweet your sources pushed is one (issue 0068)
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


def lead(posts: Sequence[Tuple[str, str]], origins: Iterable[str] = ()) -> Optional[str]:
    """A story's lead, as 0050's: its origin (issue 0064: the first of `origins`, the posts no
    other post of their 0050 story came from), else its first report, else its first share.
    `posts`: (id, role), first posted first."""
    origins = set(origins)
    for pid, _ in posts:
        if pid in origins:
            return pid
    for want in ("report", "share"):
        for pid, role in posts:
            if role == want:
                return pid
    return None


__all__ = ["names", "surges", "longest", "Surge", "news", "NewsStory", "score", "tally", "lead"]
