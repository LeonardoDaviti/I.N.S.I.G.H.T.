# 0032 — Reading fidelity: know when INSIGHT reads a page worse than the site shows it

Status: **built** 2026-10-28, steps 1 and 2; step 3 measured, not adopted (see below). Not yet deployed. (Owner, 2026-10-28: "would you prevent that ever happening in the future? how?")

## What happened
- The owner compared anthropic.com/news/2026-us-midterms with INSIGHT's copy: no images, and it opened with "Chapter 01: Connecting people to trusted sources".
- Causes, both in the shared article reader (`parsing.extract_article_html`, used by full text for RSS posts, page watch, saved pages and five site adapters):
  1. it kept only text blocks, so **every image inside an article was lost**;
  2. it didn't recognise a sticky table of contents as chrome.
- **Measured, not guessed:** 18 random page-read posts on the preview, re-read: 11 of 18 had been stored with 0 images while their pages had 7–30 (Apple Newsroom, the Google blog, 9to5google); 2 started with clutter (blog.google's share bar, 9to5google's topic list). NVIDIA looked wrong but wasn't: its other images are related-news cards. Fixed: 99f4b5d (images, table of contents), 251ba1a (component-part names).

## Why it wasn't caught
- The reader is heuristics (which block is the article, which class names are chrome) tested only on small hand-written fixtures. A fixture tests the rule its author thought of, never the site that breaks it.
- Nothing compares what INSIGHT kept with what the page shows, so a loss is silent until the owner happens to look.
- Each fix is tested on the case that triggered it; earlier fixes can regress (the review caught 1c07573 doing that).

## Prevention
1. **A corpus of real pages (S).** Save ~25 real article pages as test fixtures (trimmed only of scripts), covering the layouts seen so far: Anthropic, DeepMind, Meta AI, NVIDIA, Apple Newsroom, the Google blog, 9to5google, WordPress (Old New Thing), Substack, Ghost (Cloudflare), Hugo, Miessler's VitePress, borretti.me, Cohere, x.ai, Groq. For each, the expected title, first sentence, last sentence, image count, and words that must not appear (menus, share, "Chapter 01", "Related"). Every reader change runs against all of them, so a fix for one site can't silently break another. Refresh the corpus with a script (owner-run) when a site redesigns.
2. **A fidelity number on every page read (S).** When the reader keeps a page, record in the post's metadata how many images the page's main area had and how many were kept, and the kept text length. Ingestion logs and the source sheet show a source whose pages lose most of their images or start with very short blocks ("This source's pages lose images"), so the next loss is visible without anyone comparing by hand.
3. **Measure a proven extractor against the corpus (M, decision).** Mozilla Readability's algorithm (ports: readability-lxml) or trafilatura are years of real-site heuristics. With the corpus, compare INSIGHT's reader and one of them on the same pages (text kept, images, chrome left in). Adopt it only if it clearly wins; it is one dependency (0005 asks for a reason, and this would be one).

## Out of scope
- Re-reading every stored post. Posts read after the deploy get the fixed reader; the full-text repair (`repair_full_text --retry`) re-reads teasers only. A one-off "re-read page-read posts" option can follow if the owner wants old posts refreshed.

## Built

### Step 1: the corpus (c82ff9b)
- 24 real pages in `backend/insight_core/tests/fixtures/pages/` (2.2 MB), each fetched once on
  2026-10-28 with INSIGHT's User-Agent and trimmed of `<script>`, `<style>`, `<noscript>`,
  `<svg>` and base64 blobs (the reader drops them anyway; checked: same output before and
  after trimming). Anthropic news and research, DeepMind, Meta AI, NVIDIA, Apple Newsroom, the
  Google blog, 9to5google, the Old New Thing (WordPress), One Useful Thing (Substack),
  Cloudflare (Ghost-era blog), Lil'Log and jvns.ca (Hugo), Miessler (VitePress), borretti.me,
  Cohere, x.ai, Groq, Mistral, Ars Technica (news), a Guardian gallery, Hugging Face and
  FastAPI's docs (code), GitHub's blog.
- `expectations.json`: per page the source URL and fetch date, the title (`page_watch._title`),
  the first and last sentence (found within the first / last 400 characters, so a title,
  byline or date may come first), the image count (the article's own figures and inline
  images, its cover when it sits inside the article element, counted by hand on each page's
  outline; never cards, sidebars, avatars, logos), the chrome words that must not appear, and
  for code pages a snippet that must. `test_page_corpus` checks every page; a known gap (with
  its reason) must still fail, and the test says when one starts passing.
- `scripts/refresh_page_corpus.py` (owner-run): the stored pages' failures, or `--fetch` to read
  them again and report each expectation that changed, `--write` to keep the new copies.
- Reader fixes, test-first, each general and run on the whole corpus: **93 → 113 of 123
  expectations met**.
  - No chrome rule drops an element holding more than half of the page's paragraph text (the
    Old New Thing's posts sit in "entry-content **share**postcontent": the reader kept only the
    sidebar).
  - Candidates are read whole, nesting respected (a card nested in the post no longer ends
    it: the Google blog lost its end); with no candidate, the smallest element holding 80% of
    the paragraph text (ai.meta.com kept its menus and footer).
  - A tag whose attribute holds ">" is one tag (Hugging Face's Tailwind classes).
  - Code blocks (`<pre>`) and captions (`<figcaption>`) are kept (FastAPI's code, the
    Guardian gallery, which had no text at all).
  - An article's own `<header>` goes but keeps its images (Anthropic's and NVIDIA's covers).
  - Comments, ads, newsletter boxes, author boxes, badges, avatars, icons (64px or less),
    empty and dark-mode images, and `<audio>`/`<video>` fallback text go; a lazy image known
    only by its `srcset` is kept.
  - A title loses a " | Mistral AI" suffix when the site is "Mistral".

### Step 2: a fidelity number on every page read (e26f223)
- `parsing.read_article_page(html, base_url)` returns the article and
  `read_fidelity`: `{page_images, kept_images, text_chars, short_opening}`. `page_images` is
  estimated from the article block the reader chose (images with an address, no pixel, icon or
  avatar), so related cards it dropped as chrome never count (NVIDIA does not warn);
  `short_opening`: the first block after the title is under 25 characters.
- Stored in `metadata.page_read` by page watch (`post_from`, a three-line change) and full text
  (`read_article`, `with_full_text`, the repair script); a later feed fetch that keeps the body
  keeps it. No new table.
- Source health: `reading_notice` from the 8 newest page reads: "Pages from this source lose
  most of their images (5 of the last 8)" when at least 3 and half of them lost most (3 or
  more images, under half kept); "Pages from this source often open with a very short block,
  maybe a menu left in (6 of the last 8)" when at least 4 and three quarters did. A quiet line
  in the source sheet.
- Job events: a source's line adds "· 2 of 3 pages lost most of their images"; the ingestion
  log says the same.
- Limits of the estimate: it sees images the reader found but could not keep (no fetchable
  address) and image-handling regressions, not images a chrome rule dropped or an article
  block chosen wrongly; the corpus guards those.

### Known gaps (in `expectations.json`, each failing on purpose)
- Google blog: its footnotes sit outside `<article>`. (Its standfirst, in
  "uni-article-hero__**meta**-wrapper", was a gap here; main's f86cb4d replaced the bare "meta"
  component-part rule with `PART_ENDINGS`, so since the v9.3 merge it is kept and the corpus
  checks it.)
- 9to5google: the YouTube promo and the in-body "More on Google Nest:" list have no chrome name.
- Cloudflare: tags, social links and subscribe box in "post-extras" inside `<article>`.
- Mistral: category eyebrow, "Back to Blog", read time and a "0%" label in plain `<div>`s.
- Hugging Face: upvoters' avatars (no size, "rounded-full"); mentioned-datasets, more-articles
  and comments panels inside `<main>`.
- GitHub blog: "Related posts" cards and "Share:" in unnamed blocks inside `<main>`; the cover
  in a `<header>` outside any `<article>`.
- All are chrome in unnamed blocks: what Readability's link-density scoring handles (step 3).
- Old posts keep what they were read with (out of scope, as planned); a post read before this
  has no `page_read`, so health counts only new reads.

## Step 3 measurement
INSIGHT's reader (after step 1), trafilatura 2.3.1 (`extract(..., output_format="html",
include_images=True, include_tables=True)`) and readability-lxml 0.9 (`Document(...).summary()`),
in a scratch venv, on the 24 corpus pages, scored on the corpus's expectations except the title
(first, last, images, must_not, contains: 99 checks). Each cell: checks met · images kept ·
chrome words left · text length.

| page | images | INSIGHT | trafilatura 2.3.1 | readability-lxml |
|---|---|---|---|---|
| anthropic_midterms | 4 | 4/4 · 4 img · 0 chrome · 11588 ch | 2/4 · 3 img · 0 chrome · 10323 ch | 2/4 · 0 img · 0 chrome · 10331 ch |
| anthropic_research | 5 | 4/4 · 5 img · 0 chrome · 20459 ch | 2/4 · 4 img · 0 chrome · 18659 ch | 2/4 · 2 img · 0 chrome · 18668 ch |
| deepmind | 8 | 4/4 · 8 img · 0 chrome · 9892 ch | 3/4 · 0 img · 0 chrome · 7120 ch | 3/4 · 0 img · 0 chrome · 7244 ch |
| meta_ai | 3 | 4/4 · 3 img · 0 chrome · 2758 ch | 2/4 · 0 img · 1 chrome · 2767 ch | 4/4 · 3 img · 0 chrome · 2758 ch |
| nvidia | 6 | 4/4 · 6 img · 0 chrome · 7865 ch | 3/4 · 4 img · 0 chrome · 7861 ch | 3/4 · 5 img · 0 chrome · 7945 ch |
| apple_newsroom | 16 | 4/4 · 16 img · 0 chrome · 28453 ch | 2/4 · 16 img · 0 chrome · 21041 ch | 2/4 · 0 img · 0 chrome · 21959 ch |
| blog_google | 3 | 2/4 · 3 img · 0 chrome · 4766 ch | 2/4 · 3 img · 0 chrome · 3301 ch | 1/4 · 0 img · 0 chrome · 3244 ch |
| 9to5google | 1 | 3/4 · 1 img · 2 chrome · 1090 ch | 2/4 · 3 img · 1 chrome · 983 ch | 3/4 · 1 img · 2 chrome · 870 ch |
| oldnewthing | 0 | 4/4 · 0 img · 0 chrome · 1845 ch | 4/4 · 0 img · 0 chrome · 1844 ch | 4/4 · 0 img · 0 chrome · 1845 ch |
| substack | 5 | 4/4 · 5 img · 0 chrome · 11460 ch | 4/4 · 5 img · 0 chrome · 11231 ch | 3/4 · 0 img · 0 chrome · 11290 ch |
| cloudflare | 2 | 4/5 · 2 img · 3 chrome · 10491 ch | 5/5 · 2 img · 0 chrome · 10462 ch | 4/5 · 0 img · 0 chrome · 10396 ch |
| lilianweng | 16 | 4/4 · 16 img · 0 chrome · 29540 ch | 4/4 · 16 img · 0 chrome · 26656 ch | 4/4 · 16 img · 0 chrome · 34077 ch |
| miessler | 1 | 4/4 · 1 img · 0 chrome · 903 ch | 3/4 · 1 img · 0 chrome · 746 ch | 3/4 · 1 img · 0 chrome · 950 ch |
| borretti | 0 | 4/4 · 0 img · 0 chrome · 8728 ch | 4/4 · 0 img · 0 chrome · 8722 ch | 4/4 · 0 img · 0 chrome · 8688 ch |
| cohere | 0 | 4/4 · 0 img · 0 chrome · 6874 ch | 4/4 · 0 img · 0 chrome · 6870 ch | 4/4 · 0 img · 0 chrome · 6874 ch |
| xai | 0 | 4/4 · 0 img · 0 chrome · 7389 ch | 4/4 · 0 img · 0 chrome · 6120 ch | 4/4 · 0 img · 0 chrome · 7163 ch |
| groq | 1 | 4/4 · 1 img · 0 chrome · 4305 ch | 4/4 · 1 img · 0 chrome · 4375 ch | 4/4 · 1 img · 0 chrome · 4305 ch |
| mistral | 3 | 3/4 · 3 img · 3 chrome · 3623 ch | 3/4 · 1 img · 0 chrome · 6624 ch | 4/4 · 3 img · 0 chrome · 6513 ch |
| arstechnica | 2 | 4/4 · 2 img · 0 chrome · 7132 ch | 2/4 · 0 img · 0 chrome · 2004 ch | 3/4 · 1 img · 0 chrome · 7356 ch |
| guardian_gallery | 11 | 4/4 · 11 img · 0 chrome · 1240 ch | 2/4 · 11 img · 1 chrome · 453 ch | 2/4 · 0 img · 0 chrome · 233 ch |
| huggingface | 1 | 3/5 · 29 img · 3 chrome · 4179 ch | 2/5 · 2 img · 0 chrome · 3831 ch | 5/5 · 1 img · 0 chrome · 3796 ch |
| jvns | 0 | 4/4 · 0 img · 0 chrome · 9256 ch | 4/4 · 0 img · 0 chrome · 9303 ch | 4/4 · 0 img · 0 chrome · 8928 ch |
| ghblog | 1 | 1/4 · 3 img · 2 chrome · 10684 ch | 2/4 · 0 img · 0 chrome · 10040 ch | 3/4 · 0 img · 0 chrome · 10022 ch |
| fastapi_docs | 2 | 5/5 · 2 img · 0 chrome · 11684 ch | 5/5 · 2 img · 0 chrome · 11772 ch | 4/5 · 2 img · 0 chrome · 10873 ch |

Totals: **INSIGHT 89/99** checks met, image count right on 22 of 24 pages, 13 chrome words
left; **trafilatura 74/99**, 14 of 24, 3 chrome words; **readability-lxml 79/99**, 13 of 24,
2 chrome words.

Caveats: the expectations were written by inspecting the pages while building INSIGHT's fixes,
so INSIGHT is scored on the test it was fixed against; the corpus has no `<noscript>`, where some
sites keep a lazy image's real `<img>` the libraries could use (INSIGHT drops `<noscript>`
either way). Even so the shape is clear. What the libraries miss is mostly **images**:
trafilatura on 10 pages, readability on 11 (DeepMind 0 of 8 for both, Apple 0 of 16 for
readability, NVIDIA, Anthropic, Ars), which is the loss the owner noticed; then a last or
first sentence (both drop Anthropic's footnotes, Miessler's AI note, the Guardian's last
captions; trafilatura cuts Apple's and the Google blog's opening). What they do better is
**chrome in unnamed blocks**: 2-3 chrome words left against INSIGHT's 13, all on INSIGHT's
known-gap pages (Mistral, Hugging Face, GitHub, Cloudflare, 9to5google).

**Recommendation: don't adopt.** Neither wins clearly: either would trade INSIGHT's images and
complete text for less chrome, and bring a dependency (lxml; readability also needs
lxml_html_clean) that 0005 would need a reason for. As a fallback it is marginal: on the 4
pages where `short_opening` fires (Google blog, Mistral, Hugging Face, GitHub) readability meets
13 of 17 checks against INSIGHT's 9, so "readability when the opening is short" would score
93/99 on this corpus, but it would lose the Google blog's images and rests on a hint that is
also true of plain bylines. Revisit when the field says so: the source sheet's
`reading_notice` now names the sources whose pages open short. The one idea worth borrowing
first is readability's link-density scoring of unnamed blocks (link lists, card grids), the
known-gap list above, added to `parsing.py` and proven on the corpus.
