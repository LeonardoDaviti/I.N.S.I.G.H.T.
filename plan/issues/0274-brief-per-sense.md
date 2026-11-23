# 0274 — An entity's brief per sense (v10.32; 0261 the brief, 0184 senses, 0250 shared names)

Status: **built, OFF** (`entity_bands.json` `entities.brief_senses: false`). Sense assignment measured on the
11-19 server copy and above its bar; the per-sense brief lines NOT measured (the copy holds no brief rows). Not
pushed. Rows behind the measure are private (`plan/research/v1032/brief-senses/`).

## Why

0261 round 1: the "Code Mode" entity merges an experimental feature of a coding tool, another company's product of
the same name and the general technique (aliases "Cloudflare Code Mode", "Codemode"; maker none, type other; merged
by the name rules `squash` and `maker_prefix`). Its brief mixed them: ~10 of 17 lines true but about another sense.

On the copy no sense entities exist (`facts.on`, `facts.split`, `families.split` are all off) and identity's own
collide-v1 answers for the three merged entities each called the name one thing (5, 2 and 3 mentions shown, the
technique). So the page cannot rely on identity's senses yet.

## The shape (owning module: entity_brief; identity's sense question, not a new one)

1. **Sense entities first.** When entity_facts already lists senses of the root's name key (0184 splits: their
   mentions pinned), each sense is its own entity with its own brief, and the page already links the others
   (`entity.senses`). Nothing new is asked.
2. **Else identity's sense question over the brief's posts.** `entity_brief.plan_senses` (inside `plan_things`, the
   brief's planner) asks the collide kind under its guide **collide-v2** (0184's guide: one sense one exact thing, its
   `what`, kind and the maker a post states; registered now as a collide guide variant, `schemas.GUIDE_VARIANTS`) over
   the brief's report posts: one mention a post (`_mentions`: its first subject/actor mention), the input
   `entity_facts.known_block` + `identity.collide_input` (the same sample format). The task is `a = b = root`;
   identity's collision reads all read `b IS NULL` (the answers-since read gained it), so they never take it.
3. **Settled** (`entity_brief.settled`): the two-run agreement read per mention: a mention is settled when 2 runs
   (of at most 3) put it with the same mentions; while some are not, the fewest mentions are left out (unclear) so
   the rest settle; a third run is asked when two disagree on any mention. Generic and unclear mentions are in no
   sense. The numbers map back to posts with `identity.match_pick` (deepened: `members`, the merged entities too).
4. **The brief per sense** (`entity_brief.view`): with 2+ named senses, `brief.senses = [{label, kind, maker,
   post_count, what, how, results}]` (the three top lists empty): each sense's lines are its own posts' reports only,
   each line's text read from those reports alone (`_fields`, track_things.remerge's rule). No new things questions:
   the things are asked once a post, as before; only the grouping is new. Points stay mapped to the shown lines.
   `stamp` reads the sense answers (a new answer rebuilds the kept page). 0269's rules hold per sense (`_sections`,
   the one line builder): a sense's lines are shown only when SHOW_POSTS (5) of its own posts were read
   (`read_posts(posts=)`), a what line must be about the sense itself (`own_what` by the entity's names plus the
   names the sense's mentions wrote), and lines of the same figures and key words are one (`_same`). A sense short
   of them is still listed (label, maker, post count) with no lines.
5. **Frontend** `EntityBrief.tsx`: "This name stands for N different things in its posts", then one heading a sense
   (what it is · maker · posts) with its three lists.

## Measured (2026-11-21, the 11-19 copy read only; Haiku asked outside the database, claude -p, guide collide-v2)

Code Mode plus 5 shared names of the hard set (shared-names-all.json, top by makers, with 7+ brief posts): the
inputs built by `sense_input` from the copy; 2 runs each, a third where two disagreed (Code Mode, Atlas); 14 calls,
~$0.025. Each mention labelled by me from the input (the post's words), **not fully blind**: I read the first
answers before labelling.

| entity | mentions | senses settled | assigned | right | unclear |
|---|---|---|---|---|---|
| Code Mode | 9 | 4 (tool feature; an agent tool of the name; the general pattern; the other company's product) | 8 | 8 | 1 |
| Atlas | 12 | 3 | 12 | 12 | 0 |
| Muse | 12 | 3 | 12 | 12 | 0 |
| Orion | 11 | 5 | 11 | 11 | 0 |
| Halo | 8 | 2 | 8 | 8 | 0 |
| Genie | 7 | 4 | 7 | 7 | 0 |
| **all** | **59** | | **58** | **58 (100%, Wilson low 93.8%)** | **1** |

Code Mode's 3 runs never grouped alike (one mention, a blog post titled "What is Codemode", moved between the agent
tool and the pattern): with whole-answer agreement it never settles; read per mention it settles with that one post
left out. Its unclear post is the one I also found ambiguous.

**Briefs per sense supported (bar 95%): not measured.** The copy has no brief schema or things rows for any of
these entities (0261 asked Haiku outside the database), so the per-sense lines cannot be read there without
~100+ things questions per round. **The switch stays OFF**: both bars were asked for.

## To switch on

1. Run the things questions for 5+ of these entities (0261's harness) and judge every per-sense line against its
   quotes (bar 95%), and a fresh blind labeller on a new set of shared names (the 58/58 above is mine, not blind).
2. Then `entities.brief_senses: true`; the worker answers collide-v2 tasks already (the collide kind).

## Tests

`insight_core.tests.test_entity_brief_senses_0274` (7): one run never settles; two alike settle; a stray mention
left out while the rest settle (Code Mode's shape, invented numbers); an unclear mention settles by the others;
runs past 3 are not read; the guide registered as a collide variant; off by default. Also run:
`test_entity_brief_0261` (the view refactor), `test_markx_shared_names`, `test_markx_kept_pages`,
`test_markx_validate`, `test_markx_entity_facts`. Frontend: `entityBrief.test.tsx` (3), tsc clean.

## Left

- The per-sense brief measure (above) and a blind second labeller.
- When identity's senses switch on (0184 `facts`), a settled brief sense answer could feed `entity_facts.apply`
  (a split) instead of living only in the brief; not wired (the brief's answer has no maker groups or two-run split
  record of identity's shape yet).
- A sense with fewer than MIN_POSTS posts still shows its lines (thin senses: one post).
