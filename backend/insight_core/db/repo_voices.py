"""Voices (issue 0132 A): what the suggestion rules read (utils/voice_rules.py), the owner's voices and decisions
(migration 0080), and the "Also on" lines of a feed page. SQL only here; services/voices_service.py decides.

A confirmed voice of 2+ channels is what the story job counts once (SourceFacts.voice_of reads `counted`)."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from psycopg import Cursor

from insight_core.utils.addresses import host_of, publication_of
from insight_core.utils.post_links import source_kind
from insight_core.utils.voice_rules import (ALSO_WITHIN_HOURS, COPY_JACCARD, HOME_HOST_SHARE, Channel, PairCounts,
                                            account_address_key, address_key, jaccard, shingles)

def display_name(alias: str = "s") -> str:
    """A source's name as every page shows it: its display name, else its address."""
    return f"COALESCE(NULLIF(btrim({alias}.settings->>'display_name'), ''), {alias}.handle_or_url)"


DISPLAY_NAME = display_name()
LIVE = "v.confirmed_at IS NOT NULL AND v.removed_at IS NULL"
# A post's named author, as a site's feed writes it (a site of many is a platform)
META_AUTHOR = ("COALESCE(p.metadata->>'author_display_name', p.metadata->>'author_name', p.metadata->>'primary_author', "
               "p.metadata->>'author')")
URL_IN_TEXT = r"https?://[^\s<>\"')\]]+"


def counted(cur: Cursor) -> Dict[str, str]:
    """source id -> its voice id, for the confirmed voices of 2+ channels (what stories count once)."""
    cur.execute(f"""SELECT s.id::text, s.voice_id::text FROM sources s JOIN voices v ON v.id = s.voice_id
                    WHERE {LIVE} AND (SELECT count(*) FROM sources o WHERE o.voice_id = s.voice_id) >= 2""")
    return dict(cur.fetchall())


class VoicesRepository:
    # ---- what the suggestion rules read --------------------------------------------------------

    @staticmethod
    def channels(cur: Cursor) -> Tuple[Dict[str, Channel], Set[str], Dict[str, str]]:
        """(every source as voice_rules reads it, the posts that are reposts, post id -> its source)."""
        from insight_core.db.repo_stories import source_account
        cur.execute(f"""SELECT s.id::text, s.platform, s.handle_or_url, NULLIF(btrim(s.settings->>'display_name'), ''), s.enabled,
                               CASE WHEN {LIVE} THEN s.voice_id::text END
                        FROM sources s LEFT JOIN voices v ON v.id = s.voice_id""")
        out: Dict[str, Channel] = {}
        own_handle: Dict[str, str] = {}
        for sid, platform, handle, name, enabled, voice_id in cur.fetchall():
            kind = source_kind(platform, handle)
            account = source_account(platform, handle)
            keys: Set[str] = set()
            key = account_address_key(account) if account else None
            if kind in ("x", "telegram", "youtube", "reddit") and key:
                keys.add(key)
                short = key.split(":", 1)[1]
                own_handle[sid] = short
            elif kind not in ("saved", "hn"):
                key = address_key(handle)[0] if "://" in (handle or "") else None
                if key:
                    keys.add(key)
            shown = own_handle.get(sid) or (publication_of(host_of(handle)) if "://" in (handle or "") else handle)
            out[sid] = Channel(id=sid, kind=kind, name=name or shown, handle=shown or "", keys=keys,
                               enabled=bool(enabled), voice_id=voice_id)
        cur.execute(f"""SELECT p.id::text, p.source_id::text, p.url, p.author, COALESCE(cardinality(p.reposted_by), 0) > 0,
                               COALESCE(p.title, '') LIKE 'RT by @%%', p.metadata->>'channel_id',
                               p.metadata->>'channel_title', {META_AUTHOR}
                        FROM posts p""")
        reposts: Set[str] = set()
        source_of: Dict[str, str] = {}
        at_keys: Dict[str, Counter] = defaultdict(Counter)
        titles: Dict[str, Counter] = defaultdict(Counter)
        authors: Dict[str, Set[str]] = defaultdict(set)
        for pid, sid, url, author, reposted, rt, channel_id, channel_title, meta_author in cur.fetchall():
            c = out.get(sid)
            if c is None:
                continue
            source_of[pid] = sid
            c.posts += 1
            if reposted or rt or (c.kind == "x" and author and author.lower().lstrip("@") != own_handle.get(sid)):
                reposts.add(pid)
            else:
                c.own += 1
            if url:
                at_keys[sid][address_key(url)[0]] += 1
            if channel_id and c.kind == "youtube":
                c.keys.add("ytc:" + channel_id.lower())
            if channel_title:
                titles[sid][channel_title] += 1
            if meta_author and meta_author.strip():
                authors[sid].add(meta_author.strip())
        for sid, c in out.items():
            hosts = at_keys.get(sid, Counter())
            total = sum(hosts.values())
            # A website's host holding half its posts is its own address too (a feed elsewhere, its posts on its site).
            # A platform account's posts are on the platform, or on the bridge that reads it: its account is its address.
            for k, n in hosts.items():
                if c.kind == "site" and k and total and n / total >= HOME_HOST_SHARE:
                    c.keys.add(k)
            mine = sum(n for k, n in hosts.items() if k in c.keys)
            c.own_key_share = mine / total if total else 1.0
            c.other_keys = sum(1 for k in hosts if k and k not in c.keys)
            c.authors = len(authors.get(sid, ()))
            if titles.get(sid):
                c.channel_title = sorted(titles[sid].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        return out, reposts, source_of

    @staticmethod
    def pair_counts(cur: Cursor, channels: Mapping[str, Channel], reposts: Set[str],
                    source_of: Mapping[str, str]) -> Dict[Tuple[str, str], PairCounts]:
        """(A, B) -> what A's posts say of B: its links (post_links; a YouTube description's addresses too) to B's
        addresses, header/footer and bare profile links among them, and A's reposts of B's tweets."""
        import re
        key_to: Dict[str, Set[str]] = defaultdict(set)
        for sid, c in channels.items():
            for k in c.keys:
                key_to[k].add(sid)
        counts: Dict[Tuple[str, str], PairCounts] = {}

        def of(a: str, b: str) -> PairCounts:
            return counts.setdefault((a, b), PairCounts())
        per_post: Dict[str, List[Tuple[str, bool]]] = defaultdict(list)
        cur.execute("SELECT post_id::text, target_url, boilerplate FROM post_links")
        for pid, target, boilerplate in cur.fetchall():
            if pid in source_of:
                per_post[pid].append((target, bool(boilerplate)))
        youtube = sorted(i for i, c in channels.items() if c.kind == "youtube")
        if youtube:
            cur.execute("""SELECT id::text, COALESCE(metadata->>'description', '') || E'\n' || left(COALESCE(content, ''), 4000)
                           FROM posts WHERE source_id = ANY(%s::uuid[])""", (youtube,))
            for pid, text in cur.fetchall():
                per_post[pid].extend((u.rstrip(".,;"), False) for u in set(re.findall(URL_IN_TEXT, text or "")))
        for pid, links in per_post.items():
            a = source_of[pid]
            seen, seen_bp, seen_profile = set(), set(), set()
            for target, boilerplate in links:
                k, profile = address_key(target)
                if not k:
                    continue
                for b in key_to.get(k, ()):
                    if b == a:
                        continue
                    seen.add(b)
                    if boilerplate:
                        seen_bp.add(b)
                    if profile:
                        seen_profile.add(b)
            for b in seen:
                e = of(a, b)
                e.link_posts += 1
                if pid not in reposts:
                    e.link_posts_own += 1
                    e.example("own", pid)
            for b in seen_bp:
                of(a, b).bp_posts += 1
                of(a, b).example("bp", pid)
            for b in seen_profile:
                of(a, b).profile_posts += 1
                of(a, b).example("profile", pid)
        x_of = {c.handle: sid for sid, c in channels.items() if c.kind == "x"}
        if reposts:
            cur.execute("SELECT id::text, source_id::text, lower(ltrim(author, '@')) FROM posts "
                        "WHERE id = ANY(%s::uuid[]) AND author IS NOT NULL", (sorted(reposts),))
            for pid, a, author in cur.fetchall():
                b = x_of.get(author)
                if b and b != a and a in channels:
                    of(a, b).reposts += 1
                    of(a, b).example("reposts", pid)
        return counts

    @staticmethod
    def copies(cur: Cursor, pairs: Iterable[Tuple[str, str]], reposts: Set[str],
               counts: Dict[Tuple[str, str], PairCounts]) -> None:
        """Near-identical own posts (voice_rules.shingles, Jaccard COPY_JACCARD+) of each pair asked (those sharing a
        name: rule 3 needs one), counted both ways into `counts`."""
        pairs = sorted({tuple(sorted(p)) for p in pairs})
        wanted = sorted({s for p in pairs for s in p})
        if not wanted:
            return
        cur.execute("SELECT id::text, source_id::text, title, left(content, 4000) FROM posts WHERE source_id = ANY(%s::uuid[])",
                    (wanted,))
        docs: Dict[str, Dict[str, Set[int]]] = defaultdict(dict)
        for pid, sid, title, content in cur.fetchall():
            if pid in reposts:
                continue
            sh = shingles(title, content)
            if sh:
                docs[sid][pid] = sh
        for a, b in pairs:
            index: Dict[int, List[str]] = defaultdict(list)
            for pid, sh in docs.get(b, {}).items():
                for h in sh:
                    index[h].append(pid)
            for pid, sh in docs.get(a, {}).items():
                common = Counter(q for h in sh for q in index.get(h, ()))
                for q, n in common.items():
                    if n >= 3 and jaccard(sh, docs[b][q]) >= COPY_JACCARD:
                        for x, y, mine in ((a, b, pid), (b, a, q)):
                            e = counts.setdefault((x, y), PairCounts())
                            e.copies_own += 1
                            e.example("copies", mine)

    # ---- the owner's voices ---------------------------------------------------------------------

    @staticmethod
    def voice_of(cur: Cursor, source_ids: Sequence[str]) -> Dict[str, Optional[str]]:
        """source -> its live voice (None: none)."""
        cur.execute(f"""SELECT s.id::text, CASE WHEN v.id IS NOT NULL AND {LIVE} THEN v.id::text END
                        FROM sources s LEFT JOIN voices v ON v.id = s.voice_id WHERE s.id = ANY(%s::uuid[])""",
                    (list(source_ids),))
        return dict(cur.fetchall())

    @staticmethod
    def members(cur: Cursor, voice_id: str) -> List[str]:
        cur.execute("SELECT id::text FROM sources WHERE voice_id = %s ORDER BY id", (voice_id,))
        return [r[0] for r in cur.fetchall()]

    @staticmethod
    def main_name(cur: Cursor, source_ids: Sequence[str]) -> str:
        """The name of a voice's main channel: the one with the most posts (then the first added)."""
        cur.execute(f"""SELECT {DISPLAY_NAME} FROM sources s WHERE s.id = ANY(%s::uuid[])
                        ORDER BY (SELECT count(*) FROM posts p WHERE p.source_id = s.id) DESC, s.created_at, s.id LIMIT 1""",
                    (list(source_ids),))
        row = cur.fetchone()
        return row[0] if row else "A voice"

    @staticmethod
    def create(cur: Cursor, name: str, kind: Optional[str] = None) -> str:
        cur.execute("INSERT INTO voices (name, kind, confirmed_at) VALUES (%s, %s, now()) RETURNING id::text",
                    (name.strip(), kind))
        return cur.fetchone()[0]

    @staticmethod
    def set_voice(cur: Cursor, source_ids: Sequence[str], voice_id: Optional[str]) -> None:
        cur.execute("UPDATE sources SET voice_id = %s WHERE id = ANY(%s::uuid[])", (voice_id, list(source_ids)))

    @staticmethod
    def remove(cur: Cursor, voice_id: str) -> List[str]:
        """The voice removed (its row kept, removed_at), its channels kept as sources with no voice. Returns them."""
        members = VoicesRepository.members(cur, voice_id)
        cur.execute("UPDATE sources SET voice_id = NULL WHERE voice_id = %s", (voice_id,))
        cur.execute("UPDATE voices SET removed_at = now() WHERE id = %s AND removed_at IS NULL", (voice_id,))
        return members

    @staticmethod
    def rename(cur: Cursor, voice_id: str, name: Optional[str], kind: Optional[str], set_kind: bool) -> None:
        if name is not None:
            cur.execute("UPDATE voices SET name = %s WHERE id = %s", (name.strip(), voice_id))
        if set_kind:
            cur.execute("UPDATE voices SET kind = %s WHERE id = %s", (kind, voice_id))

    @staticmethod
    def link(cur: Cursor, a: str, b: str, evidence: Any) -> None:
        a, b = sorted((a, b))
        cur.execute("""INSERT INTO voice_links (a, b, kind, evidence) VALUES (%s, %s, 'related', %s::jsonb)
                       ON CONFLICT (a, b) DO UPDATE SET evidence = EXCLUDED.evidence""", (a, b, json.dumps(evidence)))

    @staticmethod
    def decide(cur: Cursor, kind: str, source_ids: Sequence[str], voice_id: Optional[str], evidence: Any) -> None:
        cur.execute("INSERT INTO voice_decisions (kind, source_ids, voice_id, evidence) VALUES (%s, %s::uuid[], %s, %s::jsonb)",
                    (kind, list(source_ids), voice_id, json.dumps(evidence)))

    @staticmethod
    def decided_pairs(cur: Cursor) -> Dict[Tuple[str, str], str]:
        """(a, b) -> the owner's last word on a pair: not_same | related (a < b)."""
        cur.execute("""SELECT kind, source_ids::text[] FROM voice_decisions WHERE kind IN ('not_same', 'related')
                       ORDER BY decided_at, id""")
        out: Dict[Tuple[str, str], str] = {}
        for kind, ids in cur.fetchall():
            ids = sorted(ids or ())
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    out[(ids[i], ids[j])] = kind
        return out

    @staticmethod
    def voices(cur: Cursor, voice_ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """The live voices (or these), each {id, name, kind, entity_id, created_at, confirmed_at, channels [{id, name,
        platform, kind, enabled, in_main_digest, priority, posts, last_post_at}], related [{id, name, evidence}],
        in_main_digest (any channel's), priority (the highest: the lowest number)}; first by name."""
        cur.execute(
            f"""SELECT v.id::text, v.name, v.kind, v.entity_id::text, v.created_at, v.confirmed_at
                FROM voices v WHERE {LIVE} AND (%(ids)s::uuid[] IS NULL OR v.id = ANY(%(ids)s::uuid[]))
                ORDER BY lower(v.name), v.id""", {"ids": list(voice_ids) if voice_ids is not None else None})
        rows = cur.fetchall()
        if not rows:
            return []
        ids = [r[0] for r in rows]
        cur.execute(
            f"""SELECT s.voice_id::text, s.id::text, {DISPLAY_NAME}, s.platform, s.handle_or_url, s.enabled, s.in_main_digest,
                       COALESCE(NULLIF(s.settings->>'priority', '')::numeric, 999),
                       (SELECT count(*) FROM posts p WHERE p.source_id = s.id),
                       (SELECT max(COALESCE(p.published_at, p.fetched_at)) FROM posts p WHERE p.source_id = s.id)
                FROM sources s WHERE s.voice_id = ANY(%s::uuid[])""", (ids,))
        channels: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for vid, sid, name, platform, handle, enabled, digest, priority, posts, last in cur.fetchall():
            channels[vid].append({"id": sid, "name": name, "platform": platform, "kind": source_kind(platform, handle),
                                  "enabled": bool(enabled), "in_main_digest": bool(digest), "priority": float(priority),
                                  "posts": int(posts), "last_post_at": last})
        cur.execute(f"""SELECT l.a::text, l.b::text, l.evidence, va.name, vb.name FROM voice_links l
                        JOIN voices va ON va.id = l.a JOIN voices vb ON vb.id = l.b
                        WHERE (l.a = ANY(%(ids)s::uuid[]) OR l.b = ANY(%(ids)s::uuid[]))
                          AND va.removed_at IS NULL AND vb.removed_at IS NULL""", {"ids": ids})
        related: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for a, b, evidence, na, nb in cur.fetchall():
            related[a].append({"id": b, "name": nb, "evidence": evidence})
            related[b].append({"id": a, "name": na, "evidence": evidence})
        out = []
        for vid, name, kind, entity_id, created_at, confirmed_at in rows:
            chans = sorted(channels.get(vid, []), key=lambda c: (-c["posts"], c["name"].lower(), c["id"]))
            out.append({"id": vid, "name": name, "kind": kind, "entity_id": entity_id, "created_at": created_at,
                        "confirmed_at": confirmed_at, "channels": chans, "related": related.get(vid, []),
                        "in_main_digest": any(c["in_main_digest"] for c in chans),
                        "priority": min((c["priority"] for c in chans), default=999.0)})
        return out

    @staticmethod
    def x_accounts(cur: Cursor, source_ids: Sequence[str]) -> List[str]:
        """The X accounts (x.com/<name>) of these sources: posts by or reposting them are queued with them."""
        from insight_core.db.repo_stories import source_account
        cur.execute("SELECT platform, handle_or_url FROM sources WHERE id = ANY(%s::uuid[])", (list(source_ids),))
        return sorted({a for p, h in cur.fetchall() if (a := source_account(p, h)) and a.startswith("x.com/")})

    # ---- "Also on <channel>" ---------------------------------------------------------------------

    @staticmethod
    def also_on(cur: Cursor, items: List[Dict[str, Any]], *, scope_kind: str, scope_id: Optional[str],
                filter: str) -> List[Dict[str, Any]]:
        """A feed page with one post on two channels of a confirmed voice shown once: a post that is a near-copy of,
        or links (or is linked by), the voice's other channel's post within ALSO_WITHIN_HOURS. The earliest shows, with
        the other as a line under it (`also_on`); the later one leaves the page when the earliest is in this view. One
        channel's own page shows every post (a single channel can still be read alone); Later, Kept and History too."""
        if scope_kind == "source" or filter not in ("all", "unread") or not items:
            return items
        ids = [str(i["id"]) for i in items if i.get("id")]
        cur.execute(f"""SELECT 1 FROM voices v WHERE {LIVE} LIMIT 1""")
        if cur.fetchone() is None:
            return items
        within = timedelta(hours=ALSO_WITHIN_HOURS)
        cur.execute(
            f"""WITH page AS (
                  SELECT p.id, p.source_id, s.voice_id, COALESCE(p.published_at, p.fetched_at) AS t, p.normalized_url,
                         p.content_hash, p.title, left(p.content, 4000) AS content
                  FROM posts p JOIN sources s ON s.id = p.source_id JOIN voices v ON v.id = s.voice_id
                  WHERE p.id = ANY(%(ids)s::uuid[]) AND {LIVE})
                SELECT pg.id::text, pg.t, pg.content_hash, pg.title, pg.content,
                       q.id::text, q.source_id::text, {display_name('qs')}, qs.platform, q.title, q.url,
                       COALESCE(q.published_at, q.fetched_at), q.content_hash, left(q.content, 4000),
                       EXISTS (SELECT 1 FROM post_links l WHERE l.post_id = pg.id AND l.target_url = q.normalized_url)
                       OR EXISTS (SELECT 1 FROM post_links l WHERE l.post_id = q.id AND l.target_url = pg.normalized_url),
                       CASE %(kind)s WHEN 'all' THEN qs.in_main_digest
                                     WHEN 'folder' THEN EXISTS (SELECT 1 FROM source_folders sf
                                                               WHERE sf.source_id = qs.id AND sf.folder_id = %(scope)s::uuid)
                                     ELSE TRUE END,
                       EXISTS (SELECT 1 FROM post_reader_state rs WHERE rs.post_id = q.id AND rs.read_at IS NOT NULL)
                FROM page pg
                JOIN sources qs ON qs.voice_id = pg.voice_id AND qs.id <> pg.source_id
                JOIN posts q ON q.source_id = qs.id
                 AND COALESCE(q.published_at, q.fetched_at) BETWEEN pg.t - %(within)s AND pg.t + %(within)s""",
            {"ids": ids, "kind": scope_kind, "scope": scope_id, "within": within})
        lines: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        hidden: Set[str] = set()
        shingled: Dict[str, Optional[set]] = {}

        def sh(pid: str, title: Optional[str], content: Optional[str]) -> Optional[set]:
            if pid not in shingled:
                shingled[pid] = shingles(title, content)
            return shingled[pid]
        for (pid, t, phash, ptitle, ptext, qid, qsource, qname, qplatform, qtitle, qurl, qt, qhash, qtext, linked,
             in_view, q_read) in cur.fetchall():
            same = bool(phash and phash == qhash)
            if not (linked or same):
                a, b = sh(pid, ptitle, ptext), sh(qid, qtitle, qtext)
                if not (a and b and jaccard(a, b) >= COPY_JACCARD):
                    continue
            if (t, pid) <= (qt, qid):   # this post is the earliest: the other is a line under it
                lines[pid].append({"id": qid, "source_id": qsource, "source_display_name": qname, "platform": qplatform,
                                   "title": qtitle, "url": qurl, "sort_at": qt,
                                   "why": "links" if linked else "copy"})
            elif in_view and not (filter == "unread" and q_read):
                hidden.add(pid)
        out = []
        for item in items:
            pid = str(item.get("id"))
            if pid in hidden:
                continue
            if lines.get(pid):
                item = {**item, "also_on": sorted(lines[pid], key=lambda line: (line["sort_at"], line["id"]))}
            out.append(item)
        return out


__all__ = ["VoicesRepository", "counted"]
