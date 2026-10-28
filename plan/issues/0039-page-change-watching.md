# 0039 — Watching pages for changes (Gwern first)

Status: **planned** for v9.5 (owner, 2026-10-28: "super useful for Gwern").

## The case: Gwern
- Gwern rewrites essays constantly. A page is re-read only while it is on `/doc/newest/index`, and the save then overwrites its text silently, with no mark. Older essays are never re-checked. The reader stores each page's `dcterms.modified` (`adapters/gwern_adapter.py`).
- gwern.net sends **no ETag and no Last-Modified** (its `cache-control` even says `immutable`, 900 days), so conditional requests alone can't see its edits.
- gwern.net's sitemap: 22,308 addresses, 685 essay-like, **0 with `<lastmod>`** (2026-10-28). The server has 75 Gwern posts (the archive was never run there).

## Design (proposed)
- **A per-source switch**, "Watch for changes", in the source sheet; off by default.
- **How often:** a single page follows the source's cadence (usually daily); a whole site checks a **rotating slice** (e.g. 50 pages a day, about two weeks for Gwern's 685; recently changed pages more often).
- **Cheap checks:** conditional requests (ETag / If-Modified-Since, 304 = no body); the page's own modified date when it has one (Gwern); then a hash of the **article text only** (the shared reader), so ads and timestamps don't count; ignore tiny changes.
- **What the owner sees:** the post comes back as "Updated 3 Nov: +2 sections, 1,400 words", with the new text; an "Updates" list per source. No full version history (post versions are skipped): the latest text plus a short summary of what changed.
- **Read only the head first** (from the Gwern study, 2026-10-28): `get_start` reads the first few KB of a page, which is enough for a modified date (`dcterms.modified`, `article:modified_time`, JSON-LD `dateModified`). Download the full page only when that date moved. Then use the article-text hash for pages without a date. This is the general path for sites that send no ETag.
- **New to you is new:** a page first seen today, but first published long ago (Gwern's "Lean Software Scaling Laws": published 2025-09, updated 2026-06, on today's newest list), must not land in the past where the Main feed never shows it. Decide the rule (e.g. order by when INSIGHT first saw it, showing the published date) for every page-based source, not just Gwern.
- **Show the page's own state** where the page states it: "Updated 23 Jun 2026", and for Gwern, the status and confidence (stored by 0043).
- Size: M. Resource cost: one conditional request per watched page per check; storage, one text hash per page.
