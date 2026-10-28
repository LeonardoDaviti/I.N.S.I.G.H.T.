```meta
kind: page
routes: /, /read/:scopeKind/:scopeId?
states: normal, empty, empty-scope, loading, error, worst
```

# Reader

Code: `pages/ReaderPage.tsx`, `components/reader/*` (`ReaderNavRail`, `FeedToolbar`, `FeedList`, `FeedItem`, `FeedGroup`, `NewPostsPill`, `ShortcutHelp`).

## Purpose

The home of INSIGHT (P1): the posts to read, newest first, scoped to everything, one track or one source. It reads; it never fetches (P7).

## Entry & URL

- `/` is the Main feed: its unread posts from the sources shown in it. `/read/:scopeKind/:scopeId?` scopes it: `/read/folder/<id>` (a track), `/read/source/<id>` (a source). An unknown scope kind redirects to `/`.
- `/tracks/:id` redirects (replace) to `/read/folder/:id` (decision 010).
- Query: `?filter=unread|later|starred|all` (unread is the default and stays out of the URL; `starred` is Kept), `?view=stream|by_source`, dev-only `?data=worst|empty|one|huge`. Density (`comfortable / compact`) persists locally, not in the URL.
- Reached from the wordmark, the `feed` nav word, the rail, ⌘K (Main feed, By source, one entry per track) and Back from a post. ⌘K also reaches Later. Old links keep working: `/?filter=starred` opens the main feed with Show kept.

## Anatomy

- **Rail** (md and up, sticky under the top bar, 15–16rem): Main feed with its icon (the sources in the main feed; Later, Kept and All are Show choices, not places); `tracks` with unread counts; `sources with unread` (top 12, most unread first) with a filter field over every source and "Show all N sources". Below md the same content is a drawer opened from the scope title.
- **Toolbar** (sticky material): the scope title (`Main feed`, a track or a source; `display`-ish, truncates) and its unread count in `text-3` (not under Show later or kept, where it says nothing; the Main feed's Later says what it costs instead: `Later · 6 posts · 52 min`); a `shortcuts ?` text action. With a track or source scope, the title is a quiet link to that track or source in Sources (P8). Below it, slash-separated words: `Show unread / later / kept / all`, `View stream / by source`, `Density comfortable / compact` (md and up), `Posts continuous / one at a time` (every width; stored as `insight.reader.flow`, it sets how the post page goes on after a post, `pages/post.md`), and the "N new posts" pill at the right when posts arrived. One source shows neither View (it has nothing to group by source; `?view=by_source` is ignored) nor Posts.
- **Stopped notice** above the list when no enabled source was fetched for a day (P11).
- **Later line** (Main feed only, not under Show later): while Later holds anything, one quiet `small` `text-2` link at the top of the list, `Later · 6 posts · 52 min` (the posts' `N min read` and video lengths added up), to `/?filter=later`. Nothing when Later is empty (decision 025).
- **List**, stream view: day headers, then bordered rows. A row: time column (`14:05`, under its day header) in `text-3` tabular nums; title (2 lines max, weight 600 unread, 400 and `text-2` read); one meta line (unread dot, a small clock if in Later, ★ if kept, source name via `sourceLabel()`, never a URL, a quiet link that reads that source at `/read/source/<id>`, left out on that source's own page, and the length: `4 min read` or a video duration); one excerpt line in comfortable density; a greyscale thumbnail at sm and up; two icon actions, the read circle ○/✓ and one save: 🕓 Read later on an unread row, ☆ Keep on a read one; a save already on keeps its button (pressed), so it can be undone by hand (decision 025). Mark read up to here is `Shift+A` only (decision 022).
- **List**, Show later: the posts in Later, oldest saved first, with no day headers (each row shows its date). A Later post is in Unread too. Main feed's Later holds every source's, not only the main feed's.
- **List**, by-source view: one section per source, its name linking to that source's scope, up to 3 rows, then "N more from <source> →".
- **Foot:** an infinite-scroll sentinel, a visible "Load more" button, or "You've reached the end."
- The list column is `max-w-5xl`, left-aligned next to the rail.

## States

- **normal:** unread rows under day headers.
- **empty:** nothing unread: "You're all caught up" + "Show all". Later: "Nothing in Later" ("Press l on a post, or its clock button, to read it later. Finishing it takes it out."). Kept: "No kept posts". All, nothing at all: "No posts yet" + "Add a source". When ingestion has stopped, the unread empty state says "No new posts: ingestion has stopped" instead of "caught up" (P11).
- **empty-scope:** a track or source with no posts: "No posts here yet. Posts appear once ingestion collects them." + a quiet "This track/source in Sources" link (P7).
- **loading:** a six-row skeleton in the list column; rail lines read "Loading…".
- **error:** `ErrorState` "Could not load the feed" with Retry; a failed next page is an inline error `Notice` with Retry, keeping the loaded rows. Tracks that fail in the rail say "× Could not load tracks."
- **worst:** long and unbroken titles, non-Latin and RTL text, missing titles ("Untitled post" when the API has no text to make one from), 1,000+ unread counts, huge source names (dev `?data=worst` / `huge`).

## Interactions & keys

- `j`/`k` move the selection (loads more at the end), `o`/Enter open (marks read), `m` read, `l` read later, `s` keep (the star), `Shift+A` mark read from the top down to the selection (confirm dialog, then a toast with Undo for 5 s; not in Later, whose order is not the feed's), `?` the shortcut table with the single-key switch.
- Read, Later and Keep are optimistic; failures roll back with a toast.
- **Later never expires.** A post leaves it when finished: its end reached on the post page, or marked read (the circle, `m`). Opening it does not (even though opening marks it read), nor does `Shift+A` (catching up is not finishing), nor marking it unread again. `l` or the clock take it out by hand.
- New posts never reorder the loaded list; the pill reloads and scrolls to the top. The unread counts (pill and rail) are checked every 10 seconds while a fetch job runs and every 60 otherwise, never in a hidden tab, and a run saves each source as it is fetched, so the pill appears while posts arrive.
- Hovering a row reveals its actions instantly with a mouse; on touch and on the selected row they always show.
- Back from a post selects and scrolls to the post read last.
- Rail links keep `view` and a non-default `filter`.

## Worst cases

- Titles wrap to 2 lines and never ellipsise at 1 (`[overflow-wrap:anywhere]`, `line-clamp-2`); `dir="auto"` on titles and excerpts.
- Source names middle-truncate (56 chars, 32 compact; 26 in the rail) with the full name in `title`.
- Counts use `formatCount` (`1,284`) and never truncate; the scope title truncates, its count does not.
- A deleted source with posts has no rail row; its posts stay in the main feed.
- 320px: the toolbar's count moves under the title; density hides; actions are 44px.

## A11y & motion

- The stream is an ARIA `feed` of `article`s with `aria-posinset`/`aria-setsize`; day headers are `aria-hidden` and each row reads its day with its time. By-source groups are labelled `section`s.
- Roving tabindex: one row is a tab stop; selection is `aria-current`. Every icon button has a label and a title with its key.
- Results (read, "Saved for later" / "Removed from Later", "Kept" / "No longer kept", marked N posts) are announced in a polite live region.
- No motion on j/k, hover, filters or rail (P12). The pill and the drawer get one short ease-out; the drawer leaves the way it came.

## Decisions

- 002 hub deleted, 003 reading-only, 007 fetching out of the reader, 010 track page into the reader, 011 names link into Sources, 022 a row's source name reads the source and its one read button is the circle, 025 read later and keep (`../decisions.md`).

## Open issues

- [0002](../../../../../plan/issues/0002-track-briefing-reading.md): a track briefing in the folder scope, rebuilt in Mark X (the old one is at the tag `mark-ix-analysis-archive`).
- [0005](../../../../../plan/issues/0005-minimal-codebase.md): keep what reading uses, retire the rest.
