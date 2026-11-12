# 0165 — A thing's timeline: built (Stealth v10.14, branch `timeline-0165`)

The spec is `0165-a-things-timeline.md`; names here are invented. **Migration 0105** (`0105_markx_timeline.sql`:
`mx_entity_redirects.kind` 'same' | 'rename', `mx_entity_queue.kind` may be 'rename'; renumber at merge if another
lands first). Switches in `markx/entity_bands.json` → `timeline`: `components` (**off**), `renames` (on: questions
only), `rename_cap` (200 a run), `rename_overlap_days` (7).

## A. Components get their own entity (`markx/components.py`; hook `identity.link_components`, `resolve_mention`)
- **Shape**: a mention's name (or its span when the span says more than the name, the name being the product's) is a
  known product's name key followed by its own words: the longest leading words aliasing a product cluster (a family,
  a version's parent, or a thing typed model/product/software; never an org or person cluster), 3+ characters left,
  the rest not a version/variant/size/build (the parser), not an org's word (CORP_WORDS), the two stated makers one
  maker or one none. A mention the parser reads as versioned keeps its version entity.
- **Evidence** (one of): role `subject`; the post's entities answer has `part_of` (component, product); the post's
  read-v2 `main.object` holds the component's words.
- **Writes** (switch on): the component entity made under the product (level `thing`, parent = product root); a thing
  already made under its maker re-parented to the product, logged in `mx_entity_fixes` (kind 'component', field
  'parent', old/new); a span-only mention sent to the component (`Book.components`, read after the owner's pins). The
  full pass computes the same, so its relink check holds.
- **View**: the product's page lists `components` (name, posts) and no longer lists them under versions (an org's page
  is unchanged: an org's things are its products, not components).
- **Measure before the switch**: `components.preview(cur)` (read only) → {mentions, moved, by_why, by_product,
  sample}.
- Not done: a component already *merged into* the product by a redirect is left (the owner's to undo); the reading's
  `part_of` is read from the call's answer, not from a table.

## B. Renames proposed by shared evidence (`markx/rename.py`; step `entity_stage.renames`, after the addresses)
- **Candidates**: two thing clusters (model, product, software, project, dataset; not versions, not org-like) of one
  maker (a stated maker's cluster, or an org/person parent's), the older's last post before the newer's first or after
  it by < 7 days, and one of: **address** (an own code/release/demo address shared, compared as host+path and a code
  platform's page as owner/repo; or a subject post of one linking an own address of the other: the birth post linking
  the launch's repository), **named** (the newer's first 3 posts about it name one of the older's names of 2+ words or
  5+ characters, never a maker's name), **formerly** (that post also says formerly / renamed / now called /
  previously known as / rebranded / ранее / переименован ...).
- **Guards**: one cluster already; any pair the owner kept apart (`Book.never`); one's part or version of the other
  (a parent in the other's cluster); `vconflict` strong or one family with two versions (a version bump).
- **Question**: kind `rename` (guide `rename-v1`, schema `RENAME_SCHEMA`: renamed / successor / part / different /
  cant_tell), asked once a pair (a = older, b = newer), the input both names with their first and last posts,
  addresses and why. Worker: `rename` is a default kind after `collide`, 5 a call (`scripts/markx-worker`).
- **Answers**: Haiku `renamed` → `mx_entity_queue` kind 'rename' (proposal same, reason rename, Haiku's confidence,
  `asked_because`); anything else keeps them apart (never asked again). **Never automatic.**
- **Owner**: `same` ("same thing, renamed" on the card) → `rename.merge`: the older root redirects into the newer
  (kind 'rename', by owner, whatever the sizes), refused (`needs_choice`) when it would put a product family and an
  org together (0164 A's `join_plan`); `different` / `not_entity` keep apart (undoing any merge between them). Undone
  from the history like any merge (the history marks it "renamed").
- **Shown name**: `entity_repair.shown` never picks an earlier name (a rename's old side) as the name shown.
- Runs: incremental, the entities the run's posts name; the full candidate pass once a night (the run that finishes
  the full pass, within the stage's budget).
- Not done: the owner's `different` on a rename item is not read into `Book.never` (that query reads alias answers and
  is in `load_book`, which another branch is changing); a rename-different pair could still be proposed as an alias.

## C. The timeline (`markx/timeline.py`, `entity_views.entity_page` → `timeline`, `MarkXTimeline.tsx`)
Read only, from stored rows: `birth` (oldest post of the cluster, any earlier name), `earlier_name` (each earlier name
at its last post) and `renamed` (first post under the name it has now), `release` (about it, subject/actor, by its
maker: a source that is the maker (0144 B1), a site whose name is the maker's, or one of its own release/demo/work
hosts; a family's versions at their first post about them), `first_outside` and `outside` by month (everyone else;
a post with a current 0131 post edge back to one of its posts counts, the vLLM-style link), `story` (Mark X and IX
blocks of the page), `later` (0163, judged development), `back` (0136, judged development). One line a post (the birth
post that is also the maker's release says so in `also`). Ranked: birth, renames, first and last release, first
outside, stories, later/back, the rest; the 8 most important `top`, "All N events" opens the rest; shown when 2+
events.

## D. The post page's before (`timeline.before_post` → `/api/markx/posts/{id}` field `before_timeline`)
For each subject thing of the post (not an org or person; at most two): up to 3 earlier events, the birth (or earlier
name / rename), the last release before it, the first outside mention, oldest first, skipping posts the 0131 Before
list holds. A separate field beside `before` (whose rows carry edge labels); the panel shows both under "Before"
("In <name>'s timeline").

## Tests
`backend/insight_core/tests/test_markx_timeline.py` (rules without a database; components, renames, timeline, before
on the test database), `test_markx_validate` (the kind set), `scripts/tests/test_markx_worker.py` (`TestRename`),
`frontend/src/components/markx/timeline.test.tsx`.

## Measure on real data (not done here)
See the report: components (preview counts, 40 read), renames (candidates by rule, 40 `renamed` read, misses from
shared addresses), timelines (30 biggest + 20 random), and the cases in `plan/research/lab/cases.json`.
