# 0266 — A source's track record: first, signal or noise, opened; and "switch off?"

Status: **built** (2026-11-21, Stealth v10.32). Stalker features 4 and 7 (`plan/INSIGHT_mark_x_stalker_plan.md`): the
reader's part of 0118 (first or repeat, lead time) and of 0093 (noise per source), from tables INSIGHT already keeps.
Rumors confirmed or wrong (0118's rest) and 0158's claim cards are not in this issue.

## What the reader gets
Per source and per voice, over the last 30 days, on `/markx/sources` (sortable columns) and on the source's page (a
"Track record, last 30 days" card, each number with its formula, its n and its cases):
- **Firsts:** stories of 2+ voices begun in the window where its post came first (within a minute of the earliest
  other voice); **first share** = firsts / its stories of 2+ voices begun in the window (too few under 5);
  **lead** = the median hours from its first post to your next source's post (too few under 3 timed firsts).
- **Signal share:** its posts in a News row, a story of 2+ voices or a topic track (a "track" or "joined" place).
  **Noise share** = the rest. Both too few under 10 posts.
- **Opened share:** its posts you opened (`post_interactions` opened or reading_session; not `read_at`, which "mark
  all read" also sets).
- **Switch off?** A list on the Sources page and a line on the source's page for an enabled source with a noise share
  of 90%+, no first, under 10% opened and fewer than 3 other voices linking it (cited_by, 90 days: a source others
  link is an origin; what it adds reaches you through them). A suggestion only: no button, nothing is switched.

## Rules
- **The stories are News's:** Mark X's current members of unmerged stories when Mark X News has a written run, else
  Mark IX's `story_posts`. A member of no source of yours (a saved page) is no voice and never first (0263).
- **Voices, not channels:** a source's own voice's other channels never count as "your next source".
- **Dates (0072 D):** a date alone (day precision or 00:00:00 UTC) counts as that day's earliest timed member of its
  story. It is first only on an earlier day than every other voice, and a first where either side is a date alone is
  not in the lead (its hour is unknown). Without this rule a date-only site was "first, 12-16 h ahead" on stories it
  printed the same day as others.
- A story begun before the window gives no first, but its window posts are still signal.

## Where it lives
`markx/source_stats.py`, the stats job's module (0132 B), deepened: `record_inputs` (three reads),
`RecordIndex` (the stories indexed once per run), six new signals in `SIGNALS`, `switch_off` (a rule over the stored
rows). Stored as `source_stats` rows, like every other card, by the nightly job; the pages read rows only. No
migration, no new table, no new job.

## Measured (server copy, 2026-11-21; private rows: `plan/research/0266-source-track-record/`)
- **Time:** the record's reads 0.13-0.19 s, its compute 0.06-0.11 s for 392 sources (5,472 story members, 16,175
  posts in 30 days), inside the stats job's 30 s (load 9-12 s, compute 20 s; peak RSS 1.6 GB, the job's own child
  process, unchanged). Over 200 ms in all, so it stays in the job, not per request.
- **Coverage:** 288 of 392 sources posted in 30 days; 138 have 10+ posts (signal and noise shown); 178 are in a story
  of 2+ voices, 77 in 5+ (first share shown); 128 were first at least once; 55 have a lead (3+ timed firsts).
- **Signal overall:** 2,933 of 16,175 posts (18%) are in a News row, a story of 2+ voices or a track. Noise share
  among the 136 enabled sources with 10+ posts: p10 32%, median 79%, p75 95%, p90 100%.
- **Top 10 by firsts, read:** the sense is right. Large tech news sites and makers' own newsrooms lead (makers 74-85%
  first share, a lead of 0.7-8 h over your next source, often the maker's own X accounts); a high-volume aggregator
  site and a large subreddit come first often but are mostly noise (signal 9-10%); a leaks account is first on 17 of
  36 with a 3 h lead. One aggregator (HN) carries the original page's time; its firsts say little (the older
  first_to_report card already flags it).
- **Bottom 10 by signal, read:** every one is 0% signal with 0% opened: personal essay blogs, X accounts of opinion,
  a hardware hobby site, a vendor newsroom, a weekly YouTube roundup. Right for news; wrong as a verdict on long-form
  writing the owner may keep for Classics, which is why the suggestion needs few linkers (it spares 12 of 32: research
  institutes, a government newsroom and the essayists others cite).
- **Switch off?:** 20 sources suggested (32 before the linked-by rule). The 10% open rule spares none today (the
  reader opened 228 of 16,175 window posts); the highest opened share among the 20 is 9%.

## Not done
- Per topic (0118's split by entity), rumors and their outcomes, accuracy of numbers: they need Stealth's "came true"
  links.
- 90-day window and trend (this 30 days against the last): one more window would double the rows; not asked.
- The owner's check: the suggestions against the owner's own keep or quiet choices on 30 sources (0093's measure).
