# 0008 — Full text that is clean: no site menus, no HTML codes

Status: **ready-for-agent** (owner observations on the server, 2026-10-16). Builds on the full-text work on local main (c3d09cc, e21bf81), which is not deployed yet.

## Problem Statement
- **I still have to leave INSIGHT to read posts.** On the server, NVIDIA's "European Cities Deploy…" (346 characters) and Daniel Miessler's "Custom Content for Everyone" (301 characters) are teasers. That part is fixed on local main but not deployed: on the local preview the same posts come in at 5,765 and 1,294 characters.
- **The page reader keeps the site's chrome.** On Miessler's page the stored text starts with "Daniel Miessler Main Navigation home blog telos ideas projects…" and ends with "Related Reading … © 1999 — 2026 Daniel Miessler. All rights reserved." The feed's own 909-character version was clean, but the page's longer text won.
- **HTML codes show as text.** `&#39;` and similar stay in the stored plain text (16 of 40 posts in two sources on the preview). Previews and the copied text show "That&#39;s".

## Solution
- The article reader drops navigation, header, footer, aside and "related" blocks before it picks the article, and list items count only inside the chosen article.
- Plain text is stored with HTML codes decoded ("That's"), for every kind, in one place.
- The page wins over the feed only when it is clearly the same article, longer: the feed body's opening must appear near the start of the page text. Otherwise the feed body is kept.
- A no-network repair option decodes the codes in posts already stored.

**For the owner, after merge (not the implementer's job):** deploy, then run `repair_full_text --dry-run`, then `repair_full_text`, then `repair_full_text --entities`. Posts already read with menus on the local preview need `repair_full_text --retry` (a normal run skips posts already read from their page).

## User Stories
1. As the reader, I want every post's full text inside INSIGHT, so that I never leave to read.
2. As the reader, I want the article text without the site's menu, so that the post starts with its first sentence.
3. As the reader, I want no footer, copyright or "related reading" list at the end, so that the post ends where the author ended.
4. As the reader, I want apostrophes and quotes to look like characters, not codes, so that text reads normally.
5. As the reader, I want feed previews without codes either, so that the list looks clean.
6. As the reader, I want a clean feed body kept when the page only adds chrome, so that the better version wins.
7. As the reader, I want posts already stored with codes cleaned once, without INSIGHT re-reading any site, so that old posts read right too.
8. As the owner, I want the repair to stay a one-off that I start, so that no outside site is hit without my go.
9. As the owner, I want the dry run to show how many posts would change, so that I can decide.

## Implementation Decisions
- **Article extraction** (the existing `extract_article_html`) uses the stdlib `html.parser` with a depth count to drop `nav`, `header`, `footer`, `aside`, `form`, and any element whose class or id token starts with `nav`, `menu`, `footer`, `related`, `share`, `subscribe` or `sidebar`, before it chooses a candidate. Regex can't find where a nested element ends. No new dependency. The current whole-page fallback no longer collects `<li>` outside the candidate.
- **Entities, in one place.** At least ten places produce plain text with `strip_html` and no decoding (telegram_rss, substack, the adapters, the RSS parser). Decision: `strip_html` decodes by default. Remove the `"keep"` option if nothing still needs it. Decoding repeats until nothing changes, at most 2 passes, because some stored text is double-escaped (`&amp;#39;`). The implementer first confirms the raw stored form on the preview database, and the fixtures use it. The content hash already decodes before hashing (`normalize_text`), so this change doesn't make stored posts look changed.
- **Same-article check.** `read_article` accepts the page only if the first 80 characters of the current body are found in the first 25% of the page text, both decoded, whitespace collapsed and case-folded. A body shorter than 80 characters is matched whole. The check is skipped when the current body is under 200 characters. The existing length rule still applies on top.
- **`repair_full_text --entities`.** Decodes `content` in every stored post containing `&…;`, with no network; `--dry-run` counts them. This is the only new option.
- Docs: the `repair_full_text` docstring, `scripts/README.md`, and `DEPLOYMENT.md`'s repair section.
- No new modules and no new seams: the changes stay in the parsing helpers, the full-text module and the repair script.

## Testing Decisions
- Unit tests at the existing parsing and full-text seam with fixture HTML:
  - a page with a nav menu (`<li>`s), a footer and a related list yields only the article paragraphs;
  - a nested `<div class="menu">` inside the page is dropped whole;
  - a page whose text doesn't contain the feed's opening is rejected, and the feed body stays;
  - `strip_html` decodes `&#39;`, `&amp;`, `&quot;` and the double-escaped `&amp;#39;`.

  Prior art: `test_full_text.py`, `test_source_kinds.py`.
- A fixture modelled on the Miessler page (a nav menu, an article without an `<article>` tag, a footer) is the regression case.
- Repair: `--entities` on the test database decodes a stored `&#39;` and makes no HTTP request; `--entities --dry-run` writes nothing.

## Out of Scope
- A readability library or headless browser.
- Sites that block us (they keep the summary).

## Further Notes
- Local preview evidence (2026-10-16): NVIDIA 5,765 chars from the page; Miessler 1,294 chars including menu and footer.
