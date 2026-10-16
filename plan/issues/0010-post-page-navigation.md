# 0010 — Post page: back always in reach, and the source name reads the source

Status: **ready-for-agent** (owner observations on the server, 2026-10-16). UX. Changes one decision of issue 0003.

## Problem Statement
- **Getting back means scrolling up.** The "Back / Previous / Next" row is at the top of the post and scrolls away. With a mouse there is nothing to click at the end of a long post.
- **The source name opens settings, not the source.** In the byline, the source name goes to the source's settings sheet (issue 0003). I want it to show all of that source's posts in the reader.

## Solution
- The post's "Back / Previous / Next" row becomes sticky under the top bar, compact, always visible while reading. At the end of the article the same three actions repeat once, large enough to tap.
- The source name in the byline opens the reader on that source (`/read/source/<id>`). A small settings icon next to it (tooltip "Source settings") keeps the 0003 path to the sheet.
- The reader's header (from 0003) is unchanged: there the title still links to settings, because you are already reading the source.

## User Stories
1. As the reader, I want Back visible while I scroll a post, so that I can leave without scrolling up.
2. As the reader, I want Previous and Next visible too, so that I can move on from anywhere in the post.
3. As the reader, I want Back/Previous/Next at the end of the article, so that the natural place to act after reading has them.
4. As the reader on a phone, I want the sticky row small and tappable, so that it doesn't eat the screen.
5. As the reader, I want clicking the source name to show all its posts, so that I can read more from it.
6. As the reader, I want a quiet settings icon by the source name, so that I can still manage the source in one click.
7. As the reader, I want Back to return to the list position I came from, so that I keep my place (as today).
8. As the keyboard reader, I want u/Esc/j/k to keep working, so that nothing changes for shortcuts.
9. As the reader with reduced motion, I want no animation when the row sticks, so that it stays calm.

## Implementation Decisions
- The existing top row of the post page gets `sticky` positioning under the top bar, using the same "reader-material" surface the reader toolbar uses. No new component unless the row is reused at the end; if reused, extract the row (Back/Previous/Next) into one small component used in both places.
- Byline link target uses the existing scope path helper for `source:<id>`; the settings icon uses the existing settings href helper. Issue 0003 gets a note that the byline target was changed by 0010.
- Design docs (post page) are updated to match.

## Testing Decisions
- Post page component tests (existing testkit): the byline source link points to `/read/source/<id>`; the settings icon points to `/settings/sources?source=<id>`; the end-of-article actions exist and navigate like the top row. Sticky positioning is checked in a Playwright screenshot only if the design wall already covers the post page.

## Out of Scope
- Continuous reading (issue 0014).
