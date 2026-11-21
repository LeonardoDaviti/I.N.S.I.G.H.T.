# 0276 — Authors in Discover: the people and makers behind what your tracks and News care about

Status: **built** (Stealth v10.33, 2026-11-21). Follows 0101 ("attribution", "coverage gaps by entity"), after 0262
closed Reddit to INSIGHT: practitioners' value now has to come from following the people and makers directly.

## What
`markx/discover_people.py` builds the list. The jobs process's "discover" view keeps it
(`services/discover_reads.keep_people`, at most once an hour, KEEP_FOR), and `GET /api/discover/people?limit=30` serves
the kept list with `built_at` and `refreshing`. A missing or old list marks the job wanted. Discover shows it as the
section "People and makers your tracks quote" (`frontend/src/components/sources/PeopleAndMakers.tsx`).
- **Posts read** (30 days):
  - each topic track's own posts, placed in the track or joined (`track_feed.track_posts`, the track's reading view);
    a post in the track's Discover is not counted;
  - the posts of News rows first seen in the window (news_posts).
- **Authors (a)**: accounts these posts quote, repost, @mention or link. That covers X, Bluesky, Telegram, YouTube and
  `medium.com/@user`-style accounts, code-host owners from linked repositories, and model-hub orgs. They are keyed with
  the scout's key (`scout.key_of`).
- **Makers (b)**: the current maker (entity_facts) of each entity the posts name. Each maker comes with the channels
  the official-channels module already found for it (`official.book`).
- **Ranking**: by the distinct posts that brought the candidate, then by how many tracks it appears in. A candidate
  needs **3+ posts, or 2+ posts from 2+ sources**, and carries its 5 newest posts as evidence.
- **People**: an account belongs to a person only when the handles module says so (the owner's yes in
  mx_entity_handles). That module never takes a handle from a name, and never treats the same handle on another
  platform as the same person (handles.py).
  - Such accounts fold into one row (`person:<id>`).
  - A person you follow under any account or site is left out: a yes handle that is a followed source's account, a
    source the owner said is theirs (mx_entity_sources), or a live voice of theirs.
- **Left out**:
  - anything you follow or hid in Discover;
  - Reddit, Hacker News, plain sites, and a site's sections;
  - search feeds, code-host pages that have no owner, and YouTube pages that are not a channel;
  - a maker whose own channel you already follow.
- **Follow…** opens Add source on the row's address (the feed finder, then page watching), as every add does. An X or
  Telegram account goes through its bridge, and `ready` is false when the bridge is not set. A maker uses its first
  official channel; a maker with no channel found has no Follow button.
- **Suggestions only.** Nothing is added. Makers' channels stay with the official module.

## Measured (2026-11-21)
**Production, GET only** (people-2.json): 878 posts (in-track posts from each track's feed, plus News leads), 4,940
hits.
- **Authors kept: 14 of 26 wanted (54%).** Only 26 rows passed the floor.
  - Wanted: ggml-org, unsloth, ista-daslab, qwen and earendil-works, plus code owners of local-inference tools
    (tandem.cpp, Basalt, gpu-unlock, benchmarks) and one X practitioner.
  - Unwanted: mostly owners from one Habr or Telegram source with 3 posts, two keys of one project, and simonw.
- **Rows from 2+ sources: 7 of 8 wanted.** The only miss is gh/simonw. That form of the floor is the better rule on
  this data. It is not adopted yet: 8 rows are too few to set it.
- **Track posts fixed**: Anthropic and OpenAI are no longer listed under "Cool 3D Projects". Alibaba, AMD, Espressif,
  Raspberry Pi, Seeed Studio and Autodesk remain, from posts that sit in that track too.
- **Followed person under another key**: gh/simonw stays, and so do gh/hemanth and hf/gnumanth (two keys).
  Production's handles module has no confirmed handle for either person: Simon Willison's entity has `handles.known`
  empty, and his site and X account are only *proposed* as his. By the handles rule, the same handle on GitHub is not
  his. The fold and the skip are built and tested, and they act once the owner confirms the handles.
- **Bug found and fixed after the run**: two section keys of a news site were listed as people
  (word `account`). Only `@user` accounts are kept now.

**Server copy** (insight_srv1119_check_a, the product SQL path, read-only; 162k posts):
- 2,056 window posts and 5,872 hits; 60 authors and 5 makers.
- One build took 0.98–1.06 s with 171–178 MB peak RSS. That is over 300 ms, hence the kept list.
- There, News posts dominate. Round-up posts (a weekly AI digest, AINews) quote dozens of X accounts, and those
  accounts lead the list: andrewcurran_, peterwildeford, tszzl, semianalysis_.

## Next
1. Decide the floor: require 2+ sources (7 of 8 here) against today's "3+ posts or 2+ sources", once a larger window
   gives more rows.
2. Weigh round-up posts half, as Discover does (units.py's round-up tag), so a digest's 20 quotes count less.
3. Bylines of linked articles. Linked pages keep no author today, so this needs the linked fetch to store one.
