# 0190 — One owner per decision: dates, event-type lists, round-ups; dead code (v10.17)

Status: **built** (branch `v1017-owners` from v1016; the frontend part on `v1017-owners-fe`, cherry-picked). Not
merged, not pushed, not deployed. Migration **0130**. Measured on a scratch clone of `insight_ru_show` (49,384 posts,
copy of 2026-11-05; 211 round-ups with an issue time, 51 posts with `surfaced_at`), dropped afterwards. Names below
are invented or left out.

Owner rule: deepen the owning module, no parallel paths, no added memory.

## 1. A post's date: Pairing owns it

### The problem

`pairing.post_date` / `ordinary_date` had 3 users; 115 inline `COALESCE` date expressions in 4 orders were spread
over ~45 modules, so 0181's round-up issue time reached only the modules that asked Pairing, and nothing said which
order meant what.

### Built

`markx/pairing.py` ("the dates") names every meaning, each with the spec that sets it:

| Function | SQL | Meaning, spec | Who reads it |
|---|---|---|---|
| `post_date(a)` | issue time, else ordinary | Mark X's time (0166, 0181) | Pairing's windows, back, anchors, happenings, units' typing; now also the entity timelines, the entity page's mentions, the News page's "subjects today / this week" |
| `ordinary_date(a)` | surfaced, published, fetched | the post's own date: the feed's sort key (indexed, 0037), the planners' and lease's order and windows (0176), every task input (0128: a changed input is a new question), what the issue time is made from | the reader, every planner, tasks, the lease, story windows, tracks, research, labels, handles |
| `published_date(a)` | published, surfaced, fetched | 0128's "published": the order a story's lines are shown in | built, folds, News rows' lines, the seam's `of_stories`, graph G2 |
| `ix_date(a)` | published, fetched | Mark IX's time (StoryPost.t, 0111's News window, Discover, statistics) | db/repo_*, Mark X News's window, surges, identity's mention times, the source judge |

Also `post_date_within(a, lo, hi)`: a `post_date` window that bounds the own date by the attach row's issue reach
first, so the feed index finds the rows (exact: an issue time is within `issue_reach` of the own date, units._times).

Every inline expression was replaced by the function whose meaning it had (about 90 calls in 40 modules). A converter
rewrote them mechanically; a check substituted each call back and compared every string with v1016's: of 45 strings
in the modules it could align, the only differences are the intended ones below; the hand-edited files were read by
hand. Left inline: the Voice slice's files (`db/repo_stories.py` 3,
`db/repo_voices.py` 4, `markx/source_stats.py` 2), pinned by count in the guard until that slice merges.

### Sites whose output changes (measured, both code trees on the same scratch copy)

- **`news.entities` (the News page's "subjects today / this week") → `post_date`.** Correct by 0181 and the glossary
  (a round-up's time is its issue's). 17 subject mentions on 15 round-ups with an issue time move. At 6-hour clocks
  over 21 days (84 clocks, 168 lists): 25 lists differ at 18 clocks; 22 rows' counts change (posts −1 or −2, voices
  0 or −1: the round-up now counts at its later issue time, outside the window), 7 rows enter the top 30 and 7 leave.
- **Entity timelines (`timeline.lines_of`, `_linking_back`, `before_post`) and the entity page's mentions
  (`entity_views._rows`, `_examples`) → `post_date`.** Correct by the same rule. On the copy no round-up with an issue
  time has a linked mention or a post edge, so the entity list (7 clocks) and the queue are identical; on other data a
  round-up's mention moves by its issue shift (mean +6.8 h, −48 to +42 h, 0181).
- **`scout.followed` (a scout's source precision "since it was followed") `(surfaced, fetched)` → `ordinary_date`.**
  "Since followed" is the posts dated after the follow; the old order counted a followed source's archive (fetched
  after the follow, 0167, published before it). 0 scout rows on the copy: no change measurable here; on the server
  the archive's posts leave the precision.

Every other site keeps its output (its order was its meaning). Not changed, decided per site: the planners, lease and
task inputs keep `ordinary_date` (0128: a changed input asks again; 0176); a story's shown order keeps
`published_date` (0128 measured it: 2 of 2,469 members differ); Mark IX keeps its own time (39 posts differ from
`published_date`: undated posts with `surfaced_at`); identity's mention times stay Mark IX's (they become stored
`first_seen`); research, labels, rename, person and track pages keep `ordinary_date` (display and queues; candidates
for `post_date` once measured).

### Speed (migration 0130, EXPLAIN ANALYZE on the scratch copy)

- `ordinary_date` windows already use `posts_feed_order_idx` (a planner page: index scan, 0.2 ms).
- `ix_date` had no index: `posts_ix_date_idx` on `((COALESCE(published_at, fetched_at)) DESC, id DESC)`, with
  `ANALYZE posts` in the migration (without statistics the planner kept the sequential scan). Mark X News's window
  posts 21.6 → 0.8 ms; Mark IX News's window 16.3 → 0.85 ms (both a bitmap scan of the new index). 2.0 MB.
- `post_date` is not indexable (the issue time is looked up in `mx_roundups`); through `post_date_within`:
  `news.entities` 50.1 → 2.4 ms (the feed index, then the post date on 519 rows), the same rows.
- The server has ~3x the posts.

Side effect: pairing, tasks, news, repo_news and stories_service are in `incremental.CODE_MODULES`, so the first
decision run after the deploy is a full one (as after any change to them).

### Guard

`tests/test_dates_owner.py`: a grep over `insight_core/` (tests aside) fails on any `COALESCE` with two post-date
columns as consecutive arguments outside pairing.py (the Voice files pinned by count); the four meanings' SQL; the
feed's and 0130's indexes are on the exact expressions; `post_date_within`'s form.

## 2. Event-type lists: the seam owns them

`markx/event_types.py` makes every list from `schemas.EVENT_TYPES`: `NEWS_TYPES` (a confirmed happening, was
folds.py's copy, read by built), `LEAK`, `NOT_HAPPENINGS`, `ANNOUNCED` (Discover's main source, was its own copy) and
`UNIT_NEWS` (was a copy). The values are identical (tested against the old literals): the differences between the
three were by design (a unit's promotion is `promo`; Discover's main source is never a lawsuit), no bug.
`main_objects(cur, ids)`: the main action's object under GROUP_GUIDE; components.py read read-v2's raw field by its
guide name, now asks the seam. Left raw (not event types, read inside bulk SQL across every guide; moving them needs
a SQL-fragment API, not cheap): search.py's headline/actors/numbers, finders.py's numbers (2).

Side effect: happening.py's key version hashes event_types.py, so the deploy re-keys every post in place (the
existing backfill, 2,000 a candidates run; 0175's rule).

## 3. Round-up: units.py's predicate

Discover's "linked only in roundups" (0067: weighs half in the order) used Mark IX's 3+ anchors rule
(`discover_rules.is_roundup`, its SQL copy in repo_discover). It now reads `units.roundup_sql` (the tag `units.tag`
keeps: the reading says so, or a digest's shape in a digest source). `is_roundup` is deleted (only a test used it).
Discover's kept counts are counted again when the tags move (`units.tags_stamp` in `DiscoverRepository.base`, so a
story run's partial recount becomes a full one then).

Measured (fresh counts, read-only, both trees): round-ups among all posts 7,305 by 3+ anchors → 410 by units (329 in
both, 81 new). Of the 6,976 no longer counted, none is read as a round-up: read ones are reports 332, commentaries 320,
tools 154, other 98; 6,072 unread; 6,814 from RSS sources. Discover's list: 1,233 suggestions both; the same keys but
two whose key changes (a host to its parent site, twice); 1,103 scores go up, none down (fewer voices weigh half);
1,192 rows move (median 54 places, max 263); the top 20 is the same set (one adjacent swap), top 50 shares 48, top
100 shares 95. Discover's tests (test_discover_clean, test_discover_counts) read the round-up from mx_roundups.

Costs: units.py's split version hashes the module, so the deploy re-splits every post once (1,000 a candidates run,
0.5–2 s a step, 0181; a round-up's issue time is made again in the same step). Discover depends on the units backfill
being current: a post not split yet is no round-up.

## 4. Dead and Shadow code

- `later.NEWS_KEY` / `on_news()`: deleted. One caller only filled the Later page's `news` field, always false, which
  the frontend typed but never read (field, type and test fixture removed).
- `anchors.SHADOW_KEY`: off by default (0180: 20% against an 85% bar; 0.8–3.9 s a stage call). The engine and its
  setting stay: `anchors_shadow = true` turns it on. The scratch copy had no row for it.
- `tests/legacy/` (2,424 lines): **kept.** 0166's equivalence was measured on real data (0 of 21,931 rows differ),
  but 0175's happening equivalence only on seeded worlds; and the decision-run and stored-happening proofs compare old
  and new on worlds whose URLs and ids are random each run (the answers hash the task input), so they cannot become
  fixed expected values without making those worlds deterministic first. A slice of its own.
- `pairing.HAPPENING_KEY`: kept, documented as an experiment (off; E1 measured the company groups only).

## 5. Frontend

/blog and /design (frontend/src/blog, frontend/src/design) are dev-only routes (`import.meta.env.DEV`), out of the
production bundle; the bundle gate now fails if any file of them is built. Production gzip: feed route 178,554 →
177,326 bytes, post route 318,915 → 317,872, all chunks 576,170 → 440,828 (74 → 62 files); the baseline is updated.

## Not done

- The Voice slice's 9 inline dates (pinned in the guard).
- The fresh lane's arrival time (`GREATEST(fetched_at, surfaced_at)`) is written twice (tasks.fresh_sql, repo._lease).
- `news.entities` picks a subject's type with an unordered `array_agg` (`(array_agg(m.type))[1]`): which type shows
  depends on the plan (seen when the index changed the plan: same rows, a different type on 73 of 84 lists).
- `built._load` returns a story's members in no set order (no ORDER BY; the event-type equivalence test now compares
  them sorted: 0130's ANALYZE changed the test database's plan).
- Mark IX's "a post with 3+ links is about its first only" (story_rules.ROUNDUP_ANCHORS) is copied as
  `pairing.ROUNDUP_ANCHORS`: a focus rule, not the round-up predicate; story_rules is the Voice slice's.
- The server's data: none of this was measured there.

## Tests run (only the modules touched, a fresh test database each)

test_dates_owner, test_markx_event_types, test_markx_anchors, test_markx_later, test_markx_back,
test_discover_clean, test_discover_counts, test_discover_main_source, test_markx_folds, test_markx_units,
test_markx_timeline, test_markx_pairing, test_markx_happenings_stored: 224 tests, 3 failures on the first run (the
units-table guard read 0130's comment; the member order above, twice), fixed and run again: OK. Frontend (its
branch): typecheck, eslint, the bundle gate, vitest on the touched components.
