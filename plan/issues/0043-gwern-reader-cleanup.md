# 0043 — The Gwern reader reads only Gwern's writing

Status: **planned** for v9.4 (owner, 2026-10-28, from the Gwern study).

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

## Not here (0039, v9.5)
Re-checking edits, dating a page that is new *to you*, and the "Updated" mark.

## Done when
- Tests in `test_source_adapters.py` cover: the candidate filter (directories and newsletters out); the blog index parsed with its dates; no duplicate between the two indexes; one request per page; the text without markdown syntax or the "16ya" subscript; and the metadata fields.
- A live check, fetching only gwern.net's sitemap, its two index pages and 5 essays: the candidate count, the daily list, and one post's stored fields, recorded here.
