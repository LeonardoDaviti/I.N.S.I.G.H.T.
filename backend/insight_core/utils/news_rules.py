"""News: names in titles, News stories and their score. Pure functions over plain data; the story job
(services/news_service.py) loads the posts and writes what these return (`news`, `surges`, `lead`, `main_story`).
Every News threshold is here, in one place.

A News row is a group of stories joined by surging names (for News only: a name never folds rows in the Main feed);
its score is reports + 1/2 shares + 1/2 roundup mentions, each voice once, in its strongest role. A name is a run of
1 to 3 capitalised or digit-holding words of a title (one word only when it mixes letters and digits, "GPT-6"). A
name surges when, within NAME_WINDOW, NAME_MIN_POSTS+ posts of NAME_MIN_VOICES+ voices use it and it was rarely said
in the NAME_BASELINE before; only sources followed for that whole baseline are evidence (a newer source's archive
joins a burst but never starts it).
"""
from __future__ import annotations

import bisect
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.utils import voice
from insight_core.utils.story_rules import Story, StoryPost, _UnionFind, background, lead_order, roles, story_start, story_times
from insight_core.utils.titles import comparable

# ---- the thresholds, tune here ("the prototype's": plan/research/dedup-prototype's, checked as a whole) ----------

NEWS_DAYS = 30                      # News shows the stories whose first post is in the last 30 days ...
NEWS_RECENT = timedelta(hours=48)   # ... the API's part "recent" the last 48 hours; neither measured
NEWS_KEEP = timedelta(days=30)      # the story job writes News for stories begun this recently; not measured
# The job reads NEWS_EDGE before the window too, so a row whose first post just left it is found whole and never
# re-led by its second post (a name joins posts within NAME_WINDOW).
NEWS_EDGE = timedelta(hours=48)
SCOPE_ROLES = ("origin", "report", "share", "mention")   # a source's part in a News row, strongest first
NEWS_MIN_VOICES = 2                 # the prototype's, not measured
# A row grows only by what holds against a story's core (0203): its lead's names, or CORE_SHARE of its posts' ...
CORE_SHARE = 0.5
# ... and two stories of LARGE_POSTS+ posts join only by each one's main name.
LARGE_POSTS = 5
SHARE_WEIGHT = 0.5                  # the prototype's, not measured
MENTION_WEIGHT = 0.5                # the prototype's, not measured
NAME_WINDOW = timedelta(hours=48)   # a name surges within 48 hours ...
NAME_MIN_POSTS = 3                  # ... in 3+ posts ...
NAME_MIN_VOICES = 2                 # ... of 2+ voices (these three the prototype's, not measured) ...
NAME_MAX_USUAL = 1                  # ... said at most once in the 30 days before (measured: plan/issues/0070) ...
NAME_BASELINE = timedelta(days=30)  # (the 30 days the prototype's)
NAME_MIN_NEW_VOICES = 2             # ... by 2+ voices that didn't say it then (measured: plan/issues/0070)
# A later burst of NAME_WAVE_VOICES voices new to the name is judged as a first (measured: plan/issues/0070).
NAME_WAVE_VOICES = 3
NAME_MAX_WORDS = 3                  # not measured
NAME_SKIP_KINDS = frozenset({"arxiv"})

# ---- names in titles ------------------------------------------------------------------------

TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё0-9][\w\-\.’']*", re.U)
SMALL_WORDS = frozenset("the a an and or of to in on for with is are was be by at from as it its this that how why "
                        "what new you your we our i my vs not".split())
_TRIM = ".’'"


# A word glued to the next line's capital in another script ("CarbonМодель") is two words.
GLUED = re.compile(r"(?<=[A-Za-z0-9])(?=[А-ЯЁ])|(?<=[а-яёА-ЯЁ])(?=[A-Z])")


def _words(title: Optional[str]) -> List[str]:
    return TOKEN.findall(GLUED.sub(" ", comparable(title)))


# A hyphen, an underscore or a non-decimal dot reads as a space: "GPT-6.1 Terra" is "GPT 6.1 Terra".
SEPARATOR = re.compile(r"[-_]+|\.(?!\d)|(?<!\d)\.")


def _lower(words: Sequence[str]) -> List[str]:
    return [" ".join(SEPARATOR.sub(" ", w.lower().strip(_TRIM)).split()) for w in words]


# A month beside a day or a year names a day, not one event: no name (0111).
MONTH = re.compile(r"^(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sept?(ember)?|oct(ober)?"
                   r"|nov(ember)?|dec(ember)?|январ[ьяе]|феврал[ьяе]|марта?|апрел[ьяе]|ма[йяе]|июн[ьяе]|июл[ьяе]"
                   r"|августа?|сентябр[ьяе]|октябр[ьяе]|ноябр[ьяе]|декабр[ьяе])$")
DAY_OR_YEAR = re.compile(r"^(0?[1-9]|[12]\d|3[01])(st|nd|rd|th)?$|^(1\d|2\d)\d\d$")


def dated(words: Sequence[str]) -> bool:
    return any(MONTH.match(w) and any(DAY_OR_YEAR.match(x) for x in words[max(i - 1, 0):i] + words[i + 1:i + 2])
               for i, w in enumerate(words))


def names(title: Optional[str]) -> Set[str]:
    """The names in a title, lowercase, separators as spaces ("gpt 6", "opus 5.5")."""
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
                    continue   # ... and doesn't start with one: "30b", "128gb", "2m" are sizes
            out.add(" ".join(_lower(w)))
    return out


def phrases(title: Optional[str]) -> Set[str]:
    """Every run of 1 to 3 words of a title, lowercase, a joined word ("Model-V4.1-Flash-1017") read as its parts too."""
    words = _lower(_words(title))
    parts = " ".join(words).split()
    return {" ".join(run[i:i + n]) for run in (words, parts)
            for n in range(1, NAME_MAX_WORDS + 1) for i in range(len(run) - n + 1)}


def phrases_among(title: Optional[str], wanted: Any, heads: Optional[Set[str]] = None) -> Set[str]:
    """`phrases(title) & wanted`, made only from runs starting with a wanted name's first word (`heads`)."""
    heads = heads_of(wanted) if heads is None else heads
    words = _lower(_words(title))
    out: Set[str] = set()
    for run in (words, " ".join(words).split()):
        for i, first in enumerate(run):
            if first.split(" ", 1)[0] not in heads:
                continue
            for n in range(1, min(NAME_MAX_WORDS, len(run) - i) + 1):
                phrase = " ".join(run[i:i + n])
                if phrase in wanted:
                    out.add(phrase)
    return out


def heads_of(names_: Iterable[str]) -> Set[str]:
    return {name.split(" ", 1)[0] for name in names_}


@dataclass
class Surge:
    name: str
    at: datetime                 # its first post in the 48 hours
    posts: List[str]             # the posts of those 48 hours, first first
    usual: int                   # posts that used it in the 30 days before


def surges(posts: Sequence[StoryPost], followed_since: Dict[str, datetime]) -> List[Surge]:
    """The names that surge among `posts`, first first. `followed_since`: when each source was added."""
    return sorted(longest(name_surges(posts, followed_since)), key=lambda s: (s.at, s.name))


def name_surges(posts: Sequence[StoryPost], followed_since: Dict[str, datetime],
                only: Optional[Set[str]] = None, named_by: Optional[Dict[str, Set[str]]] = None) -> List[Surge]:
    """Each name's surges among `posts`, before `longest`; a name's depend only on the titles that name or say it.
    `only`: those names' alone; `named_by`: name -> the posts that name it (stored keys)."""
    rows = sorted((p for p in posts if p.title and p.kind not in NAME_SKIP_KINDS), key=lambda p: (p.t, p.id))
    named: Dict[str, List[StoryPost]] = defaultdict(list)
    said: Dict[str, List[StoryPost]] = defaultdict(list)
    if named_by is not None:
        # each name's posts by id, in `rows`' order (0215)
        at = {p.id: i for i, p in enumerate(rows)}
        for name in only or ():
            found_at = sorted(at[pid] for pid in named_by.get(name, ()) if pid in at)
            if found_at:
                named[name] = [rows[i] for i in found_at]
    else:
        for p in rows:
            for name in names(p.title):
                if only is None or name in only:
                    named[name].append(p)
    # only the phrases that are such a name are kept (memory)
    named = {name: uses for name, uses in named.items() if len(uses) >= NAME_MIN_POSTS}
    # few names: only the runs that may say one (phrases_among); every name: every run (faster). Same phrases.
    heads = heads_of(named) if only is not None else None
    for p in rows:
        for phrase in (phrases_among(p.title, named, heads) if heads is not None else phrases(p.title) & named.keys()):
            said[phrase].append(p)
    found = []
    for name, uses in named.items():
        every = said[name]           # in time order, as `rows`
        times = [p.t for p in every]
        after = None                 # the last post of its last surge: a later burst is judged after it
        for start in uses:
            since = start.t - NAME_BASELINE

            def heard(p: StoryPost) -> bool:
                """A post of a source followed for the whole baseline before the burst."""
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
    """(reports, shares, mentions): each voice once, in its strongest role. A source that reposted a tweet is a share,
    the tweet's author a report."""
    best: Dict[str, str] = {}
    posts = [p for p in posts if voice.is_voice(p.kind)]   # a page you saved is no voice
    for p in posts:   # each voice as its owner's
        role = post_roles[p.id]
        own = voice.voice_of(p, voice.Policy.NEWS_IX)
        if best.get(own) != "report":
            best[own] = role
    for p in posts:
        voices = dict(zip(p.other_sources, voice.others_of(p, voice.Policy.NEWS_IX)))
        if p.author_source:
            best[voices[p.author_source]] = "report"
        for source_id in p.reposters:
            best.setdefault(voices[source_id], "share")
    reports = sum(1 for role in best.values() if role == "report")
    mentions = len({voice.voice_of(p, voice.Policy.NEWS_IX) for p in mentioned_by} - set(best))
    return reports, len(best) - reports, mentions


def _said(story: Story, found: Sequence[Surge]) -> Dict[str, Set[str]]:
    mine = {p.id for p in story.posts}
    said: Dict[str, Set[str]] = defaultdict(set)
    for s in found:
        said[s.name] |= mine & set(s.posts)
    return said


def _first(story: Story) -> Optional[str]:
    """A story's first post by time, never by the order handed in (`lead_order`)."""
    if not story.posts:
        return None
    return lead_order(story.posts, story_times(story.posts))[0].id   # never a background page nor a non-report


def core_names(story: Story, found: Sequence[Surge]) -> Set[str]:
    """The surging names a story is about: its first post's, or CORE_SHARE of its posts', the most specific only."""
    first = _first(story)
    if first is None:
        return set()
    said = _said(story, found)
    core = {name for name, ps in said.items() if first in ps or len(ps) >= CORE_SHARE * len(story.posts)}
    # the most specific only: "gemini 4 carbon", never "gemini" inside it
    return {c for c in core if not any(o != c and f" {c} " in f" {o} " for o in core)}


def main_name(story: Story, found: Sequence[Surge]) -> Optional[str]:
    """The most specific core name most of a story's posts say: "Acme releases Vela 5.2" is vela 5.2, not acme."""
    core = core_names(story, found)
    if not core:
        return None
    said = _said(story, found)
    return max(core, key=lambda c: (len(said[c]), len(c), c))


def news(posts: Sequence[StoryPost], stories: Sequence[Story], found: Sequence[Surge], *,
         judged: Optional[Iterable[FrozenSet[str]]] = None) -> List[NewsStory]:
    """The stories joined by the surging names, those with 2+ voices, first first.

    A surging name joins a story's post only when it says one of the story's core names, and a post in several
    stories is in its lowest story id's row only. Two large stories join only by each one's main name. With `judged`
    (Mark X: the story pairs its judge connected) two stories of any size join by a name only when also judged; a
    post of no story still joins by its name alone."""
    by_id = {p.id: p for p in posts}
    # the rows must not depend on input order: the incremental and full jobs read in different orders (0205)
    stories = sorted(stories, key=lambda s: s.id)
    found = sorted(found, key=lambda s: (s.at, s.name, tuple(s.posts)))
    uf = _UnionFind()
    for p in sorted(posts, key=lambda p: p.id):
        uf.find(p.id)
    story_of: Dict[str, Story] = {}
    large: Dict[str, Set[str]] = {}            # a group's root -> its large stories
    held: Dict[str, Set[str]] = {}             # a group's root -> its stories (Mark X: two join only when judged)
    pairs = None if judged is None else {frozenset(x) for x in judged}
    for story in stories:
        for p in story.posts:
            if p.id in story_of:
                continue                       # a post in several stories: the lowest story id's
            uf.union(p.id, story.id)
            story_of[p.id] = story
    _held(stories, uf, large, held)
    cores = {story.id: core_names(story, found) for story in stories}
    mains = {story.id: main_name(story, found) for story in stories}

    def says_main(name: str, group: Set[str]) -> bool:
        return any(mains.get(x) and f" {mains[x]} " in f" {name} " for x in group)

    def join(a: str, b: str, name: str) -> None:
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            return
        la, lb = large.get(ra, set()), large.get(rb, set())
        # two large stories: the name must be each one's main name
        if la and lb and not (says_main(name, la) and says_main(name, lb)):
            return
        ha, hb = held.get(ra, set()), held.get(rb, set())
        # Mark X: two stories of any size only when the judge connected them too (two large ones: those two)
        if pairs is not None and ((ha and hb and not any(frozenset((x, y)) in pairs for x in ha for y in hb))
                                  or (la and lb and not any(frozenset((x, y)) in pairs for x in la for y in lb))):
            return
        uf.union(a, b)
        root = uf.find(a)
        for d, got in ((large, la | lb), (held, ha | hb)):
            d.pop(ra, None), d.pop(rb, None)
            if got:
                d[root] = got
    joined_by: Dict[str, str] = {}
    held_by: Dict[Tuple[str, datetime], List[str]] = {}
    # a post two surging names say joins the one it says first (with names nested in it), never the other
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

    def holds(pid: str, name: str) -> bool:
        """A post of no story always; a story's post when the name says one of its core names."""
        story = story_of.get(pid)
        return story is None or any(f" {c} " in f" {name} " for c in cores.get(story.id, ()))

    find = uf.find
    for surge in found:
        members = sorted((pid for pid in surge.posts if pid in by_id and nested(surge.name, first_said(pid).name)
                          and holds(pid, surge.name)), key=lambda pid: (by_id[pid].t, pid))
        held_by[surge.name, surge.at] = members
        # each post tries every group the surge reached, not only its first post's (0205)
        reached: List[str] = []
        for pid in members:
            for other in reached:
                join(pid, other, surge.name)
            if uf.find(pid) not in {uf.find(r) for r in reached}:
                reached.append(pid)
    # the name each post says, once every join is made: main_story reads it, and a row's lead says the row's name
    for surge in found:
        said = sorted((pid for pid in surge.posts if pid in by_id and nested(surge.name, first_said(pid).name)),
                      key=lambda pid: (by_id[pid].t, pid))
        reached_rows = {find(pid) for pid in held_by[surge.name, surge.at]}
        for pid in said:
            if find(pid) in reached_rows:
                joined_by.setdefault(pid, surge.name)
    groups: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in sorted(posts, key=lambda p: (p.t, p.id)):
        groups[find(p.id)].append(p)
    out = []
    for group in groups.values():
        # its lead (`lead_order`) is the earliest report, never a background page; its start its earliest post
        times = story_times(group)
        group = lead_order(group, times)
        if len(group) < 2 and not group[0].other_sources:   # one tweet your sources pushed is one
            continue
        voices = voice.count(group, voice.Policy.NEWS_IX)   # one owner's channels one voice
        if voices < NEWS_MIN_VOICES:
            continue
        ids = {p.id for p in group}
        post_roles = roles(group)
        mentioning = {pid for story in {story_of[p.id].id: story_of[p.id] for p in group if p.id in story_of}.values()
                      for pid in story.mentions} - ids
        reports, shares, mentions = tally(group, post_roles, [by_id[pid] for pid in mentioning if pid in by_id])
        out.append(NewsStory(
            id=group[0].id, first_at=story_start(group, times), posts=group, voices=voices, roles=post_roles,
            names={p.id: joined_by[p.id] for p in group if p.id in joined_by},
            reports=reports, shares=shares, mentions=mentions,
        ))
    return sorted(out, key=lambda s: (s.first_at, s.id))


def _held(stories: Sequence[Story], uf: _UnionFind, large: Dict[str, Set[str]], held: Dict[str, Set[str]]) -> None:
    for story in stories:
        root = uf.find(story.id)
        held.setdefault(root, set()).add(story.id)
        if len(story.posts) >= LARGE_POSTS:
            large.setdefault(root, set()).add(story.id)


def lead(posts: Sequence[Tuple[str, str]], origins: Iterable[str] = (), roundups: Iterable[str] = (),
         sharers: Iterable[str] = ()) -> Optional[str]:
    """A story's lead: its first origin (`origins`), else its first report, or an earlier share of the story's
    origin page (`sharers`), else its first share; a roundup (`roundups`) is passed over while another report or
    share exists. `posts`: (id, role), oldest first."""
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
    """The posts a row's lead may come from: its main story's (most voices, then posts, then first) and what joined it
    by the name its posts say most; another name's stories never lead. `posts`: (id, story, its voices, the name that
    joined it), oldest first. None: the row holds no story."""
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
