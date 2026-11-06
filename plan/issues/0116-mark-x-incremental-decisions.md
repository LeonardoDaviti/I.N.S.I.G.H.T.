# 0116 — Mark X incremental decisions: recompute only the stories new answers touched

Status: **spec** (2026-11-05, the owner). Not built. After v10.0.1 (0112), which moves the decision job out of the API (decision 10) and gives it stage logs and a time limit (decision 12).

**The owner (2026-11-05):** "Incremental decisions: recompute only stories that new answers touched, not all 347 stories and the full News on every upload."

**Constraints:**
- the result must equal a full run's result: same stories, memberships, connections and News rows. A full run stays as the check, and as the nightly run;
- Mark IX's tables never change because of Mark X;
- keep everything: changes close rows (`valid_to`), never delete;
- nothing merges unless `scripts/realdata-check.sh` passes.

## Why
- **Every run recomputes everything** (`decide.run`). It takes:
  - all of Mark IX's stories with a post in the window;
  - every answer;
  - glue, merges, the second pass and the whole of Mark X News.

  And it does that **after every upload** (60 s later) and hourly.
- On 5 Nov the first big batch of answers, 313 merges and about 1,400 entities, joins and pairs, made one run spin the API process at 101% for minutes (0112, wrong today 5).
- Most uploads change a handful of stories: a batch of 20 joins touches at most 20 stories, and a merge two.
- With the reading window growing to 120 days (0112 decision 9), and later the decision window, a full run grows with the archive, not with the change.

## What it does
1. **Dirty set.** An accepted answer marks what it touches:
   - a join or check: its story and its post;
   - a pair: the pair's two posts and any story either is in;
   - a merge: both stories;
   - a card, headline or connect: its story or stories.

   New posts, readings and entities mark their candidates' stories. Kept in a small `mx_dirty` table (kind, id, since), cleared by the run that handles it.
2. **Closure.** The run expands the dirty set to everything a change can reach:
   - the stories glued or merged with a dirty story (its union-find group);
   - the stories sharing a post with it;
   - the stories its second-pass questions compare (the candidates of its new members).

   Everything else is untouched and kept as it is.
3. **Recompute only the closure:**
   - plan its questions, apply glue and merges inside the closure, and run the second pass for its new stories;
   - write only the changed memberships and connections (opening new rows, closing changed ones), as a full run does today.
4. **News incrementally:**
   - recompute only the rows whose stories are in the closure, plus rows that lost or gained a story;
   - the rest of the day's rows stay;
   - tags (NEW / CHANGED / MERGED / SAME) are computed for the changed rows against Mark IX the same way.
5. **The full run stays,** nightly, and whenever a guide or a rule changes (the code version or a guide id differs from the last full run's). It is the check: if a full run would change anything the incremental runs left, the difference is logged as an incremental-run bug, with its stories.
6. **Shown:** `/api/markx/status` and the Worker tab show each run's kind (incremental or full), its dirty count, its closure size and its duration.

## Measure before building
- **On the server copy with 5 Nov's answers:** replay the uploads in their order. Incremental runs after each, against a full run after each:
  - the outcome must be identical at every step: stories, memberships, News rows and tags;
  - **time:** an incremental run after a batch of 20 answers in under 1 s;
  - **the full run's time** recorded, on 30 and on 120 days.
- **The closure's size:** the median and the largest per upload. Flag a closure over 25% of all stories (a hub story merged with many): such a run is as costly as a full one, and should simply be one.

## Not in this issue
- Moving the job out of the API, and its time limit: that's 0112 decisions 10 and 12, needed first.
- Deciding over 120 days: a separate setting once this lands, since this is what makes it affordable.

## Built (branch `issue-0112-reask-and-0116` from main 3fde2c6, 2026-11-06)
Not merged, not pushed, not deployed. Built with [0112](0112-mark-x-v10.0.1-live-fixes.md)'s Decided 8 on the same branch; it leaves 0112's decisions 10–12 (the job out of the API, the time limit, stage logs) to their own branch, and touches none of its files (the Scheduler, `api.py`'s jobs and upload hooks, `main.py`, compose, `checks/`).

**Measured first, on the server's copy** (v10.0's real-Haiku copy, 30 days, 6,606 posts, 275 stories, 2,308 questions): a full run is 2.76 s, and almost none of it is deciding.
- Reading: the posts' texts 0.47 s, near-copies 0.29 s, each question's task and answer one query at a time 0.45 s, Mark IX's StoryPosts for every News post 0.87 s.
- The rules (plan, glue, merges, both passes): 0.05 s.
- On 120 days: 4.33 s (808 stories, 6,213 questions).

So an incremental run re-reads only what changed, and runs the same rules over the same world (`markx/incremental.py`).

**What changed:**
1. **The dirty set** is every judge task whose (status, valid calls) changed since the last run: one query for all of them (20 ms), then the calls of those tasks only.
   - An answer, a second ask (0112 Decided 8) or a failure changes that pair, and calls are never changed or deleted. So no writer has to mark anything, and none can forget to.
   - **Not built as specified:** the `mx_dirty` table. The query is the table: it can't miss an answer, and needs no migration (the other branch may take 0070).
2. **The closure** is what the dirty answers reach: the Mark X stories holding their posts, now and in the last run (merge groups), those posts' Mark IX stories, and the stories sharing a post with any of them.
   - It is reported (`counts.run.closure`, and `hub` for over 25% of 40+ stories).
   - **What is recomputed:** the database reads of the closure's answers; the rules are re-run over every story because they cost 50 ms, and that is what keeps the result a full run's.
   - **What is written:** only the memberships and connections that changed (`persist`, as before).
3. **Texts** are re-read only where Mark IX's rows changed: a stamp per table (`posts`, `post_parts`, `post_links`, `sources`: rows, newest xmin, a hash of every row version; 60 ms), then per post only when a table changed. New posts are always read. Readings are stored once and never changed, so only posts with none are read again. Near-copies, the rules' posts and the connect inputs are kept by their posts' row versions.
4. **News incrementally** (`news.write`): only the rows the changed stories reach are made again, as Mark IX's own incremental News (0072 A).
   - **The seeds:** the posts of every story whose members or mentions changed, now and before; the posts that came into or left the window; the stories whose start left it.
   - **The group:** the seeds and every row, story (members and mentions) and surge holding one of them, until nothing joins.
   - The rest of the last run's rows stay; every row is tagged again against Mark IX.
   - It is in full when Mark IX's posts, parts, links, sources, surges or roundups changed (a new post can change another post's StoryPost through its links).
5. **A run is full** without the last run's memo (a start, another process ran last, the last run failed), when the code version, config or a guide changed, nightly (the first run after 04:00 server time, by the runs' own clocks), and with `run(full=True)`.
   - **The check:** a full run with a memo first reads the same snapshot as an incremental run would, writing nothing, then reads it in full. Any difference in stories and memberships, typed connections or News rows and tags is logged as an incremental-run bug, with the stories' posts (`counts.check`).
6. **Shown:** `counts.run` (in `/api/markx/status`'s last run): kind, dirty tasks and posts, texts read, Mark IX tables changed, closure, changed stories, seconds. **Not built:** the Worker tab's display (frontend).

**Measured: a replay of the copy's answers, in their order** (`insight_server_1105_mxreal_check_<pid>_{b,d}`).
- **How:** the 3,446 recorded judge answers were hidden, then shown again 20 at a time in the order they were made: 173 batches.
  - A task a run asked again got its recorded first answer once more, as its second (504 of them). That exercises joins, pairs and merges. It is a simulated agreement, not a measurement of Haiku.
  - After each batch: an incremental run, committed; then a full run of the same snapshot, rolled back.
- **Identical at every step, in both replays:** the full run wrote no membership, connection or News row, and its check found no difference (0 of 173 steps; replay 1 at be9a884, replay 2 at the final code).
- **Time, replay 2:**

| Measure | Value |
|---|---|
| Incremental run | median **0.66 s**, p90 0.74 s, max 1.20 s |
| Over 1 s | 2 of 173, while the machine was loaded (the full runs at those steps took 3.9 and 5.2 s against a median of 3.4 s) |
| Full run with its check | median 3.4 s |
| Dirty tasks a batch | median 22, max 36 |

- **The closure:** median 21 stories, largest 54 of 345 (16%); none over 25%. News was made incrementally at every step; rows were written 102 times.
- **After real second asks** (0112 Decided 8's copy, 342 stories, 3,000 connect pairs): an incremental run is 0.58 s with nothing new, against 2.7 s for a full one. One upload of 471 answers had a closure of 142 of 341 stories (flagged as a hub) and took 1.03 s.

**Tests** (`test_markx_incremental.py`, 6):
- every incremental run is a full run's result: a full run of the same snapshot writes nothing and its check finds no difference, after each of 5 answer batches;
- the dirty set is the tasks answered since, and a quiet run reads no text again;
- a changed post's text is read again, and News is then made in full;
- the check finds a memo gone wrong, with its stories' posts;
- a run is full without the last run's memo, with another rule, and nightly, and the nightly check finds no difference;
- a failed run leaves no memo.

**Proposed real-data invariant** (`checks/` is the other branch's, so not edited): `markx.incremental_matches_full`, a job check on the head's copy after its deploy runs, in one transaction rolled back.
- Hide the newest 60 judge calls, run `decide.run(full=True)`, then show them 20 at a time with an incremental run after each, then run `decide.run(full=True)` again.
- Count that last full run's memberships, connections and News rows written, plus `counts.check.differences`. The bar is 0.
- Also report the incremental runs' seconds (under 1 s) and their closures.

**The suite and the real-data check:** as in [0112's Built: Decided 8](0112-mark-x-v10.0.1-live-fixes.md): backend 1,859 after merging main (1 unrelated flaky search test, which passes alone), worker 51 OK. `realdata-check --base main --head issue-0112-reask-and-0116 insight_lab`: **PASS**, 0 change in every derived thing, every invariant equal, Mark IX unchanged.
