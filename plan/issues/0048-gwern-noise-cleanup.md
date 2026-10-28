# 0048 — Remove the Gwern posts that aren't Gwern's writing

Status: **built, not deployed** (2026-10-28, migration 0036) for v9.5 (owner, 2026-10-28).

## The case
0043 stops the Gwern reader from storing topic directories (`/doc/**`, including `/doc/**/index` and `/abstract` pages) and newsletter issues (`/newsletter/...`). Posts stored before 0043 from those addresses stay.

## Decided
- **A migration (0036)** deletes posts of sources whose address is on gwern.net (www. ignored) whose URL path starts with `/doc/` or `/newsletter/`.
- **Never deleted:** posts saved to Later or kept, and pages saved by hand (0031). Read state and positions of deleted posts go with them, through whatever the existing delete path or foreign keys do. Check that no table is left with orphans.
- Use the existing deletion path or cascades; no new mechanism. Search vectors (0040) go with the row.
- It must be safe to run on a database with no Gwern source, and running it twice must do nothing.

## Done when
- Backend tests run the migration on a `_test` DB with: Gwern posts on each path, an essay that stays, a kept and a Later post on a `/doc/` path that stay, a non-Gwern site with a `/doc/` path that stays, and a second run that does nothing.
- A dry count on `insight_preview` (read only: a SELECT, not the migration) is recorded here.

## Built
- **One file**, `backend/insight_core/db/migrations/0036_gwern_noise_cleanup.sql`: a single
  `DELETE FROM posts ... USING sources`. No code changes; the reader, saver and adapter are as
  0043 left them.
- **The rule:** a post is deleted when
  - its source's `handle_or_url`, lowercased, has the host `gwern.net` (scheme optional, a
    leading `www.` dropped, port and path ignored): `gwern.substack.com` and other sites do not
    match;
  - the path of the post's own `url` (query and fragment left out) starts with `/doc/` or
    `/newsletter/` (so `/doc/**/index`, `/doc/**/abstract` and the copies under `/doc/`);
    `/doctor-...` does not;
  - and it has no `post_reader_state` row with `later_at` or `starred_at` set (Later, Keep).
- **Saved pages (0031)** belong to the built-in Saved source (platform `saved`, address
  `Saved`), so a saved `gwern.net/doc/...` page never matches the source rule.
- **What goes with the row:** the three tables that point at `posts` today, all
  `ON DELETE CASCADE` (checked on `insight_preview`'s `pg_constraint`): `post_reader_state`
  (read state, the 0030 position, the 0031 Later/Keep marks), `post_interactions` (the open
  log) and `post_notes` (no code reads or writes it since 0027). The search vector (0033,
  issue 0040) is a column of `posts`. Folders hold sources, not posts. No new mechanism.
- **Idempotent:** without a Gwern source nothing matches; a second run deletes nothing.
- **Test** (`test_migrate_runner.py`, `GwernNoiseMigrationTests`, on the `_test` DB, rolled
  back): a `www.gwern.net` source with a `/doc/.../index`, a `/doc/.../abstract`, a `/doc/` copy
  (with a note) and a `/newsletter/` issue (with an interaction), all gone, the directory's read
  state and position with it; an essay, a blog post and `/doctor-...` kept; a kept `/doc/` post
  and a Later `/newsletter/` post kept with their state; a saved `gwern.net/doc/` page, a
  `gwern.substack.com/doc/` post and an `example.invalid/doc/` post kept; no orphan in the three
  tables; the second run's row count 0. Backend suite: 785 tests, OK.

### Dry count on `insight_preview` (2026-10-28, read only: `BEGIN READ ONLY`, the migration's predicates as a SELECT, rolled back)
- **Gwern sources: 0**, so **0 posts would be deleted, 0 exempt (Keep / Later), 0 kept** in
  every path kind (`/doc/**/index`, `/doc/**/abstract`, other `/doc/`, `/newsletter/`, writing).
  No post of any source has `gwern` in its address. The preview DB has 94 sources (58 RSS, 23
  YouTube, 12 Telegram, 1 Reddit) and 7,720 posts and has no Gwern source, so the real
  count is only known on the database that has one.

### Left open
- The live count is not measured here (the server is out of reach for this issue). Before
  deploying, the same SELECT on the server tells how many go.

