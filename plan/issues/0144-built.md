# 0144 — Built (Stealth v10.10): stories for all history, and the person page

Built 2026-11-09 on its own branch from main cc17e4c (0138, 0139, 0140 merged), parts A, B and C. **Migration 0092**
(`0092_markx_story_window.sql`: three Mark X tables, no foreign key, nothing deleted). Nothing here fetches from the
development machine; the real checks are GETs to the server and runs on a scratch copy of the server's export.

**realdata-check: run at merge** (the owner's rule of 2026-11-09: agents no longer run it).

## What a deploy changes
- Nothing until the owner sets the **Story window** on `/markx` (Worker tab, under the reading window): with no row it
  is 30 days, the decision run's window as before (`decide.Config.days`), and the run's counts are unchanged.
- At 120 / 365 / everything the decision run grows its window back from the newest day, **a week a run**, once the
  week's candidates are found and its questions asked; the candidate finder reads the next week's posts first (1,000
  a run). News is unchanged (`NEWS_DAYS`, `news.NEWS_KEEP`): an old story never enters News; surges keep 30 days.
- Every entity page of a person or org asks once "These sources are <name>: … ? Yes / No" when a source's handle,
  profile name or site is its name; a `Yes` puts their posts on the page as `by`.
- Every entity page visit may offer up to 10 old stories to label (30 a day over every page).

## A. Stories for every post — `markx/story_window.py`
1. **`story_window_days`** in `mx_settings` beside the reading window: days, or null for everything; 30 when unset.
   `POST /api/markx/settings/story-window` `{days}` (1–36500 or null); `GET /api/markx/settings` answers
   `story_window_days`; `GET /api/markx/overview` answers `story_window` (`days`, `in_force`, `fallback`, `run_days`,
   `reached`, the samples' `precision`, `keep` 0.97, `min_labels` 20). Read on every run: `decide.run` replaces
   `Config.days` by `days_for_run` (unless `Config.story_window` is False), `candidates.backfill` reads one step past
   it, and `tasks.plan_checks` defaults to it (`days=SETTING`). Choosing everything keeps the window it replaced
   (`story_window_previous`, the fallback's).
2. **Newest first, resumable** (`story_backfill.reached` in `mx_settings`): past 30 days a run decides from the oldest
   day reached (30 days at first). After the run, `advance` steps 7 days further back when no old question waits and
   the candidate finder found every embedded post of the next step (`candidates.unfound_count`); a step with no post
   goes on to the week of the next older post (the export's oldest post is dated 2000: one step, not 1,300). The
   candidate job's backfill (`candidates.backfill`, run after its usual work, in its transaction) finds the next
   step's unread posts newest first by the same four sources and rules, 1,000 a run, and marks them found
   (`mx_candidate_posts`); a stopped run resumes from what is left.
   **Questions in pages:** while the window reaches past 30 days, a run adds at most 200 new questions a kind about
   posts older than 30 days (`Ask.old_after`, `old_cap`), asked newest first (`_ask_all`: the decisions never depend on
   the order, `decide` sorts by kind and id), at priority 1 (`BACKFILL_PRIORITY`): a worker's lease takes today's
   first, then these with yesterday's, instead of queueing them behind every new one. `plan_checks` does the same for
   Mark IX's uncertain members (old ones newest first, 200 a call, priority 1).
3. **Old Mark IX stories are inputs, not answers:** unchanged rules — a pair already in one Mark IX story is still
   checked (`check`), so Mark X's stories over history are its own.
4. Measured before switching: below.

## B. The entity page — `markx/person_page.py`, `markx/entity_views.entity_page`
1. **By:** for a person or org, `by_sources`: a source whose confirmed voice (`voices.entity_id`, 0132) is the entity
   (`via: voice`), and a source whose handle, profile name or site label is one of the entity's names by identity's key
   (squashed: its members' keys, aliases, names, and a person's surname of 5+ letters), offered once
   (`by.proposed`) until the owner answers (`POST /api/markx/entities/{id}/sources {source_ids, answer: yes|no}`,
   `mx_entity_sources`, the newest answer counts); a `yes` is `via: owner`. Reddit, HN and saved pages are never one.
   Their posts join the page with role `by`, counted in `posts` and `voices` (`sources[].by`), never in surges (surges
   read mentions alone). `current` (0138's "named by a current reading") still counts mentions only.
2. **Stories:** every current Mark X story (`mx_story_posts` members) of the page's posts, and for a post in none, its
   Mark IX story (`story_posts`, read only), `mark: x | ix`; each lists **all** its posts (`about: false` for one that
   neither names the entity nor is by it), most voices first.
3. **Original first:** the earliest post by the entity itself (`why: by`), else the root: Mark IX's outside page
   (`origin_url`, linked to its stored post when INSIGHT has it, `why: origin`) or first post, a Mark X story's earliest
   member (`why: root`); the page shows it first, labelled **Original**.
4. **Loose posts by role:** subject and actor, then by (the newest 50; `?by_limit=` for all: `Show all N posts in no
   story`), then venue / source / recommended, then mentions, collapsed to an `N mentions` button
   (`loose_counts`). The page: **By <name>** (its sources, the question, its own loose posts) apart from **About
   <name>**.

## C. Labels for the past
- The page offers up to 10 of the entity's Mark X stories older than 30 days (`mx_story_samples`, a stable hash order,
  the unlabelled first; 30 offered a day over every page), each `right` / `wrong` / `missed a post`
  (`POST /api/markx/stories/{id}/sample`, `mx_story_sample_labels`, the newest answer counts).
- The Worker tab shows old stories' precision (first post older than 30 days when offered) beside the newer ones';
  `missed` never counts against it. With the window at everything and 20+ old stories judged under 97%, the window in
  force falls back to the last window set before everything (else 30), and the tab says why.

## Tests
- Backend `tests/test_markx_story_window.py` (16): the original rule, the roles order, a source's names; the setting
  (default 30, everything kept, a narrower window at once), the decision run reading it (the old pair never asked at 30
  days; at 90 the window grows back, the pair asked at priority 1, Mark X's own story made, **no News row**), a run's
  page of old questions (the rest wait), the step waiting for old questions and candidates and skipping an empty year,
  the candidate backfill newest first and resumed (and none at 30 days), `plan_checks` following the window, the
  fallback (20 labels, under 97%, back to the window before everything; a missed post no wrong story); by through a
  confirmed handle (offered, then `yes`, then `no`) and through the voice, never for a product; a person's own post on
  his page (posts 3, voices 3); a Mark IX story with all its posts and his post as Original, and a Mark X story winning
  for its post; the sample's 10 a page and 30 a day; the API routes (`story-window`, `sample`, `sources`).
  Updated: `test_markx_storage` (34 tables), `test_markx_api` (plan_checks' default is the story window's).
- `markx.incremental.memo_for` and `repo.last_run` order runs of one start time by `finished_at` before `ctid`: in a
  test all runs share `now()`, and a larger run row (the config's new field) moved one to another page, so the last
  run was misread and `test_markx_incremental` failed; the order no longer depends on where Postgres put a row.
- The whole backend suite: **2,500 tests, OK** (2 skipped). Frontend: `personPage.test.tsx` (4: the original first and
  the Mark IX mark, By with Yes and Show all, mentions collapsed, the sample's buttons; the story window's radios,
  precision and fallback line), `entities.test.tsx` (the loose posts' region is "About <name>"); `npm run build` and
  `npx vitest run` (856 tests) pass; the design doc (`pages/shell.md`) claims the page parts and the setting.

## The real checks (private rows in `plan/research/0144-notes.md` and /tmp, never committed)
1. **A4: counts and the decision run's time per window** (scratch copy of `insight_server_1105_mxreal`, migrated to
   0092, `now` = the export's time; each window one full run with `story_window` off and `Config.days` set, in a
   transaction rolled back; the copy dropped after):

   | window | posts | embedded | Mark IX stories touching | candidate pairs | questions (check / pair / join / merge) | run | questions and decisions | counted against the 120 s limit |
   |---|---|---|---|---|---|---|---|---|
   | 30 days | 5,734 | 5,734 | 281 | 4,468 | 164 / 1,462 / 590 / 90 = **2,306** | 58.1 s | 1.6 s | ~21 s |
   | 120 days | 15,530 | 15,530 | 823 | 13,139 | 447 / 3,749 / 1,609 / 408 = **6,213** | 58.9 s | 2.6 s | ~23 s |
   | 365 days | 38,025 | 20,742 | 1,938 | 18,839 | 882 / 4,714 / 1,974 / 479 = **8,049** | 60.3 s | 4.0 s | ~25 s |
   | everything (9,726 days) | 49,384 | 20,742 | 2,207 | 18,839 | 1,062 / 4,714 / 1,974 / 479 = **8,229** | 61.5 s | 4.6 s | ~26 s |

   - **Time:** the run grows 3.4 s from 30 days to everything; the entities stage (~36 s, its own budget) and the
     connections (~18 s, the same at every window) dominate. Everything stays well inside the 120 s limit. Each step
     changes `Config.days`, so each step's run is a full one (61.5 s measured).
   - **The candidate finder** read every embedded post of each window again: 8.5–10.7 ms a post (176 s for 20,742),
     **0 new pairs** — the copy's candidates were already found when its vectors came, as the server's are (every
     upload notes its posts). Hence the backfill's page of 1,000 posts (~11 s) a run: it finds what an upload missed.
   - **The copy understates the old part:** only its last ~5 months are embedded (20,742 of 49,384) and only 5,344
     posts read, so a pair or join of unread posts is planned but never asked here (the server read and embedded every
     post: 68,800 embeddings, 69,758 readings). From 30 to 120 days the copy adds **0.40 questions a post**
     ((6,213 − 2,306) / (15,530 − 5,734)).
   - **Cost estimate (everything on the server):** ~63,000 posts past 30 days × 0.40 ≈ **25,000 questions**; at the
     copy's measured tokens a judge answer costs $0.00015–0.00022 at Haiku's API price (check 864/127 tokens, pair
     906/153, join 1,033/153, merge 1,192/197): **≈ $4–5**, ≈ $8–9 if every one were asked twice (story-changing
     answers are confirmed), plus a card and a headline for each new story of 2+ voices (~$0.0007 a story: ~$2 for
     ~2,000–3,000 stories by the copy's 2,153). **Under $15 at the API price**; on the owner's subscription the worker
     did 145,000 calls on 8 Nov, so the questions are a fraction of a day's work. The window's steps (a week a run,
     and a week of more than 200 questions a kind needs another run) make it a matter of days, newest first.
2. **B: the owner's entity** (GETs from the server, the page as v10.9 serves it, and B's rules run offline over the
   server's sources list): the handle rule offers **exactly his six sources** (X, the video channel, two blogs, the
   gists, the old blog: 1,400 posts), nothing else; after `yes` the page lists them as `by` (the existing 278 + 1,400).
   The weekend-project story (Mark X) has 4 posts (GET of the story): his own post first by time and by source, so it
   is the **Original** (`why: by`) and the page lists all 4, not the 2 that name him. Of the 275 posts in no Mark X
   story, **52 sit in 41 Mark IX stories** (GET of each post), shown as Mark IX stories with all their posts; 30 of the
   41 hold a post of his own sources (his post is their Original once his sources are `by`).
3. **B on unnamed entities** (the same offline rule over the server's 12 most-voiced people and orgs of the entity
   list): 13 sources offered, all the entity's own (orgs' news or research feeds and channels, a person's site and X
   account); 5 people with no own source followed got none; no other person's or org's source was offered.
4. Not measured here: a night with `story_window = everything` on the server (stories a year; a 20-story sample right /
   wrong) needs the deploy and the owner's setting; the page's sample (C) collects those labels.

## Open points
1. **The night run (Measure 3)** waits for the deploy: the owner sets the story window on `/markx`; the Worker tab
   then shows the steps (`back to <day>`) and the old stories' precision as the entity pages collect labels.
2. **The fallback applies to everything only** (as specified): a window of 120 or 365 days keeps its setting whatever
   the old stories' precision; extending the rule to any window past 30 days is one line.
3. **Mark IX stories are shown for posts in no Mark X story** (B2); a Mark IX story whose posts are partly in a Mark X
   story is shown when one of the entity's posts is in none, so a few posts can show under both.
4. **The entity list** (`/markx?tab=entities`, 30 days) still counts mentions only; `by` posts count on the entity's
   own page.
5. **A person's surname alone** (5+ letters) can match another person's handle; it is only ever an offer the owner
   answers once, never applied by itself.
