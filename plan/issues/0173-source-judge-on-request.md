# 0173 — Is this worth it? A candidate source judged by the worker, on the owner's tap (spec + built)

INSIGHT v10.15, part G. Owner decision 2026-11-12: no trial follow and no spend cap for new sources; instead "our worker
can understand, on request, whether we actually care about the source or not". Builds on 0148 (the scout's test read,
`markx/scout_reads.py`) and 0149 (E8: the model passes `fit` and fails `reads`, so reads is measured by code). Private
rows: `plan/research/0173/` (gitignored). Names below are invented.

## What it does

- **Where:** a quiet **Is this worth it?** under every Discover row that can be followed (the suggestions in every
  section, each "Other channels" line, "The main source is missing" rows, a Pages row's section or account) and in the
  Add source dialog once the finder found a feed (or the site is read directly) or page watching found articles.
  Nothing is asked before the tap. The owner still decides: Follow is the row's own Follow… (Add source).
- **The test read** (0148's `Reader`, the add path's own): a platform account through its kind, anything else through
  the feed finder, then page watching; up to 10 newest items kept on the judgement row only (never a post, never in a
  feed, nothing followed). With `INSIGHT_DISCOVER_READS=0` nothing is read ("reading the web is off").
- **Measured by code** (`source_judge.signals`), on the owner's own data:
  - linked: how many of your (on) sources' posts link its address (and which, five named);
  - stories of yours that started at its pages (Mark IX origin pages, 2+ voices), and in the last 90 days;
  - its items in your stories: of the items read, how many your sources link, how many started a story;
  - rate from the items' span in hours (10 items in an hour is ~1,700 a week; the scout's day-floored cadence caps
    10 items at 63 a week), the newest item's age, how many are dated; health (0148's: stopped, undated, titles only);
  - **reads** (0149 E8): full text in the feed; else up to 2 of its teaser items' pages read as the fetcher reads them
    (`full_text.read_page`): `full_page` (INSIGHT reads it in full from its pages), `teaser`, or `paywalled` (the page
    states it, 0167's markers); a platform's posts are `short` (complete as posted), a channel's `video`;
  - languages; **repeats**: its items you already have from an on source (the same address, or the same title of 20+
    characters in 60 days) and your sources on its site;
  - **rewriter marks**: high rate (140+ a week), many languages (3+), never first (no story started at its pages and
    none of its items), rarely cited (1 source or none); the pattern needs the high rate and two more;
  - followed before: a source at this address you turned off (its posts, opens, stories it was first in).
- **The reader** (`interests`): the described tracks (first), the sources read most in 90 days by opens, what those
  reads are about (Mark X's subjects and actors), the folders, how many sources are followed. Ordered by what is read
  most, so the owner's main reading (AI news) leads without naming it.
- **The question:** kind `source_judge`, guide `source-judge-v1`, subject `source_candidate` (a = the judgement), one
  candidate a call, priority -5 (leased first; the worker's default kinds start with it). Input: CANDIDATE, MEASURED,
  THE READER, ITEMS (`[i<n>] <date> · <title>` and 500 characters). Answer `{verdict: follow | maybe | skip, reasons:
  1-4 one-line, examples: 1-4 item ids, fits: bool, original: low | medium | high}`: the schema
  (`schemas.SOURCE_JUDGE_SCHEMA`) and `validate._source_judge` (a reason one line and said once; each example an item
  the question shows, named once). A free-text answer is never valid. The guide forbids judging reads from the texts.
- **The cache:** per candidate address (no scheme, no www, no trailing slash). An answered judgement is shown again
  for 30 days without a read; asking again (**Ask again**) reads again and asks again only when the items read differ
  from the ones the last answer judged (`items_sig`); else that answer stands ("Asked again: no new items, the same
  answer"). A judgement that could not be read, or whose question the worker gave up on (its task failed), is read
  again on the next tap. A judgement being made is shown, never asked twice. Nothing is deleted (a new ask is a row).

## Built (Stealth v10.15, branch `v1015-source-judge`)

| Part | Where |
|---|---|
| Table `mx_source_judgements`, `mx_tasks.subject_kind` may be `source_candidate` | migration `0116_markx_source_judge.sql` (0114 is v1015-voices') |
| Ask, read, measure, question, answer, view | `markx/source_judge.py` |
| Routes: `GET /api/markx/source-judge?address=`, `POST /api/markx/source-judge {address, again}` (404 while Mark X is off; the read runs in the background) | `markx/source_judge_api.py` |
| Kind, schema, guide, validation, `tasks.record` hook | `markx/schemas.py`, `markx/guides/source-judge-v1.md`, `markx/validate.py`, `markx/tasks.py` |
| Worker: `source_judge` first in `DEFAULT_KINDS`, `PER_CALL source_judge=1`, no tool | `scripts/markx-worker` |
| UI: `SourceJudge` (the button, the wait, the verdict box, the measured fold, Ask again / Try again) | `components/sources/SourceJudge.tsx`, `services/sourceJudge.ts` |
| Placed in Discover's rows and Add source | `SuggestedSources.tsx`, `MainSourceMissing.tsx`, `DiscoverPages.tsx`, `AddSourceModal.tsx` |
| Design | `design/docs/pages/sources.md` (the suggested tab) |

Nothing writes a source: only `mx_source_judgements` and the question (`mx_tasks`). Not touched: `decide.py`,
`incremental.py`.

## Tests

- `test_markx_source_judge` (28): the kind, guide and schema; validation (an example the question doesn't show, twice,
  a reason on two lines or said twice, a free-text answer); the cache key; the rewriter marks; the items' ids newest
  first; the question's parts. Reads by code on stubbed pages (FakeHttp): full in the feed asks nothing, a platform's
  posts, a paywalled page, a page holding nothing longer, a page holding the article. On the test database: the tap
  reads, measures and asks one `source_judge` question (subject `source_candidate`, priority below 0) and writes no
  source, post, folder or link; the measured signals from your data (two sources link it, a story started at its page,
  an item linked, an item you have, the rate); a source you turned off; the reader in the question (a track first,
  reads most, folders); the answer shown with its reasons and example items; an answer naming an item not shown is
  refused; a failed question says so and is asked again; a read that never finished is read again; unreadable says why and asks nothing; reads off; the cache
  (30 days without a read, after that a new read; a judgement being made is not asked twice; Ask again with the same
  items keeps the answer and asks nothing; with a new item asks again); the routes (the tap and the look, 400 without
  an address, 404 while Mark X is off).
- `test_markx_validate`, `test_markx_storage`, `test_markx_api` (MX_TABLES) for the kind, the table and the migration.
- Worker (fake-claude): `TestSourceJudge`: the first default kind, one a call, no tool.
- Frontend `components/sources/sourceJudge.test.tsx` (6): the lines in words; the tap only (no request before it), the
  wait; the verdict, reasons, example links, the measured fold, Ask again; nothing while Mark X is off; in Add source
  once a feed is found (asks about the feed, adds nothing); on "The main source is missing" rows.

## Measured (offline, before deploy; no model called)

A labelled set of 25 real sources: 15 the owner follows and opens, 10 the owner turned off (4, among them the SEO farm
turned off on 2026-11-12) or clearly bad (6: five stopped 2016–2024, one titles-only feed). Each as if it were a
candidate: the server copy of 2026-11-05 cloned to a scratch database, the source turned off inside a rolled-back
transaction, its 10 newest stored posts as the recorded test read (the farm, not in the copy, from the live server's
`GET /api/feed`); tracks and folders from the live server's GETs. Exact rows: `plan/research/0173/notes.md`.

- **The inputs are complete:** 25 of 25 questions carry 5–10 items, the MEASURED block and THE READER block; 2,500–8,400
  characters (median ~7,400; about 0.7–2.3k tokens plus the guide's ~0.7k).
- **Code alone flags 9 of 10 bad and 0 of 15 kept:** 7 by health (6 stopped, 1 titles only), 2 by the rewriter
  pattern (the farm: ~1,390 items a week, 1 source links it, never first; a turned-off X account: ~400 a week, none
  links it). The tenth (a turned-off subreddit, 31 a week, newest 24 days) is the model's (fits, original).
- **The rate had to be hourly:** the first run gave 63.0 a week to the farm, the X account and the busiest kept
  subreddit alike (10 items, a day floor). Hourly: 1,386 / 401 / 317. The kept subreddit stays clear of the pattern
  (19 of your sources link it).
- **"never first" is weak alone:** it fires on 24 of 25 (Mark IX knows an outside origin for 424 of 1,936 stories,
  mostly makers' own sites). It counts only next to the high rate and "rarely cited".
- **Repeats** found 0 of 25 (the farm rewrites titles): kept as a line, not a mark.

## Cost per judgement

One call a candidate: ~1.5–3k tokens in (guide + question), ~100–200 out. On the worker's measured spend (2026-11-08
log, Claude Code headless, Haiku: ~$0.18 per million tokens in with the cache, ~$0.49 per million out, fitted on its
`read` calls) about **$0.001 a judgement**; at Haiku's list price ($1 / $5 per million) about $0.004. The test read
costs requests, not money: ~3–15 for the finder and the items, plus up to 2 article pages.

## After deploy: the live measurement (steps)

1. Deploy (migration 0116 runs at start). Mark X on. Check a production page: Discover shows **Is this worth it?** on
   a suggestion; Add source shows it after the finder found a feed.
2. On the server, tap it on the 25 labelled candidates where they can be asked (the turned-off ones through Add source
   on their address; the kept ones are followed, so ask on 15 Discover suggestions the owner then labels follow /
   maybe / skip instead) and on 10 fresh Discover suggestions. Each reads in seconds and waits for the worker.
3. Run the worker by hand once: `scripts/markx-worker cycle --kinds source_judge --batch 1 --batches 40 --parallel 3`
   (the owner's device, its own token file). Note the cost from the worker's log (`event: call`, `kind: source_judge`).
4. Read every answer: `GET /api/markx/source-judge?address=<address>` (verdict, reasons, examples, measured). I judge
   them first (memory: I review first), then the owner labels only my flags. Report as built right / wrong / missed with
   the exact rows (address → verdict, reasons → label), private, in `plan/research/0173/live.md`.
5. Bars: a turned-off or clearly bad source called `follow` 0 times; a kept one called `skip` at most 1 of 15; every
   example an item it relied on (the owner opens two per answer); no reason that contradicts the measured `Reads:`
   line. Below a bar: change the guide (a new id, `source-judge-v2`), never patch one site.
6. Ask again on 5 answered ones the next day: no new items keeps the answer with no call; a new item asks once.

## Open

- The interests summary is computed at each ask (a few queries); cache it if the tap gets slow.
- Item pages are checked only for a teaser feed (2 at most); a watched page whose articles are short says `teaser`
  without a check.
- "Stories it started" reads Mark IX's origins only; Mark X's own first-member stories are not counted yet.
