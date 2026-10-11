```meta
kind: page
routes: /blog, /blog/:slug
states: index, article, unknown
```

# Blog

Code: `pages/BlogPage.tsx`, `blog/posts.ts` (the registry), `blog/components.tsx` (the building blocks), `blog/figures.tsx`, `lib/highlight.ts`, one file per post in `blog/posts/`.

## Purpose

Teach how INSIGHT is built, from its own code and numbers, so the owner (and any reader) learns to judge the next change. A post is a lesson you read once and come back to for its figures, its cheat sheet and its sources. It is reading, so it follows the reader's rules (P1, P4).

## Entry & URL

- `/blog` lists the posts, newest first. `blog` is a top bar word, after `sources`, and a ⌘K entry.
- `/blog/:slug` reads one post. An unknown slug replaces itself with `/blog`.
- Section headings are anchors (`/blog/:slug#retire`), so one section can be linked.

## Anatomy

- **Index:** `PageHeader` "Blog" with one meta line; one bordered row per post: date · minutes (`small`, `text-3`, tabular), the title (`heading`, 600), the summary (`text-2`).
- **Post:** `BackLink` "blog", then date · minutes, the title at the display step (650), then the body in the reading column.
- **Lede:** the first paragraph in `text-2` at a step above body: what the post shows, in two or three sentences.
- **Sections:** numbered `H2` with anchors; each ends with one **Takeaway** (a `2px` left rule, bold "Takeaway.").
- **Figures** (owner decision 015: figures are what make a post worth reading):
  - inline SVG, drawn only with the tokens (`rgb(var(--text))`, `--text-2`, `--text-3`, `--border*`, `--raised`, `--inverse`), so they follow dark and light (P2);
  - the one loudest mark is the inverted block, and it is the thing that is real or kept; dashed outlines are planned, removed or not built yet (P3);
  - every number is measured on the repository and dated in the caption; nothing is invented or rounded without saying so (P11);
  - a caption starts with **Figure N.** and says what to see, not what the chart is;
  - one figure per major section is the norm; figures and wide code may break out of the column (`lg:-mx-24`).
- **Code:** real excerpts only, captioned with their path (and line); `lang` is required, and highlighting is monochrome: keywords and defined names bold, strings and numbers `text-2`, comments `text-3` italic, never a hue (P2, P3). Wrap lines to about 70 characters so nothing scrolls sideways. Code that does not exist yet is labelled "where we are heading".
- **Before/after:** `Compare`, two labelled blocks; the after label is the inverted chip.
- **Table:** the habits table, `small`, a hairline per row, the middle column bold.
- **End of every post:** "Check yourself" (a retrieval quiz), a cheat sheet (`dl` of the terms), "Read next" (one primary source first), then one line inviting questions.

### How a post is written

- Plain English, short sentences, sentence-case headings; no marketing voice and no hype.
- Every claim about INSIGHT cites real code (path) or a measured number with its date.
- Every outside claim links its primary source, checked before publishing; quotes are exact. What cannot be checked is softened or cut.
- Trade-offs are written both ways: what a change gains and what it costs, and how the cost is contained.
- Teaching shape: knowledge first, then practice. Quiz options have the same number of words, and the right answer moves between positions.
- One post per file in `blog/posts/`, registered in `blog/posts.ts` (slug, title, summary, date, minutes); the body loads as its own chunk.

## States

- **index:** the list with every post.
- **article:** a post with its figures, code, quiz and cheat sheet.
- **unknown:** a slug no post has: the list, with the history entry replaced.

## Interactions & keys

- Links and heading anchors only; a quiz answer is a radio, then **Check**, then the verdict as a glyph and a word (● Right. / × Not quite.) with the why, and **Try again** to retrieve it later.
- No keys of its own; the shell's ⌘K and `?` work as everywhere.

## Worst cases

- A title of three lines wraps and balances; it is never cut.
- A figure at 390px scales down with its viewBox; its labels stay legible because each figure is at most one column of rows.
- A long code line scrolls inside its block, never the page.
- Many posts: the index is a plain list; no paging until there are more than a screen of posts.

## A11y & motion

- Every figure is `role="img"` with an `aria-label` that states its numbers; the caption repeats what to see.
- The quiz is a `fieldset` per question with a `legend`; the verdict is `role="status"`.
- Nothing animates; hover only changes a border (P12).

## Decisions

- 015 (the blog, its figures and how posts are written), 016 (analysis is retired, which section 7 of the first post weighs both ways).

## Open issues

- No RSS feed of the blog yet, which a reader that reads feeds should have.
- Figures are checked in dark; the light theme has not been screenshot-checked.
- The Wall's site map has no blog node yet.
