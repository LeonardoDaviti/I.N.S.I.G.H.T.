# 0205: Mark X News becomes the main News (Stealth v10.18)

Status: **built** (branch `v1018-measure`, which has v10172 merged in: 0198's kept pages and 0202's API memory). Not
merged, not pushed, not deployed. No migration. Follows [0203](0203-ship-or-drop.md), where Mark X News passed the
owner's bar (33 clean major rows against 20, 0 missed events against 14).

## 1. The reader's News reads Mark X's rows

- **One reading.** `GET /api/news` (every scope: Main, a track, a source, a voice) reads Mark X's stored rows. These
  are `mx_news` of its newest written run: the rows each decision run writes, which 0198's jobs process also keeps
  for `/markx`. They go through Mark IX's own News reading. `repo_news.news_posts(..., mx_run=)` reads mx_news (its
  news_posts rows in `posts`) in place of news_stories and news_posts. Scopes, leads, voices, read state, lines and
  paging are one path.
- **The choice** (`NewsService.rows_of`).
  - Mark X's rows when Mark X is on and its newest written run has a row in the 30-day window.
  - Otherwise Mark IX's rows, with `fallback: true` and a `note`. The two notes are "Mark X has no News yet (a new
    install, or its worker has not run): this is the older News" and "Mark X is off on this install …".
  - `?mark=ix` asks for the older News. The answer says which rows it holds (`mark`: `x` | `ix`).
- **The reader.**
  - "Older News view" above the list shows Mark IX's rows, and "Back to News" returns.
  - The fallback's note is a status line, and no switch is offered then: the page already is the older News.
  - Mark IX's News is not deleted: its job and rows run as before.
- **Not switched (stated):**
  - A post page's "in News" line (`row_of`) still names its Mark IX row.
  - Search's News filter reads Mark IX's rows.
  - Both are one-line follow-ups on the same switch once the owner has read the new main page.
- **Tests.**
  - The choice: on with rows, on with none, off, and `ix`.
  - A track's scope over Mark X's rows, and Mark IX's rows unchanged.
  - The route's `mark` and the bad value.
  - The reader's switch and back, and the fallback's note.

## 2. The weaker parts of Mark X News

### (a) Small rows with one stray post: the class

The 11 small mixed rows from 0203's labels were labelled from titles. I read each post's own text and links:

| class | rows | owner |
|---|---|---|
| on-story by its text (the labeller had only the title) | 6 | none. Examples: a reddit post on the benchmark it cites; a tweet sharing the article; the result's own announcement; the release's own reddit post |
| a roundup joined to a story by Mark IX's citation rule | 3 | **decide.py checks**: fixed |
| a commentary citing the story's page in passing | 1 | the check (a 2-voice story's second voice goes only once asked again, 0121 D1) |
| a "reaction" join of an essay on another topic | 1 | the join judge |

- **The rule.** One of the three roundup rows was two digests citing one outside page: a story of their own. Its
  first digest was never asked, because `plan_pass1` skipped a story's first post before asking whether it is a
  roundup. A roundup is now checked against the story's other reports even when it is the first post ("digest item"
  demotes it, as any roundup).
- **Cost.** On the copy's 30 days, 5 of 132 stories of 2+ voices begin with a roundup: 5 more check questions.
- **Not measurable on the rebuild yet.** The change asks questions; their answers move the rows on the next runs.

### (b) The IPO in 4 rows

- **Why.** Its three stories (12, 7 and 5 posts, each with the company as its main name) were connected by the judge,
  so the large-story guard allowed them. But `news_rules.news` joined each member of a surge to the surge's first
  post only, and that first post belonged to the release story, which each IPO story refused (another main name).
- **The fix.** Each member now tries every group the surge has reached.
- **On the rebuild of 2026-11-07..12:**
  - The IPO's three rows become one of 22 posts.
  - No other row changes.
  - Clean major rows go 33 → 34: the three IPO rows were major but duplicates, and are now one clean row.
  - Missed events stay at 0, because no row lost a post.

## 3. Stale story connections

- **The fix.**
  - A typed connection now records the members its question showed (evidence `shown`): a connect question's
    earliest members of each story, a merge's two sides, or a late post's story side.
  - It holds only while those posts are still members of the stories it joins (`decide.holds`, over this run's
    `members_of`).
  - One that doesn't hold is not found, so `persist_connections` closes it. The pair, if still a candidate, is asked
    again over the current members (its connect input changes).
  - Only those pairs are asked again; there is no full re-ask.
  - `persist_connections` compares the recorded members too. The first run after the deploy rewrites the current
    connections once with their record, and asks nothing.
- **Measured on the copy** (a full decision run, old code against new, each on its own clone): the same 4 current
  story connections, now each with its record. The copy holds none of the server's stale cases.
- **What I could not trace.** The server's pages show the 16 stale connections, but not their history. So the exact
  path that kept them open is not traced here; any path now closes them, because none of the 16 holds its shown
  members.
- **Unchanged.** `markx/unchanged.py` stamps whole passes so a no-op pass is skipped. It does not fit a per-connection
  record, so the record lives with the connection.

## Also fixed

- **0203's `rows_of`.** It passed a dry reading's new story ids ("new:<key>") to `built._connected`, whose uuid cast
  failed in the decision run's check. Only stored stories' ids are now asked. `test_markx_incremental` caught it.
