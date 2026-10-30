# 0052 — What I read: find again a post I read yesterday

Status: **built, not deployed (2026-10-30)** for v9.6 (owner, 2026-10-30: "I want to find post I read yesterday, but I can't find it anymore").

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

## Built
- **Backend** (`repo_reader.py`): a new `FeedFilter` value, `history`.
  - The stream view goes through its own `_history` query: a CTE over `post_interactions` (`opened`, `reading_session`) takes `MAX(created_at)` per post, joins the post, and orders by that last open, then id, newest first.
  - The cursor pages on `(opened_at, id)`. Each row's `sort_at` is the last open, so the day headers, the time column and the cursor follow it. `opened_at` says the same by name.
  - `days` and `date` bound the open, not the publication.
  - Scopes are the usual ones. Main ignores "Show in Main feed: off", as Later does.
  - `By source` keeps its usual query, with an `EXISTS` filter on the same interactions.
  - Bulk mark-read and Keep add no interaction, so they never put a post in History.
  - No migration and no index. On `insight_preview` (read-only, 661 interactions, 257 posts) the query is a hash aggregate over a seq scan, then the post's primary key: 2.9 ms.
- **Frontend:**
  - `history` added to `FeedFilter` (`services/api.ts`, `lib/feedContext.ts`).
  - `Show unread / later / kept / all / history` (`FeedToolbar.tsx`).
  - `ReaderPage.tsx`: no unread count under History; the empty state "Posts you open show up here"; the rail keeps `?filter=history` across scopes.
  - `FeedList.tsx`: `Shift+A` says "Mark read up to here does not work in History."
  - Day grouping needed no new code: it already groups on `sort_at`, in your time zone.
  - `useFeed.ts`: History has `staleTime: 0`, so coming back to it reloads it with the post just read on top. It still never refetches on focus.
  - The rows are `FeedItem` unchanged. A post opened more than 2 days after its date shows the existing `published <date>` note.
- **Design:**
  - `pages/reader.md` covers History, with states `history` and `history-empty`.
  - Decision 034 added.
  - Fixture scenarios: `scenarios.ts`, and a history filter in `site.ts`.
- **Tests:**
  - Backend (`test_repo_reader`): order by last open; opened twice appears once, at the last open; bulk mark-read, Keep and a `favorited` interaction are not History; keyset paging over 3 pages with a tie; every scope plus Main feed: off; `days` bounds the open; By source.
  - Backend route test (`test_feed_listing_routes`): through the real `/opened` endpoint.
  - Frontend: Show order; the History query, day headers, open time and rail link; the empty state in a source scope; the `Shift+A` refusal; the refetch on coming back (it fails without the `staleTime` change).
- **Suites:** backend 881 tests OK. Frontend: typecheck, 619 tests in 45 files, lint and build all green.
- **Bundle:** the reader's initial JS is 475,414 bytes, +349 (0.07%) against 475,065.
- **Screens:** `npm run design:shots -- --page reader --state history,history-empty`, at 1400 and 390 px, dark and light. They are in `frontend/.design-shots/reader/` and not committed.

## Left open
- The History query aggregates the whole open log on each page. That is fine at today's size; around 50k opens it may want a covering index on `(interaction_type, post_id, created_at)`.
- In By source, History is grouped and ordered by publication, not by open. It filters correctly; nobody asked for this ordering.
- Opening a post from History logs a new open. While you read in the continuous stream, that post's neighbours come from the History page you opened it from. The list reorders only when you come back to it.
