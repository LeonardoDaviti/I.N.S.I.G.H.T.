# 0019 — Feed rows: one read button, and the source name reads the source

Status: **built** 2026-10-27 (owner observations, 2026-10-27). UX. Changes decision 011 for feed rows, as 0010 did for the byline.

## Problem Statement
- **Two read buttons.** The selected row on the main page shows "mark read up to here" (✓✓), the read circle (○/✓) and the star. Two of the three look like "read". I want only the circle.
- **The source name goes nowhere.** On a feed row the source name is plain text. I want a click on it to show all of that source's posts.

## Solution
- The row's "mark read up to here" button is removed. The circle (`m`) and the star (`s`) stay. Mark read up to here stays on `Shift+A`, with its confirm dialog and Undo.
- The source name on a row links to the reader on that source (`/read/source/<id>`), as in the post byline (issue 0010).

## User Stories
1. As the reader, I want one read button per row, so that I don't have to guess which one to press.
2. As the keyboard reader, I want `Shift+A` to keep marking read up to the selection, so that nothing changes for shortcuts.
3. As the reader, I want clicking a row's source name to show all its posts, so that I can read more from it.
4. As the reader, I want to middle-click or Tab to the source name, so that it behaves like any link.
5. As the reader, I want clicking the source name not to open or mark the post, so that the post stays unread.

## Implementation Decisions
- **`FeedItem`.** The `onMarkThrough` prop and its button are gone; `FeedList` still wires `Shift+A` to `askMarkThrough`. The source name is a `TextLink` to `sourceReadPath(item.source_id)`, quiet like the byline (`text-fg-3`, underline only on hover). The full name is in `title`.
- **No propagation code.** The row's own click handler already ignores clicks on `a` and `button`, like the title link. The source link is a sibling link, not inside the title.
- **Design rules.** Decision 022, P8 and its explanation, `reader.md`, and the Wall's feed → source edge.

## Testing Decisions
- `FeedList` component tests: each row has two links, the title and the source. The source link points to `/read/source/<id>`, navigates there and marks nothing read. A selected row's buttons are exactly "Mark read" and "Star".
- The existing `ReaderPage` `Shift+A` test still covers mark read up to here.

## Out of Scope
- The by-source view's group heading, which already reads the source.
