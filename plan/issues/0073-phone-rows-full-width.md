# 0073 — Phones: the title gets the row's full width

Status: **spec** (2026-11-03). Owner, 2026-11-03: "yes, please do updates and checks for the phones only. and if you learned something new for desktop experience you can flag them as well." From a study of an open-source Android RSS reader's phone layout (`plan/research/readyou-mobile-ux.md`, private) and the v9.13 and v9.14 reader reviews' phone findings.

**Phones only (below `sm`).** Wide screens are unchanged, compared screen by screen. No new settings, no gestures (no swipe or long press), no new bars. Download nothing.

## The case
At 390 px the feed row's time column and its two 44 px buttons take about 45% of the width:
- titles get about 180–200 px ("Ternary-Bonsai-2-27B TQ1_0 or Gemma 4 12B it…");
- History rows read "darin… · 2 min read · publis…";
- News's line reads "4 sources (1 share) · H…";
- HN counts read "1,675 poin…".

## Decided
1. **The title runs across the full row.** The two buttons (read, later) move to the right of the meta and excerpt lines, keeping 44 px targets. The time leaves its column and joins the meta line: `r/LocalLLaMA · 11:09 · 1 min read`.
2. **News's coverage line may wrap to two lines,** so its names show: `▸ 8 sources (1 share) · in 1 roundup ·` / `Hacker News, seeallochnaya, +6`.
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
