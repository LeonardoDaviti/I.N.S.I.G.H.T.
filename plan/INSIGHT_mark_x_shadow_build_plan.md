# Mark X Shadow: the build plan for agents

The spec is [0086](issues/0086-mark-x-phase-1-haiku-in-insight.md). This file says **how to build it**: in what order, which agent owns which files, what each slice must prove before it merges. Read 0086 in full first; where this file and 0086 disagree, 0086 wins and this file gets fixed.

Entities are [0090](issues/0090-mark-x-entities.md) (Shadow ships part A only: extraction and `mx_mentions`). The future features (0091–0101) are **not** part of Shadow.

## Read before starting
1. `plan/issues/0086-mark-x-phase-1-haiku-in-insight.md`: the spec, parts A–H.
2. `plan/issues/0090-mark-x-entities.md`: the `entities` task, its checks, the name key.
3. `plan/issues/0075-*.md` and `scripts/realdata-check.sh`: the merge rule and the real-data check.
4. The latest `plan/HANDOFF-*.md`: what's on the server, what's on main, what other agents hold.
5. The prototype (private, gitignored): `plan/research/lab/markx/proto/`.
   - **Guides:** `guides/reading.md` (`read-v2`), `guides/ent3_extract.md` (`ent-v3`), `guides/judge*.md`, `guides/card.md`, `guides/bg_headline.md`, `guides/bg_briefing.md`, `guides/bg_graph.md`.
   - **The worker prototype:** `markx_worker.py`: the `claude -p` call, the batch prompt, the JSON-line parsing, the retry.
   - **Rules to port:** `hybrid.py` (the evidence each question sees) and the decision rules in the night report.
   - **Name key:** `entparse.py` (`key()`).
   - **Recorded answers:** `out/cache.sqlite`, the fixtures for parts C and E. Don't commit them (they hold real posts); tests use small synthetic fixtures written from their shapes.

## Rules for every agent
- **Shadow never changes Mark IX.** Only `mx_*` tables are written. Mark IX's stories, News, Classics, feeds and unread counts are identical with Mark X on and off.
- **One switch:** `INSIGHT_MARKX` (default `off`). Off means no Mark X job runs, no hook does work, the page is hidden.
- **The merge rule (0075):**
  - one slice per branch;
  - each slice lists the files it touches, and no two parallel slices share a file;
  - nothing merges unless `scripts/realdata-check.sh` passes on the lab copy, with its report path in the merge commit;
  - the full suite (`./run-tests.sh`) passes in the image.
- **No real channel or source names** in committed code, guides, tests or fixtures. The prototype's guides must be scrubbed when they are copied: examples keep product and company names, never a channel, account or subreddit.
- **No PyTorch, no training, no downloads by agents.** The BGE-M3 GGUF is downloaded by the owner at deploy. On the dev machine it is at `~/Documents/models/markx/bge-m3-q8_0.gguf`; mount it, never copy it into the repo.
- **Never touch the server or its database.** The server is HTTP GET only. The lab copy is read-only except through the app's own migrations on a scratch copy.
- **Keep everything:** memberships and connections close with `valid_to`; nothing derived is deleted. A changed guide is a new guide id.
- **Commit on your branch; merge and push only when the owner says.**
- **Don't edit `plan/research/lab/cases.json`** before your branch merges. Don't stop processes you didn't start.

## Slices and order
```
S1  A  storage ──┬──▶ S2  B  embeddings + candidates ──┐
                 ├──▶ S3  C  tasks, checks, worker API ─┼──▶ S5  E  decisions + /markx ──▶ S6  F  labels
                 └──▶ S4  D  the worker (needs S3's API contract, not its code)
```
S1 merges first and alone. S2, S3 and S4 run in parallel: their files don't overlap. S5 needs S2 and S3 merged. S6 needs S5.

Version: S1–S4 are invisible and merge under the current Mark IX version. **S5 merging is "Mark X v10.0 (Shadow)"** (0086 open question 5).

### S1 — Part A: storage
- **Files:** one new migration `backend/insight_core/db/migrations/NNNN_markx_shadow.sql` (next free number at merge), `backend/insight_core/markx/__init__.py`, `backend/insight_core/markx/repo.py` (inserts and reads for the `mx_*` tables), `backend/insight_core/tests/test_markx_storage.py`.
- **Build:** the 14 tables exactly as 0086 A lists them, with their keys, uniques and indexes, the HNSW index on `mx_embeddings` (open question 4: now). Additive only.
- **Done when:**
  - the migration applies on a scratch copy of the lab;
  - the realdata check passes with no other change (table diff of Mark IX's tables: 0);
  - tests: the uniques (task per kind, guide, input hash; one current membership per story and post), `valid_to` closing.

### S2 — Part B: embeddings and candidates
- **Files:** `markx/embed.py`, `markx/candidates.py`, `docker-compose.yml` (the `embedder` service, behind `INSIGHT_MARKX`), `backend/insight_core/ingestion/runner.py` (one hook after `self.stories`, never raising), the place the runner is constructed (one argument), tests `test_markx_embed.py`, `test_markx_candidates.py`.
- **Build:** 0086 B: title plus the first 1,500 characters; newest first, at most 500 posts a run; the four candidate sources (`embedding`, `link`, `entity` for specific subjects only, `burst`) at 0086's thresholds.
- **Test without the model:** a fake embedder returning fixed vectors, so the suite never needs the GGUF.
- **Done when:**
  - a scratch copy's last 30 days are embedded (on the dev machine, with the local GGUF);
  - the candidates match the prototype's on its 16 days at the same thresholds (report the overlap; small differences from the embedder build are expected and explained);
  - E8 is reported: ms per post on CPU, RAM with the embedder up;
  - the realdata check passes.

### S3 — Part C: tasks, checks and the worker API
- **Files:** `markx/tasks.py` (task creation per kind, `input` built as the prototype's `hybrid.py` does), `markx/validate.py` (the per-kind checks in 0086 C's table), `markx/schemas.py`, `markx/guides/*.md` (scrubbed copies), `markx/api.py` (the router), `backend/main.py` (one `include_router` line), the token in the credentials table (generated in Sources → Connections: one small backend route and one frontend button, listed in the branch), tests `test_markx_validate.py`, `test_markx_api.py`.
- **Build:** the 11 task kinds; `GET /api/markx/work`, `POST /api/markx/answers`, `POST /api/markx/release`, `GET /api/markx/status`; 30-minute leases; invalid answers back to open with their error, failed after 3 tries; a second answer stored as a call and changing nothing. Guides loaded into `mx_guides` at start, by sha256.
- **The contract** (S4 builds against it): the request and response shapes in 0086 C. Freeze them in `markx/api.py`'s docstring on day one and tell S4.
- **Done when:** 200 tasks of every kind round-trip on a copy with recorded prototype answers as the "model", and the invalid cases come back with their errors (spans not in the input, versions not in the input, figures that don't occur, wrong sets, too many entities).

### S4 — Part D: the worker
- **Files:** `scripts/markx-worker` (one Python file, standard library only), `scripts/tests/fake-claude` (a fake binary for tests), the worker's test file.
- **Build:** 0086 D: batches of 20, one kind per batch, 3 in parallel, one retry of what's missing or invalid; `claude -p --model haiku --tools "" --system-prompt <guide> --output-format json --no-session-persistence --strict-mcp-config`, prompt on stdin; tokens and cost from Claude Code's JSON logged and posted; on a usage-limit or auth error it releases its leases and exits non-zero. Port the prototype's `markx_worker.py`; don't redesign it.
- **Done when:** against the fake `claude` and S3's API (or a stub of its contract before S3 merges) every path works: valid, invalid then retried, missing lines, usage limit, auth error, lease expiry. After S3 merges: the last 30 days of a scratch copy read and judged through the real `claude -p`, every answer stored. **The owner runs the real-Haiku part** (it is their Claude account).

### S5 — Part E: decisions and the Mark X page
- **Files:** `markx/decide.py`, `markx/news.py` (calls Mark IX's `NewsService.refresh` over Mark X's stories into `mx_news`, and tags NEW / CHANGED / MERGED / SPLIT / SAME), the scheduling of the decision job (after uploads, debounced, and hourly), `frontend/src/pages/MarkXPage.tsx` and its components, the post page's folded "Mark X" panel, `frontend/src/App.tsx` (the route), the menu (one item when `INSIGHT_MARKX` is on), the realdata check's five new invariants (0086 Safety), tests `test_markx_decide.py`.
- **Build:** the decision job as a pure function of (Mark IX's current stories, the valid answers, `config`), with the prototype's rules and bars untouched: rule A, rule B, roundups as mentions, the two-event guard, joins at p ≥ 0.6, merges at p ≥ 0.85, the second pass, typed connections, the late-post table.
- **Done when:**
  - on the prototype's recorded answers the job reproduces the prototype's decisions for its 16 days, exactly;
  - Mark IX's tables are identical before and after a run (the table diff);
  - the reader review passes on the lab, phone included (`plan/research` reader-review method);
  - the realdata check passes with its new invariants.

### S6 — Part F: labels in the app
- **Files:** `markx/labels.py`, the labels part of the Mark X page, the one-tap controls on Mark X News rows, tests.
- **Build:** 0086 F: the queue (near a bar, every merge, a weighted sample), the evidence as the judge saw it without its verdict, one tap plus a note, the dev/test split by date, each feature's precision with its bar and interval.
- **Done when:** the owner's E1 set (about 2 hours) can be done on the page, and the page shows precision per feature on those labels.

### Later, not now
- **Part G** (switching features on) needs E1 labels and two weeks in Shadow per feature.
- **Part H** (the API worker on the server) needs the owner to buy the API.
- **0087** (local Gemma) needs Shadow's stored answers.

## What to report after each slice
In the branch's last commit and in a private handoff under `plan/research/markx-build/<slice>.md`:
- built right / wrong / missed, with real examples (private file only);
- the realdata check's report path;
- the numbers its "done when" asks for, with intervals where there's a sample;
- the files touched, matching the slice's list.

## Owner decisions this plan assumes
0086's open questions, with the recommendations taken as the default until the owner says otherwise:
1. every post may go to Anthropic;
2. the worker is run by hand for the first days, then on a two-hour timer;
3. at least two weeks in Shadow per feature, after its labels pass;
4. the HNSW index now;
5. "Mark X v10.0 (Shadow)" at S5.
