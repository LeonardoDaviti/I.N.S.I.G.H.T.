# 0053 — Reader gaps: pages built from tables, code in figures, and the gaps nobody has listed yet

Status: **built, not deployed** (2026-10-30; branch `issue-0053-reader-gaps`) for v9.6 (owner, 2026-10-30: "the reader's known gaps … and also discover newer gaps and fix them as well").

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

## Built
Built 2026-10-30 on `issue-0053-reader-gaps` (from 672056d), not deployed. Every rule is in the
shared reader (`ingestion/kinds/parsing.py`, steps 1-5 of its header comment) but the title
one (`page_watch.page_title`); none names a host; no dependency.

### The fixes and the class each covers
- **Loose text** (`_LooseText`, step 1). An element that breaks its own text with a double
  `<br>` has each run of loose text and inline tags made a `<p>`; an inline tag a run doesn't
  both open and close (a `<font>` around the whole page) is left out of it. An element with no
  double `<br>` (a byline, an address) is left alone. Covers pages with no `<p>`: paulgraham.com
  (a layout table's one cell), incompleteideas.net (straight in `<body>`); also Apple Newsroom's
  lease fine print, lost the same way until now.
- **A lone `<code>` is a code block** (step 1): outside any text block, over several lines or in
  a `<figure>`, it becomes `<pre><code>`. Inline code stays inline. fasterthanli.me's 77 code
  figures.
- **Chrome at the article's edges** (`_without_edge_chrome`, step 5), judged by links and length
  as Readability judges unnamed blocks, but only at the edges, where chrome sits. Each block is a
  link (80% of its text in links, or a short row of several links), a label (under 50 characters,
  no sentence end; a colon ends a sentence of four words or more), letterless ("0%", "+23"), an
  image, a short paragraph (200 characters) or text.
  - Before the first paragraph, labels, links within the site and letterless blocks go, and a
    list item holding only a picture (avatars); the cover and headings stay. A link to another
    site ends the opening (Simon Willison's link posts keep their subject).
  - **The title again** goes: the first heading that is the page's `<title>` or og:title (perhaps
    with " | Site"), quotes compared straight. The reader shows the title above the text.
  - After the last paragraph, a tail of links goes with the labels just before it and what lies
    between its links (card pictures, short excerpts). It must end on a link or a label, or on a
    card's excerpt after two or more link titles, so an article's own closing link stays
    (NVIDIA's "Watch … in replay"), and so do references with a linked title (Lil'Log) and a
    whole sentence linking to another site (vuzix). Letterless blocks at the very end go.
  - **Cards**: a text block inside a link (`<a><img><h2>Title</h2></a>`) is marked in `_Structure`
    and read as a link (Hugging Face's more-articles cards); the first card's picture goes with it.
  - Covers 0032's 9to5google, Cloudflare, Mistral, Hugging Face and GitHub gaps, and the new
    techcrunch, tomsguide, roadtovr, solosglasses, vuzix and nvidianews chrome.
- **Notes after the article** (`_notes_after`, step 3): an element after the article, outside it,
  whose id a note mark in it links to ("1", "[2]", "*") is read after it: blog.google's
  footnotes (0032's gap). A "25 comments" link is no note mark.
- **A chrome name around the article** (step 2): no chrome rule drops an element around a
  candidate article holding a fifth of the paragraph text. lesswrong.com lays its post out in
  "MultiToCLayout-tableOfContents" and its comments hold three quarters of the text, so the post
  read as nothing. "instapaper_body" (the read-later marker) joins the content classes.
- **A short post is still the post**: "long enough" (500 characters) is judged before the edges
  go, so a 414-character summary under a shop's product grid (solosglasses) reads as itself,
  neither as nothing nor as the grid.
- Smaller, same classes: "-nav" joins the chrome endings ("bottom-nav": fasterthanli's next
  article teaser); an image sized in its style ("max-width:24px": about.fb.com's share icons) is
  an icon; a table with no word in it (fabiensanglard's palette, its colours in styles that go)
  is no table.
- **Titles** (`page_watch.page_title`): an og:title that is the og:site_name (vuzix.com's blog:
  "Vuzix Corporation") is no title; one equal to the `<title>` loses its short suffix as a
  `<title>` does ("— LessWrong", " - Alex Gorin").

### The corpus, before and after
- Before (672056d): **194 of 203** expectations met on the 25 pages (0032's 113 of 123 was
  counted before 0042's structure checks). With the new pages: **367 of 420 on 54 pages**.
- After: **202 of 203** on the 25 pages, **404 of 420 on 54 pages**. **No expectation that
  passed before fails**; 37 that failed pass. 0032's gaps that pass now: blog.google's last,
  9to5google's, Cloudflare's and Mistral's chrome, Hugging Face's images and chrome, GitHub's
  last and chrome. Left: GitHub's cover (Left open).
- Per new page, checks met before → after: paulgraham 5/8 → 8/8, incompleteideas 5/7 → 7/7,
  fasterthanli 5/9 → 9/9, lesswrong 4/7 → 7/7, techcrunch 4/8 → 8/8, roadtovr 5/8 → 8/8,
  solosglasses 5/8 → 8/8, vuzix 6/8 → 8/8, fabiensanglard 6/7 → 7/7, aleksagordic 6/7 → 7/7,
  nvidianews 7/8 → 8/8, about.fb 7/8 → 8/8, tomsguide 4/8 → 5/8. Unchanged, with a listed gap:
  hn_item 4/5, seangoedecke 6/8, ir.vuzix 6/7, longform_pod 7/8, androidauthority 6/8, augmentix 6/8,
  uploadvr 6/7, pluralistic 5/7. Unchanged and met: dan_lu_notes, matklad, nnteacher.bearblog,
  simonwillison, displaydaily, skarredghost, kguttag, sivers.
- Unit tests: 11 in `test_full_text.ReaderGapsTests` (9 fail on 672056d; 2 guard what must not
  change: a byline with one `<br>`, a link post's opening) and 1 in `test_page_watch` (titles).
- The corpus grows to 4.4 MB (`test_the_corpus_stays_small`: under 5 MB). Five big pages were
  cut of whole repeated elements, each reading the same cut as whole (`_page_corpus`'s
  docstring): lesswrong (1.9 MB to 138 KB, its post kept under half the page's text so the rule
  is still tested), sivers, tomsguide, vuzix, uploadvr. incompleteideas.net is served over http
  only; the corpus test accepts an http address.

### The new pages (29) and why each
- Named by the spec: **paulgraham** (greatwork, the table layout), **fasterthanli** (code in
  figures), **hn_item** (a Show HN item page; its post is a link, so the page is its discussion).
- The worst sites of the symptom scan (teasers the repair would read, or reader-read posts with
  a symptom): **uploadvr** (169 teasers), **roadtovr** (70), **augmentix** (48),
  **androidauthority** (43), **about_fb** (35), **tomsguide** (31, link-dense), **techcrunch**
  (26), **skarredghost** (23, link-dense), **solosglasses** (20, a shop's blog), **ir_vuzix** (12,
  the title repeated), **displaydaily** (10), **nvidianews** (8), **vuzix** (a shop's blog),
  **kguttag**, **seangoedecke**, **simonwillison** (the most posts; link posts),
  **karpathy_bearblog**, **longform_pod** (a podcast page), **aleksagordic** (link-dense references).
- Sites the owner reads (`config/sources.json`) the corpus didn't have, chosen for their
  layouts: **incompleteideas** (no `<p>`), **lesswrong** (a big app-rendered page),
  **pluralistic** (WordPress, a long colophon), **dan_lu_notes** (data tables), **matklad** (a static
  site), **fabiensanglard** (hand-written HTML, a palette table), **sivers** (568 comments).

### Symptoms on the preview (read only, 2026-10-30)
7,198 RSS posts exported read-only from `insight_preview`: 315 read by the reader (full text,
page watch) and 6,883 whose body is the feed's. "Read differently": the posts on those sites
whose symptom the fixed reader no longer has on the site's corpus page; no stored post was read
again.

| symptom | read by the reader | feed bodies | where | read differently |
|---|---|---|---|---|
| a reading of 0 or few words (under 80) where the feed's was longer | 0 | 873 teasers never read from their page (below) | | 0 on the preview's sites; 3 sites of the owner's list read 0 words before (paulgraham, incompleteideas, lesswrong) and in full now |
| HTML codes or tags left in the text | 17 | 1,465 | reader: blogs.nvidia 11 and miessler 3 (`&nbsp;`, `&#39;` stored before 0008), anthropic 2 and aleksagordic 1 (a literal `<scratchpad>`, code: right); feed: reddit 858, github 253, simonwillison 115, roadtovr 70, uploadvr 66 | 0: the reader's text is decoded since 0008 (`repair_full_text --entities` fixes stored ones); feed bodies are not the reader's |
| chrome words in the first or last two blocks | 12 | 29 | reader: blogs.nvidia 12 ("Share This Article", read by an older reader); feed: oneusefulthing 20, kaitchup 8 (Substack's own feed bodies), tomsguide 1 | 1 (tomsguide, read from its page); the corpus nvidia page has met it since 0032 |
| the title repeated as the first line | 29 | 987 | reader: blogs.nvidia 10, apple 6, blog.google 5, ir.vuzix 3, miessler 3, anthropic 1, roadtovr 1; feed: github 682, t.me 168, simonwillison 118 (feeds whose first line is the title by design) | 9 (blog.google 5, ir.vuzix 3, roadtovr 1); apple's heading is a longer headline than its title and stays; nvidia's, miessler's and anthropic's pages no longer open with it |
| images with no source | 0 | 0 | | 0 |
| link-dense paragraphs (80% link, 40+ characters) | 29 | 172 | reader: blogs.nvidia 12 (the old share list), aleksagordic 5 and anthropic 5 (references, links in text: right), 9to5google 3, miessler 2, ir.vuzix 1, roadtovr 1; feed: simonwillison 77, reddit 36, tomsguide 19, skarredghost 10 | 4 (9to5google 3, roadtovr 1) |

### Which stored posts `repair_full_text` would help
- Not run. Its query and plan replicated on the export: it would read **873 teasers**, 868 pages
  on 22 sites and 5 Substack posts through the API: simonwillison 257, uploadvr 169, roadtovr
  70, augmentix 48, apple 45, androidauthority 43, about.fb 35, tomsguide 31, blog.google 31,
  techcrunch 26, 9to5google 25, skarredghost 23, solosglasses 20, ir.vuzix 12, displaydaily 10,
  gordicaleksa.medium 9, nvidianews 8, vuzix 2, 4 others. It skips 3,394 other short posts
  (arXiv, Reddit, Telegram, nitter, page watch, links to GitHub).
- **260 of them are on the 10 sites whose pages the fixed reader reads differently**: roadtovr
  70, about.fb 35, tomsguide 31, blog.google 31, techcrunch 26, 9to5google 25, ir.vuzix 12,
  nvidianews 8 and vuzix 2 (240) would be stored without the related lists, share icons, repeated
  title and labels the old reader kept; solosglasses' 20 keep their feed summary instead of
  getting the product grid (the page holds nothing longer). The others read the same with either
  reader; medium answers INSIGHT's User-Agent 403; most of Simon Willison's link posts are
  already their whole page.
- The 315 posts already read from their page keep what they were read with: the repair skips
  them (0042: a `--reread-pages` option would be needed; not built).

### Pages fetched
33 requests, one at a time, 3 s apart, INSIGHT's User-Agent and 30 s timeout: the 29 pages
above, paulgraham's a second time (its first copy failed to save), and three not kept:
righto.com (404), chiark.greenend.org.uk (connection reset), gordicaleksa.medium.com (403).
No ingestion run, no `repair_full_text`, no other fetching.

### Checks
- Backend suite: **893 tests pass** (`test-backend.sh i0053`, 12 new). No frontend change.

## Left open
Each listed in `expectations.json` with its reason, failing on purpose:
- **GitHub blog's cover**: in a `<header>` outside `<article>` and `<main>`; nothing ties it to
  the post but its place.
- **Hacker News item page**: a link post's page is its discussion, in a `comment-tree` table,
  chrome by name; reading discussions is the comments kind's (0017). An Ask HN's own text (loose
  text in a cell) is the class the loose-text rule reads, but no such page was in the sample.
- **A related preview with no link** (seangoedecke): another post's title and first paragraphs
  in a `<blockquote>` after the post, nothing marking them as chrome.
- **Prose-like chrome**: augmentix's newsletter box and author box (a plugin's own names,
  "m-a-box-bio"); tomsguide's "Follow Tom's Guide on Google News" promo (a linked picture, then
  a paragraph under half link); androidauthority's affiliate notice (a sentence before the
  title); longform_pod's player line ("Podcast: Play in new window | Download"), links and words
  together. A rule loose enough to take these takes real paragraphs too.
- **Images with no size or name**: ir.vuzix's company logo, pluralistic's Creative Commons
  badge, uploadvr's ten in-body bookmark cards (an icon and a thumbnail each),
  androidauthority's review box badges and "Google Discover" logos.
- **pluralistic's title**: no og:title, and its `<title>`'s site name (43 characters) is longer
  than the 40 a suffix may be.
- **Not in `expectations.json`, a cost of the tail rule**: an article's own closing list of links
  with no label and links only (x.ai's "LatchBio blog / Grok 4.6 model card / Frontier
  Artificial Intelligence Framework", introduced by "linked below") goes; its expectations still
  pass.
- **JavaScript-only pages**: none of the 29 needed JavaScript; lesswrong.com, which looks
  app-rendered, sends its post in the HTML. gordicaleksa.medium.com answered 403 to the reader's
  User-Agent (blocked, not JavaScript). When a JavaScript-only page turns up it stays a gap the
  reader can't fix (out of scope).
