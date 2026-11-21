# 0261 — An entity's brief: what it is, how it works, is it good (v10.31; 0156 the knowledge page + 0245 the briefer)

Status: **built, switched off** (`entity_bands.json` `entities.brief: false`): measured under the bar (89.6% of
lines supported by their quotes, bar 95%). Migration **0167**. Not pushed. Real rows behind the measure are private
(`plan/research/v1031/entity-brief/`).

## Why

The owner opened an experimental feature's entity page and got a list of stories and posts. They want to read, on
the page, what it is, how it works (how to turn it on), and whether it is good (measured results, who measured them,
caveats), every line cited, updated as posts join.

## The shape chosen: the entity is the briefer's subject (no second briefer)

An entity is briefed **as a track whose subject is the entity** (`markx/entity_brief.py`):

- its "track" id is the entity's root id; its description is the entity's own words only (name, type, maker, other
  names: `entity_brief.subject`), its excludes "anything not about <name> itself";
- its schema is one general schema for every entity, written by code (`entity_brief.SCHEMA`): `what_it_is`
  (definition, stage, maker), `how_it_works` (how, detail), and the practice kind code always adds (what, result,
  evidence). No entity, type or field of one is named anywhere;
- everything else is the track briefer's, unchanged: the questions (`track_things.ask_posts`, now the one path a
  track's posts and an entity's posts are asked by: windows, links, the maker's linked pages), the quote checks
  (`track_things.salvage`, the worker too), reports, key joins, and "what changed" (digest-v3; `track_brief._ask`,
  `track_brief.plan_subject`: one period, every row so far, asked again only when the rows change, at most every 12 h).

**Stored where track things are** (mx_track_schemas / mx_track_things / mx_track_thing_reports / mx_track_brief_asks,
`track_id` = the entity's root). Migration 0167 adds `mx_track_schemas.subject` ('track' | 'entity') and allows
`by = 'code'`. Why not new tables: the rows are the same rows (a thing, its reports with quotes, its joins, the asks);
a second set of tables would be a parallel path with the same code. Why not a column on every table: the schema row
already names whose rows they are; every reader of a track's rows filters by `track_id`, and the track planners walk
`tracks.described` (folders), so an entity's rows never show in a track. An entity merged later keeps its rows under
the root it was briefed as (keep everything); it is briefed again under its new root.

## Which posts, which entities, what it costs

- Posts: those whose current reading names the entity (through merges and pins) as **subject or actor**, newest first,
  12 at most. A post that only mentions it is not read for it; a story's other members are not either (they are about
  the story).
- Entities: the 50 most opened entity pages of the last 14 days (`kept_pages.most_opened`) with **3+** such posts.
- Bound: 150 things questions a day across entities (`ASKS_A_DAY`), one digest an entity per 12 h at most. Measured
  cost: 107 questions for 5 entities (46 posts) = $0.086, under 2 cents an entity.

## The page

`GET /api/markx/entities/{id}` gains `brief` {what, how, results, points, as_of, posts}: each line `{text, cites: [{n,
post, quote, quotes}], sources}`, results also `who` (the sources of the posts that reported it: from the posts,
never from Haiku); `posts` numbers the cited posts for the superscripts. The kept page's shape is 3 and its inputs
include the brief's reports and points (`entity_brief.stamp`), so a new report rebuilds the page. Frontend
`components/markx/EntityBrief.tsx`: three plain lists (What it is / How it works / Results), superscript numbers to the
posts, the quote and the post's title on hover; nothing while off or empty. Points are in the API, not shown yet.

## Measured (2026-11-21, the 11-19 server copy, read only; Haiku asked outside the database)

Five entities of five kinds: an experimental tool feature, a phone OS, a language model (Russian-language posts), a
research org, a humanoid robot. The brief served (the capped sections, 77 lines), each line judged by me against its
cited quotes and post:

| entity kind | lines | supported | adds words its quotes lack | wrong | duplicates / low use |
|---|---|---|---|---|---|
| tool feature | 17 | 17 | 0 | 0 | 2 dup, 2 low |
| phone OS | 17 | 12 | 5 | 0 | 0 |
| model | 11 | 8 | 2 | 1 | 0 |
| research org | 17 | 17 | 0 | 0 | 3 low |
| robot | 15 | 15 | 0 | 0 | 0 |
| **all** | **77** | **69 (89.6%)** | **7** | **1** | 5 dup, 5 low |

Supported < 95%: **off**. The causes, each a class:

1. **Words beyond the quote (7).** A practice's `what` or `result` names a device, a time span or the option meant,
   taken from the post around the quote; the checks prove the quote is in the post, not that the value is read in it.
   Fix: a value-in-its-quote check for text (its content words in the quote, or a second blind check), in
   track_things, so tracks gain it too.
2. **The other subject of a comparison (1).** "Both computed it correctly" was about the two models tested as the
   entity's replacements. Fix: the entity guide line "the subject of the result must be the entity itself", measured.
3. **Senses merged in the cluster (the tool feature).** The entity merges the tool's feature with a general pattern of
   the same name and another product's mode: ~10 of its 17 lines are true but about the other senses. An identity fix
   (0184 senses), not the briefer's.
4. **Duplicates (2)** where two reports of one thing were worded differently (key text joins only exact keys).

Points (digest-v3) were not measured this round.

## Tests

`insight_core.tests.test_entity_brief_0261` (2): the switch, the 3-post rule, the general schema written by code,
questions asked once a version and never for a mention; the brief's lines, cites numbered, `who`, a dropped value's
line kept, the points asked once and mapped to the cites, the entity page carrying it. Also run:
`test_track_briefer_0245`, `test_markx_kept_pages` (entity shape 3 recorded), `test_markx_storage`. Frontend:
`components/markx/entityBrief.test.tsx` (2), tsc clean.

## Left

- The value-in-its-quote check (cause 1) and the subject line (cause 2), then a fresh held-out set (other entities)
  and switch on at >= 95%.
- Measure the points; show them (one line above the three lists) once measured.
- An entity's brief when its cluster has senses (0184): brief per sense.
- Caveats as their own line kind (now they are results' text when the post states them).
