# 0061 — Smooth loading: no broken tab after a deploy, no wait on the first post, a budget that measures what you wait for

Status: **spec** (2026-10-31) for v9.8 (owner, 2026-10-31: "decide what is the best practice from engineering side and then think from the UI/UX side, nothing should fail and everything should work very smoothly").

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
