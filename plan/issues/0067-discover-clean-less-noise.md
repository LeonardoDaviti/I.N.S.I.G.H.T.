# 0067 — Discover: cleaner, less noise

Status: **spec** (2026-10-31) for v9.9; item 4 added 2026-10-31. Owner, 2026-10-31: on the 467 X accounts, "not noise because we sort them by impact, priority and sourced by", then "yes please, discover should be more clean and less noise left". Builds on 0065 (Discover by origins) and 0066 (one address per tweet).

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
   - The result must be byte-identical to today's (0062's test style: compare against the current walk).
   - Measure the first open and memory before and after, back to back on one copy. Record the story job's extra time.
5. **No new settings, no fetching, no new UI.

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
