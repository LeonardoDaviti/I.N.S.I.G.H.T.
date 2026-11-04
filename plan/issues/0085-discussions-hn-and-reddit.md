# 0085 — Discussions: Hacker News and Reddit comments on the post page, one design

Status: **spec** (owner, 2026-11-04: "yes please add them"), for v9.17. It starts after 0076 merges (that branch holds the post page). Replaces the comments halves of 0012 (Reddit) and 0017 (HN): one comments design for both, as the owner asked on 2026-10-27.

**Constraints:** no login or API app; no real names in committed files or fixtures; every request through the per-host limiter (0016); nothing merges unless `scripts/realdata-check.sh` passes.

## Why
- An HN post and a Reddit post are, for the owner, the article **and** its discussion (0017).
- Today the post page only has "Open discussion ↗".
- **Reddit:** comments were never loaded, because `.json` answers 403 to any request not logged in (measured 2026-08-14, still 403 on 2026-11-04). 0012 waited on a Reddit app, and Reddit now approves new apps by hand.

## Ways in that need no login (each tested once from this machine, 2026-11-04)

| | Address | Answer | What it gives |
|---|---|---|---|
| HN | `https://hn.algolia.com/api/v1/items/<hn_id>` | 200 | the whole tree in one request: author, time, text, parent; about 10,000 requests an hour per IP |
| Reddit | `<thread address>/.rss` | 200, 64 entries for one thread | comments as a flat list: author, time, text; no nesting, no scores |

**Not tested yet:**
- whether the **server's** address gets 200 on Reddit's comments RSS (it does for post feeds);
- how many comments the RSS gives for a very large thread (look for a cap; try `?limit=`).

Measure both before building the Reddit half.

## Decided
1. **A post's discussion is stored with the post:**
   - a `discussions` table, one row per comment: post id, the platform's comment id, author, time, text (plain and HTML), parent comment id when known (HN; Reddit's RSS gives none), and the position in its thread;
   - plus, per post, `fetched_at` and `count`;
   - the raw answer isn't kept.
   - It is the same store for both platforms, and the analysis version reads it later.
2. **When it's fetched:**
   - when the owner opens the post, if never fetched or older than its refresh;
   - while the thread is young, once at about 6 hours and once at about 24 hours after the post, then never by itself.
   - Never every comment of every post up front: a busy subreddit would be thousands of requests a day.
   - Measure the requests a day this makes on the server's fetch history before choosing the 6 h and 24 h.
3. **Kept:** a later fetch adds new comments and updates edited ones. A comment removed upstream stays, marked "removed at the source" (the owner's "keep everything").
4. **The post page:**
   - a "Discussion · 42 comments" section under the post;
   - HN as a tree (replies indented, collapsible);
   - Reddit as a list, oldest first;
   - "Open discussion ↗" stays;
   - a thread too large to store in full shows what was stored and says so;
   - loading is quiet: the post shows first, the discussion when it arrives.
5. **Pacing:** one request at a time per host through the limiter, and the HN and Reddit hosts' own floors. A 403 or 429 backs off that host, never retries in a loop.
6. **Search** can find comment text later (not in this issue).

## Done when
- On the lab, opening an HN post and a Reddit post stores and shows their discussions.
- A second open within the refresh time makes no request.
- The young-thread refresh is measured: requests a day on the server's fetch history.
- The Reddit half is checked from the server's address (the owner runs one `curl`, or a first fetch's result is read).
- The real-data check passes (new tables only, nothing derived changes).

## Not in this issue
- Reddit's nesting and scores (they need a Reddit app; revisit if Reddit approves one).
- Comments of other platforms (YouTube, X replies).
- Ranking or summarising discussions (the analysis version, Mark X).
