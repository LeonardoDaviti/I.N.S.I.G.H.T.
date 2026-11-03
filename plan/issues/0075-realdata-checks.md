# 0075 — Real-data checks on every change: the cases run, the rules hold on every post, every change shows its diff

Status: **spec (draft)** for v9.15, written 2026-11-03 by the Mark X session on the owner's request ("analyze why bugs keep appearing … propose specs"). Filed as 0075 (owner, 2026-11-03: "yes please"), with its merge rule approved. Build it **first** in v9.15, before the incremental story job merges, so that job and the date-only fix are checked by it.

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

**How builds merge (the owner's call, proposed):**
- **One area at a time.** The story job is v9.15's area; the post parse (0076) is v9.16's.
- **Parallel slices list the files they touch,** and two slices don't share a file. The story is D4's Discover names, deferred because the file belonged to the memory work.
- **A move that should change nothing ships separately** from a change in behaviour, and its diff must be 0.

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
