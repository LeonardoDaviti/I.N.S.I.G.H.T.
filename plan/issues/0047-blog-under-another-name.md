# 0047 — Find a site's blog when it isn't called "Blog"

Status: **built, not deployed** (2026-10-28), for v9.5 (owner, 2026-10-28).

## The case (from 0041's live check)
On 3 of the 26 homepages, the homepage names its blog with other words: linear.app ("Now"), reka.ai ("Reka Latest"), atlassian.com ("AI blogs & news"). They get the warned homepage. Adding those words to `BLOG_LINK_TEXTS` would be overfitting ([[generalize-not-overfit]]).

## The general rule
When the homepage names no blog or news page, **let the evidence choose**:
- take the homepage's own menu links (same site; header and navigation first, then the footer), shallow paths first, at most a small number, e.g. 8;
- preview each with the page watch, the same path 0041 uses for named blog links;
- offer the page with the most dated articles, if it has enough to count as an article list (e.g. at least 5).
- Named blog links (0041) still win when they exist. This is only the fallback before the warned homepage.

## Decided
- Same budget as 0041 (15 s for the previews), in parallel, with no second crawl of the homepage.
- It applies wherever 0041 applies: the Add source dialog, adding many sources at once, and the doctor for root sources.
- What the offer says is unchanged ("Follow linear.app/now: 64 articles").

## Done when
- Backend tests cover: an unnamed blog found by its article count, a product page with few dated links not offered, named links still winning, and the budget respected.
- A live check on 0041's 3 misses **and** on 10+ new homepages not named before (by the owner or in 0041), with the table recorded here. `~/.cache/insight-checks/` holds 0041's scripts (`offer41.py`, `table41.txt`); the 32 big sites must not change.

## Built
- **The finder reports the menu** (`feed_finder.py`): when stage 3 found no page named blog or
  news, `FeedFinding.menu` carries the home page's own menu links, unread: anchors inside
  `<header>`, `<nav>` (and the footer's after them, `MENU_TAGS`), on the same site, the
  shallowest first, never the home page itself or a link with a query (a sign-up form's
  `?plan=`), at most `MAX_MENU_LINKS` (12). No second crawl: the home page's one parse gives
  both the named links and the menu. Named pages found: no menu (they still win).
- **12, not 8:** live, intercom.com's menu leads with ten sign-up, demo and product pages; its
  blog is the eleventh one-segment link.
- **The choice** (`page_watch.offers(http, pages, menu)`): the named pages first, as in 0041;
  when none of them is offered, the menu links are previewed at once in what is left of the same
  `OFFER_BUDGET_S` (15 s, one deadline for both), and a menu page is offered only when it reads
  as an **article list** (`_article_list`): at least `MENU_POSTS` (3) of the posts its preview
  read are dated within `MENU_RECENT` (a year). A post with no date of its own is dated when it is
  read, so it is left out. The offers are ranked by the preview's article count (`found`), as
  in 0041. Nothing names a site; no word is added to `BLOG_LINK_TEXTS`.
- **Why those thresholds (live):** 5 posts would lose linear.app/now (3 dated posts among the 8
  read: its category pages come first). Any 3 posts would offer ideo.com/leaders (25 pages dated by
  a joining year, 1978-2025) and 37signals.com/policies (3 dated, 2 of them updated this year).
  "Newest first" would lose intercom.com/blog (a featured post first) and bcg.com/publications.
  Three posts from the last year kept every blog and dropped both.
- **One sitemap read per run:** the previews of one `offers` call (named and menu) share the
  site's robots.txt and sitemap reads (`SiteReads`, a per-run map of address -> the read in
  flight, passed into `preview`/`discover`; no global cache): twelve previews of one site read
  its sitemap once. A preview cut by the budget never cancels a read another one awaits; reads
  still running at the deadline are cancelled with the previews. Live re-check: linear.app
  (/now, 106) and intercom.com (/blog/, 1758) offer the same.
- **Everywhere 0041 applies:** `POST /api/sources/find-feed` passes `finding.menu` (the Add source
  dialog and add-many both use it, so no frontend change); the source doctor gathers the menu of
  each search with the pages, for a root source only (`page_watch.is_home`). What the offer
  says is unchanged ("Follow linear.app/now: 106 articles").
- Tests: `test_feed_finder.py` `BlogUnderAnotherNameTests` (an unnamed blog found by its article
  count; the one with the most articles first; a product page with few dated links not offered;
  a page of people with old dates not offered; a page of policies with few recent dates not
  offered; a named blog still wins over a menu link with more articles; the budget respected: a
  menu page that never answers is left out, the rest offered in time; the menu as reported:
  header first, shallowest first, at most 12, no other site, no home, no query, no body links;
  no menu when a page is named; the previews of one run read the site's robots.txt and sitemap
  once); `test_source_doctor.py` (a root source is offered a blog its home
  page names otherwise). Backend 795 tests OK. Frontend untouched.
- **Limits:** a blog link deeper than the twelve shallowest menu links is not reached
  (atlassian.com's `/blog/category/ai`, three deep after sixty product links; bain.com's menu
  leads with seventy office and language pages). A list whose articles carry no date of their own
  is not offered (reka.ai/news: each article page shows its related posts' dates too, so page
  watch dates none of them and could not follow it anyway). Customer stories are dated articles
  too: notion.com now offers `/customers` (13) with `/releases` (12) under "Other pages".

## Live check (2026-10-28)
The branch's code in a throwaway image (`insight-backend:m0005-issue0047`), the find-feed
route's logic run directly (`~/.cache/insight-checks/offer47.py`: 0041's `offer41.py` with the
menu passed; `menu47.py` and `nav47.py` for the menu links and their previews); nothing stored,
no preview container used. The host's network dropped several times; rows hit by it were run
again.

0041's three misses:

| Site | Menu links read | Offered | Articles | Right? |
|---|---|---|---|---|
| linear.app | 12 (/customers 49 links 0 posts, /docs 105/0, /now 106/3) | /now | 106 | **yes** |
| reka.ai | 10 (/news 56 links, 0 dated; /labs/notes 6/5) | /labs/notes | 6 | partly: its research notes; "Reka Latest" (/news) has no article page watch can date |
| atlassian.com | 12 (/software 572/1, /trust 9/1, ...) | home page + warning | - | miss: the blog link is three deep, after the twelve |

17 homepages named nowhere before (not by the owner, not in 0041):

| Site | Named / menu | Offered | Articles | Right? |
|---|---|---|---|---|
| intercom.com | menu 12 | /blog/ | 1758 | yes (the eleventh link) |
| bcg.com | menu 12 | /publications | 5312 | yes |
| skild.ai | menu 3 ("Blogs") | /blogs | 12 | yes |
| physicalintelligence.company | menu 2 (lands on pi.website) | pi.website/blog | 8 | yes |
| ideo.com | menu 12 (/leaders 25/5, joining years) | home page + warning | - | yes as last resort: the people page is not offered |
| 37signals.com | menu 12 (/policies 11/3, 2 this year) | home page + warning | - | yes as last resort: its writing is on other sites |
| basecamp.com | menu 12, none a list | home page + warning | - | yes as last resort |
| loom.com | menu 4, product pages | home page + warning | - | yes as last resort: no list in its menu |
| rapha.cc | menu 9 (journal pages undated) | home page + warning | - | yes as last resort |
| bain.com | menu 12 (offices, language homes) | home page + warning | - | **miss**: its insights are past the twelve |
| metalab.com | no menu read | home page + warning | - | yes: nothing readable |
| canva.com | no menu (built with JavaScript) | home page + warning | - | yes: nothing readable |
| hashicorp.com | - | (429) | - | yes: unreadable |
| hex.tech | named /blog/, /newsroom/ | /blog/ | 423 | yes, unchanged (named wins) |
| 1x.tech | named /press (no article) | home page + warning | - | yes, unchanged |
| discord.com, retool.com | (feed found) | the feed | - | yes, unchanged |

Of the 17: right 16 (4 unnamed blogs found; 4 unchanged, a named blog or a feed; 8 given the
warned home page with nothing wrong offered), missed 1 (bain.com).
Of 0041's 3 misses: 1 found, 1 partly, 1 still missed. No other site's page and no product,
people or policy page was offered.

0041's other homepages, re-run: cohere, airtable, ai21, asana, bosch, mistral, sqlite,
perplexity, deepseek unchanged (deepseek's menu has no list; its home page answers 0-16 links
from run to run on both images). notion.so changed: `/customers` (13) offered, `/releases` (12)
under "Other pages": partly (no blog in its readable menu).

Timing: finder 0.4-9.7 s; the menu previews within the one 15 s budget (linear.app 4 s,
intercom.com 11 s, bcg.com cut at 15 s with its offer in time).

`bigsites47.py` (0041's `bigsites41.py`, the menu passed when the code has it), 32 sites on the
branch and on main (`insight-backend:m0005-base47`, ff06a5b): no change. Rows that differed in
one run were the network dropping (ollama, databricks, bloomberg: matched on a re-run) and
www.deepseek.com/'s own flakiness (its home page preview reads 0-16 links on either image; on
the branch its menu offers nothing, so it is followed as before).
