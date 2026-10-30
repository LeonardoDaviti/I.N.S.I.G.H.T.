# 0060 — Follow a site where your sources' links point

Status: **built, not deployed** (2026-10-31; spec the same day) for v9.8 (owner, 2026-10-31: "a user who finds claude from the Discover page won't paste the blog… our discover should understand where the posts that were linked are stored and suggest by that which feed to use").

## The case (the lab, the server's data)
- **Following claude.com from Discover starts at the home page.** The finder offers `/resources/`, the section with the most articles: 274 articles, 146 guides and 117 webinars.
- **Claude's blog is `/resources/articles/`:** `claude.com/blog` redirects there. Pasting `claude.com/blog` gives the right section, 273 articles, but nobody following from Discover types that.
- **Discover already knows the answer:** 95% of the claude.com articles your sources linked are under `/blog/`.
- **Across the top 60 Discover sites:**
  - **27 have one clear section** holding 60%+ of the linked articles: ai.meta.com `/blog/` 90%, cloud.google.com `/blog/` 95%, alignmentforum.org `/posts/` 100%, forethought.org `/research/` 100%, tobyord.com `/writing/` 100%, astralcodexten.com `/p/` 90%.
  - **28 are newspapers** whose addresses go by date or desk (nytimes.com/2026/…, reuters.com/world/…).
  - **5 keep articles at the root.**

## Decided
1. **Start where the links point.** Follow… from Discover passes the suggestion's linked articles.
   - If 60%+ of them share a first path segment that isn't a date or a number (`2026`, `2025`), the finder starts at that section (`https://claude.com/blog`), not the home page.
   - The finder follows redirects (`/blog` → `/resources/articles/`), looks for a feed there first, and otherwise offers page watching of that section.
   - Otherwise it starts at the home page, as today.
2. **Rank every finding by coverage.** For each finding (a feed, a page-watch section, the home page's offers), count how many of the linked articles it holds:
   - for a feed, its item addresses after normalization;
   - for a section, the articles under its path, after following one sample article's redirect if the links point elsewhere (`/blog/x` → `/resources/articles/x`).
   - **Show all findings,** each with "holds N of the M articles your sources linked". The most coverage comes first, and the narrower section wins a tie (`/resources/articles/` over `/resources/`). The article count no longer decides.
3. **A typed-in address gets the same ranking** when your sources have linked that site; otherwise it behaves as today.
4. **No guessing by names** ("Blog", "News"), and no list of sites.
5. **Cost:** no more requests than the finder makes today, plus at most one redirect check per site.

## The comparison (part of this issue, recorded here)
- **Run on the top 60 site suggestions** in `insight_lab`'s Discover, read only. For each site, run today's Follow and the new one, through the real finder, against the real sites.
  - One request at a time per host, with the finder's own User-Agent and timeouts.
  - At most 2 runs per site. No ingestion; nothing is added as a source.
- **Record per site:**
  - what each returns: the feed address or page-watch path, with the preview's article count;
  - its coverage of the linked articles;
  - which one the new rule ranks first.
- **Must hold:**
  - claude.com comes out as `/resources/articles/` with coverage near 95%;
  - no site where today's choice had higher coverage gets worse;
  - sites that block programs (Reuters 401, Axios 403) are listed as such.
- **Summary:** how many sites improved, stayed the same, or got worse, and why.

## Done when
- **Backend tests:**
  - the section rule (60%, dates skipped);
  - redirect following;
  - coverage for a feed and for a section;
  - the narrower-wins tie;
  - a typed-in address;
  - a site with no links.
- **Frontend:** findings listed with their coverage, the best preselected. Tests and screens in light and dark.
- **The comparison table** is recorded here.
- **Checks:** suites green; bundle within budget.

## Built
- **Where the links point** (`ingestion/where_linked.py`, new; `POST /api/sources/find-feed` calls `where_linked.follow`):
  - The route reads the site's linked articles itself (`StoriesRepository.linked_articles`: the kept `post_links` on the address's host, `is_article`, the same set Discover counts; one query by `target_site`, 13 ms on the lab's 142k links). So Discover's Follow… and a typed-in address go the same way, and the dialog sends only the address.
  - `start_section`: for a home page, the first segment 60%+ of them share (`SECTION_SHARE`, at least 2), never a date or a number (`NUMBERISH`: `2026`, `10`, `2026-10-31`). The finder starts there and follows its redirect (`FeedFinding.landed`).
  - A section that cannot be read, lands on the home page or lands on another site is no section: the finder has already taken the home page's links, as before (`start` null). A section with nothing to follow (no feed, no page with an article) offers the pages the home page names. The finder read the home page beside the section (`FeedFinding.home_pages` / `home_menu`), so it is not asked again.
  - With feeds at the section, the home page's own feeds are read beside them (`feed_finder.page_feeds`, stage 1 only): scmp.com's tech feed holds 31 of 41, its feed of everything 37.
- **What each finding holds** (`holds`):
  - **A feed:** its items as read by the finder (`Feed.items`, from the same 64 KB that proves it; `compare=False`), plus the articles under the section its items share (`feed_place`). The section stops before a date or a number.
    - At a host's root, only addresses shaped like its items count (`_shape`): a feed of `/2026/10/x` holds `/2025/01/y`, not `/pricing/plans`.
    - Why not by items alone: a feed carries only its latest items, so it would rank below any section.
  - **A page:** the articles under its prefix, on the host its preview landed on.
  - **When a section moved:** if no finding holds a single article of the links' main section, one linked article is fetched (`where_moved`, 16 KB, the finder's timeout). Where it lands maps the old section onto the new one (`/blog/` → `/resources/articles/`). That is the one extra request.
- **The ranking:** the most held first, a tie to the narrower path, then the finder's or the preview's order. The article count no longer decides when your sources linked the site. With no links, everything is as before: no `holds`, offers by article count, `linked: 0`, `start: null`.
- **The answer** adds `linked` and `start`, and `holds` on every feed and page when `linked > 0` (BACKEND.md).
- **Add source dialog:**
  - When your sources linked the site, every page found is listed as a radio, "claude.com/resources/articles · 273 articles", with "Holds 21 of the 24 articles your sources linked" under it. The one holding the most is chosen and previewed already, with no "Other pages".
  - Feeds say the same: under each radio when there are several, and under "Found the feed…" when there is one.
  - Unlinked sites look as before.
  - The dialog stays in the Sources chunk. The reader's initial JS is unchanged at 479,685 bytes.
- **Not touched:** add many, the source doctor and search. Add many still reads `pages[0]` and `feeds`, now ranked when the site was linked.
- **Tests:**
  - Backend: `test_where_linked.py` (19). It covers:
    - the 60% rule, with dates and numbers skipped;
    - articles at the root, and a non-home address, which start nowhere;
    - redirect following, with one article asked where it moved (claude.com's case);
    - a feed in the section found first, and the home page's feeds beside the section's (scmp.com's case);
    - a section that cannot be read, one that gives nothing and offers the home page's pages without reading the home page again, and one that lands on the home page;
    - coverage for a feed (items, shared section, dated root, shapes) and for a section;
    - a moved section, and the narrower-wins tie;
    - a typed-in address ranking its feeds, and a site with no links;
    - RSS, Atom and guid item parsing.
  - Backend, elsewhere: `test_stories.py` (a site's linked articles: host, `www.`, article-like only) and `test_feed_finder.py` (route stub, the answer's new keys).
  - Frontend: `AddSourceModal.test.tsx` (4). It covers every page listed with what it holds, with the best chosen and previewed; feeds with what they hold; one feed; and an unlinked site as before.
  - Totals: backend 1025 tests OK; frontend 651 tests, typecheck, lint and build clean.
- **Screens** (fixture modeled on claude.com, Design Studio frame `sources/follow-where-linked`): `~/.cache/insight-checks/0060-shots/follow-where-linked.1400.{light,dark}.png`.

## The comparison (2026-10-31)
- **Sites:** the top 60 site suggestions (platform accounts left out) of `insight_lab`'s Discover. They were read through `StoriesService.discover` and `linked_articles` in a read-only session (`default_transaction_read_only=on`), and nothing was written.
- **Runs:** each site had today's Follow (the finder on the home page, then the home page's offers, else the home page's own preview) and the new one (`where_linked.follow`, else the address's preview). Both used the real finder against the real sites, in a throwaway container of the branch image. Scripts: `/tmp/i60/scripts/compare60.py`, `final_table.py`.
- **Request rules:**
  - one request at a time per host (a lock per host around every request);
  - the finder's own User-Agent (`INSIGHT Archive Fetcher/1.0`) and per-request timeout (5 s);
  - the overall budgets (finder 10 s, offers 15 s) raised alike for both runs, since one request at a time would otherwise cut them short.
- **Nothing stored.** No source added and no ingestion.
- **The network:**
  - The host's network dropped twice. 24 sites got no HTTP answer on either run (every request failed without a status) and were run again once. On cloud.google.com, link.springer.com and web.archive.org the new run got no answer, so only the new run was repeated. nature.com got no answer on either run and was run again.
  - Where a run was lost and no section applies (the finder takes the same path either way), the other run's findings stand in, ranked by the new rule. Each such row says so. nytimes.com refused the second run (403).
- **Code changes after the runs:**
  - The home page's feeds beside a section's were added after the runs. On the 11 rows that started at a section with feeds, those feeds are taken from today's run, which read them the same way (only scmp.com's first choice changes).
  - The section fallback no longer re-runs the finder on the home page. So claude.ai's and chatgpt.com's new request counts are those of the earlier code.
- **Holds:** counted the same way for both runs, with the section move the new run found (claude.com only).

| Site | Linked | Today's Follow (home page): first choice, holds | New: started at | New: first choice, holds | Requests today / new | Result |
|---|---|---|---|---|---|---|
| reuters.com | 356 | nothing | home | nothing | 12 / 12 | blocked (401) |
| claude.com | 24 | page watch `claude.com/resources` `/resources/` (546 articles): 21/24 (88%) | `claude.com/blog` | page watch `claude.com/resources/articles` `/resources/articles/` (273 articles): 21/24 (88%) | 59 / 26 | **improved** |
| axios.com | 106 | nothing | home | nothing | 12 / 12 | blocked (403) |
| epoch.ai | 115 | feed `epoch.ai/atom.xml`: 87/115 (76%) | home | feed `epoch.ai/atom.xml`: 87/115 (76%) | 2 / 2 | same |
| ai.meta.com | 38 | nothing | `ai.meta.com/blog` | page watch `ai.meta.com/blog/` `/blog/` (10 articles): 24/38 (63%) | 13 / 22 | **improved** |
| github.blog | 64 | feed `github.blog/feed/`: 2/64 (3%) | home | feed `github.blog/feed/`: 2/64 (3%) | 3 / 4 | same |
| transformer-circuits.pub | 38 | feed `transformer-circuits.pub/feed.xml`: 38/38 (100%) | home | feed `transformer-circuits.pub/feed.xml`: 38/38 (100%) | 2 / 2 | same |
| astralcodexten.com | 98 | feed `astralcodexten.com/feed`: 96/98 (98%) | home | feed `astralcodexten.com/feed`: 96/98 (98%) | 2 / 3 | same (`astralcodexten.com/p` 404: the home page's feeds, as today (final code reports no start)) |
| alignmentforum.org | 147 | feed `alignmentforum.org/feed.xml`: 147/147 (100%) | home | feed `alignmentforum.org/feed.xml`: 147/147 (100%) | 2 / 3 | same (`alignmentforum.org/posts` 404: the home page's feeds, as today (final code reports no start)) |
| pewresearch.org | 24 | nothing | home | nothing | 12 / 12 | blocked (403) |
| digital-strategy.ec.europa.eu | 8 | feed `digital-strategy.ec.europa.eu/rss.xml`: 7/8 (88%) | `digital-strategy.ec.europa.eu/en` | feed `digital-strategy.ec.europa.eu/rss.xml`: 7/8 (88%) | 17 / 18 | same |
| forethought.org | 33 | feed `forethought.org/feed`: 32/33 (97%) | `forethought.org/research` | feed `forethought.org/feed`: 32/33 (97%); also `pinecast.com/feed/forecast` 0 | 3 / 3 | same |
| tobyord.com | 6 | nothing | `tobyord.com/writing` | feed `tobyord.com/writing?format=rss`: 6/6 (100%) | 31 / 2 | **improved** |
| futureoflife.org | 17 | feed `futureoflife.org/feed`: 2/17 (12%) | home | feed `futureoflife.org/feed`: 2/17 (12%) | 3 / 4 | same |
| bloomberg.com | 333 | nothing | home | nothing | 12 / 13 | blocked (403) |
| techcrunch.com | 218 | feed `techcrunch.com/feed/`: 218/218 (100%) | home | feed `techcrunch.com/feed/`: 218/218 (100%) | 2 / 2 | same |
| nytimes.com | 500 | feed `rss.nytimes.com/services/xml/rss/nyt/HomePage.xml`: 476/500 (95%) | home | feed `rss.nytimes.com/services/xml/rss/nyt/HomePage.xml`: 476/500 (95%) | 2 / 26 | same (new run lost (the site answered the second run 403); no start section, so the same finder path: today's findings ranked) |
| web.archive.org | 158 | nothing | home | nothing | 12 / 12 | same: nothing either way |
| wired.com | 151 | feed `wired.com/feed/rss`: 140/151 (93%) | `wired.com/story` | feed `wired.com/feed/rss`: 140/151 (93%) | 3 / 3 | same |
| wsj.com | 338 | nothing | home | nothing | 12 / 12 | blocked (401) (new run lost (network down); no start section, so the same finder path: today's findings ranked) |
| theguardian.com | 179 | feed `theguardian.com/europe/rss`: 67/179 (37%) | home | feed `theguardian.com/europe/rss`: 67/179 (37%) | 2 / 3 | same |
| cnbc.com | 184 | home page watch `cnbc.com` `/2026/` (149 articles): 102/184 (55%) | home | home page watch `cnbc.com` `/2026/` (149 articles): 102/184 (55%) | 44 / 24 | same (new run lost (network down); no start section, so the same finder path: today's findings ranked) |
| nature.com | 305 | feed `nature.com/nature.rss`: 304/305 (100%) | home | feed `nature.com/nature.rss`: 304/305 (100%) | 2 / 3 | same |
| theverge.com | 182 | feed `theverge.com/rss/index.xml`: 51/182 (28%) | home | feed `theverge.com/rss/index.xml`: 51/182 (28%) | 26 / 2 | same (today's run lost to the network; no start section, so the same finder path as the new run) |
| businessinsider.com | 141 | feed `feeds.businessinsider.com/custom/all`: 140/141 (99%) | home | feed `feeds.businessinsider.com/custom/all`: 140/141 (99%) | 2 / 3 | same |
| claude.ai | 120 | nothing | home | nothing | 12 / 27 | blocked (403) |
| cloud.google.com | 49 | nothing | `cloud.google.com/blog` | page watch `cloud.google.com/blog/products/application-development` `/blog/products/application-development/` (3 articles): 1/49 (2%) | 48 / 76 | **improved** |
| ft.com | 148 | nothing | home | nothing | 12 / 13 | blocked (403) |
| arstechnica.com | 95 | feed `arstechnica.com/feed`: 75/95 (79%) | home | feed `arstechnica.com/feed`: 75/95 (79%) | 3 / 3 | same |
| forbes.com | 80 | nothing | home | nothing | 12 / 13 | blocked (403) |
| finance.yahoo.com | 87 | nothing | home | nothing | 36 / 12 | same: nothing either way (new run lost (network down); no start section, so the same finder path: today's findings ranked) |
| chatgpt.com | 69 | nothing | home | nothing | 17 / 35 | same: nothing either way |
| tomshardware.com | 58 | feed `tomshardware.com/feeds.xml`: 15/58 (26%) | home | feed `tomshardware.com/feeds.xml`: 15/58 (26%) | 2 / 3 | same |
| fortune.com | 80 | feed `fortune.com/feed`: 76/80 (95%) | home | feed `fortune.com/feed`: 76/80 (95%) | 3 / 4 | same |
| link.springer.com | 92 | nothing | home | nothing | 24 / 80 | same: nothing either way |
| theinformation.com | 172 | feed `theinformation.com/feed`: 147/172 (85%) | `theinformation.com/articles` | feed `theinformation.com/feed`: 147/172 (85%) | 3 / 4 | same |
| washingtonpost.com | 113 | nothing | home | nothing | 5 / 5 | same: nothing either way |
| politico.com | 66 | nothing | home | nothing | 12 / 13 | blocked (403) |
| aws.amazon.com | 28 | feed `aws.amazon.com/rss`: 4/28 (14%) | `aws.amazon.com/blogs` | feed `aws.amazon.com/rss`: 4/28 (14%) | 4 / 6 | same |
| whitehouse.gov | 42 | feed `whitehouse.gov/news/feed`: 4/42 (10%) | home | feed `whitehouse.gov/news/feed`: 4/42 (10%) | 4 / 5 | same |
| time.com | 40 | feed `time.com/feed`: 10/40 (25%) | home | feed `time.com/feed`: 10/40 (25%) | 3 / 3 | same |
| theregister.com | 39 | feed `theregister.com/feed`: 0/39 (0%) | home | feed `theregister.com/feed`: 0/39 (0%) | 3 / 4 | same |
| npr.org | 49 | nothing | home | nothing | 5 / 5 | same: nothing either way |
| 404media.co | 28 | feed `404media.co/rss/`: 28/28 (100%) | home | feed `404media.co/rss/`: 28/28 (100%) | 4 / 4 | same |
| support.claude.com | 23 | feed `support.claude.com/feed.xml`: 23/23 (100%) | `support.claude.com/en` | feed `support.claude.com/feed.xml`: 23/23 (100%) | 5 / 6 | same |
| apnews.com | 52 | nothing | home | nothing | 12 / 13 | blocked (403) |
| venturebeat.com | 45 | nothing | home | nothing | 12 / 12 | blocked (429) |
| stackoverflow.com | 20 | nothing | home | nothing | 12 / 13 | blocked (403) |
| openclaw.ai | 9 | feed `openclaw.ai/rss.xml`: 9/9 (100%) | `openclaw.ai/blog` | feed `openclaw.ai/rss.xml`: 9/9 (100%) | 2 / 2 | same |
| quantamagazine.org | 21 | feed `quantamagazine.org/feed`: 21/21 (100%) | home | feed `quantamagazine.org/feed/`: 21/21 (100%) | 3 / 2 | same |
| cnn.com | 44 | home page watch `cnn.com` `/2026/` (241 articles): 19/44 (43%) | home | home page watch `cnn.com` `/2026/` (241 articles): 19/44 (43%) | 26 / 26 | same |
| nbcnews.com | 35 | feed `nbcnews.com/feed`: 33/35 (94%) | home | feed `nbcnews.com/feed`: 33/35 (94%) | 4 / 4 | same |
| aisi.gov.uk | 25 | page watch `aisi.gov.uk/blog` `/blog/` (103 articles): 21/25 (84%) | `aisi.gov.uk/blog` | page watch `aisi.gov.uk/blog` `/blog/` (103 articles): 21/25 (84%) | 33 / 23 | same |
| newyorker.com | 45 | feed `newyorker.com/feed/rss`: 40/45 (89%) | `newyorker.com/magazine` | feed `newyorker.com/feed/rss`: 40/45 (89%) | 3 / 3 | same |
| scmp.com | 41 | feed `scmp.com/rss/feed`: 37/41 (90%) | `scmp.com/tech` | feed `scmp.com/rss/feed`: 37/41 (90%); also `scmp.com/rss/36/feed` 31 | 2 / 2 | same (the home page's own feeds beside the section's (final code; read in today's run)) |
| edition.cnn.com | 33 | home page watch `edition.cnn.com` `/2026/` (77 articles): 14/33 (42%) | home | home page watch `edition.cnn.com` `/2026/` (77 articles): 14/33 (42%) | 44 / 44 | same |
| spectrum.ieee.org | 25 | feed `spectrum.ieee.org/feeds/feed.rss`: 24/25 (96%) | home | feed `spectrum.ieee.org/feeds/feed.rss`: 24/25 (96%); also `spectrum.ieee.org/customfeeds/feed/all-topics/rss` 24 | 3 / 4 | same |
| aistudio.google.com | 22 | nothing | home | nothing | 15 / 15 | same: nothing either way |
| ourworldindata.org | 22 | feed `ourworldindata.org/atom.xml`: 7/22 (32%) | `ourworldindata.org/grapher` | feed `ourworldindata.org/atom.xml`: 7/22 (32%) | 2 / 3 | same |
| investopedia.com | 11 | feed `feeds-api.dotdashmeredith.com/v1/rss/google/f8466ec3-5044-46bc-94b7-2df65f770eff`: 8/11 (73%) | home | feed `feeds-api.dotdashmeredith.com/v1/rss/google/f8466ec3-5044-46bc-94b7-2df65f770eff`: 8/11 (73%) | 2 / 3 | same |

**Summary:**
- **Improved: 4.**
  - claude.com: `/resources/articles/` (273 articles) instead of `/resources/` (546), the same 21 of 24 links, in 26 requests instead of 59. The other 3 links are product and form pages; the lab has 24 links, not the server's 95% sample.
  - ai.meta.com: nothing before; `/blog/` now holds 24 of 38.
  - tobyord.com: nothing before; the `/writing` feed holds 6 of 6.
  - cloud.google.com: barely. Its blog builds its list with JavaScript, so the only page watch can read is a 3-article subsection holding 1 of 49. Before, nothing was offered.
- **Same: 37.** Mostly sites with a feed on the home page, where the finder takes the same path and the first feed already holds the most. On the 11 sites that started at a section, the section led to the same feed. The newspapers by date (nytimes.com, cnn.com, cnbc.com) start at the home page, as before.
- **Worse: 0.** scmp.com would have been worse without the home page's feeds beside the section's: its tech feed holds 31 of 41, its feed of everything 37, which stays first.
- **Blocked: 12.** reuters.com (401), axios.com (403), pewresearch.org (403), bloomberg.com (403), wsj.com (401), claude.ai (403), ft.com (403), forbes.com (403), politico.com (403), apnews.com (403), venturebeat.com (429), stackoverflow.com (403).
- **Nothing either way: 7.** web.archive.org, finance.yahoo.com, chatgpt.com, link.springer.com (its `/article` section is a 404), washingtonpost.com, npr.org, aistudio.google.com.
- **Requests:** on the 52 sites both runs reached cleanly, today used 480 and the new one 474. More than today plus one:
  - ai.meta.com (13 → 22: the section's preview, where today offered nothing);
  - claude.ai and chatgpt.com (the earlier fallback's second finder run, since removed);
  - aws.amazon.com (4 → 6).
  - With the home page's feeds read beside a section's, the 11 sites that start at a section with feeds take the home page and its feed links once more: 2-7 requests each.
- **Requests made for the comparison:** 2,066 in all, first runs and repeats, one at a time per host, each by the finder's own client.

## Left open
- **Cost:** reading the home page's feeds beside a section's costs the home page and its feed links once more (2-7 requests), past "today plus one". It is what keeps scmp.com from getting worse. A cheaper way would be the finder reading the home page's feed links beside the section's in stage 1.
- **A feed read only to its first item or two** (full-text feeds over 64 KB) is judged by those items' section. github.blog's feed holds 2 of 64 by that count, so feed coverage is a floor, not a measure.
- **A section whose list is built with JavaScript** (cloud.google.com/blog) yields whatever subsection page watch can read. Its holds say how little that is ("Holds 1 of the 49…"), and it is still chosen first.
- **Language segments** (`/en/` on support.claude.com and digital-strategy.ec.europa.eu) count as a section. Both led to the same feed as today, but a locale home is not a blog.
- **Not shown when the section has a feed or an offer:** the home page's own offers (`/resources/` beside `/resources/articles/` for claude.com). Showing them would cost their previews.
- The source doctor and add many are unchanged. Neither reads linked articles.
