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
- **Top bar** (sticky, translucent material, 3.5rem): the inverted `INSIGHT` wordmark (links to `/`); at the right the lowercase slash nav (`feed / sources / blog`; with analysis on `feed / tracks / briefings / sources / ingestion / blog`), the current word bold with a solid underline; a `go to ⌘K` button (Ctrl+K off Mac); the theme toggle (☾/☀). Its hairline appears only once content scrolls under it.
- **Quick switcher:** a dialog at 18vh, 34rem wide: a "Go to…" combobox with `esc`, then a listbox of destinations, each with its group in `text-3` (feed, tracks, sources, theme). The active option is the inverted block with ↵. Reading-only: Unread, Starred, All posts, By source, one entry per track (to `/read/folder/<id>`), Sources, Source health, Ingestion, Design studio, then "Switch to light/dark theme". Design studio is the last destination with analysis on too. "No page matches “…”" when the filter finds nothing.
- **Keyboard help** (`?`): a dialog with the single-key switch and the key table (Feed / Post page columns).
- **Design studio** (`/design`, ⌘K only, never in the top bar): a sticky 3rem header under the top bar with the `handbook / wall / bench` segmented control (`?mode=`, ← → step it unless a field has focus); Handbook is the rail (studio · pages · prototypes · parked) beside the centred doc, with the specimen slot under page and parked docs.
- **Wall** (`/design?mode=wall`): the whole site as one wall (`wall/siteMap.ts`): eleven pages in use at their normal state, in navigation order (feed left, what it opens to its right), each a frame card captioned with its name (a link to its page doc), route and the P-numbers its doc cites. Quiet `border-strong` lines with arrowheads join them, each labelled on a pill by what moves you ("click a title", "source name", "⌘K"); a move to the next column curves through the gutter, across two columns it runs over the top. Above: P1–P12 chips (hover previews, a click keeps it in `?p=`; the pages whose doc cites it stay lit and outlined, the rest dim to 22%, and the rule and "n of 11 pages" show under the bar), `fixtures / live` (`?data=`) and `dark / light` (`?theme=`) for every frame, zoom out / fit (with the %) / in, and the `walk` toggle (`?walk=1`).
- **Walk** (the Wall's right 52%, `wall/walk.ts`): one 1280 × 800 interactive frame on fixtures replaying feed → post → back → source feed → source name → Sources sheet → close → ⌘K track → feed with real clicks and keys, at real speed with a 1.2s beat on each page; restart / play-pause / step icons, a status line (glyph + words, a failed step says why) and the eight steps with the current one inverted. The move being walked is drawn in `text` at 2.5px with an inverted label, its page outlined.
- **Dialogs and sheets:** `Dialog` centred with a scrim; `Sheet` from the right; `ConfirmDialog` for destructive actions; toasts bottom, monochrome, with an action (Undo) where reversible.

## States

- **switcher-many-tracks:** ⌘K with 40+ tracks and long names: the list scrolls inside `min(22rem, 60dvh)`, names truncate, the active option scrolls into view.
- **narrow-topbar:** at 320px the nav words and the `go to` button give way to the `menu` icon; wordmark, menu and theme toggle fit without wrapping.
- Also: scrolled (hairline on), analysis on (five words), route loading, route error.

## Interactions & keys

- ⌘K / Ctrl+K toggles; ↑/↓ move (wrapping), Enter goes, Esc closes; typing filters on label, group and keywords (every word must match). Hovering an option makes it active.
- The theme toggle and the switcher's theme entry flip dark ↔ light; the choice persists.
- `?` opens the shortcut help from the reader and the post.
- Wall: drag or scroll to pan, pinch or ⌘/Ctrl-scroll to zoom about the pointer (10–150%); on the focused map `+` `-` zoom and `0` fits. The view fits the wall until you move it, also when the walk panel opens. Frames are pictures (`pointer-events: none`) except the walk's.

## Worst cases

- Track names of 200 characters or in RTL scripts truncate in one line.
- No tracks: the switcher shows only the fixed entries.
- `GET /api/config` slow or failing: the bar shows the reading-only words (build flag fallback) and parked routes wait before redirecting.

## A11y & motion

- `header` with a `nav` labelled "Primary"; the current word is `aria-current="page"`. The switcher is a combobox + listbox with `aria-activedescendant`; the `go to` button has `aria-keyshortcuts`.
- The switcher never animates: it opens many times a day (P12). The Wall pans and zooms with one `transform` on the whole map, written per pointer event without React (1:1, no easing); buttons and `0` ease it in 240ms ease-out, instant under reduced motion. Only frames within 240px of the viewport mount, then stay. The walk's map highlight never animates; the pages inside the frame follow their own reduced-motion rules. Dialogs scale from 0.97 (200ms in, 150ms out), sheets slide; both fade under reduced motion. The bar turns solid under reduced transparency.

## Decisions

- 002 hub deleted, 003 reading-only bar, 006 per-track ⌘K entries, 010 track entries open the reader, 014 the Wall (`../decisions.md`).

## Open issues

- None filed.
