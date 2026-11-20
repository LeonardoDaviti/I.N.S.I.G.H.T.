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

## Step 0: the measurement to run (written, not run: no real data in this build)

On ONE read-only server copy (owner 2026-11-19: no clones; deleted after). Both read only; neither writes.

1. The rule the journeys' hard set uses (by name key: what the readings call it, so it is the same before and after a
   split), makers resolved through their aliases (one company, many spellings) and word containment:

```sh
docker run --rm --network insight_insight-network -e DSN="$COPY_DSN" -v "$MAIN/plan/research/v1027:/out" \
  insight-backend:<tag> python - <<'PY'
import json, os
from insight_core.checks.session import open_copy, copy_now
from insight_core.checks import journeys as J
with open_copy(os.environ["DSN"]) as conn, conn.cursor() as cur:
    copy = J.Copy(cur, copy_now(cur))
    every = J.shared_names(cur, copy, makers_at_least=2, mentions_each=2, top=None)
    by = {k: sum(1 for x in every if len(x["makers"]) >= k) for k in (2, 3, 4, 6)}
    print("bare names, 2+ companies each 2+ mentions:", by)
    json.dump(every[:50], open("/out/shared-names-top50.json", "w"), indent=1, ensure_ascii=False)
PY
```

2. The same per entity, raw (no alias resolution: the upper bound the 1,560 figure came from), for comparison:

```sql
SELECT e.id, e.name, e.maker, count(*) FILTER (WHERE n >= 2) AS makers_2plus, jsonb_object_agg(mk, n) AS makers
  FROM (SELECT m.entity_id, lower(btrim(m.maker)) AS mk, count(*) AS n
          FROM mx_mentions_now m JOIN mx_entities e ON e.id = m.entity_id
         WHERE m.guide IN ('ent-v3', 'ent-v4', 'ent-v3-6k', 'ent-v4.2', 'ent-v5')   -- schemas.mention_guides()
           AND e.level = 'thing' AND e.status <> 'not_entity'
           AND e.type IN ('model', 'product', 'software', 'project', 'dataset')
           AND e.key !~ '[[:space:][:digit:]]' AND NULLIF(btrim(m.maker), '') IS NOT NULL
         GROUP BY 1, 2) x
  JOIN mx_entities e ON e.id = x.entity_id
 GROUP BY 1, 2, 3 HAVING count(*) FILTER (WHERE n >= 2) >= 2
 ORDER BY 4 DESC, sum(n) DESC LIMIT 50;
```

The top 50 of (1) with their makers go to `plan/research/v1027/` (private). The difference between (1) and (2) is the
alias share; the names of (1) are the hard set's.

## Built (v10.27, 2026-11-20; module tests only, no real data)

Invented names only in code and tests. Migration 0164 (the placed values). Nothing deleted anywhere.

1. **Split by maker** (`identity.split_names`, `split_plan`, `maker_groups`; repair step `names`, the last of
   `entity_repair.STEPS`, under the stage's budget). 0230's grouping is now one function, `maker_groups`, used by both
   `family_makers` and the split (a name joins a group when it fits any of its names, not only the top one). A bare
   thing (one word, no digit, a product type) whose mentions state 2+ makers each by `SPLIT_MIN` (2): the maker its
   entity states keeps it (else the most stated; its id and redirects kept; shown "<name> (<maker>)", `shown_by`
   'split', which the shown-names step never replaces); each other maker gets "<name> (<maker>)" under its maker
   entity, recorded in `mx_entity_fixes` (kind `maker_split`), the mentions moved by facts pins (`from_entity` kept,
   undoable) and `mx_mentions.entity_id` (as the linking would). A mention stating no maker: the post's other makers
   (`rule:post`), else a link to one maker's site (`rule:link`), else the settled collide answer (2+ agreeing runs,
   `facts`; the collide question is identity.collisions' own, asked once for any name of 2+ makers), else `unsure` on
   the parent. New mentions of a split name are placed the same way each run (the calls since `maker_split_since`).
   **Switch: `families.split`, default OFF.** The tests show two companies are never one thing and aliases that are
   one cluster or word-contained ("X" / "X Labs") never split; they cannot show the third case: one company under two
   names that are neither (a parent and an unmerged brand) IS split. That needs the measurement below.
2. **Links follow**: relations read each side through its pin, and `graph._relation_scope` now reads again the posts
   whose pins changed since (a split's, the owner's), so edges move with their mention (test: released and based_on
   land on their maker's thing, the parent keeps only its own). **Held**: `identity.held_released`, called by
   `graph.entity_relations`: a `released` only one post states whose maker is not the thing's settled maker is kept
   and not shown until a second post states it. Switch `families.released_held`, default ON (it only hides a single
   contradicted post).
3. **Timelines**: an outside event (first or monthly) counts only posts whose role is subject, actor or compared
   (`timeline.OUTSIDE_ROLES`; posts linking back still count); the split's own mentions are its pins. Switch
   `timeline.outside_roles`, default ON. Two 0165 tests changed accordingly (a named-only month is no event now).
4. **Story pages**: `entity_views.story_things` -> `story_view()["things"]` (role then member count then name, up to
   12, through merges and pins); frontend `StoryThings` (MarkXEntities.tsx) under the headline on MarkXStoryPage, each
   a link to `/markx/entities/{id}`.
5. **Journeys** (`checks/journeys.py`, run by `side.sh` after the invariants, `journeys.json`; `report.py` compares
   its counts base vs head like invariants (a rise fails) and prints section B1 with the head's rows). Steps:
   story_things, story_makers, entity_links, entity_timeline, family_makers; sets hard and random (seeded by stable
   keys). Rows in the breakage format (start, post, title, returned, said, label, cause, fix). The hard set file is
   `plan/research/lab/journeys.json` (private; realdata-check.sh copies it in as JOURNEYS and keys the base cache on
   it), seeded with the owner's walk as a rule (`shared_names`, 6+ makers each 2+ mentions) and step 0's top 50.

Tests: `test_markx_shared_names` (13, new), `test_checks_journeys` (3, new), `test_markx_entity_fixes` (the
resumable-repairs test counts the sixth step), `test_markx_timeline` (2 changed), with `test_markx_entities`,
`_graph`, `_entity_facts`, `_perspectives`, `_built`, `_handles`, `_entity_guards`, `test_voice_owner`,
`test_markx_api`, `_kept_pages`, `test_realdata_checks`, `test_check_api_during_run`: 391 pass. Frontend:
`storyThings.test.tsx` (3), tsc clean.

### To measure on real data (before `families.split` goes on)

On one read-only server copy, then a scratch copy for the run: (a) step 0 above; (b) the stage once with
`families.split` on, rolled back, dumping every split (parent, child, maker, 3 example posts each) and every
`unsure` row: counts of splits, pins added (the run book holds every pin: its MB), the step's seconds; (c) blind
labels (two Haiku labellers, a referee) on the hard set (step 0's top 50 + the owner's walk) and a random 150 of the
split mentions: "this post's <name> is <maker>'s thing"; bar 97% / Wilson 90% on each set, and the alias miss
counted apart (a split whose two makers are one company); (d) the realdata-check with the journeys step: every step
agrees on the hard set (bar), links on a split page >= 97%, timeline events about the split >= 97%. `released_held`
and `outside_roles` are on: their effect is in the journeys' entity_links and entity_timeline rows on that run.
