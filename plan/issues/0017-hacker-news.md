# 0017 — Hacker News: the article and its discussion

Status: **first version built** 2026-10-27 (reading through hnrss.org), not deployed; **the kind and the comments are future** (owner, 2026-10-27).

## What the owner wants
- **Both the article and the HN discussion.** The discussion is kept for the future analysis version.
- **HN comments come with Reddit comments** (0012's comments half): one comments design, not two.
- Now only the easiest version for reading.

## Built now: hnrss.org as a plain RSS source
- Add `https://hnrss.org/frontpage?points=100` as an RSS source (no new kind). Each item's `<link>` is the article, its `<comments>` the HN thread.
- The RSS parser keeps an item's RSS 2.0 `<comments>` as `metadata.comments_url` (generic: WordPress feeds use it too). The post page shows it as a 💬 "Open discussion" action next to ↗ "Open original".
- The post is the article: its title and link, its full text read by the full-text reader (the feed's body is a stub: "Article URL … Comments URL … Points … # Comments"). An article and the same article from its own blog's feed are one post (the URL upsert).
- Limits: hnrss.org is a third party; points and comment counts are frozen at the first fetch and only in the stub text; no archive; no comments in INSIGHT.

## Future: a `hackernews` kind on the Algolia API
- **Why Algolia** (`hn.algolia.com/api/v1`, HN's own search, no key): one request returns many stories with `points`, `num_comments`, `url`, `objectID`; it filters by points and date (`search_by_date?tags=story&numericFilters=points>N,created_at_i>T`). The official Firebase API needs one request per story. Never scrape news.ycombinator.com.
- **Fetch:** stories at or above the source's points threshold since the last fetch. The threshold is part of the source (e.g. `hn:100`), not a settings screen. Measure how many a day each threshold gives before choosing the default.
- **Post shape:** url = the article (for Ask/Show HN without a link, the HN item; its text is the body); `metadata` = `hn_id`, `points`, `num_comments`, `comments_url`. Re-fetching updates points and comments, and a story that crosses the threshold later is picked up.
- **Archive:** by date, the same way as Nitter in 0015 (`created_at_i<T`).
- **Comments (with 0012):** `GET /api/v1/items/<hn_id>` returns the whole tree in one request. Load on open, keep with the post, as Reddit's are kept. The stored tree is the discussion the analysis version will read.
- **Pacing:** Algolia allows about 10,000 requests an hour per IP; the shared host limiter (0016) is enough.

## Found on the server's data (2026-10-30), for the owner to decide with the kind
- **"An article and the same article from its own blog's feed are one post" costs HN its voice.**
  - With 0050 a story counts its sources. When HN and the site share one row, the story is "covered by 1": Hacker News never appears as a voice next to the site.
  - **The site also loses its own post.** In the lab, adding the Cloudflare blog saved 19 of its 20 posts. The 20th (`kv-cache-exposure-remediation`) already belonged to the HN source and stayed HN's row.
  - **It isn't rare:** 26 of the server's 62 HN posts (3 days) are articles from sites you already have posts from (openai.com, anthropic.com, apple.com, wired.com, bbc.com…).
- **Proposal for the kind:**
  - an HN post's address is its discussion (`news.ycombinator.com/item?id=…`), with the article as its first link;
  - the article's text can stay its body when you don't follow the site.
  - Then 0050's rules do the rest with no HN-specific code. If the site's post is stored, HN cites it, a citation within 72 hours, and the story reads "covered by 2 · Cloudflare Blog, Hacker News", HN as a share. Points and comments ride on the HN post.

## Points over time (owner, 2026-10-31: "we need to somehow track points for the posts")
- **Today:** 19 of the 62 hnrss posts on the server carry points in their text, as a snapshot at the first fetch. They aren't used.
- **Tracking points over time** needs this kind: Algolia's `points` and `num_comments`, updated on re-fetch, become an outside popularity signal for News.
- **For the future,** with this kind. The owner chose not to do a snapshot-only version.

## Out of Scope (now)
- Analysis of the discussion (the future analysis version).
- HN users, favourites, job posts.
