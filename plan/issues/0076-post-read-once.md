# 0076 — A post is read once, when it is saved: one stored structure that every page and the story job read

Status: **built** (branch `issue-0076-post-read-once`, not merged, not deployed; Built below) for v9.16, the stability release (no new features), written 2026-11-03 by the Mark X session on the owner's request. Filed as 0076 (owner, 2026-11-03). It needs 0075 built first: this whole change is judged by its diffs.

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

## Measured (2026-11-04, a copy of the lab, 41,637 posts; details private in `plan/research/0076-measure/`)
1. **Pages and the story job disagree on 43% of titles** (17,975 posts), and **the story job's title key changes for 16,887 (40.6%)**.
   - By kind: X 89%, Telegram 61%, Reddit 11%, sites 2%.
   - Causes:
     - X: the raw key keeps the `RT by @` and `R to @` handles and the whole tweet;
     - Telegram: the glued second line and the cut body;
     - sites and Reddit: double-encoded entities, non-breaking spaces, and the 120-character cut.
   - **Expect step 2 to move many title joins.** Its diff (0075) must be read by hand, by kind.
2. **Storage: cut points win.**
   - The row without the body is 22 MB (4.4% of `posts`, 509 MB).
   - With cut points it is 27.6 MB (5.4%).
   - A cleaned copy only where it differs is 59 MB (11.6%), and always 279 MB (55%, over budget).
   - 60.5% of posts need no cut at all.
   - Cut points can't express 3,415 text bodies and 317 HTML ones, from two causes:
     - entity decoding in Telegram's plain text;
     - the X quote byline replaced by a line break.

     Two flags (`decode_entities`, `cut_leaves_break`) cover nearly all of them (about 23 MB, estimated). The rest are stored as a copy.
   - **Decided by the numbers:** cut points plus the two flags, with a copy only where neither expresses it.
3. **Dates:**
   - 3,298 posts are date-only today: all of YouTube, 38 site feeds that are always midnight, and 636 posts in 22 mixed feeds.
   - At most 21 are real midnight posts.
   - **Precision is decided per item at ingestion, not per source** (some feeds are 40–97% midnight).
   - **Missed today:** 6 sources (376 posts) put 80%+ of their posts on one fixed non-midnight hour (dates read in the site's timezone), and these count as exact.
     - Rule: a source whose times sit 80%+ on one hour is date-only for those posts.
     - Measure it again on the fresh server copy before adopting.
   - **68 undated posts** (59 with made-up backlog times) count as exact in `trusted_time`; `published_precision = none` fixes that.
4. **Telegram needs the HTML:**
   - 83.5% of Telegram posts have line breaks only in the HTML;
   - without it, 1,752 titles and 3,280 bodies change.
   - The parser reads both. The warning "line breaks recovered from HTML" is expected on about 1.75k titles and 3.3k bodies.
5. **Call sites:**
   - `post_title` is called at 9 read-time sites (reader, post page, News, search, Discover); `reading_text`, `quote_only`, `hnrss_counts`, `link_post_target` and `quoted_tweet` at 11 more.
   - The story job duplicates the raw title, the reply prefix, `quoted_tweet`, `reddit_author`, its own word count for link posts, and the raw `content_hash` (`stories_service._story_post`).
   - `_story_post` also feeds Discover's article titles, so it moves with the rest.
   - The 0075 tooling (`checks/compat.py`) imports the parsers on purpose and is exempt from the import guard.
6. **A display bug found, fixed in this issue:** the glued-first-line rule cuts a title at a number written two ways ("…145GB models…" against the article's "145 GB" shows as "…145"). Fix it in the one parser, then count it over every site and HN post (0075's diff).

7. **From the v9.15 reader review (2026-11-04), fixed by the one parser:**
   - a reaction tweet's title ("no! really?!", an emoji alone) leads News: a quote tweet whose own words are a short reaction takes the quoted tweet's title (`title_from: quoted words`);
   - an account's self-quoting reply shows its quoted tweet twice on the account's page (71 posts on the lab): the quote card of a tweet the stream already shows right above is folded.

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

## Built
Branch `issue-0076-post-read-once` (2026-11-04), on main c895b7a (0083 item 1 merged). Not merged, not deployed. Migrations 0060–0063.
- **1, `post_parts` and the one parser** (`utils/post_parser.py`; the stored structure `utils/post_parts.py`; writer and readers `db/repo_post_parts.py`; migration 0060):
  - one row per post: the shown title and `title_from` (feed field 36,717, first line 4,720, linked page 198, none 2 on the lab), a row's lead, the post page's text and HTML as cut points into the raw columns (`Body`: kept spans, `decode_entities`, `cut_leaves_break`, a copy only where neither says it), the quoted tweet, `quote_only`, the folded post (without its card: the post page, a thread's reply), hnrss's counts, the link post's target and kind, `reply_to`, Reddit's poster, the words, the quoted words, `warnings` ("title from the first line" 4,720, "line breaks recovered from HTML" 972), `parse_stamp`, `parsed_at`, `digest`.
  - **Not built as the spec listed:** `links` with roles and `media` (post_links already holds the links; no page reads a role yet), `language`/`author`/`reposted_by` (already posts' save-time columns, not duplicated), `published_precision` (on `posts`, item 4: what the source said can't be derived again from the raw post).
  - written at save inside `upsert_post`'s savepoint (no extra subtransaction) and by `save_full_text`; a change to the raw title, text, HTML or address drops the row (trigger), and the next save or the catch-up writes it again, so no row is read against another body than it was cut from.
  - the catch-up (`catch_up`, first in `StoriesService.recompute`, so in the story job's own process at start and after each fetch run): the posts with no row, newest first, 500 a transaction; when `parse_stamp()` changes (a fingerprint of the parser's output on `stamps.PARSED`), every post again, resumable, writing only rows whose digest changed. The raw columns never change for it.
- **2, the pages read `post_parts`** (the move, its own commit): the feed's rows (title, lead, counts, the tweet a post only quotes), trees, threads and roundup names, the post page (title, body, folded body, counts, link, a reply's card), News and its lines, search and its News filter, Classics and its background, Discover's origins and articles, a link's title. Every `title_columns()`/`post_title` call is one SQL column (`shown_title()`); a post not parsed yet reads its stored title and text. **The 0075 diff of the move: 0 in every part** (titles, text starts, link titles, roundups, story membership, origins, News, Classics, Discover). A full comparison of every stored part against the read-time rules on every post and each page's variant (the feed's 4,000/2,000-character windows included): 1 difference in 41,637, a quote card past the first 2,000 characters of a post's HTML, now read from the whole HTML (trees and News used the window, the post page the whole).
- **3, the story job reads `post_parts`**: first as a move (the raw title still: reply, quoted tweet, quoted words, Reddit's poster, link-post words; Discover's counting query reads the poster too), then **one post for everyone** (its own commit): the title key, News's names and the queue's old title (migration 0061) read the shown title. Diff of that step alone (`--head c3482e9`, read by hand, below).
- **4, dates**: `posts.published_precision` (migration 0063: exact | date | none) set at ingestion per item (`parsing.date_precision`: a date string with no time of day is `date`; otherwise the saver tells it by its time as before; no date is `none`), kept on a re-fetch without a date; stored posts stay NULL and read as before, so no row is rewritten and nothing moves. `StoryPost.undated`: a post its source gave no date orders nothing (`trusted_time`). **The fixed-hour rule is not adopted**: no fresh server copy was available (`insight_server_copy` ends 30 October, the lab's period); on it 4 sources (363 posts) put 80%+ of their dated posts on one non-midnight hour (10, 12, 14, 19 UTC), on the lab 6 (376). Only 07/08 UTC are a local midnight (US Pacific); the others are not, so the stored times can't tell a date-only feed read in a timezone from a feed that publishes at a fixed hour. Measure again on the fresh copy (0075 D).
- **5, fixes by the one parser** (migrations 0062, 0064, 0065; each a new parser stamp):
  - **the number-split title**: a whole title is cut where the text's first line ended only if its HTML, where its text says the title's start, ends a line there; where it ends the line further on (two emoji kept together), the title ends there. Diff (all 41,637 posts): 22 titles, all right on a read by hand (`…145GB models…` whole again; hyphenated and slashed words no longer cut, "ИИ-концепций", "NLA/J", "Навье-Стокса-Чейна"; an emoji kept with its line; "…как говорится 🌌🗿" without the next line's "UPD."; 9 run-on titles now end at their HTML's line end).
  - **a reaction tweet leads News by what it quotes**: a quote tweet whose own words are 4 words or fewer and 30 characters or fewer (measured on the lab's quote tweets: up to 4 they read as reactions, from 5 most say something of their own) gets `subject` = "<quoted author>: <quoted tweet's title>"; **News's lead reads it, the feed row and the post page keep the post's own words** (the owner's review: "the rows themselves are right"; the spec's "title_from: quoted words" is not used). 3 News leads change, all three right.
  - **a self-quote folds**: a post with nothing of its own that quotes its own account's tweet, stored, is no row on any page (`NOT_ALBUM_PIECE`: feed, counts, search).
  - **nothing the stored title said is lost** (`post_parts.opening`, after the review of the first diff): what a post's stored title says past the title shown (a bridge's title is the post's first ~85 characters with its lines glued; Nitter's the whole tweet), without "RT by"/"R to" and the bridge's cut, spaced as the text is when it is the text's start. The story job joins by its key as by a title (`StoryPost.title_keys`: copies of one post across a writer's channels, whose title shown is under 5 words and whose texts differ by a line), and News's names read it (a name said on a bridge post's second line); the queue keeps it for a changed post's old names. Measured: an exact hash of the shown text joins none of those copies (they differ at characters 95–1,066, or are 104 characters long), so the join is by the opening, as main's stored title did; the text key stays `content_hash` and `SAME_TEXT_MIN_CHARS`.
  - Cases: `news-lead-reaction-title` and `source-stream-self-quote-row` pass.
- **6, the import guard** (`tests/test_post_parts.py`): no service, repository, adapter or `main.py` imports the read-time rules (post_title, reading_text, quote_only, link_post_target, hnrss_counts, quoted_tweet, quoted_words, reddit_author, …) or the parser; the writer `db/repo_post_parts.py` is exempt, the checks' `compat.py` isn't scanned. The checks read the stored parts when a version has them (`compat.stored_parts`), as its pages do.
- **Budgets, measured on a copy of the lab (41,637 posts), back to back, load recorded**: `post_parts` **33.0 MB = 6.2% of posts** (532 MB; at the ~6% budget: 3.3 MB of it the openings of 11,792 posts; 60.5% of posts need no cut, 102 text and 1,475 HTML copies, 2.3 MB). First-start parse **261 s and 260 s** (load 8–12 on 32 cores; before the opening) and **246 s** with it (load 14–27), peak **145, 159 and 164 MB** in its process, WAL 91–165 MB (cluster-wide, an upper bound); a second catch-up does nothing (0 s). **API idle memory: the uvicorn process 70 MB (container 56 MB after the job)**, unchanged. The story job's full run on the check's copy: 48–89 s main, 347–426 s head (the first parse included). A comparison of every stored part with the read-time rules on every post: 1 difference (a quote card past the HTML's first 2,000 characters, now read from the whole HTML).
- **Tests**: backend 1,365 pass (`./run-tests.sh`; `test_post_parts.py` new). Frontend unchanged: node 218/218, vitest 695/695, typecheck, build; bundle: feed 0.97% of its 1% budget, post 0.65% (unchanged).
- **The real-data check** (`insight_lab`, clock 2026-10-30, after the fixes): **PASS** with two allowances, each read by hand: `title.places.news` 0 → 3 (the three reaction leads), `date.date_only_first` 43 → 44 (a video with a date alone joined its story as the origin, the repost of its tweet the same day a share). Cases 68 pass (main 66): `news-lead-reaction-title`, `source-stream-self-quote-row` fail → pass; every case passing on main passes (`news-name-in-comparison`, marked fail, passed in the run before the opening and fails again with it, as on main). `text.repeats_title` 2,361 → 2,349. Diff, every change read by hand, **no wrong move left**:
  - titles 22, text starts 21: the glue fix above, all right;
  - **story membership 43** (joined 24: Reddit 9, X 6, Telegram 6, YouTube 1, site 2; role or reason 11: Telegram 7, X 4; gained or lost 8: X 6, Telegram 2; none left every story): joined, all right (a YouTube talk and the repost of its tweet; a paper's link post and a paper-sharing account's post by its title once the address and the bridge's `[...]` are gone; Reddit cross-posts in two subreddits; a Telegram `[Photo]` post and its copy by their first line; a Reddit post and the X post of one announcement; a forum post and its link post); role, all right (a link post whose title is the page's own now shares it); gained, all right (copies and quotes of one tweet, a Reddit copy of a write-up);
  - roundups 5 (a roundup now names one more story, by the joins above);
  - **News 9**: 3 leads titled by what they quote (right); two rows re-led with the same posts (a launch, a release; neutral); a row loses a post about another model that was in it by a shared word (right). The first diff's losses are back (the 3-post launch row, the name's mention), and the generic "Q3" row doesn't surge;
  - Discover 111: a site gains a story origin (its blog's study, now 3 voices with a Reddit copy) and moves up, the 109 between move down one; one voice more on another site.
  - Report: `plan/research/lab/checks/issue-0076-post-read-once-2026-11-04.md` (private); the title-key step alone, before the fixes: `checks/c3482e9-2026-11-04.md`.

## Left open
- The text key still hashes the raw title, text and HTML (`content_hash`): a hash of the shown body would join no more copies on the lab (measured above) and would move the voices' names (0082) too.
- `links` with roles and `media` in `post_parts`; `title_from` "page title" and "quoted words" aren't told apart (a link preview's page title reads "first line").
- `post_parts` is at 6.2% of `posts` against ~6%: the lead (11.5 MB raw) is the largest part; it could be dropped where it equals the text's start.
- The fixed-hour date rule: measure on the fresh server copy (0075 D) before adopting; stored posts' `published_precision` stays NULL (today's rule).
- `tree_rules.origin_title` titles quoted words with `display_title` in the job (a rule module, not a page; the guard scans services, repositories and the API).
- `test_search`'s ranking test failed once under load in a full run and passed alone and in the next full runs.
