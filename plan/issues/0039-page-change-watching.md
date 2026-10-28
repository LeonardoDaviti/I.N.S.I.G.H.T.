# 0039 — Watching pages for changes (Gwern first)

Status: **planned** for v9.5 (owner, 2026-10-28: "super useful for Gwern").

## The case: Gwern
- Gwern rewrites essays constantly; INSIGHT keeps the first text it read. The reader stores each page's `dcterms.modified` (`adapters/gwern_adapter.py`) but never re-checks it.
- gwern.net's sitemap: 22,308 addresses, 685 essay-like, **0 with `<lastmod>`** (2026-10-28). The server has 75 Gwern posts (the archive was never run there).

## Design (proposed)
- **A per-source switch**, "Watch for changes", in the source sheet; off by default.
- **How often:** a single page follows the source's cadence (usually daily); a whole site checks a **rotating slice** (e.g. 50 pages a day, about two weeks for Gwern's 685; recently changed pages more often).
- **Cheap checks:** conditional requests (ETag / If-Modified-Since, 304 = no body); the page's own modified date when it has one (Gwern); then a hash of the **article text only** (the shared reader), so ads and timestamps don't count; ignore tiny changes.
- **What the owner sees:** the post comes back as "Updated 3 Nov: +2 sections, 1,400 words", with the new text; an "Updates" list per source. No full version history (post versions are skipped): the latest text plus a short summary of what changed.
- Size: M. Resource cost: one conditional request per watched page per check; storage, one text hash per page.
