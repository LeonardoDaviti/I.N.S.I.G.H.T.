# 0076 — A post is read once, when it is saved: one stored structure that every page and the story job read

Status: **spec (draft)** for v9.16, the stability release (no new features), written 2026-11-03 by the Mark X session on the owner's request. Filed as 0076 (owner, 2026-11-03). It needs 0075 built first: this whole change is judged by its diffs.

**Constraints:** download nothing; no real channel names in committed files; measure on a copy of the lab (and on the fresh copy, 0075 D).

## Why
1. **The structure is guessed again at every read.**
   - Pages call `post_fields.post_title(title, content, html)` at nine call sites. It re-reads the text's first 4,000 characters and the HTML's first 2,000 on every request.
   - `reading_text`, `body_after_title`, `without_quote_marks`, `quote_only`, `link_post_target`, `hnrss_counts` and `body_without_feed_lines` do the same for the body, the quote card, the footer and the link.
   - D1 found 1,757 posts whose title differed by page; one shared call fixed that.
   - One call still looks separate: News's titles for the stored posts its citations point to call `display_title(title, content)` without the HTML (`news_service.py`, the `stored` map).
2. **Two parsers read the same post.**
   - The story job builds its own post (`stories_service._story_post`) from the raw stored title, not the title the pages show. It works out replies from the raw title, the quoted tweet and Reddit's author from the HTML, and words for link posts.
   - So a story and a page can disagree about one post. Title joins group by a title the reader never shows.
3. **Facts the source gives are lost at save, then guessed later.**
   - A date with no time is stored as 00:00:00 UTC, and `story_rules.trusted_time` recognises it by that value. A real midnight post, or a date read in another timezone, is misread.
   - Undated backlog posts get made-up times: the start of the UTC day minus a second, plus microseconds for order (`repo_posts.UNDATED_BACKLOG_SQL`).
   - A Telegram post's line breaks are lost in the stored text and recovered from its HTML (0072 B2).
4. **Every display fix is a patch at read time.** It touches every page at once, and nothing stores what the rule said before. Five versions running needed title sections.

`build_post_fields` already runs at save (language, addresses, content hash, author, reposts). This spec extends that layer to the post's whole structure.

## Decided
1. **One parser, one stored result per post** (`post_parts`, one row per post). It holds:
   - **title:** the shown title, and `title_from`: feed field | page title | first line | quoted words | linked page | none;
   - **lead:** up to 300 characters, for rows and cards;
   - **shown body:** where it starts and ends in `content` and `content_html`. Decide by measurement between cut points (offsets, checked against `content_hash`) and a stored cleaned copy, within the budget below;
   - **quote:** the quote card (author, handle, address, where its text sits), and `quote_only`;
   - **footer:** its kind (Reddit, hnrss, Nitter, the Telegram bridge) and where it sits; the link post's target and `link.kind`;
   - **links:** address, position, anchor text and role (own | quoted | footer | label | media);
   - **media;**
   - **`published_precision`:** exact | date | none, from the source's own date format at ingestion;
   - **people:** language, author, reposted_by, reply_to (moved here from the story job);
   - **bookkeeping:** `parse_stamp` (0071's stamp mechanism), `parsed_at`, and `warnings`: where a rule guessed, e.g. "title from the first line", "line breaks recovered from HTML", "roundup shape unsure".
2. **Written at save,** and again when the parse stamp changes:
   - in batches, in a child process (0072 A's approach), writing only rows whose result changed (a hash compare), so a re-parse doesn't rewrite the table;
   - never at read time;
   - the raw `title`, `content` and `content_html` never change, so a parse can always be redone.
3. **Dates say what they know.**
   - `published_precision` replaces the 00:00:00 rule in `trusted_time` and the date-only fix's day logic.
   - `surfaced_at` keeps its job (order), but no longer stands in for "how precise".
   - Stored posts get their precision from their source's date format where it can be told; otherwise it's set to `date` exactly where today's rule says date alone, so nothing moves.
4. **Every reader of a post reads `post_parts`:**
   - the feed, the post page, trees and threads;
   - News, its citations included;
   - search and its News filter;
   - Discover's origins and articles, Classics and its background;
   - roundup names and link titles;
   - **the story job:** title key, text key, quote, reply and author.

   `post_fields`' read-time functions are called only by the parser. A test fails if a service or repo imports them.
5. **Two steps, each with its diff:**
   - **Step 1, the move:** the output is unchanged. `realdata-diff` shows 0 changes for every page. The story job keeps its present inputs, now read from `post_parts` (raw title as `story_title`).
   - **Step 2, one post for everyone:** the story job's title and text keys come from the shown title and the shown body (no footer, no quote card). This changes stories. It's measured as its own diff (joined, left, split, merged), checked by hand from the diff, and reviewed before merging.
   - **After that:** v9.16's fixes, each a parser change with its diff.

## Budgets (measure on the lab copy, before and after, back to back)
- **Storage:** `post_parts` should stay within about 20% of `posts`' size. Prefer cut points to copies of bodies.
- **The first start's writes** (WAL) and the parse's time. They must fit 0072 A's budget; a deploy already writes about 2.9 GB on its first start, so this must not add another full rewrite.
- **Response times and memory:** the feed's, the post page's, News's and search's answer times, and the API's idle and peak memory. They shouldn't get worse, and the reads should get cheaper.

## Prepare in v9.15 (small, optional)
The incremental story job reads a post's fields through one function, so v9.16 changes their source without touching the job's logic.

## Done when
- `realdata-check.sh` passes: the cases, the invariants no worse, step 1's diff 0, and step 2's diff reviewed.
- The import guard test is in.
- The budgets are measured and met.
- The review runs on the fresh copy, not only the 30 October one.

## Not in this issue
- Mark X's readings.
- New display features.
- Changes to what is fetched.

## For Mark X
- **`post_parts` is the input of Mark X's reading (F0.2):** the title, the cleaned text, links with position, anchor text and role, and the platform. Mark X never parses a post again.
- **The three layers:**
  - the raw post is what was observed;
  - `post_parts` is derived by rules;
  - Mark X's reading is judged by a model;
  - the owner's corrections are judgements.

  Each layer is versioned (stamps, prompt versions), and the precedence is owner over model over rule.
- **`warnings` mark the fields where the rules guess.** Mark X's reading fills those first, so the last few percent of text-only guesses get a model's answer instead of another rule.
- **`published_precision` feeds "first" and "earliest copy we saw"** (the tradecraft note).
