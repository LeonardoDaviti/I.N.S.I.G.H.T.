# Research: who competes with INSIGHT for reading, and why would someone pick them?

Status: research only, nothing changed. Date: 2026-10-10.

## Question

"List all the competing applications that might compete with INSIGHT, what their strong sides are compared to INSIGHT, and why someone would choose another platform for reading instead of INSIGHT."

Follow-up from the owner: a full list of the features these products have that INSIGHT lacks, grouped by area, with a matrix.

Method:
- Competitor facts come from each product's own site, pricing page, docs, changelog or GitHub repo. Each claim has a URL next to it, or in the sources list at the end.
- A few facts could only be found in news reports or could not be checked at all. Those are marked *secondary* or *unverified*.
- Prices are as listed on 2026-10-10, in the currency the page showed.
- INSIGHT facts are cited to files in this repo.

## Short answer

**INSIGHT is a single-user, self-hosted, multi-platform ingestion engine with a calm web reader on top. Its AI layer is real but currently switched off. Almost every competitor beats it on reading comfort and reach (mobile apps, offline, sync, search, highlights, OPML, integrations). Few beat it on what it collects and how carefully it collects it.**

Who wins on what:
- **Closest overall: Folo and Inoreader.** Both are hosted. Both add arbitrary RSS, newsletters, social and video sources, plus AI summaries and briefings, with apps on every platform.
- **Closest self-hosted: FreshRSS and Miniflux.** Both are mature, light, multi-user, and have Google Reader/Fever APIs, so dozens of mobile apps work with them. Neither has first-party Telegram MTProto, paid-Substack or adaptive-cadence ingestion.
- **Best reading and annotation: Readwise Reader.** Highlights, text-to-speech, PDF/EPUB, offline and export are all far beyond INSIGHT.
- **AI news apps (Particle, Ground News, Perplexity Discover, Google/Apple/Yahoo News, SmartNews) are a different job.** They curate publishers for you, and you cannot bring your own Telegram channels or blogs.
- **Dead or dying, so no longer competition:**
  - Pocket, shut down 2025-07-08.
  - Omnivore, hosted service shut in Nov 2024; self-host-only repo now.
  - Artifact, shut down in 2024 and folded into Yahoo News.
  - ChatGPT Pulse, sunset June 2026 (*secondary*).
  - Stoop, likely shut down Oct 2025 (*secondary*).
- **Market risk:** Reddit announced it will stop serving RSS on 2026-11-13 (Inoreader blog; TechCrunch, *secondary*). INSIGHT's Reddit kind reads `/r/<sub>/new/.rss` (`backend/insight_core/ingestion/kinds/reddit.py:3,67`), so this hits INSIGHT directly, as it does every RSS reader.

Where INSIGHT is genuinely different, in one line: one self-hosted place that reads **Telegram channels natively over MTProto, paid Substack in full, YouTube via yt-dlp, Reddit, Nitter and hand-written site adapters**, on a per-source adaptive cadence with backoff and a health table, with **archive backfill** and an optional **LLM analysis layer (entity/event memory, per-track expert briefings, stories)** whose data stays in your Postgres.

## What INSIGHT actually is today (from the repo)

**Sources (one adapter per kind)**
- The kinds registered, in resolution order (`backend/insight_core/ingestion/kinds/__init__.py:36-57`):
  - site adapters
  - `substack`
  - `reddit`
  - `youtube`
  - `telegram_rss`
  - `nitter_rss`
  - `telegram_mtproto`
  - `generic_rss`
- The site adapters are hand-written scrapers for LessWrong (GraphQL), Gwern, Dario Amodei, Phil Schmid, DeepLearning.AI The Batch and ZeroToMastery (`backend/insight_core/adapters/`).
- **Telegram** comes two ways:
  - an RSS bridge you self-host (TelegramRSS);
  - native MTProto over a Telethon session, which also covers channels with no web preview. It has an advisory-locked session and flood-wait handling (`plan/INSIGHT_mark_ix_plan.md` §D.2 and §8.3; `README.md` "Supported Source Types").
- **Nitter** needs a self-hosted Nitter instance (`README.md` "External Source Infrastructure").
- **Substack, including paid posts in full,** uses the owner's `substack.sid` cookie (`plan/INSIGHT_mark_ix_plan.md` §10).
- **YouTube** uses yt-dlp, and watch progress is saved (`README.md` data model, `youtube_watch_progress`).
- **Reddit** live fetch reads the subreddit's `/new/.rss`; the archive pages the JSON listing (`kinds/reddit.py`).
- **Archive / backfill** for any source is manual only (`README.md` "Manual Operations").

**Fetching**
- Every fetch goes through one entry point, `run_ingestion`.
- Each source gets an adaptive cadence from its publishing rate, with a backlog guard, probation, an exponential backoff ladder, per-host politeness floors and a run lock (`plan/INSIGHT_mark_ix_plan.md` goals 1–5 and §1 glossary).
- Health shows per source: tier, interval, next due, last error and override (goal 7).
- Run reports and a job history live under sources → ingestion.

**Reader** (`README.md` "Frontend pages"; `FRONTEND.md`)
- One feed over every source, filtered by unread, starred or all.
- `stream` or `by_source` view, so one loud source can't bury a quiet one.
- Tracks (folders) work as filters, and `in_main_digest` keeps a source out of the main feed.
- Keyboard j/k navigation (`frontend/src/lib/feedItem.ts`) and a `?` shortcut list.
- Cmd/Ctrl+K quick switcher.
- Post page: prev/next, open original, star, copy.
- Monochrome UI with a dark/light toggle, checked at 375–390px widths (`plan/INSIGHT_mark_ix_design.md`).

**Analysis layer** (`INSIGHT_ANALYSIS`, default **off**; `README.md` "Analysis switch")
- Entity and event memory built at ingest.
- Daily, weekly, topic and vertical briefings; experts (a persona prompt over a track); stories and an inbox; milestones.
- On the post page: summary, intelligence inspector, notes, chat and related posts.
- YouTube roadmap, evaluate and chat.
- **The only LLM provider is Google Gemini**, with a fallback chain (`.env.example:40-79`, `processors/ai/gemini_processor.py`). When Gemini fails, a deterministic fallback briefing is written.

**Deployment**
- Docker Compose with four containers: postgres (pgvector), backend, frontend (Nginx) and ingestion.
- The backend image is 464 MB (commit `0584efd`).
- Secrets are Fernet-encrypted in the DB and entered in Sources → Connections (`plan/INSIGHT_mark_ix_plan.md` §10.1).

**Not in the repo (checked)**
- No app login or user accounts: `backend/main.py` has only `CORSMiddleware`; the only "login" is Telegram's.
- No OPML import or export (no match for `opml` in `backend/` or `frontend/src`).
- No feed search: deferred by owner decision (`plan/INSIGHT_mark_ix_plan.md` §8.4).
- No PWA manifest or service worker (`frontend/public` holds only `vite.svg`).
- No Google Reader or Fever API.
- No email/newsletter ingestion, no podcast player and no PDF or EPUB.
- No text-to-speech, translation, webhooks, notifications or third-party integrations.
- No user-made highlights. `POST /api/posts/item/{id}/highlights` is AI-generated and `@analysis_only` (`main.py:501-503`).

## Category comparison

### Hosted RSS / multi-source readers

| | Sources beyond RSS | AI | Mobile | Client API | Price (entry paid) | Self-host |
|---|---|---|---|---|---|---|
| **INSIGHT** | Telegram (RSS + MTProto), Nitter, Reddit, YouTube, Substack paid, custom adapters | Gemini briefings, experts, memory (off by default) | Web only, responsive | None | Free (your server) | Yes, the only mode |
| **Inoreader** | Web-page feeds, monitoring, newsletters, Facebook, Bluesky, Telegram, VK, YouTube, podcasts, Google News | Summaries, reports, choose OpenAI/Mistral/Anthropic or BYO key | Yes | Google Reader-style | Pro €6.67/mo yearly | No |
| **Feedly** | Newsletters, YouTube, Reddit, Bluesky, X (BYO API key), RSS Builder | Feedly AI (prioritise, dedupe, mute, summarise) on Pro+; deep AI only on $1,600+/mo MI/TI | Yes | Own API | Pro ~$7/mo (2024 doc; current *unverified*) | No |
| **NewsBlur** | Newsletters, YouTube, web feeds | Ask AI, daily briefing, clustering, NL classifiers, MCP | iOS, Android, Mac | Own API | $36/yr; $99/yr for AI | Yes (MIT, Docker) |
| **Feedbin** | Newsletters, YouTube, podcasts, Mastodon | None | iOS (own); Android via third-party | Own REST API | $7/mo | Possible, unsupported |
| **The Old Reader** | None (RSS only) | None | Third-party only | Google Reader-like | Premium (current price *unverified*) | No |
| **Feeder** | YouTube, Reddit, Mastodon, Bluesky, Telegram, Twitch, Google Alerts, newsletters, RSS-from-HTML | Summaries (quota), translation, TTS beta, daily brief, MCP | iOS, Android, extensions | *unverified* | Plus ~$7.99–9.99/mo | No |
| **Folo** | RSSHub routes (thousands), newsletters, podcasts, video | Q&A over feeds, timeline digest, scheduled AI briefings, translation, MCP | iOS, Android, desktop | None found | Basic $49.99/yr | Clients only; backend not public |

### Read-later / reading-and-annotation apps

| | Status | RSS | Highlights / notes | TTS | AI | Platforms | Self-host |
|---|---|---|---|---|---|---|---|
| **Readwise Reader** | Alive | Yes | Yes, export to Notion/Obsidian | Yes | Ghostreader (GPT-5 Mini, BYO key), MCP | iOS, Android, Mac, Windows, web, extensions, e-ink | No |
| **Matter** | Alive | "Planned" (*unverified*) | Yes | HD TTS | AI summaries implied (*unverified*) | iPhone, iPad, web | No |
| **Instapaper** | Alive (independent) | *unverified* | Yes, Obsidian/Notion | AI voices | Summaries | iOS, Android, macOS, web, Kobo, BOOX | No |
| **Wallabag** | Alive (2.6.14) | Import only | Yes | *unverified* | None | Web, Android, iOS | Yes |
| **Karakeep** | Alive | Auto-import from RSS | Yes | *unverified* | LLM tagging and summaries, Ollama, MCP | Web, iOS, Android | Yes |
| **Omnivore** | Hosted shut Nov 2024; repo self-host only | — | — | — | — | — | Yes (AGPL) |
| **Pocket** | **Shut down 2025-07-08** | — | — | — | — | — | — |

### Self-hosted readers

| | Latest release | Stack / DB | Sources | Client API | Multi-user / auth | AI |
|---|---|---|---|---|---|---|
| **INSIGHT** | (not released) | Python, Postgres 15 + pgvector, 4 containers | See above | None | Single user, no auth | Gemini analysis (off) |
| **FreshRSS** | 1.30.1, 2026-10-05 | PHP; Postgres/SQLite/MySQL; runs on a Pi 1 | RSS, WebSub, XPath scraping, extensions (YouTube, Reddit, newsletters) | Google Reader, Fever | Yes; OIDC | LLM Classification extension (official); summary extensions (third-party) |
| **Miniflux** | 2.3.3, 2026-07-24 | Go single binary, Postgres; "a couple of MB" | RSS/Atom/JSON, scraper rules | Google Reader, Fever, REST | Yes; OIDC, passkeys | None official |
| **tt-rss (community fork)** | Rolling; original retired 2025-11-01 | PHP, Postgres | RSS + plugins | Own API, plugins for GReader/Fever | Yes; OIDC plugin | None |
| **CommaFeed** | 7.3.2, 2026-08-22 | Java/Quarkus, H2 or Postgres/MySQL | RSS | REST, Fever, Google Reader (7.3.0) | Yes | None |
| **Nextcloud News** | 29.0.0, 2026-10-10 | Inside Nextcloud | RSS | Own REST | Via Nextcloud | None |
| **Yarr** | v2.9, 2026-09-07 | Go single binary, SQLite/Postgres | RSS, enclosures | Fever, REST | Single, basic auth | None |
| **RSSHub** (bridge, not a reader) | Daily builds | Node + Redis | Telegram, X, YouTube, Mastodon, Bluesky, Substack, Instagram... | Outputs RSS | — | None |
| **Glance** (dashboard) | v0.8.6, 2026-09-03 | Go binary, YAML | RSS, YouTube, Reddit, HN widgets | — | Optional password | None |

### AI news, briefing and aggregator apps

| | Status | Can you add your own sources? | AI | Platforms | Price |
|---|---|---|---|---|---|
| **Perplexity Discover / Comet** | Alive | No; curated, plus finance and sports watchlists | AI pages, Discover Daily podcast | Web, apps, Comet browser | Free; Comet Plus $5/mo |
| **Particle** | Alive | No; topics from publisher partners | Multi-source summaries, ELI5 styles, Q&A, listen | iOS, Android, web | Free; Plus $2.99/mo |
| **Ground News** | Alive | No; hide or re-rate sources | Bias and factuality ratings, Blindspot, AI summaries | iOS, Android, web, extension | Vantage €8.50/mo yearly (EU); other tiers *unverified* |
| **Google News** | Alive | Follow sources and topics, "Preferred Sources"; no RSS | Full Coverage, AI audio briefings (Android, Aug 2026) | Android, iOS, web | Free |
| **Apple News / News+** | Alive | No | Narrated audio, editors; no generative AI described | Apple only | News+ $12.99/mo |
| **Yahoo News** (Artifact inside) | Alive | Topics and publishers | Key Takeaways, Daily Digest audio, Scout | iOS, Android, web | Free (*unverified*: ads) |
| **SmartNews** | Alive | No | AI Matome (Japan), translation | iOS, Android | Free |
| **ChatGPT Pulse** | **Sunset June 2026** (*secondary*) | — | Replaced by scheduled tasks | — | — |
| **Artifact** | **Shut down 2024**, acquired by Yahoo | — | — | — | — |

### Newsletter and Telegram digest tools

| | Status | What it does | Price |
|---|---|---|---|
| **Meco** | Alive | Pulls newsletters out of Gmail/Outlook into a reader; AI summaries and an audio roundup | PRO $4.99/mo |
| **Kill the Newsletter** | Alive, MIT | Email address → Atom feed | Free |
| **Readless** | Alive | Newsletters, Substack and RSS → scheduled AI digest, deduplicated | $4.90–$9/mo |
| **Stoop** | Likely shut down Oct 2025 (*secondary*) | — | — |
| **Telegram chat folders** | Built into Telegram | Group up to 100–200 channels; no digest | Free / Premium |
| **Aggregaat** | Alive | Telegram bot: merges channels, AI digests with your own key | Free–$15.99/mo |
| **Junction Bot** | Alive | Telegram AI digests; private chats if you connect your account | Free–€12.60/mo |
| **Telebrief** | Alive | Self-hosted Telethon digest via OpenAI, Anthropic or Ollama | Free (self-host) |

## Per-competitor notes

Each entry gives the product's **strong sides vs INSIGHT** and **why a reader would pick it over INSIGHT**.

### Inoreader
- **Strong sides:** the widest hosted source set:
  - web-page feeds and change monitoring;
  - newsletters;
  - Facebook, Bluesky, Telegram and VK;
  - YouTube, and podcasts with transcripts.
- It also has rules (30) and filters (50), annotations exported to Readwise, persistent full text, global search in 30 languages and offline mobile reading.
- It integrates with Zapier, n8n, IFTTT, Pocket, Evernote and Instapaper, and keeps automatic OPML backups.
- AI "Intelligence" covers summaries, mentions and reports. You choose the AI platform or bring your own key.
- TTS with narration tracking shipped in Sep 2026. It has passkeys and is ISO 27001.
- **Why pick it:** it does most of what INSIGHT does, on a phone, with no server to run, plus search, rules and a choice of LLM, for about €80/yr.
- What it lacks vs INSIGHT: Telegram is capped (30 on Pro) and its mechanism is *unverified* (likely the public preview, not your own MTProto session). No paid-Substack cookie, no archive backfill, no self-hosting, and your data lives on their servers.

### Feedly
- **Strong sides:**
  - the most polished mainstream reader;
  - Feedly AI prioritises, deduplicates, mutes, and offers 1,000+ pre-trained topics;
  - newsletters, YouTube, Reddit, Bluesky, and X with your own API key;
  - Boards with notes and highlights;
  - Zapier, IFTTT and Slack/Teams.
- It is the enterprise leader for threat and market intelligence: SOC 2 Type 2, OpenCTI and MISP, a STIX API and an MCP server.
- **Why pick it:** team or professional monitoring with dedup and prioritisation, at scale, with compliance paperwork.
- **Against it:** the deep AI is priced at $1,600+/mo (MI), and the consumer AI is gated to Pro+. No Telegram found (*unverified*), and no self-hosting.

### NewsBlur
- **Strong sides:**
  - a trainable "intelligence" filter by author, tag, title, full text, regex, and natural-language text and image classifiers;
  - Ask AI, a daily briefing and story clustering ($99/yr);
  - an MCP server, CLI and agent skill (Apr 2026);
  - highlights and notes, and tag feeds;
  - offline mobile apps on iOS, Android and Mac (v15, Oct 2026);
  - social shared stories.
- It is open source (MIT) and self-hostable with Docker.
- **Why pick it:** INSIGHT's AI-briefing idea already shipped, cheaply, with real mobile apps and decades of polish, and it can still be self-hosted.
- **Against it:** the self-host stack is heavy (Django, Postgres, MongoDB, Redis, Elasticsearch, Celery). No Telegram or paid-Substack ingestion found.

### Feedbin
- **Strong sides:**
  - newsletters, YouTube (with chapters), podcasts (the Airshow app) and Mastodon;
  - full-text extraction, a search syntax and saved searches;
  - actions (auto-star, mark read, push notifications);
  - diffs of edited articles;
  - a browser extension for subscribe and save-for-later;
  - a big third-party client ecosystem (Reeder, NetNewsWire, Unread);
  - no ads and no tracking scripts.
- **Why pick it:** a calm, privacy-respecting, no-AI reader. That is the same ideology as INSIGHT reading-only, but with apps, search and newsletters, for $7/mo.
- **Against it:** no AI, no Telegram, and self-hosting is unsupported.

### The Old Reader
- **Strong sides:** simple, social (follow friends, likes, comments), and works with Google Reader-API clients (Reeder, FeedMe and others).
- **Why pick it:** cheap, minimal RSS with existing mobile clients.
- **Against it:** RSS only, no AI, and little visible development (blog unreadable; *unverified*).

### Feeder
- **Strong sides:** the closest *hosted* match to INSIGHT's source mix:
  - RSS, YouTube, Reddit, Mastodon, Bluesky, Telegram (Plus), Twitch, Google Alerts, newsletters, RSS-from-HTML.
- It adds AI summaries, translation and a daily brief, an MCP connection, and RSS→Telegram output.
- It has extensions and mobile apps.
- **Why pick it:** INSIGHT's "all my platforms in one place" without running Docker.
- **Against it:** AI quotas (Free 2/day, Plus 10/day), public Telegram channels only, and no backfill or self-host.

### Folo (formerly Follow, by the RSSHub team)
- **Strong sides:**
  - every platform: web, iOS, Android, macOS, Windows, Linux;
  - thousands of RSSHub routes (X, Telegram, Instagram, Bilibili...), newsletters, podcasts and video;
  - Actions rules (filter, star, rewrite, notify, summarise);
  - TTS;
  - integrations (Obsidian, Readwise, Instapaper, Zotero);
  - AI at its core: Q&A over an article, feed, folder or everything; timeline digests; scheduled AI briefings to chat or email; your own key; MCP.
- Released every two weeks.
- **Why pick it:** it is the most direct product-level competitor to INSIGHT with analysis on: folders + AI briefings + multi-platform sources, polished and free to start.
- **Against it:** the backend is hosted only (clients are AGPL; no public server code found). RSSHub's Telegram route scrapes the public `t.me/s/` preview, not your own session. Usage limits apply per tier (RSSHub subscriptions 30/200/500).

### Readwise Reader
- **Strong sides:**
  - it ingests RSS, newsletters, PDF, EPUB, YouTube (transcript highlighting) and X threads;
  - highlights, tags and notes, with a query language for filtered views;
  - TTS with AI voices;
  - offline with offline search;
  - export to Notion and Obsidian, and OPML export;
  - Ghostreader: summarise, translate, Q&A, and a library-wide "Global Ghostreader" with citations;
  - MCP server and CLI;
  - apps on every platform, plus e-ink and Kindle delivery.
- **Why pick it:** a reader who *studies* what they read (highlight, review, export) will find INSIGHT has none of that today.
- **Against it:** $9.99–12.99/mo, closed SaaS, and no Telegram, Reddit or paid-Substack ingestion.

### Matter, Instapaper, Wallabag, Karakeep
- **Matter:** HD text-to-speech and audio highlights; YouTube and podcasts as time-synced text; Notion, Obsidian and Readwise sync; API.
  - Why pick it: listening and an iPhone-first reading queue.
- **Instapaper:** independent and actively shipping (API v2 in Sep 2026, iOS 10 in Jul 2026); highlights on the open web; tags; Obsidian and Notion; Kindle, Kobo and BOOX; AI voices.
  - Why pick it: e-ink and long-form reading.
- **Wallabag:** self-hosted and MIT; save by email; tagging rules; export to EPUB, PDF and mobi; hosted option at €11/yr.
  - Why pick it: a self-hosted read-later queue that pairs with FreshRSS or Miniflux.
- **Karakeep:** self-hosted; LLM tagging and summaries with local models (Ollama); OCR; semantic search; a rules engine; MCP; mobile apps.
  - Why pick it: the closest *self-hosted AI-first* tool, with local LLMs, which INSIGHT does not support.

### FreshRSS and Miniflux (the self-hosted default choices)
- **Strong sides, both:**
  - multi-user with OIDC;
  - Google Reader and Fever APIs, so mobile apps work: Reeder, NetNewsWire (Miniflux), Read You, FeedMe, Fluent Reader;
  - OPML;
  - full-text search;
  - filters and rules, full-text extraction, scraping of sites without feeds.
- **FreshRSS** adds XPath scraping, saved queries reshared as RSS, 20+ share targets, and an AI-tagging extension. It runs on a Raspberry Pi 1.
- **Miniflux** is a single Go binary using a few MB of RAM, with 25+ integrations (Readwise Reader, Notion, Telegram, ntfy, webhooks) and passkeys.
- **Why pick them:** most self-hosters want "RSS on my server, read on my phone". Both do that, and INSIGHT cannot: it has no client API, no auth and no PWA.
- **Against them:** neither has native Telegram MTProto, paid Substack, yt-dlp YouTube, per-source adaptive cadence with a health table, archive backfill, or a built-in briefing layer.

### tt-rss, CommaFeed, Nextcloud News, Yarr, Glance
- **tt-rss:** the original was retired on 2025-11-01; a community fork continues. It has scoring filters, email digests, deduplication and plugins.
- **CommaFeed:** a native binary with an embedded H2 database, rule-based auto-mark-read, push to ntfy, Gotify and Pushover, and a Google Reader API since 7.3.0.
- **Nextcloud News:** for people who already run Nextcloud.
- **Yarr:** a one-binary personal reader with a Fever API.
- **Glance:** a dashboard, not a reader. People who want "a glance at my sources" may pick it instead of a reader at all.

### RSSHub (bridge)
- Not a reader, but it is the main reason RSS readers can match INSIGHT's source reach. It has routes for Telegram, X, YouTube, Mastodon, Bluesky, Substack and Instagram, ships daily, and has 5,000+ instances.
- A FreshRSS or Miniflux plus RSSHub stack covers most of INSIGHT's source list.
- **Against it:** RSSHub's Telegram route has open reliability issues, and some channels need a session.

### AI news apps (Particle, Ground News, Perplexity Discover, Google News, Apple News, Yahoo News, SmartNews)
- **Strong sides:**
  - zero setup;
  - a professional publisher catalogue, including paywalled partners (Comet Plus, Apple News+);
  - multi-perspective views (Particle "every side", Ground News bias and factuality with a published method, Google Full Coverage, SmartNews spectrum slider);
  - AI audio briefings (Google News, Yahoo Daily Digest, Perplexity Discover Daily, Particle listen);
  - polished mobile apps.
- **Why pick them:** someone who wants "the news" rather than "my sources". INSIGHT does not ship sources; you have to know what to follow.
- **Against them:** you cannot add your own Telegram channels, blogs, subreddits or YouTube channels. Personalisation means data collection: Particle's App Store label lists linked location, contacts and identifiers, and its policy names AI providers.

### Newsletter and Telegram digest tools
- **Meco and Readless** solve newsletters, a source INSIGHT does not ingest at all. Meco says it keeps email data on the device.
- **Kill the Newsletter** is a free bridge that would let INSIGHT read newsletters through `generic_rss` today, with no code change. Entries older than a month are deleted.
- **Aggregaat, Junction and Telebrief** prove there is demand for "AI digest of my Telegram channels", which is INSIGHT's analysis-on use case. Telebrief is self-hosted with Telethon and supports OpenAI, Anthropic or Ollama, which is close to INSIGHT's design.

## Feature gaps: what competitors have that INSIGHT doesn't

How to read this section:
- **No:** checked in the repo and absent.
- **Partial:** something exists, but it is limited. The note explains what.
- **Analysis-on only:** it exists, but is hidden in the default reading-only app.

Examples of who has each feature are cited in the comparison tables and sources above; the URL is repeated here where the claim is not already there.

### Reading and annotation

| Feature | Who has it | INSIGHT |
|---|---|---|
| User highlights | Readwise Reader, Instapaper, Matter, Wallabag, Karakeep, NewsBlur, Inoreader (spotlights), Feedly (Boards) | **No.** `POST /api/posts/item/{id}/highlights` is AI-generated and `@analysis_only` (`main.py:501`) |
| Notes and annotations on posts | Readwise, Instapaper, NewsBlur, Inoreader, Feedly | **Analysis-on only.** `GET/PUT /api/posts/item/{id}/notes` exist (`main.py:983,993`); the post page hides notes when off (`README.md`) |
| Text-to-speech / listen | Readwise, Matter, Instapaper, Inoreader, Folo, Feeder (beta), Particle | **No** |
| Full-text extraction for partial feeds | Feedbin, Inoreader, Miniflux, FreshRSS, tt-rss, Yarr, Nextcloud News | **Partial.** `generic_rss` has optional full-content expansion (`extract_article_html` in `kinds/parsing.py`; `plan/INSIGHT_mark_ix_plan.md` §2), and paid Substack gives full bodies. No per-feed CSS-selector or Readability toggle in the UI |
| Article diffs (edited posts) | Feedbin | **No.** The save upserts by url, so the new body silently replaces the old one (`plan/INSIGHT_mark_ix_plan.md` §10) |
| PDF / EPUB reading | Readwise, Instapaper (PDF), Karakeep | **No** |
| Speed reading, e-ink mode, Kindle/Kobo delivery | Instapaper, Readwise | **No** |
| Read-later queue for arbitrary URLs | Readwise, Instapaper, Matter, Wallabag, Karakeep, Feedbin (Pages) | **No.** Only posts from configured sources; starring is the nearest equivalent |
| Reading progress | Readwise, Matter | **Partial.** YouTube only (`youtube_watch_progress`, `GET/PUT /api/youtube/progress/{id}`) |

### Capture

| Feature | Who has it | INSIGHT |
|---|---|---|
| Browser extension (save / subscribe) | Readwise, Instapaper, Matter, Feedbin, Feeder, Karakeep, Ground News, CommaFeed | **No** |
| Email-in address for newsletters | Feedly, Inoreader, NewsBlur, Feedbin, Folo, Readwise, Matter, Wallabag, Meco | **No.** Only indirectly, through a Kill the Newsletter Atom feed |
| Save from mobile share sheet | All read-later apps with mobile apps | **No** (no mobile app, no PWA) |
| Bookmarklet / subscribe-URL handler | The Old Reader, Nextcloud News | **No** |
| Feed autodiscovery from a page URL | The Old Reader, Nextcloud News, Miniflux | ***Unverified*** (not checked in `AddSourceModal.tsx`) |

### Sources

| Feature | Who has it | INSIGHT |
|---|---|---|
| Newsletters | See email-in | **No** |
| Podcasts (player, transcripts) | Inoreader, Feedbin (Airshow), Folo, Matter, tt-rss, Yarr | **Partial.** Enclosure URLs are parsed as media (`kinds/parsing.py:215-224`). No player and no transcripts |
| X/Twitter | Feedly (BYO API key), RSSHub | **Partial.** Through a self-hosted Nitter (`nitter_rss`) |
| Mastodon, Bluesky | Inoreader, Feedly (Bluesky), Feedbin (Mastodon), Feeder, RSSHub | **No native kind.** Only if the instance exposes RSS (`generic_rss`) |
| Facebook, Instagram, VK, Twitch, LinkedIn | Inoreader, Feeder, RSSHub | **No** |
| Web pages without a feed (scraping / change monitoring) | Inoreader (web and monitoring feeds), Feedly (RSS Builder), FreshRSS (XPath), Miniflux (scraper rules), NewsBlur, Feeder | **Partial.** Six hand-coded site adapters (`backend/insight_core/adapters/`). Not user-configurable |
| Google News / keyword alerts | Inoreader, Feeder | **No** |
| Publisher catalogue / discovery | Particle, Ground News, Apple/Google News, NewsBlur (YouTube and subreddit catalogues) | **No.** You must know your sources |
| Reddit after 2026-11-13 | Nobody, if they rely on Reddit RSS | **At risk.** Live fetch uses `.rss` (`kinds/reddit.py:67`) |

### Organisation and search

| Feature | Who has it | INSIGHT |
|---|---|---|
| Full-text search | Nearly all (Inoreader, Feedbin, Miniflux, FreshRSS, Readwise, NewsBlur Premium...) | **No.** Deferred (`plan/INSIGHT_mark_ix_plan.md` §8.4) |
| Saved searches / user queries | Feedbin, FreshRSS (reshared as RSS/OPML), Readwise filtered views | **No** |
| Rules / filters (auto-mark-read, auto-star, keyword block) | Inoreader, Feedbin actions, Miniflux regex, FreshRSS, CommaFeed, tt-rss, Nextcloud News, Folo Actions, Feedly mute | **Partial.** `in_main_digest` hides a whole source from the main feed (`migrations/0016_tracks.sql:28`); feed filter is unread/starred/all. No per-post rules |
| Tags / labels on posts | Readwise, Instapaper, NewsBlur, FreshRSS, CommaFeed, Wallabag, Karakeep | **No** for the user. The analysis layer has topics and entities (`db/repo_topics.py`, `repo_memory.py`) |
| Folders | All readers | **Yes** (tracks) |
| Trained / scored ranking | NewsBlur, tt-rss scoring, Feedly priority | **No.** Feed is newest-first |
| Mark-all-read, keyboard navigation | All | **Yes** (`POST /api/feed/mark-read`, j/k) |

### AI

| Feature | Who has it | INSIGHT |
|---|---|---|
| Per-article summary | Inoreader, Feedly Pro+, Folo, Feeder, Readwise, Particle, Instapaper | **Analysis-on only** (post summary) |
| Daily / scheduled briefing | NewsBlur, Folo (AI Tasks), Feeder, Inoreader reports, Readless, Meco, Telegram digest bots | **Analysis-on only.** Daily, weekly, topic and vertical briefings, plus experts per track (`README.md`) |
| Q&A / chat over one article | Readwise, Particle, Folo | **Analysis-on only** (`POST /api/posts/item/{id}/chat`, `main.py:1031`) |
| Q&A across the whole library, with citations | Readwise Global Ghostreader, Folo, NewsBlur Ask AI | **No.** Stories and inbox exist, but not free-form library Q&A (*unverified* beyond `main.py` routes) |
| Choice of LLM provider / own key | Inoreader (OpenAI, Mistral, Anthropic), Readwise (OpenAI), Folo, FreshRSS extensions, Telebrief | **No.** Gemini only (`.env.example:77-79`) |
| Local LLMs (Ollama) | Karakeep, FreshRSS extensions, Telebrief | **No** |
| Story clustering / dedup across sources | Feedly, NewsBlur, Readless, Particle, Ground News | **Partial.** Exact dedupe by url (`posts.url UNIQUE`); stories and topics only with analysis on |
| Translation | Inoreader, Feedly Multilingual AI, Folo, Feeder, Readwise, SmartNews | **No** |
| Bias / perspective view | Ground News, Particle, SmartNews, Google Full Coverage | **No** |
| Audio briefing | Google News, Yahoo, Perplexity, Meco, Particle | **No** |
| MCP server / agent access | Readwise, NewsBlur, Feedly TI, Feeder, Folo, Karakeep | **No** |
| Auto-tagging | Readwise, Karakeep, FreshRSS LLM Classification, Inoreader suggested tags | **No** for the user. Entities and topics only with analysis on |

### Sync and clients

| Feature | Who has it | INSIGHT |
|---|---|---|
| Native iOS / Android apps | Feedly, Inoreader, NewsBlur, Feedbin (iOS), Folo, Readwise, Instapaper, Particle... | **No** |
| PWA / installable web app | Miniflux | **No** (no manifest) |
| Offline reading | Inoreader, NewsBlur, Readwise, Matter, Wallabag, Karakeep | **No** |
| Google Reader / Fever API (third-party apps) | FreshRSS, Miniflux, CommaFeed, Inoreader, The Old Reader, Yarr (Fever) | **No** |
| OPML import / export | Every RSS reader | **No.** The nearest is `sources.json` ↔ DB sync (`README.md` "Source Sync") |
| Data export (posts, highlights) | Readwise (CSV/Markdown), Matter, Wallabag (EPUB/PDF) | **Partial.** You own the Postgres and `sources.json`; no export UI |
| Cross-device read-state sync | All hosted readers | **Partial.** State is server-side, so any browser that reaches the server shares it; not reachable from outside your network unless you expose it |

### Sharing and collaboration

| Feature | Who has it | INSIGHT |
|---|---|---|
| Teams / shared folders | Feedly, Inoreader Teams, Feeder Professional, Karakeep shared lists | **No** |
| Public / social sharing (blurblogs, follow friends, comments) | NewsBlur, The Old Reader | **No** |
| Share to services (Pocket, Instapaper, Mastodon...) | FreshRSS (20+), Miniflux, Inoreader, Feedbin | **Partial.** Copy (⧉) and open original (↗) only |
| Publish a folder or tag as RSS | NewsBlur, FreshRSS, Karakeep, Wallabag | **No** |
| Quote images / share cards | Matter (Quoteshots), NewsBlur | **No** |

### Integrations and automation

| Feature | Who has it | INSIGHT |
|---|---|---|
| Zapier / IFTTT / n8n | Feedly, Inoreader, NewsBlur | **No** |
| Notion / Obsidian / Readwise export | Readwise, Instapaper, Matter, Inoreader (to Readwise), Folo, Miniflux | **No** |
| Webhooks | Miniflux, FreshRSS (extension) | **No** |
| Public documented API for third parties | Inoreader, NewsBlur, Feedbin, Miniflux, Instapaper, Readwise | **Partial.** FastAPI `/docs` exists (`README.md` "Default URLs"), but it has no auth and no stability promise |
| Slack / Teams / Discord / Telegram output | Feedly, Miniflux, Feeder (RSS→Telegram) | **No** |
| CLI | NewsBlur, Readwise, Matter, Karakeep | **Partial.** Operator CLI only (`safe_ingest`, `telegram_login`) |

### Notifications

| Feature | Who has it | INSIGHT |
|---|---|---|
| Push notifications for new posts or keywords | Feedbin, CommaFeed (ntfy/Gotify/Pushover), Miniflux (ntfy, Pushover), Folo, TGStat alerts | **No** |
| Email digests | Inoreader, tt-rss, Folo | **No** |

### Accessibility and theming

| Feature | Who has it | INSIGHT |
|---|---|---|
| Dark/light theme | All | **Yes** (top-bar toggle) |
| Font, size, width and layout choices | Readwise, Instapaper, CommaFeed (4 layouts), Feedly | **No.** Fixed reading column and one type scale (`plan/INSIGHT_mark_ix_design.md`) |
| Custom CSS / JS | CommaFeed, Folo | **No** |
| Keyboard shortcuts (and switching them off) | Most readers | **Yes**, with a WCAG 2.1.4 toggle (`FRONTEND.md`) |
| Localised UI | FreshRSS, Inoreader and others | **No** (English only; *unverified* that no i18n exists) |

### Account and hosting

| Feature | Who has it | INSIGHT |
|---|---|---|
| Zero setup (sign up and read) | All hosted products | **No.** Docker Compose; self-hosted TelegramRSS and Nitter for those kinds |
| User accounts / login / OIDC / passkeys | FreshRSS, Miniflux, tt-rss, CommaFeed, Inoreader (passkeys) | **No.** No auth on the API or UI |
| Multi-user | FreshRSS, Miniflux, tt-rss, CommaFeed, NewsBlur | **No** |
| Tiny footprint | Miniflux (a few MB), Yarr and Glance (single binary), FreshRSS (Pi 1) | **No.** 4 containers and a 464 MB backend image, ~80–120 MB per Python process (`plan/INSIGHT_merge_api_ingestion_research.md`) |
| Managed hosting option | Wallabag.it, Karakeep Cloud, NewsBlur, CommaFeed.com | **No** |
| Compliance (SOC 2, ISO 27001) | Feedly, Inoreader | Not applicable (self-hosted) |

### Matrix

Legend: ● has it · ◐ partial or tier-gated · ○ no · ? unverified · A = INSIGHT with analysis on only.

| Feature | INSIGHT | Inoreader | Feedly | NewsBlur | Feedbin | Feeder | Folo | Readwise | Instapaper | FreshRSS | Miniflux | Karakeep | Particle |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Native mobile apps | ○ | ● | ● | ● | ◐ (iOS) | ● | ● | ● | ● | ◐ (3rd-party) | ◐ (3rd-party) | ● | ● |
| Offline | ○ | ● | ? | ● | ? | ? | ? | ● | ? | ◐ (via apps) | ◐ (via apps) | ● | ? |
| GReader / Fever API | ○ | ● | ○ | ○ | ○ | ? | ? | ○ | ○ | ● | ● | ○ | ○ |
| OPML | ○ | ● | ● | ? | ● | ? | ● | ● (export) | ○ | ● | ● | ? | ○ |
| Full-text search | ○ | ● | ? | ◐ | ● | ? | ? | ● | ◐ | ● | ● | ● | ○ |
| Rules / filters | ◐ | ● | ◐ | ● | ● | ● | ● | ◐ | ○ | ● | ● | ● | ○ |
| User highlights | ○ | ● | ● | ● | ? | ? | ? | ● | ● | ○ | ○ | ● | ○ |
| Notes | A | ● | ● | ● | ? | ? | ? | ● | ● | ○ | ○ | ? | ○ |
| Text-to-speech | ○ | ● | ? | ? | ○ | ◐ | ● | ● | ● | ○ | ○ | ? | ● |
| Browser extension | ○ | ? | ? | ? | ● | ● | ? | ● | ● | ○ | ○ | ● | ? |
| Newsletters (email-in) | ○ | ● | ● | ● | ● | ● | ● | ● | ? | ◐ (ext.) | ○ | ? | ○ |
| Podcasts | ◐ | ● | ? | ? | ● | ? | ● | ? | ? | ○ | ◐ | ? | ◐ |
| YouTube | ● | ● | ● | ● | ● | ● | ● | ● | ? | ◐ (ext.) | ● | ◐ | ○ |
| Reddit | ● (RSS, at risk) | ? | ● | ◐ | ? | ● | ● | ? | ? | ◐ (ext.) | ◐ | ? | ○ |
| Telegram | ● (RSS + MTProto) | ● | ? | ? | ○ | ● | ● (RSSHub) | ○ | ○ | ○ | ○ | ○ | ○ |
| Paid Substack in full | ● | ? | ? | ? | ? | ? | ? | ? | ◐ (logged-in pages) | ○ | ◐ (cookies) | ○ | ○ |
| Scrape sites without feeds | ◐ (coded adapters) | ● | ◐ | ● | ○ | ● | ● (RSSHub) | ○ | ○ | ● | ● | ○ | ○ |
| Archive backfill | ● | ? | ? | ◐ (archive tier) | ○ | ? | ? | ○ | ○ | ○ | ○ | ○ | ○ |
| Per-source adaptive cadence + health | ● | ○ | ○ | ◐ | ○ | ○ (fixed refresh by tier) | ? | ○ | ○ | ◐ | ◐ | ○ | ○ |
| AI summaries | A | ● | ◐ | ● | ○ | ◐ | ● | ● | ● | ◐ (ext.) | ○ | ● | ● |
| AI briefings / digests | A | ● | ◐ | ● | ○ | ● | ● | ○ | ○ | ◐ (ext.) | ○ | ○ | ◐ |
| Choice of LLM / BYO key | ○ (Gemini) | ● | ○ | ? | ○ | ? | ● | ● | ○ | ● (ext.) | ○ | ● | ○ |
| Local LLM | ○ | ○ | ○ | ○ | ○ | ○ | ? | ○ | ○ | ● (ext.) | ○ | ● | ○ |
| Translation | ○ | ● | ● | ? | ○ | ● | ● | ● | ? | ◐ (ext.) | ○ | ? | ● |
| MCP server | ○ | ? | ● (TI) | ● | ○ | ● | ● | ● | ○ | ○ | ○ | ● | ○ |
| Integrations (Zapier, Notion...) | ○ | ● | ● | ● | ◐ | ? | ● | ● | ● | ● | ● | ◐ | ○ |
| Push notifications | ○ | ? | ? | ? | ● | ? | ● | ? | ? | ○ | ● | ? | ? |
| Teams / sharing | ○ | ● | ● | ● (social) | ○ | ● | ? | ○ | ○ | ◐ (share) | ◐ (share) | ● | ○ |
| Multi-user + auth | ○ | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | ● | ● | ● | n/a |
| Self-host | ● | ○ | ○ | ● | ◐ | ○ | ◐ (clients) | ○ | ○ | ● | ● | ● | ○ |
| Zero setup | ○ | ● | ● | ● | ● | ● | ● | ● | ● | ○ | ○ | ◐ (cloud) | ● |

Cells marked "?" mean the primary source did not say; they are not claims of absence. FreshRSS and Miniflux cadence is ◐ from general knowledge of their per-feed TTL and polling-scheduler settings, which this research did not re-verify (*unverified*).

## Honest gaps (why a reader picks something else)

1. **No phone experience.** There are no apps, no PWA, no offline mode and no client API. This is the single biggest reason a reader would pick Inoreader, Feedly, NewsBlur, Folo or Readwise, or FreshRSS/Miniflux with Reeder or NetNewsWire. A Google Reader or Fever API would unlock dozens of existing apps for little code. A PWA manifest is smaller still.
2. **Not safe to expose to the internet.** There is no login. Today the only safe use is on a home LAN or behind a VPN or an auth proxy. Every self-hosted rival ships auth, often OIDC.
3. **No search and no OPML.** These are table stakes for RSS readers. Without OPML, moving in from or out to another reader is manual.
4. **No annotation.** No user highlights, no notes in the default app, no TTS, no export. That rules INSIGHT out for "read to learn" users (Readwise, Instapaper, Matter).
5. **No newsletters.** This is the most common non-RSS source in the competitor set. Kill the Newsletter is a zero-code bridge for now.
6. **Setup cost.** INSIGHT needs Docker, Postgres and four containers, and Telegram RSS and Nitter need their own self-hosted services. Hosted products take seconds; Miniflux takes one binary.
7. **AI lock-in to Gemini, and off by default.** Competitors let you pick OpenAI, Anthropic or Mistral, bring your own key, or run Ollama locally. INSIGHT's analysis layer is hidden in the shipped app, so today it is not a selling point a user sees.
8. **No rules, notifications or integrations.** No keyword alerts, no auto-star, no webhooks, no Notion or Obsidian, no Zapier.
9. **Reddit RSS ends 2026-11-13** (*secondary* for the date: Inoreader blog title plus TechCrunch). Reddit was one of INSIGHT's six platforms.
10. **Single user.** You cannot share a track with a partner or team.

## Where INSIGHT is genuinely differentiated

1. **Telegram done properly.** Native MTProto with your own session: private and preview-less channels, archive pages, flood-wait handling (`plan/INSIGHT_mark_ix_plan.md` §D.2).
   - Hosted rivals and RSSHub read the public `t.me/s/` preview.
   - Only small Telegram-only bots (Junction, Telebrief) use your account, and none of them are full readers.
2. **Paid Substack in full** through your own cookie, with expiry detection and a health notice (§10). I found no competitor that documents this.
3. **Archive backfill** of a source's history into the same store (Reddit top 250, Telegram, Nitter, Substack, YouTube). Most readers only keep what arrived after you subscribed.
4. **Careful, legible fetching.** Per-source adaptive cadence (fast, medium, slow, probation), a backlog guard, a backoff ladder, host politeness floors, and a health table with the next-due time and the reason a source was skipped. Competitors mostly show a global refresh interval by tier (Feeder 30 min / 5 min / 1 min).
5. **A calm reader by design.** `by_source` view so a loud source can't bury a quiet one, `in_main_digest`, a monochrome UI, no ads and no tracking. Feedbin is the nearest in spirit.
6. **Your data, your box.** Posts, read state and analysis all live in your Postgres, with encrypted credentials. Nothing goes to a third party with analysis off.
7. **An analysis layer that the rivals' AI does not have:** entity and event memory across sources, stories and milestones over time, and expert personas per track. Folo, NewsBlur and Inoreader offer summaries, Q&A and briefings, but I found none that build a persistent entity/event memory. It is off, so it is potential, not a shipped advantage.
8. **Hand-written adapters for high-signal sites** that have poor feeds (LessWrong GraphQL, Gwern, The Batch).

The positioning that follows: **"a private, self-hosted intelligence reader for the sources mainstream readers can't reach well (Telegram, paid Substack, niche sites), with an archive"**. It is not a general RSS reader. The cheapest gaps to close for that audience are an auth proxy or login, a PWA, OPML import, search, and a choice of LLM provider (or Ollama).

## Open questions for the owner

1. Is phone reading in scope? If yes, which first: a PWA (smallest), a Google Reader/Fever API (reuses existing apps), or native apps?
2. Will INSIGHT ever be reachable outside the LAN? If yes, auth comes before anything else.
3. Reddit after 2026-11-13: drop the kind, switch to the registered Data API (registration closes 2027-01-12 per the same announcement, *secondary*), or accept stale Reddit sources?
4. Newsletters: document Kill the Newsletter as the bridge, or build an email-in kind?
5. When analysis comes back on, should it stay Gemini-only, or go provider-agnostic (OpenAI-compatible endpoint, which also covers Ollama)?

## Sources

INSIGHT (repo): `README.md`, `FRONTEND.md`, `plan/INSIGHT_mark_ix_plan.md` (§1, §2, §8, §9, §10), `plan/INSIGHT_mark_ix_reading_finish_plan.md`, `plan/INSIGHT_mark_ix_design.md`, `plan/INSIGHT_merge_api_ingestion_research.md`, `backend/main.py`, `backend/insight_core/ingestion/kinds/{__init__,reddit,parsing}.py`, `backend/insight_core/adapters/`, `.env.example`, `frontend/public/`, commit `0584efd`.

Hosted RSS readers
- Inoreader: https://www.inoreader.com/pricing , https://www.inoreader.com/blog/ , https://www.inoreader.com/blog/2025/03/inoreader-intelligence-and-article-summaries-are-here.html , https://www.inoreader.com/blog/2026/01/follow-different-sources.html , https://www.inoreader.com/blog/2025/12/inoreader-2025-intelligence-and-automation-in-one-content-hub.html , https://www.inoreader.com/developers/
- Feedly: https://feedly.com/new-features , https://feedly.com/ai , https://feedly.com/new-features/posts/feedly-ai-and-summarization , https://feedly.com/new-features/posts/bluesky , https://feedly.com/market-intelligence/pricing , https://feedly.com/threat-intelligence/pricing , https://docs.feedly.com/article/140-what-is-the-difference-between-feedly-basic-pro-and-teams , https://docs.feedly.com/article/50-i-want-to-switch-to-yearly-monthly-billing , https://docs.feedly.com/article/768-follow-sources-in-feedly , https://docs.feedly.com/article/663-how-to-follow-a-newsletter , https://docs.feedly.com/article/383-what-types-of-reddit-subreddit-feeds-can-i-add-to-feedly , https://docs.feedly.com/article/594-how-can-i-access-the-rss-builder , https://docs.feedly.com/article/52-how-can-i-export-my-sources-and-feeds-through-opml , https://docs.feedly.com/collection/420-integrations , https://docs.feedly.com/article/809-how-to-use-multilingual-ai
- NewsBlur: https://newsblur.com/ , https://blog.newsblur.com/ , https://newsblur.com/api , https://newsblur.com/faq , https://github.com/samuelclay/NewsBlur , https://blog.newsblur.com/2020/07/17/highlight-passages-and-add-private-notes-on-saved/
- Feedbin: https://feedbin.com/ , https://feedbin.com/pricing , https://feedbin.com/blog , https://feedbin.com/apps , https://github.com/feedbin/feedbin , https://github.com/feedbin/feedbin-api , https://assets.feedbin.com/privacy-policy , https://feedbin.com/blog/2023/03/30/twitter-access-revoked/
- The Old Reader: https://www.theoldreader.com/en/tour/ , https://www.theoldreader.com/en/apps/ , https://theoldreader.com/users/sign_up , https://github.com/theoldreader/api , https://www.theoldreader.com/en/privacy/
- Feeder: https://feeder.co/ , https://feeder.co/pricing , https://feeder.co/blog/1166-follow-telegram-channels , https://feeder.co/rss-to-telegram
- Folo: https://github.com/RSSNext/Folo/blob/dev/README.md , https://github.com/RSSNext/Folo/releases , https://folo.is/pricing

Read-later
- Readwise: https://readwise.io/read , https://readwise.io/pricing , https://docs.readwise.io/reader/docs , https://docs.readwise.io/reader/docs/faqs/ghostreader
- Matter: https://www.getmatter.com/ , https://www.getmatter.com/patron , https://www.getmatter.com/nucleus , https://docs.getmatter.com/api , https://www.getmatter.com/updates/own-your-data
- Instapaper: https://blog.instapaper.com/ , https://www.instapaper.com/premium , https://blog.instapaper.com/post/752995536017178624/bringing-highlights-to-the-open-web
- Wallabag: https://github.com/wallabag/wallabag/releases , https://wallabag.it/en/pricing , https://doc.wallabag.org/
- Karakeep: https://github.com/karakeep-app/karakeep , https://karakeep.app/ , https://karakeep.app/pricing
- Omnivore: https://elevenlabs.io/blog/omnivore-joins-elevenlabs , https://github.com/omnivore-app/omnivore
- Pocket: https://blog.mozilla.org/en/mozilla/building-whats-next/ , https://getpocket.com/farewell

Self-hosted
- FreshRSS: https://github.com/FreshRSS/FreshRSS/releases/tag/1.30.1 , https://github.com/FreshRSS/FreshRSS/blob/edge/README.md , https://github.com/FreshRSS/FreshRSS/blob/edge/docs/en/users/06_Mobile_access.md , https://github.com/FreshRSS/FreshRSS/blob/edge/docs/en/users/10_filter.md , https://github.com/FreshRSS/Extensions/blob/main/README.md , https://github.com/FreshRSS/FreshRSS/blob/edge/app/shares.php
- Miniflux: https://github.com/miniflux/v2/blob/main/README.md , https://github.com/miniflux/v2/releases/tag/2.3.3 , https://miniflux.app/opinionated.html , https://miniflux.app/docs/apps.html , https://miniflux.app/docs/rules.html
- tt-rss: https://github.com/tt-rss/tt-rss/blob/main/README.md , https://tt-rss.org/ , https://tt-rss.org/docs/Plugins.html
- CommaFeed: https://github.com/Athou/commafeed/blob/master/README.md , https://github.com/Athou/commafeed/releases/tag/7.3.0 , https://github.com/Athou/commafeed/releases/tag/7.0.0
- Nextcloud News: https://github.com/nextcloud/news/releases/tag/29.0.0 , https://github.com/nextcloud/news/blob/master/docs/user.md , https://github.com/nextcloud/news/blob/master/docs/clients.md
- Yarr: https://github.com/nkanaev/yarr/releases/tag/v2.9 , https://nkanaev.github.io/yarr/en/
- Glance: https://github.com/glanceapp/glance/releases , https://github.com/glanceapp/glance/blob/main/docs/configuration.md
- RSSHub: https://github.com/DIYgod/RSSHub/releases , https://github.com/DIYgod/RSSHub/tree/master/lib/routes , https://github.com/DIYgod/RSSHub/blob/master/lib/routes/telegram/channel.ts , https://github.com/DIYgod/RSSHub/issues/18260

AI news / aggregators
- Perplexity: https://www.perplexity.ai/discover , https://www.perplexity.ai/curators , https://www.perplexity.ai/changelog/what-we-shipped-july-18th , https://www.perplexity.ai/hub/blog/introducing-comet-plus , https://www.perplexity.ai/hub/blog/comet-is-now-available-to-everyone-worldwide , https://www.perplexity.ai/hub/blog/perplexity-partners-with-elevenlabs-to-launch-discover-daily-podcast (perplexity.ai blocked direct fetches; read via search snippets of its own pages)
- Particle: https://particle.news/ , https://particle.news/plus , https://particle.news/partners , https://particle.news/privacy
- Ground News: https://ground.news/subscribe , https://ground.news/rating-system , https://help.ground.news/en/articles/3189505
- Google News: https://support.google.com/googlenews/answer/9010862 , https://support.google.com/googlenews/answer/9005749 , https://blog.google/products-and-platforms/products/search/personalize-search-discover-news/
- Apple News: https://www.apple.com/apple-news/ , https://support.apple.com/en-us/102209
- Yahoo / Artifact: https://medium.com/artifact-news/shutting-down-artifact-1e70de46d419 , https://www.yahooinc.com/press/yahoo-announces-the-acquisition-of-artifact-the-news-discovery-platform-created-by-instagram-cofounders-kevin-systrom-and-mike-krieger , https://www.yahooinc.com/press/yahoo-news-app-reimagined-with-next-level-personalization-from-artifact , https://www.yahooinc.com/press/yahoo-news-launches-personalized-ai-powered-audio-feature-your-daily-digest
- SmartNews: https://www.smartnews.com/ , https://about.smartnews.com/en/news/2579.html
- ChatGPT Pulse: https://openai.com/index/introducing-chatgpt-pulse/ ; sunset post https://x.com/ChatGPT/status/2067316962225684888 (did not load; wording from search snippet, *secondary*)

Newsletters / Telegram
- Meco: https://meco.app/ , https://docs.meco.app/docs/meco-pro/overview
- Kill the Newsletter: https://kill-the-newsletter.com/ , https://github.com/leafac/kill-the-newsletter
- Readless: https://www.readless.app/
- Stoop: https://stoopinbox.com/ ; shutdown *secondary*: https://inboxreads.co/blog/stoop-inbox-shutting-down-substack-for-scientists
- Telegram folders: https://telegram.org/blog/shareable-folders-custom-wallpapers
- Aggregaat: https://aggregaat.bot/ ; Junction: https://www.junctionbot.io/ai-digests ; Telebrief: https://telebrief.ti1orn.com/ ; TGStat: https://tgstat.com/alerts

Reddit RSS shutdown (no Reddit primary post found)
- Inoreader blog post "Reddit is ending RSS support" (2026-10-01, title seen on https://www.inoreader.com/blog/ )
- *secondary*: https://techcrunch.com/2026/09/30/reddit-is-killing-rss-feeds-ending-public-api-access-because-of-ai-bots/
