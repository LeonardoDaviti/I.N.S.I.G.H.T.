# 0058 — A page your sources linked before is not "new to you"

Status: **spec** (2026-10-31) for v9.8 (owner, 2026-10-31: "why this is posted yesterday, if it was published on Aug 18?").

## The case (the lab, the server's data)
- **"Claude accelerates protein design and analytical chemistry"** (`anthropic.com/research/…`) was published on 18 Aug. The page-watched source "anthropic.com/research" first saw it on 30 Oct.
- **0039's "new to you is new"** set `surfaced_at`, so it sits on top of the Main feed with "published Aug 18".
- **But you did get it in August:** six of your sources' posts linked that page from 19 Aug on (Just Links, turboproject and others). It's in a story from 19 Aug.
- **"New to you" was decided for pages you never saw** (Gwern's "Lean Software Scaling Laws"). A page your sources already linked is known news.

## Decided
- **A page a post links is known.** When a page-based source saves a page that would be surfaced as "new to you", it is not surfaced if a stored post from another source linked that page's address before (0050's post links, before the page was first seen). It keeps its published date and sits where that date puts it.
  - Updates (0039's changed pages) still surface as before; this is only about first sight.
- **One-off cleanup:** a migration clears `surfaced_at` on stored posts that meet the same condition and were surfaced as new to you, not as an update. On the server copy that's 1 post; record the count.
- **No new setting.**

## Done when
- **Backend tests:**
  - a never-linked old page still surfaces;
  - a linked one doesn't;
  - an update still surfaces;
  - a link from the same source doesn't count;
  - a link made after the page was seen doesn't count.
- **The migration's count** on a copy of the lab is recorded here.
- **Lab case** `protein-design-surfaced` passes.
