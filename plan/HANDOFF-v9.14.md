# Handoff: v9.14 in progress (2026-11-01, device turned off)

## Where things stand
- **main** is at `cbd0baa`: v9.13 (0071), plus 0072 C (safety) and 0072 B (rows that read right) merged. Backend 1,287 tests OK; frontend node 213 OK. Nothing is pushed; the owner decides pushes.
- **Not done in 0072:** part A, "a light API". It waited for the API memory analysis, which was mid-run when the device went off.
- **The lab** (`insight-lab-api`/`insight-lab-web`, 127.0.0.1:8100/3100) runs v9.13 (`c2859d8`), not B or C yet. After a reboot, run `docker start insight-lab-api insight-lab-web`.

## The API memory analysis (branch `issue-api-memory`, worktree `.claude/worktrees/agent-aa71ed88ebbf9159b`)
- **Question:** the API holds ~926 MB at idle after its first start on the lab (41,637 posts). v9.12's resource review measured ~475 MB.
- **Found so far** (from its code and comments; its full numbers are in `plan/research/api-memory/HANDOFF.md` if it got to write one; private, gitignored):
  - **Most of the idle memory is freed memory never returned to the OS, not live objects.** It measured "612–949 MB after the first start, ~40 MB of it live". glibc and Python reuse freed memory but seldom return it.
  - **The stored-bodies repair (0068's `drop_hidden_link_labels`) loads every body at once:** 2,958 bodies, 214 MB of HTML, taking the API to 796 MB. Its work in progress reads them in batches of 200 with a named server-side cursor (`repo_posts.BODIES_BATCH`).
  - **Heavy jobs in their own process:** `stories_service.in_own_process(job, *args)` runs a job in a fresh `spawn` process and waits for it, so its memory goes back to the OS when it ends. With the start's work run that way, the API holds ~47 MB. The ingestion runner already calls `recompute_job` through it. `main.py`'s start-up path was being changed the same way.
  - Its measurement scripts are in `plan/research/api-memory/` (private).
- **Its uncommitted changes when stopped** (6 files, +103/−14): `db/repo_posts.py`, `ingestion/__init__.py`, `services/stories_service.py`, `main.py`, and tests in `test_reading_gaps.py` and `test_stories.py`. It was asked to commit them as a WIP commit; check `git log main..issue-api-memory`, and if they're absent, look in the worktree.
- **Approaches it was told to measure** (see the 0072 spec, part A):
  - A: `malloc_trim`, `MALLOC_ARENA_MAX`;
  - B: child process (in progress, looks like the winner);
  - C: dropping references;
  - D: streaming, names-only phrases in the News pass, compact records, Classics in SQL.

  Each to be measured for idle, peak, job time and row-by-row identical results.

## To continue
1. Finish or redo the memory analysis on `issue-api-memory`. Measure B, with A as a fallback, on a scratch copy of `insight_lab` (back to back, with the load average recorded). Confirm stories, News, Classics and Discover are identical, then merge.
2. Build 0072 part A on top: the incremental story job (the full rebuild stays as the oracle), `post_edges`, fewer writes, smaller Discover and `/api/sources` answers, "first" only when true, and threads as one item in News and trees.
   - Also from B's Left open: a short single-topic post shouldn't count as a roundup, and a title with no words should take its story's origin title. Both need the story job.
3. Update the lab, and run the owner-style reader review plus a memory and load re-check.
4. If the review finds problems, spec and build v9.15 without waiting (owner, 2026-11-01). If nothing needs fixing, say so and stop.

## Rules that hold
- **Download nothing** (limited connectivity).
- **`plan/research/` is private:** never commit it, and no real channel names in committed files.
- The lab and server copies are read-only for agents.
- Never touch the live `insight` DB or the server.
- Keep the local `sources.json` (now untracked) when merging.

## Waiting on the owner
- Rewriting the unpushed history to drop `plan/research/`.
- Channel names in `plan/issues/` and older test fixtures.
- The source list already on GitHub.
- Cleaning this machine (worktrees, images, scratch databases).
- yt-dlp pinned or not.
- The arXiv address forms (R16).
- The server's `docker version` (compose `start_interval` needs Engine 25+).
- Deploying: put the server's own `sources.json` back before the first v9.14 start; run `repair_full_text` only once on v9.14+.
