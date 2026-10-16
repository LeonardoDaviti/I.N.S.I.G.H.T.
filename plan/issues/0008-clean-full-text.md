# 0008 — Full text that is clean: no site menus, no HTML codes

Status: **ready-for-agent** (owner observations on the server, 2026-10-16). Builds on the full-text work on local main (c3d09cc, e21bf81), which is not deployed yet.

## Problem Statement
- **I still have to leave INSIGHT to read posts.** On the server, NVIDIA's "European Cities Deploy…" (346 characters) and Daniel Miessler's "Custom Content for Everyone" (301 characters) are teasers. That part is fixed on local main but not deployed: on the local preview the same posts come in at 5,765 and 1,294 characters.
- **The page reader keeps the site's chrome.** On Miessler's page the stored text starts with "Daniel Miessler Main Navigation home blog telos ideas projects…" and ends with "Related Reading … © 1999 — 2026 Daniel Miessler. All rights reserved." The feed's own 909-character version was clean, but the page's longer text won.
- **HTML codes show as text.** `&#39;` and similar stay in the stored plain text (16 of 40 posts in two sources on the preview). Previews and the copied text show "That&#39;s".

## Solution
- Deploy the full-text work and run the one-off repair (already built; waits for the owner's go).
- The article reader drops navigation, header, footer, aside and "related" blocks before it picks the article, and list items count only inside the chosen article.
- Plain text is stored with HTML codes decoded ("That's").
- The page wins over the feed only when it is clearly the same article, longer: the feed body's opening must appear near the start of the page text. Otherwise the feed body is kept.

## User Stories
1. As the reader, I want every post's full text inside INSIGHT, so that I never leave to read.
2. As the reader, I want the article text without the site's menu, so that the post starts with its first sentence.
3. As the reader, I want no footer, copyright or "related reading" list at the end, so that the post ends where the author ended.
4. As the reader, I want apostrophes and quotes to look like characters, not codes, so that text reads normally.
5. As the reader, I want feed previews without codes either, so that the list looks clean.
6. As the reader, I want a clean feed body kept when the page only adds chrome, so that the better version wins.
7. As the reader, I want posts already stored with codes to be cleaned by the repair, so that old posts read right too.
8. As the owner, I want the repair to stay a one-off that I start, so that no outside site is hit without my go.
9. As the owner, I want the dry run to show how many posts would change, so that I can decide.

## Implementation Decisions
- **Article extraction** (the existing `extract_article_html`) removes `<nav>`, `<header>`, `<footer>`, `<aside>`, `<form>` and elements whose class or id says nav/menu/footer/related/share/subscribe before choosing a candidate. Block collection from the whole page (the current fallback) excludes `<li>` outside the candidate.
- **Entities.** The plain-text field is produced with entity decoding (the existing `strip_html` already has `entities="decode"`); the full-text module and the RSS parser use it for `content`. `content_html` is unchanged.
- **Same-article check.** `read_article` accepts the page only if its text contains the first ~80 characters of the current body (normalised whitespace, case-insensitive) within its first 25%, or the current body is under 200 characters. Else it returns None (the feed body stays).
- **Repair.** The existing `repair_full_text` also decodes entities in stored `content` for posts it reads. A separate pass for entity-only fixes is out of scope.
- No new modules, no new seams: the changes live in the parsing helpers and the full-text module.

## Testing Decisions
- Unit tests at the existing parsing/full-text seam with fixture HTML: a page with nav + footer + related list yields only the article paragraphs; a page whose text doesn't contain the feed opening is rejected; `content` decodes `&#39;` / `&amp;` / `&quot;`. Prior art: `test_full_text.py`, `test_source_kinds.py`.
- A fixture modelled on the Miessler page (nav `<li>` menu, article without `<article>` tag, footer) is the regression case.

## Out of Scope
- A readability library or headless browser.
- Sites that block us (they keep the summary).

## Further Notes
- Local preview evidence (2026-10-16): NVIDIA 5,765 chars from the page; Miessler 1,294 chars including menu and footer.
