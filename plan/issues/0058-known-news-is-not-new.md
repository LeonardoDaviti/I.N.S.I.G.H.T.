# 0058 — A page your sources linked before is not "new to you"

Status: **built, not deployed** (2026-10-31, migration 0043) for v9.8 (owner, 2026-10-31: "why this is posted yesterday, if it was published on Aug 18?").

## The case (the lab, the server's data)
- **"Claude accelerates protein design and analytical chemistry"** (`anthropic.com/research/…`) was published on 18 Aug. The page-watched source "anthropic.com/research" first saw it on 30 Oct.
- **0039's "new to you is new"** set `surfaced_at`, so it sits on top of the Main feed with "published Aug 18".
- **But you did get it in August:** six of your sources' posts linked that page from 19 Aug on (Plain Links, turbo_bench and others). It's in a story from 19 Aug.
- **"New to you" was decided for pages you never saw** (Gwern's "Lean Software Scaling Laws"). A page your sources already linked is known news.

## Decided
- **A page a post links is known.** When a page-based source saves a page that would be surfaced as "new to you", it is not surfaced if a stored post from another source linked that page's address before (0050's post links, before the page was first seen). It keeps its published date and sits where that date puts it.
  - Updates (0039's changed pages) still surface as before; this is only about first sight.
- **One-off cleanup:** a migration clears `surfaced_at` on stored posts that meet the same condition and were surfaced as new to you, not as an update. On the server copy that's 1 post; record the count.
- **No new setting.**

## Done when
- **Backend tests:**
  - a never-linked old page still surfaces;
  - a linked one doesn't;
  - an update still surfaces;
  - a link from the same source doesn't count;
  - a link made after the page was seen doesn't count.
- **The migration's count** on a copy of the lab is recorded here.
- **Lab case** `protein-design-surfaced` passes.

## Built
- **The rule** (`backend/insight_core/db/repo_posts.py`, `LINKED_BEFORE_SQL`): the saver's "new to you" update now also needs that no stored post **from another source**, **first seen (`fetched_at`) before the page was**, has a `post_links` row whose `target_url` is the page's `normalized_url` (0050 normalizes both the same way, so `http://www.` and `https://` forms match).
  - **Order of operations:** in `_after_save` the new post's own links are written first, then the surfacing update runs. Its own links can't count (same source), and the links compared are the ones other posts stored when they were saved (or the story job's backfill). The page's address is compared against `post_links.target_url` (indexed: `post_links_target_idx`).
  - **Updates are untouched:** `repo_page_watch` still sets `surfaced_at = now()` on a meaningful change, whether or not the page was linked.
  - **Every link counts,** boilerplate ones included: a signature link to a page is a page you were shown.
- **Migration 0043** (`0043_known_news_is_not_new.sql`) clears `surfaced_at` on stored posts that meet the same condition **and were surfaced as new to you.** How it tells the two apart from what 0039 stores:
  - "new to you" sets `surfaced_at = fetched_at` (when first seen, never moved) and writes nothing else;
  - an update sets `surfaced_at = now()` at the check and always writes `metadata.page_update`;
  - so it clears only posts with `surfaced_at = fetched_at` and no `page_update`. A page surfaced as new and later updated keeps its update's `surfaced_at`.
- **The count on a copy of the lab:** `insight_lab` (41,570 posts, at 0041) was copied by `pg_dump` into `insight_m0058_lab_test`, then 0043 was run there. **It cleared 1 post**, "Claude accelerates protein design and analytical chemistry". It was the only surfaced post on the copy. Its address was linked by 6 posts from 4 other sources between 23 Aug and 11 Oct, all before it was first seen on 30 Oct. The copy was dropped afterwards.
- **Lab case `protein-design-surfaced`: passes.** After 0043 its `surfaced_at` is NULL, so it sorts at its published date (18 Aug).
- **Tests** (`test_page_change_watching.py`, `KnownNewsTests`, 6): a never-linked old page still surfaces; one another source linked before keeps its date; an update of a linked page still surfaces; a link from the same source doesn't count; a link made after the page was seen doesn't count; the migration clears only a linked page surfaced as new to you (not an update, an unlinked page, a same-source link or a later link). **Suite: 988 tests, OK.** No frontend change.

## Left open
- **"Before" means the linking post was first seen before the page** (`q.fetched_at < p.fetched_at`), not published before it. A post fetched in the same transaction as the page doesn't count (an equal time isn't before).
- **Only the page's `normalized_url` is matched.** A page whose stored address differs from the address others linked (a redirect, another canonical form) still surfaces. The lab case didn't need more.
- **A page saved before the story job read the other posts' links** (posts stored before 0050 that are still unscanned) can still surface. That's only possible during the first backfill after 0050 is deployed.
