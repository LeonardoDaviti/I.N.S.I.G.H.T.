"""News and Classics (issue 0051): what many of your sources cover now, and what they keep citing.

Both are measured from your own sources, with no AI and no reading history:
- **News:** several independent sources cover the same thing within days. The story job finds the
  names surging in titles (over the last 32 days of titles) and joins 0050's stories by them, for
  News only, then scores each story (utils/news_rules.py). GET /api/news reads the stories whose
  first post is in the last 30 days. Every News row is kept (issue 0077): a run rewrites its own
  window only.
- **Classics:** your sources keep linking the same page over months. The story job aggregates the
  kept post links into `classics`; GET /api/classics reads them, cited again this week first.
- **Background:** a post that links a classic says so (at most 2, in the post's detail).
- **Discover** counts each suggestion's classics (StoriesService.discover).

The job part (`refresh`) runs inside the story job's transaction (StoriesService.regroup). The
Main feed is never reordered: News and Classics are views next to it.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

from insight_core.db import database as db
from insight_core.db.repo_discover import DiscoverRepository
from insight_core.db.repo_news import NewsRepository
from insight_core.db.repo_reader import FeedScope, ReaderRepository, story_voices
from insight_core.db.repo_stories import SourceFacts
from insight_core.services import page_titles
from insight_core.utils import voice
from insight_core.utils.addresses import paper_id
from insight_core.utils.classic_rules import Citation, Classic, cited_again, classic_order, classics
from insight_core.utils.story_rules import page_key, paper_aliases
from insight_core.utils.news_rules import (NAME_MIN_POSTS, NAME_SKIP_KINDS, NEWS_DAYS, NEWS_EDGE, NEWS_KEEP, NEWS_RECENT, SCOPE_ROLES,
                                          Surge, lead, longest, main_story, name_surges, names, news, phrases)
from insight_core.utils.story_rules import Story, StoryPost

PARTS = ("recent", "earlier")    # "Last 48 hours", the rest (the reader splits it by week, issue 0077)
WORDS = re.compile(r"\w+")


class NewsService:
    def __init__(self, db_url: str, *, repo: NewsRepository | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.db_url = db_url
        self.repo = repo or NewsRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---- the job ------------------------------------------------------------------------

    keep = NEWS_KEEP

    def refresh(self, cur: Any, *, posts: Sequence[StoryPost], stories: Sequence[Story],
                sources: SourceFacts) -> Dict[str, Any]:
        """News and every classic of a full story run (`posts`, every post, grouped into `stories`), on
        the caller's transaction: every name's surges, and News for the stories begun in the last
        NEWS_KEEP and the posts of no story posted in it; the rows begun before it are kept (issue 0077,
        `write_news`). Returns what it counted, how many rows changed and how many News rows it removed."""
        raw = name_surges(self._titled(sources, self.repo.load_titles(cur, None)), self.repo.followed_since(cur))
        surges_changed = self.repo.write_surges(cur, raw)
        found = sorted(longest(raw), key=lambda s: (s.at, s.name))
        since = self.clock() - NEWS_KEEP
        stories_now = self.rows(posts=posts, stories=stories, found=found, since=since)
        news_changed, news_removed = self.repo.write_news(cur, stories_now, since=since)
        self.repo.write_owners(cur, getattr(sources, "owners", {}))   # how News named its voices (issue 0111)
        found_classics = self._classics(cur, sources)
        classics_changed = self.repo.write_classics(cur, found_classics)
        return {"names": len(found), "surges_changed": surges_changed, "news": len(stories_now),
                "news_changed": news_changed, "news_removed": news_removed, "classics": len(found_classics),
                "classics_changed": classics_changed}

    @staticmethod
    def rows(*, posts: Sequence[StoryPost], stories: Sequence[Story], found: Sequence[Surge],
             since: datetime) -> List[Any]:
        """A full run's News rows, written by no one here (`refresh` writes them; Mark X writes its own, issue 0086
        E): the stories begun since `since` and the posts of no story posted since, joined by the surging names. A
        row is in the window by its first post (issue 0111): those of NEWS_EDGE before are read too, and a row they
        begin is no row of the window (the one stored stays as it was)."""
        edge = since - NEWS_EDGE
        shown = [s for s in stories if s.first_at >= edge]
        in_story = {p.id for s in stories for p in s.posts}
        ids = {p.id for s in shown for p in s.posts} | {p.id for p in posts if p.id not in in_story and p.t >= edge}
        return [s for s in news([p for p in posts if p.id in ids], shown, found) if s.first_at >= since]

    def update(self, cur: Any, *, sources: SourceFacts, posts: Dict[str, StoryPost],
               load: Callable[[Iterable[str]], None], touched: Set[str], titles: Sequence[Optional[str]],
               urls: Sequence[str], since: datetime, before: Optional[datetime]) -> Dict[str, int]:
        """News and Classics after an incremental batch (issue 0072 A), on its transaction, as a full run
        makes them: the names its titles say (`titles`: of the posts saved, changed or removed, as they
        are and were) judged again; News for the stories it regrouped (`touched`), the posts of the surges
        that changed, and the stories and posts that left the window or came into it since `before`;
        Classics for the pages it links or held (`urls`). `posts`/`load`: the batch's StoryPosts."""
        old = {(s.name, s.at, tuple(s.posts)) for s in longest(self.repo.stored_surges(cur))}
        surges_changed = self.judge_names(cur, sources, titles)
        raw = self.repo.stored_surges(cur)
        found = sorted(longest(raw), key=lambda s: (s.at, s.name))
        seeds = set(touched) | {p for name, at, ps in old ^ {(s.name, s.at, tuple(s.posts)) for s in found} for p in ps}
        edge = since - NEWS_EDGE   # a row is in the window by its first post (issue 0111): read from the edge before it
        if before is not None and before != since:
            lo, hi = min(before, since) - NEWS_EDGE, max(before, since)
            seeds |= set(self.repo.window_posts(cur, lo, hi))
        surges_of: Dict[str, List[Surge]] = defaultdict(list)
        for s in found:
            for pid in s.posts:
                surges_of[pid].append(s)
        # The News stories they are in, now and before: their stories, the roundups mentioning those,
        # the surges they are in, until nothing more joins (news_rules.news).
        group, frontier, stories = set(seeds), set(seeds), {}
        while frontier:
            held = self.repo.stories_of(cur, sorted(frontier), edge)
            stories.update(held)
            more = self.repo.news_mates(cur, sorted(frontier))
            more |= {pid for story in held.values() for pid in (*story["posts"], *story["mentions"])}
            more |= {pid for f in frontier for s in surges_of.get(f, ()) for pid in s.posts}
            frontier = more - group
            group |= frontier
        shown = set(self.repo.window_posts(cur, edge, ids=sorted(group)))
        load(shown)
        window = [posts[pid] for pid in sorted(shown) if pid in posts]
        held = [Story(id=sid, first_at=edge, posts=[posts[pid] for pid in story["posts"] if pid in posts], voices=0,
                      roles={}, reasons={}, mentions=story["mentions"]) for sid, story in sorted(stories.items())]
        stories_now = [s for s in news(window, held, found) if s.first_at >= since]   # a row begun before is left whole
        news_changed, news_removed = self.repo.write_news(cur, stories_now, since=since, post_ids=sorted(group))
        # How News named its voices (issue 0111); a source whose owner changed has its posts queued (_facts).
        self.repo.write_owners(cur, getattr(sources, "owners", {}))
        # A classic no link points to any more (its links read into another address, 0109 B1) goes, as in a full run.
        urls = sorted(set(urls) | set(self.repo.unlinked_classics(cur)))
        urls = self.repo.paper_paths(cur, urls)   # a paper's every path is one classic (issue 0106)
        urls = self.repo.moved_paths(cur, urls)   # and a page that moved is one with where it moved (0108)
        found_classics = self._classics(cur, sources, urls)
        classics_changed = self.repo.write_classics(cur, found_classics, urls)
        return {"surges_changed": surges_changed, "news_posts": len(group), "news_changed": news_changed,
                "news_removed": news_removed, "classics_changed": classics_changed}

    def judge_names(self, cur: Any, sources: SourceFacts, titles: Optional[Sequence[Optional[str]]]) -> int:
        """The surges of the names these titles say (every name when None) judged again
        (news_rules.name_surges), from every title that names or says them. Returns rows changed."""
        followed = self.repo.followed_since(cur)
        if titles is None:
            raw = name_surges(self._titled(sources, self.repo.load_titles(cur, None)), followed)
            return self.repo.write_surges(cur, raw)
        said = set().union(*(phrases(t) for t in titles if t))
        if not said:
            return 0
        judged = self.repo.named(cur, sorted(said), NAME_MIN_POSTS) | self.repo.surging(cur, sorted(said))
        if not judged:
            return 0
        rows = {r["id"]: r for r in self.repo.titles_saying(cur, sorted({"%".join(WORDS.findall(n)) for n in judged}))}
        named_by = self.repo.naming(cur, sorted(judged))
        rows.update((r["id"], r) for r in self.repo.titles_of(cur, sorted(set().union(*named_by.values()) - rows.keys())))
        raw = name_surges(self._titled(sources, rows.values()), followed, only=judged, named_by=named_by)
        return self.repo.write_surges(cur, raw, judged)

    @staticmethod
    def names_of(post: StoryPost) -> Set[str]:
        """The names in a post's title, as the name rule reads them (none for arXiv's): its opening when its
        stored title said more than the title shown (issue 0076: a bridge's glued second line), as load_titles."""
        said = post.opening or post.title
        return names(said) if said and post.kind not in NAME_SKIP_KINDS else set()

    @staticmethod
    def _titled(sources: SourceFacts, rows: Iterable[Dict[str, Any]]) -> List[StoryPost]:
        return [StoryPost(id=row["id"], source_id=row["source_id"], kind=sources.kind.get(row["source_id"], "site"),
                          own_site=sources.publication(row["source_id"]), t=row["t"], title=row["title"])
                for row in rows]

    def _classics(self, cur: Any, sources: SourceFacts, targets: Optional[Sequence[str]] = None) -> List[Classic]:
        """The classics among the kept links (to `targets`, when given), each titled as every page you don't
        follow is (issue 0106, page_titles.evidence): its stored post's title, else the evidence of every post
        linking any path of it; else the link words classic_rules reads (none of 182 on the lab needed them)."""
        citations, stored, aliases = self._cited(cur, sources, targets)
        found = classics(citations, stored)
        outside = [c.target for c in found if c.post_id is None]
        titles = page_titles.evidence(cur, sources, outside, aliases=aliases) if outside else {}
        for c in found:
            if c.post_id is None:
                c.title = titles.get(c.target) or c.title
        return found

    def _citations(self, cur: Any, sources: SourceFacts, targets: Optional[Sequence[str]] = None):
        """`_cited`'s citations and stored posts."""
        return self._cited(cur, sources, targets)[:2]

    def _cited(self, cur: Any, sources: SourceFacts, targets: Optional[Sequence[str]] = None):
        """The kept links as citations, each paper's paths cited as the one address that names it (issue
        0106: its abstract and its PDF are one classic), a page that moved as where it moved (issue 0108:
        a redirect stub's post is one page with the post stored there), the stored posts they are, and
        those aliases."""
        rows = self.repo.citations(cur, reddit=sources.of_kind("reddit"), saved=sources.of_kind("saved"), targets=targets)
        papers: Dict[str, Set[str]] = defaultdict(set)
        at: Dict[str, Optional[str]] = {}
        for row in rows:
            at.setdefault(row["target"], row["stored"])
            if paper_id(row["target"]):
                papers[page_key(row["target"]) or row["target"]].add(row["target"])
        aliases = paper_aliases(papers.values(), stored=[t for t, sid in at.items() if sid])
        for old, (new, post_id) in self.repo.moved_pages(cur, sorted(at) if targets is not None else None).items():
            if old in at:
                aliases[old] = new
                at.setdefault(new, post_id)
        authors: Dict[str, Optional[str]] = {}
        out = []
        for row in rows:
            if row["post_id"] not in authors:
                authors[row["post_id"]] = row["author"]
            key = self._voice(sources, row["source_id"], authors[row["post_id"]])
            target = aliases.get(row["target"], row["target"])
            out.append(Citation(voice=key, name=sources.voice_name(key, row["source_id"]),
                                source_id=row["source_id"], t=row["t"], target=target,
                                stored=row["stored"] if target == row["target"] else at.get(target), text=row["text"]))
        stored = {}
        for row in self.repo.stored_posts(cur, sorted({c.stored for c in out if c.stored})):
            stored[row["id"]] = (self._voice(sources, row["source_id"], None), row["t"], row["title"])   # as every place (0072 D1)
        return out, stored, aliases

    @staticmethod
    def _voice(sources: SourceFacts, source_id: str, author: Optional[str]) -> str:
        return voice.key(sources.kind.get(source_id, "site"), source_id, sources.publication(source_id), author)

    # ---- News ---------------------------------------------------------------------------

    def news(self, scope: str | None = None) -> Dict[str, Any]:
        """The News of a scope (the Main feed, a track or one source): the stories with 2+ voices
        begun in the last NEWS_DAYS, with a post from the scope's sources (the score counts every
        source), in two parts ("recent": the last 48 hours; "earlier"), each by score, then the
        newest. Each item is its story's lead as a feed row, with `story` (who covered it, its other
        posts) and `news` {part, first_at, reports, shares, mentions, score}. On one source (issue
        0077) also the stories a roundup of it mentions, and `news.scope_role`: its part, the
        strongest of its posts' (`SCOPE_ROLES`): origin (its post began the row: the row's first, and
        the origin of its 0050 story, issue 0082), report, share, else mention."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.news_on(cur, scope)

    def news_on(self, cur: Any, scope: str | None = None, news_id: Optional[str] = None) -> Dict[str, Any]:
        """`news` on the caller's cursor; `news_id`: that row only."""
        feed_scope = FeedScope.parse(scope)
        one_source = feed_scope.kind in ("source", "voice")   # a voice's page reads as a source's (issue 0132 A)
        now = self.clock()
        rows = self.repo.news_posts(cur, feed_scope, now - timedelta(days=NEWS_DAYS), news_id)
        followed = lru_cache(maxsize=1)(lambda: ReaderRepository.followed_accounts(cur))
        owners = self.repo.owners(cur)   # one owner's channels one voice, as the job counted them (issue 0111)
        by_story: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_story[row["_news"]].append(row)
        items = []
        for posts in by_story.values():
            shown = [p for p in posts if p["_in_scope"]]
            # The lead is the origin (issue 0064): a post its 0050 story's tree starts from.
            origins = [p["id"] for p in posts if p["_origin"]]
            roundups = [p["id"] for p in posts if p["_roundup"]]   # without an origin, never the lead (issue 0083)
            # Without an origin, the first share of a story's outside origin page leads (issue 0103).
            sharers = [p["id"] for p in posts if p["_shares_origin"]]
            # The lead comes from the row's main story, or what its own name joined (issue 0111), in the scope first.
            may = main_story([(p["id"], p["_story"], p["_story_voices"], p["_name"]) for p in posts])
            main = posts if may is None else [p for p in posts if p["id"] in may]

            def first(of: Sequence[Dict[str, Any]]) -> Optional[str]:
                return lead([(p["id"], p["role"]) for p in of], origins, roundups, sharers)
            in_main = {p["id"] for p in main}
            lead_id = (first([p for p in shown if p["id"] in in_main]) or first(shown) or first(main) or first(posts))
            first_report = first(main) or first(posts)
            head = next(p for p in posts if p["id"] == lead_id)
            covered = sorted(posts, key=lambda p: p["id"] != first_report)   # stable: time order after
            # Every voice the count holds is named, once (issues 0069, 0082), the first reporter first.
            sources = story_voices([p["_voiced"] for p in covered], followed, owners)
            item = {k: v for k, v in head.items() if not k.startswith("_") and k != "role"}
            # A lead whose own words are a short reaction reads what it quotes (post_parts.subject, issue 0076).
            item["title"] = head["_subject"] or item["title"]
            item["story"] = {"id": head["_news"], "voices": head["_voices"], "sources": sources,
                             "posts": NewsRepository.lines(posts, lead_id)}
            item["news"] = {
                "part": "recent" if head["_first_at"] >= now - NEWS_RECENT else "earlier",
                "first_at": head["_first_at"], "reports": head["_reports"], "shares": head["_shares"],
                "mentions": head["_mentions"], "score": head["_score"],
            }
            if one_source:
                # "Started it" only when first (issue 0082): the row's first post, the origin of its 0050
                # story (the post page's first, 0072 D); a first share of an outside page is a share.
                origin = posts[0]["id"] if posts[0]["_origin"] else None
                item["news"]["scope_role"] = min(
                    (("origin" if p["id"] == origin else p["role"]) for p in shown),
                    key=SCOPE_ROLES.index, default="mention")
            items.append(item)
        items.sort(key=lambda i: (PARTS.index(i["news"]["part"]), -i["news"]["score"],
                                  -i["news"]["first_at"].timestamp(), i["id"]))
        return {"success": True, "items": items, "next_cursor": None}

    def row_of(self, cur: Any, post_id: str, source_id: str) -> Optional[Dict[str, Any]]:
        """The News row a post is in (issue 0083: its page says it), as the Main feed's News shows it,
        else as its source's (a source outside the Main feed): {id, title, voices, lead_id, scope};
        None when it is in no row of the last NEWS_DAYS."""
        cur.execute("SELECT np.news_id FROM news_posts np JOIN news_stories ns ON ns.id = np.news_id "
                    "WHERE np.post_id = %s AND ns.first_at >= %s", (post_id, self.clock() - timedelta(days=NEWS_DAYS)))
        found = cur.fetchone()
        if not found:
            return None
        for scope in ("all", f"source:{source_id}"):
            for item in self.news_on(cur, scope, str(found[0]))["items"]:
                return {"id": item["story"]["id"], "title": item["title"], "voices": item["story"]["voices"],
                        "lead_id": item["id"], "scope": scope}
        return None

    # ---- Classics -----------------------------------------------------------------------

    def classics(self, scope: str | None = None) -> Dict[str, Any]:
        """The classics a source of the scope cited and you did not hide: cited again this week
        first (`cited_again`), then most voices, then cited longest. Each {url, post_id (the stored
        post, when it is one), title, voices, days, first_at, last_at, cited_again, citers [{name,
        at}] (each voice once, first citation first), read_at, later_at}. On one source (issue 0077)
        also its own posts that are classics, and `scope_role`: origin (its own post), else report."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.classics_on(cur, scope)

    def classics_on(self, cur: Any, scope: str | None = None) -> Dict[str, Any]:
        """`classics` on the caller's cursor."""
        feed_scope = FeedScope.parse(scope)
        now = self.clock()
        rows = self.repo.classics(cur, feed_scope)
        named = self.repo.source_name(cur, feed_scope.id) if feed_scope.kind == "source" else None
        read = self._read_titles(cur, rows)
        out = []
        for row in sorted(rows, key=lambda r: classic_order(r["last_at"], r["voices"], r["days"], r["url"], now)):
            title = row["post_title"] if row["post_id"] else row["title"] or read.get(row["url"])
            out.append({
                "url": row["url"], "post_id": row["post_id"], "title": title or None, "voices": row["voices"],
                "days": row["days"], "first_at": row["first_at"], "last_at": row["last_at"],
                "cited_again": cited_again(row["last_at"], now),
                "citers": self._citers(row["citers"], feed_scope.id if named is not None else None, named),
                "read_at": row["read_at"], "later_at": row["later_at"],
            })
            if feed_scope.kind in ("source", "voice"):   # issue 0077: the source's own page, else a page it cites
                out[-1]["scope_role"] = "origin" if row["own"] else "report"
        return {"success": True, "classics": out}

    @staticmethod
    def _citers(citers: Sequence[Dict[str, Any]], source_id: Optional[str], name: Optional[str]) -> List[Dict[str, Any]]:
        """A classic's citers as the API sends them ({name, at}), first citation first. On one source's
        page (issue 0105) that source's own voices come first, a Reddit author with the subreddit as its
        `place` ("u/a in r/x", as on News), so the page names its source among the first shown."""
        if source_id is None:
            return [{"name": c["name"], "at": c["at"]} for c in citers]
        own = [c for c in citers if source_id in (c.get("source_ids") or ())]
        out = []
        for c in own:
            out.append({"name": c["name"], "at": c["at"]})
            if name and voice.is_poster(str(c.get("voice", ""))):
                out[-1]["place"] = name
        return out + [{"name": c["name"], "at": c["at"]} for c in citers if c not in own]

    def hide(self, url: str) -> Dict[str, Any]:
        """Hide a classic ("I know it", "not for me"): it never comes back."""
        url = (url or "").strip()
        if not url or len(url) > 2000:
            raise ValueError("url must be a classic's address")
        with db.transaction(self.db_url) as cur:
            self.repo.hide_classic(cur, url)
        return {"success": True, "url": url}

    def background(self, cur: Any, post_id: str) -> List[Dict[str, Any]]:
        """The classics a post links, on the caller's cursor: [{url, post_id, title, voices}]."""
        rows = self.repo.background(cur, post_id)
        read = self._read_titles(cur, rows)
        return [{
            "url": row["url"], "post_id": row["post_id"], "voices": row["voices"],
            "title": (row["post_title"] if row["post_id"] else row["title"] or read.get(row["url"])) or None,
        } for row in rows]

    @staticmethod
    def _read_titles(cur: Any, rows: Sequence[Dict[str, Any]]) -> Dict[str, str]:
        """The page titles read (issue 0106, discover_reads) of the classics the stored data leaves untitled:
        a read fills one, never over a stored post's title or the evidence's."""
        untitled = [row["url"] for row in rows if not row["post_id"] and not row["title"]]
        return DiscoverRepository.read_titles(cur, untitled) if untitled else {}

    def untitled_classics(self, cur: Any) -> List[str]:
        """The classics whose page's own title Discover's reads read (issue 0106): no stored post, no title."""
        return self.repo.untitled_classics(cur)

    def classic_urls(self, cur: Any) -> List[str]:
        return self.repo.classic_urls(cur)
