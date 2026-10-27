# 0029 — Review fixes: correctness and overengineering in 0b1458d..1c07573

Status: **open** (two read-only reviews, 2026-10-27). Owner picks; recommended set marked ★.

## Correctness (code review; each reproduced or traced to file:line)
1. ★ **Stale feed-finder answer overwrites typing** (`AddSourceModal.tsx:302-318`): type `a.com`, pause, keep typing; the `a.com` answer replaces the field. Drop answers whose address is no longer current.
2. ★ **One dropped connection fails a whole page-watch fetch**: `KindHttp._classified` (`http.py:52`) doesn't wrap `OSError`/`http.client.HTTPException` (RemoteDisconnected, IncompleteRead…), so they escape `PageWatchKind._page`; the source backs off every fetch, preview gives 500. Map them to `HttpError` (fixes every kind).
3. ★ **One malformed link breaks page watch and the finder**: `urljoin` raises `ValueError` on `href="http://[x/"` (`page_watch.py:73,117`, `feed_finder.py:243`). Skip bad hrefs.
4. ★ **Tag/category/pagination pages become posts**: the first `<time datetime>` anywhere dates the page (`page_watch.py:171`); worse since 1c07573. Without meta/JSON-LD date require one distinct `<time>` (as the written-date rule), or `og:type=article`.
5. ★ **The "no post" memory lasts one run** (a new registry per run; `ingestion/__init__.py:71`), failed pages are never remembered, and both count toward the read cap: category pages re-read every fetch, and 25+ skipped candidates ahead of a new article hide it. Persist skipped URLs in the source's fetch state (or drop the memory) and don't count skips toward the cap. The test reuses one instance and hides this.
6. ★ **Feed finder leaks threads/sockets past its 10 s budget** (`wait_for` can't stop `to_thread`; a slow-drip server kept 3 sockets 40 s+), on the shared default executor. Wall-clock deadline in `_get_start_sync` and a small own executor.
7. **A 429 mid-fetch throws away posts already read** (`page_watch.py:290`, runner retry): return the partial list when ≥1 post was read.
8. **Preview has no overall budget; sitemaps are parsed whole** (`get_text` + `ET.fromstring`, up to 5 × 50 MB per live fetch). `asyncio.timeout` on preview; `get_start` with a few-MB cap + `iterparse`.
9. ★ **Security: the two new routes are a synchronous fetch proxy** with no auth: error bodies (first 200 bytes) come back as 400 detail (`http.py:58`); `file://` is accepted by preview (file-existence oracle); robots `Sitemap:` can steer to internal hosts. Allow only http/https in `preview` and `KindHttp`; keep bodies out of user-facing detail; optional private-IP refusal.
10. ★ **1c07573 regression**: `extract_article_html` now falls back to `<body>` when `<article>` is short, so generic RSS full text can replace a short post with the whole page (related lists included). Fall through only past candidates under the size *and* keep the body fallback for when no candidate matched — i.e. try `<article>`/`<main>`/content divs in turn, but never the whole body when a candidate matched.
11. **sources.json doesn't carry `settings.page_watch`**: a rebuild from sources.json brings followed pages back as broken generic RSS. Export/import it.
12. ★ **Old `max_posts_per_fetch` values still enforced, invisible**: one SQL step `settings - 'max_posts_per_fetch'` (a migration) + `BACKEND.md` fix.
13. Nit: `?status=backoff` filters with no chip shown; map to Failing.
14. Nit: first JSON-LD/`<time>` may belong to a related card; a written date in prose may date the post.
15. Nit: `page_watch` can't be cleared via settings (deep merge).
16. Test gaps for 1–7.

Solid: XML (expat blocks billion laughs, no external entities), the finder's budget/grace/fan-out, the Path preview's debounce, track main-feed derivation, archive resume.

## Overengineering (check against 0005; ~360 lines in clear wins)
17. ★ Reddit comments backend orphaned since 0027 removed its button (route, job, cache, JSON scraper; `main.py:309,500-589`, `post_detail_service.py:157-193`, `reddit.py:160-205`). Keep showing stored comments. ~130 lines.
18. ★ Add source's YouTube path can never run (the only caller passes `platform="rss"`), with its `listYouTubeChannelVideos` client, route and service. Drop the `platform` prop and branch. ~100 lines.
19. ★ Template shape bigger than its data (`defaultSettings` one key, fallbacks that never trigger, `fixedHandle` testing `buildHandle('a')==('b')` instead of `!variableName`). ~35 lines.
20. ★ page_watch skip memory (see 5). ★ Always-`'enabled'` state field in the dialog. ★ "add https" written three times; origins built by hand next to `parsing.origin_from_source`. ★ Small leftovers: try/except around an int parse, `getattr(kind,"archive_refused")`, one-use `read_page`, one-child grid, `tier`/`CadenceTier` only in fixtures.
21. Judgement: the finder's proof loop (could be `gather`, but may wait 5 s longer); the dialog's preview state; moving `TEMPLATES` to a data file; the run summary written in both backend and frontend; the version "out of step" formatting; the API still accepting `priority`; two link-extraction styles (merge when retiring adapters, 0028 "Later"); the `?status=backoff`/`?group=platform` shims.
