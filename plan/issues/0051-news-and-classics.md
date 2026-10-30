# 0051 — News and Classics: what many of my sources cover now, and what they keep citing

Status: **spec** (2026-10-30) for v9.7, with 0050 (owner, 2026-10-30: "yes we can go"). It needs 0050's post links and stories. It replaces 0013's idea of ranking by what I read: only 0.3% of the server's posts are read, so there is nothing to learn from yet.

## The idea (owner, 2026-10-30)
INSIGHT is for two things: **news** (what is happening now) and **classics** (what lasts). Both can be measured from your own sources, without AI and without reading history:
- **News:** several *independent* sources cover the same thing within days.
- **Classic:** your sources keep linking the same page over months, long after it came out.

**What doesn't change:**
- The Main feed stays in time order. Ranking adds two views; it never reorders the feed.
- **Popular isn't the same as yours.** A Gwern essay nobody links can be the best thing this week, and it stays in the feed where it always was.

## How others do it (from knowledge, not checked against their current docs)
- **Techmeme and Memeorandum:** stories grouped across outlets, ranked by how many credible outlets cover them and how fast.
- **Google News:** groups ranked by coverage, freshness, trust in the outlet and who reported first.
- **Ground News:** "covered by N sources".
- **HN and Reddit:** votes, with time decay.
- **Feedly Leo and Artifact:** your own clicks. Our version of that is 0013, later.

## Evidence (prototype on `insight_preview`, 2026-10-30, read only; scripts in `plan/research/dedup-prototype/`)
- **The top story of each week, from 0050's stories plus names (below):**
  - W36: GPT-6 Astra;
  - W38: Snap Specs;
  - W39: Meta Connect (29 posts, 11 voices) far above the rest, then Opus 5.5 / GPT-6 Sol;
  - W41: XREAL Aura;
  - W42: XREAL 1 Pro+.
- **Names in titles find the stories links miss.**
  - Meta's VR Glasses: links joined 2 sources; the name joined 8.
  - Raw, a name rule is noisy: "pc", "ai", "first", and every source added on the same day looked like a burst.
  - With the rules below, **19 of 20** surges were real stories. The miss, "18 Pro Max", mixed a Xiaomi phone and an iPhone.
- **Classic, with no tuning beyond a reference-page filter:** 25 pages linked by 2+ of your voices over 30+ days, including:
  - "Machines of Loving Grace" (3 voices over 414 days);
  - the GPT-3 and scaling-laws papers;
  - "The Bitter Lesson";
  - METR's long-tasks study;
  - "The Adolescence of Technology";
  - Golden Gate Claude.
  - Without the filter, docs and product pages (Claude docs, `claude.com/product/...`) are the noise.
- **The preview's limits:**
  - 94 sources overlap little: 1 to 5 stories a week.
  - No Hacker News on the preview.
  - The server has 41k posts and more overlap, so expect more. The thresholds are a starting point to tune on the server after a few weeks (v9.7's "tuning").

## Decided
### 1. The News score of a story
- **A story's score = reports + ½ × shares + ½ × roundup mentions.** Each voice is counted once, in its strongest role. Roles, voices and mentions are 0050's.
- **The row says it in words, not as a number:** "4 sources · 1 share · in 1 roundup".

### 2. Names in titles (ranking only)
Posts that share a surging name join one story **for News only**. A name never folds rows in the Main feed: it is likely, not certain.
- **A name** is a phrase from a title of 2+ words that are all capitalized or have a digit ("Steam Frame", "Meta VR Glasses", "Opus 5.5"), or one word mixing letters and digits ("GPT-6", "a01"). Pure numbers and lowercase words are not names.
- **It surges when:**
  - within 48 hours, 3+ posts from 2+ voices use it;
  - that is at least 4× its usual 48-hour rate over the 30 days before (counted as at least 0.5);
  - and every source involved was followed for those whole 30 days, so a newly added source's archive isn't a burst.
- **Only the longest name is kept** when a shorter one covers the same posts.
- **arXiv titles are left out.**

### 3. The News view
- **A view next to Main:** stories with 2+ voices whose first post is in the last 7 days, in two parts:
  - "Last 48 hours";
  - "Earlier this week".
  - Each part is ordered by score, then by recency.
- **A story card shows:**
  - the lead's title;
  - who covered it, in time order (the first reporter first);
  - its posts one click away.
- **Reading a story from News** marks it the way 0050 does.

### 4. Classics
- **A classic is a page linked by 2+ of your voices** (not counting the page's own site), with links at least 30 days apart. It can be a stored post or an outside page.
- **Reference pages aren't classics:** an address with a path segment like `docs`, `documentation`, `product(s)`, `pricing`, `support`, `help`, `api`, `reference`, `release-notes`, `changelog`, `wiki`, `articles`, `collections`, `download`, `login` or `signup`, and home pages. This is a vocabulary of page kinds, not a list of sites.
- **Ordered by voices, then by how long it has been cited.**
- **Each card shows:**
  - its title: the stored post's title, or the most common link text;
  - who cited it and when ("Simon Willison, Aug 2025 · …");
  - Read: a stored post opens in the reader, and an outside page through Save any page (0031), fetched only on click;
  - Later.
- **A view next to Main and News.**

### 5. Tracks
News and Classics can be opened for a track:
- they show the stories and classics with at least one post from the track's sources;
- the score counts all your sources.

### 6. How it runs
- **Names are found by the same job as 0050's stories,** over the last 32 days of titles.
- **Classics are an aggregate over post links,** refreshed by that job.
- No AI, no new service.

## Done when
- **Backend tests on a `_test` DB:**
  - the score;
  - each part of the name rule, with a case that must and one that must not: a lowercase word, a new source's archive, a phrase below the rate, a shorter name inside a longer one;
  - Classic's spread and the reference filter;
  - track scoping.
- **On a copy of the preview data:**
  - the weekly top stories above;
  - the name rule's 20 surges, with "18 Pro Max" allowed to stay a known miss;
  - Classics that include the six named above and none of the docs or product pages.
- **Screens** of News and Classics, light and dark, plus an empty week.
- **Thresholds in one place,** so tuning on the server is a one-line change.

## Not in this issue
- Ranking by what I read (0013): later, when there is reading data.
- HN points and Reddit scores.
- Trend charts ("3× the usual volume").
- Stories told in different words, and entities: Mark X. The name rule is the cheap first step toward Mark X's trend detection.
