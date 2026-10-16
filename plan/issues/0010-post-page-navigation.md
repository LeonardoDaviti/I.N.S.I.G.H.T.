# 0010 — Post page: back always in reach, and the source name reads the source

Status: **built** 2026-10-16 (owner observations on the server, 2026-10-16). UX. Changes one decision of issue 0003.

## Problem Statement
- **Getting back means scrolling up.** The "Back / Previous / Next" row is at the top of the post and scrolls away. With a mouse there is nothing to click at the end of a long post.
- **The source name opens settings, not the source.** In the byline, the source name goes to the source's settings sheet (issue 0003). I want it to show all of that source's posts in the reader.

## Solution
- The post's "Back / Previous / Next" row becomes sticky under the top bar, compact, always visible while reading. At the end of the article the same three actions repeat once, large enough to tap, when continuous reading (issue 0014) is off.
- The source name in the byline opens the reader on that source (`/read/source/<id>`). A quiet word next to it, `/ settings`, keeps the 0003 path to the sheet (words for places, principle P5).
- The reader's header (from 0003) is unchanged: there the title still links to settings, because you are already reading the source.

## User Stories
1. As the reader, I want Back visible while I scroll a post, so that I can leave without scrolling up.
2. As the reader, I want Previous and Next visible too, so that I can move on from anywhere in the post.
3. As the reader, I want Back/Previous/Next at the end of the article, so that the natural place to act after reading has them.
4. As the reader on a phone, I want the sticky row small and tappable, so that it doesn't eat the screen.
5. As the reader, I want clicking the source name to show all its posts, so that I can read more from it.
6. As the reader, I want a quiet "settings" link by the source name, so that I can still manage the source in one click.
7. As the reader, I want Back to return to the list position I came from, so that I keep my place (as today).
8. As the keyboard reader, I want u/Esc/j/k to keep working, so that nothing changes for shortcuts.
9. As the reader with reduced motion, I want no animation when the row sticks, so that it stays calm.

## Implementation Decisions
- **Extract `PostNav`** (Back / Previous / Next) from the post page. It is used at the top, `sticky top-topbar z-30` on the `reader-material` surface like the reader toolbar, on one line with no wrapping on phones. It is also used at the end of the article when continuous reading is off.
- **Byline.** The source name links to `sourceReadPath(id)`, a new helper in the feed-context helpers beside `folderReadPath`, which escapes the id. Issue 0011 reuses the same helper. `/ settings` next to it uses the existing `sourceSettingsHref`.
- **Design rules.** Amend principle P8: in the post byline, the source name reads the source and a settings link manages it. Add a decision that supersedes decision 011. Add a note to issue 0003 that 0010 changed the byline target. Update `post.md` and the design wall's post edge in `siteMap.ts`.

## Testing Decisions
- Post page component tests (existing testkit):
  - the byline source link points to `/read/source/<id>`;
  - `/ settings` points to `/settings/sources?source=<id>`;
  - the end-of-article `PostNav` exists and navigates like the top one;
  - u/Esc/j/k still work.
- No Playwright: the frontend has none. The sticky row is checked visually on the local preview.

## Out of Scope
- Continuous reading (issue 0014).
