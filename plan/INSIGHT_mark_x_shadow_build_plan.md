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

## Corrections before building (2026-11-05, after v9.17's rule changes merged)
Found when the plan was checked against v9.16–v9.17 (0076, 0080, 0103). Each binds every slice.
1. **The prototype's baseline is v9.12's stories, not today's.** The prototype read the server's v9.12 stories (`corpus/stories_ix.json`) and posts read by that version's code. Since then 0072, 0076, 0080 and 0103 changed Mark IX's stories. So S5's "reproduces the prototype's decisions exactly" runs on the **recorded** v9.12 stories and recorded answers as a fixture, never on stories recomputed today; S2's candidate overlap is reported against the prototype's text and explained where post_parts (0076) reads a post differently.
2. **Key Mark X by posts and content, never by a Mark IX story id.** A Mark IX story's id is its first post's id, and its row is deleted and rewritten when the story changes shape. So:
   - no `mx_*` table has a foreign key to `stories` or `story_posts`;
   - a task's `input` is built from content only (texts, readings, member post ids in a fixed order), never from a story id, so a re-rooted story with the same members has the same `input_hash` and is never asked twice;
   - the decision job matches answers to today's Mark IX stories by their member posts.
3. **Mark X's text is its own versioned function** (`markx text v1`: title plus the first 1,500 characters, read from post_parts). A post_parts change in Mark IX doesn't change Mark X's inputs unless the text version is bumped on purpose (a bump re-reads every post).
4. **A Mark IX story-rule change reports what it re-asks.** From S3 on, the real-data check counts the open and answered Mark X tasks whose input would change under the head's stories (checks, cards, merges); the merge commit states the number.
5. **0074 (a post in several stories) is not built in 9.x.** `mx_story_posts` is that edge model; Mark IX reads it at Part G. **0089** is settled by experiment W (bursts are candidates, part B), not a rule.
6. **The embedder runs on the owner's device for the first experiments, not on the server** (owner, 2026-11-05: no extra service on the server). So S2 changes:
   - **no `embedder` compose service and no embedding in the ingestion runner.** The server only stores vectors and finds candidates;
   - **embedding is a task kind, `embed`,** leased like the others. The worker embeds it with a local `llama-server --embedding` (BGE-M3, the GGUF on the device) and posts the vectors to `POST /api/markx/embeddings`;
   - **vectors travel as base64 little-endian float16** (2 KB a post, not ~9 KB of JSON numbers): the last 30 days are about 10 MB, all 41.6k posts about 85 MB;
   - **every vector records its model and the GGUF's sha256.** The server refuses a vector from another build than the one already stored, since cosines across builds don't compare;
   - **candidates are found on the server when vectors arrive** (debounced), with pgvector, as before;
   - **the server never embeds a query in Shadow:** nothing searches by meaning yet. Embedding on the server comes back at Part H, or with search by meaning.
   - The `embed` kind is added to `scripts/markx-worker` by S2, after S4 merges, so the two never share a file. Tests use a fake embedder.
7. **The export (0079) includes `mx_*` tables** automatically (it reads the catalog). Embeddings as text add an estimated 150–200 MB to the zip; S2 measures it.
8. **The worker shares the owner's Claude usage with build agents.** First runs read the last 30 days only (about 500 batches); no backfill while build agents run.
9. **One merge queue.** Mark X slices merge through the same queue as Mark IX work, one at a time, each with its real-data check report.

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
- **Files** (as corrected, item 6): `markx/embed.py` (the `embed` tasks and the vectors' check and store), `markx/candidates.py`, the `embed` kind in `scripts/markx-worker` (after S4 merges), `POST /api/markx/embeddings` in `markx/api.py` (after S3 merges, or S2 adds it to S3's router), tests `test_markx_embed.py`, `test_markx_candidates.py`. No compose service, no runner hook.
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

## After Shadow: Mark X Stealth (the owner, 2026-11-05)
"All this new features we are testing rn will be in next update which is Mark X Stealth update." Shadow's scope stays as 0086 says; nothing below enters S1–S6. Stealth gets its own build plan once each feature passes its bar on the owner's labels.

| Feature | Issue | Where it stands (2026-11-05) |
|---|---|---|
| Perspectives inside a story + the story sheet | 0106 | testing (v3.1 run) |
| How stories are built: an event type per story, leaks resolved ("came true"), the original by links and maker, published time, duplicates collapsed, related posts | 0106, 0086 E | rules decided by the owner; needs `read-v3` with event types |
| Entity identity: name key, maker-prefix aliases, version hierarchy, merge queue | 0090 B–C | measured; rules decided |
| Surges per exact version, subjects only | 0090 E | measured: 96% precise |
| Back in the news | 0092 | measured: trigger changed, judge 73% |
| Numbers over time | 0095 | measured: extraction 87%; needs a metric list and 0090 C |
| Discover by attribution | 0101 | measured: which credits count |
| Questions with citations | 0098 | retrieval measured; answers not yet |
| Chains across months, since you last looked, noise per source | 0091, 0094, 0093 | need Shadow's data first |
