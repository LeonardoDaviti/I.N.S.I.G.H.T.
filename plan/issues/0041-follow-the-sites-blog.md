# 0041 — Paste a homepage, follow its blog

Status: **built, not deployed** (2026-10-28), for v9.4 (owner, 2026-10-28: "user needs to find blog by himself? can't it just add url and blog will be found by itself?").

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

## Built
- **The finder reports the pages** (`feed_finder.py`): `FeedFinding.pages` are the blog or news
  pages stage 3 read, by their final address, on the same site (a link that lands on another
  site is dropped) and never the address itself; a "none" (and a search cut by the budget)
  carries them. No second crawl. Three general changes to stage 3:
  - an address that cannot be read (a feed gone) takes its **home page's** blog links, so a
    root source's dead feed still reaches the site's blog (the source doctor);
  - the links are taken **shallowest first** (`/blog` before `/blog/tag/research`, still at most two);
  - a link counts by its whole text **or its first piece of text**: a menu item "Blog →" over
    "Product updates, insights…" is a blog link.
- **The choice** (`page_watch.offers`): the reported pages are previewed with `page_watch.preview`
  at once, within `OFFER_BUDGET_S` (15 s; one not done by then, or failing, is left out). A page
  whose preview read no article is never offered; the rest are ranked by the preview's count of
  articles (`found`), the most first. Nothing names a site. `page_watch.is_home`: an address with
  no path is a site's home page.
- **`POST /api/sources/find-feed`** adds `homepage` (status none and a home page) and `pages`
  (those offers, each `{url, prefix, found, sitemap, items}`), only for a home page; a section or
  article address gets `homepage: false, pages: []`, so it is followed as before (BACKEND.md).
- **Add source dialog:** a home page with no feed shows "Follow stripe.com/blog: 269 articles";
  pressing it opens the page-watch panel already previewed ("Following stripe.com/blog", the five
  titles, the path), and adds the blog page with `settings.page_watch`, named by the pasted
  address ("stripe.com") unless a name is typed. The other candidates are under "Other pages on
  this site" (the one followed moves there when another is chosen). No page with articles: "This
  is the site's homepage: it may pick up product pages, not articles." over "Follow this page
  instead", and again in the panel.
- **Add several (0035):** a home page's row reads "No feed: follow stripe.com/blog (269 articles)"
  and adds the blog page, named by the pasted address; without an offer the home page is
  previewed as before and its row carries the same warning.
- **Source doctor (0036):** for a source whose section is the site's root (`/rss`, or the home
  page), the blog or news page with the most articles is suggested before the home page; any
  deeper source keeps its same-section rule (`/news/rss` gone is still followed as `/news/`).
  Page watching is only ever suggested, never switched to.
- Tests: `test_feed_finder.py` `FollowTheBlogTests` (the blog offered with its count, the choice
  by count whatever the order, a page with no article not offered, another site's blog never
  followed (linked, or landed on by a redirect), no blog link: the last resort, a section address
  unchanged, a feed unchanged, the reported pages, the menu-item label, the home page's links for
  an unreadable address); `test_source_doctor.py` (a root source gets the blog with the most
  articles; a section source keeps its section); `AddSourceModal.test.tsx` (the offer, "Other
  pages on this site", the warning, a section address); `AddSeveralSources.test.tsx` (the
  bulk-add row). Backend 755 tests OK; frontend 586 tests, typecheck, lint and build clean; the
  reader's initial JS unchanged at 468,143 bytes (the dialog is in the Sources chunk).
- **Limits:** a home page is an address with no path: a locale home (`/en-us/`) is a section and
  is followed as typed. A blog the home page names otherwise ("Now", "Reka Latest", "AI blogs &
  news") is not found; the warned home page is the last resort. A site's news on another domain
  is never followed. The count is the preview's candidates, not dated articles one by one.

## Live check (2026-10-28)
The branch's code in a throwaway image (`insight-backend:m0005-issue0041`), the find-feed
route's logic run directly (`~/.cache/insight-checks/offer41.py`); nothing stored, no preview
container used. 26 homepages the owner didn't name:

| Site | Candidate pages (finder) | Offered | Articles | Right? |
|---|---|---|---|---|
| anthropic.com | /news | /news | 280 | yes |
| x.ai | /news | /news | 90 | yes |
| cohere.com | /blog, /newsroom | /blog (newsroom: no article) | 430 | yes (before the shallowest-first rule: /blog/tag/research, then the home page) |
| runwayml.com | runway.com/news (redirect, same site) | runway.com/news | 103 | yes |
| scale.com | /blog | /blog | 70 | yes |
| groq.com | /blog | /blog | 15 | yes |
| glean.com | /blog, /press | /blog (press 129 under Other pages) | 345 | yes |
| ai21.com | /newsroom/, /blog/ | /blog/ (newsroom 3) | 142 | yes: chosen by count, not page order |
| airtable.com | /articles ("Blog"), /newsroom | /articles (newsroom 70) | 216 | yes |
| miro.com | /blog/ | /blog/ | 26 | yes |
| cartesia.ai | /blog | /blog | 32 | yes |
| harvey.ai | /blog, /newsroom | /blog | 546 | yes (before the menu-label rule: none, home page /platform/) |
| asana.com | /press | /press | 3 | yes: the only page it names; its other links are a resource center |
| bosch.com | /research/news/ | /research/news/ | 38 | partly: a real news section, but the group's press portal is on another domain (never followed) |
| mistral.ai, figma.com, supabase.com, mozilla.org, samsung.com | (feed found) | the feed | - | yes, unchanged |
| linear.app | none named | home page + warning (/customers/, 0 articles: cannot follow) | - | **miss**: its blog is "Now" (/now) |
| reka.ai | none named | home page + warning (/legal/) | - | **miss**: "Reka Latest" -> /news |
| atlassian.com | none named | home page + warning (/software/) | - | **miss**: "AI blogs & news" -> /blog/category/ai |
| deepseek.com | none named ("更多" -> /news/) | home page + warning (its prefix /news/; 0-3 articles read, the site is flaky) | - | yes as last resort |
| notion.so | none (built with JavaScript) | home page + warning (/product/, 0 articles) | - | yes: nothing readable |
| sqlite.org | /news.html (one page, no section) | home page + warning (0 articles) | - | yes: no blog |
| perplexity.ai | - | (403) | - | yes: unreadable |

Of 26: right 22 (13 feedless blogs offered, 5 feeds unchanged, 4 with no readable blog given
the warned home page), partly 1 (bosch.com), missed 3. Every miss is a blog the home page names
by another word; it gets the warned home page, never another site's or a wrong section.
Finder plus offers took 2-11 s.

`bigsites.py`'s 32 sites, by an equivalent run on the branch and on main (`bigsites41.py`;
the preview API was not used): no change. Only www.deepseek.com/ is a home page among them,
with no named blog link, so it is followed as before; the rows that differed in one parallel run
(about.fb.com/news, together.ai/blog, runwayml.com/news, scale.com/blog's count) were timeouts
under load and matched exactly on a sequential re-run of both images.
