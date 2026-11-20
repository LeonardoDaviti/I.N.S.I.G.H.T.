# 0253 — the real-data check fast enough for every release (v10.28)

Status: built on its branch (not merged, not pushed). Measured on a synthetic server-shaped database and on the v10.26
check's outputs; the real-data measurement is the integrator's (below).

## Wrong
A release's check took ~2.5 h on the one server copy (owner 2026-11-19: one copy, never cloned): the export restored
(~16 min), the base side in place (v10.26: 64 min), the export restored again (~16 min), the head side (51 min), the
report. Of each side, the job checks took 37-44 min and 2-3 GB.

Where the job checks' time went (v10.26's `jobs.json`, head / base, seconds):

| part | head | base |
|---|---|---|
| `story.rebuild_identity` (a second full rebuild) | 118 | 144 |
| `markx.ix_unchanged` (Mark-X-off tick, two decision runs, checksums, the markx invariants) | 1043 | 1520 |
| `story.identity` (two full runs, three incremental, two 4M-row snapshots) | 526 | 480 |
| `markx.api_during_run` | 296 | 199 |
| `markx.api_during_rebuild` | 223 | 223 |

The second full rebuild is not most of it: `markx.ix_unchanged` is. Its log shows the Mark-X-off tick (2.7 min, of
which ~90 s the story run's originals and scouts fetching the web: +11 posts, and the invariant counted those writes
as "Mark IX tables changed", 8 on both sides) and then ~22 min with nothing logged: the two `decide.run` calls (no
entity budget: the entities stage's whole pass) and the `markx.*` invariants. Which of them is most of the 22 min is not
measured: this change writes each part's seconds into the invariant's note (`seconds`), so the next run says.

## Changed
1. **One cache, both modes** (`scripts/realdata-check.sh`). The in-place stash (keyed only by the base ref's name) and
   the dump mode's cache are one: `$OUT/base-cache/<key>`, the key the content of the code a side ran (its backend
   tree with the checks package over it, every file hashed), the data (`dump:` the dump as SQL, or `export:` the
   export zip's sha256), the cases and journeys files, the image, `--now`, how the copy was prepared.
   `--in-place <export.zip> <db>` now restores `<db>` itself (db/import_export.restore, at the export's migrations; each
   side migrates), runs the base side only when the cache lacks it, restores again, runs the head side, drops `<db>`
   at the end (`--keep` keeps it). The head side is kept too (unless `--identity`): the next release over the same
   export, whose base is this head merged (the same backend tree), runs only its head: one restore, one side.
   Run a release's check with `--head <ref>` so the next base's tree is the same files.
2. **The job checks** (`checks/job_checks.py`, `scripts/story_identity.py`):
   - `story_identity`: the two states are kept in the copy (an unlogged table per derived table, each row with the md5
     of its text) and compared in SQL (a FULL JOIN of distinct row hashes per table, the tables at once on a
     connection each); only the differing rows come to Python, streamed, shown as before (sorted JSON, five a side).
   - `table_checksums` (`markx.ix_unchanged`, before and after): the same sums, 8 tables at once.
   - `markx.ix_unchanged`'s Mark-X-off tick reads no web, as `resources.py` runs the story job (originals and scouts
     off, `INSIGHT_DISCOVER_READS=0`). **This changes what is checked:** the tick no longer runs the story run's web
     step, and its fetches no longer count as Mark IX tables changed. Separate commit (a9e48e6), to keep or drop.
   - Each part of `markx.ix_unchanged` timed in its note; its `seconds` now include the first checksums.
   - Not changed: the second full rebuild. No equivalent check exists: `story.identity`'s full runs are over held-back
     posts or a moved clock, `api_during_rebuild` stops its rebuild, `job.py`'s deploy check compares a deploy start
     with a full run. Every check is kept.
3. **The restore** (`db/import_export.py`): the valid foreign keys and the primary/unique keys come off for the load
   and back after it (as pg_restore does: a key's index built once, a foreign key checked by one join, not row by row),
   `maintenance_work_mem` the server's own when above 256 MB (the scratch server: 2 GB). `COPY … FREEZE` was
   tried and dropped (no gain measured). The restored schema is the same (a test compares every constraint's
   definition, validity, deferrability and every index's definition).

## Equality
- `story_identity`: on the synthetic copy (4 043 263 derived rows), the old and new compare give byte-identical JSON;
  the module test compares them on rows changed three ways. Rows are told apart by their text in SQL where the old
  compare used Python's JSON: the same, except numbers in jsonb with different trailing zeros (1.10 / 1.1), which SQL
  now counts as differing (stricter), and an md5 collision.
- `table_checksums`: identical dicts, at once and one by one (synthetic copy; test).
- The restore: every table's checksum, every constraint and every index identical to the synthetic source's (but
  system_settings' row the export itself writes after its snapshot: in the source only, as test_export says); test_export.
- The cache: a tiny export through `--in-place`: run 1 (base v1027, head HEAD) ran both and kept both; run 2 with
  `--base HEAD` ran only the head (83 s, one restore), the report naming the cached side.

## Measured (synthetic, on a machine at load 40-47 from other agents)
The synthetic copy (`insight_synth0253_test`, dropped after): 9.2 GB, 162 446 posts (~3 KB text, html, a search
vector), 953k post_links, 2.3M story_keys, 702k discover_addresses, 1.9M mx_tasks (1.5 KB inputs), 1.56M mx_calls,
the story tables at the server's counts; loaded in random order. Its export: 1.3 GB.

| step | before | after |
|---|---|---|
| `story_identity`'s two snapshots and compare (4.04M rows) | 27.1-27.2 s, **2 171 MB** peak | 18.9 s, **39 MB** (one connection a table; serial: 34.2 s) |
| `table_checksums` (45 tables) | 24.1 s | 9.6 s |
| the Mark-X-off tick | 2.7 min on the server's copy, ~90 s of it the web | the web step skipped (not measured here) |
| the restore of the export, whole (machine at load 15-25) | 306, 330, 362 s | 228, 256, 269, 324 s |
| — story_keys' load | 32-53 s | 1.4-15.8 s (then its key, index and foreign key with the others) |
| — after the load | 205 indexes 24-80 s | 149 keys 8.6-10 s, then the 205 indexes 22-33 s, then 116 foreign keys 3.5-4 s |
| story_keys alone, interleaved 3 rounds (COPY, key, index, FK) | 41.7, 47.0 s (305 s at load 48) | 5.8, 5.9 s (FREEZE: no gain, 5.6-5.9 s; dropped) |
| mx_tasks alone, as the restore loads it (COPY only) | 40, 86 s | 19, 26 s |
| a release with the base cached (tiny export) | both sides, two restores | 83 s: one restore, the head side |

The machine ran other agents' suites throughout (load 15-78): single timings vary 2x; the interleaved per-table runs are
the steadier evidence. mx_tasks' COPY inside the whole restore was slower with the keys off in 3 of 4 runs (89-141 s
against 81-124 s) though alone it is 2-4x faster: not explained, and with it the whole restore gained ~20%, not more.

**Estimated release (the server's copy):** before ~147 min (16 + 64 + 16 + 51). After, base cached (the next release
over the same export): one restore (~16 min, less story_keys' 59 s and the foreign keys' row-by-row checks: ~12-14 min
estimated) + the head side (~51 min, less ~2-3 min: the off tick's web, the identity compare, the checksums) ≈ **60-65
min**. Base not cached (a changed checks package, cases or journeys file, image, export): ~130 min.

## The real-data measurement (for the integrator)
On the one server copy's export, with this branch:
1. `time scripts/realdata-check.sh --in-place <export.zip> --base origin/main --head <v10.28 ref> insight_srv1119_check_a`
   — the restore lines (`… keys built`, `… indexes built`, `… foreign keys checked`, `restored … in … s`) against the
   ~16 min before; the jobs.json note of `markx.ix_unchanged` (`seconds`: checksums_before, off, run_1, run_2,
   checksums_after, invariants) says where its 17-25 min goes; `story.identity`'s seconds against 480-526.
2. Then the next release with `--base <that ref>`: "base side cached (…, the head side of …)", one restore, one side.
3. Peak memory of the job checks: `/usr/bin/time -v` on the head container or `docker stats`; before 2-3 GB (the
   identity snapshots: 2.2 GB on the synthetic copy), expected under 1 GB.

## Left
- `markx.ix_unchanged`'s two `decide.run` calls run with no entity budget (the entities stage's whole pass), unlike
  the jobs process (`ENTITY_BUDGET` 45 s, resumed next run). If the parts' seconds show they are most of its time,
  passing the jobs' budget would cut it, and would change what is checked (the decision runs the server runs, not a
  whole entities pass): the owner's call.
- The restore runs in one transaction, so its index builds can't run on several connections; btree builds use the
  server's parallel maintenance workers.
