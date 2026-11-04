# Handoff: v9.16 in progress (2026-11-04, owner pausing)

## Where things stand
- **The server** runs `c8a99cb`, deployed by the owner on 2026-11-04. That's v9.15 plus v9.16's first slices:
  - 0075, the real-data checks;
  - 0072 A, the incremental story job;
  - 0077 F + K, News over 30 days, kept, and on source pages;
  - 0082, counts that name what they count, and "Started it" only when first;
  - 0083, a name written as one word, a roundup never leads, "In News" on the post page;
  - 0076, a post read once at save;
  - 0084 A, Substack's cookie only where you pay.

  Its version label read "Mark IX v9.12" (the VERSION file was stale); VERSION now says v9.16 on main.
- **Checked from outside after the deploy:** News 117 rows, no Substack source in error. The owner still has to check Sources → Connections → the Substack test, which should say "full text on 1 publication you pay for". "No publication you pay for found" means the assumed answer format is wrong (see 0084 Built).
- **main = `6e49203`,** 24 commits ahead of GitHub, **not pushed**. On top of the deployed version:
  - **0088:** a 5xx or a timeout waits 12 h at most; health names the failing site; the rail lists sources by newest unread post;
  - **0080:** Discover — owners not platforms, references apart, followed sites never suggested, ranked 30 at a time, follow-test labels, page titles read once, archive rows that follow their archive;
  - the per-run scratch names in the real-data check;
  - DEPLOYMENT's first-start timing (30–45 min);
  - the bundle baseline reset to the deployed v9.15;
  - VERSION v9.16.
- **Don't push 0080 until its speed fix lands.** On the lab, a cold `GET /api/sources/suggested` takes about 30 s, twice in a row; v9.12 took 0.24 s. Warm, it's 9 ms. The answer is 111 KB, down from 1.96 MB.
- **Backend suite on main:** 1,409 OK. The size check passes: feed +0.03%, post +0.02% over the v9.15 baseline.
- **The lab** (`insight-lab-api`/`insight-lab-web`) runs main `6e49203`, started with `INSIGHT_DISCOVER_READS=0` so this machine fetches nothing.
  - **A lab container is started without migrations.** Run `python insight_core/db/migrate.py` in a one-off container first, as `plan/research/lab/README.md` step 3 says.
  - Its data is the server copy of 2026-10-30, migrated to 0065.

## Agents running when paused (each asked to commit and write a private handoff)
1. **0079, export everything** (branch `issue-0079-export`, worktree `.claude/worktrees/agent-ae2e8e69d2dbd95ea`).
   - The owner chose INSIGHT's own export: a CSV per table, `schema.sql` from the migrations, a manifest and a README.
   - It restores into INSIGHT, or opens alone in any tool.
   - Logins are left out by default, with a checkbox.
   - Handoff: `plan/research/0079-build/HANDOFF.md`.
2. **The Discover speed fix** (branch `issue-0080-discover-speed`, worktree `.claude/worktrees/agent-ad2a09822c4fa4f65`).
   - The cause of the 30 s cold answer and why the second call missed the cache.
   - Target ≤1 s cold.
   - Handoff: `plan/research/0080-speed/HANDOFF.md`.

## Next, in order
1. Merge the Discover speed fix, then push 0088 + 0080 together (the owner says "push").
2. Merge 0079 (export).
3. **0085, discussions:** HN via Algolia, Reddit via the thread's comments RSS. It waits for 0079 because every route is in `backend/main.py`.
4. **0084 B:** a source's own older posts that its posts link, fetched with the source's reader.
5. **0080 decision 1:** one name for a source everywhere (it touches News).
6. The v9.16 reader review on the lab, and on a fresh server copy once 0079 can export one.

## Decided today (see each issue)
- **Keep everything:** posts and everything derived from them are never deleted; operational logs may be pruned.
- **0078 channels and 0081 walled sites:** on hold.
- **0080:** every recommendation.
- **0079:** format B, logins out by default.
- **0089** (the shared link's window counts from the first-ever link): measured, not adopted. Half of the new joins are later essays citing the page as background; it waits for the same-story labels.
- **The rail order:** newest unread post first.

## Lessons from today
- **The real-data check's scratch copies collided when several ran at once.** Each run now has its own (`<db>_check_<pid>_a/b`).
- **Agents must not edit the shared `plan/research/lab/cases.json` before their branch merges,** and must never stop processes they didn't start.
- **Another session uses `plan/issues/0086` and `0087`** (Mark X files, uncommitted, with uncommitted README rows). Leave them uncommitted when committing README changes; stage only your own rows.

## Waiting on the owner
- "push" (after the Discover speed fix).
- The Substack connection test result on the server.
- A fresh server copy (by 0079's export once merged, or `pg_dump`).
- Pressing "Fetch now" once on the feed service source that's still in its old 6-day wait (0088 doesn't rewrite stored waits).
