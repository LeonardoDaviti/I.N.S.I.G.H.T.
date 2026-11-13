"""Voice counting as v10.16 wrote it, before issue 0189 put it behind utils/voice.py: frozen here, word for word, so
the seeded worlds of tests/test_voice_0189.py can show the module gives every caller what it gave before."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from insight_core.utils.story_rules import _UnionFind

VOICE_PREFIX = "voice:"


# ---- utils/story_rules.py (StoryPost's voice properties, voice_groups, count_voices, confirmed, reposter_voice) ----

def voice(p: Any) -> str:
    if p.kind == "site":
        return "site:" + p.own_site
    if p.kind == "reddit" and p.author:
        return "reddit:" + p.author
    return "source:" + p.source_id


def owner_voice(p: Any) -> str:
    return p.owner or voice(p)


def counted_voice(p: Any) -> str:
    return p.owner if confirmed(p.owner) and p.kind != "reddit" else voice(p)


def other_voices(p: Any, by_owner: bool = False) -> List[str]:
    owners = p.other_owners
    return [(owners[k] if k < len(owners) and owners[k] and (by_owner or confirmed(owners[k])) else None)
            or reposter_voice(s) for k, s in enumerate(p.other_sources)]


def voice_groups(items: Iterable[Tuple[Any, Optional[str], str]]) -> List[List[Any]]:
    uf = _UnionFind()
    keys: Dict[str, Any] = {}
    order = []
    for node, text, v in items:
        order.append(node)
        uf.find(node)
        for key in (("text:" + text) if text else None, "voice:" + v):
            if key is None:
                continue
            if key in keys:
                uf.union(node, keys[key])
            else:
                keys[key] = node
    groups: Dict[Any, List[Any]] = {}
    for node in order:
        groups.setdefault(uf.find(node), []).append(node)
    return list(groups.values())


def count_voices(posts: Sequence[Any], *, by_owner: bool = False) -> int:
    posts = [p for p in posts if p.kind != "saved"]
    return len(voice_groups([*((p.id, p.text_key, owner_voice(p) if by_owner else counted_voice(p)) for p in posts),
                             *((f"{p.id}>{s}", None, v) for p in posts
                               for s, v in zip(p.other_sources, other_voices(p, by_owner)))]))


def confirmed(owner: Optional[str]) -> bool:
    return bool(owner) and owner.startswith(VOICE_PREFIX)


def reposter_voice(source_id: str) -> str:
    return "source:" + source_id


# ---- markx/pairing.py ---------------------------------------------------------------------------------

NOT_VOICE = frozenset({"saved"})


def is_voice(kind: Optional[str]) -> bool:
    return kind not in NOT_VOICE


def pairing_voices(items: Iterable[Tuple[Any, Optional[str]]]) -> int:
    return len({source for source, kind in items if is_voice(kind)})


def counted_source(source_id: str, author_account: Optional[str], of_account: Mapping[str, str]) -> str:
    return (of_account.get(author_account) if author_account else None) or source_id


# ---- markx/built.py (v10.16: every member's source, a saved post's too) ---------------------------------

def built_voices(posts: Sequence[Any]) -> int:
    return len({p.source for p in posts})


# ---- db/repo_stories.py SourceFacts._own's key, owner_voice, voice_name -----------------------------------

def source_voice(kind: Optional[str], source_id: str, publication: str) -> str:
    return "site:" + publication if kind == "site" else "source:" + source_id


def owner_of(owners: Mapping[str, str], v: str) -> Optional[str]:
    if v.startswith("reddit:"):
        return owners.get(v.lower())
    return owners.get(v)


# ---- markx/source_stats.py ----------------------------------------------------------------------------

def channel_voice(source_id: str, voice_id: Optional[str]) -> str:
    return f"v:{voice_id}" if voice_id else f"s:{source_id}"


def story_voice(stored: Optional[str], source_id: str, voice_id: Optional[str]) -> str:
    v = stored or ""
    if v.startswith("source:") or not v:
        return channel_voice(source_id, voice_id)
    return v


# ---- db/repo_discover.py voice_source ---------------------------------------------------------------------

def voice_source(v: str, site_namers: Dict[str, str]) -> Optional[str]:
    if v.startswith("source:"):
        return v.split(":", 1)[1]
    return site_namers.get(v)
