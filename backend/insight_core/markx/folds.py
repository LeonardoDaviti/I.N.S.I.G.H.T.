"""Mark X v10.3 (issue 0127): duplicates folded. Inside a Mark X story, the posts that retell the same happening (the same
announcement reposted, translated, summarised) fold under one, so the happening shows once.

**The reading** (kind `read3`, guide `read-v3`): read-v2's fields plus `type_why`, `event_type` (14 types) and `origin`
(maker / relay / other), the lab's frozen rv3d guide without `confirms_earlier` and with invented examples. Asked only of
the current members of Mark X stories with 2+ members, in the reading window, once a post (`plan`); 5 a call (the
worker's PER_CALL). Stored as a reading under `read-v3` in mx_readings, beside the post's read-v2 one; `read` and the
decisions are unchanged.

**The rule** (`roles`, ported from the lab's rv3_rules.rv3_roles, round 1: F1 0.70 on 60 unseen clusters, one run
0.68-0.72): over a story's members with a read-v3 reading, in published order,
  1. the story's type: the most common news type of its members (a tie: the first to appear);
  2. originals: a member of that type by its maker, or the first relay of it while no original came before;
  3. leaks: a leak_rumour with a later member of the story's type (never folded, not shown as a leak);
  4. retellings: the other members of the story's type whose origin is other or relay.
**The group** (`group`): the head is the earliest original, else the earliest retelling; every other retelling folds
under it. The owner's answers (mx_labels, item kind `fold`, the newest per story and post; `undo` takes one back) beat
the rule: `not_same` unfolds a post, `same` folds one under the head. The head is never answered away.

**Nothing is stored of its own:** the fold is a function of the readings (never changed), the members (closed with
valid_to) and the owner's answers, computed when a page is built (`story_folds`). Only mx_* tables are read or written.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from insight_core.markx import event_types, pairing, repo, tasks

KIND, GUIDE = "read3", "read-v3"
PER_CALL = 5                     # the lab's rv3d batch size (the worker's PER_CALL names it)
NEWS_TYPES = event_types.NEWS_TYPES   # the seam's lists (0190)
LEAK = event_types.LEAK
ANSWERS = ("same", "not_same", "undo")
LAB = {"f1": 0.70, "single_runs": [0.68, 0.72, 0.71], "set": "60 unseen lab clusters, 214 members", "date": "2026-11-06"}


# ---- the rule (pure) -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Member:
    id: str
    at: datetime
    event_type: Optional[str]     # None: no read-v3 reading yet
    origin: Optional[str]


def _read(members: Iterable[Member]) -> List[Member]:
    """The members with a reading, in published order."""
    return sorted((x for x in members if x.event_type is not None), key=lambda x: (x.at, x.id))


def story_type(members: Sequence[Member]) -> Optional[str]:
    ids = _read(members)
    c = Counter(x.event_type for x in ids if x.event_type in NEWS_TYPES)
    if not c:
        return None
    first = {}
    for n, x in enumerate(ids):
        first.setdefault(x.event_type, n)
    return max(c, key=lambda t: (c[t], -first[t]))


def roles(members: Sequence[Member]) -> Dict[str, str]:
    """{post id: original | leak | retelling | reaction} for the members with a reading (rv3_roles)."""
    ids = _read(members)
    st = story_type(ids)
    out: Dict[str, str] = {}
    origs: List[str] = []
    for x in ids:
        if x.event_type == st and (x.origin == "maker" or (x.origin == "relay" and not origs)):
            out[x.id] = "original"
            origs.append(x.id)
    for n, x in enumerate(ids):
        if x.id in out:
            continue
        if x.event_type == LEAK:
            later = [y for y in ids[n + 1:] if y.event_type in NEWS_TYPES and y.event_type == st]
            out[x.id] = "leak" if later else "reaction"
        elif st and x.event_type == st and x.origin in ("other", "relay"):
            out[x.id] = "retelling"
        else:
            out[x.id] = "reaction"
    return out


@dataclass
class Group:
    head: Optional[str]
    folded: Dict[str, str] = field(default_factory=dict)     # post -> "rule" | "owner"
    rule: Dict[str, Optional[str]] = field(default_factory=dict)   # post -> the rule's role (None: not read)
    rule_folded: set = field(default_factory=set)
    answers: Dict[str, str] = field(default_factory=dict)    # post -> the owner's standing answer (same | not_same)

    def state(self, post: str) -> Optional[str]:
        """head | folded | shown (a read member outside the group) | None (not read yet, or no group to fold under)."""
        if post == self.head:
            return "head"
        if post in self.folded:
            return "folded"
        if self.head is not None and (self.rule.get(post) is not None or post in self.answers):
            return "shown"
        return None

    def view(self, post: str) -> Optional[Dict[str, Any]]:
        s = self.state(post)
        if s is None:
            return None
        return {"state": s, "head": self.head, "by": self.folded.get(post), "answer": self.answers.get(post),
                "rule": "folded" if post in self.rule_folded else "head" if post == self.head else "shown",
                "count": len(self.folded) if s == "head" else None}


def group(members: Sequence[Member], answers: Optional[Mapping[str, str]] = None) -> Group:
    r = roles(members)
    ids = _read(members)
    origs = [x.id for x in ids if r[x.id] == "original"]
    tells = [x.id for x in ids if r[x.id] == "retelling"]
    head = (origs or tells or [None])[0]
    rule_folded = {p for p in tells if p != head}
    answers = {p: a for p, a in (answers or {}).items() if a in ("same", "not_same") and p != head}
    folded = {p: "rule" for p in tells if p != head}
    if head is not None:
        for p, a in answers.items():
            if a == "not_same":
                folded.pop(p, None)
            elif p not in folded:
                folded[p] = "owner"
    g = Group(head=head, folded=folded, rule={x.id: r.get(x.id) for x in members}, rule_folded=rule_folded,
              answers=answers if head is not None else {})
    return g


# ---- the reading's input and task --------------------------------------------------------------------

def read3_input(p: Any, *, url: Optional[str], repost: Optional[Mapping[str, Any]]) -> str:
    """read-v2's input (markx text v1) with the lines the lab's rv3 block added after its first: the address, who
    wrote a repost, the published time (UTC, minutes)."""
    head, _, rest = tasks.read_input(p).partition("\n")
    extra = [f"Address: {url or ''}"]
    if repost and repost.get("author"):
        extra.append(f"Repost: written by @{repost['author']}, reposted by {p.source}")
    extra.append(f"Published: {p.at.astimezone(timezone.utc).isoformat()[:16]}")
    return "\n".join([head, *extra] + ([rest] if rest else []))


def _extras(cur: Any, ids: Sequence[str]) -> Dict[str, Tuple[Optional[str], Optional[dict]]]:
    """{post: (its url, its repost {by, author} or None)} as the reader names a repost (issue 0066)."""
    from insight_core.db.repo_reader import repost_of
    if not ids:
        return {}
    cur.execute("""SELECT p.id::text, p.url, s.platform, s.handle_or_url, p.author, p.reposted_by
                     FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = ANY(%s::uuid[])""", (list(ids),))
    return {pid: (url, repost_of(platform, handle, author, reposted_by))
            for pid, url, platform, handle, author, reposted_by in cur.fetchall()}


def inputs(cur: Any, ids: Iterable[Any]) -> Dict[str, str]:
    ids = [str(i) for i in ids]
    posts = tasks.load_posts(cur, ids)
    extra = _extras(cur, list(posts))
    return {pid: read3_input(p, url=extra.get(pid, (None, None))[0], repost=extra.get(pid, (None, None))[1])
            for pid, p in posts.items()}


def read3_task(cur: Any, post_id: Any, priority: int = 0):
    text = inputs(cur, [post_id]).get(str(post_id))
    if text is None:
        raise LookupError(f"no post {post_id}")
    return tasks.add(cur, KIND, text, a=str(post_id), priority=priority)


def plan(cur: Any, *, days: Any = tasks.SETTING, limit: int = tasks.PLAN_LIMIT, now: Optional[datetime] = None,
         fetched_since: Optional[datetime] = None) -> int:
    """`read3` tasks for the current members of Mark X stories with 2+ members, posted in the last `days` (default:
    the owner's reading window; None: every post) that have none, newest first: how many were added.
    `fetched_since` (0176 A, the fresh lane): the members fetched or surfaced since then (tasks.fresh_sql) instead."""
    if fetched_since is not None:
        days = None
    elif days is tasks.SETTING:
        days = tasks.reading_window(cur)
    cur.execute(
        f"""SELECT p.id::text, GREATEST(0, floor(extract(epoch FROM (COALESCE(%(now)s, now())
                                    - {pairing.ordinary_date('p')})) / 86400))::int
             FROM posts p
            WHERE p.id IN (SELECT sp.post_id FROM mx_story_posts sp
                            WHERE sp.valid_to IS NULL AND sp.role = 'member'
                              AND sp.story_id IN (SELECT story_id FROM mx_story_posts
                                                   WHERE valid_to IS NULL AND role = 'member'
                                                   GROUP BY story_id HAVING count(*) >= 2))
              AND (%(days)s::int IS NULL OR {pairing.ordinary_date('p')}
                                             >= COALESCE(%(now)s, now()) - make_interval(days => %(days)s))
              AND (%(fresh)s::timestamptz IS NULL OR {tasks.fresh_sql()})
              AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = p.id)
            ORDER BY {pairing.ordinary_date('p')} DESC, p.id
            LIMIT %(limit)s""", {"now": now, "days": days, "kind": KIND, "guide": GUIDE, "limit": limit,
                                 "fresh": fetched_since})
    rows = cur.fetchall()
    texts = inputs(cur, [r[0] for r in rows])
    added = 0
    for pid, age in rows:
        if pid in texts and tasks.add(cur, KIND, texts[pid], a=pid, priority=age)[1]:
            added += 1
    return added


# ---- a story's fold, from the database -----------------------------------------------------------------

def owner_answers(cur: Any, pairs: Iterable[Tuple[str, str]], labeller: str = "owner") -> Dict[Tuple[str, str], str]:
    """{(story, post): the newest answer} (same | not_same; an undo is no answer)."""
    pairs = list(pairs)
    if not pairs:
        return {}
    cur.execute("""SELECT DISTINCT ON (a, b) a::text, b::text, answer FROM mx_labels
                    WHERE item_kind = 'fold' AND labeller = %s
                      AND (a, b) IN (SELECT * FROM unnest(%s::uuid[], %s::uuid[]))
                    ORDER BY a, b, created_at DESC, ctid DESC""",
                (labeller, [s for s, _ in pairs], [p for _, p in pairs]))
    return {(a, b): ans for a, b, ans in cur.fetchall() if ans != "undo"}


def story_folds(cur: Any, story_ids: Iterable[str]) -> Dict[str, Group]:
    """{story: its Group} over each story's current members (role member) and their read-v3 readings, in published
    order (0128: built.PUBLISHED, a post's own date before the time it was received)."""
    story_ids = sorted({str(s) for s in story_ids if s})
    if not story_ids:
        return {}
    cur.execute(f"""SELECT sp.story_id::text, sp.post_id::text, {pairing.published_date('p')}
                     FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id
                    WHERE sp.story_id = ANY(%s::uuid[]) AND sp.valid_to IS NULL AND sp.role = 'member'""",
                (story_ids,))
    rows = cur.fetchall()
    types = event_types.types_of(cur, [pid for _s, pid, _at in rows])
    members: Dict[str, List[Member]] = {}
    for sid, pid, at in rows:
        et, origin = types[pid]
        members.setdefault(sid, []).append(Member(id=pid, at=at, event_type=et, origin=origin))
    answers = owner_answers(cur, [(s, x.id) for s, ms in members.items() for x in ms])
    return {s: group(ms, {p: a for (st, p), a in answers.items() if st == s}) for s, ms in members.items()}


def annotate(cur: Any, items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The News page's rows: each line of a Mark X story gets `fold` (Group.view, or None); a folded line whose head is
    not a line of its row is shown as `shown`. -> the header's count."""
    gs = story_folds(cur, {line.get("story") for r in items for line in r["posts"]})
    for r in items:
        here = {line["id"] for line in r["posts"]}
        for line in r["posts"]:
            g = gs.get(line.get("story") or "")
            v = g.view(line["id"]) if g else None
            if v and v["state"] == "folded" and v["head"] not in here:
                v = dict(v, state="shown")
            line["fold"] = v
        r["folded"] = sum(1 for line in r["posts"] if (line.get("fold") or {}).get("state") == "folded")
    return {"lab": LAB, **score(cur)}


# ---- the owner's answers --------------------------------------------------------------------------------

def answer(cur: Any, *, story: str, post: str, answer: str, note: Optional[str] = None,
           labeller: str = "owner") -> Dict[str, Any]:
    """One answer on a member's fold, applied at once (the next page reads it) and stored as a label: `same` folds it
    under the story's head, `not_same` shows it, `undo` takes the standing answer back. ValueError: not an answer, or
    the post is the head or has nothing to fold under; KeyError: not a current member."""
    if answer not in ANSWERS:
        raise ValueError(f"{answer!r} is not one of {', '.join(ANSWERS)}")
    cur.execute("""SELECT 1 FROM mx_story_posts WHERE story_id = %s AND post_id = %s AND valid_to IS NULL
                     AND role = 'member'""", (story, post))
    if cur.fetchone() is None:
        raise KeyError(f"{post} in {story}")
    g = story_folds(cur, [story]).get(story)
    if g is None or g.head is None:
        raise ValueError("this story has no group to fold under")
    if post == g.head:
        raise ValueError("the group's head is not folded")
    payload = {"rule": "folded" if post in g.rule_folded else "shown", "head": g.head}
    if note and note.strip():
        payload["note"] = note.strip()
    repo.add_label(cur, item_kind="fold", a=story, b=post, answer=answer, split="test", labeller=labeller,
                   note=json.dumps(payload))
    now = story_folds(cur, [story])[story]
    return {"story": story, "post": post, **(now.view(post) or {"state": None, "head": now.head, "answer": None})}


def story_view(cur: Any, story: str) -> Dict[str, Any]:
    """GET /api/markx/stories/{id}/folds: the story's members with their fold, in published order (0119 B6's view)."""
    g = story_folds(cur, [story]).get(story)
    if g is None:
        raise KeyError(story)
    cur.execute(f"""SELECT sp.post_id::text FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id
                    WHERE sp.story_id = %s AND sp.valid_to IS NULL AND sp.role = 'member'
                    ORDER BY {pairing.published_date('p')}, p.id""", (story,))
    posts = [r[0] for r in cur.fetchall()]
    return {"story": story, "head": g.head,
            "posts": [{"id": p, "role": g.rule.get(p), **(g.view(p) or {"state": None})} for p in posts]}


def score(cur: Any, labeller: str = "owner") -> Dict[str, Any]:
    """The owner's count: precision of the rule's folds (same among the folded ones answered) and the misses (same on a
    post the rule showed), each answer counted by its newest row (an undo counts nothing), with Wilson 95%."""
    from insight_core.markx.labels import wilson
    cur.execute("""SELECT DISTINCT ON (a, b) answer, note FROM mx_labels WHERE item_kind = 'fold' AND labeller = %s
                    ORDER BY a, b, created_at DESC, ctid DESC""", (labeller,))
    rows = []
    for ans, note in cur.fetchall():
        try:
            rule = (json.loads(note or "{}") or {}).get("rule")
        except ValueError:
            rule = None
        if ans != "undo":
            rows.append((ans, rule))
    folded = [a for a, rule in rows if rule == "folded"]
    right = sum(1 for a in folded if a == "same")
    lo, hi = wilson(right, len(folded))
    return {"answered": len(rows),
            "folded": {"n": len(folded), "right": right, "precision": round(right / len(folded), 3) if folded else None,
                       "interval": [round(lo, 3), round(hi, 3)] if folded else None},
            "missed": sum(1 for a, rule in rows if rule == "shown" and a == "same"),
            "shown_right": sum(1 for a, rule in rows if rule == "shown" and a == "not_same")}
