# 0150 — Reading that wastes nothing: invalid answers re-asked alone, what may share a call, long posts read whole

Status: **spec** (2026-11-10). Fusion stage 2 (Read). Parts A and B: the worker, buildable now. Part C:
**passed E5 (2026-11-10)** (see "Measured"). Roadmap: `plan/INSIGHT_fusion_plan.md`.

Read first: `plan/HANDOFF-v10.md`; 0086 (tasks, the worker, validation), 0112 (readings the server accepts);
`scripts/markx-worker` (`PER_CALL`, how a refusal halves a batch); `markx/validate.py`; `post_parts` (check what it
holds before adding a table).

**Constraints:** no always-on worker; keep everything (a refused answer stays in `mx_calls`); tests use the fake
claude; realdata-check once at release.

## Why (all rough: the exploration, private `plan/research/fusion/out/F8h`, `F2b`, `F2c`, `F9c`)
- **About 12.7% of today's reading spend produced no stored answer** (calls whose answer failed validation), on the
  local copy's call log. Reading costs about $1.38 per 1,000 posts.
- **Items that share a call leak into each other** when they are related: windows of one long text answered with
  each other's content; sources of different spheres judged against the wrong sphere (13 of 63 verdicts in one).
- **A reading of 6,000 characters misses most of a long post.** Long items stayed dense with facts through 8
  windows of 6,000 characters. Reading the windows costs about $0.33 more per 1,000 posts.

## What it does
### A. An invalid answer costs one item, not a batch
- First: count, on the server by GET, the calls of the last 30 days whose answer was refused, by kind and by reason
  (not JSON, schema, an item missing, an id that was not asked). This is the baseline.
- When a batch's answer is valid for some items and not for others, **the valid items are stored** and only the
  invalid ones are asked again, **alone**, once. A second invalid answer fails the task with its reason (as today).
- The worker's summary line counts spend with no stored answer, per kind.

### B. What may share a call (a rule of the worker, per kind)
- Never in one call: two windows of the same post; items judged against different descriptions (tracks, spheres,
  sources' test-reads: 0149 B); two members of the same story when the question is about each alone.
- May share: unrelated posts asked the same question (as today).
- Stated per kind beside `PER_CALL`, tested with the fake claude.

### C. Long posts read whole (after E5)
- A post longer than one reading (6,000 characters) is cut into **windows** at paragraph ends, at most 8, each read
  by its own call (kind `window`, the claims guide of 0152 with one line of context: the post's title and the
  window's number of how many).
- **Merged by code:** claims in order with their window; entities as a union (identity as today); the post's own
  reading (kind, main event) stays the first window's.
- A post past 8 windows keeps its remainder unread and says so on its page ("read to 48,000 of 130,000
  characters").
- Planned newest first, after the short posts of the same run; its own page size per run.

## What the results should be
- Spend with no stored answer: from about 12.7% to under 4%.
- No answer in a stored row that belongs to another item of its call (E5 measures it on windows: 95% of a window's
  claims are in that window).
- Long posts: every fact a reader would cite is reachable from the post's claims, not only the first 6,000
  characters' share.

## Done when
- Tests: a half-valid batch stores its valid half and re-asks the rest alone; a second failure fails the task; the
  call rule per kind; windows cut at paragraph ends, capped at 8, merged in order.
- On the server (GET): A's baseline, then the same count after a week of runs.
- C is switched on only when E5 passes.

## Measured (E5, 2026-11-10; private: `plan/research/fusion/measure/E5/REPORT.md`)
30 unseen long posts (12,000–48,000 characters, three groups of spheres, 5 video transcripts), 104 windows, one call
a window with 0152's claims guide.

| | Result | Bar |
|---|---|---|
| A claim's quote is in its own window (code) | 745 of 746 | 95%: met |
| What two blind labellers kept from later windows (98 facts each) is covered by a claim | fully 44–53%, fully or partly 87–88%; not covered 12–13 | 85%: met if "partly" counts |

- **70% of a long post's claims come after the first 6,000 characters,** and windows stay as dense to the end (about
  7 claims each). A first-window reading covers 1–2 of the 98 later facts.
- **"Partly" is mostly the labellers' compound sentences** against one claim per assertion (6 of 9 rows read).
- **The misses have a cause:** 66 of 104 windows returned exactly 8 claims, the guide's cap. For a window, the cap
  becomes 12 (claims-v2, a new set).
- **Added to C:** a window that is not prose (page styling, formulas, link lists) is not asked: one post of the 30
  was mostly markup and still cost a call a window. Decided by code (the share of letters and sentence ends).
- **Cost:** about $0.0022 a window; $7.70 per 1,000 posts of this length.
