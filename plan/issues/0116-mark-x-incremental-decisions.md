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
