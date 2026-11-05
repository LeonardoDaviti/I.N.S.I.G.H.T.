# 0102 — Archives for history: back to a date, and a feed's past through its site

Status: **spec, draft** (2026-11-04). Mark IX (9.x).

## Why
- **The owner** (2026-11-04): "should I run archivers on the most valuable feeds to add more posts for our Mark X shadow to be tested?"
- **The sources review that day:**
  - Mark X's entities, trends and connections across time need history. Experiment G found only 16 pairs older than a year.
  - Two things stand in the way.

1. **An archive has no horizon.** It runs until the source ends (0015).
   - A Telegram channel with 9,000+ older posts gives its whole history, or someone stops it by hand.
   - The useful first step for Mark X is "back to a date": about 2.4k Telegram posts back to 1 Nov 2025, against 64k for everything.
2. **A feed only gives its window.**
   - Several of the most valuable feeds are "archived" to their window: a blog with 93 story memberships lists 30 posts, and another with 38 lists 48.
   - Their sites list every article in a sitemap, which page watching already reads (0028, 0041, 0047).

## Part 1: archive back to a date
- **The archive plan takes an optional date.** The plan says "about N posts back to <date>, about M minutes", from the source's rate, or "size unknown" when the source doesn't say.
- **The archive stops** at the first page whose posts are all older than the date. Resuming keeps the date.
- **Kinds:** Telegram (bridge), X (Nitter's search jumps by date already, 0015), Substack, YouTube and page watching (by sitemap dates).

## Part 2: a feed source's past through its site
- **For a feed source,** the archive can find the site's article pages:
  - through its sitemap, then its listing pages (page watching's discovery);
  - under the prefix the feed's posts share;
  - saved as the same source's posts, with the same address normalisation and dedup (0049).
- **The plan shows** how many pages the sitemap lists under the prefix before anything is fetched.

## Both parts
- **Archived posts are unread, as today** (all-time unread is the owner's decision). The plan says "adds about N unread".
- **Nothing runs by itself:** an archive is started by you.

## Measure before building part 2
How many of the 30 most valuable feed sources have a sitemap listing their posts, under one prefix, with dates. That reads 30 sitemaps once, on your go.
