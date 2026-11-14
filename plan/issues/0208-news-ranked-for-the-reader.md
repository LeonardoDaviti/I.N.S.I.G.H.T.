# 0208: News ranked for the reader (Stealth v10.19)

Status: **built and measured** (branch `v1019-rank` from `v1018`). Not merged, not pushed, not deployed. Migration
**0141**. The ranked order passed its bar on a held-out window and is News' main order; the reader's fit is computed and
shown but weighs nothing (a Shadow). Exact rows are in the private notes (`plan/research/rank-1019/`).

## The problem (owner, 2026-11-14)

A significant item was in INSIGHT but could not be found. It was a new clustering method from a major lab: it replaces
a classic algorithm, runs 10-45x faster, ships inside a widely used library and has a paper. Over three days it was
covered by:

- one line in a digest newsletter;
- two expert Telegram channels, one of them a full breakdown of the method;
- two Reddit posts. One of them was a link post with no text, and it never joined the story.

Mark X News ranked it 84th of 244 rows. Its score was 3.0, because a row's score is its count of voices and reports.
The top rows were big-lab launches with 20-55 points. The owner: "without already knowing about it, I could never have
found it as relevant and prior."

So News was ordered by loudness. That is the class to fix, not this one case.

## What was built

### 1. Significance of each row (`markx/significance.py`, guide `significance-v1`, kind `significance`)

- **One question per News row.** It shows the row's headline first, then the existing signals:
  - its kind of happening (the event-type seam);
  - its main subjects and their kind (current entities);
  - its coverage: posts, sources and long posts, in buckets, so one more repeat asks nothing new;
  - the kinds of pages its posts link: paper, code, demo, package, model hub (entity_originals' address kinds; no
    list of sites).
- **The members shown.** Up to 6 of the row's posts: the first two, then the longest of the others, one per source
  first. They come from the row's **main story** only. A stray post that another story brought into the row never
  speaks for it (see "Wrong" below).
- **The answer:**
  - `event`: new method / model / tool, release, research, benchmark, product, deal, policy, security, outage, people,
    opinion, tutorial, other;
  - `usable`: now / soon / no;
  - `shipped_in`;
  - `adoption`: widely used library, open code, open weights, API, paper, paper with code, official, benchmark result;
  - `coverage`: expert breakdown / reports / passing mentions;
  - `effect`: 1-5;
  - `scope`;
  - `why`.
- **The guide is sphere-agnostic.** It judges effect on "people who work in the event's field", never AI by name.
- **The score.** `score` maps the answer to [0, 1], effect first. It adds usable now (+.10), a widely used library
  (+.10), open code or weights or a paper with code (+.05), an expert breakdown (+.05) and scope (±.05). The weights
  were set before the measure. Effect alone measured worse (below).
- **When it is asked.** The decision run has a stage `news_significance` after News, in the jobs process. It asks each
  row of the window once. It asks again only when the row's posts changed and its last ask is 6 hours old. It never
  asks while a question waits. It asks at most 120 a run, newest rows first. The asks are kept in
  `mx_news_significance_asks` (task, row, members, time).
- **The worker** asks 5 rows a call (`PER_CALL significance=5`); `significance` is in its default kinds.

### 2. Fit with the reader (`markx/news_rank.Profile`, `fit`): computed, shown, weight 0

- **Where it comes from.** Over 90 days, it reads what the owner did:
  - read, kept, Later or opened;
  - for each source, its reads against its share of all posts, smoothed by 100 posts;
  - the things the read posts are about: entities, subjects and actors;
  - the posts their topic tracks hold.
- **No model call.** It is computed in the jobs process.
- **Not done: entities the owner opens.** INSIGHT records no entity-page opens. Recording them would be a new write in
  the API.

### 3. The rank and the "Notable for you" lane (`markx/news_rank.py`)

- **The rank score.** `0.6 x significance + 0.3 x coverage + 0 x fit`.
  - Coverage is the old score on a log scale, 30+ points being 1, so loudness still counts, but once.
  - A row not answered yet counts as significance 0.4, the middle.
- **The lane.** Up to 5 rows of the last 7 days with significance 0.7 or more that the order by coverage puts below
  20th.
- **Where it is computed.** `keep` runs in the jobs process, inside the `news` kept-view job (`news.keep_pages`),
  before the pages are built. It writes one `mx_news_rank` row per News row. The rank's inputs are in the page stamp:
  the significance answers, the hour of the reader's newest action, and the switch. So a new answer rebuilds the page
  within the rebuild gap.
- **What the API does.** It reads the kept ranks by row id and orders by them (`NewsService.ranked`). It computes
  nothing.
- **The switch.** mx_settings `news_rank`: `{"order": "ranked" | "coverage"}`, default `ranked`.
  - `/api/news?order=coverage` gives the old order.
  - `?mark=ix` gives Mark IX's News with its own order.
- **The reader.**
  - "Notable for you" is the first part of News. Each lane row's line starts with why it is there ("New method ·
    usable now").
  - A "By coverage" link gives the old order, and "Ranked for you" brings the ranked order back.
- **`/markx`.** Each row shows its significance, its effect and its fit, marked "(Shadow)".

### 4. A link post with no words of its own (`services/originals_service.plan_link_posts`, `markx/tasks.load_posts`)

- **Why it sat loose.** The case's second Reddit post had a title and a link to the project page, and no text. Mark
  X read only its title, so it never joined its story.
- **The originals step, deepened.** There is no new fetcher. Under Collect originals' switch and credit, after the
  entity originals and before the cited pages, the step reads the page a link post shares. This applies to:
  - link posts of the last 72 hours whose link is a page (not a picture or a video);
  - posts with no more than 200 characters of their own beyond the title.

  The page is read as 0123 reads a page and recorded once (`story_originals` kind `linked`, by address). A page stored
  already is recorded with no request. A followed source's page is left to 0114.
- **What Mark X reads.** `load_posts` (Mark X's one text of a post) reads such a post with "[The page it links:
  <title>]" and the page's first 3,000 characters. Its reading, entities, vector and the judge's join all see what it
  shares.
- **The stamp.** `plan_marks.STAMP` adds the page's id once the page is stored. Every other post's stamp is unchanged.
  A test checks this.

## The measure (blind)

### How it was measured

- **The rows.** The server's Mark X News (read-only GETs of `/api/markx/news?all=1`, each post's item and Mark X panel,
  the owner's reading history, sources) as of 2026-11-14:
  - **window a**: the rows begun 2026-11-08..12, 109 rows;
  - **window b, held out**: 2026-11-03..07, 64 rows. It was answered and labelled only after the bar was written down.
- **The labels.**
  - Three labellers (Claude subagents) labelled each window, each from its own shuffle.
  - Each saw the reader profile of the brief, and the rows' headlines, coverage and posts.
  - They never saw a score, a rank or a significance answer.
  - Each picked the 20 rows the reader would want at the top, and marked every row wanted or not.
  - **TOP** = picked by 2+ of the 3. **Wanted** = marked by 2+ of the 3.
  - Agreement was high: 18-19 of 20 shared for each pair of labellers. The labellers are one model family given one
    profile, so this is likely correlated, not independent.
- **The significance answers.** Each row's question was built by the production code (`significance.question`) from
  the server's data and asked of Haiku exactly as the worker asks (the worker's system prompt, prompt and parser).
  All 173 answers passed the server's checks.
- **The fit.** It was built from the owner's reading history before each window (no leak): 177 reads for a, 115 for b.
- **The old order** is the page's: score, then the newest.
- **The bar, fixed before window b.** The ranked order becomes the main order if, on b:
  1. P@20 (TOP) is at least the old order's + 0.10;
  2. P@20 (wanted) is not lower;
  3. pooled over a and b, at least 80% of the lane's rows are wanted.
  Otherwise it ships as a Shadow.

### Old vs new

The new order is 0.6 x significance + 0.3 x coverage. The numbers in brackets are Wilson 95% intervals.

| | window a (109 rows) | window b, held out (64 rows) | pooled |
|---|---|---|---|
| P@20, TOP: old | 8/20 = .40 (.22-.61) | 10/20 = .50 (.30-.70) | 18/40 = .45 (.31-.60) |
| P@20, TOP: **new** | **12/20 = .60** (.39-.78) | **15/20 = .75** (.53-.89) | **27/40 = .68** (.52-.80) |
| P@20, wanted: old | 13/20 | 16/20 | 29/40 = .72 |
| P@20, wanted: **new** | **19/20** | **20/20** | **39/40 = .97** |
| nDCG@20 (TOP 2, wanted 1): old → new | .57 → .82 | .73 → .90 | |
| wanted rows moved from below 50th into the top 20 | 5 (1 TOP) | 2 (1 TOP) | 7 |
| rows that fell out of the top 20 | 10: 1 TOP, 3 wanted, 6 neither | 9: 1 TOP, 4 wanted, 4 neither | |
| the named case | old 22nd of the pool → new **4th**, and in the lane | | |
| Notable lane | 5 rows: 3 TOP, 2 wanted | 5 rows: 3 TOP, 2 wanted | **10/10 wanted**, 6/10 TOP |

The bar was passed before the fix below: on b, P@20 went .50 → .75, wanted 16 → 20, and the pooled lane was 9/9 wanted.
The table is after the fix.

Other orders, on the same labels (P@20 TOP, a / b):

| order | a | b |
|---|---|---|
| significance alone | 13 | 14 |
| effect alone | 9 | 13 |
| 0.5 x significance + 0.5 x coverage | 11 | 15 |
| fit alone | 4 | 9 |
| coverage + fit, no significance | 7 | 10 |
| 0.5 x significance + 0.3 x coverage + 0.2 x fit | 11 | 14 |

- **Significance carries the gain.** The combined score beats effect alone, which supports the score's parts.
- **Fit moved nothing,** or worse. Its weight is 0: it is a Shadow. A generic reader's labels cannot test a personal
  fit, and the owner's own reads are few: 115-177 in 90 days.

### Built right, wrong, missed

The exact rows are in `plan/research/rank-1019/notes_rows*.md`.

- **Built right.**
  - Open-weight model releases, a new method, a formal-verification result, a speech model topping its leaderboard,
    benchmarks of agents and hardware, a training handbook.
  - They moved up from 22nd-79th. The named case is 4th and in the lane.
  - Down went: office-product launches, acquisitions, an airline policy, a conference announcement, data-center
    politics, executive moves.
- **Wrong, then fixed.**
  - The held-out window's biggest launch (old 1st, TOP) was answered effect 1, "posts mostly about a CEO's scandal".
    Its row had swallowed long off-story posts (0203's chaining), and the question showed the longest posts.
  - The fix: the question shows only the row's main story's posts (`significance.core_of`). After it, the launch's
    significance is .95 and it is 1st.
  - 16 of 173 questions changed. They were asked again (their answers are re-measured, so window b is no longer
    strictly held out for this change).
- **Wrong, still.** A 24-hour office-suite outage (window a, 15th, labelled neither): effect 3, "disrupting
  businesses". The guide's "people in its field" reads an outage as practice-relevant.
- **Missed** (TOP, still outside the top 20): 9 rows in a, 4 in b.
  - **Just outside, effect 3** (21st-33rd):
    - an open model claimed to run on laptops;
    - a weight-repair method;
    - an interpretability report;
    - a coding-tool feature;
    - a coding agent's 99% cost cut;
    - a benchmark-wording study.
  - **Effect 2** (39th-74th):
    - a practical multi-repo agent pattern;
    - a local/hosted model router;
    - a hobbyist multi-GPU build;
    - a cheaper model replacing a bigger one in production;
    - an unconfirmed local-inference app;
    - a forensic claim about training chips;
    - an allegation that a model was benchmaxxed.
  - **Why.** The guide weighs "changes how many practitioners work", so small practical tips and unconfirmed claims
    land at 2. Lifting them for this reader is fit's job, and fit has no measured signal yet.

## Cost, time and memory

- **Haiku.** The measure's answers were 39 calls (5 rows a call) for 189 questions, the reruns included: **$0.088**,
  326k tokens in, 72k out (about 1.7k in and 0.4k out per row).
- **Worker cost per day on the server.**
  - About 14 new rows a day, plus re-asks when a row's posts change (at most every 6 h).
  - At most ~40-50 questions a day: **about $0.02 a day** at the measured cost.
  - The first run after deploy asks every row of the window once: ~420 rows, about $0.20.
- **Jobs process** (a clone of the server copy, `prep_mxreal`; 129 rows):
  - the decision run with the new stage: 62.9 s, peak 202 MB (a full run);
  - the stage asked 120 rows, then 9 at the next run;
  - `news_rank.keep`: **0.13 s, peak 45.7 MB** (+4 MB over the process's start);
  - `news.keep_pages` with the rank: 1.1 s, peak 76 MB.
  - At the server's ~420 rows, keep is linear in rows (well under 1 s).
- **API.** `/api/news`, ranked vs by coverage: peak RSS 72.0 vs 72.4 MB, +0.08 s. It reads ~420 small rows by id.
- **Link posts.** On the copy's last 72 hours: 22 pages to read (some will come back "no article") and 2 stored
  already. That is about 7 a day, inside the originals credit.

## On, Shadow, off

| what | state |
|---|---|
| significance questions (decision run stage, worker kind) | on |
| News ordered by rank (Mark X's rows, every scope) | **on** (switch `news_rank.order`; `?order=coverage` for the old) |
| "Notable for you" lane | **on** (with the ranked order) |
| fit with the reader | **Shadow**: computed, kept, shown on /markx, weight 0 |
| link post read with its page | on, under Collect originals' switch and credit |
| Mark IX's News, the old score | unchanged, one click away |

## Not done

- **The link-post join effect** is not measured. It needs the worker's readings of the read pages and a decision run.
  After deploy: count the link posts whose page was read, and how many of them join a story within a day.
- **Fit** has no measured signal:
  - entity-page opens are not recorded;
  - the owner's reads are few (115-177 in 90 days);
  - the labels are a generic reader's.

  Next: owner labels on the lane, or measure on the owner's own "read it" signal after the window.
- **Practitioner tips.** A practical tip or setup is judged effect 2-3 and stays at 21st-45th. A guide variant that
  asks "can a practitioner use this today, and how many" separately could lift them. It would need its own blind
  measure.
- **Re-measure on the server after deploy**, with the real-data check on main and a look at the server's News page,
  as for every release.
- **The post page's "in News" line** and Search's News filter still name Mark IX's rows (0205's follow-ups), and they
  have no rank.
