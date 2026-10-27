# 0018 — pipecraft.me: a blog with no feed

Status: **built** 2026-10-27, not deployed. The owner asked for it to be built without being consulted first.

## Problem
- The owner wants to read Tornike Gomareli's blog, https://www.pipecraft.me/, in INSIGHT.
- The site has no feed. The page is a 1.6 KB shell (`<div id="root">`) filled in by JavaScript.
  - No `<link rel=alternate>`.
  - `/rss.xml`, `/feed.xml`, `/atom.xml`, `/sitemap.xml` and `robots.txt` are 404.
  - `/feed` and `/rss` return the same HTML shell.
- So `generic_rss` can't read it, and the full-text reader only sees the empty shell.

## Where the posts come from
The site's script calls the site's own JSON API (read from `/assets/index-*.js`, 2026-10-27):
- `GET /api/posts` is the index: `{"posts": [...], "essays": [...], "projects": [...], "talks": [...]}`.
  Each entry has `slug`, `title`, `date` (`YYYY-MM-DD`), `spoiler`, `section`, `readingTime`, and sometimes `youtubeId`.
  Today it lists 11 posts, 3 essays, 2 projects and 4 talks.
- `GET /api/posts/<section>/<slug>` is one entry plus `content`, the post's whole HTML. Its images are absolute URLs.
- A post's page is `https://www.pipecraft.me/<section>/<slug>`.

## Decision
A site adapter, `pipecraft_site` (`backend/insight_core/adapters/pipecraft_adapter.py`). It is the seventh site adapter, next to Dario, Gwern and the others.

**Why not something general:**
- The API is the site's own. No standard covers it: it isn't JSON Feed, and an entry has no URL and no body.
- A general "JSON index" reader would need a field map for each source (where the list is, how to build the post URL, where the body is), plus a screen to set it up. That is bigger than this adapter, and only one site needs it today.
- No headless browser is needed, because the API returns the whole HTML.
- If a second site like this appears, compare the two before writing anything general.

## Built
- **`matches`:** any URL on `pipecraft.me` or `www.pipecraft.me` is the whole blog.
- **Posts:**
  - the index's `posts` and `essays`, newest first (the site's own writing list);
  - `projects` (product pages) and `talks` (YouTube videos) are left out.
- **`fetch_latest(limit)`:** reads the index once, then the full post for the `limit` newest entries, one request each.
- **The post:**
  - url `https://<host>/<section>/<slug>`, external id `<section>/<slug>`;
  - the title and date (UTC midnight) from the API;
  - the whole HTML as the body, and its plain text;
  - its `<img>` URLs as media;
  - the section as its category.
- **`inspect`:** only the index, with no post read. The count is exact, and the oldest date comes from the index.
- **Archive:** `BaseSourceAdapter.index_pages`, 5 posts a page, resumable.
- **Tests:** `test_source_adapters.PipecraftAdapterTests`, with a fixture trimmed from the real API answers; plus a row in the resolution table, the kind count and `available_basis` in `test_source_kinds`.
- **Docs:** the kind list in `backend/insight_core/docs/CONNECTOR_DEVELOPMENT_GUIDE.md`.
- **No frontend change:** the Add-source dialog takes the URL as it is.

## How to add it
Sources → add an **RSS** source → paste `https://www.pipecraft.me/`. The kind is picked from the URL.

The blog has only 14 posts. To get them all at once, run one fetch-now with a limit of 20, or an archive.

## Limits
- **It breaks if the site changes its API.** A changed path or shape fails the source's fetch, and the source shows the error. Nothing breaks silently, but nothing adapts either.
- **Dates are days only** (UTC midnight). The API gives no time.
- **A post's YouTube video (`youtubeId`) is not kept.** The site shows it above the text, but the API's HTML doesn't include it.
- **Each fetch re-reads `limit` full posts**, one request each, as the other site adapters do. Keep `max_posts_per_fetch` small, for example 5.
- **The full-text repair skips this source**, because it isn't `generic_rss`. It doesn't need it: the body is already whole.
