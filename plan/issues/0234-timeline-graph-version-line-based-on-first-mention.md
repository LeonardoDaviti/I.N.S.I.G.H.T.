# 0234 — The Timeline Graph's last pieces: the version line's classes, based_on from new posts, the first outside mention (Stealth v10.25, slice I)

Backlog items #20, #21, #5 of 0225. Reads: 0220 (the version line, links between things), 0223 + its section 0224
(relations from ent-v5's fields), 0165 (a thing's timeline). No migration. Module tests only. Private rows, the frozen
set, the runs, the labels and every script: `plan/research/v1025/i/` (gitignored: real posts and names).

**Data this slice could not have (2026-11-19).** The server-shaped template (`v1024srv_s1`) is prep_scale's: its Mark X
rows are synthetic (scale.py's invented names and mentions), so it measures resources only; no local copy holds
ent-v5 readings or the server's families; then the scratch Postgres was emptied (every prepared copy gone, not by this
slice) and the owner stopped every request to the server. So: **the version line is not measured on a fresh set**
(only a dev check on 0220's cached 11-17 pages), **#5 is not measured**, **no resources were measured**. #21 was measured
(Haiku through the claude CLI on posts rendered from the 11-05 mxreal copy before the wipe).

## #20 The version line (timeline.py section "0220 / 0234"; graph.next_version_edges reads the same line)

What was wrong (0220's held-out sets and the owner's review of 2026-11-17) and what changed, each a class:

| problem | change |
|---|---|
| rumoured versions shown as real (one account's 62 posts; a tier the maker never released; a guessed next number) | a stop is real only when its maker announced it: a post about it whose reading's origin is the maker and whose type is never `leak_rumour`; or, when the maker never speaks for itself here (or not yet when the version came), `RELEASE_VOICES` = 2 independent voices report its release (release-typed readings, never a leak; one voice a source however many posts) |
| dates from a sighting or a wrong archive date | a stop is dated by its maker's first announcement, else its first release report; never by a post that only names it (an archive date wrong at the source is slice C's: #2) |
| year-named versions ordered by number (95, 98 after 10) | a line is ordered by its stops' release dates (ties by number); a four-digit year (1980-2039) is a name, never a build number |
| series read as versions ("RTX 40 Series") | `name_shape`: a series word (series, family, lineup, generation...) makes no version |
| junk entities inside stops ("X 4 in Copilot", "X vs Y") | `name_shape`: a variant with a function word or more than two words is a phrase, never a stop's member |
| no product lines inside a family (Max/Plus/Flash/Coder/VL/Omni) | a version's variant, its stage words dropped (`line_word`: preview, instruct, thinking, exp...), is a line of its own; variant versions are no longer left out of the line (nor of next_version) |
| tiers need a generation grid | `grid(lines)`: two product lines or more sharing two numbers or more give {tiers, rows: generation -> {tier: stop}} in release order, in the page's `version_line` (with `words`, each stop's `by`) |
| code names and nicknames not aliases | a line word one number ever has, that the plain line also has, is that number's code name ("X 10.12 Sierra" is 10.12's stop); a nickname the maker never used ("Sonnet 3.6") is no stop once the maker speaks; **not done**: a code name written with no number ("macOS Sierra") joining its number, a nickname shown as its version's other name |
| recall 54% | the 4-post threshold dropped (realness decides now); a maker-announced version with one post is a stop |

**Measured: not on a fresh set** (see above). Dev check only (`lines/dev_cached.py`, in sample: 0220's three sets were
labelled for 0220's rules; the labels have no release dates; the pages give an approximation of the database rule: the
maker's posts are the page timeline's `release` items, a voice is a source reporting it, leaks are not told apart):

| set (0220's labels, both labellers) | 0220's line (as served by next_version) | 0234's line | 0234's recall of real versions |
|---|---|---|---|
| dev (21 families) | 90/91 | 64/64 links right | 109/149 = 73% |
| held out 1 (40 families) | 27/28 | 19/19 | 28/87 = 32% |
| held out 2 (80 families) | 80/88 | 60/62 (2 split, 0 wrong) | 71/215 = 33% |

`RELEASE_VOICES` = 1 instead: held 2 118/130 (8 wrong): 2 kept. Recall's losses (held 2): one voice only 84, the maker
speaks and never announced it 20, grouped off 34. Dates the pages gave that a release-date order exposes (the shape a
fresh set must score): a maker post dated years early (an archive date: #2's class, e.g. a tier "5.5" dated 2023-03-31,
a "V3" dated 2023-11), and old versions (an OS's 95/98/3.1) dated by 2026 posts that only mention them: the database rule
reads only release-typed posts, so such versions are off there rather than misdated (unverified).

**Decision: `timeline.version_line` stays off.** `graph.next_version_edges` uses the new line (one path): the post
panel's "X is the next version after Y" now needs both stops announced (or reported by 2+ voices) and follows release
order; on the dev check it has fewer links and none wrong. That changes served edges without a fresh measure: the
integrator's call (risk listed in the report).

**Slice E's fix changes these numbers**: a family's members and name decide which versions share a line (the other
makers' fine-tunes under a family, #3, are mostly cut by the maker rule already; Claude's tiers are separate families on
the server today, so no grid appears for them until E puts them under one family).

## #21 based_on from new posts (graph.py section "0234"; kind `derive`, guide `derive-v1`)

**Wrong:** 0224's derived based_on (the reading's subject based_on each `predecessor`) was 20/33 = 60.6%: a predecessor is
mostly what the subject replaces or is compared with, and half the misses paired one window's subject with another's
predecessor.

**Built** (following the chain kind exactly: schema, guide file, validate, consumer, hold word, a background planner,
an after-answer hook, worker settings):
- `graph.derived`: a based_on pair only within one window (the mentions' `call`).
- Kind `derive` (`schemas.DERIVE_SCHEMA`: reason, relation in derived / replaces / compared / other), guide
  `guides/derive-v1.md`, subject `entity_entity` (a = the subject's root, b = the predecessor's).
- `graph.plan_derive` (jobs process, `tasks.BACKGROUND_PLANNED`): the ent-v5 calls since its mark (`mx_settings
  derive_planned`) with a model/product/software predecessor, each pair of roots asked once, the question
  (`derive_question`) the reading's own window cut around both names (`_excerpt`, 3,500 characters at most).
- `derive_after_answer`: open again until `runs` valid answers; `derive_verdicts`: the newest task of a pair (sides
  read through their roots, a redirect followed); `_derived_stated` keeps a based_on pair only when its verdict is
  `derived` (every run). `_relation_scope` reads again the posts naming a predecessor whose pair was answered since.
- Switches (`entity_bands.json relations`): `derive.ask` (false), `derive.runs` (3), `derived.based_on` (false).

**Worker changes** (scripts/markx-worker, made here; the worker runs from the main checkout, so they reach it at merge):
`DEFAULT_KINDS` + `derive` right after `chain`; `PER_CALL` `derive=10`; `EFFORT` `derive=low`. Test
`TestDerive0234` (the settings, the server's rules on an answer). Nothing else: the prompt cache stays the default
(`off`).

**Measured** (Haiku as the worker asks it: its system prompt, prompt, 10 a call, effort low, its parser, the server's
`validate.check`; `based/run_derive.py`). The set (`based/pick.py`, frozen and hashed before the first call,
`frozen.sha`): 1,500 posts of the 11-05 mxreal copy with 0224's base-cue words, none in 0212's, 0220's, 0223's or
0224's files; read by ent-v5 (3,777/3,884 windows valid, $3.49); 32 posts name a model/product/software predecessor,
44 (subject, predecessor) pairs in one window (`items.json`, hashed with the guide and graph.py before any derive answer:
`items.sha`). Two blind labellers (haiku subagents, 0224's guide verbatim, 0224's view of the post), 8 decoys, a
referee on the 2 splits.

| verdict | `derived` | right | Wilson 95% | recall of the 25 labelled based_on | bar 97 / 90 |
|---|---|---|---|---|---|
| one run | 16 | 15 (93.8%) | 71.7-98.9 | 15 | fails |
| both of 2 runs | 14 | 14 (100%) | 78.5-100 | 14 | fails (n) |
| all of 3 runs (as built, `runs` 3) | 14 | 14 (100%) | 78.5-100 | 14 | fails (n) |
| majority of 3 | 16 | 16 (100%) | 80.6-100 | 16 | fails (n) |

Decoys: 1 of 8 labelled based_on (a fork credited to its author's project). The one wrong (a single run): a diffusion
model "derived" from its base family in a window whose labellers' view never named the base (the labellers' excerpt
is 0224's cut, the question's is `_excerpt`'s: a view difference, not checked further). Cost: 3 runs $0.025 for 44
pairs (~$0.0006 a pair a run); at the server's ~1,000 posts a day, ~0.6-2% with a predecessor: about one call a day a run.

**Decision: off** (`derived.based_on` false, `derive.ask` false). Every settled `derived` was right, but 44 pairs give
at most 16 `derived`: the Wilson bound needs 36+ right with none wrong. More pairs need more base-cue posts read by
ent-v5 (the copy's pool left 2,204 after this set; ~$5), on a real copy: the scratch Postgres was emptied before a
second set could be rendered. Switching `derive.ask` on (questions only, no edge) would collect the server's own pairs
for that measure at ~3 calls a day: the owner's call.

## #5 The first outside mention is about the thing (timeline._first_about)

A post the extractor marks as about the thing but whose main subject is another thing (Qwen's: a method shown on
another maker's model) was its first outside mention. Now the first outside mention is the first outside post that
links back to its posts, or whose role is `subject` (an actor is in it, not what it is about) and whose reading says
so (`about_by_reading`: no round-up, its main event names the thing; a post with no reading keeps its role). The
readings are read 50 posts at a time, oldest first, until one is found (no switch: `by_reading`, 0220's whole-line rule,
stays off). **Not measured** (no database with the server's readings; no server requests). Test:
`Timeline.test_the_first_outside_mention_is_about_the_thing`.

## Tests

`test_markx_timeline` (VersionLineRules rewritten: release order and year names, rumours and nicknames, series and
phrases, product lines with a code name and the tier grid; the page's line at its maker's date with a leak off; #5;
DerivedRelations + the question and verdict; DerivedLinks: based_on waits for its check, `replaces` no edge, `derived`
the edge, a predecessor in another window no candidate), `test_markx_graph` (next_version fixtures announced by their
maker), `test_markx_validate` (the kind list), `_consumers`, `_holds`, `_chains`, `_unchanged`, `_reading5`: 190 OK.
Worker: `cd scripts/tests && python -m unittest test_markx_worker test_markx_worker_embed`: 118 OK (TestDerive0234 among them).

## Resources

Not measured (the scratch Postgres was emptied; nothing rebuilt, the integrator's instruction). What could cost:
`version_counts` now joins each subject/actor mention to its preferred reading (one index lookup a row) and returns the
reporting sources per version (an array); `next_version_edges` reads every version's counts each decision run, as
before. `plan_derive` reads the ent-v5 calls since its mark with a predecessor (a few a day on the server), their
mentions and their task inputs (one window each).
