"""Mark X Shadow's questions (issue 0086 C): each kind's input, built from content only, and the tasks.

The input is the exact text the worker sends after the guide. It is built from content alone (the posts'
texts, their readings, a story's members in a fixed order), never from a Mark IX story id (build plan,
corrections 2): a story Mark IX re-roots with the same members asks the same question, so its input_hash
is the same and it is never asked twice. A story's answer is found again by building its input from
today's members (`repo.task_for`), not by an id. A task's `a` and `b` are posts (a story task's are its
earliest member posts) or Mark X stories when S5 passes them; never a Mark IX story id.

Mark X's text is its own function, `markx text v1` (corrections 3): the title every page shows and the
first 1,500 characters of the text every page shows, both read from post_parts (issue 0076), the post's
kept links in order and the tweet it quotes. A post_parts change in Mark IX changes Mark X's inputs only
when TEXT_VERSION is bumped on purpose (a bump re-reads every post). Translation reads 2,500 characters,
as the prototype measured it (F5).

The renders are the prototype's (plan/research/lab/markx/proto: read.block, judge.render*, cards.model_card,
exp_f4, exp_f6, exp_f12, exp_f5), and each question sees the evidence that suits it (hybrid.py):
  - read, entities: the post;
  - check: the raw post and the story's members, no reading (judge-raw-v1);
  - join, pair: the post with its reading, and the story's card and members (judge-read-v1);
  - merge: both stories as cards and up to 3 members each (judge-story-v1);
  - connect: both stories by up to 5 members each, with dates (connect-v1);
  - card, headline: the story's members (with their readings for the card);
  - briefing: the day's top stories, keyed s1..sN, with a few posts each;
  - translate: the post's title and text.

0168 E: a repost (an X row its feed carried but another account wrote; a Telegram forward) says so wherever a reading,
a card, a headline or a briefing reads it: "Author: @acme (a post by @acme shared by <feed>)", members as
"[a post by @acme shared by <feed>, x, ...]", so a story never reads "<feed> announces" for another account's post.
It counts as its author's voice (`voices`) only when one of the sources follows that author, as Mark IX counts it
(Voice's rule, utils/voice.py: voice.counted_source); a stranger's post its feed carries stays the feed's voice. The
sameness questions (check, join, pair, merge, connect) are unchanged: they ask whether two posts tell one story, not
who said it (and are not asked again).

Who creates which tasks: `plan_posts` (read, entities: the newest posts of the last 30 days first,
corrections 8) and `plan_checks` (check: Mark IX's uncertain members) here, called when the worker asks
for work (markx/api.py). Joins, pairs, merges and connections come from S2's candidates, and cards,
headlines, briefings and translations from S5's decisions and News: they call the builders below.
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
from insight_core.utils.byline import author_account, original_author  # 0168 E's rule lives in Byline (0185, 0189)
from insight_core.utils.post_links import source_kind
from insight_core.utils.post_parts import Body, shown

TEXT_VERSION = "markx-text-v1"
TEXT_CHARS = 1500            # corrections 3
ENTITY_TEXT_CHARS = 6000     # 0133: what entities_input shows under ent-v4 (and its fallback); read and embed keep 1,500
TRANSLATE_CHARS = 2500       # the prototype's F5
READ_LINKS, ENTITY_LINKS, JUDGE_LINKS = 12, 6, 6
STORY_MEMBERS = 3            # members a judge question shows (judge.render_story; 0086 C says "up to 5")
CARD_MEMBERS, HEADLINE_MEMBERS, CONNECT_MEMBERS, BRIEFING_POSTS = 8, 6, 5, 4
PUBLISHER_KINDS = {"site", "arxiv", "hn", "youtube", "saved"}
CERTAIN = {"thread", "quote", "address"}   # a tree reason that is not a guess: no check (unless a roundup)
MIN_WORDS = 20                             # rule A: a shorter post is never judged, never removed
PLAN_DAYS = 30                             # corrections 8: the first runs read the last 30 days only; since
                                           # 0112 Decided 9 the read, entities and embed planners' default only
PLAN_LIMIT = 500
SCAN_PAGES = 40                                # plan_posts: at most 40 pages of PLAN_LIMIT a call (v10.4.1)
READING_WINDOW = "reading_window_days"     # mx_settings: the owner's window for those three (an int, or null: every post)
SETTING = object()                         # a planner's `days` when the caller names none: the owner's setting

# 0176 A: the fresh lane. A post fetched (or surfaced) in the last FRESH_HOURS is planned first for the kinds of
# FRESH_KINDS whatever its date says and however long the queue is (fresh_planners, run on every lease of the kind),
# and a lease gives those tasks up to FRESH_SHARE of its slots before the rest (backfill pages, older posts): a big
# backfill never holds a new post back, and the rest always keeps at least one slot of a lease of two or more.
FRESH_HOURS = 24
FRESH_KINDS = ("read", "entities", "read3", "headline")   # leased in the lane (a headline by its story's first post)
FRESH_SHARE = 0.75                                         # of a lease's slots, at most (the rest keep the others)
FRESH_DATED_DAYS = 7                                       # ... and dated in the last week: an archive import of
                                                           # old posts (fetched today, dated months back) is not new


def fresh_sql(alias: str = "p", since: str = "%(fresh)s") -> str:
    """The fresh lane's condition over posts `alias`, `since` the lane's start (now - FRESH_HOURS): fetched or surfaced
    since then, and dated (surfaced, published, fetched) within FRESH_DATED_DAYS."""
    return (f"(GREATEST({alias}.fetched_at, {alias}.surfaced_at) >= {since} "
            f"AND {pairing.ordinary_date(alias)} "
            f">= {since}::timestamptz + make_interval(hours => {FRESH_HOURS}) - make_interval(days => {FRESH_DATED_DAYS}))")


def reading_window(cur: Cursor) -> Optional[int]:
    """The read, entities and embed planners' window in days, as the owner set it on the page (0112 Decided 9): an
    int, or None for every post; PLAN_DAYS when it was never set. Read on every planner run, so a change counts from
    the next one (no restart). The decision window (decide.Config.days) and plan_checks follow the story window
    instead (0144 A1: markx/story_window.py)."""
    value = repo.get_setting(cur, READING_WINDOW, default=PLAN_DAYS)
    return None if value is None else int(value)


def set_reading_window(cur: Cursor, days: Optional[int]) -> Optional[int]:
    repo.set_setting(cur, READING_WINDOW, days)
    return days


READING_PLANNED = "reading_window_planned"   # mx_settings: {kind: the window its planner last ran for} (0121 D4)
NEVER = "never"                              # a kind whose planner never ran for a window


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
    kind: str                 # the platform as the reader names it (site, telegram, x, reddit, hn, arxiv, ...)
    source: str
    source_id: str
    at: datetime
    title: str
    text: str                 # the whole shown text; each render cuts it
    links: List[Tuple[str, Optional[str]]] = field(default_factory=list)
    quote: Optional[str] = None
    lang: Optional[str] = None
    by: Optional[str] = None  # 0168 E: a repost's (or a Telegram forward's) original author ("@acme"), not the feed's
    counts_as: Optional[str] = None   # v10.15: the source its author is, when one of the sources follows the author
                                      # (voice.counted_source); Voice counts a Post by Policy.MARKX

    @property
    def iso(self) -> str:
        return self.at.astimezone(timezone.utc).isoformat()

    @property
    def who(self) -> str:
        """0168 E: who a render says wrote it: the source, or "a post by @X shared by <source>" for a repost (Byline's
        words, issue 0185)."""
        return byline.who({"author": self.by, "via": self.source})

    @property
    def voice(self) -> str:
        """The voice it counts as (Voice's MARKX rule): a repost's original author when one of the sources follows
        that author, else its own source. `by` is the credit a render shows, whoever the author."""
        return voice.voice_of(self, voice.Policy.MARKX)


def _squash(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def load_posts(cur: Cursor, ids: Iterable[Any]) -> Dict[str, Post]:
    """{id: Post} for the posts that exist (markx text v1: post_parts' title and text, kept links in order)."""
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
    return out


def readings(cur: Cursor, ids: Iterable[Any], guide: str = "read-v2") -> Dict[str, dict]:
    """{post id: reading} of the posts Mark X has read under `guide`."""
    return {str(k): v["reading"] for k, v in repo.readings(cur, list(ids), guide).items()}


def words(p: Post) -> int:
    return len((p.title + " " + p.text).split())


# A near-copy (0112 bug 3, the prototype's rule: 0106 step 1, persp32.Story): another member's text folded, or a
# 5-word shingle Jaccard of COPY_JACCARD or more, whatever the source. Never checked, so never removed or demoted.
COPY_SHINGLE, COPY_JACCARD = 5, 0.6


def fold(s: Optional[str]) -> str:
    """The prototype's fold: lowercase, ё as е, every run of non-word characters one space."""
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
    """The ids of the members that are a near-copy of another member."""
    keys = [(fold(m.title + " " + m.text), shingles(m)) for m in members]
    out = set()
    for i, (fi, si) in enumerate(keys):
        for j in range(i + 1, len(keys)):
            fj, sj = keys[j]
            if (fi and fi == fj) or _jaccard(si, sj) >= COPY_JACCARD:
                out.update((members[i].id, members[j].id))
    return out


def voices(posts: Iterable[Post]) -> int:
    """Distinct voices (Voice's MARKX rule: a repost counts as its author only when a source follows the author)."""
    return voice.count(posts, voice.Policy.MARKX)


def _cut(text: str, n: int) -> str:
    return text[:n] + (" […]" if len(text) > n else "")


# ---- the renders (the prototype's) ----------------------------------------------------------------

def _head(p: Post) -> List[str]:
    """The lines every post render starts with: platform and source, the author of a repost, the title."""
    lines = [f"Platform: {p.kind} | Source: {p.source}", f"Title: {p.title}"]
    if p.by:   # 0168 E: a repost: its author is the original one, never the feed that carried it
        lines.insert(1, f"Author: {p.by} (a post by {p.by} shared by {p.source}; not {p.source}'s own words)")
    return lines


def post_block(p: Post, nlinks: int, chars: int = TEXT_CHARS) -> str:
    """read.block: the post as every reader sees it: platform, source, title, text, links in order, the quote."""
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
    """judge.render_post: the post a judge question asks about, with its reading when it has one."""
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
    """judge.render_story: a story by its card (headline, slots, summary) and its first members."""
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
    """cards.rule_card without embeddings: the earliest report's main event (a publisher's first), else the most
    common object's, else the earliest member's title."""
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
    """`shared` (0168 E: the headline's and the card's members): a repost says whose post it is."""
    return f"- [{p.who if shared else p.source}, {p.kind}, {when}] {p.title[:160]} — {p.text[:chars]}"


# ---- the inputs, one function a kind --------------------------------------------------------------

def read_input(p: Post) -> str:
    return post_block(p, READ_LINKS)


def entities_input(p: Post, chars: int = TEXT_CHARS) -> str:
    """0133: `chars` is the switched-to entities arm's (ENTITY_TEXT_CHARS under ent-v4; 1,500 under ent-v3)."""
    return post_block(p, ENTITY_LINKS, chars)


def _render(cur: Cursor, kind: str) -> Any:   # 0133: the planners' input, the entities arm's cut
    if kind == "read":
        return read_input
    chars = schemas.entities_arm(cur).chars
    return lambda p: entities_input(p, chars)


# ---- 0176 B (0150 C): a long post's entities read in windows ---------------------------------------
# The entities arm shows the first `chars` of a post's text (1,500 or 6,000); a long round-up names most of its people
# after that (experiment E7: 31% of them lost). A post whose text is longer than one window is asked per window: the
# first window's input is exactly today's (entities_input: the same task, never asked again), each later window shows
# the post's head (platform, source, author, title), which window of how many and the characters it holds, and the
# text from (w * (chars - WINDOW_OVERLAP)) for `chars` characters: consecutive windows share WINDOW_OVERLAP characters,
# so a name cut by one window's end is whole in the next. At most `max_windows` (the setting, MAX_WINDOWS by default);
# a post's text past them stays unread. A short post has one window and behaves exactly as before.

WINDOW_OVERLAP = 200                 # characters two consecutive windows share
MAX_WINDOWS = 12                     # windows a post is read in at most (the default of the setting)
WINDOWS_SETTING = "entity_windows_max"   # mx_settings: the owner's cap (an int; 1: the first window only, as before)
WINDOW_N = repo.WINDOW_N                # window w's mentions are numbered from w * WINDOW_N (mx_mentions' key stays (post, guide, n))
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
    """The windows (start, end) a text of this length is read in: one, (0, min(len, chars)), unless it is longer than
    `chars`; then windows of `chars` characters every chars - WINDOW_OVERLAP, at most `cap`."""
    n = len(text or "")
    if n <= chars or cap <= 1:
        return [(0, min(n, chars))]
    step = chars - WINDOW_OVERLAP
    count = min(cap, 1 + -(-(n - chars) // step))
    return [(w * step, min(n, w * step + chars)) for w in range(count)]


def window_input(p: Post, w: int, windows: Sequence[Tuple[int, int]]) -> str:
    """Window w's input (w >= 1): the post's head, which window it is, its text. The post's links and quote are read
    with its first window."""
    start, end = windows[w]
    n = len(p.text)
    lines = _head(p)
    lines.append(f"Window: {w + 1} of {len(windows)} of the post's text (characters {start + 1:,}-{end:,} of {n:,})")
    lines.append("Text: […] " + p.text[start:end] + (" […]" if end < n else ""))
    return "\n".join(lines)


def entity_inputs(p: Post, chars: int, cap: int = MAX_WINDOWS) -> List[str]:
    """The post's entities inputs, one a window: [entities_input(p, chars)] for a short post."""
    windows = text_windows(p.text, chars, cap)
    return [entities_input(p, chars)] + [window_input(p, w, windows) for w in range(1, len(windows))]


def window_of(input: str) -> int:
    """The window (0 first) an entities input shows: 0 for the first window's (every input before 0176)."""
    m = _WINDOW_LINE.search(input.split("\nText: ", 1)[0])
    return int(m.group(1)) - 1 if m else 0


def window_overlap(input: str) -> Tuple[str, str]:
    """A later window's text as (what it shares with the window before it: its first WINDOW_OVERLAP characters, the
    rest); ("", "") for the first window."""
    body = input.split("\nText: […] ", 1)
    if window_of(input) == 0 or len(body) < 2:
        return "", ""
    return body[1][:WINDOW_OVERLAP], body[1][WINDOW_OVERLAP:]


def add_entities(cur: Cursor, p: Post, *, chars: int, cap: int, priority: int = 0) -> Tuple[bool, int]:
    """The post's entities tasks, a window each: (whether its first window's is new, how many tasks were added)."""
    inputs = entity_inputs(p, chars, cap)
    first = add(cur, "entities", inputs[0], a=p.id, priority=priority)[1]
    return first, int(first) + sum(1 for x in inputs[1:] if add(cur, "entities", x, a=p.id, priority=priority)[1])


def check_input(post: Post, members: Sequence[Post]) -> str:
    """The raw-text form (plan_noread): the story by its earliest other member's title and its first members, the
    post without its reading."""
    ms = [m for m in _earliest(members) if m.id != post.id]
    card = {"headline_en": ms[0].title} if ms else {}
    return render_story(card, ms[:STORY_MEMBERS]) + "\n\n" + render_post(post, None)


def shows_empty_story(text: str) -> bool:
    """Whether a check's input shows its story with no member (0112 bug 2; the real-data check's
    markx.check_empty_story)."""
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
    """exp_f6.render: each story first seen when, by how many sources, by its first members with dates. The
    prototype showed the members nearest the story's centroid; until S2's vectors, the earliest."""
    def one(tag: str, ps: Sequence[Post]) -> str:
        ps = _earliest(ps)
        # by source, as before 0168 (not asked again)
        n = voice.count((voice.Said(p.source_id, p.kind) for p in ps), voice.Policy.MARKX)
        lines = [f"STORY {tag} — first seen {ps[0].iso[:10]}; {n} sources", "Members (earliest first):"]
        lines += [_member_line(p, 300, p.iso[:10]) for p in ps[:CONNECT_MEMBERS]]
        return "\n".join(lines)
    return one("A", members_a) + "\n\n" + one("B", members_b)


def card_input(members: Sequence[Post], rd: Dict[str, dict]) -> str:
    """cards.model_card: the first 8 members, earliest first, each by an 8-character id the card's `odd` names."""
    lines = []
    for m in _earliest(members)[:CARD_MEMBERS]:
        r = rd.get(m.id) or {}
        main = (r.get("main") or {}).get("headline_en", "")
        lines.append(f"- id {m.id[:8]} [{m.who}, {m.kind}, {m.iso[:16]}] {m.title[:160]} | {m.text[:300]} | "
                     f"reading: {r.get('kind')}, {main}")
    return "MEMBERS:\n" + "\n".join(lines)


def headline_input(members: Sequence[Post]) -> str:
    """exp_f4.story_text: up to 6 members, earliest first (the prototype took the 6 nearest the centroid)."""
    return "Members (earliest first):\n" + "\n".join(_member_line(p, 400, p.iso[:10], shared=True)
                                                     for p in _earliest(members)[:HEADLINE_MEMBERS])


def briefing_input(day: date, stories: Sequence[Tuple[str, Sequence[Post]]]) -> str:
    """exp_f12: the day's stories (at most 10, the caller's order: most voices first) keyed s1..sN, each with its
    headline, its sources and up to 4 posts."""
    parts = [f"DAY {day.isoformat()}: {len(stories[:10])} stories"]
    for n, (headline, posts) in enumerate(stories[:10], 1):
        ps = _earliest(posts)
        sources = list(dict.fromkeys(p.by or p.source for p in ps))   # 0168 E: a repost by its author
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
    guide = schemas.guide_of(cur, kind)   # 0133: entities under the switched-to guide
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
    """The post's first window's entities task (its id, whether it is new); a long post's later windows are added
    with it (0176)."""
    p, = _posts(cur, [post_id])
    inputs = entity_inputs(p, schemas.entities_arm(cur).chars, max_windows(cur))   # 0133, 0176
    got = add(cur, "entities", inputs[0], a=p.id, priority=priority)
    for x in inputs[1:]:
        add(cur, "entities", x, a=p.id, priority=priority)
    return got


def translate_task(cur: Cursor, post_id: Any, priority: int = 0):
    p, = _posts(cur, [post_id])
    return add(cur, "translate", translate_input(p), a=p.id, priority=priority)


def check_task(cur: Cursor, post_id: Any, members: Sequence[Any], *, story: Any = None):
    """Is this member of the story (its other members, `members`) about the story's event? `story`: a Mark X story,
    never a Mark IX story id."""
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
    """`read` or `entities` tasks for the newest posts of the last `days` (by default the owner's reading window,
    `reading_window`; None: every post) that have none under the kind's guide, newest first (priority: the post's
    age in days, so a lease takes today's first): how many were added. A long post's entities are a task a window
    (0176). `fetched_since` (the fresh lane, 0176 A): the posts fetched (or surfaced) since then and dated in the last
    FRESH_DATED_DAYS instead (`fresh_sql`), whatever the window."""
    guide = schemas.guide_of(cur, kind)   # 0133: a new entities guide plans new tasks (no row rewritten)
    if fetched_since is not None:
        days = None
    elif days is SETTING:
        days = reading_window(cur)
    render = _render(cur, kind)
    chars, cap = (schemas.entities_arm(cur).chars, max_windows(cur)) if kind == "entities" else (0, 1)
    added, after = 0, None
    # v10.4.1: a post whose input repeats an asked one (a media-only post, a repost) gets no task of its own (the
    # same input is one task), so it stays "unplanned"; newest first, such posts filled every LIMIT and the older
    # posts were never reached. Page on past them (keyset), at most SCAN_PAGES pages a call. v10.14: such a post is
    # marked (plan_marks) and not read again while its text is unchanged, so a planner with nothing to add reads no post.
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
                  AND p.filtered_by IS NULL   -- 0196: a post its source's item filter hid is never read
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
            if kind == "entities":   # 0176: a task a window
                first, n = add_entities(cur, p, chars=chars, cap=cap, priority=age)
                added += n
            else:
                first = add(cur, kind, render(p), a=p.id, priority=age)[1]
                added += int(first)
            if not first:   # v10.14: its input is another post's task: not read again until its text changes
                passed.append((p.id, plan_marks.SAME_INPUT, stamp))
        plan_marks.mark(cur, kind, guide, passed)
        if added >= limit or len(rows) < limit:
            break
        after = (rows[-1][2], rows[-1][0])
    return added


def check_questions(cur: Cursor, *, days: Optional[int] = PLAN_DAYS, now: Optional[datetime] = None,
                    threads: Optional[bool] = None) -> Iterable[Tuple[Post, str]]:
    """F1's checks over Mark IX's current stories (pipeline.plan), as (post, input), without writing: every member
    of a 2+ voice story but its earliest, joined by a guess (a citation, a time, a copy, a repost, no reason) or a
    roundup, of 20 words or more unless a roundup, and not a near-copy of another member (0112 bug 3); with `threads` (default: the decision job's
    `Config.check_threads`), a member joined by `thread` too. Stories with a member in the last `days` (None: every
    story). Mark IX is only read."""
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
    # 0183: the stories' posts read a chunk of stories at a time, and of their readings only the kind (was: every
    # story's texts and whole readings at once, the plan job's peak). The same stories in the same order.
    order = list(stories.values())
    for at in range(0, len(order), CHECK_CHUNK):
        chunk = order[at:at + CHECK_CHUNK]
        posts = load_posts(cur, {p for ms in chunk for p, _, _ in ms})
        kinds = reading_kinds(cur, list(posts))
        yield from _checks_of(chunk, posts, kinds, certain)


CHECK_CHUNK = 500   # stories a check planner reads at once (0183)


def reading_kinds(cur: Cursor, ids: Sequence[str], guide: str = "read-v2") -> Dict[str, Any]:
    """{post id: its reading's kind} of the posts read under `guide` (the reading's own value, as `readings` gives it)."""
    cur.execute("SELECT post_id::text, reading->'kind' FROM mx_readings WHERE post_id = ANY(%s::uuid[]) AND guide = %s",
                (list(ids), guide))
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
    """The story a check of `post` shows: its `reports` (post ids) but the post; when the post is the story's only
    report, its other members of any role (0112 bug 2: Haiku was shown "Headline: " and no member, and answered
    "different"); [] when it has no other member: a story's only post is never checked."""
    reports = set(reports)
    return ([m for m in members if m.id in reports and m.id != post.id]
            or [m for m in members if m.id != post.id])


BACKGROUND_PLANNED = ("check", "cite", "track")   # v10.13.4: kinds the decision job plans, never a lease


def planned_in_background(cur: Cursor, kind: str, now: Optional[datetime] = None) -> bool:
    """v10.13.4: whether the decision job (jobs.Jobs.plan_background), not a lease, plans `kind`. `cite` (ent42.plan
    pages through every post read without a cite task: ~60 s on the server) and `track` (tracks.plan learns each
    track's finders over 30 days of posts: ~47 s) always; `check` while the story window is wide (v10.13.2)."""
    if kind == "check":
        return checks_in_background(cur, now)
    return kind in BACKGROUND_PLANNED


# 0183: what each background planner reads and writes (markx/unchanged.py skips a pass while these are as they were at
# its last pass that planned nothing). Every table a planner reads or writes is named; the key holds what else it
# depends on: its code and its settings as it computes them. The clock only narrows check's and cite's windows within
# a day (now - days: a post that leaves the window adds no question, and an age is only a new task's priority), so the
# window's length in days is in their key. track's bar and windows move with the clock itself (the share of the last
# 30 days' posts a probe passes): it has no declaration and always runs.
# v10.18 (0199): of mx_tasks, only the kinds each reads (unchanged.of_kinds): check its own (tasks.add's lookup);
# cite its own and the ent-v4.2 entities tasks it plans from (ent42.plan). Another kind's lease or answer (the track
# answers that stream all day) no longer wakes them.
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
    """0183: (tables, key) of the background planner `kind`'s pass at `now` (unchanged.run); key None: it always runs."""
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
    """v10.13.2: while the story window reaches past RECENT days, planning the checks reads every story it reaches
    (over a minute on the server with `everything`, longer than a worker waits for its lease), so the decision job
    plans them before its run (jobs.Jobs.decide) and a lease never does. Within RECENT days a lease plans them."""
    from insight_core.markx import story_window
    return story_window.days_for_run(cur, now or datetime.now(timezone.utc)) > story_window.RECENT


def plan_checks(cur: Cursor, *, days: Any = SETTING, limit: int = PLAN_LIMIT, now: Optional[datetime] = None) -> int:
    """The checks `check_questions` asks of the last `days` (by default the story window as the decision run reads
    it, 0144 A1; None: every story), as tasks: how many were added. While the window reaches past 30 days, the checks
    of posts older than that come newest first, at most a page (story_window.BACKFILL_PAGE) a call, at the backfill's
    priority (0144 A2)."""
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
    # 0183: what the sort keeps of each question is its post's time and id and the input (not the post's whole text)
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
    """Build plan corrections 4: of the open and answered check tasks, how many today's Mark IX stories would no
    longer ask (their story changed shape: a member came or went, a post moved): {"check": {"tasks", "would_change"}}.
    The real-data check reports it for a story-rule change; cards and merges join it with S2's and S5's planners."""
    today = {repo.sha256_hex(text) for _p, text in check_questions(cur, days=None)}
    cur.execute("SELECT input_hash FROM mx_tasks WHERE kind = 'check' AND status IN ('open', 'leased', 'answered')")
    hashes = [h for (h,) in cur.fetchall()]
    return {"check": {"tasks": len(hashes), "would_change": sum(1 for h in hashes if h not in today)}}


def _plan_embeds(cur: Cursor, **kw) -> int:
    """S2's planner, over the owner's reading window unless the caller names `days` (0112 Decided 9)."""
    from insight_core.markx import embed   # S2's planner (embed.py imports this module)
    if kw.get("days", SETTING) is SETTING:
        kw["days"] = reading_window(cur)
    return embed.plan(cur, **kw)


def _plan_names(cur: Cursor) -> int:
    """0119 A1: the entities' name vectors (embed.plan_names)."""
    from insight_core.markx import embed
    return embed.plan_names(cur)


def _plan_read3(cur: Cursor, **kw) -> int:
    """0127: the read-v3 readings of Mark X stories' members (folds.plan)."""
    from insight_core.markx import folds   # folds imports this module
    return folds.plan(cur, **kw)


WINDOWED = ("read", "entities", "embed", "read3", "cite")   # the planners the reading window (and a lease's `days`) applies to (0133 v4.2: + cite)
PLANNERS = {"read": lambda cur, **kw: plan_posts(cur, "read", **kw),
            "entities": lambda cur, **kw: plan_posts(cur, "entities", **kw),
            "check": plan_checks,
            "embed": _plan_embeds,
            "embed_name": lambda cur, **kw: _plan_names(cur),
            "read3": lambda cur, **kw: _plan_read3(cur, **kw),
            "translate": lambda cur, **kw: _plan_translations(cur, **kw),   # 0130 D
            "relate": lambda cur, **kw: _plan_relate(cur),                  # 0131
            "back": lambda cur, **kw: _plan_back(cur)}                      # 0136


def _plan_back(cur: Cursor) -> int:   # 0136: back in the news (back.plan), capped like the decision run's
    from insight_core.markx import back
    from insight_core.markx.decide import Config
    return back.plan(cur, open_cap=Config().back_open)   # 0203: Later developments' questions dropped


def _plan_relate(cur: Cursor) -> int:   # 0131: Stalker's questions (graph.plan), capped like the decision run's
    from insight_core.markx import graph   # graph imports this module
    from insight_core.markx.decide import Config
    return graph.plan(cur, open_cap=Config().relate_open)


def _plan_translations(cur: Cursor, **kw) -> int:   # 0130 D: Mark X News' non-English leads (translate.plan)
    from insight_core.markx import translate   # translate imports this module
    return translate.plan(cur, **kw)


# ---- what a valid answer writes besides its call ----------------------------------------------------

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−⁃﹘﹣－"), "-")


def name_key(name: Optional[str]) -> str:
    """0090's name key (the prototype's entparse.key): NFKC, every dash as '-', no soft hyphen, casefold, ё as е,
    letters glued to digits split, separators as one space. key("Qwen3.8‑Flash") == key("qwen 3.8 flash")."""
    s = unicodedata.normalize("NFKC", name or "").translate(_DASHES).replace("­", "")
    s = s.casefold().replace("ё", "е")
    s = re.sub(r"(?<=[a-zа-я])(?=\d)", " ", s)
    return re.sub(r"[\s_\-/·,:;()\[\]\"'«»“”]+", " ", s).strip()


SEARCHED_KINDS = ("read", "read3", "entities", "cite")   # 0139: the answers mx_post_search is made of


def _note_happening(cur: Cursor, task: Dict[str, Any]) -> None:
    """0175: a read-v2 reading, a mention set or a cite answer's mentions landed: the post's happening key stored
    now (happening.note)."""
    from insight_core.markx import happening
    if task["kind"] in ("entities", "cite") or task["guide"] == happening.READING_GUIDE:
        happening.note(cur, [str(task["a"])])


def _note_units(cur: Cursor, task: Dict[str, Any]) -> None:
    """0181: a read-v2 reading landed: the post split again now (a reading may make it a round-up: units.note), in a
    savepoint: a failure is logged and the reading stands (the candidates job's step splits it later)."""
    from insight_core.markx import units
    if task["guide"] != units.READING_GUIDE:
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
    if task["kind"] in ("read", "read3"):          # 0127: a read3 answer is a reading under read-v3
        main = answer.get("main") or {}
        repo.add_reading(cur, post_id=task["a"], guide=task["guide"], call_id=call_id, kind=answer.get("kind"),
                         events=answer.get("events"), lang=answer.get("lang"), headline=main.get("headline_en"),
                         reading=answer)
        _note_happening(cur, task)
        _note_units(cur, task)
    elif task["kind"] == "relate":                 # 0131: asked until it has graph.RELATE_RUNS valid answers
        from insight_core.markx import graph
        graph.after_answer(cur, task)
    elif task["kind"] == "back":                   # 0136: asked until it has back.RUNS valid answers
        from insight_core.markx import back
        back.after_answer(cur, task)
    elif task["kind"] == "entities":
        win = window_of(task["input"])   # 0176: a long post's later window (0: the first, every short post's)
        entities = answer.get("entities") or []
        if win:   # a name wholly in the text the window shares with the one before was read there
            shared, rest = window_overlap(task["input"])
            entities = [e for e in entities if not (e.get("span") and e["span"] in shared and e["span"] not in rest)]
        mentions = [dict({f: e.get(f) for f in repo.MENTION_FIELDS}, name_key=name_key(e.get("name")),
                         by_name=e.get("by") or None)                                       # 0133: ent-v4's `by`
                    for e in entities]
        arm = schemas.ENTITY_ARMS.get(task["guide"])
        if win == 0 and arm is not None and arm.rule:   # 0133: the citation rule, merged in (never under ent-v3)
            from insight_core.markx import citations
            mentions = citations.for_post(cur, task["a"], mentions, name_key)
        if task["guide"] == "ent-v4.2":    # 0133 v4.2: own title dropped, the cite answer merged (q2); no rule
            from insight_core.markx import ent42
            mentions = (ent42.main_mentions(cur, task["a"], entities) if win == 0
                        else ent42.window_mentions(cur, task["a"], entities))   # 0176: the cite answer is window 0's
        repo.add_mentions(cur, post_id=task["a"], guide=task["guide"], call_id=call_id, mentions=mentions, win=win)
        _note_happening(cur, task)
    elif task["kind"] == "cite":           # 0133 v4.2: the second question's new entities, after the main answer
        from insight_core.markx import ent42
        ent42.after_cite(cur, task, call_id, answer)
        _note_happening(cur, task)
    elif task["kind"] in ("track", "subtopics"):   # 0145: a track's verdict, or its sub-topics proposed
        from insight_core.markx import tracks
        tracks.after_answer(cur, task, call_id, answer)
        if task["kind"] == "track":                 # 0148: a scout's test-read item shares the judge (scratch rows)
            from insight_core.markx import scout
            scout.after_judge(cur, task, answer)
    elif task["kind"] == "probes":                  # 0147: a track's example posts
        from insight_core.markx import finders
        finders.after_answer(cur, task, call_id, answer)
    elif task["kind"] == "scout":                   # 0148: the sources Haiku names for a track's sphere
        from insight_core.markx import scout
        scout.after_answer(cur, task, answer)
    elif task["kind"] == "identity":                # 0162: two accounts, one maker?
        from insight_core.markx import research
        research.after_identity(cur, task, answer)
    elif task["kind"] == "websearch":               # 0171: the worker's web search for a research run
        from insight_core.markx import research
        research.after_websearch(cur, task, answer)
    elif task["kind"] == "source_judge":            # 0173: "Is this worth it?" for a candidate source
        from insight_core.markx import source_judge
        source_judge.after_answer(cur, task, answer)
    elif task["kind"] == "news_sections":           # 0174: Mark X News' titled sections
        from insight_core.markx import news_sections
        news_sections.after_answer(cur, task, call_id, answer)
    elif task["kind"] == "news_place":              # 0197: new News rows into those sections
        from insight_core.markx import news_sections
        news_sections.after_place(cur, task, call_id, answer)
    elif task["kind"] == "unit_types":              # 0181: a round-up's items: type, headline, continues
        from insight_core.markx import units
        units.after_types(cur, task, call_id, answer)
    if task["kind"] in SEARCHED_KINDS:     # 0139: the post's English layer in search, from its answers as they are now
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


# ---- 0132 B: a source's stance (monthly), and Part C1 (each source's last posts read, behind a switch) ----------

STANCE_POSTS = 15           # 0132 B: random own posts of 250+ characters a stance question shows
STANCE_MIN_CHARS = 250
STANCE_CHARS = 1200          # each cut here, as the lab asked it
STANCE_DAYS = 90             # the posts of the last 90 days (the stats window)
LAST_POSTS = 20              # 0132 C1: a source's last 20 posts, whatever their date
LAST_POSTS_BELOW = 10        # for the sources with fewer read posts than this
LAST_POSTS_SWITCH = "INSIGHT_MARKX_READ_LAST20"   # off by default (the owner's open decision 3)


def stance_input(name: str, kind: str, texts: Sequence[str]) -> str:   # 0132 B
    """The stance question: the source's name and kind, then its posts numbered [1]..[N] (title and text, cut)."""
    return f"Source: {name} ({kind})\n\n" + "\n\n".join(f"[{i + 1}] {t[:STANCE_CHARS]}" for i, t in enumerate(texts))


def plan_stance(cur: Cursor, *, now: Optional[datetime] = None, limit: int = PLAN_LIMIT, **_kw: Any) -> int:   # 0132 B
    """One `stance` task per source a month: STANCE_POSTS random own posts of STANCE_MIN_CHARS+ characters of the last
    STANCE_DAYS (seeded by the source and the month, so a month asks one question), for every source that has that
    many and no stance task this month (Reddit, a platform of many voices, is never asked). How many were added."""
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


def last_posts_on() -> bool:   # 0132 C1
    import os
    return os.getenv(LAST_POSTS_SWITCH, "off").strip().lower() in ("on", "1", "true", "yes")


def plan_last_posts(cur: Cursor, kind: str, *, limit: int = PLAN_LIMIT, now: Optional[datetime] = None) -> int:   # 0132 C1
    """`read` or `entities` tasks for the last LAST_POSTS posts, whatever their date, of every source with fewer than
    LAST_POSTS_BELOW posts read under the kind's guide (a reading, or an answered entities task), only while
    INSIGHT_MARKX_READ_LAST20 is on; priority the post's age in days, as plan_posts. It fills the role card's "too few
    to tell". How many were added."""
    if not last_posts_on():
        return 0
    guide = schemas.guide_of(cur, kind)   # 0133
    done = ("SELECT 1 FROM mx_readings r WHERE r.post_id = p.id AND r.guide = %(guide)s" if kind == "read" else
            "SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = p.id "
            "AND t.status = 'answered'")
    cur.execute(
        f"""WITH few AS (SELECT s.id FROM sources s
                          WHERE s.platform <> 'saved'
                            AND (SELECT count(*) FROM posts p WHERE p.source_id = s.id AND EXISTS ({done})) < %(below)s),
                 last AS (SELECT p.id, {pairing.ordinary_date('p')} AS at,
                                 row_number() OVER (PARTITION BY p.source_id ORDER BY
                                                    {pairing.ordinary_date('p')} DESC, p.id DESC) AS k
                            FROM posts p WHERE p.source_id IN (SELECT id FROM few))
            SELECT l.id, GREATEST(0, floor(extract(epoch FROM (COALESCE(%(now)s, now()) - l.at)) / 86400))::int
              FROM last l
             WHERE l.k <= %(last)s
               AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = l.id)
             ORDER BY 2, l.id
             LIMIT %(limit)s""",
        {"guide": guide, "kind": kind, "below": LAST_POSTS_BELOW, "last": LAST_POSTS, "now": now, "limit": limit})
    rows = cur.fetchall()
    posts = load_posts(cur, [r[0] for r in rows])
    render = _render(cur, kind)   # 0133
    added = 0
    for pid, age in rows:
        p = posts.get(str(pid))
        if p is None:
            continue
        if kind == "entities":   # 0176: a task a window
            added += add_entities(cur, p, chars=schemas.entities_arm(cur).chars, cap=max_windows(cur), priority=age)[1]
        elif add(cur, kind, render(p), a=p.id, priority=age)[1]:
            added += 1
    return added


def _with_last_posts(kind: str, planner: Any) -> Any:   # 0132 C1: the window's planner, then the last posts'
    def plan(cur: Cursor, **kw: Any) -> int:
        return planner(cur, **kw) + plan_last_posts(cur, kind)
    return plan


PLANNERS["stance"] = plan_stance                                           # 0132 B
PLANNERS["read"] = _with_last_posts("read", PLANNERS["read"])              # 0132 C1
PLANNERS["entities"] = _with_last_posts("entities", PLANNERS["entities"])  # 0132 C1

WINDOWS_MARK = "entities-windows"   # 0176: plan_marks' kind for a long-stored post the windows planner passed over


def plan_windows(cur: Cursor, *, days: Any = SETTING, limit: int = PLAN_LIMIT, now: Optional[datetime] = None) -> int:
    """0176 B: the later windows of the posts whose first window was asked before windows existed (or under a lower
    cap), newest first, over the owner's reading window (or `days`; None: every post): how many tasks were added. A
    post whose text needs one window, or whose windows are another post's tasks (a repost), is marked and not read
    again until its text changes. Cheap to call: only posts stored longer than one window are read."""
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


def _with_windows(planner: Any) -> Any:   # 0176 B: the window's planner, then the later windows of earlier posts
    def plan(cur: Cursor, **kw: Any) -> int:
        got = planner(cur, **kw)
        return got + plan_windows(cur, **{k: v for k, v in kw.items() if k in ("days", "now")})
    return plan


PLANNERS["entities"] = _with_windows(PLANNERS["entities"])                # 0176 B


def fresh_since(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - timedelta(hours=FRESH_HOURS)


def plan_fresh(cur: Cursor, kind: str, *, limit: int = PLAN_LIMIT, now: Optional[datetime] = None) -> int:
    """0176 A: the fresh lane's planning for `kind` (read, entities, read3): the posts fetched or surfaced in the last
    FRESH_HOURS that have no task of the kind, whatever their date and the reading window: how many were added. A
    lease runs it first, every time (the general planner runs only when its queue runs low)."""
    since = fresh_since(now)
    if kind in ("read", "entities"):
        return plan_posts(cur, kind, limit=limit, now=now, fetched_since=since)
    if kind == "read3":
        from insight_core.markx import folds
        return folds.plan(cur, limit=limit, now=now, fetched_since=since)
    return 0


FRESH_PLANNERS = {k: (lambda kind: lambda cur, **kw: plan_fresh(cur, kind, **kw))(k) for k in ("read", "entities", "read3")}


def _plan_cite(cur: Cursor, **kw: Any) -> int:   # 0133 v4.2: ent-v4.2's second question, cue posts only (ent42.plan)
    from insight_core.markx import ent42   # ent42 imports this module
    return ent42.plan(cur, **kw)


PLANNERS["cite"] = _plan_cite                                              # 0133 v4.2


# ---- 0145: tracks as topics (markx/tracks.py) --------------------------------------------------------------------

def _plan_tracks(cur: Cursor, **kw: Any) -> int:   # 0145: active posts, passive ones the prefilter passes, the history pass
    from insight_core.markx import tracks   # tracks imports this module
    return tracks.plan(cur, **kw)


def _plan_subtopics(cur: Cursor, **kw: Any) -> int:   # 0145: a track's sub-topics proposed (15+ items, then weekly)
    from insight_core.markx import tracks
    return tracks.plan_subtopics(cur, **kw)


def _with_track_vectors(planner: Any) -> Any:   # 0145: the tracks' descriptions embedded with the posts (embed kind)
    def plan(cur: Cursor, **kw: Any) -> int:      # 0147: and their example posts
        from insight_core.markx import finders, tracks
        return tracks.plan_vectors(cur) + finders.plan_vectors(cur) + planner(cur, **kw)
    return plan


def _plan_probes(cur: Cursor, **kw: Any) -> int:   # 0147: a track's example posts, once a version
    from insight_core.markx import finders
    return finders.plan_probes(cur, **kw)


PLANNERS["track"] = _plan_tracks                                           # 0145
PLANNERS["subtopics"] = _plan_subtopics                                    # 0145
PLANNERS["probes"] = _plan_probes                                          # 0147
PLANNERS["embed"] = _with_track_vectors(PLANNERS["embed"])                 # 0145


def _plan_news_sections(cur: Cursor, **kw: Any) -> int:   # 0174: News' sections, when its rows changed (news_sections.plan)
    from insight_core.markx import news_sections   # news_sections imports this module
    return news_sections.plan(cur, **kw)


PLANNERS["news_sections"] = _plan_news_sections                            # 0174


def _plan_news_place(cur: Cursor, **kw: Any) -> int:   # 0197: the rows added since, into the sections (news_sections.place)
    from insight_core.markx import news_sections
    return news_sections.place(cur, **kw)


PLANNERS["news_place"] = _plan_news_place                                  # 0197
