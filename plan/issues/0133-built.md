# 0133 — Built (Stealth v10.7): ent-v4, documents and cited sources as entities

Built 2026-11-08 on its own branch, test-first, parts 1–5 of the spec. **The lab's ent-v4.1 run
(`out/entv41_v1/`) has no REPORT.md yet**, so this is the spec's "the build doesn't wait for the guide": everything is
code, `guides/ent-v4.md` is a placeholder, and **a guide switch defaults to ent-v3 and the 1,500-character cut, so a
deploy changes nothing until the owner switches.**

## The switch (what a deploy changes: nothing)
- **Where:** `mx_settings` key `entities_guide`, set on the **/markx Worker tab** ("Entities guide", under the reading
  window), or `POST /api/markx/settings/entities-guide {guide}`. `GET /api/markx/settings` and the overview show it.
- **No row = the default = `ent-v3`:** 1,500 characters, no citation rule, ent-v3's schema. Exactly the code path
  before 0133: the same task inputs, so no task is planned again and no Haiku call is made.
- **The arms** (`schemas.ENTITY_ARMS`):

  | guide | characters | citation rule | schema |
  |---|---|---|---|
  | `ent-v3` (default) | 1,500 | no | ent-v3's (paper, the six roles) |
  | `ent-v4` | 6,000 | yes | ent-v4's (document, + source, recommended, `by`) |
  | `ent-v3-6k` | 6,000 | yes | ent-v3's: the spec's fallback (ent-v3's text, byte for byte) |

- **The placeholder can't be switched to.** `ent-v4.md` starts with `<!-- 0133 placeholder:`; the switch refuses it
  (409, and the Worker tab shows it disabled, "waiting for the lab's guide"). That matters beyond safety: a guide id is
  one body forever (`mx_guides`), so if the placeholder were ever loaded on the server under `ent-v4`, the frozen guide
  couldn't take that id. Only the switched-to arm is loaded into `mx_guides` (at start and on switching).
- **The citation rule sits behind the same switch.** It runs only when an answer of an arm with the rule is recorded
  (ent-v4, ent-v3-6k), never under ent-v3. So a deploy finds nothing and writes nothing.
- `KINDS["entities"].guide` stays `ent-v3`: the readers that name it (0132 B's `source_stats`, untouched) keep reading
  ent-v3 rows.

## What was built
1. **The cut** (`tasks.py`): `ENTITY_TEXT_CHARS = 6000`, used by `entities_input` only, and only when the switched-to
   arm says so (`_render`). `TEXT_CHARS` (1,500) stays for read, embed and the judges.
2. **The schema** (`schemas.py`, `validate.py`):
   - `ENTITY_TYPES_V4` (`document` replaces `paper`), `ENTITY_ROLES_V4` (+ `source`, `recommended`), and
     `ENTITIES_V4_SCHEMA` (+ `by`). ent-v3's sets and schema are unchanged.
   - `validate.check(kind, answer, input, guide)` checks an answer against its task's guide's schema (the API and the
     `markx.calls_valid` invariant pass the task's guide). `recommended` on a non-document is refused.
   - **`paper` is read as `document`, no row rewritten:** `schemas.entity_type` on every page and panel; identity's
     `types_ok`; `candidates.SPECIFIC_TYPES` has `document`, and its filter matches the stored `paper` too
     (`stored_types`). Identity's own type values and its question inputs are left as stored, so no alias or collision
     question is asked again because of the rename.
3. **The citation rule** (`markx/citations.py`, new; no model). Over the post's full stored text (title and text, not
   the task's cut), its open non-boilerplate `post_refs` and its kept links. Each hit: type `document`, role `source`,
   `rule = 'citation'`, at most 60 a post.
   - **Final:** arXiv ids and links (`arXiv:<id>`, `arxiv.org/abs|pdf|html/<id>`, the arXiv DOI, versions dropped);
     DOIs; document links through `candidates.document_key` (a paper by its id; a record or filing by 0109's shapes).
   - **First set, to be replaced from the frozen report:** `IN_TEXT` — "Author et al. (YYYY)" / "Author et al., YYYY",
     "Author & Author (YYYY)" / "Author and Author (YYYY)", "Author and Author, YYYY", "Author (YYYY)", each in Latin
     and Cyrillic ("и др.", "и соавт.", "и"). `PATTERNS_VERSION = "0133-first-set"`.
   - **The merge with the model's mentions:** a hit and a model document naming the same thing are one mention: the
     same arXiv id or DOI in its span or name, or the same name key. The rule's span is kept; the model's name and
     role win (so `source` only when the model said so or had no mention). The rest of the hits follow the model's
     mentions.
   - `mx_mentions.ref` keeps the identifier, and identity joins a document across posts by it whatever name each post
     gives it (`identity._join_refs`: the name's key and the identifier's key alias one entity).
4. **`by` → a `published` edge.** I chose **0131's edge storage** (`mx_connections`) over a new identity table: an
   edge with its rule and evidence, closed not deleted, already read by the invariants. Migration 0082 lets
   `a_kind`/`b_kind` be `entity`; the row is `('entity', publisher, 'entity', document, 'published')`, rule
   `mention_by`, the mention's call, evidence `{post, guide, n, by}`. The publisher is the entity its name's key
   aliases, made a provisional org (or the person type a same-post mention gives that name) when there is none. Every
   post-post reader of `mx_connections` already filters `a_kind = 'post'`; decide's story pass reads by story ids.
5. **Re-extraction and the current set.**
   - A new guide is a new task: the planner (`plan_posts`, 0132 C1's `plan_last_posts`, `entities_task`) asks under
     `schemas.guide_of(cur, "entities")`, newest first within the reading window. Old tasks, calls and mentions stay.
   - **The current mention set = the newest valid answer** (migration 0082): `mx_mention_sets` (one row a post: the
     guide of its newest valid entities answer, written with the mentions by `repo.add_mentions`, an empty answer
     included) and the view `mx_mentions_now`. 0082 fills it from the stored ent-v3 sets. Identity, surges, the entity
     list and page, the queue's examples, the post panel, News' entities, the graph's subjects (0131), candidates'
     subjects, perspectives' and Built's mentions read the view. The post panel says which guide the entities came
     from (`entities_guide`, shown when not ent-v3).
   - A collision split's pins name the post's current guide; an ent-v3 pin carries to the same post's ent-v4 mention of
     the same name (`Book.pin_keys`).
6. **Where it shows.**
   - **The entity page:** "published by" in its header, "Published" (an org's or person's works), "Cited as
     evidence" (posts with role `source`) and "Recommended" (role `recommended`).
   - **The Mark X post panel:** the entities, then "Documents and cited sources": cited as evidence, recommended, and
     the documents it names, each with its publisher and a "citation rule" mark.
   - **Surges** already counted only subject and actor; now documented and tested (`schemas.NOT_SURGING`).
   - Frontend additions are in lazy chunks only (the panel, the entity page, the Mark X page). The switch's call is in
     the Mark X page's chunk, not `api.ts` (the api.ts block cost the feed route 73 gzip bytes and it is at its
     budget): the feed route is +8 bytes (0.00%).

## Migration 0082 (Mark X tables only, idempotent)
`mx_mentions.rule`, `.by_name`, `.ref`; `mx_mention_sets` (+ the backfill); the view `mx_mentions_now`;
`mx_connections` a_kind/b_kind CHECKs rebuilt with `entity` (0081's way).

## Tests
- `test_markx_ent_v4` (26): the default arm and the cut (entities only); paper read as document in every reader;
  the new roles under ent-v4 only, `recommended` a document only; each in-text shape in English and Russian, the
  identifiers, document links only; the merge by arXiv id, DOI and name key; ent-v3 runs no rule; the placeholder
  refused; a guide change plans new tasks with the 6,000 cut and rewrites no row; the newest answer is current (an
  empty one too); `by` as a published edge and the document page's publisher, citing and recommending posts; one arXiv
  id one entity across posts; an owner's split carries to the new guide's mention; surges ignore `source` and
  `recommended`; 0082 fills the sets and runs again.
- All `test_markx_*`, `test_realdata_checks` and `test_voices` pass: 457 tests (the storage test's table count now 28).
- Frontend: `entv4.test.tsx` (the panel's sections, none for an ent-v3 post, the entity page, the switch with the
  placeholder disabled); every Mark X frontend test; `npm run build` (bundle check passes).
- Not run (the owner's instruction): `scripts/realdata-check.sh`, lab re-measurements, any Haiku call.

## On the server copy (`insight_server_1105_mxreal_sep`, scratch `..._check_388994_a`, dropped after)
Run once, no Haiku call. The dates count back from the export (2026-11-05 11:14 UTC).
- **Migration:** 0080–0082 together in 6.2 s. 0082 filled `mx_mention_sets` with 8,997 posts (every post with
  ent-v3 mentions); `mx_mentions_now` = `mx_mentions` = 32,414 rows, so every reader reads what it read before.
- **The rule's hits** (all 49,384 posts, full text + links, 31.6 s):

  | | posts | posts with a hit | hits | hits / 1,000 posts |
  |---|---|---|---|---|
  | last 30 days | 5,870 | 590 | 2,726 | 464 |
  | last 120 days | 15,640 | 1,688 | 6,835 | 437 |
  | all | 49,384 | 4,875 (98.7 / 1,000) | 18,591 | 376 |

  By shape: document links 10,836, et al. 3,694, arXiv 2,308, "Author (YYYY)" 946, DOI 408, "A and B, YYYY" 246,
  "A & B (YYYY)" 153. Not judged: the in-text shapes are the first set; the frozen report says which to keep.
- **Re-extraction, planned ent-v4 tasks** (each counted in a rolled-back transaction; at $0.00136 a task):
  30 days 5,578 (about $7.60, planned in 2.8 s); 120 days 14,709 (about $20, 16 s); all 46,195 (about $63, 230 s over
  several planner calls). A post whose input repeats another's is one task, so these are under the post counts.
- **The entity stage with the new mentions.** The 30 days' 5,578 ent-v4 tasks were answered with each post's own ent-v3
  mentions (paper → document; no model) and recorded, so the rule merged in: 20,787 ent-v4 mentions, 2,264 of them
  `citation`; the current set went from 32,414 to 34,661 mentions.
  - First, the copy's own first full pass had to finish (the copy had never run identity): 47.3 s, then 10.1 s.
  - Then an incremental run: 8.3 s (it links 6,000 mentions a run, `LINK_LIMIT`; the rest wait for the next runs),
    asking 1,095 alias and 8 collision questions (identity's usual cheap ones, about the new names).
  - Then the night's full pass: 46.3 s, stopped at its 45 s budget after 14 of 16 chunks (12 of 14 before), to resume
    next run as 0128 designed. Surges 0.2–0.4 s.
  - So the stage stays inside its own budget (`jobs.ENTITY_BUDGET`, 45 s outside the run's 120 s); a re-extraction adds
    about two chunks to the full pass.
- Not measured: `published` edges (the simulated answers have no `by`).

## What waits for the frozen guide (out/entv41_v1/REPORT.md)
- `guides/ent-v4.md` replaced byte for byte (drop the placeholder line with it); its md5 in the merge commit. Then the
  switch accepts `ent-v4`.
- `citations.IN_TEXT` and `PATTERNS_VERSION` from the report's patterns (the identifiers and links stay).
- If ent-v4.1 fails its bars, the fallback arm `ent-v3-6k` is ready (switchable today); if both fail, nothing switches.
- The owner's review (20 relaying posts, 10 ordinary) after a switch.

## For the owner
- Switching plans the window's posts again (see the counts above): choose the reading window first.
- 0132's code reads ent-v3 rows as before: `source_stats` (by `KINDS["entities"].guide`) and `utils/source_roles`
  (every guide's rows of a post, so after a switch a re-read post's names count from both sets). Neither was mine to
  edit; moving them to `mx_mentions_now` is a one-line change each when 0132's owner wants it.
- A document the rule finds by a link alone is named by its address or identifier ("arXiv:2401.01234",
  "doi:10.…", a filing's address) until a post names it.
