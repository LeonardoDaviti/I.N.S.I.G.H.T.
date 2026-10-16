# 0013 — Priority order: the sources I read most come first

Status: **ready-for-agent** (owner observation, 2026-10-16). UX / reading.

## Problem Statement
- The feed has one order: newest first. A burst from a source I rarely read sits above a post from a source I always read. I want an order that puts what matters to me on top.

## Solution
- A third word in the reader's view choice: **Priority**, next to Stream and By source.
- Priority orders the feed by how much I read each source lately: sources I open, read for long and star come first; within a source, newest first. It is computed from what I already do; there is nothing to set.
- Each source's place can be nudged by hand in the source sheet: "Always first" / "Normal" / "Always last".

## User Stories
1. As the reader, I want a Priority order, so that the sources I care about are at the top.
2. As the reader, I want it learned from what I read, so that I don't have to configure it.
3. As the reader, I want recent reading to count more than old reading, so that the order follows my current interests.
4. As the reader, I want stars to count a lot, so that what I save rises.
5. As the reader, I want reading time to count, so that a source I read in depth ranks above one I only open.
6. As the reader, I want to pin a source first or last, so that I can correct the order.
7. As the reader, I want Priority to work with Unread / Starred / All, so that filters still apply.
8. As the reader, I want Priority remembered like Stream/By source, so that it stays my choice.
9. As the reader, I want new sources not to be buried forever, so that I can discover them (a new source starts at the middle).
10. As the reader, I want paging in Priority to be stable, so that scrolling never repeats or skips posts.

## Implementation Decisions
- **Source score** (computed in the reader repository, one CTE per request): over the last 60 days, `opens + reading_minutes/2 + 5 × stars`, each interaction weighted by `0.5^(age_days/14)`, from the existing interaction and reader-state tables joined to posts. Pin: first = +∞ tier, last = −∞ tier, stored in source settings (`priority: first|normal|last`). A source with no history gets the median score.
- **Order:** `ORDER BY tier DESC, score_bucket DESC, sort_key DESC, id DESC`, where `score_bucket` is the score rounded to an integer so the cursor stays small. The Priority cursor encodes `snapshot|tier|bucket|sort_key|id`. `snapshot` is the time of the first page. Every later page computes the scores only from interactions up to that snapshot, so a post opened mid-scroll doesn't move sources between pages.
- **API:** the feed endpoint's `view` gains `priority`. The frontend view choice gains the word. No new endpoint.

## Testing Decisions
- Reader repository tests: a source with more recent opens ranks above a newer post from an unread source; pins override; paging through Priority returns each post once while a new interaction is recorded mid-scroll. Prior art: reader repository keyset tests.
- Frontend: the view choice renders "Priority" and sends `view=priority`.

## Out of Scope
- Per-post ranking by content; AI scoring.
