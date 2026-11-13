# 0174: Mark X News in sections, every row titled by Haiku (Stealth v10.16)

Owner, 2026-11-12: "categorize news in the Mark X News page: with categories divide et impera works and it's easier to
read; entitle those news as well; this should be Haiku's job."

## Built

1. **The question** (kind `news_sections`, guide `news-sections-v1`, one task per call, subject `news_run`, `a` = the
   News run). Input: the current News rows (the newest written run's rows inside News' 30 days, in News' own order:
   `news.rank_key`, the page's order), keyed `r1..rN`, each with its headline, its main entities with their types
   (current entities of its posts, subjects before actors, most posts first, at most 3), its kind of happening when
   read-v3 read its posts (`folds.story_type`), its voices, and `last: sN` (its section in the last answer). Then the
   last answer's titles (`LAST TIME'S SECTIONS: [s1] ...`) so the page stays stable. Rows are keyed, never named by id
   (cheaper output, fewer mistakes); `mx_news_section_asks` keeps the ids in key order to read the answer back.
   Sphere-agnostic: no list of sections in code, the guide names no field; the titles are Haiku's.
2. **The checks** (validate.py `_news_sections`): 3 to 8 sections (schema); every row of the question in exactly one
   section (a missing key, a key twice, an unknown key: refused, naming them); titles one line, at most 4 words and 40
   characters, none twice (folded); "Other" and its like for 2 rows or fewer.
3. **When** (`news_sections.plan`, the lease's planner in `tasks.PLANNERS`): first time, or when new + removed rows are
   20% or more of the last asked rows; at most once every 30 minutes; never while one waits (open or leased); a failed
   question does not count as the last asked one. Fewer than 8 rows: nothing asked. Priority -1 (first of its kind).
4. **The answer** (`after_answer`, from `tasks.record`): one `mx_news_sections` row a section (keep everything: every
   sectioning stays), ordered by its most important row.
5. **The page** (`GET /api/markx/news` gains `sections: {at, pending, groups: [{title, rows}], new}` and
   `counts.untitled`): the newest valid sectioning over the rows shown, sections in the page's order, rows in News'
   order inside; rows added since are `new`, shown first under "New since". A pending question never holds the page:
   the last valid sectioning shows meanwhile; none yet: the plain list. The frontend groups under small headings, a
   switch "in sections" for the plain list, and "Sections updated 12m ago" (plus "new sections asked" while one waits,
   and how many rows are not titled by Haiku yet).
6. **Entitle the news** (`news_sections.title_rows`, the decision run's `news_titles` stage after News, in a
   savepoint): every current row still titled by its lead has its headline asked first: its open headline tasks (by any
   of its posts) raised to priority -1, or, when none is open or leased, the row's own headline question added at -1
   (`news.row_headline_input`, the one the page finds the answer by). Counts `{untitled, raised, added, waiting,
   failed}` in the run's counts.
7. The worker: `news_sections` in DEFAULT_KINDS after `headline`, `news_sections=1` in PER_CALL.

Migration 0117 (`mx_news_section_asks`, `mx_news_sections`, subject kind `news_run`).

## Measured

- On the server's News now (GET /api/markx/news, 2026-11-12): 293 rows (180 shown as differences); 11 rows show their
  lead's title, not a Haiku headline (all SAME rows, so only with "only differences" off; 9 of them in no Mark X story:
  posts joined by a surging name). The `news_titles` stage asks theirs first after the deploy.
- Cost: the 293-row question is about 46,000 characters (about 13k tokens) plus the guide; the answer about 1.1k tokens
  (293 keys and 3-8 titles). At Haiku 5.5's $0.10 / $0.50 per million: about $0.002 a sectioning (Claude Code's own
  overhead may add a little; the worker logs cost_usd). At most 48 a day (one per 30 minutes, only when 20% changed):
  under $0.10 a day, typically a few a day.

## Verify after deploy

1. Migration 0117 applied; a worker cycle with the default kinds leases one `news_sections` task.
2. `GET /api/markx/news?all=1` has `sections.at` set and `sections.groups` with 3-8 titles; `counts.untitled` drops
   toward 0 after the next decision runs and the worker's headline answers.
3. The Mark X News page shows the section headings, "Sections updated N ago", and the switch back to the plain list.
4. `GET /api/markx/status`: `news_sections` answered with no failed tasks; read the titles yourself (concrete, parallel,
   no catch-all) before calling it done.

## Not done

- No owner labels on sections yet; no per-section collapse; the main reader's News is unchanged (Mark X page only).

## Addendum (v10.17): new rows placed between sectionings

Rows added between two full sectionings no longer wait under "New since" for the 20% rule: issue
[0197](0197-news-sections-placement.md) places them into the existing sections with one small question (`news_place`,
news-place-v1), at most every 10 minutes; a full sectioning (rules unchanged) supersedes the placements.
