# 0220 — Lines: the version line, links between things, and the identity failures that break a thing's line (Stealth v10.24, slice "lines")

Status: **built** on branch `worktree-agent-aecfcaa343109562e` (from origin/main 2dce4786, v10.23). **No migration**
(the edges are `mx_connections` rows, entity to entity, which 0082 allows). Module tests only; the full suite and the
real-data check are the owner's session's. Names below are invented; the real rows, the frozen sets, every label and
every script are in `plan/research/0220-lines/` (private; copied to the main checkout's `plan/research/`).

**On / off:** links between things **on** for `based_on` and `released` (95/95; 89/90 held out), off for the rest;
the version line **off** on the page (90.9% on its second frozen set), though `next_version` now joins posts by it
(better than before on every set); the round-up / other-thing rule **off** (the line gained nothing); one name, several
things: the collision question asked more widely (a question, never applied by itself).

Reads: 0091 (the timeline graph: entity edges), 0131 part 3 (next_version from identity), 0165 (a thing's timeline:
its failures), 0090 F, 0184 (identity facts and splits).

## The bar

A word shown to the reader: point >= 97%, Wilson lower bound >= 90%, on a set frozen (hashed) before reading, blind
labellers as subagents (two, a referee on splits). The whole line (0165's measure): blind judges prefer the new line and
it passes more, on a frozen held-out set. Passing things ship ON; failing ones stay off behind their switch
(`entity_bands.json`).

## 1. The version line

**Spec.** A thing's family's versions on one line on its entity page ("Orbit 2 -> Orbit 2.5 -> Orbit 3"), each with the
month of its first post about it; the page's own version marked, the others linked; a family running two numbered lines
(a maker's "R" and "V" models) shows each. The same line orders `graph.next_version_edges` (the post panel's "X is the
next version after Y"): one path.

**Measured first, as it stood** (0131's rule: a family's versions with a subject post, ordered by their numbers with a
leading letter dropped). Two blind labellers labelled every version entity either line shows (is it one real version of
one product line, which line); a link (two neighbouring stops) is right when both are real versions of one line.

| set | served (next_version as built) | new line | bar |
|---|---|---|---|
| dev: the 21 families of the server's 200 most-voiced things (193 versions labelled) | 86/102 = 84.3% [76.0-90.1] | 90/91 = **98.9% [94.0-99.8]** | tuned here |
| held out 1: 40 families from random feed posts, frozen (112 versions) | 51/61 = 83.6% [72.4-90.8] | 27/28 = 96.4% [82.3-99.4] | too few links |
| **held out 2**: 80 more families, frozen (315 versions; labellers agree on 311) | 149/189 = 78.8% [72.5-84.1] | **80/88 = 90.9% [83.1-95.3]** | **fails: off** |
| held out 2 with the dot rule fixed after reading it (in sample) | | 82/88 = 93.2% [85.9-96.8] | |

(A link is right when both labellers call both stops real versions of one line and the newer stop's labelled number is
above the older's; on dev that order check turned one more link wrong: 90/91 before it.)

**Decision: the version line stays off** (`timeline.version_line` false; built, tested, the page's block and its
component ready). `graph.next_version_edges` does use the new line: the post panel's "X is the next version after Y" was
78.8-84.3% right as built (0131) and is 90.9-98.9% on the same sets now, better on every set, though still under the bar
for a new word. What held out 2 still fails: a product generation read as a version ("Orbit 40 Series -> Orbit 50
Series", 3 links: the labellers call a series several versions), a guess at the next number that many posts name (14),
a junk number on a rocket's line ("V3 -> 42"), two accelerator names the labellers put on different lines; and, fixed
after (in sample, `_on_line`'s dot rule): a well-named "11" folded into a rare "1.01" (read as 1.1), which put an OS's
11 before its 3.

**What failed, each a class (dev):**
- *Two lines read as one.* A letter starts a line of its own ("Orbit R1" and "Orbit V2" are not one line; "Lumen M3"
  and "Lumen H3" are not one version): the old rule dropped the letter. Now `line_key` keeps it; a version whose fields
  lost the letter takes the one its name writes before the number ("Kite K2.6" read as 2.6); a number written without
  its letter joins the only lettered line that has it, unless the unlettered numbers are a line of their own.
- *Another maker's thing filed under the family's name* ("Zentra Orbit 5" under Vantor's Orbit): off, when its stated
  maker is not the one most of the family's posts state (the family's own maker field is its first run's majority and
  was wrong on one dev family).
- *A version few posts name* (a guess at the next number, a slip: "Orbit 7.5", "Orbit 4.7" written for another thing):
  a stop needs 4+ posts naming it and 1+ about it (2 or 3 posts were guesses and slips on dev; the threshold is dev's).
- *A build or date number* in a family numbered 1, 2, 3 ("Orbit 2512", "Orbit 407"): off; a dot left out ("Orbit 46"
  for 4.6) is the dotted version's stop.
- *A one-letter family* (things named "X-33", "X-45" filed under "x"): no line.
- A stop's date is its first post about it under a name on the line by itself (a third of the stray names filed under
  a number were another thing: they never date it, and are not shown).

**The cost of precision (recall):** of the versions the served line showed that both labellers call real, the new line
keeps 107/108 on dev (big families, many posts) but **38/70 (54%) on held out 1 and 104/194 (54%) on held out 2**: smaller products' real versions
named by 1-3 posts are off (an old browser's 3.1, an OS's 11.10), a browser's 141-160 (real, over BUILD_FROM), a
code assistant's "2" whose stated maker is the maker's legal name (word-compared makers miss aliases), a GPU maker's
"A7 / B5"-style models (each its own letter, one stop each). The full list of versions stays on the page below the line.

## 2. Links between things

**Frequency first** (the 11-05 server copy's 5,541 valid ent-v3 answers: 1,164 stated relations; ent-v4.2, the server's
guide, asks the same `relations`; ent-v5 asks none): released 511, beats 148, partnered_with 106, based_on 95,
announced 73, part_of 71, leads 68, acquired 25, joined 22, left 22, invested_in 14, hired 5, sued 4. Each side read as
one of the same answer's own mentions: 494/511 released, every other relation 98-100%.

**Measured** (frozen samples, `rel_frozen.sha`, `rel2_frozen.sha`; two blind labellers each saw the post and the two
names and chose the relation themselves; a referee on the 10 splits):

| relation | as stated | bar | |
|---|---|---|---|
| based_on (a fine-tune, quantisation, fork of b) | 95/95 = 100% [96.1-100] | 97 / 90 | **on** |
| released (a makes b) | 87/90 = 96.7% [90.7-98.9]: a host, a quantiser or an OEM "released" another's model | | |
| released, the thing's own mention naming the same maker | dev 75 kept of the 90, 0 wrong; **held out 90 more: 89/90 = 98.9% [94.0-99.8]** | 97 / 90 | **on** |
| acquired | 25/25 = 100% [86.7-100]: too few rows for the bound | | off |
| part_of | 63/70 = 90.0% [80.8-95.1]: plugins (built on, not part of), spin-offs, divested units | | off |
| partnered_with | 86/106 = 81.1% [72.6-87.4]: a customer using a vendor, two things named together | | off |

**Built** (`markx/graph.py`, section 4; graph owns edges): `stated` reads the current entities answers of a set of
posts, keeps the relations switched on (`entity_bands.json relations`), reads each side as one of that answer's
mentions (pins read) and its entity's root, and for `released` asks `corroborated`. `sync_relations` makes the edges
exactly what the posts state: a post joins an edge's evidence (`{posts, since, dates}`; the edge valid from its first
post's date), leaves the evidence of one it no longer states; an edge with no post left closes (kept, never deleted). In
the decision run's `connections` stage (`graph.stage`): the posts whose answer is new since the last run (and the
evidence posts of edges whose side merged since), then a resumable backfill (`mx_settings graph_relations`, 500 posts a
chunk, until the stage's deadline; a relation switched on reads everything again). The entity page's **Links**
(`entity_views._relations`): "Based on", "Built on it", "Released", "Released by", one row a relation and direction, the
other things linked with their post counts.

## 3. The line's identity failures

**(c) digests and (b) the subject-role error: built, off.** `timeline.named_only`: a post whose role says it is about
the thing but whose reading is a round-up (kind `roundup`, event type `digest`), or whose main event (object, actors,
headline) never names the thing by one of its names, only names it: never its birth, a release, its first outside
mention or a month's lead, never counted in a story's share. Measured with 0165's method on a set frozen before any page
was read (`line_frozen.sha`: 24 things that random feed posts of the last 30 days are about, never in 0165's sets; 20
with a timeline; the code hashed before reading): three blind judges, served against new in random order:

| | served (v10.23) | with the rule | judges prefer |
|---|---|---|---|
| pass (the line tells its history, at most one line off-topic) | 17/20 = 85% [64-95] | 17/20 = 85% [64-95] | new 5, served 6, same 9 |

No gain: `timeline.by_reading` stays **off**. 27 posts on these 20 lines lost their "about" role; the judges' remaining
failures are a product's line full of a GPU maker's holiday posts (one name, several products), a task tracker's
borrowed posts, and a line that lost a true post (a release headline naming the product by its maker's other name).
This random set's served line already passes 85% (0165's sets: 60%): the failures 0165 listed are concentrated in big,
old, bare names.

**(a) one name, several things: built as a question.** `identity.collisions` asks the collision question (`collide`,
0184's: v1 50/53 splits right, v2 54/54) also of a run's touched names whose posts span a year or more
(`COLLIDE_SPAN_DAYS`), its sample one mention a year, the oldest first (`collide_sample`): an archive post about
another thing of the name is in front of the judge. Two runs splitting queue a `split` for the owner, as every
collision does (never applied by itself: `facts.split` is off). On the 11-05 copy's incremental run: 4 more questions.
Not measured beyond its tests: how many of the server's names it asks, and how many splits it finds.

## Switches (`entity_bands.json`)

| switch | value | why |
|---|---|---|
| `timeline.version_line` | false | held out 2: 80/88 = 90.9% |
| `relations.on.based_on` / `released` | true | 95/95; 89/90 held out |
| `relations.on.acquired` / `part_of` / `partnered_with` | false | under the bar or too few rows |
| `timeline.by_reading` | false | the line gained nothing |

## Resources (the 11-05 server copy, prep_mxreal migrated to 0153; `checks/resources.py`, each job its own process)

| job | base (2dce4786) | head | |
|---|---|---|---|
| decide_full | 151.7 MB, 42.4 s (CPU 23.7) | 157.8 MB, 45.9 s (CPU 26.1) | the relations backfill: 5.5k answers once; graph 11.4 -> 12.3 s |
| decide (incremental) | 104.7 MB, 15.7 s | 102.9 MB, 16.3 s | graph 10.6 -> 11.1 s, entities 0.8 -> 0.9 s |
| stories / discover | 209.2 / 70.0 MB | 209.8 / 71.1 MB | untouched |

The entity page (30 pages: the 20 most-named things and the 10 biggest families, built once each): 3.04 s base, 3.03 s
head, peak 56.5 / 57.0 MB; the version line 6 ms at most a page, the relations 1 ms. Edges written on the copy: 88
based_on, 303 released. Not measured at the server's size: `version_counts` counts every version's mentions each run (one
row a version back; the server has several times the copy's versions), and the backfill's first runs read every answer
stating a relation (chunked, under the stage's deadline).

## Tests

`test_markx_timeline` (+13: `VersionLineRules` 6 pure, the page's version line (off, and on), `ThingLinks`, the round-up
and other thing's posts, the span question and its sample, the reading rule), `test_markx_graph` (next_version on the line; its
fixtures name each version 4+ times), the identity modules (`test_markx_entities`, `_entity_facts`, `_entity_fixes`,
`_entity_guards`: 95, unchanged), frontend `versionLine.test.tsx` (3), `timeline.test.tsx`, `entities.test.tsx`.

## For the owner

- **Renames stay questions** (0165): nothing here changes them.
- **ent-v5 asks no relations.** Once it is the entities guide, no new `based_on` or `released` edge comes from it; the
  relations would need ent-v5 to ask them, or a Haiku question of their own (measured the same way).
- **acquired** passed every row (25/25) but needs ~36 for the bound: the server's ent-v4.2 answers hold many more, not
  readable by GET.
- **The version line is off** (90.9% on held out 2). To pass: a product generation ("40 Series") is not a version (the
  labellers' reading; the parser could mark a series), and a guess at the next number needs more than many posts (the
  maker's own post about it, or a stop answer saying launch). Each needs a new frozen set.
- **Its recall** on smaller products (54% of real versions kept on both held-out sets): lowering the 4-post threshold
  brings the guesses back (dev: 9 wrong links); comparing makers through identity's aliases would keep a maker's
  legal-name versions (one held-out case); a browser's real 141-160 are cut by BUILD_FROM.
- **(a)'s cost** at the server's size is unknown (names spanning a year: many old products are asked once, "one
  thing" settles after one run).
