# 0064 — Stories as trees: each post knows where it came from

Status: **spec** (2026-10-31) for v9.9 (owner, 2026-10-31: "our idea is to use the most advanced ways of the data structures, just like brain stores and connects informations. List → Tree and with Mark X we will unlock top tier, graphs"; on time: "we will not use that alone, never, only ensembled"). It continues issue 0004 (the citation graph), open since the start.

## The case (the lab, the server's data)
- **A story is a flat list today.** "Covered by" lists the other posts with "first" and "share", but not who each one came from.
- **GPT-6.1 Terra is two rows of one article.** OpenAI News' own post (26 Oct) and Hacker News' (26 Oct 18:01) share an address with different titles.
  - data_secrets, Simon Willison and LessWrong link that address, and every link resolves to HN's row, the first seen.
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
  - the case `openai-terra-same-address` passes: OpenAI's post is the origin, HN, data_secrets and Simon Willison are its children, and LessWrong sits under them;
  - every passing case in `plan/research/lab/cases.json` still passes;
  - record how many stories become trees deeper than one level, and how parents split by reason (`address`, `citation`, `copy`, `time`, `none`).
- **Frontend:** tests and screens of the tree in the feed row and on the post page, light and dark, wide and narrow.
- **Checks:** the bundle stays within the gzip budget (0061).
