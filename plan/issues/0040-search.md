# 0040 — Search across every post

Status: **planned** for v9.4 (owner, 2026-10-28: "for 9.4 we move search into it").

## Why
On the server 41,000 of 41,128 posts are unread (0.3% read). Nobody scrolls that; you find things in it by asking. Search is the way into everything INSIGHT has already stored ("that Tailscale post on HN last month", "what did Simon write about MCP", "the Russian Telegram post about the outage").

## Decided
- **Where:**
  - a search field in the reader's toolbar, scoped to what is on screen: the Main feed, a track or a source;
  - ⌘K / Ctrl+K "Search posts…", which searches everything.
  - One results view in the reader. Opening a result opens the post as it opens anywhere else, so read state, Later and Keep work as usual.
- **What it matches:** the title, the full text and the source name. The title counts most.
  - Word forms count, in English and Russian ("watching" finds "watch", "серверы" finds "сервер").
  - "Quoted phrases" and `-word` work. Hits in another language are still found as plain words.
- **Results:**
  - Newest first by default, with "Best match" as the other order.
  - Each result shows the title, the source, the date and **the matching line** with the words marked.
  - Read or unread doesn't matter, because search covers everything.
- **Narrowing:** track, source, Later, Kept, and a date range ("last week / month / year / any"), as chips beside the field. The scope you searched from starts as the first chip.
- **Engine:** Postgres full-text search with a GIN index, in a migration. No new service and no new container.
  - Backfill the index for existing posts inside the migration, or in batches if that would lock the table for too long on 41k+ posts.
- **Speed, measured and recorded here:**
  - under 200 ms for a typical query on a database the size of the server's (fill a `_test` DB with ~50k posts);
  - also report the index size.
- **Empty states:** "No posts match 'xyz'" plus the active chips, with a one-click "Search everything" when a chip narrows the search.

## Not now
Saved searches (later, in a minor release), search inside one post, fuzzy or typo matching, and semantic or AI search (Mark X).

## Done when
- The backend route has tests: word forms in English and Russian, phrases, `-word`, each filter, ordering, the snippet, and paging.
- The frontend has tests for the toolbar field, ⌘K, the chips, the result row with the marked line, and the empty state.
- The design docs say where search lives. If it adds a rule, it gets a numbered decision in `frontend/src/design/docs/decisions.md`.
- Frontend checks pass (typecheck, test, lint and build, including the bundle budget). Any growth in the bundle is stated.
- The timing and index size are written into this issue.
