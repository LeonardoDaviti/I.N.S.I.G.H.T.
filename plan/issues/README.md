# Local issues

INSIGHT has no external issue tracker. Each issue is one markdown file here, numbered
`NNNN-slug.md`, with a `Status:` line: `discussion`, `future` (not now), `spec` (written, not
built), `built` (on `main`), `decided: no change`, or `done`. A part may carry its own status.

**What is on the server.** The server runs v9.5: the copy of its database taken 2026-10-30
(`insight_server_copy`) has applied every migration up to `0037`, v9.5's last, and every issue up
to 0048 was built in v9.5's commit (d1d3c75) or before. So the rows below say "on the server
(v9.5)" for those, where an issue file's own Status line, written when it was built, may still
say "not deployed". v9.6 to v9.13 (0049 on) are on `main` only.

| # | Title | Status |
|---|---|---|
| [0001](0001-entity-pages-and-milestones.md) | Entity pages (e.g. Anthropic) with personalised milestones | discussion |
| [0002](0002-track-briefing-reading.md) | Track briefing: a readable, clickable briefing for the analysis version | discussion |
| [0003](0003-source-name-opens-source-settings.md) | Clicking a source/track name opens it in Sources (sheet open) | done |
| [0004](0004-citation-graph-sources-of-truth.md) | Citation graph: parents and sources of truth between posts | discussion |
| [0005](0005-minimal-codebase.md) | Minimal codebase: keep what reading uses, retire analysis completely | built, on the server (v9.5) |
| [0006](0006-image-cache.md) | Post images through a 24-hour cache | built, on the server (v9.5) |
| [0007](0007-visible-jobs-live-reader.md) | See the jobs that run, and a reader that updates by itself | built, on the server (v9.5) |
| [0008](0008-clean-full-text.md) | Full text that is clean: no site menus, no HTML codes | built, on the server (v9.5) |
| [0009](0009-short-titles.md) | A title is a title: cut posts whose whole text is the title | built, on the server (v9.5) |
| [0010](0010-post-page-navigation.md) | Post page: back always in reach, the source name reads the source | built, on the server (v9.5) |
| [0011](0011-sources-list-sort-and-read.md) | Sources list: sort by column, find the newest source, read from a row | built, on the server (v9.5) |
| [0012](0012-reddit-comments-and-bursts.md) | Reddit: comments that load, posts that don't flood the top | bursts half built, on the server (v9.5); comments half waits for the owner |
| [0013](0013-priority-order.md) | Priority order: the sources I read most come first | discussion (future; 0051 ranks by coverage until there is reading data) |
| [0014](0014-continuous-reading.md) | Continuous reading: scroll from one post into the next | built, on the server (v9.5) |
| [0015](0015-smart-archiving.md) | Smart archiving: continue below what I have; no measuring phase in fetch runs | built, on the server (v9.5) |
| [0016](0016-learned-pace.md) | A pace that learns: survive 429s and timeouts instead of failing | built, on the server (v9.5) |
| [0017](0017-hacker-news.md) | Hacker News: the article and its discussion | first version built (hnrss.org), on the server (v9.5); kind and comments future |
| [0018](0018-pipecraft-blog.md) | pipecraft.me: a blog with no feed, read from its own JSON API | built, on the server (v9.5) |
| [0019](0019-feed-row-read-and-source.md) | Feed rows: one read button, the source name reads the source | built, on the server (v9.5) |
| [0020](0020-version-display.md) | The running version on the Ingestion tab, in the Mark scheme | built, on the server (v9.5) |
| [0021](0021-useful-ingestion-logs.md) | Ingestion jobs that say what they delivered | built, on the server (v9.5) |
| [0022](0022-bookmarks-and-read-later.md) | Bookmarks: read later, keep, and what the star means | built, on the server (v9.5) |
| [0023](0023-github-feed.md) | GitHub Trending in INSIGHT, without scrolling github.com | Trending built (RSS feed), on the server (v9.5); Following later |
| [0024](0024-release-updates.md) | Release updates: new versions of the apps and services I use | future |
| [0025](0025-reddit-after-rss.md) | Reddit after its RSS ends (13 Nov 2026) | decided: no change |
| [0026](0026-feed-finder.md) | Find a site's feed from any page URL | built, on the server (v9.5) |
| [0027](0027-illogicalities.md) | Illogicalities: controls and words that contradict their place | built, on the server (v9.5) |
| [0028](0028-follow-a-page-without-a-feed.md) | Follow a page without a feed: its links and its sitemap | built, on the server (v9.5) |
| [0029](0029-review-fixes.md) | Review fixes: correctness and overengineering in today's work | ★ set built, on the server (v9.5); 7, 11, 14, 15 and the judgement calls open |
| [0030](0030-continue-where-i-stopped.md) | Continue where I stopped: a long post offers to go back to where it was left | built, on the server (v9.5) |
| [0031](0031-save-any-page.md) | Save any page: a bookmarklet and "paste a URL" | built, on the server (v9.5) |
| [0032](0032-reading-fidelity.md) | Reading fidelity: know when INSIGHT reads a page worse than the site shows it | built, on the server (v9.5) (steps 1-2; step 3 measured: not adopted) |
| [0033](0033-continuous-reading-design.md) | Continuous reading: one calm column of separate articles | built, on the server (v9.5) |
| [0034](0034-one-reading-density.md) | One reading density: the compact choice goes | built, on the server (v9.5) (frontend only) |
| [0035](0035-add-many-sources.md) | Add many sources at once: a paste box and OPML | built, on the server (v9.5) |
| [0036](0036-source-doctor.md) | Source doctor: a broken source finds its replacement | built, on the server (v9.5) |
| [0037](0037-full-arxiv-papers.md) | Full arXiv papers, from their HTML version | future |
| [0038](0038-pdf-text.md) | Reading the PDFs posts link to | future |
| [0039](0039-page-change-watching.md) | Watching pages for changes (Gwern first) | built, on the server (v9.5) |
| [0040](0040-search.md) | Search across every post | built, on the server (v9.5) |
| [0041](0041-follow-the-sites-blog.md) | Paste a homepage, follow its blog | built, on the server (v9.5) |
| [0042](0042-reader-keeps-structure.md) | The reader keeps tables, figures and captions | built, on the server (v9.5) |
| [0043](0043-gwern-reader-cleanup.md) | The Gwern reader reads only Gwern's writing | built, on the server (v9.5) |
| [0044](0044-conditional-fetching.md) | Conditional fetching: an unchanged feed costs nothing | built, on the server (v9.5) |
| [0045](0045-reading-settings.md) | Reading settings: font, size and width | built, on the server (v9.5) |
| [0046](0046-source-hygiene.md) | Source hygiene: quiet and never-opened sources | built, on the server (v9.5) |
| [0047](0047-blog-under-another-name.md) | Find a site's blog when it isn't called "Blog" | built, on the server (v9.5) |
| [0048](0048-gwern-noise-cleanup.md) | Remove the Gwern posts that aren't Gwern's writing | built, on the server (v9.5) |
| [0049](0049-one-post-one-address.md) | One post, one address: a post is never saved twice under another form of its URL | built, not deployed (v9.6) |
| [0050](0050-one-story-many-sources.md) | One story, many sources: the links inside posts, story groups, "covered by", and Discover | built, not deployed (v9.7) |
| [0051](0051-news-and-classics.md) | News and Classics: what many of my sources cover now, and what they keep citing | built, not deployed (v9.7) |
| [0052](0052-what-i-read.md) | What I read: find again a post I read yesterday | built, not deployed (v9.6) |
| [0053](0053-reader-gaps.md) | Reader gaps: pages built from tables, code in figures, and the gaps nobody has listed yet | built, not deployed (v9.6) |
| [0054](0054-source-anatomy.md) | Source anatomy: how each source is read, and what it gives | built, not deployed (v9.6) |
| [0055](0055-covered-by-on-the-post.md) | "Covered by" on the post page, not only in the feed | built, not deployed (v9.8) |
| [0056](0056-search-finds-stories.md) | Search finds stories: version names, folded results, News and Classics | built, not deployed (v9.8) |
| [0057](0057-links-stay-in-insight.md) | A link to a post you already have opens it in INSIGHT | built, not deployed (v9.8) |
| [0058](0058-known-news-is-not-new.md) | A page your sources linked before is not "new to you" | built, not deployed (v9.8) |
| [0059](0059-classics-discussion.md) | Classics: what's wrong with them (to discuss) | discussion |
| [0060](0060-follow-where-your-links-point.md) | Follow a site where your sources' links point | built, not deployed (v9.8) |
| [0061](0061-smooth-loading.md) | Smooth loading: no broken tab after a deploy, no wait on the first post, a budget that measures what you wait for | built, not deployed (v9.8) |
| [0062](0062-what-the-pipeline-review-found.md) | What the pipeline review found: same address, teasers retried, a shorter update, Discover in the database, background work you can see | built, not deployed (v9.9) |
| [0063](0063-saved-pages-keep-their-date.md) | Saved pages keep their own date, and link labels stay out of the text | built, not deployed (v9.9) |
| [0064](0064-stories-as-trees.md) | Stories as trees: each post knows where it came from | built, not deployed (v9.9) |
| [0065](0065-discover-the-sources-your-stories-start-from.md) | Discover suggests the sources your stories start from | built, not deployed (v9.9) |
| [0066](0066-x-reposts-quotes-and-threads.md) | X: reposts, quotes and threads become connections | built, not deployed (v9.9) |
| [0067](0067-discover-clean-less-noise.md) | Discover: cleaner, less noise (a roundup weighs half in the order; languages and mirrors aren't sites) | built, not deployed (v9.9) |
| [0068](0068-reading-v9.9-gaps.md) | What reading v9.9 would show: threads, roundups, reposts, origin titles, phones, labels, shared blog hosts | built, not deployed (v9.10) |
| [0069](0069-v9.11-deploy-reading-voices.md) | v9.11: a deploy that finishes, text that reads, one voice per publication | built, not deployed (v9.11) |
| [0070](0070-v9.12-names-joins-reading.md) | v9.12: names that surge, joins that hold, rows that read right | spec (v9.12); A, B and C built, not deployed (A9 measured, not built) |
| [0071](0071-v9.13-safe-data-simpler-code.md) | v9.13: your sources can't be lost, versions keep themselves, one rule for each thing | built, not deployed (v9.13) |
| [0072](0072-v9.14-light-api-rows-that-read.md) | v9.14: a light API, rows that read right, a doctor that checks | spec (v9.14); A (memory), B, C, D1–D4 built, not deployed; A (incremental job, stored connections, date-only starts) to do |
| [0073](0073-phone-rows-full-width.md) | Phones: the title gets the row's full width | built, not deployed |
| [0074](0074-a-post-in-several-stories.md) | A post in several stories: membership is an edge, not glue | spec (draft); after the incremental job |
| [0075](0075-realdata-checks.md) | Real-data checks on every change: the cases run, the rules hold on every post, every change shows its diff | built (v9.15), not merged |
| [0076](0076-post-read-once.md) | A post is read once, when it is saved: one stored structure every page and the story job read | built, not merged (v9.16) |
| [0077](0077-news-longer-kept-and-on-sources.md) | News: a longer view, every row kept, News and Classics on a source's page | spec (v9.16) |
| [0078](0078-channels-one-source-per-voice.md) | Channels: one source for one company, person or blog, made of its channels | on hold (owner) |
| [0079](0079-export-everything-from-the-web.md) | Export everything from the web: one click for a full database dump (and the sources list) | spec, decided (after 0080) |
| [0080](0080-discover-that-reads-well.md) | Discover that reads well: tested suggestions, real names and titles, owners not platforms | spec, decided (v9.17) |
| [0081](0081-reading-walled-and-feedless-sites.md) | Reading walled and feedless sites: more places to look, a real browser when needed, headlines when that is all | on hold (owner) |
| [0082](0082-v9.16-labels-that-match.md) | v9.16 first slice: a story's count names what it counts; "Started it" only when it was first | built, not merged (v9.16) |
| [0083](0083-v9.16-news-names-and-leads.md) | v9.16 News: a name said inside a joined word joins its burst; a roundup never leads a row; a post page says "In News" | 1 merged (v9.16); 2 (a roundup never leads) and 3 (a post page names its News row) built, not merged |
| [0084](0084-substack-cookie-per-publication-and-linked-past-posts.md) | Substack: the cookie only where you pay (bug); a source's own older posts its posts link | spec (v9.16) |
| [0085](0085-discussions-hn-and-reddit.md) | Discussions: Hacker News and Reddit comments on the post page, one design, no login | spec (v9.17) |
| [0088](0088-v9.16-backoff-health-and-rail-order.md) | v9.16: a wait that fits the error (a 5xx retries within hours), health that names the site, the rail's newest unread first | built, not merged (v9.16) |
| [0089](0089-shared-link-window-from-the-first-link.md) | A shared link's 72 hours count from the page's first-ever link: measured, not adopted (waits for the same-story labels) | measured |

## Analysis archive

Issue 0005 removes the analysis version from `main`. The git tag `mark-ix-analysis-archive`
marks the last commit that still holds it (briefings, Gemini, topics, entity/event memory,
stories, inbox, experts, milestones, the track briefing). It is created when that removal
lands. Read old code with `git show mark-ix-analysis-archive:<path>`. Issues 0001 and 0002
list the files to look at. The finished analysis plans are in `plan/archive/`.

## Ideas, not issues yet

Still open from the old backend `FUTURES.md` (the rest is built or obsolete):

- Post versioning: keep a post's earlier text when its source edits it.
- Retention: none. INSIGHT keeps every post and everything derived from it (News, stories, Classics); owner, 2026-11-04: "keep everything is priority". Only operational logs (job_runs, 30 days) are pruned.
