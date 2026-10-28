# 0048 — Remove the Gwern posts that aren't Gwern's writing

Status: **planned** for v9.5 (owner, 2026-10-28).

## The case
0043 stops the Gwern reader from storing topic directories (`/doc/**`, including `/doc/**/index` and `/abstract` pages) and newsletter issues (`/newsletter/...`). Posts stored before 0043 from those addresses stay.

## Decided
- **A migration (0036)** deletes posts of sources whose address is on gwern.net (www. ignored) whose URL path starts with `/doc/` or `/newsletter/`.
- **Never deleted:** posts saved to Later or kept, and pages saved by hand (0031). Read state and positions of deleted posts go with them, through whatever the existing delete path or foreign keys do. Check that no table is left with orphans.
- Use the existing deletion path or cascades; no new mechanism. Search vectors (0040) go with the row.
- It must be safe to run on a database with no Gwern source, and running it twice must do nothing.

## Done when
- Backend tests run the migration on a `_test` DB with: Gwern posts on each path, an essay that stays, a kept and a Later post on a `/doc/` path that stay, a non-Gwern site with a `/doc/` path that stays, and a second run that does nothing.
- A dry count on `insight_preview` (read only: a SELECT, not the migration) is recorded here.
