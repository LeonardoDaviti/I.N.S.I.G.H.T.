# 0050 — One story, many sources: the links inside posts, story groups, "covered by", and Discover

Status: **spec** (2026-10-30), release not decided (proposed: v9.7, where it replaces "also discussed on HN / Reddit"). Prioritization is 0051 and builds on this.

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
- **Scripts:** `~/.cache/insight-checks/dedup-scripts/`, run against an export in `~/.cache/insight-checks/dedup-exp/`. They are outside the repo.
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
