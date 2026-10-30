# 0049 — One post, one address: a post is never saved twice under another form of its URL

Status: **built, not deployed** (2026-10-30, migration 0038) for v9.6 (owner, 2026-10-30: "draft a spec for the bug and hand it to a sub-agent").

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
  - `utm_` tags (230 preview posts carry them: danielmiessler.com, lexfridman.com);
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
- **The rule:** two URLs are the same post when their `normalized_url` is equal. The normalizer
  (`utils/url_normalization.py`) drops, as before, tracking keys (`utm_*`, `ref`, `source`, ...),
  `www.`, the trailing slash and the fragment, and now also:
  - writes `http` as `https` in `normalized_url` (`canonical_url` keeps the scheme it was given);
  - keeps a fragment starting with `/` or `!` (`#/post/1`, `#!/post/1`): a single-page site's
    address.
- **The saver** (`db/repo_posts.py`): no new path. The INSERT keeps `ON CONFLICT (url)`; a post in
  another form of a stored URL violates the new unique index `posts_normalized_url_unique`, which
  is handled by the same savepoint-and-resolve loop as `posts_source_external_unique`. The
  resolver's lookup finds "the row this post already is" by exact `url` first, else by
  `normalized_url`, then updates that row by id, never writing `url`: the kept row keeps its
  `url`, `id` and everything pointing at it. Across sources as with the exact url: the row stays
  with its source.
- **Migration 0038** (`0038_one_post_one_address.sql`):
  1. brings stored `normalized_url` to the new normalizer (`http://` → `https://`; an address
     fragment appended) before merging, so two `#!/` pages are never merged;
  2. per group sharing a `normalized_url`, keeps the row the owner touched (a reader-state row
     with read, Later, Keep or a position; a note; any logged interaction), else the first seen
     (`fetched_at`, then `created_at`, then `id`);
  3. moves the others' state to it: read / Later / Keep if any row has them (earliest time), the
     furthest position (`resume_block` with its `resume_blocks`), notes (joined with a blank line,
     the kept row's first), the interaction log, and a page watch (0037) when the kept row has
     none; then deletes the others (their own rows cascade);
  4. replaces `posts_normalized_url_idx` with the unique `posts_normalized_url_unique` (NULLs
     allowed).
  Tables pointing at `posts`, from `pg_constraint` on `insight_preview`: `post_reader_state`,
  `post_notes`, `post_interactions`, `post_watch` (all `ON DELETE CASCADE`). Safe with no copies;
  a second run changes nothing.
- **Tests** (all on the `_test` DB, rolled back):
  - `test_post_fields_utils.py`: the four forms (`#atom-everything`, trailing slash, `utm_source`,
    `http://www.`) give one `normalized_url`; `#!/post/1`, `#/post/2` kept and distinct.
  - `test_repo_posts_upsert.py`: saving `…/a/#atom-everything`, `…/a/`, `…/a/?utm_source=rss`,
    `http://www.…/a` leaves one post, the first row with its url; `#!/post/1` and `#!/post/2` stay
    two; the same exact URL on another source updates the first row and keeps its source; another
    form on another source (with an external id) updates the first row.
  - `test_migrate_runner.py` (`OnePostOneAddressMigrationTests`): a pair where only the newer row
    has state (read, an open; the older row's page watch moves to it), a pair where both have it
    (read and position 3/10 on one, Later, position 7/10 and a note on the other: the older keeps
    read, Later, 7/10 and the note), an untouched pair (older kept), an `http` pair stored by the
    old normalizer (merged), two `#!/` pages (kept apart, their `normalized_url` fixed); the set of
    tables pointing at `posts` is exactly the four handled; no orphans; a second run changes
    nothing.
  - Backend suite: 873 tests, OK. No frontend change.

### Count on `insight_preview` (2026-10-30, read only)
- **17 groups, 34 rows** (17 would be removed), all Simon Willison's `#atom-everything` pairs;
  **0 groups whose texts differ** (by `content_hash`, and by `md5(content || content_html)`).
  No stored `normalized_url` starts with `http://` and no post URL has a `#/` or `#!` fragment, so
  step 1 of the migration changes nothing there. 2 rows in the groups have reader state.

### The count on the server, before deploying (read only, not run)
From the compose directory on the server (service `postgres`, user and database `insight`; change
`-U` / `-d` if `.env` sets others). One row: `groups`, `rows_removed`,
`groups_with_different_text`. The grouping key is the migration's (http written https, an address
fragment kept). If `groups_with_different_text` is not 0, stop: the normalization merges posts
that aren't the same.

```sh
docker compose exec -T postgres psql -U insight -d insight -v ON_ERROR_STOP=1 -c "SET default_transaction_read_only = on" -c "SELECT count(*) AS groups, coalesce(sum(n - 1), 0) AS rows_removed, count(*) FILTER (WHERE texts > 1) AS groups_with_different_text FROM (SELECT count(*) AS n, count(DISTINCT content_hash) AS texts FROM posts WHERE normalized_url IS NOT NULL GROUP BY regexp_replace(normalized_url, '^http://', 'https://') || coalesce('#' || substring(url FROM '^[^#]*#([/!].*)$'), '') HAVING count(*) > 1) g"
```
On `insight_preview` it gives `17 | 17 | 0`.

### Left open
- `normalized_url` stored by older normalizer versions is not recomputed beyond the two changes
  above (SQL cannot rerun the Python normalizer); such a row only matters if a later save of the
  same post computes a different value, which then saves it as before rather than merging.

## Not in this issue
- Saving the outside links inside posts, and grouping one story across sources: 0050.
- Different posts that tell the same story (same text across sources, same title): 0050. Those aren't
  copies to delete; they are one story with several sources.
