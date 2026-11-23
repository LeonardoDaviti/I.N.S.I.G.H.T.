"""Entity surges: a decision run stage, no model. Per UTC day and per entity (version level, through the merges),
the distinct voices (a saved page is none) whose post credits it in its current mention set: a subject credits its
own entity, its maker and its family (the roll-up); an actor its own; no other role anything. A day of MIN_VOICES or
more is a surge, stored in mx_entity_surges with its posts and roll-up children ("Acme, via Nimbus 5"). A recount
that changes a row closes it (valid_to) and opens another; nothing is deleted. Incremental: the days of mentions
linked this run and of entities merged or undone since; the nightly full pass recounts the window.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from insight_core.markx import identity as I
from insight_core.markx import names as N
from insight_core.markx import pairing

RULE = "rollup3"
DATE = pairing.ix_date            # a mention's day: its post's Mark IX time (published, else fetched)
MIN_VOICES = 3
PRECISION = "91% (84-95%) on a fresh window, 88% (83-91%) across both (lab, 2026-11-06)"


def credits(book: I.Book, role: Optional[str], own: Optional[str], maker: Optional[str],
            family: Optional[str]) -> Dict[str, Optional[str]]:
    """{entity root: the child that credited it through the roll-up, or None (its own)}."""
    out: Dict[str, Optional[str]] = {}
    me = book.root(own) if own else None
    if me is None or role not in ("subject", "actor"):
        return out
    out[me] = None
    if role == "subject":
        for k in (N.key(maker), N.key(family), N.fields_key({"family": family}, maker)[0]):
            up = book.root(book.by_key(k)) if k else None
            if up and up not in out:
                out[up] = me
    return out


def count(cur: Any, book: I.Book, days: Optional[Iterable[date]], since: date, guide: str) -> Dict[Tuple[str, date], Dict]:
    """{(entity, day): {voices, posts, via}} of the days (None: every day since `since`)."""
    from insight_core.utils.post_links import source_kind
    day_list = sorted({d for d in days if d >= since}) if days is not None else None
    if day_list is not None and not day_list:
        return {}
    day = f"({DATE('p')} AT TIME ZONE 'UTC')::date"
    cur.execute(f"""SELECT m.post_id::text, m.role, m.entity_id::text, m.maker, m.family, m.n, m.guide,
                           {day}, p.source_id::text, s.platform, s.handle_or_url
                      FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id JOIN sources s ON s.id = p.source_id
                     WHERE m.guide = ANY(%s) AND m.role IN ('subject', 'actor') AND m.entity_id IS NOT NULL
                       AND {day} >= %s
                       {f"AND {day} = ANY(%s::date[])" if day_list is not None else ""}""",
                (guide, since, day_list) if day_list is not None else (guide, since))
    rows = cur.fetchall()
    # what the credits ask of the book, read ahead in one go
    book.prime(ids=[book.pins.get((r[0], r[6], r[5]), r[2]) for r in rows],
               keys=[k for r in rows if r[1] == "subject"
                     for k in (N.key(r[3]), N.key(r[4]), N.fields_key({"family": r[4]}, r[3])[0]) if k])
    acc: Dict[Tuple[str, date], Dict[str, Any]] = {}
    for pid, role, eid, maker, family, n, g, day, src, platform, handle in rows:
        eid = book.pins.get((pid, g, n), eid)
        if book.ents.get(book.root(eid) or "") and book.ents[book.root(eid)].status == "not_entity":
            continue
        voice = None if source_kind(platform, handle) == "saved" else src
        for ent, via in credits(book, role, eid, maker, family).items():
            row = acc.setdefault((ent, day), {"voices": set(), "posts": set(), "via": defaultdict(set)})
            if voice:
                row["voices"].add(voice)
            row["posts"].add(pid)
            if via:
                row["via"][via].add(pid)
    return acc


def stage(cur: Any, *, now: datetime, run_id: Any, days: Optional[Iterable[date]], window_days: int = 30,
          book: Optional[I.Book] = None) -> Dict[str, Any]:
    """Recount the days (None: every day of the window) and write what changed. `book`: the entity book as it is now,
    else a lazy book is read here."""
    from insight_core.markx import schemas
    guide = schemas.mention_guides()   # the current set
    book = I.lazy_book(cur) if book is None else book
    since = (now.astimezone(timezone.utc) - timedelta(days=window_days)).date()
    acc = count(cur, book, days, since, guide)
    want: Dict[Tuple[str, date], Dict[str, Any]] = {}
    for (ent, day), row in acc.items():
        if len(row["voices"]) >= MIN_VOICES:
            via = sorted(({"entity": c, "name": book.label(c) if c in book.ents else None, "posts": len(ps)}
                          for c, ps in row["via"].items()), key=lambda v: (-v["posts"], v["name"] or ""))
            want[(ent, day)] = {"voices": len(row["voices"]), "posts": len(row["posts"]),
                                "evidence": {"posts": sorted(row["posts"]), "via": via}}
    scope = None if days is None else {d for d in days if d >= since}
    cur.execute("""SELECT entity_id::text, day, voices, posts, evidence FROM mx_entity_surges
                    WHERE valid_to IS NULL AND rule = %s AND day >= %s""", (RULE, since))
    have = {(e, d): {"voices": v, "posts": p, "evidence": ev} for e, d, v, p, ev in cur.fetchall()
            if scope is None or d in scope}
    opened = closed = 0
    for k in sorted(set(have) | set(want), key=lambda k: (k[1], k[0])):
        old, new = have.get(k), want.get(k)
        if old == new:
            continue
        if old is not None:
            cur.execute("""UPDATE mx_entity_surges SET valid_to = now()
                            WHERE entity_id = %s AND day = %s AND rule = %s AND valid_to IS NULL""", (k[0], k[1], RULE))
            closed += 1
        if new is not None:
            cur.execute("""INSERT INTO mx_entity_surges (entity_id, day, voices, posts, rule, evidence, run_id)
                           VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)""",
                        (k[0], k[1], new["voices"], new["posts"], RULE, json.dumps(new["evidence"]), run_id))
            opened += 1
    return {"days": "all" if days is None else len(scope or ()), "surges": len(want), "opened": opened, "closed": closed}


def surging(cur: Any, book: I.Book, *, since: date) -> Dict[str, List[Dict[str, Any]]]:
    """{entity root: its current surges since `since`, newest first} (read through merges made after the count)."""
    cur.execute("""SELECT entity_id::text, day, voices, posts, evidence FROM mx_entity_surges
                    WHERE valid_to IS NULL AND rule = %s AND day >= %s ORDER BY day DESC""", (RULE, since))
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for eid, day, voices, posts, ev in cur.fetchall():
        out[book.root(eid) or eid].append({"day": day.isoformat(), "voices": voices, "posts": posts,
                                           "via": (ev or {}).get("via") or [], "post_ids": (ev or {}).get("posts") or []})
    return dict(out)
