# 0026 — Find a site's feed from any page URL

Status: **ready-for-agent** (owner, 2026-10-27). From the "Ideas" list ("Feed discovery").

## Problem
Add source accepts only a feed address. Pasting a page (`https://borretti.me/article/no-man-is-an-island`) adds a source that can never fetch. The owner wants the finder to be as fast and as accurate as possible.

## Measured (prototype, 40 real pages, 2026-10-27)
- **The standard `<link rel="alternate">` tag is not enough:** borretti.me has none, on the article or the home page; its feed is only a visible "RSS" link (`/feed.xml`). Old New Thing and Martin Fowler are the same.
- **Never download a whole feed to check it:** danluu.com's is 6.6 MB, Project Zero's 11 MB. Reading the first ~16 KB and streaming them into a pull parser until the first `<item>`/`<entry>` proves a feed.
- **Where hits came from:** page `<link>` tag (most), page `<a>` link (borretti, Old New Thing, Martin Fowler, danluu), the home page (Paul Graham, whose feed is on aaronsw.com; Cloudflare article pages), common paths (Ars Technica's home page, Stratechery), platform rules (Medium, GitHub). Real misses: anthropic.com/news (no feed exists), economist.com (section feeds only).
- Typical: **2 requests, under 1 s**. Path guessing was the slow part (10.8 s on Ars, sequential): it must be parallel with short timeouts.
- Prototype (throwaway, not INSIGHT code): `/tmp/fd-proto/proto.py`.

## Solution: one search, cheapest first, stop at the first stage that finds something
0. **No request.**
   - The URL is something an INSIGHT kind or site adapter reads directly (YouTube, Reddit, Telegram, Nitter, Substack, Pipecraft, Gwern, Dario, LessWrong…): leave it as is, "INSIGHT reads this site directly". Use the kinds' own `matches` (whichever is not the generic RSS kind).
   - Platform rules, each one line: `medium.com/@user` → `medium.com/feed/@user`; `<pub>.medium.com` → `/feed`; `github.com/<owner>/<repo>` → `…/releases.atom`. Validated like any candidate.
1. **One request: fetch the URL.** If it is a feed, done. Otherwise parse the HTML (stdlib `html.parser`, honouring `<base href>`; read at most ~1 MB):
   - `<link rel="alternate">` with an RSS, Atom or RDF type, in page order;
   - then `<a>` links that look like feeds (path segment `rss`/`atom`/`feed`, or ending in `.rss`/`.atom`/`feed.xml`/`rss.xml`/`atom.xml`/`index.xml`, or link text "RSS"/"Atom"/"Feed").
   - Drop comment feeds (`comment` in the title or address).
2. **Validate the candidates** concurrently (at most 4 at once): stream each and accept it at its first item. Keep every valid one, with its title, in candidate order.
3. **Nothing yet:** the section page (first path segment, e.g. `/blog/`) and the home page, fetched in parallel, the same way.
4. **Still nothing:** common paths on the site, in parallel, short timeouts, first valid in this order: `/feed`, `/rss`, `/feed.xml`, `/rss.xml`, `/atom.xml`, `/index.xml`, `/feed.atom`, `/?feed=rss2`, `/feeds/posts/default`.
- **Budget:** about 5 s per request and 10 s overall. A blocked or slow site gives "no feed found", never a hang. All requests are to the site the owner pasted, so a dozen at most is fine.
- JSON Feed is skipped (INSIGHT's parser reads RSS and Atom).

## In Add source
- Typing or pasting an address that is not a feed and not read directly: after a short pause (or on leaving the field), "Looking for a feed…".
  - **One found:** the field becomes the feed, the name comes from the feed's title, and a quiet line says "Found the feed for this page: borretti.me/feed.xml".
  - **Several:** a short choice list (title + address), the first chosen. For example, an Ars article page offers "AI - Ars Technica" and "Ars Technica".
  - **Read directly:** "INSIGHT reads this site directly", nothing replaced.
  - **None:** "No feed found on this page", and Add stays disabled.
- Add waits while it is looking. A feed already in the sources says so.

## Implementation notes
- A backend module `ingestion/feed_finder.py` with one entry point, `async find_feeds(http, registry, url) -> FeedFinding` (`status`: `feed | found | direct | none`, plus `feeds: [{url, title}]`), and `POST /api/sources/find-feed {url}`.
- Reading only the start of a response needs a byte cap in `KindHttp` (check what it has; add the smallest option, e.g. `max_bytes`). A pull parser accepts a prefix, so a cut-off feed is still recognised by its first item.
- Frontend: follow the modal's existing YouTube-handle lookup (`isResolvingChannel`) for the async state.

## Testing
- Unit tests with `FakeHttp` and trimmed fixtures, one per stage: the URL is a feed; a page `<link>`; borretti's `<a href="/feed.xml">RSS`; a comment feed dropped; `<base href>`; the home-page fallback; the common-path fallback; a huge feed accepted from its first 16 KB; a direct kind left alone; the Medium and GitHub rules; none found; a slow candidate doesn't stall the result.
- Component tests: found (one and several), direct, none (Add disabled), already a source.
- A live check of the finished finder on: borretti.me/article/no-man-is-an-island, danluu.com, googleprojectzero.blogspot.com, medium.com/@karpathy, github.com/astral-sh/uv, arstechnica.com, paulgraham.com/articles.html, blog.cloudflare.com/building-a-better-internet/, openai.com/news/, anthropic.com/news (expect none).
