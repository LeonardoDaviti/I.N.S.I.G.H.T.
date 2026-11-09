# 0140 — Teasers read in full: why a page read kept the summary, a same-article test that works, pages that need scripts, the repair again

Status: **spec** (2026-11-09). Mark IX (ingestion). Builds on 0062 (retries), 0069 (page tries), 0108 (stubs, empty
reads), 0135 / 0137 (silent failures), `scripts/repair_full_text.py`.

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; `backend/insight_core/ingestion/full_text.py` whole;
`generic_rss._maybe_expand`, `_read`, `_read_again`; the repair script's docstring.

**The owner (2026-11-09):** "Why <a vLLM blog post> is not fully fetched? which posts are not fully fetched? can't we
fully fetch them?"

**Constraints:** no fetches from the development machine (fixtures from pages the server already stored, or
hand-written ones of the same shape); no real names in committed files (rows: `plan/research/0140-notes.md`); fix the
class, never a site; keep everything; a page read stays polite (the host gate, `PAGE_DELAY_S`, budgets);
`realdata-check.sh` passes; 3–5 real checks.

## Why (measured on the server by GET, 2026-11-09; newest 4,000 posts, back to 29 Oct)
- **~170 website posts are teasers** (body < `SHORT_BODY_CHARS`), full text on for every one of their sources.
- **~140 of them carry no trace of a page read:** `metadata` empty — no `full_content_fetched`, no `page_read`, no
  `page_tries`. Only one path does that: `_read` got `None` from `read_article` (the page held nothing longer, or
  `_same_article` said it isn't the same article) on a post **with** a body, or an `Exception` other than HttpError —
  and recorded nothing. The biggest: a Russian tech-site "all posts" feed (108 in 10 days: its feed carries the text
  before the read-more cut), a vLLM-style project blog (its feed's description is a written abstract, not the
  article's opening), a company blog and a news site (some posts read, some not).
- One source's feed has no body and every page read fails (23, `page_tries` 3): counted, given up.
- Paid newsletter teasers (need the session) and link-blog posts (short by design) are not this issue's.
- `_same_article`'s rule (the body's first 80 characters in the page's first quarter) and `SHORT_BODY_CHARS` are both
  marked "not measured" in the code.

## What it does
1. **Every read leaves a reason.** `metadata.page_read_outcome`: `full` | `nothing_longer` | `not_same_article` |
   `needs_script` | `error:<class>` | `http:<status>`, with the time; the post's source page (anatomy, "Full text")
   counts teasers by outcome. An `Exception` path is logged with the class, not `debug` only.
2. **A same-article test that works**, measured on fixtures of the classes above before adopting:
   - the page is the article when **any** holds: today's opening rule; the post's title (normalised) is the page's
     `<title>`/`og:title`/`h1`; the post's address (normalised) is the page's canonical; 60%+ of the teaser's word
     shingles (5-grams) appear anywhere in the page text;
   - a read-more cut marker in the feed body (a "read more" link to the post's own address, or the feed's cut
     anchor) marks the post a teaser **whatever its length**.
3. **Pages that need a script:** when the reader finds no article but the page holds an embedded data block (Next.js
   `__NEXT_DATA__`, JSON-LD `articleBody`, a framework's hydration JSON) with the article's text, read it from there.
   A headless read is **not** in this issue (0081 is on hold); such pages end `needs_script`.
4. **The repair again:** `repair_full_text.py` re-reads posts whose last outcome is `nothing_longer` /
   `not_same_article` / `needs_script` / none, once per rule version (`metadata.full_text_rule`), newest first, polite
   as today; run by the deploy's first start (resumable, logged), like 0130 E1.
5. **The reader:** a teaser shows "Summary only · <reason> · Open the page" under its text.

## Measure
1. On fixtures of each class: right / wrong (a page accepted that isn't the article) — wrong must be 0.
2. After deploy: the newest 4,000 posts' teaser count before (~170) and after, by outcome (private rows).
3. 3 real posts the owner names read in full on the server.

## Done when
- Tests: each outcome recorded; the new same-article rules each accept and reject on fixtures; the cut marker; the
  embedded-data reader (Next.js, JSON-LD); the repair's rule version and resume; the reader's line.
- `realdata-check.sh` passes; frontend builds; design docs claim the new line.
