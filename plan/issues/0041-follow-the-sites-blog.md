# 0041 — Paste a homepage, follow its blog

Status: **planned** for v9.4 (owner, 2026-10-28: "user needs to find blog by himself? can't it just add url and blog will be found by itself?").

## The case
On `stripe.com` the feed finder now reaches `stripe.com/blog/feed.rss` (d8cd5ec, with the blog-link stage). On a site whose blog has **no** feed, "Follow this page instead" follows the address you pasted, which is the homepage. Following Stripe's homepage would guess the prefix `/customers/`: 557 links, 0 articles. Following `/blog` finds 269 dated articles. The owner should never have to find the blog page by hand.

## The general rule
A site's homepage is a poor page to follow. The pages it calls its own **blog / news / newsroom / press** (the same `_blog_links` rule the feed finder uses: link text, or a `blog.`/`news.`/`newsroom.` host on the same site) are the pages to follow. Pick among them **by evidence, the page-watch preview's article count**, never by site name. Don't hardcode any site; check the rule on sites the owner didn't name ([[generalize-not-overfit]]).

## Decided
- **Backend:** `find_feeds` also reports the blog/news pages it looked at (for example `FeedFinding.pages`) and passes them through `POST /api/sources/find-feed`. No second crawl: the finder has already fetched them.
- **When no feed is found and the address is a site's root or homepage:**
  - preview the reported blog pages with the page watch (`page_watch.preview`, in parallel, within the existing time limits);
  - offer the one with the most dated articles, as "Follow stripe.com/blog: 269 articles";
  - the other candidates go behind "Other pages on this site".
- **When the address is already a section or article page** (`/blog`, `/news/x`), behaviour stays as it is: that page is followed.
- **Last resort:** when the site links no blog or news page, or none of them yields articles, the homepage can still be followed. The offer says plainly that a homepage mixes everything ("This is the site's homepage: it may pick up product pages, not articles").
- **Every way of adding a source uses it** ([[source-adding-rule]]):
  - the Add source dialog;
  - add many at once (0035);
  - the source doctor's look for a replacement (0036), which must still keep its same-section rule.
- The pasted address stays the source's **name or site**. The followed address is the blog page.

## Done when
- Backend tests cover: a homepage with a feedless blog link, where the blog is offered with its count; a choice between two candidates by article count; another site's blog, which is never followed; a homepage with no blog link, which gets the last-resort warning; and a section address, which is unchanged.
- Frontend tests cover the dialog's offer, the "Other pages" list, the warning, and the bulk-add row.
- It is checked live through the throwaway finder (`~/.cache/insight-checks/ff.py`, or an equivalent that never touches the live DB) on **10+ company or project homepages the owner didn't name**. The table goes into this issue: site, candidate pages, offered page, article count, and whether the result is right.
- `~/.cache/insight-checks/bigsites.py` shows no change on the 32 sites, other than intended improvements.
