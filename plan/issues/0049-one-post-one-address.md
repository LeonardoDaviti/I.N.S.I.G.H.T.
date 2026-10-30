# 0049 — One post, one address: a post is never saved twice under another form of its URL

Status: **spec** (2026-10-30) for v9.6 (owner, 2026-10-30: "draft a spec for the bug and hand it to a sub-agent").

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

## Not in this issue
- Saving the outside links inside posts, and grouping one story across sources: 0050.
- Different posts that tell the same story (same text across sources, same title): 0050. Those aren't
  copies to delete; they are one story with several sources.
