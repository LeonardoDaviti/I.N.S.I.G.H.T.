# 0176: The fresh lane, and long posts' entities read in windows (Stealth v10.16, slice L)

Architecture: `plan/research/v1016-architecture.md` sections 5–6 (private). Window reading is 0150 C, for entities.

## Why

- **Fresh posts waited behind older work.** A real case: the posts of a company's deal close, fetched on 10 Nov, were
  still unread on 12 Nov, so every rule (stories, News, entities) missed them. Two causes in the code, both of the
  same class (a new post is ordered by its date or by the queue, never by when INSIGHT got it):
  1. A lease runs a kind's planner only when fewer than `limit` tasks of the kind wait (`api.work`). Behind a big
     queue (a window change, a backfill, every post read) new posts are not even planned until the queue drains.
  2. The planners and the lease order posts by `COALESCE(surfaced_at, published_at, fetched_at)`: a post fetched today
     but dated days earlier ranks behind newer-dated work, and a post dated before the owner's reading window is never
     planned at all.
- **Entities are read from the first 1,500 / 6,000 characters only** (the entities arm's cut; the server's arm is
  ent-v4.2, 6,000). Long round-ups (40–150k characters) lose 31% of their people (experiment E7).

## Built

### A. The fresh lane (`tasks.py`, `folds.plan`, `repo.lease_tasks`, `api.work`)
- **Fresh** = a post fetched or surfaced in the last `FRESH_HOURS` (24) and dated in the last `FRESH_DATED_DAYS` (7),
  whatever the reading window (`tasks.fresh_sql`). The date bound keeps an archive import (posts fetched today, dated
  months back) out of the lane: it is history, read in the general order.
- **Planned first:** `tasks.plan_fresh` (read and entities through `plan_posts(fetched_since=…)`, read3 through
  `folds.plan(fetched_since=…)`) runs on **every** lease of the kind, before the general planner and whatever the queue
  holds (`FRESH_REST_SECONDS` = 30 after a call that added nothing). Headlines are planned by the decision run; they
  ride in the lane by their story's first post.
- **Leased first, with a cap both ways** (`repo.lease_tasks(fresh=FRESH_KINDS, fresh_hours=24, fresh_share=0.75)`):
  a lease takes fresh tasks of read, entities, read3 and headline first, up to 3/4 of its slots (at least one, and at
  least one left to the rest when the lease is 2 or more); then the rest in the order as before (urgent, inside the
  window, by age; backfill pages at their priority); then fresh tasks again if slots are left. A big backfill never
  holds a new post back; new posts never take a whole lease while older work waits.
- **Cost unchanged:** only the order and the planning trigger changed; every task is the one that would have been
  asked anyway.

### B. Long posts' entities in windows (`tasks.py`, `repo.add_mentions`, `ent42.py`, migration 0119)
- **Windows** of the arm's size (`chars`: 1,500 or 6,000) over the whole shown text, consecutive windows sharing
  `WINDOW_OVERLAP` = 200 characters, at most `entity_windows_max` (mx_settings; default `MAX_WINDOWS` = 12; 1 is the
  behaviour before 0176). The rest of a post past the cap stays unread.
- **A task a window.** Window 1's input is exactly today's (`entities_input`): the same task, never asked again. A later
  window shows the post's head (platform, source, author of a repost, title), `Window: k of n of the post's text
  (characters a-b of N)` and its text; no links (they go with window 1). A short post has one window and behaves
  exactly as before (tested: same input, one task, mentions numbered from 0).
- **Planned:** with the post (`plan_posts`, `plan_last_posts`, `entities_task`, the fresh lane), and for posts asked
  before windows existed by `plan_windows` (the entities planner's second step): posts stored longer than one window
  (`octet_length`, no detoast) with only their first window's task; a post whose shown text fits one window, or whose
  windows are another post's tasks, is marked (`mx_plan_marks` why `one_window` / `same_input`) and not read again
  until its text changes.
- **Stored:** `mx_mentions.win` (migration 0119; every earlier row is 0). Window w's mentions are numbered from
  w × 1000, so `(post, guide, n)` stays a mention's key, n stays the order in the text whichever window answers first,
  and identity links them unchanged (it reads `mx_mentions_now`, which carries `win`). A name wholly inside the text a
  window shares with the one before is that window's, not counted twice. The citation rule (ent-v4, ent-v3-6k) and
  ent-v4.2's cite merge stay the first window's; ent-v4.2's own-title rule applies to every window. A later window
  that adds mentions marks the post's set changed (`mx_mention_sets.at`) so the readers of new sets read it again.
- **The worker** (`scripts/markx-worker`): a lease's entities tasks carry their `post`; `split_calls` never puts two
  windows of one post in one call (0150 B's rule: windows asked together answer from each other).
- **Incremental runs** (0169): entities are not among the inputs a run keeps; the entities stage reads the current
  mentions. Tested: after each later window is answered, the incremental run is a full run's result.

## Measured (the 2026-11-05 copy, read-only; worker logs of the hand runs)

**Windows** (the real shown text, `post_parts`; 49,384 posts; 8,130 fetched in the copy's last 7 days):

| Arm (chars) | Cap | Posts over one window | Extra windows, all posts | Past the cap | Extra windows, last 7 days |
|---|---|---|---|---|---|
| 6,000 (ent-v4.2, the server's) | 12 | 7,256 (14.7%) | 22,021 | 351 | 2,994 (≈428/day) |
| 6,000 | 8 | 7,256 | 19,996 | 635 | 2,811 |
| 1,500 (ent-v3) | 12 | 16,383 (33.2%) | 79,354 | 3,364 | 15,325 (≈2,190/day) |

By platform (6,000): feeds 6,076, video transcripts 1,112, Reddit 67.

**Cost** (worker logs: entities ≈ $0.0008–0.0010 a task over 7–12 Nov; a later window is a full 6,000 characters, so
$0.001–0.002 a window is the range used):
- Ongoing at 6,000 / 12: ≈ 428 extra tasks a day → **≈ $0.45–0.85 a day** (≈ $13–26 a month).
- Once, the history (the copy's 22,021 windows; the server has about 20% more posts): **≈ $22–53**, planned over the
  owner's reading window, newest first, PLAN_LIMIT a call, behind the fresh lane.
- Under ent-v3 (1,500) the same would be ≈ 2,190 tasks a day (≈ $1.5–2 a day) and 79k once: switch the cap
  (`entity_windows_max`) to 1 to stop windows at any time.

**Fresh-lane lag** (fetched → leased). Fixture (`test_the_lag_of_a_fresh_post_behind_a_backfill`): 400 backfill tasks
waiting, 10 posts fetched now but dated 5 days back, leases of 20: before, the new posts are leased in the **21st**
lease; with the lane, in the **1st**. Simulation (hourly steps, 48 posts an hour × 1.4 tasks, a 22,000-task backlog
such as the windows' history; `/tmp`-only script): the longest wait of a new post, before → after:

| Worker throughput | Before | After |
|---|---|---|
| 200 tasks/h | 107 h | ≤ 1 h |
| 400 tasks/h | 54 h | ≤ 1 h |
| 1,000 tasks/h | 23 h | ≤ 1 h |

**Expected lag:** a new post is planned within 30 s of the next lease of its kind and leased in that lease (as long as
new posts need under 3/4 of the worker's throughput: about 65 tasks an hour against hundreds), so the lag is one worker
round (the hand loop's rounds are 15–35 minutes apart), not the queue's length. The backfill keeps at least 1/4 of each
lease (at 200 tasks/h it drains 22,000 in about 7 days instead of 4.6, while new posts wait an hour instead of 4 days).

## Not done
- The post page's "read to 72,000 of 130,000 characters" (0150 C) and the windows' prose check (a window that is
  markup is still asked).
- Claims windows (0150 C's `window` kind with claims-v2): this slice reads entities only.
- The headline planner's order inside the decision run (decide.py is another slice's): headlines ride the lane at lease.

## Tests
`insight_core.tests.test_markx_reading_windows` (windows split, caps, short posts unchanged, the window index and
numbering of mentions, overlap, the set marked changed, the windows planner and its marks, fresh planning outside the
window, the lease's lane and both starvations, the lag fixture, the API lease, incremental == full);
`scripts.tests.test_markx_worker` (two windows of a post never in one call; `split_calls`).
