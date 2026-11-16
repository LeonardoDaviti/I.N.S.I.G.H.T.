# 0165 — A thing's timeline: earlier names, outside mentions, the launch (built: v10.14 and v10.23, see the end)

Owner 2026-11-11, on a launch read in INSIGHT: "how the whole story and timeline looks like for it?" INSIGHT had
every post needed and could show none of the timeline. The real case (names, posts, dates) is in
`plan/research/0165-case.md`; the names below are invented.

## The case, as seen (read-only API, 2026-11-11)

A maker ("Vantor") launches an open-source tool "Vantor Snap" on its developer blog, the same hour as two sibling
launches at a conference, and its news site's round-up names it an hour later. The tool is not new: six months
earlier the same blog introduced it as an experimental part of Vantor's serving product, "Vantor Forge Snap".

What INSIGHT holds, from the posts already stored:

| When | Source | What | In INSIGHT's view |
|---|---|---|---|
| 2 years before | maker's dev blog | the open tool it builds on | not linked |
| −165 days | maker's dev blog | **birth**: "Forge Snap", experimental | filed under "Forge" (the parent product) |
| −22 days | an inference engine's blog (independent) | "what comes next: restore warm workers with Forge Snap" | filed under "Forge" |
| −19 days | maker's news site | a customer uses Forge Snap | filed under "Forge" |
| day 0 | maker's dev blog | **launch**: "Vantor Snap", renamed, open source | the entity's page: 2 posts |
| day 0 +1 h | maker's news site | conference round-up naming it | the entity's page |

What the owner sees: the launch post has 0 stories, 0 connections, an empty "before"; the entity page lists two
same-day posts from the maker. **No way to see the timeline in INSIGHT today.** The entity's stored code address is the
same repository the birth post links (`github.com/<maker-org>/snap`), so the join was one rule away.

## The four gaps (classes, not this case)

1. **A rename is not joined to the earlier name.** "Forge Snap" → "Snap" is one thing; nothing proposes it.
2. **A name inside a bigger product is swallowed by it.** "Forge Snap" is linked to "Forge" (a component's mentions
   read as its parent's), so the component has no entity, no page, no history.
3. **No story without independent voices** — correct (two maker posts are not a story); but the one independent voice
   is 3 weeks earlier, outside any story window.
4. **An entity with no story has no timeline.** The page lists loose posts by role, newest first; the earlier name, the
   outside mentions, the birth and the launch are not shown as one line.

## What to build

### A. Components get their own entity (identity)
A mention whose span is `<parent product> <name>` where `<name>` is a component or feature (the guide's reading says
so, or the post's subject is the component, not the parent) is linked to the component's own entity, with
`parent` = the product (the `thing` level the family logic already has). The parent's page lists its components; a
component's posts count on its own page and, read-only, under the parent's "components" block. Rule from the reading,
never a word list; measured on the lab's mentions of the 20 biggest products before the switch (how many mentions
move, sample 40 read by me).

### B. Renames proposed by shared evidence (identity → queue)
Two entities of the same maker, one older (its last post before the other's first, or overlapping by < 7 days), become
a **rename candidate** when one of:
- the same own address (0138 `mx_entity_addresses`: code repository, release page, docs page), normalized;
- one name contains the other's distinctive word and a post says so ("formerly", "renamed", "now called",
  "previously known as", or the guide's reading marks the relation);
- the new post's text names the old name (the launch post names its prototype).

A candidate is a **question** (`rename`, a new queue kind): Haiku judges with both entities' first and last posts;
`same thing, renamed` merges as a redirect with `kind = 'rename'` (the old name stays an alias, shown as "earlier
name"); `different` keeps them apart for good. Automatic only after measurement (a band like 0130's), never at build.
The version guard holds (a version bump is not a rename). Owner's answers win, as in 0164.

### C. The timeline on the entity page (view)
Every entity page gets a **Timeline** block above the loose posts when it has ≥ 2 dated events, built read-only
from what is stored:
- **first seen** (the oldest post naming it or any earlier name),
- **earlier names** (rename merges) with their first and last posts,
- **releases** (posts whose role is subject, from the maker or its own address; versions for a family),
- **outside mentions**: posts by sources not the maker's, grouped by month, the first one marked,
- **stories** it is in (Mark X and IX), at their dates,
- **later developments** (0163 rows) and **back in the news** events.

Each line: date, source, title, why it is on the line (birth / rename / release / outside / story / later). Collapsed to
the 8 most important by default (birth, renames, releases, first outside, stories), "all" opens the rest.

### D. The post page: "before" from the entity's timeline
A post whose subject has a timeline shows its subject's previous events (up to 3: birth, last release, first outside
mention) in the post page's "before" section, which is empty for a launch today.

## Measure (before and after, on the lab / a fresh dump)
- **Renames:** candidates found, Haiku `same thing, renamed` precision on 40 read by me, and the ones missed (sample
  the maker's products with an address shared by two entities).
- **Components:** mentions moved, 40 read; the parent's page still right.
- **Timelines:** for the 30 biggest products of the last 30 days and 20 random ones: does the timeline tell the
  thing's history (my read, pass/fail per entity, the failures listed with exact rows, per [[report-breakage-format]]).
- Check cases in `plan/research/lab/cases.json`: this case (the launch's entity has its earlier name, its timeline
  starts at the birth post and holds the independent mention), plus two renames and one non-rename (a successor
  product with a new address).

## Not in scope
Fetching anything new for the timeline (only stored posts); predictions; a timeline for persons (later, with 0091).

## Slices (separate files)
- A + B: `markx/identity.py`, `markx/rename.py` (new), the queue kind, a migration (`mx_entity_redirects.kind`).
- C + D: `markx/timeline.py` (new), `entity_views.py`, the post page API, `MarkXEntity.tsx` / the post page.

## Second case for Stalker: one model's events, filed as separate stories (owner 2026-11-14)

Owner, on a practitioner's architecture breakdown of an open model: "we already have this model's news, so such a post
would be an addition?" It is, and INSIGHT filed it right: a member of the weights-release story, read as commentary
with its numbers. But the model's history is split across stories that nothing presents as one line. The real rows
are in `plan/research/0165-case.md` (section 2); the names below are invented.

| When | What | In INSIGHT's view |
|---|---|---|
| day 0 | a lab launches "Orbit 2 Small"; an evaluator's results; a forum thread | story A (launch + benchmarks) |
| day +1 | the daily digest: parameters, training time, tokens | story A |
| day +3 | an arena ranking | its own post |
| day +7 | weights released under an open license; an inference engine's day-0 support; a model router | story B (weights) |
| day +8 | a practitioner's breakdown of its architecture against a rival's (numbers, what is missing) | story B, a plain member |

**The gap for Stalker (a class, not this case):** two stories about one thing at different times are each correct,
and the timeline should still show them as one line: launch → benchmarks → ranking → weights → analysis. The breakdown
should hang on that line as analysis of the thing, not only as a member of one event. The entity ("Orbit 2 Small",
model, 27 posts and 16 voices on the server) already links every post, so the line can be built from the entity and its
stories by time, with each story's event type (`built`: release, benchmark, ...). This is C + D above, with stories as
the timeline's stops. Expected check case: the model's timeline lists both stories in order, and the breakdown is shown
as analysis on it.

Related, Stealth v10.19 (0208): a News row shows its expert breakdowns as "Analysis", apart from its reports.

## Built and measured: the second case (Stealth v10.23, branch `v1023-timeline`)

v10.14 built A-D (`0165-built.md`); v10.18 dropped A's rule (0203: 26 of 60 right). v10.23 builds C + D's second case
and measures the line. Names below are invented; the real rows and every answer are in `plan/research/0165-timeline/`.

### Built
- **Stops** (`markx/stops.py`, kind `stop`, guide `stop-v1`): a story is a *candidate* stop when the thing is subject
  or actor of a quarter of its members or of its first post. The jobs process's plan job (`tasks.BACKGROUND_PLANNED`;
  never a decision run, never a lease) asks each candidate (thing, story) of the stories that gained members in the
  last 30 days once: is the story about the thing, and what happened to it (teaser, preview, launch, availability,
  update, weights, benchmark, ranking, adoption, research, incident, deal, analysis, other). Worker: 10 a call, effort
  low; no table (the answer is the task's call, read by `stops.of`).
- **The line** (`markx/timeline.py`): `story` = a stop (the stored answer says about; unasked, by its share), `in_story`
  = a story that only names it (in "All events", never among the top). Every post event inside a stop's story, and an
  analysis after one, carries the stop as `on`; the entity page nests them under their stop ("In this story").
- **Posts that only name it** (found by the measure below): the birth is the oldest post *about* it (subject or actor;
  `named_since` keeps the older mention's date), the first outside mention is the first outside post about it or
  linking back, and a month of outside posts that only name it is `named_only` (never among the top).
- **Analysis** on the line (`analysis`: an outside post about it read as commentary, 1000+ own characters, origin not
  the maker: News' Analysis rule) is built and **off**.
- **Switches** (`entity_bands.json` → `timeline`): `stops` **on**, `stop_types` **off** (answers kept, the word not
  shown), `analysis` **off**.
- Tests: `test_markx_timeline` (21: both cases as fixtures, the second as one model's two stories with a rival's story
  that names it once and a breakdown; the planner asks once; the switches), `test_markx_jobs` / `test_markx_validate`
  (the kind), the worker's 104, `timeline.test.tsx` (7: stops with their posts and the breakdown nested).

### Measured (read-only GETs of the server, 2026-11-17; Haiku 5.5 as the worker asks it; blind labellers as subagents)
Bars: a word shown to the reader about a story or a post (the stop's word, Analysis) needs News Analysis' bar (point
97%, Wilson lower 90%); the line's composition (which stories are stops, which posts mark its birth) replaces the line
served today, so it needs the blind judges to prefer it on held-out entities and pass more of them.

| what | set | result | bar | |
|---|---|---|---|---|
| stop: about the thing (precision of the stops shown) | dev: 169 (thing, story) pairs, 50 entities | 79/84 = 94.0% [86.8–97.4] (rule alone 68.3%) | 97 / 90 | guide revised after |
| stop: about the thing | **held out**: 123 new pairs, final guide, two runs | 95/98 and 97/100 = **97.0% [93.5–98.6]** pooled; recall 93–95% | 97 / 90 | **pass: on** |
| stop: the word (what happened) | held out, the same two runs | 67/94 = 71.3%, 70/96 = 72.9% (labellers with each other 95–97%; run to run 81%) | 97 / 90 | **fail: off** |
| analysis (commentary, 1000+ own chars, not by the maker) | 60 rule positives, 40 negatives, 3 labellers | 40/60 = 66.7% [54.1–77.3]; 5/40 negatives are analysis | 97 / 90 | **fail: off** (News Analysis is a Shadow too: 9/12) |
| the line, per entity (0165's measure: pass = it tells the thing's history, under 2 lines off-topic) | the 30 biggest products of the last 30 days | served 9/30 = 30% [17–48] → new **22/30 = 73% [56–86]**; new better 22, same 6, worse 2 | judges prefer, more pass | **pass: on** |
| | 20 random (19 with a timeline) | 6/19 = 32% → **14/19 = 74% [51–88]**; better 15, same 4 | | |
| | **held out**: 15 more random products | 4/15 = 27% [11–52] → **10/15 = 67% [42–85]**; better 10, same 5, worse 0 | | |

(The line was judged twice: the stop split alone, 29/49 = 59%, then with the post rules; the 30 + 20 are in-sample for
the post rules, the 15 are not.)

**The two cases:** the second case's model: launch, benchmark, weights and the training report are stops in order
(Haiku: launch, benchmark, weights, research; three labellers the same), the engine's release that names it is
`in_story`; the breakdown is read as commentary with 1,803 own characters, so it hangs on the weights stop once
`analysis` is on. The first case is unchanged: its earlier name has no entity of its own (A was dropped), so no rename
can be asked.

**What still fails** (18 of the 64 lines, the exact rows in `plan/research/0165-timeline/eval2_*.jsonl`):
- the extractor's role: a post whose subject is another thing marks it `subject` (an engine's day-0 support for
  another model as a model's own post; a newsletter);
- identity: one name, several things (a language and unrelated posts; a messaging app and a capture card; a
  benchmark and a model's launch post): 0184's facts and splits, not the timeline;
- releases by a maker's site that are about something else (a maker's news on another product).

**Renames and components (A + B):** not changed. On the server, 15,383 rename questions are answered and one
`renamed` waits in the queue: too few to measure a precision, so renames stay questions (never automatic). The first
case needs the component rule (an earlier name inside its parent's name) that 0203 dropped; a Haiku question for it
(as stop-v1) is the next step, measured the same way.

**Resources:** on the 11-05 server copy (entities built once): the stop planner's first pass (344 stories, 306 pairs)
0.21 s, peak RSS 111 MB (110 at start); the 20 biggest things' entity pages 0.07–0.38 s each (2.1 s in all), peak 110
MB. The page is the kept entity page (0198): built on demand or by the jobs process, never in a decision run. Haiku spent
measuring: about $0.19.

## Second night (v10.23, after the merge into v1023)

**The whole-line bar, confirmed on a frozen set.** 15 more random products of the last 30 days, chosen and hashed
(`plan/research/0165-timeline/frozen3.sha`, with the scripts and the guide) before any page was read; the rules
unchanged; three new blind judges. Served line 2/15 = 13% [4–38] pass → new **8/15 = 53% [30–75]**; judges prefer the
new 11, the served 2, same 2. With the first held-out 15: served 6/30 = 20% [10–37] → new **18/30 = 60% [42–75]**.
The bar holds (preferred, more pass); the pass rate itself is modest, and the failures are again identity (one name,
several things: a constant, a social network, a mythological name) and digests that name everything.

**The post page's before** shows the thing's stops before the post (its stored stop answers saying about; the post's
own stories left out; the last 3; nothing asked on a page): `timeline._stops_before`, tested on the second case (the
breakdown's page shows the launch stop, not the weights story it is in).

**Migration 0152**: a partial index `mx_story_posts (valid_from) WHERE valid_to IS NULL` for the stop planner's pass:
on a scratch copy inflated to 509k rows (64k current) 9–13 ms → 0.15 ms a pass (776 kB).

**The stop's word: still off.** Why it fails, measured:
- Not the vocabulary: grouped into 7 coarse words (before / release / results / adoption / explained / incident / deal)
  the held-out answers are still 76.6–78.1% right (dev 82.9–86.6%); errors cross groups (a launch with its scores read
  as `benchmark`, security research done with the thing read as `incident`).
- Not missing input: stop-v2 (`plan/research/0165-timeline/stop-v2-draft.md`) showed each post's own reading (its
  English headline: 381 lines across the 130 test items had one) and ordered the questions; on the dev sets it scored
  77.6% and 70.3% (v1: 85.9% and 69.3%) and its about-precision fell on one set (87.6% against 93.2%). Not shipped.
- Haiku's own noise is the size of the gap: two runs of the same guide agree on 75–81% of the words, while the
  labellers agree with each other on 95–97%. A story holds several happenings; Haiku picks one inconsistently.
- ent-v5's event type and origin are not readable through the server's API (the post panel serves read-v2/v3 fields),
  and its 14 types (model_release, research_result...) cannot tell launch from weights from availability; not tried.
Next, if wanted: one word per post (the stop as its first post's happening) or several words a stop, measured the same way.

**Components (A): still off.** Question `component-v1` (`plan/research/0165-timeline/component-v1-draft.md`: is the
longer name a component, the product itself, a version, other) on every name filed under one of the 79 products whose
written name had words after the product's (52, from 1,788 post panels): the labellers find **3 components in 52**
(most are "X app", "X models", "X GPUs"). Haiku said `component` 6 times, **2 right (33%)**; overall 33/52 agree.
Far under the bar and too rare a class to measure at 97/90 from the server's posts (a Wilson lower bound of 90% needs
~36 right answers in a row). Not built into the pipeline; the first case stays unjoined.

Haiku spent the second night: about $0.09.
