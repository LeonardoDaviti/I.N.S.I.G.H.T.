# 0063 — Saved pages keep their own date, and link labels stay out of the text

Status: **built, not deployed** (2026-10-31) for v9.9; spec 2026-10-31 (owner, 2026-10-31: "spec all the issues we found while discussion").

## 1. A saved page is dated by the page, not by the day you saved it
- **The case (the lab):**
  - All 8 Saved pages (0031) are dated the day they were saved.
  - Your sources link them a lot. Of the 1,248 citations between stored posts, 252 have the linked post published *after* the post linking it, which is impossible. Saved pages make most of them: 46 from finetune_dan, 26 from LessWrong, 17 from Smol.
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

## Built
(2026-10-31, branch `issue-0062-0063-reading-fixes`, not deployed.)

### 1. A saved page is dated by the page
- **Saving a page** (`services/saved_service.py`): `read` passes on the date the page states (`page_watch.page_date`: `article:published_time`, JSON-LD `datePublished`, the date metas, a single `<time datetime>`, a single written date), or None. `dated_by_page` makes it `published_at`; with none, or one after the save (a clock off), the save time, as before.
- **Where it sorts:** a save still tops the feed (0022's decision). A page dated earlier gets the save time in `surfaced_at`, the feed's sort key since 0039 ("sorts at when it reached you"). An undated page needs none: its date is the save time.
- **When it was saved** stays `fetched_at`, so History and Later are unchanged. `metadata.article_published_at` is no longer written: `published_at` holds the page's date.
- **The repair** is migration **0045** (`0045_saved_pages_keep_their_date.sql`). It reads only what was stored; nothing is fetched.
  - The stored body (`content_html`) is the reader's output: the page's `<head>`, JSON-LD and `<time>` elements never reach it. `page_date` over the 8 stored bodies finds **0** dates.
  - What the save read off the whole page *is* stored: `metadata.article_published_at`. When the page stated no date, that key holds the moment of reading, which always comes after the save time (the clock is taken before the read). So a key earlier than `published_at` is a date the page stated, and only those are taken. That's a fact of the code path, not a threshold.
  - Each such post gets that date as `published_at` and the old save time as `surfaced_at`. Idempotent.
- **Tests** (`tests/test_saved.py`): a page with a meta date (dated by it, sorting at the save, `fetched_at` untouched), with only `<time>`, with none (read: no date; saved: the save time, no `surfaced_at`), an unreadable page (the save time), and 0045 on stored rows (a stated date taken, a reading moment and an unreadable page left, twice over).
- **On a copy of the lab** (`pg_dump` of `insight_lab`, migrated with 0045):
  - **3 of 8** Saved pages repaired: The Law of Leaky Abstractions (2002-11-11), Inside NVIDIA GPUs (2025-09-29), Anthropic raises $30B Series G (2026-02-12).
  - **Impossible orders** (citations between posts of different sources, boilerplate links left out, where the linked post is published after the post linking it): **252 → 230** of 1,254.

### 2. Link labels stay out of the text
- **The rule** (`parsing._without_hidden_link_labels`, step 1 of the reader): inside a link that shows words of its own, an element hidden from the eye goes. Hidden means `_visually_hidden`:
  - a class token that, without `-` and `_`, holds `visuallyhidden`, `hiddenvisually` or `screenreader`, or ends in `sronly`. That covers Bootstrap's and Drupal's `visually-hidden`, h5bp's `visuallyhidden`, WordPress's `screen-reader-text`, GOV.UK's `govuk-visually-hidden`, `u-hidden-visually`, Tailwind's `sr-only`, and prefixed ones like `wt-cli-sr-only`;
  - or an inline clip to nothing: `clip: rect(0 0 0 0)` / `rect(1px, 1px, 1px, 1px)`, `clip-path: inset(50%)`.
  - Never a toggle: `hidden`, `overflow-hidden`, a breakpoint variant (`md:sr-only`), or an element undone by `not-sr-only` at some breakpoint. That text shows somewhere.
  - No phrase list and no site names.
- **Why only inside a link** (measured, not assumed): on the lab's stored bodies, hidden text outside links carries meaning the reader would otherwise lose:
  - technologyreview's figures read "66 % of manufacturers say…" from a hidden "66 %";
  - Apple's comparison cells hold "No TrueDepth camera system" under an icon;
  - Apple's footnote markers are labelled "Footnote".

  A first version dropped all hidden text and would have lost these, so it was narrowed. An icon-only link keeps its hidden name: it is the link's only text.
- **On the lab's stored bodies**, the rule takes out exactly 97 labels in 13 posts, and nothing else:
  - 90 × "(opens in a new window)", 4 × "(opens in new tab)", 1 × "(Opens in a new window)";
  - 2 × Apple's "Learn more – Creator Studio (Opens in a new window)" behind a visible "Learn more".
  - By source: OpenAI News 9, Hacker News 3, MIT Technology Review 1. Technology Review wasn't in the issue's count.
- **The corpus** (0032/0053): 56 pages. Every expectation that passed still passes, and the 16 known gaps still fail as recorded. The 54 old pages read word for word the same. A first version dropped Apple Newsroom's hidden "Media" heading, which this one keeps.
  - Two pages were added from bodies the lab already stored, never fetched: `openai_model_spec` (12 labels: `must_not` "(opens in a new window)") and `technologyreview` (`must_not` "(opens in new tab)", `contains` "66 % of manufacturers say", "40 % of manufacturers expect").
  - Both pass.
- **Tests** (`tests/test_full_text.py`, `HiddenLinkLabelTests`): each hiding class and clip, hidden text outside a link kept, an icon-only link's name kept, toggles and breakpoint classes not hiding.
- Backend suite: 1060 tests green.

## Left open
- **The 5 undated Saved pages** keep the save time:
  - two GitHub repositories (a repository states no date);
  - two arXiv abstracts, Grokking and Chinchilla. As far as known, arXiv states the date only in `citation_*` metas, which `page_date` doesn't read. This isn't checked against these two pages, because their `<head>` wasn't stored. Teaching `page_date` those metas would change page watch's dates too, so it's a reader change of its own, and it needs each page again;
  - The Bitter Lesson, saved unreadable.

  They make 124 of the 230 remaining impossible orders. 0064 treats a Saved page's time as untrustworthy anyway.
- **LessWrong's 7 posts** keep "(opens in a new window)". Their authors pasted quotes from openai.com with the label as plain words (`system card addendum⁠(opens in a new window)`), with no markup to read. Only a phrase list would catch it, and that's ruled out.
- **The 13 stored posts with labels** keep them until their pages are read again. Their stored bodies still hold the hidden spans, so a repair could take them out without fetching. The issue didn't ask for one.
