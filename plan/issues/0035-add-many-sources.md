# 0035 — Add many sources at once: a paste box and OPML

Status: **ready-for-agent** (owner, 2026-10-28: "everything your pick").

## Owner
"What about multiple source adding? How can we manage that? … all the multiple sources and links I will add should use all the feed finding or other related features we have." Standing rule: every way of adding a source goes through the feed finder (0026) and offers page watching (0028).

## Decided
- **Add several**, in Add source: paste up to ~50 addresses, one per line (pages, feeds, YouTube channels, `@handles`). Each goes through the **feed finder**, 4 at a time; results arrive as a table: *feed found* (title, address; several → a small picker), *INSIGHT reads it directly*, *no feed → follow page* (with the page watch preview's count), *already in your sources*, *nothing readable*. Each row has a tick (unreadable and already-added rows unticked and disabled). Optional: one track for all. "Add N sources" adds the ticked ones; each gets its first fetch, as a single add does.
- **OPML import** fills the same table from a file (the export other readers make; nested outlines become track suggestions).
- **OPML export** of every source, with its settings that matter (`page_watch`, name, tracks) in INSIGHT attributes: also an off-site copy of the source list (issue 0029 item 11).
- **The GitHub Trending template** (and any template with a field) shows what is already added under it: "Added: All languages, Python".
