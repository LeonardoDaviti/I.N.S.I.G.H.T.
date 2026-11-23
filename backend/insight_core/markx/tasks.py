"""Mark X's questions: each kind's input, built from content only, and the task planners.

An input is the exact text the worker sends after the guide, built from content alone (post texts, readings, a
story's members in a fixed order), never from a Mark IX story id: a re-rooted story with the same members has the
same input_hash and is never asked twice, and a story's answer is found again by rebuilding its input
(`repo.task_for`). Post text is `markx text v1` (post_parts' title and text, kept links, the quoted tweet); bump
TEXT_VERSION on purpose to re-read every post. A repost renders as its original author's post shared by the feed,
and counts as the author's voice only when a source follows that author (utils/voice.py). Planners: `plan_posts`
(read, entities), `plan_checks` (check) and the fresh lane, called when the worker asks for work (markx/api.py);
the other kinds are built by S2's candidates and S5's decisions through the builders below.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from psycopg import Cursor

from insight_core.markx import pairing, plan_marks, repo, schemas
from insight_core.utils import byline, voice
from insight_core.utils.byline import author_account, original_author
from insight_core.utils.post_links import source_kind
from insight_core.utils.post_parts import Body, shown

TEXT_VERSION = "markx-text-v1"
TEXT_CHARS = 1500
ENTITY_TEXT_CHARS = 6000     # entities_input under ent-v4 (0133)
TRANSLATE_CHARS = 2500
READ_LINKS, ENTITY_LINKS, JUDGE_LINKS = 12, 6, 6
STORY_MEMBERS = 3            # members a judge question shows
CARD_MEMBERS, HEADLINE_MEMBERS, CONNECT_MEMBERS, BRIEFING_POSTS = 8, 6, 5, 4
HEADLINE_CHARS = 400
PUBLISHER_KINDS = {"site", "arxiv", "hn", "youtube", "saved"}
CERTAIN = {"thread", "quote", "address"}   # a tree reason that is not a guess: no check (unless a roundup)
MIN_WORDS = 20                             # rule A: a shorter post is never judged, never removed
PLAN_DAYS = 30                             # the read, entities and embed planners' default window
PLAN_LIMIT = 500
SCAN_PAGES = 40
READING_WINDOW = "reading_window_days"     # mx_settings: the owner's reading window (null: every post)
SETTING = object()                         # a planner's `days` when the caller names none: the owner's setting

# The fresh lane (0176 A): a post fetched or surfaced in the last FRESH_HOURS is planned first for FRESH_KINDS, and a
# lease gives those tasks up to FRESH_SHARE of its slots, so a backfill never holds a new post back.
FRESH_HOURS = 24
FRESH_KINDS = ("read", "entities", "read3", "headline", "reading")   # a headline by its story's first post
FRESH_SHARE = 0.75                                         # of a lease's slots, at most
FRESH_DATED_DAYS = 7                                       # and dated in the last week: an archive import is not new


def fresh_sql(alias: str = "p", since: str = "%(fresh)s") -> str:
    """The fresh lane's SQL condition over posts `alias`; `since` is the lane's start (now - FRESH_HOURS)."""
    return (f"(GREATEST({alias}.fetched_at, {alias}.surfaced_at) >= {since} "
            f"AND {pairing.ordinary_date(alias)} "
            f">= {since}::timestamptz + make_interval(hours => {FRESH_HOURS}) - make_interval(days => {FRESH_DATED_DAYS}))")


def reading_window(cur: Cursor) -> Optional[int]:
    """The read, entities and embed planners' window in days (None: every post; PLAN_DAYS when never set), read on
    every planner run. The decision window and plan_checks follow markx/story_window.py instead."""
    value = repo.get_setting(cur, READING_WINDOW, default=PLAN_DAYS)
    return None if value is None else int(value)


def set_reading_window(cur: Cursor, days: Optional[int]) -> Optional[int]:
    repo.set_setting(cur, READING_WINDOW, days)
    return days


READING_PLANNED = "reading_window_planned"   # mx_settings: {kind: the window its planner last ran for}
NEVER = "never"


def planned_window(cur: Cursor, kind: str) -> Any:
    """The window `kind`'s planner last ran for (days, None for every post), or NEVER."""
    return (repo.get_setting(cur, READING_PLANNED, default=None) or {}).get(kind, NEVER)


def note_planned(cur: Cursor, kind: str, days: Optional[int]) -> None:
    value = dict(repo.get_setting(cur, READING_PLANNED, default=None) or {})
    if value.get(kind, NEVER) != days:
        value[kind] = days
        repo.set_setting(cur, READING_PLANNED, value)


# ---- the posts, as Mark X reads them (markx text v1) ----------------------------------------------

@dataclass
class Post:
    id: str
    kind: str                 # the platform as the reader names it (site, telegram, x, ...)
    source: str
    source_id: str
    at: datetime
    title: str
    text: str
    links: List[Tuple[str, Optional[str]]] = field(default_factory=list)
    quote: Optional[str] = None
    lang: Optional[str] = None
    by: Optional[str] = None  # a repost's or forward's original author ("@acme"), not the feed's
    counts_as: Optional[str] = None   # the author's source, when one of the sources follows the author

    @property
    def iso(self) -> str:
        return self.at.astimezone(timezone.utc).isoformat()

    @property
    def who(self) -> str:
        """Who a render says wrote it: the source, or "a post by @X shared by <source>" for a repost."""
        return byline.who({"author": self.by, "via": self.source})

    @property
    def voice(self) -> str:
        """The voice it counts as: a repost's author when a source follows that author, else its own source."""
        return voice.voice_of(self, voice.Policy.MARKX)


def _squash(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def load_posts(cur: Cursor, ids: Iterable[Any], *, linked: bool = True) -> Dict[str, Post]:
    """{id: Post} for the posts that exist (markx text v1).

    A link post with no words of its own is read with its linked page's text once the originals step has the page
    (0208), so every question sees what it shares. `linked` False: the posts' own text only."""
    ids = [str(i) for i in ids]
    if not ids:
        return {}
    cur.execute(
        f"""SELECT p.id, s.platform, s.handle_or_url,
                  COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''),
                           s.handle_or_url),
                  p.source_id, {pairing.ordinary_date('p')}, COALESCE(pp.title, p.title),
                  p.content, pp.text_cut, pp.text_decode_entities, pp.text_cut_leaves_break, pp.text_copy, pp.quoted,
                  p.language_code, p.author, NULLIF(btrim(p.metadata->'forwarded_from'->>'name'), ''),
                  NULLIF(btrim(p.metadata->'forwarded_from'->>'username'), '')
             FROM posts p JOIN sources s ON s.id = p.source_id LEFT JOIN post_parts pp ON pp.post_id = p.id
            WHERE p.id = ANY(%s::uuid[])""", (ids,))
    out: Dict[str, Post] = {}
    owns: Dict[Tuple[Any, Any], str] = {}
    followed: Optional[Dict[str, str]] = None
    for (pid, platform, handle, name, source_id, at, title, content, cut, decode, brk, copy, quoted,
         lang, author, forwarded, forwarded_user) in cur.fetchall():
        text = shown(content, Body(cut=cut, decode_entities=bool(decode), cut_leaves_break=bool(brk), copy=copy))
        kind = source_kind(platform, handle)
        by = original_author(kind, platform, handle, author, forwarded, owns)
        account = author_account(kind, by, forwarded_user)
        if account and followed is None:
            followed = voice.followed_accounts(cur)
        counts = voice.counted_source(str(source_id), account, followed or {}) if account else None
        out[str(pid)] = Post(id=str(pid), kind=kind, source=name or "", source_id=str(source_id),
                             at=at, title=_squash(title), text=(text or "").strip(), quote=quoted, lang=lang,
                             by=by, counts_as=counts if counts != str(source_id) else None)
    cur.execute("""SELECT post_id, target_url, link_text FROM post_links
                    WHERE NOT boilerplate AND post_id = ANY(%s::uuid[]) ORDER BY post_id, position""", (ids,))
    for pid, url, anchor in cur.fetchall():
        if str(pid) in out:
            out[str(pid)].links.append((url, anchor))
    if linked and out:
        _with_linked_pages(cur, out)
    return out


def _with_linked_pages(cur: Cursor, out: Dict[str, Post]) -> None:
    """Appends the linked page's text to each link post of `out` with no words of its own (0208)."""
    from insight_core.utils import originals_rules as rules
    cur.execute(f"""SELECT p.id::text, ({plan_marks.LINKED_PAGE.format(post='p.id')})::text FROM posts p
                     WHERE p.id = ANY(%s::uuid[])""", (sorted(out),))
    pages = {pid: page for pid, page in cur.fetchall() if page and page != pid}
    if not pages:
        return
    got = load_posts(cur, set(pages.values()), linked=False)
    for pid, page in pages.items():
        p, g = out[pid], got.get(page)
        if g is None or not g.text:
            continue
        own = p.text[len(p.title):] if p.title and p.text.startswith(p.title) else p.text
        if len(own.strip()) > rules.LINK_POST_OWN_CHARS:
            continue
        head = f"[The page it links: {g.title}]" if g.title else "[The page it links]"
        p.text = (p.text + "\n\n" if p.text else "") + head + "\n" + g.text[:rules.LINKED_PAGE_CHARS]


def readings(cur: Cursor, ids: Iterable[Any], guide: Optional[str] = None) -> Dict[str, dict]:
    """{post id: reading} under `guide`; None: the preferred reading (reading5.pick)."""
    if guide is None:
        from insight_core.markx import reading5
        return {k: v["reading"] for k, v in reading5.pick(cur, ids, ("read-v2",)).items()}
    return {str(k): v["reading"] for k, v in repo.readings(cur, list(ids), guide).items()}


def words(p: Post) -> int:
    return len((p.title + " " + p.text).split())


# A near-copy: another member's folded text, or a 5-word shingle Jaccard of COPY_JACCARD or more. Never checked,
# so never removed or demoted (0112).
COPY_SHINGLE, COPY_JACCARD = 5, 0.6


def fold(s: Optional[str]) -> str:
    return re.sub(r"[\W_]+", " ", (s or "").lower().replace("ё", "е")).strip()


def shingles(p: Post, k: int = COPY_SHINGLE) -> set:
    w = re.findall(r"\w+", (p.title + " " + p.text).lower())
    return {tuple(w[i:i + k]) for i in range(max(0, len(w) - k + 1))}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def near_copy(a: Post, b: Post) -> bool:
    fa = fold(a.title + " " + a.text)
    return (bool(fa) and fa == fold(b.title + " " + b.text)) or _jaccard(shingles(a), shingles(b)) >= COPY_JACCARD


def near_copies(members: Sequence[Post]) -> set:
    keys = [(fold(m.title + " " + m.text), shingles(m)) for m in members]
    out = set()
    for i, (fi, si) in enumerate(keys):
        for j in range(i + 1, len(keys)):
            fj, sj = keys[j]
            if (fi and fi == fj) or _jaccard(si, sj) >= COPY_JACCARD:
                out.update((members[i].id, members[j].id))
    return out


def voices(posts: Iterable[Post]) -> int:
    return voice.count(posts, voice.Policy.MARKX)


def _cut(text: str, n: int) -> str:
    return text[:n] + (" […]" if len(text) > n else "")


# ---- the renders ----------------------------------------------------------------------------------

def _head(p: Post) -> List[str]:
    lines = [f"Platform: {p.kind} | Source: {p.source}", f"Title: {p.title}"]
    if p.by:
        lines.insert(1, f"Author: {p.by} (a post by {p.by} shared by {p.source}; not {p.source}'s own words)")
    return lines


def post_block(p: Post, nlinks: int, chars: int = TEXT_CHARS) -> str:
    """The post as every reader sees it: head, text, links in order, the quote."""
    lines = _head(p)
    if p.text:
        lines.append("Text: " + _cut(p.text, chars))
    if p.links:
        lines.append("Links, in order:")
        for n, (url, anchor) in enumerate(p.links[:nlinks]):
            lines.append(f"{n + 1}. {url}" + (f' "{anchor[:80]}"' if anchor else ""))
        if len(p.links) > nlinks:
            lines.append(f"(+{len(p.links) - nlinks} more links)")
    if p.quote:
        lines.append(f"Quotes the tweet: {p.quote}")
    return "\n".join(lines)


def render_post(p: Post, reading: Optional[dict]) -> str:
    lines = ["POST", f"Platform: {p.kind} | Source: {p.source}", f"Title: {p.title}"]
    if p.text:
        lines.append("Text: " + _cut(p.text, TEXT_CHARS))
    if p.links:
        lines.append("Links: " + " | ".join(url + (f' "{anchor[:60]}"' if anchor else "")
                                            for url, anchor in p.links[:JUDGE_LINKS]))
    if reading:
        m = reading.get("main") or {}
        lines.append(f"Reading of the post: kind={reading.get('kind')}, events={reading.get('events')}, "
                     f"main={m.get('headline_en', '') if m else ''}; mentions="
                     + ", ".join(f"{x.get('name')} ({x.get('role')})" for x in (reading.get("mentions") or [])[:6]))
    return "\n".join(lines)


def render_story(card: dict, members: Sequence[Post]) -> str:
    lines = ["STORY", f"Headline: {card.get('headline_en') or ''}"]
    slots = [f"{k}: {card[k] if isinstance(card[k], str) else ', '.join(map(str, card[k]))}"
             for k in ("actors", "object", "action", "date") if card.get(k)]
    if slots:
        lines.append("Event: " + "; ".join(slots))
    if card.get("summary_en"):
        lines.append("Summary: " + card["summary_en"])
    if members:
        lines.append("Members (earliest first):")
        for m in members[:STORY_MEMBERS]:
            lines.append(f"- [{m.source}, {m.kind}] {m.title[:160]} — {m.text[:240]}")
    return "\n".join(lines)


def rule_card(members: Sequence[Post], rd: Dict[str, dict]) -> dict:
    """A card without a model: the earliest report's main event (a publisher's first), else the most common
    object's, else the earliest member's title."""
    rs = [(m, rd.get(m.id)) for m in members]
    reports = [(m, r) for m, r in rs if r and r.get("kind") == "report" and r.get("main")]
    pick = None
    if reports:
        pubs = [(m, r) for m, r in reports if m.kind in PUBLISHER_KINDS]
        pick = (pubs or reports)[0]
    else:
        objs = Counter((r["main"].get("object") or "").lower() for m, r in rs if r and r.get("main"))
        if objs:
            top = objs.most_common(1)[0][0]
            pick = next(((m, r) for m, r in rs if r and r.get("main")
                         and (r["main"].get("object") or "").lower() == top), None)
    if not pick:
        return {"headline_en": members[0].title[:140] if members else ""}
    main = pick[1]["main"]
    return {k: main.get(k, "") for k in ("headline_en", "actors", "object", "action", "date")}


def _earliest(posts: Iterable[Post]) -> List[Post]:
    return sorted(posts, key=lambda p: (p.at, p.id))


def _member_line(p: Post, chars: int, when: str, shared: bool = False) -> str:
    """`shared`: a repost says whose post it is."""
    return f"- [{p.who if shared else p.source}, {p.kind}, {when}] {p.title[:160]} — {p.text[:chars]}"


# ---- the inputs, one function a kind --------------------------------------------------------------

def read_input(p: Post) -> str:
    return post_block(p, READ_LINKS)


def entities_input(p: Post, chars: int = TEXT_CHARS) -> str:
    return post_block(p, ENTITY_LINKS, chars)


def _render(cur: Cursor, kind: str) -> Any:
    if kind == "read":
        return read_input
    chars = schemas.entities_arm(cur).chars
    return lambda p: entities_input(p, chars)


# ---- a long post's entities read in windows (0176 B) -----------------------------------------------
# A post longer than `chars` is asked per window: the first window's input is entities_input (the same task as a short
# post's), each later one shows the post's head and its slice of the text. Consecutive windows share WINDOW_OVERLAP
# characters so a name cut at one window's end is whole in the next; text past `max_windows` stays unread.

WINDOW_OVERLAP = 200
MAX_WINDOWS = 12
WINDOWS_SETTING = "entity_windows_max"   # mx_settings: the owner's cap (1: the first window only)
WINDOW_N = repo.WINDOW_N                # window w's mentions are numbered from w * WINDOW_N
_WINDOW_LINE = re.compile(r"^Window: (\d+) of (\d+) ", re.M)


def max_windows(cur: Cursor) -> int:
    got = repo.get_setting(cur, WINDOWS_SETTING, default=MAX_WINDOWS)
    try:
        return max(1, int(got))
    except (TypeError, ValueError):
        return MAX_WINDOWS


def set_max_windows(cur: Cursor, n: int) -> int:
    n = max(1, int(n))
    repo.set_setting(cur, WINDOWS_SETTING, n)
    return n


def text_windows(text: str, chars: int, cap: int = MAX_WINDOWS) -> List[Tuple[int, int]]:
    """The windows (start, end) a text is read in: one unless it is longer than `chars`, at most `cap`."""
    n = len(text or "")
    if n <= chars or cap <= 1:
        return [(0, min(n, chars))]
    step = chars - WINDOW_OVERLAP
    count = min(cap, 1 + -(-(n - chars) // step))
    return [(w * step, min(n, w * step + chars)) for w in range(count)]


def window_input(p: Post, w: int, windows: Sequence[Tuple[int, int]]) -> str:
    """Window w's input (w >= 1); the post's links and quote are read with its first window only."""
    start, end = windows[w]
    n = len(p.text)
    lines = _head(p)
    lines.append(f"Window: {w + 1} of {len(windows)} of the post's text (characters {start + 1:,}-{end:,} of {n:,})")
    lines.append("Text: […] " + p.text[start:end] + (" […]" if end < n else ""))
    return "\n".join(lines)


def entity_inputs(p: Post, chars: int, cap: int = MAX_WINDOWS) -> List[str]:
    windows = text_windows(p.text, chars, cap)
    return [entities_input(p, chars)] + [window_input(p, w, windows) for w in range(1, len(windows))]


def window_of(input: str) -> int:
    m = _WINDOW_LINE.search(input.split("\nText: ", 1)[0])
    return int(m.group(1)) - 1 if m else 0


def window_overlap(input: str) -> Tuple[str, str]:
    """A later window's text as (the part shared with the window before, the rest); ("", "") for the first."""
    body = input.split("\nText: […] ", 1)
    if window_of(input) == 0 or len(body) < 2:
        return "", ""
    return body[1][:WINDOW_OVERLAP], body[1][WINDOW_OVERLAP:]


def add_entities(cur: Cursor, p: Post, *, chars: int, cap: int, priority: int = 0) -> Tuple[bool, int]:
    """The post's entities tasks, a window each: (whether the first window's is new, how many were added)."""
    inputs = entity_inputs(p, chars, cap)
    first = add(cur, "entities", inputs[0], a=p.id, priority=priority)[1]
    return first, int(first) + sum(1 for x in inputs[1:] if add(cur, "entities", x, a=p.id, priority=priority)[1])


def check_input(post: Post, members: Sequence[Post]) -> str:
    """The raw-text form: the story by its earliest other member's title and first members, the post unread."""
    ms = [m for m in _earliest(members) if m.id != post.id]
    card = {"headline_en": ms[0].title} if ms else {}
    return render_story(card, ms[:STORY_MEMBERS]) + "\n\n" + render_post(post, None)


def shows_empty_story(text: str) -> bool:
    """Whether a check's input shows its story with no member (0112)."""
    return "\nMembers (earliest first):\n" not in text.split("\n\nPOST\n", 1)[0] + "\n"


def join_input(post: Post, reading: Optional[dict], members: Sequence[Post], card: dict) -> str:
    ms = [m for m in _earliest(members) if m.id != post.id]
    return render_story(card, ms[:STORY_MEMBERS]) + "\n\n" + render_post(post, reading)


def pair_input(anchor: Post, post: Post, rd: Dict[str, dict]) -> str:
    return render_story(rule_card([anchor], rd), [anchor]) + "\n\n" + render_post(post, rd.get(post.id))


def merge_input(card_a: dict, members_a: Sequence[Post], card_b: dict, members_b: Sequence[Post]) -> str:
    a = render_story(card_a, _earliest(members_a)[:STORY_MEMBERS]).replace("STORY", "STORY A", 1)
    b = render_story(card_b, _earliest(members_b)[:STORY_MEMBERS]).replace("STORY", "STORY B", 1)
    return a + "\n\n" + b


def connect_input(members_a: Sequence[Post], members_b: Sequence[Post]) -> str:
    """Each story by when it was first seen, how many sources, and its earliest members with dates."""
    def one(tag: str, ps: Sequence[Post]) -> str:
        ps = _earliest(ps)
        # counted by source, not by repost author: this input must not change (not asked again)
        n = voice.count((voice.Said(p.source_id, p.kind) for p in ps), voice.Policy.MARKX)
        lines = [f"STORY {tag} — first seen {ps[0].iso[:10]}; {n} sources", "Members (earliest first):"]
        lines += [_member_line(p, 300, p.iso[:10]) for p in ps[:CONNECT_MEMBERS]]
        return "\n".join(lines)
    return one("A", members_a) + "\n\n" + one("B", members_b)


def card_input(members: Sequence[Post], rd: Dict[str, dict]) -> str:
    """The first members, earliest first, each by an 8-character id the card's `odd` names."""
    lines = []
    for m in _earliest(members)[:CARD_MEMBERS]:
        r = rd.get(m.id) or {}
        main = (r.get("main") or {}).get("headline_en", "")
        lines.append(f"- id {m.id[:8]} [{m.who}, {m.kind}, {m.iso[:16]}] {m.title[:160]} | {m.text[:300]} | "
                     f"reading: {r.get('kind')}, {main}")
    return "MEMBERS:\n" + "\n".join(lines)


_CORE_WORD = re.compile(r"\w*\d\w*|\w{5,}")   # a word a member's core is told by: a name, a version, a number


def _core_words(p: Post) -> set:
    return set(_CORE_WORD.findall(fold(p.title + " " + p.text[:HEADLINE_CHARS])))


def headline_members(members: Sequence[Post]) -> List[Post]:
    """The members a headline reads, the story's core, earliest first. A larger story than HEADLINE_MEMBERS shows the
    posts whose words most other voices share (ties by time), a feed's copies left out, so an early teaser or
    side post cannot write a big story's headline."""
    ps = _earliest(members)
    if len(ps) <= HEADLINE_MEMBERS:
        return ps
    words = {p.id: _core_words(p) for p in ps}
    voices: Dict[str, set] = {}
    for p in ps:
        for w in words[p.id]:
            voices.setdefault(w, set()).add(p.voice)
    shared = {p.id: sum(len(voices[w] - {p.voice}) for w in words[p.id]) for p in ps}
    shown: List[Post] = []
    seen = set()
    for p in sorted(ps, key=lambda p: (-shared[p.id], p.at, p.id)):
        same = (p.voice, fold(p.title + " " + p.text[:HEADLINE_CHARS]))
        if same in seen:
            continue
        seen.add(same)
        shown.append(p)
        if len(shown) == HEADLINE_MEMBERS:
            break
    return _earliest(shown)


def headline_input(members: Sequence[Post]) -> str:
    """The story's core members (headline_members), earliest first. It changes only when the core does, so a
    headline is asked again only then, not for every later post."""
    return "Members (the story's core, earliest first):\n" + "\n".join(
        _member_line(p, HEADLINE_CHARS, p.iso[:10], shared=True) for p in headline_members(members))


def briefing_input(day: date, stories: Sequence[Tuple[str, Sequence[Post]]]) -> str:
    """The day's stories (at most 10, in the caller's order) keyed s1..sN, each with its headline, sources and posts."""
    parts = [f"DAY {day.isoformat()}: {len(stories[:10])} stories"]
    for n, (headline, posts) in enumerate(stories[:10], 1):
        ps = _earliest(posts)
        sources = list(dict.fromkeys(p.by or p.source for p in ps))
        parts.append(f"\n[s{n}] {headline} — {voices(ps)} sources: {', '.join(sources[:8])}")
        parts += [f"  - [{p.who}, {p.kind}, {p.iso[11:16]}] {p.title[:160]} — {p.text[:250]}"
                  for p in ps[:BRIEFING_POSTS]]
    return "\n".join(parts)


def translate_input(p: Post) -> str:
    return f"Title: {p.title}\nText: {p.text[:TRANSLATE_CHARS]}"


# ---- tasks ---------------------------------------------------------------------------------------

def add(cur: Cursor, kind: str, input: str, *, a: Any = None, b: Any = None, day: Optional[date] = None,
        priority: int = 0) -> Tuple[UUID, bool]:
    """The task asking `input` under `kind`'s guide: (its id, whether it is new)."""
    spec = schemas.KINDS[kind]
    schemas.ensure_guides(cur)
    guide = schemas.guide_of(cur, kind)
    return repo.add_task(cur, kind=kind, guide=guide, subject_kind=spec.subject, input=input, a=a, b=b, day=day,
                         priority=priority)


def _posts(cur: Cursor, ids: Sequence[Any]) -> List[Post]:
    got = load_posts(cur, ids)
    missing = [str(i) for i in ids if str(i) not in got]
    if missing:
        raise LookupError(f"no post {missing[0]}")
    return [got[str(i)] for i in ids]


def read_task(cur: Cursor, post_id: Any, priority: int = 0):
    p, = _posts(cur, [post_id])
    return add(cur, "read", read_input(p), a=p.id, priority=priority)


def entities_task(cur: Cursor, post_id: Any, priority: int = 0):
    """The post's first window's entities task (its id, whether it is new); later windows are added with it."""
    p, = _posts(cur, [post_id])
    inputs = entity_inputs(p, schemas.entities_arm(cur).chars, max_windows(cur))
    got = add(cur, "entities", inputs[0], a=p.id, priority=priority)
    for x in inputs[1:]:
        add(cur, "entities", x, a=p.id, priority=priority)
    return got


def translate_task(cur: Cursor, post_id: Any, priority: int = 0):
    p, = _posts(cur, [post_id])
    return add(cur, "translate", translate_input(p), a=p.id, priority=priority)


def check_task(cur: Cursor, post_id: Any, members: Sequence[Any], *, story: Any = None):
    """Is this member about the story's event (`members`: the others)? `story`: a Mark X story, never Mark IX's."""
    post, *ms = _posts(cur, [post_id, *[m for m in members if str(m) != str(post_id)]])
    return add(cur, "check", check_input(post, ms), a=post.id, b=story)


def join_task(cur: Cursor, post_id: Any, members: Sequence[Any], *, card: Optional[dict] = None, story: Any = None):
    """Does the post belong in the story of `members`? Its card: `card` (a card-v1 answer), else the rule card."""
    post, *ms = _posts(cur, [post_id, *[m for m in members if str(m) != str(post_id)]])
    rd = readings(cur, [post.id, *[m.id for m in ms]])
    return add(cur, "join", join_input(post, rd.get(post.id), ms, card or rule_card(_earliest(ms), rd)),
               a=post.id, b=story)


def pair_task(cur: Cursor, anchor_id: Any, post_id: Any):
    anchor, post = _posts(cur, [anchor_id, post_id])
    return add(cur, "pair", pair_input(anchor, post, readings(cur, [anchor.id, post.id])), a=anchor.id, b=post.id)


def merge_task(cur: Cursor, members_a: Sequence[Any], members_b: Sequence[Any], *, card_a: Optional[dict] = None,
               card_b: Optional[dict] = None, a: Any = None, b: Any = None):
    pa, pb = _posts(cur, members_a), _posts(cur, members_b)
    rd = readings(cur, [p.id for p in pa + pb])
    pa, pb = _earliest(pa), _earliest(pb)
    return add(cur, "merge", merge_input(card_a or rule_card(pa, rd), pa, card_b or rule_card(pb, rd), pb),
               a=a or pa[0].id, b=b or pb[0].id)


def connect_task(cur: Cursor, members_a: Sequence[Any], members_b: Sequence[Any], *, a: Any = None, b: Any = None):
    pa, pb = _earliest(_posts(cur, members_a)), _earliest(_posts(cur, members_b))
    return add(cur, "connect", connect_input(pa, pb), a=a or pa[0].id, b=b or pb[0].id)


def card_task(cur: Cursor, members: Sequence[Any], *, story: Any = None):
    ps = _earliest(_posts(cur, members))
    return add(cur, "card", card_input(ps, readings(cur, [p.id for p in ps])), a=story or ps[0].id)


def headline_task(cur: Cursor, members: Sequence[Any], *, story: Any = None):
    ps = _earliest(_posts(cur, members))
    return add(cur, "headline", headline_input(ps), a=story or ps[0].id)


def briefing_task(cur: Cursor, day: date, stories: Sequence[Tuple[str, Sequence[Any]]]):
    """The day's briefing from its top News rows: [(headline, member post ids)], most voices first."""
    rows = [(headline, _posts(cur, members)) for headline, members in stories]
    return add(cur, "briefing", briefing_input(day, rows), day=day)


# ---- planning: what is asked without S2 or S5 ------------------------------------------------------

def plan_posts(cur: Cursor, kind: str, *, days: Any = SETTING, limit: int = PLAN_LIMIT,
               now: Optional[datetime] = None, fetched_since: Optional[datetime] = None) -> int:
    """Adds `read` or `entities` tasks for the posts of the last `days` (default `reading_window`; None: every post)
    with none under the kind's guide, newest first (priority: age in days); returns how many. `fetched_since`: the
    fresh lane's posts (`fresh_sql`) instead, whatever the window."""
    guide = schemas.guide_of(cur, kind)   # a new guide plans new tasks; no row rewritten
    if fetched_since is not None:
        days = None
    elif days is SETTING:
        days = reading_window(cur)
    render = _render(cur, kind)
    from insight_core.markx import reading5
    old_kinds = reading5.old_kinds_sql(cur, "p.id")
    chars, cap = (schemas.entities_arm(cur).chars, max_windows(cur)) if kind == "entities" else (0, 1)
    added, after = 0, None
    # a post whose input repeats an asked one gets no task and stays unplanned: page past such posts (keyset, at most
    # SCAN_PAGES) and mark them (plan_marks) so they are not read again while their text is unchanged
    for _page in range(SCAN_PAGES):
        rows = plan_marks.execute(cur,
            f"""SELECT p.id, GREATEST(0, floor(extract(epoch FROM (COALESCE(%(now)s, now())
                                        - {pairing.ordinary_date('p')})) / 86400))::int,
                      {pairing.ordinary_date('p')}, {plan_marks.STAMP}
                 FROM posts p
                WHERE (%(days)s::int IS NULL OR {pairing.ordinary_date('p')}
                                                 >= COALESCE(%(now)s, now()) - make_interval(days => %(days)s))
                  AND (%(fresh)s::timestamptz IS NULL OR {fresh_sql()})
                  AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = p.id)
                  AND {plan_marks.unmarked()}
                  AND (%(fresh)s::timestamptz IS NOT NULL   -- v10.22: the window's posts narrowed first (the fresh lane's are few)
                       OR {plan_marks.unread("NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = q.id)")})
                  AND p.filtered_by IS NULL   -- 0196: a post its source's item filter hid is never read
                  AND {old_kinds}             -- 0212: not a post ent-v5 reads, while its switch is on
                  AND (%(at)s::timestamptz IS NULL
                       OR ({pairing.ordinary_date('p')}, p.id) < (%(at)s::timestamptz, %(id)s::uuid))
                ORDER BY {pairing.ordinary_date('p')} DESC, p.id DESC
                LIMIT %(limit)s""",
            {"now": now, "days": days, "kind": kind, "guide": guide, "limit": limit, "fresh": fetched_since,
             "at": after[0] if after else None, "id": after[1] if after else None})
        posts = load_posts(cur, [r[0] for r in rows])
        passed = []
        for pid, age, _at, stamp in rows:
            if added >= limit:
                break
            p = posts.get(str(pid))
            if p is None:
                continue
            if kind == "entities":
                first, n = add_entities(cur, p, chars=chars, cap=cap, priority=age)
                added += n
            else:
                first = add(cur, kind, render(p), a=p.id, priority=age)[1]
                added += int(first)
            if not first:
                passed.append((p.id, plan_marks.SAME_INPUT, stamp))
        plan_marks.mark(cur, kind, guide, passed)
        if added >= limit or len(rows) < limit:
            break
        after = (rows[-1][2], rows[-1][0])
    return added


def check_questions(cur: Cursor, *, days: Optional[int] = PLAN_DAYS, now: Optional[datetime] = None,
                    threads: Optional[bool] = None) -> Iterable[Tuple[Post, str]]:
    """The checks over Mark IX's current stories, as (post, input), without writing (Mark IX is only read): every
    member of a 2+ voice story but its earliest, joined by a guess or a roundup, of MIN_WORDS or more unless a
    roundup, and not a near-copy; with `threads` (default Config.check_threads), `thread` joins too. Stories with
    a member in the last `days` (None: every story)."""
    if threads is None:
        from insight_core.markx.decide import Config   # one setting for both planners (decide imports this module)
        threads = Config().check_threads
    certain = CERTAIN - {"thread"} if threads else CERTAIN
    cur.execute(
        f"""SELECT sp.story_id, sp.post_id, sp.role, sp.parent_reason FROM story_posts sp
            WHERE %(days)s::int IS NULL
               OR sp.story_id IN (SELECT sp2.story_id FROM story_posts sp2 JOIN posts p ON p.id = sp2.post_id
                                   WHERE {pairing.ordinary_date('p')}
                                         >= COALESCE(%(now)s, now()) - make_interval(days => %(days)s))""",
        {"now": now, "days": days})
    stories: Dict[str, List[Tuple[str, str, Optional[str]]]] = {}
    for story, post, role, reason in cur.fetchall():
        stories.setdefault(str(story), []).append((str(post), role, reason))
    # a chunk of stories at a time, and only the readings' kind, to bound the plan job's memory (0183)
    order = list(stories.values())
    for at in range(0, len(order), CHECK_CHUNK):
        chunk = order[at:at + CHECK_CHUNK]
        posts = load_posts(cur, {p for ms in chunk for p, _, _ in ms})
        kinds = reading_kinds(cur, list(posts))
        yield from _checks_of(chunk, posts, kinds, certain)


CHECK_CHUNK = 500   # stories a check planner reads at once


def reading_kinds(cur: Cursor, ids: Sequence[str], guide: Optional[str] = None) -> Dict[str, Any]:
    """{post id: its reading's kind} under `guide`; None: the preferred reading's (reading5.guides)."""
    from insight_core.markx import reading5
    order = [guide] if guide else reading5.guides(cur, "read-v2")
    cur.execute("""SELECT DISTINCT ON (post_id) post_id::text, reading->'kind' FROM mx_readings
                    WHERE post_id = ANY(%s::uuid[]) AND guide = ANY(%s)
                    ORDER BY post_id, array_position(%s::text[], guide)""", (list(ids), order, order))
    return dict(cur.fetchall())


def _checks_of(stories: Sequence[List[Tuple[str, str, Optional[str]]]], posts: Dict[str, Post], kinds: Dict[str, Any],
               certain: Any) -> Iterable[Tuple[Post, str]]:
    for ms in stories:
        members = _earliest(posts[p] for p, _, _ in ms if p in posts)
        if voices(members) < 2:
            continue
        why = {p: reason for p, _, reason in ms}
        reports = {p for p, role, _ in ms if role == "report"}
        copies = near_copies(members)
        for p in members[1:]:
            if not voice.is_voice(p.kind) or p.id in copies:
                continue
            roundup = kinds.get(p.id) == "roundup"
            if (why.get(p.id) in certain or words(p) < MIN_WORDS) and not roundup:
                continue
            side = check_side(p, members, reports)
            if side:
                yield p, check_input(p, side)


def check_side(post: Post, members: Sequence[Post], reports: Iterable[str]) -> List[Post]:
    """The story a check of `post` shows: its other `reports`, else its other members of any role (an empty story
    made Haiku answer "different", 0112); [] when it has no other member: a story's only post is never checked."""
    reports = set(reports)
    return ([m for m in members if m.id in reports and m.id != post.id]
            or [m for m in members if m.id != post.id])


# kinds the decision job plans, never a lease: their planners are too slow for a lease's wait (0216)
BACKGROUND_PLANNED = ("check", "cite", "track", "relate", "stop",
                      "chain",
                      "derive")


def planned_in_background(cur: Cursor, kind: str, now: Optional[datetime] = None) -> bool:
    """Whether the decision job (jobs.Jobs.plan_background), not a lease, plans `kind`; `check` only while the story
    window is wide."""
    if kind == "check":
        return checks_in_background(cur, now)
    return kind in BACKGROUND_PLANNED


# What each background planner reads (markx/unchanged.py skips a pass while these are as they were at its last pass
# that planned nothing, 0183): every table it reads or writes (of mx_tasks only the kinds it reads), and in the key its
# code and settings. A kind with no declaration (track, relate) always runs: its inputs move with the clock or would
# mean stamping every post.
_TEXT = ("posts", "post_parts", "post_links", "sources")
BACKGROUND_INPUTS = {
    "check": _TEXT + ("story_posts", "mx_readings", "mx_tasks[check]", "mx_settings", "mx_guides"),
    "cite": _TEXT + ("mx_tasks[cite,entities]", "mx_plan_marks", "mx_settings", "mx_guides"),
}
_PLANNER_CODE = ("insight_core.markx.tasks", "insight_core.markx.plan_marks", "insight_core.markx.ent42",
                 "insight_core.markx.story_window", "insight_core.markx.pairing", "insight_core.markx.schemas",
                 "insight_core.markx.repo", "insight_core.utils.post_parts", "insight_core.utils.post_links",
                 "insight_core.utils.voice", "insight_core.utils.byline")


def background_inputs(cur: Cursor, kind: str, now: datetime) -> Tuple[Sequence[str], Any]:
    """(tables, key) of the background planner `kind`'s pass at `now` (unchanged.run); key None: it always runs."""
    if kind not in BACKGROUND_INPUTS:
        return (), None
    from insight_core.markx import unchanged
    key: Dict[str, Any] = {"kind": kind, "code": unchanged.code_stamp(_PLANNER_CODE), "limit": PLAN_LIMIT}
    if kind == "check":
        from insight_core.markx import story_window
        from insight_core.markx.decide import Config
        key.update(days=story_window.days_for_run(cur, now), threads=Config().check_threads)
    else:
        key.update(days=reading_window(cur), arm=schemas.entities_arm(cur).guide)
    return BACKGROUND_INPUTS[kind], key


def checks_in_background(cur: Cursor, now: Optional[datetime] = None) -> bool:
    """Whether the checks are planned by the decision job: while the story window reaches past RECENT days planning
    them takes longer than a worker waits for its lease; within RECENT days a lease plans them."""
    from insight_core.markx import story_window
    return story_window.days_for_run(cur, now or datetime.now(timezone.utc)) > story_window.RECENT


def plan_checks(cur: Cursor, *, days: Any = SETTING, limit: int = PLAN_LIMIT, now: Optional[datetime] = None) -> int:
    """Adds `check_questions`' tasks for the last `days` (default: the story window; None: every story); returns
    how many. Past RECENT days, older posts' checks come newest first, at most BACKFILL_PAGE a call, at the
    backfill's priority."""
    from insight_core.markx import story_window
    at = now or datetime.now(timezone.utc)
    if days is SETTING:
        days = story_window.days_for_run(cur, at)
    if days is not None and days <= story_window.RECENT:
        added = 0
        for p, text in check_questions(cur, days=days, now=now):
            if add(cur, "check", text, a=p.id)[1]:
                added += 1
                if added >= limit:
                    break
        return added
    edge = at - timedelta(days=story_window.RECENT)
    # keep only time, id and input per question, not the post (memory, 0183)
    asked = sorted(((p.at, p.id, text) for p, text in check_questions(cur, days=days, now=now)),
                   key=lambda q: (q[0], q[1]), reverse=True)
    added = old = 0
    for when, pid, text in asked:
        late = when < edge
        if late and old >= story_window.BACKFILL_PAGE or not late and added >= limit:
            continue
        if add(cur, "check", text, a=pid, priority=story_window.BACKFILL_PRIORITY if late else 0)[1]:
            if late:
                old += 1
            else:
                added += 1
    return added + old


def reasked(cur: Cursor) -> Dict[str, Dict[str, int]]:
    """Of the open and answered check tasks, how many today's Mark IX stories would no longer ask:
    {"check": {"tasks", "would_change"}} (reported by the real-data check for a story-rule change)."""
    today = {repo.sha256_hex(text) for _p, text in check_questions(cur, days=None)}
    cur.execute("SELECT input_hash FROM mx_tasks WHERE kind = 'check' AND status IN ('open', 'leased', 'answered')")
    hashes = [h for (h,) in cur.fetchall()]
    return {"check": {"tasks": len(hashes), "would_change": sum(1 for h in hashes if h not in today)}}


def _plan_embeds(cur: Cursor, **kw) -> int:
    """The embed planner, over the reading window unless the caller names `days`."""
    from insight_core.markx import embed   # embed imports this module
    if kw.get("days", SETTING) is SETTING:
        kw["days"] = reading_window(cur)
    return embed.plan(cur, **kw)


def _plan_names(cur: Cursor) -> int:
    from insight_core.markx import embed
    return embed.plan_names(cur)


def _plan_read3(cur: Cursor, **kw) -> int:
    from insight_core.markx import folds   # folds imports this module
    return folds.plan(cur, **kw)


WINDOWED = ("read", "entities", "embed", "read3", "cite")   # planners the reading window applies to
PLANNERS = {"read": lambda cur, **kw: plan_posts(cur, "read", **kw),
            "entities": lambda cur, **kw: plan_posts(cur, "entities", **kw),
            "check": plan_checks,
            "embed": _plan_embeds,
            "embed_name": lambda cur, **kw: _plan_names(cur),
            "read3": lambda cur, **kw: _plan_read3(cur, **kw),
            "translate": lambda cur, **kw: _plan_translations(cur, **kw),
            "relate": lambda cur, **kw: _plan_relate(cur),
            "back": lambda cur, **kw: _plan_back(cur),
            "stop": lambda cur, **kw: _plan_stops(cur),
            "chain": lambda cur, **kw: _plan_chains(cur),
            "derive": lambda cur, **kw: _plan_derive(cur)}


def _plan_back(cur: Cursor) -> int:   # capped like the decision run's
    from insight_core.markx import back
    from insight_core.markx.decide import Config
    return back.plan(cur, open_cap=Config().back_open)


def _plan_stops(cur: Cursor) -> int:
    from insight_core.markx import stops   # stops reads this module
    return stops.plan(cur)["asked"]


def _plan_chains(cur: Cursor) -> int:
    from insight_core.markx import graph   # graph imports this module
    return graph.plan_chains(cur)["asked"]


def _plan_derive(cur: Cursor) -> int:
    from insight_core.markx import graph   # graph imports this module
    return graph.plan_derive(cur)["asked"]


def _plan_relate(cur: Cursor) -> int:   # capped like the decision run's
    from insight_core.markx import graph   # graph imports this module
    from insight_core.markx.decide import Config
    return graph.plan(cur, open_cap=Config().relate_open)


def _plan_translations(cur: Cursor, **kw) -> int:
    from insight_core.markx import translate   # translate imports this module
    return translate.plan(cur, **kw)


# ---- what a valid answer writes besides its call ----------------------------------------------------

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−⁃﹘﹣－"), "-")


def name_key(name: Optional[str]) -> str:
    """A name's key: NFKC, dashes as '-', no soft hyphen, casefold, ё as е, letters glued to digits split,
    separators as one space. key("Qwen3.8‑Flash") == key("qwen 3.8 flash")."""
    s = unicodedata.normalize("NFKC", name or "").translate(_DASHES).replace("­", "")
    s = s.casefold().replace("ё", "е")
    s = re.sub(r"(?<=[a-zа-я])(?=\d)", " ", s)
    return re.sub(r"[\s_\-/·,:;()\[\]\"'«»“”]+", " ", s).strip()


SEARCHED_KINDS = ("read", "read3", "entities", "cite")   # the answers mx_post_search is made of


def _note_happening(cur: Cursor, task: Dict[str, Any]) -> None:
    """Stores the post's happening key once a reading, mention set or cite answer lands."""
    from insight_core.markx import happening
    if task["kind"] in ("entities", "cite") or task["guide"] in happening.reading_guides(cur):
        happening.note(cur, [str(task["a"])])


def _note_units(cur: Cursor, task: Dict[str, Any]) -> None:
    """Splits the post into units again once a reading lands, in a savepoint: a failure is logged and the reading
    stands (the candidates job splits it later)."""
    from insight_core.markx import units
    if task["guide"] not in units.reading_guides(cur):
        return
    try:
        with cur.connection.transaction():
            units.note(cur, [str(task["a"])])
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Mark X: splitting a read post into units failed")


def record(cur: Cursor, task: Dict[str, Any], call_id: Any, answer: dict) -> None:
    """The rows a task's first valid answer adds: a post's reading (mx_readings) or its entities (mx_mentions)."""
    if task["a"] is None:
        return
    if task["kind"] in ("read", "read3"):          # a read3 answer is a reading under read-v3
        main = answer.get("main") or {}
        repo.add_reading(cur, post_id=task["a"], guide=task["guide"], call_id=call_id, kind=answer.get("kind"),
                         events=answer.get("events"), lang=answer.get("lang"), headline=main.get("headline_en"),
                         reading=answer)
        _note_happening(cur, task)
        _note_units(cur, task)
    elif task["kind"] == "relate":
        from insight_core.markx import graph
        graph.after_answer(cur, task)
    elif task["kind"] == "chain":
        from insight_core.markx import graph
        graph.chain_after_answer(cur, task)
    elif task["kind"] == "derive":
        from insight_core.markx import graph
        graph.derive_after_answer(cur, task)
    elif task["kind"] == "back":
        from insight_core.markx import back
        back.after_answer(cur, task)
    elif task["kind"] == "entities":
        win = window_of(task["input"])   # 0: the first window, every short post's
        entities = answer.get("entities") or []
        if win:   # a name wholly in the text the window shares with the one before was read there
            shared, rest = window_overlap(task["input"])
            entities = [e for e in entities if not (e.get("span") and e["span"] in shared and e["span"] not in rest)]
        mentions = [dict({f: e.get(f) for f in repo.MENTION_FIELDS}, name_key=name_key(e.get("name")),
                         by_name=e.get("by") or None)
                    for e in entities]
        arm = schemas.ENTITY_ARMS.get(task["guide"])
        if win == 0 and arm is not None and arm.rule:   # the citation rule, merged in
            from insight_core.markx import citations
            mentions = citations.for_post(cur, task["a"], mentions, name_key)
        if task["guide"] == "ent-v4.2":    # own title dropped, the cite answer merged; no rule
            from insight_core.markx import ent42
            mentions = (ent42.main_mentions(cur, task["a"], entities) if win == 0
                        else ent42.window_mentions(cur, task["a"], entities))   # the cite answer is window 0's
        repo.add_mentions(cur, post_id=task["a"], guide=task["guide"], call_id=call_id, mentions=mentions, win=win)
        _note_happening(cur, task)
    elif task["kind"] == "reading":
        from insight_core.markx import reading5
        reading5.record(cur, task, call_id, answer)
    elif task["kind"] == "cite":
        from insight_core.markx import ent42
        ent42.after_cite(cur, task, call_id, answer)
        _note_happening(cur, task)
    elif task["kind"] in ("track", "subtopics", "digest", "subtopic_place"):
        from insight_core.markx import tracks
        tracks.after_answer(cur, task, call_id, answer)
        if task["kind"] == "track":                 # a scout's test-read item shares the judge
            from insight_core.markx import scout
            scout.after_judge(cur, task, answer)
    elif task["kind"] in ("track_schema", "track_things", "track_same"):
        from insight_core.markx import track_things
        track_things.after_answer(cur, task, call_id, answer)
    elif task["kind"] == "probes":
        from insight_core.markx import finders
        finders.after_answer(cur, task, call_id, answer)
    elif task["kind"] == "scout":
        from insight_core.markx import scout
        scout.after_answer(cur, task, answer)
    elif task["kind"] == "identity":
        from insight_core.markx import research
        research.after_identity(cur, task, answer)
    elif task["kind"] == "websearch":
        from insight_core.markx import research
        research.after_websearch(cur, task, answer)
    elif task["kind"] == "source_judge":
        from insight_core.markx import source_judge
        source_judge.after_answer(cur, task, answer)
    elif task["kind"] == "news_sections":
        from insight_core.markx import news_sections
        news_sections.after_answer(cur, task, call_id, answer)
    elif task["kind"] == "news_place":
        from insight_core.markx import news_sections
        news_sections.after_place(cur, task, call_id, answer)
    elif task["kind"] == "unit_types":
        from insight_core.markx import units
        units.after_types(cur, task, call_id, answer)
    if task["kind"] in SEARCHED_KINDS:
        from insight_core.markx import search
        search.refresh_safely(cur, [task["a"]])


def release(cur: Cursor, worker: str, task_ids: Optional[Sequence[Any]] = None) -> int:
    """Hand back `worker`'s leased tasks (all, or those of `task_ids`) without counting a try: how many."""
    if task_ids is None:
        return repo.release_tasks(cur, worker)
    cur.execute("UPDATE mx_tasks SET status = 'open', lease_until = NULL, leased_by = NULL "
                "WHERE status = 'leased' AND leased_by = %s AND id = ANY(%s::uuid[])",
                (worker, [str(t) for t in task_ids]))
    return cur.rowcount


# ---- a source's stance (monthly), and each thin source's last posts read (behind a switch) ----------------------

STANCE_POSTS = 15
STANCE_MIN_CHARS = 250
STANCE_CHARS = 1200
STANCE_DAYS = 90             # the stats window
LAST_POSTS = 20
LAST_POSTS_BELOW = 10
LAST_POSTS_SWITCH = "INSIGHT_MARKX_READ_LAST20"   # off by default


def stance_input(name: str, kind: str, texts: Sequence[str]) -> str:
    """The stance question: the source's name and kind, then its posts numbered [1]..[N] (title and text, cut)."""
    return f"Source: {name} ({kind})\n\n" + "\n\n".join(f"[{i + 1}] {t[:STANCE_CHARS]}" for i, t in enumerate(texts))


def plan_stance(cur: Cursor, *, now: Optional[datetime] = None, limit: int = PLAN_LIMIT, **_kw: Any) -> int:
    """One `stance` task per source a month (never Reddit): STANCE_POSTS random own posts of the last STANCE_DAYS,
    seeded by source and month so a month asks one question. How many were added."""
    import random
    from datetime import timedelta
    from insight_core.markx import source_stats   # source_stats reads this module's kinds
    if now is None:
        cur.execute("SELECT now()")
        now = cur.fetchone()[0]
    month = now.astimezone(timezone.utc).strftime("%Y-%m")
    srcs = source_stats.sources(cur)
    cur.execute("""SELECT DISTINCT a::text FROM mx_tasks WHERE kind = 'stance' AND a IS NOT NULL
                    AND created_at >= date_trunc('month', %s::timestamptz)""", (now,))
    asked = {r[0] for r in cur.fetchall()}
    cur.execute(f"""SELECT p.id::text, p.source_id::text, COALESCE(p.title, ''), COALESCE(p.content, ''), p.author,
                          p.reposted_by, (p.metadata ? 'forwarded_from')
                     FROM posts p
                    WHERE p.source_id = ANY(%s::uuid[])
                      AND {pairing.ordinary_date('p')} >= %s
                      AND length(COALESCE(p.title, '')) + length(COALESCE(p.content, '')) >= %s
                    ORDER BY p.id""",
                ([s for s in srcs if s not in asked and srcs[s].kind != "reddit"], now - timedelta(days=STANCE_DAYS),
                 STANCE_MIN_CHARS))
    by: Dict[str, List[str]] = {}
    for _pid, sid, title, content, author, reposted_by, fwd in cur.fetchall():
        if source_stats.is_repost(srcs[sid], title, author, reposted_by, fwd):
            continue
        text = f"{_squash(title)}\n{content.strip()}" if title.strip() else content.strip()
        if len(text) >= STANCE_MIN_CHARS:
            by.setdefault(sid, []).append(text)
    added = 0
    for sid in sorted(by):
        texts = by[sid]
        if len(texts) < STANCE_POSTS:
            continue
        random.Random(f"{sid}:{month}").shuffle(texts)
        s = srcs[sid]
        if add(cur, "stance", stance_input(s.name, s.kind, texts[:STANCE_POSTS]), a=sid, priority=1000)[1]:
            added += 1
            if added >= limit:
                break
    return added


def last_posts_on() -> bool:
    import os
    return os.getenv(LAST_POSTS_SWITCH, "off").strip().lower() in ("on", "1", "true", "yes")


def plan_last_posts(cur: Cursor, kind: str, *, limit: int = PLAN_LIMIT, now: Optional[datetime] = None) -> int:
    """Tasks of `kind` for the last LAST_POSTS posts of every source with fewer than LAST_POSTS_BELOW posts read,
    only while LAST_POSTS_SWITCH is on (fills the role card's "too few to tell"). How many were added.

    Only the kinds the current reading uses: while ent-v5 is on only `reading` plans (a post no picked guide has
    read); otherwise `read` and `entities` do and `reading` plans nothing."""
    from insight_core.markx import reading5   # reading5 imports this module
    if not last_posts_on() or (kind == reading5.KIND) != reading5.is_on(cur):
        return 0
    if kind == reading5.KIND:
        guide = reading5.GUIDE
        read = "SELECT 1 FROM mx_readings r WHERE r.post_id = {post} AND r.guide = ANY(%(read)s)"
    else:
        guide = schemas.guide_of(cur, kind)
        read = ("SELECT 1 FROM mx_readings r WHERE r.post_id = {post} AND r.guide = %(guide)s" if kind == "read" else
                "SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = {post} "
                "AND t.status = 'answered'")
    cur.execute(
        f"""WITH few AS (SELECT s.id FROM sources s
                          WHERE s.platform <> 'saved'
                            AND (SELECT count(*) FROM posts p WHERE p.source_id = s.id
                                    AND EXISTS ({read.format(post="p.id")})) < %(below)s),
                 last AS (SELECT p.id, {pairing.ordinary_date('p')} AS at,
                                 row_number() OVER (PARTITION BY p.source_id ORDER BY
                                                    {pairing.ordinary_date('p')} DESC, p.id DESC) AS k
                            FROM posts p WHERE p.source_id IN (SELECT id FROM few))
            SELECT l.id, GREATEST(0, floor(extract(epoch FROM (COALESCE(%(now)s, now()) - l.at)) / 86400))::int
              FROM last l
             WHERE l.k <= %(last)s
               AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = l.id)
               AND NOT EXISTS ({read.format(post="l.id")})
             ORDER BY 2, l.id
             LIMIT %(limit)s""",
        {"guide": guide, "kind": kind, "below": LAST_POSTS_BELOW, "last": LAST_POSTS, "now": now, "limit": limit,
         "read": reading5.guides(cur, "read-v3", "read-v2")})
    rows = cur.fetchall()
    if kind == reading5.KIND:
        return reading5.add_posts(cur, [(pid, age, None) for pid, age in rows])[0]
    posts = load_posts(cur, [r[0] for r in rows])
    render = _render(cur, kind)
    added = 0
    for pid, age in rows:
        p = posts.get(str(pid))
        if p is None:
            continue
        if kind == "entities":
            added += add_entities(cur, p, chars=schemas.entities_arm(cur).chars, cap=max_windows(cur), priority=age)[1]
        elif add(cur, kind, render(p), a=p.id, priority=age)[1]:
            added += 1
    return added


def _with_last_posts(kind: str, planner: Any) -> Any:
    def plan(cur: Cursor, **kw: Any) -> int:
        return planner(cur, **kw) + plan_last_posts(cur, kind)
    return plan


PLANNERS["stance"] = plan_stance
PLANNERS["read"] = _with_last_posts("read", PLANNERS["read"])
PLANNERS["entities"] = _with_last_posts("entities", PLANNERS["entities"])

WINDOWS_MARK = "entities-windows"   # plan_marks' kind for a long post the windows planner passed over


def plan_windows(cur: Cursor, *, days: Any = SETTING, limit: int = PLAN_LIMIT, now: Optional[datetime] = None) -> int:
    """Adds the later windows of posts whose first window was asked alone (before windows, or under a lower cap),
    newest first, over the reading window (or `days`; None: every post); returns how many. A post needing one
    window, or whose windows are another post's tasks, is marked until its text changes."""
    from insight_core.markx import reading5
    cap = max_windows(cur)
    if cap <= 1:
        return 0
    guide = schemas.guide_of(cur, "entities")
    chars = schemas.entities_arm(cur).chars
    if days is SETTING:
        days = reading_window(cur)
    rows = plan_marks.execute(cur,
        f"""SELECT p.id, GREATEST(0, floor(extract(epoch FROM (COALESCE(%(now)s, now())
                                    - {pairing.ordinary_date('p')})) / 86400))::int,
                  {plan_marks.STAMP}
             FROM posts p
            WHERE (%(days)s::int IS NULL OR {pairing.ordinary_date('p')}
                                             >= COALESCE(%(now)s, now()) - make_interval(days => %(days)s))
              AND octet_length(p.content) > %(chars)s   -- bytes: a toasted text is not decompressed
              AND {reading5.old_kinds_sql(cur, "p.id")}   -- 0212
              AND (SELECT count(*) FROM mx_tasks t                -- its first window's task only (no input read)
                    WHERE t.a = p.id AND t.kind = 'entities' AND t.guide = %(guide)s) = 1
              AND {plan_marks.unmarked()}
            ORDER BY {pairing.ordinary_date('p')} DESC, p.id DESC
            LIMIT %(limit)s""",
        {"now": now, "days": days, "chars": chars, "guide": guide, "kind": WINDOWS_MARK, "limit": limit})
    posts = load_posts(cur, [r[0] for r in rows])
    added, passed = 0, []
    for pid, age, stamp in rows:
        p = posts.get(str(pid))
        if p is None:
            continue
        inputs = entity_inputs(p, chars, cap)
        new = sum(1 for x in inputs[1:] if add(cur, "entities", x, a=p.id, priority=age)[1])
        added += new
        if not new:
            passed.append((p.id, plan_marks.ONE_WINDOW if len(inputs) == 1 else plan_marks.SAME_INPUT, stamp))
        if added >= limit:
            break
    plan_marks.mark(cur, WINDOWS_MARK, guide, passed)
    return added


def _with_windows(planner: Any) -> Any:
    def plan(cur: Cursor, **kw: Any) -> int:
        got = planner(cur, **kw)
        return got + plan_windows(cur, **{k: v for k, v in kw.items() if k in ("days", "now")})
    return plan


PLANNERS["entities"] = _with_windows(PLANNERS["entities"])


def fresh_since(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - timedelta(hours=FRESH_HOURS)


def plan_fresh(cur: Cursor, kind: str, *, limit: int = PLAN_LIMIT, now: Optional[datetime] = None) -> int:
    """The fresh lane's planning for `kind` (read, entities, read3), whatever the reading window: how many were
    added. A lease runs it first, every time; the general planner only when its queue runs low."""
    since = fresh_since(now)
    if kind in ("read", "entities"):
        return plan_posts(cur, kind, limit=limit, now=now, fetched_since=since)
    if kind == "read3":
        from insight_core.markx import folds
        return folds.plan(cur, limit=limit, now=now, fetched_since=since)
    return 0


FRESH_PLANNERS = {k: (lambda kind: lambda cur, **kw: plan_fresh(cur, kind, **kw))(k) for k in ("read", "entities", "read3")}


def _plan_reading(cur: Cursor, **kw: Any) -> int:
    from insight_core.markx import reading5   # reading5 imports this module
    return reading5.plan(cur, **kw)


PLANNERS["reading"] = _with_last_posts("reading", _plan_reading)
FRESH_PLANNERS["reading"] = _with_last_posts("reading", _plan_reading)


def _plan_cite(cur: Cursor, **kw: Any) -> int:
    from insight_core.markx import ent42   # ent42 imports this module
    return ent42.plan(cur, **kw)


PLANNERS["cite"] = _plan_cite


# ---- tracks as topics (markx/tracks.py) --------------------------------------------------------------------------

def _plan_tracks(cur: Cursor, **kw: Any) -> int:
    from insight_core.markx import tracks   # tracks imports this module
    return tracks.plan(cur, **kw)


def _plan_subtopics(cur: Cursor, **kw: Any) -> int:
    from insight_core.markx import track_subtopics
    return track_subtopics.plan_names(cur, **kw)


def _plan_place(cur: Cursor, **kw: Any) -> int:
    from insight_core.markx import track_subtopics
    return track_subtopics.plan_place(cur, **kw)


def _plan_digests(cur: Cursor, **kw: Any) -> int:   # sub-topic digests, track briefs' "what changed", entity points
    from insight_core.markx import entity_brief, track_brief, track_subtopics
    return (track_subtopics.plan_digests(cur, **kw) + track_brief.plan(cur, **kw)
            + entity_brief.plan_points(cur, **kw))


def _plan_track_things(kind: str) -> Any:
    def plan(cur: Cursor, **kw: Any) -> int:
        from insight_core.markx import entity_brief, track_things
        if kind == "track_things":   # a track's posts, then the briefed entities' (the entity as the track)
            return track_things.plan_things(cur, **kw) + entity_brief.plan_things(cur, **kw)
        if kind == "track_schema":
            from insight_core.markx import track_fields
            return track_things.plan_schemas(cur, **kw) + track_fields.plan(cur, **kw)
        return track_things.plan_same(cur, **kw)
    return plan




def _with_track_vectors(planner: Any) -> Any:   # tracks' descriptions, example posts and members embedded too
    def plan(cur: Cursor, **kw: Any) -> int:
        from insight_core.markx import finders, tracks
        return (tracks.plan_vectors(cur) + finders.plan_vectors(cur) + tracks.plan_member_vectors(cur)
                + planner(cur, **kw))
    return plan


def _plan_probes(cur: Cursor, **kw: Any) -> int:
    from insight_core.markx import finders
    return finders.plan_probes(cur, **kw)


PLANNERS["track"] = _plan_tracks
PLANNERS["subtopics"] = _plan_subtopics
PLANNERS["digest"] = _plan_digests
PLANNERS["subtopic_place"] = _plan_place
PLANNERS["probes"] = _plan_probes
for _kind in ("track_schema", "track_things", "track_same"):
    PLANNERS[_kind] = _plan_track_things(_kind)
PLANNERS["embed"] = _with_track_vectors(PLANNERS["embed"])


def _plan_news_sections(cur: Cursor, **kw: Any) -> int:
    from insight_core.markx import news_sections   # news_sections imports this module
    return news_sections.plan(cur, **kw)


PLANNERS["news_sections"] = _plan_news_sections


def _plan_news_place(cur: Cursor, **kw: Any) -> int:
    from insight_core.markx import news_sections
    return news_sections.place(cur, **kw)


PLANNERS["news_place"] = _plan_news_place


# ---- a task's input lifetime (0233) -----------------------------------------------------------------------------
# SPENDS: the kinds whose input nothing reads once answered (tests/test_markx_spend.py lists every reader of
# mx_tasks.input; a new reader fails it until placed). Opt-in: any other kind keeps its input. Within SPENDS, a short
# embed input (embed.set_aside) and a later entities/reading window (ent42.after_cite) are kept too. input_hash stays,
# so dedupe holds and the same question is never asked again; nothing is rebuilt from a NULL.
SPENDS = ("cite", "embed", "embed_name", "entities", "read", "read3", "reading", "track")
SPEND_AFTER = timedelta(days=14)   # the worker's same-cycle re-asks (0214) and debugging read these
SPEND_BATCH = 20000
WINDOW_RE = r"\nWindow: \d+ of \d+ "   # a later window's input (window_input), as Postgres reads it


def spend(cur: Cursor, *, now: Optional[datetime] = None, older: timedelta = SPEND_AFTER, batch: int = SPEND_BATCH,
          after: Optional[str] = None) -> Tuple[int, Optional[str]]:
    """One keyset batch of `batch` rows from `after`: answered SPENDS inputs older than `older` set to NULL.
    Returns (how many were spent, the last id looked at or None when the pass is done)."""
    from insight_core.markx import embed   # embed imports this module
    cur.execute("""WITH look AS (SELECT id, kind, status, answered_at, input FROM mx_tasks
                                  WHERE (%(after)s::uuid IS NULL OR id > %(after)s::uuid)
                                  ORDER BY id LIMIT %(batch)s),
                        spent AS (UPDATE mx_tasks t SET input = NULL FROM look l
                                   WHERE t.id = l.id AND l.status = 'answered' AND l.input IS NOT NULL
                                     AND l.kind = ANY(%(kinds)s)
                                     AND l.answered_at < COALESCE(%(now)s::timestamptz, now()) - %(older)s
                                     AND NOT (l.kind = 'embed' AND length(l.input) <= %(short)s)
                                     AND NOT (l.kind IN ('entities', 'reading') AND l.input ~ %(window)s)
                                  RETURNING 1)
                   SELECT (SELECT count(*) FROM spent), (SELECT id::text FROM look ORDER BY id DESC LIMIT 1),
                          (SELECT count(*) FROM look)""",
                {"after": after, "batch": batch, "kinds": list(SPENDS), "now": now, "older": older,
                 "short": embed.SCAN_CHARS, "window": WINDOW_RE})
    n, last, looked = cur.fetchone()
    return int(n), (last if looked >= batch else None)


def spend_all(db_url: str, *, now: Optional[datetime] = None, batch: int = SPEND_BATCH) -> int:
    """The daily pass: `spend` batch after batch, one short transaction each. How many inputs were spent."""
    from insight_core.db import database
    total, after = 0, None
    while True:
        with database.connection(db_url) as conn, conn.cursor() as cur:
            n, after = spend(cur, now=now, after=after, batch=batch)
        total += n
        if after is None:
            return total
