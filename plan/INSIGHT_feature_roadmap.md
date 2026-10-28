# INSIGHT feature roadmap: what we lack and can have

Drafted 2026-10-27 from:
- `plan/INSIGHT_competitors_research.md` (2026-10-10);
- the repo as of `41e23d1`;
- the owner's ideas: Discover, save any page, post referencing, and the serving plan.

This is for discussion, not decided. Nothing here is a commitment to build.

**Effort:**
- **S** = days.
- **M** = one or two weeks.
- **L** = several weeks.

## What changed since the competitor research

**Built** (most of it is not deployed yet):
- The feed finder finds a feed from any page URL (0026).
- Following a page with no feed, through its links and sitemap (`page_watch`, 0028).
- Hacker News through hnrss.org (0017, first version).
- GitHub Trending (0023).
- pipecraft.me, read from its JSON API (0018).
- Continuous reading (0014).
- Smart archiving (0015) and a learned pace (0016).
- Visible jobs and live unread counts (0007, 0021).
- Clean full text, always stored (0008, `e21bf81`).
- The 24-hour image cache (0006).
- The running version on the Ingestion tab (0020).

**Retired:**
- All of analysis (0005): briefings, experts, summaries, chat, notes and the Gemini processor.
- The old research counted these as "analysis-on only". They are now **missing**, and come back as new work in Mark X.

**Decided:**
- Reddit after RSS ends: no change (0025).
- Priority order: future (0013).
- Release updates: future (0024).

**Still missing (checked in code):**
- login;
- OPML;
- search (deferred);
- a PWA manifest or service worker;
- a Fever or Google Reader API;
- translation;
- stored outbound links (`post_relations` exists but is empty).

## 1. Basics
- Login for the UI and API: a password and session; OIDC and passkeys later. **S–M.** The hosted and paid tiers depend on it.
- OPML import and export. **S**
- Full-text search: Postgres `tsvector`, then saved searches as virtual folders. **M**
- Bookmarks: decide the model in 0022 ("Read later" on unread posts, "Keep" as the star). **S** once decided.
- An export screen for posts, stars and saved pages (Markdown or CSV). **S**
- Conditional fetching with `ETag` / `If-Modified-Since` (Ideas list). **S**
- A retention policy for old posts (Ideas list). **S**

## 2. Discover (owner idea)
Sources find you through the people you already read.

**Signals, collected at save time:**
- Telegram: "Forwarded from @channel" and `t.me/<channel>` links in posts.
- X through Nitter: quoted or linked statuses from other accounts. For example, `nitter.local/badlogicgames/status/…` in a post suggests `@badlogicgames`.
- Reddit: links to blogs and articles in posts and comments.
- Blogs: outbound links to other blogs, from the link graph in §4.
- Saved pages from §3: a page you saved by hand suggests its own site.
- Many-of-yours: "6 of your sources link anthropic.com/research" (0004, step 5).

**Pending queue (a Discover tab):**
- Each candidate shows:
  - the platform and handle or host;
  - who mentioned it and how many times;
  - the latest mentions as excerpts;
  - what the feed finder (0026) or `page_watch` (0028) found.
- Actions: **Add** (becomes a regular source, with a track picked), **Preview**, **Not now**, **Never** (mutes the host or handle).
- Ranked by distinct mentioners × recency. Already-followed and muted candidates never show.

**Effort:** **M** for Telegram, Nitter and links. **S** for each new signal after that.

## 3. Save any page (owner idea)
One feature with several ways in. The browser extension and the bookmarklet are two of them.

- **Ways in:**
  - paste a URL in the app — **S**;
  - a bookmarklet — **S**;
  - the share sheet from the PWA (§5) — **S**;
  - a browser extension, which can also subscribe — **M**;
  - email-in — **M**.
- **How it works:**
  - The page is fetched with the same full-text extractor as feeds (0008).
  - It is stored as a post under a built-in "Saved" source, so it is read, kept and searched like any post.
  - It feeds Discover: "you saved 3 pages from this blog; it has a feed, so follow it?"
- **Links with:**
  - 0022 (a saved page is "read later" by default);
  - §4 (a missing link target can be saved with one click).

## 4. Links between posts (0004, owner example)
A post that links an earlier post you already have shows that post as its **previous** or **cited** post, even with no in-app link.

- **Example:** "OpenAI 'rogue' agent activities found on Wikimedia projects" links `simonwillison.net/2026/Sep/4/rogue-agent-wikis/`. That post is in the archive, so the reader shows it as the previous post and opens it in INSIGHT.
- **How it works:**
  - Extract outbound links at save time into `post_links`, with noise rules (tags, share links, tracking parameters).
  - Resolve them against `normalized_url` and `canonical_url` into `post_relations(cites)`.
  - When a target arrives later, back-fill the links that were waiting for it.
- **Reading view:**
  - Quiet **Cites / Cited by** lists on the post page.
  - "Previous in this thread" when a source cites its own earlier post.
  - An in-system target opens in the reader. A missing target shows its host, with **Save** (§3).
- **Later:** walk the chain to the source of truth (Simon → NYT → Anthropic).

**Effort:** **M** for extraction, resolution and back-fill. **S** for the reading view.

## 5. Phone and clients
- Installable PWA with a share-sheet target. **M**
- Offline reading of the unread window. **M**
- A Fever or Google Reader API, so Reeder, NetNewsWire and ReadKit can connect. **M**
- Native apps. **L**; not needed if the PWA and the API exist.

## 6. Reading tools
- Your own highlights. **M**
- Notes on posts. **S–M**; these were retired with analysis.
- Read-aloud with browser voices (**S**) or better voices (**M**).
- Remembering where you stopped in a long post (0022). **S**
- Post versions: keep and show the text before an edit (Ideas list). **M**
- Reading settings: font, size and column width. **S**
- PDF and EPUB. **L**
- Send to Kindle or Kobo. **M**

## 7. Sources
- Newsletters, through email-in (§3). **M**
- Podcasts: a player (**M**), transcripts through Whisper (**M**).
- Native Mastodon and Bluesky kinds. **S–M**
- Hacker News as its own kind, with comments (0017). **M**
- Reddit comments (0012); waits for API app approval.
- GitHub following and release updates (0023, 0024). **M**
- RSSHub as a bridge for hundreds of platforms. **S**
- Keyword alerts and Google News queries. **S**

## 8. Organisation
- Rules per post: mute words, auto-star, auto-read. **M**
- Your own tags. **S–M**
- Priority order (0013). **L**; future.
- Grouping one story across sources by shared links (from §4). **M**
- Source hygiene: "not opened in 60 days" and "dead for 30 days", with a prune suggestion. **S**

## 9. AI, rebuilt in Mark X
- Choice of provider: OpenAI, Anthropic, Gemini, or Ollama for local models. **M**
- **Translation:** store an English version beside the original, with a toggle. **M.** The hosted tier (§13) needs it for the Russian sources.
- Summaries and daily or track briefings (0002). **M** each.
- Questions across the library, with citations (pgvector is installed). **M**
- Entity pages and milestones (0001). **L**
- An MCP server over your reading. **S–M**
- Audio briefing. **M**
- Auto-tags. **S**

## 10. Notifications
- Push through ntfy, Gotify or Pushover, for new posts or keyword matches. **S**
- Email digest. **S–M**
- Post to Telegram, Discord or Slack. **S**

## 11. Sharing and integrations
- Webhooks. **S**
- Publish a track or tag as RSS. **S**; the hosted tier reuses it.
- Export to Obsidian, Notion and Readwise. **M**
- A stable API with tokens. **M**
- Share-to buttons. **S**

## 12. Look and accessibility
- Layouts: list, cards, magazine. **M**
- Custom CSS. **S**
- A translated interface. **M**; only worth it for the hosted or paid tiers.

## 13. Serving: the three tiers (owner plan)

**1. Free self-hosting, not for commercial use.**
- Pick a source-available licence such as PolyForm Noncommercial, or AGPL plus a commercial licence. Note that a non-commercial licence isn't "open source" in the OSI sense.
- Needs:
  - a one-command install, made lighter by merging API and ingestion (`plan/INSIGHT_merge_api_ingestion_research.md`);
  - optional Telegram and Nitter;
  - an install guide;
  - login.

**2. A hosted public copy of the owner's sources.**
- Needs:
  - a public read-only mode, with viewers' read state kept in their browser or per account;
  - a "recommend a feed" form, which lands in the Discover queue (§2);
  - English translation of the Russian sources, with the original one click away (§9).
- **Copyright:**
  - Republishing other people's full text in public is a legal risk.
  - Paid Substack posts, read through the owner's cookie, must never appear there.
  - The safe default is title, excerpt and a link, with full text only where the source's licence allows it.

**3. Paid hosted instances.**
- Use one instance per customer. This fits today's single-user design, so no multi-user rewrite is needed.
- Needs:
  - provisioning automation;
  - billing;
  - login;
  - backups (the owner's no-backups rule can't apply to paying customers);
  - per-instance resource limits;
  - monitoring.
- Telegram needs each customer's own session or bridge.

**Effort:** **L** for tiers 2 and 3. The groundwork for them (login, a lighter install, translation, public read-only mode) is useful on its own.

## Not worth chasing
- Publisher bias ratings (Ground News): these need a proprietary database.
- Social features (comments, blurblogs) and team workspaces.
- Multi-user in one instance: per-customer instances avoid it.
- SOC 2: not needed unless business customers ask.

## Suggested order
1. **Make it safe to share:** login, OPML, search, bookmarks (0022), save any page (§3).
2. **Links and Discover:** links between posts (§4), then the Discover queue (§2). These are INSIGHT's own features; no competitor has them.
3. **Phone:** PWA, share sheet, Fever API, push notifications.
4. **Mark X AI:** provider choice with Ollama, translation, briefings.
5. **Serving:** a lighter install and licence (tier 1), then the public copy (tier 2), then paid instances (tier 3).
