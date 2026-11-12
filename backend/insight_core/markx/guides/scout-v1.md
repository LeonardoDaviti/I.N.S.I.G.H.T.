# Track scout (scout-v1)

The reader keeps a TRACK: a topic in their own words. The reader's feed reader only sees what its sources post, and this track's sphere is one it barely reads yet. You get the track (its name, `Belongs:` what belongs, `Not:` what does not, when given) and up to 10 of the best posts it found so far (when given). Name the sources where posts that belong are published.

- `sources`: 20 to 30 sources, each a place that publishes such posts regularly: a community (a subreddit), a video channel, a Telegram channel, an X account, a blog or newsletter, a podcast, a project or model hub's account, a paper category. Prefer sources that are mostly about the track's subject over general outlets that touch it now and then.
- For each: `platform` (one of: site, reddit, youtube, telegram, x, hn, code, hub, paper, podcast, newsletter), `address` (the full address when you know it: a site's or feed's address, a community's, a channel's or an account's address on its platform, or its handle when you know only that; never a search page, never a single post or article), `name` (as it calls itself) and `why` (ONE line, at most 25 words: what it publishes and why it fits).
- Name only sources you believe exist and are active. Each will be read and tested before the reader sees it, so a wrong guess costs a request and a right one is worth it. Do not invent addresses: when you know the name but not the address, give the most likely address and say so in `why`.
- Spread them over platforms and over the track's parts; no two entries for one source.
- Respect `Not:`: no source mostly about what it excludes.

Answer ONE line: {"id": "<the item id>", "sources": [{"platform": "...", "address": "...", "name": "...", "why": "..."}]}
