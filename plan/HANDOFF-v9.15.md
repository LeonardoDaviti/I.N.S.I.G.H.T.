# Handoff: v9.15 in progress (2026-11-03, owner away)

## Where things stand
- **main = GitHub main.** The history was rewritten to drop `plan/research/`, then pushed as `bf8764d`. Local main has 3 more commits: the 0074–0076 specs, the approved merge rule, and this handoff. They aren't pushed; push only on the owner's word.
- **What's on main:** v9.6–v9.14 (0072 A memory, B, C, D), plus 0073 (phones). The last full run had backend 1,302 OK and frontend node 213 / vitest 688 OK.
- **The old history** is the local branch `backup/main-before-rewrite` (cf8b2cb). Older local branches still contain `plan/research/`, so never push them or merge them into main.
- **The server:** the owner was deploying `bf8764d`. The pull had stopped on `sources.json` until the steps in DEPLOYMENT.md were run (copy aside, `git checkout --`, pull, copy back, `./update`). Ask how it went, and ask for a fresh `pg_dump` of the server.
- **The lab** (`insight-lab-api`/`insight-lab-web`) runs `6a8bf29`, from before the memory fix, D and phones. Update it after the next merges. After a reboot: `docker start insight-lab-api insight-lab-web`.

## The merge rule (owner-approved, 0075)
- One area at a time.
- Parallel slices never share a file.
- A no-op move ships separately from a behaviour change.
- Nothing merges unless `scripts/realdata-check.sh` passes on the lab copy.

## v9.15 work in progress
1. **0075, real-data checks** (branch `issue-0075-realdata-checks`, worktree `.claude/worktrees/agent-a442fe23630fde7d9`).
   - **Committed:** A (cases runner), B (invariants), C (diff and row comparison) as 940a771, 5464084, dea32cc.
   - Its own job check is `checks/job_checks.py`. The "incremental equals full" invariant calls `insight_core.scripts.story_identity:check` from the incremental branch, and reads "not measured" until that merges.
   - **First catch on main:** `title.places.classics_stored`, 1,780 of 41,637 posts. The cause is `news_service.py:77` building stored titles without HTML. The incremental job owns that file, so the fix lands with it.
   - **Left:** `scripts/realdata-check.sh` (≤10 min), the replay of 0072 D2 to prove the diff, tests, docs, Built.
   - Its private notes: `plan/research/realdata-checks/HANDOFF.md`.
2. **0072 A, the incremental story job** (branch `issue-0072-incremental`, worktree `.claude/worktrees/agent-a69053ec605198387`).
   - **State:** a large WIP (33+ files, migration 0059, `scripts/story_identity.py`, `test_incremental_stories.py`), asked to be committed as WIP.
   - **Its branch starts from the old (pre-rewrite) main.** Before merging, run `git rebase --onto main backup/main-before-rewrite issue-0072-incremental`, then check `git log main..issue-0072-incremental -- plan/research` is empty.
   - **Left:**
     - the equality checks at 30, 300 and 3,000 held-back posts against a full rebuild;
     - the speed and memory tables;
     - the date-only fix (Terra leaving News early, HN's S-1 "first", Mistral's lead);
     - one function for the post fields the job reads (so 0076 can swap the source);
     - the `news_service.py:77` fix;
     - docs and Built.
   - Its private notes: `plan/research/incremental/HANDOFF.md`.

## Next, in order
1. Finish and merge 0075.
2. Finish 0072 A, rebase it, run `realdata-check.sh` on it, and merge only if it passes.
3. Update the lab, then run the owner-style reader review of v9.15 plus a memory and load check.
4. If the review finds problems, fix them. Then v9.16 = 0076, a post read once when saved (the stability release), reviewed on the fresh server dump. 0074 (a post in several stories) comes after the incremental job.

## Waiting on the owner
- How the server deploy went, and a fresh `pg_dump`.
- **Pushing:** the 3 local commits, and later merges.
- **The 7 stored Hugging Face bodies:** one-off reread (recommended), or drop picture-only lists at display.
- "Mark above as read" on phones and desktop; sticky day headers (0073's desktop flags).
- An "Export sources" button.
- Channel names left in `plan/issues/` and old fixtures.
- arXiv address forms; yt-dlp pinning.
- A real iPhone check of the safe areas.

## Rules that hold
- **Download nothing** (limited connectivity).
- **`plan/research/` is private:** never commit it, and no real names in committed files.
- The lab and server copies are read-only for agents.
- Never touch the live `insight` DB or the server.
- Keep the local `sources.json`, which is untracked, through merges.

## Update: 0075 stopped cleanly (2026-11-03)
- **Committed** on `issue-0075-realdata-checks`: A (940a771), B (5464084), C (dea32cc), and E as WIP (facf13f: `scripts/realdata-check.sh`, `checks/side.sh`, `checks/report.py`, tests). E's script and tests haven't been run yet.
- **On main:**
  - 90 cases: 60 pass, 14 fail (as marked), 16 not checked; no `pass` case fails. The cases run takes 32 s and the invariants 36 s.
  - The private `cases.json` now has machine `expect`s (backup: `cases.before-0075.json`).
  - Baseline: `title.places.classics_stored` 1,780; date-only marked first 44 of 1,400; text repeating its title 2,361; and others. All are in `plan/research/realdata-checks/HANDOFF.md`.
- **Left:**
  - run `realdata-check.sh` end to end and time it (≤10 min);
  - replay 0072 D2 (`--titles-only --base 80f262d --head 39f13ba`, expecting ~56 changed titles);
  - run the tests and the full suite;
  - docs and Built.
- **Incident:** the agent's cleanup removed `insight-lab-api`, because it matched containers by image. I recreated it the same day (same image `lab-6a8bf29`, compose `MALLOC_*` env, 247 sources before and after). Clean up by container name, never by image.
- **Kept to continue:** the image tag `insight-backend:check-0075` and `/tmp/0075/`. Remove both afterwards.
