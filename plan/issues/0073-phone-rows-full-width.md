# 0073 — Phones: the title gets the row's full width

Status: **built** (2026-11-03, branch `issue-0073-phone`, not merged, not deployed); the WebKit / iPhone check of the safe areas left open. Owner, 2026-11-03: "yes, please do updates and checks for the phones only. and if you learned something new for desktop experience you can flag them as well." From a study of an open-source Android RSS reader's phone layout (`plan/research/readyou-mobile-ux.md`, private) and the v9.13 and v9.14 reader reviews' phone findings.

**Phones only (below `sm`).** Wide screens are unchanged, compared screen by screen. No new settings, no gestures (no swipe or long press), no new bars. Download nothing.

## The case
At 390 px the feed row's time column and its two 44 px buttons take about 45% of the width:
- titles get about 180–200 px ("Ternary-Bonsai-2-27B TQ1_0 or Gemma 4 12B it…");
- History rows read "darin… · 2 min read · publis…";
- News's line reads "4 sources (1 share) · H…";
- HN counts read "1,675 poin…".

## Decided
1. **The title runs across the full row.** The two buttons (read, later) move to the right of the meta and excerpt lines, keeping 44 px targets. The time leaves its column and joins the meta line: `r/LocalLLaMA · 11:09 · 1 min read`.
2. **News's coverage line may wrap to two lines,** so its names show: `▸ 8 sources (1 share) · in 1 roundup ·` / `Hacker News, seeall_notes, +6`.
3. **Hacker News counts take the second meta line** (like reposts and "published …"): `1,675 points · 1,628 comments`. The reading bar is no longer clipped.
4. **An open "covered by" tree uses the row's full width,** as the post page's already does. The one-indent and `↳ parent` rule stays.
5. **Safe areas:** the top bar, the sides and bottom toasts respect the notch and the home bar (`env(safe-area-inset-*)`), because `index.html` asks to draw edge to edge. Check on WebKit (Playwright's iPhone profile), not only Chromium.

## Done when
- Screens at 390 (and 360) before and after, light and dark, of: the Main feed, News, History, Later, a story's "covered by", search results, a thread, and a repost row.
- On each phone screen: no sideways overflow, every tap target at least 44 px, the title at least about 320 px wide on a 390-px screen.
- The same screens at 1400 are unchanged.
- Frontend tests updated; suites green; the bundle within budget (phone CSS only, almost no JS).
- A reader check at 390 in the owner's style, recorded in Built.

## Flag for desktop (not built here)
Recorded in Built as notes for a later issue, only where the study shows something INSIGHT's desktop lacks.

## Built (2026-11-03, branch `issue-0073-phone` from main 9954b2a, main e870b6d merged in; not merged, not deployed)
Frontend only, no migration. Measured with Playwright (Chromium; WebKit isn't installed here and nothing was downloaded) on the lab API (read-only: every non-GET request was aborted in the browser, nothing opened or marked), both builds served by `vite preview`, at 390 and 360 (touch) and 1400, light and dark. Shots in `/tmp`, not committed; the named rows read are in `plan/research/review-0073-phone.md` (private, written in the worktree).

### 1. The title runs across the row (commit a6da3cf, then 741800d, 0570a69)
- **Below `sm` the row is a grid** (`FeedItem.tsx`): the title spans it; the meta lines and the excerpt (or search's matching line) sit in the first column, the two actions (44 px on touch) beside them, vertically centred; a story's line and its open tree span the row. The time column is hidden.
- **The time joins the first meta line:** `source · 11:09 · 1 min read` (`Oct 27` where the row has no day header; the day header's name is still read out with it).
- **A second meta line** holds a repost's `↻ from @…`, a Hacker News item's counts and, for a started post, its length with the reading bar; **a third** a page's `published …` / `updated …`. No line starts on a dot.
- **From `sm` up nothing moves:** the meta line's parts are boxes with `display: contents` there, kept in their old order by `sm:order-*`, and every dot is shown where it was.
- **The source's 12-character floor (0070) is gone on a phone:** its line now holds only the time and the length, and the floor left a blank gap after names of 12–13 letters. A long name is cut before the length is; beside a short name (12 characters or fewer) the length may cut rather than run under the actions (360 px, three actions).

### 2. A story's line may take two lines (commit 4d8226b)
- `covered by …`, News's `N sources (…) · …` and `Thread · N posts` wrap to 2 lines below `sm` (left-aligned, the chevron on the first line, 44 px target kept: `py-3` makes one line 44 px and two lines 64 px); from `sm` up they truncate on one line as before.

### 3. Safe areas (commit fce1a63)
- `--topbar-h` is `3.5rem + env(safe-area-inset-top)` and the top bar pads its top by the inset, so every sticky band under it (the reader's title row, the post page's band, the rail) follows.
- The body pads its sides by `env(safe-area-inset-left/right)`.
- Toasts (sonner's `offset` / `mobileOffset`, its own 24 / 16 px plus the inset) and the Sources bulk bar sit above the home bar. Every inset is 0 off a phone.

### Measured, before → after (lab, the first 12 rows of each screen, 390 dark unless said)

| screen | title px | meta px | cut texts in the rows | overflow | buttons under 44 px |
|---|---|---|---|---|---|
| Main feed | 196 → **346** | 196 → 252 | 3 → 3 (a 16-character source) | 0 / 0 | 0 / 0 |
| Main, all | 150–196 → **346** | 150–196 → 206–252 | 6 → 3 | 0 / 0 | 0 / 0 |
| News | 180 → **346** | 180 → 252 | **12 → 2** (coverage lines, counts, a repost) | 0 / 0 | 0 / 0 |
| History | 150–196 → **346** | 150–196 → 206–252 | **8 → 0** (`published …`, `↻ from …`, HN counts) | 0 / 0 | 0 / 0 |
| Later | 134 → **346** | 134 → 206 | 3 → 0 | 0 / 0 | 0 / 0 |
| Search | 180 → **346** | 180 → 252 | 8 → 8 (long source names) | 0 / 0 | 0 / 0 |
| covered by, open | 196 → **346** (tree 196 → 346) | | | 0 / 0 | |
| News row, open | 180 → **346** (tree 180 → 346) | | | 0 / 0 | |
| a thread, open | 150 → **346** (tree 150 → 346) | | | 0 / 0 | |
| at 360, every screen | 104–166 → **316** | 104–166 → 176–222 | History 12 → 1; lengths cut on rows with three actions | 0 / 0 | 0 / 0 |

- **No meta-line text runs under the actions** on any screen at 390 or 360 (checked per row).
- **Row heights:** a row whose title now fits one line is shorter (108 → 84); a News row with its names on two lines is taller (154 → 170–174); a History row with HN counts or a repost and a `published` note gains a line (128 → 148). About the same number of rows per screen.
- **1400 unchanged:** the lab screens before and after are pixel-identical (24 of 26; 2 differ only inside thumbnail images). The design shots at 1400 (106 frames, main e870b6d against the branch, fixtures) differ only in clock text (the fixtures' relative times, shot a minute apart) and log timestamps.
- **Safe areas** (Chromium with CDP's safe-area override, an iPhone-sized page): portrait (top 47, bottom 34) — the top bar 56 → 103 px with the wordmark below the notch (y 14 → 61); a toast's bottom 828 → 794 px (it sat inside the 34 px home-bar zone). Landscape (sides 47, bottom 21) — the wordmark x 24 → 71 (it was under the notch), the page inset 47 px each side, a toast's right edge 820 → 773 and bottom 366 → 345.
- **Bundle (gzip):** the feed route 172,150 → 172,719 bytes (+569, class strings; 0.92% against the 171,142 baseline, under the check’s 1%), the post route 312,136 → 312,709 (+573).
- **Checks:** typecheck, lint, `node --test` (213), vitest (688; one new test for the phone row, three updated for the time now in two places) and `npm run build` green.

### Reader check at 390 (owner's style)
- **Built right:** titles read whole where they were cut at about 22 characters a line (a 62-character History title, two lines, was cut after 35 characters); every News row names who covered it (`8 sources (2 shares) · <name>, <name>, +6`, was `8 sources (2 shares) · …`); HN counts read whole in News and History; the reading bar is whole; trees use the row's width, so a tree line's title reads about 45 characters instead of 22; `↻ from @…` reads whole.
- **Still wrong:** a source name of 16+ characters is still cut on line 1 beside the time and length (a 16-character name reads 12 characters and `…`), as before; at 360 a row with three actions (in Later and read) cuts its length (`3 min …`).
- **Not this issue's:** a repost thread row's excerpt reads `Video` (0072 D's labels).

### Flag for desktop (not built)
- **A pointer way to catch up.** Read You's long press has "mark above / below as read" and a mark-all with conditions (`ArticleItem.kt`, `FlowPage.kt`; issues [#9](https://github.com/ReadYouApp/ReadYou/issues/9), [#962](https://github.com/ReadYouApp/ReadYou/issues/962)). INSIGHT's desktop has `Shift+A` only (decision 022), so a mouse-only reader can't catch up either, not only a phone. Needs an owner decision (it's a control, not a reading fix).
- **The day while scrolling.** Read You's day headers can stick (`StickyHeader.kt`). On desktop a row under a day header shows only `14:05`; once the header scrolls off, nothing on screen says the day. A sticky day header would cost about 24 px of sticky chrome; measure on a long day before deciding.
- Nothing else: Read You's faded read rows, tooltips on icon actions (#118) and next-article reach (#144) INSIGHT's desktop already has (weight and tone, `title` on every action, j/k and continuous reading).

## Left open
- **WebKit / a real iPhone.** No WebKit browser is installed here (Chromium and Firefox only) and nothing was downloaded, so the safe areas were checked with Chromium's override, not Safari: portrait, landscape and a home-screen install still need a WebKit or device check.
- **Sheets and dialogs** (the source sheet from the right, the quick switcher) don't pad for the landscape notch; only the page, the top bar, toasts and the bulk bar do.
- **A long source name on a phone** is still cut beside the time and length (about 12 characters at 390 for an unread row).
- **360 px with three actions:** the length cuts (`3 min …`); the row could move the length to the second line there, not done (no finding at 390).
