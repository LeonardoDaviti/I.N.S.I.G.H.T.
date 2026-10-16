# 0009 — A title is a title: cut posts whose whole text is the title

Status: **built** 2026-10-16 (owner observation on the server, 2026-10-16). UX.

## Problem Statement
- From Nitter (and other title-less feeds such as Telegram bridges), the whole tweet is the title. Post 6f3d1519 has a 1,000-character title, newlines and bullet list included. The post page shows it as a 2rem heading and then repeats the same text as the body.
- Nothing cuts titles anywhere: the only rule is an 80-character fallback for an empty title.

## Solution
- When a post's title is long (over 120 characters) or is the start of its body, INSIGHT shows a short title: the first line or first sentence, at most 120 characters, cut at a word with "…".
- On the post page, the heading shows the short title and the body is rendered in full. When the body is exactly the title (nothing more), it isn't rendered a second time.
- Applies to posts already stored, with no data change.

## User Stories
1. As the reader, I want a tweet's title to be its first sentence, so that the feed row and the heading are short.
2. As the reader, I want the heading not to repeat the body, so that I read the text once.
3. As the reader, I want a cut title to end at a word with "…", so that it reads naturally.
4. As the reader, I want a normal-length title (a blog post's) left alone, so that normal posts don't change. A real title over 120 characters is cut too.
5. As the reader, I want old posts to get the short title too, so that I don't have to refetch.
6. As the reader, I want the browser tab on a post page to show the short title, so that tabs are readable.
7. As the reader, I want multi-line titles to use only their first line, so that bullet lists never become headings.

## Implementation Decisions
- **One rule, in one place.** Add `display_title(title, content)` in the shared post fields module (beside `build_post_fields`). The reader's feed items (today an inline 80-character fallback in the reader repository) and the post detail service both call it, so the feed and the post page show the same title. The stored title is untouched.
- **The rule:**
  1. Start from the raw title, or the raw body when the title is empty. Use raw text so its line breaks are still there.
  2. Keep only the first non-empty line.
  3. If that is 120 characters or less, it is the title.
  4. Otherwise cut at the first sentence end (`[.!?…]` followed by a space or the end), found after at least 20 characters, if that end is within 120 characters.
  5. Otherwise cut at the last space within 117 characters and add "…". With no space in the first 117 characters (CJK, say), cut at 117.
- **Frontend.** Delete `displayPostTitle` and its tests: it expands a title ending in "…" back to the body's first line (up to 300 characters), which would undo the cut. The post page renders `post.title`. When the body text equals the title, the body is not rendered again; no new API field is needed for that. The post page sets the tab title to `<title> · INSIGHT`. Update `post.md` for the heading rule.

## Testing Decisions
- Backend unit tests of `display_title`:
  - a tweet with a bullet list becomes its first line;
  - a long single sentence is cut at a word, with "…";
  - a normal blog title is unchanged;
  - an empty title becomes the body's start;
  - a long CJK line is cut hard at 117.
- Route tests: a stored 1,000-character title comes back cut from both the feed and the post detail. Prior art: `test_post_detail_reader.py`, `test_feed_routes.py`.
- Frontend: the post page heading renders the API title as given, and the tab title is set.

## Out of Scope
- Rewriting stored titles; AI-generated titles.
