# 0064 — Stories as trees: each post knows where it came from

Status: **built, not deployed** (2026-10-31; spec 2026-10-31) for v9.9 (owner, 2026-10-31: "our idea is to use the most advanced ways of the data structures, just like brain stores and connects informations. List → Tree and with Mark X we will unlock top tier, graphs"; on time: "we will not use that alone, never, only ensembled"). It continues issue 0004 (the citation graph), open since the start.

## The case (the lab, the server's data)
- **A story is a flat list today.** "Covered by" lists the other posts with "first" and "share", but not who each one came from.
- **GPT-6.1 Terra is two rows of one article.** OpenAI News' own post (26 Oct) and Hacker News' (26 Oct 18:01) share an address with different titles.
  - data_whispers, Simon Willison and LessWrong link that address, and every link resolves to HN's row, the first seen.
  - OpenAI's post, the origin, is in no story.
  - Three posts share an address this way on the lab copy.
- **Time alone is unreliable.** Of 1,248 citations between stored posts, the linked post is earlier in 80%. In 20% it's later, which is impossible. The causes:
  - Saved pages' dates (0063);
  - feeds dated by their last update (Daring Fireball);
  - date-only times (13% of website posts and all YouTube videos read 00:00);
  - pages rewritten under old dates (Gwern).

## Decided
1. **Two posts at one address are one story,** with a new join reason, `address`. This moves item 1 of 0062 here.
2. **Each post in a story gets a parent:** the post it came from, or none for the origin. The parent is chosen by **evidence in order of certainty, never by one signal alone:**
   1. **The address's own site:** a post at an address on its source's own site is the origin of that address. OpenAI's post on openai.com is the root of GPT-6.1 Terra.
   2. **Citation direction:** a post linking another post in the story is that post's child, whatever the dates say.
   3. **Copy direction:** the same text or title in two posts makes the earlier *trustworthy* time the parent and the other a copy.
   4. **Time, only as a tiebreaker** between posts that 1–3 leave unrelated, and only when both times are trustworthy:
      - a real time of day, not a date alone (00:00:00);
      - not a Saved page;
      - not a watched page with a later update;
      - the two times more than 10 minutes apart.

      Otherwise the post hangs from the origin with no claim of order.
   - **One parent per post.** When several rules apply, the most certain wins; when two posts are equally certain, the earlier trustworthy time wins. No cycles.
   - **Record the reason** for each parent (`address`, `citation`, `copy`, `time`, `none`), so Mark X can add `meaning` and `attribution` later without changing the shape.
3. **Data:** a parent post and its reason on `story_posts`, computed by the story job (0050) in the same pass. The tables stay one system, ready for Mark X's graph.
4. **In the reader:**
   - "Covered by" (feed row and post page) shows the story as a small tree: the origin first, then its children indented, then theirs. Two levels of indent at most; deeper posts are listed under the second level.
   - Each line keeps its role (share, commentary as today's "report"), its date and its read state.
   - The lead of a folded row is the origin.
   - Minimal: no new controls and no new settings.
5. **News and Classics** are unchanged, except that a story's lead is its origin.

## Added 2026-10-31: the most-linked page is evidence, and often the origin
- **The owner:** "What about a link that is mentioned many times, is not that a kind of point as well?"
- **Measured on the lab:**
  - of 465 stories with 2+ voices, 358 have a page linked by 2+ of their posts;
  - in **326 (91%)** that page isn't a stored post: `anthropic.com/news/claude-fable-5-mythos-5` is linked by 14 posts of the Fable 5 story, `openai.com/index/gpt-6-astra` by 10, `kimi.com/blog/kimi-k3` by 8.
- **Decided:**
  - **A tree's root can be the outside page itself,** when 2+ focused posts of the story link it. Its title is the best title-like link text, else its address, and the linking posts are its children. No fake posts are stored.
  - **In-degree (distinct voices linking a page) is evidence in the ensemble, never alone.** A stored post at the page's own site still beats the bare page, because it *is* that page.
  - **Hubs aren't origins:** a roundup's many out-links never make it a root.
  - **The root line** reads "Anthropic · Claude Fable 5 and Mythos 5 · linked by 14", and opens the page in INSIGHT if it's stored, else through Save any page.
- **Recorded in Built:** how many stories get an outside root, the split of root kinds, and examples.

## Done when
- **Backend tests:**
  - each rule, and the order of certainty when rules disagree: a citation against a later date; a date-only time; a Saved page; a copy;
  - two posts at one address;
  - no cycles;
  - one parent per post;
  - the reason recorded.
- **On a copy of the lab:**
  - the case `openai-terra-same-address` passes: OpenAI's post is the origin, HN, data_whispers and Simon Willison are its children, and LessWrong sits under them;
  - every passing case in `plan/research/lab/cases.json` still passes;
  - record how many stories become trees deeper than one level, and how parents split by reason (`address`, `citation`, `copy`, `time`, `none`).
- **Frontend:** tests and screens of the tree in the feed row and on the post page, light and dark, wide and narrow.
- **Checks:** the bundle stays within the gzip budget (0061).

## Built
**Revised during the build (coordinator, from the owner, 2026-10-31): a page outside INSIGHT can be the root, and in-degree is evidence.** On the lab, 358 of 465 stories with 2+ voices have a page linked by 2+ of their posts, and in 326 of them that page isn't stored: the true origin is often an outside page.

- **The rules** (`utils/story_rules.py`, pure; thresholds at the top):
  - **Two posts at one address are one story** (`group`): a new join reason `address` (from different sources, within 30 days, as a shared text). Same-source posts at one address (Daring Fireball's footnote posts) still don't join.
  - **An address's own page:** a post at an address on the site its source publishes on (`StoryPost.on_own_site`). `SourceFacts.home_site`: the source's own site when its address is on it or half its posts are; never Hacker News or Saved (`NOT_PUBLISHERS`). A link to an address resolves to its own page when one is stored, not to the row seen first (HN's).
  - **`tree`**, each post's parent, the most certain evidence first:
    1. `address`: the other posts at an address hang from its own page;
    2. `citation`: a post linking another post of the story (any link, whatever the dates), or a page outside INSIGHT that 2+ of the story's posts are about (their focused links: a roundup's first link only). Among citations, the node more voices are about wins;
    3. `copy`: the same text or title from another source, the strictly earlier time the parent, only when both times are trustworthy;
    4. `time` / `none`: the posts 1–3 leave unrelated hang from the origin; `time` only when both times are trustworthy and 10+ minutes apart, else `none`.
  - **Trustworthy time** (`StoryPost.trusted_time`): a time of day (not 00:00:00 UTC), not a Saved page, not a watched page with a `page_update`.
  - **The origin is chosen first:** the node (post or page) the most voices are about (in-degree: the address, focused links; never a post's own out-links, so a hub is never a root), then a post at its own site, then a stored post before a page, then the earlier trustworthy time. It gets no parent. Then one parent per post, edges in order of certainty, ties to the earlier trustworthy time, and an edge that would close a cycle is skipped. Only the origin may be a page.
  - An outside origin's title: its most common link words under 0051's rule (`post_links.titled_link_text`, moved from `news_rules`), else none (the reader shows the address).
- **Migration 0044** (`0044_stories_as_trees.sql`):
  - `story_posts.parent_id` (→ `story_posts`, `ON DELETE SET NULL`, deferred), `parent_reason` (`address|citation|copy|time|none`, NULL for the origin post), `parent_url` (the outside origin a post hangs from);
  - `stories.origin_url`, `origin_title`, `origin_linked_by`. No post is invented for a page;
  - clears the `stories` setting so the job's next run regroups every post (frozen stories get their trees too).
- **The job** (`repo_stories.load_posts` reads link words and `page_update`; `write_stories` writes the tree with the story): same pass, writes only what differs. On the lab copy a full run takes 13–14 s for 41,689 posts (as before), and a second run changes 0 rows.
- **The reader:**
  - `attach_stories`: each post carries `parent_id` and `parent_reason`, the story its `origin` {url, title, linked_by} and the row's own place (`parent_id`, `parent_reason`). `first` is the origin post (null when the origin is a page; before the job draws the tree, the first report as before).
  - **The lead is the origin** (`_lead_sql`): the origin post, else a citer of the outside origin, else the rest; then report before share, then first posted, as before.
  - **News** (`news_rules.lead`, `repo_news.news_posts`): a News story's lead is the first origin of its 0050 stories; its list stays flat.
- **Frontend** (design decision 038; `pages/reader.md`, `pages/post.md`):
  - `lib/story.ts` `storyTree`: the origin first, children in time order, two levels of indent at most (deeper posts under the second). The row or page you are on isn't repeated when it's the origin; otherwise it's a plain `source · title · this post` line in its place. A story without a tree (News, or before the job runs) is listed flat, as before.
  - The feed row's list (`FeedItem`) and the post page's Covered by (`PostDetailPage`) render it. Each line keeps the unread dot, title link, `· share`, `· first` (post page) and date.
  - An outside origin reads `anthropic.com · Claude Fable 5 and Mythos 5 · linked by 14`; its title opens Save any page (`/save?url=…&title=…`), which saves nothing until you press Save.
  - Indent: `pl-2`/`pl-4` on a phone, `pl-4`/`pl-8` from sm.
  - No new controls or settings.
- **Tests:**
  - Backend `test_story_trees.py` (25):
    - each rule: two posts at one address (and not of one source); Terra; HN and Saved never claim an address; a source publishing elsewhere;
    - a citation against a later date; mutual citations, no cycle; citation beats copy; address beats citation;
    - a page as the origin with its title; a stored post at the most-linked address is the root; the node most voices are about is the origin though it links a page (Gemini 4 Carbon); roundup mentions and hubs; only the origin may be a page;
    - a copy; a date alone, a Saved page, an updated page order nothing; time needs 10 minutes;
    - one parent per post, no cycles, a reason each; News leads with the origin;
    - on the database: the job records parents and reasons, and a second run changes nothing; the origin leads the feed row, and the row and post page carry the tree; a page origin stored on the story; `home_site`.
    - `test_post_page.py`'s launch story now has its page as the origin (`first` null).
  - **Backend suite: 1066 tests, OK.**
  - Frontend: `lib/story.test.ts` (4 tree tests), `FeedList.test.tsx` (the Terra and Fable rows open as trees), `PostDetailPage.story.test.tsx` (the origin first with `this post` in its place; an outside origin opening Save any page). Typecheck, lint, **197 node + 659 vitest tests**, build OK.
- **Bundle (gzip, 0061):** the feed route is **170,667 bytes** (+1,115 on a6a8a27's 169,552; 0.68% against the 169,520 baseline) and the post route **309,909** (+1,353 on 308,556; 0.45%). Both are within the 1% budget, but the feed route used most of what was left.
- **Screens** (Design Studio frames, light and dark, 1400 and 390; not committed): `frontend/.design-shots/reader/story.*.png` (new reader state `story`: Terra led by OpenAI's post, Fable under Anthropic's page) and `frontend/.design-shots/post/story.*.png` (Kimi K3.1 under kimi.ai's page, this post in its place, a forward under the post it copies).

### On a copy of the lab (2026-10-31)
`insight_lab` copied by `pg_dump` into a `_test` database, migration 0044, then a full job.

- **Lab cases:**
  - `openai-terra-same-address` **passes**: OpenAI's post (26 Oct, 00:00, a date alone) is the origin and leads the Main feed row. Hacker News is under it by `address`; data_whispers and Simon Willison by `citation`.
  - **LessWrong is not in the story.** Its two posts (AI #192 and Against Moloch #49) are roundups of 233 and 30 links, with Terra at link 59 and link 2. So they're mentions (`story_mentions`), not members, as 0050 decided. The spec's "LessWrong sits under them" isn't built.
  - **Every passing case still passes:**
    - `kimi-k31-pro`: 8 posts, 7 voices;
    - `cloudflare-yandex-outage`: Cloudflare is the origin, @dennis_it under it by citation;
    - `search-kimi-31`: row 24 newest first, folded, Simon in its line;
    - `lime-paper-origin`: still the 2-source story;
    - `internal-link`: untouched.
  - **Grouping against a6a8a27's rules on the same data:** no pair of posts is split. Only the two address posts joined: Terra, and OpenAI's "Working with academic communities…".
- **Trees:** 575 stories (476 with 2+ voices). Max depth 2. **4 stories are deeper than one level** (5 posts at depth 2): depth is rare because most posts link the origin page directly.
- **Root kinds:**

  | root | all stories | 2+ voices |
  |---|---|---|
  | outside page | 359 | 301 |
  | stored post at its own site | 184 | 143 |
  | stored post, not its own site | 32 | 32 |

- **Parents by reason** (1,459 story posts):

  | reason | count | share |
  |---|---|---|
  | citation | 1,136 | 77.9% (927 under an outside page, 209 under a post) |
  | origin post (no parent) | 216 | 14.8% |
  | copy | 71 | 4.9% |
  | none | 30 | 2.1% |
  | time | 4 | 0.3% |
  | address | 2 | 0.1% |

- **Examples:**
  - **Claude Fable 5:** root `anthropic.com/news/claude-fable-5-mythos-5`, "Claude Fable 5", linked by 14. ai_dispatch, dennis_it, seeall_notes, LessWrong, data_whispers, abstract_nets, Simon Willison, Epoch AI and others hang from it by citation. Daring Fireball's DMA post hangs from it with `none`, and @toolsmith_pete sits under Daring Fireball by citation (depth 2).
  - **GPT-6.1 Terra:** OpenAI News → Hacker News (`address`), data_whispers and Simon Willison (`citation`).
  - **Ghostty leaves GitHub:** mitchellh.com's post (a date alone) → @toolsmith_pete and Mat Duggan; Andrew Nesbitt's "A GitHub for maintainers" under Duggan (depth 2).
  - **Kimi K3.1 Pro:** root `kimi.ai/blog/kimi-k3-1-pro`, "Introducing Kimi K3.1 Pro", linked by 8.
  - **Gemini 4 Carbon:** Google's post (linked by 3) is the root, not the benchmark page it links (linked by 2). This was wrong until the origin was chosen first, by in-degree.
- A random sample of 25 outside-page origins: model cards, papers, announcements and articles; 9 of 25 have a title from link words, the rest show the address.

## Left open
- **LessWrong is a mention, not a member** of the Terra story (see above). Showing a roundup that mentions a story in its tree would be a new decision.
- **Trees are shallow:** most posts link the origin page directly, so 4 stories of 575 go deeper than one level. A post that links both the origin page and another citer goes under the page: in-degree comes first, as revised.
- **Citation outranks copy, as the spec orders them:** a Telegram forward that also carries the origin's link hangs from the page, not from the post it copies (tosho_nets under the Fable page, not under dennis_it).
  - **Decided (owner, 2026-10-31): the link wins.** Measured on the lab: 129 posts have both a citation and a copy parent. In 124 the copied post links the same page, so the choice is only "beside the original" or "under it" (80 exact text copies, 39 title-only). The other 5 are one post both linked and copied (Simon Willison), so they agree. Example: Talkie (ai_dispatch 19:06, dennis_it 19:07, tosho_nets 20:02, one text, one Hugging Face link). All three stay beside each other under the page. Who forwarded whom is attribution, which is Mark X's.
- **Origin titles from link words are sometimes poor:** "Регистрация здесь, не пропустите" and "Событие №2 (Технологический меч)" pass 0051's rule. Reading the page's own title would need a fetch.
- **An outside origin's line names its host** (`anthropic.com`), not a source's name: a page outside INSIGHT has no source.
- **On a phone the lines are tight:** a deep line's title can shrink to a few letters, as in 0050's flat list. The indent is halved below sm.
- **The bundle:** the feed route has 0.32% left of its 1% budget.
- **The spec's "three posts share an address":** on the copy, two addresses are shared across sources (Terra and OpenAI's "academic communities"), and both join by `address`; any other shared address is one source's, which never joins.
- Watched pages: the lab has no `post_watch` rows, so the "updated page" rule is tested, not measured.
