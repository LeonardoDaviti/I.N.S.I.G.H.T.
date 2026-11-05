# 0110 — The v9.17 rebuild stops on its first stories batch: a mention of a story the batch removed

Status: **built** 2026-11-05 on `issue-0110-rebuild-fk`, not merged (Built, below). Urgent: production's story job has failed on every run since the v9.17 deploy.

**Constraints:** download nothing; no real names in committed files; nothing merges unless `scripts/realdata-check.sh` passes; keep everything.

## Wrong today
After the v9.17 deploy the rules stamp changed (0103 A's thread rule and 0106's paper ids). The server's story rebuild did its keys, threads and names steps and queued 48,371 posts. Then every story-job run failed on its first `stories` batch, with `ForeignKeyViolation: story_mentions_story_id_fkey` from `write_stories`. Stories never update, and the pages serve the old ones.

## Cause (measured on a scratch copy of the server's data)
- The first batch's scope holds 2,070 posts, 210 stories, and 5 stored stories that are removed.
- One removed story holds two posts, joined only through one paper's page. Under the new rules (0106: a paper id is one page across its host's paths), that page is no node of the grouping, and the two posts go to different stories.
- Six roundups of the scope list that page. It is outside the scope's stories, so `_batch` asks `stories_holding` which stored story it is in. A page's story was read from the stored link edges of its linkers, and those linkers were the two scope posts, whose story this same batch removes. `write_stories` deletes the story, then inserts the six mentions of it.
- So the class: a page that only the scope's own posts linked, once they stop being joined through it (a rule change, or an edit of their links). It isn't specific to the rebuild: the synthetic test below hits it with two edited posts and a new roundup in an ordinary batch.
- Membership is closed: in every batch of the full rebuild, no post outside the scope was in a removed story (0 of 52 batches). So `ON DELETE CASCADE` dropped no outside post's story.
- The 23 mentions by outside roundups of removed stories, which `write_stories` deletes, are correct. The full rebuild afterwards writes the same rows (below).

## Built (branch `issue-0110-rebuild-fk`, 2026-11-05)
From main fe74d7b, two commits. No migration. Nothing fetched or downloaded.

1. **The fix** (7da9ac2): `StoriesRepository.stories_holding(nodes, besides=scope)` reads a node's stored story only from posts outside the scope. For a page, that means its linkers outside the scope. The scope is closed over stored stories, so their stories are not rewritten. A page only the scope linked, and which the new grouping leaves in no story, maps to nothing, so it is mentioned by nothing, as a full run says. The change is two lines in `_batch` and the query.
2. **The check runs what a deploy runs** (8d1a9c4): `realdata-check.sh` never ran the incremental rebuild that a rules-stamp change starts. It ran a full job, then a second full rebuild, then the identity check over queue batches. Each side now first runs a deploy's first start: `StoriesService.recompute()` over the copy as stored, step by step to the end. When the copy's rows are of other rules, that is the rule change's rebuild (keys, threads, names, then every post in batches). Then comes the full job (`checks/job.py --deploy-json`, `side.sh`). The new invariants are in `deploy.json`:
   - `story.deploy_start`: the start raised. It fails the check even when main raises too.
   - `story.deploy_identity`: rows the start leaves unlike the full rebuild after it.
   - `story.deploy_lost`: posts in a story after the full rebuild, in none after the start.
   - `story.dangling`: story_posts and story_mentions rows that name no stored story. It must be 0.

   The scratch-name rule (`_check_<pid>_[ab]`) accepts `insight_server_1105_check_<pid>_a` (tested).

**On the server's data** (scratch copies of `insight_server_1105`, dropped afterwards; the machine was shared, load 25–28):

| | main fe74d7b | branch |
|---|---|---|
| deploy's first start (the stories phase of the rule change, 48,371 queued + 6,805 changed) | raises on batch 1 after 18 s: the server's error, story 29022848… | **52 batches to the end, 2,721 s (45 min)**; a second run with per-batch probes: 2,994 s |
| rows unlike the full rebuild after it (stories, story_posts, story_mentions, News, Classics) | 3,338 of 11,200 | **0 of 11,200** (the full job after it changed 0 rows, 0 edges, 0 keys) |
| posts lost (in a story by the full rebuild, in none after the start) | 746 | **0** |
| story rows naming no stored story | 0 | **0** |
| per batch: mentions to a removed story / outside posts in a removed story | 6 / 0 (batch 1) | **0 / 0 in all 52** |

After the branch's rebuild there are 2,206 stories and 6,170 posts in stories; the copy as stored had 1,936 stories and 5,464 posts.

- **Tests:** `test_incremental_stories.test_a_roundup_listing_a_page_its_story_left_mentions_nothing` shows the same shape in an ordinary batch. It went red with the same `story_mentions_story_id_fkey` error, then green, and checks every story row is whole and a full run then changes nothing. Two more tests: `test_realdata_checks.test_a_deploy_start_that_raises_fails_the_check_even_when_main_raises_too` and the scratch-name test. Backend suite (`./run-tests.sh`, image `insight-backend:i0110`): 1,462 tests, 1 failure under load (`test_deploy_finishes`, a 30 s thread wait on search vectors), which passes run alone (5 of 5).
- **The real-data check:**
  - `--base main --head issue-0110-rebuild-fk insight_lab`: **PASS**, no `--allow`. No case changes state (75 pass, 16 fail, 1 error, 17 not checked). The diff is 0 in every part. On the lab the deploy start is the queue only (its rows are of main's rules): 0.6 s, identity 0 of 8,908.
  - `... insight_server_1105` (2,743 s): the verdict is **FAIL, on the cases only**. The cases are the lab's: 13 marked pass fail on main and on the branch alike ("no stored post" on the server's data), and against main no case changes state. B, the invariants, have no rise:

    | | main | branch |
    |---|---|---|
    | `story.deploy_start` | 1 (the server's FK, 18 s) | 0 (a rule change's rebuild, about 25 min) |
    | `story.deploy_identity` | 3,338 | 0 of 11,200 |
    | `story.deploy_lost` | 746 | 0 |
    | `story.dangling` | 0 | 0 |
    | `story.identity`, `story.rebuild_identity`, `story.id_changes` | 0 | 0 |

    C, the diff after the full job: 0 in titles, text, roundups, story membership, origins, News and Classics. Discover differs by 1,582 (moved 1,232, names changed 142, voices changed 140, 64 gone, 4 new). That is the check, not the fix. Discover keeps its counts by a stamp that holds the last story run's time. On the check's one frozen clock, the branch's deploy start and the full job after it have the same time, so the full job kept the counts the start left. Main's start raised, so its full job counted again. Measured on a copy: a full job on the same clock keeps altered counts (1,432 kept), and one a millisecond later counts them (1,433). A deploy's clock moves, so the server isn't affected. Fixed in the check: the start runs a millisecond before the full job. That run was not repeated on the server copy.

## Open
- `table_rows.story_ids` reads story_posts as (story, post), but the table's columns are (post_id, story_id). So `story.id_changes` compares the wrong thing. Not changed here.
- Batch time on the server's data: 90–180 s for the first changed-post batches, then 25–40 s for each batch of the rule change, on a loaded machine.
