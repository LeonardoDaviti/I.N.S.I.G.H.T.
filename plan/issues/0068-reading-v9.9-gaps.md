# 0068 — What reading v9.9 would show: threads, roundups, reposts, origin titles, phones, labels

Status: **built, not deployed** (2026-10-31; design decision 041; no migration) for v9.10; spec 2026-10-31 (owner, 2026-10-31: "you are right about those things, so spec into single fix and solve them"). These are the gaps 0064 and 0066 left open, predicted before the owner reads v9.9. Discover's first open (the same list's #6) goes with 0067. HN points and redirect links (#7) stay saved for later (owner); resolving redirects would need requests.

## 1. Thread replies read like posts
- **The case:** the post page shows a thread's replies as plain words with line breaks. Their links aren't links and their pictures aren't shown (0066 Left open). There are 929 threads on the lab.
- **Decided:** each reply renders through the same reader as a post's body (the same sanitising, links, images through the 24-hour image cache), one after another, each with its date opening the reply. No new controls.
- **Done when:** a test that a reply's link is a link and its image is shown; screens of badlogicgames' "software is dead. sad." thread, light and dark, wide and narrow.

## 2. "Covered by" says which roundups mention the story
- **The case:** a roundup (a post whose links have 3+ anchors, 0050) joins a story only through its first link. Every other story it mentions leaves it out of the tree. LessWrong's AI #191 mentions GPT-6.1 Terra (0064) and the Extraltodeus tweet (0066), and neither shows it. News already counts these mentions at ½ (0051).
- **Decided:**
  - Under the tree, one quiet line: `Also in roundups: LessWrong, Smol` (each name opens that roundup). It sits on the feed row's "covered by" and on the post page.
  - Each roundup is listed once. A roundup already in the tree isn't repeated.
  - It's not a tree member and changes no voice count. News is unchanged.
- **Expected on the lab:** Terra lists LessWrong. Record how many stories get the line, and the most roundups on one story.
- **Done when:** tests for the line, no repeats, and the tree unchanged. The cases `openai-terra-same-address` and `x-link-joins-stored-tweet` record it.

## 3. A repost by one of your sources is that source's voice
- **The case:** 0066 records reposters (`posts.reposted_by`), but a tweet reposted by three of your sources is still one post with one voice. The story, News and "covered by" don't see who pushed it.
- **Decided:**
  - A reposter who is one of your sources (not the author reposting themselves) is a **share** voice in the tweet's story, as a share is today: ½ in News' score.
  - A tweet with 2+ voices this way is a story, like any other.
  - "Covered by" lists the reposters on one line under the tweet: `↻ reposted by @steipete, @badlogicgames`.
  - Nothing new is stored. `reposted_by` is read by the story job.
- **Expected on the lab:** record how many tweets gain voices, how many become stories or News, and the 10 with most reposters. A random 10 of the new News stories are checked by reading them and recorded as right or wrong.
- **Done when:** tests for a reposter's voice, a self-repost adding none, and News' ½; the lab numbers recorded.

## 4. An outside origin's title is a title
- **The case:** an outside root's title is the most common link text (0064), and some aren't titles: "Регистрация здесь, не пропустите", "Событие №2 (Технологический меч)".
- **Decided:** the title comes from evidence, never one signal, and nothing is fetched:
  1. a stored post at that address (it would be the root anyway), or a Saved page's title;
  2. link text that 2+ voices agree on;
  3. the address's slug made readable, when it has 3+ words (`claude-fable-5-mythos-5` → "Claude fable 5 mythos 5");
  4. a single voice's link text that passes 0051's title rule;
  5. otherwise the address.

  Measure first: record on the lab how each outside root's title changes, and check 30 by hand. Adopt the order only if it's better on that sample, else record what was found and propose another.
- **Done when:** tests for each step; the lab sample recorded with right or wrong before and after.

## 5. Trees on a phone
- **The case:** below `sm`, a deep tree line shrinks its title to a few letters (0064 Left open).
- **Decided:** below `sm`, the tree indents one level at most. A deeper line shows a small `↳ <parent name>` before its title instead of more indent. Wide screens are unchanged.
- **Done when:** screens at 390 wide of the Fable 5 and Ghostty trees, light and dark.

## 6. Link labels leave the stored posts too
- **The case:** 0063 drops screen-reader link labels when a page is read. The 13 posts stored before still show "(opens in a new window)" (97 labels). Their stored bodies still hold the hidden spans.
- **Decided:** a repair from the stored body only, nothing fetched, applied automatically once after the deploy. It uses 0063's rule, so it goes the way the search refill does (a version a background step catches up on), not an owner-run command.
- **Done when:** a test; on the lab copy, 97 labels gone from 13 posts and nothing else changed (the bodies diffed).

## 7. Two cases that may be stale
- `protein-design-surfaced` and `internal-link` in `plan/research/lab/cases.json` read "fail", with a 9.8 fix named. Check both on the lab copy, and record the result.

## 8. Writers on a shared blog host are separate voices
- **The case** (found while building 0067): a site source's voice is its registrable site (`site_of`: the last two labels). Different writers on one blog host collapse into one voice:
  - 12 Substack sources (garymarcus, gwern, epochai, aella, addyo, …) count as `site:substack.com`;
  - 7 on github.io (karpathy, lilianweng, geohot, matklad, …);
  - 3 on bearblog.dev.

  That's 22 sources counted as 3 voices. Two of them covering one story don't make a story, and News counts them once. A separate case: `blog.ncase.me` and `ncase.me` are one writer.
- **Decided:**
  - Hosting platforms are told by a general rule, never a hand list of sites. The candidate is the Public Suffix List's private section, where hosting platforms register so that each subdomain is its own site. Measure first whether it covers these three. If it doesn't, record what does and propose it.
  - The same rule applies wherever `site_of` names a voice or a place: stories, News, Discover's voices and 0060's sections. Discover keeps one place per platform site for suggestions unless the measurement says otherwise.
- **Expected on the lab:** record the stories and News gained, or changed, and 10 of them read by hand. Record that `ncase.me`'s two sources stay one voice, or why not.
- **Done when:** tests for a platform subdomain being its own voice and an ordinary subdomain (`blog.x.com`) not; the lab numbers recorded.

## Done when (all)
- Backend and frontend suites green; the bundle within budget. The feed route has about 0.23% left of its 1%, so say what each part costs.
- Every passing case in `cases.json` still passes; `now` updated for the cases above.
- No new settings, no fetching.

## Built
(2026-10-31, branch `issue-0068-reading-gaps`, main merged at b4701e3; not merged, not deployed. No migration: item 6's version lives in a setting.)

### 1. Thread replies read like posts
- **The post page** (`post_detail_service.story`): each thread reply in `story.posts` also carries `html` (its stored body) and `internal_links` (0057's links to stored posts). The feed row carries neither: only the post page asks.
- **The reader** (`ThreadPosts`): each reply goes through the post body's `MarkdownRenderer` (the same sanitising, links, a stored post's link opening here), its pictures through the image cache under the reply's own id (`/api/media?post=<reply>`); its date still opens it. A reply stored without HTML reads as before.
- **Tests:** backend `test_a_thread_reply_carries_its_html_and_its_links_to_stored_posts`; frontend `PostDetailPage.story.test.tsx` (a reply's link is a link, a stored post's opens here, its picture shows through the cache).
- **Screens** (Design Studio, not committed): `frontend/.design-shots/post/thread.{1400,390}.{light,dark}.png`, badlogicgames' "software is dead. sad." read in order. Its real replies are plain text, so they look as before; the test carries the link and the picture.

### 2. "Covered by" says which roundups mention the story
- **The reader** (`attach_stories`): `story.roundups` [{id, title, source_display_name}] from 0050's `story_mentions`, which never holds a post of the story. **Each source once, at its first roundup** (see Left open), in the order they came.
- **The line** sits under the tree, on the feed row's opened list and on the post page: `Also in roundups: LessWrong, Smol`, each name opening its roundup (its title on hover). Not a tree member; no voice, no score: News is unchanged.
- **Tests:** backend `test_the_roundups_that_mention_a_story_each_source_once_out_of_the_tree` (LessWrong's two roundups once; the tree and the voices unchanged; the post page the same), `test_a_roundup_in_the_tree_is_not_repeated`; frontend `FeedList.test.tsx`, `PostDetailPage.story.test.tsx`.
- **On the lab copy:** **425 stories** (of 1,821) get the line, 293 of them with 2+ voices. The most roundups on one story: **84 roundup posts from 10 sources** ("Hugging face incident and the road ahead"), so the line names at most 10. Terra lists **LessWrong** (Against Moloch #49, its first of two); the Extraltodeus tweet's story lists **LessWrong** (AI #191).

### 3. A repost by one of your sources is that source's voice
- **The job** (`StoriesService._story_post`): from `posts.reposted_by` (nothing new stored), a tweet's `reposters` are your other sources that reposted it, and `author_source` is its author's own source when another source holds the row. **Built beyond the spec's words, measured:** on the lab every tweet two of your sources pushed is stored once, under the first saver's source; in the 21 "repost of an author you follow" rows (0066) that is the reposter, so the reposter is already the row's voice and the missing voice is the author's. Without it, `x-repost-followed-author` gains nothing.
- **The rules:** `count_voices` and the 2+ sources test count them; News' `tally` counts a reposter as a share (½) and the author as a report, each voice once in its strongest role; one tweet with 2+ voices is a story and can be News. A source is never a voice twice (the row's own source, the author reposting itself).
- **The reader:** those sources join `story.sources` ("covered by 2 · steipete, badlogicgames"); each post (and the row's own place) carries `reposted_by`; "covered by" shows one line under the tweet, `↻ reposted by @steipete, @badlogicgames`, and the row's own at the top of its list. News lists it too.
- **Stories written just now are never deleted** by the job's last step (it removes frozen stories left with one source, and would have removed a one-row repost story every run).
- **Tests:** `RepostVoiceRulesTests` (a reposter's voice, one with its own post in the story, News' ½), and on the database a tweet another source reposted, an author reposting itself, a reposter of its own row, the followed author's report and the reposter's share (2 voices, 1 + ½ = 1.5); a second run changes nothing. Frontend: `lib/story.test.ts`, `FeedList.test.tsx`, `PostDetailPage.story.test.tsx`.
- **On the lab copy** (all time, a full run): **35 tweets gain a voice** (21 an author's, 14 a reposter's; each gains exactly one, so "the 10 with most reposters" all have one: badlogicgames' tweets held by steipete, UnslothAI's and Hesamation's held by _akhaliq and reposted by danielhanchen, julien_c's and ClementDelangue's reposted by ggerganov, …). **29 new stories**, 4 stories gain a voice, no story splits or loses a post, no parent changes. **News: 593 → 624 (+31)**, 2 scores change. A random 10 of the new News stories, read: **10 of 10 right** as stories (two of your sources really pushed that tweet): Hugging Face joining NVIDIA (julien_c; ClementDelangue's "getting acquired by nvidia"), Gemma 4 MTP, "Liberate your @openclaw" (davemorin, by _akhaliq and steipete), two Qwen3.5-27B fine-tune tweets, badlogicgames on long context, … **3 of the 10 are banter** between steipete and badlogicgames ("found @steipete's final form", "uffi ouchie wtf", "loops or graphs"): right, but not news anyone needs.

### 4. An outside origin's title is a title
- **Measured first** (`plan/research`-style scripts, not committed): every outside root on the lab (415), titled by the old rule, by the spec's order, and by a proposed one; 30 roots whose title changes, picked at random, checked by hand (R a title naming the page, A the address, W a title that doesn't name it):

  | | right | address | wrong |
  |---|---|---|---|
  | before (most common titled link words) | 4 | 25 | 1 |
  | the spec's order | 20 | 1 | **9** |
  | **built (proposed)** | **23** | 7 | **0** |

  - **The spec's order fails at step 2:** link words 2+ voices agree on are often a bare word: "Блогпост", "Веса", "Video", "playbook", "доступна на YouTube", "неплохая статья", "General opinion", a cut address ("openai.com/index/chatgpt-mem…" from two X shares), "VK Видео".
  - **And step 3 beats a better step 4:** a slug loses the title's case and dots ("Introducing chatgpt images 2 5" over Simon's "Introducing ChatGPT Images 2.5"; "Behind the scenes hardening firefox" for "… with Claude Mythos Preview").
  - A slug's "words" are words of letters: an id (`7cab4ec7-4712-…`) or a model name (`DeepSeek-V4-Pro`) is no title.
- **So each signal needs another's support** (`story_rules.origin_title`):
  1. link words 2+ voices agree on (copies of one text are one voice) that also read as a title (0051's rule);
  2. else link words the address's slug confirms (the same words: "Coddy Agent" for `coddy-agent`, "Introducing ChatGPT Images 2.5"), as written;
  3. else the slug made readable, with 3+ words of letters (`claude-fable-5-mythos-5` → "Claude fable 5 mythos 5");
  4. else one voice's link words that read as a title;
  5. else the address.

  A stored page is never an outside origin (it is the root, with its own title), so the spec's step 1 needs no code; a test says so.
- **On the lab:** 415 outside roots; titled **81 → 188**; 107 go from the address to a title, 33 change title, **none loses one**. The spec's two cases: fortune.com's "Событие №2 (Технологический меч)" → "Anthropic says testing mythos powerful new ai model after data leak reveals its existence step change in capabilities" (right); shvm.xyz's "Регистрация здесь, не пропустите" stays (one voice's words, a two-word slug; see Left open).
- **Tests:** `OriginTitleTests`, one per step, a bare word two voices agree on, a forward agreeing with itself, an id and a model name as slugs, the stored page.

### 5. Trees on a phone
- **The rule** (`storyTree`, `FeedItem`, `PostDetailPage`): below `sm` the tree indents one level at most (`pl-2`); a line at the deepest level shows `↳ <parent's name>` first, hidden from `sm` up, where the second indent stays. Wide screens are unchanged. On a feed row led by the origin the list is one level less deep, so the `↳` shows on rows not led by the origin and on the post page.
- **Tests:** `lib/story.test.ts` (Ghostty: the line under Duggan names him, this post too, the origin's row names nothing), `FeedList.test.tsx`, `PostDetailPage.story.test.tsx`.
- **Screens** (not committed): `frontend/.design-shots/reader/story.{390,1400}.{light,dark}.png`: Terra (with `Also in roundups: LessWrong`), Fable 5 (toshoseti's forward `↳ denissexy`; LessWrong and evilfreelancer in roundups) and Ghostty (the row is Mat Duggan's, mitchellh.com's post read; @steipete's repost with `↻ reposted by @steipete`; Nesbitt `↳ matduggan.com`; `Also in roundups: lucumr.pocoo.org`). `reader/thread.*` shows steipete's repost of badlogicgames as a story of 2; `post/story.*` the Kimi tree with `↳ data_secrets` at 390.

### 6. Link labels leave the stored posts too
- **The repair** (`PostsRepository.drop_hidden_link_labels`): posts whose HTML holds a hiding hint (0063's `HIDDEN_HINT_RE`, in SQL) go through 0063's own rule (`parsing._without_hidden_link_labels`) on their stored HTML; nothing is fetched. The plain text follows when it is that HTML's text (`strip_html`, true for all 13), the hash follows, and the post's links are read again by the next story job (their link words held the labels).
- **Once, after the deploy, in the background** (`PostsService.catch_up_stored_bodies`, from the API's start, before the story job): the setting `stored_bodies` holds the version the stored bodies are at (1); at that version nothing is read again. A later reader rule bumps it with its own repair, as search's `search_version` refill does. No owner command, no migration.
- **On the lab copy:** **13 posts, 97 labels, nothing else**: the stored HTML diffed against the copy before: 97 removed pieces, all hidden label spans (90 "(opens in a new window)", 4 "(opens in new tab)", 1 "(Opens in a new window)", 2 Apple "Learn more – Creator Studio (Opens in a new window)"), 0 other differences. A second run: 0. Left with the words: LessWrong's 8 pasted quotes (0063 Left open) and two pages where it sits in an `aria-label` attribute, not in the text.
- **Tests:** `StoredBodiesTests` (the label inside a link goes, hidden text outside a link stays, text, hash and links follow, a body without labels untouched, twice over nothing), `StoredBodiesCatchUpTests` (once, then never again).

### 7. Two cases that may be stale
Both **pass** on the lab copy, on main's code before this issue as on this branch:
- `protein-design-surfaced`: `surfaced_at` is empty since 0058's migration 0043, so the page sorts at 18 Aug, not on top (not in the Main feed's first 100 rows); its story holds Just Links' and turboproject's posts of 19 Aug.
- `internal-link`: data_secrets/10206's link to t.me/data_secrets/9951 resolves to the stored post (0057's `internal_links`), so it opens in INSIGHT.

### 8. Writers on a shared blog host are separate voices
- **Measured first:** the Public Suffix List's private section (version 2026-03-06, the copy the `tld` package ships; nothing fetched) lists **github.io and bearblog.dev, not substack.com**. On the lab's site sources: Substack 11 sources (the spec's 12), github.io 5 (the spec's 7: two aren't site sources on the lab), bearblog.dev 3; the only other site holding two sources is ncase.me (`blog.ncase.me` and `ncase.me`) and philschmid.de (one host).
- **Built:** `post_links.site_of` reads the private section (vendored, 3,219 rules, as `utils/public_suffix_private.dat`, MPL header kept): one label under a listed suffix is its own site (`*.` and `!` rules as the list writes them), else as before. Everything that names a voice or a place through `site_of` follows (stories, News, Classics' voices, Discover's voices and sections). No list of sites in code.
- **On the lab copy:** 8 github.io/bearblog.dev sources become 8 voices. **No story or News story is gained or changed** (9 story rows change only their voice's name; Classics: 16 rows); these writers don't cover the same thing in the window. **Discover** (measured, so not kept to one place per platform): 7 suggestions appear that following one github.io blog hid: colah.github.io, leodemoura.github.io, alexzhang13.github.io, tecunningham.github.io, rust-lang.github.io, veitner.bearblog.dev, pyfound.blogspot.com, each linked by 3-4 of your sources; goodreads.com gains a voice (10 → 11); nothing is lost; 0067's cases still read as recorded.
- **`ncase.me`'s two sources stay one voice** (`ncase.me` isn't a platform).
- **Substack is not covered** (see Left open); with it added the lab gains no story either (measured: 30 voice names change, 1 News score, 32 links no longer marked boilerplate as "the source's own site").
- **Tests:** `HostingPlatformTests` (a platform subdomain is its own site and voice; `blog.x.com`, `blog.ncase.me`, `news.bbc.co.uk` aren't; Substack recorded as not listed).

### Every passing case
On the lab copy after all items: `kimi-k31-pro` (8 posts, 7 voices, Kimi's page the root), `cloudflare-yandex-outage`, `openai-terra-same-address` (OpenAI's post the origin, HN by address, data_secrets and Simon by citation), `search-kimi-31` (row 21 newest first, 3 best match), `lime-paper-origin`, `x-quote-edge`, `x-thread-badlogicgames` (Thread · 9 posts), the Discover cases (anthropic.com/news #3; OpenAI News' archive 39/38 as 0067 recorded) all read as before. Stories, trees and search read the same as main's code (fea2a71) on a second copy, but for the new repost stories.

### Suites and the bundle
- Backend: `test_reading_gaps.py` (21); **suite 1,157 tests OK** on `insight_0068_test` (own image tag, not `run-tests.sh`).
- Frontend: typecheck, lint, **208 node + 676 vitest tests**, build OK.
- **Bundle (gzip, 0061):** main (b4701e3) 170,830 feed / 310,252 post → **171,133 (+303, 0.95% of the 1%) / 310,746 (+494, 0.72%)**. Each part, as the build without it:

  | part | feed route | post route |
  |---|---|---|
  | 1. thread replies through the reader | 0 | +20 |
  | 2. Also in roundups | +71 | +127 |
  | 3. reposted by under a tweet | +69 | +87 |
  | 5. one indent and `↳ parent` on a phone | +75 | +121 |
  | the rest (types, the tree's new line kind; gzip isn't additive) | about +90 | about +140 |

  The feed route has **82 bytes** left of its 1%. The post page keeps its own copies of the small pieces: sharing them with the feed row made the row its own chunk and cost +1,000 bytes.

## Left open
- **Roundups are named one per source.** The spec says each roundup listed once; on the lab a story is mentioned by up to 84 roundup posts from 10 sources (LessWrong's essays count as roundups, 0050's 3+ links), so the line names each source once and opens its first roundup; the others aren't reachable from the line.
- **A one-row repost story** (the tweet and the source that reposted it) has no other post: its row says "covered by 2 · …" and opens only the `↻ reposted by` line, which the row's meta line already says.
- **Reposts as News are sometimes banter** (3 of 10 sampled, all steipete reposting badlogicgames about himself). Telling banter from news is meaning, Mark X's.
- **Origin titles:** a slug reads in lower case ("Our decision on cursor following its acquisition by spacex"); one voice's words that read as a title can still be no title ("Регистрация здесь, не пропустите": its slug has two words). The 7 addresses in the sample stay addresses.
- **Substack is not in the Public Suffix List**, so its 11 writers stay one voice. What would cover it, measured on the lab: "your sources on different subdomains of one site, none on the site itself, are different voices" splits exactly Substack, github.io and bearblog.dev and keeps ncase.me and philschmid.de whole; it would also split a company with two subdomain blogs (none on the lab). Proposed for the owner; not built.
- **The vendored list ages:** refreshing it is copying the section again (version and commit at its top).
- **On a phone** the deepest line now holds `↳ name` as well as its source, so with a share mark and a date its title can still be short (toshoseti's forward in the Fable screen).
- Frozen stories (begun before the 30-day window) keep the voices they had when a reposter source is removed.
