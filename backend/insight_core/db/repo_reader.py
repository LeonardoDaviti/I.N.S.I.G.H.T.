"""Reader repository: the one post listing, read state, bounded mark-through, unread counts.

Every post list the reader shows (the feed, a source, a track, one day) is `list_posts` with a
`FeedQuery`: scope, read-state filter, an optional time bound (the last N days or one day),
a keyset cursor and a view (a stream, or one group per source).

Read state lives in the `post_reader_state` projection (0020). `post_interactions` stays the
audit log; a list query cannot aggregate it per row cheaply.

Every feed is ordered by the sort key `(COALESCE(surfaced_at, published_at, fetched_at), id)`
descending, which `posts_feed_order_idx` / `posts_source_feed_order_idx` serve directly (no Sort
node). surfaced_at (0037, issue 0039) is set only for a page that was new to you long after its
date, or a watched page that changed: it sorts at when it reached you, every other post as before;
the Later list (issue 0022) instead by when each post was saved, oldest first; History (issue
0052) by when you last opened or read each post, newest first, from the interaction log.
"Unread" means no read_at, over every post the source ever gave us: an archived post from
2015 is as unread as this morning's. INSIGHT_UNREAD_WINDOW_DAYS=N narrows unread (and the
grouped "all" view) back to the last N days; unset or 0 means no window.

One story, many sources (issue 0050): the Main feed and a track (the stream, Show unread or all)
show a story once, at its lead: its first report among the posts the view shows, else its first
share. The lead carries `story` (who covered it and its other posts). A source's own view, the
by-source view, Later and Kept show every post; search folds at the best-matching post (0056). The Main feed's and a track's unread
counts count rows; marking a story's lead read marks its shares read too.
"""
from __future__ import annotations

import base64
import binascii
import math
import re
import uuid
from functools import lru_cache
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

from psycopg import Cursor

from insight_core.db.repo_stories import source_account
from insight_core.utils.content_fingerprints import clean_text
from insight_core.utils.env import env_int
from insight_core.utils.json_safe import iso
from insight_core.utils.media import feed_thumb
from insight_core.utils.addresses import x_account
from insight_core.utils.post_links import source_kind
from insight_core.utils.story_rules import named_voices, text_key
from insight_core.db.repo_post_parts import shown_title
from insight_core.utils.post_fields import SAVED_KEY, STORY_ONLY_KEY, TITLE_TEXT_CHARS

FeedFilter = Literal["all", "unread", "later", "starred", "updated", "history"]   # starred is Keep ("Kept")
FeedView = Literal["stream", "by_source"]
FEED_FILTERS: Tuple[str, ...] = ("all", "unread", "later", "starred", "updated", "history")
FEED_VIEWS: Tuple[str, ...] = ("stream", "by_source")
SCOPE_KINDS: Tuple[str, ...] = ("all", "folder", "source")

MAX_FEED_LIMIT = 100
MAX_FEED_GROUPS = 50
DEFAULT_UNREAD_WINDOW_DAYS: Optional[int] = None   # no window: unread is all-time
EXCERPT_CHARS = 280
CHARS_PER_READING_MINUTE = 1100  # about 200 words a minute

SORT_KEY = "COALESCE(p.surfaced_at, p.published_at, p.fetched_at)"
# "Unread" as an anti-join, not `rs.read_at IS NULL` on the LEFT JOIN: the planner
# estimates a null-extended LEFT JOIN column at ~0 rows, gives up on the LIMIT, and
# seq-scans + sorts posts. The anti-join keeps the posts_feed_order_idx Index Scan.
UNREAD_SQL = (
    "NOT EXISTS (SELECT 1 FROM post_reader_state r WHERE r.post_id = p.id AND r.read_at IS NOT NULL)"
)
# A Telegram album's picture (issue 0069) is no row and no unread count: its post shows it.
# A post that is part of another (issue 0069: a Telegram album's piece; issue 0076: a tweet with nothing of
# its own that quotes its own account's tweet, stored, folds into it) is no row of its own on any page.
NOT_ALBUM_PIECE = ("p.album_of IS NULL AND NOT EXISTS (SELECT 1 FROM post_parts f JOIN posts q ON q.normalized_url = f.folds_into "
                   "WHERE f.post_id = p.id)")
# A page Collect originals stored (issue 0126) is shown only inside its story: no row of a feed (the Main feed,
# a track, a source's list) and no unread count. Later, Kept and History list it when you put it there.
NOT_STORY_ONLY = f"NOT (p.metadata ? '{STORY_ONLY_KEY}')"
_YOURS_FILTERS = ("later", "starred", "history")
# A post's length in minutes: the reading estimate, or a video's duration.
MINUTES_SQL = (
    "CASE WHEN s.platform = 'youtube' THEN CASE WHEN p.metadata->>'duration_seconds' ~ '^[0-9]+([.][0-9]+)?$'"
    " THEN ceil((p.metadata->>'duration_seconds')::numeric / 60) ELSE 0 END"
    f" ELSE ceil(COALESCE(length(p.content), 0)::numeric / {CHARS_PER_READING_MINUTE}) END"
)
# History (issue 0052): what you opened or read, never what "mark read" cleared in bulk.
HISTORY_SQL = (
    "EXISTS (SELECT 1 FROM post_interactions i WHERE i.post_id = p.id"
    " AND i.interaction_type IN ('opened', 'reading_session'))"
)
# Each post once, at its last open or reading session.
HISTORY_CTE = (
    "SELECT post_id, MAX(created_at) AS opened_at FROM post_interactions"
    " WHERE interaction_type IN ('opened', 'reading_session') GROUP BY post_id"
)
# Lists that ignore "Show in Main feed: off": a post you saved, or opened, is yours whatever its source.
_EVERY_SOURCE_FILTERS = ("later", "history")


# A story's posts, first posted first (its lead: the first report shown, else the first share).
_STORY_RANK = "COALESCE({p}.published_at, {p}.fetched_at), {p}.id"
# A story post's place in its story's order (issue 0072 D: a date alone counts as that day's earliest
# timed post), then the time: compares two posts of one story ({sp}: story_posts' or news_posts' row).
_ORDER_RANK = "COALESCE({sp}.position, 0), " + _STORY_RANK
# Where a story post sits in its tree (issue 0064), the lead's first test: 0 the origin (no parent
# and no reason: also every post before the job has drawn the tree), 1 a post citing the story's
# outside page origin, 2 the rest.
_TREE_RANK = ("(CASE WHEN {sp}.parent_reason IS NULL THEN 0"
              " WHEN {sp}.parent_id IS NULL AND {sp}.parent_url IS NOT NULL AND {sp}.parent_reason = 'citation' THEN 1"
              " ELSE 2 END)")
# The story posts that a lead's read marks read: the shares of a story whose report (or, when
# it has none, whose share) was read, and the rest of a thread read at one of its posts (0066).
# A Telegram album's pictures are read with its post (issue 0069).
_SHARES_OF_READ = """
    WITH RECURSIVE thread AS (
        SELECT post_id FROM story_posts WHERE post_id = ANY(%(read)s::uuid[])
        UNION SELECT sp.post_id FROM story_posts sp JOIN thread t ON sp.parent_id = t.post_id AND sp.parent_reason = 'thread'
    )
    SELECT DISTINCT o.post_id FROM story_posts sp
    JOIN story_posts o ON o.story_id = sp.story_id AND o.post_id <> sp.post_id AND o.role = 'share'
    WHERE sp.post_id = ANY(%(read)s::uuid[])
      AND (sp.role = 'report'
           OR NOT EXISTS (SELECT 1 FROM story_posts r WHERE r.story_id = sp.story_id AND r.role = 'report'))
    UNION SELECT post_id FROM thread WHERE NOT post_id = ANY(%(read)s::uuid[])
    UNION SELECT id FROM posts WHERE album_of = ANY(%(read)s::uuid[])
"""


def _on(sql: str, posts: str, sources: str) -> str:
    """A predicate written on `p` and `s`, on other aliases (a story's other posts)."""
    return re.sub(r"\bs\.", sources + ".", re.sub(r"\bp\.", posts + ".", sql))


def unread_window_days_from_env() -> Optional[int]:
    """INSIGHT_UNREAD_WINDOW_DAYS as a positive int, or None (unset, 0 or garbage: no window)."""
    days = env_int("INSIGHT_UNREAD_WINDOW_DAYS", 0)
    return days if days > 0 else DEFAULT_UNREAD_WINDOW_DAYS


def _require_uuid(value: str, what: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"invalid {what}: {value!r}") from None


@dataclass(frozen=True)
class FeedScope:
    """Which posts a feed shows. 'all' honours sources.in_main_digest (but not under the
    later filter: a post put in Later is there whatever its source); starred is a filter."""

    kind: Literal["all", "folder", "source"]
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in SCOPE_KINDS:
            raise ValueError(f"invalid feed scope kind: {self.kind!r}")
        if self.kind == "all":
            if self.id is not None:
                raise ValueError("scope 'all' takes no id")
        else:
            object.__setattr__(self, "id", _require_uuid(self.id or "", f"{self.kind} id"))

    @staticmethod
    def parse(value: str | None) -> "FeedScope":
        """`all`, `folder:<uuid>` or `source:<uuid>` (the API's `scope=` form)."""
        text = (value or "all").strip()
        if text == "all":
            return FeedScope("all")
        kind, sep, ident = text.partition(":")
        if not sep or kind not in ("folder", "source"):
            raise ValueError(f"invalid feed scope: {value!r}")
        return FeedScope(kind, ident)  # type: ignore[arg-type]

    def key(self) -> str:
        return "all" if self.kind == "all" else f"{self.kind}:{self.id}"


@dataclass(frozen=True)
class FeedCursor:
    """A keyset position: the sort key of the last item served (or of a group's newest post)."""

    sort_at: datetime
    post_id: str

    def encode(self) -> str:
        raw = f"{self.sort_at.isoformat()}|{self.post_id}".encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def decode(s: str) -> "FeedCursor":
        if not s:
            raise ValueError("empty cursor")
        try:
            raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8")
            stamp, sep, post_id = raw.partition("|")
            if not sep:
                raise ValueError("no separator")
            sort_at = datetime.fromisoformat(stamp)
        except (binascii.Error, UnicodeDecodeError, ValueError):
            raise ValueError(f"malformed feed cursor: {s!r}") from None
        if sort_at.tzinfo is None:
            raise ValueError(f"malformed feed cursor: {s!r}")
        return FeedCursor(sort_at, _require_uuid(post_id, "cursor id"))


@dataclass(frozen=True)
class FeedQuery:
    """One page of posts: which posts, and how they are paged.

    `days` keeps the last N days; `day` keeps one calendar day (UTC). `view="by_source"` pages
    groups (one per source, `per_source` newest items each), at most MAX_FEED_GROUPS a page.
    A bad value is a ValueError (the API's 400).
    """

    scope: FeedScope = field(default_factory=lambda: FeedScope("all"))
    filter: FeedFilter = "all"
    view: FeedView = "stream"
    cursor: Optional[FeedCursor] = None
    limit: int = 30
    days: Optional[int] = None
    day: Optional[date] = None
    per_source: int = 3

    def __post_init__(self) -> None:
        if self.filter not in FEED_FILTERS:
            raise ValueError(f"filter must be one of {', '.join(FEED_FILTERS)}")
        if self.view not in FEED_VIEWS:
            raise ValueError(f"view must be one of {', '.join(FEED_VIEWS)}")
        if not 1 <= int(self.limit) <= MAX_FEED_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_FEED_LIMIT}")
        if self.days is not None and int(self.days) < 1:
            raise ValueError("days must be at least 1")
        if self.days is not None and self.day is not None:
            raise ValueError("send days or date, not both")

    @staticmethod
    def parse(*, scope: str | None = None, filter: str = "all", view: str = "stream",
              cursor: str | None = None, limit: int = 30, days: int | None = None,
              date: str | None = None) -> "FeedQuery":
        """The API's query string: `scope=all|source:<uuid>|folder:<uuid>`, `date=YYYY-MM-DD`."""
        day = None
        if date:
            try:
                day = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError(f"date must be YYYY-MM-DD, not {date!r}") from None
        return FeedQuery(
            scope=FeedScope.parse(scope), filter=filter, view=view,  # type: ignore[arg-type]
            cursor=FeedCursor.decode(cursor) if cursor else None,
            limit=int(limit), days=int(days) if days is not None else None, day=day,
        )

    def bounds(self, now: datetime) -> Tuple[Optional[datetime], Optional[datetime]]:
        """(since, until) on the sort key: since inclusive, until exclusive."""
        if self.day is not None:
            start = datetime.combine(self.day, time.min, tzinfo=timezone.utc)
            return start, start + timedelta(days=1)
        if self.days:
            return now - timedelta(days=self.days), None
        return None, None


def _excerpt(content: str | None) -> str:
    return clean_text(content)[:EXCERPT_CHARS]


@lru_cache(maxsize=1024)
def _own_account(platform: str | None, handle: str | None) -> str:
    """The X account a source follows ("badlogicgames"), else ""."""
    account = source_account(platform, handle) or ""
    return account[len("x.com/"):] if account.startswith("x.com/") else ""


def repost_of(platform: str | None, handle: str | None, author: str | None,
              reposted_by: Sequence[str] | None) -> Dict[str, Any] | None:
    """A row its source reposted (issue 0066): {by, author}, `by` the other accounts of yours that
    reposted it, never the row's own source (issue 0070: "badlogicgames ↻ from @thsottiaux"). None
    when the row's source didn't repost it (its author's own tweet, the others said in its story)."""
    own = _own_account(platform, handle)
    if not author or not own or own not in [a.lower() for a in reposted_by or ()]:
        return None
    return {"by": [a for a in reposted_by or () if a.lower() != own], "author": author}


def story_voices(posts: Sequence[Dict[str, Any]], followed: Callable[[], Dict[str, Dict[str, str]]],
                 owners: Optional[Mapping[str, str]] = None) -> List[Dict[str, Any]]:
    """A story's voices, named (story_rules.named_voices, issue 0082: the count's names), from its
    posts as the reader reads them, in the order to name them: each {source_id, name, platform,
    handle, voice (story_posts.voice), content_hash, text_chars, author, reposted_by}. Who else of
    yours wrote or reposted a tweet is read as the story job reads it (StoriesService._story_post);
    `followed` (followed_accounts) is asked only when a post may hold one. A story of one voice has no
    count ("also shared by", 0072): its names are that voice's sources (voice_sources). `owners` (News,
    issue 0111: SourceFacts.owners, as the job kept them): a voice -> its owner's, one owner's channels one voice."""
    owners = owners or {}

    def owner(voice: str) -> Optional[str]:
        return owners.get(voice.lower() if voice.startswith("reddit:") else voice)
    shaped = []
    for p in posts:
        kind = source_kind(p["platform"], p["handle"])
        others: List[Dict[str, str]] = []
        if p["reposted_by"] or (kind == "x" and p["author"]):
            accounts = followed()
            author = accounts.get(x_account(p["author"])) if kind == "x" and p["author"] else None
            others = [author] if author and author["id"] != p["source_id"] else []
            by = {s["id"]: s for s in (accounts.get(x_account(a)) for a in p["reposted_by"] or ()) if s}
            others += [by[i] for i in sorted(set(by) - {p["source_id"], author and author["id"]})]
        voice = p["voice"] or "source:" + p["source_id"]
        if owners:
            others = [{**o, "owner": owner("source:" + o["id"])} for o in others]
        shaped.append({"source_id": p["source_id"], "name": p["name"], "kind": kind, "others": others,
                       "voice": voice, "owner": owner(voice) if owners else None,
                       "text_key": text_key(p["content_hash"], p["text_chars"] or 0)})
    voices = named_voices(shaped)
    return voice_sources(voices) if len(voices) == 1 else voices


def voiced(row: Sequence[Any], voice: Optional[str], content_hash: Optional[str]) -> Dict[str, Any]:
    """An item row's post (_ITEM_COLUMNS) as story_voices reads it, with its voice and content hash."""
    return {"source_id": str(row[4]), "name": row[5], "platform": row[6], "handle": row[20], "voice": voice,
            "content_hash": content_hash, "text_chars": row[11], "author": row[18], "reposted_by": row[19]}


def voice_sources(voices: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every source of a story's voices (story_voices), each once: who said it, copied or reposted it."""
    out: List[Dict[str, Any]] = []
    for s in (s for v in voices for s in ({"id": v["id"], "name": v.get("place") or v["name"]}, *v.get("with", ()))):
        if all(o["id"] != s["id"] for o in out):
            out.append(s)
    return out


# Item columns, in the order _item() reads them. `rs` is the LEFT JOINed projection, `pp` the post's
# parts (issue 0076: read once, when it was saved; LEFT JOINed): its title, its lead, the tweet it only
# quotes and hnrss's counts. A post not parsed yet reads its stored title and text.
_ITEM_COLUMNS = f"""
    p.id, COALESCE(pp.title, p.title), COALESCE(pp.lead, left(p.content, {EXCERPT_CHARS} * 2)), p.url, p.source_id,
    COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url), s.platform,
    {SORT_KEY}, p.published_at, rs.read_at, rs.starred_at,
    length(p.content), p.metadata->>'duration_seconds', jsonb_path_query_array(p.media_urls, '$[0 to 7]'),
    rs.resume_block, rs.resume_blocks, rs.later_at, p.metadata->'page_update', p.author, p.reposted_by, s.handle_or_url,
    pp.quote_only, pp.counts, p.metadata ? '{SAVED_KEY}' AND s.platform <> 'saved'
"""


def _item(row: Sequence[Any]) -> Dict[str, Any]:
    # The excerpt starts after a title taken from the text, without a feed's own lines (hnrss's
    # counts: the row says them), issue 0070: the post's lead (post_parts).
    title, excerpt = row[1], _excerpt(row[2])
    platform = row[6]
    duration = row[12]
    try:
        duration_seconds = int(float(duration)) if duration not in (None, "") else None
    except ValueError:
        duration_seconds = None
    counts = {"points": row[22]["points"], "comments": row[22]["comments"]} if row[22] else None
    content_length = row[22]["chars"] if counts else (row[11] or 0)
    is_video = platform == "youtube"
    return {
        "id": str(row[0]),
        "title": title,
        "counts": counts,
        "excerpt": excerpt,
        "url": row[3],
        "source_id": str(row[4]),
        "source_display_name": row[5],
        "platform": platform,
        "sort_at": row[7],
        "published_at": row[8],
        "read_at": row[9],
        "starred_at": row[10],
        "later_at": row[16],
        "reading_minutes": None if is_video or not content_length else math.ceil(content_length / CHARS_PER_READING_MINUTE),
        "duration_seconds": duration_seconds if is_video else None,
        "media_thumb": feed_thumb(row[13], row[3]),
        "resume_block": row[14],
        "resume_blocks": row[15],
        # A watched page's last meaningful change (issue 0039): {at, words, words_added, ...}.
        "update": row[17],
        # A repost (issue 0066): "↻ @by, from @author".
        "repost": repost_of(platform, row[20], row[18], row[19]),
        # A page you saved that is a followed source's post (issue 0122): "<source> · saved by you".
        "saved_by_you": bool(row[23]),
    }


class ReaderRepository:
    """SQL for the reader. Every method takes the caller's cursor; the caller owns the commit."""

    _FROM_ENV = object()

    def __init__(self, unread_window_days: Any = _FROM_ENV):
        """unread_window_days: days, None for no window; omitted reads INSIGHT_UNREAD_WINDOW_DAYS."""
        if unread_window_days is self._FROM_ENV:
            unread_window_days = unread_window_days_from_env()
        self.unread_window_days: Optional[int] = unread_window_days or None

    def _window_sql(self) -> Tuple[str, List[Any]]:
        """The unread window as a predicate on the sort key, or TRUE when there is none."""
        if self.unread_window_days is None:
            return "TRUE", []
        return f"{SORT_KEY} >= now() - make_interval(days => %s)", [self.unread_window_days]

    # ---- predicates ---------------------------------------------------------------

    @staticmethod
    def _scope_sql(scope: FeedScope, filter: str = "all") -> Tuple[str, List[Any]]:
        """The posts a scope lists; never a Telegram album's picture, which its post shows (issue 0069), nor a
        page shown only inside its story (issue 0126) unless you put it in Later, Kept or History."""
        shown = NOT_ALBUM_PIECE if filter in _YOURS_FILTERS else f"{NOT_ALBUM_PIECE} AND {NOT_STORY_ONLY}"
        if scope.kind == "all":
            return f"{shown} AND {'TRUE' if filter in _EVERY_SOURCE_FILTERS else 's.in_main_digest'}", []
        if scope.kind == "folder":
            return (f"{shown} AND p.source_id IN (SELECT sf.source_id FROM source_folders sf"
                    " WHERE sf.folder_id = %s)"), [scope.id]
        return f"{shown} AND p.source_id = %s", [scope.id]

    def _filter_sql(self, filter: str) -> Tuple[str, List[Any]]:
        if filter == "unread":
            window_sql, window_params = self._window_sql()
            return f"{UNREAD_SQL} AND {window_sql}", window_params
        if filter == "starred":
            return "rs.starred_at IS NOT NULL", []
        if filter == "later":
            return "rs.later_at IS NOT NULL", []
        if filter == "updated":   # a watched page that changed (issue 0039), latest change first
            return "p.metadata ? 'page_update'", []
        if filter == "history":   # opened or read (issue 0052); the stream orders it by last open
            return HISTORY_SQL, []
        if filter == "all":
            return "TRUE", []
        raise ValueError(f"invalid feed filter: {filter!r}")

    # ---- the post listing ----------------------------------------------------------

    @staticmethod
    def _bounds_sql(since: datetime | None, until: datetime | None, key: str = SORT_KEY
                    ) -> Tuple[str, List[Any]]:
        where, params = ["TRUE"], []
        if since is not None:
            where.append(f"{key} >= %s")
            params.append(since)
        if until is not None:
            where.append(f"{key} < %s")
            params.append(until)
        return " AND ".join(where), params

    # ---- stories (issue 0050) -------------------------------------------------------

    @staticmethod
    def folds(scope: FeedScope, filter: str) -> bool:
        """The Main feed and a track, unread or all, show a story once."""
        return scope.kind != "source" and filter in ("all", "unread")

    def _lead_sql(self, scope: FeedScope, filter: str, since: datetime | None = None,
                  until: datetime | None = None) -> Tuple[str, List[Any]]:
        """`p` is its story's lead among the posts this view shows (or in no story): no other
        shown post of its story ranks first (the origin, issue 0064; then a report before a share,
        then the first posted)."""
        scope_sql, params = self._scope_sql(scope, filter)
        filter_sql, filter_params = self._filter_sql(filter)
        bounds_sql, bounds_params = self._bounds_sql(since, until)
        shown = " AND ".join(_on(sql, "op", "os") for sql in (scope_sql, filter_sql, bounds_sql))
        sql = f"""NOT EXISTS (
            SELECT 1 FROM story_posts sp
            JOIN story_posts o ON o.story_id = sp.story_id AND o.post_id <> sp.post_id
            JOIN posts op ON op.id = o.post_id
            JOIN sources os ON os.id = op.source_id
            WHERE sp.post_id = p.id AND {shown}
              AND ({_TREE_RANK.format(sp='o')} < {_TREE_RANK.format(sp='sp')}
                   OR ({_TREE_RANK.format(sp='o')} = {_TREE_RANK.format(sp='sp')}
                       AND ((o.role = 'report' AND sp.role = 'share')
                            OR (o.role = sp.role AND ({_ORDER_RANK.format(sp='o', p='op')})
                                                         < ({_ORDER_RANK.format(sp='sp', p='p')}))))))"""
        return sql, [*params, *filter_params, *bounds_params]

    @staticmethod
    def attach_stories(cur: Cursor, items: List[Dict[str, Any]]) -> None:
        """Give each item that leads a story its `story` (else None): {id, voices, first (its origin
        post, issue 0064; before the tree is drawn its first report, else its first share: issue
        0055; None when another post of the story came before it, issue 0072 D), sources: its voices
        named, in the order they covered it (story_voices, issue 0082: {id, name, place, with}), posts: the story's other posts, in the story's order}. The post
        page (0055) asks it too.

        The tree (issue 0064): each post has `parent_id` (a post of the story) and `parent_reason`
        (address, citation, copy, time, none); the origin has neither. A post with a reason and no
        `parent_id` hangs from the story's `origin` {url, title, linked_by}, a page outside INSIGHT
        (else `origin` is None). The item's own place: `parent_id` and `parent_reason` of the story.
        On X (issue 0066): `thread` when the story is one account's replies to itself or quotes of
        itself; a reply in it carries its `text`, and its title loses Nitter's "R to @…: ".
        Issue 0068: each post (and the item's own place) carries `reposted_by`, the accounts that
        reposted it, and your sources that wrote or reposted it join `sources`; `roundups` [{id, title,
        source_display_name}] are the roundups that mention the story and are not in it, each
        source once. Issue 0069: a source's roundup is the one that links the story's pages earliest
        in it, then the first, and a source in the story has none. Issue 0070: a post its source
        reposted carries `repost` {by, author}, and `reposted_by` leaves that source out (its line
        names the author and the reposter once). Issue 0072: a post that only quotes a post of its story
        is no line (`_without_quotes_of_itself`)."""
        if not items:
            return
        cur.execute(
            f"""
            SELECT sp.post_id, st.id, st.voices, p.id, {shown_title()}, left(p.content, {TITLE_TEXT_CHARS}), p.url, p.source_id,
                   COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url), s.platform, {SORT_KEY}, p.published_at,
                   r.read_at, o.role, o.parent_id, o.parent_reason, st.origin_url, st.origin_title, st.origin_linked_by,
                   p.reposted_by, p.author, s.handle_or_url, (SELECT pp.quote_only FROM post_parts pp WHERE pp.post_id = p.id),
                   COALESCE(p.normalized_url, p.url), o.position, o.voice, p.content_hash, length(p.content)
            FROM story_posts sp
            JOIN stories st ON st.id = sp.story_id
            JOIN story_posts o ON o.story_id = sp.story_id
            JOIN posts p ON p.id = o.post_id
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN post_reader_state r ON r.post_id = p.id
            WHERE sp.post_id = ANY(%s::uuid[])
            ORDER BY sp.post_id, {_ORDER_RANK.format(sp='o', p='p')}
            """,
            ([item["id"] for item in items],),
        )
        stories: Dict[str, Dict[str, Any]] = {}
        voiced: Dict[str, List[Dict[str, Any]]] = {}   # lead -> its story's posts, as story_voices reads them
        addresses: Dict[str, set] = {}   # lead -> its story's posts' addresses
        quoting: Dict[str, str] = {}   # a post that only quotes a tweet -> that tweet (issue 0072)
        for (lead, story_id, voices, post_id, title, content, url, source_id, name, platform, sort_at,
             published_at, read_at, role, parent_id, parent_reason, origin_url, origin_title,
             origin_linked_by, reposted_by, author, handle, quotes, address, position, voice, content_hash,
             text_chars) in cur.fetchall():
            story = stories.setdefault(str(lead), {
                "id": str(story_id), "voices": int(voices), "first": None, "_first_rank": None, "sources": [],
                "posts": [], "parent_id": None, "parent_reason": None, "thread": False,
                "origin": {"url": origin_url, "title": origin_title, "linked_by": int(origin_linked_by or 0)}
                          if origin_url else None,
                "reposted_by": None, "roundups": [],
            })
            voiced.setdefault(str(lead), []).append({
                "source_id": str(source_id), "name": name, "platform": platform, "handle": handle, "voice": voice,
                "content_hash": content_hash, "text_chars": text_chars, "author": author, "reposted_by": reposted_by})
            addresses.setdefault(str(lead), set()).add(address)
            if str(post_id) != str(lead) and parent_reason and (quoted := quotes):
                quoting[str(post_id)] = quoted
            story["thread"] |= parent_reason in ("thread", "quote")
            # The origin post first (issue 0064); before the tree is drawn, the first report.
            rank = (0 if parent_reason is None else 1, 0 if role == "report" else 1)
            if story["first"] is None or rank < story["_first_rank"]:
                story["first"], story["_first_rank"], story["_first_position"] = str(post_id), rank, position
            # Saved is never a voice (issue 0070 A8), so never named (issue 0072).
            if platform != "saved" and not any(source["id"] == str(source_id) for source in story["sources"]):
                story["sources"].append({"id": str(source_id), "name": name})
            # A repost's line names its author and who of yours reposted it once (issue 0070).
            repost = repost_of(platform, handle, author, reposted_by)
            parent = {"parent_id": str(parent_id) if parent_id else None, "parent_reason": parent_reason,
                      "reposted_by": (repost["by"] if repost else reposted_by) or None}
            if str(post_id) != str(lead):
                thread = parent_reason == "thread"   # a reply in a thread (issue 0066): its own words, read in order
                story["posts"].append({
                    "id": str(post_id), "title": title,
                    "text": clean_text(content) if thread else None, "url": url,
                    "source_id": str(source_id), "source_display_name": name, "platform": platform,
                    "sort_at": sort_at, "published_at": published_at, "read_at": read_at, "role": role,
                    "repost": repost, **parent,
                })
            else:
                story.update(parent)
        for lead, story in list(stories.items()):
            if ReaderRepository._without_quotes_of_itself(story, {i for i, q in quoting.items() if q in addresses[lead] and i != lead}) \
                    and story["voices"] < 2:
                del stories[lead]   # nothing left but the post it quotes: no story (issue 0072)
                continue
            # One account's replies to itself, or its quotes of itself, read as a thread (issue 0066).
            story["thread"] = story["thread"] and len(story["sources"]) == 1
            # A story whose origin is a page outside INSIGHT has no first post.
            if story["origin"] is not None and story["_first_rank"][0] != 0:
                story["first"] = None
            # "First" only when it is (issue 0072 D): the origin a post of the story came before is no first.
            if story["_first_position"]:
                story["first"] = None
            del story["_first_rank"], story["_first_position"]
        # Named as counted (issue 0082): one name a voice, your sources that wrote or reposted a tweet
        # of the story among them (issue 0068).
        followed = lru_cache(maxsize=1)(lambda: ReaderRepository.followed_accounts(cur))
        for lead, story in stories.items():
            story["sources"] = story_voices(voiced[lead], followed)
        # Each source's roundup that is most about the story (issue 0069): the one that links the story's
        # pages earliest in it (post_links.position), then the first; none of a source in the story.
        cur.execute(
            f"""
            SELECT * FROM (
                SELECT DISTINCT ON (m.story_id, p.source_id) m.story_id, p.id, {shown_title()},
                       COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url), p.source_id,
                       {SORT_KEY} AS at
                FROM story_mentions m JOIN posts p ON p.id = m.post_id JOIN sources s ON s.id = p.source_id
                -- A page you saved is never a roundup (issue 0072).
                AND s.platform <> 'saved'
                LEFT JOIN LATERAL (
                    SELECT min(pl.position) AS position FROM post_links pl
                    WHERE pl.post_id = m.post_id AND pl.target_url IN (
                        SELECT COALESCE(sp_p.normalized_url, sp_p.url) FROM story_posts sp
                        JOIN posts sp_p ON sp_p.id = sp.post_id WHERE sp.story_id = m.story_id
                        UNION ALL SELECT origin_url FROM stories WHERE id = m.story_id)
                ) linked ON TRUE
                WHERE m.story_id = ANY(%s::uuid[])
                ORDER BY m.story_id, p.source_id, linked.position NULLS LAST, {SORT_KEY}, p.id) first
            ORDER BY at, id
            """,
            ([story["id"] for story in stories.values()],),
        )
        roundups: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        for story_id, post_id, title, name, source_id, _ in cur.fetchall():
            roundups.setdefault(str(story_id), []).append(
                (str(source_id), {"id": str(post_id), "title": title, "source_display_name": name}))
        for story in stories.values():
            voices = {source["id"] for source in voice_sources(story["sources"])}
            story["roundups"] = [r for source_id, r in roundups.get(story["id"], []) if source_id not in voices]
        for item in items:
            item["story"] = stories.get(item["id"])

    @staticmethod
    def _without_quotes_of_itself(story: Dict[str, Any], quotes: set) -> bool:
        """A post with nothing of its own that only quotes a post of its story (issue 0072: a reply
        repeating the thread's first tweet) is no line: what hung from it hangs from its parent.
        True when that leaves the story no other post."""
        if not quotes:
            return False
        parents = {p["id"]: (p["parent_id"], p["parent_reason"]) for p in story["posts"]}
        for place in (story, *story["posts"]):
            while place["parent_id"] in quotes:
                place["parent_id"], reason = parents[place["parent_id"]]
                place["parent_reason"] = place["parent_reason"] if place["parent_reason"] == "thread" else reason
        story["posts"] = [p for p in story["posts"] if p["id"] not in quotes]
        return not story["posts"]

    @staticmethod
    def followed_accounts(cur: Cursor) -> Dict[str, Dict[str, str]]:
        """Your sources by the account they follow ("x.com/<user>"): {id, name}."""
        cur.execute("SELECT id, platform, handle_or_url, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url)"
                    " FROM sources ORDER BY id DESC")
        return {source_account(r[1], r[2]): {"id": str(r[0]), "name": r[3]} for r in cur.fetchall()}

    @staticmethod
    def _with_shares(cur: Cursor, read: List[str], marked: List[str], *, at: datetime | None = None) -> List[str]:
        """`read` were marked read (`marked`: the ones that were unread): mark their stories'
        shares read too. Returns every id marked."""
        if not read:
            return marked
        cur.execute(_SHARES_OF_READ, {"read": read})
        shares = [str(r[0]) for r in cur.fetchall()]
        if not shares:
            return marked
        cur.execute(
            """
            INSERT INTO post_reader_state (post_id, read_at)
            SELECT p.id, COALESCE(%s::timestamptz, now()) FROM posts p WHERE p.id = ANY(%s::uuid[])
            ON CONFLICT (post_id) DO UPDATE
                SET read_at = EXCLUDED.read_at, updated_at = now()
                WHERE post_reader_state.read_at IS NULL
            RETURNING post_id
            """,
            (at, shares),
        )
        return marked + [str(r[0]) for r in cur.fetchall() if str(r[0]) not in marked]

    def list_posts(self, cur: Cursor, query: FeedQuery, *, now: datetime
                   ) -> Tuple[List[Dict[str, Any]], FeedCursor | None]:
        """One page of `query`: items (stream) or groups (by_source), and the next page's cursor."""
        since, until = query.bounds(now)
        if query.view == "by_source":
            return self._by_source(cur, query, since=since, until=until)
        if query.filter == "history":
            return self._history(cur, query, since=since, until=until)
        return self._stream(cur, query, since=since, until=until)

    def _history(self, cur: Cursor, query: FeedQuery, *, since: datetime | None, until: datetime | None
                 ) -> Tuple[List[Dict[str, Any]], FeedCursor | None]:
        """What you opened or read (issue 0052): each post once, latest open first.

        A row's `sort_at` is that last open, so the day headers, the time column and the
        cursor all follow it; `opened_at` says so by name. A time bound bounds the open.
        """
        scope_sql, params = self._scope_sql(query.scope, "history")
        bounds_sql, bounds_params = self._bounds_sql(since, until, "h.opened_at")
        where = [scope_sql, bounds_sql]
        params += bounds_params
        if query.cursor is not None:
            where.append("(h.opened_at, p.id) < (%s, %s::uuid)")
            params += [query.cursor.sort_at, query.cursor.post_id]
        limit = query.limit
        cur.execute(
            f"""
            WITH h AS ({HISTORY_CTE})
            SELECT {_ITEM_COLUMNS}, h.opened_at
            FROM h
            JOIN posts p ON p.id = h.post_id
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN post_reader_state rs ON rs.post_id = p.id
            LEFT JOIN post_parts pp ON pp.post_id = p.id
            WHERE {' AND '.join(where)}
            ORDER BY h.opened_at DESC, p.id DESC
            LIMIT %s
            """,
            [*params, limit + 1],
        )
        rows = cur.fetchall()
        items = []
        for row in rows[:limit]:
            item = _item(row)
            item["sort_at"] = item["opened_at"] = row[-1]
            items.append(item)
        next_cursor = None
        if len(rows) > limit:
            next_cursor = FeedCursor(items[-1]["opened_at"], items[-1]["id"])
        return items, next_cursor

    def _stream(self, cur: Cursor, query: FeedQuery, *, since: datetime | None, until: datetime | None
                ) -> Tuple[List[Dict[str, Any]], FeedCursor | None]:
        scope_sql, params = self._scope_sql(query.scope, query.filter)
        filter_sql, filter_params = self._filter_sql(query.filter)
        bounds_sql, bounds_params = self._bounds_sql(since, until)
        where = [scope_sql, filter_sql, bounds_sql]
        params += filter_params + bounds_params
        # Later is a queue: oldest saved first, its cursor on later_at. Every other list: newest first.
        later = query.filter == "later"
        key, order, after = ("rs.later_at", "ASC", ">") if later else (SORT_KEY, "DESC", "<")
        if query.cursor is not None:
            where.append(f"({key}, p.id) {after} (%s, %s::uuid)")
            params += [query.cursor.sort_at, query.cursor.post_id]
        fold = self.folds(query.scope, query.filter)
        if fold:
            lead_sql, lead_params = self._lead_sql(query.scope, query.filter, since, until)
            where.append(lead_sql)
            params += lead_params
        limit = query.limit
        cur.execute(
            f"""
            SELECT {_ITEM_COLUMNS}
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN post_reader_state rs ON rs.post_id = p.id
            LEFT JOIN post_parts pp ON pp.post_id = p.id
            WHERE {' AND '.join(where)}
            ORDER BY {key} {order}, p.id {order}
            LIMIT %s
            """,
            [*params, limit + 1],
        )
        rows = cur.fetchall()
        items = [_item(r) for r in rows[:limit]]
        if fold:
            self.attach_stories(cur, items)
        next_cursor = None
        if len(rows) > limit:
            next_cursor = FeedCursor(items[-1]["later_at" if later else "sort_at"], items[-1]["id"])
        return items, next_cursor

    def _by_source(self, cur: Cursor, query: FeedQuery, *, since: datetime | None, until: datetime | None
                   ) -> Tuple[List[Dict[str, Any]], FeedCursor | None]:
        """One group per source, newest group first; keyset on (newest_sort_at, source_id).

        `count` honours the filter and, when one is set, the unread window: it then bounds
        `unread` and `all` (an explicit star or Later never ages out).
        The time bound (`days` or `day`) bounds both the counts and the items. Two queries per
        page whatever its size: the groups, then every group's newest items in one LATERAL.
        """
        scope, filter, group_cursor = query.scope, query.filter, query.cursor
        groups, per_source = min(query.limit, MAX_FEED_GROUPS), query.per_source
        scope_sql, scope_params = self._scope_sql(scope, filter)
        filter_sql, filter_params = self._filter_sql(filter)
        window = ["TRUE"]
        window_params: List[Any] = []
        if filter == "all":
            all_window_sql, all_window_params = self._window_sql()
            window.append(all_window_sql)
            window_params += all_window_params
        bounds_sql, bounds_params = self._bounds_sql(since, until)
        window.append(bounds_sql)
        window_params += bounds_params
        window_sql = " AND ".join(window)
        group_where, group_params = "TRUE", []
        if group_cursor is not None:
            group_where = "(g.newest_sort_at, g.source_id) < (%s, %s::uuid)"
            group_params = [group_cursor.sort_at, group_cursor.post_id]
        cur.execute(
            f"""
            WITH g AS (
                SELECT p.source_id, MAX({SORT_KEY}) AS newest_sort_at, COUNT(*) AS n
                FROM posts p
                JOIN sources s ON s.id = p.source_id
                LEFT JOIN post_reader_state rs ON rs.post_id = p.id
                WHERE {scope_sql} AND {filter_sql} AND {window_sql}
                GROUP BY p.source_id
            )
            SELECT g.source_id, g.newest_sort_at, g.n,
                   COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url), s.platform
            FROM g JOIN sources s ON s.id = g.source_id
            WHERE {group_where}
            ORDER BY g.newest_sort_at DESC, g.source_id DESC
            LIMIT %s
            """,
            [*scope_params, *filter_params, *window_params, *group_params, groups + 1],
        )
        group_rows = cur.fetchall()
        page = group_rows[:groups]
        items_by_source: Dict[str, List[Dict[str, Any]]] = {str(row[0]): [] for row in page}
        if page:
            cur.execute(
                f"""
                SELECT x.*
                FROM unnest(%s::uuid[]) AS g(source_id)
                CROSS JOIN LATERAL (
                    SELECT {_ITEM_COLUMNS}
                    FROM posts p
                    JOIN sources s ON s.id = p.source_id
                    LEFT JOIN post_reader_state rs ON rs.post_id = p.id
                    LEFT JOIN post_parts pp ON pp.post_id = p.id
                    WHERE p.source_id = g.source_id AND {filter_sql} AND {window_sql}
                    ORDER BY {SORT_KEY} DESC, p.id DESC
                    LIMIT %s
                ) x
                """,
                [list(items_by_source), *filter_params, *window_params, per_source],
            )
            for row in cur.fetchall():
                item = _item(row)
                items_by_source[item["source_id"]].append(item)
        out: List[Dict[str, Any]] = [
            {
                "source_id": str(source_id),
                "source_display_name": display_name,
                "platform": platform,
                "newest_sort_at": newest,
                "count": int(n),
                # LATERAL keeps each source's rows in its ORDER BY, but say so rather than rely on it.
                "items": sorted(items_by_source[str(source_id)], key=lambda i: (i["sort_at"], i["id"]),
                                reverse=True),
            }
            for source_id, newest, n, display_name, platform in page
        ]
        next_cursor = None
        if len(group_rows) > groups:
            last = out[-1]
            next_cursor = FeedCursor(last["newest_sort_at"], last["source_id"])
        return out, next_cursor

    # ---- read state ---------------------------------------------------------------

    def set_read(self, cur: Cursor, post_ids: Sequence[str], read: bool) -> List[str]:
        """Mark posts read (keeping the first read time; a story's shares with its report) or
        unread. Returns the ids changed."""
        ids = [_require_uuid(pid, "post id") for pid in post_ids]
        if not ids:
            return []
        if read:
            cur.execute(
                """
                INSERT INTO post_reader_state (post_id, read_at)
                SELECT p.id, now() FROM posts p WHERE p.id = ANY(%s::uuid[])
                ON CONFLICT (post_id) DO UPDATE
                    SET read_at = now(), updated_at = now()
                    WHERE post_reader_state.read_at IS NULL
                RETURNING post_id
                """,
                (ids,),
            )
            # A story read at its lead: its copies and shares are read too (issue 0050).
            return self._with_shares(cur, ids, [str(r[0]) for r in cur.fetchall()])
        cur.execute(
            """
            UPDATE post_reader_state SET read_at = NULL, updated_at = now()
            WHERE post_id = ANY(%s::uuid[]) AND read_at IS NOT NULL
            RETURNING post_id
            """,
            (ids,),
        )
        return [str(r[0]) for r in cur.fetchall()]

    def set_starred(self, cur: Cursor, post_id: str, starred: bool) -> None:
        post_id = _require_uuid(post_id, "post id")
        if starred:
            cur.execute(
                """
                INSERT INTO post_reader_state (post_id, starred_at)
                SELECT p.id, now() FROM posts p WHERE p.id = %s
                ON CONFLICT (post_id) DO UPDATE
                    SET starred_at = COALESCE(post_reader_state.starred_at, now()), updated_at = now()
                """,
                (post_id,),
            )
        else:
            cur.execute(
                "UPDATE post_reader_state SET starred_at = NULL, updated_at = now() WHERE post_id = %s",
                (post_id,),
            )

    def set_position(self, cur: Cursor, post_id: str, block: int | None, blocks: int | None) -> None:
        """Where a long post was left: the top block in view of `blocks` (issue 0030). None clears it."""
        post_id = _require_uuid(post_id, "post id")
        if block is None:
            self.clear_positions(cur, [post_id])
            return
        if blocks is None or blocks < 1 or not 0 <= block < blocks:
            raise ValueError("block must be within 0 and blocks - 1")
        cur.execute(
            """
            INSERT INTO post_reader_state (post_id, resume_block, resume_blocks)
            SELECT p.id, %s, %s FROM posts p WHERE p.id = %s
            ON CONFLICT (post_id) DO UPDATE
                SET resume_block = EXCLUDED.resume_block, resume_blocks = EXCLUDED.resume_blocks, updated_at = now()
            RETURNING post_id
            """,
            (block, blocks, post_id),
        )
        if cur.fetchone() is None:
            raise LookupError(f"Post {post_id} not found")

    def clear_positions(self, cur: Cursor, post_ids: Sequence[str]) -> None:
        cur.execute(
            """
            UPDATE post_reader_state SET resume_block = NULL, resume_blocks = NULL, updated_at = now()
            WHERE post_id = ANY(%s::uuid[]) AND resume_block IS NOT NULL
            """,
            (list(post_ids),),
        )

    def set_later(self, cur: Cursor, post_ids: Sequence[str], later: bool, *, at: datetime | None = None
                  ) -> List[str]:
        """Put posts in Later (at `at`, default now; a post already there keeps its time) or take
        them out. Returns the ids changed. Nothing calls this on a clock: Later never expires."""
        ids = [_require_uuid(pid, "post id") for pid in post_ids]
        if not ids:
            return []
        if later:
            cur.execute(
                """
                INSERT INTO post_reader_state (post_id, later_at)
                SELECT p.id, COALESCE(%s::timestamptz, now()) FROM posts p WHERE p.id = ANY(%s::uuid[])
                ON CONFLICT (post_id) DO UPDATE
                    SET later_at = EXCLUDED.later_at, updated_at = now()
                    WHERE post_reader_state.later_at IS NULL
                RETURNING post_id
                """,
                (at, ids),
            )
        else:
            cur.execute(
                """
                UPDATE post_reader_state SET later_at = NULL, updated_at = now()
                WHERE post_id = ANY(%s::uuid[]) AND later_at IS NOT NULL
                RETURNING post_id
                """,
                (ids,),
            )
        return [str(r[0]) for r in cur.fetchall()]

    def mark_read_through(self, cur: Cursor, scope: FeedScope, through: FeedCursor, *, newest: FeedCursor,
                          now: datetime) -> List[str]:
        """Mark unread posts in `scope` from `newest` down to `through` (inclusive) read.

        Bounded by the page: posts newer than `newest` (arrived after the page rendered) stay
        unread, nothing older than `through` is touched (nor, with a window set, anything
        outside it), and only rows with read_at IS NULL are written. Returns the ids
        marked, so the UI can undo with set_read(ids, False).
        """
        scope_sql, params = self._scope_sql(scope)
        window_sql, window_params = "TRUE", []
        if self.unread_window_days is not None:
            window_sql, window_params = f"{SORT_KEY} >= %s", [now - timedelta(days=self.unread_window_days)]
        # The rows the unread view shows: a story's lead, not the reports folded under it (0050).
        lead_sql, lead_params = self._lead_sql(scope, "unread") if self.folds(scope, "unread") else ("TRUE", [])
        cur.execute(
            f"""
            INSERT INTO post_reader_state (post_id, read_at)
            SELECT p.id, %s
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            WHERE {scope_sql}
              AND {UNREAD_SQL}
              AND ({SORT_KEY}, p.id) <= (%s, %s::uuid)
              AND ({SORT_KEY}, p.id) >= (%s, %s::uuid)
              AND {window_sql}
              AND {lead_sql}
            ON CONFLICT (post_id) DO UPDATE
                SET read_at = EXCLUDED.read_at, updated_at = now()
                WHERE post_reader_state.read_at IS NULL
            RETURNING post_id
            """,
            [now, *params, newest.sort_at, newest.post_id, through.sort_at, through.post_id, *window_params,
             *lead_params],
        )
        marked = [str(r[0]) for r in cur.fetchall()]
        return self._with_shares(cur, marked, marked, at=now)

    def unread_counts(self, cur: Cursor) -> Dict[str, Any]:
        """{total (main digest), by_source: {id: n}, by_folder: {id: n}} of unread posts (all-time unless a window is set),
        `newest_unread`: {id: when} each source's newest unread post, as "By source" orders its groups (issue 0088),
        and `later`: {count, minutes}, every post in Later and what reading them costs. The total and a
        track's count are rows, as those feeds show them (a story with unread posts is one, issue 0050);
        a source's count is its posts."""
        window_sql, window_params = self._window_sql()
        cur.execute(
            f"""
            SELECT p.source_id, COUNT(*), MAX({SORT_KEY})
            FROM posts p
            WHERE {NOT_ALBUM_PIECE} AND {NOT_STORY_ONLY} AND {UNREAD_SQL} AND {window_sql}
            GROUP BY p.source_id
            """,
            window_params,
        )
        rows = cur.fetchall()
        by_source: Dict[str, int] = {str(source_id): int(n) for source_id, n, _ in rows}
        newest_unread: Dict[str, Optional[str]] = {str(source_id): iso(newest) for source_id, _, newest in rows}
        cur.execute(
            f"""
            SELECT sf.folder_id, COUNT(DISTINCT COALESCE(sp.story_id, p.id))
            FROM posts p
            JOIN source_folders sf ON sf.source_id = p.source_id
            LEFT JOIN story_posts sp ON sp.post_id = p.id
            WHERE {NOT_ALBUM_PIECE} AND {NOT_STORY_ONLY} AND {UNREAD_SQL} AND {window_sql}
            GROUP BY sf.folder_id
            UNION ALL
            SELECT NULL, COUNT(DISTINCT COALESCE(sp.story_id, p.id))
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN story_posts sp ON sp.post_id = p.id
            WHERE s.in_main_digest AND {NOT_ALBUM_PIECE} AND {NOT_STORY_ONLY} AND {UNREAD_SQL} AND {window_sql}
            """,
            [*window_params, *window_params],
        )
        total = 0
        by_folder: Dict[str, int] = {}
        for folder_id, n in cur.fetchall():
            if folder_id is None:
                total = int(n)
            else:
                by_folder[str(folder_id)] = int(n)
        cur.execute(
            f"""
            SELECT COUNT(*), COALESCE(SUM({MINUTES_SQL}), 0)
            FROM post_reader_state rs
            JOIN posts p ON p.id = rs.post_id
            JOIN sources s ON s.id = p.source_id
            WHERE rs.later_at IS NOT NULL
            """
        )
        later_count, later_minutes = cur.fetchone()
        return {"total": total, "by_source": by_source, "newest_unread": newest_unread, "by_folder": by_folder,
                "later": {"count": int(later_count), "minutes": int(later_minutes)}}
