# 0050 — One story, many sources: the links inside posts, story groups, "covered by", and Discover

Status: **built, not deployed** (2026-10-30, migration 0039) for v9.7 (owner, 2026-10-30: "yes we can go"). It replaces "also discussed on HN / Reddit". Prioritization is 0051 and builds on this.

## The idea
Every post carries links. Saved once, as data, those links answer three questions without AI:
- **Is this the same story?** Two sources link the same page within days, or one cites the other.
- **How many of my sources covered it?** That count is the signal 0051 ranks by.
- **What do my sources read that I don't follow?** Sites they keep linking are Discover's suggestions.

**Built to scale:**
- **Mark X plugs in.** It adds new ways of joining posts (meaning, language, entities) to the same story table, without a second system. The first reporter and credibility per source are later computed on these stories.
- **The hosted tier needs no separate design.** Each instance computes its own stories the same way.

## Evidence (prototype on `insight_preview`, 2026-10-30, read only)
- **Data:** 7,735 posts from 94 sources (2,485 site posts, 3,439 arXiv, 898 Reddit, 537 YouTube, 356 Telegram, 20 X). There is no Hacker News source on the preview; the server has one.
- **Scripts:** `plan/research/dedup-prototype/` (export, report, and the expected output). The real code must reproduce it.
- **Links:** posts hold 13,830 links. After the filters below, 5,031 remain:
  - own site: 6,891;
  - a source's signature: 1,093;
  - media files: 815.
- **Joining through every link fails.** A weekly roundup (skarredghost's "XR Week Peek" links 24 stored posts) chained unrelated stories into groups of 26.
- **The rules below work.** With them, the prototype found:
  - 24 stories covered by 2+ independent sources;
  - 18 groups of pure copies (Telegram forwards, one Reddit user posting to several subreddits).
  - **None is wrong** on review. Examples:
    - "Introducing Claude Opus 5": Anthropic, Simon Willison and two Telegram channels;
    - Snap's AR glasses: TechCrunch and a Telegram channel (in Russian);
    - "3 Google updates from Galaxy Unpacked": blog.google and r/androidxr.
- **Links cross languages for free:** Russian Telegram posts join English articles through the link they share.
- **Grouping hides little:** 56 rows of 7,735 (0.7%) would fold under another post. The value is the count, not a shorter feed.
- **Links miss stories that nobody links.** XR sites cover the same launch without linking each other: Meta's VR Glasses had 19 posts from 8 sources, but links joined only 2 of them. Names in titles find those stories; that's 0051's job, because it is likely, not certain.

## Decided
### 1. Post links (the base)
- **A table of the outside links in each post,** filled when a post is saved, plus a one-time background fill for the posts already stored (as search's backfill did). Each row holds:
  - the normalized target address (0049's normalizer);
  - its site;
  - its place in the post: first link or not;
  - the link's own text, which becomes the title when the target isn't stored.
- **Not saved:**
  - links to the post's own site;
  - media files;
  - a source's signature: a link found in 25% or more of a source's posts, at least 4 of them (subscribe buttons, the author's profile, a sponsor);
  - Reddit's own `[link]`, `[comments]` and user links, and other links back into the platform the post came from.
- **YouTube descriptions** count as the post's text when they are stored as HTML. Otherwise YouTube has no links for now.

### 2. Who is a voice
- **One voice per site** for websites (the site's registrable domain: `blog.google` and `google.com` are one).
- **One voice per channel or account** for Telegram, X and YouTube.
- **On Reddit, the person who posted, not the subreddit.** One user posting to three subreddits is one voice.
- **Posts by the same voice never join each other** through links. Several roadtovr.com articles on one launch are one voice, counted once.

### 3. When posts are one story
A story is a group of posts from 2+ sources.
- **Same text:** the same `content_hash` (at least 120 characters of text), within 30 days. These are copies.
- **Same title:** the same normalized title (at least 5 words), within 7 days.
- **The same link:** posts by 2+ voices link the same outside page within 72 hours.
- **A citation:** a post links a stored post by another voice, within 72 hours of it.
- **A roundup** is a post with 3+ links into stories. It joins only the story of its first link and **mentions** the others. A mention counts in 0051's score but joins nothing.
- **Not used:** home and profile pages (a site root, or one path segment). They say who, not what.
- **Not in this issue:**
  - stories told in different words with no link or title in common (Mark X: meaning);
  - names in titles (0051, ranking only).

### 4. Each post's role in its story
- **A report:** its own writing.
- **A share:**
  - a copy of an earlier post's text or title by another voice (a forward);
  - a Reddit or HN post that is mostly a link (fewer than 60 words of its own).
- **The lead** is the story's first report among the posts the current view shows. If a story has no report, its first share leads.

### 5. In the reader
- **Main feed and tracks show a story once,** at its lead. The row says "covered by 3 · Anthropic, Simon Willison, +1", and a click opens the other posts.
- **A source's own view and search show every post,** as today.
- **Opening the lead marks its copies and shares read.** Other reports (someone's own take) stay unread and stay reachable from the row.
- **The Main feed's unread count counts rows,** so folded posts are not counted twice.
- **When a later post joins an old story,** it never brings it back to the top of the feed. 0051's News view is where a growing story shows.

### 6. Discover
- **A candidate is a site or account that 3+ of your voices link,** in 2+ article-like pages (a date in the path, or a slug of 4+ words) that make 40%+ of its links, and that you don't follow.
- **On a platform, the unit is the account,** not the site: `x.com/karpathy`, `github.com/openai`, `huggingface.co/blog`. A host is a platform when your links to it reach 8+ different first path segments and none of them holds half. This is measured, not a list.
- **Each suggestion says why:** "linked by 6 of your sources (Simon Willison, …), 9 articles", with those articles one click away.
- **Following goes through the feed finder** and page watching (`source-adding-rule`), like every other way of adding a source. Nothing is fetched until you click.
- **"Not interested"** hides a suggestion for good. A source you removed (Tidy up, 0046) is never suggested again.
- **It lives in Sources** as a "Suggested" list.

### 7. How it runs
- **Stories are recomputed by a job after each fetch run,** over the last 30 days of posts. Older stories are frozen.
  - It's deterministic and idempotent.
  - A story is keyed by its first post, so a recount doesn't reshuffle what you saw.
  - The prototype does 7.7k posts in seconds; the server's last 30 days are fewer posts than that.
- **No new service and no AI.** The tables are post links, stories and story posts, plus a role and the reason each post joined (text, title, link, citation), so Mark X can add new reasons later.

## Done when
- **Backend tests on a `_test` DB** cover each of these:
  - every joining rule, with one case that must join and one that must not;
  - roundups;
  - voices: two Reddit subreddits by one user count as one voice;
  - roles and the lead;
  - read propagation;
  - unread counts;
  - Discover's filters;
  - a second job run changing nothing.
- **The prototype's preview numbers are reproduced** by the real code on a copy of the preview data:
  - 24 stories with 2+ voices;
  - 18 copy groups;
  - Discover's top suggestions include openai.com, metr.org, darioamodei.com, transformer-circuits.pub and epoch.ai;
  - Discover does not suggest en.wikipedia.org, store pages, or sites you follow.
- **Screens** of a folded row and its opened list, light and dark.
- **A read-only count for the server,** run by the owner before deploying: how many posts it has links for, and how long the backfill took on the preview.

## Not in this issue
- Ranking (News, Classic): 0051.
- Stories without a shared link or title, translation and entities: Mark X.
- HN points and Reddit scores as popularity: later, if News needs them.

## Built
- **The rules** (pure, ported from the prototype; thresholds in one place):
  - `backend/insight_core/utils/post_links.py`: a post's outside links from its `content_html`, made absolute and normalized with 0049's normalizer; not kept: the post's own site, media files, links back into its platform (Reddit, HN, X, t.me, YouTube). Also `site_of`, `is_home`, `is_article`, the source kind, the Reddit author.
  - `backend/insight_core/utils/story_rules.py`: voices, the four joining rules, roundups and mentions, roles, voices per story, Discover's filters and platform accounts.
  - **Voices and places, as the prototype:** a story's voices count people (on Reddit the poster), but joining by links and telling a copy go by where a post was said (on Reddit the subreddit). One person posting a link to two subreddits is one story of one voice, a copy.
- **Migration 0039** (`0039_post_links_and_stories.sql`), all derived and recomputable:
  - `post_links (post_id, target_url, target_site, position, link_text, boilerplate)`: position 0 is the first link (0051's first-link flag); `link_text` is the title of a page that isn't stored; `boilerplate` marks a source's signature (25% of its posts, 4+) and links to its source's own site (the most common site of its posts). `posts.links_scanned_at` says a post's links were read.
  - `stories (id = its first post, first_at, voices)`, `story_posts (post_id, story_id, role report|share, reasons text[] of text/title/link/citation, voice)`, `story_mentions (story_id, post_id)` for roundups.
  - `discover_hidden (key, reason not_interested|removed)`.
- **Saving:** the saver reads a post's links from what it stored (inside the existing after-save savepoint: still at most two savepoints a post); a full-text repair clears `links_scanned_at`, so the next job reads them again.
- **The story job** (`services/stories_service.py`, `db/repo_stories.py`): reads the links of every post not read yet (500 a transaction), marks boilerplate, groups the posts of the last 30 days (the first run: every post), writes only what differs; a story begun before the window is frozen. One at a time (advisory lock), never raises. It runs after a fetch run that saved posts (the runner's `stories` port) and in the background when the backend starts (the post links backfill). Its last summary is in `system_settings.stories`.
- **The reader** (`db/repo_reader.py`):
  - The Main feed and a track, Show unread or all, show a story once at its lead (its first report the view shows, else its first share); the lead carries `story` {id, voices, sources, posts}. A source's view, by source, Later, Kept, History (0052) and search show every post; History has its own query and never folds.
  - Marking read (open, the circle, mark-through) a story's report reads its shares, not its other reports; the returned ids include them, so Undo works. Mark-through marks only the rows the unread view shows.
  - The Main feed's and a track's unread counts count rows (a story once); a source's count stays posts.
- **Discover:** `GET /api/sources/suggested`, `POST /api/sources/suggested/hide {key}`.
  - On a platform (a host whose links reach 8+ first path segments, none half: measured) the unit is the account, and only the account you follow is followed. A source's account comes from its address, read by the kinds' own parsers: a Telegram bridge feed (`tg.i-c-a.su/rss/<channel>`, `telegram.local/rss/<channel>`) or channel is `t.me/<channel>`, a Nitter feed `x.com/<user>`, a subreddit `reddit.com/r/<sub>`, a YouTube channel `youtube.com/channel/<id>`, any other address the account its path is under (`github.com/<owner>`). Following one channel hides no other. Off a platform the unit stays the site.
  - A removed source (any delete, Tidy up included) is never suggested again: a website by its site, any source by its account.
- **UI** (design decision 035; `pages/reader.md`, `pages/sources.md`):
  - A folded row has one quiet line under its excerpt, `▸ covered by 4 · Anthropic News, @denissexy, +2`, which opens the story's other posts (unread dot, source, title linking to the post, `· share`, date).
  - Sources gets a `suggested` tab: each site or account with `linked by 7 of your sources (…) · 32 articles` opening its most linked articles, **Follow…** (Add source opened on its address: the feed finder and page watching) and **Not interested**.
- **Tests:**
  - Backend: `test_stories.py` (31): links; each joining rule with a must-join and a must-not; one place never joining itself through links; a Reddit cross-post as one story of one voice; citations; home pages; roundups and mentions; roles; Discover's filters, platform accounts, following one channel hiding no other, a source's account from its address; the saver; backfill and signatures; stories, roles and reasons; a second run (full and windowed) changing nothing; a frozen story; the folded feed and the lead; History not folding; read propagation; mark-through; row counts; a removed source; the Discover service. Plus the runner calling the job, and 0049's table check knowing the derived tables. **Suite: 913 tests, OK** (after merging main at e49b520).
  - Frontend: the folded row and its list (`FeedList.test.tsx`), the suggested tab (`SourcesConfig.test.tsx`), `lib/story.test.ts`. Typecheck, lint, **170 node + 621 vitest tests**, build OK.
  - The reader's initial JS: **477,646 bytes**, +0.54% on the 475,065 baseline (0052's change included).
- **Screens** (dev server against the copy of the preview, light and dark; not committed): `~/.cache/insight-checks/0050-shots/` (`0050-folded-row-*`, `0050-folded-row-open-*`, `0050-feed-folded-*`, `0050-discover-*`).

### Reproduction on a copy of the preview (2026-10-30)
`insight_preview` copied by pg_dump into a `_test` database, migrations 0038 and 0039 run, then the job.

| | prototype (`expected-report.txt`) | built |
|---|---|---|
| stories with 2+ voices | 24 (20 × 2, 3 × 3, 1 × 4) | **24** (20 × 2, 3 × 3, 1 × 4), the same groups |
| copy groups (1 voice) | 18 | **18** |
| posts in stories | 98 | 96 |
| Discover | 31 sites and accounts | **the same 31, same counts and order** (openai.com 7 voices / 32 of 49 … 9to5mac.com) |
| backfill and first run | | 7,718 posts, 1,237 with kept links (4,973 kept links), **2.3 to 3.4 s**; a second run 0.05 s, 0 rows changed |

The differences, explained:
- **2 fewer posts in stories:** Simon Willison's `#atom-everything` copies that 0038 merges (the same stories, one row fewer each).
- **Links:** 12 fewer links kept than the prototype (5,019 vs 5,031 on the same rows): the post's own site is dropped per post, as the spec says, besides the source's own site (digilens.com posts on other hosts, aleksagordic.com on medium.com), and links into X from X posts.

Discover suggests openai.com, metr.org, darioamodei.com, transformer-circuits.pub and epoch.ai; not en.wikipedia.org, a store, or a followed site. It still lists facebook.com, chatgpt.com and support.claude.com, the prototype's known misses (the feed finder turns them down on Follow…).

Folding on the copy: the Main feed shows 2,173 rows for 2,215 posts (42 folded); its unread count is 1,992 rows for 2,030 unread posts. Over every post, 54 of 7,718 fold (the spec's 56, less the 2 merged copies).

### Before deploying: a read-only count on the server
From the compose directory (service `postgres`, user and database `insight`; change `-U` / `-d` if `.env` sets others). The backfill reads every post's HTML once, in the background, after the backend starts: 3.4 s for 7,718 posts on the preview, so expect well under a minute for 41k.

```sh
docker compose exec -T postgres psql -U insight -d insight -v ON_ERROR_STOP=1 -c "SET default_transaction_read_only = on" -c "SELECT count(*) AS posts, count(*) FILTER (WHERE content_html ~* '<a\s[^>]*href') AS posts_with_links, count(*) FILTER (WHERE COALESCE(published_at, fetched_at) >= now() - interval '30 days') AS posts_last_30_days FROM posts"
```
On `insight_preview` it gives `7735 | 2546 | 466` (posts_with_links counts any link, own site included; 1,237 keep an outside one).

### Left open
- **`blog.google` and `google.com` are not one voice.** The spec calls them one site, but by registrable domain `blog.google` is its own (`.google` is a top-level domain). Making them one needs a list of who owns what, which the rules avoid. The prototype treats them as two too.
- **"A roundup is a post with 3+ links into stories":** built as the prototype does it, 3+ anchors (article links), since which links are "into stories" is only known after grouping.
- **Signatures are stored, marked:** a source's signature is known only over all its posts, so its links are saved and marked `boilerplate` by the job rather than not saved; nothing reads them.
- **A frozen story** (begun more than 30 days ago) takes no new posts; a late copy of a month-old post starts a new story.
- **Discover's platform test is measured:** a host with few links (fewer than 8 first segments) is treated as a site, so following one account there still hides the host.
- A post that joins an old story under Show unread can lead it (it is the first unread report shown); nothing marks late shares of a story already read.

## Real data (the server copy, 2026-10-30)
Measured in the lab on a copy of the server's 41,543 posts (`backups/lab/`, `insight_lab`):
- **Two bugs, fixed:**
  - one LessWrong link whose "port" was a sentence made the URL parser raise, and the whole story job stopped: no stories at all on the server;
  - a cited stored post with a one-segment address (`blog.cloudflare.com/yandex-outage`) was taken for a profile page, so citations of it never joined.
- **The Cloudflare scenario passes:** adding the Cloudflare blog folds @denissexy's post (2.8 h later, citation) under Cloudflare's "Yandex outage" post. Every check a–g held.
- **Stories:** 572, about 2% of Main-feed rows folded.
  - Joins through links, text, titles and citations are precise.
  - Joins through a roundup's first link are right about 85% of the time (34 of 40 sampled). The errors are multi-topic digests (AINews "not much happened today", weekly digests, "Links (N)").
  - Two rules were tested: roundups join nothing, and digests (anchors in 2+ stories) join nothing. Each removed about as many right joins as wrong ones, so no change. Telling a digest from a single-topic post with many links needs to know what the post is about: Mark X's "same story?" check.
- **Discover:** the "platform" test (8+ first path segments) fired on 249 hosts. It split publishers by year or section (nytimes.com/2026, reuters.com/world) and hid blogs whose posts sit at the root: blog.cloudflare.com, linked by 16 voices, was never suggested.
  - It now uses the sites where INSIGHT follows one account: its kinds (Reddit, X, Telegram, YouTube) and the feed finder's platforms (GitHub, Medium).
  - That removes 100+ fragments and keeps publishers whole. The article rule was right; it wasn't the cause.
  - **Still noise:** web.archive.org, app links (claude.ai, chatgpt.com).
