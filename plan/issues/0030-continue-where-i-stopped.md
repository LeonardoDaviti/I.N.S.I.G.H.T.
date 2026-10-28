# 0030 — Continue where I stopped

Status: **built** 2026-10-28 (owner design, 2026-10-28). UX. Decision 025.

## Problem Statement
I stop half way through a long post and come back later. The post opens at the top and I scroll to find where I was. The feed doesn't show which posts I started.

## Solution
- A long post remembers the text block at the top of the screen. The server keeps it with the post's read state.
- When I open the post again, a quiet line under the title says "Continue from where you stopped (40%)". It is a button that scrolls to that block. Nothing scrolls by itself.
- Reaching the end clears it. In continuous mode that is the moment the post counts as read. Marking a post read clears it too.
- A feed row of a post I started shows a thin line with how far I read.

## User Stories
1. As the reader, I want a post I left half way to offer to take me back, so that I don't hunt for my place.
2. As the reader, I want it to offer, not jump, so that opening a post never moves under me.
3. As the reader, I want the place to survive images loading and another window width, so that it lands on the same paragraph.
4. As the reader, I want a finished post to forget the place, so that the offer doesn't come back.
5. As the reader, I want feed rows to show posts I started, so that I can pick them up again.
6. As the continuous reader, I want each post in the stream to keep its own place, and only the post I opened to offer it.
7. As a keyboard or screen-reader user, I want the offer to be a real button, and focus to land on the block it scrolls to.

## Implementation Decisions
- **Storage.** Migration 0030 adds `resume_block` and `resume_blocks` to `post_reader_state`. `resume_block` is the index of the top text block in view of the body, and `resume_blocks` is the body's block count, used for the percentage. Both NULL means not started or finished.
- **API.** `PUT /api/posts/item/{id}/position {block, blocks}`, `0 <= block < blocks`. `block: null` clears it. `reader_state` and feed items carry both fields. `PUT /api/feed/read` marking posts read (by ids or mark-through) clears their position. Opening a post does not clear it.
- **Blocks.** These elements count as blocks: `p, li, h1–h6, pre, blockquote, table, figure` in the post body, in document order. The top block is the first one whose bottom is below the sticky navigation band.
- **Thresholds.** A post is long at 4,500 characters of text or more, about three screens. Shorter posts, videos and fixtures are not tracked. The offer and the row line show only between 5% and 90%.
- **Saving.** Nothing is saved until you scroll. After scrolling, the position is saved 3 seconds after scrolling stops. It is also saved at once when the tab hides or the post unmounts. While the offer is shown, a place above the stored one does not replace it. Reading past the stored place replaces it and closes the offer. Once the end has passed the top half of the screen, the position is cleared and nothing more is saved for this visit.
- **Code.** `hooks/useReadingPosition.ts` (the hook and `resumeShare`). `PostArticle` uses it, and only the stream's first post gets `offerResume`. `FeedItem` draws the line. The post body is memoised, so a state change no longer rebuilds its blocks, which kept the focus on the block.

## Testing Decisions
- Backend (`test_post_detail_reader.py`): a position is stored and shows on the post and its feed row. `null` clears it. Marking read clears it and opening does not. An out-of-range position gives 400 and an unknown post gives 404.
- Frontend (`PostDetailPage.test.tsx`): the offer shows at 40% and not under 5%, over 90%, with no position or on a short post. The button scrolls to and focuses the block. The save is debounced and happens at once on hide or unmount. Nothing is saved without a scroll. Looking about above the old place keeps it. Reaching the end clears it. In the stream only the opened post offers. `FeedList.test.tsx` covers the row line and its "40% read" text for screen readers.

## Out of Scope
- YouTube posts, which keep their own watch progress.
- Resuming inside a block (a long code block or table).
