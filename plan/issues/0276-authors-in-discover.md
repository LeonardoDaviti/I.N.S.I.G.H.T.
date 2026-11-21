# 0276 — Authors in Discover: the people and makers behind what your tracks and News care about

Status: **built, first slice** (Stealth v10.33, 2026-11-21). Follows 0101 ("attribution", "coverage gaps by entity"),
after 0262 closed Reddit to INSIGHT: practitioners' value now has to come from following the people and makers directly.

## What
`markx/discover_people.py`, served at `GET /api/discover/people?limit=30&days=30` (routers/discover_main_source.py).
- **Posts read**: each topic track's in and ✓ posts of 30 days (scout.in_posts), plus the posts of News rows first seen
  in the window (news_posts).
- **Authors (a)**: accounts these posts quote, repost, @mention or link. That covers X, Bluesky, Telegram and YouTube
  accounts (a quote or retweet is a link to the author's tweet), code-host owners from linked repositories, and
  model-hub orgs. They are keyed with the scout's key (scout.key_of), so a key here matches a key in the track scout.
- **Makers (b)**: the current maker (entity_facts) of each entity the posts name. Each maker comes with the channels
  the official-channels module already found for it (official.book). This module runs no new search.
- **Ranking**: by the distinct posts that brought the candidate (a track post or a News post), then by how many tracks
  it appears in. A candidate needs at least 2 posts, and each one carries its 5 newest posts as evidence.
- **Left out**:
  - anything you follow (scout.Followed);
  - anything you hid in Discover;
  - Reddit, Hacker News, and plain sites (those are Discover's main list);
  - search feeds, code-host pages that have no owner, and YouTube pages that are not a channel;
  - a maker whose own channel you already follow.
- **Follow**: each author carries the address that Follow sends through the add path (the feed finder, then page
  watching). An X or Telegram account goes through its bridge (feed_finder.bridge_feed), and `ready` is false when the
  bridge is not set. A code owner's `.atom` feed is the finder's first try, then page watching. No candidate is
  dropped for having no feed.
- **Suggestions only**. Nothing is added here. Makers' official channels stay with the official module
  (INSIGHT_OFFICIAL). The 2026-11-13 "discovered → judged → auto-added" pipeline is not wired for people: that is a
  later slice, once its bar is measured.

## Measured (production, GET only, 2026-11-21)
Data: 545 posts (in-track posts of 30 days, plus 99 News leads), 2,796 hits. Rows are in
plan/research/v1033-people/ (private).
- **Top 30 authors: 18 of 30 wanted (60%)**:
  - the wanted ones are makers' and labs' code or hub orgs and a few X practitioners;
  - 12 are unwanted, mostly owners of one-off projects named in 2 Habr or Telegram posts;
  - every one of the 30 has a followable shape: X through the bridge, a code owner's feed or page, a hub org's page
    watched. Nothing was test-read.
- **Duplicates**: the same maker shows under two keys (an X account and a hub org; a code owner and a hub org for one
  person). Folding them belongs in voices (0132), not here.
- **Code Mode practitioner case**: an X practitioner who posts hands-on coding-agent tests surfaced at rank 30, from 2
  posts (both retweets by a followed account). The signal for X people is thin: few X posts quote or retweet accounts
  you don't already follow.
- **Makers**: 85 makers, led by the big labs at 34–103 posts each, and those are already followed. The GET run could
  not drop makers whose channel is followed. `suggestions()` does that, but it has not been checked on production.

## Next
1. A floor for one-off owners: 3 or more posts, or posts from 2 or more sources, and measure again.
2. Fold the same maker's keys through voices or entity addresses.
3. Bylines of linked articles. Linked pages keep no author today, so this needs the linked fetch to store one.
4. A frontend section in Discover.
5. Measure on the read-only server copy (product SQL path) and time the request.
