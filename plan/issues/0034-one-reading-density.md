# 0034 — One reading density: comfortable only

Status: **built** 2026-10-28 (frontend only).

## The owner's wish
"I don't want to read compactly." The reader toolbar's `Density comfortable / compact` choice goes; comfortable is the only layout.

## Built
- **Toolbar:** no Density choice; `Show`, `View` and `Posts` stay.
- **Rows:** every row is the comfortable one: an excerpt line, a thumbnail at sm and up, `py-2` and `gap-2` between rows; source names middle-truncate at 56 characters.
- **Gone:** `FeedDensity`, `useDensityPreference` and the `density` props through `ReaderPage`, `FeedToolbar`, `FeedList`, `FeedGroup` and `FeedItem`, with the compact-only classes. An old stored `insight.reader.density` is simply never read.
- **Docs:** `pages/reader.md` (toolbar, row, truncation, 320px), decision 026.

## Not changed
Unrelated "compact" code stays: `compactAge` (Sources columns), run-report compaction, `RunCycleButton`'s small size, compact view counts on the post page.
