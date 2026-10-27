# Local issues

INSIGHT has no external issue tracker. Each issue is one markdown file here, numbered
`NNNN-slug.md`, with a `Status:` line (`open` / `discussion` / `ready-for-agent` / `planned` / `built` / `done`).

| # | Title | Status |
|---|---|---|
| [0001](0001-entity-pages-and-milestones.md) | Entity pages (e.g. Anthropic) with personalised milestones | discussion |
| [0002](0002-track-briefing-reading.md) | Track briefing: a readable, clickable briefing for the analysis version | discussion |
| [0003](0003-source-name-opens-source-settings.md) | Clicking a source/track name opens it in Sources (sheet open) | done |
| [0004](0004-citation-graph-sources-of-truth.md) | Citation graph: parents and sources of truth between posts | discussion |
| [0005](0005-minimal-codebase.md) | Minimal codebase: keep what reading uses, retire analysis completely | built, not deployed |
| [0006](0006-image-cache.md) | Post images through a 24-hour cache | built |
| [0007](0007-visible-jobs-live-reader.md) | See the jobs that run, and a reader that updates by itself | built |
| [0008](0008-clean-full-text.md) | Full text that is clean: no site menus, no HTML codes | built, not deployed |
| [0009](0009-short-titles.md) | A title is a title: cut posts whose whole text is the title | built |
| [0010](0010-post-page-navigation.md) | Post page: back always in reach, the source name reads the source | built |
| [0011](0011-sources-list-sort-and-read.md) | Sources list: sort by column, find the newest source, read from a row | built |
| [0012](0012-reddit-comments-and-bursts.md) | Reddit: comments that load, posts that don't flood the top | bursts half built; comments half waits for the owner |
| [0013](0013-priority-order.md) | Priority order: the sources I read most come first | discussion (future) |
| [0014](0014-continuous-reading.md) | Continuous reading: scroll from one post into the next | built |
| [0015](0015-smart-archiving.md) | Smart archiving: continue below what I have; no measuring phase in fetch runs | built, not deployed |
| [0016](0016-learned-pace.md) | A pace that learns: survive 429s and timeouts instead of failing | built, not deployed |
| [0017](0017-hacker-news.md) | Hacker News: the article and its discussion | first version built (hnrss.org); kind and comments future |
| [0018](0018-pipecraft-blog.md) | pipecraft.me: a blog with no feed, read from its own JSON API | built, not deployed |
| [0019](0019-feed-row-read-and-source.md) | Feed rows: one read button, the source name reads the source | built |
| [0020](0020-version-display.md) | The running version on the Ingestion tab, in the Mark scheme | built |
| [0021](0021-useful-ingestion-logs.md) | Ingestion jobs that say what they delivered | built |
| [0022](0022-bookmarks-and-read-later.md) | Bookmarks: read later, keep, and what the star means | discussion |
| [0023](0023-github-feed.md) | A GitHub feed in INSIGHT, without scrolling github.com | discussion |

## Analysis archive

Issue 0005 removes the analysis version from `main`. The git tag `mark-ix-analysis-archive`
marks the last commit that still holds it (briefings, Gemini, topics, entity/event memory,
stories, inbox, experts, milestones, the track briefing). It is created when that removal
lands. Read old code with `git show mark-ix-analysis-archive:<path>`. Issues 0001 and 0002
list the files to look at. The finished analysis plans are in `plan/archive/`.

## Ideas, not issues yet

Still open from the old backend `FUTURES.md` (the rest is built or obsolete):

- Conditional fetching: send `ETag` / `If-Modified-Since` and skip unchanged feeds.
- Post versioning: keep a post's earlier text when its source edits it.
- Retention: a policy for old posts (soft delete, then purge).
- Feed discovery: find the feed from a site URL when adding a source.
