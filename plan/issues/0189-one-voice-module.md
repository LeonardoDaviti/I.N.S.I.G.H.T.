# 0189 — One Voice module (v10.17)

Status: **built** (branch `v1017-voice` from v1016 bae0ac0: the module 4cbb2e6, the built fix 6528ae2; v1016 591a5c4
merged in 7770d10; the rest of the class 3adba4a, its fix 5ed01f5). Not merged into v1016, not pushed, not deployed.
No migration.

## The problem

An audit found voice counting written about seven times with three rules, and "who wrote a post" read around Byline:

- Mark X: `pairing.voices` (distinct sources, a saved post none) and `pairing.counted_voice` (a repost counts as its
  author's source when a source follows the author); decide, tasks and anchors went through them, `markx/built.py`
  did not (`len({p.source})`: it counted saved pages), nor did `perspectives` (by hand, the same rule).
- Mark IX: `StoryPost.voice` (`site:<publication>` / `reddit:<poster>` / `source:<id>`), `owner_voice`,
  `counted_voice`, `other_voices`, `voice_groups` and `count_voices` (copies of one text one voice) in
  `utils/story_rules.py`; the owners layer in `db/repo_stories.py` built its own `site:` / `source:` / `reddit:` /
  `voice:` keys; `db/repo_reader.py`, `db/repo_discover.py` (in SQL, three times), `services/stories_service.py`,
  `services/news_service.py` and `utils/classic_rules.py` read or built the same prefixes by hand;
  `markx/source_stats.py` had a fourth scheme (`v:` / `s:`) and parsed Mark IX's.
- Who wrote it: the story job read `x_account(row["author"])` itself (X only), `repost_of` lived in
  `db/repo_reader.py`, three repost tests were written by hand (source stats twice, the Voices suggestions once) and
  "RT by @" was matched by four copies of one pattern.

## What was built

**`backend/insight_core/utils/voice.py`** — the Voice module. Interface:

- `voice_of(post, policy) -> key` and `count(posts, policy) -> int`;
- `others_of(post, policy)` (Mark IX's other voices of a post: its tweet's author's source, its reposters) and
  `groups(items)` (Mark IX's voices among items, copies of one text one; `named_voices` names a count by it);
- Mark X's basics: `is_voice(kind)`, `independent(...)`, `counted_source(...)`, `followed_accounts(cur)`, `Said`
  (the facts Mark X counts a post by: source, kind, `counts_as`).

The engines' rules are named policies, never guessed by a caller: `Policy.MARKX`, `Policy.STORIES_IX`,
`Policy.NEWS_IX` (STORIES_IX with every owner's channels one voice). The key forms (`site:`, `reddit:`, `source:`,
`voice:`, source stats' `v:` / `s:`) are private: constructors (`key`, `source_key`, `site_key`, `poster_key`,
`confirmed_key`, `channel_key`, `story_channel_key`), readers (`poster`, `is_poster`, `source_of`, `is_site`,
`is_confirmed`, `owner_of`, `channel_of`) and SQL (`key_sql`, `source_key_sql`, `site_key_sql`, `POSTER_LIKE`) are
the only way in or out. Mark IX's keys are stored (story_posts.voice, news_posts.voice, the News owners, Discover's
addresses), so their forms did not change.

**`backend/insight_core/utils/byline.py`** now owns every "who wrote it" question: `author_account` (moved from
tasks), `tweet_account` (Mark IX's reading of a tweet's stored author), `repost_of` (moved from repo_reader; still
importable there), `is_repost` (source stats' test) and `retold` (the Voices suggestions' older test) with their
SQL (`retweet_sql`, `forwarded_sql`, `reposted_sql`, `not_retold_sql`), and `RT_BY` / `RT_BY_PREFIX`, the one
"RT by @user: " pattern (post_fields' `REPOST_BY_RE`, handles' `REPOST`, post_parser's cut and x_articles' prefix
read it).

**Callers** (all go through Voice or Byline now): markx/decide.py, tasks.py, anchors.py, pairing.py (story_pairs,
`Posts.voice`), perspectives.py, built.py, incremental.py (`accounts_stamp`; Voice and Byline added to
`CODE_MODULES`, and to tasks' `_PLANNER_CODE`), source_stats.py, handles.py, folds.py; utils/story_rules.py,
news_rules.py, tree_rules.py, classic_rules.py, post_fields.py, post_parser.py; db/repo_stories.py (owners layer),
repo_reader.py (`story_voices`, `confirmed_owners`), repo_discover.py (three SQL keys, `voice_source`, the site
namers), repo_voices.py; services/stories_service.py (`_story_post`, `_linking`), news_service.py (`_voice`,
`_citers`), post_detail_service.py, discover_main_source.py; ingestion/kinds/x_articles.py.

**Deleted:** `pairing.NOT_VOICE`, `is_voice`, `voices`, `counted_voice`, `followed_accounts`, `independent`;
`story_rules.VOICE_PREFIX`, `voice_groups`, `count_voices`, `confirmed`, `reposter_voice` and StoryPost's
`owner_voice`, `counted_voice`, `other_voices` (StoryPost keeps `voice`, the stored key, and `place`);
`tasks.NOT_VOICE`, `tasks.author_account`; `decide.NOT_VOICE`; `candidates.NOT_VOICE` (unused); the hand-written
key prefixes listed above; four copies of the "RT by @" pattern. Kept as thin adapters: `decide.voices(posts, ids)`
(ids over decide's map), `tasks.voices(posts)`, `source_stats.is_repost(src, ...)` (a source's facts into Byline).

## Identity (no output changed)

- **Seeded worlds** (`tests/test_voice_0189.py`, 1,500 seeds each against `tests/legacy/voice_v1016.py`, the v10.16
  code word for word): STORIES_IX and NEWS_IX count, `voice_of`, `others_of`, `StoryPost.voice` / `place` as
  before; MARKX as `pairing.voices`, `independent`, `counted_voice` were; every key reader (owners, posters,
  Discover's `voice_source`, source stats' keys) as before; the SQL fragments equal the Python keys in Postgres;
  Byline's `is_repost` / `retold` as the hand-written tests were. The existing equivalence suites (test_markx_pairing:
  decide's planning against the legacy decide; test_markx_units, test_byline_0185, test_sources_0178,
  test_stories, test_voices, test_markx_incremental) pass: 195 tests.
- **A scratch copy** of `insight_ru_show` (two `CREATE DATABASE ... TEMPLATE` copies, migrated 0125-0128). v1016
  on one, this branch on the other: the full story job (summary identical), the snapshot's stories, News, Classics
  and Discover parts, every `story_posts.voice` (6,249), `stories.voices` (2,233), `news_posts` (480),
  `news_stories` (127), the News owners (103), Classics (510), the News answer: **identical**. Mark X's full
  decision run: every current story's members (277) and the News rows (126: voices, reports, shares, mentions,
  score, tag, each post's voice) **identical**; `tasks.voices` of every story identical. (The run's entity stage
  differs between the two copies by itself: random ids and its own order; nothing reads a voice there.)
- **Both versions over one state** (copy 1, read only, PYTHONHASHSEED=0, no synchronized or parallel scans): the
  Mark X News page, `built` of all 277 stories, Discover's main-source pick, every anchor's voices (1,119), the News
  answer and source stats' 4,845 rows **identical**. (Source stats' evidence lists vary between two runs of the same
  code when scans run concurrently: rows tied in an unordered query. With those off, three runs agree exactly.)

## The one fix: `markx/built.py` counted saved pages

`built.voices` was `len({p.source for p in posts})`; it now counts by `Policy.MARKX` over each member's source and
kind (`built.Post.kind`, loaded by `built._load` and `discover_main_source._stories`). The same count decides a
leak's own coverage in `leaks_inside` (was the same `len({source})`). Readers: `came_true`'s "a one-voice leak story
joins its release", `leaks_inside`, Discover's main-source `pick` (MIN_VOICES and the voices it reports).

**Effect on real data: no row changes.** On the `insight_ru_show` copy one current Mark X story holds a saved page:
11 sources, now 10 voices; it is not a leak story, not in the pick's window, and `built` reports no count, so
`built` for all 277 stories, the News page and the main-source pick are identical before and after. The 11-05 server
copy holds the same one story; the lab copy holds one story of 2 sources one of which is a saved page (now 1 voice),
from 2025-09, outside the pick's 30 days, with no read-v3 reading: no output there either. The seeded test shows the
change (`BuiltVoices`).

## The rules that still differ (not unified in this slice)

Measured on the `insight_ru_show` copy, read only: each Mark IX rule added alone to MARKX, the stories whose count
moves and those that cross the 2-voice line (Mark IX's 2,233 stories, 989 of 2+ voices by MARKX, 945 by STORIES_IX;
Mark X's 277, 134 by MARKX, 123 by STORIES_IX).

| rule (STORIES_IX has it, MARKX not) | Mark IX stories moved / cross 2 | Mark X stories moved / cross 2 | recommendation |
|---|---|---|---|
| a website's voice is its publication (two feeds of one site are one) | 1 down / 1 | 0 / 0 | unify on the publication: two feeds of one site are one voice; Pairing's independence gate would then read Voice too |
| a Reddit post's voice is its poster, not the subreddit | 5 up / 0 | 5 up / 0 | unify on the poster (a person is the voice); no threshold moves |
| copies of one text (120+ characters) are one voice, whatever the sources | 124 down / 98 | 13 down / 11 | the largest; decide on judged cases first (cases.json: a mirror or bridge vs a syndicated wire copy), then unify; Mark X already never checks near-copies but counts them |
| a tweet's reposters (posts.reposted_by) and its author's source are voices beside the row's own source; Mark X counts the repost as the author's source instead | 64 up / 55 | 2 up / 0 | keep apart for now: Mark IX's News counts reposts as shares on purpose; owner decision |
| a confirmed voice's channels are one (0132 A; News: every owner's) | 0 / 0 | 0 / 0 | unify (the owner confirmed them); this copy has none: measure on one that has |

Who wrote it: Mark X reads a repost's author through `byline.author_account` (X reposts by another account, and
Telegram forwards naming a followed channel); Mark IX's story job reads `byline.tweet_account` (X only, the stored
author whoever it is). On this copy the two agree on all 56 posts either reads (no forwards of followed channels
here). Recommendation: unify on `author_account` (a superset), checked on a copy with Telegram forwards.

`hn`: not a voice difference. Mark IX's `NOT_PUBLISHERS = ("hn", "saved")` says whose addresses are not their own
pages (home sites, on-own-site), never who counts; an HN post's voice is its source under both policies. Both engines
count no saved page (`voice.NOT_VOICE`).

The repost tests in Byline differ too, each kept as it was: `is_repost` (source stats) reads Telegram forwards;
`retold` (Voices suggestions) does not, and counts a row any account of yours reposted whoever wrote it;
`not_retold_sql` (the stance count's filter) reads no author. Recommendation: one `is_repost` for all three, after
measuring the suggestions' and stance counts it moves.

## The merge of v1016 (591a5c4, 0190) — 7770d10

Four conflicts, both slices' intent kept: `db/repo_discover.py` (0190's `pairing, units` import beside Voice's
keys), `markx/built.py` (0190's `pairing.published_date` and `event_types` lists beside Voice's count),
`markx/pairing.py` (the docstring names 0190's dates and Voice's basics; 0189's deletions stay deleted),
`tests/test_markx_event_types.py` (0190's by-id order, and the members' `kind` left out of the comparison). 0190's
guard `tests/test_dates_owner.py` pinned nine inline Mark IX dates in this slice's files (repo_stories 3, repo_voices
4, source_stats 2); they now read `pairing.ix_date` / `ordinary_date` (the same SQL text), and the guard pins none.
`markx/tasks.py` keeps its `pairing` import (0190's `ordinary_date`).

## The rest of the class — 3adba4a (no output change) and 5ed01f5 (the second fix)

Every remaining voice count asks Voice: `markx/back.py` (the story gate, a burst, a trigger), `markx/later.py` (the
story gate, the quiet rule), `markx/entity_views.py` (a story block's voices), `markx/timeline.py` (a month's
sources), `markx/news.py` (`entities`), `markx/search.py` (entity cards), `markx/research.py` (`held`'s voices),
`services/originals_service.py` (a front page's linking sources, saved already out). New: `voice.count_sql(source,
platform=None)`, MARKX in a query. 3adba4a moved them unchanged (each still counts what it counted).

5ed01f5 makes the ones named voices, or gating on "2+ sources" of a story, count a saved page as none: back's and
later's Mark IX story gate (`back.sources`; members now carry their saved flag), the entity page's story voices,
`news.entities`, search's entity voices, research's voices. Kept as source counts (not voices): the bursts and
triggers (their posts drop saved pages first), the quiet rule (sources naming a subject) and the timeline's month
line. Effect, both versions over one state of a migrated `insight_ru_show` copy: **no output changes** (back's 884
stories, later's long-lived stories, `news.entities` identical; no saved page holds a mention there, so entity pages,
cards and research counts cannot move; its one Mark IX story with a saved member keeps 2+ voices). On the lab copy
one Mark IX story, a one-account thread plus a saved page of its address, drops from 2 sources to 1 voice and leaves
back's and later's story set.

"RT by": `voice_rules.shingles` and `series.clean_title` now cut Byline's `RT_BY_TAG` ("RT by @user:"). Their
behaviour is not RT_BY's and was kept: they cut the tag with any whitespace after it (`\s*`; series also "R to"),
where `RT_BY` needs exactly one space (Nitter's form). They differ only on a title whose tag is followed by no space
or by another whitespace.

The guard `tests/test_voice_owner.py` fails on a new `count(DISTINCT …source_id)`, a `len({…source/src…})` or an
"RT by @" pattern (regex, LIKE, startswith) outside voice.py / byline.py. Pinned, with why (counts of sources, not
voices): `story_rules.is_story`, `entity_repair`'s span spread, `repo_folders`' folder size.
