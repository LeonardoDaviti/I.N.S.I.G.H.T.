# 0086 — Mark X Shadow: Haiku reads and judges every post beside Mark IX, from your device first

Status: **spec, ready to build** (2026-11-04; owner: "commit all the issues", 2026-11-05). Not built. How agents build it: [the build plan](../INSIGHT_mark_x_shadow_build_plan.md). It's built as parts A–F, each merged on its own (the merge rule, 0075); G and H come later. It replaces the design draft of the same morning. The storage maths, the time windows and the late-post rules below are that draft's, measured the same day.

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
