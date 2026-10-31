# 0063 — Saved pages keep their own date, and link labels stay out of the text

Status: **spec** (2026-10-31) for v9.9 (owner, 2026-10-31: "spec all the issues we found while discussion").

## 1. A saved page is dated by the page, not by the day you saved it
- **The case (the lab):**
  - All 8 Saved pages (0031) are dated the day they were saved.
  - Your sources link them a lot. Of the 1,248 citations between stored posts, 252 have the linked post published *after* the post linking it, which is impossible. Saved pages make most of them: 46 from danielhanchen, 26 from LessWrong, 17 from Smol.
  - Those dates also mislead the story tree (0064) and Classics' spread.
- **Decided:**
  - **Saving a page:** it takes the page's own published date when the page states one, using the same reading the page-watch reader and 0039 already do (meta tags, JSON-LD, `<time>`). Otherwise it takes the save time, as now.
  - **Stored Saved pages:** a one-off repair re-reads their dates from their stored HTML. Nothing is fetched.
  - The date the page *was saved* stays where it is today (`fetched_at`), so History and Later are unchanged.
- **Done when:**
  - tests cover a page with a meta date, with only `<time>`, and with none;
  - the repair's count on a copy of the lab is recorded;
  - the 252 impossible orders are counted again on that copy, and the new count is recorded.

## 2. Link labels for screen readers stay out of the text
- **The case:**
  - "(opens in a new window)" and "(opens in a new tab)" appear inside the text of 19 posts from 3 sources (OpenAI News 9, LessWrong 7, Hacker News 3).
  - They're visually hidden labels sites add for screen readers, and the reader keeps them as words.
- **Decided:**
  - The reader drops visually hidden text (elements marked `sr-only`, `visually-hidden`, `screen-reader-text` and the like). This is a general rule on how a page hides text, with no site names and no phrase list.
  - It's tested on the page corpus (0032/0053): no expectation that passes today may fail.
- **Done when:** a corpus page with such labels passes, and the corpus is no worse.

## Done when (all)
Backend suite green; every passing case in `plan/research/lab/cases.json` still passes.
