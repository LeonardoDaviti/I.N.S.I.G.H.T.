# 0028 — Follow a page without a feed

Status: **built** (2026-10-27, not deployed). Follows 0026 (the feed finder's "none").

## Problem
Some sites publish no feed at all. anthropic.com/news has no RSS or Atom anywhere: the feed
finder (0026) answers `none` and Add source stays disabled. Until now such a site needed a
site adapter of its own (Dario, Gwern, The Batch…). The owner wants to follow the page itself,
with no rules to write beyond one optional path.

## Measured (2026-10-27)
- `https://www.anthropic.com/news`: a 420 KB server-rendered page linking 26 articles as
  `href="/news/<slug>"`, plus category pages (`/news/announcements`, `/news/policy`…).
- Its `robots.txt` names `Sitemap: https://www.anthropic.com/sitemap.xml`: 75 KB, 584 URLs,
  279 under `/news/` (the whole history, the two category pages included).
- The sitemap's `<lastmod>` is not a publication date: 103 news URLs share 2026-10-14 (a
  redeploy). Each article page carries its own date (`article:published_time`, JSON-LD
  `datePublished`, `<time datetime>`). A category page has none, and `og:type` "website".

## Built
- **A kind, `page_watch`** (`backend/insight_core/ingestion/kinds/page_watch.py`). A source is
  `platform: rss`, `handle_or_url` the listing page, `settings.page_watch = {"prefix": "/news/"}`;
  the setting selects the kind (first in `KindRegistry.default`). It extends `BaseSourceAdapter`
  for `index_pages`.
  - Prefix: the listing page's path (`/news` → `/news/`); for a home page, the most common first
    segment of its same-host links two or more segments deep. The owner may override it.
  - Discovery: the listing page's same-host links under the prefix (page order), plus the
    sitemap's URLs under it (robots.txt `Sitemap:` lines, else `/sitemap.xml`; an index is
    followed to at most 5 files, children naming the section or "post" first; `.gz` skipped).
    The listing page itself is left out; URLs lose their fragment and trailing slash; deduped.
  - Live fetch: the candidates not stored yet (the `stored_urls` lookup generic RSS uses),
    listing links first, then the sitemap's by lastmod, newest first; up to `limit` posts
    (at most `limit + 5` pages read), 2 s between pages. A failed page is skipped; a 429 or a
    timeout stops the fetch (the learned pace, 0016).
  - One article: `extract_article_html` + `strip_html`; the title from `og:title`, `<title>` or
    `<h1>`, less a "| Site" suffix (the `og:site_name`'s, or any short one on a `<title>`); the
    date from the page (above, then `meta name=date`), else the lastmod, else now; `og:image`
    and the body's images.
  - Not a post: no article body, or neither a page date nor `og:type` article (category pages).
    A live fetch remembers such a page for the process's life and does not read it again.
  - Archive: every candidate, one article page per archive page (the host gate spaces them),
    resumable through the `site_index` checkpoint's `next_index`; `start_checkpoint` is None
    (it starts at the newest; the URL upsert absorbs what is stored). `inspect` reports the
    candidate count (`estimate`), the prefix, the listing and sitemap counts.
- **`POST /api/sources/page-watch/preview {url, prefix?}`** → `{success, prefix, found, sitemap,
  items: [{url, title, published_at}]}`: `found` the candidates, `items` the first 5 posts of
  the first 8 candidates (4 read at once), through the dialog's own `KindHttp(timeout=5)`.
  `POST /api/sources` takes `page_watch: {prefix?}` (validated, stored as `settings.page_watch`).
- **Add source**: under "No feed found on this page", a "Follow this page instead" button. Then
  "Looking for articles…", and "Found N articles under /news/ (from the sitemap)" with the
  first five titles and dates, an optional "Path" field (a change previews again after 600 ms),
  and Add enabled; Add sends `page_watch: {prefix}` (and the address with https). No readable
  article: "This page's articles can't be read without a browser (it builds them with
  JavaScript)." and Add stays disabled.
- Live check (preview only, from a container, 2026-10-27):
  - anthropic.com/news: `/news/`, 279 found, sitemap; 11 requests, 4.0 s. Items: Investing in the
    public benefit (10-18), Expanding the Cyber Verification Program (10-06), Anthropic files S-1
    with the SEC (10-26), Donating Agent Skills to the Agentic AI Foundation (10-22), Open call for
    guest investigators in the life sciences (10-22). The category pages among the first eight
    (announcements, features) were not posts.
  - cohere.com/blog (no feed, finder `none`): `/blog/`, 430 found, sitemap; 11 requests, 4.2 s;
    five dated articles (Rerank 5, AISLE, North 2, Embed 5, Future of work).
  - x.ai/news (no feed, finder `none`): `/news/`, 90 found, sitemap; 11 requests, 1.7 s; five
    dated articles.
  - pipecraft.me: `/`, 0 found, no sitemap, no items → the JavaScript message; 3 requests, 3.3 s.

## Limits
- A site whose articles carry neither a date nor `og:type` article is not followed (its pages
  look like category pages).
- The listing page's order is the site's (Anthropic puts featured posts first), not by date.
- Sitemap-only candidates are ordered by lastmod, which can be a redeploy date; a redeploy that
  reorders the sitemap during an archive can shift a resumed run (it re-reads or, rarely, skips).
- A live fetch reads backlog too: candidates not stored yet include the sitemap's history, read
  `limit` at a time until the archive (or the fetches) have stored them.
- The "no post" memory is per process; after a restart a category page is read once more.
- A JavaScript-only site (empty shells) gives no posts; its site adapter stays.

Later: test each site adapter (Dario, Gwern, LessWrong, The Batch, Phil Schmid, ZTM) against
page_watch and retire those it covers; JS-only sites like Pipecraft keep theirs.
