# 0132 B (+ C1, C3) — Stealth v10.6: the source analysis page, every number with its evidence

Status: **Built (B, C1, C3)** on branch `worktree-agent-ab884513e8f0f7db0` (off main a250184), not merged, not pushed
(2026-11-08). C2 (channel profiles) is not built: the owner hasn't decided. The spec is `0132-voices-and-source-analysis.md`.

## Built

1. **Storage: migration 0081.** `source_stats (subject_kind source | voice, subject_id, signal, value jsonb, n,
   evidence jsonb, computed_at)`, one row per subject and signal. It also lets `mx_tasks.subject_kind` be `source` (the
   stance question) and `mx_labels.item_kind` be `stance` (the owner's right / wrong); both CHECKs are rebuilt from what
   they allow now plus the new value (0078's way), so other branches' values stay whatever the merge order.
   - A new run writes over a subject's last row. These are numbers made again from rows that are all kept (posts,
     stories, News, readings, Classics, answers); nothing they count is touched. If the owner wants their history (to
     watch a source change), it is an append table and a `valid_to`, one line in `write`.
2. **The stats job** (`markx/source_stats.py`, `Runner`, started by insight-ingestion's scheduler in
   `run_scheduler.py`): only while Mark X is on. It looks every 5 minutes and runs:
   - nightly (a start between 02:00 and 06:00 UTC, once a day; and never more than 36 hours apart);
   - after a regroup: when Mark IX's story job wrote `full_at` (a full run or a rule change's rebuild finished) after
     the last stats run;
   - never while the story job holds its lock or a rebuild is in progress or due (`jobs.mark_ix_busy`);
   - in a child process of its own, killed after 900 s; a failed run is tried again after an hour.
   - Its state (the last run's time, rows, subjects, peak memory, error) is kept in `mx_settings source_stats_job`,
     and `GET /api/markx/sources` shows it.
3. **The signals**, per source and per voice (`SIGNALS`: card, one-line formula, "too few to tell" threshold, what n
   counts), each with its evidence posts:

   | Signal | Formula | n / too few below |
   |---|---|---|
   | channels | its channels, the same address added twice (flagged), related voices (`voice_links` when present) | — |
   | role | the role rule (below), its line, 3 example posts; staff or beat says "needs a bio" | read posts / 5 |
   | own_share | 1 − reposts / posts, 90 days (a repost: "RT by", a row its source reposted, on X another author, a kept Telegram forward) | posts / 10 |
   | forwards | its posts that are later near-copies (5-word shingles, Jaccard ≥ 0.5) of another voice's post, 90 days | posts / 10 |
   | root_share | its story posts with no parent / its story posts (every stored story) | stories / 10 |
   | perspectives | the current Mark X perspective labels of its posts | labels / 20 |
   | first_to_report | stories with 2+ voices where it was the earliest voice (a day-precision date counts as noon; within a minute is a tie) / its stories with 2+ voices; each story with who came next or first and how much later; HN and platforms flagged "carries the original page's date" | stories / 10 |
   | solo_share | its posts in no story with 2+ voices / its posts, 90 days ("nobody else in your sources covered this") | posts / 10 |
   | news_yield | its posts in News / its posts in the News window; Mark X News' newest written run when there is one, else Mark IX News; "new source" under 30 days | posts in the window / 10 |
   | cited_by | distinct other voices whose posts (90 days) link its posts or its addresses; own channels excluded; Classics pointing at it; the bias note | always shown |
   | kinds, languages, media_only | reading kinds of its read own posts; languages and media-only posts (under 40 characters of text, title under 15), 90 days | read posts / 10; posts / 10 |
   | per_week, age | posts in 90 days / weeks (since it was added, when later; at least one week); first stored post, date added, a first date before its platform existed flagged | — |
   | audience | median YouTube views per video, as fetched; else "no audience data" | videos / 5 |
   | reputation | inside your sources only: cited by, Classics, first to report | — |
   | stance | grounded patterns of its newest stance answer | posts of 250+ characters / 15 |

   - **Another voice** is a source's voice when it has one (0132 A), else the source; Mark IX's voice key when a post
     speaks for someone else (a Reddit author, a page's site).
   - **Addresses** (for cited by and "the same channel twice"): a platform account (x.com/, t.me/, youtube.com/channel/,
     github.com/), else the publication (host without www); a site's own address also from the host 50%+ of its posts
     live on. Platform address shapes only, no list of sites. Reddit, HN and 10+-author sites are never matched by
     address (their address is everyone's).
4. **Voices, defensively.** When `voices` and `sources.voice_id` exist (slice A's 0080), a voice gets rows over all
   its channels' posts and the list shows one row per voice (and per source with no voice); otherwise per source only.
   Tested by creating both in a rolled-back transaction.
5. **The role rule** (`markx/source_role.py`), in the spec's order: platform (Reddit; 10+ authors), curator by links
   (a site whose own pages are under 30% of 10+ posts), official (`official`: the source itself as subject, actor or
   venue in ≥ 30% of ≥ 5 read own posts, matched by a distinctive name word, the squashed name, handle or site label,
   or the acronym), staff or beat (≥ 50% of ≥ 5 read posts about one other maker), reposter (own share < 60%, 10+
   posts), curator (roundups ≥ 30%; or link posts ≥ 40% on X or Telegram), commentator (≥ 40%), reporter (≥ 50%),
   independent author, too few to tell. **Slice A writes step 3 in `utils/source_roles.py`; this one is our own
   copy: dedupe at merge.**
6. **The page.** `/markx/sources` (the list: name, role, posts a week, first to report, News yield, cited by, solo
   share; sortable by any column, too few always last; no overall score; on a phone each row is a block) and
   `/markx/sources/<voice or source>` (a tab per channel, a voice's own first; one card per signal, each with its
   number, n, the one-line formula, clickable evidence posts and "too few to tell (n of what; m needed)").
   Routes `GET /api/markx/sources`, `GET /api/markx/sources/{id}`, `POST /api/markx/sources/stance/label`
   (`markx/sources_api.py`, one include line in `api.py`). Both read source_stats rows only.
   - **Default sort: by name.** The owner's open decision 4 (their labels of the top and bottom 20) should set it.
   - **The Channels card shows no Join / Not the same / Related buttons:** they are slice A's (voices). It shows each
     channel, the same channel twice ("Disable one?") and related voices.
7. **The `stance` kind.** Guide `stance-v1` (the lab's `sources_bias_v1.md`, which names no source). `tasks.plan_stance`
   (the `stance` planner): one task a source a month, over 15 random own posts of 250+ characters of the last 90 days
   (seeded by the source and the month), Reddit never; priority 1000 (after everything else). The input holds no ids:
   the stats job finds each numbered post back by its text. `validate`: a quote naming a post the question doesn't show
   is an error; `validate.stance_grounded` keeps a pattern only with 2+ exact quotes (folded) from 2 different posts,
   at most 4, and the card shows only those, Experimental, with ✓ right / ✗ wrong (mx_labels kind `stance`, a = the
   task, b = the source, note `pattern <n>`; a second tap sends undo).
8. **Part C1, switch `INSIGHT_MARKX_READ_LAST20` (off by default).** `tasks.plan_last_posts`: `read` and `entities`
   tasks for the last 20 posts, whatever their date, of each source with fewer than 10 read posts; it runs after the
   window's planner whenever the worker leases `read` or `entities`. Never more than 20 a source.
9. **Part C3, switch `INSIGHT_TELEGRAM_FORWARDS` (off by default).** The native Telegram adapter keeps a forwarded
   message's header in `metadata.forwarded_from` (channel id, user id, name, post, date: what Telethon's `fwd_from`
   has; no extra request). The stats count such a post as a repost. Nothing in Mark IX reads it.

## Measured once, on a scratch copy of `insight_server_1105_mxreal_sep` (migrated to 0081, dropped after)

- **The stats job:** 255 subjects (no voices table), 4,590 rows, **4.5 s, peak memory 226 MB** (the process's
  max RSS, Python and its imports included).
- **The page:** `GET /api/markx/sources` 25–43 ms (255 rows, 129 KB); `GET /api/markx/sources/<id>` over all 255:
  median 3 ms, p95 5 ms, max 11 ms (largest 50 KB). Under 300 ms.
- **Roles:** official 16, staff or beat 9, commentator 32, independent 35, reporter 11, curator 11, reposter 4,
  platform 4, too few to tell 133. The lab had 12 official over its reading; this copy has more read posts. Two of the
  16 are an individual's blog and a company employee's blog matched by name or site label: for the owner's review.
- **Too few to tell:** first to report on 211 of 255 (as the lab: 36–57 sources have 10 stories), News yield on 150,
  solo share on 142, role on 134.
- **Planners (rolled back):** `stance` would ask 81 sources this month (about $0.22 at the lab's $0.0027 a call);
  C1 would read 1,918 posts (and as many entities).

Not run, as asked: `scripts/realdata-check.sh` and the lab's re-measurements.

## Unverified until the server runs it

- Stance with real Haiku on this page (the lab's 91/93 exact quotes were on its own runner).
- Telethon's real `fwd_from` on forwarded channel posts (the adapter reads only attributes; tested on fakes).
- Voices with slice A's real schema (`voices.name`, `voice_links` columns are read defensively).
- The perspectives card: the copy has no current perspectives.

## The worker

`scripts/markx-worker` is not edited. To answer stance, add `stance` to `--kinds` and ask it alone per call:
`--kinds read,read3,entities,alias,alias2,collide,check,join,pair,merge,perspective,sheet,connect,card,headline,briefing,translate,stance --per-call merge=1,collide=6,perspective=1,sheet=1,read3=5,stance=1`
(or the same two additions to `DEFAULT_KINDS` and `PER_CALL`).

## Tests

`insight_core.tests.test_markx_sources` (the role rule's order and official; stance quotes; C3; the schedule; each
card's formula and threshold on synthetic sources; voices; the routes; the stance planner and labels; C1),
`test_markx_validate` (the kinds list gains `stance`), every `test_markx_*`, `test_telegram_kind`,
`test_run_scheduler`; `frontend/src/components/markx/sources/sources.test.tsx` (the list, sorting, too few, empty,
phone; a page's cards, evidence, stance labels, a voice's tabs, not computed). `npm run build` passes its bundle check
with little room: the feed route is +0.99% against its 1% budget, so another slice's api.ts block may cross it at
merge (this slice's block is types and three small methods; the pages are their own chunks).
