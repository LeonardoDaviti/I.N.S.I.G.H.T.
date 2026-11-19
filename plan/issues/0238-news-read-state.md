# 0238 — News read state: a row, new posts in a read row, an Unread view (0237 #1)

v10.26, slice A. Deterministic UI and read-state behaviour: ships on, no switch. No migration (0165 unused), no new
table: the per-post `read_at` in `post_reader_state` is the only state.

## What was wrong
- `m` and the row's read button marked only the lead post (`FeedItem` → `PUT /api/feed/read` with one id). The row's
  other posts (its lines) stayed unread, so they still counted in the Main feed's unread count.
- There was no "Mark all News read". Shift+A in News was refused ("does not work in News").
- A row whose lead was read showed as read, even when posts joined it later. The only sign was an unread dot in the
  folded list, which is closed by default.
- There was no Unread view: the toolbar hid Show for every ranked view.

## What changed
**Definitions** (one place each: `news_service.row_posts` / `unread_posts` on the server, `lib/story.rowPosts` /
`newsReadState` in the reader):
- A row's posts are its lead and its lines (`story.posts`), what the row shows.
- A row is **read** when every post is read.
- **"N new"** = the unread posts of a row that has at least one read post.

**Backend**
- `GET /api/news`: each row carries `news.unread` (its unread posts). The answer carries `rows` and `unread_rows` over
  the whole scope, not just the page. `unread=true` lists only rows with an unread post, in the same order, before
  paging (`news_service.read_state`).
- `PUT /api/feed/read {scope, news: true, mark}`: "Mark all News read". It marks every post of every row the scope lists
  (`NewsService.post_ids`, the same rows `news` reads), read only, and keeps Later and the reading position
  (`keep_later`). The ids it answers undo it exactly. It refuses `read: false`, a combination with ids or cursors, a bad
  scope, and a mark other than main/ix.

**Frontend**
- `useReaderMutations`: a read patch now reaches story lines in every cached feed (`patchLines`). Read changes find
  lines as well as rows (`findReadTargets`; `findFeedItems` is unchanged for the post page).
  - `setRowRead`: the row's posts that change, in one request (batched only past 500 ids), with Later kept.
  - `markIds`: the batched Undo; `markUnread` is now `markIds(ids, false)`.
  - `markAllNewsRead`.
- `FeedItem`: a News row is bold unless every post is read, and shows "N new" in its meta. The button's title says it
  marks every post.
- `FeedList` (`ranked.rows`):
  - `m` and the button mark the whole row, with an Undo toast that restores exactly the posts that changed.
  - Opening an unread lead reads the whole row, so only posts that join later show as new.
  - Opening a lead that was already read leaves its new lines unread.
  - Shift+A calls `ranked.markAll`.
- `NewsList`:
  - A line at the top: "N stories with unread posts · Mark all News read", or "Every story read".
  - The count is the server's `unread_rows`, moved by the reads made in the loaded rows since.
  - Mark all News read uses a confirm dialog and an Undo toast, like mark-through.
- `FeedToolbar` / `ReaderPage`: News has its own Show choice, All / Unread (`?news=unread`). It opens on All, so read
  rows stay in place.

**The unread count for News:** it is on the News view's own line, not in the nav rail. It is free there, because the
answer already counts every row. A count in the rail would mean a second News request every 60 s, so I left it out.

## Not done
- Hidden quote-only posts (a post that only quotes a post of its row is no line, 0072) are not marked with the row.
  They are not part of the row's read state.
- The read state plays no part in a row's place (still part → score → first_at).

## Tests
- `backend/insight_core/tests/test_news_read_0238.py` (9 tests):
  - the row and view rules;
  - the routes with fake services;
  - on the database, a row read and then joined by a new post (unread 3 → 0 → 1, the new post the one unread line).
- `test_news`, `test_feed_routes` and `test_markx_news_rank` still pass (116).
- `frontend/src/pages/ReaderPage.news.test.tsx` (5 new tests, 25 in all):
  - "N new" and the unread line;
  - `m` in one request, and an exact Undo;
  - opening reads the whole row;
  - Mark all News read with confirm and Undo;
  - Show Unread.
- Also run: `components/reader`, `useReaderMutations`, `ReaderPage*` and `PostDetailPage` (220 tests).

## Owed on real data (not run: no real data in this release)
1. **The time of `GET /api/news`** before and after, on the server's News (`scope=all`, main), with `unread=true` and
   without. Expect no change: the count is a pass over rows already built.
2. **Mark all News read on a copy:** the number of ids, the request's time, and the peak RSS of the API process. The ids
   must equal the posts of the rows `GET /api/news` lists.
3. **The owner's row** (private notes): after the row is read, a post joining it shows "1 new" and is listed by
   `unread=true`.
