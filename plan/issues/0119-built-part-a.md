# 0119 Part A — Built (v10.1: entities in Shadow)

Branch `issue-0119-v10.1-entities` (main merged at `deb2f01`). Not pushed, not merged. The spec is `0119-mark-x-v10.1-entities-and-perspectives.md` (its working copy of 2026-11-06, experiment 2/v3 rules); Part B is not built. Real names, rows and the measuring scripts are in the private `plan/research/0119-build/`.

## What was built
- **Migration `0072_markx_entities.sql`** (0071 is 0123's). Mark X tables only, nothing deleted, idempotent:
  - `mx_entities` (type, name, key, level thing/family/version/variant/checkpoint, parent, maker, family key, version and its tuple, variant, size, build, status provisional/confirmed/not_entity, first seen);
  - `mx_entity_aliases`, `mx_entity_redirects` (by, automatic, call, `undone_at`), `mx_entity_queue`, `mx_entity_pins` (the owner's splits), `mx_entity_vectors` (name vectors), `mx_entity_surges` (`valid_from`/`valid_to`);
  - `mx_tasks.subject_kind` may be `entity` / `entity_entity`.
- **Task kinds:** `alias` (guide `alias-v1` = the lab's `eid_judge.md`, examples replaced by invented ones), `collide` (`collide-v1` = `eid_collide.md` v4, md5 `7f6fe496…`; its body is unchanged but the title line), and `embed_name` (`embed-name-v1`: a name's BGE-M3 vector, embedded by the worker's embedder as posts are; stored by `POST /api/markx/embeddings`). Schemas in `schemas.py`; `validate.py` checks a collision answer names each mention once.
- **Worker:** default `--kinds` read, entities, **alias, collide**, check, join, pair, merge, connect, card, headline, briefing, translate; `collide` 6 a call; `embed_name` goes the embedder's way.
- **A1 identity** (`markx/names.py`, `identity.py`, `entity_answers.py`, `entity_stage.py`):
  - the name key and the version parser ported from the lab (tuples, sizes and builds never versions, mixed-script words flagged), with the maker strip fixed (a maker that is the family stays: "Acme V4 Pro");
  - linking as a decision-run stage `entities`, incremental by the database (the mentions with no entity yet, 6,000 a run, newest first; the owner's pins); the first run after 04:00 is the full pass: every mention relinked and checked (`counts.entities.check`), every entity pooled;
  - the pool, rules, guards and queue exactly as A1 (see Deviations for the three readings I had to make);
  - the collision judge, asked twice and a third time only when the two disagree; a split two runs make is queued, never applied;
  - the owner's answers in the request's transaction (mx_entity* and `mx_labels`, item kind `entity`, split `test`); `same` merges, `other version` / `different` keep apart and undo a merge between them, `not an entity`; a collision's yes splits it (new entity, the shown mentions pinned); `undo` from the merges' history. A pair the owner answered, or a merge the owner undid, is never merged again by a rule or Haiku.
- **A2 surges** (`surges.py`): the stage `surges` after `entities`; per UTC day and entity, distinct voices (saved pages are no voice) crediting it by the roll-up (subject: itself, its maker, its family; actor: itself), through merges and pins; 3+ voices; rows with their posts and the children that credited them; a recount closes a changed row. Incremental: the days of the mentions linked this run, every day of the window when a merge, undo or split changed.
- **A3** (`entity_views.py`, API, frontend):
  - `GET /api/markx/entities` (one list over 30 days ranked by voices, then reports, then the newest post; read posts kept and dimmed; stories, 3 newest posts, last seen, surges);
  - `GET /api/markx/entities/{id}` (every post in every role by Mark X story, the loose ones last; sources with counts; maker, family and versions as links; a merged id opens its group);
  - `GET /api/markx/entities/queue`, `POST …/queue/{id}`, `POST …/merges/{id}/undo`;
  - the Entities tab (`MarkXEntities.tsx`: the queue with the four buttons, the merges' history with undo, the list, the lab's accuracy stated) and `/markx/entities/:entityId` (`MarkXEntityPage.tsx`, lazy); the post panel's entities link to their pages; News rows show `surging`.
- **Invariants:** `markx.entity_dangling`, `markx.entity_redirect_loop`, `markx.entity_cross_version`, `markx.entity_big_cluster`.

## Measured (a scratch copy of the server's 2026-11-05 data with its 120-day Mark X answers, 32,414 mentions of 8,997 posts)
- **Entities:** 13,958 made, all provisional (confirmed comes from the owner's answers): 11,416 things, 573 families, 997 versions, 516 variants, 456 checkpoints.
- **Automatic merges:** 342 (Haiku 182, squash 47, maker prefix 58, fields 43, handle 11, anchor 1). **Queue:** 455 open (423 pairs: below the bar 265, one-sided version 114, maker only guessed 35, fields without the parser 22, type 9, chain 8, handle with an extra word 2; and 32 collision splits of 499 keys asked).
- **50 automatic merges read by hand** (fixed seed; one reader, me, not blind): 49 or 50 right (one is an org and its accelerator programme that the posts use as one name); **wrong version merges 0/50**.
- **On experiment 2's labelled pairs** (two blind Opus labellers + referee; the 580 of 828 whose two names exist on this copy, unweighted, so the strata the lab oversampled weigh more):
  - automatic merges **86/88 = 97.7%** (bar ≥ 95%); one wrong (two government departments, joined through a chain of Haiku merges), one gold `cant_tell`; version merges 0;
  - recall of the gold `same` pairs: automatic 86/159, **automatic + queue 139/159 = 87%** (lab: 93%); the queue is 53/60 = 88% the same;
  - wrong spelling splits (gold same, kept apart): 20/159 = 13%.
- **Parser** on the lab's parse gold: 81.5% / 81.0% (test / test2) against the lab parser v2's 78.5% / 80.5%; they differ on 12 names, the backend right on 9, the lab's on 2.
- **Surges, replay of the lab's windows** (`out/surges_v2`, `out/surges_v3`; their entity-days counted by `surges.count`): v2 112 lab surges, 102 found too, 10 only the lab's, 13 only mine; v3 118, 103, 15, 22. The differences are merges (no embedder in the lab's v3 run; event and family names joined differently) and the lab's separate extraction. On the labelled surges both find: **92/101 and 97/101 real** (lab: 91%, 84–95).
- **Speed** (this machine, the scratch copy): the list 0.35–0.43 s; the biggest entity's page (798 posts, 74 sources, 120 days) 0.22–0.28 s; the queue 0.19 s. Stage `entities`: incremental 0.8–0.9 s, the full pass 31–39 s (the very first, making every entity, 40 s); `surges` 0.1–0.3 s.
- **Haiku:** $1.69 (alias 7,072 tasks $1.44; collide 1,037 asks $0.45), through `scripts/markx-worker` against my own lab API with my own token. 1,506 alias questions of the last full pass were left unanswered (the cap); they are not in the numbers.

## Deviations and readings of the spec
1. **Name vectors are a new kind, `embed_name`** (the spec lists only alias, collide, perspective, sheet). The pool's "BGE-M3 cosine ≥ 0.80 among a name's 10 nearest" needs names' vectors, and the stored ones are posts'. The worker's embedder answers it; nothing is downloaded.
2. **A Haiku–parser version disagreement is never asked of Haiku:** two stated versions that differ in either parse are kept apart (the guard's 135/135), and the disagreement that changes a merge is the fields rule's queue. Asking them was 1,533 extra questions on this copy, nearly all other versions.
3. **The queue-only rules** (X (Y), an org's handle with an extra word, the maker only guessed, Haiku's fields without the parser) are asked of Haiku and queued when it says `same` at any confidence; never automatic.
4. **Anchors:** an address anchors a name only by its whole name (a build tag after it dropped). The lab's containment test merged a maker's model family into its coding tool's repository on this copy.
5. **The collision judge's third run** is asked only when the first two disagree on a pair (two that agree are already the majority): 36 of 499 needed it.
6. **The full pass is the first run after 04:00 by the entity stage's own record** (`counts.entities.kind`), not the story memo: each job runs in a process of its own, so the decision run is full every time and the entity stage would be too.
7. **Surging News rows** are marked when one of their posts is a surge's evidence (subject or actor or a roll-up), not only a subject.
8. The old `MarkXEntities` in `MarkXOverview.tsx` (0124's file) is left in place, unused; `/api/markx/overview` still returns its today/week entities.

## Open for the owner
- The full pass takes 31–39 s of the 120 s limit on the 120-day data; with the decision run's own 5–6 s it fits, but it grows with the entities. A cap or a split pass may be needed later.
- The automatic-merge interval is still wide; your queue answers over the first month are the next test (the spec's rule: below 95% and the Haiku bar moves to the queue).
- Collision proposals are 32/499 = 6% of the keys asked here, against the lab's 4%; read them before trusting the judge.
- Not built: Part B (perspectives and the story sheet), and `/api/markx/overview`'s entities are not replaced (the tab reads the new route).
