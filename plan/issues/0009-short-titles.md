# 0009 — A title is a title: cut posts whose whole text is the title

Status: **ready-for-agent** (owner observation on the server, 2026-10-16). UX.

## Problem Statement
- From Nitter (and other title-less feeds such as Telegram bridges), the whole tweet is the title. Post 6f3d1519 has a 1,000-character title, newlines and bullet list included. The post page shows it as a 2rem heading and then repeats the same text as the body.
- Nothing cuts titles anywhere: the only rule is an 80-character fallback for an empty title.

## Solution
- When a post's title is long (over 120 characters) or is the start of its body, INSIGHT shows a short title: the first line or first sentence, at most 120 characters, cut at a word with "…".
- On the post page, when the title was cut from the body, the full text appears once, as the body, not again in the heading.
- Applies to posts already stored, with no data change.

## User Stories
1. As the reader, I want a tweet's title to be its first sentence, so that the feed row and the heading are short.
2. As the reader, I want the heading not to repeat the body, so that I read the text once.
3. As the reader, I want a cut title to end at a word with "…", so that it reads naturally.
4. As the reader, I want a real title (a blog post's) left alone, so that normal posts don't change.
5. As the reader, I want old posts to get the short title too, so that I don't have to refetch.
6. As the reader, I want the browser tab and copied link text to use the short title, so that they are readable.
7. As the reader, I want searching or ⌘K to still find words from the full text, so that nothing is lost.
8. As the reader, I want multi-line titles to use only their first line, so that bullet lists never become headings.

## Implementation Decisions
- **One rule, in one place: the reader API.** The backend already computes the display title for empty titles (the reader repository's title fallback). That same function gains the cut rule, so the feed and the post detail both return the short title; the stored title is untouched. The response keeps `title` as the display title and adds nothing new unless needed: if the frontend needs to know the title was cut, it gets `title_cut: true`.
- **The rule:** take the title (or the body when the title is empty); take the first line; if over 120 characters, cut at the end of the first sentence if that is ≤ 120, else at the last word boundary ≤ 117 plus "…". A title is "the body's start" when the normalised body starts with the normalised title's first 60 characters.
- **Frontend.** The post page hides the duplicated opening only via `title_cut`; the existing `displayPostTitle` stays for its ellipsis case and is not given a second length rule (no duplicate rule in two places).

## Testing Decisions
- Backend unit tests of the title rule (tweet with bullets → first line; long single sentence → word cut + "…"; normal blog title unchanged; empty title → body start), and a reader route test that a stored 1,000-character title comes back cut. Prior art: reader repository tests for the 80-character fallback.
- Frontend: the post page with `title_cut` renders the body once.

## Out of Scope
- Rewriting stored titles; AI-generated titles.
