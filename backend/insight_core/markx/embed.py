"""Mark X Shadow's embeddings (issue 0086 B, the build plan's corrections 6): `embed` tasks, and the vectors' check
and store.

The embedder runs on the owner's device, not on the server: an `embed` task is leased like every other kind
(GET /api/markx/work?kinds=embed), the worker (scripts/markx-worker, --embedder) embeds its input with a local
`llama-server --embedding --pooling cls` (BGE-M3), and posts the vectors to POST /api/markx/embeddings. The server
never embeds anything in Shadow: it plans the tasks, checks and stores the vectors, and finds the candidates
(markx/candidates.py) when they arrive.

  - **The text** (`embed_text`, markx embed text v2): markx text v1's title and first 1,500 characters of the text
    (tasks.load_posts, read from post_parts), the title left out when the text starts with it, web addresses
    removed and spaces squashed, as the prototype embedded its posts (its step 1; it cut at 1,200 characters,
    0086 B says 1,500). The task's input is that text, so two posts with the same text are one task: the second
    post's vector is the first's, copied when the planner meets it again (`plan`).
  - **A text that says nothing** (v2, 2026-11-12): v1 embedded a post whose title and text were only web addresses
    or a media placeholder ("[Photo]", "Image") as one constant ("(empty)", "[Photo]", ...), so hundreds of posts
    shared one vector and every pair of them was an embedding candidate at cosine 1.0. A text says something when
    it has MIN_WORDS words of two letters or more once its addresses are removed (`says_something`; a bracketed
    placeholder is no word, a bare site name one). When the title and text don't, v2 describes the post by its
    links (their first LINKS, a link to a media file none): a linked post stored here by its title, the anchor
    text, the address's readable slug, and then the sites' names; when even that says nothing, the post gets no
    vector (and so no embedding candidate), recorded in mx_embed_skips under TEXT_VERSION, never a constant. A post
    v1 described says the same in v2: only the posts v1 embedded as nothing change.
  - **The v1 vectors of nothing** (`set_aside`): an `embed` vector stored for a text that says nothing is set
    aside, its row kept as it is under the model SET_ASIDE (every reader of mx_embeddings reads MODEL only), so the
    post is planned again under v2 (a vector of what describes it, or a skip). Candidate pairs found from such a
    vector are kept (never deleted) but not asked: the decision run reads an embedding candidate by its posts'
    current vectors (`current_candidates`).
  - **Identical vectors** (`same_vector`): two posts whose vectors are at cosine IDENTICAL or more are never an
    embedding candidate unless their texts are near-copies that say something (tasks.near_copy): one vector for
    two different posts is a text that said nothing, not one meaning; a real copy is Mark IX's to join. Measured
    on the 2026-11-05 server copy: of 6,490 candidates at 1.0, one was a real copy (kept), 6,489 were posts of
    "[Photo]", "(empty)", "[Video]" and "Image" texts paired with unrelated posts.
  - **The vector:** 1,024 little-endian float16, base64 (2 KB a post, not ~9 KB of JSON numbers), scaled to
    length 1 by the worker. The server decodes it, checks its length, its numbers and its norm, and stores it in
    mx_embeddings (halfvec, so float16 is stored as sent) with text_hash = the task's input hash.
  - **One build per database:** every vector names its model (`bge-m3`) and the GGUF's sha256. A vector from
    another build than the one already stored is refused (BuildMismatch, 409), since cosines across builds don't
    compare. A new build is a new database's vectors, or a deliberate re-embed (not in Shadow).
  - **Newest first, at most 500 posts a plan** (0086 B): every post, the newest first (priority = its age in
    days). Embedding costs no Claude usage, so it is not held to the last 30 days (corrections 8 is about Haiku).

An embed task has no mx_calls row: a vector is not a model's answer to audit, and the row it would duplicate is
the vector itself, which records its model and build.
"""
from __future__ import annotations

import base64
import math
import re
import struct
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit
from uuid import UUID

from psycopg import Cursor

from insight_core.markx import pairing, repo, schemas, tasks

KIND = "embed"
MODEL = "bge-m3"
TEXT_VERSION = "markx-embed-text-v2"          # v2: a text that says nothing is described by its links, or not embedded
SET_ASIDE = MODEL + ":said-nothing"            # the model a v1 vector of a text that says nothing is kept under
MIN_WORDS = 2                                  # a text says something with 2 words of 2+ letters (addresses removed)
LINKS = 3                                      # the links a post that says nothing is described by (a roundup's 3)
IDENTICAL = 0.9999                             # two vectors this close are one text, not one meaning
SCAN_CHARS = 400                               # set_aside reads the embed inputs this short (a text of nothing is short)
TEXT_CHARS = tasks.TEXT_CHARS                  # 1,500 (0086 B)
DIMENSIONS = repo.DIMENSIONS                   # 1,024
VECTOR_BYTES = 2 * DIMENSIONS                  # float16
NORM_TOLERANCE = 0.01                          # a float16 copy of a unit vector is within ~0.001 of 1
PLAN_LIMIT = 500
PLAN_PAGES = 4                                 # rows read per plan: up to 4 x the limit (duplicates are skipped)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
URL_RE = re.compile(r"https?://\S+|\b(?:[\w-]+\.)+[a-z]{2,}/\S*", re.I)
BUILD_LOCK = 0x6D78656D62   # pg_advisory_xact_lock key: one build is decided at a time ('mxemb')


class BuildMismatch(Exception):
    """A vector from another embedder build than the one stored (POST /api/markx/embeddings answers 409)."""


# ---- the text --------------------------------------------------------------------------------------

PLACEHOLDER_RE = re.compile(r"^\[[^\[\]]{0,40}\]$")          # a feed's stand-in for media: [Photo], [Video], ...
LETTER_RE = re.compile(r"[^\W\d_]")
WIDE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")   # scripts written without spaces
SLUG_SPLIT_RE = re.compile(r"[-_+]+")


def words(s: Optional[str]) -> int:
    """The words of `s` that say something: tokens of 2+ letters ("Next.js" and a bare "example.com" one each), a
    bracketed placeholder ("[Photo]") none (web addresses are the caller's to remove); a run of a script written
    without spaces counts a word per two characters."""
    n = 0
    for tok in (s or "").split():
        if PLACEHOLDER_RE.match(tok.rstrip(".,:;!?…")):
            continue
        tok = tok.strip("()[]{}<>\"'«»“”‘’.,:;!?…-—–*#")
        if not tok:
            continue
        wide = len(WIDE_RE.findall(tok))
        if wide:
            n += max(1, wide // 2)
        elif len(LETTER_RE.findall(tok)) >= 2:
            n += 1
    return n


def says_something(s: Optional[str]) -> bool:
    """Whether a text says something worth a vector: MIN_WORDS words once its web addresses are removed."""
    return words(URL_RE.sub(" ", s or "")) >= MIN_WORDS


def _own_text(p: tasks.Post) -> str:
    """markx embed text v1 without its constant: the title (left out when the text starts with it) and the first
    1,500 characters of the text, web addresses removed, spaces squashed."""
    title, text = p.title or "", (p.text or "")[:TEXT_CHARS]
    if text.startswith(title[:40]):
        title = ""
    return re.sub(r"\s+", " ", URL_RE.sub(" ", title + "\n" + text)).strip()


MEDIA_FILE_RE = re.compile(r"\.(?:jpe?g|png|gif|webp|avif|bmp|svg|mp4|webm|mov|m4v|m3u8|mkv|avi|mp3|m4a|ogg|wav|tgs)$",
                           re.I)                       # a link to the post's own picture, clip or sticker: no page
SLUG_WORD_RE = re.compile(r"^(?:[^\W\d_][^\W\d_A-Z]+|[^\W\d_a-z]{2,})\d{0,2}$")   # word, Word or WORD (+ "3")


def _slug(url: str) -> str:
    """The readable words of an address's path: a segment of 2+ words joined by - or _ ("ai-agents-course"), its
    file extension off; a token that is no word (an id, a hash, "ncWRe") is left out."""
    out = []
    for seg in urlsplit(url).path.split("/"):
        seg = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", seg)
        parts = [w for w in SLUG_SPLIT_RE.split(seg) if SLUG_WORD_RE.match(w)]
        if len(parts) >= 2:
            out.append(" ".join(parts))
    return " ".join(out)


def _site(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def linked_titles(cur: Cursor, posts: Iterable[tasks.Post]) -> Dict[str, str]:
    """{address: title} of the posts stored here that the first LINKS links of `posts` point at (by normalized
    address), the titles that say something."""
    from insight_core.utils.url_normalization import normalize_url
    want: Dict[str, List[str]] = {}
    for p in posts:
        for url, _anchor in p.links[:LINKS]:
            n = normalize_url(url)
            if n:
                want.setdefault(n, []).append(url)
    if not want:
        return {}
    cur.execute("""SELECT p.normalized_url, COALESCE(pp.title, p.title) FROM posts p
                     LEFT JOIN post_parts pp ON pp.post_id = p.id
                    WHERE p.normalized_url = ANY(%s) ORDER BY p.normalized_url, p.id""", (sorted(want),))
    out: Dict[str, str] = {}
    for n, title in cur.fetchall():
        title = re.sub(r"\s+", " ", title or "").strip()
        if says_something(title):
            for url in want[n]:
                out.setdefault(url, title)
    return out


def embed_text(p: tasks.Post, titles: Optional[Dict[str, str]] = None) -> Optional[str]:
    """markx embed text v2: the text an `embed` task asks for (its input), or None when nothing describes the post.
    The post's own words (v1's text) when they say something; else they and what its first LINKS links say (a
    stored post's title from `titles`, linked_titles', the anchor text, the address's slug), then the sites' names;
    None when even that says nothing (no vector, never a constant)."""
    own = _own_text(p)
    if says_something(own):
        return own
    about, sites = [], []
    for url, anchor in p.links[:LINKS]:
        if MEDIA_FILE_RE.search(urlsplit(url).path):
            continue
        for said in ((titles or {}).get(url), anchor, _slug(url)):
            said = re.sub(r"\s+", " ", URL_RE.sub(" ", said or "")).strip()
            if said and words(said) and said not in about and said not in own:
                about.append(said)
        site = _site(url)
        if site and site not in sites:
            sites.append(site)
    text = " ".join([own, *about]).strip()
    if not says_something(text):
        return None
    return " ".join([text, *sites]).strip()


# ---- the tasks -------------------------------------------------------------------------------------

def embed_task(cur: Cursor, post_id: Any, priority: int = 0):
    """The embed task of one post: (its id, whether it is new); (None, False) when nothing describes the post (its
    skip recorded)."""
    p, = tasks._posts(cur, [post_id])
    text = embed_text(p, linked_titles(cur, [p]))
    if text is None:
        skip(cur, [p.id])
        return None, False
    return tasks.add(cur, KIND, text, a=p.id, priority=priority)


def skip(cur: Cursor, post_ids: Sequence[Any]) -> None:
    """The posts nothing describes under TEXT_VERSION: no vector, and never planned again under it."""
    if post_ids:
        cur.execute("""INSERT INTO mx_embed_skips (post_id, text_version)
                       SELECT unnest(%s::uuid[]), %s ON CONFLICT DO NOTHING""", ([str(i) for i in post_ids], TEXT_VERSION))


_set_aside: set = set()


def set_aside(cur: Cursor, model: str = MODEL) -> int:
    """Set aside the `embed` vectors of texts that say nothing (markx embed text v1's "(empty)", "[Photo]", ...):
    each row is kept as it is under the model SET_ASIDE, so no reader of `model` vectors sees it and the post is
    planned again under v2. How many were set aside. Once a process and database (after it commits): a text that
    says nothing is never asked again, and `store` sets aside a late answer to one asked before."""
    from insight_core.db import database
    info = cur.connection.info
    where = (info.host, info.port, info.dbname, model)
    if where in _set_aside:
        return 0
    cur.execute("""SELECT input_hash, input FROM mx_tasks
                    WHERE kind = %s AND subject_kind = 'post' AND length(input) <= %s""", (KIND, SCAN_CHARS))
    nothing = [h for h, text in cur.fetchall() if not says_something(text)]
    n = 0
    if nothing:
        cur.execute("""UPDATE mx_embeddings e SET model = %s
                        WHERE e.model = %s AND e.text_hash = ANY(%s)
                          AND NOT EXISTS (SELECT 1 FROM mx_embeddings o WHERE o.post_id = e.post_id AND o.model = %s)""",
                    (SET_ASIDE, model, nothing, SET_ASIDE))
        n = cur.rowcount
    database.after_commit(cur.connection, lambda: _set_aside.add(where))   # a plain connection: every time
    return n


def _copy_vector(cur: Cursor, post_id: str, task: Dict[str, Any], model: str) -> bool:
    """Another post with the same text: its vector, already stored, copied to `post_id`."""
    cur.execute("""INSERT INTO mx_embeddings (post_id, model, model_sha256, text_hash, v)
                   SELECT %s, model, model_sha256, text_hash, v FROM mx_embeddings
                    WHERE post_id = %s AND model = %s AND text_hash = %s
                   ON CONFLICT (post_id, model) DO NOTHING""", (post_id, task["a"], model, task["input_hash"]))
    return cur.rowcount == 1


def plan(cur: Cursor, *, days: Optional[int] = None, limit: int = PLAN_LIMIT, now: Optional[datetime] = None,
         model: str = MODEL) -> int:
    """Embed tasks for the newest posts with no vector and no embed task of their own (every post when `days` is
    None), newest first (priority: the post's age in days): how many tasks were added. A post whose text another
    post's task already asks gets that post's vector once it is stored (and goes to the candidates' run), else
    waits for it."""
    from insight_core.markx import jobs
    spec = schemas.KINDS[KIND]
    set_aside(cur, model)
    added = 0
    seen: set = set()
    copied: List[str] = []
    for _page in range(PLAN_PAGES):
        cur.execute(
            f"""SELECT p.id, GREATEST(0, floor(extract(epoch FROM (COALESCE(%(now)s, now())
                                        - {pairing.ordinary_date('p')})) / 86400))::int
                 FROM posts p
                WHERE (%(days)s::int IS NULL OR {pairing.ordinary_date('p')}
                                                 >= COALESCE(%(now)s, now()) - make_interval(days => %(days)s))
                  AND NOT EXISTS (SELECT 1 FROM mx_embeddings e WHERE e.post_id = p.id AND e.model = %(model)s)
                  AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = p.id
                                     AND t.status <> 'answered')   -- answered with no vector: set aside
                  AND NOT EXISTS (SELECT 1 FROM mx_embed_skips k WHERE k.post_id = p.id AND k.text_version = %(version)s)
                  AND NOT (p.id = ANY(%(seen)s::uuid[]))
                ORDER BY {pairing.ordinary_date('p')} DESC, p.id
                LIMIT %(limit)s""",
            {"now": now, "days": days, "model": model, "kind": KIND, "guide": spec.guide, "seen": list(seen),
             "limit": limit, "version": TEXT_VERSION})
        rows = cur.fetchall()
        if not rows:
            break
        posts = tasks.load_posts(cur, [r[0] for r in rows])
        titles = linked_titles(cur, [p for p in posts.values() if not says_something(_own_text(p))])
        skipped = []
        for pid, age in rows:
            seen.add(str(pid))
            p = posts.get(str(pid))
            if p is None:
                continue
            text = embed_text(p, titles)
            if text is None:
                skipped.append(p.id)
                continue
            task_id, new = tasks.add(cur, KIND, text, a=p.id, priority=age)
            if new:
                added += 1
                continue
            task = repo.get_task(cur, task_id)
            if task["status"] == "answered" and _copy_vector(cur, p.id, task, model):
                copied.append(p.id)
        skip(cur, skipped)
        if added >= limit or len(rows) < limit:
            break
    jobs.note_posts(cur, copied)
    return added


NAME_KIND = "embed_name"


def plan_names(cur: Cursor, *, limit: int = PLAN_LIMIT, **_kw) -> int:
    """0119 A1: embed_name tasks for the entities (not marked not-an-entity) with no name vector and no task, the
    newest first: how many were added. The input is the entity's shown name, spaces squashed; a name of no letter or
    digit is not embedded (every such name would share one vector)."""
    cur.execute("""SELECT e.id::text, e.name FROM mx_entities e
                    WHERE e.status <> 'not_entity'
                      AND NOT EXISTS (SELECT 1 FROM mx_entity_vectors v WHERE v.entity_id = e.id)
                      AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %s AND t.a = e.id)
                    ORDER BY e.created_at DESC, e.id LIMIT %s""", (NAME_KIND, limit))
    added = 0
    for eid, name in cur.fetchall():
        name = re.sub(r"\s+", " ", name or "").strip()
        if not re.search(r"\w", name):     # a name of no letter or digit: one vector for every such name
            continue
        if tasks.add(cur, NAME_KIND, name, a=eid)[1]:
            added += 1
    return added


# ---- the vectors -----------------------------------------------------------------------------------

def encode(vector: Sequence[float]) -> str:
    """A vector as the worker sends it: 1,024 little-endian float16, base64 (the tests' and the worker's)."""
    return base64.b64encode(struct.pack(f"<{len(vector)}e", *vector)).decode("ascii")


def decode(text: Any) -> List[float]:
    """A posted vector, checked: 1,024 finite float16 of norm 1 (ValueError says why not)."""
    if not isinstance(text, str):
        raise ValueError("vector: a base64 string of 1,024 little-endian float16")
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        raise ValueError("vector: not base64") from None
    if len(raw) != VECTOR_BYTES:
        raise ValueError(f"vector: {len(raw)} bytes, not {VECTOR_BYTES} ({DIMENSIONS} float16)")
    v = list(struct.unpack(f"<{DIMENSIONS}e", raw))
    if not all(math.isfinite(x) for x in v):
        raise ValueError("vector: a number that is not finite")
    norm = math.sqrt(sum(x * x for x in v))
    if abs(norm - 1) > NORM_TOLERANCE:
        raise ValueError(f"vector: norm {norm:.4f}, not 1 (scale it to length 1)")
    return v


def check_build(cur: Cursor, model: str, model_sha256: str) -> None:
    """One embedder build per database: BuildMismatch when vectors of another build are stored under `model`."""
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (BUILD_LOCK,))
    others = {sha: n for sha, n in repo.embedding_builds(cur, model).items() if sha != model_sha256}
    if others:
        sha, n = max(others.items(), key=lambda kv: kv[1])
        raise BuildMismatch(f"this database holds {n} {model} vectors of build {sha or '(unknown)'}; "
                            f"a vector of build {model_sha256} doesn't compare with them")


def store(cur: Cursor, *, model: str, model_sha256: str, vectors: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Check and store posted vectors ({task_id, vector}): {stored, invalid: [{task_id, error}], repeated, posts}.
    A valid vector is stored for its task's post and closes the task; an invalid one puts the task back to open
    with its error (failed at the third try); one for a task already answered changes nothing (repeated).
    `posts`: the posts whose vector is new (for the candidates). ValueError: a model or build that isn't one;
    BuildMismatch: another build's vectors are stored."""
    if model != MODEL:
        raise ValueError(f"model: {MODEL!r} (BGE-M3), not {model!r}")
    if not isinstance(model_sha256, str) or not SHA256_RE.match(model_sha256):
        raise ValueError("model_sha256: the GGUF's sha256, 64 lowercase hex characters")
    check_build(cur, model, model_sha256)
    stored = repeated = 0
    invalid: List[Dict[str, Any]] = []
    posts: List[str] = []
    for item in vectors:
        raw_id = item.get("task_id") if isinstance(item, dict) else None
        try:
            task_id: Optional[UUID] = UUID(str(raw_id))
        except (TypeError, ValueError):
            task_id = None
        task = repo.get_task(cur, task_id) if task_id else None
        if task is None or task["kind"] not in (KIND, NAME_KIND):
            invalid.append({"task_id": raw_id, "error": "no such embed task"})
            continue
        try:
            v = decode(item.get("vector"))
        except ValueError as exc:
            invalid.append({"task_id": str(task_id), "error": str(exc)})
            if repo.fail_attempt(cur, task_id, str(exc)) is None:
                repeated += 1
            continue
        if task["status"] in ("answered", "failed"):
            repeated += 1
            continue
        if task["subject_kind"] == "track":   # 0145: a track's description, for its prefilter (markx/tracks.py)
            from insight_core.markx import tracks
            tracks.store_vector(cur, task, v)
            repo.answer_task(cur, task_id)
            stored += 1
            continue
        if task["subject_kind"] == "track_probe":   # 0147: a track's example post (markx/finders.py)
            from insight_core.markx import finders
            finders.store_vector(cur, task, v)
            repo.answer_task(cur, task_id)
            stored += 1
            continue
        if task["kind"] == NAME_KIND:      # 0119 A1: a name's vector, for the alias candidates
            cur.execute("""INSERT INTO mx_entity_vectors (entity_id, model, model_sha256, text_hash, v)
                           VALUES (%s, %s, %s, %s, %s::halfvec) ON CONFLICT (entity_id, model) DO NOTHING""",
                        (task["a"], model, model_sha256, task["input_hash"], repo.vector_text(v)))
            repo.answer_task(cur, task_id)
            stored += 1
            continue
        if not says_something(task["input"]):   # a v1 text of nothing asked before v2: kept, set aside
            repo.put_embedding(cur, post_id=task["a"], model=SET_ASIDE, text_hash=task["input_hash"], vector=v,
                               model_sha256=model_sha256)
        elif repo.put_embedding(cur, post_id=task["a"], model=model, text_hash=task["input_hash"], vector=v,
                                model_sha256=model_sha256):
            posts.append(str(task["a"]))
        repo.answer_task(cur, task_id)
        stored += 1
    return {"stored": stored, "invalid": invalid, "repeated": repeated, "posts": posts}


# ---- the candidates' guards ------------------------------------------------------------------------

def same_vector(cur: Cursor, pairs: Iterable[Tuple[str, str, float]]) -> Set[Tuple[str, str]]:
    """The pairs (a, b, cosine) whose two vectors are one vector (cosine IDENTICAL or more) while their texts are not
    near-copies (tasks.near_copy) that say something: never an embedding candidate (one vector for two different
    posts is a text that said nothing, not one meaning; two "[Photo]" posts are no copy of each other; a real copy
    is Mark IX's to join)."""
    one = [(str(a), str(b)) for a, b, c in pairs if c >= IDENTICAL]
    if not one:
        return set()
    got = tasks.load_posts(cur, {p for ab in one for p in ab})

    def copies(a: str, b: str) -> bool:
        return (a in got and b in got and says_something(_own_text(got[a])) and tasks.near_copy(got[a], got[b]))
    return {(a, b) for a, b in one if not copies(a, b)}


def current_candidates(cur: Cursor, rows: Sequence[Tuple[Any, Any, str, Optional[float]]], model: str = MODEL
                       ) -> Iterator[Tuple[Any, Any, str, Optional[float]]]:
    """mx_candidates rows (a, b, source, score) as the posts' current vectors have them: an `embedding` row whose
    post's vector was set aside and not replaced (a text that said nothing, embed text v1) is dropped, a row of two
    current vectors carries their cosine now (a vector replaced since moved) and is dropped when they are one vector
    (same_vector).
    The rows themselves are kept (never deleted). A dropped row whose post already has an answered pair or join
    stays as it was, so no story it made changes silently.

    v10.17.2 (0201): each embedding row's cosine is read by its place among them (not keyed by its two posts), and the
    rows are given back one at a time, in order: a decision run's ~450k pairs were held three times at once (the
    rows, their cosines by (a, b), the list given back)."""
    emb = [k for k, (_a, _b, src, _s) in enumerate(rows) if src == "embedding"]
    if not emb:
        return iter(rows)
    cur.execute("""SELECT k.i, 1 - (x.v <=> y.v)
                     FROM unnest(%s::uuid[], %s::uuid[]) WITH ORDINALITY AS k(a, b, i)
                     JOIN mx_embeddings x ON x.post_id = k.a AND x.model = %s
                     JOIN mx_embeddings y ON y.post_id = k.b AND y.model = %s""",
                ([str(rows[k][0]) for k in emb], [str(rows[k][1]) for k in emb], model, model))
    now: Dict[int, float] = {}            # the row's index in `rows` -> its cosine now
    for i, c in cur:
        now[emb[i - 1]] = float(c)

    def ab(k: int) -> Tuple[str, str]:
        return str(rows[k][0]), str(rows[k][1])
    ids = sorted({p for k in emb if k not in now for p in ab(k)})
    cur.execute("""SELECT s.post_id::text FROM mx_embeddings s
                    WHERE s.model = %s AND s.post_id = ANY(%s::uuid[])
                      AND NOT EXISTS (SELECT 1 FROM mx_embeddings e WHERE e.post_id = s.post_id AND e.model = %s)""",
                (SET_ASIDE, ids, model))
    aside = {r[0] for r in cur.fetchall()}
    one = same_vector(cur, [(*ab(k), c) for k, c in now.items() if c >= IDENTICAL])
    gone = {ab(k) for k in emb if ab(k)[0] in aside or ab(k)[1] in aside or (k in now and ab(k) in one)}
    if gone:
        ids = sorted({p for pair_ in gone for p in pair_})
        cur.execute("""SELECT DISTINCT unnest(ARRAY[a, b])::text FROM mx_tasks
                        WHERE kind IN ('pair', 'join') AND status = 'answered'
                          AND (a = ANY(%s::uuid[]) OR b = ANY(%s::uuid[]))""", (ids, ids))
        asked = {r[0] for r in cur.fetchall()}
        gone = {pair_ for pair_ in gone if not (pair_[0] in asked or pair_[1] in asked)}

    def given() -> Iterator[Tuple[Any, Any, str, Optional[float]]]:
        for k, (a, b, src, score) in enumerate(rows):
            if src == "embedding":
                if gone and ab(k) in gone:
                    continue
                if k in now:
                    score = round(now[k], 4)
            yield a, b, src, score
    return given()
