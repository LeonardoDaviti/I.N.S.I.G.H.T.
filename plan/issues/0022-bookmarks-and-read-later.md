# 0022 — Bookmarks: read later, keep, and what the star means

Status: **discussion** (owner, 2026-10-27). Nothing is built; decide the model first.

## The owner's observations
- "Can you add a feature like bookmarks? But first discuss how bookmarks should work for each post and what bookmarks are needed for." (2026-10-16)
- "Why do we have a favourite button on the main page, on the post? If I have not read the post, why do I need to favourite it? I need to store it as *read later*, yes?" (2026-10-27)

## Today
- Each feed row and the post page have a **star** (`s`), stored as `starred_at` in the reader state. A row also has the read circle (`m`). Issue 0019 removed the row's "Mark read up to here" button.
- On an unread row the star is the only "save" action, so it is used as "read later", but nothing treats it so: a starred post still leaves Unread once read and has no place of its own in the reader flow.

## Questions to decide
1. **What is a bookmark for?**
   - *Read later*: saved before reading, kept out of the way until I come back.
   - *Keep*: saved after reading, because it mattered.
   - *A place in a post*: where I stopped in a long post.
   - *A place in a stream*: where I stopped in a feed.
2. **Is "read later" separate from the star?** One action with two meanings, or two: "Read later" on unread rows, "Keep" (the star) after reading.
3. **Does read later clear itself?** When the post is read, after N days, or never.
4. **Notes and folders?** A short note on a saved post; folders or tags; or neither (the minimal answer).

## Notes for the discussion
- The likely smallest model: an unread row offers **Read later**; the star means **Keep** and is offered once a post is read. A "Read later" view in the reader rail lists them; reading one clears it. Remembering the scroll position in a long post is a separate, small feature.
- Saved posts are input for the future analysis version: what I keep says what matters to me (compare 0013, priority order).
