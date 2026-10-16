# 0014 — Continuous reading: scroll from one post into the next

Status: **built** 2026-10-16 (owner observation, 2026-10-16). UX / reading.

## Problem Statement
- Reading means: open a post, read, go back or press Next, open the next one. I want to read like an online comic: keep scrolling, and the next post is simply there.

## Solution
- On a post page, when I reach the end of the article, the **next post of the same feed follows below**, in full, separated by a thin divider with its source and title. And the next after that, as I keep scrolling.
- The address bar follows the post I'm reading (replace, not push), so Back still returns to the list where I left it, and a reload opens the post I was on.
- A post is marked read when I have scrolled through it (its end has passed the top half of the screen), not when it merely appears.
- The sticky Back / Previous / Next row (issue 0010) applies to the post currently in view. In continuous mode the end-of-article Back / Previous / Next appears only after the last post, with "You're all caught up". Between posts there is only the divider.
- Continuous reading is on by default. A choice in the reader toolbar, `posts continuous / one at a time`, turns it off, at every screen width.

## User Stories
1. As the reader, I want the next post to appear below when I finish one, so that I can keep reading without clicking.
2. As the reader, I want the next posts to come from the same feed and filter, in newest-first order (as Next works today), so that I read what I came from.
3. As the reader, I want a clear divider with the next post's source and title, so that I know where one ends.
4. As the reader, I want the address to follow the post in view, so that a reload or a shared link opens it.
5. As the reader, I want Back to take me to the list at my place, so that continuous reading doesn't fill history.
6. As the reader, I want a post marked read only when I've scrolled through it, so that skimming past doesn't lose posts.
7. As the reader, I want reading time recorded per post, so that a future priority order (0013) can learn from it.
8. As the reader, I want images and videos in later posts to load only as I approach them, so that the page stays fast.
9. As the reader, I want the stream to end with "You're all caught up" when the feed ends, so that I know I'm done.
10. As the reader, I want j/k to jump between the posts in the stream, so that keyboard reading still works.
11. As the reader, I want to turn continuous reading off, so that I can go back to one post at a time.
12. As the reader on a phone, I want it to work with touch scrolling, so that it feels like a comic reader.
13. As the reader with reduced motion, I want no smooth auto-scrolling, so that it is calm.

## Implementation Decisions
- **Split the existing `PostView`** (keyed by post id, holding the per-post state: comments, YouTube progress, star, open and reading session) into:
  - `PostArticle`: one post, with that state, the byline from 0010 and its settings link;
  - a page shell: the sticky `PostNav`, the keys, the help, Back.

  No other new component.
- **Next posts.** They follow the stream order of the context's scope and filter, through the existing neighbour logic (`ctx`, cached feed pages, fetching the next page at the end), as Next does today. By source doesn't change that. The next post's detail is prefetched when the reader is near the end of the current one.
- **Window.** At most 3 posts are mounted: previous, current, next. A post scrolled far above is unmounted, with its height kept so the scroll doesn't jump.
- **Current post.** The post crossing the viewport midline is current. The URL follows it through the existing Next navigation (`replace`, the same `location.state`). Previous and `k` scroll to the previous post if it is mounted, or else navigate to it.
- **Read.** In continuous mode, `recordPostOpen` (which logs the open and marks the post read) fires once per post, when the post's end passes the top half of the screen. A post whose end is already above the midline when shown counts at once. This applies to the first post too. Single mode keeps open-on-mount.
- **Reading time.** Counted while the post is current, paused while the tab is hidden, and sent with the existing reading-session call when it stops being current (if 1 s or more).
- **The choice** is a stored `insight.reader.flow` ∈ {continuous, single}, via the existing `useStoredChoice`.
- **Docs.** `design/docs/pages/post.md` (the layout, the read rule, the end of the page) and `reader.md` (the new choice).

## Testing Decisions
- Component tests with the existing post page testkit and a stubbed IntersectionObserver: the next post renders after the end sentinel is seen; the URL is replaced (history length unchanged); read is recorded only when the post's end passes; "one post at a time" renders a single article. Prior art: `PostDetailPage.test.tsx`, `usePostNeighbors` tests.

## Out of Scope
- Continuous reading in the list view itself (inline expansion).
- Offline reading.
