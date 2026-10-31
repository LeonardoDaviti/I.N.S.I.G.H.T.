# 0066 — X: reposts, quotes and threads become connections

Status: **built, not deployed** (2026-10-31; spec 2026-10-31) for v9.9 (owner, 2026-10-31: "I love this approach, we could build even more connections from that"). Builds on 0064 (stories as trees).

## The case (the lab, the server's data: 9,657 X posts through Nitter)
- **A tweet has two addresses, and they never meet.** Your copies are stored at their Nitter address (`nitter.local/user/status/123`), while your other sources link `x.com/user/status/123`.
  - Your posts hold **24,869** links to x.com statuses.
  - **721** of them point at tweets you have stored (606 tweets), and none of them joins.
- **Reposts:** **3,951** posts are "RT by @reposter: …".
  - The repost's address is the **original author's** status, so the original author is known for free.
  - **20** of them repost someone else you also follow, so the same tweet arrives twice. Another 307 are authors reposting themselves. A count of 327 made earlier included those self-reposts and was wrong.
- **Quotes:** **2,423** X posts quote another tweet (a `<blockquote>` with the quoted status's link). That's an explicit "built on".
- **Threads:** **1,920 of 1,928** replies ("R to @x") are replies to **the author themselves**, one person continuing their own post. Today each is a separate row.

## Decided
1. **One address per tweet** (owner, 2026-10-31: "you should join nitter and X links, cause I currently use nitter").
   - **Any address shaped like a tweet,** `/<user>/status/<numeric id>` (the id 15+ digits), is the same post as `x.com/<user>/status/<id>`, whatever the host.
   - Measured forms in your links: x.com 24,869 · xcancel.com 615 · nitter.net 245 · fxtwitter.com 77 · fixupx.com 38 · vxtwitter.com 17 · fixvx.com 4 · nitter.cc 2, plus your own nitter.local.
   - It's a rule on the address's shape, which every mirror copies, not a list of hosts. Applied in 0049's normalizer to posts and to links alike.
   - **Your own Nitter's links are no longer dropped** as "the source's own platform": 3,232 of your X posts link other tweets through it.
   - **Existing posts** are re-addressed by a migration that keeps their reading state. Check the shape doesn't catch non-X sites (count any matches outside known X forms on the lab, and list them).
2. **A repost is a share, and it names the original author.**
   - The repost hangs from the original tweet in the story tree (0064), with reason `repost`.
   - When the original is stored (you follow its author), the two are one story (0064's address rule, now that they share an address).
   - The original author is recorded on the post (attribution, ready for Mark X's entities), and shown as "↻ @reposter, from @author".
3. **A quote is a citation:** a quoting tweet's parent is the quoted tweet, reason `quote`, whether the quoted tweet is stored or not (0064's outside root).
4. **A thread is one item, with continuity.**
   - An author's replies to themselves within 24 hours of the previous post in the chain form a **thread**. The first post is its root; each reply's parent is the post before it (reason `thread`).
   - **A thread starts at the author's own post, never at a repost.** In the lab, pankajkumar_dev's chain began with "RT by @pankajkumar_dev: …".
   - **In the feed,** a thread shows once, at its first post, with "Thread · 5 posts". Opening it reads the posts in order.
   - Read state: opening the thread marks its posts read.
   - Threads are trees too, so they use 0064's structure, not a second one.
5. **No new settings, no fetching.** Everything comes from what Nitter already gives.

## Expected outputs on the lab (measured 2026-10-31; the build must reproduce them, or explain each difference)
- **A tweet you have, linked at x.com, joins:**
  - LessWrong's "AI #191: The Hackening Begins" (`lesswrong.com/posts/ZoMJdvq9meE4shyzJ/…`) links `x.com/Extraltodeus/status/2111872584338018562`. It's stored as predict_addict's repost at `nitter.local/Extraltodeus/status/2111872584338018562#m`, and the two become connected.
  - Overall, the 721 x.com links to 606 stored tweets resolve (more with the other mirror forms).
- **Reposts:**
  - 3,951 in all: **307 are authors reposting themselves**, which is no edge to anyone else, and 3,644 repost others.
  - **20** repost an author you follow, e.g. `nitter.local/badlogicgames/status/2114444636303364349` ("RT by @steipete: how i work with agents in 2026"): badlogicgames' tweet reposted by steipete.
  - Check whether the original and the repost are two rows or already one (the same exact address). If one, steipete's voice as a share must still be recorded.
- **A quote:** badlogicgames' "i'm joining the frontier pacers." (`…/2115969197113053639`) quotes `hvent90/status/2115936457806479851`. That's its parent, an outside root if not stored. 2,423 X posts quote.
- **A thread:** badlogicgames, 6 posts from "software is dead. sad." (`…/2115002476311241104`), show as one row "Thread · 6 posts".
  - Overall, **951 threads holding 2,867 posts, the longest 13** (before the "no repost root" rule, so the final number is a little lower; record it).

## Done when
- **Backend tests:**
  - address mapping (post and links);
  - repost edge and original author;
  - two copies of one tweet joining;
  - a quote edge, stored and outside;
  - a thread of 3 replies to self;
  - a reply to someone else not making a thread;
  - the 24-hour limit;
  - the migration keeping read state.
- **On a copy of the lab, recorded here:**
  - how many of the 721 x.com links now join;
  - repost edges and attributions;
  - quote edges;
  - threads, with their sizes;
  - how many Main-feed rows fold into threads;
  - every passing case in `plan/research/lab/cases.json` still passes.
- **Frontend:** a thread row and its reading; a repost's "from @author". Tests and screens in light and dark.
- **Checks:** suites green; budget within limits.

## Built
- **One address per tweet** (`utils/url_normalization.py`, `TWEET_PATH`): a path `/<user>/status/<id>` (the id 15+ digits) on any host is `https://x.com/<user, lower case>/status/<id>` in `normalized_url` and `canonical_url`, `url_host` x.com. A tail (`/photo/1`, `/history`) and a query (`?s=46`) are the same tweet. X's accounts are case-insensitive, so the account is lower case (1 link on the lab differs from its stored tweet only by case).
  - **The shape catches only X:** over every post's address and every href on the lab copy, the shape matched these hosts and no other: x.com 23,386 · twitter.com 5,217 · nitter.local 3,791 · xcancel.com 890 · nitter.net 247 · fxtwitter.com 123 · fixupx.com 42 · vxtwitter.com 23 · mobile.twitter.com 9 · fixvx.com 5 · nitter.cc 2 · cunnyx.com 2 · nitter.ca 1 (raw hrefs, repeats counted). cunnyx.com and nitter.ca are X mirrors the spec's list lacked. Status-like addresses the shape leaves out (25): two addresses glued together (`…/status/2072352274270052831https://x.com/…`), `.wavefunction` suffixes, archive.is / archive.today / web.archive.org wrappers, `farside.link/nitter/…`, and ids under 15 digits (`twitter.com/op/status/176767`).
  - **Your own Nitter's links are kept** (`post_links.extract_links`): a link to a tweet is kept even on the post's own platform; its own address, profiles and every other link into the platform are still dropped (a tweet's own site is now x.com, so the host it was read from, nitter.local, is blocked too). `mark_boilerplate` no longer calls a platform a source's own site (X sources' site is now x.com; for Reddit, Telegram and YouTube nothing changes: their own platform's links were never kept).
- **Attribution** (migration 0047, the saver): `posts.author` is a tweet's account as its address writes it (`Extraltodeus`); `posts.reposted_by` the accounts of your sources that reposted it, the author not counted. The saver adds each feed's `RT by @user`, so a tweet two of your sources repost, stored once, keeps both (`repo_posts`: the update merges, never drops).
- **Migration 0047** (`0047_x_connections.sql`): the two columns; every post at a tweet-shaped address re-addressed (url, id, read state and everything pointing at it stay); `reposted_by` from the title and, when the post's own source is an X account other than the author, from that source (a second feed bringing a tweet again leaves only its own title); `links_scanned_at` cleared on every post whose HTML links a tweet (the job reads their links again); `parent_reason` gains `repost`, `thread`, `quote`; the `stories` setting cleared (a full regroup). On the lab copy no two posts then share an address and a title, so nothing merges (0049's rule; the only shared address is Sam Altman's tweet and Daring Fireball's link post to it, two titles). Idempotent.
- **The rules** (`utils/story_rules.py`), in order of certainty, `address`, `repost`, `thread`, `quote`, `citation`, `copy`, `time`, `none`:
  - **Repost:** a tweet of another account its source reposted (`StoryPost.reposted`: the source's account is not the author) is a `share`, never its address's own page; stored apart from its original it hangs from it by `repost`.
  - **Thread** (`threads`): in each X source's timeline (reposts included, time order; tweets of one second by their ids, which X gives in writing order), a reply to the author itself hangs from the post right before it when that post is the author's own (not another account's repost, not a reply to another account) and 24 hours or less earlier. An author's repost of its own tweet is its own post. A thread's posts are one story whatever the sources.
  - **Quote** (`post_links.quoted_tweet`: the address in the `<cite>` of Nitter's `<blockquote>`): the quoting tweet hangs from the tweet it quotes by `quote`; a stored one joins its story within 72 hours (as a citation does), whatever the place; one not stored is an outside root when 2+ posts are about it (0064). A quote is what its tweet is about, never one of a roundup's listed links: without that, 3 stories of main lost 9 posts (a tweet with two links and a quote became a roundup).
  - A story is 2+ sources, or one account's thread or quote of itself.
- **The job:** `load_posts` reads `author` and X posts' HTML. A full run on the lab copy takes 24 s with 5,079 posts' links read again, 14 s after; a second run changes 0 rows.
- **The reader:**
  - a feed row (and a post) carries `repost` {by, author}; the title loses Nitter's `RT by @…: `;
  - a story carries `thread` (one account's replies or quotes of itself); a thread reply carries its `text`, its title without `R to @…: `;
  - marking a post read marks the rest of its thread read (`_SHARES_OF_READ`, down the `thread` edges), so opening the thread reads it all;
  - the post page shows a thread's story although it has one voice.
- **Frontend** (decision 039; `pages/reader.md`, `pages/post.md`):
  - the row's line reads `▸ Thread · 6 posts` (`coveredBy`); the replies keep their parent's indent, so a thread lists in its order (`storyTree`);
  - the post page reads the replies that follow the post, in order, each its own words and date (a link to it), then the list as `Thread · 6 posts`;
  - a repost's meta line, and the post page's byline: `↻ @steipete, from @badlogicgames` (`repostLine`).
- **Tests:**
  - backend `test_x_connections.py` (17): every form of a tweet is one address and only the shape is one; a tweet's links to other tweets kept through your own Nitter, its profile and itself not; author and reposters from the title (an author reposting itself is no one); a repost stored apart hangs from its original by `repost` and is a share; a quote of a stored tweet (same source) and of one not stored (an outside root of two quotes); a quote never makes a roundup; a thread of 3 replies to itself; tweets of one second follow their ids; a reply to someone else makes no thread; the 24-hour limit (of the post before, not the first); never rooted at another account's repost, rooted at the author's own; on the database: a tweet two sources repost is one row keeping both reposters (and the feed's `repost` and title); two copies of one tweet join by address; a thread is one row, its replies' text in order, the post page reads it, and reading it marks the replies read; migration 0047 re-addresses tweets, fills the attribution, keeps read state and Keep, clears a linking post's scan, twice.
  - **Backend suite: 1,116 tests, OK.**
  - Frontend: `lib/story.test.ts` (a thread's label and order, opened at its root and at a reply; `repostLine`), `FeedList.test.tsx` (a thread row and a repost row), `PostDetailPage.story.test.tsx` (a thread read in order; a repost's byline). Typecheck, lint, **203 node + 669 vitest tests**, build OK.
- **Bundle (gzip, 0061):**

  | route | before (9854af7) | after | change | against the 1% budget |
  |---|---|---|---|---|
  | feed | 170,712 | 170,844 | +132 | 0.78% of 169,520 |
  | post | 309,966 | 310,284 | +318 | 0.57% of 308,512 |

- **Screens** (Design Studio frames, light and dark, 1400 and 390; not committed): `frontend/.design-shots/reader/thread.*.png` (new reader state `thread`: badlogicgames' thread open as one row, steipete's repost above it) and `frontend/.design-shots/post/thread.*.png` (the thread read in order).

### On a copy of the lab (2026-10-31)
`insight_lab` copied by `pg_dump` into `_test` databases: one migrated and grouped with main's code (9854af7), one with this branch (0047, a full job).

| measure | the spec expected | measured | why it differs |
|---|---|---|---|
| x.com links of other kinds' posts that join a stored tweet | 721 of 24,869 (606 tweets) | **726 of 24,866** (610 tweets); 7 joined before (posts stored at x.com) | Matching the account exactly gives 716; X's accounts are case-insensitive, so 0066 lower-cases them. The spec's own query isn't recorded; its 721 lies between. All forms (xcancel, fxtwitter, …): **731 of 25,427** links, 613 tweets |
| X posts' links to tweets through your Nitter | 3,232 X posts link other tweets | **2,522 links kept**, 598 to stored tweets (460 tweets) | The spec counted posts with any Nitter status link; a tweet's link to itself and its media aren't kept |
| reposts | 3,951: 307 self, 3,644 of others | **3,645 posts with `reposted_by`** (3,644 by title, plus `ggerganov/2107513582925853030`, _akhaliq's row whose title ggerganov's own feed rewrote); 307 self-reposts record no one; 14 posts hold 2 reposters | as expected |
| reposts of an author you follow | 20 | **21** posts (the 20, plus the ggerganov row above), every one a single row | as expected: original and repost share the exact address, so they were always one row; the reposter is now recorded on it |
| repost edges | (not given) | **0** | No tweet is stored twice with one a repost: the only tweet address held by two posts is Sam Altman's tweet and Daring Fireball's link post to it (`address`). The rule is tested |
| quote edges | 2,423 X posts quote | **2,423 quoting posts** found; **500 `quote` edges**: 412 to a stored tweet of the same source, 33 of another source, 55 to an outside tweet as a story's root | 1,849 quote a tweet not stored, alone (no story: one post); 574 quote a stored one, 523 of them within 72 hours |
| threads | 951 holding 2,867 posts, longest 13, before the "no repost root" rule | **929 threads, 2,809 posts, longest 13** | With any post before a reply: 960 / 2,874 / 13 (the spec's measure, with same-second tweets ordered by id). The rule leaves out 32 replies after another account's repost and 1 after a reply to another account |
| Main-feed rows | (not given) | **37,083 → 34,658 rows (−2,425)** | below |

- **Threads by size:** 2 posts 622, 3: 98, 4: 59, 5: 52, 6: 28, 7: 18, 8: 20, 9: 14, 10: 8, 11: 6, 12: 3, 13: 1. 815 are a story of their own; the rest are in a story with other sources or with their quotes.
- **What folds in the Main feed** (all time, sources in the Main feed): 876 one-account stories with a thread fold 1,917 rows; 269 one-account stories of quotes only fold 306; stories of 2+ sources fold 1,025 (main: 823 in 576 stories; +202, from tweets now joining).
- **Stories:** 576 → 1,792 (1,120 of one account). No story of main is split or loses a post, and no two of main's stories merge; 3,644 posts newly in stories. 97 new stories of 2+ sources hold no post of main's; a random 10 were all real (tweets quoted or linked by two of your sources: OpenAI's Astra tweet quoted by steipete and sama, Elon Musk's tweet quoted by sama with Daring Fireball's post on sama's, Claude's announcement quoted by karpathy and _akhaliq). **News:** 506 → 593 stories; **Classics:** 178 → 181.
- **Lab cases:**
  - `x-link-joins-stored-tweet` **partial**: LessWrong's link resolves to predict_addict's repost of the Extraltodeus tweet (its story: the repost and predict_addict's quote of it), but AI #191 is a roundup of 219 links (this one the 218th), so it mentions the story, as Terra's LessWrong posts do in 0064.
  - `x-quote-edge` **passes**: hvent90's tweet is stored, as badlogicgames' own repost of it 2 hours earlier, so the quote hangs from that post (`quote`), not from an outside root.
  - `x-thread-badlogicgames` **passes as one row**, `Thread · 9 posts`: the thread is the expected 6, and three later quotes of its first post ("this thread is brought to you by this very cool giraffe", 2 h later; "nice that youngsters like @hotlinemagi get me.", "jk", the next day) hang under it by `quote`.
  - `x-repost-followed-author` **passes**: one row, `author` badlogicgames, `reposted_by` {steipete}, read as `↻ @steipete, from @badlogicgames`.
  - **Every passing case still passes:** `kimi-k31-pro` (8 posts, 7 voices, Kimi's page the root); `cloudflare-yandex-outage` (Cloudflare the origin, @denissexy under it by citation); `openai-terra-same-address` (OpenAI's post, HN by address, data_secrets and Simon by citation); `lime-paper-origin` (the 2-source story under the arXiv page); `search-kimi-31` (found, folded, Simon in its line; row 3 under best match, row 21 newest first, was 24: three newer matching rows folded into X threads and quotes).
- **pankajkumar_dev, the spec's repost root:** the chain began with "RT by @pankajkumar_dev: Gemini 4 Flash leaks", at `pankajkumar_dev/status/2115000801290801413`: his own tweet, reposted by himself, posted 27 s before its four replies. So it is his own post and the thread's root. Rooting threads at other accounts' reposts is what the rule refuses (32 chains on the lab: the replies' real parent isn't stored, e.g. _akhaliq's "paper: https://…" replies after a repost).

## Left open
- **One-account stories of quotes only read as a thread** (`Thread · 2 posts`): 269 on the lab, mostly an author reposting a tweet and then quoting it, or quoting its own earlier tweet. The label is the nearest word without a new one.
- **A quote within 72 hours of the quoted tweet joins its story, whatever the place:** a quote of an older tweet stays apart (51 on the lab), as a citation would, so a new post never hides under an old row.
- **Thread text is plain:** the post page shows a reply's words with line breaks, not its links as links or its pictures; its date opens the reply.
- **A tweet two of your sources share is one row of the first saver's source:** in the second reposter's timeline that repost is missing, so a self-reply after it could hang from the post before (rare: 15 rows on the lab are held for another reposter).
- **`/i/status/<id>`** (fxtwitter, cunnyx) names no account; it becomes `x.com/i/status/<id>` and doesn't join the tweet stored under its account.
- **Reposters are not counted as story voices:** a tweet reposted by three of your sources is one post of one source's voice. Mark X's entities can read `reposted_by`.
- **The server:** the lab copy is the server's data of 2026-10-30; the migration was measured there, not on the server.
