# 0047 — Find a site's blog when it isn't called "Blog"

Status: **planned** for v9.5 (owner, 2026-10-28).

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
