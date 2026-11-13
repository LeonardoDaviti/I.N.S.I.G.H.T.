# Handoff: Mark X v10.0.x (2026-11-06)

Read this first. Older handoffs (`HANDOFF-v9.16.md`, `HANDOFF-v9.15.md`) are history.

## Where things stand
- **The server** runs **Mark X v10.0.1 (Shadow)**, `3fde2c6`, with `INSIGHT_MARKX=on`.
  - It hung once on 2026-11-05: the API at 101% CPU with the database idle, `/health` passing and `/api/*` timing out. A `docker compose restart backend` brings it back.
  - The cause isn't known yet. v10.0.2's watchdog saves a stack dump before restarting, so the next hang names its function.
- **main** is 33 commits ahead of GitHub, **not pushed**: v10.0.2.
  - **0111:** News leads from the main story, a date is no name, one owner one voice, a row leaves the 30-day window whole; plus the archive-row, directory-subdomain and licence fixes.
  - **0084 B:** a source's own pages its posts link and no post is: "Linked by your posts, not stored: N · Fetch them".
  - **0112 Decided 10–13 and 0117:**
    - Mark X's jobs run in `insight-ingestion`, never the API;
    - a 120 s run limit, stage logs, and at most one run per 5 minutes;
    - `uvicorn --workers 2` under `scripts/api_supervisor.py`;
    - the healthcheck uses `/api/version`;
    - the ingestion watchdog restarts a hung API (no Docker socket; a request file in the shared logs volume);
    - the check's `markx.api_during_run` gate.
  - VERSION "Mark X v10.0.2 (Shadow)". The specs 0113–0121 are committed.
- **v10.0.2 is blocked:** its real-data check (`--base 3fde2c6 --head main insight_lab`) failed only on `markx.api_during_run`, 0 → 35: `/api/version` p50 5.4 s during a 4.4 s run.
  - The agent that built the gate measured 0 before 0084 B merged. The machine was loaded (load ~10).
  - **A diagnosis agent is on it,** on branch `fix-api-during-run`: is it a regression (bisect) or a load-sensitive gate (measure the run's slowdown against a baseline, never just raise the threshold)?
  - `discover.name_address` +1 is known and accepted: 0111's new directory card.
- **A v10.0.2 reader review is running,** with the server's way of running: API ×2, ingestion with the watchdog, nginx, on a copy of the server data. Report: `plan/research/review-v10.0.2-reader.md`.

## Branches ready, not merged
- **`issue-0112-reask-and-0116`** (head `2d53590`) is **v10.0.3**.
  - **0112 Decided 8:** a story-changing answer is asked twice. A join counts when both answers are "about"; a pair or merge when both are "same event". There's also the reason rule, and merges go one per call.
  - **0116, incremental decisions:** median 0.66 s per run; replay matched a full run after every batch.
  - Measured on the blind sample: kept joins right 25 of 27 (93%), but 14 of 39 right joins are dropped.
  - Its real-data check last passed before the agreement-rule change. **Rerun it at merge.**
  - It merged main at `b08b8d0`, so it already contains v10.0.2.

## Next, in order
1. Fix or explain the gate, rerun the v10.0.2 check, read the v10.0.2 review, then ask the owner to "push". On deploy, remove `API_WORKERS=1` from the server's `.env` if it's there.
2. **v10.0.3:**
   - merge `issue-0112-reask-and-0116` with its real-data check;
   - then build **0121**: checks never remove a post that links the story's page; a headline per row with 2 words of slack; no run during Mark IX's rebuild and candidates before decisions; the reading window applies at once; a document as a merge candidate (default yes); folding typographic apostrophes; an incremental entity flush; the speed gate during the first start.
3. **v10.1 = 0119 A (entities), then v10.1.1 = 0119 B (perspectives, 0120).** 0119 was reviewed on 2026-11-06 with 8 changes applied.
4. **Mark IX queue:**
   - 0113 and 0114: measured, both "change then build" (`plan/research/0113-measure.md`, `0114-measure.md`). First fix 0113's finding: a page saved and dated at save time dissolves its story (31 of 50).
   - 0085: discussions.
   - 0080 decision 1: one name for a source everywhere.
   - 0118: source track record.
5. **Small:** `test_search`'s "dates compete" test is flaky under load (seen 5 times), so make it deterministic.

## Rules for every agent (the owner's)
- **Merge rule:** one area at a time; slices never share files; nothing merges unless `scripts/realdata-check.sh` passes; read every lead change it flags.
- **Mark X is Shadow:** only `mx_*` tables. Mark IX's tables must be identical with Mark X on or off (`markx.ix_unchanged`).
- **Keep everything:** never delete posts or derived rows; close with `valid_to`.
- **Never touch the live `insight` database.** The server only gets read-only GETs from agents, and nothing while it's hung.
- **Download nothing,** and fetch nothing from this machine. Lab containers run with `INSIGHT_DISCOVER_READS=0`.
- **No real channel or account names** in committed files, fixtures or commit messages. `plan/research/` is private and gitignored.
- **Push only when the owner says "push".** The owner deploys with `git pull && ./update` in `<deploy dir>`.
- **Live Mark X workers run from the MAIN checkout** (another session), using `<token file>` and a llama-server on this machine.
  - Never stop them, and never use that token in tests.
  - Never overwrite `scripts/markx-worker` in the main checkout while they run.
  - At merge, an identical uncommitted change can be checked out first.
- **Another session writes specs** in `plan/issues/` and leaves README rows uncommitted. Commit only your own rows: commit README from `git show HEAD:` plus your row, then restore the working copy.
- **Data:** `insight_server_1105` is a restored export of the server (2026-11-05 11:14 UTC), read-only. Use scratch copies named `<db>_check_<pid>_a`. The lab copy (`insight_lab`) is the 30 Oct server data, at migration 0068+.
- **Real Haiku** only within a stated cap, through `scripts/markx-worker` against your own API.

## Lessons from 2026-11-05/06
- **A deploy's first start must be in the check:** the v9.17 server rebuild stuck on a foreign key the full rebuild never hit (0110). The check now runs it.
- **The decision job in the API process risked the reader's pages;** jobs go in ingestion (0112 Decided 10).
- **`/health` can pass while the API hangs;** health is `/api/version` now (0117).
- **Measure before adopting:**
  - 0113's save path dissolves stories;
  - 0114 as written was +1.44% requests against a 1% bar;
  - the second ask's precision cost recall.
