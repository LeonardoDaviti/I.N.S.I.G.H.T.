# 0066 — X: reposts, quotes and threads become connections

Status: **spec** (2026-10-31) for v9.9 (owner, 2026-10-31: "I love this approach, we could build even more connections from that"). Builds on 0064 (stories as trees).

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
