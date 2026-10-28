# 0042 — The reader keeps tables, figures and captions

Status: **planned** for v9.4 (owner, 2026-10-28, from the Gwern study).

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
