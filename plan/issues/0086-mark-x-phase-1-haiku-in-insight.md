# 0086 — Mark X Shadow: Haiku reads and judges every post beside Mark IX, from your device first

Status: **spec, ready to build** (2026-11-04; owner: "commit all the issues", 2026-11-05). Not built. How agents build it: [the build plan](../INSIGHT_mark_x_shadow_build_plan.md); read its "Corrections before building" (2026-11-05) first: the prototype's baseline is v9.12's recorded stories, and Mark X is keyed by posts and content, never by a Mark IX story id. It's built as parts A–F, each merged on its own (the merge rule, 0075); G and H come later. It replaces the design draft of the same morning. The storage maths, the time windows and the late-post rules below are that draft's, measured the same day.

**Constraints:**
- No real channel names in this file or in fixtures.
- Never touch the live database; measure on copies.
- Keep everything: no row is deleted or overwritten; a new prompt version adds rows, and a membership that changes is closed, not removed.
- Nothing merges unless `scripts/realdata-check.sh` passes.
- Mark X never writes Mark IX's tables.

## Why (the owner, 2026-11-04)
- "Give current INSIGHT the ability to have these features, but run Haiku from my local device, because I have it here, not on the server, and let it do all the job and see results in the actual INSIGHT platform. After the real testing, I will purchase the API and run everything in real time."
- "I want Haiku to govern the whole INSIGHT" first; a local model (0087) later.
- "So we are ready for Mark X Shadow to be developed."

## What "Shadow" means
- **Mark X runs beside Mark IX, on the same posts,** and writes only its own tables (`mx_*`).
- **Mark IX doesn't change because of it:** its stories, News, Classics, feeds and unread counts stay exactly what they are.
- **You see both:**
  - Mark X's News beside Mark IX's, every difference tagged and explained;
  - a Mark X panel on each post;
  - a labels page.
- **A feature replaces Mark IX's only after your labels pass** (part G, a later version). Until then, Mark X is something to look at and label, never something the reader depends on.

## What is ready
The prototype (`plan/research/lab/markx/proto/`, private) ran every feature below on the server's posts. Its numbers come from blind Claude labels; yours (E1) are still missing.

| Feature | Prototype result (Claude labels) | In Shadow (v10.0) | Replaces Mark IX |
|---|---|---|---|
| F0.2 Reading | kind 86.7% right, events 90.4% | yes, every post | after E1 |
| F7 Entities | from the reading's slots: names right 48%. Own extraction v2: 99% real, names right 98%, 91% clean, roles 92%, versions 91% ([0090](0090-mark-x-entities.md)); finds a little less (93%) | yes, every post, v3 (2026-11-05) | the entity layer is new; nothing to replace |
| F0.3 Story cards | the medoid card cut wrong removals 11 → 3 | yes | with F1 and F2 |
| F0.4 Candidates (BGE-M3) | 88% of a story's posts in its top 10 (step 1) | yes; E8 decides CPU or GPU | yes, once it runs |
| F1 Check | keeps 99% of right members; 4 of its 6 changes right | yes | after E1 |
| F2 Joins and new stories | 98% right at the 0.6 bar (95% on held-out days). Through the worker on unseen days (1–4 Nov): 19/23 = 83% (63–93%) of changes right, 11/12 where a post was new, 0/30 rejected were misses; the errors are the same company's different products | yes | after E1 and two weeks in Shadow |
| F2 Merges | 10 made, all right; on 200 story pairs "same event" 7 of 7 right, 4 of them under the 0.85 bar | yes, at 0.85; the bar is re-picked from E1 | after E1's merge labels |
| F6 Links between stories (≤ 30 days) | "development" 13 of 15 right; finds 95% of connected pairs | yes | after E1 |
| F4 Headlines | Haiku's chosen best 94%, names the main event 97% (lead titles 45%) | yes | after Shadow |
| F12 Briefing | Haiku's preferred on 15 of 15 days, no unsupported line | yes | after Shadow |
| F5 Translation | all meaning kept 87%, misleading 2% (Russian tech slang) | yes, with a slang glossary, for News leads and on request | after Shadow |
| F3 Digests | inside F1 and F2 | yes | with F1 |

**Not in Shadow** (their own issues):
- entity identity, pages and timelines (0090, 0001);
- connections across years and the timeline graph (0091);
- the features filed as future on 2026-11-04 (0092–0101).

## How it works
```
 server (INSIGHT)                                              your device (now)       server (part H, later)
 new post ─▶ embedding ─▶ candidates ─▶ tasks (mx_tasks) ──▶   markx-worker            markx-worker --api
            (BGE-M3)      (meaning, links,      ▲               claude -p --model haiku  Messages API, Batch API
                           entities, bursts)    │               (batches of 20)          (one request a task)
                                                └──── answers, each checked against its guide's schema ◀──┘
 answers ─▶ decision job (bars, rules, order) ─▶ Mark X stories, connections, News (mx_*) ─▶ the Mark X page
```
- **The server never calls a model in Shadow.** It embeds posts, finds candidates, writes tasks, checks answers and decides.
- **Each question gets the evidence that suits it** (the prototype's `hybrid.py`):
  - checks: the raw post and the story's members;
  - joins and new stories: the posts' readings;
  - merges: two stories as cards.
- **The worker runs where the model is:** your device now (Claude Code), the server later (the API). Both see the same tasks, guides and answer schemas, so an answer is stored once and never paid for twice.

## Part A: storage (one migration, additive)
Every table is new, so Mark IX's tables keep their columns. Model output is JSONB stamped with its guide; what INSIGHT joins, filters or counts are typed columns. Not a schemaless store, not a graph database: connections are rows, and chains across time are recursive queries. pgvector 0.8.3 is already in the image (`halfvec`, HNSW).

| Table | A row is | Key columns | JSONB |
|---|---|---|---|
| `mx_guides` | one prompt, as sent | `id` (`read-v2`, `ent-v2`, …; a changed guide is a new id, never edited), `kind`, `sha256`, `body`, `created_at` | `schema` (the answer's JSON schema) |
| `mx_tasks` | one question | `id`, `kind`, `guide`, `subject_kind` (post, post_story, post_post, story_story, day), `a`, `b` (uuids or null), `day`, `input` (the exact text after the guide), `input_hash`, `priority` (0 first), `status` (open, leased, answered, failed), `lease_until`, `leased_by`, `attempts`, `last_error`, `created_at`, `answered_at`; **unique (`kind`, `guide`, `input_hash`)** | — |
| `mx_calls` | one answer from one model | `id`, `task_id`, `executor` (claude-code, api, api-batch), `model`, `valid`, `error`, `tokens_in`, `tokens_out`, `ms`, `cost_usd`, `created_at` | `answer` |
| `mx_readings` | a post's reading (F0.2) | `post_id`, `guide`, `call_id`, `kind`, `events`, `lang`, `headline`; PK (`post_id`, `guide`) | `reading` |
| `mx_mentions` | one entity named in one post (F7) | `post_id`, `guide`, `n`, `call_id`, `span`, `name`, `name_key`, `type`, `role`, `maker`, `family`, `version`, `variant`, `size`, `build`, `entity_id` (null until 0090's identity); PK (`post_id`, `guide`, `n`); indexes on `name_key` and (`family`, `version`) | — |
| `mx_embeddings` | a post's vector | `post_id`, `model`, `text_hash`, `v halfvec(1024)`; PK (`post_id`, `model`); HNSW (`halfvec_cosine_ops`) | — |
| `mx_candidates` | a pair worth a question | `kind`, `a`, `b`, `source` (embedding, link, entity, burst), `score`, `created_at`; PK (`kind`, `a`, `b`, `source`) | — |
| `mx_runs` | one decision run | `id`, `started_at`, `finished_at`, `code_version` | `config` (bars, rules, guides), `counts` |
| `mx_stories` | a Mark X story | `id`, `first_at`, `created_run`, `merged_into`, `headline`, `headline_call`, `card_call` | — |
| `mx_story_posts` | a post in a Mark X story | `story_id`, `post_id`, `role` (member, mention, digest_item), `reason` (rule:link…, judge:join, judge:pair, merge), `p`, `call_id`, `valid_from`, `valid_to` (null = current), `run_id`; unique current (`story_id`, `post_id`) | — |
| `mx_connections` | a typed connection | `a_kind`, `a`, `b_kind`, `b` (post or story), `relation` (same_event, development, follows_up, reaction, same_topic, …), `p`, `call_id` or `rule`, `valid_from`, `valid_to`, `run_id` | `evidence` |
| `mx_news` | a Mark X News row | written as Mark IX's `news` rows are (same code path, same shape), plus `run_id` | as `news` |
| `mx_briefings` | a day's briefing | `day`, `call_id`, `created_at` | `lines` (each with its story keys) |
| `mx_labels` | your answer to one item | `id`, `item_kind` (join, check, merge, news_row, entity, connection), `a`, `b`, `answer`, `labeller`, `split` (dev, test), `note`, `created_at` | — |

**Done when** the migration applies on a copy of the lab and the realdata check passes with no other change.

### How much it takes
Measured 2026-11-04:
- **The server copy** (taken 30 Oct): 41,608 posts in 489 MB, about 11.8 KB a post, about 170 new posts a day.
- **The prototype's sizes:**
  - a reading's input averages 1,558 characters, and a reading is 480 characters of JSON;
  - a question is 1,943 characters and a verdict about 190;
  - there are 0.22 questions per post.

| Mark X adds, per post | KB |
|---|---|
| Embedding, `halfvec(1024)` | 2.1 |
| Its HNSW index | 2.3 |
| Reading | 0.7 |
| Every model call with its input (the audit trail and 0087's training set) | 3.1 |
| Entities | 0.3 |
| Connections, cards, stories, labels | under 0.1 |
| **Total** | **about 8.6** |

| | Posts | Today | Mark X adds | Total |
|---|---|---|---|---|
| The server now | 41.6k | 0.49 GB | 0.36 GB | 0.85 GB |
| Each year at ~200 posts a day | +73k | +0.86 GB | +0.63 GB | +1.5 GB a year |
| One million posts | 1M | 11.8 GB | 8.6 GB | 20 GB |

**RAM:**
- the HNSW index takes about 0.1 GB now, and 0.23 GB per 100k posts;
- BGE-M3 takes about 1 GB on the CPU, or 0.8 GB of the 1660 Ti's 6 GB;
- the worker runs on your device.

### Built (S1, 2026-11-05, branch `markx-s1-storage` from main 58ba6ae)
Not merged, not deployed. Nothing was fetched or downloaded; measured on scratch copies of `insight_lab` (41,637 posts), never on the lab itself.

**What changed** (the slice's files only):
- `backend/insight_core/db/migrations/0066_markx_shadow.sql`: the 14 tables above, with their keys, uniques and indexes, and the HNSW index `mx_embeddings_v_hnsw_idx` (`halfvec_cosine_ops`). It creates `mx_*` things only and is idempotent.
- `backend/insight_core/markx/__init__.py` and `markx/repo.py`: every insert and read the later slices need.
  - Guides: `put_guide` (loaded again at each start), `guides`.
  - Tasks: `add_task` (one per kind, guide and input), `task_for`, `lease_tasks` (30-minute leases, by priority then age, `SKIP LOCKED`, expired leases leased again), `release_tasks`, `expire_leases`, `answer_task`, `fail_attempt` (failed at the 3rd), `queue_counts`.
  - Calls, readings and mentions: `add_call`, `calls`, `valid_call`, `add_reading`, `readings`, `add_mentions`, `mentions`, `posts_naming`.
  - Embeddings and candidates: `put_embedding`, `embedding`, `embedding_hashes`, `embedding_builds`, `nearest` (through the HNSW index), `add_candidate`, `candidates`.
  - Runs and stories: `start_run`, `finish_run`, `last_run`, `add_story`, `get_story`, `merge_story`, `set_story_headline`, `set_story_card`.
  - Memberships and connections: `open_membership`, `close_membership`, `current_members`, `stories_of_post`, `membership_history`, `open_connection`, `close_connection`, `current_connections`. Closing sets `valid_to`; nothing in the module deletes.
  - News, briefings and labels: `add_news_rows`, `news_rows`, `add_briefing`, `briefings`, `add_label`, `labels`.
- `backend/insight_core/tests/test_markx_storage.py`: 19 tests.

**How the tables keep the rules** (the build plan's corrections):
- **No foreign key leaves `mx_*`.** No key goes to `stories` or `story_posts` (corrections 2), and none to `posts` either. A key to `posts` would put Mark X's checks on Mark IX's deletes: a cascade would delete Mark X rows, and a restrict would block Mark IX. Keys inside `mx_*` stay (task → guide, call → task, reading → call, …).
- **A task is keyed by its content.** It is unique per (`kind`, `guide`, `input_hash`), and a check makes `input_hash` the sha256 of `input` alone. A re-rooted story with the same input is the same task, whatever subject ids come with it (tested).
- **A guide is never edited.** A check makes `sha256` the body's hash, and a trigger refuses any update to its id, kind, body, hash or schema. `put_guide` refuses the same id with another body.
- **One current membership per story and post:** a unique index on (`story_id`, `post_id`) where `valid_to` is null. The same applies to connections, per (`a`, `b`, `relation`). A closed row stays, and the slot opens again. A check keeps `valid_to` ≥ `valid_from`.
- **Every connection names a call or a rule** (a check; 0086 Safety 3).
- **Set columns are checked:** task status and subject kind, executor, candidate source, membership role, News tag, label kind and split. Task `kind` is not checked, so new kinds (`embed`) need no migration.

**Beyond the table list, and why:**
- **`mx_embeddings.model_sha256`** (nullable): the embedder build's GGUF sha256. Main's build plan (36eb66d, corrections 6, the owner on 2026-11-05) says every vector records it, so S2 can refuse vectors from another build. S2's file list has no migration, so the column is added here.
- **`mx_news`** has Mark IX's `news_stories` columns, plus `run_id`, `tag` (NEW, CHANGED, MERGED, SPLIT, SAME: Part E's tags, so S5 needs no migration) and `posts`, the row's `news_posts` rows as JSONB. Its key is (`run_id`, `id`).
- **`mx_briefings`** is keyed by (`day`, `call_id`), so a new guide's briefing is kept beside the old one.

**Measured** on a scratch copy of `insight_lab` (`insight_lab_check_<pid>_a`; machine load average 10–15):
- **The migration takes about 0.1–0.56 s of SQL** (3 runs, each in a rolled-back transaction), and 1.5 s for the whole `migrate` run with the container's start.
- **The empty tables take 376 KB** (385,024 bytes: 14 tables, 32 indexes). The database grows 600 KB.
- **No existing table changes.** Every table but `mx_*` was compared before and after the migration: rows, an md5 of all their rows, columns, constraints (71), indexes (76), triggers (123) and functions (17). The only change is `schema_migrations`' new row (60 → 61).
- **With 1,000 fake embeddings** (normalised 1,024-dimension vectors on the newest real posts): `mx_embeddings` takes 5.7 MB, the HNSW index 2.7 MB of it, so about 2.7 KB a post (estimated above: 2.3). `nearest`'s query plan is an index scan on the HNSW index.

**0079's export and restore with the new tables:**
- `test_export` passes with them, and so does the whole suite.
- **A real export and restore of the scratch copy:**
  - The scratch copy held 1,000 fake embeddings, plus a guide, task, call, reading and mention whose text has quotes, commas, a tab, a newline and ünïcode.
  - Exported with `ExportService`, then restored with `import_export.py` into a new database.
  - Every table's rows and md5 are equal, `mx_*` and the halfvec values included. Two tables differ, as designed: `credentials` (logins left out) and `system_settings` (`last_export`, written after the export's snapshot).
  - The HNSW index is rebuilt by the restore, and the restored copy's nearest-neighbour query uses it.
- **The zip grows 4.36 MB per 1,000 embeddings** (243,593,286 → 247,957,032 bytes; the CSV is 12.8 MB raw, about 12.7 KB of text a vector).
  - For all 41.6k posts that is about 182 MB, inside corrections 7's estimate of 150–200 MB.
  - The export took 83–123 s on the loaded machine.

**Tests:** `test_markx_storage` has 19 tests, which pass on a new database migrated from 0001 (run-tests.sh's own `_test` database):
- the 14 tables;
- no key out of `mx_*`;
- the migration run again changes nothing;
- the HNSW index;
- the migration only adds;
- one guide id is one body (and the database refuses an edit or a wrong hash);
- one task per kind, guide and input hash, by content;
- leases, answers, retries and failure;
- releasing and expired leases;
- calls, readings and mentions;
- halfvec, `nearest`, and the build;
- candidates once per source;
- one current membership per story and post;
- `valid_to` closing that keeps the row;
- a post in several stories;
- connections closed and opened again;
- stories, runs, News, briefings and labels.

**The whole backend suite: 1,465 tests OK** (run-tests.sh, in the image).

**The real-data check** (`scripts/realdata-check.sh`, on `insight_lab`; the reports are private in `plan/research/lab/checks/` and `plan/research/markx-build/s1/`). It was run three ways, because the branch's base (58ba6ae) is older than 0106, which main and `markx-shadow` now hold:
1. **Against its own base** (`--base 58ba6ae --head markx-s1-storage`):
   - every derived thing changed 0, every invariant is the same, and no case changes state;
   - the verdict reads FAIL only because 0106's two new cases (`discover-one-title-per-page`, `classic-paper-one-page`) fail on both sides: 58ba6ae predates 0106.
2. **On `markx-shadow`, as it would merge** (S1 merged onto `markx-shadow` 543830d in a trial commit, `--base markx-shadow`): **PASS.** Every derived thing changed 0, every invariant is the same, and no case changes state. Its backend equals main's (36eb66d).
3. **Literally `--base markx-shadow --head markx-s1-storage`:**
   - FAIL, with the diff of 0106 undone: the two 0106 cases pass → fail, Classics 230, Discover 740 moved, story membership 32, roundups 16, story origins 3, News 2;
   - none of it is S1's: run 2 shows the same code with S1 on top changes 0.
   - Merging S1 needs no rebase: its files are all new.

## Part B: embeddings and candidates (server)

## Part B: embeddings and candidates (server)
- **The embedder:**
  - BGE-M3 runs in a new compose service `embedder` (llama.cpp `llama-server --embedding`, the GGUF in a volume), on the CPU or the 1660 Ti, as E8 decides;
  - the model file is downloaded once, at deploy, by you;
  - the backend calls it over the compose network;
  - the text embedded is the title plus the text's first 1,500 characters.
- **When:** the ingestion runner calls Mark X after the story job (one hook, like `stories`, never raising). It embeds the posts saved in that run, then backfills newest first, at most 500 posts a run.
- **Candidates** (each pair written once per source):
  - `embedding`: posts from other sources within 72 h at cosine ≥ 0.65, not already in one Mark IX story; story pairs whose centroids are ≥ 0.70, at most 14 days apart;
  - `link`: Mark IX's own joins, which are the check's input;
  - `entity`: posts sharing a specific main-subject entity within 72 h, with the same `name_key` and the same version. Specific means a model or product version, a paper, a repository or a tool, never a company or person alone. Measured 2026-11-05 on held-out days: 7 of 11 accepted were right overall, 7 of 8 for specific subjects, and they were stories the embeddings missed;
  - `burst`: 0089's late bursts, posts linking the same page within 72 h of each other but long after its first linker.
- **E8 (measure first):** embedding time per post on the server's CPU, and the server's RAM with the embedder up.
  - Proxy on the development machine (2026-11-05): 48 ms a post on 6 CPU threads, 25 ms on a GPU.
  - So a CPU is enough: a day's posts take seconds, and a 13k archive minutes.
- **Done when** a server copy's last 30 days are embedded and its candidates match the prototype's on the 16 days it ran: the same pairs at the same thresholds, allowing for the embedder build.

## Part C: tasks, guides and the worker API (server)
**Task kinds:** the evidence each sees, and how its answer is checked before it is stored as valid.

| Kind | Subject | Guide (from the prototype) | Evidence in `input` | Created for | Server-side checks on the answer |
|---|---|---|---|---|---|
| `read` | post | `read-v2` (`reading.md`) | the post: platform, source, title, text (≤ 1,500 chars), links | every post, newest first | kind, events and lang from their sets; `main` null exactly when events is none; headline ≤ 25 words |
| `entities` | post | `ent-v3` (`ent3_extract.md`) | as `read` | every post | each `span` occurs in the input (after folding case, dashes and ё); every `version` occurs in the input; type and role from their sets; ≤ 20 entities |
| `check` | post_story | `judge-raw-v1` (raw-text form) | the raw post and up to 5 of the story's members | every uncertain member of a 2+ voice story (joined by a citation or with no recorded reason) and every roundup member | relation from its set; p in [0, 1] |
| `join` | post_story | `judge-read-v1` (form with readings) | the post's reading and text; the story's card and members | embedding, entity and burst candidates | as `check` |
| `pair` | post_post | `judge-read-v1` | both posts with their readings | candidate pairs where neither is in a story | as `check` |
| `card` | story | `card-v1` | the story's members with readings, the earliest first | every 2+ voice story a merge or join question needs | headline ≤ 14 words; slots present |
| `merge` | story_story | `judge-story-v1` | both stories as cards plus up to 3 members each | story-pair candidates | relation from its set; p in [0, 1] |
| `connect` | story_story | `graph-v1` | both stories' cards and dates | story pairs ≤ 30 days apart at centroid cosine ≥ 0.6 that aren't merged | relation from its set |
| `headline` | story | `headline-v1` | the story's members | every News row with 2+ voices | ≤ 14 words; every number and version in it occurs in a member's text |
| `briefing` | day | `briefing-v1` | the day's top News rows with keys | each day, after 20:00 server time | 5–7 lines; each cites a key; every figure occurs in a cited story |
| `translate` | post | `translate-v1` (+ glossary) | the post's text, by paragraph | Russian posts that lead a News row, and any post you ask for | the numbers in the text survive; length within 0.5–2× |

- **Guides** live in `backend/insight_core/markx/guides/<id>.md`, with their answer schemas in `markx/schemas.py`. They're copied from the prototype when this part is built, and loaded into `mx_guides` at start.
- **The worker API** (an `APIRouter` in `markx/api.py`, one `include_router` line in `main.py`). Behind the frontend's nginx, as `/api` already is, with a bearer token from the credentials table, generated in Sources → Connections:
  - `GET /api/markx/work?kinds=read,entities&limit=20&worker=<name>`
    - Leases up to `limit` open tasks for 30 minutes, by priority then age.
    - Answers `{lease_until, guides: {id: {sha256, body, schema}}, tasks: [{id, kind, guide, input}]}`.
  - `POST /api/markx/answers` with `{worker, executor, model, answers: [{task_id, answer, tokens_in?, tokens_out?, ms?, cost_usd?}]}`.
    - Each answer is checked as the table says and stored in `mx_calls`, valid or not.
    - A valid answer closes its task. An invalid one goes back to open with its error; after 3 tries the task fails.
    - It answers `{stored, valid, invalid: [{task_id, error}]}`.
    - A second answer to a task already answered is kept as a call and changes nothing.
  - `POST /api/markx/release`: hands back a worker's leased tasks.
  - `GET /api/markx/status`: the queue by kind and status, answers per day, tokens, the last contact of each worker, the last decision run.
- **Done when** 200 tasks of every kind round-trip on a copy, with recorded prototype answers as the "model", and the invalid cases come back with their errors.

### Built (S3, branch `markx-s3-api` from `markx-shadow` b897369, 2026-11-05)
Not merged, not deployed. Nothing was fetched or downloaded, and the real `claude` was never run. Measured on a scratch copy of `insight_lab` (`insight_lab_check_<pid>_a`, migrated to 0066), never on the lab itself.

**What changed** (the slice's files):
- `markx/schemas.py`: the 11 kinds (guide, subject, answer schema in the worker's JSON Schema subset), their sets, and the guides loaded into `mx_guides` by sha256 once per process and database, before the first lease or task (`ensure_guides`).
- `markx/guides/*.md`: 10 guides copied from the prototype: `read-v2`, `ent-v3`, `judge-raw-v1` and `judge-read-v1` (both `judge.md`), `card-v1`, `judge-story-v1`, `connect-v1`, `headline-v1`, `briefing-v1`, and `translate-v1` (written from F5's measured prompt). Checked against the lab's 380 source names and handles: none occurs, except "Hacker News" in ent-v3's venue examples, a product name kept as the guide was measured.
- `markx/validate.py`: the checks of the table above, after the schema. Text is compared folded (NFKC, case, dashes, ё).
- `markx/tasks.py`: `markx text v1` (corrections 3: post_parts' title and first 1,500 characters, the kept links, the quoted tweet), one input builder per kind ported from the prototype's renders, the task builders S2 and S5 call, and two planners: `read`/`entities` for the newest posts of the last 30 days (priority = the post's age in days), and `check` from Mark IX's current stories (`check_questions`, read only). A valid answer writes the post's reading (`mx_readings`) or its entities (`mx_mentions`, with 0090's name key). `reasked` counts the check tasks today's stories would no longer ask (corrections 4).
- `markx/api.py`: the router, with the contract frozen in its docstring. `INSIGHT_MARKX` off (the default): every path answers 404 and nothing runs.
- `backend/main.py`: one `include_router` line (and its import).
- The worker token: `GET`/`POST /api/markx/token` (in `markx/api.py`), stored encrypted in `credentials` (provider `markx`), and one button in Sources → Connections (`MarkXToken.tsx`, hidden while the route answers 404; the token is shown once; the design frames' fixtures answer 404).
- Tests: `test_markx_validate.py` (35), `test_markx_api.py` (27), `markxToken.test.tsx` (3).

**How the build plan's corrections are kept:**
- **No Mark IX story id in a task.** Inputs are content only; a check's `b` is null, a story task's `a`/`b` are its earliest member posts (or Mark X stories from S5). The same members in another order are the same task (tested), and a re-rooted story asks nothing new.
- **Mark X's text is versioned** (`TEXT_VERSION = "markx-text-v1"`); translation reads 2,500 characters, as F5 measured.

**S4's open points, settled** (the worker needs no change): answers posted as `{task_id, answer}` (an answer wrapped in its own name, `{"reading": {..}}`, is unwrapped); ids are uuid strings; `valid` is a count; `release` honours `task_ids`; an answer after its lease, or to a task another worker holds, is taken like any other, and one to an answered or failed task is a call that changes nothing (`repeated`); `schema` is the worker's subset, never null; tokens are per answer; `lease_until` always has its offset.

**Decided here, for the owner to confirm:**
- `connect` uses F6's guide (`bg_judge_story_dates.md`, story pairs with their members and dates), not `bg_graph.md`: this table's row (story pairs ≤ 30 days, both with dates) and F6's measured "development 13 of 15" are that experiment; `bg_graph` is the across-years post graph (0091).
- A judge question shows 3 members, as the prototype's renders (and its numbers) did, not "up to 5".
- Until S2's vectors, headline, connect and briefing inputs show the earliest members; the prototype showed those nearest the story's centroid.

**The round trip** (the prototype's recorded answers as the model, every request through the app; inputs built by `tasks.py` from the copy's posts and the prototype's recorded v9.12 members, corrections 1). Kinds below 200 are bounded by the recorded answers whose posts are in the copy (the lab ends 30 Oct; the prototype read to 5 Nov):

| Kind | Tasks | Valid | Invalid, with their errors |
|---|---|---|---|
| read | 200 | 200 | 0 |
| entities | 200 | 197 | 3: a version the post doesn't state ("6" for a model the posts call by its variant only) — right |
| translate | 87 | 86 | 1: "2 years" written as "two years" — strict |
| card | 43 | 43 | 0 |
| check | 54 | 54 | 0 |
| join | 111 | 111 | 0 |
| pair | 200 | 200 | 0 |
| merge | 43 | 43 | 0 |
| connect | 143 | 143 | 0 |
| headline | 138 | 135 | 3: one right (a version no member has), two false ("Q2" from "the second quarter", "November 6" from "11.6") |
| briefing | 5 | 4 | 1: a figure in a post outside the 4 shown (member choice, above) |
| **all** | **1,224** | **1,216 (99.3%)** | **8** |

- **The first run had 16 invalid; 9 errors were the checks', fixed as classes and measured again:**
  - a reading with 7 actors (the prototype's schema capped 6; neither the guide nor this table does);
  - 6 of 43 cards naming odd members by position (`odd` is kept as given: no decision reads it, and a position's base can't be told);
  - a headline's "GPT-5.6" from "their 5.6 versions" (a version is now found by its number);
  - a briefing's year from the day's own line (the same briefing then failed on a later line, above).

  A test then found "02" read against "2"; figures now drop leading zeros.
- **The invalid cases** (each answered task of every kind answered again wrongly, 5 a kind): a span or a version not in the post, a type or a relation out of its set, 21 entities, a confidence of 150, an odd member that isn't one, a 15-word headline, a figure or version in no member, a key not of the day, 8 lines, numbers dropped, three times the length. **Every one came back with its error**; the one exception was a "numbers dropped" case on a post with no number.
- **Mark IX's tables** (every non-`mx_*` table's rows and md5, before and after): only `credentials` changed, its new `markx` token row.

**The worker end to end** (`scripts/markx-worker` and `scripts/tests/fake-claude`, both unchanged, against the API in a container of its own on the scratch copy, Mark X on):
- **valid plan:** 60 tasks leased (planned by the server from the copy's last 30 days), the fake's answers refused by the worker's check of the server's schema, retried once, posted; the server stored 60 invalid calls with their errors and re-opened the tasks;
- **usage limit:** exit 4, 60 leases released; **auth:** exit 5, released; **missing lines:** retried, then released; **a wrong token:** exit 6.
- **The valid path, with the recorded answers as the model** (a private replay fake): 107 readings and 34 entity answers valid through both the worker's and the server's checks, stored with their readings and mentions.
- **For S4 (no change needed):** fake-claude's answers fit the stub's schema, not part C's, and its `FAKE_CLAUDE_STATE`/`_LOG` must be absolute (the worker runs `claude` in the temp directory). Because the server tops up `read` as it drains, `--kinds read,entities` reaches `entities` only when the 30 days are read.

**Tests:** backend suite SUITE_RESULT. Frontend: 708 tests pass; the bundle gate passes (feed route +0.10%, post route +0.09%).

**The real-data check:** REALDATA_RESULT

## Part D: the worker, Claude Code mode (your device)
`scripts/markx-worker` is one Python file using the standard library only.
```
markx-worker cycle --server http://<server>:5173 --token-file ~/.config/insight/markx-token \
                   --kinds read,entities --batch 20 --batches 5 --parallel 3
```
- **Each batch:**
  1. It leases tasks.
  2. It writes one prompt: the tasks' inputs, and an instruction to answer each as one JSON line `{"task_id", "answer"}`.
  3. It runs `claude -p --model haiku --tools "" --system-prompt "<the guide>" --output-format json --no-session-persistence --strict-mcp-config`, with the prompt on stdin. With no tools, Haiku only reads and answers; `--strict-mcp-config` keeps your MCP servers from starting with every call.
  4. It parses the lines, posts the answers, and logs the tokens Claude Code reports.
- **Measured** (2026-11-05, 51 calls, no errors):
  - **Batches of 20, 3 at a time, one retry** of what's missing or invalid.
    - At 20, kind agreed with the subagent readings 20/20.
    - At 40 and 60, it agreed 85% and 76%, with about a quarter of the output per post: shorter, less careful answers.
  - A batch of 20 readings takes about a minute.
  - About 1 in 40 entity answers needed the retry.
- **It stops cleanly:** on a usage-limit or auth error it releases its leases, logs why, and exits non-zero. A timer reruns it later.
- **The order:**
  1. `read` and `entities` for the newest posts;
  2. the questions;
  3. cards, headlines and the briefing;
  4. backfill.

  Each batch is one kind, so its guide is sent once.
- **Done when** the last 30 days are read and judged through it, and every answer is stored.

### Built (S4, branch `markx-s4-worker`, 2026-11-05)
The worker, ported from the prototype's `markx_worker.py` (the same `claude -p` call, the same instruction and item blocks, the same JSON-line parser, the same one retry in batches of their own). Not yet run against S3 or the real `claude`: **the owner runs the real-Haiku part** once S3 merges.
- **Files:**
  - `scripts/markx-worker`: one executable Python file, standard library only;
  - `scripts/tests/fake-claude`: a fake binary that checks the exact flags and answers by plan (valid, invalid, missing, usage limit, auth, errors, sleeps);
  - `scripts/tests/test_markx_worker.py`: a stub of part C's API (`http.server`, in memory: leases, expiry, checks, 3 tries, releases) and 36 tests.
- **What it does:** `cycle` (also `status` and `release`):
  - leases one kind per batch, kinds in the order given (default: part D's order);
  - batches of 20, 3 at a time, at most `--batches` leases a cycle;
  - checks each line against the guide's JSON schema (a subset), posts the valid ones, and retries what's missing or invalid once;
  - posts the still-invalid ones after the retry, so the server stores them with their errors;
  - releases what is still unanswered at the end of the cycle.
- **Tokens and cost** come from Claude Code's JSON:
  - in = input + cache read + cache creation;
  - out = output;
  - `total_cost_usd`, and the model from `modelUsage`.

  Each call is logged with them. Each answer is posted with its share of its batch (a retried task carries both calls' shares), so the posted totals add up to the spend on answered tasks.
- **Stops:** exit codes 4 (usage limit) and 5 (auth). On either, it starts no new call, posts what the running calls return, releases all its leases, and exits.
- **Leases:**
  - no call starts with under `--lease-margin` (120 s) left on its lease;
  - a running call isn't killed when its lease ends (its tokens are spent either way): its answers are posted, never retried.
- **The server unreachable:** exit 3. An answer whose post fails 3 times goes to a local spool, and the next cycle posts the spool first, so nothing is paid for twice. A wrong token exits 6.
- **The contract** S3 must match is in the worker's docstring: the four endpoints, their bodies and responses, and the bearer token. It lists where part C is ambiguous:
  - the answer line's shape (flat, as measured, then posted as `{task_id, answer}`);
  - the id type;
  - `valid` as a count or a list;
  - `release`'s body (`worker`, optional `task_ids`);
  - answers after a lease ended;
  - the schema dialect;
  - tokens per answer only;
  - `lease_until` without an offset.
- **Tests:** 36 pass (`python3 -m unittest discover -s scripts/tests -p 'test_markx_worker.py'`, about 25 s; run 4 times, no flakes). They cover:
  - valid: 45 tasks in calls of 20, 20 and 5, with the exact flags; tokens and cost posted and logged;
  - one kind per batch, in order; the `--batches` cap;
  - string ids, fenced and nested lines;
  - invalid then retried; still invalid after the retry; missing lines; missing after the retry (released);
  - retries combined by kind; the server's invalid answers left to the server; a non-fatal error; unparsable output;
  - usage limit (alone, and with calls in flight); auth (JSON and plain text); `claude` not found;
  - leases: about to end, ending during the call, the call's timeout;
  - a guide whose sha256 doesn't match;
  - the server unreachable; a post failing, spooled, then posted by the next cycle; a post failing once; the spool with the server still down;
  - a wrong token; a missing or empty token file; `status` and `release`;
  - the parser, the schema subset, the shares, the error classes and the lease times.

  The real `claude` was never run.
- **Real-data check** (`scripts/realdata-check.sh --base 58ba6ae --head markx-s4-worker insight_lab`, report `plan/research/lab/checks/markx-s4-worker-2026-11-05.md`): **0 change**, as expected with no app code touched.
  - Every derived thing is unchanged (titles, text starts, link titles, roundups, membership, origins, News, Classics, Discover), and so is every invariant. No case changes state.
  - The verdict says FAIL only for `discover-one-title-per-page` and `classic-paper-one-page`. Those are 0106's cases: marked pass after 0106 merged into main (5c1a375), they fail at the base 58ba6ae as well.
  - A first run against `main` (by then 543830d) showed 0106's own changes, reversed (Classics 230, Discover 740, membership 32). That run doesn't measure this branch.
- **Backend suite** (`./run-tests.sh`, unchanged code): 1,446 tests, 1 failure. `test_deploy_finishes`'s held-rows test timed out on a thread while the real-data check ran beside it; that module run alone passes (5/5).

## Part E: decisions and the Mark X page
**The decision job** (`markx/decide.py`):
- **How it runs:** a pure function from (Mark IX's current stories, the valid answers, `config`) to Mark X's stories, memberships and connections. It runs after each upload (debounced) and hourly, in the ingestion container.
- **Each run writes `mx_runs`.** It closes the memberships and connections that changed (`valid_to`) and opens the new ones.

The rules are the prototype's, none tuned on the server's window:
1. **Start from Mark IX's stories.** The link rules stay the first evidence.
2. **Gates:** a post under 20 words is never removed (rule A), and a roundup never joins as a whole: its items become mentions.
3. **Checks (F1):** "mention" or "digest item" demotes a member to a mention; "different" removes it below p 0.30 (0.15 in 2-voice stories, rule B). **Two-event guard:** a post whose reading has two events, one of them the story's, is demoted, never removed (measured: wrong removals 5 → 3).
4. **Joins and new stories (F2):** "about" at p ≥ 0.6. That's the measured best bar: 98% right, 95% on held-out days.
5. **Merges:** "same event" at p ≥ 0.85, until E1's merge labels set the bar.
6. **A second pass** compares every new story with the existing ones.
7. **Connections (F6):** development, follows_up and reaction are stored typed; same_topic is stored as related.
8. **Late posts:**

| What the late post is | What happens | News |
|---|---|---|
| The same event, reported late | joins only on the judge's "same event" at the merge bar; the story's date doesn't move | no new row; "back in the news" (0092) only when 2+ new voices arrive within 72 hours |
| A follow-up | its own story, linked "follows up" both ways | its own row: "Follows up: <the earlier story>" |
| Refers back, builds on | a connection, shown as background on the post | never by itself |
| About the same thing | "related", for reading on | never |

**Mark X News:**
- **The rows:** written into `mx_news` by Mark IX's own News code (`NewsService.refresh` over Mark X's stories), so the two Newses compare row to row.
- **Each row is tagged against Mark IX's:**
  - NEW: no Mark IX row has its lead;
  - CHANGED: the members differ;
  - MERGED: two Mark IX rows became one;
  - SPLIT: one became two;
  - SAME.

**The Mark X page** (`/markx`, in the menu when `INSIGHT_MARKX` is on):
- **News:** Mark X's News beside Mark IX's, with "only differences" on by default.
  - Every row shows its tag and Haiku's headline.
  - Opened, it shows each member with why it is there (the rule, or the judge's relation, p and words) and what Mark IX did with it.
- **Briefing:** today's briefing, each line linked to its stories, with the rule version beside it.
- **Entities:** today's and this week's main-subject entities, with their posts and voices. A first look at F7 v2; pages and timelines are 0090.
- **Labels:** part F.
- **Worker:**
  - the queue by kind;
  - answers per day;
  - tokens and the cost they would have on the API;
  - failures with their errors;
  - the last contact;
  - the last decision run.
- **On a post page:** a folded "Mark X" panel with its reading, its entities and their roles, its Mark X story, and its connections, each with its reason.

**Done when:**
- the prototype's numbers reproduce on a server copy: the same decisions on the same answers for its 16 days;
- the page reads well in the reader review (phone included);
- with Mark X on, Mark IX's tables are identical before and after a run (the realdata check's table diff).

## Part F: labels in the app (E1), and one tap
- **The labels page:**
  - **The queue:** the questions whose answer changes a bar: decisions near a bar, and every merge. It also takes a sample of the rest, weighted to the pools, as the prototype's labels were.
  - **What you see:** each item shows its evidence the way the judge saw it, but not the judge's verdict. You answer with one tap (same event, follow-up, related, different; or right, wrong, unsure), plus an optional note.
  - **The split:** older days are dev and the newest are test. The bars are re-picked on dev and reported on test, with their confidence intervals.
- **One tap on Mark X rows:** "wrong story" / "not about this" on any member in the Mark X News. These become labels too: no separate labelling sessions after E1, only a small monthly audit sample.
- **Done when** E1's set (about 2 hours of your time) is in, and the page shows each feature's precision on your labels with its bar.

## Part G (later): switching on, one feature at a time
Order:
1. F1 checks;
2. F2 joins and new stories;
3. merges;
4. headlines;
5. the briefing.

Each switch follows its feature's labels passing, after at least two weeks in Shadow. When one is on, Mark IX's News reads Mark X's membership for that feature only, and Mark IX's own rows stay stored (keep everything).

## Part H (later): the API worker on the server
After you buy the API: `markx-worker --api` on the server.
- Haiku 5.5 (`claude-haiku-5-5`, $0.10 / $0.50 per million tokens in and out), with the guide as a cached system prompt.
- The Batch API (half price) for backfills.
- A daily spending cap.
- Real time for new posts.

Before switching, 200 tasks run through both executors and their answers are compared.

## Safety and checks
- **One switch:** `INSIGHT_MARKX=off` stops every Mark X job, hides the page and leaves the tables as they are.
- **Mark IX untouched:** the realdata check (0075) gains these invariants on every copy:
  1. Mark IX's tables are the same with Mark X on and off;
  2. every valid call validates against its guide's schema;
  3. every current membership and connection names a rule or a valid call;
  4. tasks are unique per (kind, guide, input hash);
  5. no task stays leased past its lease.
- **Tests:**
  - validation per kind (spans, versions, figures);
  - leasing and answers;
  - the decision job on the prototype's recorded answers, which must reproduce its decisions;
  - the worker against a fake `claude` binary.

## Files
Shadow is mostly new files:
- **New:**
  - `backend/insight_core/markx/` (`api.py`, `tasks.py`, `validate.py`, `embed.py`, `candidates.py`, `decide.py`, `schemas.py`, `guides/`);
  - one migration;
  - `scripts/markx-worker`;
  - `frontend/src/pages/MarkXPage.tsx` and its components.
- **Shared, one line each:**
  - `backend/main.py` (the router);
  - the ingestion runner (the hook);
  - `docker-compose.yml` (the embedder);
  - `frontend/src/App.tsx` (the route);
  - the menu.

The migration takes the next free number when it merges.

## Open questions for the owner (each with my recommendation)
1. **Which posts may go to Anthropic?** All of them. Entities need every post read (a dictionary finds 16% of names), and through your device it is your own Claude account either way.
2. **The worker: by hand or on a timer?** By hand for the first days, to watch quality and your usage. Then a timer every two hours.
3. **How long in Shadow before switching on?** At least two weeks per feature, and only after its labels pass.
4. **The HNSW index now or later?** Now: it's 0.1 GB, and late posts need candidates across all time.
5. **The version name:** "Mark X v10.0 (Shadow)" when part E, the first part you can see, merges. Parts A–D are invisible and merge under the current version.

## Measured: time windows and late posts (2026-11-04, the lab copy, read-only)
Mark IX's windows had never been measured. They were checked with the app's own grouping, with each window as it is and widened to a year:

| Reason | Joins inside the window | Of those, within a day | Extra joins with a year |
|---|---|---|---|
| Shared link (72 h) | 1,104 | 88% | 724 |
| Citation (72 h) | 301 | 70% | 227 |
| Quote (72 h) | 525 | 90% | 47 |
| Title (7 days) | 212 | 97% | 7 |
| Text (30 days) | 129 | 95% | 0 |
| Address (30 days) | 3 | — | 0 |

**Labelled (experiment W, 135 pairs, two blind labellers):**
- Links and citations past a week are one story only 8 times in 48 (17%); at 3–7 days, 10 in 16. **Keep the 72 h windows.** Beyond them, pairs become typed connections, not joins.
- Quotes 3–30 days apart are one story or a follow-up 14 times in 16, and titles past 7 days 7 in 7. They may widen (small numbers).
- **The late-burst gap (0089):**
  - 23 of 35 burst pairs are one story or a follow-up, but 12 are not.
  - A burst rule on its own would add a wrong join for every two right ones.
  - **So bursts are candidates for the judge** (part B's `burst` source), not a rule.
