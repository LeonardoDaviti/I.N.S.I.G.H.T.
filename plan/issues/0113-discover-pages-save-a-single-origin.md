# 0113 — Discover, a second tab: Pages. A story's origin you don't follow, saved as one post

Status: **draft spec** (2026-11-05, the owner). Not built.

**The owner (2026-11-05):** "so this post should be shown in the discover to be fetched yes? we can have second tab for the discover where we can fetch single posts, not whole sources."

**Constraints:**
- reuse the existing save path (`POST /api/saved`, issue 0031) and Discover's origins (0065); no new fetcher;
- download nothing from the development machine;
- no real names in committed files;
- fix the class, never a site;
- measure on the server's data before adopting;
- nothing merges unless `scripts/realdata-check.sh` passes.

**This changes an owner decision.** 0065 (31 Oct) said "nothing is fetched until you follow; no storing of origin pages", with Discover suggesting the *site*. That still holds for everything automatic. This tab adds one thing: **you** can save a single origin page with one tap, without following its site.

## Why
- **Most stories' origins are pages no source of yours publishes:** 326 of 358 stories with a page linked by 2+ of their posts (0065).
  - Discover suggests their sites. But many are one-off pages, and following their site would bring noise, or there's nothing to follow: an essay's own site, a report's page, a paper or a model card.
- **Without the page, a story has no original.**
  - Example (Mark X Shadow, 5 Nov): a story about an interpretability essay, with 6 sources.
  - Its members link the essay's own site, and one quotes the author's announcement.
  - The essay itself isn't in INSIGHT, so the story shows retellings but not the source.
  - 0120 (Stealth) wants to show "Original: <page>". With the page saved, the original is a real post: readable in the reader, read by Mark X, and the one the perspectives sheet is built from.

## What it is
**Discover gets two tabs:** **Sources**, what it is today, and **Pages**, new.

**A row in Pages is one page,** not a site. It's listed when all of these hold:
- one of your stories links it, as 0065's origins count it: a page linked by 2+ posts of one story, or by its first post. Reposts and quotes count as links, as in 0065;
- it isn't stored: no post has its address or the address it redirects to, normalised as `/api/saved` does;
- it's an article page: not an archive, a CDN, an app share link, a document host, or a site's front page (0109's not-sources rules);
- it isn't from a source you follow. If it is, the source's own row in Sources offers the archive (0015), as today.

**Each row shows:**
- the page's title: its read title or the links' text, never the site's name (0109 rule 8);
- its site, and the stories that link it, with their headlines and voices;
- when it was first linked.

**Actions:**
- **Save page:** `POST /api/saved` with the address.
  - The page becomes a post of the Saved source, unread and in Later, as today.
  - Its own date is kept (`published_at` since 0063; the save time is `surfaced_at`), so stories and Mark X order it by when it was published, not saved (0120). Measured 2026-11-06 (`plan/research/0113-measure.md`): a page dated at its save time dissolves its story (31 of 50); the citation rule is fixed first.
  - The story job then finds it by the members' links. It joins its story by the existing citation rule, and Mark X sees it as the original by links.
- **Follow site…:** the existing Discover follow path, through the feed finder and page watching (the owner's source-adding rule).
- **Hide:** the row stays hidden, kept as a decision.

**Ordering:**
1. stories' voices, so the biggest stories' missing originals come first;
2. how many members link the page;
3. recency.

## Measure before building (on the server's data, read by GET)
- How many pages qualify over 30 days, and how many per story.
- How many are articles (the save path's `readable`) against pages that can't be read: a sign-in wall or no article on the page.
- On a scratch copy, whether a saved origin joins its story through the existing rules. The rate, with exact rows: a saved page that doesn't join is a bug in the citation rule, not in this tab.

## Open, for the owner
1. **Automatic saving:** never (today's rule); or automatic for a page linked by 3+ voices in one story; or only for pages Mark X marks as a story's missing original. **Default: never.** Every save is your tap.
2. **Should Mark X's story page offer "Save the original" too** (0120's sheet), the same action as this tab?
3. **Hidden pages:** hide one page, or the whole site's pages?
