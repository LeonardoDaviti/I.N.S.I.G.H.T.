# 0065 — Discover suggests the sources your stories start from

Status: **built, not deployed** (2026-10-31; spec the same day) for v9.9 (owner, 2026-10-31: on storing origin pages, "no, suggest source in discover"). Builds on 0064's outside roots and 0062's Discover in SQL.

## The case (the lab, the server's data)
- **The origins of your stories are mostly pages you don't follow.** Of 358 stories with a page linked by 2+ of their posts, 326 have that page outside your sources (0064). By site:
  - by site: openai.com 42, huggingface.co 42, github.com 33, anthropic.com 24, arxiv.org 22;
  - by section: openai.com/index 38, arxiv.org/abs 21, **anthropic.com/news 14**, youtube.com/watch 9, huggingface.co/collections 7, qwen.ai/blog 7, blog.google/innovation-and-ai 6, **anthropic.com/research 6**, github.com/openai 5, z.ai/blog 5, cursor.com/blog 4;
- **Discover ranks by how many of your sources link a site.** It never says "this site starts the news you read".
- **Discover hides a site by its domain once any part of it is followed.** You follow `anthropic.com/research`, so Anthropic is never suggested, while `anthropic.com/news` originates 14 of your stories (24 across all of anthropic.com).
- **A followed site can still miss origins:** openai.com's feed holds only its latest 20 posts.

## Decided
- **"Origin of N stories" is Discover's first reason.**
  - Suggestions are ranked by the number of stories whose root (0064) is a page on that site or account, then by today's link counts.
  - The card says "Started 24 of your stories" with 2–3 of those stories, then "linked by N of your sources" as today.
- **Sections, not just sites:**
  - A site you follow in one section is suggested for **another section** that originates stories, using 0060's sections (`anthropic.com/news`: "You follow anthropic.com/research; /news started 14 of your stories").
  - Follow… starts the finder at that section (0060 already does).
- **Followed sources whose origins are missing:** when a followed source's own site originates stories whose pages aren't stored (older than its feed), its card in Discover says so and offers the archive (0015), not a second source.
- **Nothing is fetched until you follow.** No storing of origin pages (owner).
- **Out of scope:** popularity from outside (HN points, 0017).

## Added 2026-10-31: Discover suggests no X account at all
- **Found from the owner's question** ("did Discover suggest the author of that tweet?"): Discover suggests **0 X accounts** of its 576 suggestions.
  - **Articles:** Discover counts only article-like pages (a date or a 4-word slug in the address). A tweet's address (`/<user>/status/<id>`) never is one, so every X account fails the "2+ articles" rule.
  - **Reposts:** they aren't counted, because a repost is stored as a post, not a link.
- **Decided:**
  - **A post on a platform is an article of its account:** a tweet (`/<user>/status/<id>`, in any form, after 0066's one-address rule) and a Telegram post (`t.me/<channel>/<id>`) count as articles of their account.
  - **A repost or a quote by one of your sources is a voice for the original author's account,** as a link is.
  - The 3-source bar stays.
- **Expected on the lab** (accounts you don't follow, counting all tweet forms and reposts): @elonmusk 21 sources, @OpenAI 12, @bcherny 12, @gdb 11, @claudeai 11, @thsottiaux 11, @ArtificialAnlys 10, @OpenAIDevs 10. Extraltodeus (1 source and 1 repost) is correctly not suggested.
- **YouTube:** 2,661 links from 110 sources point at `youtube.com/watch?v=…`, which names no channel. A channel can't be known without a request, so it stays out of scope.

## Expected outputs on the lab (measured 2026-10-31; the build must reproduce them, or explain each difference)
- **anthropic.com/news** is suggested as a section of a site you follow: "started 14 of your stories". anthropic.com/research is followed.
- **openai.com:** followed through `openai.com/news/rss.xml`, but 38 stories started at `openai.com/index/…` pages it doesn't hold (its feed starts on 23 Oct). Expected: an archive offer on the followed source, not a new source.
- **anthropic.com/research:** followed, yet 6 stories started at research pages it doesn't hold. Expected: an archive offer, or a note on why those pages are missing (record which).
- **qwen.ai (7), z.ai (5), cursor.com (4)** are suggested with "started N of your stories", above sites with only link counts.
- **github.com/openai (5)** is suggested as an account (GitHub is a platform in Discover). huggingface.co isn't a followable platform, so it stays one site suggestion.
- **arxiv.org/abs (21) and youtube.com/watch (9)** originate stories but can't be followed as a site this way. They're listed as origins with no new Follow behaviour (arXiv waits for 0037).

## Done when
- **Backend tests:**
  - ranking by origins, then links;
  - a section suggested on a followed site;
  - a followed source with missing origins;
  - a site with no stories behaving as today.
- **On a copy of the lab:**
  - the top 15 before and after are recorded;
  - anthropic.com/news is suggested, with its 24 stories;
  - openai.com's missing origins are offered as an archive.
- **Frontend:** tests and screens, light and dark.
- **Checks:** suites green; budget within limits.

## Built
- **Where each story starts** (`utils/story_rules.py`, pure):
  - A story's root is 0064's: its outside page (`stories.origin_url`), else its one origin post's address. Only stories of 2+ voices count (`ORIGIN_MIN_VOICES`, the base the spec measured on).
  - `origins()` puts each story in one place:
    - an origin post on the site its source publishes on (`home_site`) is held: nothing to say;
    - at a place one of your sources holds (`discover_place`: on a platform the account; elsewhere the host and its section, the host alone at the root or under a date) and not stored: a story **that source misses**;
    - on a site you don't follow, or an account no source holds: that **site or account**;
    - on a site you follow, in a section none of your sources holds: that **section** when 60% of the site's such stories start in it (0060's `SECTION_SHARE`/`SECTION_MIN`, moved to `post_links` with `NUMBERISH` so both use one rule), else the **site**;
    - on a platform page that names no account (`youtube.com/watch`): only listed.
  - The places your sources hold: the platform accounts they follow, and the sections their own posts are in on the followed sites where stories start (the source with the most posts there; Hacker News and Saved never hold a place).
- **X and Telegram** (`discover_address`, `discover_article`):
  - A tweet by its shape, `/<user>/status/<15+ digits>` on any host, is `x.com/<user>`'s (it works before and after 0066's normalizer), and a post of a platform account (a tweet, `/<channel>/<number>` on a platform) is an article of it.
  - A post of a platform account's source at another account's address (a repost) counts as that source's link to it (`repo_discover`: `reposted`), so `discover_addresses` also keeps those sources' post addresses (filled by the story job and by Discover, as before; `ADDRESS_RULES_VERSION` 2 redoes every row once). No migration.
  - Fixed on the way: a platform page's first segment is read without its query, so `youtube.com/watch?v=…` names no account (it was the key `youtube.com/watch`).
- **The service** (`StoriesService.discover`):
  - Each suggestion gains `origins` (stories started there), `origin_stories` (up to 3, most voices first) and, on a site you follow, `follows` (the places of it your sources hold).
  - A place that started stories but isn't linked enough to be suggested by links is suggested by its stories, at the same bar: 2+ pages, 3+ voices (the stories' voices), not hidden.
  - **Order:** most stories first, then today's order (classics, voices, articles, links, key). Suggestions no story starts from keep today's order.
  - `archives`: each followed source whose own pages started 2+ stories it doesn't hold, with where (`places`), how many, its first post and how many are older.
  - `unnamed`: the platform pages that started 2+ stories and name no account.
- **Discover** (`components/sources/SuggestedSources.tsx`, `lib/discover.ts`, design decision 039, `pages/sources.md`):
  - **Sources you follow that miss where your stories start**, above the list: the source's name, "37 of your stories started at openai.com/index pages it doesn't hold, 36 from before its first post (Oct 23)", up to 3 stories, and **Archive…** (Ingestion → archive on that source). No Follow….
  - A suggestion that started stories says "Started 7 of your stories", or "You follow anthropic.com/research; /news started 16 of your stories", with up to 3 of them (title or address, opening the page, `· 13 sources`), then the linked-by line as before. Follow… on a section opens Add source at it.
  - The list ends with "Stories also start at pages that name no account to follow: youtube.com/watch (9)."
  - The search box also reads the stories' titles and the missing sources. On a phone the buttons go under a card's text (beside them the titles were cut to a few letters).
- **Tests:**
  - Backend `test_discover_origins.py` (11): a tweet in any form and a Telegram post as articles of their account; where each story starts (site, account, held, missing, own post, unnamed); a section on a followed site, and a site with no main section (huggingface.co); on the database: ranked by stories then links, with a site with no stories as today; a section of a followed site (and Not interested hiding it); a followed source with missing origins (older than its first post); tweets in three forms plus a repost suggesting an account; one link and one repost not enough (Extraltodeus).
  - `test_discover_counts.py`: the oracle (the old walk) uses `discover_article`; the comparison holds on every link field, in the walk's order for the suggestions no story starts from.
  - **Backend suite: 1110 tests, OK.**
  - Frontend: `lib/discover.test.ts` (3), `SourcesConfig.test.tsx` (the cards, the archive link, the unnamed line, Follow… on a section). Typecheck, lint, **204 node + 668 vitest tests**, build OK.
- **Bundle (gzip, 0061):** the feed route **170,706 bytes** (0.70%), the post route **309,942** (0.46%): as on main, within a few bytes of chunk names. Discover and `lib/discover.ts` are in the Sources chunk.
- **Screens** (Design Studio frame `sources/discover-origins`, 1400 and 390, light and dark; not committed): `frontend/.design-shots/sources/discover-origins.*.png`.

### On a copy of the lab (2026-10-31)
`insight_lab` copied by `pg_dump` into a scratch database, a full story run on main (576 stories, 477 of 2+ voices), then this branch (its full run changed 0 rows: the stories are untouched).

- **Discover's first open** (a fresh service after a story run, the addresses filled; three opens per run, main and the branch alternating in one session):

  | | first open | API memory |
  | --- | --- | --- |
  | main (9854af7) | 0.35-0.42 s | |
  | this branch | 0.57-0.65 s | +15 MB peak |

  - **The 0.5 s target is missed** by about 0.1 s. With `jit=off`, as the API runs, the counting query went from ~0.30 s to ~0.50 s: about 0.15 s is the X accounts (tweets as articles: 4,153 candidate keys instead of 1,588, 44.7k links read for voices instead of 20.5k), about 0.05 s the reposts (28k posts of platform accounts checked against their addresses). Origins and the places held cost ~15 ms. Two rewrites of the reposts' join were measured and dropped (slower).
  - The first open after the deploy redoes every address once (rules version 2): 2.2-4.5 s, once. The story job's fill when nothing is new: 0.16-0.21 s (was 45 ms; it now reads the sources' facts and checks their posts).
- **Top 15, before:** reuters.com (42 voices, 1 classic), claude.com, axios.com, epoch.ai, ai.meta.com, github.blog, transformer-circuits.pub, astralcodexten.com, joelonsoftware.com, alignmentforum.org, pewresearch.org, digital-strategy.ec.europa.eu, forethought.org, tobyord.com, futureoflife.org (classics first, then voices). 576 suggestions, 0 X accounts.
- **Top 15, after** (stories started there): huggingface.co 39, arxiv.org 25, **anthropic.com/news 16**, qwen.ai 7, reuters.com 5, claude.com 5, github.com/openai 5, z.ai 5, ai.meta.com 4, cursor.com 4, transformer-circuits.pub 3, theinformation.com 3, habr.com 3, openai.com/ru-RU 3, bloomberg.com 2. **982 suggestions**: 60 started stories (19 of them suggested by their stories alone), **387 are X accounts**.
- **Against the expected outputs:**
  - **anthropic.com/news: suggested, #3**, "You follow anthropic.com/research; /news started 16 of your stories". 14 are the outside pages the spec counted; 2 are Daring Fireball link posts stored at /news addresses ("U.S. Government Directs Anthropic to Shut Down Fable 5…", "Claude Fable and Kayfabe"), which are roots too. The Done when's "24" is all of anthropic.com: 25 here, of which 6 are research pages (below), 2 engineering and 1 at the root; those 3 aren't shown, as the section takes the site's suggestion.
  - **openai.com: an archive offer.** OpenAI News: 37 stories at openai.com/index pages it doesn't hold (spec: 38; the spec counted pages linked by 2+ posts, this counts 0064's roots of 2+ voice stories), 36 from before its first post (23 Oct). Not a new source. Its 3 stories at `openai.com/ru-RU/…` are a separate suggestion (Left open).
  - **anthropic.com/research: an archive offer** (recorded: the archive, not a note). 6 stories at research pages it doesn't hold, **none older** than its first post (18 Apr 2025): the page watch missed them, not its age. Its archive (page watching) reads the section's pages.
  - **qwen.ai 7, z.ai 5, cursor.com 4: suggested** by their stories, above every site with only links. None of the three was suggested before (their addresses aren't article-like: `blog?id=`, short slugs).
  - **github.com/openai 5: suggested** as an account. **huggingface.co: one site suggestion** (its blog is followed; its stories start in collections, model pages and spaces, and no section holds 60%), #1 with 39.
  - **arxiv.org (25) and youtube.com/watch (9):** arXiv isn't followed on the lab, so it is suggested as a site by its stories, with today's Follow… (nothing new); youtube.com/watch names no channel and is the last line, with no Follow.
  - **X accounts:** @elonmusk 21 sources, @OpenAI 13, @bcherny 12, @gdb 11, @claudeai 11, @thsottiaux 11, @ArtificialAnlys 10, @OpenAIDevs 10. All as the spec's measure except @OpenAI: 12 by tweets and reposts, as the spec counted, plus Phil Schmid linking `x.com/OpenAI` (the profile, an address of the account as any). Also @AnthropicAI 10 and @polynoamial 11. Extraltodeus (LessWrong's link and predict_addict's repost: 2 voices) **is not suggested**. Reposts of others: 3,645 (spec 3,644). Tweet forms counted: x.com 24,866, xcancel.com 615, nitter.net 245, fxtwitter.com 77, fixupx.com 38, vxtwitter.com 17, fixvx.com 4, nitter.cc 2, nitter.ca 1, cunnyx.com 1: no host outside X's mirrors has the shape.
  - blog.google: News from Google is followed and its posts are under `/innovation-and-ai`, so its 8 stories there are an archive offer (all 8 older than its first post, 28 Oct), not a section.
- **Lab cases:** `discover-anthropic-news-section`, `discover-openai-archive` and `discover-x-accounts` pass. Every case that passed still passes: this branch's story run changed no row, and search and the reader are untouched.

## Left open
- **The first open is 0.57-0.65 s** against 0.5 s (above). Keeping the counts between runs (0062's Left open) would cut it, as would counting X accounts in a cheaper second pass; neither is built.
- **Suggestions that read wrong** on the lab (the rules are shapes, so these come with them):
  - `openai.com/ru-RU` (3 stories) and `help.openai.com/en` (2): a language segment is read as a section (0060 left the same open);
  - `nitter.net` (2): `nitter.net/t.co/…` and `nitter.net/i/article/…` aren't tweets, so they key the mirror's host;
  - `mastodon.social` (2): Mastodon isn't a Discover platform, so it is one site, not two accounts;
  - **arxiv.org #2:** its papers are real origins, but following arXiv as a site gives little until 0037;
  - **huggingface.co #1:** you follow its blog, and Follow… on the site will likely find that blog again; its origins are model and collection pages no feed lists.
- **387 X accounts** join the list. The 3-source bar stays, as decided; whether that many helps is the owner's call.
- **OpenAI News is RSS:** its archive can add only what the feed lists (0015), so Archive… will say so after measuring. Holding the 37 pages would need page watching of `openai.com/index`, a second source, which the spec ruled out.
- **Quotes:** a quote's link through your own Nitter is dropped as the platform's own link until 0066 keeps it; then it counts as a voice with no change here. The expected X numbers match without them.
- An origin post that isn't on its source's own site (a Daring Fireball link post at an anthropic.com address) counts as a story started at that page.
- A story example opens the outside page, not INSIGHT (a page outside INSIGHT has no post).
