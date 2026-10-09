# Frontend UI guide (Mark IX)

What the user sees and how each surface behaves. The binding design language (tokens, type,
motion, status vocabulary, component inventory) is `plan/INSIGHT_mark_ix_design.md`; how to build
with it is `FRONTEND.md`. This replaces the Mark VIII guide, which described a colour-coded
"Database posts" briefing page that no longer exists.

## The shell

Every route renders under one top bar: the inverted `INSIGHT` wordmark, the lowercase slash nav
(`feed / tracks / briefings / sources / ingestion`) with the current word marked, the theme toggle,
and a Cmd/Ctrl+K switcher that only navigates. The bar is translucent; its hairline appears once
content scrolls under it. Dark is the default theme; light has parity.

## Feed (`/`, `/read/:scopeKind/:scopeId`)

- Opens on the unread feed of the main digest. The rail lists tracks and sources with unread
  counts; below `md` it is a drawer opened from the scope title.
- Rows: a muted date column, a bold title (wraps to two lines, never ellipsised to one), and a
  one-line meta with the source name (`sourceLabel()`, never a raw URL). Day headers group the rows.
  Read and star sit side by side and are always visible on touch.
- Toolbar: `unread / starred / all`, `stream / by source`, and density `comfortable / compact`
  (persisted), as slash-separated words.
- New posts never reorder the loaded list; a "N new posts" pill appears instead.
- Infinite scroll with a visible "Load more" fallback.
- Keyboard (`?` shows the table, and can switch single-key shortcuts off): `j`/`k` move,
  `o`/Enter open, `m` read, `s` star, `Shift+A` mark all read up to here (confirms, 5-second Undo),
  `f` fetch the current scope.

## Post (`/posts/:postId`)

A reading column of about 68ch: the full title, the original content first as wrapped prose
(monospace only for real code blocks), then the secondary panels collapsed. Prev/next follow the
feed order, carried in `?ctx=` so a reload keeps them; `u`/Esc returns to the feed with scroll and
selection restored. Opening a post marks it read.

## Sources (`/settings/sources`)

The source list with one primary "Add source", tracks, and the health tab
(`?tab=health`). The health table shows every source's status as glyph plus word, tier and
interval, next due, backoff, last success and last error, with `Fetch now` and a cadence override
per row. `?status=error` shows the failing sources (`error` and `backoff`). Deleting a source or a
track asks first and says what goes with it.

## Ingestion (`/ingestion`)

`Run due sources` runs what the next tick would; `Force all` ignores cadence and backoff after a
confirmation. Each run gets a readable run report (fetched, inserted, failed, per-source failures).
A stopped scheduler shows as one clear warning line, not quiet grey text. Raw payloads sit behind a
closed disclosure.

## Status words

Status is never colour alone: `ok`, `due`, `scheduled`, `backoff`, `failing`, `unavailable`,
`disabled`, `running`, plus `unread`, `read`, `starred` in the reader. Each has a glyph
(`StatusGlyph`).

## Analysis pages

Briefings, stories, inbox, vertical briefings and expert tracks share the same primitives. Under
the reading-only scope (spec §9) they will be hidden behind `INSIGHT_ANALYSIS=off`; that switch is
not built yet.
