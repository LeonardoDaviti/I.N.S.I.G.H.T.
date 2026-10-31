# 0068 — What reading v9.9 would show: threads, roundups, reposts, origin titles, phones, labels

Status: **spec** (2026-10-31) for v9.10 (owner, 2026-10-31: "you are right about those things, so spec into single fix and solve them"). These are the gaps 0064 and 0066 left open, predicted before the owner reads v9.9. Discover's first open (the same list's #6) goes with 0067. HN points and redirect links (#7) stay saved for later (owner); resolving redirects would need requests.

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

## Done when (all)
- Backend and frontend suites green; the bundle within budget. The feed route has about 0.23% left of its 1%, so say what each part costs.
- Every passing case in `cases.json` still passes; `now` updated for the cases above.
- No new settings, no fetching.
