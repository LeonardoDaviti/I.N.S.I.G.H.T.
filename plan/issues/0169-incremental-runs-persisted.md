# 0169 — The decision run's incremental state in Postgres (built)

Status: **built** (Stealth v10.15 part C, branch `v1015-incremental` from main 7b651e5). Not merged, not pushed, not
deployed. Migration **0113**. The owner chose this over a long-lived decision process.

## The problem (found 2026-11-12)

[0116](0116-mark-x-incremental-decisions.md) made a decision run re-read only what changed since the last run and
re-run the rules over the same world, with a nightly full run as the check. Its memo lived in the process. Since the
jobs left the API (0112 Decided 10) every decision run is a spawned process of its own (`jobs.Runner._in_own_process`),
so no run ever found the last run's memo: every run was "full". On the server: 137 s, 28,902 texts read, 2,706
stories; peak RSS 2.8 GiB in "questions and decisions" (every post of the window with its full text and its reading,
kept for the whole run) and 3.36 GiB in entities.

## What was built

The state a run needs from the last one is kept in five tables (migration 0113), written in the run's own
transaction (`incremental.save`), read by the next run in a fresh process (`incremental.open_state`).

| table | holds | keyed by |
|---|---|---|
| `mx_inc_state` | the run that left it, its key (code, config, guides), Mark IX's table stamps, the last News inputs and rows, the last memberships (typed json, `incremental.encode`) | one row, `decide` |
| `mx_inc_posts` | each world post as the rules read it: source, kind, time, words | the post, with its text stamp (`plan_marks.STAMP`) |
| `mx_inc_inputs` | a question's input hash | its kind and the stamps of the posts it shows (+ their readings' row versions where it shows a reading, + the cards a merge shows) |
| `mx_inc_copies` | a story's near-copies | its members' stamps |
| `mx_inc_tasks` | each judge task's (status, valid calls) as the last run saw it | the task |

**What an incremental run reads** (`incremental.world`, `rendered`, `copies`, `refresh`):

- The rules' posts from `mx_inc_posts`. A post's text is read only when its stamp changed or it is new (when none of
  Mark IX's text tables changed since the last run, the kept stamps are not even recomputed). Readings: kind and
  events from mx_readings' jsonb, which posts have one, and each reading's row version; never every reading.
- Every question is still planned and settled as before, but its input is not rendered: its key (what it shows) gives
  the input hash, which is all a run needs to find the task and its answer. A key that misses (a new question, a
  changed post, a new reading, a new card) is rendered from the texts, read then in one query (`LazyTexts`,
  `LazyReadings`). A kept input is rendered only if its task must be added; it is checked against its hash then.
- Answers: the calls of the tasks the kept inputs name, in one query; any other on first use.
- The dirty set: every judge task whose (status, valid calls) differs from `mx_inc_tasks`, in the same one query as
  before. Reported with its closure in `counts.run` (as 0116).
- News: the last run's inputs and rows from `mx_inc_state`, so News is made again only for the rows the changed
  stories reach (0116's `news.write`, unchanged), and in full when Mark IX's posts, links, surges or roundups changed.
  The News rows' own headline questions are kept like the others (`news._ask_row_headlines_kept`).

**The rules still run over the whole world** (plan, glue, merges, both passes, the matching of stories in `persist`,
connections): they are global and cheap next to the reading, and running them in full is what makes the result a full
run's. Every kept value is a function of the rows its key names, so a key that matches can only give what a render
would; the code that makes them is in the key (`incremental.code_stamp`, a sha256 of the modules that render, read and
make News), so any code change makes the next run full.

**When a run is full** (nothing kept is trusted; everything is read; the state is written whole again): no state, or
the state is not the last finished run's (a run that fails rolls its state back with it, so the state stays the last
finished run's and the next run is still incremental), the code, config or a guide changed, nightly (the first run
after 04:00 server time), and `run(full=True)`. A full run with a state first reads the snapshot as an incremental run
would (writing nothing), then in full, and logs any difference as an incremental-run bug with its stories
(`counts.check`, as 0116 defined it).

**Kept rows are a cache, not derived rows**: each run keeps only what it used (the inputs, near-copies and posts of
this world); a full run rewrites them. Nothing of Mark IX's, no post and no Mark X story, membership, connection or
News row is deleted.

**The first run after deploying**: there is no state, so it is a full run, as every run is today (same time and
memory, plus writing the state: on the copy 9,668 posts, 9,575 inputs, 1,940 near-copy sets and 4,947 tasks in
0.24 s). Every run after it is incremental until the night's full run.

## Equivalence

**Tests** (`test_markx_incremental.py`, 8; `test_markx_decide.py` and `test_markx_pairing.py` unchanged in what they
check):
- after each of 5 answer batches, an incremental run and then a full run of the same snapshot that writes nothing
  (no membership, connection or News row) and whose check finds no difference;
- a seeded random world (8 sources, 36 posts in 6 topics, Mark IX stories, random candidates), 8 rounds of random
  answers of every kind, relation and confidence, with a text changed, a new post with candidates and new readings in
  some rounds: every round incremental, every round's full run writes nothing and its check is the same;
- the dirty set and closure; a quiet run reads no text, renders no input; a changed text or a new post is read again
  (one text) and its questions rendered again;
- a state gone wrong (the kept check inputs pointing at no task) is found by the check, with the stories' posts, and
  the full run writes the state whole again;
- a run in a new process is incremental; full without the state, with another rule, with other code, nightly;
- a failed run leaves the last finished run's state: the next run is incremental and right;
- the state's codec gives back what it was given (types included).

`test_markx_storage.py` lists the five new tables (its count of mx_* tables is 56). `test_markx_pairing.py` compares the decision run with a verbatim copy of the code before Pairing
(`tests/legacy/decide_a395c13.py`), which used 0116's in-process memo: that module is kept verbatim as
`tests/legacy/incremental_a395c13.py` and the legacy decide imports it (the only change to the legacy copy).

**On real data** (a scratch copy of `insight_server_1105_mxreal`, migrated; story window "everything", backfill a year
back: 9,668 posts, 1,886 stories, 41k tasks; 300 judge answers hidden, chosen at random within each judge kind but
briefing, then shown 25 at a time in the order they were made). Two copies of the same seed: "before" ran main's code (each run a fresh process, so full),
"after" this branch (incremental), one committed run each a round, then on "after" a full run of the same snapshot,
rolled back. After every round the copies were diffed without their ids (current memberships by their member sets,
story first dates and headlines, current connections with stories as their member sets, every task's kind, guide,
input hash, status, priority and posts, the newest News rows with their tags):

- **18 rounds, every one the same on both copies** (stories, story heads, connections, tasks, News: identical
  hashes), and every round's full run on "after" wrote nothing and its check said `{"same": true}`.
  - Rounds 0–11: the 300 recorded answers shown again 25 at a time (check, join, pair, merge 60 each; card, headline,
    connect 20 each). Memberships changed in rounds 0 and 3; the rest settled questions (asked again) without
    changing a story.
  - Rounds 12–17: 60 new answers a round to open judge tasks (relations and confidences across the bars, made from
    the task's input only, so both copies got the same rows): new stories, joins, removals and closed connections
    every round (e.g. round 17: 2 stories new, 7 memberships opened, 1 closed), all equal.
  - Rounds 6 and 14 also wrote 300 post rows again (nothing in them changed: ingestion's kind of write): the
    incremental run read 60 world posts' texts again, rendered their questions again (same hashes, so the same
    tasks) and made News in full.
  - Round 12 ran after rebuilding the branch's image with one more edit: the code stamp differed, so the run was full
    (as after a deploy) and wrote the state again; it equalled main's run too.
- Before the rounds, the branch's first run on the seed (full, no state) wrote no membership, connection or News row
  over main's last run, and the copies were identical.

## Measured (seconds and peak RSS per stage, the same copy, each run a fresh process)

Medians over the rounds where only answers arrived (15 runs each; the copy is the server's of 5 Nov: 9,668 posts in
the window, about a third of the server's 28,902 today). Peak RSS per stage is the process's high-water mark during
the stage (VmHWM reset at each stage start).

| stage | before (main: always full) | after (incremental) | after, full with its check |
|---|---|---|---|
| load (the state read; the check's incremental reading) | 0.01 s, 44 MiB | 0.17 s, 62 MiB | 1.31 s, 93 MiB |
| questions and decisions | **3.48 s, 224 MiB** | **0.80 s, 92 MiB** | 3.31 s, 229 MiB |
| write | 0.07 s | 0.07 s | 0.07 s |
| connections | 0.34 s | 0.20 s | 0.34 s |
| graph | 0.12 s | 0.14 s | 0.14 s |
| back | 1.38 s | 1.36 s | 1.31 s |
| headlines | 0.02 s | 0.01 s | 0.02 s |
| news | **1.34 s, 278 MiB** | **0.12 s, 94 MiB** | 1.36 s, 258 MiB |
| entities | 0.78 s, 277 MiB | 0.74 s, 136 MiB | 10.23 s (`full=True` is the entities' full pass too) |
| surges | 0.09 s | 0.08 s | 0.25 s |
| perspectives_plan | 0.36 s | 0.48 s | 0.86 s |
| **the run** | **8.06 s, peak 278 MiB** | **4.24 s, peak 136 MiB** | 18.90 s, peak 274 MiB |

- An incremental run with nothing new reads no text and renders no input (texts_read 0, inputs_rendered 0); with 60
  new answers it read 241–333 texts (the posts of the questions its new structure asks) and rendered 78–149 inputs.
- With 300 post rows written again (rounds 6 and 14): 4.84 s against 6.85 s (round 14; round 6 ran while the machine
  was loaded by other suites: 11.2 s against 7.7 s, every stage of it slower), questions and decisions 0.92 s and
  93 MiB, News in full 1.04 s and 164 MiB peak.
- A full run of this branch without a check (round 12, the first after a code change): 7.03 s against main's 6.53 s
  the same round (questions and decisions 2.96 s, 226 MiB, against 2.82 s, 224 MiB); writing the whole state took
  0.24 s.
- What is left of an incremental run is mostly other stages' own reads (back 1.4 s, entities 0.7 s, perspectives
  0.5 s) and, in questions and decisions, the reads every run makes in SQL: every post_post candidate and its
  vectors' check (embed.current_candidates, 0.36 s), the Mark IX story rows, the light post rows, the tasks' one
  query, the centroid cosines.

The server's numbers will differ in size, not in kind: the 2.8 GiB came from the full texts and readings of every
world post (and the memo); an incremental run holds the light rows (source, kind, time, words, the reading's kind
and events), the tasks' index and the answers of the questions it asks.

## The entities stage

Not changed; it cannot follow the decision run's dirty set. Its inputs are the mentions and the entity answers
(alias, alias2, collide), not the judge tasks or the stories, and it is already incremental by the database
(entity_stage's docstring): a run links the mentions that have no entity yet and decides the pairs answered since the
last run's start; the nightly pass relinks everything in chunks within its own budget. What costs on the server is
fixed per run: `identity.load_book` reads every entity, alias, redirect and pin and every entity's mention-type counts
(a GROUP BY over mx_mentions_now) into memory, and a run reads it three times (entity_stage.entities,
surges.stage, perspectives.stage; 0.12 s each on this copy's 8,216 entities, 2.0 s each on the scale copy's 250k).
Making the stage follow its own dirty set means keeping the book, or an index of it, in Postgres and reading only
the clusters a run touches: identity.py's design, which a concurrent branch owns, so it is left to it. A cheap first
step for that branch: read the book once a run and hand it to surges and perspectives.

## Not done

- **News under changed posts.** News is made in full whenever Mark IX's posts, parts, links, sources, surges or
  roundups changed (0116's rule: a post's StoryPost depends on the stored posts its links name and on every source's
  facts). On the server ingestion writes posts between almost any two runs, so there News will usually be made in
  full (round 14: 1.04 s, against 0.12 s incremental). Making it incremental then needs those dependencies as seeds
  (the changed posts, the posts linking their addresses, a changed source's posts).
- **A written but unchanged post row re-reads that post.** The stamp is the row versions; ingestion rewriting a row
  makes the post's text and its questions read and rendered again (same inputs, same tasks), as measured above.
- **Still read in full each run, in SQL:** every post_post candidate (and embed.current_candidates over them), Mark
  IX's story rows of the window, every judge task's status and calls count, the Mark X stories touching the world
  (`persist`), the centroid cosines of every story pair. Light in the process, O(world) in Postgres.
- **The rules run over the whole world**, by design (above).
- **The nightly full run costs what a full run costs today** plus the check's incremental reading (1.3 s here), and
  holds both readings' memory at its peak. `run(full=True)` also forces the entities' full pass (unchanged).
- **The Worker tab's display** of each run's kind (0116 left it): not built. `/api/markx/status` shows `counts.run`
  with the new `texts_loaded`, `inputs_rendered`, `inputs_kept` and `state` (rows written and dropped).
- `scripts/realdata-check.sh` was not run (as asked); the real-data equivalence above was run by hand on scratch
  copies, dropped after.

## Follow-up: a repost counts as its author only when a source follows the author

0168 E counted every repost (an X repost, a Telegram forward) as its original author's voice in `tasks.voices`, while
the decision rules counted the feed. Counting every reposted account (tried on branch `v1015-voices`, not merged)
turned 218 of 1,886 stories on the server's copy from 1 voice into 2+, all from one feed and most of them one
account's conversation with strangers. Now one rule, Mark IX's (StoryPost.author_source, issue 0068), in Pairing's
voice basics:
- `pairing.counted_voice(source_id, author_account, of_account)`: a post its feed carries but another account wrote
  counts as that account's source when one of the sources follows that account (`pairing.followed_accounts`: Mark
  IX's `SourceFacts.of_account` over every source, the first source by id), else it stays the feed's own voice. A
  quote or a reply is the feed's own post (its author is the feed), so the quoted or replied-to account never adds a
  voice. Accounts are Mark IX's form (`source_account`): x.com/<user> for an X repost, t.me/<channel> for a Telegram
  forward whose header names the channel (`forwarded_from.username`; a forward by name alone names no account).
- `tasks.Post.voice` is that voice (`tasks.voices`, decide's rule Posts in the full path and in the kept state:
  `mx_inc_posts.voice`, migration 0114). The credit renders keep (`by`, "a post by @acme shared by <feed>") is
  unchanged.
- The kept state: `STATE_VERSION` in the code stamp makes the first run after it full; which source follows which
  account is not in any post's stamp, so its digest (`incremental.accounts_stamp`) is in the state's key: a source
  added or changed makes the next run full.
- Tests: two feeds forwarding one followed channel are one voice (never checked); a stranger's forwards stay the two
  feeds' voices; a feed quoting a stranger is one voice; the state keeps the voice; a member that becomes a forward is
  read again; a source that starts following the stranger makes the next run full and the two forwards one voice;
  incremental equals full throughout. 0168's own test now says a stranger's repost counts as the feed.

**Measured** on a scratch copy of `insight_server_1105_mxreal` (migrated, story window everything; v1015 settled
first, then two copies, v1015 against this rule, one run each, then the copies diffed):
- 56 of the 9,668 world posts count as another source (of 3,819 X reposts in the copy; no Telegram forward here).
- 5 of 1,886 stories count other voices (4 from 1 to 2, 1 from 3 to 4). Memberships, connections and News rows: the
  same; 4 headline questions more (for the stories now of 2 voices). Incremental equals full after it.
- The 5 (all of them): two followed accounts on one event, one reposted beside the other (a pricing change and an
  employee's note on it): right. A followed account's post reposted beside the feed owner's own reply to it: right by
  the rule (two followed people), a thin story. A 3-feed story that already mixed unrelated posts gains a fourth
  followed voice: the count is right, the story was wrong before (its checks can now take the stray posts out). Two
  stories of one feed's own aside and a followed account's quip, or two unrelated reposts of followed accounts: the
  count follows the rule, the stories are chatter Mark IX put together; as 2-voice stories their members are now
  checked.

## Follow-up 2: a concurrent update never loses the run

**The server's failure** (v10.13.11, 2026-11-12: ok false after 103.6 s, "could not serialize access due to
concurrent update", stages logged up to back, so it failed in later). A decision run is one REPEATABLE READ snapshot;
Postgres fails any write of a row another transaction changed after the snapshot. The run's later stage plans back
questions (`later.plan`, v10.13.11 later.py:452–453: `tasks.add`, i.e. repo.py:100 `INSERT ... ON CONFLICT (kind,
guide, input_hash) DO NOTHING`, then `UPDATE mx_later SET task_id`), as does back's (back.py:382–383, and its clock
back.py:446). The same rows are written meanwhile by the worker: a lease of `back` runs the same planners in the API's
transaction (api.py:284–292 → tasks.py:646 `_plan_back` = back.plan + later.plan; v10.14 skips it while a run holds
its lock, but a lease that began before the run still commits inside it), and leases (repo.py:143, status 'leased')
and answers (back.py:388, reopened) change the back tasks themselves. An insert whose conflicting task row is newer
than the snapshot, or an update of an mx_later/mx_back row the lease planned, is a serialization failure, and the whole
run rolled back. Shown by `test_the_cause_a_task_another_transaction_changed_since_the_snapshot_fails_its_insert`.

**The fix (the class):**
- back and later plan each row in a savepoint (`back.planned`): a row another transaction planned, or a task it added
  or leased since the snapshot, is left for the next plan (which finds the task and points the row at it), as Ask
  already does for the judge kinds and graph for relate.
- every stage after the run's own decisions (graph, back, later, entities, surges, perspectives, briefing) runs in a
  savepoint (`decide.run`'s `guarded`): any other serialization failure or deadlock undoes that stage's writes only,
  is logged and shown (`counts.deferred`), and the next run does it (each stage resumes from its own clock; an
  entities stage deferred writes no `entities` counts, so a half-done full pass resumes from the last record). The
  run's decisions, memberships, connections, News and the kept state (0169) are written by the run alone and kept.
- Decisions are unchanged (no stage reads another's deferred writes; the core is as before). Tests with two
  connections: a back question a lease asks mid-run is skipped and planned by the next run; a stage's row updated
  mid-run defers that stage, the run commits with its stories and its state, and the next run is incremental and
  does the stage.
