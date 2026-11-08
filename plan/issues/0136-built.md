# 0136 — Built (Stealth v10.8): Back in the news, in Shadow

Built 2026-11-08 on its own branch, test-first, parts 1–4 of the spec. **Migration 0085.**

## What was built
- **`markx/back.py`** (new):
  1. **The trigger** (no model), ported from the lab's `bk_cands.py`:
     - Old stories are Mark IX stories (`story_posts`) with 2+ sources. The window starts ≥ 14 days after the first post
       and ≥ 7 days after the last.
     - In one 72 h window, posts outside the story from 2+ distinct sources hit one of these:
       - **E:** the story's subject, by exact name key. The subject is ent-v3's (current mention set), the subject of
         2+ members (1 when only one member was read), and of a specific type (model, product, software, paper,
         document, dataset, event, law, other).
       - **L:** one of the story's pages. These are its members' own addresses, pages 2+ members link, and Mark IX's
         origin page. The lab's `norm` drops home pages, social profiles and subreddits. Pages linked or posted in 6+
         distinct ISO weeks (all time) are hubs and don't count.
       - **V:** cosine ≥ 0.70 to the mean of the members' unit vectors, for stories with every member's vector or 2+.
     - The window starts at the earliest E or L burst, else at the V burst. Its posts are every hit inside it, E/L
       first then by date, at most 6. Its triggers are the ones with 2+ sources inside.
     - Rows go into `mx_back`, once per story and window.
     - **A story fires once** (see "Not as the spec reads" below).
  2. **The `back` kind** (`back-v1`):
     - The input is the lab's render: the old story's 4 earliest posts at 300 characters, "(+N more posts)", then the
       new posts numbered, at 500 characters.
     - The answer is a verdict per post. `relation()` is the lab's `bk_judge.rel`: the first of development, retold,
       related, unrelated that any post has.
     - The judge is asked three times (`tasks.record` reopens until 3 valid answers). The majority wins; "unknown"
       when all three differ.
     - `plan` takes the newest window first and adds nothing while 50 are open or leased (`Config.back_open`). It
       runs in the decision run and in the lease (`tasks.PLANNERS["back"]`, marked `# 0136`).
  3. **`page` / `label` / `precision`** for /markx.
- **`decide.py`:** `Config.back_open = 50`. `back.stage` runs inside the existing `connections` stage, right after the
  graph, so no new stage name was added. Its counts are in `counts.back`.
- **`schemas.py` / `validate.py`:**
  - `BACK_SCHEMA` is `{old_thing?, what_new?, posts [{n, about?, verdict (the four)}] (1+)}`.
  - Validation refuses a post number the question doesn't show, and a post with two verdicts.
- **`guides/back-v1.md`:** the lab's frozen `back_v3c.md`, copied byte for byte (md5 `0c748c76…`, checked by a test).
  It names no channel or account. Its only names are public product names in the version examples, left as they are so
  the md5 holds.
- **Migration 0085:**
  - adds `mx_back` (story, members as asked, first/last, window_at, trig, posts, post_trig, task_id, run_id; unique on
    story and window);
  - adds `mx_labels.item_kind` `'back'` (a = the `mx_back` row);
  - Mark X tables only, with no key to Mark IX.
- **API** (`markx/back_api.py`, one include line in `api.py`):
  - `GET /api/markx/back`;
  - `POST /api/markx/labels/back {row, answer: development | retold | related | unrelated | undo}`.
- **Frontend:**
  - `components/markx/MarkXBack.tsx` sits at the top of /markx's News tab (Mark X chunk). It never touches Mark IX's
    News.
  - Each row shows:
    - the old story's headline and date, "back N days later", and what fired;
    - Haiku's old thing and what's new (k of 3 runs);
    - the new posts with their per-post majority;
    - the four label buttons, with undo.
  - The header shows "measured 87% precise (68–96%), about 1 in 8 wrong", the owner's running precision, and the
    candidates and how many are waiting.
  - `services/api.ts` gets one block at the end marked `// 0136`.

## Not as the spec reads
- **A story fires once.** The lab took each story's earliest burst over 4.5 months. I first let a story fire again 7
  days after its last return. On the server copy that made 535 candidates of 197 stories in four months (one story 12
  times), mostly perennial stories, V above all. Once per story gives 171.
- **Posts outside the story** may come from the story's own sources (the lab's `bursts()` counted any two distinct
  sources of non-member posts).
- **A candidate is stored when its burst fires,** with the window's posts up to that run. The lab read the whole 72 h.
  A post arriving later in the same window isn't added.
- **The first run reads 30 days back.** Each later run reads from its last clock less 73 h.

## Tests
- `test_markx_back` (22, new):
  - the frozen guide, the schema and its checks, the lab's per-post combining, the majority and "unknown", `norm`, the
    lab's render;
  - E (another version is another name), L (a page 2+ members link; a page one member links, and home pages, don't
    count), the hub exclusion, V only, E winning over an earlier V burst;
  - the 14/7-day windows; a one-source story, a member and an org subject don't count;
  - one candidate per story and window; 6 posts at most, E/L first;
  - planned, capped, asked three times, shown with the API;
  - unknown not shown;
  - the labels, undo and the running precision;
  - Mark IX's tables byte-identical.
- `test_markx_validate` (kinds set), `test_markx_storage` (mx_back), `test_markx_api` (MX_TABLES).
- Every `test_markx_*` (18 modules): 415 tests, OK.
- Frontend:
  - `components/markx/back.test.tsx` (4);
  - every Mark X test (11 files, 55 tests);
  - `npm run build` (bundle check passed: feed +0.03%, post +0.02%).

## On a server copy (scratch `insight_server_1105_mxreal_sep_check_<pid>_a`, migrated to head, dropped after)
The copy's ent-v3 mentions start in September and its vectors in June, so E counts from September only. The runs were
simulated once a day, 1 Jul – 5 Nov.

| Month | E | E+V | L | L+V | V only | All |
|---|---|---|---|---|---|---|
| Sep | 7 | 0 | 1 | 0 | 37 | 45 |
| Oct | 11 | 1 | 2 | 1 | 43 | **58** |

- **Planned:** 50 `back` tasks (the cap) from 171 candidates. On average a candidate has 2.8 posts, 36 days after the
  story's first post.
- **The stage's time:**
  - a daily run: median 0.86 s, max 3.1 s (the first run, which reads 30 days);
  - an hourly run: 1.3 s;
  - the decision run's limit is 120 s.
- **The guide's md5** is the lab's (a test).
- **V fires about 4–5 times the lab's rate** (Oct 43 vs about 9 a month). The lab's vectors were a partial cache;
  every post on the copy has one. At cosine 0.75 instead (not adopted, not measured for precision), October has E 15,
  L 3, V 14: 32 candidates.

## For the owner
- **The worker:** add `back` to `DEFAULT_KINDS` (after `relate`). `PER_CALL` can name `back=8`, the lab's batch size.
  `scripts/markx-worker` was not edited.
- **Decide:** whether V stays at 0.70 (about 58 candidates a month on the copy, 3 Haiku calls each) or is held back
  until the next round measures it. And whether a story may fire again later (and when).
- **Not done:** the real-data check (`scripts/realdata-check.sh`), the next round (part 4: 120+ fresh candidates with
  the owner's labels and the three narrow fixes), and the owner's first 20 labels.
