# 0143 — The smart archiver: a feed's whole history, by platform fingerprint and a ladder of strategies, checked by coverage; what each source discovered

Status: **spec** (2026-11-09). Mark IX (ingestion, archives). Builds on 0015 / 0107 (archive jobs), 0108 (the
sitemap, stubs), 0130 B (the newsletter platform's archive API), 0130 C (back to a date), 0137 (feeds from robots and
sitemaps, learned shapes, why none was found), 0039 / page watching (listing pages). Starts after 0140 merges (it
shares ingestion files).

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; `ingestion/kinds/generic_rss.py` (`archive_pages`,
`_sitemap_posts`, `_sitemap_post`), `ingestion/kinds/page_watch.py` (`sitemap_entries`, listings, `article_post`),
`ingestion/kinds/substack.py`, `services/archive_jobs.py`, `ingestion/inspection.py`.

**The owner (2026-11-09):** "can't we fetch full archive from <a Bear Blog>? sometimes RSS does not give us ability to
fetch archive from the rss feeds, it only limits to 20 posts, that's why we require smart archiver which will fetch
posts smarter and will override rss limits. so we need to find a general way to make smart archiver." And: "add
ability to see individual discoveries from each source."

**Constraints:** fix the class, never a site (platform behaviour is a class; no site names in code); no fetches from
the development machine (hand-written fixtures in each platform's shape); polite (host gates, learned budgets,
delays, backoff, resumable checkpoints); keep everything; no real names in committed files (rows:
`plan/research/0143-notes.md`); unit tests + 3–5 real checks; realdata-check runs once at release (not by the agent).

## Why (measured on the server by GET, 2026-11-09)
- **~70 of 146 feed sources look capped at the feed:** stored ≈ what the feed holds (10, 15, 20, 25, 30), the oldest
  post recent. Classes: Bear Blog sites, newsletter-platform publications on their own domains, WordPress, Blogger,
  Ghost, static-site blogs (Hugo / Jekyll / others). A few are full-history feeds (false alarms).
- **Three Bear Blog sources say "archived" though their archive never ran** (`last_archived_at` empty): the
  inspection estimated 0 more pages and the status became archived. No reason is recorded.
- **Why:** the archiver knows two strategies (the feed; the sitemap, 0108). When the sitemap is missing, unread, or
  lists no more than the feed, the source is "archived". A publication of the newsletter platform on its own domain
  is a generic feed, so 0130 B's archive API is never tried. Nothing compares stored with the site's real count.

## What it does
### 1. A platform fingerprint (no request beyond what the archive reads anyway)
From the feed (its `generator`, its namespaces, its item address shapes) and the home page (`<meta name=generator>`,
known script and asset paths, `link rel` tags, response headers): `wordpress`, `blogger`, `ghost`, `newsletter`
(the platform of 0130 B, on any domain), `bearblog`, `hugo`, `jekyll`, `medium`, `writeas`, `micro.blog`, `tumblr`,
`unknown`. Stored per source (`settings.archive.platform`, with the evidence). Each is a **class** with its known
behaviour; adding one is a table row and a fixture.

### 2. A ladder of strategies, tried in order until one gives more than the feed
1. **The feed's own paging:** RFC 5005 (`rel="next"`, `prev-archive`), and per platform: WordPress `?paged=N`,
   Blogger `?start-index=&max-results=`, Ghost `/rss/N/`, Tumblr `/rss?page=` etc.
2. **The platform's archive API:** the newsletter platform's archive (0130 B's paging) on its own domain; WordPress
   REST (`/wp-json/wp/v2/posts?page=&per_page=`); Ghost's public pages; Blogger's JSON feed.
3. **The sitemap, read well:** robots.txt `Sitemap:` lines, sitemap indexes, `sitemap-posts.xml` /
   `post-sitemap.xml`, gzip; the posts' common path learned from the feed (0108), excluding tags, pages, listings.
4. **Listing pages:** the blog's index (`/blog/`, `/archive/`, `/posts/`, the feed's `<link>`), following `rel=next`
   or `/page/N/`, reading post links by the shape the feed's items have (page watching's listing reader).
5. **Last resort, opt-in per source:** the Web Archive's address index (CDX) for the posts' path, each page read from
   the live site (or the archived copy only when the live one is gone). Off by default.
Each strategy stops at 0130 C's date when one is set. A post found by a strategy is read like an archived post today
(`_sitemap_post` / `article_post`), so 0140's full-text rules apply.

### 3. Coverage, not "done"
- **An estimate of the site's total:** the API's total, the sitemap's post count, the listing's count, the feed's
  paging depth — the largest trustworthy one.
- **"archived"** only when stored ≥ 95% of the estimate (or no strategy finds more and every one was tried, with each
  one's outcome recorded); else **"partial"** with the reason per strategy (`no_sitemap`, `sitemap_no_posts`,
  `listing_unread`, `api_refused:<status>`, `blocked`, …). The Sources page shows "stored N of ~M".
- **The learned ladder:** per platform, which strategy worked (counts in `system_settings.archive_learned`); a new
  source of that platform tries it first. Never per site.

### 4. Re-run what was called archived
A one-off, resumable job on the deploy's first start: every feed source whose archive status is `archived` but
`last_archived_at` is empty, or whose stored count ≈ its feed's, is inspected again through the ladder and, where
more exists, queued as an archive (one host at a time, 0107's waits; Telegram and X untouched). Logged; its summary
says how many sources went from capped to full.

### 5. What each source discovered
On a source's page, **"Discovered through this source"**: the sites it linked that Discover lists (followed or not),
the pages and originals collected because of it (0123, 0138), the entities it named first (`first_seen`, 0137), the
sources you followed from a suggestion it fed. Read from what Discover and Mark X already store; one GET
(`/api/sources/{id}/discoveries`). Sorted by what you followed, then voices.

## Measure (3–5 real checks after deploy)
1. The Bear Blog sources: stored before (19 / 11 / 34) and after, against the site's count.
2. Five capped sources of five platforms: stored before / after, strategy that worked, coverage.
3. The re-run's summary: sources capped → full, partial with reasons; requests spent.

## Done when
- Tests (fixtures only): each fingerprint from feed and page shapes; each strategy on its platform's fixture (paging,
  API, sitemap index, listing with `rel=next`, Bear Blog's one-page listing); the ladder's order and stop at the
  date; coverage states and reasons; the learned order; the re-run's selection; the discoveries endpoint.
- Migration if needed; frontend builds; vitest passes; design docs claim the coverage line and the discoveries tab.
