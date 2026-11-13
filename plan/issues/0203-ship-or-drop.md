# 0203: Ship or drop: Mark X's built-but-unshipped features measured blind (Stealth v10.18)

Status: **measured; the News chaining fixed and re-measured; five drops built** (branch `v1018-measure` from `main` at
v10.17.1). Not merged, not pushed, not deployed. No migration. **Decision: Mark X News becomes the main News** (see
1g, after the fix).

## The question

Several Mark X features are built and wait in Shadow. Each gets a verdict: ship it as an automatic decision, ship only
its top bands, keep working on it, or drop it. The verdicts rest on blind labels. The owner said on 2026-11-14 that
the "99%" bar was rhetorical. The method is the project's usual one:

- **Sample size.** 40 to 100 blind-labelled rows per feature, more where a bar needs it.
- **Passes.** One labelling pass per row.
- **Statistics.** Precision with its Wilson 95% interval, and per band where the feature has bands.
- **Bars.** Each feature is judged against its own spec's bar: back 90%, Later a Wilson lower bound of 80% or more,
  ent-v4.2's LEAVE_AT a lower bound of 85% over 100 or more rows, identity bands 97% / 90%.

The Mark X News vs Mark IX News comparison (1g) is the most important item. It decides which page becomes the owner's
main News.

## How it was measured

- **Labelling.** Claude subagents labelled every row, blind. Each saw the posts (title, source, date, opening text;
  6,000 characters for entities) and never the system's verdict, judge text, tag or score. Each labelled 40 to 170
  rows in a batch. Where both answers are labelled (Later, the folds' shown and folded members), the rows were mixed
  and shuffled first.
- **Records.** The rows are in `plan/research/measure-1018/<feature>.tsv`: the post ids, the system's decision and the
  label. These files are private. The scripts that gathered and scored them sit beside them (`gather_*.py`,
  `clone_*.py`, `score.py`).
- **Where the answers came from: mostly the server.** The prepared copy `prep_mxreal` was refreshed to main (0135).
  It holds only ent-v3 entities and read-v2 readings up to 2026-11-05. It has no ent-v4.2 answers, no back or Later
  rows, no read-v3 readings (so no folds), no Mark X News rows and no tracks. So the stored answers of 1a–1d and 1g
  were read from the server with light GETs, cached once each, and no server writes. These were the Mark X post panel,
  entity pages, `/back`, `/later`, `/news?all=1` and Mark IX's `/api/news`.
- **What ran on a clone of the copy.** 1e, 1f and the dead-code check ran on a clone, `v1018_measure`, which was
  dropped afterwards.
- **The window.**
  - 1a: posts sampled uniformly from the copy's last 30 days.
  - 1b, 1c, 1d and 1g: the server's rows as of 2026-11-14 00:28 UTC.
  - 1g: the five full days 2026-11-08..12. The copy has no Mark X News, so the comparison uses the pages the owner
    actually reads, both built from the same posts.

## The table

| feature | n | precision (Wilson 95%) | per band | verdict | why |
|---|---|---|---|---|---|
| **1a** ent-v4.2: every entity (uniform) | 80 | **94%** (86–97) | org 95%, person 91%, model and product 100%, `other` 4/8 | (in use) | right name, type and real thing |
| **1a** ent-v4.2: new entities (LEAVE_AT's class: document, source, recommended, q2) | 133 | **89%** (82.2–93.0) | main answer 90% (83–94); q2 16/19; source 89%; recommended 10/12; documents 89% (80–94) | **needs work** (stays in Shadow) | LEAVE_AT needs a lower bound of 85% over 100+ rows; this is 82.2%. No band clears it |
| **1a** ent-v4.2: links (mention → entity) | 150 | **97%** (92–99) | uniform sample 56/57 | ok | 5 wrong: one author-year bucket mixing papers, one version/family confusion |
| **1b** Back in the news (old engine): rows shown | 40 (all) | **68%** (52–80) | judges agreeing 3/3: 79% (60–90); split: 5/12; trigger V 68%, E 67%, E+V 67% | **needs work** (not on News) | bar 90%; no band reaches it. 20 of 69 "development" posts are wrong; 13 of those 20 are `related` (another version or launch of the same family), 6 `retold` |
| **1c** Later developments: rows shown | 7 (all reachable) | **4/7** (25–84) | trigger: E 6/92 developments, L 0/70 | **dropped** (owner, 2026-11-14) | bar: lower bound ≥ 80%. Only 6 of 167 candidates (4%) are developments; the judge keeps 4 of those 6 and adds 3 wrong |
| **1d** Duplicate folds: folded posts | 70 of 762 | **77%** (66–85) | — | **needs work** | 1 in 4 hidden posts is not a duplicate. Shown members that are duplicates: 19/50 (estimated recall 66%; F1 ≈ 0.71, which reproduces the lab's 0.70) |
| **1e** Happening pairs (switched on on the clone) | 4 (all) | 4/4 (51–100) | every group (key only): 23/28, 82% (64–92); release 10/12, research 7/10, deal 4/4 | **leave off** | yield: 4 pairs in 30 days in the paired groups (24 keyed posts of 5,274 read). They are candidates for the judge, never a decision. Too few to measure or to matter |
| **1f** Corporate-suffix merges | 11 candidates | merges 0 (none has 2 posts beside) | the bare pairs: 8 same org, 1 wrong (a division vs its parent), 2 unsure | **dropped** (owner) | as configured it merges nothing on the copy. Without the post evidence, 73% |
| **1f** Components (`timeline.components`) | 60 of 296 | **43%** (32–56) | changes a link 12/26; doesn't 14/34; by reading 5/12, by subject 21/48 | **dropped** (owner) | the product itself under a longer name, a fine-tune, a separate product and a wrong parent are all called components |
| **1g** Mark X News, before the fix: rows a single story | 103 rows, 5 days | **89%** (82–94), plus one runaway row | — | fixed (below) | one 397-post row hid the week's top stories |
| **1g** Mark X News, after the fix: rows a single story | 118 rows, 6 days | **83%** (75–89) | — | **main News** | no runaway; the mixed rows are small (below) |
| **1g** Mark X News, after the fix: rows not a duplicate | 118 | **86%** (79–92) | — | | |
| **1g** Mark IX News: rows a single story | 97 | **94%** (87–97) | — | stays as it is until the switch | |
| **1g** Mark IX News: rows not a duplicate | 97 | **73%** (64–81) | — | | a story split across 2–4 rows is common (one launch in 4 rows, an IPO in 3) |

### 1g: Mark X News vs Mark IX News, 2026-11-08..12

| | Mark X | Mark IX |
|---|---|---|
| rows | 103 | 94 |
| a single story | 92 (89%) | 88 (94%) |
| not a duplicate of another row | 101 (98%) | 68 (72%) |
| major rows | 46 | 45 |
| clean major rows (single story, no duplicate) | **42** | 25 |
| major events the other page has and this one lacks | 12 | 17 |

- **Where Mark X is better.** Its rows are distinct: one story is one row. Mark IX shows the week's biggest launch
  in four rows and an IPO in three. Mark X has 17 more clean major rows. Mark IX misses 17 major events Mark X shows,
  mostly ones a single source covered: a framework release, a phone update, a quarterly revenue figure, a model
  release, a genome model, a takedown.
- **One runaway row in Mark X.** Its biggest row starts on 2026-11-07, just outside the window, so the per-day
  labels don't count it. It holds 397 posts. It is headed by one model release, but it also swallowed:
  - the week's top company story (its CEO's resignation and the scandal before it, about 100 posts);
  - two releases from another lab;
  - a third lab's IPO;
  - two benchmark launches.
  By a count of keywords, about two thirds of the row is off-story. The posts got there by chained merges: `merge` 100
  posts, `rule:thread` 79, `rule:citation` 66, `judge:join` 73.
- **What that does to the "missing" count.** 9 or 10 of the 12 major events "missing" from Mark X are inside this
  row. They are stored, but they never get a row of their own. On the page, the week's biggest news is invisible.
- **Verdict then.** Mark X News could become the main News only once a row could no longer grow by chaining.

### Where the chain was, and the fix

- **Not inside the stories.** The runaway row held 57 Mark X stories, and they were coherent: the release (51 posts),
  the CEO's resignation (39), the second lab's two releases (24 and 21), the scandal (21), the IPO. The `merge`,
  `rule:thread` and `rule:citation` reasons are those stories' own members' reasons; no story held two of the
  happenings. Mark X's merges (decide.py) and Mark IX's link rules were not the chain.
- **In how stories become News rows.** `utils/news_rules.news`, which both Mark IX's News and Mark X's
  (`NewsService.rows` from `markx/news.rows_of`) use, joins stories into one row by any surging name any of their
  posts say, and by any post in two stories. A digest inside one release story named the CEO ("… resigns after 33
  years"), so the CEO's stories joined the release's row; a post in two stories glued two more; and so on to 57.
- **The fix, in that module** (no parallel path; Mark IX's News follows the same rule):
  - a surging name joins a story's post only when it says one of the story's **core names**: the names its lead says
    or at least half its posts say, the most specific of them (`gemini 4 carbon`, never `gemini` inside it);
  - a post in several stories is in its first story's row only;
  - two **large** stories (5+ posts each) join only by a name that says **each one's main name** (the core name most
    of its posts say: a release story's model, not its maker's name its lead also says), and for Mark X only when
    the judge also connected the two stories (its story connections, `built._connected`: development, follow-up,
    the same event).
- **Measured how.** No local copy holds the posts after 2026-11-05, so the rows were rebuilt from the server's own
  page: every row's posts, each post's Mark X stories (its post panel), the surges each row lists, the judge's story
  connections (the post panels). The old code gives the page back exactly (largest rows 397, 67, 44, 41, …), so the
  rebuild is faithful; the new code's largest row is 100 posts (the release alone). Then both pages' rows of
  2026-11-07..12 were labelled blind again, Mark IX's as the owner reads them.

### 1g after the fix: Mark X News (rebuilt) vs Mark IX News, 2026-11-07..12, the runaway counted

| | Mark X | Mark IX |
|---|---|---|
| rows | 118 | 97 |
| a single story | 98 (83%) | 91 (94%) |
| not a duplicate of another row | 102 (86%) | 71 (73%) |
| major rows | 48 | 38 |
| clean major rows (single story, no duplicate) | **33** | 20 |
| major events the other page has and this one lacks | **0** | 14 |

The five days alone (2026-11-08..12): Mark X 33 clean major rows, 0 missed; Mark IX 20 and 14.

- **The owner's bar is met:** Mark X has more clean major rows than Mark IX (33 vs 20) and misses no more events (0
  vs 14). **Mark X News becomes the main News.**
- **What is still weaker in Mark X:** 20 of its 118 rows mix in something, against 6 of Mark IX's 97. Mostly small:
  11 of the 20 are rows of 2–4 posts with one stray post (two unrelated tweets, two digests); in rows of 10+ posts
  the largest off share is a third (a 12-post row mixing a benchmark index with a model's analysis, which Mark IX's
  page mixes the same way), and the 100-post release row is 7% off. Mark IX's worst is an 86-post row, 47% off (the
  CEO's resignation with the other lab's release). Mark X's are the stories' own joins (the judge's pairs), not News
  chaining; the next step for them is the join judge, not News.
- **Still split:** the CEO saga is several rows in both pages (its happenings are judged separate stories: the
  report, the investigation, the resignation, the successor); the IPO is 4 rows in Mark X (its stories were never
  connected by the judge).
- **Mark IX's News changes too** (the same module): rebuilt on the copy (`prep_mxreal`), 125 of its 129 rows are
  unchanged; 4 change. A 32-post row mixing a weights paper with a benchmark's posts splits right. A model family's
  8-post launch row splits into two rows of 4, and a security advisory's row loses 3 replies (they say only the
  advisory's tag). Those two splits are the cost of the core rule.
- **Found on the way:** the judge's story connections are stale for stories whose members changed after the
  question was asked: 16 of 94 `same_event` story connections carry a reason saying the two are unrelated (the
  connection kept a story id whose members moved). The large-story guard needs both the connection and each one's
  main name for that reason.

## Dropped

- **SUBJECT_LINKS** (`markx/built.py`). Its job was to link a leak story to its release by a shared main subject. It
  was off since 0128, measured 0 of 5 right. It is removed with its helpers. A leak story now links to its release
  only through a judged connection. Rows keep `via: "connection"`, so the API and pages are unchanged.
- **The four never-adopted track finders** (`markx/finders.py`): entity, the source prior, the story prior and the
  classifier.
  - The slice's recall check could not run on the copy: `prep_mxreal` holds no tracks.
  - On the server, the owner has 7 labels (7 ✓, 0 ✗) on one track. The classifier's gate is 30 labels.
  - 0147's held-out measure is the only one there is: entity and story added no recall; the source prior gave −2 on
    one track and +3 on the other; the classifier as the order lost 21 points on projects at the 30% budget.
  - So none showed ≥5% recall with no precision loss, and all four are dropped.
  - `mx_track_models` keeps the rows it ever wrote (no migration).
  - `INSIGHT_TRACK_FINDERS` still picks among probe, domain and word.
- **Later developments** (owner, 2026-11-14): no longer produced, read or shown. Gone: the follow-up trigger, its
  questions, the decision run's stage, the story and entity pages' Later blocks, the timeline's later events, the
  labels and the follow switch (`later_api.py`, `MarkXLater.tsx`), and the anchors engine's Later half. Kept: every
  mx_later and mx_later_stops row (keep everything), and the long-lived subject rule (`later.long_lived`, `mains`,
  `specific`, `stopped`) that back in the news and the anchors engine read.
- **Corporate-suffix merges** (owner): `entity_repair.link_suffix` and the `repairs.suffix` switch. The alias questions
  alone decide such pairs.
- **Components** (owner): the rule that made component entities (`components.split`, `plan`, `make`, `preview`,
  `identity.link_components`, the span routing, the `timeline.components` switch). The entity page still lists the
  things under a product apart from its versions (`components_of`).
- **Kept, as the slice asked.** Anchors stay (their back engine; their decision comes after this table).
  mx_happenings stays too: the anchors engine reads its keys, even though 1e leaves pairing off.

## Notes on the labels

- **ent-v4.2 entities outside the excerpt.** 64 entities were not in the first 6,000 characters the labellers saw. 63
  of them were found later in the post's own text. The model reads the whole post by windows (0176), so these were
  labelled on that text. One was found nowhere in the post and is counted wrong.
- **Back and Later.** These were labelled against the back guide's own definitions: development, retold, related,
  unrelated. Back rows come from the old engine; `anchors.shown` is `old` on the server.
- **Folds.** Precision is over the folded posts. Recall is estimated from the shown members' duplicate rate, weighted
  by the page's counts (762 folded, 797 shown members with a head).
- **1g's labels.** Lists were named P and Q at random per day. "Major" and "missing" are the labeller's calls on the
  first titles of each list's rows on the other days. An event buried inside a big row on another day could be missed.
  That is how the runaway row came to light.

## What next

- **Mark X News as the main News:** the switch itself (which page the reader opens) is its own slice; before it, a
  real-data check on main and a look at the server's page after deploy.
- **Back in the news:** next, a back-v2 guide that tells `related` (another version or launch of the family) from
  `development`, measured blind on the same 40 rows plus 40 new ones against the 90% bar.
- **Folds:** next, measure folds on the fixed News (rows no longer mix stories) and give the fold rule a judged check
  for a commentary post (77% precise: 1 in 4 folded posts had a view of its own).
- **ent-v4.2 new entities:** next, re-measure 100+ new entities on the next server copy (89%, lower bound 82.2%
  against 85%); the `other` type and the `recommended` role first.
