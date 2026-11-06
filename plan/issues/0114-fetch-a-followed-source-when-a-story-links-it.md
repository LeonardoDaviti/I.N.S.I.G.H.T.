# 0114 — A story links a page of a source you follow, and we don't have it yet: fetch that source now

Status: **built, narrowed** (branch `issue-0113-0114-0123`, 2026-11-06): its measure put it at +1.44% requests against the 1% bar, so the rule is narrowed (below) and shares 0123's budget. Spec 2026-11-05, the owner; open questions decided. Mark IX (ingestion and the story job); Mark X benefits without changes.

**The owner (2026-11-05):** "if our system spots that some of the posts from the story is original or related, and we don't have that fetched yet, and that post's source is in our source list, it should be fetched automatically."

**Constraints:**
- every fetch goes through the existing fetcher, the host limiter and the learned budgets (0107), and the same politeness;
- download nothing from the development machine;
- no real names in committed files;
- fix the class, never a site;
- measure on the server's fetch history before adopting;
- nothing merges unless `scripts/realdata-check.sh` passes.

## Why: what happens today (server, 5 Nov)
- **No source is fetched more often than every 24 hours** (`schedule.TIER_INTERVAL_MIN`), whatever its tier. A lab's own feed that posts about every 8 hours is "fast", and is still fetched once a day.
- **So an announcement reaches INSIGHT last.** Example, from 5 Nov (UTC):
  1. A lab publishes an image-model release on its site, around 00:00.
  2. A channel posts a hands-on test at 00:54.
  3. Another channel retells it and **links the lab's page** at 07:11.
  4. Mark X makes a correct new story from the two channels.
  5. The lab's own feed, which you follow, was fetched at 18:32 the day before and is next due at 18:32. Its post (the story's original) arrives about 11 hours after the first link to it, and 18 hours after it was published.
  6. Meanwhile the story has no original, and Mark IX can't use the page's text.
- The same holds for any followed source whose page your other sources link first: a lab's blog, a researcher's site, a followed X account whose post others quote.

## What it does
1. **Spot.** When a post is saved, the story job sees its links. That's the same pass that reads citations (0064) and Discover's origins (0065), so it's not a new read. A link is **wanted** when all of these hold:
   - **it belongs to a followed source.** The source's own site and sections (0065's own sites, 0060's sections), its page-watch prefix, or a followed X account's status address. A repost or quote of a followed account's post counts, as in 0065;
   - **it isn't stored.** No post has that address or the address it redirects to, normalised as `/api/saved` does;
   - **it's recent:** linked within the last 72 hours, by a post published in the last 72 hours;
   - **it's an article page,** not the site's front page or a tag page (0109's rules).
2. **Fetch that source early.**
   - The source's schedule gets a new decision: `fetch_linked`, "a story links its page 2026-11-05/…".
   - It's due now, unless the source was fetched in the last **15 minutes**, or is in backoff or waiting on a host limit (then it's due when that ends).
   - It goes through the normal fetch path: same fetcher, host limiter and budget (0107); live fetches already go first on a shared host.
   - **At most once per source per hour** from this rule, whatever number of links point at it.
3. **After the fetch:**
   - **The page arrived:** it joins its story by the existing rules (citation: members link it; for Mark X, the original by links).
   - **The feed didn't hold it** (the page isn't in the feed, or the feed keeps only its latest items): the link is marked *missing from the feed*, never asked again by this rule.
     - It shows in Discover: the followed source's row says "a story links a page its feed doesn't carry" (0065's missing origins). It offers the archive (0015), or **Save page** (0113) if that's built.
     - **Not saved automatically** unless the owner decides so (open question 1).
4. **Shown:** the source's health row shows `fetch_linked` with the link that triggered it. The story's post panel shows "the original arrived 12 min after a story linked it".

## Not in this issue
- **Pages of sites you don't follow:** that's 0113 (Discover's Pages, saved by one tap).
- **The scheduler's floor for fast feeds** (24 h, for every source). That's a separate rule change: it would make most early fetches unnecessary for official feeds, but not for late links to slow sources. Proposed separately; the owner decides.
- **Mark X asking for fetches.** Mark X's stories benefit because the original arrives, but the trigger is Mark IX's link reading. One rule for both.

## Measure before building (on the server's data and fetch history, read by GET)
1. **For the last 30 days, every link to a followed source's page:**
   - how often the page was **not stored at the time it was first linked**;
   - how long until it was stored: the gap between the first link and the source's next fetch. That's the delay this removes.
2. **The early fetches it would have made:** per day, and per source at most.
   - The bar: under 1% more requests than today's schedule makes. No host gets more requests than 0107's budget allows.
3. **How often the fetch finds the page** (it's in the feed) against *missing from the feed*. This also tells which followed sources' feeds don't carry their own pages.
4. **The cases:**
   - add the example above, a lab's release linked by a channel before its feed is fetched, to `plan/research/lab/cases.json`: the story gets its original within an hour of the link;
   - check it on the server copy by replaying 5 Nov's fetches.

## Decided by the owner (2026-11-05)
1. **When the feed doesn't hold the page:** shown in Discover (the source's row, "a story links a page its feed doesn't carry"), with the archive or **Save page** (0113). Never saved automatically.
2. **The window and the cap:** links from the last 72 hours; at most one early fetch per source per hour; none within 15 minutes of the source's last fetch.
3. **Quotes of a followed account's post count** as links (0065's rule).

## Narrowed by the measure (2026-11-06; private: `plan/research/0114-measure.md`, `0123-measure.md`)
As written it was +1.44% requests (26 days) and 4 in 5 early fetches found nothing. Built narrower:
1. **Wanted only when a story's post links it** (a member, or the story's root), as the issue's title says; never any post's link.
2. **A followed source's own page** is 0084 B's `OwnPages` (its post pages on its publication; on a platform its account's posts), never a platform host; the source followed when the linking post was stored; the linking post of another source.
3. **Never a page dated 7+ days before the link, or a day before the source's last fetch** (by its address or a tweet's id): its feed can't hold it.
4. **At most one early fetch per source per 24 hours** (every tier's interval is at least that), not one an hour: the measure saw 3 a day for one source. Never within 15 minutes of its last fetch, never in backoff.
5. **One budget with 0123**: a credit of 1% of a request per scheduled fetch, at most 3; 0114 first.
6. The delay starts when the linking post is stored, not when it was posted: the linking source is on its own schedule.

**Measured** (the 8.7 days the per-source fetch history covers, 222 requests a day): 0114 alone **+0.52%** (10 early fetches, 7 found the page, 0.8–59.5 hours sooner); with 0123 and the credit, both together **+0.78%** (0114: 9, 6 found).

## Built (branch `issue-0113-0114-0123`, 2026-11-06)
- `ingestion/schedule.py`: `DecisionKind.FETCH_LINKED` ("A story links its page <url>"): due now while no fetch succeeded since the ask, after backoff, before the due check. `CadenceStats.linked_wanted_at`, `linked_url` from the fetch state.
- `db/repo_fetch_state.py`: the three columns (migration 0071); a `fetch_linked` decision records `linked_fetched_at`.
- `db/repo_linked.LinkedPage.by`: the linking posts (0084 B's set, unchanged otherwise).
- `services/originals_service.plan_linked` asks (one page per source, the most linked first) and `settle` records `found` (the page arrived) or `missing` (the source was fetched and the feed didn't hold it: 0084 B's "Linked by your posts, not stored" row shows it, decided 1). Each ask is a `story_originals` row (kind `fetch_linked`), never asked again.
- The runner runs it after a scheduler run's story job (`runner.originals`); never a Fetch now in the API.
- Tests: `test_fetch_schedule.py` (+1), `test_originals_rules.py`, `test_story_originals.py` (FetchLinkedTests).
- Not built: "the original arrived 12 min after a story linked it" in the story's post panel, and the source's health row's link (the decision's detail carries it).
