"""Voices (issue 0132 A, 0078): one company, person or publication made of its channels (today's sources).

- **Suggested voices**: utils/voice_rules.py's rules over every source (the same address, a standing link, near-
  identical own posts with a shared name, both official for the same maker), each with its evidence; name-only pairs
  as "possible"; related voices (staff <-> company, heavy reposting). Computed in the background and kept
  (system_settings `voice_suggestions`); what the owner decided since is applied when they are read, so a decision
  shows at once. **Never applied without the owner.**
- **The owner decides**: Join (a voice, named by its main channel, editable), Not the same, Related, Make a voice
  by hand, a channel leaves, the voice is removed (its channels stay sources: 0078's question 4, default yes).
- **Stories count a confirmed voice once** (voice.count by Policy.STORIES_IX, through SourceFacts.voice_of). A
  decision that changes which voice a source counts as queues only those sources' posts (and the X posts by or reposting their
  accounts) for the story job, then asks for a run; nothing else regroups, and the rules' stamp never moves.

One voice per source (sources.voice_id): joining a source of another voice moves it (that voice, left with none, is
removed). Keep everything: no source, post or decision is deleted.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, ContextManager, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from insight_core.db import database as db
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_stories import StoriesRepository
from insight_core.db.repo_voices import VoicesRepository, counted
from insight_core.utils import source_roles
from insight_core.services import profiles_service
from insight_core.utils.voice_rules import (Channel, Verdict, groups, judge, not_followed, platform_of, profile_verdicts,
                                            shared_names, site_label, with_profiles)

logger = logging.getLogger(__name__)

SUGGESTIONS_KEY = "voice_suggestions"
SUGGESTIONS_FRESH = timedelta(hours=24)
KINDS = ("company", "person", "publication")

Officials = Callable[[Any, Mapping[str, Channel], Set[str]],
                     Tuple[Dict[str, source_roles.Official], Dict[str, source_roles.Focus]]]


def default_officials(cur: Any, channels: Mapping[str, Channel], reposts: Set[str]
                      ) -> Tuple[Dict[str, source_roles.Official], Dict[str, source_roles.Focus]]:
    """The role rule's step 3 and 4 (utils/source_roles.py) over Mark X's readings of each source's original posts:
    who is official, for which maker, and which maker each is most about. The hook Part B's role rule can replace."""
    reads = source_roles.load_reads(cur)
    officials, focus = {}, {}
    for sid, posts in reads.items():
        c = channels.get(sid)
        if c is None:
            continue
        own = {pid: m for pid, m in posts.items() if pid not in reposts}
        tokens, squashed = source_roles.self_names([c.name, c.channel_title],
                                                   [c.handle if c.kind != "site" else site_label(c.handle)])
        o = source_roles.official(own, tokens, squashed)
        if o:
            officials[sid] = o
        f = source_roles.focus(own)
        if f:
            focus[sid] = f
    return officials, focus


def one_question_per_voice(pairs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """v10.6.1: one question per (voice or source, voice or source): a channel possible with a confirmed voice is
    asked once, not once per channel of the voice; two channels of one voice are never asked. First kept."""
    seen: Set[Tuple[str, str]] = set()
    out: List[Dict[str, Any]] = []
    for p in pairs:
        ka, kb = (p["a"].get("voice_id") or p["a"]["id"]), (p["b"].get("voice_id") or p["b"]["id"])
        key = tuple(sorted((ka, kb)))
        if ka == kb or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _run_story_job(db_url: str) -> None:
    from insight_core.services.stories_service import in_own_process, recompute_job
    threading.Thread(target=in_own_process, args=(recompute_job, db_url), name="stories-voices", daemon=True).start()


class VoicesService:
    def __init__(self, db_url: str, *, officials: Optional[Officials] = None,
                 after_change: Optional[Callable[[str], None]] = None,
                 clock: Optional[Callable[[], datetime]] = None, background: bool = True,
                 cursor: Optional[Callable[[], ContextManager[Any]]] = None):
        self.db_url = db_url
        # One transaction a call (tests hand their own cursor: what it does is rolled back with theirs)
        self._cursor = cursor or (lambda: db.transaction(self.db_url))
        self.officials = officials or default_officials
        self.after_change = after_change if after_change is not None else _run_story_job
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.background = background
        self._computing = threading.Lock()

    # ---- suggestions ------------------------------------------------------------------------

    def compute_on(self, cur: Any) -> Dict[str, Any]:
        """Every pair of sources judged (voice_rules.judge), with what the page names them by. Read only."""
        started = time.monotonic()
        channels, reposts, source_of = VoicesRepository.channels(cur)
        outside: Dict[Tuple[str, str], List[Any]] = {}
        counts = VoicesRepository.pair_counts(cur, channels, reposts, source_of, outside)
        held_by: Dict[str, int] = {}
        for c in channels.values():
            for t in c.tokens:
                held_by[t] = held_by.get(t, 0) + 1
        named = [(a, b) for a in channels for b in channels if a < b and channels[a].tokens & channels[b].tokens
                 and shared_names(channels[a], channels[b], held_by)]
        VoicesRepository.copies(cur, named, reposts, counts)
        try:
            with cur.connection.transaction():   # a savepoint: a failed read leaves the rest of the run
                officials, focus = self.officials(cur, channels, reposts)
        except Exception:   # noqa: BLE001 - no reading (Mark X's tables missing): rule 4 says nothing
            logger.exception("Voices: the official rule could not run")
            officials, focus = {}, {}
        verdicts = judge(channels, counts, officials, focus)
        # 0132 C2: what the channels' profiles say (none before migration 0086 or a first fetch), and the channels
        # nobody follows that a profile, a source's own posts or Discover name as a source's other channel.
        profiles = profiles_service.current(cur)
        if profiles:
            verdicts = with_profiles(verdicts, profile_verdicts(channels, profiles, counts, held_by), channels,
                                     profiles, held_by)
        others = not_followed(channels, profiles, {k: (v[0], v[1]) for k, v in outside.items()},
                              VoicesRepository.discover_candidates(cur), held_by)
        return {
            "computed_at": self.clock().isoformat(), "seconds": round(time.monotonic() - started, 2),
            "not_followed": others, "followed": sorted({k for c in channels.values() for k in c.keys}),
            "profiles": len(profiles),
            "channels": {i: {"name": c.name, "kind": c.kind, "posts": c.posts, "enabled": c.enabled,
                             "platform": platform_of(c)} for i, c in channels.items()},
            "verdicts": [{"a": v.a, "b": v.b, "verdict": v.verdict, "evidence": v.evidence, "names": v.names}
                         for v in verdicts],
        }

    def refresh(self) -> Dict[str, Any]:
        """Judge every pair now and keep it. Returns the shaped suggestions."""
        with self._cursor() as cur:
            found = self.compute_on(cur)
        with self._cursor() as cur:
            SystemSettingsRepository.upsert(cur, SUGGESTIONS_KEY, found)
            return self.shape(cur, found)

    def _refresh_quietly(self, own_process: bool = False) -> None:
        try:
            if own_process:   # what it reads (every source's posts and links) goes back to the OS when it ends
                from insight_core.services.stories_service import in_own_process
                in_own_process(refresh_job, self.db_url)
            else:
                self.refresh()
        except Exception:  # noqa: BLE001 - derived; the next ask computes again
            logger.exception("Voices: suggestions could not be computed")
        finally:
            self._computing.release()

    def start_refresh(self) -> bool:
        """Compute the suggestions in the background, in a process of its own (one at a time; measured on the
        server copy of 2026-11-05: 4.0 s, 196 MB at its peak). True when one started."""
        if not self._computing.acquire(blocking=False):
            return False
        if not self.background:
            self._refresh_quietly()
            return True
        threading.Thread(target=self._refresh_quietly, args=(True,), name="voice-suggestions", daemon=True).start()
        return True

    def suggestions(self) -> Dict[str, Any]:
        """The kept suggestions with the owner's decisions since applied; when none are kept, or they are over a day
        old, they are computed again in the background (`computing`)."""
        with self._cursor() as cur:
            row = SystemSettingsRepository.get(cur, SUGGESTIONS_KEY)
        found = row[0] if row else None
        if found is None or self.clock() - datetime.fromisoformat(found["computed_at"]) > SUGGESTIONS_FRESH:
            self.start_refresh()
        with self._cursor() as cur:
            row = SystemSettingsRepository.get(cur, SUGGESTIONS_KEY)
            found = row[0] if row else None
            shaped = self.shape(cur, found) if found else {"computed_at": None, "voices": [], "possible": [], "related": [],
                                                                 "not_followed": [], "profiles": 0}
        return {"success": True, **shaped, "computing": self._computing.locked()}

    def shape(self, cur: Any, found: Mapping[str, Any]) -> Dict[str, Any]:
        """What the page shows of kept verdicts, as things stand now: the suggested voices (a pair said not the same
        never joins; a group already one voice is gone), the possible ones and the related ones the owner has not
        answered."""
        info = found.get("channels", {})
        verdicts = [Verdict(v["a"], v["b"], v["verdict"], v["evidence"], v.get("names", [])) for v in found.get("verdicts", [])]
        verdicts = [v for v in verdicts if v.a in info and v.b in info]
        ids = sorted(info)
        voice = VoicesRepository.voice_of(cur, ids) if ids else {}
        decided = VoicesRepository.decided_pairs(cur)
        current = {i: voice.get(i) for i in ids if i in voice}
        info = {i: c for i, c in info.items() if i in voice}   # a source removed since is not suggested
        verdicts = [v for v in verdicts if v.a in info and v.b in info]
        no = [p for p, kind in decided.items() if kind == "not_same"]
        found_groups = groups(verdicts, joined=current, rejected=no)
        in_group = {s: g for g in found_groups for s in g}

        def source(i: str) -> Dict[str, Any]:
            c = info[i]
            return {"id": i, "name": c["name"], "kind": c["kind"], "posts": c["posts"], "enabled": c["enabled"],
                    "voice_id": current.get(i)}
        out_voices = []
        for g in found_groups:
            members = set(g)
            edges = [{"a": v.a, "b": v.b, "verdict": v.verdict, "evidence": v.evidence} for v in verdicts
                     if v.verdict in ("same_channel", "join") and v.a in members and v.b in members
                     and (v.a, v.b) not in decided]
            existing = sorted({current[s] for s in g if current.get(s)})
            out_voices.append({"key": "|".join(g), "sources": [source(s) for s in g], "edges": edges,
                               "voice_ids": existing, "same_channel": any(e["verdict"] == "same_channel" for e in edges)})
        same_voice = lambda a, b: bool(current.get(a)) and current.get(a) == current.get(b)   # noqa: E731

        def open_pair(v: Verdict) -> bool:
            return (v.a, v.b) not in decided and not same_voice(v.a, v.b) \
                and not (v.a in in_group and in_group.get(v.b) is in_group[v.a])
        possible = one_question_per_voice([{"a": source(v.a), "b": source(v.b), "names": v.names, "evidence": v.evidence}
                                           for v in verdicts if v.verdict == "possible" and open_pair(v)])
        related = one_question_per_voice([{"a": source(v.a), "b": source(v.b), "evidence": v.evidence}
                                          for v in verdicts if v.verdict == "related" and open_pair(v)])
        return {"computed_at": found.get("computed_at"), "seconds": found.get("seconds"), "voices": out_voices,
                "possible": possible, "related": related,
                "not_followed": sorted(self._not_followed(cur, found, current).values(),
                                       key=lambda g: (g["subject"]["name"].lower(), g["subject"]["id"])),
                "profiles": found.get("profiles", 0)}

    @staticmethod
    def _not_followed(cur: Any, found: Mapping[str, Any], current: Mapping[str, Optional[str]]
                      ) -> Dict[str, Dict[str, Any]]:
        """0132 C2: the kept "not followed" channels as things stand now, one group per voice (its channels' merged)
        or per source with no voice: {subject {kind, id, name}, channels [{key, url, label, platform, of, why}]}.
        A channel followed since is gone."""
        kept = found.get("not_followed") or {}
        if not kept:
            return {}
        info = found.get("channels", {})
        followed = VoicesRepository.followed_keys(cur) | set(found.get("followed") or ())
        voice_ids = sorted({v for s, v in current.items() if v and s in kept})
        names = {v["id"]: v["name"] for v in VoicesRepository.voices(cur, voice_ids)} if voice_ids else {}
        out: Dict[str, Dict[str, Any]] = {}
        for sid, entries in kept.items():
            if sid not in current:
                continue   # a source removed since
            vid = current.get(sid)
            if vid and vid in names:
                subject = {"kind": "voice", "id": vid, "name": names[vid]}
            else:
                subject = {"kind": "source", "id": sid, "name": (info.get(sid) or {}).get("name", "")}
            group = out.setdefault(f"{subject['kind']}:{subject['id']}", {"subject": subject, "channels": []})
            of = (info.get(sid) or {}).get("name", "")
            for e in entries:
                if e["key"] in followed:
                    continue
                have = next((c for c in group["channels"] if c["key"] == e["key"]), None)
                if have is None:
                    group["channels"].append({**e, "of": [of], "why": list(e["why"])})
                else:
                    have["of"].append(of)
                    have["why"].extend(w for w in e["why"] if w not in have["why"])
        return {k: g for k, g in out.items() if g["channels"]}

    def not_followed_of(self, voice_id: str) -> List[Dict[str, Any]]:
        """A voice's channels nobody follows (the voice page's "Not followed"), from the kept suggestions."""
        with self._cursor() as cur:
            row = SystemSettingsRepository.get(cur, SUGGESTIONS_KEY)
            found = row[0] if row else None
            if not found or not found.get("not_followed"):
                return []
            current = VoicesRepository.voice_of(cur, sorted(found["not_followed"]))
            group = self._not_followed(cur, found, current).get(f"voice:{voice_id}")
        return group["channels"] if group else []

    # ---- the owner's decisions ----------------------------------------------------------------

    def _changed(self, cur: Any, before: Mapping[str, str]) -> List[str]:
        """The sources whose counted voice changed (repo_voices.counted, before and now), their posts queued for the
        story job with the X posts by or reposting their accounts."""
        now = counted(cur)
        changed = sorted(s for s in set(before) | set(now) if before.get(s) != now.get(s))
        if changed:
            StoriesRepository.queue_posts(cur, changed, VoicesRepository.x_accounts(cur, changed))
        return changed

    def _settled(self, changed: Sequence[str]) -> None:
        if changed:
            try:
                self.after_change(self.db_url)
            except Exception:  # noqa: BLE001 - the queued posts wait for the next story run
                logger.exception("Voices: the story job could not be asked for")

    @staticmethod
    def _check_sources(cur: Any, source_ids: Sequence[str], least: int) -> List[str]:
        ids = sorted({str(s) for s in source_ids or ()})
        if len(ids) < least:
            raise ValueError(f"a voice needs {least} source{'s' if least > 1 else ''} at least")
        found = VoicesRepository.voice_of(cur, ids)
        missing = [s for s in ids if s not in found]
        if missing:
            raise LookupError(f"no such source: {missing[0]}")
        return ids

    def join(self, source_ids: Sequence[str], *, voice_id: Optional[str] = None, name: Optional[str] = None,
             kind: Optional[str] = None, evidence: Any = None, by_hand: bool = False) -> Dict[str, Any]:
        """Join these sources into one voice (confirmed now): `voice_id`'s, else the voice most of them are in, else a
        new one named `name` or by its main channel. A source of another voice moves (one voice per source); a voice
        left with no channel is removed. `by_hand`: "Make a voice" (no suggestion behind it)."""
        if kind is not None and kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        with self._cursor() as cur:
            ids = self._check_sources(cur, source_ids, 1 if voice_id else 2)
            before = counted(cur)
            of = VoicesRepository.voice_of(cur, ids)
            if voice_id is not None:
                if not VoicesRepository.voices(cur, [voice_id]):
                    raise LookupError(f"no such voice: {voice_id}")
                target = voice_id
            else:
                held = sorted({v for v in of.values() if v}, key=lambda v: (-sum(1 for x in of.values() if x == v), v))
                target = held[0] if held else VoicesRepository.create(cur, (name or VoicesRepository.main_name(cur, ids)), kind)
            left = {v for s, v in of.items() if v and v != target}
            VoicesRepository.set_voice(cur, ids, target)
            for v in sorted(left):
                if not VoicesRepository.members(cur, v):
                    VoicesRepository.remove(cur, v)
            if name is not None or kind is not None:
                VoicesRepository.rename(cur, target, name, kind, kind is not None)
            VoicesRepository.decide(cur, "make" if by_hand else "join", ids, target, evidence or [])
            changed = self._changed(cur, before)
            voice = VoicesRepository.voices(cur, [target])[0]
        self._settled(changed)
        return {"success": True, "voice": voice, "queued_sources": changed}

    def not_same(self, a: str, b: str, evidence: Any = None) -> Dict[str, Any]:
        """The owner says two sources are not one voice: never suggested together again."""
        with self._cursor() as cur:
            ids = self._check_sources(cur, [a, b], 2)
            VoicesRepository.decide(cur, "not_same", ids, None, evidence or [])
        return {"success": True, "source_ids": ids}

    def related(self, a: str, b: str, evidence: Any = None) -> Dict[str, Any]:
        """Two sources are related voices (staff <-> company): each its own voice (one made for a source with none,
        named by it), the two linked with the evidence."""
        with self._cursor() as cur:
            ids = self._check_sources(cur, [a, b], 2)
            before = counted(cur)
            of = VoicesRepository.voice_of(cur, ids)
            if of[ids[0]] and of[ids[0]] == of[ids[1]]:
                raise ValueError("these sources are one voice: a voice is not related to itself")
            voices = []
            for sid in ids:
                vid = of[sid]
                if not vid:
                    vid = VoicesRepository.create(cur, VoicesRepository.main_name(cur, [sid]))
                    VoicesRepository.set_voice(cur, [sid], vid)
                voices.append(vid)
            VoicesRepository.link(cur, voices[0], voices[1], evidence or [])
            VoicesRepository.decide(cur, "related", ids, None, evidence or [])
            changed = self._changed(cur, before)
            out = VoicesRepository.voices(cur, voices)
        self._settled(changed)
        return {"success": True, "voices": out, "queued_sources": changed}

    def leave(self, source_id: str) -> Dict[str, Any]:
        """A channel leaves its voice (it stays a source); a voice left with none is removed."""
        with self._cursor() as cur:
            ids = self._check_sources(cur, [source_id], 1)
            before = counted(cur)
            vid = VoicesRepository.voice_of(cur, ids)[ids[0]]
            if not vid:
                raise ValueError("this source is in no voice")
            VoicesRepository.set_voice(cur, ids, None)
            if not VoicesRepository.members(cur, vid):
                VoicesRepository.remove(cur, vid)
            VoicesRepository.decide(cur, "leave", ids, vid, [])
            changed = self._changed(cur, before)
        self._settled(changed)
        return {"success": True, "voice_id": vid, "queued_sources": changed}

    def remove(self, voice_id: str) -> Dict[str, Any]:
        """Remove a voice: its channels stay sources, with no voice (the row is kept, removed_at)."""
        with self._cursor() as cur:
            if not VoicesRepository.voices(cur, [voice_id]):
                raise LookupError(f"no such voice: {voice_id}")
            before = counted(cur)
            members = VoicesRepository.remove(cur, voice_id)
            VoicesRepository.decide(cur, "remove", members, voice_id, [])
            changed = self._changed(cur, before)
        self._settled(changed)
        return {"success": True, "voice_id": voice_id, "source_ids": members, "queued_sources": changed}

    def rename(self, voice_id: str, name: Optional[str] = None, kind: Optional[str] = None,
               set_kind: bool = False) -> Dict[str, Any]:
        """A voice's name (editable; its main channel's by default) and kind. Counting never changes with it."""
        if name is not None and not name.strip():
            raise ValueError("a voice's name can't be empty")
        if set_kind and kind is not None and kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        with self._cursor() as cur:
            if not VoicesRepository.voices(cur, [voice_id]):
                raise LookupError(f"no such voice: {voice_id}")
            VoicesRepository.rename(cur, voice_id, name, kind, set_kind)
            VoicesRepository.decide(cur, "rename", [], voice_id, [{"name": name, "kind": kind}])
            return {"success": True, "voice": VoicesRepository.voices(cur, [voice_id])[0]}

    # ---- reading ----------------------------------------------------------------------------

    def voices(self) -> Dict[str, Any]:
        with self._cursor() as cur:
            return {"success": True, "voices": VoicesRepository.voices(cur)}

    def voice(self, voice_id: str) -> Dict[str, Any]:
        with self._cursor() as cur:
            found = VoicesRepository.voices(cur, [voice_id])
        if not found:
            raise LookupError(f"no such voice: {voice_id}")
        return {"success": True, "voice": found[0], "not_followed": self.not_followed_of(voice_id)}

    # ---- 0132 C2: the channel profiles' switch --------------------------------------------------

    def profiles_setting(self) -> Dict[str, Any]:
        with self._cursor() as cur:
            return {"success": True, "on": profiles_service.setting_on(cur)}

    def set_profiles_setting(self, on: bool) -> Dict[str, Any]:
        with self._cursor() as cur:
            return {"success": True, "on": profiles_service.set_setting(cur, on)}

    def of_source(self, source_id: str) -> Dict[str, Any]:
        """The voice a source is in (null when none): the source page's "part of <voice>"."""
        with self._cursor() as cur:
            vid = VoicesRepository.voice_of(cur, [source_id]).get(source_id)
            found = VoicesRepository.voices(cur, [vid]) if vid else []
        return {"success": True, "voice": found[0] if found else None}


def refresh_job(db_url: str) -> None:
    """The suggestions computed and kept, in a process of its own (stories_service.in_own_process)."""
    VoicesService(db_url, background=False).refresh()


__all__ = ["VoicesService", "default_officials", "refresh_job", "SUGGESTIONS_KEY"]
