# 0052 — What I read: find again a post I read yesterday

Status: **spec** (2026-10-30) for v9.6 (owner, 2026-10-30: "I want to find post I read yesterday, but I can't find it anymore").

## The case
- **No view of what you read.** The feed's filters are All, Unread, Later, Kept and Updated. "All" includes read posts, but in publication order, so a week-old post read yesterday is buried under a week of posts. Search helps only if you remember its words.
- **The data already exists.**
  - Opening a post logs an `opened` interaction (`post_detail_service.py`).
  - Reading logs a `reading_session`.
  - The preview holds 453 opens and 208 reading sessions.
- **Why not `read_at`:** "Mark all read up to here" sets it on hundreds of posts at once. History must be what you opened, not what you cleared.

## Decided
- **A "History" filter next to the others,** in the same toolbar and the same feed list.
- **What's in it:** posts with an `opened` or `reading_session` interaction.
- **Order:** the latest such interaction, newest first. Each post appears once.
- **Grouped by day:** "Today", "Yesterday", then dates, in your time zone.
- **Rows** are the feed's usual rows, with the time you opened it in place of the published time.
- **It works in every scope the other filters do** (Main, a track, a source). It ignores "Show in Main feed: off", because you did open that post.
- **No new tables and no new setting:** a query over the interaction log, with an index on it if the query needs one.
- **Out of scope:** clearing history, and pausing it.

## Done when
- **Backend tests:**
  - order by last open;
  - a post opened twice appears once, at its last open;
  - posts only marked read in bulk are not in it;
  - scopes and paging work.
- **Frontend tests and screens** (light and dark): the toolbar with History, a day-grouped list, and the empty state ("Posts you open show up here").
- Backend suite and frontend checks green; bundle within the 1% budget.
