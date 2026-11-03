# 0075 — Real-data checks on every change: the cases run, the rules hold on every post, every change shows its diff

Status: **built** (branch `issue-0075-realdata-checks`, not merged, not deployed) for v9.15; spec, written 2026-11-03 by the Mark X session on the owner's request ("analyze why bugs keep appearing … propose specs"). Filed as 0075 (owner, 2026-11-03: "yes please"), with its merge rule approved. Build it **first** in v9.15, before the incremental story job merges, so that job and the date-only fix are checked by it.

**Constraints:**
- **Download nothing.**
- **No real channel names in committed files.** The runner and the rules are generic code; the cases, the baselines and the reports stay in `plan/research/lab/` (private, gitignored).
- **Copies only:** a `pg_dump` of `insight_lab`, never the live DB or the server.

## Why
- **The same areas keep coming back:**
  - titles had fix sections in five versions running (13 sections in 0068–0072);
  - dates and times appear in six issues (about 11 sections).
- **Each fix was measured on its own target:** a count before and after, plus 30–40 posts by hand. Nothing showed what else it changed. When a count was taken (D2: "56 titles change against D1"), it was by hand.
- **Real data can't check anything automatically today:**
  - `cases.json` holds 90 judged cases from the owner's data, but their state is prose ("pass (9.12, 0070 B, lab copy …)") and nothing runs them;
  - the 0071 stamps see only a made-up sample, and their own docstring says "what the sample doesn't show, its stamp can't see";
  - so only the reviews see real shapes, after the build.

## A. The cases run
1. **Each case gets a machine-checkable `expect`** next to its `note`, by kind:

   | kind | `expect` | Checked by |
   |---|---|---|
   | `title` | `{"post": url, "title": exact}`, or `contains` / `not_contains` | the title every page shows (`post_title` today) |
   | `reader_text`, `full_text` | `{"post": url, "contains": [...], "not_contains": [...]}` | the post page's shown text |
   | `same_story`, `not_same_story` | the posts are (or aren't) in one story; optionally `via` a reason | the story tables after the story job |
   | `same_post`, `thread`, `tree_edge`, `continues` | the expected relation | the trees and threads the reader shows |
   | `label` | the label's exact text | the API field the page renders |
   | `search` | `{"query", "expect": [urls], "top": N}` | the search service |
   | `discover`, `voice`, `not_new`, `ops` | written per case | the matching service |

   - `now` becomes `pass` | `fail`, plus `since` (the version) and a short `why`. The prose stays in `note`.
2. **The runner:** `backend/insight_core/scripts/check_cases.py --db <dsn> --cases <path>`.
   - It calls the same services the pages call, not SQL written again.
   - It prints one line per case.
   - It exits 1 if a case marked `pass` fails, and lists cases that now pass but are marked `fail`.
3. **Coverage is visible:** a kind the runner can't check yet is listed as "not checked", never silently skipped.

## B. Rules that hold on every post
1. **The invariants:** a file of checks over the whole copy, not a sample. Each has a name, a count, and up to 5 example ids written to the private report. Starting list:
   - **Titles:**
     - empty where the post has words;
     - longer than 300 characters;
     - ending in an address, or on a word that led to one;
     - nothing but a label and an address;
     - different between the feed and any other place (D1's check, kept).
   - **Shown text:**
     - repeats its title;
     - keeps a feed's footer lines;
     - keeps a quote card's byline.
   - **Dates:**
     - a date after the fetch plus a day;
     - after v9.15's fix, a post with only a date marked first over a timed post of the same day.
   - **Stories:**
     - the incremental job against the full rebuild, row by row (0072 A's oracle becomes a standing check);
     - a story with no posts;
     - a story id that changes in a rebuild with no new posts.
   - **Labels:** a shown count that differs from the counted rows ("629 in News").
2. **Baselines:** main's counts are recorded for each version in the private report. A count that rises fails the check unless the spec names the reason.

## C. Every change shows its diff
1. **`realdata-diff`:** runs main's code and the branch's code over the same copy. For each derived thing it reports how many changed, by kind of change, with 20 random examples each (id, before → after). The derived things:
   - titles;
   - the start of the shown text;
   - link titles;
   - roundup flags;
   - story membership: joined, left, split, merged;
   - News rows and their "first";
   - Classics;
   - Discover.

   The report goes to `plan/research/lab/checks/<branch>-<date>.md`.
2. **The hand checks come from the diff.** The 30 checked by hand are drawn across its kinds of change, not only from the class the rule targets. That's how a change's side effects get seen before review.

## D. Fresh data, not only the 30 October copy
1. When a version is ready, the owner makes a read-only dump of the server's newest two weeks of posts. Agents never touch the server.
2. Each version's check runs on the lab copy and on the fresh copy.
3. A rule tuned on posts before a cut-off date is confirmed on posts after it.

## E. One command before every merge
- **`scripts/realdata-check.sh <db>`** runs A, B and C, in at most 10 minutes on the lab copy.
- The report's path goes in the merge notes.
- It runs locally, because real data can't go to CI.

**How builds merge (approved by the owner, 2026-11-03):**
- **One area at a time.** The story job is v9.15's area; the post parse (0076) is v9.16's.
- **Parallel slices list the files they touch,** and two slices don't share a file. The story is D4's Discover names, deferred because the file belonged to the memory work.
- **A move that should change nothing ships separately** from a change in behaviour, and its diff must be 0.
- **Nothing merges into main unless `scripts/realdata-check.sh` passes** on the lab copy, with its report in the merge notes.

## Done when
- On main, every case marked `pass` passes, and the runner lists the kinds it doesn't check.
- Main's invariant baseline is recorded.
- Replaying D2 over D1 shows its 56 changed titles; that proves the diff works.
- The incremental job's identity check runs as one of the invariants.
- The command takes at most 10 minutes on the lab copy.

## Not in this issue
- New rules or fixes.
- CI.
- Mark X's models. The same runner and diff later score a model or prompt change against the owner's labels; this is the start of Mark X's F0.7 (labels, the benchmark as a regression suite, shadow mode).

## Built (2026-11-04, branch `issue-0075-realdata-checks`)

Each item is its own commit on main 24d9c4b. Not merged and not deployed. Nothing was fetched or downloaded: the code ran mounted on a local `insight-backend:lab-*` image. It was measured on scratch copies of `insight_lab` (41,637 posts), on the copy's own clock (its last fetch, 2026-10-30). The cases, the baseline and the reports are in `plan/research/lab/` (private); this file names no channel or post.

### A. The cases run
- **The format:** `backend/insight_core/checks/case.schema.json`.
  - `now` is `pass` | `fail`, with `since` and `why`; the judged prose stays in `note`.
  - `expect` is a list of assertions. Each has a surface (`post`, `row`, `feed`, `news`, `origin`, `search`, `discover`, `classic`, `stories`), a path into its answer, and one test (`equals`, `contains`, `has_post`, `count`, …).
  - Posts are named by address, or by a source and words of the title.
- **The runner:** `python -m insight_core.scripts.check_cases --db <dsn> --cases <file>`.
  - It asks the services the pages ask (`PostDetailService.get_post_by_id`, `attach_stories`, `NewsService.news_on`, `ReaderService.search` and `list_posts`, `StoriesService.discover`, `NewsService.classics_on`), not SQL written again. Only story membership reads `story_posts` and `story_mentions` directly.
  - Every connection it opens is read-only (`checks/readonly.py`): a service that tried to write would fail.
  - It prints one line per case. It exits 1 when a case marked `pass` fails, and lists the cases marked `fail` that now pass.
  - Coverage is visible: a kind it can't check (layout, a start's order of events, the doctor, Mark X targets), or a case with no `expect`, reads "not checked" with its `why`.
- **The cases file** was rewritten (privately): 74 of the then 90 cases have an `expect`; `partial` became `pass` or `fail`, each with its `why`.
- **On main:** 60 pass, 14 fail (all marked `fail`), 16 not checked. **Every case marked `pass` passes.**
  - Not checked, by kind: date 1, deploy 1, layout 1, mark_x_target 1, not_same_story 1, ops 2, reader_text 3, same_story 2, same_story_when_followed 1, source_doctor 1, thread 1, voice 1.
  - Two cases another session added since read: one marked `pending` is an error (the schema says `pass` | `fail`); one has no `expect` yet.

### B. Rules that hold on every post
- **The runner:** `python -m insight_core.scripts.check_invariants --db <dsn> [--baseline main.json] [--allow name=reason]`, read-only.
  - One parallel pass reads every post through the app's own `post_title` and `reading_text` (`checks/derive.py`).
  - The invariants' own address, label and footer patterns are written apart from the rules they measure, so a change to a title rule can't also move its own measure.
- **The invariants:**
  - **Titles:** `title.empty_with_words`, `title.over_300`, `title.ends_in_address`, `title.ends_on_lead_word` and `title.label_and_address`.
  - **Titles, the feed against every other place:** `title.places.classics_stored`, `title.places.trees_roundups`, `title.places.news` and `title.places.discover`.
  - **Shown text:** `text.repeats_title`, `text.feed_footer`, `text.quote_byline` and `post.unreadable`.
  - **Dates:** `date.after_fetch` and `date.date_only_first`.
  - **Stories and labels:** `story.empty`, `label.story_voices` and `label.news_voices`.
  - **The story job, on a scratch copy only** (`checks/job_checks.py`): `story.rebuild_identity` and `story.id_changes`, from a second full rebuild with no new posts.
  - **The incremental job's identity:** `story.identity` calls the incremental job's own check (`insight_core.scripts.story_identity:check`, its slice). It is pluggable by `--identity module:function`, and reads "not measured" on a version without it (main today).
- **Main's baseline:**

  | invariant | count | of |
  |---|---|---|
  | title.empty_with_words | 2 | 41,637 |
  | title.over_300 | 0 | 41,637 |
  | title.ends_in_address | 11 | 41,637 |
  | title.ends_on_lead_word | 18 | 41,637 |
  | title.label_and_address | 6 | 41,637 |
  | **title.places.classics_stored** | **1,780** | 41,637 |
  | title.places.trees_roundups | 0 | 3,857 lines |
  | title.places.news | 0 | 101 lines |
  | title.places.discover | 0 | 1,000 articles |
  | text.repeats_title | 2,361 | 41,637 |
  | text.feed_footer | 0 | 41,637 |
  | text.quote_byline | 0 | 41,637 |
  | post.unreadable | 0 | 41,637 |
  | date.after_fetch | 2 | 41,569 dated |
  | date.date_only_first | 44 | 1,400 stories with a first post |
  | story.empty | 0 | 1,820 |
  | label.story_voices | 3 | 1,815 |
  | label.news_voices | 1 | 27 |
  | story.rebuild_identity | 0 | 11,170 rows |
  | story.id_changes | 0 | 1,820 |
  | story.identity | not measured | |

- **What it caught on main:** `title.places.classics_stored`.
  - The story job stores a classic's title for a stored post through `NewsService._citations`. Its `stored` map calls `display_title(title, content)` without the HTML (`services/news_service.py`; `NewsRepository.stored_posts` doesn't select it). Asked for every post, 1,780 would store a title the feed doesn't show.
  - On today's 20 stored-post classics the two agree, and the Classics page reads the post's own title at read time, so no page shows it yet.
  - The fix belongs to the incremental-job slice, which owns those files.

### C. Every change shows its diff
- **`checks/snapshot.py`** records what a version derives:
  - every post's title and the start of its shown text;
  - link posts' link titles;
  - story membership, roundups and origins;
  - the News rows;
  - the Classics table and page;
  - Discover's suggestions and archives.

  Each part is guarded, so an older checkout snapshots what it has and says what it lacks.
- **`checks/diff.py`** compares two snapshots by kind of change, with 20 random examples each:
  - titles: runs on, cut, an address came or left, other words;
  - membership: joined, left, split, merged, gained or lost posts, role or parent reason.
- **`checks/table_rows.py`** compares the story tables of two copies row by row (for a move that must change nothing).
- **The proof, replaying 0072 D2 over D1** (`--titles-only --base 80f262d --head 39f13ba`): **56 titles change**, as D2 measured. An address came 20, runs on 19, an address left 16, cut 1. Text starts change 21, link titles 0. It took 38 s.

### D. Fresh data
Not built here: it waits on the owner's dump. The script takes any copy's name.

### E. One command before every merge
- **`scripts/realdata-check.sh <db>`** compares this checkout (or `--head <ref>`) against `--base` (main).
  - It dumps the copy once (read only) and restores it into `<db>_check_a`, then file-copies that to `_b`.
  - Each version's code runs over its own copy, in containers it names, both at once: migrate, a full story job, snapshot, invariants, cases, job checks.
  - It writes the report and its JSON to `plan/research/lab/checks/<branch>-<date>.md`. It exits 1 on a broken case, an invariant that rose without a named reason, or a step that produced nothing.
  - It removes only its own containers (by name) and scratch copies.
  - `DEPLOYMENT.md`, "Before a merge", says how to run it.
- **This branch against main:**
  - **PASS.** Every derived thing changed 0; every invariant is the same; no case changes state.
  - **Time: 342 s (5.7 min)**, with the machine loaded by other sessions (load average about 40). The dump took 9 s, the restore 88 s, the file copy 42 s, and the two checks at once 3 min 22 s.
  - Restoring both copies with `pg_restore`, in parallel, took 523 s on a quieter machine, and 1,500 s under load (the restores waited on WAL writes). That's why `_b` is now a file copy of `_a`.
- **Tests:** `test_realdata_checks` (21): paths and tests, the verdicts (broken, fixed, error, not checked), the invariants' patterns and the baseline rule, the diff's kinds, the scratch-only and read-only guards (in a subprocess), and refs and story assertions on the database. The backend suite: **1,323 tests OK** on an own `_test` database.

## Left open
- **The News title leftover** (`title.places.classics_stored`, 1,780): fixed with the incremental job, through `post_fields.post_title`. The invariant should then read 0, and the diff shows Classics' stored titles changing.
- **Time:** the restore is the largest step. On a very busy database server it can still pass 10 minutes. Reusing a kept, already-restored copy (`--keep`) would save about 2 minutes; not built.
- **The 16 cases not checked:**
  - 6 need a browser, the API's start or a failing fetch: layout, deploy, ops, the doctor, a Mark X target.
  - The rest have no surface yet: a page style, a page's date format, the post page's list, a count over the copy, or a Mark X case with no rule to check.
- **`text.repeats_title`, 2,361:** most are one-line posts whose text is their title. The pages may want to show no text for them; this is a measure, not a fix.
- **D (fresh data):** the owner's dump of the server's newest two weeks.
