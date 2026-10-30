# 0060 — Follow a site where your sources' links point

Status: **spec** (2026-10-31) for v9.8 (owner, 2026-10-31: "a user who finds claude from the Discover page won't paste the blog… our discover should understand where the posts that were linked are stored and suggest by that which feed to use").

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
