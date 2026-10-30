# 0053 — Reader gaps: pages built from tables, code in figures, and the gaps nobody has listed yet

Status: **spec** (2026-10-30) for v9.6 (owner, 2026-10-30: "the reader's known gaps … and also discover newer gaps and fix them as well").

## The case
The reader (`backend/insight_core/ingestion/kinds/parsing.py`, used by full text, page watching and Save any page) has known gaps:
- **Pages laid out in tables read as 0 words.** paulgraham.com and Hacker News put their text in `<td>` with `<br>`, no `<p>`. The reader finds no article: `greatwork.html` is 79,767 characters and reads as nothing (0039's checks). 0042 left these out on purpose.
- **Code inside `<figure><code>` with no `<pre>` is lost** (fasterthanli.me), because the reader keeps no text outside a block (0042).
- **0032's known gaps,** each failing on purpose in the page corpus (`backend/insight_core/tests/fixtures/pages/`, `expectations.json`):
  - Google blog: its footnotes sit outside `<article>`;
  - 9to5google: a promo block and an in-body "More on …" list;
  - Cloudflare: tags, social links and a subscribe box inside `<article>`;
  - Mistral: an eyebrow, "Back to Blog", a read time and a "0%" label;
  - Hugging Face: avatars and side panels inside `<main>`;
  - GitHub blog: related-posts cards, "Share:", and a cover outside `<article>`.
  - All but the first are chrome in blocks with no telling name.
- **Gaps nobody has listed yet.** The owner reads ~100 sites, and the corpus has 26 pages.

## Decided
- **Fix classes, never sites** (`generalize-not-overfit`). No rule names a host:
  - a table-layout rule recognises a layout table by its shape (one main cell holding the text, `<br>` breaks, few cells with text);
  - a code rule reads `<code>` blocks that stand alone as code blocks;
  - chrome is judged by link density and short repeated labels, the way Readability scores blocks (0032's step 3 measured trafilatura and readability; borrow the idea, add no dependency).
- **Test-first on the corpus.** Each fix adds or flips an expectation. The run reports expectations met before and after (today: 113 of 123, from 0032). **No expectation that passes today may fail.** A fix that helps one page and breaks another isn't a fix.
- **Find new gaps from real data, read only:**
  - On `insight_preview`, look for symptoms in stored posts:
    - a full-text read of 0 or very few words where the feed's own summary was longer;
    - leftover HTML codes or tags in the text;
    - chrome words ("Subscribe", "Share", "Related", "Comments", "Sign up", "Cookie") in the first or last paragraph;
    - the title repeated as the first line;
    - images with no source;
    - very link-dense paragraphs.
  - Count each symptom per site. The worst sites and kinds become the candidate list.
- **New corpus pages:** fetch at most **40 public pages** for the corpus, one at a time, one per site, with the same User-Agent and timeouts the reader uses. Include:
  - paulgraham.com and fasterthanli.me;
  - Hacker News's item page;
  - the worst sites from the symptom scan;
  - a few sites the owner reads that the corpus doesn't have yet.
  - Store them trimmed as 0032 did, with expectations counted by hand.
  - No other fetching, and no ingestion runs.
- **No re-reading of stored posts** (owner, 2026-10-28). Fixes apply to posts read from now on. The existing `repair_full_text` stays the owner's one-off tool; say in the spec which stored posts it would help, and how many on the preview.
- **Out of scope:**
  - PDFs (0038) and arXiv (0037);
  - JavaScript-only pages: list them as gaps the reader can't fix.

## Done when
- The corpus run shows expectations met before and after, with the new pages included. paulgraham.com, the fasterthanli.me code and as many of 0032's known gaps as a general rule can fix now pass.
- Every remaining gap is listed in `expectations.json` with its reason, failing on purpose, so the test says when one starts passing.
- **A symptom table, recorded here:** each symptom, its count on the preview before, and how many posts on those sites the fixed reader would read differently (measured on the corpus pages, not by re-reading stored posts).
- Backend suite green; no frontend change expected.
