# 0282 Page watching a catalogue site (a maker's library pages)

Found 2026-11-26 adding a maker's site that has no feed and no blog: one page per library, listed in its sitemap with
a lastmod (the newest, 2026-11-24), each page `og:type website` and undated in its markup.

## Wrong today (ingestion/kinds/page_watch.py)
- `post_from` / `read_page_post`: a page with no date of its own and no `og:type article` is no post. All 37 library
  pages were refused (the archive read 40 pages: 1 stored, 37 no_post, 1 unreadable). A new library page
  will be refused the same way.
- The one page kept was the site's Terms & License: "Last updated October 2026" dated it. A legal page's
  "last updated" is the date it was changed, not when it was published, and the page is no post.
- (fixed in v10.50) `infer_prefix` took `/cdn-cgi/` (one CDN email-protection link) as the home page's section.

## Direction
- A site whose sitemap lists pages of one shape (same depth, its own content, each with a lastmod) is a catalogue:
  a page new to the sitemap is a new thing, dated by its lastmod (precision 'seen' at worst), kept as backlog for
  the old ones.
- "Last updated" / legal pages (terms, privacy, license) are no post: by the page's nature, not a list of sites.

## Bar before merging
Before/after on all page-watched sources (31 on the 2026-11-19 copy): every post kept today is kept; list each
newly kept page, read every one, no non-post among them.
