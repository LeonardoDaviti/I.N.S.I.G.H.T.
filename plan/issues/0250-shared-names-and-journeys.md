# 0250 — One name, many things: split bare names by maker; links, timelines and story pages that follow; journey tests (v10.27)

Status: **approved** (owner 2026-11-20). Real rows are private (`plan/research/v1026/` and the check's notes).

## The case (the owner's walk, 2026-11-20)

Story "Genie 4 world model now available to developers via Gemini API" -> no way to the entity from the story page ->
a post -> the entity "Genie" -> its family page: "model · by DeepMind", links "Based on: GPT-4o", "Released by:
Anthropic, OATI", a timeline of 23 events from 2017.

On the server copy, the bare-name entity's mentions name these makers: Google DeepMind/Google 13, Cosine 5, Databricks
4, General Electric 3, OATI 2, Anthropic 2, none 6. Six different things share the name: the world model, a coding agent
(a GPT-4o fine-tune for SWE-bench), a BI assistant, a grid-operations AI, others. Identity grouped them by the bare name
key and took the most common maker. Every link stated about any of them lands on the one page ("based on GPT-4o" is the
coding agent's, "released by OATI" the grid AI's), and the timeline's "outside" events include an old online service and
the plain word "genie". The versioned entities (2, 3, 4) are clean.

Why the bars missed it: the merge bar (97.6%, 40/41) is a random sample; bare names shared by several makers are rare
in a random sample but they are the names a reader looks up. Collision splits were 55% (6/11) and v10.25's family
maker rule (0230) was built OFF.

Scale (server copy): 1,560 of 9,285 product-like entities with 5+ maker-tagged mentions have a second maker named twice
or more; most are one company under two names (aliases), so the true collision count is to be measured (step 0).

## What to build (general; nothing named)

0. **Measure first:** resolve maker names to org entities (aliases: one company, many spellings); count bare-name
   entities whose mentions name 2+ distinct companies each with 2+ mentions; list the top 50 with their makers (private).
1. **Split by maker** (identity, 0230's family maker rule deepened, not a second path): a bare-name entity whose
   mentions name distinct companies splits into one entity per company ("<name> (<maker>)" as its shown name when two
   are live); mentions without a maker attach by the post's other entities and links, else are asked once (the
   collide kind), else stay "unsure" on the parent. Redirects keep old ids working; nothing deleted.
2. **Links follow the split:** each stated or derived relation moves with its post's mention. A single-post
   "released by X" whose X disagrees with the entity's settled maker is held until the split settles.
3. **Timelines count real mentions:** "outside" events need the thing as subject, actor or compared (not a bare
   mention), and only the split's own mentions.
4. **Story pages show their things:** "Things in this story" under the headline, from the members' readings, ranked by
   role (subject first) and count, each linking to its entity page (`/markx/entities/{id}`).
5. **Journey tests** (owner rule 2026-11-20, memory `journey-testing`): the real-data check gains a journeys step:
   scripted walks over the copy's pages, each step checked against the others:
   - story -> its things -> each entity: the entity's maker agrees with the story's maker mentions; the entity is
     reachable in one click;
   - entity -> its links: each link's post names this split (not a namesake);
   - entity -> timeline: every event's post is about this split (subject/actor/compared);
   - entity -> family -> versions: one maker across the family unless the family is a split parent.
   A permanent **hard set**: the bare names with several makers from step 0 plus the owner's own walks (this one first),
   measured apart from random samples; reported in the breakage format (exact rows, cause, the fixing feature).

## Bars

Splits right >= 97% (Wilson >= 90%) on the hard set and on a random sample, judged blind; links on a split page
belonging to it >= 97%; timeline events about the split >= 97%; journeys: every step agrees on the hard set.
