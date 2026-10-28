# Mark IX (the full reader) and Mark X (analysis): the lists

Written 2026-10-28 from the owner's direction:
- **Two audiences:** a self-hosted "own newspaper" for technical people, and a paid hosted service with predefined sources and tracks for everyone else.
- **Mark IX** is the reader that makes today's RSS readers look incomplete.
- **Mark X** adds analytics, topics and AI on top.

Sources: the issues in `plan/issues/`, `plan/INSIGHT_feature_roadmap.md`, and `plan/INSIGHT_competitors_research.md`.

✓ built and deployed · ◐ built for v9.3 or partial · ○ to do · ⧗ future issue

## Mark IX: everything a full reader needs

### 1. Sources: read anything worth reading
- ✓ RSS and Atom, with full text and images, and no menus or HTML codes (0008, 0032).
- ✓ The feed finder: paste any page and get its feed (0026).
- ✓ Page watching for sites without a feed: links plus sitemap, with an archive (0028).
- ✓ Site readers for special sites (Pipecraft, Gwern, Dario and others).
- ✓ Paid Substack with your cookie.
- ✓ Telegram (bridge and your account).
- ✓ YouTube.
- ✓ X through your own Nitter.
- ✓ Reddit, until Reddit ends RSS on 13 Nov 2026 (0025).
- ✓ Hacker News, first version (0017).
- ✓ GitHub Trending (0023).
- ◐ Add many at once, and OPML import and export (0035).
- ◐ The source doctor, so broken sources find their replacement (0036).
- ◐ Save any page, and the bookmarklet (0031).
- ⧗ Full arXiv papers (0037). ⧗ PDF text (0038).
- ⧗ Hacker News as its own kind, with comments (0017).
- ⧗ GitHub and app release updates (0024).
- ○ Native Mastodon and Bluesky, both open and free to read.
- ○ Podcasts: a player, then transcripts.
- ○ Keyword alerts and news queries.
- ○ Page-change watching, only when a real page needs it.
- ○ Email-in for newsletters with no web version, only when one exists.
- ○ Conditional fetching (ETag / If-Modified-Since): fewer bytes and gentler on sites.
- Not planned: bot-walled news (Reuters, AP, Bloomberg…), closed platforms without an API, and a headless browser.

### 2. Reading: better than reading on the site
- ✓ One calm column, continuous reading, and a byline that links to the source.
- ✓ Clean full text and images.
- ✓ The discussion link.
- ✓ Nothing pointless on screen (0027).
- ◐ Read later and Keep (0022).
- ◐ Continue where I stopped (0030).
- ◐ Calmer continuous reading (0033).
- ◐ One reading density (0034).
- ◐ The reading-fidelity corpus as a merge gate (0032).
- ○ **Search across everything**, then saved searches. This is the biggest gap; nearly every competitor has it.
- ○ Reading settings: font, size and column width.
- ○ Read aloud with browser voices.
- ○ Your own highlights and notes.
- ○ Post versions: keep the text a source later edits.
- ○ Offline reading, and send to Kindle or Kobo, after the PWA.

### 3. Organisation: your newspaper, arranged your way
- ✓ Tracks, the Main feed, and Unread / Later / Kept / All.
- ○ Rules: mute words, auto-read, auto-keep.
- ○ Your own tags.
- ○ Source hygiene: "not opened in 60 days" and "dead for 30 days", with a prune suggestion.
- ○ "Also discussed on Hacker News or Reddit": a badge from shared links.

### 4. Everywhere you read
- ○ An installable PWA, with a share sheet.
- ○ The Fever or Google Reader API, so Reeder, NetNewsWire and others can connect.
- ○ Notifications (ntfy, Gotify, Pushover; Telegram or Discord posts).
- ○ Publish a track as RSS.
- ○ Webhooks.
- ○ Export to Obsidian or Notion.
- ○ A stable API with tokens.

### 5. Product foundations, for both audiences
- ✓ The version line (0020). ✓ Useful logs (0021).
- ○ **Login**. The hosted tiers need it first.
- ○ A one-command install, lighter by merging the API and ingestion.
- ○ A licence choice for the free self-hosted tier.
- ○ A public read-only mode, with title, excerpt and link where full text isn't licensed.
- ○ For the paid tier: one instance per customer, provisioning, billing, **backups**, limits and monitoring.
- ○ A translated interface, for the paid tier.

## Mark X: analysis on another level (ideas)

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
