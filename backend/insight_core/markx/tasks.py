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

from insight_core.markx import pairing, repo, schemas
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
NOT_VOICE = pairing.NOT_VOICE   # Pairing's voice rule (0166)
CERTAIN = {"thread", "quote", "address"}   # a tree reason that is not a guess: no check (unless a roundup)
MIN_WORDS = 20                             # rule A: a shorter post is never judged, never removed
PLAN_DAYS = 30                             # corrections 8: the first runs read the last 30 days only; since
                                           # 0112 Decided 9 the read, entities and embed planners' default only
PLAN_LIMIT = 500
SCAN_PAGES = 40                                # plan_posts: at most 40 pages of PLAN_LIMIT a call (v10.4.1)
READING_WINDOW = "reading_window_days"     # mx_settings: the owner's window for those three (an int, or null: every post)
SETTING = object()                         # a planner's `days` when the caller names none: the owner's setting


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

    @property
    def iso(self) -> str:
        return self.at.astimezone(timezone.utc).isoformat()


def _squash(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def load_posts(cur: Cursor, ids: Iterable[Any]) -> Dict[str, Post]:
    """{id: Post} for the posts that exist (markx text v1: post_parts' title and text, kept links in order)."""
    ids = [str(i) for i in ids]
    if not ids:
        return {}
    cur.execute(
        """SELECT p.id, s.platform, s.handle_or_url,
                  COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''),
                           s.handle_or_url),
                  p.source_id, COALESCE(p.surfaced_at, p.published_at, p.fetched_at), COALESCE(pp.title, p.title),
                  p.content, pp.text_cut, pp.text_decode_entities, pp.text_cut_leaves_break, pp.text_copy, pp.quoted,
                  p.language_code
             FROM posts p JOIN sources s ON s.id = p.source_id LEFT JOIN post_parts pp ON pp.post_id = p.id
            WHERE p.id = ANY(%s::uuid[])""", (ids,))
    out: Dict[str, Post] = {}
    for (pid, platform, handle, name, source_id, at, title, content, cut, decode, brk, copy, quoted,
         lang) in cur.fetchall():
        text = shown(content, Body(cut=cut, decode_entities=bool(decode), cut_leaves_break=bool(brk), copy=copy))
        out[str(pid)] = Post(id=str(pid), kind=source_kind(platform, handle), source=name or "", source_id=str(source_id),
                             at=at, title=_squash(title), text=(text or "").strip(), quote=quoted, lang=lang)
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
    return pairing.voices((p.source_id, p.kind) for p in posts)


def _cut(text: str, n: int) -> str:
    return text[:n] + (" […]" if len(text) > n else "")


# ---- the renders (the prototype's) ----------------------------------------------------------------

def post_block(p: Post, nlinks: int, chars: int = TEXT_CHARS) -> str:
    """read.block: the post as every reader sees it: platform, source, title, text, links in order, the quote."""
    lines = [f"Platform: {p.kind} | Source: {p.source}", f"Title: {p.title}"]
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


def _member_line(p: Post, chars: int, when: str) -> str:
    return f"- [{p.source}, {p.kind}, {when}] {p.title[:160]} — {p.text[:chars]}"


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
        lines = [f"STORY {tag} — first seen {ps[0].iso[:10]}; {voices(ps)} sources", "Members (earliest first):"]
        lines += [_member_line(p, 300, p.iso[:10]) for p in ps[:CONNECT_MEMBERS]]
        return "\n".join(lines)
    return one("A", members_a) + "\n\n" + one("B", members_b)


def card_input(members: Sequence[Post], rd: Dict[str, dict]) -> str:
    """cards.model_card: the first 8 members, earliest first, each by an 8-character id the card's `odd` names."""
    lines = []
    for m in _earliest(members)[:CARD_MEMBERS]:
        r = rd.get(m.id) or {}
        main = (r.get("main") or {}).get("headline_en", "")
        lines.append(f"- id {m.id[:8]} [{m.source}, {m.kind}, {m.iso[:16]}] {m.title[:160]} | {m.text[:300]} | "
                     f"reading: {r.get('kind')}, {main}")
    return "MEMBERS:\n" + "\n".join(lines)


def headline_input(members: Sequence[Post]) -> str:
    """exp_f4.story_text: up to 6 members, earliest first (the prototype took the 6 nearest the centroid)."""
    return "Members (earliest first):\n" + "\n".join(_member_line(p, 400, p.iso[:10])
                                                     for p in _earliest(members)[:HEADLINE_MEMBERS])


def briefing_input(day: date, stories: Sequence[Tuple[str, Sequence[Post]]]) -> str:
    """exp_f12: the day's stories (at most 10, the caller's order: most voices first) keyed s1..sN, each with its
    headline, its sources and up to 4 posts."""
    parts = [f"DAY {day.isoformat()}: {len(stories[:10])} stories"]
    for n, (headline, posts) in enumerate(stories[:10], 1):
        ps = _earliest(posts)
        sources = list(dict.fromkeys(p.source for p in ps))
        parts.append(f"\n[s{n}] {headline} — {voices(ps)} sources: {', '.join(sources[:8])}")
        parts += [f"  - [{p.source}, {p.kind}, {p.iso[11:16]}] {p.title[:160]} — {p.text[:250]}"
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
    p, = _posts(cur, [post_id])
    return add(cur, "entities", _render(cur, "entities")(p), a=p.id, priority=priority)   # 0133


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
               now: Optional[datetime] = None) -> int:
    """`read` or `entities` tasks for the newest posts of the last `days` (by default the owner's reading window,
    `reading_window`; None: every post) that have none under the kind's guide, newest first (priority: the post's
    age in days, so a lease takes today's first): how many were added."""
    guide = schemas.guide_of(cur, kind)   # 0133: a new entities guide plans new tasks (no row rewritten)
    if days is SETTING:
        days = reading_window(cur)
    render = _render(cur, kind)
    added, after = 0, None
    # v10.4.1: a post whose input repeats an asked one (a media-only post, a repost) gets no task of its own (the
    # same input is one task), so it stays "unplanned"; newest first, such posts filled every LIMIT and the older
    # posts were never reached. Page on past them (keyset), at most SCAN_PAGES pages a call.
    for _page in range(SCAN_PAGES):
        cur.execute(
            """SELECT p.id, GREATEST(0, floor(extract(epoch FROM (COALESCE(%(now)s, now())
                                        - COALESCE(p.surfaced_at, p.published_at, p.fetched_at))) / 86400))::int,
                      COALESCE(p.surfaced_at, p.published_at, p.fetched_at)
                 FROM posts p
                WHERE (%(days)s::int IS NULL OR COALESCE(p.surfaced_at, p.published_at, p.fetched_at)
                                                 >= COALESCE(%(now)s, now()) - make_interval(days => %(days)s))
                  AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = p.id)
                  AND (%(at)s::timestamptz IS NULL
                       OR (COALESCE(p.surfaced_at, p.published_at, p.fetched_at), p.id) < (%(at)s::timestamptz, %(id)s::uuid))
                ORDER BY COALESCE(p.surfaced_at, p.published_at, p.fetched_at) DESC, p.id DESC
                LIMIT %(limit)s""",
            {"now": now, "days": days, "kind": kind, "guide": guide, "limit": limit,
             "at": after[0] if after else None, "id": after[1] if after else None})
        rows = cur.fetchall()
        posts = load_posts(cur, [r[0] for r in rows])
        for pid, age, _at in rows:
            if added >= limit:
                break
            p = posts.get(str(pid))
            if p is not None and add(cur, kind, render(p), a=p.id, priority=age)[1]:
                added += 1
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
        """SELECT sp.story_id, sp.post_id, sp.role, sp.parent_reason FROM story_posts sp
            WHERE %(days)s::int IS NULL
               OR sp.story_id IN (SELECT sp2.story_id FROM story_posts sp2 JOIN posts p ON p.id = sp2.post_id
                                   WHERE COALESCE(p.surfaced_at, p.published_at, p.fetched_at)
                                         >= COALESCE(%(now)s, now()) - make_interval(days => %(days)s))""",
        {"now": now, "days": days})
    stories: Dict[str, List[Tuple[str, str, Optional[str]]]] = {}
    for story, post, role, reason in cur.fetchall():
        stories.setdefault(str(story), []).append((str(post), role, reason))
    posts = load_posts(cur, {p for ms in stories.values() for p, _, _ in ms})
    rd = readings(cur, list(posts))
    for ms in stories.values():
        members = _earliest(posts[p] for p, _, _ in ms if p in posts)
        if voices(members) < 2:
            continue
        why = {p: reason for p, _, reason in ms}
        reports = {p for p, role, _ in ms if role == "report"}
        copies = near_copies(members)
        for p in members[1:]:
            if p.kind in NOT_VOICE or p.id in copies:
                continue
            roundup = (rd.get(p.id) or {}).get("kind") == "roundup"
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
    asked = sorted(check_questions(cur, days=days, now=now), key=lambda pt: (pt[0].at, pt[0].id), reverse=True)
    added = old = 0
    for p, text in asked:
        late = p.at < edge
        if late and old >= story_window.BACKFILL_PAGE or not late and added >= limit:
            continue
        if add(cur, "check", text, a=p.id, priority=story_window.BACKFILL_PRIORITY if late else 0)[1]:
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
    from insight_core.markx import later   # 0163: later developments' questions, under the same cap, after back's
    return back.plan(cur, open_cap=Config().back_open) + later.plan(cur, open_cap=Config().back_open)


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


def record(cur: Cursor, task: Dict[str, Any], call_id: Any, answer: dict) -> None:
    """The rows a task's first valid answer adds: a post's reading (mx_readings) or its entities (mx_mentions)."""
    if task["a"] is None:
        return
    if task["kind"] in ("read", "read3"):          # 0127: a read3 answer is a reading under read-v3
        main = answer.get("main") or {}
        repo.add_reading(cur, post_id=task["a"], guide=task["guide"], call_id=call_id, kind=answer.get("kind"),
                         events=answer.get("events"), lang=answer.get("lang"), headline=main.get("headline_en"),
                         reading=answer)
    elif task["kind"] == "relate":                 # 0131: asked until it has graph.RELATE_RUNS valid answers
        from insight_core.markx import graph
        graph.after_answer(cur, task)
    elif task["kind"] == "back":                   # 0136: asked until it has back.RUNS valid answers
        from insight_core.markx import back
        back.after_answer(cur, task)
    elif task["kind"] == "entities":
        mentions = [dict({f: e.get(f) for f in repo.MENTION_FIELDS}, name_key=name_key(e.get("name")),
                         by_name=e.get("by") or None)                                       # 0133: ent-v4's `by`
                    for e in answer.get("entities") or []]
        arm = schemas.ENTITY_ARMS.get(task["guide"])
        if arm is not None and arm.rule:   # 0133: the citation rule, merged in (never under ent-v3)
            from insight_core.markx import citations
            mentions = citations.for_post(cur, task["a"], mentions, name_key)
        if task["guide"] == "ent-v4.2":    # 0133 v4.2: own title dropped, the cite answer merged (q2); no rule
            from insight_core.markx import ent42
            mentions = ent42.main_mentions(cur, task["a"], answer.get("entities") or [])
        repo.add_mentions(cur, post_id=task["a"], guide=task["guide"], call_id=call_id, mentions=mentions)
    elif task["kind"] == "cite":           # 0133 v4.2: the second question's new entities, after the main answer
        from insight_core.markx import ent42
        ent42.after_cite(cur, task, call_id, answer)
    elif task["kind"] in ("track", "subtopics"):   # 0145: a track's verdict, or its sub-topics proposed
        from insight_core.markx import tracks
        tracks.after_answer(cur, task, call_id, answer)
    elif task["kind"] == "probes":                  # 0147: a track's example posts
        from insight_core.markx import finders
        finders.after_answer(cur, task, call_id, answer)
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
    cur.execute("""SELECT p.id::text, p.source_id::text, COALESCE(p.title, ''), COALESCE(p.content, ''), p.author,
                          p.reposted_by, (p.metadata ? 'forwarded_from')
                     FROM posts p
                    WHERE p.source_id = ANY(%s::uuid[])
                      AND COALESCE(p.surfaced_at, p.published_at, p.fetched_at) >= %s
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
                 last AS (SELECT p.id, COALESCE(p.surfaced_at, p.published_at, p.fetched_at) AS at,
                                 row_number() OVER (PARTITION BY p.source_id ORDER BY
                                                    COALESCE(p.surfaced_at, p.published_at, p.fetched_at) DESC, p.id DESC) AS k
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
        if p is not None and add(cur, kind, render(p), a=p.id, priority=age)[1]:
            added += 1
    return added


def _with_last_posts(kind: str, planner: Any) -> Any:   # 0132 C1: the window's planner, then the last posts'
    def plan(cur: Cursor, **kw: Any) -> int:
        return planner(cur, **kw) + plan_last_posts(cur, kind)
    return plan


PLANNERS["stance"] = plan_stance                                           # 0132 B
PLANNERS["read"] = _with_last_posts("read", PLANNERS["read"])              # 0132 C1
PLANNERS["entities"] = _with_last_posts("entities", PLANNERS["entities"])  # 0132 C1


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
