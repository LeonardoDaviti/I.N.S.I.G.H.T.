# 0175: Stored happenings and the event-type seam (Stealth v10.16, slice H)

From the v10.16 architecture plan (slices: "1. Stored happenings + the event-type seam — first, everything reads it").
Anchors, units and the closed event-type guide all read what a post reports; this slice gives them one stored key and
one accessor, behaviour-identical. Names below are invented.

## Built

### 1. Stored happenings (`mx_happenings`, migration 0118)

- **The table**: one row per (post, key as computed): `post_id`, `guide` (the reading's, read-v2), `reading_call`,
  `version` (KEY_VERSION + a hash of happening.py and event_types.py), `basis`, `read_group` (the event-type seam's
  group of the reading's main action, before parties refine it), the key — `grp` (NULL: the reading names no
  happening), `parties` (resolved roots or `name:<name key>`, stored sorted, read as a set), `stage`, `at` (the stated
  day), `money` (sorted amounts) — and `computed_at`, `checked_at`. View `mx_happenings_now`: the newest row per post.
  No key to a Mark IX table; nothing is deleted.
- **The basis** is the sha256 of every input `key()` reads: the code version, the reading's call (a reading is never
  changed once written) and each current mention's (guide, n, root) — root = the pin's entity, else the mention's,
  through the current redirects. A merge, an undone merge, a pin, a relink, a new mention set (or a cite answer's
  appended mentions) all move it.
- **Writes**: a changed key (or a post's first) adds a row; the same key from a new basis updates that row's basis in
  place (so a row exists per distinct key in a post's history, never a duplicate). `tasks.record` stores the key when
  a read-v2 reading, an entities answer or a cite answer lands (`happening.note`).
- **Reads**:
  - `happening.keys(cur, ids)` (Pairing's source, and the interface for anchors): reads the posts' mentions and roots,
    compares the basis with the stored row, and computes again only where it moved (or no row): it returns exactly what
    the recompute returns, by construction. It skips loading the readings' JSON and re-resolving every name.
  - `happening.stored(cur, ids)`: the newest rows as they are (a reader that can take a key one sweep old).
  - `happening.compute(cur, ids)`: the recompute (0166's `keys`), nothing stored.
- **Pairing's happening source** (`happening.pairs`) reads `keys`; its pool is the read posts in the window whose
  stored `read_group` may make a key of the paired groups (a row of older code, or none, is always in the pool and is
  keyed then). Before, the pool filtered the readings' raw `main.action` by a verb list.
- **Backfill** (`happening.backfill`, resumable): each candidates-job run (`jobs._happenings_step`, in a savepoint: a
  failure is logged and the candidates run stands) keys up to 2,000 read posts with no row of this code, newest first,
  then re-checks the 500 rows checked longest ago (a merge since moves their keys); `counts.happenings = {keyed,
  checked, left}` in the job's last result. The source is correct without it (it validates what it reads); the
  backfill is for raw readers (`stored`) and to keep the source's checks cheap. A code change of happening.py or
  event_types.py changes `version`: the backfill keys every post again (in place where the key is the same).

### 2. The event-type seam (`markx/event_types.py`)

The interface (what a caller must know):

- `of_posts(cur, post_ids) -> {post: EventType}` — posts with any reading the seam reads; `EventType(type, origin,
  group, stage)`: `type`/`origin` the closed event type and who tells it (today read-v3's `event_type`/`origin`),
  `group`/`stage` the happening group of the main action (today read-v2's action through ACTION_GROUPS + SYNONYMS).
- `types_of(cur, post_ids) -> {post: (type, origin)}` — every post asked, (None, None) when none read.
- `of_stories(cur, {story: [post ids]}) -> {story: type or None}` — folds.story_type over the posts with a type, at
  their own date.
- `typed_sql(post_column, types_placeholder)` — a SQL condition "has one of these types" (same guide order), for a
  query over a window too wide to fetch each post's type first.
- `action_group(action)`, `from_reading(reading, guide)` — the pure mapping, for a caller holding a reading.

Which guide gives what lives only here: TYPE_GUIDES (first with a reading wins), GROUP_GUIDE, and TYPE_GROUPS (a
future closed type -> group, preferred over the verb; empty until the guide change is measured).

**Consumers moved** (each test runs its old query, copied verbatim from 784d232, beside the new one on 12 seeded random
worlds: same output):

| Consumer | Read before | Now |
|---|---|---|
| happening.py's groups | its own ACTION_GROUPS / SYNONYMS / `_group`; the pool's raw `main.action` verb list | `event_types.action_group`; the pool by stored `read_group` |
| folds.story_folds (fold of a story, News page) | LEFT JOIN read-v3 `event_type`, `origin` | `types_of` |
| built._load (how a story is built) | the same join | `types_of` |
| built._neighbours ("came true" stories) | JOIN read-v3, `event_type = ANY(leak + news types)` | `typed_sql` (one query over the window, as before) |
| news_sections._types (a row's kind in the sections question) | read-v3 join + folds.story_type | `of_stories` |
| Discover's main-source stories (services/discover_main_source._stories) | LEFT JOIN read-v3 | `types_of` |

Read no event type (nothing to move): the source judge (it reads source_stats' reading `kind` and mentions), back and
later (their type lists are entity types; back/later move to anchors in slice 3), the decision run (reading `kind` and
`events`, not types).

### 3. The decision run's incremental state

Stored happenings feed no decision directly: they reach the decisions only as `mx_candidates` rows (source
`happening`, written by the candidates job while `pairing_happening` is on), which the decision run reads whole every
run, incremental or full. So nothing is added to the post stamp or the state key, and incremental == full holds as
before (test_markx_incremental, unchanged, passes). tasks.py is in incremental.CODE_MODULES: this slice's hook makes
the first decision run after deploy full.

## Tests

- `tests/test_markx_happenings_stored.py`: rows (reading, mentions, link each add a row; same key in place; a merge to
  one party: a no-key row; a read-v3 reading stores nothing); the backfill (resumable, newest first, `left`, the sweep
  catching a merge, a code change keying again in place, the job's step in a savepoint); **equivalence** on 10 seeded
  worlds through link / merge / pin / undo / new mention set / relink / merge: 0166's code (verbatim copy,
  `tests/legacy/happening_784d232.py`), `compute`, `keys` and `stored` give the same keys, and Pairing's happening
  source makes the same candidates with the old code and the new (default groups and every group). Breaking the basis
  (roots left out) fails it (checked).
- `tests/test_markx_event_types.py`: the mapping is happening's old one (every verb, case, padding); the pool groups are
  the old verb lists; `of_posts` by guide; every moved consumer equals its old query on 12 seeded worlds (pointing the
  seam at the wrong guide fails it: checked).

## Not done here

- Measuring the backfill's time on a server copy (one step = 2,000 posts' mentions and readings; the sweep 500).
- The closed event-type field (slice 2) fills TYPE_GROUPS / TYPE_GUIDES; anchors (slice 3) read `keys` / `stored`.
- Two differences from 0166 that no test world shows, both by design: the mentions are read in (guide, n) order (0166
  read them in table order: in practice insertion order, n's; only a post naming one name twice could tell them
  apart), and the pool's group test trims the action as the key always did (0166's pool compared `lower(action)`
  untrimmed, so a padded verb made a key for a new post but never joined the pool).
