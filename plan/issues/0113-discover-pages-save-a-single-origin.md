# 0113 — Discover, a second tab: Pages. A story's origin you don't follow, saved as one post

Status: **built** (branch `issue-0113-0114-0123`, 2026-11-06), changed by its measure (below). Spec 2026-11-05, the owner.

**The owner (2026-11-05):** "so this post should be shown in the discover to be fetched yes? we can have second tab for the discover where we can fetch single posts, not whole sources."

**Constraints:**
- reuse the existing save path (`POST /api/saved`, issue 0031) and Discover's origins (0065); no new fetcher;
- download nothing from the development machine;
- no real names in committed files;
- fix the class, never a site;
- measure on the server's data before adopting;
- nothing merges unless `scripts/realdata-check.sh` passes.

**This changes an owner decision.** 0065 (31 Oct) said "nothing is fetched until you follow; no storing of origin pages", with Discover suggesting the *site*. That still holds for everything automatic. This tab adds one thing: **you** can save a single origin page with one tap, without following its site.

## Why
- **Most stories' origins are pages no source of yours publishes:** 326 of 358 stories with a page linked by 2+ of their posts (0065).
  - Discover suggests their sites. But many are one-off pages, and following their site would bring noise, or there's nothing to follow: an essay's own site, a report's page, a paper or a model card.
- **Without the page, a story has no original.**
  - Example (Mark X Shadow, 5 Nov): a story about an interpretability essay, with 6 sources.
  - Its members link the essay's own site, and one quotes the author's announcement.
  - The essay itself isn't in INSIGHT, so the story shows retellings but not the source.
  - 0120 (Stealth) wants to show "Original: <page>". With the page saved, the original is a real post: readable in the reader, read by Mark X, and the one the perspectives sheet is built from.

## What it is
**Discover gets two tabs:** **Sources**, what it is today, and **Pages**, new.

**A row in Pages is one page,** not a site. It's listed when all of these hold:
- one of your stories links it, as 0065's origins count it: a page linked by 2+ posts of one story, or by its first post. Reposts and quotes count as links, as in 0065;
- it isn't stored: no post has its address or the address it redirects to, normalised as `/api/saved` does;
- it's an article page: not an archive, a CDN, an app share link, a document host, or a site's front page (0109's not-sources rules);
- it isn't from a source you follow. If it is, the source's own row in Sources offers the archive (0015), as today.

**Each row shows:**
- the page's title: its read title or the links' text, never the site's name (0109 rule 8);
- its site, and the stories that link it, with their headlines and voices;
- when it was first linked.

**Actions:**
- **Save page:** `POST /api/saved` with the address.
  - The page becomes a post of the Saved source, unread and in Later, as today.
  - Its own date is kept (`published_at` since 0063; the save time is `surfaced_at`), so stories and Mark X order it by when it was published, not saved (0120). Measured 2026-11-06 (`plan/research/0113-measure.md`): a page dated at its save time dissolves its story (31 of 50); the citation rule is fixed first.
  - The story job then finds it by the members' links. It joins its story by the existing citation rule, and Mark X sees it as the original by links.
- **Follow site…:** the existing Discover follow path, through the feed finder and page watching (the owner's source-adding rule).
- **Hide:** the row stays hidden, kept as a decision.

**Ordering:**
1. stories' voices, so the biggest stories' missing originals come first;
2. how many members link the page;
3. recency.

## Measure before building (on the server's data, read by GET)
- How many pages qualify over 30 days, and how many per story.
- How many are articles (the save path's `readable`) against pages that can't be read: a sign-in wall or no article on the page.
- On a scratch copy, whether a saved origin joins its story through the existing rules. The rate, with exact rows: a saved page that doesn't join is a bug in the citation rule, not in this tab.

## Open, for the owner
1. **Automatic saving:** never (today's rule); or automatic for a page linked by 3+ voices in one story; or only for pages Mark X marks as a story's missing original. **Default: never.** Every save is your tap.
2. **Should Mark X's story page offer "Save the original" too** (0120's sheet), the same action as this tab?
3. **Hidden pages:** hide one page, or the whole site's pages?

## Changed by the measure (2026-11-06; private: `plan/research/0113-measure.md`, `0123-measure.md`)
1. **A row is a story's root, not every page its posts link:** Discover's origin lines (`suggest` and `unnamed`, stories of 2+ voices, the last 30 days), checked by address. Read literally, "a page linked by 2+ posts, or by its first post" listed 287–369 pages a month, mostly a stored article's references; the root is about 50, one a story.
2. **The citation rule is fixed first.** A page saved and dated at the save time pulled its story apart: 31 of 50 stories dissolved. Now (`story_rules.grouping`): a saved page's linkers keep that page's link join (2+ places within 72 hours of its first link) and the saved page joins them, whatever its own date or the save's; its other linkers still join it by its date (the citation rule, as before). **Re-measured: 49 of 50 join, each as its story's root, 0 dissolve** — dated as the save path now dates it, and also at the save time (the worst case: a page stating a date far from its links). The one that doesn't, its story intact: a repository page linked for months (its link window is its first links'). Every save gets the fix, not only this tab's. Measured and dropped on the way: the link join only (no citation by date) lost a saved page under its author's one-account thread (the lab's `post-page-also-shared` case); joining the first linker when there is no link join hung a page linked for months on a months-old thread (`saved-is-not-a-voice`).
3. **The date:** a page that states none is dated by the first post linking it (0122's rule, now for every save: 0122's open point 5), never the save time; it sorts at the save time (`surfaced_at`). So its 72 hours are its links', and a page saved now pulls in no post that linked it the day before (measured at the save time: 3 of 44 of 0123's stories did).
4. **Tweets** (12 of 50) get no Save: the save path reads x.com's app shell. Their words are in the posts quoting them; Collect originals (0123) keeps them from the quote.
5. **Videos and a hub's collections or spaces** are listed with no Save.
6. **`Origin.stored`** counts a post at the origin's address: a story whose origin you saved was counted as not stored.
7. **"Probably can't be read"** when the server's reads of its site were all untitled or its follow test blocked, or the address carries an access token (5 of 50).
8. Open question 1 (automatic saving) became 0123's switch, "Collect originals", default off.

## Built (branch `issue-0113-0114-0123`, 2026-11-06)
- `utils/story_rules.grouping`: the saved-page rule above; 0070 A6 (a platform post listing links joins the story its first link is the origin of) compares a saved origin as the page, as the tree names it (on 0123's measure 2 posts left their stories without it). Tests: 7 in `test_names_and_joins.py`, 1 in `test_x_connections.py` (a thread about a saved page).
- `services/saved_service.save`: a page that states no date is dated by its first link whoever owns it (`test_save_fetch_first.py` +1).
- `utils/discover_rules.pages` and `page_key_of`; `Origin.at_post` (from `_ORIGINS`) in `Origin.stored`.
- `services/stories_service._discover_all`: `pages` rows `{url (no token), title, site, hide_key, video, tweet, first_linked_at, voices, readable, stories}` in Discover's answer; a page's hide key is `page:<address>` (`POST /api/sources/suggested/hide`, up to 2,048 characters).
- Frontend: Discover's tabs **Sources** and **Pages** (`components/sources/DiscoverPages.tsx`): Save page (`api.savePage`, 0122's path: a followed source's page is fetched there first), Follow site… (Discover's follow), Hide.
- On the server's copy the built list is 50 rows: 3 with no article, 12 tweets, 5 "probably can't be read".
- Tests: `test_discover_pages.py` (4), `discoverPages.test.tsx` (5).
