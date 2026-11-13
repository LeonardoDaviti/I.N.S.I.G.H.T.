# 0049 — One post, one address: a post is never saved twice under another form of its URL

Status: **built, not deployed** (2026-10-30, migrations 0038 and 0041; revised after the server-data rehearsal: the same post also has the same title) for v9.6 (owner, 2026-10-30: "draft a spec for the bug and hand it to a sub-agent").

## The case
On `insight_preview`, 17 of Simon Willison's posts are stored twice:
`…/2026/Aug/10/openclaw/#atom-everything` and `…/2026/Aug/10/openclaw/`. The two rows of each pair have the same
source, title and text (the same `content_hash`).
- Up to 12 Aug the feed's posts were saved with the `#atom-everything` fragment (161 posts). From 13 Aug the
  same posts arrive without it. Every post still in the feed window then got a second row.
- `posts.url` is unique, but it is compared exactly. `normalized_url` (fragment and tracking keys dropped,
  `www.` and the trailing slash ignored; `utils/url_normalization.py`) is computed and saved for every post,
  then never used when saving.
- **The class, not the site:** any change in how a source writes a link makes a second copy:
  - a fragment;
  - `utm_` tags (230 preview posts carry them: danielmiessler.com, longform_pod.com);
  - `http` → `https`, `www.`, a trailing slash.
- One of the doubled pairs has read state on both rows, so the owner can see the same post twice, once read
  and once unread.

## Decided
- **Two URLs with the same `normalized_url` are the same post.** Saving a post whose `normalized_url`
  matches an existing post updates that post, exactly as an exact `url` match does today. This holds across
  sources, as the exact-URL rule already does.
- **A database guarantee, not only a check in Python:** a unique index on `normalized_url` (posts without
  one are allowed), so a race or a new save path cannot bring the copy back. Mind the existing insert:
  one `ON CONFLICT` target per INSERT, and the retry loop around `posts_source_external_unique`
  (`repo_posts.py`).
- **The kept row keeps its `url`, `id` and everything pointing at it.** The new form of the URL does not
  overwrite it. Links, read state and positions stay valid.
- **Fragments that are addresses stay part of the address.** A fragment starting with `/` or `!`
  (`#/post/1`, `#!/post/1`, single-page sites) is kept in `normalized_url`. Every other fragment is
  dropped, as today. There are none on the preview today; it's a guard for the class.
- **Cleaning the copies already stored:** a migration (0038) merges every group sharing a `normalized_url`
  into one row:
  - **Which row stays:** the one the owner touched (Later, Keep, a note, read state, an open). If both or
    neither were touched, the older one.
  - **What moves to it:** the owner's state from the other rows. Read if either was read; Later and Keep
    if either has them; notes; the open log; the furthest reading position.
  - **What it checks:** every table that points at `posts`, checked in `pg_constraint`, not assumed
    (0048 found three, and 0037's page-watch table may be a fourth). No orphans.
  - **Safety:** safe on a database with no copies; a second run does nothing.
- **Before the index:** check on the preview, read only, that no group sharing a `normalized_url` holds
  posts with different text. If one does, normalization merges things that aren't the same. Stop and
  report it; do not widen the rule to make the index fit.
- **No new mechanism:** the existing normalizer, the existing saver, and one migration.

## Done when
- Backend tests on a `_test` DB:
  - saving `…/a/#atom-everything`, then `…/a/`, then `…/a/?utm_source=rss`, then `http://www.…/a`,
    leaves one post (the first row);
  - a `#!/post/1` and a `#!/post/2` stay two posts;
  - the migration merges a pair where only the newer row has state, and a pair where both have it
    (read on one, Later on the other, a note on one), keeping all of it;
  - a second run of the migration does nothing;
  - posts on different sources with the same exact URL behave as before.
- Backend suite and frontend checks green.
- Recorded here:
  - a read-only count on `insight_preview` (expected: 17 groups, 34 rows);
  - a read-only one-liner the owner runs on the server before deploying, giving the groups, the rows that
    would be removed, and groups whose texts differ. Same form as 0048's.

## Built
**Revised after the rehearsal on the server's data (2026-10-30): the same address is not enough; the
same post also has the same title.** On a copy of the server, 63 groups share a `normalized_url`
(the migration's key), 28 of them with different texts. 24 of those are one post with excerpts of
different lengths. 4 are different Daring Fireball posts at one address: a footnote post told apart
only by `#fn1-…`, a "One More Thing" post only by `#:~:text=…`, and six WorkOS sponsor posts only by
`utm_campaign` (two groups). Merging on the address deleted 6 real posts, and the unique index then
made such posts overwrite each other on save. Their titles differ; the copies' titles don't.

- **The rule:** two posts are the same post when their `normalized_url` is equal **and** their
  titles are equal under `post_title_key` (a SQL function, migration 0038): HTML entities decoded
  (the named ones feeds use and every numeric one), non-breaking spaces as spaces, whitespace runs
  as one space, trimmed, lower case; no title is `''`. One function, used by the migration and the
  saver alike. The normalizer (`utils/url_normalization.py`) is unchanged by the revision: it drops
  tracking keys (`utm_*`, `ref`, `source`, ...), `www.`, the trailing slash and the fragment, writes
  `http` as `https` in `normalized_url` (`canonical_url` keeps the scheme it was given) and keeps a
  fragment starting with `/` or `!` (`#/post/1`, `#!/post/1`: a single-page site's address).
- **The saver** (`db/repo_posts.py`): a post whose exact `url` is stored takes the INSERT's
  `ON CONFLICT (url)` path, as before, and costs nothing more. Otherwise `_other_form` takes a
  transaction-scoped advisory lock on the `normalized_url` and looks for a post at that address
  with the same title key. Found: the resolver updates that row by id, never writing `url` (the
  kept row keeps its `url`, `id` and everything pointing at it). Not found: the INSERT runs, and the
  lock, held until the batch commits, makes a concurrent save of another form wait and then find
  this row. A different form of a stored URL **with another title is saved as a new post.** The
  `url` uniqueness, `ON CONFLICT (url)` and the savepoint-and-resolve loop around
  `posts_source_external_unique` are as before; the resolver's url row is the exact url's, else the
  first seen (`fetched_at`, `created_at`, `id`) at the same address with the same title. Across
  sources as with the exact url: the row stays with its source.
- **No unique index on `normalized_url`:** it cannot say "same address and same title" when a
  re-fetch may change a title. It stays the plain `posts_normalized_url_idx`.
- **Every join on `normalized_url` picks one post** (the first seen: `fetched_at`, `created_at`,
  `id`) through a `LATERAL ... LIMIT 1`: `repo_stories.load_posts` (a link's stored post),
  `repo_news.citations`, `classics` and `background`; `saved_service.stored_post` prefers an exact
  url, then the first seen. Two posts at one address never double a link, a citation or a classic.
- **Migration 0038** (`0038_one_post_one_address.sql`), **edited in place** (never deployed):
  0. defines `post_title_key`;
  1. brings stored `normalized_url` to the normalizer (`http://` → `https://`; an address fragment
     appended) before merging, so two `#!/` pages are never merged;
  2. per group sharing a `normalized_url` **and a title key**, keeps the row the owner touched (a
     reader-state row with read, Later, Keep or a position; a note; any logged interaction), else
     the first seen (`fetched_at`, then `created_at`, then `id`);
  3. moves the others' state to it: read / Later / Keep if any row has them (earliest time), the
     furthest position (`resume_block` with its `resume_blocks`), notes (joined with a blank line,
     the kept row's first), the interaction log, and a page watch (0037) when the kept row has
     none; then deletes the others (their own rows cascade);
  4. leaves `posts_normalized_url_idx` a plain index.
  Tables pointing at `posts`, from `pg_constraint` on `insight_preview`: `post_reader_state`,
  `post_notes`, `post_interactions`, `post_watch` (all `ON DELETE CASCADE`). Safe with no copies;
  a second run changes nothing.
- **Migration 0041** (`0041_same_post_same_title.sql`), for the databases that ran the first 0038
  (`insight_preview`, `insight_lab`): defines `post_title_key` (the same definition as 0038's; a
  test checks the two are identical), drops `posts_normalized_url_unique` and recreates the plain
  `posts_normalized_url_idx`. Elsewhere it changes nothing. What the first 0038 merged there stays
  merged (on the preview: the 17 same-title Simon Willison pairs).
- **Tests** (all on the `_test` DB, rolled back):
  - `test_post_fields_utils.py`: the four forms (`#atom-everything`, trailing slash, `utm_source`,
    `http://www.`) give one `normalized_url`; `#!/post/1`, `#/post/2` kept and distinct.
  - `test_repo_posts_upsert.py`: saving `…/a/#atom-everything`, `…/a/`, `…/a/?utm_source=rss`,
    `http://www.…/a` with the same title (case, whitespace and `&amp;` / `&#38;` / `&nbsp;` apart)
    leaves one post, the first row with its url; the Daring Fireball shapes (a `#fn1-` fragment, a
    `#:~:text=` fragment, three `utm_campaign` posts) with different titles stay seven posts, and
    re-fetching each updates only its own row; another form with another title is a new post, and a
    third form with the first title goes to the first; the address lock is taken for a url not
    stored and not for a re-fetch; `#!/post/1` and `#!/post/2` stay two; the same exact URL on
    another source updates the first row and keeps its source; another form on another source (with
    an external id) updates the first row.
  - `test_migrate_runner.py` (`OnePostOneAddressMigrationTests`): the pairs of the first version
    (only the newer row has state; both have it; untouched; `http` by the old normalizer; two `#!/`
    pages kept apart), an `&nbsp;` / case pair (merged), and the Daring Fireball shapes (kept, all
    seven); the set of tables pointing at `posts` is exactly the four handled; no orphans; a second
    run changes nothing. 0041 on a database with the unique index and no function: the plain index
    and the function after it, twice. `post_title_key` on entities, spaces, case and `NULL`.
  - `test_news.py`: two posts at one address with different titles, linked by others: each link
    once in the story job, one citation per citing post, one classic and one Background entry, all
    on the first seen post.
  - Backend suite: 964 tests, OK.

### Rehearsal on the server's data (2026-10-30)
A `_test` database restored from `backups/server/insight-server-2026-10-30.dump` (at 0037),
migrated to 0041, then dropped:
- before: 41,608 posts; 63 groups share an address;
- after: 41,549 posts (**59 removed: 59 groups**, the 58 with the same title exactly and
  `danieldelaney.net/atomic`, "Atomic design in&nbsp;1998" / "Atomic Design in&nbsp;1998"); 4 groups
  still share an address, the Daring Fireball ones, every post kept; no group shares an address and
  a title key; `posts_normalized_url_idx` plain, no unique index;
- a second run of 0038 and 0041 left every post id and `normalized_url` as they were.
None of the merged rows had owner state.

### Count on `insight_preview` (2026-10-30, read only, before the revision)
- **17 groups, 34 rows** (17 would be removed), all Simon Willison's `#atom-everything` pairs;
  **0 groups whose texts differ** (by `content_hash`, and by `md5(content || content_html)`).
  No stored `normalized_url` starts with `http://` and no post URL has a `#/` or `#!` fragment, so
  step 1 of the migration changes nothing there. 2 rows in the groups have reader state.

### The count on the server, before deploying (read only)
From the compose directory on the server (service `postgres`, user and database `insight`; change
`-U` / `-d` if `.env` sets others). One row: `groups` (that would merge under the new rule: one
address and one title), `rows_removed`, `groups_with_different_text` (among those: expected, one
post with excerpts of different lengths), `addresses_kept_apart` (addresses shared only by posts
with titles of their own). The address is the migration's (http written https, an address fragment
kept); the title is a close inline form of `post_title_key` (the server has no such function before
deploying), covering the entities the server's titles hold.

```sh
docker compose exec -T postgres psql -U insight -d insight -v ON_ERROR_STOP=1 -c "SET default_transaction_read_only = on" -c "WITH k AS (SELECT content_hash, regexp_replace(normalized_url, '^http://', 'https://') || coalesce('#' || substring(url FROM '^[^#]*#([/!].*)$'), '') AS address, lower(btrim(regexp_replace(translate(replace(replace(replace(replace(replace(replace(replace(coalesce(title, ''), '&nbsp;', ' '), '&lt;', '<'), '&gt;', '>'), '&quot;', '\"'), '&#39;', ''''), '&apos;', ''''), '&amp;', '&'), chr(160), ' '), '\s+', ' ', 'g'))) AS title FROM posts WHERE normalized_url IS NOT NULL), g AS (SELECT address, count(*) AS n, count(DISTINCT content_hash) AS texts FROM k GROUP BY address, title HAVING count(*) > 1), a AS (SELECT address FROM k GROUP BY address HAVING count(*) > 1 AND count(DISTINCT title) = count(*)) SELECT count(*) AS groups, coalesce(sum(n - 1), 0) AS rows_removed, count(*) FILTER (WHERE texts > 1) AS groups_with_different_text, (SELECT count(*) FROM a) AS addresses_kept_apart FROM g"
```
On the server copy of 2026-10-30 it gives `59 | 59 | 24 | 4`, which is what the migration did on
the rehearsal.

### Left open
- `normalized_url` stored by older normalizer versions is not recomputed beyond the two changes
  above (SQL cannot rerun the Python normalizer); such a row only matters if a later save of the
  same post computes a different value, which then saves it as before rather than merging.
- **A post retitled while its link changes form** is saved as a new post: the title is part of
  identity now. A re-fetch at the same exact url that retitles it updates it as before.
- **Posts without a title** at one address count as one post (both keys are `''`): on the server
  copy no such group exists.
- **No database guarantee** for the rule: the advisory lock covers the saver; another save path
  writing `posts` directly would not take it. Two saves of new posts locking addresses in opposite
  orders can deadlock; Postgres then fails one post (its savepoint rolls back, the batch carries
  on) and the next fetch saves it.
- What the first 0038 merged on `insight_preview` and `insight_lab` is not split again; on the
  preview all 17 pairs had the same title.
- `post_title_key` decodes the named entities feeds use (`&amp; &lt; &gt; &quot; &apos; &nbsp;`,
  dashes, quotes, `&hellip;`) and every numeric one, not the full HTML list.

## Not in this issue
- Saving the outside links inside posts, and grouping one story across sources: 0050.
- Different posts that tell the same story (same text across sources, same title): 0050. Those aren't
  copies to delete; they are one story with several sources.
