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
            return [{"post_id": pid, "source_id": sid, "t": now, "target": "", "stored": pid, "text": None, "html": None}
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


def _label_story_voices(run: Run):
    """A row's count ("covered by N", story.voices) isn't its names (story.sources, one a voice, issue
    0082): the label and the list beside it disagree."""
    out = [sid for sid, st in run.stories.items() if st["voices"] != len(st.get("sources") or [])]
    return out, len(run.stories)


def _label_news_voices(run: Run):
    """A News row's count (its story's voices) isn't its names (issue 0082)."""
    from insight_core.services.news_service import NewsService
    answer = plain(NewsService(run.db_url, clock=lambda: run.now).news_on(run.cur))
    out = [i["story"]["id"] for i in answer["items"] if i["story"]["voices"] != len(i["story"].get("sources") or [])]
    return out, len(answer["items"])


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
    Invariant("date.after_fetch", "dates", "published more than a day after it was fetched", _date_after_fetch),
    Invariant("date.date_only_first", "dates", "a date-only post marked first over a timed post of its day", _date_only_first),
    Invariant("story.empty", "stories", "a story with no posts", _story_empty),
    Invariant("label.story_voices", "labels", "a row's count isn't its names (one a voice)", _label_story_voices),
    Invariant("label.news_voices", "labels", "a News row's count isn't its names (one a voice)", _label_news_voices),
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
