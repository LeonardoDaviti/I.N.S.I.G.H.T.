# 0061 — Smooth loading: no broken tab after a deploy, no wait on the first post, a budget that measures what you wait for

Status: **built, not deployed** (2026-10-31) for v9.8 (owner, 2026-10-31: "decide what is the best practice from engineering side and then think from the UI/UX side, nothing should fail and everything should work very smoothly").

## The case (measured on main, `vite build`)
- **The feed's first download** is ~480 KB raw, about **160 KB compressed** (`index` 424 KB / 135 KB gzip, plus the reader page and the rail).
- **The first post you open** downloads the post page (75 KB / 27 KB gzip) and the text renderer (`MarkdownRenderer`: 340 KB / 103 KB gzip, which is react-markdown, remark-gfm, rehype-raw and rehype-sanitize). That's **~130 KB compressed**, only when you click. News, Classics, search and Sources also load on first use.
- **A deploy can break an open tab.** Each build renames the code files. A tab opened before `./update` asks for the old names, gets 404, and the lazy page throws into the error screen. There is no `vite:preloadError` handling. `index.html` has no `Cache-Control: no-cache`, while assets are cached `immutable` for a year, which is right for them.
- **The budget** (`scripts/bundle-check.mjs`, `src/lib/bundleBudget.ts`) checks **raw** bytes of the feed's first download only, against a baseline (475,065), with a 1% limit. It ignores the post route, and its raw-byte margin pushed 0055 to duplicate code to save ~300 bytes.

## Decided
1. **The budget measures what you wait for:**
   - **compressed (gzip) bytes** of two routes' first downloads: opening the feed (`/`), and opening a post (`/posts/:id`, the feed's files plus the post page's own);
   - **1% within a release:** the baseline is reset at each release with `--update` and the reason in the commit;
   - **a ceiling that never resets:** either route over **110% of the v9.8 baseline** fails the build, whatever the current baseline.
   - Record both sizes in `bundle-baseline.json`. The check prints both routes.
2. **A stale tab recovers by itself.** On `vite:preloadError` (a missing chunk after a deploy), the app reloads **once**, guarded in `sessionStorage` so it can never loop. If the reload doesn't help, the error screen says "INSIGHT was updated, reload" with a button.
   - nginx serves `index.html` with `Cache-Control: no-cache`, in the repo's `frontend/nginx.conf`. Hashed assets stay `immutable`.
3. **Load ahead when idle.** After the feed has rendered and the browser is idle (`requestIdleCallback`, with a timeout fallback), prefetch the chunks of the post page (with the renderer), News and Classics. Don't block the feed or compete with it. Skip it when the connection says `saveData`.
4. **No visible change otherwise:** no new UI and no new settings.

## Measured (recorded here)
- **Cold first-post open:** Playwright on a production build, with the network throttled to "Fast 3G" and a cache that starts empty. Measure the time from clicking a feed row to the post's title on screen, before and after. Expect it to drop because of prefetching; record the numbers.
- **Stale tab:** build A, open the feed, deploy build B (other hashes, A's files gone), click a post. Before: the error screen. After: one reload, then the post. Recorded.
- **Sizes:** both routes' gzip sizes before and after.

## Done when
- **Tests:**
  - the budget logic for gzip, two routes and the ceiling (unit);
  - the reload guard: one reload, never two (unit);
  - prefetch only after the feed renders, and not with `saveData` (unit).
- **The measurements above** are recorded.
- **Frontend checks** green; the new budget passes, with its baseline set in this issue and the reason given.

## Built
- **A stale tab recovers by itself.** `main.tsx` listens for `vite:preloadError`; `reloadOnce` (`src/lib/staleTab.ts`) says yes once and records `{from: build, at}` in `sessionStorage`. It refuses when the last reload was under a minute ago, or when the reload brought back the same build (a cached `index.html`). So a reload that doesn't help never loops, and a later deploy in the same tab still recovers. When it refuses, the error screen (`AppErrorBoundary`) recognises a chunk error and says **"INSIGHT was updated"**, "Reload to get the new version", with a **Reload** button. Before, it said "Could not reach the backend", which was wrong.
- **nginx** (`frontend/nginx.conf`): `expires -1;` in `location /`, so `index.html` (and every SPA route) is sent with `Cache-Control: no-cache`. It uses `expires`, not `add_header`, because a location's `add_header` would drop the server's security headers. Checked with curl: `/` and `/posts/x` send `no-cache` plus the three security headers, and `/assets/*.js` stays `public, immutable`. **The preview's `~/.config/insight/nginx-preview.conf` needs the same line in its `location /`.** It's the owner's local file, so it wasn't edited.
- **Load ahead** (`src/lib/loadAhead.ts`, wired in `ReaderPage`): once the feed's list query has succeeded (any data for News and Classics) and nothing is fetching, `requestIdleCallback` (timeout 5 s, or `setTimeout` 2 s where it's missing) imports the post page with its renderer, then News, then Classics. They load one after another, once per page load. It's skipped when `navigator.connection.saveData` is set. A chunk that fails here loads again when its page is opened. It subscribes to the query cache, so ReaderPage doesn't re-render for it.
- **The budget** (`src/lib/bundleBudget.ts`, `scripts/bundle-check.mjs`) now measures **gzip bytes** (level 9, as Vite's report), JS and CSS. It checks two routes:
  - **feed:** the entry and `ReaderPage` with their static imports;
  - **post:** the feed's files plus `PostDetailPage`'s, each file counted once.
  - Each route may grow 1% over `gzipBytes`, which `--update` resets each release. Each must also stay under **110% of `ceilingBase`**, which `--update` never touches. The check prints both routes.
- **The new baseline** (`bundle-baseline.json`): feed **169,520**, post **308,512** gzip bytes. These are also the v9.8 ceiling base, so the ceilings are 186,472 and 339,363. The reason: the old baseline was raw JS of one route, so it can't be compared. The sizes are this build's: the guard, the error text and the prefetch add **+785 gzip bytes** to the feed (0.47%) and the same to the post route.

### Measured
A production build was served by `nginx:alpine` with the repo's `nginx.conf` (gzip on), and the API was mocked (30 posts, one ~20-section post). Playwright Chromium was used, with a cold context each run.
- **Cold first-post open** on Fast 3G (CDP `Network.emulateNetworkConditions`: 562.5 ms, 1.44 Mbit/s down). The time runs from clicking the first row, 8 s after the feed showed, to the post's `h1`, median of 3. **Before: 2,320 ms** (2,317 to 2,332). **After: 809 ms** (800 to 815). What's left is the post's own API request. The feed's first paint is unchanged (about 4.5 to 5.0 s, both).
- **Stale tab.** Build A was served and the feed opened, then A's files were deleted and build B copied in, then a post was clicked.
  - **Before** (A = main at 78d2b10, B = this branch): 10 chunks returned 404, and the error screen said "This page hit an error. Could not reach the backend".
  - **After** (A = this branch, B = a rebuild with one changed string): the post opened with no reload, because loading ahead had already fetched its chunks. With loading ahead off (`saveData`): the same 10 chunks returned 404, then **one reload, then the post**. With a reload already recorded seconds before: no reload, and the screen said **"INSIGHT was updated. Reload to get the new version."**
- **Sizes (gzip):**

  | Route | Before | After |
  |---|---|---|
  | Feed | 168,735 | 169,520 |
  | Post | 307,727 | 308,512 |

  Raw bytes for comparison: feed 533,112 to 534,990, post 972,024 to 973,902. The old check counted JS only: 479,685.
- **Tests:** `bundleBudget.test.ts` covers CSS, both routes, the 1% on each, and a ceiling that fails even when the baseline passes. `staleTab.test.ts` covers one reload and never two, the same build, a later deploy, a broken record and the error kinds. `loadAhead.test.ts` covers nothing before the feed, in order when idle, nothing with `saveData`, and a failure not stopping the rest. `npm run typecheck`, `npm test` (192 node and 646 vitest), `npm run lint` and `npm run build` with the new budget are green.

## Left open
- **The preview's nginx config** (`~/.config/insight/nginx-preview.conf`) needs `expires -1;` in `location /`.
- **Parallel branches** (0056, 0060) still carry the old `bundle-baseline.json` format. Whichever merges after this one takes this file and runs `npm run bundle:baseline`, with the reason in the commit. It must not touch `ceilingBase`.
- **A deploy in the first seconds after a page load,** before loading ahead runs, makes its failed import trigger the one reload while the reader is on the feed. That's rare and harmless, but visible.
- **Other lazy pages** (Sources, search, the blog, the settings dialogs) aren't loaded ahead. In a stale tab they recover through the reload.
