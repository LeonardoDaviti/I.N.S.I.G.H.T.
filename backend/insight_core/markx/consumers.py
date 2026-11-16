"""Who reads each kind's answers (issue 0210): a question is asked only while a feature that reads its answer is on.

Measured 2026-11-14 on the server's counts and the worker's logs: questions were still planned for a feature that is
not shipped (Back in the news failed its bar, 68%: 0136). The dropped features (Later developments, the components
rule, suffix merges: 0203) plan nothing any more. Perspectives, story sheets and stance stay asked (the owner,
2026-11-16: used later). Every kind names its consumer here (`CONSUMER`: a feature in
`FEATURES`), and a feature is on by its default or by the owner's word (mx_settings `consumers`: {feature: bool}).

While a feature is off:
  - its kinds' planners add nothing (api.work skips them; the decision run skips the back and perspectives stages);
  - a task of its kinds still added by any path is born closed: status `failed`, last_error NOT_ASKED (kept, with its
    reason; repo.add_task asks `born_closed`);
  - its kinds' open tasks are closed the same way (`close_off`, each plan job and at the switch).
Switched on again, the tasks it closed are open again (`set_on`).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from psycopg import Cursor

SETTING = "consumers"   # mx_settings: {feature: bool}, the owner's word over the defaults
NOT_ASKED = "not asked: no feature that reads it is on (0210)"
CACHE_SECONDS = 30.0


@dataclass(frozen=True)
class Feature:
    name: str
    on: bool                  # its default
    why: str


FEATURES: Dict[str, Feature] = {f.name: f for f in (
    Feature("news", True, "Mark X News, its stories, headlines, cards and readings (the reader's)"),
    Feature("entities", True, "entities: the pages, names and the identity review queue"),
    Feature("tracks", True, "tracks: verdicts, sub-topics, digests and finders"),
    Feature("graph", True, "Stalker's edges: a post's earlier posts on its page (0131)"),
    Feature("sources", True, "sources: stance, the source judge and research (asked by the owner)"),
    Feature("embeddings", True, "the embedder's vectors (no model cost)"),
    Feature("briefing", True, "the day's briefing on /markx"),
    Feature("back", False, "Back in the news (0136): not shipped, its bar failed (68%); off since 0210"),
    Feature("perspectives", True, "perspectives and story sheets (0119 B): Shadow on /markx, kept for later use (the "
                                  "owner, 2026-11-16)"),
)}

CONSUMER: Dict[str, str] = {
    "read": "news", "entities": "entities", "check": "news", "join": "news", "pair": "news", "merge": "news",
    "connect": "news", "card": "news", "headline": "news", "briefing": "briefing", "translate": "news",
    "embed": "embeddings", "embed_name": "embeddings", "alias": "entities", "alias2": "entities", "alias3": "entities",
    "alias4": "entities", "collide": "entities", "rename": "entities", "perspective": "perspectives",
    "sheet": "perspectives", "read3": "news", "relate": "graph", "stance": "sources", "back": "back", "cite": "entities",
    "track": "tracks", "subtopics": "tracks", "digest": "tracks", "subtopic_place": "tracks", "probes": "tracks",
    "scout": "tracks", "identity": "sources", "websearch": "sources", "source_judge": "sources",
    "news_sections": "news", "news_place": "news", "unit_types": "news", "significance": "news", "stop": "entities",   # 0165 C: the timeline stops
    "reading": "news",   # 0212: ent-v5 (planned only while its own switch is shadow or on)
}

_LOCK = threading.Lock()
_CACHE: List[Any] = [0.0, None]   # [read at (monotonic), {feature: on}]


def forget() -> None:
    with _LOCK:
        _CACHE[0], _CACHE[1] = 0.0, None


def states(cur: Cursor) -> Dict[str, bool]:
    """{feature: on}: the defaults, then the owner's word."""
    from insight_core.markx import repo
    got = repo.get_setting(cur, SETTING, default=None) or {}
    return {name: bool(got.get(name, f.on)) for name, f in FEATURES.items()}


def _states(cur: Cursor) -> Dict[str, bool]:
    with _LOCK:
        at, got = _CACHE
    if got is None or time.monotonic() - at > CACHE_SECONDS:
        got = states(cur)
        with _LOCK:
            _CACHE[0], _CACHE[1] = time.monotonic(), got
    return got


def feature_of(kind: str) -> str:
    return CONSUMER.get(kind, "news")


def wanted(cur: Cursor, kind: str) -> bool:
    """Whether a feature that reads `kind`'s answers is on (read from mx_settings at most every CACHE_SECONDS)."""
    return _states(cur).get(feature_of(kind), True)


def off_kinds(cur: Cursor, fresh: bool = False) -> List[str]:
    got = states(cur) if fresh else _states(cur)
    return sorted(k for k, f in CONSUMER.items() if not got.get(f, True))


def close_off(cur: Cursor) -> Dict[str, int]:
    """The open tasks of the kinds no feature reads, closed (kept: failed, NOT_ASKED): {kind: closed}."""
    kinds = off_kinds(cur, fresh=True)
    if not kinds:
        return {}
    cur.execute("""UPDATE mx_tasks SET status = 'failed', last_error = %s, lease_until = NULL, leased_by = NULL
                    WHERE kind = ANY(%s) AND status = 'open' RETURNING kind""", (NOT_ASKED, kinds))
    out: Dict[str, int] = {}
    for (kind,) in cur.fetchall():
        out[kind] = out.get(kind, 0) + 1
    return out


def set_on(cur: Cursor, feature: str, on: bool) -> Dict[str, Any]:
    """The owner's word on a feature; its kinds' tasks closed for it are open again (on) or its open ones closed."""
    from insight_core.markx import repo
    if feature not in FEATURES:
        raise ValueError(f"feature: one of {', '.join(FEATURES)}")
    got = dict(repo.get_setting(cur, SETTING, default=None) or {})
    got[feature] = bool(on)
    repo.set_setting(cur, SETTING, got)
    forget()
    kinds = sorted(k for k, f in CONSUMER.items() if f == feature)
    if on:
        cur.execute("""UPDATE mx_tasks SET status = 'open', last_error = NULL
                        WHERE kind = ANY(%s) AND status = 'failed' AND last_error = %s""", (kinds, NOT_ASKED))
        return {"feature": feature, "on": True, "reopened": cur.rowcount}
    return {"feature": feature, "on": False, "closed": sum(close_off(cur).values())}


def born_closed(cur: Cursor, kind: str) -> Optional[Tuple[str, str]]:
    """repo.add_task's question: (status, last_error) a new task of `kind` is born with when no feature reads it."""
    return None if wanted(cur, kind) else ("failed", NOT_ASKED)


def view(cur: Cursor) -> List[Dict[str, Any]]:
    """/markx: each feature, on or off, its kinds and why."""
    got = states(cur)
    return [{"feature": name, "on": got[name], "default": f.on, "why": f.why,
             "kinds": sorted(k for k, c in CONSUMER.items() if c == name)} for name, f in FEATURES.items()]
