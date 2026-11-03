"""What a page shows, asked of the services the pages call (issue 0075: not SQL written again).

Each surface answers one assertion's selector with a JSON-shaped value its `path` reads:

| on | selector | answers | the page |
|---|---|---|---|
| post | post: ref | PostDetailService.get_post_by_id | the post page |
| feed | scope?, filter?, limit?, days? | ReaderService.list_posts (one page, newest first) | the feed |
| row | post: ref | the feed row's `story` (ReaderRepository.attach_stories) as `{"story": …}` | a feed row |
| news | post: ref (a post of the row), scope? | the News item holding it (NewsService.news_on), else None | News |
| origin | origin: url | the story whose outside origin is the page, as a row carries it | a tree's origin line |
| search | query, filter?, days?, order?, limit? | ReaderService.search | search |
| discover | key? | StoriesService.discover (the suggestion with that key, else the whole answer) | Discover |
| classic | url | the Classic at that address (NewsService.classics_on), else None | Classics |
| stories | together / apart: [refs], via? | the story tables after the story job (no service reads them whole) | trees |

The services read the clock: a check of a static copy passes the copy's own "now" (`Context.now`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from insight_core.checks import compat, refs
from insight_core.checks.paths import plain


class Context:
    """One copy's services on one clock, and what they answered, so a page asked twice is built once."""

    def __init__(self, db_url: str, now: datetime, cur: Any):
        self.db_url = db_url
        self.now = now
        self.cur = cur
        self.refs: Dict[str, List[str]] = {}
        self._memo: Dict[Any, Any] = {}

    def clock(self) -> datetime:
        return self.now

    def memo(self, key: Any, build: Callable[[], Any]) -> Any:
        if key not in self._memo:
            self._memo[key] = build()
        return self._memo[key]

    def ids(self, ref: refs.Ref) -> List[str]:
        return refs.resolve(self.cur, ref, self.refs)

    def one(self, ref: refs.Ref) -> str:
        return self.ids(ref)[0]


def _post(ctx: Context, a: Dict[str, Any]) -> Any:
    from insight_core.services.post_detail_service import PostDetailService
    pid = ctx.one(a["post"])
    return ctx.memo(("post", pid), lambda: plain(PostDetailService(ctx.db_url).get_post_by_id(pid)))


def _feed(ctx: Context, a: Dict[str, Any]) -> Any:
    from insight_core.db.repo_reader import FeedQuery
    from insight_core.services.reader_service import ReaderService
    ask = {k: a[k] for k in ("scope", "filter", "limit", "days") if k in a}
    key = ("feed", tuple(sorted(ask.items())))
    return ctx.memo(key, lambda: plain(ReaderService(ctx.db_url, clock=ctx.clock).list_posts(FeedQuery.parse(**ask))))


def _row(ctx: Context, a: Dict[str, Any]) -> Any:
    from insight_core.db.repo_reader import ReaderRepository
    pid = ctx.one(a["post"])

    def build():
        item: Dict[str, Any] = {"id": pid}
        ReaderRepository.attach_stories(ctx.cur, [item])
        return plain(item)
    return ctx.memo(("row", pid), build)


def news_answer(ctx: Context, scope: Optional[str] = None) -> Dict[str, Any]:
    from insight_core.services.news_service import NewsService
    return ctx.memo(("news", scope), lambda: plain(NewsService(ctx.db_url, clock=ctx.clock).news_on(ctx.cur, scope)))


def _news(ctx: Context, a: Dict[str, Any]) -> Any:
    ids = set(ctx.ids(a["post"]))
    ctx.cur.execute("SELECT DISTINCT news_id FROM news_posts WHERE post_id = ANY(%s::uuid[])", (list(ids),))
    held = {str(r[0]) for r in ctx.cur.fetchall()}
    for item in news_answer(ctx, a.get("scope"))["items"]:
        story = item.get("story") or {}
        if story.get("id") in held or item["id"] in ids or ids & {p.get("id") for p in story.get("posts", [])}:
            return item
    return None


def _origin(ctx: Context, a: Dict[str, Any]) -> Any:
    from insight_core.db.repo_reader import ReaderRepository
    url = compat.normalize(a["origin"])
    ctx.cur.execute("""SELECT sp.post_id FROM stories st JOIN story_posts sp ON sp.story_id = st.id
                       WHERE st.origin_url = %s ORDER BY st.voices DESC, st.first_at, st.id, sp.post_id LIMIT 1""", (url,))
    row = ctx.cur.fetchone()
    if row is None:
        return None
    item: Dict[str, Any] = {"id": str(row[0])}
    ReaderRepository.attach_stories(ctx.cur, [item])
    return plain(item.get("story"))


def _search(ctx: Context, a: Dict[str, Any]) -> Any:
    from insight_core.db.repo_search import SearchQuery
    from insight_core.services.reader_service import ReaderService
    ask = {k: a[k] for k in ("query", "scope", "filter", "days", "order", "limit") if k in a}
    ask["q"] = ask.pop("query")
    key = ("search", tuple(sorted(ask.items())))
    return ctx.memo(key, lambda: plain(ReaderService(ctx.db_url, clock=ctx.clock).search(SearchQuery.parse(**ask))))


def discover_answer(ctx: Context) -> Dict[str, Any]:
    from insight_core.services.news_service import NewsService
    from insight_core.services.stories_service import StoriesService

    def build():
        news = NewsService(ctx.db_url, clock=ctx.clock)
        return plain(StoriesService(ctx.db_url, clock=ctx.clock, news=news).discover())
    return ctx.memo("discover", build)


def _discover(ctx: Context, a: Dict[str, Any]) -> Any:
    answer = discover_answer(ctx)
    if "key" not in a:
        return answer
    for rank, s in enumerate(answer.get("suggestions", []), 1):
        if s.get("key") == a["key"]:
            return {**s, "rank": rank}
    return None


def classics_answer(ctx: Context, scope: Optional[str] = None) -> Dict[str, Any]:
    from insight_core.services.news_service import NewsService
    return ctx.memo(("classics", scope), lambda: plain(NewsService(ctx.db_url, clock=ctx.clock).classics_on(ctx.cur, scope)))


def _classic(ctx: Context, a: Dict[str, Any]) -> Any:
    url = compat.normalize(a["url"])
    for rank, c in enumerate(classics_answer(ctx, a.get("scope")).get("classics", []), 1):
        if compat.normalize(c.get("url") or "") == url:
            return {**c, "rank": rank}
    return None


def story_sets(ctx: Context, ids: List[str]) -> Dict[str, set]:
    """post id -> the stories it is in (story_posts), and, under "mentions", those it is a roundup of."""
    ctx.cur.execute("SELECT post_id, story_id FROM story_posts WHERE post_id = ANY(%s::uuid[])", (ids,))
    out: Dict[str, set] = {i: set() for i in ids}
    for pid, sid in ctx.cur.fetchall():
        out[str(pid)].add(str(sid))
    return out


SURFACES: Dict[str, Callable[[Context, Dict[str, Any]], Any]] = {
    "post": _post, "row": _row, "feed": _feed, "news": _news, "origin": _origin, "search": _search,
    "discover": _discover, "classic": _classic,
}
