# 0272 — Numbers over time on the entity page (Stalker feature 3; 0095, on the 0261 brief and the 0245 briefer)

Status: **built, switched OFF** (`entity_bands.json` `entities.numbers: false`): values passed (97-98%), joins
failed (90.9% round 1, 94.2% with the code fixes), and the held-out set gave too few series to judge. Not pushed. The
real rows behind the measure are private (`plan/research/v1032/numbers/`).

## Why

0095: the brief pulls an entity's figures from its posts, but only as words inside a result line. The owner wants to
read "what did it score, cost or measure, and when, and who said so" for each recurring measure: a benchmark score, a
price, a speed, a size, a share.

## The shape: a measure is a kind of the brief, no second extractor

- **The measure kind** (`entity_brief.MEASURE_KIND`, added to the entity schema by code only while the switch is on;
  the schema's version is then `NUMBERS_VERSION` 3 (0269's schema is 2), so each briefed entity's posts are read again, once, under the
  same ASKS_A_DAY bound): `measure` (text key: the measure's name, the same in every post, with its period when it
  is a flow, such as quarterly or annual revenue), `value` (number, with its unit as the quote writes it; a fall is
  negative), `amount` (money, with what it is per: "per million input tokens"), `setting` (the version, mode, game or
  test it is of), `as_of` (the period it is for, when stated). Asked by `track_things.ask_posts`, checked by
  `track_things.salvage` like every value. Nothing names an entity or a type. Off: the schema is the one 0261 was
  measured with, unchanged, and nothing is asked again.
- **The checks gained, in track_things (so tracks get them too):**
  - `figures(quote, strict=True)` for typed numbers: a figure followed by a word multiplier ("115,8 млрд") or a letter
    glued to it ("16K") is read only multiplied (the copy had 115.8 USD for "$115.8 billion"). A letter after a space
    may be a unit ("5 m") and is read both ways, as before.
  - a negative number is checked by its digits (a drop of 7% is -7).
  - money may carry a `unit`, what it is per, which must be shown by its quote. `shown_value` writes "3 USD per million
    input tokens".
  - `unit_shown` checks every word of a unit by its first three letters (before: only the first, so "per month" passed
    for "per million tokens").
- **The series** (`entity_brief.series`): one per measure name (`key_text`), unit (`unit_key`: folded, every percent
  spelling is "%"; money: its currency and what it is per) and setting. A different setting is a different measure,
  and the frame rate in one game never joins another game's. Each value has its date (the post's, or the stated
  period), post, quote and setting. A post's same figure counts once. Only series with 2+ values from 2+ posts are
  kept, the most reported first, NUMBERS_SHOWN (12) at most. When two posts give different values for the same date
  (stated period or post day), that is a **dispute**: both are kept and marked (`dispute`, the series' `disputes`),
  never averaged, ready for 0097.
- **The page**: `brief.numbers` (`GET /api/markx/entities/{id}`; each value's post is numbered with the brief's
  cites). Frontend `EntityBrief.tsx` shows "Numbers over time": one small plain table per measure (date, value with
  a superscript cite and the quote on hover, "(disputed)", setting). The page's shape is 5 (0269 made it 4) and its stamp includes the
  switch.

## Measured (2026-11-21, the 11-19 server copy, read only; Haiku asked outside the database, $1.00 for 506 questions)

Each shown value was judged by me against its quote and the post around it. A join is right when the value belongs to
the same measure (and unit) as the rest of its series.

**Round 1** (5 entities: a model, a GPU, a company, an OS, a coin; 256 questions):

| entity kind | series | values | value right | join right | the wrong ones |
|---|---|---|---|---|---|
| coin | 5 | 28 | 27 | 27 | a drop of 7% given as +7; a $/EH/s/day figure in a $/PH/s/day series (a false dispute) |
| company | 4 | 12 | 11 | 10 | "115,8 млрд" read as 115.8 USD; a quarter's revenue in an annual series (2) |
| GPU | 10 | 26 | 26 | 23 | two games' frame rates in one series (2); a modded 96 GB listing joined to the 32 GB card |
| model | 0 | 0 | | | 37 measures, none recurring in its 12 posts |
| OS | 0 | 0 | | | 4 measures |
| **all** | **19** | **66** | **64 (97.0%)** | **60 (90.9%)** | |

Fixes (each a class, in code or the field words, none per entity): the strict multiplier and the sign (track_things),
money's per-unit, the setting in the series key, and the field words (a flow's period in its name, a fall negative,
money's per-unit, the game or test as the setting). **The same answers re-scored with the code fixes** (no new asks):
52 values, 51 right (the sign needs the new words, which the old answers lack), 49 joins right (94.2%: the per-unit
and the quarter/annual cases need the new words).

**Held out** (5 new entities of the same kinds: a model family, a company, an OS, a GPU, a coin; the new field words;
250 questions): only the GPU gave series (5 series, 15 values). Values 15/15, joins 15/15 (Wilson low 79.6%). One
value loses a hedge ("reaching over $2,000" shown as 2,000 USD). The other four had measures but none recurring
across 2+ of their 12 posts.

**Off**: joins are under the bar in round 1, and the held-out set is too small to show the fixes work.

## Left (the next measure)

- **Recall is the main gap.** An entity is read from its 12 newest subject/actor posts (MAX_POSTS), so 6 of 10
  entities had no recurring measure, and names split ("CUDA cores" / "CUDA core count", "memory size" / "memory
  capacity"). Next: read the measure kind over more of an entity's posts (a number-bearing filter, cost measured), and
  join names by a second check (track_same-style, Haiku) rather than exact keys.
- A held-out set with 60+ values across 5+ entities (a frontier model with benchmark posts, a company's quarterly
  results, a coin's price), then switch on if values and joins are both >= 97%.
- Hedges ("over", "about", "up to") are kept only in the quote.
- Disputes (0097) are marked but not yet explained (which source, which method).
- A sparkline: left out, since the tables are short.

## Tests

`insight_core.tests.test_numbers_0272` (7): a series per name, unit and setting with 2+ posts, a post's same figure
counted once; a dispute of one date; money by currency and per-unit, a stated period; units as written; a typed figure
read with its multiplier and sign, money's unit checked; the measure kind's types; the page: the schema gains the
kind (version 3) only when on, measures are never brief lines, the values are cited, the API carries it, and off
shows no numbers. Also run: `test_entity_brief_0261`, `test_markx_kept_pages` (entity shape 5),
`test_track_briefer_0245`, `test_markx_validate`, `test_markx_storage`, `scripts/tests/test_markx_worker.py`.
Frontend: `components/markx/entityBrief.test.tsx` (3), tsc clean.
