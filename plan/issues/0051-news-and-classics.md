# 0051 — News and Classics: what many of my sources cover now, and what they keep citing

Status: **built, not deployed** (2026-10-30, migration 0040; design decision 036) for v9.7, with 0050 (owner, 2026-10-30: "yes we can go"). It needs 0050's post links and stories. It replaces 0013's idea of ranking by what I read: only 0.3% of the server's posts are read, so there is nothing to learn from yet.

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
  - it was said at most once in the 30 days before. Changed 2026-10-30 from "4× its usual 48-hour rate", measured on the server's 41k posts: names never said before were real stories ~88% of the time, said once ~75%, said twice or more ~27% (see "Real data" below);
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
- **A classic is a page linked by 2+ of your voices** (not counting the page's own site), with links at least 180 days apart, counted from the page's own date when it's a stored post, else from the second voice's first link. It can be a stored post or an outside page. (Changed 2026-10-30 from "30 days apart, from the first link", measured on the server's data: see "Real data".)
- **Reference pages aren't classics:** an address with a path segment like `docs`, `documentation`, `product(s)`, `pricing`, `support`, `help`, `api`, `reference`, `release-notes`, `changelog`, `wiki`, `articles`, `collections`, `download`, `login` or `signup`, and home pages. This is a vocabulary of page kinds, not a list of sites.
- **Ordered by voices, then by how long it has been cited.** A page's age never counts against it.
- **Cited again comes first:** a classic one of your sources cited in the last 7 days goes to the top, marked "cited again this week". Old doesn't mean unimportant: it can be the foundation of something new.
- **Each card shows:**
  - its title: the stored post's title, or the most common link text;
  - who cited it and when ("Simon Willison, Aug 2025 · …");
  - Read: a stored post opens in the reader, and an outside page through Save any page (0031), fetched only on click;
  - Later;
  - Hide: one control for both "I know it" and "not for me". A hidden classic never comes back. Reading one through INSIGHT stores it, and it then counts as read like any post.
- **A view next to Main and News.**
- **Background under a post:** when a post you read links a classic, one quiet line under it: "Builds on: Scaling Laws for Neural Language Models · cited by 3 of your sources". It shows at most 2, and nothing when there are none.
- **Discover leans on it:** a suggested site that holds classics comes first, and its card says "2 classics". No new section.

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
  - cited again first, Hide, Background (at most 2; none without a classic), Discover's order;
  - track scoping.
- **On a copy of the preview data:**
  - the weekly top stories above;
  - the name rule's 20 surges, with "18 Pro Max" allowed to stay a known miss;
  - Classics that include the six named above and none of the docs or product pages.
- **Screens** of News and Classics, light and dark, plus an empty week, and a post with its Background line.
- **Nothing more:** no new settings, no badges beyond these lines, no extra views.
- **Thresholds in one place,** so tuning on the server is a one-line change.

## Not in this issue
- Ranking by what I read (0013): later, when there is reading data.
- HN points and Reddit scores.
- Trend charts ("3× the usual volume").
- Stories told in different words, and entities: Mark X. The name rule is the cheap first step toward Mark X's trend detection.

## Built
- **The rules** (pure, ported from the prototype): `backend/insight_core/utils/news_rules.py`. **Every 0051 threshold is at its top** (`NEWS_DAYS`, `NEWS_RECENT`, the weights, `NAME_*`, `CLASSIC_*`, `BACKGROUND_SHOWN`, the `REFERENCE` vocabulary): tuning on the server is a one-line change.
  - Names: a 1-3 word phrase of a title, every word capitalised or with a digit, not starting or ending on a small word; one word only when it mixes letters and digits. A surge as the prototype judges it: a name's **first** burst (3+ posts, 2+ voices, 48 hours, 4x the usual rate, at least 0.5) is the one judged, and a source added in the 30 days before it means the name does not surge. Only the longest name is kept when a shorter one's posts are a subset of it. arXiv left out.
  - News stories: 0050's stories joined by the surging names, kept with 2+ voices (0050's `count_voices`: copies of one text are one voice). Roles are 0050's `roles` over the joined group; each voice once in its strongest role, report, share, then roundup mention (0050's `story_mentions`).
  - Classics: as the prototype (anchors of kept links, no home pages; a stored post counts from its date, less its own voice; outside pages through the reference filter), voices are 0050's (a Reddit poster, not a subreddit); a link from the Saved source is no voice; a stored post counts from the earlier of its date and its first link (so a classic you saved does not vanish).
- **Migration 0040** (`0040_news_and_classics.sql`): `news_stories` (id = first post, first_at, voices, reports, shares, mentions, score), `news_posts` (post, story, role, voice, the joining name), `classics` (target_url, post_id, voices, first_at, last_at, title, citers jsonb), `classic_hidden`. All derived but the last.
- **The job:** `services/news_service.py` `refresh`, called by 0050's story job (`StoriesService.regroup`) on its transaction: names over the last 32 days of titles (every title on a full run), News over the job's window (the tables hold that window), every classic over all kept links; writes only what differs. Its counts join the job summary (`names`, `news`, `classics`, `*_changed`).
- **API:** `GET /api/news?scope=all|folder:<id>` (a FeedPage of leads, each with `story` and `news` {part, first_at, reports, shares, mentions, score}; the lead is the story's first report among the scope's posts); `GET /api/classics?scope=…`; `POST /api/classics/hide {url}`; `background` (at most 2) in `GET /api/posts/item/{id}`; Discover's suggestions carry `classics` and those holding some come first.
- **UI** (design decision 036; `pages/reader.md`, `post.md`, `sources.md`): `View stream / by source / news / classics` on the Main feed and tracks (Show, Posts, the unread count, the Later line and the pill are left out there). News reuses the feed's list and row (`PostList` `ranked`: two part headers, rows open on their own, no Shift+A) and 0050's story line in its own words; Classics is its own list (title reads, Later, Hide). Both views are lazy chunks. The post page has the Background line; Discover's line ends ` · 2 classics`.
- **Tests:**
  - Backend `test_news.py` (28): the score and the lead; names (what is one); each part of the name rule with a must and a must-not (too few posts, voices, too slow; a lowercase word; a new source's archive; below the rate at 20, 12 and 5 posts; a shorter name inside a longer one; arXiv); News joining by a name for News only, two independent voices, roundup mentions; classics' spread, a stored post's date and own voice, the reference filter, the order; on the database: News in two parts, a week later nothing, track scoping (led by the track's post, scored over all), reading from News, a second run changing nothing, classics cited again first with no reference page, Hide (and after a rerun), Background (at most 2; none without a classic), a track's classics; Discover's order (committed rows); the routes. 0049's table check knows the new tables. **Suite: 941 tests, OK.**
  - Frontend: `ReaderPage.news.test.tsx` (8), `PostDetailPage.background.test.tsx` (2), `lib/news.test.ts`, `lib/classics.test.ts`, `lib/story.test.ts`. Typecheck, lint, **174 node + 631 vitest tests**, build OK.
  - The reader's initial JS: **479,521 bytes**, +0.94% on the 475,065 baseline (+1,875 on 0050's 477,646). News and Classics are lazy chunks (1.3 KB, 4.2 KB); their helpers live apart from `lib/story.ts` so the feed row does not carry them. No ⌘K entries: they did not fit the budget and the spec asks for nothing more.
- **Screens** (dev server against the copy of the preview, light and dark; not committed): `~/.cache/insight-checks/0051-shots/` — `0051-news-track-*` (Smart Glasses Development, News read at 2026-09-24 09:00), `0051-news-open-*` (a story's posts opened), `0051-news-main-*`, `0051-news-empty-week-*` (now: nothing in the last 7 days), `0051-classics-*`, `0051-post-background-*` ("2026 in LLMs (so far)").

### Reproduction on a copy of the preview (2026-10-30)
`insight_preview` copied by pg_dump into a `_test` database, migrations 0038 to 0040, then a full job (0.6 s; a second run: 0 rows changed).

| | prototype (`expected-report.txt`, `names.py`) | built |
|---|---|---|
| W36 | GPT-6 Astra 3.0, Claude Fable 5.1 3.0 | **GPT-6 (6 posts) 3.0**, Claude Fable 5.1 3.0 (tied; News orders ties newest first: GPT-6) |
| W38 | Snap Specs 4.5 (4r 0s 1m, 6 posts) | **Snap Specs 4.0** (4r, 6 posts), Half-Life: Alyx 2.0 |
| W39 | Meta Connect 11.5 (11r 1s, 29 posts), Opus 5.5 / GPT-6 Sol 3.0 | **Meta Connect 11.5 (11r 1s, 29 posts), Opus 5.5 / GPT-6 Sol 3.0 (6 posts)** |
| W41 | XREAL Aura 3.5 | **XREAL Aura 3.5** |
| W42 | XREAL 1 Pro+ 3.0 | **XREAL 1 Pro+ 3.0** |
| name surges | 20 (after the prototype's filters and longest-name) | **the same 20** (`hugging face` … `1 pro`), "18 Pro Max" the known miss |
| classics | 25 | **the same 25, same voices and days**, the six named among them; no docs or product page |
| News stories (all weeks) | | 32 |

A lead's title is 0050's lead (its first report), so a row may read differently from the prototype's pick (the longest site post): W39 is led by "Meta Connect 2026: 6 devices and AI services we expect to see".

The differences, explained:
- **Each voice once, mentions included:** a roundup by a channel that already reported the story no longer adds ½ (W38 Snap Specs 4.5 → 4.0; W28 "Rewriting Bun in Rust" 2.5 → 2.0; W30 HuggingFace 3.5 → 2.5).
- **Copies are one voice:** a report and its verbatim copy alone are not News (0050's voices; the spec's "independent"): the prototype's W29 "Две новости в утро воскресенья" (1r 1s 5m) and "Andon Labs" (1r 1s) are not stories here.
- 0038's merged Simon Willison copies make some stories one post smaller ("hugging face" 5 → 3 posts, W32 6 → 4).
- On the preview the XR sources are a track out of the Main feed: the Main feed's News holds only the AI stories; the track's News holds Meta Connect (as the screens show).

### Left open
- **The name rule, read literally, finds 24 surges, not 20.** "Every source involved was followed for those whole 30 days" checked on every window (not only a name's first burst) lets later windows through: `steam frame`, `smart glasses`, `18 pro`, `android xr`. `smart glasses` then joins 15 posts into one W38 "story" that outranks Snap Specs. Built as the prototype (the first burst decides), which gives the spec's 20; the alternative is one line in `surges`.
- **Classic titles from link words are often poor** ("over 100,000 commits", "Kaplan et al.", "on March 24th"): the spec's "most common link text" (we keep only link words of 3+ words). Reading the page's own title would need a fetch; left for tuning.
- **News lead:** the first report (0050's), not the prototype's longest site post; in a track, the first report among the track's posts.
- **The News tables hold the job's window:** a windowed run drops News older than 30 days (News shows 7); a full run fills every week (the reproduction).
- **The 32 days of titles:** a surge 5 days ago is judged on 25 days of baseline in a windowed run.
- No ⌘K entries for News and Classics (budget, and "nothing more").

## Real data (the server copy, 2026-10-30)
Measured in the lab on a copy of the server's 41,543 posts:
- **Names:** 191 surges under the 4× rule. By how often the name was said in the 30 days before:
  - never: 105 surges, ~88% real (26 of 30 sampled);
  - once: 26, ~75% (6 of 8);
  - twice or more: 60, ~27% (3 of 11). Generic phrases like "has been", "world cup", "open weights" and "time series" all came from this group.
  - A one-word name can't start with a digit: of 27 one-word surges, the 5 that did were sizes ("30b", "128gb", "2m"), and no real name did.
  - The rule is now "at most once". Its cost: an ongoing story whose name was already in use isn't found by name (RTX Spark, Le Chonk; the preview's Steam Frame launch day).
- **Names read the stored titles, not the shown ones:** after the glued-title fix (Telegram), names from shown titles were measured. They found some real stories the stored ones miss (Gemini 4 Argon, Sonnet 5.5) and missed others they find (GLM 5.3, Kimi-K3), with as much noise. Not clearly better, so no change.
- **Classics:** 1,244 under the 30-day rule, and all of the top 30 were "cited again this week".
  - **Most were news with legs,** not classics: the Hugging Face incident, Navier–Stokes, "We Must Pace the Frontier". By citation spread, a random sample of each bucket held about 15% real classics at 30–60 days, ~45% at 90–180 days and ~80% at a year or more.
  - **A Gwern page dated 2023** links a 2026 post (GPT-6 Astra), which gave it a 1,307-day spread. Gwern rewrites pages under their old dates, and 62 classics started from a Gwern link.
  - **The rule now:** 180+ days, counted from the second voice's first link, so one voice's date alone can't make a classic. That leaves 172 classics, ~80% real in a random sample of 30. "Cited again this week" (30 of them) now shows the Bitter Lesson, "The Adolescence of Technology", the Law of Leaky Abstractions (2002), grokking, Sleeper Agents, emergent misalignment and Toby Ord on RL scaling.
  - **What's left as noise:** code repositories and model pages (llama.cpp, vLLM, OpenClaw, Codex CLI, Hugging Face model cards), a license page and two news figures. Not fixed: no rule tells a repository from an article without naming sites.
- **Discover:** the rehearsal found its platform test wrong on real data; measured separately before any change.
