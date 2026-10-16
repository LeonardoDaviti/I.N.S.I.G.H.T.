# 0014 — Continuous reading: scroll from one post into the next

Status: **ready-for-agent** (owner observation, 2026-10-16). UX / reading.

## Problem Statement
- Reading means: open a post, read, go back or press Next, open the next one. I want to read like an online comic: keep scrolling, and the next post is simply there.

## Solution
- On a post page, when I reach the end of the article, the **next post of the same feed follows below**, in full, separated by a thin divider with its source and title. And the next after that, as I keep scrolling.
- The address bar follows the post I'm reading (replace, not push), so Back still returns to the list where I left it, and a reload opens the post I was on.
- A post is marked read when I have scrolled through it (its end has passed the top half of the screen), not when it merely appears.
- The sticky Back / Previous / Next row (issue 0010) applies to the post currently in view.
- Continuous reading is on by default; a "one post at a time" choice in the reader's density menu turns it off.

## User Stories
1. As the reader, I want the next post to appear below when I finish one, so that I can keep reading without clicking.
2. As the reader, I want the next posts to come from the same feed and filter, so that the order matches the list.
3. As the reader, I want a clear divider with the next post's source and title, so that I know where one ends.
4. As the reader, I want the address to follow the post in view, so that a reload or a shared link opens it.
5. As the reader, I want Back to take me to the list at my place, so that continuous reading doesn't fill history.
6. As the reader, I want a post marked read only when I've scrolled through it, so that skimming past doesn't lose posts.
7. As the reader, I want reading time recorded per post, so that Priority (0013) learns correctly.
8. As the reader, I want images and videos in later posts to load only as I approach them, so that the page stays fast.
9. As the reader, I want the stream to end with "You're all caught up" when the feed ends, so that I know I'm done.
10. As the reader, I want j/k to jump between the posts in the stream, so that keyboard reading still works.
11. As the reader, I want to turn continuous reading off, so that I can go back to one post at a time.
12. As the reader on a phone, I want it to work with touch scrolling, so that it feels like a comic reader.
13. As the reader with reduced motion, I want no smooth auto-scrolling, so that it is calm.

## Implementation Decisions
- **Extract the article** (header, byline, body, media, actions) of the post page into one component that renders a single post from post-detail data. The post page renders a list of these.
- **Next posts** come from the existing neighbour logic (feed context `ctx`, cached feed pages, fetching the next page at the end). The next post's detail is prefetched when the reader is near the end of the current one (as Next is prefetched today).
- **Window:** at most 3 posts mounted (previous, current, next); posts scrolled far above are unmounted with their height kept so the scroll doesn't jump.
- **Read and reading time** use the existing open/reading-session calls, triggered per post by an IntersectionObserver instead of by page mount.
- **URL** uses `replace` navigation as the current post changes.
- **Preference** stored like the existing density preference.

## Testing Decisions
- Component tests with the existing post page testkit and a stubbed IntersectionObserver: the next post renders after the end sentinel is seen; the URL is replaced (history length unchanged); read is recorded only when the post's end passes; "one post at a time" renders a single article. Prior art: `PostDetailPage.test.tsx`, `usePostNeighbors` tests.

## Out of Scope
- Continuous reading in the list view itself (inline expansion).
- Offline reading.
