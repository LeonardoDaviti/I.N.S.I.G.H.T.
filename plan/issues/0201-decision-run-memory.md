# 0201 — The Mark X decision run's peak memory (Stealth v10.17.2)

Status: **built** (branch `v10172-run-memory` from main = v10.17.1, d57aa11). Not merged, not pushed, not deployed.
No migration.

## The problem (the owner's Grafana, v10.17, ~250k entities, ~157k posts)

insight-ingestion spikes to ~4.2 GB at every decision run (every ~5 min on v10.17, every 15 min on v10.17.1), mean
~1.8 GB; insight-db CPU mean ~50%. 0183 measured the entities stage at 1.4 GB peak on the scale copy.

## How it was measured

- **The copy.** A clone of `prep_scale` (main's migrations, 148k posts, 452k candidate pairs, 844k mentions). Its
  synthetic entity names had to be fixed first (below), on the clone only (`plan/research/run-memory-0201/names.sql`:
  each "Name N" a pseudo-word, each "Topic T Labs/Model" the topic's pseudo-word and the suffix). Then one first full
  run (main's code) and the fake worker's 1,816 answers: **the measured state S** (103,171 entities, every mention
  linked, 1,816 judge tasks answered, a kept incremental state).
- **The runs.** Each run in a fresh process as the runner's child does it (`jobs.Jobs.decide`: the candidate finder,
  then `decide.run` in its snapshot), per stage and per step: seconds, Python CPU and **peak RSS (VmHWM, reset with
  `clear_refs` at each stage)**; the clock fixed (NOW = 5 Nov 18:00), PYTHONHASHSEED=0, parallel scans off, LIMIT
  off, the graph backfill without its share (both deterministic), container capped at 40 GB.
  - incremental: `ENTITY_BUDGET` 45 as on the server, on a clone of S;
  - full: `full=True`, entities budget none (the whole nightly pass), on a clone of S.
  The after code reads S's state with the before code's stamp (`incremental.code_stamp` of main's tree), so an
  incremental run is compared with an incremental run (a changed module would otherwise make it full).
- **Equivalence.** Every id default (`gen_random_uuid()`) swapped for a sequence-made uuid on the clones (`det.sql`),
  so the same inserts in the same order get the same ids; then every mx_* table and system_settings digested (row
  count and an order-free sum of each row's md5; durations dropped, timestamps written by the run's own clock masked).
- **Statement time** by stage and call site (a psycopg wrapper): pg_stat_statements is not preloaded on the scratch
  server and the shared server was not restarted for it.
- The machine was shared (load 5-17): seconds swing; peaks and digests are stable.

Scripts and outputs: `plan/research/run-memory-0201/` (private).

## The 30-35 GB full runs on prep_scale: the copy's names, not the code's class

`prep_scale`'s mentions are named "Name 12345" (Zipf over 230k) and "Topic 12 Labs". `names.parse` reads "Name 12345"
as family "name", version 12345: every one of those entities is one family (6,015 live ones after three runs; ~100k
once all are linked). `identity.pool_family` pools a seed with every member of its family, so a full pass's chunk
of 1,000 seeds pools ~10^8 pairs: on main the entities stage grew past 8 GB within 3.5 minutes (stopped there, the
other agent's run reached ~35 GB in 2 h). The server's own 120-day pass pooled ~29k pairs (0183): real families are
small. With name-like names (above) the same first full run of main peaks at **3.1 GB** and its entities stage at
+260 MB over what the reading left. Nothing in this slice changes how a family is pooled (that would change
decisions); `scripts/prep/scale.py` should name its mentions as `names.sql` does before the next rebuild of prep_scale
(not done here: it changes the shared copy for everyone).

## Results (state S, scale copy)

### Incremental run (the 15-minute one): peak RSS per stage, MB

| stage | before | after |
|---|---|---|
| candidates | 156 | 155 |
| load | 118 | 115 |
| questions and decisions | 610 | **490** |
| write / connections | 545 | 426 / 443 |
| graph | 546 | 517 |
| back, later, headlines, news | 546 | 446-492 |
| entities | **682** | **568** |
| surges | 587 | 491 |
| perspectives_plan | 603 | 491 |
| **the run's peak** | **682** | **568** (-17%) |

Python CPU 41.5 → 39.6 s. The incremental state's read of its tasks: 2.2-2.9 s → 0.2 s (the statement 0.84 s → 0.03 s
quiet). Wall seconds were noise-bound (the before run met a 36 s lock wait of the shared server).

### Full run (the nightly one; entities' whole pass): peak RSS per stage, MB

| stage | before | after |
|---|---|---|
| load (the check reading) | 609 | 492 |
| questions and decisions (the full reading) | **2,851** | **515** |
| graph ... news | 2,829-2,836 | 552-618 |
| entities (identity's pass / the addresses' sweep) | 2,805 | 811 / **897** |
| surges, perspectives_plan | 2,805-2,807 | 715-754 |
| **the run's peak** | **2,851** | **897** (-69%) |

The full reading alone, run alone on the quiet machine twice each: 36.5 s, 2,842 MB → **47 s, 462 MB** (+10.5 s: its
renders read their 10.6k texts and their readings when they show them, 15.3k statements instead of 29). The first
full run ever (no entities yet, main): 3,110 MB, 1,117 s.

**At the server's size** (inferred, not measured): the entities stage holds the whole book, ~3.3 KB an entity on main
and ~2.5 KB after (measured on S: book, cached keys, indexes). At ~250k entities the incremental run's peak is
~1.1-1.2 GB on main and ~0.9-1.0 GB after, under the 1.5 GB target either way; the full run's ~3 GB becomes ~1.2 GB.
The 4.2 GB container spike is not reproduced by the decision run on this copy: on v10.17 the Labels queue was built
after every run (0199 measured 3.1 GB for it on the scale copy; v10.17.1 builds it only when wanted, 300 MB here), and
the container's figure includes the long-lived ingestion process (its ~1.8 GB mean). To read after the deploy: the
`decide` job's peak per run (this slice records none; Grafana's spike height at each 15-minute run).

## What was built (each in the module that owns the read)

1. **incremental.world (the full reading)**: reads the posts' texts a page (TEXT_PAGE = 2,000) at a time to make the
   rules' posts, and keeps neither the texts nor the readings: a question's render reads what it shows, in one query
   (`incremental.rendered`, as an incremental reading always did). Was: every post's text (~1 GB of Python strings)
   and every reading (~0.3 GB of JSON) held for the whole run.
2. **embed.current_candidates**: each embedding pair's cosine read by its place among the rows (`WITH ORDINALITY`),
   not keyed by a new pair of strings, and the rows given back one at a time: the run's 452k pairs were held three
   times at once (rows, cosines by pair, the list given back). -120 MB in the questions stage.
3. **identity.Ent and identity.Mention with slots**: their worked-out keys (hk, pk, sq, grams; a mention's key) kept in
   slots, not by `cached_property`, which gave every entity a `__dict__` of its own (75 MB of a 103k-entity book).
   The strings index computes a live entity's trigrams without keeping them (only seeds and their candidates keep
   theirs).
4. **The surges and perspectives read a page's book** (`identity.lazy_book`, 0186) instead of a second whole book:
   decide.run no longer reads any book itself (the entities stage reads its own); `surges.count` reads ahead the
   entities and keys its rows credit, `perspectives.stage` reads ahead as a News page does (`Makers.prepare`).
5. **entity_addresses**: names only of the roots its rows name, and each root's makers from its cluster (no
   `book.members()` of every root at each run).
6. **incremental.refresh**: each judge task's valid calls counted by its own (`mx_calls_task_idx`), not by grouping
   every valid call of every kind (~1M on the server).

Deleted: decide.run's two whole-book reads, the full reading's prefetch of every text and reading, `_makers`'
`members` parameter.

## Proved

- **Incremental run: every table identical** (80 tables: every mx_* table and system_settings, 45 with rows; row digests) between main and this
  branch on two clones of S, Labels queue built after both; the one difference is mx_label_queues.stamp, which is the
  code's stamp by design (`labels.stamp`).
- **Full run: every table identical**, except mx_runs' `counts.run.texts_loaded` (130,545 → 141,324: the renders read
  their texts again; a count of reads, not a decision). The full run's own check reading (`counts.check`) found the
  same snapshot the same.
- Tests: `test_markx_incremental` (a full reading holds no text or reading; a page of 1 and of 1,000 decide the same),
  `test_markx_entities` (the surges count with a page's book as with the whole book); the touched modules' tests and
  the whole suite once (`JOBS=6 scripts/test-backend.sh`: 6 shards, 175 modules, 3,479 tests, OK).

## insight-db time of the run (statement seconds by call site, scale copy)

Incremental, after: the candidate finder's vector neighbours (15 s for 1,000 posts, `pairing.py:564`) and the graph
stage's link reads (15 s, 297 calls) lead, but both are this harness's clock (NOW fixed in the past, the rows' own
times today: every post looks new to them) and are not counted here. The run's own: the 452k pairs' cosines
(`embed.current_candidates`, 6-13 s a run), back's story centres (2-13 s under load), the incremental state's task read
(2.2 s → 0.03 s, cut). Full, after: the nightly pass's paging of mx_mentions_now (`identity.py` relink pages, 65 x
0.6-2 s) and its mention reads (66 x ~1 s).

## Not done

- **The pairs' cosines every run** (6-13 s of database time a run): the same pairs' cosines are computed again each
  run; keeping them needs a column or a table (mx_candidates.score is a real of the cosine when found, not the one the
  run rounds), and 0199 left it for the same reason.
- **back's whole read of Mark IX's stories** (`back.stories`): 13,727 story posts on the copy, a few MB; a story "that
  may fire" excludes only the newest ones (t0 is after the last member), so bounding it saves nothing measurable.
- **The addresses' nightly sweep** reads every linked mention at once (+90 MB, the full run's peak now); reading it a
  chunk at a time changes the order rows are met in, which picks an address's first post: not done without a rule
  for that order.
- **The full pass's page query** (DISTINCT over mx_mentions_now; 0.6 s quiet, 2 s under load, 65 pages): an
  equivalent read of mx_mention_sets is 0.37 s; small, not done.
- The answered `embed_name` read by answered_at (1.7 s a run under load: 296k tasks, no index on answered_at) would
  need an index (a migration).

Not run: the real-data check (one run on main per release, owner 2026-11-09). Clones dropped.
