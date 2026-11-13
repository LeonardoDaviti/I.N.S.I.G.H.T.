"""The entity page's person parts (issue 0144 B, C): a person's (or org's) own posts, every story of the entity's posts
with its original first, the loose posts by role, and the sample of old stories to label.

  - **By** (B1): an entity of type person or org is linked to the sources that *are* it:
      - `voice`: a source whose confirmed voice (0132, voices.entity_id) is the entity, no question asked;
      - `handle`: a source whose handle, profile name or site label is one of the entity's names by identity's key
        (its squashed key, or a person's surname of 5+ letters), offered once on the page ("These sources are <name>:
        yes / no"); only a `yes` (mx_entity_sources, the newest answer counts) makes it `by`. A platform of many voices
        (Reddit, HN) or a saved page is never one.
    Their posts are on the page with role `by`, counted in its posts and voices, never in surges (surges read the
    mentions alone).
  - **Stories** (B2): each Mark X story holding one of the entity's posts and, for a post in no Mark X story, its Mark IX
    story (marked "Mark IX"); both list **all** their posts, not only those naming the entity.
  - **Original first** (B3): the story's earliest post by the entity itself, else its root (Mark IX: the outside page it
    hangs from, `origin_url`, stored or not, else its first post; Mark X: its earliest member).
  - **Loose posts by role** (B4): subject and actor first, then by, then venue / source / recommended, then mentions
    (the page collapses them: "158 mentions").
  - **The sample** (C): the page offers up to SAMPLE_PAGE of the entity's Mark X stories older than 30 days (oldest
    unlabelled first, a stable order), at most SAMPLE_DAY offered a day over every page; right / wrong / missed.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from insight_core.markx import identity as I
from insight_core.markx import names as N
from insight_core.markx import pairing

BY_TYPES = ("person", "org")
NOT_A_SELF = ("reddit", "hn", "saved")       # a platform of many voices, or the owner's saved pages
SURNAME_MIN = 5
SAMPLE_PAGE = 10                             # old stories offered a page visited
SAMPLE_DAY = 30                              # ... and at most this many a day, every page together
SAMPLE_ANSWERS = ("right", "wrong", "missed")
ROLE_ORDER = {"subject": 0, "actor": 0, "by": 1, "venue": 2, "source": 2, "recommended": 2, "mention": 3}
BY_LIMIT = 50                                # the by posts listed loose by default (the page asks for more)


# ---- by ------------------------------------------------------------------------------------------------

def entity_keys(book: I.Book, root: str, members: Set[str]) -> Set[str]:
    """The entity's names as squashed identity keys (each member's name and every alias that leads to it), and for a
    person the surname of a two-word-or-more name (5+ letters)."""
    names = {book.ents[m].name for m in members if m in book.ents}
    keys = {N.squash(book.ents[m].key) for m in members if m in book.ents}
    keys |= {N.squash(k) for k in book.alias_keys(root)}
    keys |= {N.squash(N.key(n)) for n in names}
    from insight_core.markx import schemas
    if schemas.entity_type(book.ents[root].type) == "person":
        for n in names:
            words = [w for w in re.split(r"\s+", N.key(n)) if w]
            if len(words) >= 2 and len(N.squash(words[-1])) >= SURNAME_MIN:
                keys.add(N.squash(words[-1]))
    return {k for k in keys if len(k) >= 3}


def source_keys(platform: Optional[str], handle: Optional[str], display: Optional[str]) -> Set[str]:
    """What a source calls itself, squashed: its display name, its account's handle (an X, Telegram or YouTube
    account, a code host's or blog platform's user), and a site's own label."""
    from urllib.parse import urlparse
    from insight_core.db.repo_stories import source_account
    from insight_core.markx.source_role import site_label
    out = {N.squash(N.key(display))} if display else set()
    account = source_account(platform, handle)
    if account:
        last = account.rstrip("/").rsplit("/", 1)[-1]
        if not account.startswith("youtube.com/channel/"):
            out.add(N.squash(N.key(last)))
    raw = (handle or "").strip()
    if "://" in raw:
        u = urlparse(raw)
        host = (u.hostname or "").lower()
        label = site_label(host)
        if label:
            out.add(N.squash(label))
        segs = [s for s in u.path.split("/") if s]
        if segs:   # a user's page on a shared host (a gist, a blog platform): its first segment, without its file
            first = re.sub(r"\.(atom|rss|xml|json)$", "", segs[0].lstrip("@"), flags=re.I)
            if first and first.lower() not in ("feed", "feeds", "rss", "atom", "blog", "index.xml", "users", "user"):
                out.add(N.squash(N.key(first)))
    return {k for k in out if len(k) >= 3}


def _answers(cur: Any, members: Set[str]) -> Dict[str, str]:
    cur.execute("""SELECT DISTINCT ON (source_id) source_id::text, answer FROM mx_entity_sources
                    WHERE entity_id = ANY(%s::uuid[]) ORDER BY source_id, created_at DESC, id DESC""", (sorted(members),))
    return dict(cur.fetchall())


def by_sources(cur: Any, book: I.Book, root: str, members: Set[str]) -> Dict[str, Any]:
    """{"by": [{id, name, kind, via}], "proposed": [{id, name, kind}]}: the sources that are the entity (via its voice,
    or by the owner's yes) and those whose names match, not answered yet. Empty for a type that is not a person or org."""
    from insight_core.markx import schemas
    from insight_core.utils.post_links import source_kind
    if schemas.entity_type(book.ents[root].type) not in BY_TYPES:
        return {"by": [], "proposed": []}
    cur.execute("""SELECT s.id::text, s.platform, s.handle_or_url, NULLIF(btrim(s.settings->>'display_name'), ''),
                          v.entity_id::text
                     FROM sources s LEFT JOIN voices v ON v.id = s.voice_id
                                                      AND v.confirmed_at IS NOT NULL AND v.removed_at IS NULL""")
    rows = cur.fetchall()
    keys = entity_keys(book, root, members)
    answers = _answers(cur, members)
    by, proposed = [], []
    for sid, platform, handle, display, voice_entity in rows:
        kind = source_kind(platform, handle)
        row = {"id": sid, "name": display or handle, "kind": kind}
        if voice_entity and book.root(voice_entity) == root:
            by.append({**row, "via": "voice"})
        elif kind in NOT_A_SELF:
            continue
        elif source_keys(platform, handle, display) & keys:
            if answers.get(sid) == "yes":
                by.append({**row, "via": "owner"})
            elif sid not in answers:
                proposed.append(row)
    order = lambda r: (r["kind"] or "", (r["name"] or "").lower(), r["id"])
    return {"by": sorted(by, key=order), "proposed": sorted(proposed, key=order)}


def answer_sources(cur: Any, book: I.Book, entity_id: str, source_ids: Iterable[str], answer: str) -> int:
    """The owner's yes / no on "These sources are <name>": one row a source (the newest counts)."""
    if answer not in ("yes", "no"):
        raise ValueError("answer: yes or no")
    root = book.root(entity_id)
    ids = sorted(set(map(str, source_ids)))
    for sid in ids:
        cur.execute("INSERT INTO mx_entity_sources (entity_id, source_id, answer) VALUES (%s, %s, %s)", (root, sid, answer))
    return len(ids)


def by_posts(cur: Any, source_ids: Iterable[str]) -> Dict[str, Tuple[datetime, str, bool]]:
    """{post: (its time, its source, read)} of these sources."""
    ids = sorted(set(source_ids))
    if not ids:
        return {}
    cur.execute(f"""SELECT p.id::text, {pairing.ordinary_date('p')}, p.source_id::text,
                          rs.read_at IS NOT NULL
                     FROM posts p LEFT JOIN post_reader_state rs ON rs.post_id = p.id
                    WHERE p.source_id = ANY(%s::uuid[])""", (ids,))
    return {pid: (at, src, read) for pid, at, src, read in cur.fetchall() if at is not None}


# ---- stories --------------------------------------------------------------------------------------------

def mark_x_stories(cur: Any, post_ids: Iterable[str]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """({post: its current Mark X stories}, {story: every current member})."""
    ids = sorted(set(post_ids))
    if not ids:
        return {}, {}
    cur.execute("""SELECT post_id::text, story_id::text FROM mx_story_posts
                    WHERE valid_to IS NULL AND role = 'member' AND post_id = ANY(%s::uuid[])""", (ids,))
    of: Dict[str, List[str]] = defaultdict(list)
    for pid, sid in cur.fetchall():
        of[pid].append(sid)
    sids = sorted({s for ss in of.values() for s in ss})
    members: Dict[str, List[str]] = defaultdict(list)
    if sids:
        cur.execute("""SELECT story_id::text, post_id::text FROM mx_story_posts
                        WHERE valid_to IS NULL AND role = 'member' AND story_id = ANY(%s::uuid[])""", (sids,))
        for sid, pid in cur.fetchall():
            members[sid].append(pid)
    return dict(of), dict(members)


def mark_ix_stories(cur: Any, post_ids: Iterable[str]) -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    """({post: its Mark IX story}, {story: {"posts": every post, "root": its first post, "origin_url",
    "origin_title"}}). Mark IX is only read."""
    ids = sorted(set(post_ids))
    if not ids:
        return {}, {}
    cur.execute("SELECT post_id::text, story_id::text FROM story_posts WHERE post_id = ANY(%s::uuid[])", (ids,))
    of = dict(cur.fetchall())
    sids = sorted(set(of.values()))
    out: Dict[str, Dict[str, Any]] = {}
    if sids:
        cur.execute("SELECT id::text, origin_url, origin_title FROM stories WHERE id = ANY(%s::uuid[])", (sids,))
        for sid, url, title in cur.fetchall():
            out[sid] = {"posts": [], "root": sid, "origin_url": url, "origin_title": title}
        cur.execute("SELECT story_id::text, post_id::text FROM story_posts WHERE story_id = ANY(%s::uuid[])", (sids,))
        for sid, pid in cur.fetchall():
            if sid in out:
                out[sid]["posts"].append(pid)
    return {p: s for p, s in of.items() if s in out}, out


def original_of(posts: List[str], at: Callable[[str], Any], by: Set[str], root: Optional[str] = None,
                origin_url: Optional[str] = None) -> Dict[str, Any]:
    """B3: a story's original: {"post": id or None, "url": the outside page or None, "why": by | origin | root}. The
    earliest post by the entity itself, else the root: Mark IX's outside page (origin_url) or first post, a Mark X
    story's earliest member."""
    mine = sorted((p for p in posts if p in by), key=lambda p: (at(p), p))
    if mine:
        return {"post": mine[0], "url": None, "why": "by"}
    if origin_url:
        return {"post": None, "url": origin_url, "why": "origin"}
    if root and root in posts:
        return {"post": root, "url": None, "why": "root"}
    first = sorted(posts, key=lambda p: (at(p), p))
    return {"post": first[0] if first else None, "url": None, "why": "root"}


def loose_order(roles: Set[str]) -> int:
    """B4: subject and actor first, then by, then venue / source / recommended, then mentions."""
    return min((ROLE_ORDER.get(r, 3) for r in roles), default=3)


# ---- the sample of old stories (C) ----------------------------------------------------------------------

def _rank(sid: str) -> str:
    return hashlib.sha256(("0144:" + sid).encode()).hexdigest()


def offer(cur: Any, root: str, stories: Dict[str, Any], now: datetime) -> List[Dict[str, Any]]:
    """C: the old stories this page offers to label: those already offered for the entity (unlabelled first), then
    new ones (a stable order) while the page has fewer than SAMPLE_PAGE and the day fewer than SAMPLE_DAY. `stories`:
    {Mark X story: its first post's time}. [{story, first_at, answer}]."""
    from insight_core.markx.story_window import RECENT
    edge = now - timedelta(days=RECENT)
    old = {s: at for s, at in stories.items() if at is not None and at < edge}
    if not old:
        return []
    cur.execute("""SELECT s.story_id::text, s.first_at,
                          (SELECT l.answer FROM mx_story_sample_labels l WHERE l.story_id = s.story_id
                            ORDER BY l.created_at DESC, l.id DESC LIMIT 1)
                     FROM mx_story_samples s WHERE s.story_id = ANY(%s::uuid[])""", (sorted(old),))
    shown = {sid: (at, answer) for sid, at, answer in cur.fetchall()}
    day = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    cur.execute("SELECT count(*) FROM mx_story_samples WHERE offered_at >= %s AND offered_at < %s",
                (day, day + timedelta(days=1)))
    today = cur.fetchone()[0]
    for sid in sorted((s for s in old if s not in shown), key=_rank):
        if len(shown) >= SAMPLE_PAGE or today >= SAMPLE_DAY:
            break
        cur.execute("""INSERT INTO mx_story_samples (story_id, entity_id, first_at, offered_at) VALUES (%s, %s, %s, %s)
                       ON CONFLICT (story_id) DO NOTHING""", (sid, root, old[sid], now))
        if cur.rowcount:
            today += 1
        shown[sid] = (old[sid], None)
    items = sorted(shown.items(), key=lambda kv: (kv[1][1] is not None, kv[1][0], kv[0]))[:SAMPLE_PAGE]
    return [{"story": sid, "first_at": at, "answer": answer} for sid, (at, answer) in items]


def label_sample(cur: Any, story_id: str, answer: str) -> Dict[str, Any]:
    """The owner's right / wrong / missed on an offered story (a new row; the newest counts). LookupError: never
    offered."""
    if answer not in SAMPLE_ANSWERS:
        raise ValueError("answer: right, wrong or missed")
    cur.execute("SELECT 1 FROM mx_story_samples WHERE story_id = %s", (story_id,))
    if cur.fetchone() is None:
        raise LookupError("This story was never offered for labelling")
    cur.execute("INSERT INTO mx_story_sample_labels (story_id, answer) VALUES (%s, %s)", (story_id, answer))
    return {"story": story_id, "answer": answer}
