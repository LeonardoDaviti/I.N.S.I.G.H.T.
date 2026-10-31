# 0067 — Discover: cleaner, less noise

Status: **built, not deployed** (2026-10-31, branch `issue-0067-discover-clean`; spec the same day) for v9.9; item 4 added 2026-10-31. Owner, 2026-10-31: on the 467 X accounts, "not noise because we sort them by impact, priority and sourced by", then "yes please, discover should be more clean and less noise left". Builds on 0065 (Discover by origins) and 0066 (one address per tweet).

## The case (the lab, after 0065 and 0066 merged: 1,063 suggestions, 467 of them X accounts)
- **Two digests carry most of "linked by" for X accounts.**
  - Smol AI News: 15,116 tweet links in 224 posts (about 67 a post), to 3,036 accounts.
  - LessWrong (Zvi's weekly roundups): 8,379 tweet links in 516 posts, to 2,707 accounts.
  - The next source, predict_addict, has 1,109.
- **309 of the 467 X accounts (66%)** reach the 3-source bar only because Smol and LessWrong are two of the three. For sites it's 152 of 596 (26%).
- **Discover counts a roundup's every link as a full voice.** Stories already treat a roundup differently: a post with 3+ anchors joins only its first link (0050). News counts a roundup mention at ½ (0051).
- **A cut is wrong.** Counting those two sources at ½ as a *bar* drops 250 X accounts, including real ones: @vllm_project, @ollama, @togethercompute, @danluu, @peterwildeford, @TheZvi.
- **0065's Left open:** misreadings that show as noise.
  - `openai.com/ru-RU` (3) and `help.openai.com/en` (2): a language segment is read as a section.
  - `nitter.net` (2): its `t.co` and `i/article` pages aren't tweets, so they're counted under the mirror's host as a site.

## Decided
1. **A roundup's link weighs ½ in Discover's order, never in its bar.**
   - A roundup is a post whose links have 3+ anchors, by the rule stories already use (`story_rules.anchors`). It's decided per post; digest sources are never named.
   - Order: stories started first (0065), as now. Then the weighted voices: a voice whose every link to the place comes from roundups counts ½, any other voice 1. Then today's counts.
   - The bar stays: 3+ voices, counted as today. Nothing is hidden by weight.
   - The card's "linked by N of your sources" is unchanged. Its names list non-roundup voices first.
2. **A language segment is not a section.** A first path segment that is a language tag (`en`, `ru-RU`, `zh-hans`, by the tag's shape, not a list of sites) is skipped when reading a site's section (0060's `section_of`). `openai.com/ru-RU/index/…` reads as `openai.com/index`.
3. **A tweet mirror is X, not a site.** A host where Discover finds tweets by shape (0066's `TWEET_PATH`) is an X form. Its other pages (`t.co`, `i/…`) belong to X's kinds of page (`NOT_ACCOUNT`), never a site suggestion. Decided by shape, with no host list.
4. **Discover's first open under 0.5 s, by keeping its counts between runs** (0062's and 0065's Left open; owner, 2026-10-31, with 0068). Today each first open after a start or a story run counts 138k links again: about 0.6 s, against 0.4 s before 0065's X accounts.
   - The story job, which already fills `discover_addresses`, also keeps the per-place counts Discover needs, in the database, updated in the same pass. Discover's open then reads them.
   - The result must be identical to a fresh count with the same rules (0062's test style: compare against a walk over every link).
   - Measure the first open and memory before and after, back to back on one copy. Record the story job's extra time.
5. **No new settings, no fetching, no new UI.**

## Expected on the lab (the build must reproduce these, or explain each difference)
- **The bar:** the same 1,063 suggestions minus the misreadings of item 2 and 3 (`openai.com/ru-RU`, `help.openai.com/en`, `nitter.net`). `openai.com/ru-RU`'s stories move to the section they belong to.
- **The order:**
  - Accounts and sites linked by 3+ non-roundup voices move above those carried by Smol, Zvi and one more.
  - Record the top 30 before and after, and the 15 places that move most (up and down) with their voices.
- **The 34 X accounts that started stories** keep ranking by origins first.

## Done when
- **Backend tests:**
  - a roundup voice weighing ½ in the order but counting in the bar;
  - a voice with one roundup link and one ordinary link counting 1;
  - a language segment skipped (`en`, `ru-RU`, `zh-hans`), and a real two-letter section kept when it isn't a language tag's shape (record how this is decided);
  - a mirror's non-tweet pages not becoming a site.
- **On a copy of the lab:** the numbers above recorded in Built.
- **Speed:** Discover's first open and memory measured before and after on the same copy, same machine, back to back. It must not get slower.
- **Checks:** suites green; every passing case in `plan/research/lab/cases.json` still passes, and a new case `discover-roundups-weigh-half` is added.

## Built
- **A roundup's link weighs half in the order** (`db/repo_discover.py`, `services/stories_service.py`, `utils/story_rules.py`):
  - A roundup is `story_rules.is_roundup`: a post whose kept links have 3+ anchors (`anchors`, the rule stories use). The counting query reads it per post in SQL (each kept link an anchor, but a home page no post is at, or the post's own address).
  - **Checked on the lab copy:** the SQL rule and `is_roundup` agree on every post, 5,774 roundups of 19,580 posts with links, 0 differences.
  - Each suggestion keeps which of its voices link it only in roundups. Its weight is its voices less half of those.
  - **Order:** stories started first (0065), then classics (0051), then the weight, then today's counts (all voices, articles, links, key). Classics stay ahead of the weight, because the weight takes the place of "voices" in today's order. The bar and "linked by N" count every voice, as before.
  - The card's names list the voices that link it in their own posts first, then the roundup voices, each group by name. No frontend change: the names come in that order.
- **A language segment is not a section** (`post_links.section_of`, `LANGUAGE`):
  - The language tag's shape is `en`, `ru-RU`, `zh-hans`, `en_US` or `es-419`: 2 letters, then optionally `-` or `_` and 2 letters, 4 letters or 3 digits.
  - The shape alone isn't enough. On the lab's linked addresses it is also a section on many hosts: `/ai/` (33 hosts, `arstechnica.com/ai/2026/…`), `/us/`, `/cs/`, `/tv/`, `huggingface.co/ai-sage/…` (an organisation).
  - So a second signal is needed: a first segment of that shape is skipped only when a section and a page follow it, and the next segment isn't a date or a number. `openai.com/ru-RU/index/x` is in `/index`; `arstechnica.com/ai/2026/10/x` stays `/ai`; `huggingface.co/ai-sage/GigaChat` stays `/ai-sage`; `developers.googleblog.com/en/a-post` stays `/en`, the language's own home.
  - **How a real two-letter section is kept:** by that second signal, since the shape can't tell. A segment that isn't the shape (`/v2/`, `/api/`) is never skipped.
  - **Measured on the lab copy** over every story root and every post on the hosts where stories start, the rule moved these sections: `help.openai.com` en→articles (4 addresses), `habr.com` ru→companies (3), `support.claude.com` en→articles (2), `openai.com` ru-RU→index (2), `sothebys.com` en→buy, `apple.com` in→newsroom, `theverge.com` cs→tech. Only the two openai.com ones change Discover.
  - The shape alone gives the same Discover on the lab, but it reads `huggingface.co/ai-sage` as a language.
  - Follow… (`ingestion/where_linked.py`) has its own reading of a section and is unchanged.
- **A tweet mirror is X, not a site:**
  - A mirror is a host where a tweet is found by shape: 0066's `TWEET_PATH` in a link of any post's HTML (`TWEET_HREF`). The stored links can't say this, because 0066 gives every tweet its x.com address.
  - On the lab this finds 13 hosts, the same 13 as 0066's measure: x.com, nitter.local, twitter.com, xcancel.com, nitter.net, fxtwitter.com, fixupx.com, vxtwitter.com, mobile.twitter.com, fixvx.com, nitter.cc, cunnyx.com, nitter.ca. No host list.
  - A mirror's other pages are no key in the counts. A story started at one is listed with the pages that name no account (`origins(mirrors=…)`), never suggested.
  - The scan reads every post's HTML once (about 1.4 s on the lab). After that it reads only the posts whose links were read since (`links_scanned_at`, about 25 ms). The hosts found and how far it has read are kept with the counts.
- **Discover's counts kept between runs** (no migration: `system_settings` key `discover_counts`):
  - The story job's Discover step (`fill_discover_addresses`, in the same transaction as the addresses) counts with the rules above. It keeps the suggestions with a stamp: the counting version, `ADDRESS_RULES`, the last story run, and the kind, own site and account of each source with posts.
  - An open reads the kept counts while the stamp holds. Otherwise it counts and keeps them itself. It then leaves out the keys you follow or hid (`discover_open`, as the query did) and counts the classics you didn't hide (both can change between runs).
  - A source added with no posts yet doesn't change the stamp: it links nothing. A source removed takes its posts, so the stamp changes. The in-process cache (0050) is unchanged.
- **Tests:**
  - New `test_discover_clean.py` (9). Two backend tests asked for by Done when:
    - a roundup voice weighs ½ in the order but counts in the bar: 4 voices in roundups rank below 3 in their own posts, and the card still says 4;
    - a voice with one roundup link and one ordinary link counts 1: 2 against 1.5, ahead with fewer articles, and named first.
  - Also in `test_discover_clean.py`:
    - language segments `ru-RU`, `en`, `zh-hans` and `en_US` skipped; `/ai/2026/…`, `ai-sage`, `/en/<page>`, `v2` and `api` kept;
    - the ru-RU stories move to the source that holds `/index`;
    - a mirror's non-tweet pages are no site, by its stories and by links (a host with the same pages and no tweet stays a site);
    - the walk weighs roundups;
    - the story job keeps the counts and an open reads them: the kept list is byte-identical to a fresh count, an edited kept value is what an open shows, and a removed source counts again.
  - `test_discover_counts.py`: the oracle walk now reads `is_roundup` over each post's links and the mirrors from every post's HTML. Every DB test still compares the whole list with it. `test_discover_origins.py`: the "busy" fixture linked 3 pages a post, which made those posts roundups, so it links 2 now.
  - **Backend suite: 1,136 tests, OK** (scratch `insight_0067_test`; the `_test` suffix is what lets the DB tests run).
  - Frontend, unchanged except `pages/sources.md`: typecheck, lint, **206 node + 673 vitest tests**, build OK.
- **Bundle (gzip, 0061):** the feed route **170,826 bytes** (0.77% of 169,520), the post route **310,244** (0.56% of 308,512), as on main.

### On a copy of the lab (2026-10-31)
- **Setup:** `insight_lab` was copied by `pg_dump` into a scratch database (41,689 posts, 140,738 kept links) and migrated. A story run on main (fea2a71) and on this branch each changed 0 rows: the stories are untouched.
- **The bar:** main suggests **1,063** (467 X accounts). This branch suggests **1,062** (467 X accounts), with no count changed on any suggestion the two share.
  - **Gone:** `openai.com/ru-RU`, `help.openai.com/en`, `nitter.net`.
  - **New, where those stories now start:**
    - `help.openai.com/articles`: the same 2 stories, now under their real section;
    - `openai.com`: 2 stories. One is `openai.com/ru-RU/codex`, a page right under the language, so it keeps the language as its section. The other is `openai.com/supply/co-lab/work-louder`, which the ru-RU section's suggestion used to hide. With no main section, 0065 suggests the site, as with huggingface.co.
  - **The ru-RU index pages:** openai.com/ru-RU's 2 `/index` stories moved to OpenAI News' archive: **39 stories (was 37), 38 older (was 36)**.
  - **nitter.net's 2 stories** (`nitter.net/t.co/…`, `nitter.net/i/article/…`): each place has 1, under the 2 needed for the "pages that name no account" line.
  - **Reproduced from The case:** 309 of 467 X accounts (66%) and 152 of 596 others (26%) reach the bar only with Smol and LessWrong. They all still pass: @vllm_project #602→#557, @ollama #606→#559, @togethercompute #608→#560, @danluu #603→#558, @peterwildeford #604→#693, @TheZvi #613→#697.
- **The order:**
  - Of the 962 suggestions with no story and no classic, the **125 linked by 3+ voices outside roundups are #1–#361**. The **148 carried by Smol's and LessWrong's roundups and one more are #593–#962**: every one of the first ranks above every one of the second.
  - The voices most often only in roundups: LessWrong (673 of 763 keys), Smol (600 of 600), DeepLearning.AI The Batch (316 of 317), substack.com (191 of 211), tedium.co (100 of 100), gwern.net (89 of 89), danluu.com (88 of 94), dwarkesh.com (84 of 84).
- **The 34 X accounts that started stories** still rank by stories first (#5, #6, #18, #19, #39, …). Among accounts with the same stories, some swap places by the weight (@openaidevs and @trq212, both 1 story and 11 voices).
- **Top 30, before:** huggingface.co 39, arxiv.org 25, anthropic.com/news 16, qwen.ai 7, x.com/claudeai 6, x.com/openai 6, reuters.com 5, claude.com 5, github.com/openai 5, z.ai 5, ai.meta.com 4, cursor.com 4, transformer-circuits.pub 3, theinformation.com 3, habr.com 3, openai.com/ru-RU 3, bloomberg.com 2, theverge.com 2, x.com/artificialanlys 2, x.com/thsottiaux 2, research.meta.ai 2, stratechery.com 2, gist.github.com/karpathy 2, mistral.ai 2, thinkingmachines.ai 2, 9to5mac.com 2, deepmind.google/models 2, github.com/deepseek-ai 2, github.com/ggml-org 2, help.openai.com/en 2 (stories started).
- **Top 30, after:** #1–#15 the same; then bloomberg.com 2, theverge.com 2, x.com/artificialanlys 2, x.com/thsottiaux 2, research.meta.ai 2, stratechery.com 2, gist.github.com/karpathy 2, mistral.ai 2, **openai.com 2**, thinkingmachines.ai 2, deepmind.google/models 2, github.com/deepseek-ai 2, github.com/ggml-org 2, **help.openai.com/articles 2**, mastodon.social 2.
  - 9to5mac.com went from #26 to #31: Jeff Geerling and Daring Fireball link it in their own posts, seeallochnaya and Tedium only in roundups.
  - The top is ranked by stories, so the weight shows lower down.
- **The 15 that moved most** (all up, voices as the card names them, own posts first; each now has 3 voices):

  | change | key | was | now | voices |
  |---|---|---|---|---|
  | +588 | x.com/_lyraaaa_ | #1049 | #461 | data_secrets, predict_addict, steipete |
  | +526 | x.com/neuralink | #986 | #460 | Lesswrong, seeallochnaya, steipete |
  | +493 | rb.ru | #952 | #459 | ai_newz, data_secrets, neuraldeep |
  | +456 | blog.jetbrains.com | #914 | #458 | badlogicgames, denissexy, toshoseti |
  | +450 | androidauthority.com | #907 | #457 | denissexy, Daring Fireball, neuraldeep |
  | +449 | x.com/foxnews | #905 | #456 | denissexy, Daring Fireball, predict_addict |
  | +440 | meetup.com | #895 | #455 | Lesswrong, Tom Renner, llm_under_hood |
  | +415 | x.com/feross | #1054 | #639 | karpathy, neuraldeep, Lesswrong |
  | +414 | x.com/axiommathai | #1052 | #638 | akhaliq, gordic_aleksa, Smol |
  | +390 | cepr.org | #1027 | #637 | Lesswrong, turboproject, theworldisnoteasy |
  | +365 | x.com/unitreerobotics | #1001 | #636 | ai_newz, denissexy, Smol |
  | +363 | x.com/superwhisper | #998 | #635 | akhaliq, steipete, Smol |
  | +358 | x.com/robinebers | #991 | #633 | _philschmid, steipete, Smol |
  | +358 | x.com/rohanvarma | #992 | #634 | sama, steipete, Smol |
  | +357 | x.com/reflection_ai | #989 | #632 | akhaliq, danielhanchen, Lesswrong |

  LessWrong is an ordinary voice where a LessWrong post that isn't a roundup links the place.
- **The most down:** each has 3 voices, every one only in roundups.

  | change | key | was | now | voices |
  |---|---|---|---|---|
  | −292 | x.com/_nathancalvin | #607 | #899 | Lesswrong, Smol, technology review |
  | −280 | x.com/s_oheigeartaigh | #620 | #900 | The Batch, Lesswrong, Smol |
  | −278 | x.com/andymasley | #623 | #901 | Lesswrong, Simon Willison, Smol |
  | −278 | transformernews.ai | #624 | #902 | Knowingless, Lesswrong, Nintil |
  | −278 | discuss.python.org | #626 | #904 | Hacker News, Simon Willison, nesbitt.io |
  | −260 | x.com/johnschulman2 | #650 | #910 | Dwarkesh Patel Blog, Lesswrong, Smol |

- **Identity:** an open with the counts kept by the job and an open after deleting them (a fresh count) give byte-identical JSON.
  - Against the Python walk over every link, every one of the 942 suggestions it finds is in the list. The 168 that differ are all X accounts, which the walk misses because it counts no reposts. The 720 with no story and no difference are in the walk's order.
- **Speed and memory** (a fresh process with the API's imports; the first open after a story run; main and this branch alternating, a story run before each open, 3 rounds in each of two sessions on the final code, jit off as the API runs):

  | | first open | memory: after the open (peak) | story run, nothing new |
  |---|---|---|---|
  | main (fea2a71) | 0.70–0.74 s (load 5.7–6.0); 0.76–0.77 s (load 9.2–12.4) | +15 MB (+15) | 5.04–5.29 s |
  | this branch | 0.13–0.14 s (load 5.8–6.5); 0.13 s (load 9.3–12.4) | +19–20 MB (+24–25) | 5.99–6.41 s |

  - **The story job's extra time: about +1 s per run** (its Discover step went from 0.22–0.26 s to 1.23–1.31 s): the counting the first open used to do, and a ~2.3 MB kept value.
  - **Memory:** the open reads that value, so its memory is a few MB above main's, not below.
  - **Rarer opens:**
    - with no kept counts (after the deploy, before the first story run): 2.32–2.39 s, once, the full mirror scan included. The backend's start runs the story job, which usually pays it;
    - with an older stamp (a source with posts removed, or the job's Discover step failed): 1.12–1.14 s.
- **Lab cases:** `discover-roundups-weigh-half` **passes** (its `now` recorded). `discover-anthropic-news-section` (#3, 16 stories) and `discover-x-accounts` (@elonmusk, @OpenAI, @bcherny, @gdb, @claudeai with the same voices as main on this copy; Extraltodeus not suggested) pass. `discover-openai-archive` passes with 39 and 38 (its `now` updated).
  - The story, search and reader cases are untouched: the stories didn't change (0 rows) and that code wasn't edited.

## Left open
- **The open after a source with posts is removed, or after a failed Discover step, is slower than main** (1.12–1.14 s against 0.70–0.77 s): it counts with the roundups (+~0.2 s) and writes the kept value. It is rare: adding or following a source changes nothing until its posts are read by a story run.
- **The story job is ~1 s longer each run.** It recounts after every run, because the stamp holds the last run.
- **An essay with many links is a roundup too:** gwern.net 89 of 89 keys, dwarkesh.com 84 of 84, danluu.com 88 of 94, by the same 3-anchor rule stories use (e.g. @johnschulman2 −260: Dwarkesh Patel Blog, Lesswrong, Smol). The spec chose the stories' rule; telling a digest from an essay is meaning (Mark X).
- **substack.com is one voice** for every Substack source (`site:substack.com`, 0050's voice by site): seen here (191 keys), not changed.
- **`help.openai.com/articles`:** the key drops the language, so Follow… starts the finder at `https://help.openai.com/articles`, not `/en/articles`. Whether the site sends it on wasn't checked: nothing is fetched.
- **A language with only a page under it stays the section** (`openai.com/ru-RU/codex` is in `/ru-RU`, `developers.googleblog.com/en/x` in `/en`), which keeps `/ai/<page>`-like sections right. Follow…'s own section reading (`where_linked`) doesn't skip languages.
- **A mirror is known only once one of its tweets is seen in a post's HTML.** A mirror whose tweets you never saw stays a site. The hosts found are never forgotten (a deleted post's mirror stays).
- **Classics stay ahead of the weight** in the order (read from "then today's counts"). Say if the weight should come first.
- **Posts deleted without a source removed** (none on the lab) would leave the kept counts stale until the next story run.
