# 0119 Part B — Built (v10.1.1: perspectives inside a story and the story sheet, in Shadow)

Branch `worktree-agent-ad0a9d15a21116376` (from main `8feb8c9`, v10.1). Not pushed, not merged. The spec is `0119-mark-x-v10.1-entities-and-perspectives.md` Part B (its working copy of 2026-11-07) and `0120-perspectives-inside-a-story.md` (v3.2f). Real names, rows and the measuring scripts are in the private `plan/research/0119-build-b/` of the worktree.

## What was built
- **Migration `0074_markx_perspectives.sql`** (0073 left for another branch). Mark X tables only, nothing deleted, idempotent:
  - `mx_perspectives` (story, post, run, member hash, label, who settled it, Haiku's own label, facts with spans, claims, point, before the original, copies folded, facts dropped, call, `valid_from`/`valid_to`);
  - `mx_sheets` (story, run, member hash, sheet jsonb, the merge call, `valid_from`/`valid_to`);
  - `mx_labels.item_kind` may be `perspective` and `fact`.
- **B1-B5, `markx/perspectives.py`**, the decision run's stage `perspectives_plan` (after `surges`):
  - B1: the Mark X stories of the newest written News rows in the News window with 3+ voices; a story is built again only when its member set hash differs from its sheet's; it waits while a member's entities task is open.
  - B2: the lab's `persp32.Story` ported line by line: duplicates and near-copies, the original by links, by the maker, by a page-kind member on the maker's page, by a link post carrying the maker's page (repository and model page titles), one original per page, the source page, "same" by code, published order, "before the original", the address and "written by @x".
  - The maker comes from part A's identity (`Makers`): a mention's stated maker, an org as subject or actor, an entity's maker or ancestors, matched to page owners, accounts and source names by the maker's aliases and handle forms. No word lists or handle maps.
  - B3: task kind `perspective`, guide `persp-v1` = the lab's `persp_v32f_frozen.md` byte for byte (md5 `ee89e27e…`, a test checks it). Its examples were already generic; no name to replace. One task a story, or a group of at most 5 members.
  - A member an answer skips is asked alone; that task is reopened once when it skips it again; then it is given up.
  - `final` is the lab's `final()`: spans occur, facts not about the story dropped, repeated quantities dropped, the label order, a one-line take is `same`; and at most 4 facts.
  - B4: task kind `sheet`, guide `persp-merge-v1` = `persp_merge_v1.md` (md5 `8ce37bac…`). Asked only with 2+ fact lines. The sheet is data: the original or earliest report, the source page, new facts merged with their posts and sources (corrections marked), before the release, unconfirmed claims, opinions, related, "N more say the same" and the copies.
  - B5: a changed row closes the old one and opens a new one; a member gone is closed; an unchanged row is kept.
- **B6, the story view:** `GET /api/markx/stories/{id}` (`markx/perspective_views.py`) and `/markx/stories/:storyId` (`MarkXStoryPage.tsx`, lazy):
  - the header is the lab's sentence until the owner has 50 labels, then the owner's numbers with intervals;
  - the sheet sits above the members;
  - worth opening first, each line with its sign, label, who settled it, new facts one line each with their span, and copies folded; the rest is folded under "N say the same";
  - an opened News row links to it.
- **B7, the label buttons:**
  - ✓ / ✗ on each label; ✗ offers the right label in one tap. `POST /api/markx/labels/perspective`, item `perspective`, a = story, b = post, note = the shown label and row.
  - ✓ / ✗ on each fact (not new / not true to the post / not about this story). `POST /api/markx/labels/fact`, note = "index: text".
  - Labels are `labeller = 'owner'`, `split = 'test'`.
  - The Labels tab's precision view gains "Perspectives and new facts" (`GET /api/markx/labels/perspectives`): the four labels, worth opening, each label's precision, new facts and each fact, with Wilson intervals, against the lab's 70 / 83 / 62.
- **The worker:** the default `--kinds` is read, entities, alias, collide, check, join, pair, merge, **perspective, sheet**, connect, card, headline, briefing, translate. Both new kinds are asked one task a call. The Worker tab lists them, as it lists every kind.

## Measured
All on `insight_server_1105_check_94011_a`, a template copy of `insight_server_1105_mxreal_sep` (the server's 5 Nov data with its 120-day entity answers). `insight_server_1105` itself has no Mark X tables, so it has no maker evidence. Its entities stage ran once, rule merges only, no Haiku. The copy is dropped.

**The port is the prototype** (held-out-4: 74 stories, 148 posts):

| | Result |
|---|---|
| Code steps (kept members, copies, code labels, the reference, original or not) | the same on 74 of 74 stories |
| `final` on the lab's own Haiku answers (f1) | the same label on 136 of 136 members; the same facts kept on 136 of 136; 4 facts dropped, as the lab |
| Scores from the lab's f1, f2, f3 answers through the backend's `final` | equal to the lab's to the digit |

The inputs differ from the lab's on 45 of 74 stories, for three reasons:
- **Links:** Mark IX's `post_links` carry a quoted tweet's address the lab's extractor didn't. That changes the source page on 16 stories.
- **The maker hint** by identity rather than word lists: 26 hint lines differ. It adds a hint for small makers (a blog, a channel) and drops some of the lab's.
- **Titles and texts:** post_parts' text against the lab's reading text, on 12 stories.

Real Haiku on the backend's own inputs, one run as production asks (two runs, to see the noise):

| Run | Four labels | Worth opening | New-facts precision |
|---|---|---|---|
| Backend, run 1 | 111/148 = **75.0%** | 123/148 = **83.1%** | 30/43 = 69.8% |
| Backend, run 2 | 107/148 = **72.3%** | 120/148 = **81.1%** | 30/46 = 65.2% |
| Lab, single runs f1 / f2 / f3 | 66.9 / 70.3 / 71.4% | 81.1 / 83.8 / 87.1% | 57.9 / 62.8 / 61.2% |

- **Worth opening:** within 3 points of the lab (82.1 against 84.0 on average).
- **Four labels:** 4.1 points above the lab's average, outside "within 3" upwards; one run's spread is about 4 points.

**Cost and time** (the first pass on the copy's News window as of 5 Nov 16:44):
- 198 Mark X stories in the News rows, 78 with 3+ voices, 446 member lines.
- Calls: 104 group tasks, 7 solo re-asks (all answered), 60 sheets.
- Tokens: 718,762 in, 427,068 out. Cost: **$0.32**, as the worker reports Claude Code's cost.
- About 5 minutes of worker time at 6 calls at once.
- The stage itself: 0.65–0.82 s while asking, 0.08 s when nothing changed (well inside the 120 s limit).
- **A re-run after one new member** (opened by hand in the largest story): 77 stories unchanged, 1 waiting, 4 tasks, only for that story.

**Haiku spend, all of it:** $0.47. That is held-out-4 twice ($0.15) and the first pass ($0.32), through this worktree's `scripts/markx-worker` against my own lab API with my own token. The cap was $3.

## The reader review (5 stories as the owner reads them; rows in the private `run/read5.txt`)
**Built right (4 of 5):**
- A local-model refresh with 19 members: 18 worth opening, 29 fact lines (benchmarks, speeds, a quant's sizes), the rumour post before it as an opinion.
- A paper story: the saved paper is the original by links; 8 "same", 4 opinions with their points, a reproduction's facts.
- A model-family launch: the model pages are original by the maker's link; 13 facts from the community's tests.
- A frontier-model announcement: a staff post is original; prices and ranks are facts; a benchmark digest is related.

**Wrong (1 of 5):** a 40-member launch story.
- Its earliest text member is another lab's model announcement. Mark X's story holds it, a membership error.
- It became the "earliest report" and the subject. Haiku then called it `original` and 33 of the 34 real members `not_this_story`: 1 worth opening of 40.
- The code takes the reference as the lab does: the first original, else the earliest member with 30+ words.
- A generic fix to measure, not adopted: when no member is the original but a source page is known, the reference is the earliest member that links it; or the subject comes from the story's headline. Either changes the frozen prototype's input, so it needs a held-out set first.

## Deviations and readings of the spec
1. **Spans of 5–25 words are asked of Haiku, never enforced.** The lab's `final()` only checks a span occurs. On held-out-4, 2 of 103 kept spans fall outside 5–25, so enforcing it would have changed the port.
2. **Groups are in published order,** not the lab's sort by member id. The lab's order (and its ties between pages linked as often) came from Python's set order, which differs per process. An input must be the same text every time, so ties now break by address.
3. **Members a call skips:** "asked again alone, at most twice" is one solo task, reopened once (two solo answers), then given up. Those members have no row and show as "not judged yet".
4. **A story is stored when every member is settled.** Its member rows are stored before the sheet's answer arrives. The sheet row carries the member hash that marks the story done.
5. **Copies get no row of their own.** They are listed on their kept member's row (`copies`) and folded on the page.
6. **The story view is a page of its own** (`/markx/stories/<id>`, linked from an opened News row), not inside the News row.
7. The guide test now allows `@x` (persp-v1's placeholder for a repost's author) in the no-handles check.

## Shared files touched (hooks only)
- `markx/schemas.py`: two schemas, two kinds.
- `markx/decide.py`: three lines after `surges`, the stage.
- `markx/api.py`: four routes, appended.
- `scripts/markx-worker`: the default kinds and per-call settings, this worktree's copy only.
- Tests: `test_markx_api.py` (`MX_TABLES`), `test_markx_storage.py` (the table set), `test_markx_jobs.py` (the stage list), `test_markx_validate.py` (the kinds; `@x`).
- Frontend: `App.tsx` (the route), `MarkXNews.tsx` (the link), `MarkXLabels.tsx` (the section), `services/api.ts`, `services/markx.ts`, `labels.test.tsx` (one fake), and the design docs `shell.md` and `information-architecture.md`.
- New files: `0074_markx_perspectives.sql`, `markx/perspectives.py`, `markx/perspective_views.py`, `guides/persp-v1.md`, `guides/persp-merge-v1.md`, `tests/test_markx_perspectives.py`, `MarkXPerspectives.tsx`, `MarkXStoryPage.tsx`, `perspectives.test.tsx`.

## Tests
- Backend: `test_markx_perspectives` 20 (guides, schemas, code steps, final checks, sheet; the stage end to end, a new member re-judges one story, skipped members, waiting, the view and the labels). The full suite ran once at the end: 1,986 tests, OK (1 skipped).
- Frontend: 57 files, 762 tests; the build passes (the feed route +0.43% for one lazy import line).
- `scripts/tests`: 51.
- **Not run:** `scripts/realdata-check.sh`, as the build instructions say; the merge decides.

## Open for the owner
- **Merge before the bar?** The spec says yes, Shadow with label buttons: worth opening about 82%, new facts 65–70% here.
- **The misjoined earliest member** (the reader review) hides a whole big story. Which fix should be measured first: the reference that links the source page, or the subject from the headline?
- **The maker hint by identity** marks small makers (a blog's own post, a channel's own post) where the lab's word lists did not. On held-out-4 the labels didn't fall. Your ✓ / ✗ will show if the hint misleads.

## Handoff
- **Done:** B1–B7 and the worker's kinds, measured as above, committed on this branch.
- **Left:**
  - the real-data check (`scripts/realdata-check.sh`) at merge;
  - the reader review on the real `/markx` after deploy;
  - renumber the migration if 0074 is taken at merge;
  - the main checkout's `scripts/markx-worker` must get this branch's two-line change when the live worker can be paused (the owner's rule: never while it runs).
- **To resume measuring:** the scripts are in `plan/research/0119-build-b/` (`run.sh <script>` runs one in the `insight-backend:i0119b` image against a scratch copy named in `run.sh`). The order is:
  1. `entities_once.py`: link the mentions;
  2. `lab_side.py` on the host, then `port_check.py [answers]`: code and final against the lab;
  3. `make_tasks.py`, the worker, `make_tasks.py answers N`: held-out-4 on Haiku;
  4. `stage_once.py <now> [add-member]`: the stage;
  5. `read5.py`: the reader review.
