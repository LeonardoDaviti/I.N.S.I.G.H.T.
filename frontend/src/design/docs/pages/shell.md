```meta
kind: page
routes: /design/*, /save, /markx, /markx/entities/:entityId, /markx/stories/:storyId, /markx/sources, /markx/sources/:sourceId
states: switcher-many-tracks, narrow-topbar
```

# Shell

Code: `components/layout/*` (`AppShell`, `TopBar`, `QuickSwitcher`, `navigation.ts`), `components/ThemeToggle.tsx`, `components/ui/{Dialog,Sheet,Toaster}.tsx`, `App.tsx`. Every route renders inside the shell (`system/information-architecture.md` holds the route map and redirects). It also claims `/design/*`, the Design Studio, which lives in the shell but in no nav: its source is `src/design/`, and how it works is `system/studio.md`; and `/save`, the save page (`pages/SavePage.tsx`, below), reached from the bookmarklet and ⌘K, never from the top bar; and `/markx`, Mark X Shadow's page (`pages/MarkXPage.tsx`, below, issue 0086 E), only while the server's `INSIGHT_MARKX` is on.

## Purpose

Wayfinding on every screen (P1): where am I (the current nav word), where can I go (the words and ⌘K), how do I get out (the wordmark returns to the feed). Plus the overlays every page shares.

## Entry & URL

- Always present. ⌘K / Ctrl+K anywhere (also from inputs) toggles the quick switcher; below 640px the `menu` button opens it.
- While a route's code loads, a quiet four-row skeleton sits in the page column. A page that throws shows the error boundary, which resets when the route changes.

## Anatomy

- **Skip link** "Skip to content" (visible on focus) to `main#main`.
- **Top bar** (sticky, translucent material, 3.5rem; on a phone with a notch it grows by `env(safe-area-inset-top)` and its bar sits under the notch, `--topbar-h` including it so every sticky band below follows, decision 045): the inverted `INSIGHT` wordmark (links to `/`); beside it the activity sign; at the right the lowercase slash nav (`feed / sources / blog`), the current word bold with a solid underline; a `go to ⌘K` button (Ctrl+K off Mac); the theme toggle (☾/☀). Its hairline appears only once content scrolls under it.
- **Activity sign** (P7): small `text-2` words beside the wordmark, on every page. While an ingestion run or archive job runs, the running glyph and `fetching · 3 of 41` (sources done of due; just `fetching` without a count); for an hour after the newest ingestion run failed, `last fetch failed`. It links to that job (`/settings/sources?tab=ingestion&sub=jobs&job=<id>`). Nothing when idle; the daily work doesn't count. It reads the operations overview, which polls every 5 seconds while a job runs and every 15 otherwise.
- **Quick switcher:** a dialog at 18vh, 34rem wide: a "Go to…" combobox with `esc`, then a listbox of destinations, each with its group in `text-3` (feed, tracks, sources, theme). The active option is the inverted block with ↵. Main feed, Later (`/?filter=later`, decision 029), By source, one entry per track (to `/read/folder/<id>`), Sources, Ingestion, Blog, "Save a page…" (group save, to `/save`), Design studio, then "Switch to light/dark theme", "Reading settings: font, size, width" (group settings; it opens a dialog with the post page's three choices over a sample paragraph, issue 0045, decision 033), and last, always, "Search posts…" (group search; with words typed, "Search posts for “…”", to `/search?q=…` over every post, decision 030). Design studio is the last destination, and absent inside a studio frame. When no place matches, the search entry is the one option, so Enter searches.
- **Save page** (`/save`, issue 0031): `PageHeader` "Save to INSIGHT" in the reading column. From the bookmarklet (`?url=…&title=…`) a bordered block with the page's title and its site (`example.com`), then primary **Save** and ghost Cancel (closes the tab); from ⌘K a "Page address" field (Enter saves) and, under a hairline, the bookmarklet line. Only Save saves: a POST from INSIGHT's own page, so no website can save by itself. After it, a notice: completion "Saved to INSIGHT" (`<title> is in Saved and in Later, unread. Read it`), warning "Saved, without its text" (the page couldn't be read as an article (HTTP 403); its title and link are kept in Saved and in Later), or status "Already in INSIGHT" (`It’s in Later. Read it`). Every save puts the post in Later at the time it was saved, and a new saved post is dated by that time, so it tops the feed (decision 029, issue 0022); then, when the site has a feed that is not a source, "This site has a feed. Follow it?" with its name and address and a Follow button (adds it as a source and fetches it now; then "Following <name>"); then "Close tab" (from the bookmarklet) or "Save another page".
- **Mark X** (`/markx`, issue 0086 E; the top bar's last word `mark x` and a ⌘K entry, both only while `GET /api/markx/on` answers; off, `/markx` lands on the feed): Haiku's stories beside Mark IX's, never read by the feed or News. `PageHeader` "Mark X" in the ops width, tabs news · briefing · entities · worker · labels. **news**: Mark X's News rows with an `only differences` switch (on); each row a tag chip (`new` inverted, `merged` / `split` / `changed` outlined, `same` quiet), its headline (Haiku's, else the lead's title), sources, its time and `+n` / `−n`; opened, each post with why it is there (Mark IX's rule, or Haiku's relation, p and words) and what Mark IX did with it, then Mark IX's posts it left out; Mark IX rows no longer News close the list; an opened row links `Perspectives and the story sheet`: `/markx/stories/<id>` (0119 B6-B7), the measured accuracy as its header (the lab's, then the owner's from 50 labels), the sheet (original or earliest report, the source page, new facts merged with their sources and corrections marked, before the release, unconfirmed claims, opinions, related, `N more say the same`), then the members worth opening (sign ★ + ~, label, who settled it, new facts one line each with their span, copies folded) and the rest folded under `N say the same`; ✓ / ✗ on each label (✗ offers the right label) and on each new fact (✗: not new / not true to the post / not about this story). **briefing**, **entities** (0119 A3: the review queue — two names, 2 posts each, the proposal and Haiku's evidence, buttons `same` / `other version` / `different` / `not an entity`, and the merges' history with `undo` — then one list over 30 days ranked like News: name, type, maker and exact version, sources and posts, its Mark X stories, its 3 newest posts (read ones dimmed, never hidden), `last seen`, a `surging` chip; each name opens `/markx/entities/<id>`: first its **Original** (issue 0138: the paper or release page its posts link, found by its identifier, its title or its maker's site; the stored post when INSIGHT has it, `· collected original` when Collect originals stored it, else the page with `· not collected yet`; then its code, demo and other pages as quiet links), and when no post's current reading names it, "Not named in any post's current reading. An earlier guide (ent-v3) named it in 2 posts:" with those posts linked, the words it was named by and what each post's current reading names instead (such an entity is in no list, queue item or edge); for an org, person or document with 2+ works or 10+ posts, **The rabbit hole** (issue 0138 E3): its sites, each `Followed ✓`, `Stored ✓`, **Follow** or **Watch page** (both open Add source on it: the feed finder, then page watching), its works, each `Stored ✓` (its post) or **Collect** (the save path), its people as links, and **Go down the rabbit hole** (collects every work not stored, then opens Add source on the first site you don't follow; nothing is followed without your tap there); then its posts by Mark X story then the loose ones, each with its role, its sources with counts, its family and versions as links; the header states the lab's measured accuracy), **worker** (the queue by kind, answers and their API price, failures, contacts, the last run and a `run the decisions now` button). On a post page a folded `Mark X` panel (lazy, loaded when opened): reading, entities, Mark X story and connections. Page and panel are their own chunks.
- **Bookmarklet line** (`components/BookmarkletHint.tsx`, on the save page and at the foot of Add source): `text-3`, "Save pages from any site: drag [Save to INSIGHT] to your bookmarks bar, then click it on a page you want to keep." The bordered link is the bookmarklet: it opens this INSIGHT's `/save` for the current page in a new tab (`noopener`).
- **Keyboard help** (`?`): a dialog with the single-key switch and the key table (Feed / Post page columns).
- **Design studio** (`/design`, ⌘K only, never in the top bar): its header, modes, Wall, walk, Bench and keys are described in `system/studio.md`.
- **Dialogs and sheets:** `Dialog` centred with a scrim; `Sheet` from the right; `ConfirmDialog` for destructive actions; toasts bottom, monochrome, with an action (Undo) where reversible, lifted above a phone's home bar (and clear of the landscape insets) by the safe area (decision 045). The page pads its sides by `env(safe-area-inset-left/right)`, so nothing sits under a notch in landscape; every inset is 0 off a phone.

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

- 002 hub deleted, 003 reading-only bar, 006 per-track ⌘K entries, 007 (amended) the bar shows a running fetch, 010 track entries open the reader, 029 Later in ⌘K, 030 ⌘K searches posts (`../decisions.md`); the studio's own decisions are listed in `system/studio.md`.

## Open issues

- None filed.
