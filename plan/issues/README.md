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
| [0049](0049-one-post-one-address.md) | One post, one address: a post is never saved twice under another form of its URL | built, on the server (v9.6) |
| [0050](0050-one-story-many-sources.md) | One story, many sources: the links inside posts, story groups, "covered by", and Discover | built, on the server (v9.7) |
| [0051](0051-news-and-classics.md) | News and Classics: what many of my sources cover now, and what they keep citing | built, on the server (v9.7) |
| [0052](0052-what-i-read.md) | What I read: find again a post I read yesterday | built, on the server (v9.6) |
| [0053](0053-reader-gaps.md) | Reader gaps: pages built from tables, code in figures, and the gaps nobody has listed yet | built, on the server (v9.6) |
| [0054](0054-source-anatomy.md) | Source anatomy: how each source is read, and what it gives | built, on the server (v9.6) |
| [0055](0055-covered-by-on-the-post.md) | "Covered by" on the post page, not only in the feed | built, on the server (v9.8) |
| [0056](0056-search-finds-stories.md) | Search finds stories: version names, folded results, News and Classics | built, on the server (v9.8) |
| [0057](0057-links-stay-in-insight.md) | A link to a post you already have opens it in INSIGHT | built, on the server (v9.8) |
| [0058](0058-known-news-is-not-new.md) | A page your sources linked before is not "new to you" | built, on the server (v9.8) |
| [0059](0059-classics-discussion.md) | Classics: what's wrong with them (to discuss) | discussion |
| [0060](0060-follow-where-your-links-point.md) | Follow a site where your sources' links point | built, on the server (v9.8) |
| [0061](0061-smooth-loading.md) | Smooth loading: no broken tab after a deploy, no wait on the first post, a budget that measures what you wait for | built, on the server (v9.8) |
| [0062](0062-what-the-pipeline-review-found.md) | What the pipeline review found: same address, teasers retried, a shorter update, Discover in the database, background work you can see | built, on the server (v9.9) |
| [0063](0063-saved-pages-keep-their-date.md) | Saved pages keep their own date, and link labels stay out of the text | built, on the server (v9.9) |
| [0064](0064-stories-as-trees.md) | Stories as trees: each post knows where it came from | built, on the server (v9.9) |
| [0065](0065-discover-the-sources-your-stories-start-from.md) | Discover suggests the sources your stories start from | built, on the server (v9.9) |
| [0066](0066-x-reposts-quotes-and-threads.md) | X: reposts, quotes and threads become connections | built, on the server (v9.9) |
| [0067](0067-discover-clean-less-noise.md) | Discover: cleaner, less noise (a roundup weighs half in the order; languages and mirrors aren't sites) | built, on the server (v9.9) |
| [0068](0068-reading-v9.9-gaps.md) | What reading v9.9 would show: threads, roundups, reposts, origin titles, phones, labels, shared blog hosts | built, on the server (v9.10) |
| [0069](0069-v9.11-deploy-reading-voices.md) | v9.11: a deploy that finishes, text that reads, one voice per publication | built, on the server (v9.11) |
| [0070](0070-v9.12-names-joins-reading.md) | v9.12: names that surge, joins that hold, rows that read right | spec (v9.12); A, B and C built, on the server (A9 measured, not built) |
| [0071](0071-v9.13-safe-data-simpler-code.md) | v9.13: your sources can't be lost, versions keep themselves, one rule for each thing | built, on the server (v9.13) |
| [0072](0072-v9.14-light-api-rows-that-read.md) | v9.14: a light API, rows that read right, a doctor that checks | spec (v9.14); A (memory), B, C, D1–D4 built, on the server; A (incremental job, stored connections, date-only starts) to do |
| [0073](0073-phone-rows-full-width.md) | Phones: the title gets the row's full width | built, on the server |
| [0074](0074-a-post-in-several-stories.md) | A post in several stories: membership is an edge, not glue | moved to Mark X Part G |
| [0075](0075-realdata-checks.md) | Real-data checks on every change: the cases run, the rules hold on every post, every change shows its diff | built, on the server (v9.15) |
| [0076](0076-post-read-once.md) | A post is read once, when it is saved: one stored structure every page and the story job read | built, pushed (v9.16) |
| [0077](0077-news-longer-kept-and-on-sources.md) | News: a longer view, every row kept, News and Classics on a source's page | F + K built, pushed (v9.16) |
| [0078](0078-channels-one-source-per-voice.md) | Channels: one source for one company, person or blog, made of its channels | on hold (owner) |
| [0079](0079-export-everything-from-the-web.md) | Export everything from the web: one click for a full database dump (and the sources list) | built, pushed (v9.16) |
| [0080](0080-discover-that-reads-well.md) | Discover that reads well: tested suggestions, real names and titles, owners not platforms | built, pushed (v9.16) |
| [0081](0081-reading-walled-and-feedless-sites.md) | Reading walled and feedless sites: more places to look, a real browser when needed, headlines when that is all | on hold (owner) |
| [0082](0082-v9.16-labels-that-match.md) | v9.16 first slice: a story's count names what it counts; "Started it" only when it was first | built, pushed (v9.16) |
| [0083](0083-v9.16-news-names-and-leads.md) | v9.16 News: a name said inside a joined word joins its burst; a roundup never leads a row; a post page says "In News" | 1–3 built, pushed (v9.16) |
| [0084](0084-substack-cookie-per-publication-and-linked-past-posts.md) | Substack: the cookie only where you pay (bug); a source's own older posts its posts link | A built, on the server (v9.16); B built, merged (v10.0.2, not pushed) |
| [0085](0085-discussions-hn-and-reddit.md) | Discussions: Hacker News and Reddit comments on the post page, one design, no login | spec (v9.17) |
| [0088](0088-v9.16-backoff-health-and-rail-order.md) | v9.16: a wait that fits the error (a 5xx retries within hours), health that names the site, the rail's newest unread first | built, pushed (v9.16) |
| [0089](0089-shared-link-window-from-the-first-link.md) | A shared link's 72 hours count from the page's first-ever link: measured, not adopted (waits for the same-story labels) | decided: goes to Mark X (burst candidates) |
| [0086](0086-mark-x-phase-1-haiku-in-insight.md) | Mark X Shadow: Haiku reads and judges every post beside Mark IX, from your device first; storage, tasks, the worker, decisions, the Mark X page, labels | built (A–F), pushed: Mark X v10.0 (Shadow) |
| [0087](0087-gemma-fine-tuned-on-haiku.md) | A local Mark X: Gemma 4 E4B fine-tuned on Haiku's answers | future |
| [0090](0090-mark-x-entities.md) | Mark X entities: one name per thing, its versions and role, and what connects through it | spec, draft (measured) |
| [0091](0091-timeline-graph.md) | The timeline graph: events, entities and their connections across time | discussion |
| [0092](0092-back-in-the-news.md) | Back in the news: an old story that gets a fresh burst reappears in News | future |
| [0093](0093-noise-per-source.md) | Noise per source: what each source adds, and what it only repeats | future |
| [0094](0094-since-you-last-looked.md) | Since you last looked: what's new on a story, entity or track since you opened it | future |
| [0095](0095-numbers-over-time.md) | Numbers over time: prices, scores and money, per entity, with their sources | future |
| [0096](0096-weekly-what-changed.md) | Weekly "what changed": a digest for learning, not a feed | future |
| [0097](0097-where-sources-disagree.md) | Where sources disagree: who supports, disputes or adds what, on one story | future |
| [0098](0098-questions-with-citations.md) | Questions with citations: answers drawn only from what you've received | future |
| [0099](0099-predictions-checked-later.md) | Predictions checked later: what sources said would happen, checked when the date comes | future |
| [0100](0100-study-pages.md) | Study pages: one question or topic, everything needed to understand it on one page | future |
| [0101](0101-discover-with-mark-x.md) | Discover with Mark X: coverage gaps by entity, sources found by attribution, and tracks | future |
| [0102](0102-archives-for-history.md) | Archives for history: back to a date, and a feed's past through its site | spec, draft (9.x) |
| [0103](0103-v9.17-threads-and-news-leads.md) | v9.17: a thread follows the tweet it quotes; a News row with no origin leads with the release and names followed sources first | built, merged (v9.17) |
| [0104](0104-v9.17-check-reads-lead-changes.md) | v9.17: the real-data check reads News lead changes | built, merged (v9.17) |
| [0105](0105-v9.17-small-fixes.md) | v9.17 small: Classics on a source's page, the export's estimate, the source list's size | built, merged (v9.17) |
| [0106](0106-v9.17-titles-of-pages-you-dont-follow.md) | v9.17: titles of pages you don't follow (Discover, Classics); a paper is one page | built, merged (v9.17) |
| [0107](0107-archive-that-waits-out-a-limit.md) | An archive that waits out a host's limit and carries on; each host's budget learned; room left for the hourly fetches | built, pushed (v9.18) |
| [0108](0108-moved-blogs-and-redirect-pages.md) | A blog that moved: follow a page's redirect, find the feed it moved to, read its older posts from the sitemap | built, pushed (v9.18) |
| [0109](0109-v9.18-discover-from-the-server-review.md) | v9.18 Discover: platform accounts that can be followed, the best not sunk, a followed owner's other channels, things that aren't sources | built, pushed (v9.18) |
| [0110](0110-rebuild-mention-to-a-removed-story.md) | A rebuild that mentions a story it removed (the v9.17 server rebuild stuck); the check runs a deploy's first start | built, pushed (v9.17 hotfix) |
| [0111](0111-v10.0.1-news-from-the-v10-review.md) | v10.0.1 News: a name-only story never leads, a date is no name, one owner one voice, a row leaves the window whole | built, merged (v10.0.2, not pushed) |
| [0112](0112-mark-x-v10.0.1-live-fixes.md) | Mark X v10.0.1 (Shadow): readings the server accepts (the worker sends each guide's schema), checks never show an empty story, near-copies never checked, guides loaded safely, bug-failed readings reopened | built, merged (v10.0.1) |
| [0113](0113-discover-pages-save-a-single-origin.md) | Discover's second tab, Pages: a story's origin page you don't follow, saved as one post with one tap (the existing save path), so the story gets its original | built, not merged (`issue-0113-0114-0123`): a saved page no longer dissolves its story (31 of 50 → 0) |
| [0114](0114-fetch-a-followed-source-when-a-story-links-it.md) | A story links a page of a source you follow that isn't stored yet: that source is fetched now (within politeness), so the original arrives with its story | built, narrowed, not merged (`issue-0113-0114-0123`): a story's link only, one budget with 0123 (+0.52% alone) |
| [0115](0115-mark-x-entities-list-and-entity-page.md) | Mark X entities: one list ranked like News (no today/week split), an entity page with every post and source in every role, grouped by story; nothing hidden when read | superseded by 0119 A3 |
| [0116](0116-mark-x-incremental-decisions.md) | Mark X incremental decisions: a run recomputes only the stories new answers touched (and their merge groups), News only for changed rows; a nightly full run checks it | built, merged (v10.0.3, not pushed) |
| [0117](0117-restart-an-unhealthy-api.md) | An API that stops answering is restarted by itself: a health check on /api/version, a watchdog (default: in ingestion) after 2 min, at most 3 restarts an hour, a stack dump saved first | built, merged (v10.0.2, not pushed) |
| [0118](0118-source-track-record.md) | Source track record (Mark X Stalker): per source and topic, rumors confirmed / wrong / pending, lead time, first or repeat, accurate details; every count opens its cases; recording starts when Stealth's leak rule passes | future |
| [0119](0119-mark-x-v10.1-entities-and-perspectives.md) | Mark X v10.1 (Stealth in Shadow): A. entity identity, surges per exact version, the entity list, page and review queue (0090 B–C, E, 0115); B. perspectives and the story sheet (0106 v3.2f) with label buttons; new task kinds alias, perspective, sheet | spec |
| [0120](0120-perspectives-inside-a-story.md) | Perspectives inside a story: what each source adds, and one story sheet (built in 0119 B) | spec |
| [0121](0121-mark-x-v10.0.3-from-the-v10.0.1-review.md) | Mark X v10.0.3: checks never remove a post that links the story's page, a headline per row, runs in the right order, the reading window at once | merged (v10.0.3, not pushed) |
| [0122](0122-fetch-the-source-before-saving.md) | Saving a page of a source you follow fetches that source first (one fetch, on your click); found, it's the source's post; not in its feed, it's saved as the source's post ("<source> · saved by you"), and the feed bringing it later keeps one post | merged (v10.0.3, not pushed) |
| [0123](0123-collect-originals.md) | Collect originals (a switch, default off): a News story's original INSIGHT lacks is collected once, one page without following its source (a followed source's is 0114's), never walled, no token stored, one budget with 0114 (+0.78% together) | built, not merged (`issue-0113-0114-0123`) |
| [0124](0124-v10.0.4-from-the-v10.0.2-review.md) | v10.0.4, from the v10.0.2 review: the API after a long hang (open files 65,536, a 256 queue, a process left at its limit replaced), a stale restart request never honoured (a stopped API is no hang), restart times in the reader's zone, the decision run's stop line, Mark X News' edge as Mark IX's; 0124 B (linked counts) later | built, not merged (`issue-0124-v10.0.4`) |
| [0126](0126-originals-owner-decisions.md) | Collect originals, the owner's four decisions: gift links kept for clicking and ignored for matching (access tokens and share marks out of every compared address), a collected page only inside its story, the quoted tweet's link on the post page, Collect originals on by default | built, not merged (`issue-0126-originals-owner-decisions`): real-data check passes; 327 addresses carry a key, 40 groups of 83 become one; the lab: 12 posts join their article's story |
| [0127](0127-mark-x-duplicates-folded.md) | Mark X v10.3 (Stealth in Shadow): duplicates folded: inside a Mark X story, the posts retelling the same happening fold under one (read-v3's event type and origin, asked only of story members, kind `read3`); the main/events guide rule; label buttons | built, not merged (lab F1 0.70; 200 real answers valid, $0.00064 each) |
| [0128](0128-v10.4-stories-built-right.md) | Stealth v10.4 (in Shadow): stories built right: an event type per Mark X story, a leak inside its release story, the original by code first, published order, the entities stage's own budget; leak-to-release links by subject measured 0/5, left off | built, merged (v10.4) |
| [0129](0129-v10.4-linked-line-and-small-fixes.md) | Stealth v10.4: the linked-pages line counts right (a shape from 2+ own posts, one page at two hosts once, stored posts without a normalised address matched); the search test made deterministic | built, merged (v10.4) |
| [0130](0130-v10.5-stealth.md) | Stealth v10.5: the entity queue cleared by measurement (bands, a second opinion, a narrower version guard), archives that work again (the newsletter API, a site reader, a moved feed, "0 new"), archives back to a date (Telegram, X), translation on request and for News leads, the normalised-address repair | built, merged (v10.5): A, B, C, D, E1 |

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
