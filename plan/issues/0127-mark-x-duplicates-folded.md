# 0127 — Mark X v10.3: duplicates folded (the same happening, retold, shows once)

Status: **built on branch `worktree-agent-a30d5eaecac1f23c6`, not merged** (2026-11-07). Mark X Stealth in Shadow. Not merged, not pushed. v10.2 is perspectives (0119 Part B), built at the same time by another session; this is **v10.3**.

## Why
- 0119 "Not in this issue": `read-v3` and its story rules are the next version.
- Experiment 1 (`read-v3`, lab, 2026-11-06) tested four story rules built on per-post event types. **One passed: "duplicates folded".**
  - Within a story, the posts that retell the same happening (the same announcement reposted, translated, summarised) fold, so the happening shows once, with the others under it.
- The same experiment found a guide rule that ends a live refusal ("main is null but events is several"): **0 violations in 6,143 answers.** It goes into the next reading guide.

## Scope
**In:**
- the fold;
- the `read-v3` reading guide (with the main/events rule) that the fold reads;
- the owner's label buttons on the fold.

**Out, below their bars** (measured in experiment 1 and its round 2, `read-v3e`; not built):

| Rule | Bar | Result (unseen) | Why it's out |
|---|---|---|---|
| Event type as a feature (14 types) | ≥ 90% | 73.9% (69.7–77.7); 5 coarse groups 82.3% (round 2: 85.7%) | below the bar; the fold uses the type only as "same as the story's", inside one story |
| The original first (in News) | beat today's F1 0.71 | F1 0.63 (round 2: 0.507 against 0.568) | worse than today's code + `persp-v3.2f` |
| Leak inside a story | beat 0/4 | 2/4 (n = 4; round 2 1/2) | too few to tell |
| Rumour → confirmation across stories | beat 0/6 | 0/6 (round 2's pairwise judge: F1 0.800, but it needs a precise rumour flag first) | not built here |
| `confirms_earlier` | — | 0/5 precise | dropped from the guide |
| "Strict" fold (nothing new) | — | F1 0.21 against 0.33 | that's perspectives' `same` (0120), a different feature |

The leak role still runs inside the fold rule: a leak is never folded. It isn't shown as a leak.

## What was measured (lab, private: `plan/research/lab/markx/proto/out/read_v3/REPORT.md`, `out/read_v3e/REPORT.md`)
"Fold = retelling": a member's role "retelling" (two blind Opus labellers plus a referee) against the rule's.

| Set | Rule | F1 | P | R |
|---|---|---|---|---|
| Round 1 test (60 clusters, 214 members), 3-run vote | read-v3 (14 types) | **0.70** | 70.1% | 70.1% |
| the same, **one run** (each of the 3; replayed 2026-11-07 from the lab's answers, no call) | read-v3 | **0.68 / 0.72 / 0.71** | 67–77% | 66–73% |
| the same, gold members only (171), one run | read-v3 | 0.71 / 0.74 / 0.72 | 73–80% | 66–73% |
| Round 1 test, today | `persp-v3.2f` `same` | 0.24 | | |
| Round 2 test (64 noisier clusters, 210 members), vote | read-v3e (coarse groups) | 0.556 (gold members 0.641) | | |
| Round 2 test, today | `persp-v3.2f` `same` | 0.382 (0.406) | | |

- **One run is enough:** production asks once. The single runs lie within the vote's noise (±2 points).
- **The rule built here is round 1's** (14 types, `rv3_rules.rv3_roles`), the better of the two on both sets' own terms. Round 2's coarse groups lost 0.15 F1 on noisier clusters, but there its baseline fell too.

## Decided

### 1. A new task kind `read3` with guide `read-v3`, asked only of story members
`read` stays `read-v2`, so Mark X's decisions don't change. **Kind `read3`:**
- **Guide `read-v3`:** the lab's frozen `read_v3d_frozen.md` (md5 `eaea4ae05b4c5b4974d4e9ff02da7bde`) with:
  - `confirms_earlier` dropped;
  - its real names replaced by invented ones (6 lines), and its `@x` as `@<author>` (2 lines; the guides' name check);
  - its title line changed.

  Everything else is word for word, including the main/events consistency rule and `type_why` before `event_type`. Its md5 is `56c6326c656428ed4b839e3b9bbf6c39`.
- **The answer:** read-v2's fields, plus `type_why` (≤ 15 words), `event_type` (14 types) and `origin` (maker / relay / other).
  - The server checks read-v2's checks (main/events, headline length).
  - The answer is stored as a reading under guide `read-v3` in `mx_readings`, beside the post's `read-v2` reading.
- **The input:** read-v2's (`markx text v1`), plus what the lab's block added for `origin`:
  - `Address: <the post's url>`;
  - for a repost, `Repost: written by @<author>, reposted by <source>`;
  - `Published: <UTC, minutes>`.
- **Asked of:**
  - the current members of Mark X stories with 2 or more members;
  - in the reading window (the read planner's setting), newest first;
  - once per post: a post in two stories is read once.

  It's planned when the worker asks for `read3`, as `read` is.
- **The worker:** `read3` comes after `read` in the default `--kinds`, **5 a call** (the lab's rv3d batch size; 20 a call is unmeasured).

**The cost** (Haiku 5.5 at the API's prices, as `mx_calls` records them):
- **Measured:** 200 real `read3` answers cost **$0.00064 each** (40 calls of 5; about 1,000 tokens out an answer). Today's read-v2 answers average $0.00033 (5,344 on the server copy).
- **Asked only of story members (built):**
  - the server copy has 1,094 posts in Mark X stories with 2+ members (355 current stories);
  - the first pass is about **1,100 answers, ≈ $0.70**. After that, only new members: a few cents a day.
- **Rejected: `read` switched to `read-v3` for every post.** It would re-read about 10,600 posts (≈ $6.8). Every later read would cost about twice as much, and the stories would change with the new readings. That would be a second change measured as one.
- **Rejected: a slimmer guide asking only `event_type` and `origin`.** It would cost less a pass, and its F1 is unmeasured.

### 2. The fold rule (code; `markx/folds.py`, ported from `rv3_rules.rv3_roles`)
Per Mark X story, over its current members (role `member`) that have a `read-v3` reading, in published order (Mark X's `at`, then id):
1. **The story's type:** the most common of its members' news types (model, product, research, business, policy, incident, statement, promotion). A tie goes to the type that appears first.
2. **Originals:**
   - a member of the story's type whose origin is `maker`;
   - or the first member of the story's type that is a `relay`, while no original came before it.
3. **Leaks:** a `leak_rumour` member with a later member of the story's type. Never folded.
4. **Retellings:** the other members of the story's type whose origin is `other` or `relay`.
5. **The group:**
   - the head is the earliest original, else the earliest retelling;
   - every retelling but the head folds under it.

   A story without at least one folded member has no group.
- **Members without a `read-v3` reading** (not read yet) are never folded and don't count towards the type.
- **A post in two stories** is folded per story.

### 3. Where the fold is stored: nowhere of its own
The fold is a function of rows Mark X already keeps:
- the readings: `mx_readings`, guide `read-v3`, never changed;
- the members: `mx_story_posts`, closed with `valid_to`, never deleted;
- the owner's answers: `mx_labels`.

It is computed when the page is built (`folds.story_folds`), as 0120's sheet is computed and never stored as prose. Any past fold can be rebuilt from these rows' history. **Keep everything holds:** nothing is deleted, and nothing derived needs closing.

**Migration `0075_markx_folds.sql`** (0073/0074 are other branches') changes one thing: `mx_labels.item_kind` may be `fold`.
- The CHECK is rebuilt from the values it already allows plus `fold`, so a branch's migration that added its own kinds (0119 B's `perspective`, `fact`) keeps them, whatever the order of merging.
- It is idempotent, and touches no Mark IX table.

### 4. How it is shown
**The Mark X News tab** (the Mark X story view today):
- In an opened row, the group's head shows as now. Under it, one line **"↳ N more retell it"** opens the folded posts. Each folded post is a normal line, indented, with its source and time, and opens its post.
- The row's summary line adds **"· N retold"**.
- The members outside the group are unchanged.
- **The header** gives the lab's number: "Duplicates folded: experimental; on unseen lab stories F1 0.70 (lab, 2026-11-06)". The owner's own count comes next to it once there are labels.

**Mark IX's News and reader:** unchanged. Mark X is Shadow; `markx.ix_unchanged` holds with Mark X on or off.

**0119 B6's story view** (perspectives, v10.2): when it lands, its member list uses the same `folds.story_folds` and shows the group the same way. `GET /api/markx/stories/{id}/folds` serves it.
- The two folds are different features: perspectives' `same` is "nothing new"; this one is "the same happening, retold", which may add facts.
- A folded member keeps its perspective label inside the group.

**The post page's Mark X panel:** shows the newest reading. For a story member that is the `read-v3` one; its event type and origin aren't shown.

### 5. The owner's label buttons (like 0119 Part A's queue answers: applied at once, stored as a label)
**The buttons:**

| On | Buttons | What each does |
|---|---|---|
| A folded post | **same happening ✓** / **not the same ✗** | ✓ confirms the fold; ✗ unfolds the post at once |
| A member outside the group (not the head), in a story that has a head | **fold: same happening** | folds it under the head at once |
| Any line after an answer | **you: …** and **undo** | undo returns the post to the rule's fold |

**Storage:** `mx_labels`:
- `item_kind` `fold`; `a` the story, `b` the post;
- `answer`: `same`, `not_same` or `undo`;
- `labeller` `owner`, `split` `test` (unseen by construction);
- `note`: JSON with what the rule said (`folded` or `shown`) and the head.

The newest answer counts, and a changed answer is a new row. The rule never overrides an answer.

**The count** (`GET /api/markx/folds/score`, shown in the header):
- **precision:** of the folded posts the owner answered, how many are `same`;
- **missed:** the `same` answers on posts the rule showed;
- each with a Wilson 95% interval.

**No bar is re-picked on these labels.** A changed guide or rule is a new id, measured on new labels.

### 6. Hooks in shared files (the rest is in new files)
| File | Change |
|---|---|
| `markx/schemas.py` | `READ3_SCHEMA`, the `read3` kind |
| `markx/tasks.py` | `record` stores a `read3` reading; `PLANNERS` and `WINDOWED` name `read3` |
| `markx/validate.py` | `read3` gets read's checks |
| `markx/news.py` | `page` adds each line's fold and the header's count |
| `markx/api.py` | includes `fold_api.router` |
| `scripts/markx-worker` | `read3` in the default kinds, 5 a call |
| `frontend/src/services/markx.ts`, `api.ts` | the types, two calls |
| `frontend/src/components/markx/MarkXNews.tsx` | the row's posts through `FoldedPosts` |

**New files:**
- `markx/folds.py`, `markx/fold_api.py`, `markx/guides/read-v3.md`;
- `db/migrations/0075_markx_folds.sql`;
- `tests/test_markx_folds.py`;
- `frontend/src/components/markx/MarkXFolds.tsx` and its test.

## Measure before merging (not done here; what to measure)
- **On Mark X's own stories:** the lab's sets are used up. Use a scratch copy of the server data with Mark X's stories (`insight_server_1105_mxreal` has them; `insight_server_1105` has no `mx_*` tables).
  1. Take 40 stories with 3+ members, after their membership checks.
  2. Two blind Opus labellers plus a referee label each member's role (original / retelling / reaction / leak / not a member), as `rv3_story_label.md` does.
  3. Run `read3` once through the worker (about 200 posts, ≈ $0.10).
  4. Score the fold's F1 against today's `persp-v3.2f` `same` on the same stories.
  - **Bar:** F1 ≥ 0.60 and above today's.
- **Cost:** the first pass's calls, tokens and cost from `mx_calls` on the server.
- **The real-data check** (`scripts/realdata-check.sh`) at merge: `markx.ix_unchanged`, `markx.api_during_run`, the speed of `/api/markx/news` with the fold.
- **The reader review** on the real `/markx`: 5 stories with a group, read as the owner would.

## Open questions for the owner
1. **Start the fold now, at F1 0.70?** It's experimental, behind the header, with label buttons. Or wait for the Mark X stories measure above?
2. **The first pass reads about 1,100 posts (≈ $0.70).** Should the read window for `read3` be the reading window (30 days), or only News's?
3. **Should a folded group also fold in News's count of sources?** Not built: the row still counts every voice.
4. **Several "originals" in one story** (each maker's post, e.g. a paper's page saved and its authors' posts) are each shown, not folded. That is the lab's rule. Should the maker's later posts fold under the first?

## Built (2026-11-07)
**Commits:**
- `4a56909`: the spec;
- `84a7465`: the backend;
- `ec78283`: the Mark X News tab;
- the next one: this section.

**What's in:**
- **Kind `read3`:** its guide, schema, checks, planner (`folds.plan`) and storage (a `read-v3` reading).
- **The worker:** `read3` in the default kinds, 5 a call.
- **The rule and the group** (`folds.roles`, `folds.group`); the fold of a story from the database (`folds.story_folds`).
- **The News page's lines:** `fold`, the row's `folded`, the header's `folds`.
- **The routes:**
  - `GET /api/markx/stories/{id}/folds`;
  - `POST /api/markx/folds/answer`;
  - `GET /api/markx/folds/score`.
- **Migration 0075.**
- **The Mark X News tab:** the group, its count, the header and the buttons.

**Checked:**
- **The port is the lab's rule.** On the lab's dev and test clusters, `folds.roles` gives the same role as `rv3_rules.rv3_roles` for 338 of 338 members, for each of the three runs and the vote. The fold F1 is the same: test 0.68 / 0.72 / 0.71 one run, 0.70 vote. This was a local replay, with no call.
- **Real Haiku, end to end.** On a scratch copy of the server data with Mark X's stories (`insight_server_1105_mxreal`, migrated to 0075, dropped after), through this worktree's worker, against its own API and token:
  - 200 `read3` answers, newest story members first, 40 calls of 5;
  - **200 of 200 valid**, and **0 main/events violations**;
  - $0.128 in all, $0.00064 an answer.
- **The fold on Mark X's own stories:** 54 stories had every member read (184 members).
  - 37 have a head; 14 have a group; 21 members are folded (11%).
  - Read by eye (not labelled, so not an F1):
    - a paper's channel retellings fold under its first link post;
    - two retellings of a security incident fold together;
    - the opinions stay shown.
  - Two of the lab's known errors show:
    - an independent test is taken for a maker's post, so it is shown as an original;
    - a later reproduction on another model is folded as a retelling.
- **Tests:**
  - `test_markx_folds` (20, new);
  - the backend suite once: **1,986 tests OK** (1 skipped);
  - `folds.test.tsx` (2, new);
  - `npm test`: 240 node tests and 760 vitest, all pass;
  - `npm run build` passes, with the bundle check: feed route +0.34%, post route +0.21%.

**Not done:**
- `scripts/realdata-check.sh` (at merge);
- the measure on Mark X's own stories with blind labels (above);
- the reader review.

## Handoff
- **Done:** the spec, the build and the checks above. Nothing pushed or merged.
- **Shared files touched:** each is a small hook; the table in §6, plus one line in `tests/test_markx_validate.py` (the kinds' set gains `read3`).
  - `schemas.py`, `tasks.py`, `validate.py`, `api.py` and the worker's `DEFAULT_KINDS` are also touched by 0119 Part B (perspectives). Merge them by hand: both add kinds and planners.
  - **The worker:** at merge, the main checkout's `scripts/markx-worker` gets the new default kinds and `read3=5` only when no live worker runs from it.
- **Left:**
  - the measure on Mark X's own stories (40 stories, blind labels, about $0.10 of Haiku);
  - the real-data check;
  - the reader review;
  - the owner's four questions above;
  - 0119 B6's story view, when it lands, uses `GET /api/markx/stories/{id}/folds`.
- **To resume:**
  - `./run-tests.sh insight_core.tests.test_markx_folds` (with `TEST_IMAGE` set, so `insight-backend:latest` isn't rebuilt);
  - `cd frontend && npx vitest run src/components/markx/`.
