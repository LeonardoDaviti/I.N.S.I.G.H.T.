# 0214 — Entity answers missing from the worker's calls: causes and fixes (spec)

Status: **spec** (2026-11-16). Follows 0213 (refused answers). Nothing built. Private: `plan/research/entity-waste/`
(`missing.py`, `per_run.py`).

## Measured (the worker's logs since 0191's settings, 14 Nov 01:45 – 16 Nov; entities calls, retries included)
81,744 entities answers asked; **9,263 missing (11.3%)**; at the first attempt 6,387 of 71,195 (9.0%). A missing
answer is a task whose line is not in the call's output. It is asked again in the same cycle once, then released.

| cause | missing answers | share | calls | paid? |
|---|---|---|---|---|
| the call answered, but some of its lines are missing | 4,282 | 46% | 812 | **yes** (the call's price is split over its items) |
| the API unreachable (`Can't reach the API server`; calls up to 3 minutes each) | 2,984 | 32% | 268 | no (no tokens) |
| the weekly limit (`You've hit your weekly limit · resets …`) | 1,416 | 15% | 148 | no |
| the call answered, but no line could be read at all | 450 | 5% | 40 | **yes** |
| a usage-policy refusal (handled by 0191's halving) | 128 | 1% | 26 | no |

- **Paid and lost: 4,732 answers (5.8% of those asked)**, all in calls that answered. The other half of the 9% cost
  calls and time, not tokens.
- **Some lines missing:**
  - in 812 calls (median size 10, median 2 missing; 341 calls lack exactly one line);
  - not an output cap: these calls' outputs are shorter than complete calls' (output deciles 355–27,679 tokens
    against 2,052–30,902; the largest complete call wrote 76,088);
  - the logs keep no output text, so whether the model skipped an item, merged two, or wrote a line the parser
    cannot read (a JSON object over several lines, an id written differently) is not known.
- **No line at all:** 40 calls with short outputs (median about 600 tokens): an answer in another shape (a JSON
  array, one object holding all items, prose).
- **The weekly limit and the unreachable API did not stop the cycles they hit.**
  - Five cycles on 14 Nov (01:45–05:41, `per_run.py`; every kind, not entities alone) logged 246–521 weekly-limit
    failures and 195–482 unreachable failures each, over 20–40 minutes, each ending `done`.
  - The worker classifies the weekly-limit text as `usage`, which should be fatal (exit 4) and stop new calls. That it
    did not is the first thing to explain.

## Fixes, one per cause (the worker, `scripts/markx-worker`; tested with the fake claude)
1. **Some lines missing → ask the missing ones alone, at once** (0150 A's rule for invalid items, applied to missing
   ones). A call that returns k of n lines keeps the k. The missing tasks are asked again in calls of at most
   `ceil(n/2)`, halving down to one, in the same cycle, never in the original batch again. The output of a call with
   missing lines is kept (its first 4,000 characters, in the log line `missing_text`) for a week, so the cause can be
   counted: a skipped item, a merged item, or a line the parser rejected. A parser fix follows only from that count.
2. **No line at all → read the other shapes, then ask again halved.** `parse_lines` also accepts a JSON array of
   answers and one object keyed by id, each still checked by schema. Otherwise, the halving of 1.
3. **API unreachable → retry the call, not the items.** The same prompt again after 30 s, 60 s and 120 s, not
   counted as an attempt and not halved. After three unreachable calls in a row, the cycle stops: it releases its
   leases and exits 3 (server-side errors already exit 3), so the loop script waits instead of leasing again.
4. **Weekly limit → stop at the first one, and wait for the reset.**
   - Find why `classify` → `usage` → `set_fatal` did not stop the five cycles: a fake-claude test with 20 parallel
     calls, all answering the weekly-limit text, must end the cycle within one round of in-flight calls and release
     the rest.
   - The hand loop scripts (the owner's `always.sh`, `day.sh`, private) read the reset time the message states (`resets Nov 15, 3pm
     (Asia/Tbilisi)`). They sleep until then instead of starting a new cycle every round.
5. Refusals: unchanged (0191).

## What the results should be
- Paid and lost entities answers: from 5.8% to under 1% (re-asked alone in the same cycle). Measured on the worker's
  logs of the week after: the share of `missing` in answered calls, and how many recover alone.
- No call is sent while the weekly limit stands, and none while the API is down past three tries.
- Missing at the first attempt: from 9.0% to the answered-call share only (about 6%), then under 1% after the alone
  retries.

## Done when
Fake-claude tests for each fix (partial output → only the missing re-asked, halving; an array-shaped answer parsed;
three unreachable → exit 3 with leases released; the weekly-limit text → the cycle ends within one round; the loop
waits for a stated reset). Then one hand cycle on the owner's device, and its log counted as above.
