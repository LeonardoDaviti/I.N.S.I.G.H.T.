# 0243 — the real-data check's invariants at the server's size

Status: built on the v10.26 branch (not merged, not pushed).

## Wrong
`check_invariants` (side.sh's "invariants" step of `scripts/realdata-check.sh`) ran 25+ minutes at 100% CPU, holding
15.8 GB in one Python process, on a copy of the server's database (15 GB, 162k posts, 1.9M Mark X tasks, 1.56M calls),
while Postgres sat idle. It was written on ~49k-post copies.

## Measured (the server's copy, read-only; each invariant in a process of its own)
Seconds and peak RSS of the process tree (the check and its worker processes), before → after:

| invariant | before | after |
|---|---|---|
| `markx.call_invalid` | **2190 s, 15 906 MB** | **32 s, 777 MB** |
| `refs.every_link` | 38.6 s, 113 MB | 4.4 s, 1 534 MB (12 workers) |
| the post facts (`derive.all_posts`, the title/text invariants) | 2.5-3 s, ~2 550 MB | unchanged |
| `title.places.classics_stored` | 17.6 s, 4 045 MB | unchanged (19 s) |
| `discover.*` (each alone; one run asks Discover twice) | ~20 s, 456 MB | unchanged |
| the other 19 | under 6 s, under 300 MB each | unchanged |

The whole check, one process as side.sh runs it: before 2 255 s (37.6 min), peak 16 196 MB (16 182 MB in the main process); after 111 s, peak 4 689 MB
of the process tree (748 MB in the main process; the peak is `classics_stored`'s 12 workers while the main process holds
every post's facts).

**Causes.** `markx.call_invalid` read every valid call with its task's input in one `fetchall` (1.55M rows, ~3.5 GB of
inputs, as Python strings and parsed JSON answers: 15.9 GB), then checked them in one process. 90% of a check's time
was `validate.fold` of the input, done again for every entity of an answer (and again by salvage): an entities answer
of 20 entities folded its post 40 times. `refs.every_link` ran `body_hrefs` over every post's whole body in one process.

## Changed
- `checks/invariants.py`: an invariant that runs Python over every row of a large table reads it in shares, one worker
  process each (a hash of the row's key), through a server-side cursor (`_stream`, `_in_shares`; `STREAM_ROWS` 500 a
  fetch): no process holds the table, only the ids it finds. `markx.call_invalid` and `refs.every_link` use it. A run
  whose connection is inside a transaction (a test's uncommitted rows) reads in it, in its own process, so what it
  counts is what that transaction sees.
- `markx/validate.py`: `occurs` and `version_occurs` keep the folded input (`_folded`, `_bare`: an 8-entry cache of a
  pure function). Same answers, the worker's checks faster too.

The invariants' definitions, names, counts, `of` and examples are unchanged.

## Equality
Every one of the 38 invariants run alone, before and after: the `--json` outputs identical except `seconds`. The whole
check, before and after (one process each, the examples sampled in order): identical except `seconds`.

## The other steps (side.sh)
- snapshot (read-only): 26 s, 2 557 MB tree / 742 MB main (Discover 22 s). Its output holds every post: memory goes
  with the posts, by design.
- cases (read-only): 32 s, 464 MB.
- resources: measures the jobs themselves; not run here (it writes).
- job checks (write; not run here, code read): `markx_unchanged` asks the `markx.*` invariants after its decision
  runs, so it had the same 36-minute, 16 GB `markx.call_invalid`; fixed with it. `table_checksums` hashes every non-mx
  table in SQL (no rows in Python). `rebuild_twice` reads the six story tables into Python sets (11k story_posts here:
  small). `story_identity.snapshot` reads 13 derived tables as JSON strings, twice, held together: story_keys (2.3M
  rows), post_links (953k) and discover_addresses (702k) are about 4M rows a snapshot, an estimated 1-3 GB; comparing
  row hashes in SQL would bound it. Not changed: not measured at this size (it writes), left for a run on a scratch copy.

## Left as they are
- The post facts' 12 workers (~200 MB each, mostly imports) and `classics_stored`'s (~330 MB each) set the check's peak
  (4.7 GB tree). Fewer workers (`--workers`) trade it for time.
- Discover's answer is the service's (20 s at this size), asked twice by the check.
