# 0042 — The reader keeps tables, figures and captions

Status: **built, not deployed** (2026-10-28, branch `issue-0042-reader-keeps-structure`). Planned for v9.4 (owner, 2026-10-28, from the Gwern study).

## The case (measured 2026-10-28)
- `extract_article_html` turns every `<table>` into a column of loose paragraphs.
  - gwern.net/spaced-repetition's comparison table reads "Metric / Mnemosyne / Mnemododo / Anki / …".
  - The corpus has the same loss: `lilianweng.html` and `borretti.html` each have a table in the page and 0 in our output.
- `<figure>` wrappers are dropped (gwern 4 → 0, lilianweng 16 → 0, borretti 1 → 0). The images survive, but some captions are lost (gwern: 8 `figcaption` → 4).
- **Headings left with nothing under them** close the article. Every Gwern page ends with "Similar Links Bibliography": section headings whose content JavaScript fills in.
- Why nobody noticed: the fidelity corpus (0032) measures words, not structure.

## The general rule
The reader keeps an article's **structure**, not only its words:
- tables, with header cells and their rows and columns (no inline styles);
- figures, with their image and caption together;
- a heading only when something follows it before the next heading of the same or a higher level.

Write it as a general rule on HTML semantics. No site names in code ([[generalize-not-overfit]]).

## Decided
- **Backend:** in `parsing` (the shared reader), keep `table/thead/tbody/tr/th/td/caption` and `figure/figcaption`, sanitised like the rest (no `style`, no event attributes). Drop an empty heading.
  - Layout tables, where a page uses a table for its whole layout: if the reader would keep one, state the rule it uses (e.g. a table holding block content such as headings or other tables is unwrapped, a data table is kept), and test it.
- **Frontend:** the reader shows tables calmly. A wide table scrolls sideways inside the column, and the page never scrolls. Captions are set under their figure in the reader's style (`frontend/src/design/docs/`; a numbered decision only if a new rule is needed).
- **Corpus:** add **structure checks** to `backend/insight_core/tests/fixtures/pages/expectations.json` (and its test): tables kept with their cell count, figures with their captions, no trailing empty headings. Add a trimmed Gwern page, `spaced-repetition`, as a fixture: table, figures, footnotes, the trailing JS-filled headings.
- **Stored posts:** say whether posts already stored keep their flattened tables, and whether the existing one-off repair or full-text refetch path can re-read them. Don't run it; just describe how the owner would.

## Done when
- Backend tests cover the new structure checks and the whole page corpus. Every existing expectation still holds, or each change is explained.
- A before/after on the 48 out-of-corpus pages used for 0032 (or an equivalent set of real pages): count tables and figures kept, list any text that newly appears or disappears, and explain each case. Fetching public pages for this check is allowed; never touch the live DB or the preview.
- Frontend checks pass, with the bundle change stated.

## Built
- **One pass in the shared reader** (`parsing._Structure`, step 4 of the reader's header
  comment), run on the chosen article block before its blocks are read. `BLOCK_RE` reads a
  table, a figure and a caption whole, up to their own end tag (a cell or a caption holds `<p>`s).
  - **A data table is kept as a table:** `table/caption/thead/tbody/tfoot/tr/th/td`, with no
    attribute but a numeric `colspan`/`rowspan`; `colgroup`/`col` (widths) go. A cell's text with
    no `<p>` around it, lost before, is kept.
  - **The layout-table rule:** a table that lays out the page is unwrapped, its blocks read like
    any others: it holds a heading or another table, it is marked `role="presentation"` (or
    `none`), or it has a single cell. A data table inside a layout table is still kept. A table
    never closed is unwrapped.
  - **A figure** is one `<figure>` holding its own blocks (images, caption, a table or code); a
    figure inside a figure is one figure; a figure left with nothing it can keep (its only image
    a pixel or with no address) goes.
  - Inside a table or a figure no tag keeps a `style` or an `on…` attribute (the frontend
    sanitiser removes them anyway).
  - **The empty-heading rule:** a heading goes when no block with text or an image comes before
    the next heading of a **higher** level, or the end. Gwern's "Backlinks / Similar Links /
    Bibliography" end every page with nothing under them and go. Not "the same or a higher
    level", as the plan put it: on the 50 pages below that version also dropped three real
    titles, a page title over a same-level subtitle (gov.uk's "Income Tax rates and Personal
    Allowances" over its h1 "Current rates and allowances") and a section title over a
    same-level note title (the PostgreSQL docs' "8.1.4. Serial Types" over "Note"), and
    PEP 8's "References"; what it caught in exchange was mid-page placeholders (MDN's
    script-filled "Browser compatibility", Nature's "Reporting Summary", the Verge's "More in:").
    Losing a title is worse than keeping a placeholder.
- **Frontend:** `MarkdownRenderer`'s sanitiser keeps `figure`, `figcaption` and `caption`
  (GitHub's schema unwrapped them into loose text); a figure's caption sits under its image at
  0.875em in `text-2`, a table's caption under the table; cells keep `colspan`/`rowspan`; a wide
  table scrolls sideways in its hairline frame, the page never does (unchanged). The post page's
  `headings` state has a wide captioned table and a captioned figure. Docs: `pages/post.md`
  (body, worst cases, the state), `system/typography.md` (captions). No numbered decision: this
  is the reader showing what the page has, not a new rule.
- **Corpus:** `expectations.json` gains `tables` (each kept table's cell count) and `figures`
  ([kept, with a caption]), both checked on every page (none when absent), and every page is
  checked never to end on a heading (`heading_last`). New page `gwern_spaced_repetition`
  (gwern.net/spaced-repetition, trimmed like the others and cut to some sections and its first
  ten footnotes, 107 KB): the comparison table (54 cells), 4 figures with their 4 captions,
  footnotes, and the three script-filled closing sections. **25 pages, every earlier expectation
  still holds**; lilianweng now keeps its table (14 cells). borretti's one table and figure are
  outside the article (the post-metadata box, the header's card image), so 0 is right there.
- **The Gwern page whole** (370 KB): before 0 tables, 0 figures, 4 captions and 4 images loose,
  ending "Backlinks Similar Links Bibliography"; after 1 table (6 header cells, 48 cells), 4
  figures each with its caption, ending on the last footnote. The page has 4 `figcaption`s (8
  was its open and close tags): the old reader kept their text, apart from their images.

### Before/after on real pages
The 48 pages of 0032's check were not kept, so an equivalent set: 50 public article pages
outside the corpus, fetched once on 2026-10-28 with INSIGHT's User-Agent (read only, nothing
stored): Wikipedia (3), paulgraham.com (2), danluu.com (2), Simon Willison, Martin Fowler, the
Rust and Go blogs, PEP 8, MDN, SQLite, the PostgreSQL docs, Python's docs, kernel.org, gov.uk,
ACOUP, Schneier, Eugene Yan, Chip Huyen, Karpathy, colah, Distill, overreacted, Joel on
Software, Daring Fireball, Quanta, Nature, arXiv HTML, two Substacks, Stratechery, two more Gwern
pages, the Verge, Wired, Tom's Hardware, Phoronix, Hacker News, PyTorch, Anthropic engineering,
jvns, ciechanow.ski, fasterthanli.me, Smashing, CSS-Tricks, web.dev. Base cbc5931 against the
branch, the same pages.

| | before | after |
|---|---|---|
| tables kept | 1 (danluu, by accident inside a `<p>` block) | 108 (on 14 pages) |
| figures kept | 0 | 321 (on 20 pages) |
| captions kept | 199 | 199 (now inside their figures) |
| images kept | 351 | 351 |
| words kept | | +13,973 newly kept, 17 newly gone |

- **Newly kept, all table text no `<p>` held:** arXiv's 74 data tables (+9,940 words: Llama 2's
  results), Wikipedia's largest-cities table (1,121 cells, +1,780) and Rust's two infoboxes,
  Tom's Hardware's benchmark tables (+646), CSS-Tricks (+798), danluu's input-lag tables (+349),
  the PostgreSQL types table (+118), MDN, kernel.org's releases, gov.uk's tax bands, ciechanow.ski,
  fasterthanli's type table. Python's 13 tables were kept as loose paragraphs before; same words,
  now tables.
- **Not kept, rightly:** Wikipedia's navboxes and sidebars (already chrome: `navbox`, role
  navigation), its "citations needed" box (`role="presentation"`), the PostgreSQL docs' nav
  tables (chrome), gov.uk's two other tables (inside JSON-LD scripts), paulgraham.com's and
  Hacker News's layout tables (unwrapped; those pages have no `<p>` text, so the reader reads
  nothing of them, before or after).
- **Newly gone, 17 words, all headings with nothing under them:** Gwern's "Similar Links
  Bibliography" (two pages with no backlinks section), ACOUP's "Published by Bret
  Devereaux" (an author box title), colah's "Deep Learning, NLP, and Representations" (a more-posts
  title), Quanta's "Next article". In the corpus: Cloudflare's "Subscribe to receive
  notifications of new posts" and Hugging Face's "Datasets / Spaces mentioned in this article"
  (chrome titles whose lists were already dropped).
- **Figures kept with no image:** tables in a figure (arXiv, CSS-Tricks, MDN), code in a figure
  (overreacted's 62 `<figure><pre>`), a CodePen's fallback text (Smashing), a video's caption
  whose player goes (Quanta, Wikipedia): the same words as before, now held together.
- **Seen, not changed:** fasterthanli.me's code blocks are `<figure><code>` with no `<pre>`; the
  reader keeps no text outside a block, so they are lost before and after. arXiv's table 9 holds
  small tables for line breaks in its header cells, so it reads as a layout table: its own
  numbers are not kept (they were not before either), the small ones are.

### Stored posts
- Posts already stored keep the body they were read with: a table read before this is loose
  paragraphs, and figures loose images and captions. Page watch reads only new links, and a
  later feed fetch keeps a body read from the page.
- The existing repair does not reach them: `repair_full_text` re-reads teasers only, and skips
  every post with `metadata.full_content_fetched` even with `--retry`.
- Posts whose feed carried the full HTML (`content:encoded`) already have their tables and
  figures: the frontend change shows them properly once deployed (figures and captions were
  unwrapped into loose text before).
- How the owner would re-read the others: a one-off option to the repair (say `--reread-pages`)
  that takes the posts read from their page (`metadata.page_read` or `full_content_fetched`),
  reads each page again with `read_article_page`, politely as the repair does, and saves with
  `save_full_text`. Not built and not run: it would send a request per stored post.

### Checks
- Backend: 747 tests pass (`test-backend.sh issue0042`), 4 new reader tests in
  `test_full_text.py` (a data table without its styles, layout tables unwrapped, a figure with
  its caption, the empty-heading rule), the corpus test with the new checks.
- Frontend: typecheck, 582 tests (1 new), lint clean, build. The reader's initial JS is
  unchanged (468,143 bytes, 0.00%); the lazy `MarkdownRenderer` chunk grows by 599 bytes
  (339,304 to 339,903; gzip +0.14 kB).
- Scripts for the before/after (not in the repo): `~/.cache/insight-0042/bin/`.
