```meta
kind: page
routes: /design/*, /save
states: switcher-many-tracks, narrow-topbar
```

# Shell

Code: `components/layout/*` (`AppShell`, `TopBar`, `QuickSwitcher`, `navigation.ts`), `components/ThemeToggle.tsx`, `components/ui/{Dialog,Sheet,Toaster}.tsx`, `App.tsx`. Every route renders inside the shell (`system/information-architecture.md` holds the route map and redirects). It also claims `/design/*`, the Design Studio, which lives in the shell but in no nav: its source is `src/design/`, and how it works is `system/studio.md`; and `/save`, the save page (`pages/SavePage.tsx`, below), reached from the bookmarklet and ⌘K, never from the top bar.

## Purpose

Wayfinding on every screen (P1): where am I (the current nav word), where can I go (the words and ⌘K), how do I get out (the wordmark returns to the feed). Plus the overlays every page shares.

## Entry & URL

- Always present. ⌘K / Ctrl+K anywhere (also from inputs) toggles the quick switcher; below 640px the `menu` button opens it.
- While a route's code loads, a quiet four-row skeleton sits in the page column. A page that throws shows the error boundary, which resets when the route changes.

## Anatomy

- **Skip link** "Skip to content" (visible on focus) to `main#main`.
- **Top bar** (sticky, translucent material, 3.5rem): the inverted `INSIGHT` wordmark (links to `/`); beside it the activity sign; at the right the lowercase slash nav (`feed / sources / blog`), the current word bold with a solid underline; a `go to ⌘K` button (Ctrl+K off Mac); the theme toggle (☾/☀). Its hairline appears only once content scrolls under it.
- **Activity sign** (P7): small `text-2` words beside the wordmark, on every page. While an ingestion run or archive job runs, the running glyph and `fetching · 3 of 41` (sources done of due; just `fetching` without a count); for an hour after the newest ingestion run failed, `last fetch failed`. It links to that job (`/settings/sources?tab=ingestion&sub=jobs&job=<id>`). Nothing when idle; the daily work doesn't count. It reads the operations overview, which polls every 5 seconds while a job runs and every 15 otherwise.
- **Quick switcher:** a dialog at 18vh, 34rem wide: a "Go to…" combobox with `esc`, then a listbox of destinations, each with its group in `text-3` (feed, tracks, sources, theme). The active option is the inverted block with ↵. Main feed, Later (`/?filter=later`, decision 029), By source, one entry per track (to `/read/folder/<id>`), Sources, Ingestion, Blog, "Save a page…" (group save, to `/save`), Design studio, then "Switch to light/dark theme". Design studio is the last destination, and absent inside a studio frame. "No page matches “…”" when the filter finds nothing.
- **Save page** (`/save`, issue 0031): `PageHeader` "Save to INSIGHT" in the reading column. From the bookmarklet (`?url=…&title=…`) a bordered block with the page's title and its site (`example.com`), then primary **Save** and ghost Cancel (closes the tab); from ⌘K a "Page address" field (Enter saves) and, under a hairline, the bookmarklet line. Only Save saves: a POST from INSIGHT's own page, so no website can save by itself. After it, a notice: completion "Saved to INSIGHT" (`<title> is in Saved and in Later, unread. Read it`), warning "Saved, without its text" (the page couldn't be read as an article (HTTP 403); its title and link are kept in Saved and in Later), or status "Already in INSIGHT" (`It’s in Later. Read it`). Every save puts the post in Later at the time it was saved, and a new saved post is dated by that time, so it tops the feed (decision 029, issue 0022); then, when the site has a feed that is not a source, "This site has a feed. Follow it?" with its name and address and a Follow button (adds it as a source and fetches it now; then "Following <name>"); then "Close tab" (from the bookmarklet) or "Save another page".
- **Bookmarklet line** (`components/BookmarkletHint.tsx`, on the save page and at the foot of Add source): `text-3`, "Save pages from any site: drag [Save to INSIGHT] to your bookmarks bar, then click it on a page you want to keep." The bordered link is the bookmarklet: it opens this INSIGHT's `/save` for the current page in a new tab (`noopener`).
- **Keyboard help** (`?`): a dialog with the single-key switch and the key table (Feed / Post page columns).
- **Design studio** (`/design`, ⌘K only, never in the top bar): its header, modes, Wall, walk, Bench and keys are described in `system/studio.md`.
- **Dialogs and sheets:** `Dialog` centred with a scrim; `Sheet` from the right; `ConfirmDialog` for destructive actions; toasts bottom, monochrome, with an action (Undo) where reversible.

## States

- **switcher-many-tracks:** ⌘K with 40+ tracks and long names: the list scrolls inside `min(22rem, 60dvh)`, names truncate, the active option scrolls into view.
- **narrow-topbar:** at 320px the nav words and the `go to` button give way to the `menu` icon; wordmark, menu and theme toggle fit without wrapping, and the activity sign truncates rather than wraps.
- Also: scrolled (hairline on), route loading, route error, fetching (the activity sign), last fetch failed; the save page's confirm, saving, saved, unreadable, already and feed-offered.

## Interactions & keys

- ⌘K / Ctrl+K toggles; ↑/↓ move (wrapping), Enter goes, Esc closes; typing filters on label, group and keywords (every word must match). Hovering an option makes it active.
- The theme toggle and the switcher's theme entry flip dark ↔ light; the choice persists.
- `?` opens the shortcut help from the reader and the post.

## Worst cases

- Track names of 200 characters or in RTL scripts truncate in one line.
- No tracks: the switcher shows only the fixed entries.
- A saved page with a 300-character title or no title: the block wraps it, or names the page by its site.

## A11y & motion

- `header` with a `nav` labelled "Primary"; the current word is `aria-current="page"`. The switcher is a combobox + listbox with `aria-activedescendant`; the `go to` button has `aria-keyshortcuts`.
- The switcher never animates: it opens many times a day (P12). Neither does the activity sign: it is static words and a glyph. Dialogs scale from 0.97 (200ms in, 150ms out), sheets slide; both fade under reduced motion. The bar turns solid under reduced transparency.

## Decisions

- 002 hub deleted, 003 reading-only bar, 006 per-track ⌘K entries, 007 (amended) the bar shows a running fetch, 010 track entries open the reader, 029 Later in ⌘K (`../decisions.md`); the studio's own decisions are listed in `system/studio.md`.

## Open issues

- None filed.
