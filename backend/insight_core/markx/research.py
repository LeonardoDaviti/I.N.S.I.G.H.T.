"""Research (issue 0162, Stealth v10.14): start from a pasted post, a link, an entity, a name or a question; INSIGHT
finds what it already holds, the same announcement elsewhere, the maker and its identity graph, its channels (test-read
as 0148's scout reads), its papers and who discusses it. Only ever started by the owner's tap ("Research this"); a run
is a page of its own (`/research/<id>`), kept, re-run any time (what an earlier run of the seed found is not new).

**Steps** (`advance`, each recorded in mx_research_runs.steps when done; a step that waits for Haiku goes on later):
  1. `held` (no request, at `start`): the seed's entity (a name by identity's name key or its aliases, then search's
     entity cards; a question's entity cards each a seed; a link's or a post's by the entities whose addresses it is),
     its posts, stories, voices and addresses, the posts linking any version of its addresses (research_web.versions),
     and the other names that may be one thing with it (offered, never merged here: the owner's review queue does).
  2. `same_post` (a pasted post or a link): each link resolved (one request, a shortener lands elsewhere); the posts
     INSIGHT holds that share a unique link with it (held by at most UNIQUE_MAX posts, never a front page); then a
     near-copy of its text (the shingles Mark X compares copies by, over the posts its rarest words find); later
     (`around`) the posts of the maker's own channels in the days around. Each hit says why.
  3. `maker` (requests: platform pages only, at most PAGE_REQUESTS a run with the shorteners): the seed's things (the
     link itself, a post's project and paper links, an entity's addresses) at hop 0; the owner a platform states for a
     project page (`<host>/<owner>/<thing>`) and the links a confirmed page declares as its own, hop by hop, at most
     HOPS from the seed; each page read once (research_web.page_summary), each new address classified
     (research_web.classify). Same identity by plain rules first (research_web.same_identity: the platform's owner,
     declared both ways, the same handle, the page names the other); the rest one Haiku `identity` question each (guide
     identity-v1, at most IDENTITY_MAX a run); a name alone never. Only a confirmed page's links are followed.
  4. `web` (research_web.web_search): with SearXNG or Brave configured, the maker's name on each platform class INSIGHT
     reads; else (0171, the default) one `websearch` task asked of the worker (guide websearch-v1: Claude Code with its
     web search tool only, on the owner's device), the run waiting for its answer (`web_by_worker`); `off` skips it.
     Each result an address to read and judge as in 3, never an identity by its name. WEB_QUERIES searches a run.
  5. `channels`: every confirmed account, project and site (not a paper) a candidate of the run's scout run (0148,
     trigger 'research'): test-read through the add path into the scratch area, its health; judged by a track only
     once the run has one ("Watch this"). Follow goes through 0148's add path, its provenance kind 'research'.
  6. `papers` (a paper seed): the paper index (research_web.paper_index: OpenAlex, behind its setting) by the exact
     DOI or arXiv id: references (held / not held by every version of their address), citing papers, the authors'
     newer papers (kept only with a shared co-author or field: the index merges namesakes); at most PAPER_CALLS a paper.
  7. `discussion`: the search feeds of platforms INSIGHT reads (Reddit's, the Hacker News class's, X through the
     configured bridge) for the exact id, the project's owner/name, or the exact title; a hit must contain it whole or
     link an address of the seed (research_web.exact_hit). At most DISCUSSION_SEARCHES a run.

**Watch this** (`watch`): a track (0145) made from the run: its description from the seed and the maker, its active
sources the channels followed from the run, the seed's posts in INSIGHT its first ✓ examples.

**Cost guard** (per run): PAGE_REQUESTS page requests, the scout run's 40 test reads and 800 judgements,
PAPER_CALLS paper-index calls a paper, IDENTITY_MAX `identity` questions, WEB_QUERIES web searches,
DISCUSSION_SEARCHES search feeds; all counted on the run (and the log).

Only mx_* tables are written, except the owner's own Follow and Watch this (a source added as Add source adds one; a
track made as Sources makes one).
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from psycopg import Cursor

from insight_core.markx import repo, schemas, scout, tasks
from insight_core.markx import research_web as W

log = logging.getLogger(__name__)

KIND = "identity"
WEB_KIND = "websearch"         # 0171: the web search asked of the worker (Claude Code's web search tool)
SEED_KINDS = ("post", "link", "entity", "name", "question")
PAGE_REQUESTS = 60
PAPER_CALLS = 4               # a paper: its record, its references, its citing papers, its authors' newer papers
IDENTITY_MAX = 20
WEB_QUERIES = 5
DISCUSSION_SEARCHES = 6
HOPS = 2
UNIQUE_MAX = 10               # a link held by more posts than this is no unique link (a common page)
LINKS_MAX = 10                # a pasted post's links resolved
AROUND = timedelta(days=3)
NEAR_DAYS = 30
NEAR_WORDS = 8
QUESTION_ENTITIES = 3
HELD_POSTS = 30
CLAIM = timedelta(minutes=20)
URL_RE = re.compile(r"""https?://[^\s<>"'()\]]+""")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
QUESTION_WORDS = ("who", "what", "which", "where", "when", "why", "how", "is", "are", "does", "do", "can", "find")
SECTIONS = ("held", "same_post", "entity", "account", "paper", "discussion", "unread")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: Any) -> Optional[str]:
    return t.astimezone(timezone.utc).isoformat() if isinstance(t, datetime) else None


# ---- seeds -------------------------------------------------------------------------------------------------------

def seed_kind(seed: str) -> str:
    """What a typed or pasted seed is: an entity id, a link (one address), a pasted post (text with links, or long),
    a question (asks, or 6+ words), else a name."""
    s = (seed or "").strip()
    if UUID_RE.match(s):
        return "entity"
    links = URL_RE.findall(s)
    if links and len(links) == 1 and s == links[0]:
        return "link"
    if links or len(s) > 280 or "\n" in s:
        return "post"
    words = s.split()
    if s.endswith("?") or (words and words[0].lower() in QUESTION_WORDS and len(words) >= 3) or len(words) >= 6:
        return "question"
    return "name"


def seed_links(kind: str, seed: str) -> List[str]:
    if kind == "link":
        return [seed.strip()]
    if kind == "post":
        return list(dict.fromkeys(u.rstrip(".,;:!?") for u in URL_RE.findall(seed)))[:LINKS_MAX]
    return []


# ---- findings ------------------------------------------------------------------------------------------------------

def _earlier_runs(cur: Cursor, run: Dict[str, Any]) -> List[str]:
    cur.execute("""SELECT id::text FROM mx_research_runs WHERE id <> %s AND created_at <= %s
                     AND ((seed_kind = %s AND seed = %s) OR (%s::uuid IS NOT NULL AND entity_id = %s::uuid))""",
                (run["id"], run["created_at"], run["seed_kind"], run["seed"], run.get("entity_id"), run.get("entity_id")))
    return [r for (r,) in cur.fetchall()]


def find(cur: Cursor, run: Dict[str, Any], section: str, key: str, data: Dict[str, Any]) -> None:
    """A finding, once a (section, key) a run: its data replaced when found again; not new when an earlier run of the
    same seed (or entity) found it."""
    earlier = run.setdefault("_earlier", _earlier_runs(cur, run))
    new = True
    if earlier:
        cur.execute("SELECT 1 FROM mx_research_findings WHERE run_id = ANY(%s::uuid[]) AND section = %s AND key = %s LIMIT 1",
                    (earlier, section, key))
        new = cur.fetchone() is None
    cur.execute("""INSERT INTO mx_research_findings (run_id, section, key, data, new) VALUES (%s, %s, %s, %s::jsonb, %s)
                   ON CONFLICT (run_id, section, key) DO UPDATE SET data = EXCLUDED.data, updated_at = now()""",
                (run["id"], section, key, json.dumps(data, default=str), new))


def findings(cur: Cursor, run_id: str, section: Optional[str] = None) -> List[Dict[str, Any]]:
    cur.execute("""SELECT section, key, data, new FROM mx_research_findings WHERE run_id = %s
                     AND (%s::text IS NULL OR section = %s) ORDER BY created_at, key""", (run_id, section, section))
    return [{"section": s, "key": k, "data": d or {}, "new": n} for s, k, d, n in cur.fetchall()]


def _accounts(cur: Cursor, run_id: str) -> Dict[str, Dict[str, Any]]:
    return {f["key"]: f["data"] for f in findings(cur, run_id, "account")}


def _put_account(cur: Cursor, run: Dict[str, Any], key: str, data: Dict[str, Any]) -> None:
    find(cur, run, "account", key, data)


def get_run(cur: Cursor, run_id: str) -> Optional[Dict[str, Any]]:
    cur.execute("""SELECT id::text, seed_kind, seed, entity_id::text, scout_run_id::text, track_id::text, previous_id::text,
                          status, steps, page_requests, paper_calls, search_calls, identity_asked, stats, created_at,
                          finished_at, web_task_id::text
                     FROM mx_research_runs WHERE id = %s""", (run_id,))
    row = cur.fetchone()
    if row is None:
        return None
    cols = ("id", "seed_kind", "seed", "entity_id", "scout_run_id", "track_id", "previous_id", "status", "steps",
            "page_requests", "paper_calls", "search_calls", "identity_asked", "stats", "created_at", "finished_at",
            "web_task_id")
    return dict(zip(cols, row))


def _step_done(cur: Cursor, run: Dict[str, Any], step: str, **stats: Any) -> None:
    run["steps"] = dict(run.get("steps") or {}, **{step: _now().isoformat()})
    cur.execute("UPDATE mx_research_runs SET steps = steps || %s::jsonb, stats = stats || %s::jsonb WHERE id = %s",
                (json.dumps({step: run["steps"][step]}), json.dumps({step: stats} if stats else {}, default=str), run["id"]))


def _spend(cur: Cursor, run: Dict[str, Any], column: str, n: int = 1) -> None:
    cur.execute(f"UPDATE mx_research_runs SET {column} = {column} + %s WHERE id = %s RETURNING {column}", (n, run["id"]))
    run[column] = cur.fetchone()[0]


# ---- step 1: what INSIGHT has ---------------------------------------------------------------------------------------

def _book(cur: Cursor) -> Any:
    from insight_core.markx import identity
    return identity.lazy_book(cur)   # v10.17 (0186): the seed's entities, not the whole book


def resolve_entities(cur: Cursor, book: Any, kind: str, seed: str, links: Sequence[str]) -> Tuple[List[str], Optional[str]]:
    """(the seed's entity roots, a name to propose when none is known)."""
    from insight_core.markx import names as N
    from insight_core.markx import search
    if kind == "entity":
        root = book.root(seed.strip())
        return ([root] if root in book.ents else []), None
    if kind in ("link", "post"):
        exact: List[str] = []
        for link in links:
            exact += W.versions(link)[0]
        if not exact:
            return [], None
        cur.execute("SELECT DISTINCT entity_id::text FROM mx_entity_addresses WHERE url = ANY(%s)", (exact,))
        roots = [book.root(e) for (e,) in cur.fetchall()]
        return list(dict.fromkeys(r for r in roots if r in book.ents)), None
    if kind == "name":
        key = N.key(seed)
        found = book.by_key(key) or book.first_with_key(key)
        root = book.root(found) if found else None
        if root in book.ents:
            return [root], None
        cards = [c for c in search.entity_cards(cur, seed, 5) if N.key(c.get("name")) == key]
        if cards:
            return [book.root(cards[0]["id"]) or cards[0]["id"]], None
        return [], seed.strip()
    cards = search.entity_cards(cur, seed, QUESTION_ENTITIES)      # a question: the entities it names
    return list(dict.fromkeys(book.root(c["id"]) or c["id"] for c in cards))[:QUESTION_ENTITIES], None


def _post_rows(cur: Cursor, ids: Sequence[str]) -> List[Dict[str, Any]]:
    if not ids:
        return []
    cur.execute("""SELECT p.id::text, COALESCE(pp.title, p.title), COALESCE(p.surfaced_at, p.published_at, p.fetched_at),
                          COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url), p.url, s.id::text
                     FROM posts p JOIN sources s ON s.id = p.source_id LEFT JOIN post_parts pp ON pp.post_id = p.id
                    WHERE p.id = ANY(%s::uuid[])""", (list(ids),))
    rows = [{"post_id": i, "title": t, "at": _iso(at), "source": s, "url": u, "source_id": sid}
            for i, t, at, s, u, sid in cur.fetchall()]
    return sorted(rows, key=lambda r: r["at"] or "", reverse=True)


def linking_posts(cur: Cursor, addresses: Iterable[str]) -> Dict[str, List[str]]:
    """{post id: the addresses it links or is}, for every version of each address."""
    exact: List[str] = []
    prefixes: List[str] = []
    for a in addresses:
        e, p = W.versions(a)
        exact += e
        prefixes += p
    if not exact:
        return {}
    out: Dict[str, List[str]] = {}
    cur.execute("SELECT post_id::text, target_url FROM post_links WHERE target_url = ANY(%s) AND NOT boilerplate", (exact,))
    rows = cur.fetchall()
    cur.execute("SELECT id::text, normalized_url FROM posts WHERE normalized_url = ANY(%s)", (exact,))
    rows += cur.fetchall()
    for prefix in prefixes[:5]:
        cur.execute("SELECT post_id::text, target_url FROM post_links WHERE target_url LIKE %s AND NOT boilerplate LIMIT 200",
                    (prefix.replace("%", r"\%").replace("_", r"\_") + "%",))
        rows += cur.fetchall()
    for pid, url in rows:
        out.setdefault(pid, [])
        if url not in out[pid]:
            out[pid].append(url)
    return out


def held(cur: Cursor, run: Dict[str, Any]) -> Dict[str, Any]:
    """Step 1 (no request): the seed's entities, their posts, stories, voices and addresses, the posts linking any
    version of them, and the names that may be one thing with them."""
    from insight_core.markx import entity_addresses as EA
    from insight_core.markx import names as N
    book = _book(cur)
    links = seed_links(run["seed_kind"], run["seed"])
    roots, proposed = resolve_entities(cur, book, run["seed_kind"], run["seed"], links)
    addresses: List[str] = list(links)
    counts = {"entities": len(roots), "posts": 0, "linking": 0}
    for root in roots:
        ids = sorted(set(book.cluster(root)) or {root})
        cur.execute("""SELECT DISTINCT post_id::text FROM mx_mentions_now WHERE entity_id = ANY(%s::uuid[])""", (ids,))
        posts = [p for (p,) in cur.fetchall()]
        rows = EA._current(cur, book, [root]).get(root, [])     # (kind, url, rule, first_at, post_id, owner)
        own = [r[1] for r in rows]
        addresses += own
        cur.execute("""SELECT count(DISTINCT story_id) FROM mx_story_posts WHERE post_id = ANY(%s::uuid[])""", (posts,))
        stories = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT source_id) FROM posts WHERE id = ANY(%s::uuid[])", (posts,))
        voices = cur.fetchone()[0]
        e = book.ents[root]
        find(cur, run, "held", f"entity:{root}", {
            "entity": {"id": root, "name": book.label(root), "type": book.shown_type(root) if hasattr(book, "shown_type") else e.type,
                       "maker": e.maker}, "posts": len(posts), "stories": stories, "voices": voices,
            "addresses": [{"kind": r[0], "url": r[1], "owner": r[5]} for r in rows][:30],
            "newest": _post_rows(cur, posts)[:HELD_POSTS]})
        counts["posts"] += len(posts)
        key = e.key
        for other in book.keys_around(key) if key else ():   # the names that may be one thing with it (offered only)
            oe, r = book.ents[other], book.root(other)
            if r == root or r != other or not oe.key or not key:
                continue
            if oe.key.startswith(key + " ") or key.startswith(oe.key + " "):
                find(cur, run, "entity", f"maybe:{r}", {"id": r, "name": book.label(r), "of": root,
                                                        "why": "its name holds this one's whole"})
    if run["seed_kind"] == "entity" and roots:
        cur.execute("UPDATE mx_research_runs SET entity_id = %s WHERE id = %s", (roots[0], run["id"]))
        run["entity_id"] = roots[0]
    elif roots:
        cur.execute("UPDATE mx_research_runs SET entity_id = %s WHERE id = %s", (roots[0], run["id"]))
        run["entity_id"] = roots[0]
    if proposed:
        find(cur, run, "entity", f"new:{N.key(proposed)}", {"name": proposed, "proposed": True,
                                                           "why": "no entity INSIGHT knows has this name"})
    linking = linking_posts(cur, addresses)
    for row in _post_rows(cur, list(linking))[:HELD_POSTS]:
        find(cur, run, "held", f"post:{row['post_id']}", dict(row, links=linking[row["post_id"]][:5],
                                                              why="links " + linking[row["post_id"]][0]))
    counts["linking"] = len(linking)
    run["_addresses"] = list(dict.fromkeys(addresses))
    cur.execute("UPDATE mx_research_runs SET stats = stats || %s::jsonb WHERE id = %s",
                (json.dumps({"addresses": run["_addresses"][:50]}), run["id"]))
    return counts


def _addresses(run: Dict[str, Any]) -> List[str]:
    return list((run.get("stats") or {}).get("addresses") or run.get("_addresses") or seed_links(run["seed_kind"], run["seed"]))


def _seed_things(cur: Cursor, run: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any], str]]:
    """The seed's things at hop 0: (address, classified, how). A link seed itself; a post's project and paper links; an
    entity's addresses."""
    out: List[Tuple[str, Dict[str, Any], str]] = []
    kind = run["seed_kind"]
    for link in seed_links(kind, run["seed"]):
        got = W.classify(link)
        if kind == "link" and got:
            out.append((link, got, "the seed"))
        elif got and got["kind"] in ("project", "paper"):
            out.append((link, got, "a project the post links"))
    if kind in ("entity", "name", "question") or not out:
        for url in _addresses(run):
            got = W.classify(url)
            if got and got["kind"] in ("project", "paper") and url not in {o[0] for o in out}:
                out.append((url, got, "an address of the entity"))
    return out[:6]


def plant(cur: Cursor, run: Dict[str, Any]) -> int:
    """The identity graph's seeds: the things at hop 0, and the owners their platforms state at hop 1 (no request)."""
    accounts = _accounts(cur, run["id"])
    added = 0
    for url, got, how in _seed_things(cur, run):
        if got["key"] not in accounts:
            _put_account(cur, run, got["key"], dict(got, hop=0, how=how, parent=None, same="seed", rule="the seed",
                                                    read=None))
            accounts[got["key"]] = got
            added += 1
        if got["kind"] == "project" and got.get("owner"):
            owner = W.classify(f"https://{got['key'].split('/', 1)[0]}/{got['owner']}")
            if owner and owner["key"] not in accounts:
                _put_account(cur, run, owner["key"], dict(owner, hop=1, how=f"owns {got['key']} (its platform says so)",
                                                          parent=got["key"], same="yes",
                                                          rule="the platform says this account owns it", read=None))
                accounts[owner["key"]] = owner
                added += 1
    return added


def lean(acc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: acc.get(k) for k in ("key", "kind", "platform", "handle", "owner", "links", "handles", "text", "read")}


# ---- step 2b: the same announcement elsewhere --------------------------------------------------------------------------

async def same_post(cur_factory: Callable, run: Dict[str, Any], http: Any) -> Dict[str, int]:
    """Step 2b: the seed's links resolved (shorteners), the posts holding a unique one, near-copies of a pasted text."""
    from insight_core.utils.post_links import is_home
    links = seed_links(run["seed_kind"], run["seed"])
    resolved: List[str] = []
    for link in links:
        with cur_factory() as cur:
            if run["page_requests"] >= PAGE_REQUESTS:
                find(cur, run, "unread", f"link:{link}", {"url": link, "why": "not resolved: the run's page requests are spent"})
                continue
            _spend(cur, run, "page_requests")
        landed = link
        try:
            _, landed = await http.get_start(link, 32 * 1024)
        except Exception as exc:  # noqa: BLE001 - kept as given
            with cur_factory() as cur:
                find(cur, run, "unread", f"link:{link}", {"url": link, "why": f"could not be read ({type(exc).__name__})"})
        resolved.append(landed or link)
    hits = 0
    with cur_factory() as cur:
        for link in dict.fromkeys(resolved):
            if is_home(link) or (W.classify(link) or {}).get("kind") in ("account", "site", "community"):
                continue
            posts = linking_posts(cur, [link])
            if not posts or len(posts) > UNIQUE_MAX:
                continue
            for row in _post_rows(cur, list(posts)):
                find(cur, run, "same_post", f"post:{row['post_id']}",
                     dict(row, why=f"shares the link {link.split('://', 1)[-1]}", strength="link"))
                hits += 1
        if run["seed_kind"] == "post":
            hits += near_copies(cur, run)
        cur.execute("UPDATE mx_research_runs SET stats = stats || %s::jsonb WHERE id = %s",
                    (json.dumps({"resolved": list(dict.fromkeys(resolved))}), run["id"]))
    return {"links": len(links), "hits": hits}


def near_copies(cur: Cursor, run: Dict[str, Any]) -> int:
    """The posts of the last NEAR_DAYS days whose text is a near-copy of the pasted one (Mark X's copy rule)."""
    text = URL_RE.sub(" ", run["seed"])
    words = [w for w in re.findall(r"[^\W\d_]{6,}", text.casefold())]
    rare = sorted(set(words), key=lambda w: (-len(w), w))[:NEAR_WORDS]
    if len(rare) < 3:
        return 0
    cur.execute("""SELECT id::text FROM posts WHERE search_vector @@ websearch_to_tsquery('russian', %s)
                     AND COALESCE(surfaced_at, published_at, fetched_at) >= %s
                   ORDER BY COALESCE(surfaced_at, published_at, fetched_at) DESC LIMIT 200""",
                (" OR ".join(rare), _now() - timedelta(days=NEAR_DAYS)))
    ids = [r for (r,) in cur.fetchall()]
    seed = tasks.Post(id="seed", kind="site", source="", source_id="", at=_now(), title="", text=text)
    found = 0
    posts = tasks.load_posts(cur, ids)
    hits = [pid for pid, p in posts.items() if tasks.near_copy(seed, tasks.Post(
        id=pid, kind=p.kind, source=p.source, source_id=p.source_id, at=p.at, title="", text=f"{p.title} {p.text}"))]
    for row in _post_rows(cur, hits):
        find(cur, run, "same_post", f"post:{row['post_id']}", dict(row, why="a near-copy of its text", strength="text"))
        found += 1
    return found


def around(cur: Cursor, run: Dict[str, Any]) -> int:
    """The posts of the maker's own channels (followed sources that are a confirmed account) in the days around the
    seed (a pasted post: now; else its newest held post)."""
    confirmed = [a for a in _accounts(cur, run["id"]).values() if a.get("same") in ("seed", "yes")]
    keys = {a["key"] for a in confirmed}
    if not keys:
        return 0
    cur.execute("SELECT id::text, handle_or_url FROM sources")
    mine = []
    for sid, handle in cur.fetchall():
        h = (handle or "").lower().split("://", 1)[-1].removeprefix("www.")
        if any(h == k or h.startswith((k + "/", k + ".", k + "?")) for k in keys):
            mine.append(sid)
    if not mine:
        return 0
    at = _now() if run["seed_kind"] == "post" else run["created_at"]
    cur.execute("""SELECT id::text FROM posts WHERE source_id = ANY(%s::uuid[])
                     AND COALESCE(surfaced_at, published_at, fetched_at) BETWEEN %s AND %s""",
                (mine, at - AROUND, at + AROUND))
    n = 0
    for row in _post_rows(cur, [r for (r,) in cur.fetchall()]):
        find(cur, run, "same_post", f"post:{row['post_id']}",
             dict(row, why="a post of the maker's own channel in the days around it", strength="around"))
        n += 1
    return n


# ---- step 3: the maker and the identity graph ------------------------------------------------------------------------

def _confirmed(accounts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [a for a in accounts.values() if a.get("same") in ("seed", "yes")]


def judge_account(cur: Cursor, run: Dict[str, Any], acc: Dict[str, Any], accounts: Dict[str, Dict[str, Any]], *,
                  ask_allowed: bool = True) -> str:
    """An account's identity against the confirmed ones by the plain rules; unclear: one Haiku question (within
    IDENTITY_MAX), else unsure. Returns its `same`. Without `ask_allowed` (a later look) only the rules may settle it."""
    if acc.get("same") in ("seed", "yes", "no"):
        return acc["same"]
    why = ""
    for c in _confirmed(accounts):
        verdict, why = W.same_identity(lean(c), lean(acc))
        if verdict == "yes":
            acc.update(same="yes", rule=why)
            return "yes"
    if acc.get("same") in ("pending", "unsure") or not ask_allowed:
        return acc.get("same") or "unsure"
    if run["identity_asked"] >= IDENTITY_MAX:
        acc.update(same="unsure", rule=f"not asked: the run's {IDENTITY_MAX} identity questions are spent")
        return "unsure"
    parent = accounts.get(acc.get("parent") or "") or (_confirmed(accounts) or [None])[0]
    if parent is None:
        acc.update(same="unsure", rule="nothing to compare it with")
        return "unsure"
    pair_id, task_id = ask(cur, run, parent, acc)
    acc.update(same="pending", rule=f"asked Haiku ({why})", pair=pair_id)
    return "pending"


def _profile_block(tag: str, a: Dict[str, Any]) -> str:
    lines = [f"{tag}: {a.get('address') or a.get('key')} ({a.get('platform')}, {a.get('kind')})"]
    if not a.get("read"):
        lines.append("  (its page could not be read)")
    for field in ("title", "description"):
        if a.get(field):
            lines.append(f"  {field}: {a[field][:300]}")
    if a.get("links"):
        lines.append("  its links: " + ", ".join(u.split("://", 1)[-1] for u in a["links"][:12]))
    if a.get("text"):
        lines.append("  text: " + re.sub(r"\s+", " ", a["text"])[:600])
    return "\n".join(lines)


def identity_input(a: Dict[str, Any], b: Dict[str, Any], how: str) -> str:
    return "\n".join([_profile_block("A", a), _profile_block("B", b), f"How B was found: {how}"])


def ask(cur: Cursor, run: Dict[str, Any], a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[str, Any]:
    """One `identity` question on the pair (a = the pair's row): (the pair id, the task id)."""
    schemas.ensure_guides(cur)
    cur.execute("""INSERT INTO mx_research_pairs (run_id, a, b, how) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (run_id, a, b) DO UPDATE SET how = EXCLUDED.how RETURNING id::text""",
                (run["id"], a["key"], b["key"], b.get("how")))
    pair_id = cur.fetchone()[0]
    task_id, new = repo.add_task(cur, kind=KIND, guide=schemas.KINDS[KIND].guide, subject_kind="research_pair",
                                 input=identity_input(a, b, b.get("how") or ""), a=pair_id, priority=-1)
    cur.execute("UPDATE mx_research_pairs SET task_id = %s WHERE id = %s", (task_id, pair_id))
    if new:
        _spend(cur, run, "identity_asked")
    else:
        cur.execute("SELECT answer FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at LIMIT 1", (task_id,))
        row = cur.fetchone()
        if row:
            _apply_pair(cur, pair_id, row[0] or {})
    return pair_id, task_id


def _apply_pair(cur: Cursor, pair_id: str, answer: Dict[str, Any]) -> None:
    cur.execute("""UPDATE mx_research_pairs SET same = %s, confidence = %s, why = %s, answered_at = now()
                    WHERE id = %s RETURNING run_id::text, b""",
                (answer.get("same"), float(answer.get("confidence") or 0), (answer.get("why") or "")[:300], pair_id))
    row = cur.fetchone()
    if row is None:
        return
    run_id, key = row
    run = get_run(cur, run_id)
    accounts = _accounts(cur, run_id)
    acc = accounts.get(key)
    if acc is None:
        return
    same = answer.get("same")
    acc.update(same=same if same in ("yes", "no") else "unsure", rule=f"Haiku: {answer.get('why') or same}")
    _put_account(cur, run, key, acc)
    if acc["same"] == "yes":
        _follow_links(cur, run, acc, accounts)
    cur.execute("UPDATE mx_research_runs SET status = 'running' WHERE id = %s AND status = 'waiting'", (run_id,))


def after_identity(cur: Cursor, task: Dict[str, Any], answer: Dict[str, Any]) -> None:
    """tasks.record's part for an `identity` answer: the pair, its account, and its declared links when it is the same."""
    cur.execute("SELECT id::text FROM mx_research_pairs WHERE task_id = %s", (task["id"],))
    for (pair_id,) in cur.fetchall():
        _apply_pair(cur, pair_id, answer)


def _follow_links(cur: Cursor, run: Dict[str, Any], acc: Dict[str, Any], accounts: Dict[str, Dict[str, Any]]) -> int:
    """A confirmed page's declared links as new addresses, one hop further (within HOPS), not read yet."""
    if (acc.get("hop") or 0) >= HOPS:
        return 0
    added = 0
    for url in acc.get("links") or []:
        got = W.classify(url)
        if not got or got["key"] in accounts:
            continue
        data = dict(got, hop=(acc.get("hop") or 0) + 1, how=f"declared by {acc['key']}", parent=acc["key"], same=None,
                    rule=None, read=None)
        _put_account(cur, run, got["key"], data)
        accounts[got["key"]] = data
        added += 1
    return added


async def read_account(http: Any, acc: Dict[str, Any]) -> Dict[str, Any]:
    """An account's or page's own page read once: its title, description, text, declared links and handles."""
    url = W.profile_address(acc)
    try:
        body, landed = await http.get_start(url, W.PAGE_BYTES)
    except Exception as exc:  # noqa: BLE001 - an unreadable page is unread, said so
        status = getattr(exc, "status", None)
        return dict(acc, read=False, read_error=f"HTTP {status}" if status else type(exc).__name__)
    summary = W.page_summary(body, landed or url)
    return dict(acc, read=True, read_error=None, landed=landed, **summary)


async def maker(cur_factory: Callable, run: Dict[str, Any], http: Any) -> Dict[str, int]:
    """Step 3: the identity graph, hop by hop, within the run's page requests (resumable: the next advance goes on)."""
    with cur_factory() as cur:
        plant(cur, run)
    reads = 0
    while True:
        with cur_factory() as cur:
            accounts = _accounts(cur, run["id"])
            for acc in accounts.values():             # a newly confirmed page may settle a pending one by the rules
                if acc.get("read") and acc.get("same") in ("pending", "unsure"):
                    before = acc.get("same")
                    if judge_account(cur, run, acc, accounts, ask_allowed=False) != before:
                        _put_account(cur, run, acc["key"], acc)
                        if acc["same"] == "yes":
                            _follow_links(cur, run, acc, accounts)
            todo = [a for a in sorted(accounts.values(), key=lambda a: (a.get("hop") or 0, a["key"]))
                    if a.get("read") is None and a.get("kind") != "paper" and (a.get("hop") or 0) <= HOPS
                    and (a.get("same") in ("seed", "yes") or (accounts.get(a.get("parent") or "") or {}).get("same")
                         in ("seed", "yes") or (a.get("how") or "").startswith("web search"))]
            if not todo or run["page_requests"] >= PAGE_REQUESTS:
                if todo:
                    for a in todo:
                        find(cur, run, "unread", f"page:{a['key']}", {"url": a.get("address"),
                                                                      "why": "not read: the run's page requests are spent"})
                break
            acc = todo[0]
            _spend(cur, run, "page_requests")
        got = await read_account(http, acc)
        reads += 1
        with cur_factory() as cur:
            accounts = _accounts(cur, run["id"])
            accounts[got["key"]] = got
            if not got["read"]:
                find(cur, run, "unread", f"page:{got['key']}", {"url": got.get("address"), "why": got.get("read_error")})
            judge_account(cur, run, got, accounts)
            got["text"] = (got.get("text") or "")[:1500]
            _put_account(cur, run, got["key"], got)
            if got.get("same") in ("seed", "yes"):
                _follow_links(cur, run, got, accounts)
    return {"pages": reads}


# ---- step 4: web search -------------------------------------------------------------------------------------------------

def maker_names(cur: Cursor, run: Dict[str, Any]) -> List[str]:
    """The names to search the web for: the seed entity's maker (identity's), the confirmed accounts' handles, the
    seed's name."""
    names: List[str] = []
    if run.get("entity_id"):
        book = _book(cur)
        e = book.ents.get(run["entity_id"])
        if e is not None and e.maker:
            names.append(e.maker)
        if e is not None and book.etype(run["entity_id"]) in ("person", "org"):
            names.append(book.label(run["entity_id"]))
    for a in _confirmed(_accounts(cur, run["id"])):
        if a.get("kind") == "account" and a.get("handle"):
            names.append(a["handle"])
    if run["seed_kind"] == "name":
        names.append(run["seed"].strip())
    return list(dict.fromkeys(n for n in names if n and len(W.squash(n)) >= 3))[:2]


async def web(cur_factory: Callable, run: Dict[str, Any], http: Any, provider: Any) -> Dict[str, int]:
    """Step 4: each result of the configured web search an address to read and judge (never an identity by name)."""
    with cur_factory() as cur:
        names = maker_names(cur, run)
    queries = [q for n in names for q in W.web_queries(n, WEB_QUERIES)][:WEB_QUERIES]
    found = 0
    for q in queries:
        with cur_factory() as cur:
            if run["search_calls"] >= WEB_QUERIES + DISCUSSION_SEARCHES:
                break
            _spend(cur, run, "search_calls")
        try:
            results = await provider.search(http, q)
        except Exception as exc:  # noqa: BLE001 - said, never raised
            with cur_factory() as cur:
                find(cur, run, "unread", f"web:{q}", {"query": q, "why": f"the web search failed ({type(exc).__name__})"})
            continue
        with cur_factory() as cur:
            accounts = _accounts(cur, run["id"])
            for r in results[:10]:
                got = W.classify(r.get("url") or "")
                if not got or got["key"] in accounts or got["kind"] not in ("account", "community", "site", "project"):
                    continue
                data = dict(got, hop=HOPS, how=f"web search: {q}", parent=None, same=None, rule=None, read=None,
                            snippet=(r.get("snippet") or "")[:300], result_title=r.get("title"))
                _put_account(cur, run, got["key"], data)
                accounts[got["key"]] = data
                found += 1
    return {"queries": len(queries), "found": found}


# ---- step 4, by the worker (0171): Claude Code's web search on the owner's device ---------------------------------------

def web_budget(run: Dict[str, Any]) -> int:
    """The searches the run may still ask of the web (WEB_QUERIES, within the run's searches with discussion's)."""
    return max(0, min(WEB_QUERIES, WEB_QUERIES + DISCUSSION_SEARCHES - run["search_calls"]))


def _known_for(cur: Cursor, run: Dict[str, Any]) -> str:
    if run.get("entity_id"):
        book = _book(cur)
        if run["entity_id"] in book.ents:
            return f"{book.label(run['entity_id'])} ({book.etype(run['entity_id']) or 'a thing'})"
    seed = re.sub(r"\s+", " ", run["seed"]).strip()
    return seed[:300]


def websearch_input(cur: Cursor, run: Dict[str, Any], names: Sequence[str], budget: int) -> str:
    """The `websearch` question: the maker's names, what it is known for (the seed), the addresses already confirmed
    (to leave out, and to tie results to), the searches allowed. No run id: the same question is one task."""
    confirmed = sorted(a.get("address") or a["key"] for a in _confirmed(_accounts(cur, run["id"]))
                       if a.get("kind") != "paper")
    lines = [f"Maker: {names[0]}"]
    if len(names) > 1:
        lines.append("Also named: " + ", ".join(names[1:]))
    lines.append(f"Known for: {_known_for(cur, run)}")
    lines.append("Confirmed as its own: " + (", ".join(confirmed[:20]) if confirmed else "(none yet)"))
    lines.append(f"Searches allowed: at most {budget}")
    return "\n".join(lines)


def _web_task_answer(cur: Cursor, task_id: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """(the task's status, its first valid answer or None)."""
    cur.execute("SELECT status FROM mx_tasks WHERE id = %s", (task_id,))
    row = cur.fetchone()
    status = row[0] if row else "failed"
    cur.execute("SELECT answer FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at LIMIT 1", (task_id,))
    got = cur.fetchone()
    return status, (got[0] or {}) if got else None


def web_candidates(cur: Cursor, run: Dict[str, Any], answer: Dict[str, Any], names: Sequence[str]) -> int:
    """The worker's candidates as addresses to read and judge (never an identity by its name): each one an identity
    address (classify: an account, a community, a project or a site; never an article or a post), not yet in the run's
    graph. Idempotent (a run sharing an answered task adds them once)."""
    accounts = _accounts(cur, run["id"])
    who = names[0] if names else "the maker"
    found = 0
    for c in (answer.get("candidates") or [])[:schemas.WEBSEARCH_MAX]:
        got = W.classify((c.get("url") or "").strip())
        if not got or got["key"] in accounts or got["kind"] not in ("account", "community", "site", "project"):
            continue
        data = dict(got, hop=HOPS, how=f"web search (the worker's Claude) for {who}", parent=None, same=None, rule=None,
                    read=None, result_title=(c.get("title") or "")[:300], found_why=(c.get("why") or "")[:300])
        _put_account(cur, run, got["key"], data)
        accounts[got["key"]] = data
        found += 1
    return found


def web_by_worker(cur: Cursor, run: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Step 4 asked of the worker: one `websearch` task a run (the same question one task, its answer reused); the
    run's WEB_QUERIES searches spent when it is asked. None while the worker has not answered (the run waits; the next
    advance after the answer goes on); the step's stats once answered (its candidates in the graph) or failed."""
    names = maker_names(cur, run)
    if not run.get("web_task_id"):
        if not names:
            return {"by": "worker", "queries": 0, "found": 0, "why": "no name to search for"}
        budget = web_budget(run)
        if budget <= 0:
            return {"by": "worker", "queries": 0, "found": 0, "why": "the run's searches are spent"}
        schemas.ensure_guides(cur)
        task_id, new = repo.add_task(cur, kind=WEB_KIND, guide=schemas.KINDS[WEB_KIND].guide, subject_kind="research_run",
                                     input=websearch_input(cur, run, names, budget), a=run["id"], priority=-1)
        cur.execute("UPDATE mx_research_runs SET web_task_id = %s WHERE id = %s", (task_id, run["id"]))
        run["web_task_id"] = str(task_id)
        if new:
            _spend(cur, run, "search_calls", budget)
    status, answer = _web_task_answer(cur, run["web_task_id"])
    if answer is not None:
        queries = [q for q in answer.get("queries") or [] if isinstance(q, str)]
        return {"by": "worker", "queries": len(queries), "asked": queries[:WEB_QUERIES],
                "found": web_candidates(cur, run, answer, names)}
    if status in ("open", "leased"):
        return None
    find(cur, run, "unread", "web:worker", {"why": f"the worker's web search gave no valid answer ({status})"})
    return {"by": "worker", "queries": 0, "found": 0, "failed": status}


def after_websearch(cur: Cursor, task: Dict[str, Any], answer: Dict[str, Any]) -> None:
    """tasks.record's part for a `websearch` answer: each run waiting on it may go on (its next advance adds the
    candidates and reads them)."""
    cur.execute("UPDATE mx_research_runs SET status = 'running' WHERE web_task_id = %s AND status = 'waiting'",
                (task["id"],))


def web_waiting(cur: Cursor, run: Dict[str, Any]) -> bool:
    """Whether the run waits for the worker's web search (asked, its step not done, the task still open)."""
    if not run.get("web_task_id") or "web" in (run.get("steps") or {}):
        return False
    cur.execute("SELECT status IN ('open', 'leased') FROM mx_tasks WHERE id = %s", (run["web_task_id"],))
    return bool((cur.fetchone() or (False,))[0])


def web_view(cur: Cursor, run: Dict[str, Any]) -> Dict[str, Any]:
    """0171: which web search the run used (or uses), whether it waits for the worker, what was searched."""
    stats = (run.get("stats") or {}).get("web") or {}
    by = stats.get("by") or ("worker" if run.get("web_task_id") else getattr(W.web_search(), "name", None))
    return {"by": by, "waiting": web_waiting(cur, run), "asked": stats.get("asked") or []}


# ---- step 6: papers ---------------------------------------------------------------------------------------------------

def paper_refs(run: Dict[str, Any], accounts: Dict[str, Dict[str, Any]]) -> List[str]:
    from insight_core.utils.entity_originals import paper_ref
    refs = [paper_ref(u) for u in [*seed_links(run["seed_kind"], run["seed"]), *_addresses(run)]]
    refs += [paper_ref(a.get("address") or "") for a in accounts.values() if a.get("kind") == "paper" and a.get("hop") == 0]
    return list(dict.fromkeys(r for r in refs if r and r.split(":", 1)[0] in ("arXiv", "doi")))[:2]


def held_refs(cur: Cursor, refs: Iterable[Optional[str]]) -> Dict[str, str]:
    """{ref: a post holding it} for each paper ref INSIGHT holds under any version of its address."""
    out: Dict[str, str] = {}
    for ref in dict.fromkeys(r for r in refs if r):
        url = W.ref_url(ref)
        got = linking_posts(cur, [url]) if url else {}
        if got:
            out[ref] = sorted(got)[0]
    return out


async def papers(cur_factory: Callable, run: Dict[str, Any], http: Any, index: Any) -> Dict[str, int]:
    """Step 6: the seed paper's references (held or not), citing papers and its authors' newer papers, by exact ids."""
    with cur_factory() as cur:
        refs = paper_refs(run, _accounts(cur, run["id"]))
    counts = {"papers": 0, "references": 0, "citing": 0, "newer": 0}
    for ref in refs:
        calls = 0

        async def call(fn, *args):
            nonlocal calls
            if calls >= PAPER_CALLS:
                return None
            calls += 1
            with cur_factory() as cur:
                _spend(cur, run, "paper_calls")
            try:
                return await fn(http, *args)
            except Exception as exc:  # noqa: BLE001 - said, never raised
                with cur_factory() as cur:
                    find(cur, run, "unread", f"index:{ref}:{calls}", {"ref": ref, "why": f"the paper index failed ({type(exc).__name__})"})
                return None
        work = await call(index.work, ref)
        if not work:
            with cur_factory() as cur:
                find(cur, run, "unread", f"index:{ref}", {"ref": ref, "why": "the paper index has no paper with this exact id"})
            continue
        counts["papers"] += 1
        seed = W.short_work(work)
        lists = {"reference": await call(index.references, work) or [], "citing": await call(index.citing, work) or [],
                 "newer": await call(index.newer, work) or []}
        with cur_factory() as cur:
            all_refs = [seed["ref"]] + [w["ref"] for ws in lists.values() for w in ws]
            holding = held_refs(cur, all_refs)
            find(cur, run, "paper", f"seed:{seed['ref']}", dict(seed, role="seed", held=holding.get(seed["ref"])))
            for role, ws in lists.items():
                for w in ws:
                    if not w.get("ref"):
                        continue
                    find(cur, run, "paper", f"{role}:{w['ref']}", dict(w, role=role, held=holding.get(w["ref"])))
                    counts["references" if role == "reference" else role] += 1
            for name, aid in zip(seed["authors"], seed["author_ids"]):
                find(cur, run, "account", f"author:{aid}", {"key": f"author:{aid}", "kind": "person", "platform": "paper",
                                                           "name": name, "address": aid, "hop": 1, "same": "yes",
                                                           "rule": "an author of the seed paper (the index's own id)",
                                                           "how": "the paper index", "read": False})
    return counts


# ---- step 7: discussion -----------------------------------------------------------------------------------------------

def discussion_terms(cur: Cursor, run: Dict[str, Any]) -> Tuple[List[str], Optional[str], List[str]]:
    accounts = _accounts(cur, run["id"])
    seeds = [a.get("address") for a in accounts.values() if a.get("hop") == 0 and a.get("address")]
    seeds += seed_links(run["seed_kind"], run["seed"])
    terms = list(dict.fromkeys(t for u in seeds for t in W.id_terms(u)))[:2]
    title = None
    for f in findings(cur, run["id"], "paper"):
        if f["data"].get("role") == "seed":
            title = f["data"].get("title")
    return terms, title, list(dict.fromkeys(seeds))


async def discussion(cur_factory: Callable, run: Dict[str, Any], http: Any) -> Dict[str, int]:
    """Step 7: the platforms' search feeds for the exact id or title; exact hits only."""
    from insight_core.ingestion.kinds import parsing
    with cur_factory() as cur:
        terms, title, addresses = discussion_terms(cur, run)
    queries = [*terms, *([f'"{title}"'] if title and len(title) >= 20 else [])]
    feeds: List[Tuple[str, str]] = []
    bridge = scout._x_bridge()
    for q in queries:
        enc = urllib.parse.quote(q if q.startswith('"') else f'"{q}"')
        feeds.append((q, scout.REDDIT_SEARCH.format(q=enc)))
        feeds.append((q, scout.HN_SEARCH.format(q=urllib.parse.quote(q.strip('"')))))
        if bridge:
            feeds.append((q, f"{bridge}/search/rss?f=tweets&q={enc}"))
    hits = 0
    for q, url in feeds[:DISCUSSION_SEARCHES]:
        with cur_factory() as cur:
            _spend(cur, run, "search_calls")
        try:
            text, _ = await http.get_text(url)
            items = parsing.parse_feed_posts(text, url)
        except Exception as exc:  # noqa: BLE001 - said, never raised
            with cur_factory() as cur:
                find(cur, run, "unread", f"search:{url}", {"url": url, "why": f"the search could not be read ({type(exc).__name__})"})
            continue
        with cur_factory() as cur:
            for it in items[:50]:
                why = W.exact_hit({"title": it.get("title"), "text": it.get("content"), "url": it.get("url"),
                                   "html": it.get("content_html")}, terms=terms, addresses=addresses, title=title)
                if not why or not it.get("url"):
                    continue
                find(cur, run, "discussion", it["url"], {"url": it["url"], "title": it.get("title"),
                                                         "at": _iso(it.get("date")), "query": q, "why": why,
                                                         "where": url.split("/")[2]})
                hits += 1
    return {"searches": min(len(feeds), DISCUSSION_SEARCHES), "hits": hits}


# ---- step 5: channels ---------------------------------------------------------------------------------------------------

def channel_candidates(cur: Cursor, run: Dict[str, Any]) -> int:
    """Every confirmed account, project and site (not a paper, not an author) a candidate of the run's scout run."""
    cands = []
    for a in _confirmed(_accounts(cur, run["id"])):
        if a.get("kind") not in ("account", "project", "site", "community") or not str(a.get("address", "")).startswith("http"):
            continue
        cands.append({"finder": "research", "platform": a.get("platform") or "site", "address": a["address"],
                      "key": a["key"],   # the identity graph's own key: a project and its owner's account are two channels
                      "name": a.get("title") or a.get("handle") or a["key"], "why": a.get("rule"),
                      "evidence": {"account": a["key"], "how": a.get("how")}})
    return scout.add_candidates(cur, run["scout_run_id"], cands, track_id=run.get("track_id"))


# ---- runs ------------------------------------------------------------------------------------------------------------------

def start(cur: Cursor, seed: str, *, kind: Optional[str] = None, previous_id: Optional[str] = None) -> Dict[str, Any]:
    """A research run (the owner's tap): its scout run, step 1 at once (no request). ValueError: an empty seed or an
    unknown entity."""
    seed = (seed or "").strip()
    if not seed:
        raise ValueError("Something to research is needed: a link, a name, a post or a question")
    kind = kind or seed_kind(seed)
    if kind not in SEED_KINDS:
        raise ValueError(f"seed kind: one of {', '.join(SEED_KINDS)}")
    if kind == "entity":
        cur.execute("SELECT 1 FROM mx_entities WHERE id = %s", (seed,))
        if cur.fetchone() is None:
            raise ValueError("No such entity")
    cur.execute("INSERT INTO mx_scout_runs (trigger, status) VALUES ('research', 'running') RETURNING id::text")
    scout_run = cur.fetchone()[0]
    cur.execute("""INSERT INTO mx_research_runs (seed_kind, seed, scout_run_id, previous_id) VALUES (%s, %s, %s, %s)
                   RETURNING id::text""", (kind, seed[:20000], scout_run, previous_id))
    run_id = cur.fetchone()[0]
    cur.execute("UPDATE mx_scout_runs SET research_id = %s WHERE id = %s", (run_id, scout_run))
    run = get_run(cur, run_id)
    counts = held(cur, run)
    _step_done(cur, run, "held", **counts)
    if previous_id:              # a re-run keeps the track "Watch this" made
        cur.execute("SELECT track_id::text FROM mx_research_runs WHERE id = %s", (previous_id,))
        row = cur.fetchone()
        if row and row[0]:
            cur.execute("UPDATE mx_research_runs SET track_id = %s WHERE id = %s", (row[0], run_id))
            cur.execute("UPDATE mx_scout_runs SET track_id = %s WHERE id = %s", (row[0], scout_run))
    log.info("Research run %s (%s): %s", run_id, kind, counts)
    return {"id": run_id, "seed_kind": kind, "held": counts}


def claim(cur: Cursor, run_id: str, now: datetime) -> bool:
    cur.execute("""UPDATE mx_research_runs SET busy_until = %s WHERE id = %s AND status IN ('running', 'waiting')
                     AND (busy_until IS NULL OR busy_until < %s)""", (now + CLAIM, run_id, now))
    return cur.rowcount == 1


def settle(cur: Cursor, run: Dict[str, Any], now: datetime) -> str:
    cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_research_pairs p JOIN mx_tasks t ON t.id = p.task_id
                                   WHERE p.run_id = %s AND t.status IN ('open', 'leased'))""", (run["id"],))
    pairs_open = cur.fetchone()[0] or web_waiting(cur, run)      # 0171: the worker's web search, asked
    cur.execute("SELECT status FROM mx_scout_runs WHERE id = %s", (run["scout_run_id"],))
    scout_status = (cur.fetchone() or ("done",))[0]
    accounts = _accounts(cur, run["id"])
    unread = any(a.get("read") is None and a.get("kind") != "paper" and a.get("same") in ("seed", "yes")
                 for a in accounts.values()) and run["page_requests"] < PAGE_REQUESTS
    status = "running" if unread or scout_status == "running" else \
        "waiting" if pairs_open or scout_status == "waiting" else "done"
    cur.execute("""UPDATE mx_research_runs SET status = %s, busy_until = NULL,
                          finished_at = CASE WHEN %s = 'done' THEN COALESCE(finished_at, %s) ELSE NULL END WHERE id = %s""",
                (status, status, now, run["id"]))
    return status


class Tools:
    """What a run's outside steps use: the http client (the server's fetcher), the scout's reader, the paper index,
    the web search. Tests stub them all."""

    def __init__(self, http: Any = None, reader: Any = None, index: Any = "default", search: Any = "default") -> None:
        self.http, self.reader, self.index, self.search = http, reader, index, search


def default_tools(cur: Cursor) -> Tools:
    from insight_core.ingestion.http import KindHttp
    from insight_core.markx.scout_reads import Counting
    from insight_core.ingestion.gates import HostLimiter
    return Tools(http=Counting(KindHttp(timeout=8), HostLimiter()), reader=scout.default_reader(),
                 index=W.paper_index(cur), search=W.web_search())


async def advance(db_url: str, run_id: str, *, tools: Optional[Tools] = None,
                  now: Optional[Callable[[], datetime]] = None) -> Dict[str, Any]:
    """Advance one run as far as it goes now (claimed first; never raises for a site's failure)."""
    from insight_core.db import database
    clock = now or _now

    def tx():
        return database.transaction(db_url)
    with tx() as cur:
        if not claim(cur, run_id, clock()):
            return {"run": run_id, "claimed": False}
        run = get_run(cur, run_id)
        if tools is None:
            tools = default_tools(cur)
        if tools.index == "default":
            tools.index = W.paper_index(cur)
        if tools.search == "default":
            tools.search = W.web_search()
    steps = dict(run.get("steps") or {})
    out: Dict[str, Any] = {"run": run_id, "claimed": True}
    try:
        if scout.reads_allowed() and tools.http is not None:
            if run["seed_kind"] in ("post", "link") and "same_post" not in steps:
                got = await same_post(tx, run, tools.http)
                with tx() as cur:
                    _step_done(cur, run, "same_post", **got)
            out["maker"] = await maker(tx, run, tools.http)
            if "web" not in steps:
                if getattr(tools.search, "asks_worker", False):       # 0171: the worker's web search, asked
                    with tx() as cur:
                        got = web_by_worker(cur, run)
                    if got is not None and got.get("found"):
                        out["maker"]["web"] = await maker(tx, run, tools.http)
                elif tools.search is not None:
                    got = await web(tx, run, tools.http, tools.search)
                    out["maker"]["web"] = await maker(tx, run, tools.http)
                else:
                    got = {"off": "no web search is configured"}
                if got is not None:
                    with tx() as cur:
                        _step_done(cur, run, "web", **got)
                else:
                    out["web"] = "waiting for the worker's web search"
            if "papers" not in steps:
                got = await papers(tx, run, tools.http, tools.index) if tools.index is not None else {"off": "no paper index"}
                with tx() as cur:
                    _step_done(cur, run, "papers", **got)
            if "discussion" not in steps:
                got = await discussion(tx, run, tools.http)
                with tx() as cur:
                    _step_done(cur, run, "discussion", **got)
        with tx() as cur:
            out["channels"] = channel_candidates(cur, run)
            out["around"] = around(cur, run)
        if scout.reads_allowed():
            out["scout"] = await scout.advance(db_url, run["scout_run_id"], reader=tools.reader, now=now)
    finally:
        with tx() as cur:
            run = get_run(cur, run_id)
            out["status"] = settle(cur, run, clock())
            cur.execute("""UPDATE mx_research_runs SET stats = stats || %s::jsonb WHERE id = %s""",
                        (json.dumps({"spent": {"page_requests": run["page_requests"], "paper_calls": run["paper_calls"],
                                               "search_calls": run["search_calls"],
                                               "identity_asked": run["identity_asked"]}}), run_id))
    log.info("Research run %s: %s", run_id, out)
    return out


async def tick(db_url: str, *, tools: Optional[Tools] = None) -> Dict[str, Any]:
    """insight-ingestion's hook: the runs the owner started (in the last 30 days) that may go on: an identity answer
    came, a page is left, its channels' judgements were answered. A run is never started here."""
    from insight_core.db import database
    from insight_core.markx.api import enabled
    if not enabled():
        return {}
    out = []
    with database.transaction(db_url) as cur:
        cur.execute("""SELECT id::text FROM mx_research_runs WHERE status IN ('running', 'waiting')
                         AND created_at > now() - interval '30 days'
                         AND (busy_until IS NULL OR busy_until < now()) ORDER BY created_at""")
        ids = [r for (r,) in cur.fetchall()]
    for run_id in ids:
        try:
            out.append(await advance(db_url, run_id, tools=tools))
        except Exception:  # noqa: BLE001 - the scheduler's run stands
            log.exception("Research run %s: the tick failed", run_id)
    return {"advanced": out}


# ---- what the owner sees -----------------------------------------------------------------------------------------------

def channels_view(cur: Cursor, run: Dict[str, Any]) -> Dict[str, Any]:
    rows = [scout.row_view(c) for c in scout._candidate_rows(cur, "c.run_id = %s", (run["scout_run_id"],))]
    for r in rows:
        r["fit"] = f"{r['fits']} of {r['judged']} fit" if r["judged"] else None
    readable = [r for r in rows if r["place"] not in ("unreadable", "reads_badly", "unread")]
    readable.sort(key=lambda r: (not r["reads_well"], -(r["precision"] or 0), -(r["per_week"] or 0), r["name"]))
    return {"to_follow": readable, "unread": [r for r in rows if r["place"] == "unread"],
            "cannot": [r for r in rows if r["place"] in ("unreadable", "reads_badly")]}


def view(cur: Cursor, run_id: str) -> Optional[Dict[str, Any]]:
    """The research page: In INSIGHT, the maker, channels to follow, papers, discussion, what could not be read."""
    from insight_core.markx import identity, person_page
    run = get_run(cur, run_id)
    if run is None:
        return None
    got = {s: findings(cur, run_id, s) for s in SECTIONS}
    accounts = [dict(f["data"], new=f["new"]) for f in got["account"]]
    maker = [a for a in accounts if a.get("same") in ("yes", "seed") and a.get("kind") in ("account", "person", "site")]
    pending = [a for a in accounts if a.get("same") in ("pending", "unsure", None) and a.get("read") is not None]
    not_same = [a for a in accounts if a.get("same") == "no"]
    these = None
    if run.get("entity_id"):
        book = identity.lazy_book(cur)   # v10.17 (0186): the run's entity and its maker, not the whole book
        root = book.root(run["entity_id"])
        maker_root = None
        e = book.ents.get(root)
        if e is not None and book.etype(root) in person_page.BY_TYPES:
            maker_root = root
        elif e is not None and e.maker:
            from insight_core.markx import names as N
            found = book.by_key(N.key(e.maker))
            maker_root = book.root(found) if found else None
        if maker_root and maker_root in book.ents:
            by = person_page.by_sources(cur, book, maker_root, set(book.cluster(maker_root)) or {maker_root})
            these = {"entity": {"id": maker_root, "name": book.label(maker_root)}, **by}
    papers = [dict(f["data"], new=f["new"]) for f in got["paper"]]
    pap = {role: [p for p in papers if p.get("role") == role] for role in ("seed", "reference", "citing", "newer")}
    refs = pap["reference"]
    cur.execute("""SELECT count(*) FILTER (WHERE t.status IN ('open', 'leased')), count(*) FROM mx_research_pairs p
                     LEFT JOIN mx_tasks t ON t.id = p.task_id WHERE p.run_id = %s""", (run_id,))
    pairs_open, pairs = cur.fetchone()
    return {
        "run": {"id": run_id, "seed_kind": run["seed_kind"], "seed": run["seed"], "status": run["status"],
                "steps": run["steps"], "entity_id": run.get("entity_id"), "track_id": run.get("track_id"),
                "previous_id": run.get("previous_id"), "created_at": _iso(run["created_at"]),
                "finished_at": _iso(run["finished_at"]),
                "spent": {"page_requests": run["page_requests"], "paper_calls": run["paper_calls"],
                          "search_calls": run["search_calls"], "identity_asked": run["identity_asked"],
                          "identity_open": pairs_open, "identity_pairs": pairs},
                "web_search": web_view(cur, run),
                "budget": {"page_requests": PAGE_REQUESTS, "paper_calls": PAPER_CALLS, "identity": IDENTITY_MAX,
                           "test_reads": scout.MAX_READS, "judgements": scout.MAX_JUDGEMENTS,
                           "web_queries": WEB_QUERIES, "discussion_searches": DISCUSSION_SEARCHES}},
        "held": [dict(f["data"], key=f["key"], new=f["new"]) for f in got["held"]],
        "same_post": [dict(f["data"], new=f["new"]) for f in got["same_post"]],
        "entities": [dict(f["data"], new=f["new"]) for f in got["entity"]],
        "maker": {"accounts": maker, "asking": pending, "not_same": not_same, "these_are": these},
        "channels": channels_view(cur, run),
        "papers": {**pap, "held_references": sum(1 for r in refs if r.get("held")), "references": len(refs)},
        "discussion": [dict(f["data"], new=f["new"]) for f in got["discussion"]],
        "unread": [dict(f["data"], key=f["key"]) for f in got["unread"]],
    }


def runs_of(cur: Cursor, limit: int = 20) -> List[Dict[str, Any]]:
    cur.execute("""SELECT id::text, seed_kind, left(seed, 200), status, created_at FROM mx_research_runs
                    ORDER BY created_at DESC LIMIT %s""", (limit,))
    return [{"id": i, "seed_kind": k, "seed": s, "status": st, "created_at": _iso(at)} for i, k, s, st, at in cur.fetchall()]


# ---- the owner's taps -----------------------------------------------------------------------------------------------------

def follow(cur: Cursor, run_id: str, candidate_id: str, *, add_source: Optional[scout.AddSource] = None) -> Dict[str, Any]:
    """Follow a channel of the run through 0148's add path: active into the run's track when it has one ("Watch
    this"), else passive; its provenance kind 'research'."""
    run = get_run(cur, run_id)
    if run is None:
        raise KeyError(run_id)
    cur.execute("SELECT 1 FROM mx_scout_candidates WHERE id = %s AND run_id = %s", (candidate_id, run["scout_run_id"]))
    if cur.fetchone() is None:
        raise KeyError(candidate_id)
    as_ = "active" if run.get("track_id") else "passive"
    return scout.follow(cur, candidate_id, as_, add_source=add_source, folder_id=run.get("track_id"), kind="research")


def watch(cur: Cursor, run_id: str) -> Dict[str, Any]:
    """"Watch this": a track (0145) from the run: named for the seed, described by it and its maker, its active sources
    the channels followed from the run, the seed's posts in INSIGHT its first ✓."""
    from insight_core.db.repo_folders import FoldersRepository
    from insight_core.markx import tracks
    run = get_run(cur, run_id)
    if run is None:
        raise KeyError(run_id)
    if run.get("track_id"):
        return {"track_id": run["track_id"], "made": False}
    held_rows = findings(cur, run_id, "held")
    entity = next((f["data"]["entity"] for f in held_rows if f["key"].startswith("entity:")), None)
    label = (entity or {}).get("name") or (run["seed"] if run["seed_kind"] in ("name", "question") else None)
    if not label:
        first = W.classify(run["seed"].split()[0]) if run["seed"].split() else None
        label = (first or {}).get("key") or run["seed"][:60]
    makers = [a.get("title") or a.get("handle") for a in _confirmed(_accounts(cur, run_id))
              if a.get("kind") == "account" and (a.get("title") or a.get("handle"))][:2]
    description = (f"{label}: its new releases, papers, code and posts by its makers"
                   + (f" ({', '.join(makers)})" if makers else "") + ", and the discussion of it.")
    folder = FoldersRepository("").create_folder(cur, name=f"{label}"[:80], kind="track")
    tracks.set_topic(cur, folder["id"], description=description, excludes=None)
    cur.execute("UPDATE mx_research_runs SET track_id = %s WHERE id = %s", (folder["id"], run_id))
    cur.execute("UPDATE mx_scout_runs SET track_id = %s WHERE id = %s", (folder["id"], run["scout_run_id"]))
    cur.execute("SELECT source_id::text FROM mx_scout_candidates WHERE run_id = %s AND source_id IS NOT NULL",
                (run["scout_run_id"],))
    for (sid,) in cur.fetchall():
        FoldersRepository("").add_source_to_folder(cur, folder["id"], sid)
        cur.execute("UPDATE mx_source_provenance SET track_id = %s, as_active = true WHERE source_id = %s AND run_id = %s",
                    (folder["id"], sid, run["scout_run_id"]))
    labelled = 0
    for f in held_rows:
        for row in (f["data"].get("newest") or [])[:3] if f["key"].startswith("entity:") else [f["data"]]:
            if row.get("post_id") and labelled < 5:
                tracks.label(cur, folder["id"], post=row["post_id"], answer="in", note="research: the seed's post")
                labelled += 1
    cur.execute("UPDATE mx_research_runs SET status = 'running' WHERE id = %s AND status = 'done'", (run_id,))
    cur.execute("UPDATE mx_scout_runs SET status = 'running', finished_at = NULL WHERE id = %s", (run["scout_run_id"],))
    return {"track_id": folder["id"], "made": True, "examples": labelled}


def rerun(cur: Cursor, run_id: str) -> Dict[str, Any]:
    run = get_run(cur, run_id)
    if run is None:
        raise KeyError(run_id)
    return start(cur, run["seed"], kind=run["seed_kind"], previous_id=run_id)


__all__ = ["advance", "after_identity", "after_websearch", "follow", "held", "rerun", "seed_kind", "start", "tick", "view", "watch"]
