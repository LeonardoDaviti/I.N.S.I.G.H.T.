# 0123 — Collect originals: a News story's original that INSIGHT doesn't have, fetched once, without following its source

Status: **built** (branch `issue-0113-0114-0123`, 2026-11-06), with 0113 and 0114. Mark IX (the story job's outputs, ingestion, the save path). Builds on 0114 (a followed source's page: fetch the source), 0113 (one page saved, joined to its story), 0122 (the save path: a followed source's page is its post; one post when the feed brings it), 0084 B (whose page an address is), 0065 (a story's root).

**The owner (2026-11-06):** "can INSIGHT automatically collect the item that is the original trigger of a story, when we don't have it? Is there an on/off switch?" Today: no.

**Constraints:**
- every request goes through the existing paths: 0114's early fetch (the fetcher, the host gates, the learned budgets, backoff), and the save path's reader under the host's gate;
- one request budget for 0114 and 0123: under 1% more requests than the schedule makes (the owner's bar, 0114);
- never a walled page (0081 is on hold); never store an access or gift token;
- download nothing from the development machine; tests stub every request;
- no real names in committed files; fix the class, never a site; keep everything;
- measured on the server's data before adopting; nothing merges unless `scripts/realdata-check.sh` passes.

## Why: the case (6 Nov, details private: `plan/research/0123-measure.md`)
1. A followed person's X post (through Nitter's RSS) quotes another X account you don't follow.
2. The quote carries that account's words and handle. Nitter's quote cites the quoted tweet's address, and INSIGHT keeps it as a link, though the reader doesn't show it.
3. The quoted words link a news article behind a paywall, by a gift link: an access token in the address.
4. The post is in a News story of 2 voices. The story's origin (its root, 0064) is the article, with the token in `stories.origin_url`.
5. INSIGHT doesn't have the article, and nothing would collect it.

## Connections first: what the data already says (server's copy, 30 days)
- **The trigger is the story's root** (0064's tree: the outside page its posts link or quote first and most, `stories.origin_url`). For News, the root of the row's main story (the most voices). No new rule finds it.
- **127 News rows, 119 with a story; 52 main stories start at a page no post is at.** Every one has an address.
- **Quotes that name no address: 0 of 2,662** Nitter quotes on the copy cite the quoted tweet. A name-only quote is not fetched (there is nothing to fetch); the reader shows the quote as today.
- **What collecting the 52 would be:**

| kind | stories | requests |
|---|---|---|
| a page of a site you don't follow, that can be read | 31 | 1 each |
| a tweet a member quotes: stored from the quote (its words as Nitter shows them, its time by its id) | 10 | 0 |
| walled: a token in its address, or a site whose pages the server's reads found all untitled or blocked | 4 | 0 |
| no article: a video's watch page, a hub's space, a help or docs page | 4 | 0 |
| a followed source's page: 0114 fetches its source | 2 | (0114's) |
| a tweet nobody quotes: not fetched (the save path reads x.com's app shell) | 1 | 0 |

## What it does
**A switch, "Collect originals"**, where the scheduler's settings live (Sources → Ingestion → Scheduler; `system_settings.scheduler.collect_originals`, `PUT /api/operations/scheduler {collectOriginals}`). **Default: off** — see Decided 1.

**When on**, after each scheduler run's story job (ingestion, never the API; never a Fetch now):
1. Each News row's main story whose root isn't stored, started in the last 7 days, not asked before. The biggest stories first.
2. Classified (`utils/originals_rules.trigger_kind`), in this order:
   - **a followed source owns it** (0084 B's `OwnPages`): 0114's, nothing more here;
   - **walled**: its address or a member's link to it carries an access or gift token (a query key naming a token, gift, unlock or access, or a signed JWT value), or the server's reads of its site (Discover's) were all untitled or its follow test said blocked;
   - **no article**: a platform page naming no account, or a reference, document, app or archive address (0109's tests);
   - **a tweet**: from the quote a member holds, no request; a tweet nobody quotes isn't fetched;
   - otherwise **a page**: one request.
3. **A page** is read once by the save path's reader (`SavedService.collect`), under its host's gate:
   - stored as a post of the Saved source with `metadata.collected_original` (the time), **not in Later** (you didn't tap), unread, sorted by its own date;
   - dated by the date the page states, else the first post linking it (0122's rule), never the collection time;
   - its address keeps no token; a page that can't be read as an article is **not stored** (`unreadable`);
   - already stored, or a followed source's after all: nothing stored.
4. It joins its story by 0113's fixed rule, as its root. When a source you follow later brings the same address, 0122's rule makes it one post under that source (the collected row moves; it never becomes "saved by you").
5. Every ask is recorded once in `story_originals` (kind `collect`, the address without its token, the outcome, the requests it cost), never asked again.

**The reader:** a collected original says "· collected original" on its post page. A walled or no-article original stays the story's outside origin line, as today.

## The budget, shared with 0114
- **A credit** (`originals_rules.credit_after`): every source fetch the schedule makes adds 1% of a request; each extra request spends one; it holds at most 3. 0114's early fetches go first, then 0123's pages by the story's voices; what can't be asked now waits (0114: 72 hours; 0123: the story's first week).
- Counted from `source_fetch_state` (the sources attempted since the last count): a source attempted twice between two runs counts once, page reads not at all, so it errs low.
- **Measured** (the replay of the 8.7 days the per-source fetch history covers, 222 requests a day):

| | early or collect requests | share |
|---|---|---|
| 0114 as written | 23 | +1.19% |
| 0114 narrowed (below) | 10 (7 found the page) | +0.52% |
| 0114 narrowed + 0123, no budget | 22 | **+1.14%: over the bar** |
| **0114 narrowed + 0123, with the credit** | **15** (0114: 9, 6 found; 0123: 6, 6 more waiting) | **+0.78%** |

  A rolling "1% of the sources fetched in 24 hours, whole requests" budget allowed about 1 a day and let 2 of 10 of 0114's fetches through (the schedule overtook the rest): not adopted.

## Does it join the right story? (scratch copy, the story job)
- The 44 collectable then (33 pages dated as `collect` dates them: by the page, else its first link; 11 tweets from their quotes, dated by their ids): **43 joined their story, all as its root; 0 dissolved;** 1 didn't join (a repository page linked for months: its link window is its first links'), its story intact. One story grew by one post that links the same release. Stored at the collection time instead (the worst date), still 0 dissolved, but 3 stories pulled in a later post linking the page: why a page with no date is dated by its first link.

## Decided
1. **Default off.** It reverses an owner decision (0065: nothing is fetched until you follow), and whether the 31 pages read as articles is unmeasured without fetching (12 of their sites the server never read). The cost is bounded by the credit and the joins are right, so switching it on is safe; the first week's `story_originals` rows show what it did.
2. **The trigger is the main story's root**, not a new rule: what links, quotes and reposts already say.
3. **One page, never its source:** a site you don't follow stays unfollowed; Discover still suggests it.
4. **Never walled, never a token stored.** A gift link's token is someone's access to a paywalled page: the page is walled, so it's not fetched.
5. **Tweets come from the quote**, never from x.com.

## Open, for the owner
1. **Tokens already stored:** `post_links.target_url` and `stories.origin_url` keep access tokens today (136 links on the copy, 21 keys), and the reader's origin link opens the page with the token. Strip them everywhere (a normalisation change, measured by the real-data check), or keep them (they let you read the gifted article)?
2. **A collected page in the feed:** it is unread in Saved's feed, sorted by its own date. Mark it read, or keep it out of the feed and only in its story?
3. **The reader's quote line:** show the quoted tweet's address (it is in the data) so "no address" never reads as missing?

## Built (branch `issue-0113-0114-0123`, 2026-11-06)
From main e162228 with 0122's branch merged (its save path and its dedup are the ones used). Migration **0071** (`story_originals`; `source_fetch_state.linked_wanted_at`, `linked_url`, `linked_fetched_at`).
- `utils/originals_rules.py` (pure): tokens (`access_keys`, `tokened`, `strip_access_tokens`), page dates (tweet id, address date), 0114's `linked_wanted` and `early_fetch_blocked`, the credit, `SiteReads`/`site_reads_of`, `trigger_kind`.
- `services/originals_service.py`: `OriginalsService.run` (settle 0114's asks found/missing; plan and ask 0114; when on, plan and collect 0123), `accrue`/`spend` (the credit in `system_settings.originals_budget`), `run_originals` (the ingestion runner's hook).
- `ingestion/runner.py`: `originals` runs after the story job of a scheduler run that saved posts; never raises. `ingestion/__init__.default_runner` wires it.
- `services/saved_service.py`: `collect` (one page, no Later, no token, unreadable not stored, dated by the page or its first link), `collect_quote` (a tweet from its quote, no request).
- `db/repo_posts.py`: a collected Saved row moving to its source (0122) never gains `saved_by_owner`; `collected_original` is kept on every update.
- `services/operations_service.py`, `main.py`: `collect_originals` in the scheduler's settings (default false).
- Frontend: the switch in the Scheduler dialog; "· collected original" on the post page.
- Tests: `test_originals_rules.py` (7), `schedulerDialog.test.tsx` (1), `test_story_originals.py` (9: 0114 due once, settles, no story/no credit/recent fetch; the credit; off by default; on: read once, its own date, not in Later, joins as root, never asked again; walled: no request, no token kept; unreadable not stored; a tweet from its quote).
