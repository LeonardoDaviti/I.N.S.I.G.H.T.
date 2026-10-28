# 0043 — The Gwern reader reads only Gwern's writing

Status: **built, not deployed** (2026-10-28) for v9.4 (owner, 2026-10-28, from the Gwern study).

## The case (measured 2026-10-28, `adapters/gwern_adapter.py`)
- **The archive would fetch 1,261 pages**:
  - 526 are `/doc/**/index` topic directories (lists of links and annotations, not reading);
  - 204 are `/newsletter/...` monthly issues, the same as `gwern.substack.com/feed`, which every page advertises as its feed and which is already a source;
  - about 530 are writing: 292 root essays, 76 `/blog/`, 50 fiction, 22 reviews, 66 `/doc/.../` essay pages and a few others.
- **The daily fetch** reads only `/doc/newest/index`. That page is mostly *other people's* papers with Gwern's summaries, and gives about 7 links to his own pages. `/blog/index` lists every short post in reverse order, each with its date as the link's `id`, and is never read.
- **Two downloads per page:**
  - the HTML and the markdown copy, and the markdown, with Gwern's private syntax (`[Lean](!W "…")`, `{.include-strict}`), is stored as the post's text;
  - that text is what search (0040) and the list excerpts read;
  - the shared reader already gets about the same words from the HTML (91–96% of the markdown's count).
- **Dates as text:** the `date-range` spans render "2010<sub>16ya</sub>", so the text reads "201016ya".
- **The page's own metadata is dropped:** status (draft / in progress / finished), confidence and importance.

## Decided
- **Archive candidates:** Gwern's writing only. Leave out `/doc/**/index` directories and `/newsletter/` issues; the newsletters stay available as the Substack feed, which the feed finder offers. Put the measured count in this issue.
- **Daily:** read `/blog/index` (newest first, with the date from the link) together with Gwern's own pages from `/doc/newest/index`, without duplicates.
- **One download per page:** the post's text comes from the shared reader's HTML (`content` = its plain text, `content_html` = its HTML), so stop fetching the markdown copy.
- **Clean the text:** drop the "years ago" subscript of `date-range` spans before reading. This is a Gwern-only rule, kept in the adapter.
- **Keep the page's metadata** in the post's `metadata`: `created`, `modified`, `status`, `confidence`, `importance`. Showing it ("Updated …", "finished · likely") is 0039's work.
- It stays a site adapter: an explicit exception for a site with its own index pages. Keep every rule in the adapter and none in the shared code, and keep the adapter small.

## Built
- **One file**, `backend/insight_core/adapters/gwern_adapter.py`; the shared reader
  (`parsing.py`) and the saver are unchanged. Every Gwern rule is in the adapter.
- **Archive candidates:** the sitemap less `/doc/**/index` (any `/doc/` path ending `/index`) and
  `/newsletter/` (a banned prefix, beside `/static/` and `/metadata/`); the old skip list keeps
  `/index`, `/about`, `/me`, `/changelog`, `/blog/index` and `/doc/newest/abstract`.
- **Daily** (`_discover_recent_entries`): `/doc/newest/index`, then `/blog/index`, each read once;
  of each, the `link-page` links to candidate pages (`#fragment` dropped), in page order, as
  `{url: date}`, one entry per page. A link whose `id` is a date (`2026-09-02`, every blog
  entry) gives that date; a page listed on both keeps the date. `fetch_latest` reads entries in
  that order until it has `limit` posts. The page's own date wins; the link's date is used when
  the page has none.
- **One request per page:** the markdown copy is no longer fetched (`markdown_url` is gone from
  the metadata). `content_html` = `parsing.extract_article_html(page, canonical_url)` (the page
  address makes Gwern's relative images absolute, so figures are kept), `content` = its
  `strip_html` text (the description when no article is found).
- **Dates:** before reading, `DATE_RANGE_RE` rewrites each `date-range` span to its dates and dash:
  `2010<sub>16ya</sub>` -> `2010`, `1929<sup>–</sup><sub>60</sub>1989<sub>37ya</sub>` -> `1929–1989`.
  Other `subsup` spans (inflation-adjusted dollars) are left as they are.
- **Metadata:** `{adapter, created, modified, status, confidence, importance}`. `created` is
  `citation_publication_date` / `dc.date.issued` / the link's date, `modified` is
  `dcterms.modified`; status, confidence and importance are read from the
  `page-status` / `page-confidence` / `page-importance` spans as shown ("finished",
  "highly likely", "9"; the label before the colon dropped). A field the page lacks is left out
  (blog posts have no importance; their confidence is "log"). The post's `date` is `created`, or
  `modified` when there is none.
- **The saver** (`repo_posts`): on a re-fetch the incoming `metadata`, `content` and
  `content_html` replace the stored ones (the full-text keep rule does not apply: the adapter
  never sets `full_content_fetched`), so a stored Gwern post that is fetched again gets the HTML
  text and the new metadata in place of the markdown.
- **Tests** (`test_source_adapters.py`, fixtures trimmed from the 2026-10-28 downloads): the
  candidate filter (directories, newsletters, assets, `.md` out; `/doc/` essay pages in); both
  indexes, nav and papers dropped, blog dates kept, a page on both listed once with its date; one
  request per page, the text equal to the HTML's, no `16ya`, the range `1929–1989`, the image
  absolute, the metadata fields; `fetch_latest` dating a page from its blog link and stopping at
  the limit (17 adapter tests). Backend suite: 745 tests, OK.

### Live check (2026-10-28, read-only, 8 requests about 1.2 s apart, nothing stored)
- **Candidates: 531** (was 1,261): 292 root essays, 76 `/blog/`, 66 `/doc/` pages, 50 fiction,
  22 reviews, 7 `/zeo/`, 6 `/haskell/`, 6 `/note/`, 4 `/sicp/`, 2 `/nootropic/`.
- **Daily list: 80 pages**: the 75 dated blog entries plus 5 of Gwern's pages from
  `/doc/newest/index` (`/lean-scaling`, `/fiction/walking`, `/fiction/perished-paradise-graveyard`,
  `/fiction/molting`, `/fiction/tilakkhana`); `llm-timetravel` and `face-training` are on both and
  listed once. In order: `blog/2026/llm-timetravel` (2026-09-02), `lean-scaling`,
  `blog/2026/face-training` (2026-06-20), `fiction/walking`, ...
- **The 5 pages** (`fetch_latest(limit=5)`, one request each): llm-timetravel 1,152 words,
  lean-scaling 2,662, face-training 1,381, fiction/walking 388 (3 images), perished-paradise-graveyard
  57,479; none with a `NNya` subscript or markdown syntax.
- **One post's fields** (`/blog/2026/llm-timetravel`): title "LLM Time Travel Visualization",
  external_id `/blog/2026/llm-timetravel`, date 2026-09-02, categories `["ai/scaling"]`,
  media_urls the site logo (`og:image`), metadata `{adapter: gwern_site, created: 2026-09-02,
  modified: 2026-09-21, status: finished, confidence: log}`; the text opens "Proposal for AI
  education application: interactive prompt use of the best surviving LLM from each year ...".

### Left open
- The 66 `/doc/` pages kept as candidates are mostly not Gwern's own prose: about 35 are a topic
  directory's `/abstract` page (the directory's introduction) and most others are hosted copies of
  other people's texts (`/doc/science/1986-hamming`, `/doc/anime/eva/1996-newtype-anno-interview`).
  The decision named only directories and newsletters, so they stay; leaving them out is one more
  rule in `_is_candidate_page_url` if the owner wants it.
- Posts already stored from `/doc/**/index` and `/newsletter/` stay; nothing deletes them.

## Not here (0039, v9.5)
Re-checking edits, dating a page that is new *to you*, and the "Updated" mark.

## Done when
- Tests in `test_source_adapters.py` cover: the candidate filter (directories and newsletters out); the blog index parsed with its dates; no duplicate between the two indexes; one request per page; the text without markdown syntax or the "16ya" subscript; and the metadata fields.
- A live check, fetching only gwern.net's sitemap, its two index pages and 5 essays: the candidate count, the daily list, and one post's stored fields, recorded here.
