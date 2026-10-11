```meta
kind: page
routes: /design/*
states: switcher-many-tracks, narrow-topbar
```

# Shell

Code: `components/layout/*` (`AppShell`, `TopBar`, `QuickSwitcher`, `navigation.ts`), `components/ThemeToggle.tsx`, `components/ui/{Dialog,Sheet,Toaster}.tsx`, `App.tsx`. Every route renders inside the shell (`system/information-architecture.md` holds the route map and redirects). It also claims `/design/*`, the Design Studio, which lives in the shell but in no nav: its source is `src/design/` and its rules are the docs it shows.

## Purpose

Wayfinding on every screen (P1): where am I (the current nav word), where can I go (the words and ⌘K), how do I get out (the wordmark returns to the feed). Plus the overlays every page shares.

## Entry & URL

- Always present. ⌘K / Ctrl+K anywhere (also from inputs) toggles the quick switcher; below 640px the `menu` button opens it.
- While a route's code loads, a quiet four-row skeleton sits in the page column. A page that throws shows the error boundary, which resets when the route changes.

## Anatomy

- **Skip link** "Skip to content" (visible on focus) to `main#main`.
- **Top bar** (sticky, translucent material, 3.5rem): the inverted `INSIGHT` wordmark (links to `/`); at the right the lowercase slash nav (`feed / sources`; with analysis on `feed / tracks / briefings / sources / ingestion`), the current word bold with a solid underline; a `go to ⌘K` button (Ctrl+K off Mac); the theme toggle (☾/☀). Its hairline appears only once content scrolls under it.
- **Quick switcher:** a dialog at 18vh, 34rem wide: a "Go to…" combobox with `esc`, then a listbox of destinations, each with its group in `text-3` (feed, tracks, sources, theme). The active option is the inverted block with ↵. Reading-only: Unread, Starred, All posts, By source, one entry per track (to `/read/folder/<id>`), Sources, Source health, Ingestion, Design studio, then "Switch to light/dark theme". Design studio is the last destination with analysis on too. "No page matches “…”" when the filter finds nothing.
- **Keyboard help** (`?`): a dialog with the single-key switch and the key table (Feed / Post page columns).
- **Design studio** (`/design`, ⌘K only, never in the top bar): a sticky 3rem header under the top bar with the `handbook / wall / bench` segmented control (`?mode=`, ← → step it unless a field has focus); Handbook is the rail (studio · pages · prototypes · parked) beside the centred doc, with the specimen slot under page and parked docs.
- **Dialogs and sheets:** `Dialog` centred with a scrim; `Sheet` from the right; `ConfirmDialog` for destructive actions; toasts bottom, monochrome, with an action (Undo) where reversible.

## States

- **switcher-many-tracks:** ⌘K with 40+ tracks and long names: the list scrolls inside `min(22rem, 60dvh)`, names truncate, the active option scrolls into view.
- **narrow-topbar:** at 320px the nav words and the `go to` button give way to the `menu` icon; wordmark, menu and theme toggle fit without wrapping.
- Also: scrolled (hairline on), analysis on (five words), route loading, route error.

## Interactions & keys

- ⌘K / Ctrl+K toggles; ↑/↓ move (wrapping), Enter goes, Esc closes; typing filters on label, group and keywords (every word must match). Hovering an option makes it active.
- The theme toggle and the switcher's theme entry flip dark ↔ light; the choice persists.
- `?` opens the shortcut help from the reader and the post.

## Worst cases

- Track names of 200 characters or in RTL scripts truncate in one line.
- No tracks: the switcher shows only the fixed entries.
- `GET /api/config` slow or failing: the bar shows the reading-only words (build flag fallback) and parked routes wait before redirecting.

## A11y & motion

- `header` with a `nav` labelled "Primary"; the current word is `aria-current="page"`. The switcher is a combobox + listbox with `aria-activedescendant`; the `go to` button has `aria-keyshortcuts`.
- The switcher never animates: it opens many times a day (P12). Dialogs scale from 0.97 (200ms in, 150ms out), sheets slide; both fade under reduced motion. The bar turns solid under reduced transparency.

## Decisions

- 002 hub deleted, 003 reading-only bar, 006 per-track ⌘K entries, 010 track entries open the reader (`../decisions.md`).

## Open issues

- None filed.
