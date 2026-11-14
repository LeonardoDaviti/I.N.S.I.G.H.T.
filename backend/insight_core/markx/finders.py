"""Track recall (issue 0147, Stealth v10.13): a track's passive posts are found by several finders whose candidates
are combined, not by one description vector (0145's prefilter). The Haiku judge (track-v1) then decides as before.

0145's measure: the median post sits at cosine 0.39-0.44 to any description; posts that belong often sit at 0.36-0.45
(an abstract description, concrete posts; one vector for many sub-topics; short posts; passing mentions). Every
finder is one signal; none decides alone (the owner's ensemble rule): each only puts a post up for judging.

**The finders** (each candidate records which fired: mx_track_items.found_by):
  1. **probe**: example posts. Once per track version a `probes` task (guide probes-v1, Haiku, one call) writes
     12-20 short example posts across the track's likely sub-topics and up to 4 near-misses; each is embedded (an
     `embed` task, subject 'track_probe'). A post's probe score is its max cosine to the probes and the description
     (the description stays one probe; with ✓ / ✗ labels the 0145 profile is one more), minus how far its nearest
     near-miss is closer than that (NEAR_PULL). It fires at the bar (`bar`).
  2. **domain**: link domains (post_links, not boilerplate, not a home page, not a platform) of DOMAIN_MIN+ ✓ items,
     in at most DOMAIN_MAX_SHARE of the posts; and the domain classes the description names by its words (code
     hosts and 3D-model sites: DOMAIN_CLASSES; model hubs measured out); a post linking one (not its home page).
  3. **word**: the terms most over-represented in ✓ items against the last SHARE_DAYS' posts (log-odds with an
     informative prior, z >= WORD_Z, in WORD_MIN_POS+ ✓ items, the top WORDS), looked up in the post's index
     (posts.search_vector) and Mark X's English layer (mx_post_search, 0139); WORD_MIN_HITS+ fire. The units of the
     ✓ items' numbers (a reading's main.numbers: tok/s, GB, $) in UNIT_MIN_POS+ of them make a post's number with
     one of those units count as a word.
  4. **tool** (0207): a post naming one of the tools the track's practitioners discuss (track_tools.finder_ids: 2+
     voices of its judged-in posts, specific to the track). The domain finder also learns from the track's own posts
     in (`taught`: Haiku's in at TEACH_CONF or more from its sources, or joined), not only the owner's ✓: a track the
     owner never labelled learned nothing. The words stay the ✓'s alone (taught, they were the sources' language).
     Measured on held-out tool posts the owner never named: recall 72.5% -> 80% (issue 0207).
Dropped in v10.18 (0203): the entity finder, the source and story priors and the classifier, never adopted (0147's
held-out recall on the server copy: entity and story added none, the source prior -2 / +3, the classifier as the order
-21 points on one track at 30%; the owner's labels, 7, never opened the classifier's gate of 30). mx_track_models keeps
the rows it ever wrote.

**The bar and the budget**: until MIN_EXAMPLES ✓, the probe bar is set so the union passes the same share of the last
SHARE_DAYS' posts as 0145's prefilter (tracks.DEFAULT_PASS_SHARE, at most tracks.DEFAULT_THRESHOLD): the other
finders' hits are counted first, the probes fill the rest (at least half of it). From MIN_EXAMPLES ✓, 0145's rule on the
probe score: the bar that keeps PASS_SHARE of the ✓ items passing. The union is ordered by how many finders fired, then
the probe score (`order_key`), and capped by the per-run budget (tracks.TASKS_PER_RUN).

**Which fire** (`active()`): all three (ADOPTED), or the ones INSIGHT_TRACK_FINDERS names (the example posts always).

Only mx_* tables are written.
"""
from __future__ import annotations

import logging
import math
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from psycopg import Cursor

from insight_core.markx import pairing, repo, schemas

log = logging.getLogger(__name__)

KIND = "probes"
EMBED_SUBJECT = "track_probe"
MODEL = "bge-m3"
FINDERS = ("probe", "domain", "word", "tool")
FINDERS_ENV = "INSIGHT_TRACK_FINDERS"
ADOPTED = FINDERS   # measured on the server copy (0147-built.md); 0203 dropped the four that added no recall; 0207: tool
SHOWN = {"probe": "example post", "domain": "domain", "word": "words", "tool": "tool in use"}
TEACH_CONF = 0.8    # 0207: the track's own posts in (Haiku's in at this confidence or more, active or joined) teach ...
TEACH_MAX = 200     # ... the domain finder, the newest this many, with the owner's ✓ (the words, units and bar: the ✓ only)
NEAR_PULL = 1.0
DOMAIN_MIN, DOMAIN_MAX_SHARE = 2, 0.01
RARE_FLOOR = 10            # "rare" is at most this many posts however few the window holds
WORDS, WORD_Z, WORD_MIN_POS, WORD_MIN_HITS, WORD_PRIOR = 30, 1.96, 2, 2, 500.0
UNIT_MIN_POS = 2
PROBE_FLOOR = 0.5          # the probes keep at least this share of the budget
HOME_RE = r"^https?://[^/]+/?([?#].*)?$"
PLATFORMS = {"reddit.com", "t.me", "youtube.com", "youtu.be", "news.ycombinator.com", "medium.com", "substack.com",
             "x.com", "twitter.com", "nitter.local", "piped.video", "facebook.com", "instagram.com", "linkedin.com",
             "threads.net", "bsky.app", "mastodon.social", "telegra.ph", "google.com", "archive.org", "bit.ly"}
# The domain classes a description may name by its words (a class, not a site the owner named: 0147 finder 3).
DOMAIN_CLASSES = {
    "code": ({"github.com", "gitlab.com", "codeberg.org", "sr.ht", "bitbucket.org", "sourceforge.net"},
             r"open[- ]source|\brepo|\bcode\b|\bfork|side projects?|\bhacks?\b|\btools?\b|\bbuilds?\b"),
    # model hubs ({"huggingface.co", "ollama.com", ...} for "models", "quantisation", "local AI") were measured and left
    # out: on the local-setups track they added no recall at the 30% budget and cost 8 points at 10% (hub links ride on
    # model launches, which then rank first as two-finder posts). 0147-built.md.
    "3d": ({"printables.com", "thingiverse.com", "makerworld.com", "cults3d.com", "thangs.com", "myminifactory.com"},
           r"3d[- ]print|\bprints?\b|\bstl\b|printable"),
}
UNIT_RE = re.compile(r"\d[\d.,]*\s*([a-z$€£%/][a-z/$€£%]{0,8})", re.I)
DATE = pairing.ordinary_date("p")


# ---- probes: the example posts --------------------------------------------------------------------------

def active() -> Tuple[str, ...]:
    """The finders that fire: INSIGHT_TRACK_FINDERS (comma-separated; the example posts always), else ADOPTED."""
    raw = os.environ.get(FINDERS_ENV)
    if not raw:
        return ADOPTED
    got = {f.strip() for f in raw.split(",") if f.strip() in FINDERS} | {"probe"}
    return tuple(f for f in FINDERS if f in got)


def probes_input(cur: Cursor, track: Dict[str, Any]) -> str:
    """What a `probes` task asks: the track's header without the examples (once per version, not per label)."""
    from insight_core.markx import tracks
    return tracks.header(cur, track, {"in": [], "out": []})


def probe_rows(cur: Cursor, folder_id: Any, version: int) -> List[Dict[str, Any]]:
    cur.execute("""SELECT id::text, near, text, v IS NOT NULL FROM mx_track_probes
                    WHERE track_id = %s AND version = %s ORDER BY near, created_at, id""", (str(folder_id), version))
    return [{"id": i, "near": n, "text": t, "embedded": e} for i, n, t, e in cur.fetchall()]


def _clean(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:schemas.PROBE_CHARS]


def add_probes(cur: Cursor, folder_id: Any, version: int, answer: Dict[str, Any], task_id: Any = None) -> int:
    """A `probes` answer's example posts as the track version's rows (none when it has some): how many were added."""
    if probe_rows(cur, folder_id, version):
        return 0
    n = 0
    seen: set = set()
    for near, texts in ((False, answer.get("probes") or []), (True, answer.get("near_misses") or [])):
        for t in texts:
            t = _clean(t)
            if not t or t.casefold() in seen:
                continue
            seen.add(t.casefold())
            cur.execute("""INSERT INTO mx_track_probes (track_id, version, near, text, text_hash, task_id)
                           VALUES (%s, %s, %s, %s, %s, %s)""", (str(folder_id), version, near, t, repo.sha256_hex(t),
                                                                task_id))
            n += 1
    return n


def plan_probes(cur: Cursor, **_kw: Any) -> int:
    """A `probes` task for each described track version with no example posts yet: how many were added. A version
    whose question was already answered (the same words as an older one) takes that answer."""
    from insight_core.markx import tracks
    schemas.ensure_guides(cur)
    added = 0
    for t in tracks.described(cur):
        if probe_rows(cur, t["folder_id"], t["version"]):
            continue
        task_id, new = repo.add_task(cur, kind=KIND, guide=schemas.KINDS[KIND].guide, subject_kind="track",
                                     input=probes_input(cur, t), a=t["folder_id"], priority=-1)
        if new:
            added += 1
            continue
        cur.execute("SELECT answer FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at, ctid LIMIT 1",
                    (task_id,))
        row = cur.fetchone()
        if row and row[0]:
            add_probes(cur, t["folder_id"], t["version"], row[0], task_id)
    return added


def after_answer(cur: Cursor, task: Dict[str, Any], call_id: Any, answer: Dict[str, Any]) -> None:
    """tasks.record's part: the example posts go to every described track version whose question this is."""
    from insight_core.markx import tracks
    for t in tracks.described(cur):
        if repo.sha256_hex(probes_input(cur, t)) == task["input_hash"]:
            add_probes(cur, t["folder_id"], t["version"], answer, task["id"])


def plan_vectors(cur: Cursor, **_kw: Any) -> int:
    """An `embed` task (subject 'track_probe', leased first) for each example post with no vector: how many were added.
    A text already embedded for another probe gets its vector copied."""
    guide = schemas.KINDS["embed"].guide
    cur.execute("SELECT id::text, text, text_hash FROM mx_track_probes WHERE v IS NULL ORDER BY created_at, id")
    added = 0
    for pid, text, h in cur.fetchall():
        task_id, new = repo.add_task(cur, kind="embed", guide=guide, subject_kind=EMBED_SUBJECT, input=text, a=pid,
                                     priority=-1)
        if new:
            added += 1
            continue
        cur.execute("""UPDATE mx_track_probes SET v = s.v FROM mx_track_probes s
                        WHERE mx_track_probes.id = %s AND s.text_hash = %s AND s.v IS NOT NULL""", (pid, h))
    return added


def store_vector(cur: Cursor, task: Dict[str, Any], vector: Sequence[float]) -> None:
    """An embed task of subject 'track_probe' answered (embed.store): every example post with that text."""
    cur.execute("UPDATE mx_track_probes SET v = %s::halfvec WHERE text_hash = %s",
                (repo.vector_text(vector), task["input_hash"]))


# ---- what the ✓ items teach (finders 2-3) ---------------------------------------------------------------

def _since(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


def domain_set(pos_domains: Sequence[Iterable[str]], df: Dict[str, int], n_posts: int, description: str
               ) -> List[str]:
    """Link domains of DOMAIN_MIN+ ✓ items (not platforms, at most DOMAIN_MAX_SHARE of the posts link them), plus the
    domain classes the description names."""
    c = Counter(d for ds in pos_domains for d in set(ds))
    cap = max(RARE_FLOOR, int(DOMAIN_MAX_SHARE * n_posts))
    out = {d for d, n in c.items() if n >= DOMAIN_MIN and d not in PLATFORMS and df.get(d, 0) <= cap}
    for sites, words in DOMAIN_CLASSES.values():
        if re.search(words, description or "", re.I):
            out |= sites
    return sorted(out)


def lexicon(pos_docs: Sequence[Iterable[str]], df: Dict[str, int], n_terms: int, *, top: int = WORDS) -> List[str]:
    """The terms most over-represented in the ✓ items against the window's posts (df: posts holding each term; n_terms:
    the window's terms, each post's distinct terms counted): log-odds with an informative Dirichlet prior (Monroe et
    al. 2008) on document counts, a prior of WORD_PRIOR terms shaped like the background; terms in WORD_MIN_POS+ ✓ items, z
    at WORD_Z+, the `top` highest."""
    docs = [set(d) for d in pos_docs]
    y = Counter(w for d in docs for w in d)
    if not y:
        return []
    n_i = sum(y.values())
    n_tot = max(n_terms, n_i + 1)
    n_j = n_tot - n_i
    a0 = WORD_PRIOR
    scored = []
    for w, yi in y.items():
        if yi < WORD_MIN_POS or len(w) < 3 or w.replace(".", "").replace(",", "").isdigit():
            continue
        dw = min(max(df.get(w, yi), yi), n_tot)
        a = WORD_PRIOR * dw / n_tot
        yj = dw - yi
        d = math.log((yi + a) / max(1e-9, n_i + a0 - yi - a)) - math.log((yj + a) / max(1e-9, n_j + a0 - yj - a))
        z = d / math.sqrt(1 / (yi + a) + 1 / (yj + a))
        if z >= WORD_Z:
            scored.append((z, w))
    return [w for _, w in sorted(scored, key=lambda x: (-x[0], x[1]))[:top]]


def units_of(numbers: Iterable[str]) -> set:
    """The units of a reading's numbers ("22 tok/s", "16 GB", "$300"): {"tok/s", "gb", "$"}."""
    out = set()
    for n in numbers or []:
        s = str(n)
        if "$" in s or "€" in s or "£" in s:
            out.add(next(c for c in s if c in "$€£"))
        for m in UNIT_RE.finditer(s):
            u = m.group(1).lower().strip(".,")
            if u and not u.isdigit():
                out.add(u)
    return out


def unit_set(pos_numbers: Sequence[Iterable[str]]) -> List[str]:
    """Units in UNIT_MIN_POS+ ✓ items' numbers."""
    c = Counter(u for ns in pos_numbers for u in units_of(ns))
    return sorted(u for u, n in c.items() if n >= UNIT_MIN_POS)


def units_regex(units: Sequence[str]) -> Optional[str]:
    if not units:
        return None
    alts = []
    for u in units:
        if u in "$€£":
            alts.append(re.escape(u) + r"\s*\d|\d\s*" + re.escape(u))
        else:
            alts.append(r"\d\s*" + re.escape(u) + r"(\W|$)")
    return "(" + "|".join(alts) + ")"


def _df(cur: Cursor, cache: Dict[Any, int], kind: str, cand: Sequence[str], sql: Any, params: Sequence[Any]
        ) -> Dict[str, int]:
    """Document counts of `cand` (the posts of the window holding each), read once per key and window into `cache`
    (v10.16: the window is in the key, so one cache serves every track of a plan pass)."""
    win = tuple(params)
    missing = [c for c in cand if (kind, win, c) not in cache]
    if missing:
        cur.execute(sql, (*params, missing))
        got = dict(cur.fetchall())
        for c in missing:
            cache[(kind, win, c)] = int(got.get(c, 0))
    return {c: cache[(kind, win, c)] for c in cand}


def _words_of(cur: Cursor, ids: Sequence[str]) -> List[List[str]]:
    cur.execute("""SELECT p.id::text, ARRAY(SELECT DISTINCT w FROM unnest(
                          tsvector_to_array(COALESCE(p.search_vector, ''::tsvector))
                          || tsvector_to_array(COALESCE(s.vector, ''::tsvector))) w)
                     FROM posts p LEFT JOIN mx_post_search s ON s.post_id = p.id WHERE p.id = ANY(%s::uuid[])""",
                (list(ids),))
    return [ws for _, ws in cur.fetchall()]


def _window(cur: Cursor, cache: Dict[Any, int], win: Tuple[datetime, datetime]) -> Tuple[int, int]:
    """(posts, terms) of the window, each post's distinct terms counted, read once per window into `cache`."""
    if ("n", win) not in cache:
        cur.execute(f"""SELECT count(*), COALESCE(sum(length(COALESCE(p.search_vector, ''::tsvector))
                                                  + length(COALESCE(s.vector, ''::tsvector))), 0)
                          FROM posts p LEFT JOIN mx_post_search s ON s.post_id = p.id
                         WHERE {DATE} >= %s AND {DATE} <= %s""", win)
        cache[("n", win)], cache[("terms", win)] = cur.fetchone()
    return int(cache[("n", win)] or 1), int(cache[("terms", win)] or 1)


def _pos_domains(cur: Cursor, pos: Sequence[str]) -> Dict[str, List[str]]:
    """{✓ post: the sites its kept links (not a home page) point at}."""
    cur.execute("""SELECT post_id::text, array_agg(DISTINCT target_site) FROM post_links
                    WHERE post_id = ANY(%s::uuid[]) AND NOT boilerplate AND target_url !~ %s GROUP BY post_id""",
                (list(pos), HOME_RE))
    return dict(cur.fetchall())


# v10.16: each document count reads the window's posts first (the posts' date index), then their rows; a count of a
# frequent site read every link and probed its post, 1.4 s a track on the scale copy. The words' counts are Postgres'
# own document counts (ts_stat) of each post's terms, its index and English layer together: the same count as the
# distinct posts holding the term, without a row per term.
_DF_DOM = f"""WITH w AS MATERIALIZED (SELECT p.id FROM posts p WHERE {DATE} >= %s AND {DATE} <= %s)
              SELECT l.target_site, count(DISTINCT l.post_id) FROM w JOIN post_links l ON l.post_id = w.id
               WHERE NOT l.boilerplate AND l.target_site IN (SELECT unnest(%s::text[])) GROUP BY 1"""


def _df_words(cur: Cursor, cache: Dict[Any, int], win: Tuple[datetime, datetime], cand: Sequence[str]
              ) -> Dict[str, int]:
    from psycopg import sql
    docs = sql.SQL("""SELECT COALESCE(p.search_vector, ''::tsvector) || COALESCE(s.vector, ''::tsvector)
                        FROM posts p LEFT JOIN mx_post_search s ON s.post_id = p.id
                       WHERE {date} >= {since} AND {date} <= {until}""").format(
        date=sql.SQL(DATE), since=sql.Literal(win[0]), until=sql.Literal(win[1])).as_string(cur)
    query = sql.SQL("SELECT word, ndoc FROM ts_stat({docs}) WHERE word IN (SELECT unnest(%s::text[]))").format(
        docs=sql.Literal(docs))
    missing = [c for c in cand if ("word", win, c) not in cache]
    if missing:
        cur.execute(query, (missing,))
        got = dict(cur.fetchall())
        for c in missing:
            cache[("word", win, c)] = int(got.get(c, 0))
    return {c: cache[("word", win, c)] for c in cand}


def prefetch(cur: Cursor, pos: Iterable[str], *, now: datetime, days: int = 30, cache: Dict[Any, int]) -> None:
    """v10.16: the window's counts every ✓ item of a plan pass needs (every track's, `pos`), read in one query each
    into `cache`, so `learn` of each track reads none of the window again."""
    pos = sorted(set(pos))
    win = (_since(now, days), now)
    _window(cur, cache, win)
    if not pos:
        return
    _df(cur, cache, "dom", sorted({d for ds in _pos_domains(cur, pos).values() for d in ds}), _DF_DOM, win)
    _df_words(cur, cache, win, sorted({w for ws in _words_of(cur, pos) for w in ws}))


def learn(cur: Cursor, track: Dict[str, Any], pos: Sequence[str], *, now: Optional[datetime] = None,
          days: int = 30, cache: Optional[Dict[Any, int]] = None) -> Dict[str, Any]:
    """Finders 2-3's sets from the ✓ items `pos` (post ids) against the last `days` days' posts. `cache` keeps the
    window's counts between calls (a plan pass's tracks share them)."""
    now = now or datetime.now(timezone.utc)
    since = _since(now, days)
    cache = {} if cache is None else cache
    win = (since, now)
    n_posts, n_terms = _window(cur, cache, win)
    pos = list(dict.fromkeys(pos))
    out: Dict[str, Any] = {"pos": pos, "domains": [], "words": [], "units": [], "n_posts": n_posts}
    # domains
    pos_domains = list(_pos_domains(cur, pos).values())
    df = _df(cur, cache, "dom", sorted({d for ds in pos_domains for d in ds}), _DF_DOM, win)
    out["domains"] = domain_set(pos_domains, df, n_posts, (track.get("name") or "") + " " + (track.get("description") or ""))
    # words (the post's index and the English layer)
    pos_docs = _words_of(cur, pos)
    df = _df_words(cur, cache, win, sorted({w for ws in pos_docs for w in ws}))
    out["words"] = lexicon(pos_docs, df, n_terms)
    # units of the readings' numbers
    cur.execute("""SELECT r.post_id::text, r.reading->'main'->'numbers' FROM mx_readings r
                    WHERE r.post_id = ANY(%s::uuid[]) AND jsonb_typeof(r.reading->'main'->'numbers') = 'array'""", (pos,))
    by_post: Dict[str, List[str]] = {}
    for pid, ns in cur.fetchall():
        by_post.setdefault(pid, []).extend(str(x) for x in ns or [])
    out["units"] = unit_set(list(by_post.values()))
    return out


# ---- scoring the posts --------------------------------------------------------------------------------

def probe_vectors(cur: Cursor, track: Dict[str, Any], *, profile: Optional[Sequence[float]] = None
                  ) -> List[Tuple[str, str]]:
    """[(vector text, group)]: the description ('desc', when its vector is for its current words), the version's
    example posts ('probe' / 'near'), and the 0145 profile ('profile', when given)."""
    from insight_core.markx import tracks
    out: List[Tuple[str, str]] = []
    if track.get("has_v") and track.get("v_hash") == tracks._sha(tracks.embed_text(track)):
        cur.execute("SELECT v::text FROM mx_tracks WHERE folder_id = %s", (track["folder_id"],))
        out.append((cur.fetchone()[0], "desc"))
    cur.execute("""SELECT v::text, CASE WHEN near THEN 'near' ELSE 'probe' END FROM mx_track_probes
                    WHERE track_id = %s AND version = %s AND v IS NOT NULL ORDER BY near, created_at, id""",
                (str(track["folder_id"]), track["version"]))
    out += [(v, g) for v, g in cur.fetchall()]
    if profile is not None:
        out.append((repo.vector_text(profile), "profile"))
    return out


def probe_score(pos: Optional[float], near: Optional[float]) -> Optional[float]:
    """The max cosine to the probes, minus NEAR_PULL x how far the nearest near-miss is closer than that."""
    if pos is None:
        return None
    return pos - NEAR_PULL * max(0.0, (near if near is not None else -1.0) - pos)


_SCORE = f"""
WITH pr AS MATERIALIZED (SELECT x.v::halfvec(1024) AS v, x.g FROM unnest(%(vs)s::text[], %(gs)s::text[]) AS x(v, g)),
ps AS (SELECT p.id, {DATE} AS at, p.source_id, e.v, p.search_vector
         FROM posts p JOIN mx_embeddings e ON e.post_id = p.id AND e.model = %(model)s
        WHERE {{where}}
          AND (NOT %(passive)s OR (p.source_id NOT IN (SELECT source_id FROM source_folders WHERE folder_id = %(t)s)
                                   AND {{suggestable}})))
SELECT ps.id::text, ps.at, ps.source_id::text, s.pos, s.near, s.descr,
       cardinality(%(doms)s::text[]) > 0 AND EXISTS (
           SELECT 1 FROM post_links l WHERE l.post_id = ps.id AND NOT l.boilerplate AND l.target_site = ANY(%(doms)s)
              AND l.target_url !~ %(home)s),
       CASE WHEN cardinality(%(words)s::text[]) = 0 THEN 0 ELSE (
           SELECT count(DISTINCT w) FROM unnest(tsvector_to_array(COALESCE(ps.search_vector, ''::tsvector))
                  || tsvector_to_array(COALESCE((SELECT q.vector FROM mx_post_search q WHERE q.post_id = ps.id),
                                                ''::tsvector))) w
            WHERE w = ANY(%(words)s)) END,
       %(units)s::text IS NOT NULL AND EXISTS (
           SELECT 1 FROM mx_readings r, jsonb_array_elements_text(CASE WHEN jsonb_typeof(r.reading->'main'->'numbers')
                  = 'array' THEN r.reading->'main'->'numbers' ELSE '[]'::jsonb END) n
            WHERE r.post_id = ps.id AND n ~* %(units)s),
       cardinality(%(tools)s::uuid[]) > 0 AND EXISTS (
           SELECT 1 FROM mx_mentions_now m WHERE m.post_id = ps.id AND m.entity_id = ANY(%(tools)s::uuid[]))
  FROM ps
  CROSS JOIN LATERAL (SELECT max(1 - (ps.v <=> pr.v)) FILTER (WHERE pr.g IN ('desc', 'probe', 'profile')) AS pos,
                             max(1 - (ps.v <=> pr.v)) FILTER (WHERE pr.g = 'near') AS near,
                             max(1 - (ps.v <=> pr.v)) FILTER (WHERE pr.g = 'desc') AS descr FROM pr) s
"""
ROW = ("post_id", "at", "source_id", "probe_pos", "near", "desc", "domain", "words", "unit", "tool")


def score(cur: Cursor, track: Dict[str, Any], prep: Dict[str, Any], *, since: Optional[datetime] = None,
          until: Optional[datetime] = None, ids: Optional[Sequence[str]] = None, passive: bool = True
          ) -> List[Dict[str, Any]]:
    """Every passive post (every post: passive=False) with a vector in [since, until] (or of `ids`) with its features and the finders that fire:
    [{post_id, at, source_id, probe, desc, domain, words, ..., fired: [..]}]."""
    where = []
    if since is not None:
        where.append(f"{DATE} >= %(since)s")
    if until is not None:
        where.append(f"{DATE} <= %(until)s")
    if ids is not None:
        where.append("p.id = ANY(%(ids)s::uuid[])")
    learned = prep["learned"]
    params = {"vs": [v for v, _ in prep["vectors"]], "gs": [g for _, g in prep["vectors"]], "model": MODEL,
              "t": str(track["folder_id"]), "since": since, "until": until, "ids": list(ids or []),
              "doms": learned["domains"], "home": HOME_RE, "words": learned["words"],
              "units": units_regex(learned["units"]), "passive": passive,
              "tools": list(learned.get("tools") or []) if "tool" in set(prep.get("on") or FINDERS) else []}
    from insight_core.db.repo_stories import suggestable_sql
    # issue 0200: a passive post of a source switched off is never asked (it could only become a suggestion)
    cur.execute(_SCORE.format(where=" AND ".join(where) or "true", suggestable=suggestable_sql("p.source_id")), params)
    out = []
    for r in cur.fetchall():
        d = dict(zip(ROW, r))
        for k in ("probe_pos", "near", "desc"):
            d[k] = None if d[k] is None else float(d[k])
        d["words"] = int(d["words"] or 0) + (1 if d["unit"] else 0)
        d["probe"] = probe_score(d["probe_pos"], d["near"])
        out.append(d)
    for d in out:
        fire(d, prep)
    return out


def fire(d: Dict[str, Any], prep: Dict[str, Any]) -> List[str]:
    """The finders that fire for one scored post (d["fired"])."""
    bar = prep["bar"]
    on = set(prep.get("on") or FINDERS)
    probe = d.get("probe")
    fired = []
    if probe is not None and probe >= bar:
        fired.append("probe")
    if d.get("domain") and "domain" in on:
        fired.append("domain")
    if (d.get("words") or 0) >= WORD_MIN_HITS and "word" in on:
        fired.append("word")
    if d.get("tool") and "tool" in on:
        fired.append("tool")
    d["fired"] = fired
    return fired


def labelled(prep: Dict[str, Any]) -> set:
    """The posts the owner labelled for the track: no judgement needed (the label wins)."""
    return set(prep.get("learned", {}).get("pos") or []) | set(prep.get("neg") or [])


def order_key(d: Dict[str, Any]) -> Tuple[float, float]:
    """The union's order (highest first): how many finders fired, then the probe score."""
    return (float(len(d.get("fired") or [])), d.get("probe") if d.get("probe") is not None else -1.0)


def budget_bar(rows: Sequence[Dict[str, Any]], share: float, cap: float) -> float:
    """The probe bar that makes the union pass `share` of `rows` (the last SHARE_DAYS' scored posts): the other finders'
    hits first, the probe scores fill the rest (at least PROBE_FLOOR of it); at most `cap`."""
    budget = int(round(share * len(rows)))
    others = [d for d in rows if _other_hit(d)]
    room = max(int(math.ceil(PROBE_FLOOR * budget)), budget - len(others))
    rest = sorted((d["probe"] for d in rows if not _other_hit(d) and d.get("probe") is not None), reverse=True)
    if not rest or room <= 0:
        return cap
    cut = rest[min(room, len(rest)) - 1]
    return min(cap, math.floor(cut * 10000) / 10000)


def _other_hit(d: Dict[str, Any]) -> bool:
    """A finder other than the probes fired."""
    return any(f in (d.get("fired") or []) for f in ("domain", "word", "tool"))


# ---- preparing a track ---------------------------------------------------------------------------------

def example_scores(cur: Cursor, track: Dict[str, Any], prep: Dict[str, Any], pos: Sequence[str], neg: Sequence[str]
                   ) -> List[float]:
    """Each ✓ item's probe score as if it were not one: the probes and the description, and the 0145 profile made
    without it (leave-one-out, so the examples don't vouch for themselves)."""
    from insight_core.markx import tracks
    bare = dict(prep, vectors=[x for x in prep["vectors"] if x[1] != "profile"])
    got = {d["post_id"]: d for d in score(cur, track, bare, ids=pos, passive=False)}
    desc = next((tracks._parse(v) for v, g in prep["vectors"] if g == "desc"), None)
    vs = tracks._vectors(cur, list(pos) + list(neg))
    pv = {p: vs[p] for p in pos if p in vs}
    nv = [vs[p] for p in neg if p in vs]
    out = []
    for p, d in got.items():
        best = d["probe_pos"]
        if p in pv:
            prof = tracks.combine(desc, [v for q, v in pv.items() if q != p], nv)
            if prof is not None:
                c = tracks._dot(tracks._unit(pv[p]) or pv[p], prof)
                best = c if best is None else max(best, c)
        s = probe_score(best, d["near"])
        if s is not None:
            out.append(s)
    return out


def _placed(cur: Cursor, track: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The track's judged posts with their places (the kept placement, else placed live; none for a track not saved)."""
    from insight_core.markx import track_kept, tracks
    if not track.get("folder_id") or not track.get("version"):
        return []
    got = track_kept.placed(cur, track)
    return (got if got is not None else tracks.placed(cur, track, shown=False))["items"]


def taught(placed: Sequence[Dict[str, Any]], neg: Sequence[str] = ()) -> List[str]:
    """0207: the track's own posts that teach the domain finder: in the track (its sources' or joined) with
    Haiku's in at TEACH_CONF or more, or the owner's ✓; never an owner ✗. The newest TEACH_MAX."""
    no = set(neg)
    got = [it for it in placed if it.get("place") in ("track", "joined") and it["post_id"] not in no
           and (it.get("label") == "in" or (it.get("verdict") and (it.get("confidence") or 0) >= TEACH_CONF - 1e-9))]
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    got.sort(key=lambda it: (it.get("at") or epoch, it["post_id"]), reverse=True)
    return [it["post_id"] for it in got[:TEACH_MAX]]


def prepare(cur: Cursor, track: Dict[str, Any], ex: Dict[str, List[str]], *, now: Optional[datetime] = None,
            share: Optional[float] = None, cap: Optional[float] = None,
            on: Optional[Sequence[str]] = None, cache: Optional[Dict[Any, int]] = None) -> Dict[str, Any]:
    """Everything a plan needs to find a track's posts: {vectors, learned, bar, ready, neg, now, on (the finders that
    fire: `active()` unless given)}. `ready` is False with no vector to score by (no description vector, no probe, no
    profile)."""
    from insight_core.markx import tracks
    now = now or datetime.now(timezone.utc)
    share = tracks.DEFAULT_PASS_SHARE if share is None else share
    cap = tracks.DEFAULT_THRESHOLD if cap is None else cap
    pos, neg = list(ex.get("in") or []), list(ex.get("out") or [])
    prof = tracks.profile(cur, track, ex) if (pos or neg) else None
    vectors = probe_vectors(cur, track, profile=prof["vector"] if prof and (pos or neg) else None)
    cache = {} if cache is None else cache   # v10.16: a plan pass's tracks share it (the window's counts, `prefetch`)
    # 0207: the domain finder learns from the track's own posts in too, not only the owner's ✓ (a track the
    # owner never labelled learned nothing: its passive posts were found by the example posts alone); the tool finder
    # reads the tools the track's practitioners discuss (track_tools). The probe bar stays the ✓'s alone.
    placed = _placed(cur, track)
    teach = list(dict.fromkeys(pos + taught(placed, neg)))
    learned = learn(cur, track, teach, now=now, cache=cache) if teach else {"pos": [], "domains": [], "words": [], "units": []}
    if len(teach) > len(pos):   # the words and units stay the owner's ✓'s alone: taught by the track's own posts they
        own = learn(cur, track, pos, now=now, cache=cache) if pos else {"words": [], "units": []}   # were the language
        learned["words"], learned["units"] = own["words"], own["units"]   # of its sources (measured: issue 0207)
    learned["pos"] = pos
    learned["taught"] = len(teach) - len(pos)
    if not teach:   # the description's domain classes need no ✓ item
        learned["domains"] = domain_set([], {}, 1, (track.get("name") or "") + " " + (track.get("description") or ""))
    from insight_core.markx import track_tools
    learned["tools"] = track_tools.finder_ids(cur, placed, now=now) if placed else []
    prep: Dict[str, Any] = {"vectors": vectors, "learned": learned, "bar": cap, "neg": neg, "now": now,
                            "cache": cache, "on": tuple(on) if on is not None else active(),
                            "ready": any(g in ("desc", "probe", "profile") for _, g in vectors)}
    if not prep["ready"]:
        return prep
    if len(pos) >= tracks.MIN_EXAMPLES:
        prep["bar"] = tracks.threshold_for(example_scores(cur, track, prep, pos, neg), default=cap)
    else:
        rows = score(cur, track, prep, since=_since(now, tracks.SHARE_DAYS), until=now)
        if len(rows) >= tracks.SHARE_MIN_POSTS:
            prep["bar"] = budget_bar(rows, share, cap)
    return prep
