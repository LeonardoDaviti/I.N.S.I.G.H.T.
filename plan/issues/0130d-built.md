# 0130 D — Stealth v10.5 slice D: translation (0086 F5)

Status: **Built (D)** on branch `worktree-agent-adbbbad618703e520` (off main df54d6f), not merged, not pushed
(2026-11-07). Mark X Stealth, in Shadow: only mx_* tables are written.

## Built (D)

1. **On request.** `POST /api/markx/posts/{id}/translate` adds the post's `translate` task (guide translate-v1; the
   same task when asked again; priority -1, so the next worker run leases it before planned ones; a task that failed
   its three tries is opened again, because the owner asked). 400 on an English post or one of unknown language.
   `GET /api/markx/posts/{id}/translation` is what the page shows: the language, the task's state, the English.
   - **The language:** the post's newest Mark X reading's `lang` when it names one, else `posts.language_code`
     (`und` and empty name none; `en-GB` is `en`). The reading first, because the feed's field mislabels posts.
   - **The post page:** under the original, a "Translate" button, then "Translation asked: the next worker run answers
     it", then the English (title, text, its paragraphs) marked "Translated by Haiku from Russian · Mark X, in shadow",
     with ✓ right / ✗ wrong. Nothing shows on an English post. Mounted only while Mark X is on, its own chunk.
   - **The Mark X panel:** a Translation line with the same button and state.
   - **The labels:** `POST /api/markx/posts/{id}/translation/label {answer: right | wrong | undo}` stores a row in
     mx_labels, item kind `translation` (a = the task, b = the post; migration **0078** adds the kind, rebuilt the 0075
     way so other branches' kinds stay). A second tap on the chosen button sends `undo`. `GET
     /api/markx/translations/score` counts them by guide (Wilson 95%).
2. **Mark X News leads translate by themselves.** `tasks.PLANNERS["translate"]` (`translate.plan`): when a worker
   leases `translate` and fewer than its limit are open, a task for each non-English lead (the row's first post) of the
   newest written Mark X News run inside News' 30 days, highest score first, once a post (any guide, any state).
   - **Why at lease time, not a stage of the decision run:** fewer moving parts. No new stage, no job state, no change
     to decide.py or jobs.py; the rows are already written by the last run; a translation is only needed by a worker
     about to answer it (as `read3` is planned). The cost: a lead shows translated only after the worker's next
     `translate` lease following the decision run that made it a lead.
3. **The slang glossary, measured: not adopted.** `guides/translate-v2.md` is v1 plus a rule on digits and units, a
   paragraph-by-paragraph rule and a glossary of Russian tech slang and English written in Cyrillic (frontend,
   endpoints, production, weights, harness, GPUs, quants, ...). `schemas.KINDS["translate"]` still names
   translate-v1: v2 kept less of the meaning on F5's set (the rule: misleading ≤ v1's **and** meaning kept ≥ v1's).
4. Not built: translating every archived post.

## The measurement (2026-11-07)

Real Haiku (`claude-haiku-5-5`) through `scripts/markx-worker` (the main checkout's copy, unchanged; `--batch 20
--parallel 5`) against this branch's API on a scratch copy of the 2026-11-05 server export
(`insight_server_1105_check_501937_a`, its own worker token). The same input for both guides (`tasks.translate_input`).
Labelled blind by Opus with the lab's F5 labelling guide (the two versions shuffled into 10 batches, the guide hidden).
Rows (posts, translations, notes) are private: `plan/research/lab/markx/proto/out/bg/f5v2/`.

| | v1 | v2 |
|---|---|---|
| **F5's 150 posts**: all meaning kept | 119/147 = 81% (74%–86%) | 115/149 = 77% (70%–83%) |
| misleading | 7/147 = 5% (2%–10%) | 5/149 = 3% (1%–8%) |
| adequacy 3+ | 141/147 = 96% | 142/149 = 95% |
| wrong-term errors | 18/147 = 12% | 20/149 = 13% |
| failed the checks 3 times (no translation) | 3 | 1 |
| **100 unseen Russian posts** (held out, by length): all meaning kept | 78/99 = 79% (70%–86%) | 80/99 = 81% (72%–87%) |
| misleading | 4/99 = 4% (2%–10%) | 1/99 = 1% (0%–6%) |
| **all 250**: all meaning kept | 197/246 = 80% | 195/248 = 79% |
| misleading | 11/246 = 4% (3%–8%) | 6/248 = 2% (1%–5%) |
| cost per translation (worker-reported, retries included) | $0.00050 | $0.00058 |

Paired on the same post (F5): v2 better on 14, worse on 18; misleading only under v1 on 4, only under v2 on 1.
Held out: better on 11, worse on 7; misleading only under v1 on 3, only under v2 on 0. Every difference is inside its
interval. Spent: **$0.264** of the $2 cap (514 calls, the end-to-end checks below included).

- **What misleads now** is mostly not slang: a reversed subject ("X caught up with Y" for "Y caught up with X", both
  guides), "like" read as "unlike" (both), a source typo read as a negation (both), first-person "we" for the author's
  commentary (v1), a name read as words (v1). Of F5's three lab failures, the frontend one no longer misleads under
  either guide; the hardware-aware one is still mangled under v2.
- **The checks:** 24 of 507 answers (5%) failed a check once and were re-asked; 5 of the 488 tasks never passed,
  mostly a strict check:
  "6 с половиной" written as "6.5" fails "the number 6".
- F5's lab figures (87% kept, 2% misleading) came from another run and another labeller; this run's v1 is the
  baseline v2 was compared with.

## Tests

- `insight_core.tests.test_markx_translate` (new, 9): the language rule, ask / lease first / answer / view / ✓ ✗ undo
  as label rows / score / refusals, a failed task opened again, the planner (non-English leads of the newest run, inside
  the window, once a post), the planner from a lease, Mark IX's tables untouched, migration 0078 idempotent.
- Ran: test_markx_translate, test_markx_api, test_markx_validate, test_markx_folds, test_markx_labels,
  test_migrate_runner, test_markx_storage (159, OK). Frontend: `components/markx` and `pages/PostDetailPage*` (132, OK,
  5 new in `translation.test.tsx`); `npm run build` OK.
- End to end on the scratch API: a Russian post asked → one worker run → its English shown, ✓ stored; three Russian
  News leads planned by the lease and answered in the same run.

## For the owner

1. **v2 or v1.** By your rule v2 is not adopted (meaning kept 77% against 81% on F5's set). On the held-out posts and
   on all 250 it misleads less (2% against 4%) and keeps about as much (79% against 80%). Say "adopt v2" and it is one
   line in `schemas.py`.
2. 0130 open decision 3 (D2): only Mark X News leads are planned (the default). Mark IX News leads too would be
   a second query in `translate.plan`.
3. The number check refuses "6 с половиной" → "6.5" and similar. A looser check is a change to `validate.py`, not made.

## Files

`backend/insight_core/markx/translate.py` (new: the routes, the view, the labels, the planner), `markx/api.py` (one
include line), `markx/tasks.py` (the planner entry, marked `# 0130 D`), `markx/guides/translate-v2.md` (new),
`db/migrations/0078_markx_translation_labels.sql` (new), `tests/test_markx_translate.py` (new);
`frontend/src/components/markx/MarkXTranslation.tsx` and `translation.test.tsx` (new), `MarkXPanel.tsx` (one mount
line and its import), `pages/PostDetailPage.tsx` (one mount line and its lazy import), `services/api.ts` (one block at
the end, `// 0130 D`).
