# 0273 — Where sources differ, on the story page and the opened News row (Stalker feature 5; 0097)

Status: **built, switched off** (v10.32): measured blind under its bar (66% shown-disagreement precision, bar 97%).

## What
Inside a story with 3+ voices, a short "Where sources differ" block: only real disagreements on one fact (a number,
a date, a status, a cause, an attribution), each side with its value, its sources and a quote from each post. A side
stated only as a claim (persp-v1's `claims`) says "(claimed)". Nothing when the sources agree.

## Built
- `perspectives.py` (the sheet's owner, no parallel path): `dispute_lines` (every member's facts and claims with their
  spans, a member of another story left out), `dispute_original`, `dispute_input`, `disputes_of` (the code's checks)
  and `disputes_asked_today`. `one()` asks one `dispute` question a story with the sheet, only when the switch is on
  and the lines come from two or more sources; a story is asked again only when its input changes (members or their
  answers). At most `DISPUTES_PER_DAY` (300) new questions a day; over it the story waits for a later run, as a
  sheet waiting does. The result is kept in the sheet row (`sheet.disputes`); no migration.
- `disputes_of` keeps a difference only when the code can check it: two or more sides, each with a value and its own
  line numbers, no source on two sides, every side quoting its post (a line's stored span; the ORIGINAL, line 0, a
  quote of at least 12 folded characters found in its text). Haiku's answer is never trusted beyond that.
- Guide `dispute-v1` (markx/guides/dispute-v1.md), kind `dispute` (schemas.DISPUTE_SCHEMA, consumer `perspectives`,
  in the worker's default kinds).
- `built.build` carries `disputes` (from the current sheet, only while the switch is on), so the News row and the
  story page read the same thing; frontend `SourcesDiffer` (MarkXBuilt.tsx) in the opened News row and in the story
  page's "How it was built".
- Switch: mx_settings `stories.disputes` = "on" to ask and show; default **off**.

## Measured (copy insight_srv1119_check_a, 2026-11-21; rows in plan/research/v1032/disputes-0273/)
344 current sheets (all 3+ voices) with lines from two sources; Haiku (claude -p --model haiku, the worker's
prompt). 51 differences answered, 44 kept by the checks, in 36 stories. Labelled one by one against their quotes:

- **Precision: 29 of 44 real (66%, Wilson 51–78%).** Stated vs stated 19/32; a side only claimed 10/12.
- Wrong, by class (15): an update over time or a filing revision read as a disagreement (6: a pre-launch post vs the
  launch; a filing's first version vs its amendment, twice; weights before and after release; deposits suspended then
  reopened; a scheduled vs the actual release time); a rounder form of one value (2: "late eighties" vs "+80%"; $699
  vs a table's $700); different measures or moments (4: a quit date vs the announcement day; a half price that is
  likely the batch tier; a drop "in early trading" vs "at the open"; two scopes of one programme); no conflict (1: an
  "open-weight model" whose weights are not out yet); weak (2: "former executive" vs "head"; an edition the quote does
  not name).
- Right, for example: two output prices for one model; "all paying users" vs "only Work and Codex"; three vs four days
  after the investigation; 20 TB vs 16 TB; an intrusion's two different first steps; an attack attributed to two
  different states.
- **Recall, roughly: low.** Of the 35 stories whose sheet merge already flagged a multi-source conflicting group
  (`correction`), 12 got a kept difference; by eye most of the other 23 are real (a benchmark score 65.7% vs 67%, a
  revenue expectation $108B vs $109B, a quant's 233 GB vs 250 GB). Roughly 35–50%.

## Not switched on. Next (on a fresh set, never these 44)
1. Give each line its post's date and the ORIGINAL's, and say in the guide that a later post on a changed state is an
   update; that is the largest wrong class (6 of 15).
2. Read the merge's own `correction` groups as the candidates (its recall looks higher) and ask the dispute question
   only about those groups' lines, with their dates.
3. Measure blind again on stories mined from older server posts (held-out testing); switch on only at >= 97%,
   Wilson >= 90%.
