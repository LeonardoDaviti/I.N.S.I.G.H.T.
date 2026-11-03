"""What one version of the code derives from a copy (issue 0075 C), as one JSON file `diff` compares.

    python -m insight_core.checks.snapshot --db <dsn> --out snap.json [--now ISO] [--parts posts,links,stories,news,classics,discover]

Read-only: run it after the version's own story job on its own scratch copy (job.py), or on any copy
for the parts that need no job (posts, links). The file holds the owner's data: realdata-check.sh
writes it to a private temporary directory and deletes it.

Parts (each guarded, so an older checkout snapshots what it has and says what it hasn't):
- posts: every post's title (as every page shows it) and the start of its shown text;
- links: a link post's link title (the post page's `link`);
- stories: each post's stories and the stories it is a roundup of (story_mentions), each story's origin;
- news: the News rows (NewsService.news_on): lead, posts, voices, first;
- classics: the classics table (the job's rows) and the Classics page's titles;
- discover: Discover's suggestions in order, and its archives.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List

from insight_core.checks import derive
from insight_core.checks.paths import plain
from insight_core.checks.session import copy_now, open_copy

PARTS = ("posts", "links", "stories", "news", "classics", "discover")


def _posts(ctx) -> Dict[str, Any]:
    facts = derive.all_posts(ctx["db_url"], ctx.get("workers"))
    ctx["facts"] = facts
    return {pid: {"title": f["title"], "text": f["text"][:200], "platform": f["platform"]} for pid, f in facts.items()}


def _links(ctx) -> Dict[str, Any]:
    from insight_core.db.repo_reader import ReaderRepository
    from insight_core.services.post_detail_service import PostDetailService
    facts = ctx.get("facts") or derive.all_posts(ctx["db_url"], ctx.get("workers"))
    cur = ctx["cur"]
    linking = sorted(pid for pid, f in facts.items() if f.get("link"))
    out = {}
    for k in range(0, len(linking), 300):
        items = [{"id": pid} for pid in linking[k:k + 300]]
        ReaderRepository.attach_stories(cur, items)
        cur.execute("SELECT id::text, url FROM posts WHERE id = ANY(%s::uuid[])", ([i["id"] for i in items],))
        urls = dict(cur.fetchall())
        for item in items:
            try:
                link = PostDetailService.link(cur, facts[item["id"]]["link"], item.get("story"), urls.get(item["id"]))
            except TypeError:   # before 0072 D4 the post's own address wasn't asked
                link = PostDetailService.link(cur, facts[item["id"]]["link"], item.get("story"))
            out[item["id"]] = plain(link)
    return out


def _stories(ctx) -> Dict[str, Any]:
    cur = ctx["cur"]
    cur.execute("SELECT post_id::text, story_id::text, role, parent_reason FROM story_posts")
    member: Dict[str, List] = {}
    for pid, sid, role, reason in cur.fetchall():
        member.setdefault(pid, []).append([sid, role, reason])
    cur.execute("SELECT post_id::text, story_id::text FROM story_mentions")
    mentions: Dict[str, List[str]] = {}
    for pid, sid in cur.fetchall():
        mentions.setdefault(pid, []).append(sid)
    cur.execute("SELECT id::text, voices, origin_url, origin_title FROM stories")
    stories = {sid: {"voices": v, "origin": url, "origin_title": title} for sid, v, url, title in cur.fetchall()}
    return {"member": member, "mentions": mentions, "stories": stories}


def _news(ctx) -> Dict[str, Any]:
    from insight_core.services.news_service import NewsService
    answer = plain(NewsService(ctx["db_url"], clock=lambda: ctx["now"]).news_on(ctx["cur"]))
    return {"rows": [{"lead": i["id"], "title": i.get("title"), "posts": sorted({i["id"], *(p["id"] for p in i["story"]["posts"])}),
                      "voices": i["story"]["voices"], "first_at": i["news"].get("first_at"), "part": i["news"].get("part"),
                      "first": (i["story"].get("sources") or [{}])[0].get("id")} for i in answer["items"]]}


def _classics(ctx) -> Dict[str, Any]:
    from insight_core.services.news_service import NewsService
    cur = ctx["cur"]
    cur.execute("SELECT target_url, post_id::text, voices, title, first_at, last_at FROM classics")
    table = {url: {"post_id": pid, "voices": v, "title": t, "first_at": plain(f), "last_at": plain(l)}
             for url, pid, v, t, f, l in cur.fetchall()}
    page = plain(NewsService(ctx["db_url"], clock=lambda: ctx["now"]).classics_on(cur))
    return {"table": table, "page": [{"url": c["url"], "title": c.get("title"), "voices": c.get("voices")} for c in page.get("classics", [])]}


def _discover(ctx) -> Dict[str, Any]:
    from insight_core.services.news_service import NewsService
    from insight_core.services.stories_service import StoriesService
    clock = lambda: ctx["now"]   # noqa: E731
    answer = plain(StoriesService(ctx["db_url"], clock=clock, news=NewsService(ctx["db_url"], clock=clock)).discover())
    return {"suggestions": [{"key": s["key"], "voices": s.get("voices"), "origins": s.get("origins"),
                             "articles": s.get("article_count"), "names": s.get("voice_names", [])}
                            for s in answer.get("suggestions", [])],
            "archives": [{"name": a.get("name"), "origins": a.get("origins")} for a in answer.get("archives", [])]}


BUILD = {"posts": _posts, "links": _links, "stories": _stories, "news": _news, "classics": _classics, "discover": _discover}


def snapshot(db_url: str, cur: Any, now, parts=PARTS, workers=None) -> Dict[str, Any]:
    ctx = {"db_url": db_url, "cur": cur, "now": now, "workers": workers}
    out: Dict[str, Any] = {"now": now.isoformat(), "parts": {}, "missing": {}, "seconds": {}}
    for part in parts:
        started = time.monotonic()
        try:
            out["parts"][part] = BUILD[part](ctx)
        except Exception as e:  # noqa: BLE001 - an older version lacks a service: said, not fatal
            out["missing"][part] = f"{type(e).__name__}: {e}"
        out["seconds"][part] = round(time.monotonic() - started, 1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--now")
    ap.add_argument("--parts", default=",".join(PARTS))
    ap.add_argument("--workers", type=int)
    args = ap.parse_args(argv)
    with open_copy(args.db) as conn, conn.cursor() as cur:
        snap = snapshot(args.db, cur, copy_now(cur, args.now), [p for p in args.parts.split(",") if p], args.workers)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    print(json.dumps({"seconds": snap["seconds"], "missing": snap["missing"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
