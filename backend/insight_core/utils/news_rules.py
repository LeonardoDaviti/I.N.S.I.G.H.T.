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
  to the next line's capital in another script split; a word joined by hyphens or dots says its
  parts' names too (issue 0083). arXiv titles are left out.
"""
from __future__ import annotations

import bisect
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.utils.story_rules import Story, StoryPost, _UnionFind, count_voices, reposter_voice, roles, story_times
from insight_core.utils.titles import comparable

# ---- the thresholds (issue 0051), tune here -------------------------------------------------
# Each says whether it was measured (issue 0071). "The prototype's": the value of
# plan/research/dedup-prototype, checked as a whole (0051: 19 of 20 surges real), not one by one.

NEWS_DAYS = 30                      # News shows the stories whose first post is in the last 30 days (the owner,
                                    # issue 0077) ...
NEWS_RECENT = timedelta(hours=48)   # ... the API's part "recent" the last 48 hours (the reader splits the rest by
                                    # week); neither measured
NEWS_KEEP = timedelta(days=30)      # the story job writes News for the stories begun in the last 30 days (search's
                                    # "News, last 30 days"); the rows before stay (issue 0077); not measured
# A row is in the window by its first post (issue 0111): the job reads the posts of NEWS_EDGE before the window too,
# so a row whose first post just left it is found whole, and left as it was, never re-led by its second post. A
# name joins posts within NAME_WINDOW, so a post joined to one in the window is at most that much older.
NEWS_EDGE = timedelta(hours=48)
SCOPE_ROLES = ("origin", "report", "share", "mention")   # a source's part in a News row, strongest first (0077)
NEWS_MIN_VOICES = 2                 # the prototype's, not measured
SHARE_WEIGHT = 0.5                  # the prototype's, not measured
MENTION_WEIGHT = 0.5                # the prototype's, not measured
NAME_WINDOW = timedelta(hours=48)   # a name surges within 48 hours ...
NAME_MIN_POSTS = 3                  # ... in 3+ posts ...
NAME_MIN_VOICES = 2                 # ... of 2+ voices (these three the prototype's, not measured) ...
NAME_MAX_USUAL = 1                  # ... said at most once in the 30 days before (measured on the server's data,
NAME_BASELINE = timedelta(days=30)  # 2026-10-30: never before ~88% real, once ~75%, twice or more ~27%;
                                    # the 30 days the prototype's) ...
NAME_MIN_NEW_VOICES = 2             # ... by 2+ voices that didn't say it then (issue 0070, measured on the lab:
                                    # it drops 19 surges, 3 of them real) ... only sources followed for all of
                                    # those 30 days counting
# A later burst of 3+ voices new to the name is judged as a first (issue 0070). Measured, the rule: 16 more
# surges on the lab, 12 real; 3 not compared.
NAME_WAVE_VOICES = 3
NAME_TITLES = NAME_BASELINE + NAME_WINDOW   # the titles a windowed job reads (a full run: every one): a burst
                                    # of the last 48 hours and its 30 days before; an older one's baseline is shorter (0051)
NAME_MAX_WORDS = 3                  # not measured
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


def _words(title: Optional[str]) -> List[str]:
    return TOKEN.findall(GLUED.sub(" ", comparable(title)))


# The separators between a name's parts are one (issue 0070, as search's version names, 0042): a
# hyphen, an underscore or a dot that is no decimal point reads as a space, so "GPT-6.1 Terra",
# "GPT 6.1 Terra" and "FLUX.3 Image" / "FLUX 3 Image" are one name each (an en dash already splits words).
SEPARATOR = re.compile(r"[-_]+|\.(?!\d)|(?<!\d)\.")


def _lower(words: Sequence[str]) -> List[str]:
    return [" ".join(SEPARATOR.sub(" ", w.lower().strip(_TRIM)).split()) for w in words]


# A date is no name (issue 0111): a month beside a day or a year ("Nov 2026", "02 Nov", "March 20") names a
# day, not one event. On the server's copy (2026-11-05) the only three date surges ever ("may 2026", "july 2026",
# "nov 2026") each joined unrelated posts (a column's dated issues, "the best model at <month>?" questions,
# monthly roundups). English and Russian months, their short forms; a day 1-31 (its 1st, 2nd...); a year.
MONTH = re.compile(r"^(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sept?(ember)?|oct(ober)?"
                   r"|nov(ember)?|dec(ember)?|январ[ьяе]|феврал[ьяе]|марта?|апрел[ьяе]|ма[йяе]|июн[ьяе]|июл[ьяе]"
                   r"|августа?|сентябр[ьяе]|октябр[ьяе]|ноябр[ьяе]|декабр[ьяе])$")
DAY_OR_YEAR = re.compile(r"^(0?[1-9]|[12]\d|3[01])(st|nd|rd|th)?$|^(1\d|2\d)\d\d$")


def dated(words: Sequence[str]) -> bool:
    """Whether a name's words (lowercase) hold a date: a month beside a day or a year."""
    return any(MONTH.match(w) and any(DAY_OR_YEAR.match(x) for x in words[max(i - 1, 0):i] + words[i + 1:i + 2])
               for i, w in enumerate(words))


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
            if dated([x.lower().strip(_TRIM) for x in w]):
                continue
            if n == 1:
                letters = [c for c in w[0] if c.isalpha()]
                if not (letters and any(c.isdigit() for c in w[0])):
                    continue   # one word is a name only when it mixes letters and digits ...
                if w[0][0].isdigit():
                    continue   # ... and doesn't start with one: "30b", "128gb", "2m" are sizes (server data, 2026-10-30)
            out.add(" ".join(_lower(w)))
    return out


def phrases(title: Optional[str]) -> Set[str]:
    """Every run of 1 to 3 words of a title, lowercase: where a name is said, in any case. A word
    its separators join ("Model-V4.1-Flash-1017", a repo's name) is read as its parts too, so it
    says "flash 1017" (issue 0083)."""
    words = _lower(_words(title))
    parts = " ".join(words).split()
    return {" ".join(run[i:i + n]) for run in (words, parts)
            for n in range(1, NAME_MAX_WORDS + 1) for i in range(len(run) - n + 1)}


@dataclass
class Surge:
    name: str
    at: datetime                 # its first post in the 48 hours
    posts: List[str]             # the posts of those 48 hours, first first
    usual: int                   # posts that used it in the 30 days before


def surges(posts: Sequence[StoryPost], followed_since: Dict[str, datetime]) -> List[Surge]:
    """The names that surge among `posts` (their titles), first surge first.
    `followed_since`: when each source was added."""
    return sorted(longest(name_surges(posts, followed_since)), key=lambda s: (s.at, s.name))


def name_surges(posts: Sequence[StoryPost], followed_since: Dict[str, datetime],
                only: Optional[Set[str]] = None, named_by: Optional[Dict[str, Set[str]]] = None) -> List[Surge]:
    """Each name's surges among `posts`, before `longest`: a name's depend only on the titles that name
    or say it, so the story job judges again only the names a new title says (issue 0072 A). With
    `only`, those names' alone (`posts` holds every title that names or says them); `named_by`: each of
    those names -> the posts that name it, as their stored keys say (`names` is read again otherwise)."""
    rows = sorted((p for p in posts if p.title and p.kind not in NAME_SKIP_KINDS), key=lambda p: (p.t, p.id))
    named: Dict[str, List[StoryPost]] = defaultdict(list)
    said: Dict[str, List[StoryPost]] = defaultdict(list)
    if named_by is not None:
        for p in rows:
            for name in only or ():
                if p.id in named_by.get(name, ()):
                    named[name].append(p)
    else:
        for p in rows:
            for name in names(p.title):
                if only is None or name in only:
                    named[name].append(p)
    # Only the phrases that are such a name are kept (issue 0072: every title's held 128 MB on the lab).
    named = {name: uses for name, uses in named.items() if len(uses) >= NAME_MIN_POSTS}
    for p in rows:
        for phrase in phrases(p.title) & named.keys():
            said[phrase].append(p)
    found = []
    for name, uses in named.items():
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
    return found


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
    for p in posts:   # each voice as its owner's (issue 0111)
        role = post_roles[p.id]
        if best.get(p.owner_voice) != "report":
            best[p.owner_voice] = role
    for p in posts:
        voices = dict(zip(p.other_sources, p.other_voices(by_owner=True)))
        if p.author_source:
            best[voices[p.author_source]] = "report"
        for source_id in p.reposters:
            best.setdefault(voices[source_id], "share")
    reports = sum(1 for role in best.values() if role == "report")
    mentions = len({p.owner_voice for p in mentioned_by} - set(best))
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
        # A date alone counts as that day's earliest timed post (issue 0072 D): its start, its order, the window.
        times = story_times(group)
        group = sorted(group, key=lambda p: (times[p.id], not p.date_only, p.id))
        if len(group) < 2 and not group[0].other_sources:   # one tweet your sources pushed is one (issue 0068)
            continue
        voices = count_voices(group, by_owner=True)   # one owner's channels one voice (issue 0111)
        if voices < NEWS_MIN_VOICES:
            continue
        ids = {p.id for p in group}
        post_roles = roles(group)
        mentioning = {pid for story in {story_of[p.id].id: story_of[p.id] for p in group if p.id in story_of}.values()
                      for pid in story.mentions} - ids
        reports, shares, mentions = tally(group, post_roles, [by_id[pid] for pid in mentioning if pid in by_id])
        out.append(NewsStory(
            id=group[0].id, first_at=times[group[0].id], posts=group, voices=voices, roles=post_roles,
            names={p.id: joined_by[p.id] for p in group if p.id in joined_by},
            reports=reports, shares=shares, mentions=mentions,
        ))
    return sorted(out, key=lambda s: (s.first_at, s.id))


def lead(posts: Sequence[Tuple[str, str]], origins: Iterable[str] = (), roundups: Iterable[str] = (),
         sharers: Iterable[str] = ()) -> Optional[str]:
    """A story's lead, as 0050's: its origin (issue 0064: the first of `origins`, the posts no
    other post of their 0050 story came from), else its first report or, when one came before it, the
    first share of a 0050 story's origin page (`sharers`: posts hanging from their story's outside
    origin by a link to it, issue 0103), else its first share. Measured on the lab: a share after the
    first report leading too changed 2 more leads of 90, both wrong (a later short post over the first,
    one on another subject). Without an origin, a post the stories list as a roundup
    (`roundups`: 0050's story_mentions, issue 0083) is passed over while a report or share that is none
    exists. `posts`: (id, role), first posted first."""
    origins, roundups, sharers = set(origins), set(roundups), set(sharers)
    for pid, _ in posts:
        if pid in origins:
            return pid
    if roundups and any(role in ("report", "share") and pid not in roundups for pid, role in posts):
        posts = [(pid, role) for pid, role in posts if pid not in roundups]
    for pid, role in posts:
        if role == "report" or (role == "share" and pid in sharers):
            return pid
    for want in ("report", "share"):
        for pid, role in posts:
            if role == want:
                return pid
    return None


def main_story(posts: Sequence[Tuple[str, Optional[str], int, Optional[str]]]) -> Optional[Set[str]]:
    """The posts a row's lead may come from (issue 0111), of `posts` ((id, its 0050 story or None, that
    story's voices, the surging name that joined it), first posted first): its main story's (the most
    voices, then the most posts, then the first), and the stories and posts joined to it by the name its
    posts say most (the first said at a tie). A story joined only by another name (a thread naming the
    row's model in a comparison) never leads. None: the row holds no 0050 story, every post may lead."""
    stories: Dict[str, List[Tuple[str, Optional[str]]]] = defaultdict(list)
    voices: Dict[str, int] = {}
    for pid, story, n, name in posts:
        if story:
            stories[story].append((pid, name))
            voices[story] = n
    if not stories:
        return None
    order = list(stories)
    main = min(order, key=lambda s: (-voices[s], -len(stories[s]), order.index(s)))
    said = [name for _, name in stories[main] if name]
    if not said:
        return {pid for pid, _ in stories[main]}
    counts = {name: said.count(name) for name in said}
    own = max(said, key=lambda name: (counts[name], -said.index(name)))
    joined = {s for s, ps in stories.items() if s == main or any(name == own for _, name in ps)}
    return {pid for pid, story, _, name in posts if (story in joined if story else name == own)}


__all__ = ["names", "surges", "name_surges", "phrases", "longest", "Surge", "news", "NewsStory", "score", "tally", "lead",
           "main_story", "dated"]
