# 0066 — X: reposts, quotes and threads become connections

Status: **spec** (2026-10-31) for v9.9 (owner, 2026-10-31: "I love this approach, we could build even more connections from that"). Builds on 0064 (stories as trees).

## The case (the lab, the server's data: 9,657 X posts through Nitter)
- **A tweet has two addresses, and they never meet.** Your copies are stored at their Nitter address (`nitter.local/user/status/123`), while your other sources link `x.com/user/status/123`.
  - Your posts hold **24,869** links to x.com statuses.
  - **721** of them point at tweets you have stored (606 tweets), and none of them joins.
- **Reposts:** **3,951** posts are "RT by @reposter: …".
  - The repost's address is the **original author's** status, so the original author is known for free.
  - **327** of them repost someone you also follow, so the same tweet arrives twice.
- **Quotes:** **2,423** X posts quote another tweet (a `<blockquote>` with the quoted status's link). That's an explicit "built on".
- **Threads:** **1,920 of 1,928** replies ("R to @x") are replies to **the author themselves**, one person continuing their own post. Today each is a separate row.

## Decided
1. **One address per tweet.** A Nitter status address and its x.com address are the same post. The Nitter kind maps its posts' addresses (and the status links inside them) to the `x.com/<user>/status/<id>` form, which is the one used for matching (0049's normalizer).
   - It's a rule of the Nitter kind (it knows it's a mirror of X), not a list of hosts.
   - Existing posts are re-addressed by a migration. Their reading state is kept.
2. **A repost is a share, and it names the original author.**
   - The repost hangs from the original tweet in the story tree (0064), with reason `repost`.
   - When the original is stored (you follow its author), the two are one story (0064's address rule, now that they share an address).
   - The original author is recorded on the post (attribution, ready for Mark X's entities), and shown as "↻ @reposter, from @author".
3. **A quote is a citation:** a quoting tweet's parent is the quoted tweet, reason `quote`, whether the quoted tweet is stored or not (0064's outside root).
4. **A thread is one item, with continuity.**
   - An author's replies to themselves within 24 hours of the previous post in the chain form a **thread**. The first post is its root; each reply's parent is the post before it (reason `thread`).
   - **In the feed,** a thread shows once, at its first post, with "Thread · 5 posts". Opening it reads the posts in order.
   - Read state: opening the thread marks its posts read.
   - Threads are trees too, so they use 0064's structure, not a second one.
5. **No new settings, no fetching.** Everything comes from what Nitter already gives.

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
