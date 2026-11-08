"""Rules that hold on every post (issue 0075 B): checks over the whole copy, not a sample.

Each invariant has a name, an area and a line saying what it counts; run, it gives a count, the
number of things it looked at and up to EXAMPLES example ids (written only to the private report).
A count above the baseline (main's count on the same copy) fails the check unless the spec names its
reason (`allowed`).

The rules here are written apart from the rules they check (their own address and label patterns), so
a change to a title rule can't also change what measures it. The services are the pages' own.

Two kinds:
- `INVARIANTS` read the copy only (`Run`);
- `SCRATCH_INVARIANTS` run the story job, so they only ever get a scratch copy (story_identity.py).
"""
from __future__ import annotations

import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from insight_core.checks import compat, derive
from insight_core.checks.paths import plain

EXAMPLES = 5
_ADDRESS = r"(?:https?://\S+|(?:[\w-]+\.)+[a-zA-Z]{2,}/\S*)"
ENDS_IN_ADDRESS_RE = re.compile(rf"(\S+)\s+{_ADDRESS}\s*…?$")
ONLY_LABEL_AND_ADDRESS_RE = re.compile(rf"^\W*[^\W\d_][\w-]*(?: [\w-]+){{0,2}} ?:\s*{_ADDRESS}\s*…?$")
ADDRESS_START_RE = re.compile(rf"^\s*{_ADDRESS}")
# Words an address can be the object of (English and Russian): a title may end on one only with its address.
LEADS = {"on", "at", "by", "to", "in", "from", "of", "for", "with", "via", "into", "onto", "about", "see", "here",
         "quoting", "read", "watch", "try", "visit", "check", "в", "на", "по", "из", "от", "для", "про", "тут", "здесь",
         "читать", "прочёл", "прочел", "смотреть", "ссылка", "подробнее"}


@dataclass
class Found:
    name: str
    area: str
    what: str
    count: int
    of: int
    examples: List[str] = field(default_factory=list)
    seconds: float = 0.0
    note: str = ""


class Run:
    """One copy, read once: every post's Facts, every story as a row carries it, News, on one clock."""

    def __init__(self, db_url: str, cur: Any, now, *, workers: Optional[int] = None, seed: int = 75):
        self.db_url, self.cur, self.now = db_url, cur, now
        self.workers = workers
        self.random = random.Random(seed)
        self._posts: Optional[Dict[str, dict]] = None
        self._stories: Optional[Dict[str, dict]] = None

    @property
    def posts(self) -> Dict[str, dict]:
        if self._posts is None:
            self._posts = derive.all_posts(self.db_url, self.workers)
        return self._posts

    @property
    def stories(self) -> Dict[str, dict]:
        """story id -> the story as the feed row of one of its posts carries it (attach_stories)."""
        if self._stories is None:
            self._stories = all_stories(self.cur)
        return self._stories

    def sample(self, ids: Iterable[str]) -> List[str]:
        ids = sorted(ids)
        return self.random.sample(ids, EXAMPLES) if len(ids) > EXAMPLES else ids


def all_stories(cur: Any, batch: int = 300) -> Dict[str, dict]:
    from insight_core.db.repo_reader import ReaderRepository
    cur.execute("SELECT DISTINCT ON (story_id) story_id::text, post_id::text FROM story_posts ORDER BY story_id, post_id")
    leads = cur.fetchall()
    out: Dict[str, dict] = {}
    for i in range(0, len(leads), batch):
        items = [{"id": pid} for _, pid in leads[i:i + batch]]
        ReaderRepository.attach_stories(cur, items)
        for item in items:
            if item.get("story"):
                out[item["story"]["id"]] = plain({**item["story"], "_item": item["id"]})
    return out


# ---- titles ---------------------------------------------------------------------------------------

def _title_empty(run: Run) -> Tuple[List[str], int]:
    return [i for i, f in run.posts.items() if not f["title"].strip() and f["has_words"]], len(run.posts)


def _title_long(run: Run) -> Tuple[List[str], int]:
    return [i for i, f in run.posts.items() if len(f["title"]) > 300], len(run.posts)


def _title_ends_in_address(run: Run) -> Tuple[List[str], int]:
    out = []
    for i, f in run.posts.items():
        m = ENDS_IN_ADDRESS_RE.search(f["title"])
        if m and not ONLY_LABEL_AND_ADDRESS_RE.match(f["title"]):
            word = m.group(1).rstrip(":→-–—").casefold()
            if word not in LEADS and not m.group(1).endswith((":", "→")):
                out.append(i)
    return out, len(run.posts)


def _title_ends_on_lead(run: Run) -> Tuple[List[str], int]:
    """A title that ends on a word leading to an address the text has right after it (the address went)."""
    out = []
    for i, f in run.posts.items():
        title = f["title"].rstrip(" …")
        words = title.split()
        if not words or not (words[-1].casefold().rstrip(":") in LEADS or title.endswith((":", "→"))):
            continue
        text = " ".join(f["text"].split())
        at = text.casefold().find(" ".join(words).casefold())
        if at >= 0 and ADDRESS_START_RE.match(text[at + len(" ".join(words)):]):
            out.append(i)
    return out, len(run.posts)


def _title_label_address(run: Run) -> Tuple[List[str], int]:
    return [i for i, f in run.posts.items() if ONLY_LABEL_AND_ADDRESS_RE.match(f["title"])], len(run.posts)


def _classics_share(args) -> Tuple[List[str], int]:
    """One chunk of posts, each cited once, titled by the job's own code (NewsService._citations)."""
    db_url, now, pairs = args
    import psycopg
    from insight_core.db.repo_news import NewsRepository
    from insight_core.db.repo_stories import SourceFacts
    from insight_core.services.news_service import NewsService

    class EveryPostCited(NewsRepository):
        def citations(self, cur, **_):
            return [{"post_id": pid, "source_id": sid, "t": now, "target": "", "stored": pid, "text": None, "html": None,
                     "author": None}
                    for pid, sid, _ in pairs]

    with psycopg.connect(db_url, options="-c default_transaction_read_only=on -c jit=off") as conn, conn.cursor() as cur:
        _, stored = NewsService(db_url, repo=EveryPostCited(), clock=lambda: now)._citations(cur, SourceFacts(cur))
    feed = {pid: title for pid, _, title in pairs}
    return [pid for pid, value in stored.items() if (value[2] or "") != feed[pid]], len(stored)


def _classics_stored_titles(run: Run) -> Tuple[List[str], int]:
    """The title the story job stores for a classic that is a stored post (NewsService._citations'
    `stored` map), asked for every post as if each were cited, against the feed's. The citations are
    made here, one per post; the job's own code titles them. Read-only."""
    import multiprocessing
    posts = sorted((pid, f["source_id"], f["title"]) for pid, f in run.posts.items())
    chunks = [(run.db_url, run.now, posts[k:k + 1000]) for k in range(0, len(posts), 1000)]
    with multiprocessing.get_context("spawn").Pool(run.workers or derive.default_workers()) as pool:
        shares = pool.map(_classics_share, chunks)
    return [pid for ids, _ in shares for pid in ids], sum(n for _, n in shares)


def _trees_and_roundups(run: Run) -> Tuple[List[str], int]:
    """A tree's line and a roundup's name read the feed's title (attach_stories)."""
    posts, out, seen = run.posts, set(), 0
    for story in run.stories.values():
        for line in story.get("posts", []) + story.get("roundups", []):
            seen += 1
            if line.get("id") in posts and (line.get("title") or "") != posts[line["id"]]["title"]:
                out.add(line["id"])
    return sorted(out), seen


def _news_lines(run: Run) -> Tuple[List[str], int]:
    from insight_core.services.news_service import NewsService
    posts, out, seen = run.posts, set(), 0
    answer = plain(NewsService(run.db_url, clock=lambda: run.now).news_on(run.cur))
    for item in answer["items"]:
        for line in [item, *item["story"]["posts"]]:
            seen += 1
            if line["id"] in posts and (line.get("title") or "") != posts[line["id"]]["title"]:
                out.add(line["id"])
    return sorted(out), seen


def _discover_articles(run: Run) -> Tuple[List[str], int]:
    """Discover's kept articles (its counts, issue 0067) that are stored posts read the feed's title."""
    run.cur.execute("SELECT value FROM system_settings WHERE key = 'discover_counts'")
    row = run.cur.fetchone()
    articles = [a for s in ((row[0] or {}).get("found", []) if row else []) for a in s.get("articles", [])]
    urls = sorted({a[0] for a in articles})
    run.cur.execute("""SELECT DISTINCT ON (normalized_url) normalized_url, id::text FROM posts
                       WHERE normalized_url = ANY(%s) ORDER BY normalized_url, fetched_at, created_at, id""", (urls,))
    stored = dict(run.cur.fetchall())
    out = {stored[url] for url, _, title in articles if url in stored and stored[url] in run.posts
           and (title or "") != run.posts[stored[url]]["title"]}
    return sorted(out), sum(1 for a in articles if a[0] in stored)


# ---- shown text -----------------------------------------------------------------------------------

def _text_repeats_title(run: Run):
    return [i for i, f in run.posts.items() if f["repeats_title"]], len(run.posts)


def _text_footer(run: Run):
    return [i for i, f in run.posts.items() if f["footer"]], len(run.posts)


def _text_byline(run: Run):
    return [i for i, f in run.posts.items() if f["byline"]], len(run.posts)


def _unreadable(run: Run):
    return [i for i, f in run.posts.items() if f.get("error")], len(run.posts)


# ---- dates ----------------------------------------------------------------------------------------

def _date_after_fetch(run: Run):
    run.cur.execute("SELECT id::text FROM posts WHERE published_at > fetched_at + interval '1 day'")
    ids = [r[0] for r in run.cur.fetchall()]
    run.cur.execute("SELECT count(*) FROM posts WHERE published_at IS NOT NULL")
    return ids, run.cur.fetchone()[0]


# ---- addresses ------------------------------------------------------------------------------------

def _address_unnormalized(run: Run):
    """A post with an http(s) address and no normalized_url (issue 0130 E1: every read matching posts by it misses
    the post). Its own pattern, not the save path's rule."""
    run.cur.execute("SELECT id::text FROM posts WHERE normalized_url IS NULL AND url ~* '^https?://[^/\\s]+'")
    ids = [r[0] for r in run.cur.fetchall()]
    run.cur.execute("SELECT count(*) FROM posts WHERE url ~* '^https?://'")
    return ids, run.cur.fetchone()[0]


def _midnight(t) -> bool:
    t = t.astimezone(timezone.utc)
    return (t.hour, t.minute, t.second, t.microsecond) == (0, 0, 0, 0)


def _date_only_first(run: Run):
    """A story whose post marked first has a date alone (00:00:00 UTC) while one of its posts of that
    same day has a time: the date sorted it first, not the source."""
    run.cur.execute("SELECT sp.story_id::text, p.id::text, p.published_at FROM story_posts sp JOIN posts p ON p.id = sp.post_id "
                    "WHERE p.published_at IS NOT NULL")
    times: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for sid, pid, t in run.cur.fetchall():
        times[sid][pid] = t
    out, seen = [], 0
    for sid, story in run.stories.items():
        first = story.get("first")
        if not first or first not in times[sid]:
            continue
        seen += 1
        t = times[sid][first]
        if _midnight(t) and any(o != first and not _midnight(u) and u.astimezone(timezone.utc).date() == t.astimezone(timezone.utc).date()
                                for o, u in times[sid].items()):
            out.append(sid)
    return out, seen


# ---- stories and labels ---------------------------------------------------------------------------

def _story_empty(run: Run):
    run.cur.execute("SELECT st.id::text FROM stories st WHERE NOT EXISTS (SELECT 1 FROM story_posts sp WHERE sp.story_id = st.id)")
    ids = [r[0] for r in run.cur.fetchall()]
    run.cur.execute("SELECT count(*) FROM stories")
    return ids, run.cur.fetchone()[0]


def _refs_every_link(run: Run, batch: int = 500):
    """A post with an http(s) link of its text (the reader's body_hrefs, made absolute and normalized as internal_links
    does) that has no open post_refs row (issue 0125). A version without post_refs is not measurable."""
    from urllib.parse import urljoin
    from insight_core.utils.post_links import body_hrefs
    from insight_core.utils.url_normalization import normalize_url
    out, of, last = [], 0, None
    while True:
        run.cur.execute("""SELECT p.id, p.url, p.content_html, p.content,
                                  (SELECT array_agg(r.target_address) FROM post_refs r WHERE r.post_id = p.id AND r.valid_to IS NULL)
                           FROM posts p WHERE %(last)s::uuid IS NULL OR p.id > %(last)s::uuid ORDER BY p.id LIMIT %(n)s""",
                        {"last": last, "n": batch})
        rows = run.cur.fetchall()
        if not rows:
            return out, of
        for post_id, url, content_html, content, refs in rows:
            have, missing = set(refs or ()), False
            for href in body_hrefs(content_html, content):
                try:
                    absolute = urljoin(url or "", href)
                    address = normalize_url(absolute) if absolute.lower().startswith(("http://", "https://")) else None
                except ValueError:
                    continue
                if address:
                    missing = missing or address not in have
            of += 1
            if missing:
                out.append(str(post_id))
        last = rows[-1][0]


def _label_story_voices(run: Run):
    """A row's count ("covered by N", story.voices, 2+) isn't its names (story.sources, one a voice, issue
    0082): the label and the list beside it disagree. One voice shows no count ("also shared by")."""
    out = [sid for sid, st in run.stories.items() if st["voices"] >= 2 and st["voices"] != len(st.get("sources") or [])]
    return out, len(run.stories)


def _label_news_voices(run: Run):
    """A News row's count (its story's voices) isn't its names (issue 0082)."""
    from insight_core.services.news_service import NewsService
    answer = plain(NewsService(run.db_url, clock=lambda: run.now).news_on(run.cur))
    out = [i["story"]["id"] for i in answer["items"] if i["story"]["voices"] != len(i["story"].get("sources") or [])]
    return out, len(answer["items"])


# ---- Discover (issue 0080) -------------------------------------------------------------------------
# Its own reading of an address, a slug and a followed host, apart from discover_rules'.
DISCOVER_FIRST_PAGE = 30
DISCOVER_TEST_DAYS = 30
_WHOLE_ADDRESS_RE = re.compile(rf"^\s*{_ADDRESS}\s*…?$")
_SLUG_SPLIT_RE = re.compile(r"[-_+]+")


def _discover(run: Run, first: bool) -> List[Dict[str, Any]]:
    """Discover's suggestions as the service answers: every one, or its first page (a version without
    pages answers every one at once, which is its first page)."""
    memo = run.__dict__.setdefault("_discover_memo", {})
    if first not in memo:
        from insight_core.services.news_service import NewsService
        from insight_core.services.stories_service import StoriesService
        service = StoriesService(run.db_url, clock=lambda: run.now, news=NewsService(run.db_url, clock=lambda: run.now))
        try:
            answer = service.discover(limit=DISCOVER_FIRST_PAGE) if first else service.discover()
        except TypeError:   # before 0080: no pages
            answer = service.discover()
        memo[first] = plain(answer)
    return memo[first].get("suggestions", [])


def _is_address(text: Optional[str]) -> bool:
    return bool(text) and bool(_WHOLE_ADDRESS_RE.match(text))


def _slug_text(url: str) -> Optional[str]:
    """An address's last path segment in title case, as a title rebuilt from it reads."""
    path = re.split(r"[?#]", url.split("://", 1)[-1], maxsplit=1)[0].rstrip("/")
    if "/" not in path:
        return None
    words = [w for w in _SLUG_SPLIT_RE.split(re.sub(r"\.[a-z]{2,5}$", "", path.rsplit("/", 1)[1], flags=re.I)) if w]
    if sum(1 for w in words if w.isalpha()) < 3:
        return None
    text = " ".join(words)
    return text[0].upper() + text[1:]


def _discover_title_address(run: Run):
    lines = [(s["key"], a) for s in _discover(run, False) for a in s.get("articles", [])]
    return sorted({f"{key} {a['url']}" for key, a in lines if _is_address(a.get("title"))}), len(lines)


def _discover_name_address(run: Run):
    """Its names that are an address (the source's feed address: one name for a source is 0080 decision 1)."""
    out, seen = set(), 0
    for s in _discover(run, False):
        for name in [*s.get("voice_names", []), *(n for a in s.get("articles", []) for n in a.get("linked_by", []))]:
            seen += 1
            if _is_address(name):
                out.add(f"{s['key']} {name}")
    return sorted(out), seen


def _discover_title_slug(run: Run):
    lines = [(s["key"], a) for s in _discover(run, False) for a in s.get("articles", [])]
    out = {f"{key} {a['url']}" for key, a in lines
           if a.get("title") and (slug := _slug_text(a["url"])) and a["title"] == slug}
    return sorted(out), len(lines)


def _discover_followed_host(run: Run):
    """A suggestion that is a host one of your sources' own addresses is on (or a host of its site)."""
    run.cur.execute("SELECT handle_or_url FROM sources WHERE handle_or_url ~ '^https?://' AND platform <> 'saved'")
    hosts = {re.sub(r"^www\.", "", h.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].lower()) for (h,) in run.cur.fetchall()}
    hosts = {h for h in hosts if h.count(".") >= 1}
    keys = [s["key"] for s in _discover(run, False) if "/" not in s["key"]]
    out = [k for k in keys if any(k == h or k.endswith("." + h) or h.endswith("." + k) for h in hosts)]
    return sorted(out), len(keys)


def _discover_first_page(run: Run):
    """Over DISCOVER_FIRST_PAGE on the first page, and those that say no reason (no story, classic or source)."""
    page = _discover(run, True)
    over = [s["key"] for s in page[DISCOVER_FIRST_PAGE:]]
    silent = [s["key"] for s in page if not (s.get("origins") or s.get("classics") or s.get("voices"))]
    return sorted(set(over + silent)), len(page)


def _discover_untested(run: Run):
    """A first-page suggestion with no follow test, or one older than DISCOVER_TEST_DAYS."""
    from datetime import datetime
    out = []
    for s in _discover(run, True):
        test = s.get("follow_test") or {}
        try:
            fresh = run.now - datetime.fromisoformat(test["at"]) <= timedelta(days=DISCOVER_TEST_DAYS)
        except (KeyError, TypeError, ValueError):
            fresh = False
        if not fresh:
            out.append(s["key"])
    return sorted(out), len(_discover(run, True))


# ---- Mark X (issue 0086 Safety): the mx_* tables keep their rules on every copy ------------------------
# Invariant 1 (Mark IX's tables the same with Mark X on and off) runs the decision job, so it is a job check
# (job_checks.markx_unchanged). A version before the mx_* tables can't be asked: "not measurable".

def _markx_calls_valid(run: Run):
    """A valid call whose answer its task's checks (markx/validate.py: the guide's schema, then the input's) refuse."""
    from insight_core.markx import validate
    run.cur.execute("""SELECT c.id::text, t.kind, t.input, c.answer, t.guide FROM mx_calls c JOIN mx_tasks t ON t.id = c.task_id
                        WHERE c.valid AND t.kind <> 'embed'""")
    rows = run.cur.fetchall()
    return [cid for cid, kind, text, answer, guide in rows                 # 0133: an entities arm's own schema
            if validate.check(kind, answer, text, guide)[1] is not None], len(rows)


def _markx_unnamed(run: Run):
    """A current membership or connection that names neither a rule nor a valid call (memberships: `rule:` reasons)."""
    run.cur.execute("""SELECT sp.story_id::text || ' ' || sp.post_id::text FROM mx_story_posts sp
                         LEFT JOIN mx_calls c ON c.id = sp.call_id
                        WHERE sp.valid_to IS NULL AND sp.reason NOT LIKE 'rule:%' AND NOT COALESCE(c.valid, false)""")
    out = [r[0] for r in run.cur.fetchall()]
    run.cur.execute("""SELECT x.a::text || ' ' || x.relation || ' ' || x.b::text FROM mx_connections x
                         LEFT JOIN mx_calls c ON c.id = x.call_id
                        WHERE x.valid_to IS NULL AND x.rule IS NULL AND NOT COALESCE(c.valid, false)""")
    out += [r[0] for r in run.cur.fetchall()]
    run.cur.execute("SELECT (SELECT count(*) FROM mx_story_posts WHERE valid_to IS NULL) "
                    "+ (SELECT count(*) FROM mx_connections WHERE valid_to IS NULL)")
    return out, run.cur.fetchone()[0]


def _markx_task_twice(run: Run):
    """Two tasks with one (kind, guide, input hash): one question asked twice."""
    run.cur.execute("""SELECT kind || ' ' || guide || ' ' || input_hash FROM mx_tasks
                        GROUP BY kind, guide, input_hash HAVING count(*) > 1""")
    out = [r[0] for r in run.cur.fetchall()]
    run.cur.execute("SELECT count(*) FROM mx_tasks")
    return out, run.cur.fetchone()[0]


def _markx_lease_past(run: Run):
    """A task still leased after its lease ended (by the database's clock: leases are real time)."""
    run.cur.execute("SELECT id::text FROM mx_tasks WHERE status = 'leased' AND lease_until < now()")
    out = [r[0] for r in run.cur.fetchall()]
    run.cur.execute("SELECT count(*) FROM mx_tasks WHERE status = 'leased'")
    return out, run.cur.fetchone()[0]


def _markx_check_empty_story(run: Run):
    """A check task still to be asked (open or leased) whose input shows its story with no member (0112 bug 2). v10.0's
    answered ones stay as they were (keep everything); no decision reads them again (0112 Decided 6)."""
    run.cur.execute("SELECT id::text, input FROM mx_tasks WHERE kind = 'check' AND status IN ('open', 'leased')")
    rows = run.cur.fetchall()
    return sorted(tid for tid, text in rows if _shows_empty_story(text)), len(rows)


def _shows_empty_story(text: str) -> bool:
    """markx.tasks.shows_empty_story, here too: the checks package runs on every version's code, and v10.0's has none."""
    return "\nMembers (earliest first):\n" not in text.split("\n\nPOST\n", 1)[0] + "\n"


# ---- Mark X entities (issue 0119 A1): identity's rules on every copy -----------------------------------------

def _mx_redirects(run: Run) -> Dict[str, Tuple[str, bool, str]]:
    run.cur.execute("SELECT from_id::text, to_id::text, automatic, id::text FROM mx_entity_redirects WHERE undone_at IS NULL")
    return {f: (t, auto, rid) for f, t, auto, rid in run.cur.fetchall()}


def _series_source(run: Run):
    """0134: a series part that is not a post of the series' source. A version without series is not measurable."""
    run.cur.execute("""SELECT s.id::text, sp.post_id::text, p.source_id = s.source_id
                         FROM series_posts sp JOIN series s ON s.id = sp.series_id JOIN posts p ON p.id = sp.post_id""")
    rows = run.cur.fetchall()
    return [f"{sid} {pid}" for sid, pid, ok in rows if not ok], len(rows)


def _markx_author_links(run: Run):
    """0131: a current author-link edge (author_link_other, author_link_own) whose post_refs row is gone, closed or
    boilerplate, or no longer resolves to its older post (Connected's resolution: the post at that exact url, else the
    first seen at its normalized address)."""
    from insight_core.markx import graph
    run.cur.execute("""SELECT x.a::text, x.b::text, x.relation, p.url, r.href, r.target_address,
                              r.valid_to IS NULL AND NOT r.boilerplate
                         FROM mx_connections x JOIN posts p ON p.id = x.a
                         LEFT JOIN post_refs r ON r.post_id = x.a AND md5(r.target_address) = md5(x.evidence->>'address')
                                              AND r.target_address = x.evidence->>'address'
                        WHERE x.valid_to IS NULL AND x.a_kind = 'post' AND x.b_kind = 'post' AND x.rule = ANY(%s)""",
                    (list(graph.LINK_RULES),))
    rows = run.cur.fetchall()
    kept = [r for r in rows if r[4] is not None and r[6]]
    got = graph.resolve(run.cur, [(a, graph._absolute(url, href), address) for a, _b, _rel, url, href, address, _ok in kept])
    good = {(r[0], r[1]) for r, t in zip(kept, got) if t is not None and t[0] == r[1]}
    return [f"{a} {rel} {b}" for a, b, rel, *_ in rows if (a, b) not in good], len(rows)


def _markx_entity_dangling(run: Run):
    """A mention whose entity_id names no entity (a redirect's end that names none counts too)."""
    run.cur.execute("""SELECT m.post_id::text || ' ' || m.n FROM mx_mentions m LEFT JOIN mx_entities e ON e.id = m.entity_id
                        WHERE m.entity_id IS NOT NULL AND e.id IS NULL""")
    out = [r[0] for r in run.cur.fetchall()]
    run.cur.execute("""SELECT r.id::text FROM mx_entity_redirects r LEFT JOIN mx_entities e ON e.id = r.to_id
                        WHERE r.undone_at IS NULL AND e.id IS NULL""")
    out += [r[0] for r in run.cur.fetchall()]
    run.cur.execute("SELECT count(*) FROM mx_mentions WHERE entity_id IS NOT NULL")
    return out, run.cur.fetchone()[0]


def _markx_entity_redirect_loop(run: Run):
    """A current redirect chain that comes back to where it started."""
    red = _mx_redirects(run)
    out = []
    for start in red:
        seen, x = {start}, red[start][0]
        while x in red:
            if x in seen:
                out.append(red[start][2])
                break
            seen.add(x)
            x = red[x][0]
    return out, len(red)


def _markx_entity_cross_version(run: Run):
    """An automatic merge joining two different parsed versions or variants (both state one, and they differ)."""
    from insight_core.markx import names as N
    run.cur.execute("""SELECT r.id::text, a.name, a.type, a.maker, b.name, b.type, b.maker FROM mx_entity_redirects r
                         JOIN mx_entities a ON a.id = r.from_id JOIN mx_entities b ON b.id = r.to_id
                        WHERE r.automatic AND r.undone_at IS NULL""")
    rows = run.cur.fetchall()
    out = []
    for rid, an, at, am, bn, bt, bm in rows:
        va = N.version_part(N.fields_key(N.parse(an, at, am), am))
        vb = N.version_part(N.fields_key(N.parse(bn, bt, bm), bm))
        if any(x is not None and y is not None and not (N.ver_eq(x, y) if i == 0 else x == y)
               for i, (x, y) in enumerate(zip(va, vb))):
            out.append(rid)
    return out, len(rows)


def _markx_entity_big_cluster(run: Run):
    """An entity holding more than 10 names through automatic merges."""
    red = _mx_redirects(run)

    def root(x):
        seen = set()
        while x in red and x not in seen and red[x][1]:
            seen.add(x)
            x = red[x][0]
        return x
    size: Dict[str, int] = defaultdict(int)
    for f, (_t, auto, _rid) in red.items():
        if auto:
            size[root(f)] += 1
    return sorted(e for e, n in size.items() if n > 10), len(size)


# ---- voices (issue 0132 A) -------------------------------------------------------------------------

def _voice_one_per_source(run: Run):
    """A source in more than one voice, or in one that is no live voice (removed, never confirmed or gone): every
    source has at most one voice (sources.voice_id holds one; its voice must be one the owner keeps)."""
    run.cur.execute("""SELECT s.id::text FROM sources s LEFT JOIN voices v ON v.id = s.voice_id
                        WHERE s.voice_id IS NOT NULL AND (v.id IS NULL OR v.removed_at IS NOT NULL OR v.confirmed_at IS NULL)""")
    out = [r[0] for r in run.cur.fetchall()]
    run.cur.execute("SELECT count(*) FROM sources")
    return out, run.cur.fetchone()[0]


@dataclass
class Invariant:
    name: str
    area: str
    what: str
    count: Callable[[Run], Tuple[List[str], int]]


INVARIANTS: List[Invariant] = [
    Invariant("title.empty_with_words", "titles", "empty where the post has words", _title_empty),
    Invariant("title.over_300", "titles", "longer than 300 characters", _title_long),
    Invariant("title.ends_in_address", "titles", "ending in an address its words don't lead to", _title_ends_in_address),
    Invariant("title.ends_on_lead_word", "titles", "ending on a word that led to an address (the address went)", _title_ends_on_lead),
    Invariant("title.label_and_address", "titles", "nothing but a label and an address", _title_label_address),
    Invariant("title.places.classics_stored", "titles", "Classics' stored title of a stored post differs from the feed's (every post, as the job titles it)", _classics_stored_titles),
    Invariant("title.places.trees_roundups", "titles", "a tree's line or a roundup's name differs from the feed's", _trees_and_roundups),
    Invariant("title.places.news", "titles", "a News row or line differs from the feed's", _news_lines),
    Invariant("title.places.discover", "titles", "Discover's article (a stored post) differs from the feed's", _discover_articles),
    Invariant("text.repeats_title", "shown text", "the shown text opens with its title again", _text_repeats_title),
    Invariant("text.feed_footer", "shown text", "keeps a feed's footer lines (Reddit, hnrss, Nitter)", _text_footer),
    Invariant("text.quote_byline", "shown text", "keeps a quote card's byline", _text_byline),
    Invariant("post.unreadable", "shown text", "a post the title or text rules raise on", _unreadable),
    Invariant("post.address_unnormalized", "addresses", "an http(s) address with no normalized_url (0130 E1)",
              _address_unnormalized),
    Invariant("date.after_fetch", "dates", "published more than a day after it was fetched", _date_after_fetch),
    Invariant("date.date_only_first", "dates", "a date-only post marked first over a timed post of its day", _date_only_first),
    Invariant("story.empty", "stories", "a story with no posts", _story_empty),
    Invariant("refs.every_link", "connected", "a post with a link of its text that has no post_refs row (0125)",
              _refs_every_link),
    Invariant("series.source_posts", "series", "a series part that is not a post of the series' source (0134)",
              _series_source),
    Invariant("label.story_voices", "labels", "a row's count isn't its names (one a voice)", _label_story_voices),
    Invariant("label.news_voices", "labels", "a News row's count isn't its names (one a voice)", _label_news_voices),
    Invariant("discover.title_address", "discover", "an article line's title is an address", _discover_title_address),
    Invariant("discover.name_address", "discover", "a source or voice name is an address (one name for a source: 0080 decision 1)", _discover_name_address),
    Invariant("discover.title_slug", "discover", "an article line's title is its address's slug in title case", _discover_title_slug),
    Invariant("discover.followed_host", "discover", "a suggestion is a host one of your sources is on", _discover_followed_host),
    Invariant("discover.first_page", "discover", "the first page holds over 30, or one that says no reason", _discover_first_page),
    Invariant("discover.untested", "discover", "a first-page suggestion with no follow test in 30 days", _discover_untested),
    Invariant("markx.call_invalid", "mark x", "a valid call its guide's schema and checks refuse (0086 Safety 2)", _markx_calls_valid),
    Invariant("markx.unnamed", "mark x", "a current membership or connection naming no rule nor valid call (Safety 3)", _markx_unnamed),
    Invariant("markx.task_twice", "mark x", "two tasks of one kind, guide and input hash (Safety 4)", _markx_task_twice),
    Invariant("markx.lease_past", "mark x", "a task still leased past its lease (Safety 5)", _markx_lease_past),
    Invariant("markx.check_empty_story", "mark x", "a check still to be asked that shows its story with no member (0112)",
              _markx_check_empty_story),
    Invariant("markx.author_link_resolves", "mark x",
              "a current author-link edge whose post_refs row is gone or no longer resolves to its older post (0131)",
              _markx_author_links),
    Invariant("markx.entity_dangling", "mark x", "a mention's entity, or a redirect's end, that is no entity (0119)",
              _markx_entity_dangling),
    Invariant("markx.entity_redirect_loop", "mark x", "a redirect chain that loops (0119)", _markx_entity_redirect_loop),
    Invariant("markx.entity_cross_version", "mark x",
              "an automatic merge of two different parsed versions or variants (0119)", _markx_entity_cross_version),
    Invariant("voice.one_per_source", "voices", "a source in more than one voice, or in a voice not kept (0132 A)",
              _voice_one_per_source),
    Invariant("markx.entity_big_cluster", "mark x", "an entity holding more than 10 names from automatic merges (0119)",
              _markx_entity_big_cluster),
]


def run_all(run: Run, only: Optional[List[str]] = None) -> List[Found]:
    out = []
    for inv in INVARIANTS:
        if only and inv.name not in only:
            continue
        started = time.monotonic()
        try:
            ids, of = inv.count(run)
            found = Found(inv.name, inv.area, inv.what, len(ids), of, run.sample(ids))
        except Exception as e:  # noqa: BLE001 - a version that can't be asked says so; the others still run
            run.cur.connection.rollback() if not run.cur.connection.autocommit else None
            found = Found(inv.name, inv.area, inv.what, -1, 0, note=f"not measurable: {type(e).__name__}: {e}")
        found.seconds = round(time.monotonic() - started, 1)
        out.append(found)
    return out


def compare(found: List[Found], baseline: Dict[str, int], allowed: Dict[str, str]) -> List[str]:
    """The invariants whose count rose above the baseline without a reason the spec names."""
    out = []
    for f in found:
        base = baseline.get(f.name)
        if base is None or f.count < 0 or base < 0:
            continue
        if f.count > base and f.name not in allowed:
            out.append(f"{f.name}: {base} -> {f.count}")
    return out
