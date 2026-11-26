# 0283 Job memory: why each background job peaks where it does, and the cuts

Measured 2026-11-26 on the read-only copy (`insight_srv1119_check_a`, data to 2026-11-19; production is ~1.5x its
size), current main, writes patched out. Production's last peaks against checks/resources.py budgets:
decide 956 (600), stories 543 (300), discover 459 (300), entities 408 (600), main_source 330, candidates 272,
news 259 (400), tracks 249 (400). Base cost of a job (Python + imports): 48-55 MB.

## Causes, in one line each
- **Python objects cost 3-9x the raw data**: rows held as dicts/tuples of uuid and hex strings (tasks 82 MB vs ~9 raw;
  answers 106 vs 28 jsonb; links 168 B each).
- **Whole tables pulled into Python to answer small questions**: 366k link rows for 87-308 "same owner" pairs
  (`SourceFacts._linked`, rebuilt by stories, news, discover, candidates, originals, pairing); 282k link rows for 144
  platforms (`DR.platforms`); 287k mentions to rank 200 entities (`entity_list`); 132k judge tasks to find the dirty
  few (`decide` refresh); 101k title rows for name surges (`judge_names`).
- **State held past its use**: decide's reading state stays alive through the entities stage (+300 MB stage on top).
- **Freed memory never returned**: jobs sharing a process (news → entities → tracks → unread → main_source → discover)
  start from the last one's leftovers; `_job_main` resets the peak but never trims. The recorded peaks of later jobs
  are partly inherited.
- **Roundups and footers inflate story context**: 651 latent.space roundups hold 47% of the near links; footer
  links with 300-546 holders pull thousands of posts into every batch.

## The cuts, ranked (saving / risk / proof)
| # | Change | Jobs | Saving (MB) | Risk | Proof |
|---|---|---|---|---|---|
| 1 | `SourceFacts._linked` decided in SQL (one EXISTS over the asked pairs) | stories, news, discover, candidates, originals, pairing | -160..-175 transient each | low | 87/87 pairs identical (done on the copy) |
| 2 | `gc.collect` + `malloc_trim` before each job's `peak.reset()` in `_job_main` | every kept view | -50..-150 inherited; honest peaks | none | results untouched |
| 3 | Entity list counted in SQL, only the top 200 loaded | entities, the API's live list | -300 (397 → 103), CPU 2.1 → 0.3 s | low | 200/200 items identical but `stories` (see bug) |
| 4 | `DR.platforms` streamed one host at a time | discover | -270 | low | result dict identical (done) |
| 5 | decide: settle `save`'s diffs after the reading, drop tasks/inputs before the entities stage | decide | ~-230 | low-medium | dry diff of mx_inc_* rows |
| 6 | decide: dirty set and task lookups in SQL, not all 132k tasks | decide | ~-160 transient, -130 held | medium | `incremental.digest` old vs new |
| 7 | decide: answers read a page at a time; TEXT_KEEP 6000 → 2000 | decide | -80..-150; -85 on full runs | low | digest |
| 8 | stories: free context before `news.update`; stream `judge_names` | stories | -85..-90 | low | write_* arguments diff over several seed windows |
| 9 | news: build "all" once and filter to "differences"; no full texts for members/headlines | news | -75..-95, CPU -45% | low-medium | kept bodies byte-equal |
| 10 | stories: compact post rows (link texts only where read, interned targets, streamed load) | stories | -45..-100 | medium | write_* diff + recompute(full) oracle |
| 11 | discover: `_todo` and `DR.kept` read only what is used | discover | -60..-90, -35..-50 | low-medium | work() output equal |
| 12 | candidates: burst's `load_posts` narrowed by a SQL superset | candidates | -50..-80 | medium | candidate set equal |
| 13 | decide: entities tail as its own job | decide | -300..-400 off the peak | medium (later snapshot) | needs two disposable DBs: owner's call |
| 14 | stories: roundup/hub keys skipped in `holders` | stories | -100..-150 (est.) | needs owner decision | recompute(full) diff |

Expected after 1-12: decide ~350-450, stories ~350-400 (300 with 14), discover 150-200, entities ~250, candidates
70-90, main_source ~130, news ~170. The machine's peak is the largest job (jobs run one at a time): ~950 → ~450.

## Bugs found on the way
- `entity_list`'s `stories` per entity is nondeterministic: `Counter.most_common(3)` breaks ties by row order; two
  runs of today's code differ on 79-82 of 200 items. Fix: tie-break (count desc, story id).
- `Jobs.stories` reads its peak after `after_stories` (originals + scout/research web reads), so 543 MB mixes the
  batch with unmeasured web reads (J2: record before, or run the web part in its own process).
- Kept views' recorded peaks inherit the previous job's RSS (fixed by #2).

## Scripts (outside the repo)
/tmp/mxmem (decide, news), /tmp/memh (stories, entities), /tmp/memprobe (discover, main_source, candidates).
