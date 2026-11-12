# 0172 — Discover: correctness and speed (spec + built)

INSIGHT v10.15, part F. Evidence: plan/research/discover-2026-11-12 (REPORT.md, adds.md, adds2.md: the review's exact
rows; private, gitignored). Names below are invented. Every fix is a class, never a site.

## The problems

- **Speed (c1).** Discover's saved list was keyed on the newest `sources.updated_at`. Every fetch merges settings into
  its source's row and moves it, and Discover's own background reads moved their row's timestamp, so nearly every open
  made the list again: 255–300 s on the server, 504s at the proxy's 300 s.
- **Follow paths.** "Other channels" rows had no Follow (c2). The Pages tab followed the bare domain (`https://<site>`;
  a tweet: the platform's home) (c3). An X account filled the bridge URL client-side and skipped the finder (c4).
- **Suggestion quality.** Old or moved domains of a followed site came back as new (b1). "Other channels" credited a
  site to a source by one word shared with its name: a newspaper's science section to "<x> Science Digest", a
  country's portal to "<country> Talk" (b2). Non-channels were suggested: model listings, paper forums, interactive
  pages told by their query, platforms with no reader, model-hub orgs and code-host orgs with no feed (b3). Rows none
  of your sources link ("the original of N things") ranked above linked ones (b4). A site that can't be followed hid
  its X account that can (b5). A follow test that failed for a passing reason (a bridge's 5xx) held for 30 days (b6).
  The home page's finder said none while a section of the site's own linked pages had a feed (b7). A link blog's
  archive row listed the pages it links as its own (b8). One site's hosts were split into several cards (b9).
- **Page watch.** A year (or year/month) as the prefix (c5); www and the bare host as two articles (c6); form/apply
  pages stored as posts (c7); the site name kept on titles ("… | Blog", "… - <Site> Blog") (c8); a pagination page
  offered as a section (c10); a new page watch's newest article read by the preview but never stored ("0 new of 1").

## Built (Stealth v10.15, branch `v1015-discover-fixes`)

### Speed (c1)
- `StoriesRepository.discover_inputs` keys the list on what changes Discover's answer: the story run's `discover_at`
  (new posts and links), each source's id, platform, address, display name, enabled state and voice (an md5 of them,
  never `updated_at`), the voices, the hidden keys, and Discover's reads (only when it read something).
- The API serves the last answer built (`StoriesService.discover_served`, system_settings `discover_served`:
  `{made_from, built_at, answer}`), never building on the request. An answer due again (its inputs or code changed,
  or REFRESH_AFTER = 30 min old: Mark X's originals rows move between story runs) is rebuilt in the background
  (`discover_reads.start(refresh=True)`, one run at a time, even with reads off); after every story run the story
  process builds it (`keep_discover` → `refresh`), and after Discover's reads. Before the first build of this version
  the list an older version kept is served (else an empty one), due. The response says `built_at` and `refreshing`;
  the page shows "Updated 12m ago · updating…" and asks again each minute while a build is under way.
- Measured on a local copy (insight_v1015_seed: 49,384 posts, 256 sources, Mark X data), the list's build: 0.8–0.9 s
  with Discover's counts kept, 7.1–7.6 s when they are counted again (before and after alike: the counts' SQL,
  `platforms` 1.9 s, `mirrors` 1.5 s, `counts` 0.9 s, page titles' evidence 2.4 s). An open after a fetch's settings
  write: 0.66–0.72 s before (the list made again), 0.03 s after (the kept answer read). The server's 255–300 s was not
  reproduced on any local copy (its data is ~3× larger: 155k posts, a 159 s story run): no single step grows past
  linear here. What the server had that these copies don't: three builders at once (the open, Discover's reads,
  which made the list before and after reading, and the story process's keep), each a full build whenever the key
  moved, beside story runs on the same database. None of them is on the request now.

### Follow everywhere through the finder
- c2: each "Other channels" row has Follow (Add source on its address: the finder decides).
- c3: each Pages row (and entity page row) carries `follow_url` (`discover_rules.follow_url`): a tweet's or a platform
  page's account, else the page's section (its first path segment, never a year), else the site's home; a page naming
  no account has no Follow. The frontend falls back to the same when the server sends none.
- c4: an X address, typed or from Discover, goes to `POST /api/sources/find-feed` like any address; the source added
  is the feed the finder returns (the bridge's), never a bridge URL built in the client.

### Suggestion quality
- b1: the follow test records where the address landed (`where_linked.follow` → `landed`); a suggestion whose test
  landed on a site you follow (`moved_to`) is that source's, listed under its other channels, never new.
- b2: other channels by a real relation (`discover_rules.channel_names`, `other_channel`): the source's own addresses'
  names (its account's, its site's word; a key's word equal, starting or ending with one), its whole name (its words
  run together), and, only for an account on a platform a source kind reads (X, Telegram, Reddit, YouTube), a word of
  its display name. A site's or a section's word shared with a word of the name is no relation. Measured on the local
  copy's 26 other channels: 3 become suggestions again — a cloud company's blog credited by "Cloud" (wrong before), a
  company's developer blog credited to "News from <company>" by its one word (another channel of the company, not of
  that source: one the owner wants to add), and a renamed blog's old domain credited by a word of its new name (right
  before: lost until its follow test lands on the new site, b1); 4 more leave as non-channels (b3: two model-hub orgs,
  two code-host orgs without a feed). The other 19 stay.
- b3 (`discover_rules.place_kind`, `not_channel`): an interactive page told by its query (one path segment at most, a
  query naming the page; a publication's section is not one: its account may be offered, b5), a catalogue's entry
  (LISTING_PATH: /models/<x>, /library/<x>, /leaderboard/<x>), a model hub's owner (entity_originals.MODEL_HUBS), and an
  owner on a platform no source kind reads whose follow test found nothing (a code host's org without a feed, a network
  without a reader). Local copy: 30 of 1,261 suggestions leave (28 model-hub orgs, a code host's org its test called
  headlines, a notes app's shared pages told by their query); 3 come back from other channels (b2).
- b4: `discover_rules.order` puts a row none of your sources link after every linked one of its section.
- b5: a site that can't be followed is read once for the accounts it links ("follow us"), those a source kind reads
  (`declared_accounts`); the first whose kind answers with posts is offered (`account: {url, label}`): "Follow @acme…".
- b6: a test that failed for a passing reason (a bridge's error, a 5xx, a 429, a timeout) is stored `transient` and
  asked again after TRANSIENT_HOURS = 6, not CHECK_DAYS. FOLLOW_TEST = 4: every test is made again once by these rules.
- b7: when the home page gives nothing, the test tries the sections the suggestion's own linked pages sit in (the two
  with the most), and a followable one becomes the suggestion's address.
- b8: an archive row holds the source's own pages only (`_own_page`: its account's on a platform, else on its site).
- b9: Mark X's originals and long-read rows join the card of their owner domain as a place, never a card of their own.

### Page watch
- c5: `page_watch.stable_prefix`: an inferred (or given) prefix is cut at its first year segment (/2026/ → /,
  /blog/2026/11/ → /blog/).
- c6: discovery dedupes on `normalize_url`; storing asks for the www/bare twin too.
- c7: a page whose last segment is an action (apply, register, login, subscribe, rsvp, waitlist, …) is never read; a
  page whose body is a form of 4+ fields with under 1,500 characters of text is never a post.
- c8: `site_suffixes` learns the trailing segment after a separator (| - – — / · \) seen on 2+ titles and half of a
  section's titles (the listing page's own title counts as one) and strips it, in the preview, the fetch and the archive.
- c10: `pagination_page` (/page/<n>, ?page=<n>, "(Page N)") is never offered as a section nor read as an article.
- "0 new of 1": the page was held by Saved (collected four days before the source was added) and a new source can't
  take it back on its first fetch: `_saved_copy` moved a Saved row only when `page_source` named this source, which it
  learns from the source's stored posts (none yet). Now issue 0167's rule decides when `page_source` knows nothing
  (`_owns_page`), and a page watch reads a URL held elsewhere when its save would take it back (`kept_urls`). The
  second case (a blog's tenth article never stored) was a page whose only date sat in its byline among five dates:
  `byline_date` reads the date written right after a page's one `<h1>`.

## Tests

- backend/insight_core/tests/test_discover_fixes_0172.py (c1 inputs and serving, b1–b7, c3), test_page_watch_0172.py
  (c5–c8, c10, the 0-new case and the byline date); test_feed_finder's route body has `landed`.
- frontend: suggestedSources.test.tsx (built line, refetch while building), discoverPages.test.tsx (follow_url and its
  fallback), SourcesConfig.test.tsx (X through the finder, Follow on other channels and on a declared account),
  discover.test.ts, platformAccount.test.ts.

## Left

- The server's 4-minute build itself was not reproduced locally (see Speed); with it off the request, an open no
  longer waits on it. Measure the background build's time in the server's log after deploy.
- b1 catches a moved domain only by its follow test's redirect (a first-page suggestion, tested); an old domain that
  no longer answers, or answers with an archive of its own, stays a suggestion.
- c7's form threshold (4 fields, 1,500 characters) and c8's suffix rule are checked on fixtures only.
