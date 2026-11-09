# 0140 Built: teasers read in full

Built 2026-11-09 on its own branch. **No migration** (metadata keys only). No request in the tests: FakeHttp
answers and hand-written fixtures with invented hosts, in the shape of the classes the spec measured
(`backend/insight_core/tests/test_teasers_in_full.py`). Private rows stay in `plan/research/0140-notes.md`.

## What changed

| # | Spec | What changed |
|---|---|---|
| 1 | Every read leaves a reason | `full_text.read_page` returns a `PageRead(outcome, article)`; every caller (a new post in `generic_rss._read`, a stored one in `_read_again`, the repair) stores `metadata.page_read_outcome = {outcome, at}`: `full`, `nothing_longer`, `not_same_article`, `needs_script`, `http:<status>`, `error:<class>`, and `metadata.full_text_rule` (the rules' version, `FULL_TEXT_RULE = 2`). The path that recorded nothing (a post with a body, `None` from the page, or a non-HTTP exception) now records why; an exception is logged at warning with its class (an HTTP failure at info). The saver keeps both keys on a feed re-fetch (`repo_posts._post_update_assignments`, like `page_tries`). The source page's anatomy counts them: `Full text` reads `on · 13 summary only` (every outcome but `full` and `nothing_longer`), each reason counted on hover; a feed whose page reads all left the summary is `on`, no longer `in feed`. |
| 2 | A same-article test that works | `full_text.same_article`: today's opening rule; or, **for a post on its source's own site** (`same_site` of the post's and the source's hosts), the post's title is one of the page's titles (`<title>`, `og:title`, `<h1>`, with a site name before or after a separator; a title under 12 characters is no evidence), or the page names the post's address (canonical, `og:url`, normalized), or 60% of the teaser's 5-word runs (at least 3 runs) are anywhere in the page's text. **A link post** (its address on another site: a link blog, an aggregator) keeps today's rule alone: the linked page's title and canonical are the linked article's, and taking them would replace the author's words with the page they link. **The cut marker:** `full_text.cut_marker` makes a post a teaser whatever its length: a link to the post's own address whose fragment names a cut (`#cut`, `#more-123`, `#…cut…`) or whose class is a more-link, or the body's last link with 1–4 words of its own (the title aside), next to nothing after it, and no comments / permalink / footnote-return words. |
| 3 | Pages that need a script | `kinds/embedded_article.py` (pure): the long prose strings (700+ characters, letters not code) under a text key (`articleBody`, `content`, `body`, `html`, `markdown`, …; never a description, excerpt, summary) of the page's JSON-LD, `application/json` blocks (Next.js `__NEXT_DATA__`), and framework state assignments (`window.__NUXT__ = {…}`, `__INITIAL_STATE__`, `__APOLLO_STATE__`), each with the title of the object holding it; markdown or plain text becomes paragraphs, headings, lists and code. Tried whenever the page's markup gave nothing taken; a candidate is taken when its holder's title is the post's, or its text passes the content rules, or it is the only long one on a page that is the post's (title or address) with no other title on its holder. A page with no article, no such data, and an app root / framework runtime / `<noscript>` asking for JavaScript ends `needs_script` (no headless read: 0081). Its fidelity carries `embedded: true`. |
| 4 | The repair again | `repair_full_text --rule`: posts never read in full whose `full_text_rule` is older than 2 and whose last outcome is `nothing_longer` / `not_same_article` / `needs_script` / none; short, or cut (SQL narrows to bodies holding their own address, `is_teaser` decides); generic RSS only, no paid teaser, never a tweet / Telegram / Reddit / YouTube / GitHub / arXiv address; newest first, a site at a time, `PAGE_DELAY_S` apart, 4 sites at once, a site failing 3 times in a row left for the next run. Each read stores its outcome and the version, so it **resumes** after a stop and a later start finds nothing. `repair_safely` runs it from the ingestion process's start (`run_scheduler`, a thread, logged every 100 reads and at its end), like 0130 E1 / 0137; nothing when `INSIGHT_DISCOVER_READS=0` (a machine that must not fetch) or `INSIGHT_FULL_TEXT_REPAIR=0`. The summary carries `outcomes`. |
| 5 | The reader | The post API gives `teaser_reason`; the post page shows `Summary only · <why> · Open the page ↗` under the text (`data-teaser`), for not the same article, needs a script, an HTTP error, could not be read, and nothing longer **only** when its feed cut the body (an uncut short post whose page held nothing longer is whole: a note, a link post). Design: `post.md` state `teaser` (scenario and fixture), `sources.md` the anatomy cell. |

## Measure 1: fixtures, right / wrong per class

`FixtureMeasureTests` (one read per fixture). Wrong = a page taken that is not the post's article.

| Class | Wanted | Right | Wrong |
|---|---|---|---|
| Feed abstract (213-character class), page titled as the post | full | 1 | 0 |
| Feed abstract, page names the post's address (a short title) | full | 1 | 0 |
| Read-more cut (1,500+ characters, opening changed by a caption) | full | 1 | 0 |
| Next.js `__NEXT_DATA__` (markdown, a related post beside it) | full | 1 | 0 |
| JSON-LD `articleBody` on an app root | full | 1 | 0 |
| Link post: the linked page has the post's title and its own canonical | not_same_article | 1 | 0 |
| Another article on the site (other title and canonical) | not_same_article | 1 | 0 |
| A sign-in wall | not_same_article | 1 | 0 |
| Next.js data holding only another post | needs_script | 1 | 0 |
| A script-built page with no data | needs_script | 1 | 0 |
| A short title ("Notes") shared with another page | not_same_article | 1 | 0 |

11 right, **0 wrong**. Under the old rules the five positive classes are all refused (their bodies are 200+
characters that do not open the page, or the page holds no markup article). The rules each accept and reject on
their own fixtures (`SameArticleTests`, `CutMarkerTests`, `EmbeddedDataTests`).

## Real checks (read-only, the 2026-11-05 export `insight_server_1105`; 3 of them)

1. **The cut marker against stored bodies.** Bodies of 1,400+ characters that link their own address, generic RSS
   addresses only: the first version marked many whole posts cut (a feed ending "Comments", Reddit's "[link]
   [comments]", footnote "[return]" links). Fixed by the class (a fragment that names no cut is no cut;
   comments/permalink/return words are no cut), then: 546 such bodies, **27 cut**, every one a real "Read more"
   (two newsletter sites on their own domains). Those are tests now.
2. **What the first start reads** (`--rule --dry-run`, no request): 17,451 candidates, **5,788 pages to read** on
   327 sites (the biggest 484); skipped: 10,310 X posts, 482 + 79 + 1 site-reader posts, 282 Substack, 51 page
   watch, 457 bodies with a self-link that is no cut. At 2 s per page per site, 4 sites at once, about an hour or two.
   The owner's named post's site is among them (15 posts).
3. **The anatomy count** on the export: 8 ms (49,384 posts), no outcome stored yet (none before this version).

Measure 2 (teasers before/after by outcome on the newest 4,000) and 3 (three named posts read in full on the
server) need the deploy: rows go to `plan/research/0140-notes.md`.

## Open
- Why the "all posts" tech-site feed's 108 teasers failed is not known from here (no page is stored). After the
  deploy their outcomes say it: `not_same_article` (the shingles or cut should have caught it: look), or
  `needs_script` / `error:*`.
- The first start re-selects the 10k X posts each start (they are never marked), one query of ~50 ms; harmless,
  could be narrowed by kind later.
- The start's repair uses its own HTTP client: a host the scheduler is fetching at the same time may get two
  readers for that hour (each polite on its own).
- Not measured beyond the fixtures: `SHINGLE_SHARE` 0.6, `TITLE_MIN_CHARS` 12, `CUT_WORDS` 4, the embedded
  700-character floor. The outcomes after the deploy are the measure.
