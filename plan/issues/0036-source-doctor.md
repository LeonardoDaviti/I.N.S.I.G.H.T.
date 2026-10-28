# 0036 — Source doctor: a broken source finds its replacement

Status: **ready-for-agent** (owner, 2026-10-28: "our checker of sources should check if that old source is working, if not it should automatically run our feed finder or follow page and find all the posts"; "everything your pick").

## The case
`https://arena.ai/blog/rss/` stopped working; the source failed every fetch. Pasting `https://arena.ai/blog` offered "Follow this page instead": 76 articles.

## Decided
- **When:** after repeated failures (e.g. 3 in a row), or at once on a clear signal: HTTP 404/410, or the address no longer parses as a feed.
- **Look:** the feed finder (0026) on the source's address, its section (`/blog/` for `/blog/rss/`) and its home page; no feed → page watch preview (0028) of the section. Same rule as every source add.
- **Act:**
  - **Automatic switch** only when it is safe: a new **feed on the same site** while the old address is gone (404/410). The source keeps its id, name, tracks, read state and posts; only `handle_or_url` (and the kind) change; the job's events say "Arena: feed moved, now following arena.ai/blog/feed.xml".
  - **Otherwise suggest:** another site, page watching instead of a feed, or a flaky (not gone) feed → the Sources list and sheet show "Broken: INSIGHT found a replacement" with **Switch** and a preview ("Follow arena.ai/blog: 76 articles").
  - **Nothing found:** "Broken: no replacement found", plainly, not only "HTTP 404" in backoff.
- Posts match by URL, so a switch never duplicates what is stored; an archive after a switch brings the older ones.
- Rate: the doctor runs at most once a day per source.

## Dry run on the server's 7 failing sources (2026-10-28, before release)
| Source | Error | Doctor |
|---|---|---|
| joanwestenberg.com/rss | 404 | auto-switch → www.joanwestenberg.com/feed (same site, gone) |
| incompleteideas.net (Rich Sutton) | not a feed | suggest: follow the page (12 articles) |
| tedunangst.com/flak/rss | DNS | no replacement |
| dfarq.homeip.net/feed/ | garbled | no replacement |
| rachelbythebay.com/w/atom.xml | 404 | no replacement |
| devblogs.microsoft.com/oldnewthing/feed | SSL (temporary on the server) | **wrong:** suggested devblogs.microsoft.com/landing (all Microsoft blogs) |
| r/MachineLearning | 429 | skipped (Reddit kind) |

**Fix before release (v9.3):**
1. Check the old address first: if it reads as a feed now, record "temporary error, working again" and look no further.
2. A replacement must stay within the source's section (`/oldnewthing/…`); a home-page feed is offered only when the source was the whole site.
3. Tests from these three real cases.
