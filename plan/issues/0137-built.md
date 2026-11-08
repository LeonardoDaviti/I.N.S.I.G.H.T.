# 0137 Built: new spheres, round 2

Built 2026-11-08 on its own branch, test-first. Migration **0088** (post_links.kind; published_precision 'seen').
Every request in the tests is a FakeHttp answer or a stub, every feed and page a fixture with invented hosts:
`tests/test_new_spheres_0137.py` (A1–A5, B1–B5, B7, B9, the repair), `test_series` (B6),
`test_reference_links_0137` (B8), `test_bluesky_0137` (B10), and `frontend/src/components/AddSourceModal.test.tsx`.

## Per item

| # | Failure | What changed |
|---|---|---|
| A1 | `"errors": 0` with 3 sources failing | `summarize_health`: a source in backoff is counted in `errors` too (and still in `backoff`); `sources_failing` is `errors`. Items stored as fewer posts than they are, not explained by duplicates (the same guid, or no guid and the same title), are a failure: `kinds.base.collapsed` ("the feed has 282 items but 1 would be stored (282 items share 1 address)"), carried as `FetchedPosts.failure`; the runner saves the posts, then records the fetch as an error with that reason (failure count, backoff, the doctor's `empty_fetch`). |
| A2 | Blocked journal pages | After 0135's paths: the feed addresses the site's robots.txt and sitemaps name (robots' `Sitemap:` lines, else `/sitemap.xml`; an index's children that say feed/rss first; 2 read), then `learned_feeds`: the shapes of your own sources' addresses at that publisher with this page's own path words put in place of each non-feed word (a stored `/<code>/current.rss` gives `/<other>/current.rss`, `?jc=<code>` gives `?jc=<other>`), proved by content. The route passes your sources' addresses at the publisher (`known`). A feeds page linked from a page that answers is B3's directory. No publisher's path is named. |
| A3 | A pasted t.me address answers none | `feed_finder.bridge_feed`: a pasted t.me channel is the configured bridge's `/rss/<channel>`, an x.com account your Nitter's `/<user>/rss`; probed; none with reason "no bridge" when none is set. |
| A4 | Telegram dates | **Measured, not widened.** On the 179 posts checked against t.me (the research's files): raw 23 wrong-day, 0135's cap **18**, interpolation for the capped posts 20, interpolation for every post 19–36 (it moves correct posts early: 2–14 posts more than a day early). The cap stays. A bridge post whose channel is also followed through MTProto takes MTProto's message date (`repair_0137 --telegram`, old date in `metadata.bridge_date`, `date_from: mtproto`). |
| A5 | A saved search the only offer | A stage whose feeds are all saved searches keeps them aside and the search goes on; when nothing else is found they are offered with `note: "only a saved search was found"`, said in the dialog. |
| B1 | A podcast of 282 items stored as 1 post | `parsing.item_identity`: link, else guid (an address as is; else on the feed's address as `?insight_item=<guid>`), else the enclosure's address, else title and date (`?insight_item=`); never the feed's own address, nor a link 3+ items with other identities share (the show's page). Two items with one link stay one post, as before. `full_text.page_is_article` never reads an audio/video file or an `insight_item` address as a page. **Repair:** `repair_0137 --collapsed` drops the validators of each feed holding a post at its own address, so its next fetch reads it in full; the post is marked `collapsed_repair_0137` (once). |
| B2 | Another scope, or stale | The page's own article links (outside its menus, 2+ segments deep, a 3+-word slug) and its newest date (`<time datetime>`, JSON-LD `datePublished`). A feed holding none of its 3+ articles is `other_scope`; one whose newest item is 30+ days older than the page's newest is `stale` (`Feed.flag`, `not_this_page` in the answer). When every feed is flagged, the answer has `watch`: the page itself with its preview; the dialog says "Found the site's feed, not this page's" and offers "Follow this page instead". |
| B3 | Nitter fixed; directories; Apple | `NITTER_HOSTS` like `TELEGRAM_RSS_HOSTS` (unset: nitter.local as before; set empty: none). A bridge kind's address is probed: one answering 4xx/5xx is never `direct` (none, with its reason). A link whose words or address say RSS/feeds that is a page is a feed directory: one is followed and its links proved by content (`/rss/press.html` is a feed). An Apple Podcasts page asks the public lookup for `feedUrl`. |
| B4 | A feed the fetcher can't parse | `parsing.feed_root`: a document a strict parser refuses is read again with bare `&` escaped and control characters gone. The finder parses each of the first 3 feeds it offers with `parse_feed_posts` (the proving read when it held the whole document, else one GET); a feed it refuses is never offered: `refused: "the feed can't be read: <the parser's message>"`. |
| B5 | "none" says nothing | `reason`: blocked (403), rate-limited (429), needs login (401), gone (404/410), server error (5xx), empty feed (a feed with no item), no bridge, none found. Shown in the dialog ("No feed found: the site refused INSIGHT (blocked)"). |
| B6 | Series shapes | "#N." ends a segment; the stem of "#N" is the segment next to the number (a guest's name aside); "Name N Title" runs of 3+ with rising numbers (≤20 apart, ≤120 days), never years, never on X. `series.VERSION` 2 (the backfill reruns). |
| B7 | Glued journal authors | `parsing.element_authors` / `author_names`: one author per name element; affiliation and identifier children dropped; an identifier URL (ror.org, orcid.org) or a glued affiliation ("LeeDepartment of …") cuts the line; glued names split only when every part has 2+ words ("Ian VanderWaal" stays). **Repair:** `repair_0137 --authors`, the old list in `metadata.authors_repair_0137`. A trailing affiliation letter ("…Szczyglowskia" with its "a") is not told from the name. |
| B8 | Reference lists stored as links | `post_links.kind='reference'` for links inside a references/bibliography section (a heading so named, or an element whose class/id says so); stored as boilerplate, so no story/News/Discover rule reads them; Connected lists them folded ("References · N"). Search-engine links (scholar.*, search pages) are dropped. The migration re-reads the links of the posts whose HTML has a references section or a scholar link (narrowed from the fork's wider regex: 2,198 → 242 posts on the copy). |
| B9 | Undated items | `date_precision: "seen"`: the saver dates an undated item when first seen (insert: now; a stored undated post re-fetched: its `fetched_at`), never moving a stored date; the page's own date replaces it when the page is read. The story job reads "seen" as undated, as before. |
| B10 | Bluesky | `kinds/bluesky.py` on the public API, `!no-unauthenticated` respected (KindUnavailable), title from the text's first line; behind `INSIGHT_BLUESKY` (default off: bsky addresses go generic_rss as before). |
| B11 | One newsletter twice; "Transcript \|" | Measured on the copy: 15 same-source pairs within 7 days with the same body (300+ chars) and two titles, in 3 sources; 0 with "Transcript". 0127's fold works inside a Mark X story of 2+ sources, so a same-source pair is never folded by it: **it misses by construction.** No new rule here (the spec: none unless it misses); for the owner. |

## The repair (`scripts/repair_0137.py`)
Run by the ingestion process at each start (a thread, logged) and by hand (`--dry-run`, `--collapsed`, `--authors`,
`--telegram`). No request. Each part marks what it did; a second run finds nothing.

## On the server copy (`insight_server_1105`, a scratch copy migrated to 0088, dropped)
- **B1's repair size:** 1 source, 1 post at its feed's own address: a single item linking the feed itself (not a
  podcast). Its next fetch stores that item once more at its guid's address (one duplicate, kept).
- **Glued authors:** 0 (the server's export predates 0135's RDF authors).
- **Telegram:** 0135 found 0 bridge posts out of message order; 4 channels are followed both ways, 0 MTProto posts
  stored, so 0 moved. Wrong-day before/after measured on the research's 179 t.me posts (A4).
- **A1:** 3 enabled sources in backoff, 0 in error at the export: the summary said `"errors": 0`; now 3.
- **B9:** 80 undated posts in 3 sources: dated by their `fetched_at` when next re-fetched.
- **Repair run twice:** `{collapsed 1, authors 0, telegram 0}`, then `{collapsed 0, …}`.

## Not verified until the server or the lab fetches
The podcast feed's 282 episodes (its guids), the think tank and research-column pages' article links (B2's thresholds), the
central bank's directory page, the Apple lookup's answer, the blocked publishers' robots/sitemaps and learned
shapes, Nitter's 410 on the lab, Bluesky's labels, and the central bank feed's error being a bare `&` (recoverable) rather
than something else.
