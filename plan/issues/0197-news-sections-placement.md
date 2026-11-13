# 0197: New News rows placed into the existing sections (Stealth v10.17)

Status: **built** (branch `v1017-sections-place` from `v1016`). Not merged, not pushed, not deployed. Migration **0134**.

## The problem

Owner, on the server (v10.16): the Mark X News page shows "New since · 13": a model release that belongs in the
existing "Model releases" section, an outage that belongs with the incidents, and others, unsectioned. 0174 asks the
whole sectioning again only when new and removed rows are 20% or more of the last asked rows, at most every 30 minutes;
rows added in between go under "New since". 13 of about 373 rows is 3.5%: such rows can stay unsectioned for many hours
(a 373-row page needs about 75 changes before the next full sectioning).

## Built

1. **The question** (kind `news_place`, guide `news-place-v1`, one task per call, subject `news_run`, `a` = the News run,
   priority -1). Input: the newest sectioning's sections keyed `s1..sM` in their order, each with its title and its 3
   most important current headlines (`e.g. "..."; "..."`), then only the rows it does not cover, keyed `r1..rK` in News'
   order, each shown exactly as the sections question shows a row (headline, entities with types, type of happening,
   voices). Answer: `{"placements": [{"row_id": "r1", "section": "s2"}, ...]}`, a section key or `"new"` (no section
   fits). The ids and titles stay in `mx_news_place_asks` in key order, so the answer is read back by key.
2. **The checks** (validate.py `_news_place`): every new row of the question exactly once (a missing row, a row twice,
   an unknown row refused, naming them); a section is one the question shows, or "new" (schema and check).
3. **When** (`news_sections.place`, the lease's planner `tasks.PLANNERS["news_place"]`; `place_due`): when the newest
   sectioning (with its placements) leaves current rows uncovered, and no full sectioning is waiting or due by its
   change rule (20% changed, or never answered: the full one supersedes placements, so no call is spent first); at
   most once every 10 minutes (`PLACE_EVERY`); never while one waits (open or leased). The cheap checks come first: a
   waiting placement or one asked within 10 minutes reads no row. The full sectioning's rules are unchanged (20% /
   30 minutes).
4. **The answer** (`after_place`, from `tasks.record`): one `mx_news_placements` row per placed row (keep everything),
   tied to the sectioning it placed into (`base_call`), with its section's title, or NULL for "new".
5. **Read where the sectioning is read** (`last_sectioning`, no parallel path): the newest sectioning plus the
   placements into it; a placed row joins its section after the section's own rows, so the page (`view`, unchanged)
   groups it there in News' order, and the next full sectioning question shows it as `last: sN`. A row answered "new"
   stays under "New since" and is not asked again until a full sectioning covers it. A newer full sectioning has
   another call, so the older placements no longer count; rows it does not cover (added while it waited) are placed
   against it.
6. The worker: `news_place` in DEFAULT_KINDS right after `news_sections` (its planner sees a full sectioning planned in
   the same cycle), `news_place=1` in PER_CALL; prompt cache and effort left at the defaults (calls are 10+ minutes
   apart, so a cache would never be read). A worker newer than its server skips the unknown kind (v10.14's
   `kind-unknown`, tested).

No frontend change: the page's `sections.groups` now hold the placed rows, `sections.new` only the uncovered and the
"new" ones.

## Measured

A replay on a copy of the 2026-11-05 server database with Mark X (`prep_mxreal`, cloned, migrated to 0134; dropped
after): the newest News run's rows arrive at their `first_at`, the page holds the last 30 days in News' order, the
worker runs every 5 minutes and an answer comes back on the next cycle. The full sectioning (0174's rules, unchanged)
and the placement (this issue) are planned by the module's own functions (`due`, `place_due`, `unplaced`, `question`,
`place_question`, `sections_of`, `placements_of`), every question is asked of Haiku through the worker's own call
path (`claude -p`, the guide and schema as the worker sends them) and every answer checked by validate.py.

| replay | rows arriving | full sectionings | minutes in "New since" before (median / p90 / max) | after (median / p90 / max) | rows waiting on average, before → after |
|---|---|---|---|---|---|
| A: 6 days, about 150 rows at the start | 30 (5 a day) | 2 (the first, and one after 4.8 days) | 4,260 / 7,240 / 7,450 | 5 / 5 / 7,395 (the one row answered "new") | 14.6 → 0.9 |
| B: 10 days, about 75 rows at the start | 82 (8 a day) | 5 | 1,145 / 3,425 / 4,595 (6 rows still unsectioned at the end) | 5 / 5 / 10 | 8.5 → 0.03 |

Before: a row sat unsectioned for 19 to 71 hours (median). After: one worker cycle (the 5 minutes are the replay's
cycle; a placement is asked on the cycle after the row reaches the page and answered within it). One row of 112 was
answered "new" (a metrology decision on a page about one field, fitting no section): right, and it waits for the next
full sectioning, as designed.

- **Accuracy** (blind read of 31 placements, 29 questions picked at random from both replays: a separate reader placed
  each row from the same question text without seeing Haiku's answer): 29 of 31 the same section (94%); 1 more in a
  section the reader named as also right (a model's compressed weights placed with developer tools, not with model
  releases); 1 wrong (a company's write-up of models used to design physical products placed with hardware and
  devices; the reader: research results). 30 of 31 acceptable (97%); bar 90%.
- **Validity**: 97 of 97 placement answers valid on the first try (no refused answer); 7 of 7 full sectionings valid.
- **Calls a day**: placement 4.5 (A) and 7.0 (B), about one per arriving row when rows arrive apart (rows arriving
  within 10 minutes share a question); at most 144 a day by `PLACE_EVERY`. A question is about 2,400 characters
  (2,300 input tokens with the guide, 200-250 output), 2.5-3 s, about $0.0005 (Claude Code's reported cost): about
  $0.002-0.003 a day at these rates. A full sectioning on these pages was $0.004-0.005; the server's page (373 rows)
  more. The full sectionings asked are the same with and without placement (its rule reads only the asked rows).
- **The planner in the API** (the lease's): on the copy, 106 ms when it builds and adds a question (sections'
  examples and the new rows' headlines, entities and types); under 1 ms when a placement waits or one was asked within
  10 minutes (two small reads, no row loaded); `last_sectioning` with its placements 1 ms. Nothing is kept in memory.
- On the server's page now (13 rows under "New since" of about 373): after the deploy, the first lease of
  `news_place` asks one question for those 13 rows (3.5%, so no full sectioning is due), and the page shows them in
  their sections one worker cycle later.

## Verify after deploy

1. Migration 0134 applied; a worker cycle with the default kinds leases `news_place` (it needs a sectioning and rows it
   does not cover).
2. `GET /api/markx/news?all=1`: `sections.new` holds only rows added within the last ~10 minutes plus the worker's
   cycle, and rows answered "new"; the rows of the owner's report sit in their sections.
3. `GET /api/markx/status`: `news_place` answered, no failed tasks; read the placements yourself (the row in the
   section a reader would look in) before calling it done.

## Not done

- A row answered "new" waits for the next full sectioning; "new" answers do not count toward the 20% rule.
- No owner labels on placements.
