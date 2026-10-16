# 0011 — Sources list: sort by clicking a column, find the newest source, read a source from its row

Status: **built** 2026-10-16, not yet deployed (owner observations on the server, 2026-10-16). UX.

## Problem Statement
- **Sorting hides in a dropdown.** The list has column headers (Name, Kind, Posts, Last post, Status) but they are plain text. Sorting is a separate "Sort" dropdown, and its "Last success" sorts by the last fetch, not by the "Last post" column on screen.
- **I can't find the source I added last.** There is no sort by date added; the list's API doesn't even send it.
- **"Not in a track" bothers me.** Grouping by track is the default, so every source without a track sits under a "Not in a track" header that looks like a track. Not every source is meant to be in one.
- **Two "group by"s.** The status chips on top (All · Enabled · Failing…) and the "Group" dropdown (which also offers Status) read as two ways to do the same thing. Status shows up in four places: chips, group, sort and column.
- **From Sources I can't read a source.** Nothing links a row to that source's posts. I have to remember its name and find it in the reader.

## Solution
- **Click a column header to sort by it**; click again to reverse. An arrow marks the active column. Columns: Name, Kind, Posts, Last post, Added, Status. The "Sort" dropdown is removed.
- **A new "Added" column** (date the source was added, e.g. "3 d ago"). Sorting by it, newest first, puts the last added source on top.
- **No grouping by default**: one flat list. The "Group" dropdown stays with *Track* and *Platform* only (Status is dropped, the chips already split by status). When grouped by track, sources without a track are listed last **without a header**, after a thin divider.
- **Each row has a "read" arrow** (shown on hover, always on touch) that opens the reader on that source. The source sheet's header has "Read posts" too.
- The sort and grouping stay in the URL, as today.

## User Stories
1. As the owner, I want to click "Posts" to sort by post count, so that sorting is where I look.
2. As the owner, I want to click again to reverse the order, so that I can see both ends.
3. As the owner, I want an arrow on the sorted column, so that I know how the list is ordered.
4. As the owner, I want "Last post" to sort by the last post, so that the header means what it shows.
5. As the owner, I want an "Added" column, so that I can see when each source was added.
6. As the owner, I want to sort by Added, newest first, so that I find the source I just added.
7. As the owner, I want the list flat by default, so that sources aren't forced into tracks.
8. As the owner, I want no "Not in a track" header, so that untracked sources aren't labelled as missing something.
9. As the owner, I want one place for status (the chips), so that controls don't repeat each other.
10. As the owner, I want to still group by track or platform when I choose, so that I can organise when I want.
11. As the owner, I want a read arrow on each row, so that I can open that source's posts in one click.
12. As the owner, I want "Read posts" in the source sheet, so that settings and reading are one click apart.
13. As the keyboard user, I want headers to be buttons I can focus and press, so that sorting works without a mouse.
14. As a screen-reader user, I want the sorted header to announce its direction, so that the order is clear.
15. As the owner, I want the sort in the URL, so that a reload or a shared link keeps it.
16. As the owner on a phone, I want the hidden columns' sorts still reachable, so that I can sort by Added on mobile too.
17. As the owner, I want old links with the old sort/group values to still open, so that nothing breaks (unknown values fall back to the default).

## Implementation Decisions
- **API.** Add `s.created_at` to the schedule view query behind source health, and `created_at` to each health row. In the frontend client's `SourceHealthRow` type, add `created_at` and `last_post_at`, and delete the `lastPostAt()` cast helper (it exists only because `last_post_at` was never typed). No new endpoint.
- **The list's view state** (kept in the URL):
  - `sort` ∈ {name, kind, posts, lastPost, added, status} and `dir` ∈ {asc, desc}.
  - Default direction per column: name and kind ascending; posts, lastPost and added descending; status descending, which means worst first (the existing health sort). `asc` reverses it. Ties sort by name.
  - The default sort stays status.
  - `group` ∈ {none, track, platform}, default `none`. `writeSourcesView` writes `group=track` explicitly and leaves `none` out.
- **Old URLs.** `tab=health` maps to group `none`, keeping its status filter. `sort=success`, `group=status` and any unknown value fall back to the defaults.
- **Headers.** Remove `aria-hidden` from the header row. Each header is a `<button aria-label="Sort by Posts, descending">` with a pressed state, not `aria-sort`: the list isn't a table. On narrow screens, where columns hide, one compact "Sort: Added ↓" text button opens the same choices. It is the same control, not a second sort system.
- **Untracked sources.** When grouping by track, they render after a thin divider, without a header.
- **Read link.** Uses `sourceReadPath(id)` from the feed-context helpers, added by issue 0010. Whichever of the two lands first adds it.
- **Docs.** Update `design/docs/pages/sources.md`: the default grouping, the "Not in a track" label, the "dense" scene (grouped by track today), and the column drop rules, including where "Added" drops.

## Testing Decisions
- Pure tests of the list view model (sorting each column both ways, defaults, URL round-trip, unknown values). Prior art: the sources list module tests.
- Component tests (existing `SourcesConfig.test.tsx`): clicking "Added" twice reverses; no "Not in a track" text in track grouping; row read link and sheet link point to `/read/source/<id>`; the Sort dropdown is gone.
- Backend: a health route test that rows carry `created_at`.

## Out of Scope
- Changing what the chips filter. Bulk actions. Track management.
