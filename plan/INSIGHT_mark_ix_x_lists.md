# Mark IX (the full reader) and Mark X (analysis): the lists

Written 2026-10-28 from the owner's direction:
- **Two audiences:** a self-hosted "own newspaper" for technical people, and a paid hosted service with predefined sources and tracks for everyone else.
- **Mark IX** is the reader that makes today's RSS readers look incomplete.
- **Mark X** adds analytics, topics and AI on top.

Sources: the issues in `plan/issues/`, `plan/INSIGHT_feature_roadmap.md`, and `plan/INSIGHT_competitors_research.md`.

✓ built and deployed · ◐ built for v9.3 or v9.4 (not deployed) or partial · ○ to do · ⧗ future issue

## Focus (owner, 2026-10-28)
- **The personal product now.** The hosted product waits, and **Mark X waits**: Mark IX first.
- **v9.3** is built, not deployed. **v9.4** is the current release (being integrated): **search** (0040) and following a site's blog from its homepage (0041), the reader keeping tables and figures (0042), the Gwern reader cleanup (0043). **v9.5 = page-change watching (0039), reading settings, source hygiene, conditional fetching (ETag).**
- **Skipped:** highlights, notes, post versions, rules (mute words, auto-read, auto-keep) and tags.
  - Why skip rules: on the server, 41,000 of 41,128 posts are unread (0.3% read). Muting words would barely change that; search (v9.4) and "Show in Main feed: off" for firehose sources do.
  - Why skip tags: tracks, Keep and search already cover them.

## Mark IX, personal product: reading even better

### Sources
- ✓ RSS and Atom, with full text and images, no menus or HTML codes (0008, 0032).
- ✓ The feed finder (0026) and page watching (0028).
- ✓ Site readers, paid Substack, Telegram, YouTube, X through your Nitter.
- ✓ Reddit, until 13 Nov 2026.
- ✓ Hacker News, first version. ✓ GitHub Trending.
- ◐ v9.3:
  - add many at once, with OPML (0035);
  - the source doctor (0036);
  - save any page and the bookmarklet (0031).
- ◐ v9.4:
  - paste a homepage, follow its blog (0041);
  - the Gwern reader reads only Gwern's writing (0043).
- ⧗ Full arXiv papers (0037). ⧗ PDF text (0038).
- ⧗ Hacker News kind with comments (0017). ⧗ Release updates (0024).
- ○ Native Bluesky and Mastodon. ○ Podcasts.
- ○ v9.5: conditional fetching (ETag); it also lowers page watching's load.
- ○ Page-change watching, per source, Gwern first (0039), v9.5.
- Only on a real case: email-in.

### Reading
- ✓ Continuous reading, clean text and images, the discussion link, nothing pointless on screen (0027).
- ◐ v9.3:
  - Read later and Keep (0022);
  - continue where I stopped (0030);
  - calmer continuous reading (0033);
  - one density (0034);
  - the fidelity corpus (0032).
- **◐ v9.4:**
  - **search across everything (0040);**
  - the reader keeps tables, figures and captions (0042).
- ○ Saved searches.
- ○ v9.5: reading settings (font, size, width). ○ Read aloud.
- ✗ Skipped: highlights, notes, post versions.

### Organisation
- ✓ Tracks, the Main feed, Unread / Later / Kept / All, "Show in Main feed".
- ○ v9.5: source hygiene: "dead for 30 days", "never opened", with a prune suggestion.
- ○ "Also discussed on Hacker News or Reddit".
- ✗ Skipped: rules, tags.

### Everywhere you read (personal use)
- ○ An installable PWA with a share sheet; offline reading.
- ○ The Fever or Google Reader API (Reeder, NetNewsWire).
- ○ Notifications (ntfy). ○ Publish a track as RSS.
- ○ Export to Obsidian. ○ Webhooks.

### Running it yourself (self-hosted)
- ✓ The version line, useful logs, the faster `./update`.
- ○ A one-command install, lighter by merging the API and ingestion.
- ○ Optional login, needed once it's reachable beyond Tailscale.

## Hosted product: giving other people access (later)
- Login and accounts.
- A licence for the free self-hosted tier.
- A public read-only mode: title, excerpt and link where full text isn't licensed.
- One instance per customer, with provisioning, billing, backups, limits and monitoring.
- Predefined sources and tracks for non-technical users.
- A translated interface; translation of sources (with Mark X).
- Platform APIs paid per customer (X); Telegram sessions per customer.

## Mark X: analysis on another level (ideas, on hold)

### Added by the owner, 2026-10-28
- **Deduplication** is Mark X: one story across sources and languages.
- **Entity collection, even from skipped posts:** a Hacker News post about Tailscale, skipped in the Main feed, shows up later under *Company: Tailscale* or *Product: Tailscale* (0001 entity pages, filled automatically).
- **"Palantir for news"**, keeping the owner in charge without the noise: collect everything (Mark IX), find anything (search), connect the dots (dedup, entities, first reporter), notice what matters (watchlists, trend spikes, priority), trust it (every claim links to its posts; nothing hidden by a black box).

### Understanding stories
- **Story clustering:** the same news across sources and languages becomes one story, with who reported it first, who followed, and who added something new (0004, the citation graph).
- **Entity pages:** everything about Anthropic, Meta's glasses or a person, with milestones on a timeline (0001).
- **Topics:** automatic tags and topic pages that grow as posts arrive.
- **Trend detection:** "AR waveguides: 3× the usual volume this week".
- **Claims and changes:** what a company said before and what it says now.

### Briefings and answers
- **Track briefings and a daily briefing:** readable, every line linked to its posts (0002).
- **Questions across your library, with citations** (pgvector is installed).
- **Audio briefings.**
- **An MCP server over your reading,** so assistants can use your archive.

### Language
- **Translation:** an English version beside the original Russian or other language, one click apart. The hosted tier needs it.
- **Cross-language deduplication,** so a Russian Telegram post and an English article on the same news are one story.

### Discussion
- **Discussion analysis:** what Hacker News and Reddit threads agree on, argue about or add to an article.

### Personal signals
- **Priority order:** the sources and tracks you read most come first (0013).
- **Discover, for sources and tracks** (owner, 2026-10-28):
  - **Sources:** suggested from your own reading, e.g. "6 of your sources link this blog", forwards in Telegram, quoted X accounts, pages you saved.
  - **Tracks:** suggested from what clusters in your reading, e.g. "you follow 9 sources about AR glasses: make them a track?". Also predefined tracks for the paid tier.
- **Credibility and originality per source:** who breaks news, and who repeats it.

### Under the hood
- **A choice of AI provider:** OpenAI, Anthropic, Gemini, or Ollama for local models.

## Other platforms in the future (feasibility)
| Platform | Way in | Cost and limits |
|---|---|---|
| X | Your own Nitter today. The official API in paid tiers, priced monthly; check current prices before building. | Fits the paid tier; respect its terms on redistribution |
| Reddit | RSS until 13 Nov 2026. Registered apps until March 2027, then commercial data deals only. | Effectively closed after March 2027 |
| Bluesky | The AT Protocol, open | Free: a good first native kind |
| Mastodon | The open ActivityPub API, and RSS per account | Free |
| YouTube | Today's reader; the Data API has a free daily quota | Free within the quota |
| Telegram | Done (bridge and account) | Each paid customer needs their own session or bridge |
| Threads, Instagram, Facebook, LinkedIn, TikTok | Business-only or research-only APIs | Closed for this use |
