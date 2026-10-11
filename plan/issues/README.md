# Local issues

INSIGHT has no external issue tracker. Each issue is one markdown file here, numbered
`NNNN-slug.md`, with a `Status:` line (`open` / `discussion` / `planned` / `done`).

| # | Title | Status |
|---|---|---|
| [0001](0001-entity-pages-and-milestones.md) | Entity pages (e.g. Anthropic) with personalised milestones | discussion |
| [0002](0002-track-briefing-reading.md) | Track briefing: a readable, clickable briefing for the analysis version | discussion |
| [0003](0003-source-name-opens-source-settings.md) | Clicking a source/track name opens it in Sources (sheet open) | open |
| [0004](0004-citation-graph-sources-of-truth.md) | Citation graph: parents and sources of truth between posts | discussion |
| [0005](0005-minimal-codebase.md) | Minimal codebase: keep what reading uses, retire analysis completely | built, not deployed |
| [0006](0006-image-cache.md) | Post images through a 24-hour cache | built |

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
