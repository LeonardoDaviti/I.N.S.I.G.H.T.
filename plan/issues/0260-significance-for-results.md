# 0260: Significance for results (Stealth v10.30)

Status: **built and measured**, switch ON (`entity_bands.json` `significance.results`). Not pushed, not deployed.
No migration. Exact rows are in the private notes (`plan/research/v1030/significance/`).

## The problem

A frontier research result (a lab's model reported solving two open problems in a branch of physics; 3 voices) got
significance 0.5: effect 3, why "no released tool, but a notable step". It ranked 130 of 319 rows. The reader reads AI
news and wants capability results high. significance-v2 (0208) defines `effect` as the effect "on the work of people
in its field": every level above 3 asks for something practitioners can adopt, so a result with nothing to download
caps at 3, and its score gets none of the usable/open bonuses either.

## The change

- **significance-v3** (`backend/insight_core/markx/guides/significance-v3.md`), the same answer fields and schema as v2.
  An event matters in two ways, either enough: what it changes in what the field knows or can do (a new capability
  shown, an open problem solved, a new state of the art, a first of its kind), and what people can use today.
  `effect` 4-5 now name both kinds of advance; "nothing released yet never lowers a result's effect (that is
  `usable`'s answer)"; business (funding, deals, revenue, valuations, hires), lawsuits and opinion stay 1-2 unless
  the posts show they change what practitioners can do. A result the posts show doubted or not reproduced is lower.
  General wording, no names, no sphere.
- Registered as a guide variant of the `significance` kind (`schemas.GUIDE_VARIANTS`, its schema SIGNIFICANCE_V2);
  `schemas.guide_of` (the one seam every task's guide comes from) names it when the switch is on.
- **No mass re-ask.** A task is unique per (kind, guide, input), but `significance.plan` asks a row only when it is
  new, or its posts changed and its last ask is 6 h old (`due`): switching the guide asks no row by itself. Old rows
  keep their v2 answer until their posts change. `score` is unchanged.

## Measured (2026-11-21, the one read-only server copy, nothing written)

Frozen sample (`frozen.json`, sha256 in `frozen.sha256`): each News row's newest answered significance input, 20 a
group drawn by a fixed hash from the stored v2 event type: research (research_result, new_method, benchmark), releases
(new_model, new_tool, release_update, product_launch), business/opinion (deal_funding, opinion_analysis, people,
policy_legal); plus 6 frontier results found by headline words (discovered, proven, first, solved...): 66 rows.

Each guide asked twice with Haiku, 5 rows a call in shuffled batches, the worker's head line and system prompt (guide +
schema). 66/66 answered in all four runs. A blind judge (Haiku, two runs, its own reader rubric, never shown any guide's
answer) rated each row 1-5 for an AI-news reader; judge run vs run Spearman 0.894. Scores are `significance.score`,
averaged over the two runs.

| | v2 | v3 |
|---|---|---|
| Spearman with the judge, all 66 | 0.826 | **0.899** |
| per run | 0.812 / 0.760 | 0.898 / 0.837 |
| pairs ordered against the judge (of 1,870 untied) | 240 | **145** |
| research + frontier, within the group | 0.585 | **0.812** |
| business, within | 0.768 | **0.830** (0 pairs reversed, 8 before) |
| releases, within | **0.822** | 0.709 (runs 0.783 / 0.631 against 0.752 / 0.776) |
| research vs release pairs reversed | 93 | **65** |
| business vs the rest reversed | 56 | **20** |
| mean rank of the 6 frontier results (of 66) | 23.0 | **17.2** |
| mean rank, research / releases / business | 30.7 / 21.9 / 51.1 | 28.4 / 24.4 / 52.6 |
| top 15: release / research / frontier (judge: 8 / 3 / 3, 1 business) | 10 / 3 / 2 | 8 / 4 / 3 |

Run-to-run noise of a guide: v2 0.891, v3 0.872 Spearman; equal `effect` 50/66 and 48/66.

How rows move: 16 of 26 research/frontier rows rise (8 fall); 16 of 20 releases fall in rank, mostly by a place or a few as results pass them (their mean score 0.566 -> 0.528). Among research, the largest a lattice physics result (rank 48 -> 29,
effect 2 -> 3; judge 4), a model-reads-weights study (4.5 -> 1.5), two capability estimates (25.5 -> 16), a protein
design result (18.5 -> 12), a three-discoveries announcement (25.5 -> 18.5, effect 3 -> 3.5; judge 4.5). Business and
opinion stay at the bottom (funding, IPO, revenue, executive scandal: effect 1, several fall further).

Worse rows (judge high, v3 lower): a quantized model's long-context benchmark (rank 12.5 -> 35.5, effect 3 -> 2;
judge 3.5); an image model update (9.5 -> 21.5; judge 4.5); a world model announcement (4.5 -> 12, effect 4 -> 3.5;
judge 5); a state lawsuit about agents (31.5 -> 42; judge 3); an engineering write-up of CI workflows (22 -> 38.5;
judge 3). Releases' within-group order is the one place v3 is not better; one v3 run matches v2, the other is lower:
within the noise of two runs, not a clear regression, and watched.

Not measured: the original case (its row is newer than the copy, 2026-11-19); the judge is Haiku with a rubric that
states the reader's wish (frontier results and releases high), not the owner's labels.

## Left

- Watch releases on the server's real News (a big release dropping under a minor result is the failure to look for).
- `score` still adds usable/open/library bonuses (up to +0.25) a result never gets: an effect-4 result scores 0.75, an
  effect-4 open release 0.9+. Not changed here (0208's measured weights); a candidate if results still sit low.
- Old rows keep v2 answers until their posts change; a capped one-off re-ask of the current window is possible but
  not done (no mass re-ask).
