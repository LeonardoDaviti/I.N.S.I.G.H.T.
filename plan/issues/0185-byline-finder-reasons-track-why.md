# 0185 — Byline, the finder's reasons tell the truth, why a post is not in a track (spec + built)

INSIGHT v10.17, slice S (three small class fixes). Branch `v1017-small` off v1016; not merged, not pushed. No migration.
Names below are invented. Every fix deepens the module that owns the decision; nothing new runs in insight-api.

## 1. Byline: who wrote a post, via whom

**The problem.** An X feed carries other accounts' posts: a repost or a quoted repost is stored at
`nitter.local/<author>/status/...` in another account's feed. The post page's `repost` field named the author, but the
entity page, the Mark X News lines, the timeline, back in the news, Later, research, the track page and Connected
showed the feed's name as if the feed's owner wrote it. Telegram forwards (0178 stores `metadata.forwarded_from`) were
named nowhere on a screen; a quote's account nowhere either. Two rules decided "a repost": `tasks.original_author`
(0168 E, Mark X's renders) and `repo_reader.repost_of` (the reader).

**Built.**
- **One module** `backend/insight_core/utils/byline.py`, a pure function over stored fields → `{author, via, quoting}`:
  `author` the original writer when the feed did not write it ("@acme"; a forward's channel title), `via` the feed's
  name, `quoting` the account whose tweet it quotes (`post_parts.quoted`; a self-quote credits nobody). It owns the
  rule `original_author` (moved from `markx/tasks.py`; `tasks` re-exports the same function), `own_account` (moved
  from `db/repo_reader.py`), the SQL fragments (`SOURCE_NAME`, `COLUMNS`), `of_row`, `who` (0168 E's render words)
  and `bylines(cur, ids)` (one query, for a view that has only ids).
- **Every view reads it** (backend):
  - `db/repo_reader.py` `_item` (the reader's rows: feed, folders, search, Later/Kept/History, Mark IX News via
    `repo_news`): `byline`; `_ITEM_COLUMNS` gains the forward's name and `pp.quoted` (appended: every caller's slice
    of its extra columns is unchanged); `attach_stories`' story lines: `byline`; `repost_of` asks Byline's
    `original_author` (its `by` list of other reposters stays its own).
  - `services/post_detail_service.py` (the post page): `byline`.
  - `markx/news.py` `_posts` (the Mark X pages' post lines: News rows and left-out posts, entity list / page / older
    posts / queue examples via `entity_views`, the timeline, Connections in the panel via `graph`, the entities
    overview's examples): `byline`, and every key tuple that copies a line carries it.
  - `markx/back.py` `_shown_posts` (back in the news, and Later through it), `markx/research.py` `_post_rows`,
    `markx/perspective_views.py` (the Mark X story page's posts), `db/repo_post_refs.py` (Connected's stored rows),
    `markx/tracks_api.py` (the track page's sections and Discover, decorated after `tracks.page`: the planner's module
    is not touched).
  - `markx/tasks.py` `Post.who` (what Haiku reads) is `byline.who`: the same words as before, so no input changes.
- **Frontend**: `src/lib/byline.ts`: `bylineText` ("@acme via Feed, quoting @other"), `bylineName` (a story line's
  name), `carried`, `carriedLine` ("↻ @fan, from @acme", "↻ from Acme News", "quoting @other"). Replaced:
  `FeedItem` (story line name and "↻ feed" tail; the row's meta line), `PostDetailPage` (story lines; the header's
  line, now also forwards and quotes), `Connected`, `MarkXNews` (2), `MarkXTimeline`, `MarkXEntities` (2),
  `MarkXEntityPage` (2), `MarkXOverview`, `MarkXPanel`, `MarkXBack`, `MarkXLater`, `MarkXBuilt`, `MarkXPerspectives`
  (the member line, and the sheet's original, also-primary, claims, opinions and related through the member's
  byline), `TrackTopic`, `ResearchPage`. Types: `Byline` on the reader item, story post, post detail, Mark X lines,
  track items, research rows, Connected rows.
- **Deleted**: `story.ts` `repostLine` and `storyPostName` (now `carriedLine`, `bylineName`), `tasks.original_author`'s
  body, `repo_reader._own_account`.
- **Left as is, on purpose**: the perspectives judge's input (`perspectives.Story.who`, "written by @x" from the
  address): a model input, changing it would re-ask every story; Mark X's source page's "original in <source>" and
  Discover's source suggestions name sources, not a post's writer; Discover's Pages tab lists pages, not posts.
- **Voices unchanged.** Display only. `tasks.Post.voice` still comes from `pairing.counted_voice` over
  `tasks.author_account`; Mark IX's story voices (`story_voices`, the story job) are untouched. Proved on a seeded
  world: a stranger's repost and a stranger's forward keep their feed's voice although their byline names the stranger.

## 2. The feed finder's reasons tell the truth

**The problem.** `_Search.through_bridge` answered "no bridge" whenever the bridge's feed failed to sniff (a timeout,
an empty feed) although a bridge was configured (an X account found on a second try).

**Built** (`ingestion/feed_finder.py`): `NO_BRIDGE` only when no bridge is configured. A configured bridge (X's Nitter,
the Telegram bridge: one path) is asked `BRIDGE_TRIES` (2) times when it gave nothing or a server error; a 4xx answer is
not asked again and keeps its own reason (gone, blocked, rate-limited); nothing readable twice is the new reason
`BRIDGE_SILENT` ("bridge did not answer"). Frontend: `AddSourceModal`'s reasons say "the bridge on this server did not
answer (asked twice); try again in a minute".

## 3. Why a post is not in a track

**The problem.** Tracks keep Haiku's verdict for every judged post (`mx_track_items`), but the page shows only its
top: the owner could not see why a given post is not there.

**Built.** `markx/track_why.py` (new, read only: no task, no call, no vector computed) and
`GET /api/markx/tracks/{id}/why?post=<id, INSIGHT link or address>`:
- judged: `in` / `joined` / `discover` (its place `position` of `of`, `shown` False below the Discover cut,
  `tracks.DISCOVER_ITEMS`) / `out`, with Haiku's `why`, `confidence`, `subtopic`, `found_by`, the description version
  (`current` False: an earlier description's verdict; `waiting_again`), the owner's label; places read through
  `tracks.placed` (the page's own rule, its cheap read);
- `waiting`: asked, unanswered;
- `not_asked` with its reason: `not_a_topic`, `labelled`, `outside_window` (an active source's post older than the
  reading window), `not_planned`, `not_embedded`, `no_profile` (the finders never ran), `history_pending` (before the
  description, the history cursor not past it), `below_bar` (a passive source's post the finders did not put up; the
  last plan's bar from `mx_tracks.stats`).
The track page has a "Why not here?" field (a post's link or address) and the line (`trackWords.whyLine`). The planner
code in `tracks.py` is not touched.

## Tests
- `test_byline_0185`: pure (own post, repost, quote, quoted repost, self-quote, Telegram forward, blank forward, a
  blog's author field; 0168's words; one rule re-exported; `repost_of` identical to its old formula over a grid);
  seeded world (X feed: own, followed author's repost, stranger's repost, quote; Telegram: followed forward, stranger
  forward): `bylines`, `news._posts`, the reader row and `tasks.load_posts` give one byline; **voices identical**:
  {feed, followed author, feed, feed, followed channel, channel}, equal to `pairing.counted_voice` asked directly.
- `test_finder_bridge_0185`: none configured → no bridge, no request; silent X bridge (timeout, empty feed, a page)
  asked twice → bridge did not answer; Telegram the same; the retry finds it; a 404 keeps "gone" without a retry; a
  502 is retried, then "server error".
- `test_track_why_0185`: a folder; in / out with Haiku's why and confidence, Discover's place, read only (no task,
  call, item or label written), the owner's ✗ over Haiku's in; below the Discover cut; waiting; every not-asked reason;
  a post by its address and by its INSIGHT link; 404.
- Frontend: `lib/byline.test.ts` (node), `tracks.test.tsx` (whyLine, the field), `AddSourceModal.test.tsx` (the new
  reason); fixtures of `FeedList.test.tsx`, `PostDetailPage.story.test.tsx`, `design/fixtures/storyTrees.ts` carry the
  byline the server sends.

**Results.** The touched backend modules through `scripts/test-backend.sh` (`test_byline_0185`, `test_track_why_0185`,
`test_finder_bridge_0185`, `test_x_connections`, `test_markx_handles`, `test_titles_everywhere`, `test_markx_tracks`,
`test_sources_0178`, `test_new_spheres_0137`): all OK. Frontend: vitest **947 passed** (91 files), `node --test`
**249 passed**, `tsc` clean, `npm run build` within the bundle gate (feed route +0.26%, post route +0.16%). The whole
backend suite did not finish here: the shared Postgres was saturated by other slices' suites (9-11 `DROP DATABASE`
waiting on checkpoints at once, load 20-26); see the slice report. The real-data check was not run (the release's one
run on main).
