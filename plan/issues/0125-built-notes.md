# 0125: built notes (slice B of v10.4 Stealth)

Connected on every post: Earlier, Later and Outside INSIGHT, read from the author's own links, no model. Built on
branch `worktree-agent-a06072abbcfd6663f`, off main `edb99d1`. Nothing pushed or merged.

## The owner's open decisions: the defaults taken
1. **Earlier rows to the same source's own posts:** shown, marked "same source".
2. **The caps:** Earlier 10, Later 10 (the newest kept, shown oldest first), Outside 5. Each group says "+N more",
   which asks for the full list (`?all=true`).
3. **Placement:** after the text and before the story tree ("Covered by").

## What was built (one commit per part)
1. **The Reddit fix.** `utils/post_links.decoded_html()` decodes escaped HTML once: no raw `<a href`, and `&lt;a`
   present. `body_hrefs` and `extract_links` both use it. Migration 0076 sets `links_scanned_at` to NULL on the posts
   stored this way. The story job's link reading then reads them again. Their new `post_links` rows queue them for
   the story job (0059's trigger), so the stories they change are regrouped. `rules_stamp` stays the same: the stamp
   sample has no escaped HTML, so the deploy starts no full rebuild.
2. **The reason rule.** `utils/post_refs.py` is a port of the lab's `links_v1_supp.reason` and adds nothing to it.
   `refs_of()` reads every http(s) address of `body_hrefs`, absolute and normalized, the first link to an address
   kept, and stores the reason from steps 1, 2 and 4. `shown_reason()` adds step 3 (the stored post's title) at read
   time, before the link words, on Earlier and Later rows. Outside rows get a quote or a sentence only.
   - **Parity, checked locally on the lab's private files (nothing committed):** of the lab's 59,297 rows, the port
     gives the same line on 59,152.
   - The 13 that differ and the 132 whose address no longer exists have one cause: two hrefs of one post that now
     normalize to one address. 0126 made gift links normalize to their plain twin, so the first href's sentence wins.
3. **Storage.**
   - Migration **0076** adds `post_refs` and `posts.refs_scanned_at`.
   - `db/repo_post_refs.py` writes only the rows that differ. A link gone from the text is closed with `valid_to`,
     never deleted (keep everything). A link that comes back is opened again.
   - Rows are written where `post_links` is:
     - `StoriesRepository.save_post_links`: ingestion's writer, for new and updated posts;
     - `fill_missing_links`: the story job's link reading, after a repair.
   - **The backfill.** `PostRefsRepository.fill_missing` reads 500 posts a transaction, `FOR UPDATE SKIP LOCKED`, and is
     resumable by `refs_scanned_at`. It runs:
     - at the story job's start (`StoriesService.fill_refs`, then one signature pass over every source);
     - by hand: `python -m insight_core.scripts.backfill_post_refs`.
4. **The signature pass.** `StoriesRepository.mark_boilerplate` also marks `post_refs` by the same rule: a link in at
   least 25% of a source's posts, and in at least 4 of them. The own-site rule stays with `post_links` only: a link to
   the source's own site is the Earlier row to its own post.
5. **The API.** `GET /api/posts/item/{id}/connected[?all=true]` returns `{earlier, later, outside, more}`, or a 404.
   - Each row: `{post_id, url, source, source_id, date, title, same_source, reason, reason_kind}`.
   - An Outside row also has `{address, host}`, and its link words as `title`.
   - Resolved at read time, as 0057's internal links are: the post with that exact url, else the first seen at its
     normalized address, never the post itself. A target stored after its linker becomes a row with no re-run.
   - Later finds the post by its `normalized_url` or by its `url` normalized.
6. **The invariant.** `refs.every_link` (checks/invariants.py): every post's `body_hrefs` http(s) link has an open
   `post_refs` row. On a version without the table it reports "not measurable".
7. **The post page.** `components/post/Connected.tsx` is lazy, in its own chunk.
   - Placed after the text and Background, before Covered by. It is always on and not behind `INSIGHT_MARKX`.
   - Loaded after the post: the post never waits on it. Nothing shows while it loads, when it fails, or when the post
     has no row.
   - On a phone (below `sm`), Later and Outside fold and Earlier stays open.
   - The section has `id="connected"`, for the Mark X panel's link (see below).

## Deviations
- **The route is `/api/posts/item/{id}/connected`,** not `/api/posts/{id}/connected`. Every post route is under
  `/api/posts/item/`, so this follows the existing convention.
- **"Fetch <source>" on an Outside row** is a "Save" link to Save any page (`/save?url=…&title=…`), whose 0122 path
  shows "Fetch <source>" when a followed source owns the page. It stays one click, and nothing is fetched by itself.
  Computing the owner inside the endpoint means 0084 B's `OwnPages`, which reads every followed source's post
  addresses on each call. That breaks the 100 ms budget.
- **A reason line that only repeats the row's title** (step 3 on an Earlier or Later row) is not shown a second time.
  The API still sends it, with `reason_kind: "title"`.
- **`post_refs` keeps every http(s) address of the text,** including the post's own address and media files. This is
  what the invariant asks for ("a row for every body_hrefs link"). No row shows them: Earlier never resolves a post to
  itself, and Outside reads `post_links`.
- **Uniqueness is on `(post_id, md5(target_address))`, with a hash index on `target_address`.** A long address cannot
  break a save on the btree row-size limit.
- **The Mark X panel "links to the same section": not done.** `MarkXPanel.tsx` is slice C's file. It is a one-line
  link to `#connected`.

## Measured on a scratch copy of `insight_server_1105`
`insight_server_1105_check_362557_a`: copied, migrated with 0076, backfilled once, then dropped.

| Step | Time | Result |
|---|---|---|
| Copy | 8 s | |
| Migration (0076 and the Reddit reset) | 3 s | |
| Backfill (`fill_missing`) | 83.5 s | 49,384 posts, 248,057 open rows |
| Signature pass | 3 s | 4,891 rows marked boilerplate |
| **Total** | **86.5 s** | peak memory **78 MB** |

On the deploy, the story job's first run reads these refs before it groups anything.

**Not measured** (the owner: no long real-data runs; `scripts/realdata-check.sh` was not run):
- the 63% ±1 pt counts;
- the owner's case (3 Earlier, 2 Outside);
- the p95 over 200 posts. A script was ready, but it failed on its import path and was not run again, so the backfill
  was timed only once.
- the Reddit posts' new links and the stories they change.

All of these are for the merge's real-data check and the owner's 30-post review.

## Tests
- **Backend:**
  - `tests/test_post_refs.py` (31 tests): the Reddit fix, each step of the reason rule and the Outside restriction,
    refs on insert and update (it commits: a `_test` database), the backfill resumable, the link reading writing
    refs, the signature pass, the invariant, Later by both address forms, a target stored after its linker,
    boilerplate never a row, the caps and `more`, the route and its 404.
  - `test_migrate_runner` now counts `post_refs` among the derived tables.
- **Frontend:**
  - `components/post/Connected.test.tsx`: the render, "+N more", the empty and failing cases, the phone fold and the
    wide screen;
  - `pages/PostDetailPage.connected.test.tsx`: the placement, and the post not waiting.
  - The design studio's site fixtures answer the new route.
- **Bundle (gzip), against main `edb99d1`:** feed route 175,502 to 175,526 bytes; post route 315,869 to 315,955. The
  Connected chunk is 1.56 kB.

## Files touched outside the slice's own
- `backend/insight_core/checks/invariants.py`: the invariant, next to `story.empty`.
- `backend/insight_core/tests/test_migrate_runner.py`: `post_refs` added to the derived tables.
- `frontend/src/design/fixtures/site.ts`: the new route's fixture (the studio's frames fail on any unmocked request).
- `frontend/src/services/api.ts`: one method line next to `getPostDetail`, and the types in one `// 0125` block at
  the end.
